from honcho_codex.config import load_config


def test_workspace_id_alias_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HONCHO_WORKSPACE", raising=False)
    monkeypatch.setenv("HONCHO_WORKSPACE_ID", "workspace-from-cli-env")
    cfg = load_config()
    assert cfg.workspace == "workspace-from-cli-env"


def test_workspace_shorthand_wins_over_workspace_id(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_WORKSPACE", "plugin-shorthand")
    monkeypatch.setenv("HONCHO_WORKSPACE_ID", "official-env")
    cfg = load_config()
    assert cfg.workspace == "plugin-shorthand"


def test_session_name_uses_user_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_USER_PEER", "Jane Doe")
    cfg = load_config()
    assert cfg.session_name_for_cwd("/tmp/My Project") == "jane-doe-my-project"


def test_user_prompt_context_injection_defaults_off(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HONCHO_INJECT_USER_PROMPT_CONTEXT", raising=False)
    cfg = load_config()
    assert cfg.inject_user_prompt_context is False


def test_user_prompt_context_injection_can_be_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_INJECT_USER_PROMPT_CONTEXT", "true")
    cfg = load_config()
    assert cfg.inject_user_prompt_context is True
