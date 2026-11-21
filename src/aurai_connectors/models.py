"""Shared types."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp.server.mcpserver.exceptions import ToolError as SdkToolError

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
ACTIONS = ("read", "write")
APPROVAL_MODES = ("none", "policy", "always")


def rank(classification: str) -> int:
    return CLASSIFICATIONS.index(classification)


@dataclass(frozen=True)
class Caller:
    """Who is calling. Built only from a verified service token (or the explicit dev identity on stdio)."""

    team_id: str
    use_case_id: str
    subject: str


@dataclass(frozen=True)
class ToolSpec:
    """What a connector declares about one tool. The policy decision is made from this, never from the request."""

    name: str
    connector: str
    action: str
    classification: str  # one of CLASSIFICATIONS, or "dynamic" when the tool resolves it from its arguments
    approval: str
    description: str

    @property
    def dynamic(self) -> bool:
        return self.classification == "dynamic"


@dataclass(frozen=True)
class Decision:
    allow: bool
    approvals_required: int = 0
    tier: str = "unknown"
    ceiling: str = "public"
    reasons: tuple[str, ...] = field(default_factory=tuple)


class ToolError(SdkToolError):
    """A refusal or failure the caller should see, returned to the model as an isError result. The SDK prefixes the
    message with the tool name; the rest is a JSON object with `error`, `message` and, for approvals, the call hash."""

    code = "tool_error"


class AuthError(ToolError):
    code = "unauthenticated"


class PolicyDenied(ToolError):
    code = "policy_denied"


class ApprovalRequired(ToolError):
    code = "approval_required"


class ApprovalInvalid(ToolError):
    code = "approval_invalid"


class BadArguments(ToolError):
    code = "bad_arguments"
