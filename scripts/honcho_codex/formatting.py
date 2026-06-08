from __future__ import annotations

from typing import Any


def truncate_message(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 80].rstrip() + "\n\n[Truncated by honcho-codex]"


def meaningful_assistant_message(content: str) -> bool:
    stripped = content.strip()
    if len(stripped) < 20:
        return False
    tool_only_prefixes = (
        "[Tool]",
        "Ran:",
        "Edited ",
        "Wrote ",
        "Reading ",
    )
    return not stripped.startswith(tool_only_prefixes)


def event_key(payload: dict[str, Any], suffix: str) -> str:
    session_id = payload.get("session_id") or "unknown-session"
    turn_id = payload.get("turn_id") or "unknown-turn"
    event = payload.get("hook_event_name") or "unknown-event"
    return f"{session_id}:{turn_id}:{event}:{suffix}"


def format_memory_context(
    session_name: str,
    context: str | None,
    representation: str | None,
) -> str:
    parts = [f"Honcho session: {session_name}"]
    if context:
        parts.append("Session context:\n" + context.strip())
    if representation:
        parts.append("Relevant memory:\n" + representation.strip())
    return "\n\n".join(parts)
