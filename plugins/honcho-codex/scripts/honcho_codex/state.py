from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / ".honcho" / "codex"
STATE_PATH = STATE_DIR / "state.json"
QUEUE_PATH = STATE_DIR / "queue.jsonl"
LOG_PATH = STATE_DIR / "logs.jsonl"


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    _ensure_dir()
    if not STATE_PATH.exists():
        return {"sent": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"sent": []}


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dir()
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp_path.replace(STATE_PATH)


def was_sent(key: str) -> bool:
    state = _load_state()
    return key in set(state.get("sent", []))


def mark_sent(key: str) -> None:
    state = _load_state()
    sent = list(dict.fromkeys([*state.get("sent", []), key]))
    state["sent"] = sent[-5000:]
    _save_state(state)


def enqueue(payload: dict[str, Any]) -> None:
    _ensure_dir()
    key = payload.get("dedupe_key")
    if key and was_sent(str(key)):
        return
    existing = read_queue()
    if key and any(item.get("dedupe_key") == key for item in existing):
        return
    with QUEUE_PATH.open("a") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")


def read_queue() -> list[dict[str, Any]]:
    _ensure_dir()
    if not QUEUE_PATH.exists():
        return []
    items = []
    for line in QUEUE_PATH.read_text().splitlines():
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    return items


def rewrite_queue(items: list[dict[str, Any]]) -> None:
    _ensure_dir()
    tmp_path = QUEUE_PATH.with_suffix(".jsonl.tmp")
    tmp_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items)
    )
    tmp_path.replace(QUEUE_PATH)


def log_event(event: dict[str, Any]) -> None:
    _ensure_dir()
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
