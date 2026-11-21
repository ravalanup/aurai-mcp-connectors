# Architecture

The connectors are how Aurai's agents reach other systems: work management, operations data, messaging and files. Each
connector is a small MCP server. What makes them safe to give to an agent is that **every tool call passes through the
same governed path**, and tool code cannot register itself any other way.

```
 agent / workflow ──(MCP over HTTP, bearer service token, optional X-Aurai-Approval)──▶ connector pod
                                                                                         │
   GuardedApp          401 unless a valid token for audience aurai-connectors            │
   Governor.run  ──  1 identify the caller        team_id, use_case_id from verified claims
                     2 classify the data          from the manifest, or resolved from the arguments
                     3 policy decision  ───────────▶ OPA sidecar on 127.0.0.1:8181  (default deny, fail closed)
                     4 approval, if required      signed token bound to this tool, these arguments, this caller
                     5 run the tool, then audit line + spans (never arguments or results)
```

## One server per connector

| Connector | Tools | Reads | Writes |
| --- | --- | --- | --- |
| `tickets` | search, get, create draft, update status | internal | internal, approval by tier |
| `ops-data` | downtime summary, staffing, incidents | internal, confidential | none (read-only by construction) |
| `messaging` | create draft, send | none | draft by tier; **send always needs approval** |
| `files` | list, read, write | per-file label | per-file label, approval by tier |

Each is its own Deployment, Service and OPA sidecar. A connector can be disabled, scaled or rolled on its own, and its
security review (`connectors/<name>/review.yaml`) covers exactly its tools.

## The manifest is the contract

`connectors/<name>/connector.yaml` declares every tool: action (`read` or `write`), data classification (or `dynamic`)
and approval rule (`none`, `policy`, `always`). The framework reads it and:

- builds the policy input from it, so a tool cannot claim to be a read, or less sensitive, than the manifest says;
- refuses to start if the code registers a tool the manifest does not declare, or the manifest declares a tool the
  code does not register;
- refuses a write tool whose approval is `none`;
- takes the tool description the model sees from it, so what the model reads is reviewed text.

`aurai-connectors check` (run in CI and before every local deploy) confirms each connector has an approved, current
security review that covers its tools, and that `policy/teams.yaml` names only tools that exist. Adding a tool without
a new review fails CI (PRD MC-4).

## What a tool author writes

```python
@governor.tool(server, "tickets_get")
def tickets_get(ticket_id: str) -> dict:
    return backend.get(ticket_id)
```

Nothing about identity, policy, approval, audit or tracing appears in the tool. The wrapper keeps the tool's signature
(so the model sees the right schema) and adds the MCP context. See [connector-authoring.md](connector-authoring.md).

## Transports

HTTP (streamable, stateless) is the default and the only transport with real identity: callers present a Keycloak
service-account token. stdio exists for local development with an MCP client; it has no headers, so its caller is the
development identity (`AURAI_DEV_CALLER`), honoured only when `AURAI_ALLOW_DEV_IDENTITY=1`. Policy and audit still run.
stdio cannot carry the approval header, so writes that need approval are exercised over HTTP.

## Why OPA as a sidecar

Policy is data plus rules that security and data owners review, separate from connector code. A sidecar on the pod's
loopback keeps the decision local (no network hop to fail), makes it testable with `opa test`, and lets the same Rego
serve every connector. The policy files are mounted from one ConfigMap built from `policy/` at install time.

## Fail closed

Any of these ends in a refusal: no token, bad token, missing `team_id` or `use_case_id`, OPA unreachable or slow
(2 s), an answer that is not complete and well typed, an unknown team, an unresolvable file label (treated as
restricted), an approval that does not match the call. See [policy.md](policy.md) and [approvals.md](approvals.md).
