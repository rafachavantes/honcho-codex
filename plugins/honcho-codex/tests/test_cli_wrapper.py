import shutil
import subprocess

from honcho_codex.cli import HonchoCli
from honcho_codex.config import HonchoCodexConfig


def cfg():
    return HonchoCodexConfig(
        api_key="test-key",
        base_url="https://api.honcho.dev",
        workspace="test-workspace",
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


def test_representation_passes_session(monkeypatch):
    calls = []
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/honcho")

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    HonchoCli(cfg()).representation("user-demo")
    assert ["honcho", "session", "representation", "codex", "user-demo", "--workspace"] == calls[-1][:6]


def test_message_create_uses_no_shell(monkeypatch):
    calls = []
    run_kwargs = []
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/honcho")

    def fake_run(args, **kwargs):
        calls.append(args)
        run_kwargs.append(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    HonchoCli(cfg()).add_message("user-demo", "user", "hello", {"source": "test"})
    assert any(call[:3] == ["honcho", "message", "create"] for call in calls)
    assert all(not kwargs.get("shell", False) for kwargs in run_kwargs)


def test_ensure_session_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/honcho")

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = HonchoCli(cfg())
    cli.ensure_session("user-demo")
    cli.ensure_session("user-demo")
    session_creates = [call for call in calls if call[:3] == ["honcho", "session", "create"]]
    assert len(session_creates) == 1
