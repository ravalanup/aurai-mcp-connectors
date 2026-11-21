# Allow/deny for every tool call (PRD MC-2). Default deny: a call is allowed only when no deny rule fires.
#
# Input (built by the connector framework from its own manifest and the verified caller, never from the request):
#   team, use_case   caller identity from the verified service token
#   connector, tool  what is being called
#   action           "read" or "write", declared in the connector manifest
#   classification   public | internal | confidential | restricted, for the data this call involves
#   approval         "none" | "policy" | "always", declared in the manifest
# Data: data.teams, from policy/teams.yaml.
package aurai.tools

import rego.v1

default allow := false

rank := {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

tier_rank := {"T0": 0, "T1": 1, "T2": 2, "T3": 3}

# The lowest tier allowed to handle each classification.
min_tier := {"public": "T0", "internal": "T0", "confidential": "T2", "restricted": "T3"}

# The highest classification each tier may handle.
tier_ceiling := {"T0": "internal", "T1": "internal", "T2": "confidential", "T3": "restricted"}

# Human approvals a write needs, by tier. Reads never need approval.
approvals_by_tier := {"T0": 0, "T1": 0, "T2": 1, "T3": 2}

default teams := {}

teams := data.teams

team := teams[input.team]

scope := team.connectors[input.connector]

tool_listed(names) if input.tool in names

tool_listed(names) if "*" in names

in_scope if {
	input.action == "read"
	tool_listed(scope.read)
}

in_scope if {
	input.action == "write"
	tool_listed(scope.write)
}

# object.get keeps these checks defined when a field is missing, so an incomplete input is denied, never allowed.
deny contains "unknown_team" if not teams[object.get(input, "team", "")]

deny contains "team_paused" if team.paused == true

deny contains "unknown_action" if not object.get(input, "action", "") in {"read", "write"}

deny contains "unknown_classification" if not object.get(rank, object.get(input, "classification", ""), false) != false

deny contains "tool_not_in_scope" if {
	team
	not in_scope
}

deny contains "classification_above_team_limit" if {
	rank[input.classification] > rank[team.max_classification]
}

deny contains "classification_above_tier" if {
	tier_rank[team.tier] < tier_rank[min_tier[input.classification]]
}

allow if count(deny) == 0

tier := t if {
	t := data.teams[input.team].tier
} else := "unknown"

default tier_requirement := 0

tier_requirement := approvals_by_tier[team.tier] if input.action == "write"

default tool_requirement := 0

tool_requirement := 1 if input.approval == "always"

default approvals_required := 0

approvals_required := max([tier_requirement, tool_requirement]) if allow

# The most sensitive data this team may touch through any tool. Tools that return many items (a file listing)
# use it to leave out what the caller may not see.
ceiling := c if {
	t := tier_ceiling[team.tier]
	l := team.max_classification
	c := [k | some k, v in rank; v == min([rank[t], rank[l]])][0]
} else := "public"

decision := {
	"allow": allow,
	"approvals_required": approvals_required,
	"tier": tier,
	"ceiling": ceiling,
	"reasons": sort([r | some r in deny]),
}
