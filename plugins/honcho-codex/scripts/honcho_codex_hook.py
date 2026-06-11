#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from typing import Any

from honcho_codex.rest import HonchoClient, HonchoError
from honcho_codex.config import load_config
from honcho_codex.policy import SLIM_POINTER, decide_injection
from honcho_codex.formatting import (
    event_key,
    format_memory_context,
    meaningful_assistant_message,
    truncate_message,
)
from honcho_codex.state import (
    enqueue,
    log_event,
    mark_sent,
    read_queue,
    rewrite_queue,
    was_sent,
)


def _json_out(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def _empty_success(event_name: str) -> None:
    if event_name in {"Stop", "PreCompact"}:
        _json_out({"continue": True})


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _metadata(payload: dict[str, Any], session_name: str) -> dict[str, Any]:
    return {
        "codex_session_id": payload.get("session_id"),
        "turn_id": payload.get("turn_id"),
        "hook_event_name": payload.get("hook_event_name"),
        "session_affinity": session_name,
        "source": "honcho-codex",
    }


def _flush_queue(client: HonchoClient, max_items: int = 10) -> None:
    remaining = []
    queue = read_queue()
    for item in queue[:max_items]:
        key = item["dedupe_key"]
        if was_sent(key):
            continue
        try:
            client.add_message(
                item["session_name"],
                item["peer_id"],
                item["content"],
                item.get("metadata", {}),
            )
            mark_sent(key)
        except Exception as exc:
            log_event(
                {
                    "event": "flush_error",
                    "dedupe_key": key,
                    "error": str(exc),
                }
            )
            remaining.append(item)
    remaining.extend(queue[max_items:])
    rewrite_queue(remaining)


def _save_message(
    client: HonchoClient,
    payload: dict[str, Any],
    session_name: str,
    peer_id: str,
    content: str,
    suffix: str,
) -> None:
    key = event_key(payload, suffix)
    if was_sent(key):
        return
    metadata = _metadata(payload, session_name)
    try:
        client.add_message(session_name, peer_id, content, metadata)
        mark_sent(key)
    except Exception:
        enqueue(
            {
                "dedupe_key": key,
                "session_name": session_name,
                "peer_id": peer_id,
                "content": content,
                "metadata": metadata,
            }
        )


def _inject_context(
    event_name: str,
    session_name: str,
    context: str | None,
    representation: str | None,
    card: list[str] | None = None,
) -> None:
    additional_context = "[Honcho Memory]\n" + format_memory_context(
        session_name,
        context,
        representation,
        card,
    )
    _json_out(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": additional_context,
            }
        }
    )


def main() -> int:
    payload = _load_payload()
    event_name = payload.get("hook_event_name") or ""
    cwd = payload.get("cwd") or os.getcwd()
    config = load_config()
    session_name = config.session_name_for_cwd(cwd)

    try:
        client = HonchoClient(config)
    except HonchoError as exc:
        log_event({"event": event_name, "status": "skipped", "reason": str(exc)})
        _empty_success(event_name)
        return 0

    try:
        _flush_queue(client)

        if event_name == "SessionStart":
            mode = decide_injection(payload.get("source"), config.inject_on_compact)
            if mode != "full":
                # Post-compact start: the host's own compaction summary carries
                # recent context, so skip the session_context/peer_card REST
                # calls. The queue flush above already ran. slim -> one-line
                # pointer; off -> no output at all.
                if mode == "slim":
                    _json_out(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "SessionStart",
                                "additionalContext": "[Honcho Memory]\n" + SLIM_POINTER,
                            }
                        }
                    )
                log_event(
                    {"event": "SessionStart", "status": "post_compact", "mode": mode}
                )
                return 0
            context = client.session_context(session_name, config.context_tokens)
            card = client.peer_card()
            # Conclusions (representation) are intentionally NOT injected: the Honcho
            # backend's limit_to_session is a no-op for the semantic/most-derived branches,
            # so session-scoped conclusions leak cross-project. We inject the correctly-scoped
            # session summary + the global peerCard (identity), matching the Claude plugin.
            # See honcho-install/docs/honcho-upstream-issue-limit-to-session.md
            _inject_context("SessionStart", session_name, context, None, card)
            return 0

        if event_name == "UserPromptSubmit":
            prompt = (payload.get("prompt") or "").strip()
            if prompt and config.save_user_messages:
                content = truncate_message(prompt, config.max_message_chars)
                _save_message(
                    client,
                    payload,
                    session_name,
                    config.user_peer,
                    content,
                    "user",
                )
            if not config.inject_user_prompt_context:
                return 0
            context = client.session_context(session_name, config.context_tokens)
            card = client.peer_card()
            # See note above: conclusions leak via the backend bug, so inject
            # summary (scoped) + peerCard (global identity) only.
            _inject_context("UserPromptSubmit", session_name, context, None, card)
            return 0

        if event_name == "Stop":
            message = (payload.get("last_assistant_message") or "").strip()
            if (
                message
                and config.save_assistant_messages
                and meaningful_assistant_message(message)
            ):
                content = truncate_message(message, config.max_message_chars)
                _save_message(
                    client,
                    payload,
                    session_name,
                    config.assistant_peer,
                    content,
                    "assistant",
                )
            _json_out({"continue": True})
            return 0

        if event_name == "PreCompact":
            _json_out({"continue": True})
            return 0

        _empty_success(event_name)
        return 0
    except Exception as exc:
        log_event({"event": event_name, "status": "error", "error": str(exc)})
        _empty_success(event_name)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
