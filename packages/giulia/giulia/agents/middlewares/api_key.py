"""Validates Bearer token via the Registry or locally (JWT) on every request."""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from giulia.agents.auth.api_keys import _OPEN_PATHS, validate_api_key
from giulia.agents.auth.google_oauth import GoogleOAuthError, verify_google_token
from giulia.agents.auth.jwt_auth import JWTValidationError, verify_jwt
from giulia.agents.core.config import config
from giulia.logging import logger


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token via the Registry or locally (JWT) on every request except open paths."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)

        internal_path = config.internal_trigger_path.strip()
        internal_secret = config.internal_trigger_secret
        if internal_path and internal_secret:
            header_secret = request.headers.get("x-internal-trigger-secret", "")
            if request.url.path == internal_path and secrets.compare_digest(
                header_secret, internal_secret
            ):
                request.state.client_name = "internal-trigger"
                return await call_next(request)

        from giulia.agents.core.constants import (
            INBOUND_DELEGATION_PATH,
            INBOUND_DELEGATION_SECRET_HEADER,
            WORKFLOW_APPROVALS_PATH,
        )
        from giulia.agents.delegation.handler import inbound_delegation_secret

        delegation_secret = inbound_delegation_secret()
        internal_paths = (
            request.url.path == INBOUND_DELEGATION_PATH
            or request.url.path == WORKFLOW_APPROVALS_PATH
            or request.url.path.startswith(f"{WORKFLOW_APPROVALS_PATH}/")
        )
        if delegation_secret and internal_paths:
            header_secret = request.headers.get(INBOUND_DELEGATION_SECRET_HEADER, "")
            if secrets.compare_digest(header_secret, delegation_secret):
                request.state.client_name = "internal-workflow"
                return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization header"},
            )

        token = auth[7:] if auth.lower().startswith("bearer ") else auth

        if token.startswith("sk-"):
            key_type = request.headers.get("x-key-type")
            status_code, client_name, detail = await validate_api_key(auth, key_type)
            if status_code != 200:
                return JSONResponse(
                    status_code=status_code,
                    content={"detail": detail},
                )
        else:
            # Try Google OAuth first, then fall back to KMS JWT.
            try:
                info = await verify_google_token(
                    token, getattr(config, "google_oauth_client_id", "")
                )
                client_name = info.get("email", "google-oauth")
            except GoogleOAuthError as google_exc:
                logger.debug("Google OAuth validation failed: %s", google_exc)
                try:
                    payload = verify_jwt(token)
                    client_name = payload.get(
                        "client_name", payload.get("sub", "oauth")
                    )
                except JWTValidationError as jwt_exc:
                    logger.warning(
                        "All token validation failed (Google: %s, JWT: %s)",
                        google_exc,
                        jwt_exc,
                    )
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Unauthorized"},
                    )

        request.state.client_name = client_name
        return await call_next(request)
