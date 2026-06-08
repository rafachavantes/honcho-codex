import json
import os
import subprocess
import sys
from pathlib import Path


def test_stop_hook_returns_continue_without_cli(tmp_path):
    script = Path(__file__).parents[1] / "scripts" / "honcho_codex_hook.py"
    payload = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "codex-test",
        "turn_id": "turn-1",
        "last_assistant_message": "A useful response that should not crash without the CLI.",
    }
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PYTHONPATH": str(script.parent),
    }
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"continue": True}


def test_hook_does_not_reference_tool_payload_fields():
    script = Path(__file__).parents[1] / "scripts" / "honcho_codex_hook.py"
    source = script.read_text()
    assert "tool_input" not in source
    assert "tool_response" not in source
    assert "PostToolUse" not in source
