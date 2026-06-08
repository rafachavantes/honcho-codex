# Design — honcho-codex: replace the `honcho` CLI subprocess with an in-process REST client

**Status:** approved (brainstorming, 2026-06-08)
**Owner:** Rafa Chavantes
**Repo:** `github.com/rafachavantes/honcho-codex` (plugin under `plugins/honcho-codex/`)

## Problem

The Codex plugin is noticeably slower than the Claude Code plugin at every Honcho
read and write. Root cause is **process spawning, not the API**:

- Codex runs the hook as a fresh `python3 honcho_codex_hook.py` per lifecycle event
  (`SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`).
- Inside that process, **every** `HonchoCli._run()` does
  `subprocess.run(["honcho", ...])`, and the `honcho` binary is a pipx-installed
  Python app that cold-starts a full interpreter + Typer + httpx + pydantic on each call.
- `ensure_session()` fans out to `ensure_workspace` + `ensure_peer`×2 + `session create`
  — up to **4 cold-started CLI calls before the real operation**. The in-memory
  `_ensured_*` cache is cold on every event (new process), so this repeats every time.

Net: a single `Stop` event chains ~5 Python cold-starts plus network round-trips,
each under an 8s timeout. The Claude plugin makes **one in-process SDK call** with a
reused client and keep-alive connection — that is the entire performance gap.

The win comes from going **in-process**, not from any specific SDK.

## Goal

Eliminate the per-call subprocess cold-starts by performing Honcho reads/writes
in-process. Constraints, in priority order:

1. **No new runtime dependency.** The Codex hook must stay runnable by the bare
   system `python3` that Codex invokes (the original reason the CLI was chosen).
2. Preserve all current behavior: queue, dedup (`dedupe_key`/`mark_sent`), state
   files, session/peer scoping, message formatting, config.
3. Track 2 (inline/detached write modes) stays **paused** — out of scope.

## Approach (chosen)

**Thin REST client over the Python standard library (`urllib`).** Not the
`honcho-ai` SDK, because the SDK reintroduces the dependency-management problem the
CLI was avoiding (it needs `uv`/a venv/vendoring and pulls `pydantic`+`httpx`, whose
import cost is paid per hook process). The REST surface we actually use is tiny and
the one tricky piece (representation/conclusions, with the known `limit_to_session`
backend bug) is **already disabled** in this plugin, so there is little for an SDK to
abstract.

Rejected alternatives:
- **`honcho-ai` SDK via `uv run --with honcho-ai`** — fast and gives upstream parity,
  but adds a hard `uv` runtime dependency and per-process import cost. Keep as the
  fallback if the REST surface ever grows or the backend API churns.
- **Vendoring the SDK** — heavy transitive deps (`httpx`, `pydantic`); rejected.

### REST contract (ground-truth, captured live from `honcho-ai` 2.1.1 against `api.honcho.dev`, API **v3**)

Base URL from `config.base_url` (default `https://api.honcho.dev`).
Auth: `Authorization: Bearer <config.api_key>`. JSON in/out.

| Operation | Method + path | Body |
|---|---|---|
| get-or-create workspace | `POST /v3/workspaces` | `{"id": ws}` |
| get-or-create peer | `POST /v3/workspaces/{ws}/peers` | `{"id": peer}` |
| get-or-create session | `POST /v3/workspaces/{ws}/sessions` | `{"id": sid}` |
| add peers to session | `POST /v3/workspaces/{ws}/sessions/{sid}/peers` | `{"<peer>": {}}` |
| add messages | `POST /v3/workspaces/{ws}/sessions/{sid}/messages` | `{"messages":[{content, peer_id, created_at?, metadata?}]}` |
| peer card | `GET /v3/workspaces/{ws}/peers/{peer}/card` | — |
| session context/summary | `GET /v3/workspaces/{ws}/sessions/{sid}/context?summary=true&tokens=N` | — |

Notes captured from the live probe: get-or-create is idempotent (returns the existing
object on repeat); message `content` starting with `-` is just a JSON string (the
hyphen-as-flag bug **cannot recur** over REST); `peer card` returns `null`/empty for a
peer with no card; the context response is `{session_id, messages[], summary}`.

## Components

### New: `scripts/honcho_codex/rest.py` — `HonchoClient`

A drop-in replacement for `HonchoCli` exposing the **same public method names and
signatures** so the hook changes by one line:

- `__init__(config)` — stores config; loads the ensure-cache (below); builds an
  `Authorization` header. No network in `__init__`.
