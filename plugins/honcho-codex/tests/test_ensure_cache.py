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


def test_clear_ensured_removes_key(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path)
    state.mark_ensured("session", "rafa:s1", now=1000.0)
    state.clear_ensured("session", "rafa:s1")
    assert state.is_ensured("session", "rafa:s1", now=1000.0) is False
