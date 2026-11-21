"""The governed tool wrapper. Every tool call, on every connector, goes through Governor.run in this order:

  1. identify the caller (verified token; the stdio dev identity only when explicitly enabled)
  2. classify the data the call involves (static in the manifest, or resolved from the arguments)
  3. ask policy; a denial stops here
  4. if policy requires approval, verify the signed single-use approval token bound to this call
  5. run the tool, and audit and trace the outcome

Tool code never sees any of this and cannot skip it: tools are registered only through Governor.tool."""

from __future__ import annotations

import contextvars
import functools
import inspect
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from opentelemetry import trace

from . import audit, tracing
from .approvals import HEADER as APPROVAL_HEADER
from .approvals import ApprovalVerifier, args_hash
from .identity import IdentityResolver, header
from .manifest import Manifest
from .models import (
    ApprovalInvalid,
    ApprovalRequired,
    AuthError,
    BadArguments,
    Caller,
    Decision,
    PolicyDenied,
    ToolError,
    ToolSpec,
    rank,
)
from .policy import PolicyClient

Classifier = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class CallState:
    """What the tool body may learn about the decision that let it run."""

    caller: Caller
    decision: Decision
    approvers: tuple[str, ...]


_state: contextvars.ContextVar[CallState] = contextvars.ContextVar("aurai_call_state")


def current() -> CallState:
    return _state.get()


def _error_text(error: ToolError, **extra: Any) -> str:
    return json.dumps({"error": error.code, "message": str(error), **extra}, sort_keys=True)


