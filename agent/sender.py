"""Agent → server API client (httpx async).

TLS behavior: verify is True, False, or a filesystem path string —
passed through to httpx. The bearer token is attached on every request
as long as the agent is registered.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from agent.config import AppConfig
from agent.parser import ParsedMatch


logger = logging.getLogger(__name__)


class AgentSender:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        verify = self._resolve_verify(config.server.tls_verify)
        headers: dict[str, str] = {}
        if config.agent.api_token:
            headers["Authorization"] = f"Bearer {config.agent.api_token}"
        self._client = httpx.AsyncClient(
            base_url=config.server.url,
            verify=verify,
            headers=headers,
            timeout=30.0,
        )

    @staticmethod
    def _resolve_verify(value: bool | str) -> bool | str:
        if isinstance(value, bool):
            if value is False:
                logger.warning("TLS verification DISABLED — lab/self-signed mode")
            return value
        # path string — httpx accepts str for custom CA bundle
        return value

    async def register(
        self, username: str, password: str, machine_name: str, platform: str = "windows"
    ) -> tuple[str, str]:
        resp = await self._client.post(
            "/api/v1/agent/register",
            json={
                "username": username,
                "password": password,
                "machine_name": machine_name,
                "platform": platform,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["agent_id"], data["api_token"]

    async def heartbeat(self) -> bool:
        if not self._config.agent.api_token:
            return False
        try:
            resp = await self._client.post("/api/v1/agent/heartbeat")
        except httpx.HTTPError as exc:
            logger.info("Heartbeat failed: %s", exc)
            return False
        if resp.is_success:
            logger.info("sender: heartbeat OK")
            return True
        logger.info("Heartbeat rejected: %s %s", resp.status_code, resp.text[:200])
        return False

    async def upload(self, match: ParsedMatch) -> bool:
        payload = self._build_upload_payload(match)
        try:
            resp = await self._client.post("/api/v1/agent/upload", json=payload)
        except httpx.HTTPError:
            logger.exception("Upload failed for match %s", match.mtgo_match_id)
            return False
        if resp.is_success:
            return True
        logger.warning(
            "Upload rejected for match %s: %s %s",
            match.mtgo_match_id,
            resp.status_code,
            resp.text[:200],
        )
        return False

    def _build_upload_payload(self, match: ParsedMatch) -> dict[str, Any]:
        agent_id = self._config.agent.agent_id or str(uuid.UUID(int=0))
        return {
            "agent_id": agent_id,
            "match": {
                "mtgo_match_id": match.mtgo_match_id,
                "format": match.format or "unknown",
                "match_type": "league",
                "opponent_name": match.opponent,
                "result": match.result or "draw",
                "my_wins": 0,
                "opponent_wins": 0,
            },
        }

    async def close(self) -> None:
        await self._client.aclose()
