"""The direct sample requires a signed Keycloak bearer; debug cannot bypass it."""

import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sample_a2a_agents.auth import JwtAuthMiddleware


@pytest.mark.parametrize("mutation", ["missing", "malformed", "expired", "issuer", "audience", "signature", "valid"])
async def test_netutils_requires_verified_jwt(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("NETUTILS_OIDC_ISSUER", "https://idp.example.test/realms/example")
    monkeypatch.setenv("NETUTILS_OIDC_AUDIENCE", "example-platform")
    monkeypatch.setenv("NETUTILS_JWKS_URL", "https://idp.example.test/certs")
    monkeypatch.setenv("DEBUG", "true")
    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})
    app = JwtAuthMiddleware(Starlette(routes=[Route("/", endpoint), Route("/healthz", endpoint)]))
    monkeypatch.setattr(app.jwks, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=private.public_key()))
    claims = {"sub": "test-subject", "iss": "https://idp.example.test/realms/example", "aud": "example-platform", "exp": int(time.time())+60}
    if mutation == "expired":
        claims["exp"] = int(time.time())-60
    if mutation == "issuer":
        claims["iss"] = "https://other.example.test"
    if mutation == "audience":
        claims["aud"] = "other-platform"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if mutation == "signature" else private
    token = jwt.encode(claims, key, algorithm="RS256")
    headers = {"Authorization": "Bearer invalid" if mutation == "malformed" else f"Bearer {token}"}
    if mutation == "missing":
        headers = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://example.test") as client:
        assert (await client.get("/healthz")).status_code == 200
        response = await client.get("/", headers=headers)
    assert response.status_code == (200 if mutation == "valid" else 401)


async def test_missing_keycloak_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETUTILS_JWKS_URL", raising=False)
    app = JwtAuthMiddleware(Starlette())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://example.test") as client:
        assert (await client.get("/", headers={"Authorization": "Bearer test-token"})).status_code == 503
