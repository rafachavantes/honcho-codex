from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import state
from .config import HonchoCodexConfig


_SOURCE_META = {"source": "honcho-codex"}


class HonchoError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HonchoClient:
    """In-process Honcho v3 REST client. Drop-in for HonchoCli on the hot path."""

    def __init__(self, config: HonchoCodexConfig, timeout: float = 8.0):
        if not config.api_key:
            raise HonchoError("Honcho is not configured (missing api_key)")
        self.config = config
        self._base = config.base_url.rstrip("/")
        self._timeout = timeout

    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        url = self._base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.config.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise HonchoError(f"HTTP {exc.code}: {detail[:500]}", status=exc.code)
        except URLError as exc:
            raise HonchoError(f"request failed: {exc.reason}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.decode("utf-8", "replace")

    def _ws_path(self, *parts: str) -> str:
        ws = quote(self.config.workspace, safe="")
        segs = "/".join(quote(p, safe="") for p in parts)
        return f"/v3/workspaces/{ws}" + (f"/{segs}" if segs else "")

    # --- get-or-create (cached) ---------------------------------------------

    def ensure_workspace(self) -> None:
        if state.is_ensured("workspace", self.config.workspace):
            return
        self._request("POST", "/v3/workspaces", {"id": self.config.workspace, "metadata": _SOURCE_META})
        state.mark_ensured("workspace", self.config.workspace)

    def ensure_peer(self, peer_id: str) -> None:
        key = f"{self.config.workspace}:{peer_id}"
        if state.is_ensured("peer", key):
            return
        self.ensure_workspace()
        self._request("POST", self._ws_path("peers"), {"id": peer_id, "metadata": _SOURCE_META})
        state.mark_ensured("peer", key)

    def ensure_session(self, session_name: str) -> None:
        key = f"{self.config.workspace}:{session_name}"
        if state.is_ensured("session", key):
            return
        self.ensure_workspace()
        self.ensure_peer(self.config.user_peer)
        self.ensure_peer(self.config.assistant_peer)
        self._request("POST", self._ws_path("sessions"), {"id": session_name, "metadata": _SOURCE_META})
        self._request(
            "POST",
            self._ws_path("sessions", session_name, "peers"),
            {self.config.user_peer: {}, self.config.assistant_peer: {}},
        )
        state.mark_ensured("session", key)

    # --- writes -------------------------------------------------------------

    def add_message(
        self,
        session_name: str,
        peer_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        self.ensure_session(session_name)
        path = self._ws_path("sessions", session_name, "messages")
        body = {"messages": [{"content": content, "peer_id": peer_id, "metadata": metadata}]}
        try:
            self._request("POST", path, body)
        except HonchoError as exc:
            if exc.status != 404:
                raise
            # Session/workspace was deleted server-side though still cached as ensured.
            # Evict the stale ensure key, recreate, and retry once so the write self-heals
            # instead of staying stuck in the queue for the full TTL.
            state.clear_ensured("session", f"{self.config.workspace}:{session_name}")
            self.ensure_session(session_name)
            self._request("POST", path, body)

    # --- reads --------------------------------------------------------------

    def session_context(self, session_name: str, tokens: int) -> str | None:
        self.ensure_session(session_name)
        query = urlencode({"summary": "true", "tokens": tokens})
        result = self._request(
            "GET", self._ws_path("sessions", session_name, "context") + f"?{query}"
        )
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        return str(result) if result else None

    def peer_card(self) -> list[str] | None:
        self.ensure_peer(self.config.user_peer)
        result = self._request("GET", self._ws_path("peers", self.config.user_peer, "card"))
        if isinstance(result, dict):
            card = result.get("card") or result.get("peer_card")
            if isinstance(card, list):
                return [str(item) for item in card]
        return None

    def doctor(self) -> dict[str, Any]:
        # Uncached connectivity probe — always hits the network (idempotent get-or-create).
        self._request("POST", "/v3/workspaces", {"id": self.config.workspace, "metadata": _SOURCE_META})
        state.mark_ensured("workspace", self.config.workspace)
        return {"ok": True, "workspace": self.config.workspace, "base_url": self._base}
