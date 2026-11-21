import json
import subprocess
import sys

import pytest
from mcp.client import Client

from aurai_connectors.cli import main
from aurai_connectors.identity import IdentityResolver
from aurai_connectors.wiring import build_server
from tests.conftest import ROOT, SECRET, needs_opa


@needs_opa
async def test_stdio_style_calls_use_the_dev_identity_and_still_hit_policy(settings, opa_policy, spans):
    caller = IdentityResolver.dev_caller_from_env(
        {"AURAI_ALLOW_DEV_IDENTITY": "1", "AURAI_DEV_CALLER": "ops-insights:local-dev"}
    )
    server = build_server(
        "ops-data", settings, policy=opa_policy, identity=IdentityResolver(None, caller), tracer=spans.tracer
    )
    async with Client(server) as client:
        ok = await client.call_tool("ops_downtime_summary", {"area": "Harbor Coaster", "days": 2})
        assert not ok.is_error


@needs_opa
async def test_dev_identity_for_a_team_without_scope_is_denied(settings, opa_policy, spans):
    caller = IdentityResolver.dev_caller_from_env({"AURAI_ALLOW_DEV_IDENTITY": "1", "AURAI_DEV_CALLER": "sandbox:x"})
    server = build_server(
        "ops-data", settings, policy=opa_policy, identity=IdentityResolver(None, caller), tracer=spans.tracer
    )
    async with Client(server) as client:
        result = await client.call_tool("ops_downtime_summary", {"area": "Harbor Coaster"})
        assert result.is_error and "policy_denied" in result.content[0].text


async def test_stdio_without_dev_identity_refuses_every_call(settings, spans):
    class Allow:
        async def decide(self, _input):
            raise AssertionError("policy must not be reached without an identity")

    server = build_server("ops-data", settings, policy=Allow(), identity=IdentityResolver(None), tracer=spans.tracer)
    async with Client(server) as client:
        result = await client.call_tool("ops_downtime_summary", {"area": "Harbor Coaster"})
        assert result.is_error and "unauthenticated" in result.content[0].text


def test_check_command_passes_on_the_shipped_repo(monkeypatch, capsys):
    monkeypatch.setenv("AURAI_CONNECTORS_DIR", str(ROOT / "connectors"))
    monkeypatch.setenv("AURAI_POLICY_DIR", str(ROOT / "policy"))
    assert main(["check"]) == 0
    assert "consistent" in capsys.readouterr().out


def test_check_command_fails_when_a_review_is_missing(monkeypatch, tmp_path, capsys):
    import shutil

    shutil.copytree(ROOT / "connectors", tmp_path / "connectors")
    (tmp_path / "connectors" / "files" / "review.yaml").unlink()
    monkeypatch.setenv("AURAI_CONNECTORS_DIR", str(tmp_path / "connectors"))
    monkeypatch.setenv("AURAI_POLICY_DIR", str(ROOT / "policy"))
    assert main(["check"]) == 1
    assert "files: no review.yaml" in capsys.readouterr().err


def test_approve_command_mints_a_token_for_one_call(monkeypatch, capsys):
    import jwt

    monkeypatch.setenv("AURAI_APPROVAL_SIGNING_KEY", SECRET)
    code = main(
        [
            "approve",
            "--tool",
            "messages_send",
            "--arguments",
            '{"draft_id": "DRF-1"}',
            "--team",
            "ops-insights",
            "--use-case",
            "uc",
            "--approver",
            "alice",
            "--approver",
            "bob",
        ]
    )
    assert code == 0
    claims = jwt.decode(capsys.readouterr().out.strip(), SECRET, algorithms=["HS256"])
    assert claims["tool"] == "messages_send" and claims["approvers"] == ["alice", "bob"]


def test_approve_command_refuses_a_weak_key(monkeypatch):
    monkeypatch.setenv("AURAI_APPROVAL_SIGNING_KEY", "short")
    assert (
        main(["approve", "--tool", "t", "--arguments", "{}", "--team", "a", "--use-case", "b", "--approver", "x"]) == 2
    )


def test_the_module_runs_as_a_command():
    done = subprocess.run([sys.executable, "-m", "aurai_connectors.cli", "--help"], capture_output=True, text=True)
    assert done.returncode == 0 and "serve" in done.stdout


def test_all_connectors_build_with_the_real_wiring(settings):
    class Deny:
        async def decide(self, _input):
            raise AssertionError

    for name in ("tickets", "ops-data", "messaging", "files"):
        assert build_server(name, settings, policy=Deny(), identity=IdentityResolver(None)).name.startswith("aurai-")
    with pytest.raises(KeyError):
        build_server("nope", settings)


def test_build_requires_a_policy_source(settings, monkeypatch):
    """With neither AURAI_OPA_URL nor an opa binary, startup fails rather than running ungoverned."""
    from aurai_connectors.wiring import build_policy

    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError):
        build_policy(settings)


@needs_opa
def test_json_roundtrip_of_a_policy_input_matches_what_rego_expects(settings):
    done = subprocess.run(
        [
            "opa",
            "eval",
            "--format",
            "json",
            "--data",
            str(ROOT / "policy" / "aurai"),
            "--data",
            str(ROOT / "policy" / "teams.yaml"),
            "--stdin-input",
            "data.aurai.tools.decision",
        ],
        input=json.dumps(
            {
                "team": "ops-insights",
                "connector": "tickets",
                "tool": "tickets_get",
                "action": "read",
                "classification": "internal",
                "approval": "none",
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(done.stdout)["result"][0]["expressions"][0]["value"]
    assert value["allow"] is True and value["tier"] == "T2"
