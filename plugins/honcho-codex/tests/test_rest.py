import io
import json

import pytest

from honcho_codex import rest, state
from honcho_codex.cli import HonchoCli
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
        inject_on_compact="slim",
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


def _point_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "ENSURED_PATH", tmp_path / "ensured.json")


# --- transport ---------------------------------------------------------------

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


# --- ensure -----------------------------------------------------------------

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

    before = len(calls)
    client.ensure_session("s1")
    assert len(calls) == before


def test_ensure_peer_adds_peer_with_id_body(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client.ensure_peer("user")
    peer_call = next(c for c in calls if c["url"].endswith("/peers"))
    assert json.loads(peer_call["body"]) == {"id": "user", "metadata": {"source": "honcho-codex"}}


def test_ensure_creates_include_source_metadata(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client.ensure_workspace()
    ws_call = next(c for c in calls if c["url"].endswith("/workspaces"))
    body = json.loads(ws_call["body"])
    assert body["id"] == "test-ws"
    assert body["metadata"] == {"source": "honcho-codex"}


def test_request_maps_urlerror_to_honcho_error(monkeypatch):
    from urllib.error import URLError

    def boom(req, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr(rest, "urlopen", boom)
    client = rest.HonchoClient(cfg())
    with pytest.raises(rest.HonchoError):
        client._request("GET", "/v3/workspaces")


def test_request_returns_none_on_empty_body(monkeypatch):
    install_transport(monkeypatch, lambda *a: b"")
    client = rest.HonchoClient(cfg())
    assert client._request("POST", "/v3/workspaces", {"id": "x"}) is None


def test_add_message_raises_if_404_persists_after_retry(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    for k in ("session:test-ws:s1", "workspace:test-ws", "peer:test-ws:user", "peer:test-ws:codex"):
        kind, key = k.split(":", 1)
        state.mark_ensured(kind, key)

    def handler(method, url, headers, body):
        if url.endswith("/messages"):
            from urllib.error import HTTPError
            raise HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return b"{}"

    install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    with pytest.raises(rest.HonchoError):  # second 404 propagates — no infinite loop
        client.add_message("s1", "codex", "x", {})


# --- add_message ------------------------------------------------------------

def test_add_message_posts_to_messages_endpoint(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    calls = install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    client.add_message("s1", "assistant", "- bullet content", {"source": "test"})
    msg_call = next(c for c in calls if c["url"].endswith("/messages"))
    assert msg_call["method"] == "POST"
    payload = json.loads(msg_call["body"])
    assert payload["messages"][0]["content"] == "- bullet content"
    assert payload["messages"][0]["peer_id"] == "assistant"
    assert payload["messages"][0]["metadata"] == {"source": "test"}


def test_add_message_evicts_cache_and_retries_on_404(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    state.mark_ensured("session", "test-ws:s1")
    state.mark_ensured("workspace", "test-ws")
    state.mark_ensured("peer", "test-ws:user")
    state.mark_ensured("peer", "test-ws:codex")
    seen = {"messages": 0}

    def handler(method, url, headers, body):
        if url.endswith("/messages"):
            seen["messages"] += 1
            if seen["messages"] == 1:
                from urllib.error import HTTPError
                raise HTTPError(url, 404, "Not Found", {}, io.BytesIO(b'{"error":"no session"}'))
            return b"{}"
        return b"{}"

    calls = install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    client.add_message("s1", "codex", "- recovered", {})
    assert seen["messages"] == 2
    assert any(c["url"].endswith("/sessions") for c in calls)


# --- session_context --------------------------------------------------------

def test_session_context_strips_metadata_keeps_summary_and_messages(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    rich = {
        "id": "s1",
        "messages": [
            {
                "id": "m1", "content": "faz push agora", "peer_id": "rafa",
                "session_id": "s1",
                "metadata": {"turn_id": "x", "codex_session_id": "y", "session_affinity": "s1"},
                "created_at": "2026-06-08T14:51:35Z", "workspace_id": "rafa", "token_count": 5,
            },
        ],
        "summary": {"content": "RESUMO DO PROJETO", "message_id": "m1",
                    "summary_type": "honcho_chat_summary_long", "token_count": 1101},
        "peer_representation": None,
        "peer_card": None,
    }

    def handler(method, url, headers, body):
        if "/context" in url:
            return json.dumps(rich).encode()
        return b"{}"

    install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    out = client.session_context("s1", 500)
    # useful content kept
    assert "RESUMO DO PROJETO" in out
    assert "faz push agora" in out
    assert "rafa" in out
    # metadata noise removed
    for noise in ("turn_id", "codex_session_id", "session_affinity", "workspace_id",
                  "token_count", "summary_type", "message_id", "created_at", "session_id"):
        assert noise not in out, f"metadata leaked: {noise}"


def test_session_context_gets_summary_with_tokens(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)

    def handler(method, url, headers, body):
        if "/context" in url:
            return b'{"session_id": "s1", "summary": "did stuff"}'
        return b"{}"

    calls = install_transport(monkeypatch, handler)
    client = rest.HonchoClient(cfg())
    out = client.session_context("s1", 500)
    ctx_call = next(c for c in calls if "/context" in c["url"])
    assert ctx_call["method"] == "GET"
    assert "summary=true" in ctx_call["url"]
    assert "tokens=500" in ctx_call["url"]
    assert "did stuff" in out


# --- peer_card --------------------------------------------------------------

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


# --- doctor + parity --------------------------------------------------------

def test_doctor_returns_ok(monkeypatch, tmp_path):
    _point_state(monkeypatch, tmp_path)
    install_transport(monkeypatch, lambda *a: b"{}")
    client = rest.HonchoClient(cfg())
    assert client.doctor().get("ok") is True


def test_client_is_drop_in_for_cli():
    for name in ("ensure_workspace", "ensure_peer", "ensure_session",
                 "add_message", "session_context", "peer_card", "doctor"):
        assert hasattr(rest.HonchoClient, name), name
        assert hasattr(HonchoCli, name), name
