# Runbook

| Symptom | Likely cause | Check and fix |
| --- | --- | --- |
| Every call returns `policy_denied` with reason `policy_unavailable` | OPA sidecar down, slow (over 2 s) or returning a bad answer | `kubectl logs deploy/aurai-connector-<name> -c opa`; restart the pod. The connector is correctly refusing everything. |
| 401 from the connector | missing, expired or wrong-audience token; no `team_id`/`use_case_id` | decode the token; the client needs the `aurai-connectors` audience mapper and the two claim mappers (docs/identity.md) |
| `policy_denied` with `tool_not_in_scope` | the team has no scope for that tool | check `policy/teams.yaml`; change by pull request, not in the cluster |
| `policy_denied` with `classification_above_tier` or `_team_limit` | the data is more sensitive than the team may touch | expected; the data owner decides whether the team's tier or limit should change |
| `approval_required` every time, even with a token | the token does not match: tool, arguments, team or use case differ, or it was already used | the `message` says which; argument key order does not matter, values do |
| `approval_invalid: already used` | replay, or the pod lost its used-token list | with more than one replica set `config.redisUrl` |
| Pod fails at start with `registered … but the manifest declares …` | a tool was added or removed in only one place | fix the manifest or the module; CI catches this |
| `aurai-connectors check` fails | missing/stale review, tool not covered by it, policy naming a missing tool | the output names the connector and the cause |

## Stop a team now

Set `paused: true` for the team in `policy/teams.yaml`, then `helm upgrade` with the same `--set-file` flags. Calls from
that team are denied with `team_paused` on the next decision. To stop one connector for everyone, set it to
`enabled: false` in the chart values.

## Rotate the approval signing key

Create the new key in the Secret and in the approval service together, restart the connectors, and let in-flight
approvals expire (15 minutes at most). Rotation without a window needs two accepted keys; not built.

## Read the audit log

`kubectl logs deploy/aurai-connector-<name> -c connector | grep '"outcome"'`. One JSON line per call with team, use case,
tool, decision, reasons, approvers, outcome and the argument hash. To find the call an approval covered, match
`args_hash`. OPA also writes its own decision log to the sidecar's stdout.
