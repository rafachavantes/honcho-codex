from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Sequence


def _codex_config_path() -> Path:
    return Path.home() / ".honcho" / "codex" / "config.json"


def _unified_config_path() -> Path:
    return Path.home() / ".honcho" / "config.json"


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


_INJECT_ON_COMPACT_VALUES = {"full", "slim", "off"}


def _first_value(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _inject_on_compact(file_cfg: dict, host_cfg: dict, global_cfg: dict) -> str:
    value = os.environ.get("HONCHO_INJECT_ON_COMPACT") or str(
        _first_value(
            file_cfg.get("injectOnCompact"),
            host_cfg.get("injectOnCompact"),
            global_cfg.get("injectOnCompact"),
            "slim",
        )
    )
    value = value.lower()
    return value if value in _INJECT_ON_COMPACT_VALUES else "slim"


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    return cleaned or "session"


def _git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=32)
def _git_repo_root(cwd: str) -> str | None:
    """Main worktree root for any path inside a repo, else None.

    Subdirectories and linked worktrees (per-branch checkouts) all resolve to
    the same root, so one repo maps to one Honcho session. The common dir is
    the main worktree's .git even for linked worktrees; its parent is the
    canonical root.
    """
    toplevel = _git(cwd, "rev-parse", "--show-toplevel")
    if not toplevel:
        return None
    common_dir = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common_dir and Path(common_dir).name == ".git":
        return str(Path(common_dir).parent)
    return toplevel


def _read_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_file_config() -> dict:
    return _read_json_config(_codex_config_path())


def _read_unified_config() -> dict:
    return _read_json_config(_unified_config_path())


def _host_config(global_cfg: dict) -> dict:
    hosts = global_cfg.get("hosts")
    if not isinstance(hosts, dict):
        return {}
    host = hosts.get("codex")
    return host if isinstance(host, dict) else {}


def _cfg_value(file_cfg: dict, host_cfg: dict, global_cfg: dict, *keys: str):
    for source in (file_cfg, host_cfg, global_cfg):
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _configured_bool(
    env_name: str,
    default: bool,
    file_cfg: dict,
    host_cfg: dict,
    global_cfg: dict,
    key: str,
) -> bool:
    configured = _cfg_value(file_cfg, host_cfg, global_cfg, key)
    return _bool_env(env_name, bool(configured) if configured is not None else default)


@dataclass(frozen=True)
class HonchoCodexConfig:
    api_key: str | None
    base_url: str
    workspace: str
    user_peer: str
    assistant_peer: str
    session_strategy: str
    session_peer_prefix: bool
    save_user_messages: bool
    save_assistant_messages: bool
    save_tool_calls: bool
    inject_user_prompt_context: bool
    inject_on_compact: str
    max_message_chars: int
    context_tokens: int
    session_overrides: dict[str, str] = field(default_factory=dict)

    def session_name_for_cwd(self, cwd: str) -> str:
        # Session identity follows the repo, not the raw cwd: any
        # subdirectory or linked worktree resolves to the main repo root,
        # so one repo maps to one session. Non-git dirs keep the cwd.
        root = _git_repo_root(cwd) or cwd
        for candidate in (cwd, root):
            override = self.session_overrides.get(str(Path(candidate)))
            if override:
                return override
        repo = _sanitize(Path(root).name or "workspace")
        if self.session_peer_prefix:
            return f"{_sanitize(self.user_peer)}-{repo}"
        return repo


def load_config() -> HonchoCodexConfig:
    file_cfg = _read_file_config()
    global_cfg = _read_unified_config()
    host_cfg = _host_config(global_cfg)
    default_user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    session_overrides = global_cfg.get("sessions")
    if not isinstance(session_overrides, dict):
        session_overrides = {}
    session_peer_prefix = _configured_bool(
        "HONCHO_SESSION_PEER_PREFIX",
        True,
        file_cfg,
        host_cfg,
        global_cfg,
        "sessionPeerPrefix",
    )
    save_user_messages = _configured_bool(
        "HONCHO_SAVE_USER_MESSAGES",
        True,
        file_cfg,
        host_cfg,
        global_cfg,
        "saveUserMessages",
    )
    save_assistant_messages = _configured_bool(
        "HONCHO_SAVE_ASSISTANT_MESSAGES",
        True,
        file_cfg,
        host_cfg,
        global_cfg,
        "saveAssistantMessages",
    )
    save_tool_calls = _configured_bool(
        "HONCHO_SAVE_TOOL_CALLS",
        False,
        file_cfg,
        host_cfg,
        global_cfg,
        "saveToolCalls",
    )
    inject_user_prompt_context = _configured_bool(
        "HONCHO_INJECT_USER_PROMPT_CONTEXT",
        False,
        file_cfg,
        host_cfg,
        global_cfg,
        "injectUserPromptContext",
    )

    return HonchoCodexConfig(
        api_key=os.environ.get("HONCHO_API_KEY")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "apiKey"),
        base_url=os.environ.get("HONCHO_BASE_URL")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "baseUrl")
        or "https://api.honcho.dev",
        workspace=os.environ.get("HONCHO_WORKSPACE")
        or os.environ.get("HONCHO_WORKSPACE_ID")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "workspace")
        or "default",
        user_peer=os.environ.get("HONCHO_USER_PEER")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "userPeer", "peerName")
        or default_user,
        assistant_peer=os.environ.get("HONCHO_ASSISTANT_PEER")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "assistantPeer", "aiPeer")
        or "codex",
        session_strategy=os.environ.get("HONCHO_SESSION_STRATEGY")
        or _cfg_value(file_cfg, host_cfg, global_cfg, "sessionStrategy")
        or "per-directory",
        session_peer_prefix=session_peer_prefix,
        save_user_messages=save_user_messages,
        save_assistant_messages=save_assistant_messages,
        save_tool_calls=save_tool_calls,
        inject_user_prompt_context=inject_user_prompt_context,
        inject_on_compact=_inject_on_compact(file_cfg, host_cfg, global_cfg),
        max_message_chars=int(
            os.environ.get("HONCHO_MAX_MESSAGE_CHARS")
            or _cfg_value(file_cfg, host_cfg, global_cfg, "maxMessageChars")
            or 12000
        ),
        context_tokens=int(
            os.environ.get("HONCHO_CONTEXT_TOKENS")
            or _cfg_value(file_cfg, host_cfg, global_cfg, "contextTokens")
            or 4000
        ),
        session_overrides={str(Path(k)): str(v) for k, v in session_overrides.items()},
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Show resolved Honcho Codex config.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Directory used to resolve session name.")
    args = parser.parse_args(argv)
    cfg = load_config()
    print(
        json.dumps(
            {
                "configured": bool(cfg.api_key),
                "baseUrl": cfg.base_url,
                "workspace": cfg.workspace,
                "userPeer": cfg.user_peer,
                "assistantPeer": cfg.assistant_peer,
                "sessionStrategy": cfg.session_strategy,
                "sessionPeerPrefix": cfg.session_peer_prefix,
                "saveToolCalls": cfg.save_tool_calls,
                "injectUserPromptContext": cfg.inject_user_prompt_context,
                "injectOnCompact": cfg.inject_on_compact,
                "exampleSession": cfg.session_name_for_cwd(args.cwd),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
