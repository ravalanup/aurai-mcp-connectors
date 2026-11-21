# Policy

`policy/aurai/tools.rego` decides every call; `policy/teams.yaml` holds the per-team scopes (PRD MC-2, MC-3). Both are
reviewed like code, and `opa test policy` runs 17 tests on the rules in CI.

## Input (built by the framework, never taken from the request)

| Field | Source |
| --- | --- |
| `team`, `use_case` | verified token claims |
| `connector`, `tool`, `action`, `approval` | the connector manifest |
| `classification` | the manifest, or resolved from the arguments for `dynamic` tools |

The risk tier is **not** an input. It is looked up in `teams.yaml`, so a token or request cannot claim a higher tier.

## Rules

A call is allowed only if no deny rule fires:

| Reason | Fires when |
| --- | --- |
| `unknown_team` | the team is not in `teams.yaml` |
| `team_paused` | `paused: true` (incident response; one line to change) |
| `tool_not_in_scope` | the tool is not in the team's `read` or `write` list for that connector (a read scope never grants a write) |
| `classification_above_team_limit` | the data is more sensitive than the team's `max_classification` |
| `classification_above_tier` | the data needs a higher tier: confidential needs T2, restricted needs T3 |
| `unknown_action`, `unknown_classification` | the input is incomplete or malformed |

An empty input is denied (there is a test for it).

## Output

```json
{"allow": true, "approvals_required": 1, "tier": "T2", "ceiling": "confidential", "reasons": []}
```

- `approvals_required`: writes need one approval at T2 and two at T3; a tool whose manifest says `approval: always`
  needs at least one at any tier. Reads never need approval. A denial requires none (nothing runs).
- `ceiling`: the most sensitive data the team may touch, the lower of its tier's ceiling and its own limit. Tools that
  return many items use it to leave out what the caller cannot see; `files_list` does, so file names do not leak.

## The shipped teams

Team ids and tiers match `aurai-gateway/teams/teams.yaml`.

| Team | Tier | Limit | Scope |
| --- | --- | --- | --- |
| sandbox | T0 | internal | read tickets, list and read files |
| internal-help | T1 | internal | read and draft tickets, read files |
| ops-insights | T2 | confidential | ops data (read), tickets (draft, update), messages (draft, send), files (read) |
| finance-reporting | T2 | confidential | files (read, write), messages (draft) |
| guest-assistant | T3 | internal | read and draft tickets only; drafts need two approvals |

## Changing policy

1. Edit `policy/teams.yaml` (or the rules) and add or update a test.
2. `opa test policy && aurai-connectors check`.
3. The data owner of whatever the change opens up approves the pull request.
4. Redeploy; the chart's checksum annotation rolls the pods when the policy changes.

To stop a team immediately: set `paused: true` for it and redeploy (see [runbook.md](runbook.md)).
