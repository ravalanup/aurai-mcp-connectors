import pytest

from aurai_connectors.identity import IdentityResolver, TokenVerifier, bearer_token
from aurai_connectors.models import AuthError, Caller
from tests.conftest import AUDIENCE, ISSUER, mint


def test_valid_token_gives_the_caller(verifier, private_key):
    caller = verifier.verify(mint(private_key, team="finance-reporting", use_case="monthly-close", sub="svc-fin"))
    assert caller == Caller("finance-reporting", "monthly-close", "svc-fin")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"audience": "someone-else"},
        {"ttl": -60},
        {"team": None},
        {"use_case": None},
        {"team": ""},
        {"team": ["a", "b"]},
    ],
)
def test_bad_tokens_are_rejected(verifier, private_key, kwargs):
    with pytest.raises(AuthError):
        verifier.verify(mint(private_key, **kwargs))


def test_wrong_issuer_and_wrong_key_are_rejected(private_key):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    v = TokenVerifier(ISSUER, AUDIENCE, key_resolver=lambda _t: private_key.public_key())
    with pytest.raises(AuthError):
        v.verify(mint(other))
    v2 = TokenVerifier("http://evil/realms/x", AUDIENCE, key_resolver=lambda _t: private_key.public_key())
    with pytest.raises(AuthError):
        v2.verify(mint(private_key))


def test_unreachable_jwks_is_an_auth_error_not_a_pass(private_key):
    def broken(_token):
        raise OSError("jwks down")

    with pytest.raises(AuthError, match="could not be resolved"):
        TokenVerifier(ISSUER, AUDIENCE, key_resolver=broken).verify(mint(private_key))


def test_a_verifier_needs_a_key_source():
    with pytest.raises(ValueError):
        TokenVerifier(ISSUER, AUDIENCE)


def test_bearer_parsing():
    assert bearer_token({"Authorization": "Bearer abc"}) == "abc"
    assert bearer_token({"authorization": "bearer abc"}) == "abc"
    assert bearer_token({"Authorization": "Basic abc"}) is None
    assert bearer_token({"Authorization": "Bearer "}) is None
    assert bearer_token(None) is None


def test_http_requests_without_a_token_are_refused(verifier):
    with pytest.raises(AuthError):
        IdentityResolver(verifier).resolve({})


def test_stdio_has_no_identity_unless_dev_mode_is_on(verifier):
    with pytest.raises(AuthError, match="stdio"):
        IdentityResolver(verifier).resolve(None)
    assert IdentityResolver.dev_caller_from_env({"AURAI_DEV_CALLER": "a:b"}) is None  # flag not set
    caller = IdentityResolver.dev_caller_from_env(
        {"AURAI_ALLOW_DEV_IDENTITY": "1", "AURAI_DEV_CALLER": "ops-insights:t"}
    )
    assert IdentityResolver(None, caller).resolve(None) == Caller("ops-insights", "t", "dev:ops-insights")


def test_dev_identity_does_not_apply_to_http(verifier):
    caller = Caller("ops-insights", "t", "dev")
    with pytest.raises(AuthError):
        IdentityResolver(verifier, caller).resolve({})


def test_dev_flag_without_a_caller_is_a_startup_error():
    with pytest.raises(ValueError):
        IdentityResolver.dev_caller_from_env({"AURAI_ALLOW_DEV_IDENTITY": "1"})
