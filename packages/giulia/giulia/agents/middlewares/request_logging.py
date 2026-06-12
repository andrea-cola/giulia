"""ASGI middleware that logs the body of every incoming A2A message request."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from giulia.logging import logger


class RequestLoggingMiddleware:
    """ASGI middleware that logs the body of every incoming A2A message request."""

    _LOGGED_PATHS = frozenset({"/", ""})

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "") not in self._LOGGED_PATHS:
            await self.app(scope, receive, send)
            return

        body_chunks: list[bytes] = []

        async def _drain() -> None:
            while True:
                message = await receive()
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break

        await _drain()
        body = b"".join(body_chunks)

        try:
            payload = json.loads(body) if body else {}
            logger.info("Incoming A2A message: {}", json.dumps(payload, default=str))
        except Exception:
            logger.info(
                "Incoming A2A request body ({} bytes): {}", len(body), body[:2048]
            )

        async def _replayed_receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, _replayed_receive, send)
