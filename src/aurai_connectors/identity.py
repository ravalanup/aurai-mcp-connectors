"""Caller identity from a Keycloak service-account token. The team and use case come from verified claims; the risk
tier is looked up in policy data and is never taken from the token or the request."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import jwt

from .models import AuthError, Caller

BEARER = "bearer "


class TokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        key_resolver: Callable[[str], Any] | None = None,
        algorithms: tuple[str, ...] = ("RS256",),
        leeway_seconds: int = 10,
    ) -> None:
        if not key_resolver and not jwks_url:
            raise ValueError("provide a jwks_url or a key_resolver")
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)
        self._leeway = leeway_seconds
        if key_resolver:
            self._resolve = key_resolver
        else:
            client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)  # type: ignore[arg-type]
            self._resolve = lambda token: client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Caller:
        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token ({type(exc).__name__})") from exc
        except Exception as exc:  # an unreachable JWKS endpoint must never become a pass
            raise AuthError("token keys could not be resolved") from exc
        team, use_case = claims.get("team_id"), claims.get("use_case_id")
        if not isinstance(team, str) or not team or not isinstance(use_case, str) or not use_case:
            raise AuthError("token carries no team_id and use_case_id")
        return Caller(team_id=team, use_case_id=use_case, subject=str(claims["sub"]))


def bearer_token(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    value = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    if value.lower().startswith(BEARER):
        return value[len(BEARER) :].strip() or None
    return None


def header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    return next((v for k, v in headers.items() if k.lower() == name.lower()), None)


class IdentityResolver:
    """HTTP callers present a bearer token. A stdio server has no request headers, so it is the local-development
    transport: its caller comes from AURAI_DEV_CALLER=<team>:<use_case>, and only when AURAI_ALLOW_DEV_IDENTITY=1."""

    def __init__(self, verifier: TokenVerifier | None, dev_caller: Caller | None = None) -> None:
        self._verifier = verifier
        self._dev = dev_caller

    @classmethod
    def dev_caller_from_env(cls, env: Mapping[str, str] | None = None) -> Caller | None:
        env = os.environ if env is None else env
        if env.get("AURAI_ALLOW_DEV_IDENTITY") != "1":
            return None
        team, _, use_case = env.get("AURAI_DEV_CALLER", "").partition(":")
        if not team or not use_case:
            raise ValueError("AURAI_DEV_CALLER must be <team>:<use_case> when AURAI_ALLOW_DEV_IDENTITY=1")
        return Caller(team_id=team, use_case_id=use_case, subject=f"dev:{team}")

    def resolve(self, headers: Mapping[str, str] | None) -> Caller:
        if headers is None:  # stdio: no HTTP request exists
            if self._dev:
                return self._dev
            raise AuthError("no caller identity: stdio needs AURAI_ALLOW_DEV_IDENTITY=1 and AURAI_DEV_CALLER")
        token = bearer_token(headers)
        if not token:
            raise AuthError("missing bearer token")
        if not self._verifier:
            raise AuthError("this server has no token verifier configured")
        return self._verifier.verify(token)
