# Identity

Callers are workloads (an agent or workflow acting for a use case), authenticated with **Keycloak service-account
tokens**.

## What the connector requires

- RS256 signature verified against the realm's JWKS (cached 10 minutes); an unreachable JWKS is a refusal, not a pass.
- `iss` equals the realm issuer, `aud` contains `aurai-connectors`, `exp` is in the future.
- Claims `team_id` and `use_case_id`, both non-empty strings. These identify the caller to policy. `sub` is recorded in
  the audit log and checked against the approvers.

Nothing else is trusted. Request headers, bodies and tool arguments never set identity or tier; a test sends a token for
`sandbox` along with headers claiming `ops-insights` and a high tier, and policy sees `sandbox`.

## What has to exist in Keycloak

This repository **does not create** the service clients. For each calling use case, a confidential client with service
accounts enabled and:

- an audience mapper adding `aurai-connectors`;
- hardcoded-claim mappers for `team_id` and `use_case_id` (a service client acts for one use case);
- no user-facing flows.

The `aurai-workspace` realm tool covers groups, users and standard clients but not claim mappers for service accounts, so
creating these is part of the agent-runtime work. Until then the tests use generated keys, and local development uses
the stdio development identity.

## Audience

The connectors use their own audience, `aurai-connectors`, so a token minted for the gateway or the knowledge service
cannot be replayed here (a test checks this). The knowledge service still reuses the `litellm` audience; a dedicated
one is listed there as a gap.
