import json

from honcho_codex import status
from test_rest import install_transport, _point_state


def test_status_outputs_resolved_config_and_context(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    codex_cfg = home / ".honcho" / "codex"
    codex_cfg.mkdir(parents=True)
    (codex_cfg / "config.json").write_text(
        json.dumps(
            {
                "apiKey": "test-key",
                "workspace": "test-ws",
                "userPeer": "rafa",
                "assistantPeer": "assistant",
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    _point_state(monkeypatch, tmp_path / "state")

    def handler(method, url, headers, body):
        if "/context" in url:
            return b'{"summary": "project summary", "messages": [{"peer_id": "rafa", "content": "hello"}]}'
        if url.endswith("/card"):
            return b'{"card": ["Name: Rafa"]}'
        return b"{}"

    install_transport(monkeypatch, handler)

    status.main(["--cwd", str(tmp_path / "repo"), "--tokens", "250"])

    out = json.loads(capsys.readouterr().out)
    assert out["workspace"] == "test-ws"
    assert out["userPeer"] == "rafa"
    assert out["assistantPeer"] == "assistant"
    assert out["session"] == "rafa-repo"
    assert "project summary" in out["sessionContext"]
    assert out["peerCard"] == ["Name: Rafa"]
