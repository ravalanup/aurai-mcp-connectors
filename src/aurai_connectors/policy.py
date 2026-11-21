"""Policy decisions from Open Policy Agent. The framework builds the input from its manifest and the verified
caller, asks OPA, and fails closed: no answer, a malformed answer or an error all mean deny."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

import httpx

from .models import CLASSIFICATIONS, Decision

DECISION_PATH = "/v1/data/aurai/tools/decision"
DENY = Decision(allow=False, reasons=("policy_unavailable",))


class PolicyClient(Protocol):
    async def decide(self, policy_input: dict[str, Any]) -> Decision: ...


def parse_decision(result: Any) -> Decision:
    """Accept only a complete, well-typed answer. Anything else is a denial."""
    if not isinstance(result, dict):
        return DENY
    allow = result.get("allow")
    approvals = result.get("approvals_required")
    reasons = result.get("reasons")
    ceiling = result.get("ceiling")
    if (
        not isinstance(allow, bool)
        or not isinstance(approvals, int)
        or isinstance(approvals, bool)
        or approvals < 0
        or not isinstance(reasons, list)
        or ceiling not in CLASSIFICATIONS
    ):
        return DENY
    return Decision(
        allow=allow,
        approvals_required=approvals,
        tier=str(result.get("tier", "unknown")),
        ceiling=ceiling,
        reasons=tuple(str(r) for r in reasons),
    )


class HttpPolicy:
    """The OPA sidecar next to the connector, on localhost."""

    def __init__(self, base_url: str, timeout_seconds: float = 2.0, client: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + DECISION_PATH
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def decide(self, policy_input: dict[str, Any]) -> Decision:
        try:
            response = await self._client.post(self._url, json={"input": policy_input})
            response.raise_for_status()
            return parse_decision(response.json().get("result"))
        except (httpx.HTTPError, ValueError):
            return DENY


class OpaCliPolicy:
    """Runs `opa eval` against the policy folder. For local development and tests, where no sidecar is running."""

    def __init__(self, policy_dir: Path, opa_binary: str | None = None, timeout_seconds: float = 10.0) -> None:
        self._dir = policy_dir
        self._opa = opa_binary or shutil.which("opa")
        self._timeout = timeout_seconds
        if not self._opa:
            raise FileNotFoundError("the opa binary is not on PATH")

    def _run(self, policy_input: dict[str, Any]) -> Decision:
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv, input on stdin
                [
                    self._opa,
                    "eval",
                    "--format",
                    "json",
                    "--data",
                    str(self._dir / "aurai"),
                    "--data",
                    str(self._dir / "teams.yaml"),
                    "--stdin-input",
                    "data.aurai.tools.decision",
                ],
                input=json.dumps(policy_input),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
            value = json.loads(done.stdout)["result"][0]["expressions"][0]["value"]
        except (subprocess.SubprocessError, KeyError, IndexError, ValueError):
            return DENY
        return parse_decision(value)

    async def decide(self, policy_input: dict[str, Any]) -> Decision:
        return await asyncio.to_thread(self._run, policy_input)
