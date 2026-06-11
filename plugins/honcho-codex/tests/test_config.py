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


def _init_git_repo(path):
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    env_git = ["git", "-c", "user.email=test@test", "-c", "user.name=test"]
    subprocess.run([*env_git, "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [*env_git, "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return env_git


def test_session_name_resolves_git_subdir_to_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HONCHO_USER_PEER", "rafa")
    repo = tmp_path / "my-repo"
    _init_git_repo(repo)
    sub = repo / "deep" / "nested"
    sub.mkdir(parents=True)
    cfg = load_config()
    assert cfg.session_name_for_cwd(str(sub)) == "rafa-my-repo"
    assert cfg.session_name_for_cwd(str(repo)) == "rafa-my-repo"


def test_session_name_resolves_worktree_to_main_repo_root(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HONCHO_USER_PEER", "rafa")
    repo = tmp_path / "my-repo"
    env_git = _init_git_repo(repo)
    worktree = tmp_path / "my-repo-wt"
    subprocess.run(
        [*env_git, "worktree", "add", str(worktree), "-b", "feature-branch"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    cfg = load_config()
    assert cfg.session_name_for_cwd(str(worktree)) == "rafa-my-repo"


def test_session_name_keeps_cwd_outside_git(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HONCHO_USER_PEER", "rafa")
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    cfg = load_config()
    assert cfg.session_name_for_cwd(str(plain)) == "rafa-plain-dir"
