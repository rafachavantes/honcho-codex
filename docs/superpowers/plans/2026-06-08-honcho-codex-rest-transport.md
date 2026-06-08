# honcho-codex REST transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-call `honcho` CLI subprocess in the Codex plugin's hot path with an in-process `urllib` REST client, removing the Python cold-start that makes Codex slow at Honcho reads/writes.

**Architecture:** A new `HonchoClient` (stdlib `urllib`, Honcho REST **v3**) is a drop-in for the existing `HonchoCli` — same public methods, same return shapes — so the hook changes by one line. A disk-backed ensure-cache (24h TTL) stops re-running `ensure_workspace/peer/session` on every event. `cli.py` is kept for cold paths (setup/status skills). Queue, dedup, formatting, config, and Track 2 are untouched.

**Tech Stack:** Python 3.12 stdlib (`urllib.request`, `json`), pytest (run via `uv run --with pytest`), no new runtime dependency.

---

## Background the implementer needs

- **Where the code is:** `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex`. The git repo root is `/home/rafa/plugins/honcho-codex` (plugin lives under `plugins/honcho-codex/`).
- **Run tests:** there is no project venv; the system `python3` has no pytest. Use uv:
  ```bash
  cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex
  PYTHONPATH=scripts uv run --with pytest python -m pytest tests/ -q
  ```
  Single test: append `tests/test_x.py::test_name -q`.
- **REST contract (v3) — ground-truth, captured live from the `honcho-ai` 2.1.1 SDK against `https://api.honcho.dev`:**
  | Operation | Method + path | Body |
  |---|---|---|
  | get-or-create workspace | `POST /v3/workspaces` | `{"id": ws}` |
  | get-or-create peer | `POST /v3/workspaces/{ws}/peers` | `{"id": peer}` |
  | get-or-create session | `POST /v3/workspaces/{ws}/sessions` | `{"id": sid}` |
  | add peers to session | `POST /v3/workspaces/{ws}/sessions/{sid}/peers` | `{"<peer>": {}}` |
  | add messages | `POST /v3/workspaces/{ws}/sessions/{sid}/messages` | `{"messages":[{content, peer_id, created_at?, metadata?}]}` |
  | peer card | `GET /v3/workspaces/{ws}/peers/{peer}/card` | — |
  | session context | `GET /v3/workspaces/{ws}/sessions/{sid}/context?summary=true&tokens=N` | — |
  Auth: header `Authorization: Bearer <api_key>`. JSON in/out. get-or-create is idempotent.
- **Why this works:** the current `HonchoCli` shells out to `honcho` (a pipx app) per call; each call cold-starts a Python interpreter. `HonchoClient` does the same operations as direct HTTP from inside the already-running hook process.
- **Drop-in contract:** the hook calls only `add_message`, `session_context`, `peer_card` (each internally calls `ensure_*`). `representation()` exists on `HonchoCli` but is dead code (never called) — do **not** port it.

---

## File Structure

- **Create** `plugins/honcho-codex/scripts/honcho_codex/rest.py` — `HonchoClient` + `HonchoError`. The REST transport. One responsibility: talk to the Honcho v3 API in-process.
- **Modify** `plugins/honcho-codex/scripts/honcho_codex/state.py` — add ensure-cache helpers (`is_ensured`, `mark_ensured`, paths, TTL). Lives with the other on-disk state.
- **Modify** `plugins/honcho-codex/scripts/honcho_codex_hook.py` — swap `HonchoCli`→`HonchoClient` (import + one construction line + the except type).
- **Create** `plugins/honcho-codex/tests/test_ensure_cache.py` — unit tests for the cache.
- **Create** `plugins/honcho-codex/tests/test_rest.py` — unit tests for `HonchoClient` with an injected fake transport.
- **Keep unchanged** `cli.py`, `formatting.py`, `config.py`, the queue/dedup parts of `state.py`.

---

## Task 1: ensure-cache helpers in `state.py`

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/state.py`
- Test: `plugins/honcho-codex/tests/test_ensure_cache.py`

- [ ] **Step 1: Write the failing test**

Create `plugins/honcho-codex/tests/test_ensure_cache.py`:

```python
from honcho_codex import state


def _point(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "ENSURED_PATH", tmp_path / "ensured.json")


