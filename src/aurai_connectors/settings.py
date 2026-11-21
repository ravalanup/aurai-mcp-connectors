"""Configuration from environment variables (set by the Helm chart)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    connectors_dir: Path
    policy_dir: Path
    issuer: str
    audience: str
    jwks_url: str
    opa_url: str
    approval_signing_key: str
    redis_url: str
    otlp_endpoint: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        issuer = e.get("AURAI_ISSUER", "http://keycloak.aurai-system.svc.cluster.local:8080/realms/aurai")
        return cls(
            connectors_dir=Path(e.get("AURAI_CONNECTORS_DIR", "connectors")),
            policy_dir=Path(e.get("AURAI_POLICY_DIR", "policy")),
            issuer=issuer,
            audience=e.get("AURAI_AUDIENCE", "aurai-connectors"),
            jwks_url=e.get("AURAI_JWKS_URL", issuer.rstrip("/") + "/protocol/openid-connect/certs"),
            opa_url=e.get("AURAI_OPA_URL", ""),
            approval_signing_key=e.get("AURAI_APPROVAL_SIGNING_KEY", ""),
            redis_url=e.get("AURAI_REDIS_URL", ""),
            otlp_endpoint=e.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        )
