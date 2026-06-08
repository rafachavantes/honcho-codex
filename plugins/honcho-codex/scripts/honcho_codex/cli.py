from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from .config import HonchoCodexConfig


class HonchoCliError(RuntimeError):
    pass


class HonchoCli:
    def __init__(self, config: HonchoCodexConfig):
        if not shutil.which("honcho"):
            raise HonchoCliError("honcho CLI is not installed or not on PATH")
        self.config = config
        self._ensured_workspaces: set[str] = set()
        self._ensured_peers: set[str] = set()
        self._ensured_sessions: set[str] = set()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.config.api_key:
            env["HONCHO_API_KEY"] = self.config.api_key
        if self.config.base_url:
            env["HONCHO_BASE_URL"] = self.config.base_url
        env["HONCHO_JSON"] = "1"
        return env

    def _run(self, args: list[str], input_text: str | None = None) -> Any:
        proc = subprocess.run(
            ["honcho", *args],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            timeout=8,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise HonchoCliError(detail or f"honcho exited with {proc.returncode}")
        output = proc.stdout.strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output

    def doctor(self) -> Any:
        return self._run(["doctor", "--json"])

    def ensure_workspace(self) -> None:
        if self.config.workspace in self._ensured_workspaces:
            return
        self._run(
            [
                "workspace",
                "create",
                "--metadata",
                json.dumps({"source": "honcho-codex"}),
                "--json",
                "--",
                self.config.workspace,
            ]
        )
        self._ensured_workspaces.add(self.config.workspace)

    def ensure_peer(self, peer_id: str) -> None:
        peer_key = f"{self.config.workspace}:{peer_id}"
        if peer_key in self._ensured_peers:
            return
        self._run(
            [
                "peer",
                "create",
                "--workspace",
                self.config.workspace,
                "--metadata",
                json.dumps({"source": "honcho-codex"}),
                "--json",
                "--",
                peer_id,
            ]
        )
        self._ensured_peers.add(peer_key)

    def ensure_session(self, session_name: str) -> None:
        session_key = f"{self.config.workspace}:{session_name}"
        if session_key in self._ensured_sessions:
            return
        self.ensure_workspace()
        self.ensure_peer(self.config.user_peer)
        self.ensure_peer(self.config.assistant_peer)
        self._run(
            [
                "session",
                "create",
                "--workspace",
                self.config.workspace,
                "--peers",
                f"{self.config.user_peer},{self.config.assistant_peer}",
                "--metadata",
                json.dumps({"source": "honcho-codex"}),
                "--json",
                "--",
                session_name,
            ]
        )
        self._ensured_sessions.add(session_key)

    def add_message(
        self,
        session_name: str,
        peer_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        self.ensure_session(session_name)
        self._run(
            [
                "message",
                "create",
                "--workspace",
                self.config.workspace,
                "--session",
                session_name,
                "--peer",
                peer_id,
                "--metadata",
                json.dumps(metadata),
                "--json",
                # `--` ends option parsing so content starting with `-` is not
                # mis-parsed by the honcho CLI (Typer/Click) as an option.
                # Content MUST stay last, right after the separator.
                "--",
                content,
            ]
        )

    def session_context(self, session_name: str, tokens: int) -> str | None:
        self.ensure_session(session_name)
        result = self._run(
            [
                "session",
                "context",
                session_name,
                "--workspace",
                self.config.workspace,
                "--tokens",
                str(tokens),
                "--summary",
                "--json",
            ]
        )
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        return str(result) if result else None

    def peer_card(self) -> list[str] | None:
        """Global peer card (stable identity/preferences about the user).

        Peer-level and global by design — safe to inject in any session, unlike
        conclusions. Mirrors the Claude plugin's peerCard injection.
        """
        self.ensure_peer(self.config.user_peer)
        result = self._run(
            [
                "peer",
                "card",
                self.config.user_peer,
                "--workspace",
                self.config.workspace,
                "--json",
            ]
        )
        if isinstance(result, dict):
            card = result.get("card") or result.get("peer_card")
            if isinstance(card, list):
                return [str(item) for item in card]
        return None

    def representation(self, session_name: str) -> str | None:
        self.ensure_session(session_name)
        result = self._run(
            [
                "session",
                "representation",
                self.config.assistant_peer,
                session_name,
                "--workspace",
                self.config.workspace,
                "--target",
                self.config.user_peer,
                "--search-query",
                "preferences current projects working style recent decisions",
                "--max-conclusions",
                "12",
                "--json",
            ]
        )
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        return str(result) if result else None
