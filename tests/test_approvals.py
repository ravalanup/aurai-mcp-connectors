import jwt
import pytest

from aurai_connectors.approvals import (
    ALGORITHM,
    ApprovalVerifier,
    MemoryUsedTokens,
    RedisUsedTokens,
    args_hash,
    issue_approval_token,
)
from aurai_connectors.models import ApprovalInvalid, Caller
from tests.conftest import SECRET

CALLER = Caller("ops-insights", "ops-insights", "svc-ops")
ARGS = {"title": "Fix", "area": "Harbor Coaster", "body": "x"}


def token(**over):
    kw = dict(
        tool="tickets_create_draft", arguments=ARGS, team="ops-insights", use_case="ops-insights", approvers=["alice"]
    )
    kw.update(over)
    return issue_approval_token(SECRET, **kw)


def verify(tok, verifier=None, *, tool="tickets_create_draft", arguments=ARGS, caller=CALLER, required=1):
    verifier = verifier or ApprovalVerifier(SECRET, MemoryUsedTokens())
    return verifier.verify(tok, tool=tool, arguments=arguments, caller=caller, approvals_required=required)


def test_valid_token_returns_the_approvers():
    assert verify(token(approvers=["bob", "alice"]), required=2) == ["alice", "bob"]


def test_args_hash_ignores_key_order_but_not_values():
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"tool": "tickets_update_status"}, "different tool"),
        ({"arguments": {**ARGS, "title": "Other"}}, "different arguments"),
        ({"caller": Caller("finance-reporting", "ops-insights", "svc-ops")}, "different caller"),
        ({"caller": Caller("ops-insights", "other-use-case", "svc-ops")}, "different caller"),
        ({"caller": Caller("ops-insights", "ops-insights", "alice")}, "approve its own"),
        ({"required": 2}, "2 distinct approvers"),
    ],
)
def test_a_token_is_good_only_for_the_exact_call(kwargs, fragment):
    with pytest.raises(ApprovalInvalid, match=fragment):
        verify(token(), **kwargs)


def test_the_same_approver_twice_counts_once():
    with pytest.raises(ApprovalInvalid, match="2 distinct"):
        verify(token(approvers=["alice", "alice"]), required=2)


def test_token_is_single_use():
    verifier = ApprovalVerifier(SECRET, MemoryUsedTokens())
    tok = token()
    verify(tok, verifier)
    with pytest.raises(ApprovalInvalid, match="already used"):
        verify(tok, verifier)


def test_a_failed_check_does_not_burn_the_token():
    verifier = ApprovalVerifier(SECRET, MemoryUsedTokens())
    tok = token()
    with pytest.raises(ApprovalInvalid):
        verify(tok, verifier, tool="tickets_update_status")
    assert verify(tok, verifier) == ["alice"]


def test_expired_token_is_rejected():
    with pytest.raises(ApprovalInvalid, match="expired"):
        verify(token(now=1_000_000, lifetime_seconds=60))


def test_lifetime_is_capped_when_issuing_and_when_verifying():
    tok = token(lifetime_seconds=86_400)
    claims = jwt.decode(tok, SECRET, algorithms=[ALGORITHM])
    assert claims["exp"] - claims["iat"] == 900
    long_lived = jwt.encode({**claims, "exp": claims["iat"] + 7200}, SECRET, algorithm=ALGORITHM)
    with pytest.raises(ApprovalInvalid, match="longer than allowed"):
        verify(long_lived)


def test_tampered_or_foreign_tokens_are_rejected():
    claims = jwt.decode(token(), SECRET, algorithms=[ALGORITHM])
    forged = jwt.encode(claims, "x" * 40, algorithm=ALGORITHM)
    with pytest.raises(ApprovalInvalid):
        verify(forged)
    with pytest.raises(ApprovalInvalid):
        verify("not-a-token")
    unsigned = jwt.encode(claims, None, algorithm="none")
    with pytest.raises(ApprovalInvalid):
        verify(unsigned)


def test_short_signing_key_is_refused():
    with pytest.raises(ValueError):
        ApprovalVerifier("short", MemoryUsedTokens())


def test_memory_store_expires_entries():
    now = [100.0]
    store = MemoryUsedTokens(clock=lambda: now[0])
    assert store.claim("a", 10)
    assert not store.claim("a", 10)
    now[0] = 200.0
    assert store.claim("a", 10)


def test_redis_store_uses_set_nx_with_expiry():
    calls = []

    class FakeRedis:
        def set(self, key, value, nx, ex):
            calls.append((key, nx, ex))
            return len(calls) == 1

    store = RedisUsedTokens(FakeRedis())
    assert store.claim("j1", 30) and not store.claim("j1", 30)
    assert calls[0] == ("aurai:approval:j1", True, 30)
