import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from aurai_connectors.manifest import ManifestError, load_all, load_manifest
from aurai_connectors.reviews import check_policy_references, check_reviews
from tests.conftest import ROOT

TODAY = date(2026, 11, 20)


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def tool(**over):
    base = {"name": "demo_get", "action": "read", "classification": "internal", "description": "Get a thing."}
    base.update(over)
    return base


@pytest.fixture
def copy(tmp_path):
    target = tmp_path / "connectors"
    shutil.copytree(ROOT / "connectors", target)
    return target


def test_shipped_manifests_load():
    manifests = load_all(ROOT / "connectors")
    assert set(manifests) == {"tickets", "ops-data", "messaging", "files"}
    assert manifests["messaging"].tools["messages_send"].approval == "always"
    assert manifests["files"].tools["files_read"].dynamic


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"action": "delete"}, "action must be"),
        ({"classification": "secret"}, "classification must be"),
        ({"action": "write", "approval": "none"}, "write tool must set approval"),
        ({"action": "write"}, "approval must be"),
        ({"description": ""}, "description is required"),
        ({"name": "Bad-Name"}, "lowercase"),
        ({"approval": "sometimes"}, "approval must be"),
    ],
)
def test_manifest_validation(tmp_path, override, fragment):
    path = write(tmp_path / "demo" / "connector.yaml", {"name": "demo", "tools": [tool(**override)]})
    with pytest.raises(ManifestError, match=fragment):
        load_manifest(path)


def test_duplicate_tools_and_empty_manifests_are_errors(tmp_path):
    path = write(tmp_path / "demo" / "connector.yaml", {"name": "demo", "tools": [tool(), tool()]})
    with pytest.raises(ManifestError, match="twice"):
        load_manifest(path)
    path = write(tmp_path / "demo" / "connector.yaml", {"name": "demo", "tools": []})
    with pytest.raises(ManifestError, match="no tools"):
        load_manifest(path)


def test_the_folder_name_must_match_the_connector_name(tmp_path):
    write(tmp_path / "other" / "connector.yaml", {"name": "demo", "tools": [tool()]})
    with pytest.raises(ManifestError, match="must match its folder"):
        load_all(tmp_path)


def test_shipped_reviews_and_policy_references_pass():
    assert check_reviews(ROOT / "connectors", TODAY) == []
    assert check_policy_references(ROOT / "connectors", ROOT / "policy" / "teams.yaml") == []


def edit_review(copy, connector, **changes):
    path = copy / connector / "review.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data))


def test_a_connector_without_a_review_fails(copy):
    (copy / "files" / "review.yaml").unlink()
    assert any("files: no review.yaml" in p for p in check_reviews(copy, TODAY))


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"status": "pending"}, "not 'approved'"),
        ({"reviewer": "platform-team"}, "must not be the connector's owner"),
        ({"reviewed_on": date(2025, 1, 1)}, "older than"),
        ({"reviewed_on": date(2027, 1, 1)}, "future"),
        ({"reviewed_on": "last week"}, "YYYY-MM-DD"),
        ({"tools_reviewed": ["files_list"]}, "not covered by the review"),
        ({"tools_reviewed": ["files_list", "files_read", "files_write", "files_delete"]}, "does not declare"),
        ({"reviewer": ""}, "missing reviewer"),
        ({"findings": [{"title": "Path traversal", "severity": "high", "status": "open"}]}, "open high finding"),
    ],
)
def test_review_problems_are_reported(copy, changes, fragment):
    edit_review(copy, "files", **changes)
    problems = check_reviews(copy, TODAY)
    assert any(fragment in p for p in problems), problems


def test_adding_a_tool_without_re_review_fails(copy):
    path = copy / "files" / "connector.yaml"
    data = yaml.safe_load(path.read_text())
    data["tools"].append(
        {
            "name": "files_delete",
            "action": "write",
            "classification": "dynamic",
            "approval": "always",
            "description": "Delete a file.",
        }
    )
    path.write_text(yaml.safe_dump(data))
    assert any("files_delete" in p for p in check_reviews(copy, TODAY))


def test_policy_that_names_missing_tools_or_wrong_actions_fails(tmp_path):
    teams = write(
        tmp_path / "teams.yaml",
        {
            "teams": {
                "x": {
                    "connectors": {
                        "tickets": {"read": ["tickets_nope", "tickets_create_draft"], "write": ["tickets_get"]},
                        "ghost": {"read": ["*"], "write": []},
                    }
                }
            }
        },
    )
    problems = check_policy_references(ROOT / "connectors", teams)
    assert any("no tool 'tickets_nope'" in p for p in problems)
    assert any("tickets_create_draft is a write tool but is listed under read" in p for p in problems)
    assert any("tickets_get is a read tool but is listed under write" in p for p in problems)
    assert any("unknown connector 'ghost'" in p for p in problems)


def test_policy_with_a_bad_tier_or_limit_fails(tmp_path):
    teams = write(
        tmp_path / "teams.yaml", {"teams": {"x": {"tier": "T9", "max_classification": "secret", "connectors": {}}}}
    )
    problems = check_policy_references(ROOT / "connectors", teams)
    assert any("tier must be" in p for p in problems) and any("max_classification" in p for p in problems)
