import importlib

from honcho_codex import state
from honcho_codex.cli import HonchoCliError

hook = importlib.import_module("honcho_codex_hook")


class _FailingClient:
    def add_message(self, *args, **kwargs):
        raise HonchoCliError("No such option '- '")


def _point_state_at(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(state, "LOG_PATH", tmp_path / "logs.jsonl")


def test_flush_logs_error_detail_and_keeps_item(monkeypatch, tmp_path):
    _point_state_at(monkeypatch, tmp_path)
    state.enqueue(
        {
            "dedupe_key": "k1",
            "session_name": "user-demo",
            "peer_id": "user",
            "content": "- Lemos o CSV",
            "metadata": {},
        }
    )

    hook._flush_queue(_FailingClient())

    # the failing item stays queued for retry
    assert len(state.read_queue()) == 1
    # the error detail is logged (no longer swallowed silently)
    log_text = (tmp_path / "logs.jsonl").read_text()
    assert "No such option" in log_text
    assert "k1" in log_text
