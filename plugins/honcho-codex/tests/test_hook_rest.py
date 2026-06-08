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
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(state, "LOG_PATH", tmp_path / "logs.jsonl")
    monkeypatch.setattr(state, "ENSURED_PATH", tmp_path / "ensured.json")
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
