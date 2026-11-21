from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aurai_connectors.approvals import ApprovalVerifier, MemoryUsedTokens, issue_approval_token
from aurai_connectors.identity import IdentityResolver, TokenVerifier
from aurai_connectors.policy import OpaCliPolicy
from aurai_connectors.settings import Settings
from aurai_connectors.wiring import GuardedApp, build_server

ROOT = Path(__file__).resolve().parent.parent
ISSUER = "http://keycloak.test/realms/aurai"
AUDIENCE = "aurai-connectors"
SECRET = "test-approval-signing-key-0123456789abcdef"

needs_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="the opa binary is not installed")


@pytest.fixture(scope="session")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint(private_key, team="ops-insights", use_case="ops-insights", sub="svc-ops", audience=AUDIENCE, ttl=300, **extra):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": audience, "sub": sub, "iat": now, "exp": now + ttl}
    if team is not None:
        claims["team_id"] = team
    if use_case is not None:
        claims["use_case_id"] = use_case
    claims.update(extra)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def settings():
    return Settings.from_env(
        {"AURAI_CONNECTORS_DIR": str(ROOT / "connectors"), "AURAI_POLICY_DIR": str(ROOT / "policy")}
    )


@pytest.fixture
def verifier(private_key):
    return TokenVerifier(ISSUER, AUDIENCE, key_resolver=lambda _t: private_key.public_key())


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    exporter.tracer = provider.get_tracer("test")
    return exporter


@pytest.fixture
def used_tokens():
    return MemoryUsedTokens()


class Harness:
    """A connector served over its real ASGI app, called with real JSON-RPC requests."""

    def __init__(self, name, settings, verifier, private_key, spans, used, policy, backend=None):
        self.private_key = private_key
        identity = IdentityResolver(verifier)
        approvals = ApprovalVerifier(SECRET, used)
        self.server = build_server(
            name, settings, policy=policy, identity=identity, approvals=approvals, tracer=spans.tracer, backend=backend
        )
        inner = self.server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
        self.inner = inner
        self.app = GuardedApp(inner, verifier)

    async def start(self):
        """The MCP session manager's task group must be entered and exited by the same task, so one task owns it."""
        ready, self._stop = asyncio.Event(), asyncio.Event()

        async def own_lifespan():
            async with self.inner.router.lifespan_context(self.inner):
                ready.set()
                await self._stop.wait()

        self._task = asyncio.create_task(own_lifespan())
        await ready.wait()
        transport = httpx.ASGITransport(app=self.app)
        self._client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")

    async def stop(self):
        await self._client.aclose()
        self._stop.set()
        await self._task

    async def rpc(self, method, params=None, *, token=None, approval=None, raw_headers=None):
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if approval:
            headers["X-Aurai-Approval"] = approval
        headers.update(raw_headers or {})
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return await self._client.post("/mcp", headers=headers, content=json.dumps(body))

    async def call(
        self, tool, arguments, *, team="ops-insights", use_case="ops-insights", sub="svc-ops", approval=None, token=None
    ):
        token = token or mint(self.private_key, team=team, use_case=use_case, sub=sub)
        response = await self.rpc("tools/call", {"name": tool, "arguments": arguments}, token=token, approval=approval)
        assert response.status_code == 200, response.text
        return Result(response.json()["result"])


class Result:
    def __init__(self, raw):
        self.raw = raw
        self.is_error = bool(raw.get("isError"))
        self.text = "".join(c.get("text", "") for c in raw.get("content", []))

    @property
    def data(self):
        structured = self.raw.get("structuredContent")
        if structured is not None:
            return structured.get("result", structured) if set(structured) == {"result"} else structured
        return json.loads(self.text)

    @property
    def detail(self):
        return json.loads(self.text[self.text.index("{") :])

    @property
    def error(self):
        return self.detail["error"]


@pytest.fixture
def opa_policy(settings):
    if shutil.which("opa") is None:
        pytest.skip("the opa binary is not installed")
    return OpaCliPolicy(settings.policy_dir)


@pytest.fixture
async def harness(settings, verifier, private_key, spans, used_tokens, opa_policy):
    made = []

    async def make(name, backend=None, policy=None):
        h = Harness(name, settings, verifier, private_key, spans, used_tokens, policy or opa_policy, backend)
        await h.start()
        made.append(h)
        return h

    yield make
    for h in made:
        await h.stop()


@pytest.fixture
def approval(private_key):
    def make(tool, arguments, team="ops-insights", use_case="ops-insights", approvers=("alice",), **kw):
        return issue_approval_token(
            SECRET, tool=tool, arguments=arguments, team=team, use_case=use_case, approvers=list(approvers), **kw
        )

    return make
