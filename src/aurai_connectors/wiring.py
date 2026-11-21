"""Builds a connector server with its governor from settings. One server per connector, so each deploys, scales and is
reviewed on its own."""

from __future__ import annotations

import importlib
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from opentelemetry import trace
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .approvals import ApprovalVerifier, MemoryUsedTokens, RedisUsedTokens, UsedTokens
from .framework import Governor
from .identity import IdentityResolver, TokenVerifier, bearer_token
from .manifest import Manifest, load_all
from .models import AuthError
from .policy import HttpPolicy, OpaCliPolicy, PolicyClient
from .settings import Settings

MODULES = {
    "tickets": "aurai_connectors.connectors.tickets",
    "ops-data": "aurai_connectors.connectors.ops_data",
    "messaging": "aurai_connectors.connectors.messaging",
    "files": "aurai_connectors.connectors.files",
}


def manifests(settings: Settings) -> dict[str, Manifest]:
    return load_all(settings.connectors_dir)


def build_policy(settings: Settings) -> PolicyClient:
    if settings.opa_url:
        return HttpPolicy(settings.opa_url)
    return OpaCliPolicy(settings.policy_dir)  # development only; the chart always sets AURAI_OPA_URL


def build_used_tokens(settings: Settings) -> UsedTokens:
    if settings.redis_url:
        import redis  # optional dependency: pip install "aurai-mcp-connectors[redis]"

        return RedisUsedTokens(redis.Redis.from_url(settings.redis_url))
    return MemoryUsedTokens()


def build_server(
    name: str,
    settings: Settings,
    *,
    policy: PolicyClient | None = None,
    identity: IdentityResolver | None = None,
    approvals: ApprovalVerifier | None = None,
    tracer: trace.Tracer | None = None,
    backend: Any = None,
) -> MCPServer:
    if name not in MODULES:
        raise KeyError(f"unknown connector {name!r}; choose from {sorted(MODULES)}")
    manifest = manifests(settings)[name]
    if identity is None:
        verifier = TokenVerifier(settings.issuer, settings.audience, jwks_url=settings.jwks_url)
        identity = IdentityResolver(verifier, IdentityResolver.dev_caller_from_env())
    if approvals is None and settings.approval_signing_key:
        approvals = ApprovalVerifier(settings.approval_signing_key, build_used_tokens(settings))
    governor = Governor(manifest, identity, policy or build_policy(settings), approvals, tracer)
    module = importlib.import_module(MODULES[name])
    return module.build(governor, backend) if backend is not None else module.build(governor)


class GuardedApp:
    """Wraps the MCP HTTP app. /healthz is open for probes. Everything else needs a valid bearer token, so even
    tools/list is closed to the unauthenticated; the governor verifies the token again on each tool call."""

    def __init__(self, app: ASGIApp, verifier: TokenVerifier | None) -> None:
        self._app = app
        self._verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope["path"] == "/healthz":
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        try:
            token = bearer_token(headers)
            if not token or not self._verifier:
                raise AuthError("missing or unverifiable bearer token")
            self._verifier.verify(token)
        except AuthError as exc:
            body = {"error": exc.code, "message": str(exc)}
            await JSONResponse(body, status_code=401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            return
        await self._app(scope, receive, send)


def http_app(server: MCPServer, settings: Settings, verifier: TokenVerifier | None = None) -> ASGIApp:
    verifier = verifier or TokenVerifier(settings.issuer, settings.audience, jwks_url=settings.jwks_url)
    inner = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
    return GuardedApp(inner, verifier)


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