- `_request(method, path, body=None) -> dict | list | None` — single `urllib.request`
  helper. Sets auth + `Content-Type: application/json`, encodes/decodes JSON, applies a
  timeout from config, and on non-2xx raises `HonchoError(status, detail)` carrying the
  response body. One opener reused for the process.
- `ensure_workspace()`, `ensure_peer(peer_id)`, `ensure_session(session_name)` — same
  semantics as today (idempotent get-or-create + add peers), but short-circuited by the
  ensure-cache.
- `add_message(session_name, peer_id, content, metadata)` — `ensure_session` then
  `POST .../messages` with a single-element `messages` array.
- `session_context(session_name, tokens) -> str | None` — `GET .../context?...`,
  returns the JSON (matching today's `json.dumps(...)` contract consumed by
  `formatting.py`).
- `peer_card() -> list[str] | None` — `GET .../peers/{peer}/card`, same return shape
  as today.
- `doctor()` — lightweight connectivity check (e.g. `GET /v3/workspaces` or a HEAD);
  used only by cold paths.

`HonchoError(RuntimeError)` mirrors `HonchoCliError` so the hook's existing
`except Exception → log_event(...)` (and the queue-retry) keep working unchanged.

### New: ensure-cache (kill redundant ensures)

A small JSON file `~/.honcho/codex/ensured.json` recording which
`{workspace, peer, session}` triples have been confirmed, each with a timestamp.
On client init it is loaded; an `ensure_*` whose key is present and younger than the
TTL (24h) is a no-op. Otherwise the get-or-create REST call runs and the key is
recorded. This removes ~3–4 network round-trips from the steady-state path, leaving
only the actual read/write call. Lives in `state.py` next to the existing queue/state
helpers (same dir, same atomic-write pattern).

### Changed: `scripts/honcho_codex_hook.py`

One line: construct `HonchoClient(config)` instead of `HonchoCli(config)`. All call
sites (`add_message`, `session_context`, `peer_card`, `_flush_queue`) are unchanged
because the interface is identical.

### Unchanged / out of scope

`state.py` queue + dedup, `formatting.py`, `config.py`. `cli.py` (`HonchoCli`) is
**kept** for the cold paths used by the setup/status skills (`doctor`, human-facing
CLI output) — only the hot hook path moves to REST. Track 2 write modes untouched.

## Data flow (unchanged except transport)

```
Codex event → python3 hook → HonchoClient
  read  (SessionStart/UserPromptSubmit): ensure_session(cache) → GET context + GET card → inject
  write (UserPromptSubmit/Stop):         enqueue → _flush_queue → ensure_session(cache) → POST messages
                                          on error → log_event + keep in queue (retry next event)
```

## Error handling

- Non-2xx / network error → `HonchoError(status, detail)`; the hook already catches and
  (a) logs via `log_event` (added in the hyphen fix) and (b) re-queues writes for retry.
- Timeout: per-request timeout from config (default ~8s, but now one in-process call,
  not a spawned binary). A read timeout degrades to "no context injected", same as today.
- Auth/4xx are logged with the response body so failures are diagnosable, not silent.

## Testing

- **Unit (offline):** inject a fake transport (monkeypatch `_request` or the urllib
  opener) and assert each method issues the right METHOD + path + body + `Authorization`
  header. Explicitly assert a message whose content starts with `-` is sent as a JSON
  string (regression lock for the hyphen bug). Assert the ensure-cache short-circuits a
  second `ensure_*` within TTL and re-runs after expiry.
- **Parity test:** assert `HonchoClient` exposes the same public methods as `HonchoCli`
  (guards the drop-in contract).
- **Existing suite:** stays green (queue/dedup/formatting untouched).
- **Live smoke (manual, run by Rafa or in a throwaway workspace):** create
  ws/peer/session, add a `- bullet` message, read context + card, assert round-trip —
  the same throwaway-workspace technique used to validate the hyphen fix.
- **Perf check (manual):** time a `Stop` event before/after; expect ~5 cold-starts → 1
  in-process call.

## Rollout & risk

- **No new runtime dependency.** Reversible: the hook swap is one line; fall back to
  `HonchoCli` instantly.
- **Risk:** REST shapes drift from the captured contract → mitigated by pinning to v3
  and the live-smoke step per endpoint; the contract here was captured from the live API,
  not guessed.
- Not pushed automatically — Rafa reviews the branch/commits and pushes manually.

## Open items intentionally deferred

- Retiring `cli.py` entirely (migrating setup/status skills to REST too) — kept for now
  to minimize blast radius; revisit once the hot path is proven.
- Track 2 (inline/detached writes) — paused by prior decision.
