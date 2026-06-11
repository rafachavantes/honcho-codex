import io
import json
import sys
from pathlib import Path

import pytest

from honcho_codex.config import load_config, HonchoCodexConfig
from honcho_codex.policy import SLIM_POINTER, decide_injection

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import honcho_codex_hook as hook


@pytest.mark.parametrize("source", ["startup", "resume", "clear", None])
def test_non_compact_sources_inject_full(source):
    for mode in ("full", "slim", "off"):
        assert decide_injection(source, mode) == "full"


def test_compact_source_follows_config():
    assert decide_injection("compact", "full") == "full"
    assert decide_injection("compact", "slim") == "slim"
    assert decide_injection("compact", "off") == "off"


def test_slim_pointer_is_one_short_line():
    assert "\n" not in SLIM_POINTER
    assert len(SLIM_POINTER) < 160


def test_inject_on_compact_defaults_to_slim(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HONCHO_INJECT_ON_COMPACT", raising=False)
    cfg = load_config()
    assert cfg.inject_on_compact == "slim"


def test_inject_on_compact_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_INJECT_ON_COMPACT", "off")
    cfg = load_config()
    assert cfg.inject_on_compact == "off"


def test_inject_on_compact_invalid_value_falls_back_to_slim(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_INJECT_ON_COMPACT", "bogus")
    cfg = load_config()
    assert cfg.inject_on_compact == "slim"


def test_inject_on_compact_file_key(monkeypatch, tmp_path):
    # CONFIG_PATH is resolved at import time, so patch the constant directly
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"injectOnCompact": "full"}))
    monkeypatch.setattr("honcho_codex.config.CONFIG_PATH", cfg_file)
    monkeypatch.delenv("HONCHO_INJECT_ON_COMPACT", raising=False)
    cfg = load_config()
    assert cfg.inject_on_compact == "full"


def _config(**overrides):
    base = dict(
        api_key="test-key",
        base_url="https://api.honcho.dev",
        workspace="test",
        user_peer="rafa",
        assistant_peer="codex",
        session_strategy="per-directory",
        session_peer_prefix=True,
        save_user_messages=True,
        save_assistant_messages=True,
        save_tool_calls=False,
        inject_user_prompt_context=False,
        max_message_chars=12000,
        context_tokens=4000,
        inject_on_compact="slim",
    )
    base.update(overrides)
    return HonchoCodexConfig(**base)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def session_context(self, *args, **kwargs):
        self.calls.append("session_context")
        return "ctx"

    def peer_card(self, *args, **kwargs):
        self.calls.append("peer_card")
        return ["card"]

    def add_message(self, *args, **kwargs):
        self.calls.append("add_message")


def _run_session_start(monkeypatch, capsys, source, mode):
    client = RecordingClient()
    flushes = []
    monkeypatch.setattr(hook, "load_config", lambda: _config(inject_on_compact=mode))
    monkeypatch.setattr(hook, "HonchoClient", lambda cfg: client)
    monkeypatch.setattr(hook, "_flush_queue", lambda c: flushes.append(True))
    monkeypatch.setattr(hook, "log_event", lambda e: None)
    payload = {"hook_event_name": "SessionStart", "cwd": "/tmp/x", "source": source}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = hook.main()
    assert rc == 0
    return client, flushes, capsys.readouterr().out


def test_compact_slim_skips_rest_and_injects_pointer(monkeypatch, capsys):
    client, flushes, out = _run_session_start(monkeypatch, capsys, "compact", "slim")
    assert client.calls == []  # no session_context / peer_card REST calls
    assert flushes == [True]  # queue flush still runs post-compact
    output = json.loads(out)
    assert SLIM_POINTER in output["hookSpecificOutput"]["additionalContext"]


def test_compact_off_skips_rest_and_injects_nothing(monkeypatch, capsys):
    client, flushes, out = _run_session_start(monkeypatch, capsys, "compact", "off")
    assert client.calls == []
    assert flushes == [True]
    assert out.strip() == ""


def test_compact_full_keeps_current_behavior(monkeypatch, capsys):
    client, _, out = _run_session_start(monkeypatch, capsys, "compact", "full")
    assert "session_context" in client.calls
    assert "peer_card" in client.calls
    assert "[Honcho Memory]" in out


def test_startup_source_unaffected_by_slim_mode(monkeypatch, capsys):
    client, _, out = _run_session_start(monkeypatch, capsys, "startup", "slim")
    assert "session_context" in client.calls
    assert "peer_card" in client.calls
    assert "[Honcho Memory]" in out


def test_missing_source_treated_as_full(monkeypatch, capsys):
    client, _, _ = _run_session_start(monkeypatch, capsys, None, "slim")
    assert "session_context" in client.calls