def test_mark_then_is_ensured_true_within_ttl(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path)
    state.mark_ensured("workspace", "rafa", now=1000.0)
    assert state.is_ensured("workspace", "rafa", now=1000.0 + 10) is True


def test_is_ensured_false_when_absent(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path)
    assert state.is_ensured("peer", "rafa:user", now=1000.0) is False


def test_is_ensured_false_after_ttl(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path)
    state.mark_ensured("session", "rafa:s1", now=1000.0)
    later = 1000.0 + state.ENSURED_TTL_SECONDS + 1
    assert state.is_ensured("session", "rafa:s1", now=later) is False


def test_keys_are_namespaced_by_kind(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path)
    state.mark_ensured("workspace", "x", now=1000.0)
    assert state.is_ensured("peer", "x", now=1000.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_ensure_cache.py -q`
Expected: FAIL — `AttributeError: module 'honcho_codex.state' has no attribute 'ENSURED_PATH'` (or `mark_ensured`).

- [ ] **Step 3: Write minimal implementation**

In `state.py`, add `import time` at the top (next to `import json`), and add after the existing `QUEUE_PATH`/`LOG_PATH` constants:

```python
ENSURED_PATH = STATE_DIR / "ensured.json"
ENSURED_TTL_SECONDS = 24 * 60 * 60
```

Then add these functions at the end of the module:

```python
def _load_ensured() -> dict[str, float]:
    _ensure_dir()
    if not ENSURED_PATH.exists():
        return {}
    try:
        data = json.loads(ENSURED_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_ensured(data: dict[str, float]) -> None:
    _ensure_dir()
    tmp_path = ENSURED_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, sort_keys=True))
    tmp_path.replace(ENSURED_PATH)


