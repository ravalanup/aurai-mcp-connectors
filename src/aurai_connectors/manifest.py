"""Connector manifests. connectors/<name>/connector.yaml declares each tool's action, data classification and approval
rule. That file is the single source of truth: the framework reads it, the policy decision is built from it, and the
review check compares it with the security review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import ACTIONS, APPROVAL_MODES, CLASSIFICATIONS, ToolSpec

TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{2,63}")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    name: str
    description: str
    tools: dict[str, ToolSpec]


def load_manifest(path: Path) -> Manifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"{path}: cannot read manifest: {exc}") from exc
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ManifestError(f"{path}: missing connector name")
    tools: dict[str, ToolSpec] = {}
    for item in raw.get("tools") or []:
        tool = item.get("name")
        where = f"{path}: tool {tool!r}"
        if not isinstance(tool, str) or not TOOL_NAME.fullmatch(tool):
            raise ManifestError(f"{where}: tool names are lowercase letters, digits and underscores")
        if tool in tools:
            raise ManifestError(f"{where}: declared twice")
        action = item.get("action")
        if action not in ACTIONS:
            raise ManifestError(f"{where}: action must be one of {ACTIONS}")
        classification = item.get("classification")
        if classification not in (*CLASSIFICATIONS, "dynamic"):
            raise ManifestError(f"{where}: classification must be one of {(*CLASSIFICATIONS, 'dynamic')}")
        approval = item.get("approval", "none" if action == "read" else None)
        if approval not in APPROVAL_MODES:
            raise ManifestError(f"{where}: approval must be one of {APPROVAL_MODES}")
        if action == "write" and approval == "none":
            raise ManifestError(f"{where}: a write tool must set approval to policy or always")
        description = (item.get("description") or "").strip()
        if not description:
            raise ManifestError(f"{where}: a description is required; the model reads it to choose the tool")
        tools[tool] = ToolSpec(tool, name, action, classification, approval, description)
    if not tools:
        raise ManifestError(f"{path}: declares no tools")
    return Manifest(name=name, description=(raw.get("description") or "").strip(), tools=tools)


def load_all(connectors_dir: Path) -> dict[str, Manifest]:
    manifests = {}
    for path in sorted(connectors_dir.glob("*/connector.yaml")):
        manifest = load_manifest(path)
        if manifest.name != path.parent.name:
            raise ManifestError(f"{path}: name {manifest.name!r} must match its folder {path.parent.name!r}")
        manifests[manifest.name] = manifest
    return manifests
