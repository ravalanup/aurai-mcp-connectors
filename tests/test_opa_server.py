"""The deployed shape: OPA running as a server over a flat folder holding the Rego and teams.yaml (as the chart's
ConfigMap mounts them), asked over HTTP by the connector's own client."""

import shutil
import socket
import subprocess
import time

import pytest

from aurai_connectors.policy import HttpPolicy
from tests.conftest import ROOT, needs_opa

pytestmark = needs_opa


@pytest.fixture
def opa_server(tmp_path):
    folder = tmp_path / "policy"
    folder.mkdir()
    shutil.copy(ROOT / "policy/aurai/tools.rego", folder / "tools.rego")
    shutil.copy(ROOT / "policy/teams.yaml", folder / "teams.yaml")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        ["opa", "run", "--server", f"--addr=127.0.0.1:{port}", str(folder)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=5)


async def test_the_http_client_gets_real_decisions_from_an_opa_server(opa_server):
    policy = HttpPolicy(opa_server)

    def ask(team, tool, action, classification, approval, connector):
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

    allowed = await ask("ops-insights", "tickets_create_draft", "write", "internal", "policy", "tickets")
    assert allowed.allow and allowed.approvals_required == 1 and allowed.tier == "T2"
    two = await ask("guest-assistant", "tickets_create_draft", "write", "internal", "policy", "tickets")
    assert two.allow and two.approvals_required == 2 and two.tier == "T3"
    denied = await ask("sandbox", "tickets_create_draft", "write", "internal", "policy", "tickets")
    assert not denied.allow and "tool_not_in_scope" in denied.reasons


async def test_a_server_that_went_away_means_deny(opa_server):
    policy = HttpPolicy("http://127.0.0.1:9", timeout_seconds=0.5)
    d = await policy.decide({"team": "ops-insights"})
    assert not d.allow and d.reasons == ("policy_unavailable",)