class Governor:
    def __init__(
        self,
        manifest: Manifest,
        identity: IdentityResolver,
        policy: PolicyClient,
        approvals: ApprovalVerifier | None,
        tracer: trace.Tracer | None = None,
    ) -> None:
        self.manifest = manifest
        self._identity = identity
        self._policy = policy
        self._approvals = approvals
        self._tracer = tracer or trace.get_tracer("aurai.connectors")
        self._registered: set[str] = set()

    def tool(self, server: MCPServer, name: str, classify: Classifier | None = None) -> Callable[..., Any]:
        """Decorator: register `fn` as the MCP tool `name`, governed. The name must be declared in the manifest."""
        spec = self.manifest.tools.get(name)
        if spec is None:
            raise KeyError(f"{name!r} is not declared in connectors/{self.manifest.name}/connector.yaml")
        if spec.dynamic and classify is None:
            raise ValueError(f"{name!r} declares dynamic classification, so it needs a classify function")
        if classify is not None and not spec.dynamic:
            raise ValueError(f"{name!r} has a static classification; remove the classify function")

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            governor = self

            @functools.wraps(fn)
            async def wrapper(*args: Any, ctx: Context, **kwargs: Any) -> Any:
                return await governor.run(spec, fn, kwargs, classify, ctx)

            signature = inspect.signature(fn)
            ctx_param = inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)
            wrapper.__signature__ = signature.replace(parameters=[*signature.parameters.values(), ctx_param])  # type: ignore[attr-defined]
            wrapper.__annotations__ = {**getattr(fn, "__annotations__", {}), "ctx": Context}
            server.add_tool(wrapper, name=name, description=spec.description)
            self._registered.add(name)
            return fn

        return decorate

    def assert_complete(self) -> None:
        """Startup check: the tools the code registered are exactly the tools the manifest declares."""
        declared = set(self.manifest.tools)
        if self._registered != declared:
            raise RuntimeError(
                f"connector {self.manifest.name!r}: registered {sorted(self._registered)} "
                f"but the manifest declares {sorted(declared)}"
            )

    async def run(
        self,
        spec: ToolSpec,
        fn: Callable[..., Any],
        arguments: dict[str, Any],
        classify: Classifier | None,
        ctx: Context,
    ) -> Any:
        started = time.monotonic()
        request_id = uuid.uuid4().hex[:16]
        headers = getattr(ctx, "headers", None)
        fields: dict[str, Any] = {
            "request_id": request_id,
            "connector": spec.connector,
            "tool": spec.name,
            "action": spec.action,
            "args_hash": args_hash(arguments),
        }
        with self._tracer.start_as_current_span(tracing.SPAN_TOOL_CALL) as span:
            span.set_attribute(tracing.ATTR_TOOL, spec.name)
            span.set_attribute(tracing.ATTR_CONNECTOR, spec.connector)
            outcome, decision, approvers, result_bytes = "error", None, (), None
            try:
                caller = self._identity.resolve(headers)
                fields.update(team=caller.team_id, use_case=caller.use_case_id, subject=caller.subject)
                span.set_attribute(tracing.ATTR_TEAM, caller.team_id)
                span.set_attribute(tracing.ATTR_USE_CASE, caller.use_case_id)

                classification = self._classify(spec, classify, arguments)
                fields["classification"] = classification
                decision = await self._policy.decide(
                    {
                        "team": caller.team_id,
                        "use_case": caller.use_case_id,
                        "connector": spec.connector,
                        "tool": spec.name,
                        "action": spec.action,
                        "classification": classification,
                        "approval": spec.approval,
                    }
                )
                fields.update(
                    tier=decision.tier,
                    decision="allow" if decision.allow else "deny",
                    reasons=list(decision.reasons),
                    approvals_required=decision.approvals_required,
                )
                span.set_attribute(tracing.ATTR_TIER, decision.tier)
                span.set_attribute(tracing.ATTR_DECISION, "allow" if decision.allow else "deny")
                if not decision.allow:
                    outcome = "denied"
                    raise PolicyDenied("this call is not allowed for your team")

                if decision.approvals_required:
                    approvers = tuple(self._check_approval(spec, arguments, caller, decision, headers, fields))
                    fields["approvers"] = list(approvers)

                token = _state.set(CallState(caller, decision, approvers))
                try:
                    result = fn(**arguments)
                    if inspect.isawaitable(result):
                        result = await result
                finally:
                    _state.reset(token)
                outcome = "ok"
                result_bytes = len(json.dumps(result, default=str))
                return result
            except ApprovalRequired as exc:
                outcome = "approval_required"
                raise ToolError(
                    _error_text(
                        exc,
                        approvals_required=fields.get("approvals_required"),
                        args_hash=fields["args_hash"],
                        tool=spec.name,
                    )
                ) from None
            except ToolError as exc:
                if outcome == "error":
                    outcome = (
                        "approval_rejected"
                        if isinstance(exc, ApprovalInvalid)
                        else "unauthenticated"
                        if isinstance(exc, AuthError)
                        else "rejected"
                    )
                raise ToolError(_error_text(exc)) from None
            except Exception:
                outcome = "error"
                raise ToolError(_error_text(ToolError("the tool failed; see the connector log"))) from None
            finally:
                span.set_attribute("aurai.tool.outcome", outcome)
                audit.emit(
                    outcome=outcome,
                    result_bytes=result_bytes,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                    decision=fields.pop("decision", "deny" if decision is None else "allow"),
                    **fields,
                )

    @staticmethod
    def _classify(spec: ToolSpec, classify: Classifier | None, arguments: dict[str, Any]) -> str:
        if not spec.dynamic:
            return spec.classification
        try:
            value = classify(arguments) if classify else "restricted"
        except Exception:  # a lookup that fails is treated as the most sensitive data, never as the least
            return "restricted"
        try:
            rank(value)
        except ValueError:
            return "restricted"
        return value

    def _check_approval(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        caller: Caller,
        decision: Decision,
        headers: Any,
        fields: dict[str, Any],
    ) -> list[str]:
        with self._tracer.start_as_current_span(tracing.SPAN_APPROVAL) as span:
            span.set_attribute(tracing.ATTR_APPROVAL_REQUIRED, True)
            token = header(headers, APPROVAL_HEADER)
            if not token:
                span.set_attribute(tracing.ATTR_APPROVAL_OUTCOME, "pending")
                raise ApprovalRequired(
                    f"{decision.approvals_required} approval(s) required; "
                    f"present the signed approval in {APPROVAL_HEADER}"
                )
            if self._approvals is None:
                span.set_attribute(tracing.ATTR_APPROVAL_OUTCOME, "rejected")
                raise ApprovalInvalid("this server cannot verify approvals")
            try:
                approvers = self._approvals.verify(
                    token,
                    tool=spec.name,
                    arguments=arguments,
                    caller=caller,
                    approvals_required=decision.approvals_required,
                )
            except ApprovalInvalid:
                span.set_attribute(tracing.ATTR_APPROVAL_OUTCOME, "rejected")
                raise
            span.set_attribute(tracing.ATTR_APPROVAL_OUTCOME, "approved")
            return approvers


def require(condition: bool, message: str) -> None:
    """For tool bodies: a refusal that the caller sees, instead of an internal error."""
    if not condition:
        raise BadArguments(message)
