"""Checks run in CI (PRD MC-4: security review workflow for new connectors).

A connector may deploy only when connectors/<name>/review.yaml records an approved security review that covers every
tool the manifest declares, was done by someone other than the owner, and is less than a year old. The same check
confirms the policy data refers only to tools that exist."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .manifest import ManifestError, load_all
from .models import CLASSIFICATIONS

MAX_REVIEW_AGE_DAYS = 365
REVIEW_FIELDS = ("owner", "reviewer", "reviewed_on", "status", "tools_reviewed")


def check_reviews(connectors_dir: Path, today: date | None = None) -> list[str]:
    today = today or date.today()
    problems: list[str] = []
    try:
        manifests = load_all(connectors_dir)
    except ManifestError as exc:
        return [str(exc)]
    for name, manifest in manifests.items():
        path = connectors_dir / name / "review.yaml"
        if not path.exists():
            problems.append(f"{name}: no review.yaml; a connector needs an approved security review")
            continue
        review: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        missing = [f for f in REVIEW_FIELDS if not review.get(f)]
        if missing:
            problems.append(f"{name}: review.yaml is missing {', '.join(missing)}")
            continue
        if review["status"] != "approved":
            problems.append(f"{name}: review status is {review['status']!r}, not 'approved'")
        if review["owner"] == review["reviewer"]:
            problems.append(f"{name}: the reviewer must not be the connector's owner")
        reviewed_on = review["reviewed_on"]
        if not isinstance(reviewed_on, date):
            problems.append(f"{name}: reviewed_on must be a YYYY-MM-DD date")
        elif (today - reviewed_on).days > MAX_REVIEW_AGE_DAYS:
            problems.append(f"{name}: review from {reviewed_on} is older than {MAX_REVIEW_AGE_DAYS} days")
        elif reviewed_on > today:
            problems.append(f"{name}: reviewed_on is in the future")
        reviewed = set(review["tools_reviewed"])
        declared = set(manifest.tools)
        if declared - reviewed:
            problems.append(f"{name}: tools not covered by the review: {sorted(declared - reviewed)}")
        if reviewed - declared:
            problems.append(f"{name}: review lists tools the manifest does not declare: {sorted(reviewed - declared)}")
        for finding in review.get("findings") or []:
            if finding.get("status") == "open" and finding.get("severity") in ("high", "critical"):
                problems.append(f"{name}: open {finding['severity']} finding: {finding.get('title', '?')}")
    return problems


def check_policy_references(connectors_dir: Path, teams_file: Path) -> list[str]:
    """Policy data must be well formed: valid tiers and limits, only connectors and tools that exist, and write scopes
    that name write tools."""
    manifests = load_all(connectors_dir)
    data = yaml.safe_load(teams_file.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    for team, spec in (data.get("teams") or {}).items():
        if spec.get("tier") not in ("T0", "T1", "T2", "T3"):
            problems.append(f"team {team}: tier must be T0, T1, T2 or T3")
        if spec.get("max_classification") not in CLASSIFICATIONS:
            problems.append(f"team {team}: max_classification must be one of {CLASSIFICATIONS}")
        for connector, scope in (spec.get("connectors") or {}).items():
            manifest = manifests.get(connector)
            if manifest is None:
                problems.append(f"team {team}: unknown connector {connector!r}")
                continue
            for action in ("read", "write"):
                for tool in scope.get(action) or []:
                    if tool == "*":
                        continue
                    declared = manifest.tools.get(tool)
                    if declared is None:
                        problems.append(f"team {team}: {connector} has no tool {tool!r}")
                    elif declared.action != action:
                        problems.append(f"team {team}: {tool} is a {declared.action} tool but is listed under {action}")
    return problems
