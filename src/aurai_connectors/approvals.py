"""Approval tokens. A write that policy says needs human approval runs only with a token that names exactly this
call. An approval service (the agent runtime, in the platform) issues the token after people approve; the connector
only verifies it.

The token is HS256, signed with a secret shared between that service and the connectors, and carries:
  tool, args_hash  the tool and the SHA-256 of its canonical-JSON arguments, so the approval covers this call only
  team, use_case   the caller it was granted to
  approvers        the distinct people who approved (T2 write: one, T3 write: two); the caller cannot approve itself
  exp, jti         a short expiry (15 minutes at most) and a single-use id
It travels in the X-Aurai-Approval header, not as a tool argument, so the model cannot write one."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

import jwt

from .models import ApprovalInvalid, Caller

HEADER = "X-Aurai-Approval"
MAX_LIFETIME_SECONDS = 900
ALGORITHM = "HS256"


def args_hash(arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class UsedTokens(Protocol):
    def claim(self, jti: str, ttl_seconds: int) -> bool:
        """Mark the id used. False if it already was."""


class MemoryUsedTokens:
    """Single replica only. Several replicas need RedisUsedTokens, or a token can be used once per replica."""

    def __init__(self, clock: Any = time.time) -> None:
        self._seen: dict[str, float] = {}
        self._clock = clock

    def claim(self, jti: str, ttl_seconds: int) -> bool:
        now = self._clock()
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if jti in self._seen:
            return False
        self._seen[jti] = now + ttl_seconds
        return True


class RedisUsedTokens:
    def __init__(self, client: Any, prefix: str = "aurai:approval:") -> None:
        self._client = client
        self._prefix = prefix

    def claim(self, jti: str, ttl_seconds: int) -> bool:
        return bool(self._client.set(self._prefix + jti, "1", nx=True, ex=max(ttl_seconds, 1)))


def issue_approval_token(
    secret: str,
    *,
    tool: str,
    arguments: Mapping[str, Any],
    team: str,
    use_case: str,
    approvers: list[str],
    lifetime_seconds: int = 600,
    now: float | None = None,
) -> str:
    """For the approval service, and for the dev CLI that stands in for it."""
    issued = int(now if now is not None else time.time())
    claims = {
        "tool": tool,
        "args_hash": args_hash(arguments),
        "team": team,
        "use_case": use_case,
        "approvers": sorted(set(approvers)),
        "iat": issued,
        "exp": issued + min(lifetime_seconds, MAX_LIFETIME_SECONDS),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


class ApprovalVerifier:
    def __init__(self, secret: str, used: UsedTokens, clock: Any = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("the approval signing key must be at least 32 characters")
        self._secret = secret
        self._used = used
        self._clock = clock

    def verify(
        self, token: str, *, tool: str, arguments: Mapping[str, Any], caller: Caller, approvals_required: int
    ) -> list[str]:
        """Return the approvers, or raise ApprovalInvalid. The token is consumed only once every check has passed."""
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                options={"require": ["exp", "iat", "jti"], "verify_exp": False},
            )
        except jwt.PyJWTError as exc:
            raise ApprovalInvalid("approval token is not valid") from exc
        now = self._clock()
        exp, iat = claims.get("exp"), claims.get("iat")
        if not isinstance(exp, int | float) or not isinstance(iat, int | float) or exp <= now:
            raise ApprovalInvalid("approval token has expired")
        if exp - iat > MAX_LIFETIME_SECONDS:
            raise ApprovalInvalid("approval token lives longer than allowed")
        if claims.get("tool") != tool:
            raise ApprovalInvalid("approval was granted for a different tool")
        if claims.get("team") != caller.team_id or claims.get("use_case") != caller.use_case_id:
            raise ApprovalInvalid("approval was granted to a different caller")
        if claims.get("args_hash") != args_hash(arguments):
            raise ApprovalInvalid("approval was granted for different arguments")
        approvers = claims.get("approvers")
        if not isinstance(approvers, list) or not all(isinstance(a, str) and a for a in approvers):
            raise ApprovalInvalid("approval token names no approvers")
        distinct = set(approvers)
        if caller.subject in distinct:
            raise ApprovalInvalid("a caller cannot approve its own action")
        if len(distinct) < approvals_required:
            raise ApprovalInvalid(
                f"{approvals_required} distinct approvers are required; the token has {len(distinct)}"
            )
        if not self._used.claim(str(claims["jti"]), int(exp - now) + 1):
            raise ApprovalInvalid("approval token was already used")
        return sorted(distinct)
