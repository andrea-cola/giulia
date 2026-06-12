"""Strip a URL prefix so the inner app sees root-relative paths."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class StripPrefixMiddleware:
    """Strip a URL prefix so the inner app sees root-relative paths."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path: str = scope["path"]
            if path.startswith(self.prefix):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix) :] or "/"
                scope["root_path"] = scope.get("root_path", "") + self.prefix
        await self.app(scope, receive, send)
