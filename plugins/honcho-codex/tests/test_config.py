import json

from honcho_codex import config
from honcho_codex.config import load_config


def _clear_honcho_env(monkeypatch):
    for name in (
        "HONCHO_API_KEY",
        "HONCHO_BASE_URL",
        "HONCHO_WORKSPACE",
        "HONCHO_WORKSPACE_ID",
        "HONCHO_USER_PEER",
        "HONCHO_ASSISTANT_PEER",
        "HONCHO_SESSION_STRATEGY",
        "HONCHO_SESSION_PEER_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)


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


def test_unified_honcho_config_host_codex_is_used(monkeypatch, tmp_path):
    home = tmp_path / "home"
    config_dir = home / ".honcho"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "peerName": "rafa",
                "workspace": "global-ws",
                "apiKey": "global-key",
                "baseUrl": "https://honcho.example",
                "sessionStrategy": "per-directory",
                "sessionPeerPrefix": True,
                "hosts": {
                    "codex": {
                        "workspace": "codex-ws",
                        "aiPeer": "assistant",
                        "sessionPeerPrefix": False,
                    }
                },
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    _clear_honcho_env(monkeypatch)

    cfg = load_config()

    assert cfg.api_key == "global-key"
    assert cfg.base_url == "https://honcho.example"
    assert cfg.workspace == "codex-ws"
    assert cfg.user_peer == "rafa"
    assert cfg.assistant_peer == "assistant"
    assert cfg.session_peer_prefix is False


def test_codex_specific_config_wins_over_unified_config(monkeypatch, tmp_path):
    home = tmp_path / "home"
    unified_dir = home / ".honcho"
    codex_dir = unified_dir / "codex"
    codex_dir.mkdir(parents=True)
    (unified_dir / "config.json").write_text(
        json.dumps(
            {
                "peerName": "rafa",
                "workspace": "global-ws",
                "hosts": {"codex": {"aiPeer": "assistant"}},
            }
        )
    )
    (codex_dir / "config.json").write_text(
        json.dumps(
            {
                "workspace": "codex-specific-ws",
                "userPeer": "custom-user",
                "assistantPeer": "custom-assistant",
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    _clear_honcho_env(monkeypatch)

    cfg = load_config()

    assert cfg.workspace == "codex-specific-ws"
    assert cfg.user_peer == "custom-user"
    assert cfg.assistant_peer == "custom-assistant"


def test_session_name_uses_user_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_USER_PEER", "Jane Doe")
    cfg = load_config()
    assert cfg.session_name_for_cwd("/tmp/My Project") == "jane-doe-my-project"


def test_session_name_uses_unified_config_session_override(monkeypatch, tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home_config = home / ".honcho"
    home_config.mkdir(parents=True)
    repo.mkdir()
    (home_config / "config.json").write_text(
        json.dumps(
            {
                "peerName": "rafa",
                "sessions": {
                    str(repo): "configured-session",
                },
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    _clear_honcho_env(monkeypatch)

    cfg = load_config()

    assert cfg.session_name_for_cwd(str(repo)) == "configured-session"


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


def test_config_cli_accepts_cwd_for_example_session(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HONCHO_USER_PEER", "rafa")
    project = tmp_path / "project-dir"
    project.mkdir()

    config.main(["--cwd", str(project)])

    out = json.loads(capsys.readouterr().out)
    assert out["exampleSession"] == "rafa-project-dir"
