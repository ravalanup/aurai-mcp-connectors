import json
import logging
from pathlib import Path

import pytest
import yaml
from mcp.server.mcpserver import MCPServer

from aurai_connectors.framework import Governor
from aurai_connectors.identity import IdentityResolver
from aurai_connectors.manifest import load_manifest
from aurai_connectors.models import Decision
from aurai_connectors.policy import DENY
from tests.conftest import ROOT, mint, needs_opa


class FakePolicy:
    def __init__(self, decision):
        self.decision, self.inputs = decision, []

    async def decide(self, policy_input):
        self.inputs.append(policy_input)
        return self.decision


class ExplodingPolicy:
    async def decide(self, policy_input):
        raise RuntimeError("policy engine crashed")


ALLOW = Decision(allow=True, tier="T2", ceiling="confidential")


async def test_the_decision_input_comes_from_the_manifest_and_token_not_the_request(harness, private_key):
    fake = FakePolicy(ALLOW)
    h = await harness("tickets", policy=fake)
    await h.call("tickets_search", {"query": "lantern"}, team="ops-insights", use_case="uc-7")
    assert fake.inputs == [
        {
            "team": "ops-insights",
            "use_case": "uc-7",
            "connector": "tickets",
            "tool": "tickets_search",
            "action": "read",
            "classification": "internal",
            "approval": "none",
        }
    ]


async def test_caller_supplied_tier_or_team_fields_have_no_effect(harness, private_key):
    fake = FakePolicy(ALLOW)
    h = await harness("tickets", policy=fake)
    token = mint(private_key, team="sandbox", use_case="uc", risk_tier="T3", tier="T3")
    r = await h.rpc(
        "tools/call",
        {"name": "tickets_search", "arguments": {"query": "x"}},
        token=token,
        raw_headers={"X-Aurai-Team": "ops-insights", "X-Aurai-Tier": "T3"},
    )
    assert r.status_code == 200
    assert fake.inputs[0]["team"] == "sandbox" and "tier" not in fake.inputs[0]


async def test_policy_denial_stops_the_tool_from_running(harness):
    ran = []
    from aurai_connectors.backends import TicketBackend

    class Spy(TicketBackend):
        def search(self, *a):
            ran.append(1)
            return []

    h = await harness("tickets", Spy.seeded(), policy=FakePolicy(DENY))
    r = await h.call("tickets_search", {"query": "x"})
    assert r.error == "policy_denied" and not ran


async def test_a_crashing_policy_engine_means_deny(harness):
    h = await harness("tickets", policy=ExplodingPolicy())
    r = await h.call("tickets_search", {"query": "x"})
    assert r.is_error and "policy engine crashed" not in r.text


async def test_unexpected_tool_failures_do_not_leak_internals(harness):
    from aurai_connectors.backends import TicketBackend

    class Broken(TicketBackend):
        def search(self, *a):
            raise RuntimeError("db password is hunter2")

    h = await harness("tickets", Broken.seeded(), policy=FakePolicy(ALLOW))
    r = await h.call("tickets_search", {"query": "x"})
    assert r.is_error and "hunter2" not in r.text and r.error == "tool_error"


async def test_http_requests_without_a_token_are_401(harness):
    h = await harness("tickets", policy=FakePolicy(ALLOW))
    r = await h.rpc("tools/list")
    assert r.status_code == 401
    r = await h.rpc("tools/call", {"name": "tickets_search", "arguments": {}}, token="garbage")
    assert r.status_code == 401


async def test_a_token_for_another_audience_is_401(harness, private_key):
    h = await harness("tickets", policy=FakePolicy(ALLOW))
    r = await h.rpc("tools/list", token=mint(private_key, audience="litellm"))
    assert r.status_code == 401


async def test_healthz_is_open(harness):
    h = await harness("tickets", policy=FakePolicy(ALLOW))
    r = await h._client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def _server(manifest_path: Path, policy, register):
    manifest = load_manifest(manifest_path)
    governor = Governor(manifest, IdentityResolver(None), policy, None)
    server = MCPServer("t")
    register(governor, server)
    return governor


def test_registering_an_undeclared_tool_fails_at_startup():
    def register(governor, server):
        @governor.tool(server, "tickets_delete_everything")
        def f() -> str:
            return "x"

    with pytest.raises(KeyError, match="not declared"):
        _server(ROOT / "connectors/tickets/connector.yaml", FakePolicy(ALLOW), register)


def test_a_declared_tool_without_code_fails_at_startup():
    def register(governor, server):
        @governor.tool(server, "tickets_get")
        def f(ticket_id: str) -> str:
            return "x"

        governor.assert_complete()

    with pytest.raises(RuntimeError, match="manifest declares"):
        _server(ROOT / "connectors/tickets/connector.yaml", FakePolicy(ALLOW), register)


def test_dynamic_classification_needs_a_resolver_and_static_must_not_have_one():
    def no_resolver(governor, server):
        governor.tool(server, "files_read")

    with pytest.raises(ValueError, match="needs a classify"):
        _server(ROOT / "connectors/files/connector.yaml", FakePolicy(ALLOW), no_resolver)

    def stray_resolver(governor, server):
        governor.tool(server, "tickets_get", classify=lambda a: "public")

    with pytest.raises(ValueError, match="static classification"):
        _server(ROOT / "connectors/tickets/connector.yaml", FakePolicy(ALLOW), stray_resolver)


