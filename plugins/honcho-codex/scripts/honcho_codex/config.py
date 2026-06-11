from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path.home() / ".honcho" / "codex" / "config.json"


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


_INJECT_ON_COMPACT_VALUES = {"full", "slim", "off"}


def _inject_on_compact(file_cfg: dict) -> str:
    value = os.environ.get("HONCHO_INJECT_ON_COMPACT") or str(
        file_cfg.get("injectOnCompact", "slim")
    )
    value = value.lower()
    return value if value in _INJECT_ON_COMPACT_VALUES else "slim"


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    return cleaned or "session"


def _read_file_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


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

    def session_name_for_cwd(self, cwd: str) -> str:
        repo = _sanitize(Path(cwd).name or "workspace")
        if self.session_strategy != "per-directory":
            repo = _sanitize(Path(cwd).name or "workspace")
        if self.session_peer_prefix:
            return f"{_sanitize(self.user_peer)}-{repo}"
        return repo


def load_config() -> HonchoCodexConfig:
    file_cfg = _read_file_config()
    default_user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"

    return HonchoCodexConfig(
        api_key=os.environ.get("HONCHO_API_KEY") or file_cfg.get("apiKey"),
        base_url=os.environ.get("HONCHO_BASE_URL")
        or file_cfg.get("baseUrl")
        or "https://api.honcho.dev",
        workspace=os.environ.get("HONCHO_WORKSPACE")
        or os.environ.get("HONCHO_WORKSPACE_ID")
        or file_cfg.get("workspace")
        or "default",
        user_peer=os.environ.get("HONCHO_USER_PEER")
        or file_cfg.get("userPeer")
        or default_user,
        assistant_peer=os.environ.get("HONCHO_ASSISTANT_PEER")
        or file_cfg.get("assistantPeer")
        or "codex",
        session_strategy=os.environ.get("HONCHO_SESSION_STRATEGY")
        or file_cfg.get("sessionStrategy")
        or "per-directory",
        session_peer_prefix=_bool_env(
            "HONCHO_SESSION_PEER_PREFIX",
            bool(file_cfg.get("sessionPeerPrefix", True)),
        ),
        save_user_messages=_bool_env(
            "HONCHO_SAVE_USER_MESSAGES",
            bool(file_cfg.get("saveUserMessages", True)),
        ),
        save_assistant_messages=_bool_env(
            "HONCHO_SAVE_ASSISTANT_MESSAGES",
            bool(file_cfg.get("saveAssistantMessages", True)),
        ),
        save_tool_calls=_bool_env(
            "HONCHO_SAVE_TOOL_CALLS",
            bool(file_cfg.get("saveToolCalls", False)),
        ),
        inject_user_prompt_context=_bool_env(
            "HONCHO_INJECT_USER_PROMPT_CONTEXT",
            bool(file_cfg.get("injectUserPromptContext", False)),
        ),
        inject_on_compact=_inject_on_compact(file_cfg),
        max_message_chars=int(
            os.environ.get("HONCHO_MAX_MESSAGE_CHARS")
            or file_cfg.get("maxMessageChars")
            or 12000
        ),
        context_tokens=int(
            os.environ.get("HONCHO_CONTEXT_TOKENS")
            or file_cfg.get("contextTokens")
            or 4000
        ),
    )


if __name__ == "__main__":
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
                "exampleSession": cfg.session_name_for_cwd(os.getcwd()),
            },
            indent=2,
        )
    )
