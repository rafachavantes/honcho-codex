from honcho_codex import state


def test_enqueue_dedupes_by_key(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(state, "LOG_PATH", tmp_path / "logs.jsonl")

    payload = {"dedupe_key": "k1", "content": "hello"}
    state.enqueue(payload)
    state.enqueue(payload)
    assert len(state.read_queue()) == 1


def test_enqueue_skips_already_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "QUEUE_PATH", tmp_path / "queue.jsonl")
    monkeypatch.setattr(state, "LOG_PATH", tmp_path / "logs.jsonl")

    state.mark_sent("k1")
    state.enqueue({"dedupe_key": "k1", "content": "hello"})
    assert state.read_queue() == []