def is_ensured(kind: str, key: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    ts = _load_ensured().get(f"{kind}:{key}")
    return ts is not None and (now - ts) < ENSURED_TTL_SECONDS


def mark_ensured(kind: str, key: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    data = _load_ensured()
    data[f"{kind}:{key}"] = now
    _save_ensured(data)
```

Note: `STATE_DIR` and `_ensure_dir` already exist in `state.py`. `ENSURED_PATH` is defined from `STATE_DIR`; the test monkeypatches both so the rebind is picked up by `_load_ensured`/`_save_ensured` which read the module global at call time.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_ensure_cache.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/state.py plugins/honcho-codex/tests/test_ensure_cache.py
git commit -m "feat(state): add TTL-based ensure-cache helpers"
```

---

## Task 2: `rest.py` transport (`_request` + `HonchoError`)

**Files:**
- Create: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Create `plugins/honcho-codex/tests/test_rest.py`:

```python
import io
import json

import pytest

from honcho_codex import rest
from honcho_codex.config import HonchoCodexConfig


def cfg(**over):
    base = dict(
        api_key="test-key",
        base_url="https://api.honcho.dev",
        workspace="test-ws",
        user_peer="user",
        assistant_peer="codex",
        session_strategy="per-directory",
        session_peer_prefix=True,
        save_user_messages=True,
        save_assistant_messages=True,
        save_tool_calls=False,
        inject_user_prompt_context=False,
        max_message_chars=12000,
        context_tokens=4000,
    )
    base.update(over)
    return HonchoCodexConfig(**base)


class FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install_transport(monkeypatch, handler):
    """handler(method, url, headers, body) -> bytes (response JSON)."""
    calls = []

    def fake_urlopen(req, timeout=None):
        method = req.get_method()
        body = req.data.decode("utf-8") if req.data else None
        headers = {k.lower(): v for k, v in req.header_items()}
        calls.append({"method": method, "url": req.full_url, "headers": headers, "body": body})
        return FakeResp(handler(method, req.full_url, headers, body))

    monkeypatch.setattr(rest, "urlopen", fake_urlopen)
    return calls


def test_request_sets_auth_and_parses_json(monkeypatch):
    calls = install_transport(monkeypatch, lambda *a: b'{"ok": true}')
    client = rest.HonchoClient(cfg())
    out = client._request("GET", "/v3/workspaces/test-ws/peers/user/card")
    assert out == {"ok": True}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.honcho.dev/v3/workspaces/test-ws/peers/user/card"
    assert calls[0]["headers"]["authorization"] == "Bearer test-key"


def test_request_encodes_body(monkeypatch):
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client._request("POST", "/v3/workspaces", {"id": "test-ws"})
    assert calls[0]["method"] == "POST"
    assert json.loads(calls[0]["body"]) == {"id": "test-ws"}
    assert calls[0]["headers"]["content-type"] == "application/json"


def test_request_raises_honcho_error_on_http_error(monkeypatch):
    from urllib.error import HTTPError

    def boom(req, timeout=None):
        raise HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"nope"}'))

    monkeypatch.setattr(rest, "urlopen", boom)
    client = rest.HonchoClient(cfg())
    with pytest.raises(rest.HonchoError) as exc:
        client._request("GET", "/v3/workspaces/test-ws/sessions/s1/context")
    assert exc.value.status == 404


def test_init_raises_when_no_api_key():
    with pytest.raises(rest.HonchoError):
        rest.HonchoClient(cfg(api_key=None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'honcho_codex.rest'`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/honcho-codex/scripts/honcho_codex/rest.py`:

```python
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import HonchoCodexConfig


class HonchoError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HonchoClient:
    def __init__(self, config: HonchoCodexConfig, timeout: float = 8.0):
        if not config.api_key:
            raise HonchoError("Honcho is not configured (missing api_key)")
        self.config = config
        self._base = config.base_url.rstrip("/")
        self._timeout = timeout

    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        url = self._base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.config.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise HonchoError(f"HTTP {exc.code}: {detail[:500]}", status=exc.code)
        except URLError as exc:
            raise HonchoError(f"request failed: {exc.reason}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", "replace")
```

`urlopen` is imported at module scope so tests can monkeypatch `rest.urlopen`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): add HonchoClient transport with auth + JSON + error mapping"
```

---

## Task 3: `ensure_workspace` / `ensure_peer` / `ensure_session` with cache

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rest.py`:

```python
from honcho_codex import state


def _point_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "ENSURED_PATH", tmp_path / "ensured.json")


def test_ensure_session_issues_creates_then_caches(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())

    client.ensure_session("s1")
    paths = [c["url"].replace("https://api.honcho.dev", "") for c in calls]
    assert "/v3/workspaces" in paths
    assert "/v3/workspaces/test-ws/peers" in paths
    assert "/v3/workspaces/test-ws/sessions" in paths
    assert "/v3/workspaces/test-ws/sessions/s1/peers" in paths

    # second call: everything cached -> no new HTTP calls
    before = len(calls)
    client.ensure_session("s1")
    assert len(calls) == before


def test_ensure_peer_adds_peer_with_id_body(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client.ensure_peer("user")
    peer_call = next(c for c in calls if c["url"].endswith("/peers"))
    assert json.loads(peer_call["body"]) == {"id": "user"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: FAIL — `AttributeError: 'HonchoClient' object has no attribute 'ensure_session'`.

- [ ] **Step 3: Write minimal implementation**

Add to the top imports of `rest.py`:

```python
from urllib.parse import quote

from . import state
```

Add these methods to `HonchoClient`:

```python
    def _ws_path(self, *parts: str) -> str:
        segs = "/".join(quote(p, safe="") for p in parts)
        return f"/v3/workspaces/{quote(self.config.workspace, safe='')}" + (f"/{segs}" if segs else "")

    def ensure_workspace(self) -> None:
        if state.is_ensured("workspace", self.config.workspace):
            return
        self._request("POST", "/v3/workspaces", {"id": self.config.workspace})
        state.mark_ensured("workspace", self.config.workspace)

    def ensure_peer(self, peer_id: str) -> None:
        key = f"{self.config.workspace}:{peer_id}"
        if state.is_ensured("peer", key):
            return
        self.ensure_workspace()
        self._request("POST", self._ws_path("peers"), {"id": peer_id})
        state.mark_ensured("peer", key)

    def ensure_session(self, session_name: str) -> None:
        key = f"{self.config.workspace}:{session_name}"
        if state.is_ensured("session", key):
            return
        self.ensure_workspace()
        self.ensure_peer(self.config.user_peer)
        self.ensure_peer(self.config.assistant_peer)
        self._request("POST", self._ws_path("sessions"), {"id": session_name})
        self._request(
            "POST",
            self._ws_path("sessions", session_name, "peers"),
            {self.config.user_peer: {}, self.config.assistant_peer: {}},
        )
        state.mark_ensured("session", key)
```

Note: `ensure_peer` calls `ensure_workspace` (cheap, cached) so peer/card paths are safe even if a session was never ensured — a small, safe improvement over `cli.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): cached get-or-create for workspace/peer/session"
```

---

## Task 4: `add_message` (with hyphen regression lock)

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rest.py`:

```python
def test_add_message_posts_to_messages_endpoint(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client.add_message("s1", "assistant", "- bullet content", {"source": "test"})
    msg_call = next(c for c in calls if c["url"].endswith("/messages"))
    assert msg_call["method"] == "POST"
    payload = json.loads(msg_call["body"])
    # hyphen content is a plain JSON string — the CLI flag-parse bug cannot recur
    assert payload["messages"][0]["content"] == "- bullet content"
    assert payload["messages"][0]["peer_id"] == "assistant"
    assert payload["messages"][0]["metadata"] == {"source": "test"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py::test_add_message_posts_to_messages_endpoint -q`
Expected: FAIL — `AttributeError: ... 'add_message'`.

- [ ] **Step 3: Write minimal implementation**

Add to `HonchoClient`:

```python
    def add_message(
        self,
        session_name: str,
        peer_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        self.ensure_session(session_name)
        self._request(
            "POST",
            self._ws_path("sessions", session_name, "messages"),
            {"messages": [{"content": content, "peer_id": peer_id, "metadata": metadata}]},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): add_message via POST messages (hyphen-safe)"
```

---

## Task 5: `session_context`

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rest.py`:

```python
def test_session_context_gets_summary_with_tokens(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)

    def handler(method, url, headers, body):
        if url.endswith("/messages") or url.endswith("/peers") or url.endswith("/sessions") or url.endswith("/workspaces"):
            return b"{}"
        return b'{"session_id": "s1", "summary": "did stuff"}'

    calls = install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    out = client.session_context("s1", 500)
    ctx_call = next(c for c in calls if "/context" in c["url"])
    assert ctx_call["method"] == "GET"
    assert "summary=true" in ctx_call["url"]
    assert "tokens=500" in ctx_call["url"]
    # returns a JSON string (consumed as text by formatting.py)
    assert "did stuff" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py::test_session_context_gets_summary_with_tokens -q`
Expected: FAIL — `AttributeError: ... 'session_context'`.

- [ ] **Step 3: Write minimal implementation**

Add `urlencode` to the `urllib.parse` import line:

```python
from urllib.parse import quote, urlencode
```

Add to `HonchoClient`:

```python
    def session_context(self, session_name: str, tokens: int) -> str | None:
        self.ensure_session(session_name)
        query = urlencode({"summary": "true", "tokens": tokens})
        result = self._request(
            "GET", self._ws_path("sessions", session_name, "context") + f"?{query}"
        )
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        return str(result) if result else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): session_context via GET context?summary=true"
```

---

## Task 6: `peer_card`

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rest.py`:

```python
def test_peer_card_returns_list(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)

    def handler(method, url, headers, body):
        if url.endswith("/card"):
            return b'{"card": ["Name: Rafa", "Lang: PT"]}'
        return b"{}"

    calls = install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    out = client.peer_card()
    card_call = next(c for c in calls if c["url"].endswith("/card"))
    assert card_call["method"] == "GET"
    assert card_call["url"].endswith("/v3/workspaces/test-ws/peers/user/card")
    assert out == ["Name: Rafa", "Lang: PT"]


def test_peer_card_returns_none_when_empty(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    assert client.peer_card() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -k peer_card -q`
Expected: FAIL — `AttributeError: ... 'peer_card'`.

- [ ] **Step 3: Write minimal implementation**

Add to `HonchoClient`:

```python
    def peer_card(self) -> list[str] | None:
        self.ensure_peer(self.config.user_peer)
        result = self._request("GET", self._ws_path("peers", self.config.user_peer, "card"))
        if isinstance(result, dict):
            card = result.get("card") or result.get("peer_card")
            if isinstance(card, list):
                return [str(item) for item in card]
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): peer_card via GET peers/{peer}/card"
```

---

## Task 7: `doctor` + drop-in parity test

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex/rest.py`
- Test: `plugins/honcho-codex/tests/test_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rest.py`:

```python
from honcho_codex.cli import HonchoCli


def test_doctor_returns_ok(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    assert client.doctor().get("ok") is True


def test_client_is_drop_in_for_cli():
    # every method the hook relies on must exist with the same name on HonchoClient
    for name in ("ensure_workspace", "ensure_peer", "ensure_session",
                 "add_message", "session_context", "peer_card", "doctor"):
        assert hasattr(rest.HonchoClient, name), name
        assert hasattr(HonchoCli, name), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -k "doctor or drop_in" -q`
Expected: FAIL — `AttributeError: ... 'doctor'`.

- [ ] **Step 3: Write minimal implementation**

Add to `HonchoClient` (uses the already-verified workspace endpoint as a connectivity probe — no unverified endpoint):

```python
    def doctor(self) -> dict[str, Any]:
        self.ensure_workspace()
        return {"ok": True, "workspace": self.config.workspace, "base_url": self._base}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_rest.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex/rest.py plugins/honcho-codex/tests/test_rest.py
git commit -m "feat(rest): doctor connectivity check + drop-in parity test"
```

---

## Task 8: swap the hook to `HonchoClient`

**Files:**
- Modify: `plugins/honcho-codex/scripts/honcho_codex_hook.py` (import line 9; construction lines 138-143)
- Test: `plugins/honcho-codex/tests/test_hook_rest.py` (new)

- [ ] **Step 1: Write the failing test**

Create `plugins/honcho-codex/tests/test_hook_rest.py`. This drives `main()` for a `Stop` event with an injected fake client and asserts the assistant message is sent (no CLI, no network):

```python
import importlib
import io
import json

from honcho_codex import state

hook = importlib.import_module("honcho_codex_hook")


class FakeClient:
    last = None

    def __init__(self, config):
        FakeClient.last = self
        self.messages = []

    def add_message(self, session_name, peer_id, content, metadata):
        self.messages.append((session_name, peer_id, content))

    def session_context(self, *a):
        return None

    def peer_card(self):
        return None


def test_stop_event_sends_assistant_message_via_client(monkeypatch, tmp_path, capsys):
    # isolate state files
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(state, "LOG_PATH", tmp_path / "logs.jsonl")
    monkeypatch.setattr(state, "ENSURED_PATH", tmp_path / "ensured.json")
    # use the REST client class but inject a fake
    monkeypatch.setattr(hook, "HonchoClient", FakeClient)
    monkeypatch.setenv("HONCHO_API_KEY", "test-key")

    payload = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "codex-test",
        "turn_id": "turn-1",
        "last_assistant_message": "- did a thing with a leading bullet that is meaningful enough",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    rc = hook.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"continue": True}
    assert FakeClient.last.messages, "assistant message should have been sent"
    assert FakeClient.last.messages[0][2].startswith("- did a thing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/test_hook_rest.py -q`
Expected: FAIL — `AttributeError: module 'honcho_codex_hook' has no attribute 'HonchoClient'` (the hook still imports `HonchoCli`).

- [ ] **Step 3: Write minimal implementation**

In `honcho_codex_hook.py`, change the import (line 9) from:

```python
from honcho_codex.cli import HonchoCli, HonchoCliError
```

to:

```python
from honcho_codex.rest import HonchoClient, HonchoError
```

Then change the construction block (lines 138-143) from:

```python
    try:
        client = HonchoCli(config)
    except HonchoCliError as exc:
        log_event({"event": event_name, "status": "skipped", "reason": str(exc)})
        _empty_success(event_name)
        return 0
```

to:

```python
    try:
        client = HonchoClient(config)
    except HonchoError as exc:
        log_event({"event": event_name, "status": "skipped", "reason": str(exc)})
        _empty_success(event_name)
        return 0
```

No other lines change — `add_message`, `session_context`, `peer_card`, and `_flush_queue` have identical signatures.

- [ ] **Step 4: Run test to verify it passes (and the whole suite)**

Run: `cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex && PYTHONPATH=scripts uv run --with pytest python -m pytest tests/ -q`
Expected: PASS — all tests green. Note: `tests/test_hook_output.py::test_stop_hook_returns_continue_without_cli` still passes because its env has no `HONCHO_API_KEY`, so `HonchoClient.__init__` raises `HonchoError` → the hook skips gracefully and returns `{"continue": true}`.

- [ ] **Step 5: Commit**

```bash
cd /home/rafa/plugins/honcho-codex
git add plugins/honcho-codex/scripts/honcho_codex_hook.py plugins/honcho-codex/tests/test_hook_rest.py
git commit -m "feat(hook): use in-process HonchoClient (REST) instead of the honcho CLI"
```

---

## Task 9: live smoke + perf check (run by the implementing agent, throwaway workspace)

This task validates against the real API using the same throwaway-workspace technique used for the hyphen fix. It does **not** touch Rafa's `rafa` workspace. `HONCHO_API_KEY` is present in the environment.

- [ ] **Step 1: Run the REST client live against a throwaway workspace**

```bash
cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex
cat > /tmp/honcho_rest_smoke.py <<'PY'
import json, sys, time
sys.path.insert(0, "scripts")
from honcho_codex.config import HonchoCodexConfig
from honcho_codex import state
state.STATE_DIR = state.Path("/tmp/honcho-smoke-state")
state.ENSURED_PATH = state.STATE_DIR / "ensured.json"
from honcho_codex import rest

cfg = HonchoCodexConfig(
    api_key=__import__("os").environ["HONCHO_API_KEY"],
    base_url="https://api.honcho.dev", workspace="ztmp-rest-smoke-003",
    user_peer="user", assistant_peer="codex", session_strategy="per-directory",
    session_peer_prefix=True, save_user_messages=True, save_assistant_messages=True,
    save_tool_calls=False, inject_user_prompt_context=False,
    max_message_chars=12000, context_tokens=500,
)
c = rest.HonchoClient(cfg)
t0 = time.time()
c.add_message("s1", "codex", "- bullet line one\n- bullet line two", {"source": "smoke"})
print("add_message ok in %.0fms" % ((time.time()-t0)*1000))
print("CARD:", c.peer_card())
print("CTX:", (c.session_context("s1", 500) or "")[:160])
PY
PYTHONPATH=scripts uv run python /tmp/honcho_rest_smoke.py
```
Expected: `add_message ok`, a context string containing the bullet message. Confirms the hyphen content round-trips over REST.

- [ ] **Step 2: Confirm the message landed and clean up**

```bash
honcho message list ztmp-rest-smoke-003/s1 -w ztmp-rest-smoke-003 --json 2>/dev/null | grep -c "bullet line one" || true
honcho session delete s1 --workspace ztmp-rest-smoke-003 --yes --json >/dev/null 2>&1
honcho workspace delete ztmp-rest-smoke-003 --yes --json >/dev/null 2>&1
rm -f /tmp/honcho_rest_smoke.py
rm -rf /tmp/honcho-smoke-state
```
Expected: count ≥ 1, then cleanup succeeds.

- [ ] **Step 3: (optional) perf note**

Record in the final summary the observed `add_message` in-process latency vs. the old CLI path (the old path spawns ~5 `honcho` subprocesses per Stop event). No code change.

- [ ] **Step 4: Commit (docs only, if any notes were added)**

No code commit required for this task unless smoke reveals a fix is needed; if it does, write a failing test first (return to the relevant task).

---

## Task 10: final verification & summary

- [ ] **Step 1: Full suite + sanity**

```bash
cd /home/rafa/plugins/honcho-codex/plugins/honcho-codex
PYTHONPATH=scripts uv run --with pytest python -m pytest tests/ -q
PYTHONPATH=scripts uv run python -c "import honcho_codex.rest, honcho_codex_hook; print('import ok')"
```
Expected: all tests pass; import ok.

- [ ] **Step 2: Confirm no push**

```bash
cd /home/rafa/plugins/honcho-codex && git log --oneline -8 && git status --short
```
Expected: the new commits on `main`, clean working tree, **not pushed** (Rafa pushes after review).

---

## Self-Review notes (filled in by the planner)

- **Spec coverage:** transport (Tasks 2), in-process REST for all hot-path ops (Tasks 4-6), kill-redundant-ensures cache (Tasks 1, 3), drop-in swap (Task 8), keep `cli.py` for cold paths (untouched), no new dependency (stdlib only), hyphen regression lock (Task 4), live validation (Task 9). All spec sections map to a task.
- **Placeholder scan:** none — every code step shows full code; every run step shows the command + expected result.
- **Type consistency:** method names used in the hook swap (`add_message`, `session_context`, `peer_card`, `ensure_*`) match those defined in Tasks 3-6; `HonchoError` defined in Task 2 is the type caught in Task 8; `is_ensured`/`mark_ensured` defined in Task 1 are called in Task 3; `_ws_path` defined in Task 3 is used in Tasks 4-7.
- **Out of scope (intentional):** `representation()` (dead code) not ported; Track 2 write modes untouched; `cli.py` retirement deferred.
```
