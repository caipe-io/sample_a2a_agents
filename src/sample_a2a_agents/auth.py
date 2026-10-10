"""Keycloak JWT verification for the directly reachable Netutils sample."""

import asyncio
import os

import jwt
from jwt import PyJWKClient
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class JwtAuthMiddleware:
    """Keep only readiness public; verify every discovery and A2A request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.issuer = os.environ.get("NETUTILS_OIDC_ISSUER", "")
        self.audience = os.environ.get("NETUTILS_OIDC_AUDIENCE", "")
        jwks_url = os.environ.get("NETUTILS_JWKS_URL", "")
        self.jwks = PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=10) if jwks_url else None

    async def _verify(self, token: str) -> None:
        if not self.issuer or not self.audience or self.jwks is None:
            raise RuntimeError("Netutils Keycloak JWT verification is not configured")
        key = await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)
        jwt.decode(token, key.key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                   options={"require": ["exp", "sub", "iss", "aud"]})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
            await JSONResponse({"detail": "Bearer token required"}, status_code=401)(scope, receive, send)
            return
        try:
            await self._verify(authorization[7:].strip())
        except jwt.PyJWTError:
            await JSONResponse({"detail": "Invalid bearer token"}, status_code=401)(scope, receive, send)
            return
        except (RuntimeError, OSError):
            await JSONResponse({"detail": "JWT verification unavailable"}, status_code=503)(scope, receive, send)
            return
        await self.app(scope, receive, send)
