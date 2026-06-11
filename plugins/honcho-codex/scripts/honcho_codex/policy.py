from __future__ import annotations

SLIM_POINTER = (
    "Honcho memory is active for this session; "
    "older details can be recalled via the honcho tools."
)


def decide_injection(source: str | None, inject_on_compact: str) -> str:
    """Source-aware injection policy.

    Only a SessionStart fired by context compaction is downgraded -- the host
    CLI's own compaction summary already carries recent context. Every other
    source (startup, resume, clear, missing) keeps full injection.
    """
    if source != "compact":
        return "full"
    return inject_on_compact
