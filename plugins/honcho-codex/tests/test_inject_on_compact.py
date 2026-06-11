import pytest

from honcho_codex.policy import SLIM_POINTER, decide_injection


@pytest.mark.parametrize("source", ["startup", "resume", "clear", None])
def test_non_compact_sources_inject_full(source):
    for mode in ("full", "slim", "off"):
        assert decide_injection(source, mode) == "full"


def test_compact_source_follows_config():
    assert decide_injection("compact", "full") == "full"
    assert decide_injection("compact", "slim") == "slim"
    assert decide_injection("compact", "off") == "off"


def test_slim_pointer_is_one_short_line():
    assert "\n" not in SLIM_POINTER
    assert len(SLIM_POINTER) < 160
