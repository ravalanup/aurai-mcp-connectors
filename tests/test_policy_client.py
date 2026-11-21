import httpx
import pytest

from aurai_connectors.policy import DENY, HttpPolicy, OpaCliPolicy, parse_decision
from tests.conftest import ROOT, needs_opa

GOOD = {"allow": True, "approvals_required": 1, "tier": "T2", "ceiling": "confidential", "reasons": []}


def test_parse_accepts_a_complete_answer():
    d = parse_decision(GOOD)
    assert d.allow and d.approvals_required == 1 and d.tier == "T2" and d.ceiling == "confidential"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "allow",
        {},
        {**GOOD, "allow": "yes"},
        {**GOOD, "approvals_required": -1},
        {**GOOD, "approvals_required": True},
        {**GOOD, "approvals_required": "1"},
        {**GOOD, "reasons": "none"},
        {**GOOD, "ceiling": "secret"},
        {k: v for k, v in GOOD.items() if k != "ceiling"},
    ],
)
def test_parse_denies_anything_incomplete(bad):
    assert parse_decision(bad) == DENY


async def test_http_policy_reads_the_opa_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), request.read()
        return httpx.Response(200, json={"result": GOOD})

    policy = HttpPolicy("http://127.0.0.1:8181", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    d = await policy.decide({"team": "x"})
    assert d.allow and seen["url"].endswith("/v1/data/aurai/tools/decision")
    assert b'"input"' in seen["body"]


@pytest.mark.parametrize(
    "response", [httpx.Response(500), httpx.Response(200, json={}), httpx.Response(200, text="no")]
)
async def test_http_policy_fails_closed(response):
    policy = HttpPolicy("http://x", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)))
    assert await policy.decide({"team": "x"}) == DENY


async def test_http_policy_fails_closed_when_opa_is_down():
    def boom(request):
        raise httpx.ConnectError("refused")

    policy = HttpPolicy("http://x", client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert await policy.decide({"team": "x"}) == DENY


@needs_opa
async def test_real_opa_decisions_for_the_shipped_teams():
    policy = OpaCliPolicy(ROOT / "policy")

    def ask(team, tool, action, classification, approval="none", connector="files"):
        return policy.decide(
            {
                "team": team,
                "connector": connector,
                "tool": tool,
                "action": action,
                "classification": classification,
                "approval": approval,
            }
        )

    assert (await ask("finance-reporting", "files_read", "read", "confidential")).allow
    write = await ask("finance-reporting", "files_write", "write", "confidential", "policy")
    assert write.allow and write.approvals_required == 1
    assert not (await ask("finance-reporting", "files_write", "write", "restricted", "policy")).allow
    assert not (await ask("guest-assistant", "files_read", "read", "internal")).allow  # no files scope
    assert not (await ask("sandbox", "tickets_create_draft", "write", "internal", "policy", "tickets")).allow
    assert not (await ask("unknown-team", "files_read", "read", "public")).allow
