# honcho-codex

Persistent [Honcho](https://honcho.dev) memory for [OpenAI Codex](https://developers.openai.com/codex) sessions, wired through Codex lifecycle hooks. It captures your prompts and the assistant's responses into Honcho and injects relevant memory back at the start of a session — so context carries across sessions and projects.

This is the Codex counterpart to the Claude Code plugin (`claude-honcho`); both use the same Honcho memory model (one user peer, per-project sessions) so your identity and project context stay consistent across tools.

## How it works

The plugin registers four Codex lifecycle hooks (`hooks/hooks.json`), each running `scripts/honcho_codex_hook.py`:

| Hook | What it does |
|------|--------------|
| `SessionStart` | Injects memory: the session summary (project-scoped) + your peer card (global identity). Flushes any queued writes. |
| `UserPromptSubmit` | Saves your prompt to Honcho. Optionally injects context (off by default). |
| `Stop` | Saves the assistant's final response for the turn. |
| `PreCompact` | Flushes the queued-writes buffer. |

Tool calls are intentionally **not** saved (MVP scope).

### Architecture

- **In-process REST transport.** Reads/writes go directly to the Honcho **v3** REST API over the Python standard library (`urllib`) from inside the hook process — see `scripts/honcho_codex/rest.py` (`HonchoClient`). There is **no runtime dependency**: the hook runs on the bare `python3` Codex invokes (no SDK, no `uv`, no virtualenv). The `honcho` CLI is *not* required at runtime — it is only used by the setup/status skill for diagnostics.
- **Ensure-cache.** `workspace` / `peer` / `session` are created lazily (get-or-create) and the result is cached on disk (`~/.honcho/codex/ensured.json`, 24h TTL) so they are not re-created on every event. This is the main latency win versus shelling out to the CLI per call.
- **Local write queue + dedup.** Messages are queued locally (`~/.honcho/codex/queue.jsonl`) and deduplicated by key (`~/.honcho/codex/state.json`) so a transient failure retries on the next event instead of losing or duplicating a write.
- **Self-healing writes.** If a cached session was deleted server-side, a write returns 404; the client evicts the stale cache entry, recreates, and retries once.

### Memory model

| Concept | Value | Notes |
|---------|-------|-------|
| Workspace | `workspace` config (default `default`) | one workspace per person |
| User peer | `userPeer` config (default `$USER`) | you — global identity across projects |
| Assistant peer | `assistantPeer` config (default `codex`) | the assistant |
| Session | `<userPeer>-<dir>` (when `sessionPeerPrefix=true`) | one session per project directory |

**Session name formula:** the current directory's base name is sanitized (lower-cased; any character outside `a-z 0-9 _ -` becomes `-`). With `sessionPeerPrefix=true` (default) it is prefixed with the user peer:

- `/home/me/repos/route-converter-se` → `me-route-converter-se`
- with `sessionPeerPrefix=false` → `route-converter-se`

## Install (Codex)

```bash
codex plugin marketplace add rafachavantes/honcho-codex
codex plugin add honcho-codex@honcho-codex
# restart Codex
```

Set your API key (the plugin reads it from the environment or the config file):

```bash
export HONCHO_API_KEY=hcho_...
```

## Configuration

Settings resolve in this order: **environment variable > config file > default.**

The config file is `~/.honcho/codex/config.json` (camelCase keys).

| Config key | Environment variable | Default | What it does |
|------------|----------------------|---------|--------------|
| `apiKey` | `HONCHO_API_KEY` | — (required) | Your Honcho API key. Without it the hooks skip silently (no memory). |
| `baseUrl` | `HONCHO_BASE_URL` | `https://api.honcho.dev` | Honcho API base URL. Change only for self-hosted/staging. |
| `workspace` | `HONCHO_WORKSPACE` | `default` | The Honcho workspace — one per person; holds all your peers and sessions. |
| `userPeer` | `HONCHO_USER_PEER` | `$USER` → else `user` | Your identity (the "user" peer). Keep it stable so memory follows you across projects. |
| `assistantPeer` | `HONCHO_ASSISTANT_PEER` | `codex` | The assistant's peer id. |
| `sessionPeerPrefix` | `HONCHO_SESSION_PEER_PREFIX` | `true` | If `true`, session names are prefixed with the user peer (`<userPeer>-<dir>`); if `false`, just `<dir>`. |
| `sessionStrategy` | `HONCHO_SESSION_STRATEGY` | `per-directory` | How sessions are derived. Only `per-directory` (one session per project folder) is implemented. |
| `injectUserPromptContext` | `HONCHO_INJECT_USER_PROMPT_CONTEXT` | `false` | If `true`, injects memory on **every** prompt, not just at `SessionStart`. More context, more latency per turn. |
| `injectOnCompact` | `HONCHO_INJECT_ON_COMPACT` | `slim` | Injection after the CLI compacts context: `slim` injects a one-line pointer, `off` injects nothing, `full` re-injects the whole memory package (legacy behavior; can re-trigger compaction). |
| `saveUserMessages` | `HONCHO_SAVE_USER_MESSAGES` | `true` | Whether your prompts are saved to memory. |
| `saveAssistantMessages` | `HONCHO_SAVE_ASSISTANT_MESSAGES` | `true` | Whether the assistant's responses are saved to memory. |
| `saveToolCalls` | `HONCHO_SAVE_TOOL_CALLS` | `false` | Whether tool calls are saved (off in the MVP — kept for parity). |
| `maxMessageChars` | `HONCHO_MAX_MESSAGE_CHARS` | `12000` | Messages longer than this are truncated before upload. |
| `contextTokens` | `HONCHO_CONTEXT_TOKENS` | `4000` | Token budget for the memory/summary injected at session start. |

Example `~/.honcho/codex/config.json`:

```json
{
  "workspace": "rafa",
  "userPeer": "rafa",
  "assistantPeer": "assistant",
  "sessionPeerPrefix": true,
  "injectUserPromptContext": false,
  "injectOnCompact": "slim",
  "contextTokens": 4000
}
```

> **Note:** the Codex plugin reads `HONCHO_USER_PEER` for the user peer — **not** `HONCHO_PEER_NAME` (which belongs to the Claude Code plugin). To make the user peer explicit and avoid depending on the `$USER` fallback, set `userPeer` in the config file.

### Verify your configuration

To see the **resolved** settings the plugin will actually use (config file + environment variables + defaults merged), run:

```bash
cd plugins/honcho-codex
HONCHO_API_KEY=$HONCHO_API_KEY PYTHONPATH=scripts python3 scripts/honcho_codex/config.py
```

It prints the effective `workspace`, `userPeer`, `assistantPeer`, `injectUserPromptContext`, etc., plus an `exampleSession` showing the session name for the current directory — a quick way to confirm a change took effect before relying on it. A typical change-and-verify loop:

1. Edit `~/.honcho/codex/config.json` (or export a `HONCHO_*` variable).
2. Re-run the command above and check the value changed.
3. Restart Codex so the hooks pick up the new config.

### State files

All under `~/.honcho/codex/`:

- `config.json` — settings (see above)
- `queue.jsonl` — pending writes (retried until delivered)
- `state.json` — dedup state (sent message keys)
- `ensured.json` — get-or-create cache (24h TTL)
- `logs.jsonl` — error log for diagnostics

## Development

The plugin code lives under `plugins/honcho-codex/`. Tests run with [uv](https://docs.astral.sh/uv/) (no project virtualenv needed):

```bash
cd plugins/honcho-codex
PYTHONPATH=scripts uv run --with pytest python -m pytest tests/ -q
```

Exercise a hook directly with a simulated Codex event:

```bash
cd plugins/honcho-codex
echo '{"hook_event_name":"Stop","cwd":"/tmp/proj","last_assistant_message":"hello"}' \
  | HONCHO_API_KEY=$HONCHO_API_KEY HONCHO_WORKSPACE=my-ws PYTHONPATH=scripts python3 scripts/honcho_codex_hook.py
```

Design notes and the REST-transport implementation plan live under `docs/superpowers/`.

## License

MIT
