import json
from pathlib import Path


def test_hooks_manifest_has_only_supported_top_level_fields():
    hooks_path = Path(__file__).parents[1] / "hooks" / "hooks.json"
    data = json.loads(hooks_path.read_text())
    assert set(data) == {"hooks"}
