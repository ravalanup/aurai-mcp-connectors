package aurai.tools_test

import data.aurai.tools
import rego.v1

teams := {
	"t0": {"tier": "T0", "max_classification": "internal", "connectors": {"tickets": {"read": ["*"], "write": []}}},
	"t1": {"tier": "T1", "max_classification": "internal", "connectors": {"tickets": {"read": ["*"], "write": ["create"]}}},
	"t2": {"tier": "T2", "max_classification": "confidential", "connectors": {"files": {"read": ["read"], "write": ["write"]}}},
	"t3": {"tier": "T3", "max_classification": "restricted", "connectors": {"files": {"read": ["*"], "write": ["*"]}}},
	"paused": {"tier": "T2", "max_classification": "internal", "paused": true, "connectors": {"tickets": {"read": ["*"], "write": []}}},
	"t3low": {"tier": "T3", "max_classification": "internal", "connectors": {"files": {"read": ["*"], "write": ["*"]}}},
}

call(team, connector, tool, action, classification, approval) := {
	"team": team, "connector": connector, "tool": tool,
	"action": action, "classification": classification, "approval": approval,
}

test_read_in_scope_is_allowed if {
	d := tools.decision with input as call("t0", "tickets", "tickets_get", "read", "internal", "none") with data.teams as teams
	d.allow
	d.approvals_required == 0
	d.tier == "T0"
}

test_unknown_team_is_denied if {
	d := tools.decision with input as call("nobody", "tickets", "tickets_get", "read", "public", "none") with data.teams as teams
	not d.allow
	d.reasons == ["unknown_team"]
	d.tier == "unknown"
}

test_missing_input_is_denied if {
	d := tools.decision with input as {} with data.teams as teams
	not d.allow
}

test_tool_outside_scope_is_denied if {
	d := tools.decision with input as call("t0", "tickets", "tickets_create_draft", "write", "internal", "policy") with data.teams as teams
	not d.allow
	"tool_not_in_scope" in d.reasons
}

test_connector_outside_scope_is_denied if {
	d := tools.decision with input as call("t0", "files", "files_read", "read", "internal", "none") with data.teams as teams
	"tool_not_in_scope" in d.reasons
}

test_read_scope_does_not_grant_write if {
	d := tools.decision with input as call("t2", "files", "read", "write", "internal", "policy") with data.teams as teams
	"tool_not_in_scope" in d.reasons
}

test_write_at_t1_needs_no_approval_unless_tool_requires_it if {
	d := tools.decision with input as call("t1", "tickets", "create", "write", "internal", "policy") with data.teams as teams
	d.allow
	d.approvals_required == 0
	e := tools.decision with input as call("t1", "tickets", "create", "write", "internal", "always") with data.teams as teams
	e.approvals_required == 1
}

test_write_at_t2_needs_one_approval if {
	d := tools.decision with input as call("t2", "files", "write", "write", "confidential", "policy") with data.teams as teams
	d.allow
	d.approvals_required == 1
}

test_write_at_t3_needs_two_approvals if {
	d := tools.decision with input as call("t3", "files", "anything", "write", "restricted", "policy") with data.teams as teams
	d.allow
	d.approvals_required == 2
}

test_reads_never_need_approval if {
	d := tools.decision with input as call("t3", "files", "anything", "read", "restricted", "policy") with data.teams as teams
	d.approvals_required == 0
}

test_confidential_needs_tier_t2 if {
	d := tools.decision with input as call("t1", "tickets", "create", "write", "confidential", "policy") with data.teams as teams
	"classification_above_tier" in d.reasons
	"classification_above_team_limit" in d.reasons
}

test_team_limit_applies_even_when_tier_allows if {
	d := tools.decision with input as call("t3low", "files", "x", "read", "confidential", "none") with data.teams as teams
	d.reasons == ["classification_above_team_limit"]
}

test_restricted_needs_t3 if {
	d := tools.decision with input as call("t2", "files", "read", "read", "restricted", "none") with data.teams as teams
	"classification_above_tier" in d.reasons
}

test_paused_team_is_denied_everywhere if {
	d := tools.decision with input as call("paused", "tickets", "tickets_get", "read", "public", "none") with data.teams as teams
	d.reasons == ["team_paused"]
}

test_unknown_classification_and_action_are_denied if {
	d := tools.decision with input as call("t0", "tickets", "tickets_get", "read", "secret", "none") with data.teams as teams
	"unknown_classification" in d.reasons
	e := tools.decision with input as call("t0", "tickets", "tickets_get", "delete", "internal", "none") with data.teams as teams
	"unknown_action" in e.reasons
}

test_denied_decision_requires_no_approval if {
	d := tools.decision with input as call("nobody", "tickets", "x", "write", "internal", "always") with data.teams as teams
	d.approvals_required == 0
	not d.allow
}

test_ceiling_is_lower_of_tier_and_team_limit if {
	a := tools.decision with input as call("t3low", "files", "x", "read", "internal", "none") with data.teams as teams
	a.ceiling == "internal"
	b := tools.decision with input as call("t3", "files", "x", "read", "internal", "none") with data.teams as teams
	b.ceiling == "restricted"
	c := tools.decision with input as call("t2", "files", "read", "read", "internal", "none") with data.teams as teams
	c.ceiling == "confidential"
	d := tools.decision with input as call("nobody", "files", "read", "read", "internal", "none") with data.teams as teams
	d.ceiling == "public"
}
