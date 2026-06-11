import json

import pytest

from honcho_codex.config import load_config
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


def test_inject_on_compact_defaults_to_slim(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HONCHO_INJECT_ON_COMPACT", raising=False)
    cfg = load_config()
    assert cfg.inject_on_compact == "slim"


def test_inject_on_compact_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_INJECT_ON_COMPACT", "off")
    cfg = load_config()
    assert cfg.inject_on_compact == "off"


def test_inject_on_compact_invalid_value_falls_back_to_slim(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HONCHO_INJECT_ON_COMPACT", "bogus")
    cfg = load_config()
    assert cfg.inject_on_compact == "slim"


def test_inject_on_compact_file_key(monkeypatch, tmp_path):
    # CONFIG_PATH is resolved at import time, so patch the constant directly
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"injectOnCompact": "full"}))
    monkeypatch.setattr("honcho_codex.config.CONFIG_PATH", cfg_file)
    monkeypatch.delenv("HONCHO_INJECT_ON_COMPACT", raising=False)
    cfg = load_config()
    assert cfg.inject_on_compact == "full"
