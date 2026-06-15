from __future__ import annotations

import argparse
import json
import os
from typing import Sequence

from .config import load_config
from .rest import HonchoClient


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Show resolved Honcho Codex config and current REST context."
    )
    parser.add_argument("--cwd", default=os.getcwd(), help="Directory used to resolve session name.")
    parser.add_argument("--tokens", type=int, default=None, help="Context token budget.")
    args = parser.parse_args(argv)

    cfg = load_config()
    session_name = cfg.session_name_for_cwd(args.cwd)
    tokens = args.tokens if args.tokens is not None else cfg.context_tokens
    client = HonchoClient(cfg)

    out = {
        "configured": bool(cfg.api_key),
        "baseUrl": cfg.base_url,
        "workspace": cfg.workspace,
        "userPeer": cfg.user_peer,
        "assistantPeer": cfg.assistant_peer,
        "sessionStrategy": cfg.session_strategy,
        "sessionPeerPrefix": cfg.session_peer_prefix,
        "session": session_name,
        "sessionContext": client.session_context(session_name, tokens),
        "peerCard": client.peer_card(),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