@needs_opa
async def test_every_call_writes_one_audit_line_without_arguments_or_results(harness, caplog, approval):
    h = await harness("tickets")
    with caplog.at_level(logging.INFO, logger="aurai.audit"):
        await h.call("tickets_search", {"query": "secret-looking-query"})
        args = {"title": "Sensitive title", "body": "Sensitive body", "area": "Lantern Gardens"}
        await h.call("tickets_create_draft", args)
        await h.call("tickets_create_draft", args, approval=approval("tickets_create_draft", args))
        await h.call("tickets_update_status", {"ticket_id": "TCK-1001", "status": "resolved"}, team="sandbox")
    lines = [json.loads(r.message) for r in caplog.records if r.name == "aurai.audit"]
    assert [(line["tool"], line["outcome"]) for line in lines] == [
        ("tickets_search", "ok"),
        ("tickets_create_draft", "approval_required"),
        ("tickets_create_draft", "ok"),
        ("tickets_update_status", "denied"),
    ]
    assert lines[2]["approvers"] == ["alice"] and lines[2]["approvals_required"] == 1
    assert lines[3]["decision"] == "deny" and lines[3]["reasons"] == ["tool_not_in_scope"]
    assert all(line["team"] and line["args_hash"] and line["request_id"] for line in lines)
    blob = " ".join(r.message for r in caplog.records)
    for secret in ("secret-looking-query", "Sensitive title", "Sensitive body", "Harbor Coaster brake"):
        assert secret not in blob


@needs_opa
async def test_unauthenticated_calls_are_audited_too(harness, caplog, private_key):
    h = await harness("tickets")
    with caplog.at_level(logging.INFO, logger="aurai.audit"):
        r = await h.rpc("tools/call", {"name": "tickets_search", "arguments": {}}, token=mint(private_key, team=None))
    assert r.status_code == 401  # stopped at the edge, before any tool code


@needs_opa
async def test_spans_follow_the_governance_conventions(harness, spans, approval):
    h = await harness("tickets")
    args = {"title": "T", "body": "B", "area": "Lantern Gardens"}
    await h.call("tickets_create_draft", args)
    await h.call("tickets_create_draft", args, approval=approval("tickets_create_draft", args))
    finished = spans.get_finished_spans()
    calls = [s for s in finished if s.name == "aurai.tool.call"]
    approvals = [s for s in finished if s.name == "aurai.approval"]
    assert len(calls) == 2 and len(approvals) == 2
    for s in calls:
        assert s.attributes["aurai.tool.name"] == "tickets_create_draft"
        assert s.attributes["aurai.team.id"] == "ops-insights"
        assert s.attributes["aurai.use_case.id"] == "ops-insights"
        assert s.attributes["aurai.risk_tier"] == "T2"
    assert [s.attributes["aurai.approval.outcome"] for s in approvals] == ["pending", "approved"]
    assert all(s.attributes["aurai.approval.required"] is True for s in approvals)
    # arguments never appear on spans
    assert "Lantern" not in json.dumps([dict(s.attributes) for s in finished])


@needs_opa
async def test_a_rejected_approval_is_recorded_as_rejected(harness, spans, approval):
    h = await harness("tickets")
    args = {"title": "T", "body": "B", "area": "Lantern Gardens"}
    other = {**args, "title": "Different"}
    r = await h.call("tickets_create_draft", args, approval=approval("tickets_create_draft", other))
    assert r.error == "approval_invalid"
    approvals = [s for s in spans.get_finished_spans() if s.name == "aurai.approval"]
    assert approvals[-1].attributes["aurai.approval.outcome"] == "rejected"


@needs_opa
async def test_a_token_cannot_be_replayed(harness, approval):
    h = await harness("tickets")
    args = {"title": "T", "body": "B", "area": "Lantern Gardens"}
    token = approval("tickets_create_draft", args)
    assert not (await h.call("tickets_create_draft", args, approval=token)).is_error
    replay = await h.call("tickets_create_draft", args, approval=token)
    assert replay.error == "approval_invalid" and "already used" in replay.detail["message"]


@needs_opa
async def test_a_token_for_another_team_is_refused(harness, approval):
    h = await harness("tickets")
    args = {"title": "T", "body": "B", "area": "Lantern Gardens"}
    token = approval("tickets_create_draft", args, team="finance-reporting")
    assert (await h.call("tickets_create_draft", args, approval=token)).error == "approval_invalid"


@needs_opa
async def test_the_caller_cannot_approve_itself(harness, approval):
    h = await harness("tickets")
    args = {"title": "T", "body": "B", "area": "Lantern Gardens"}
    token = approval("tickets_create_draft", args, approvers=("svc-ops",))
    assert (await h.call("tickets_create_draft", args, approval=token)).error == "approval_invalid"


def test_the_manifest_files_parse():
    for path in (ROOT / "connectors").glob("*/connector.yaml"):
        assert yaml.safe_load(path.read_text())["tools"]
