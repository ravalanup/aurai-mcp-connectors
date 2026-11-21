from aurai_connectors.backends import FileBackend
from tests.conftest import needs_opa

pytestmark = needs_opa


async def test_list_returns_nothing_above_the_ceiling(harness):
    h = await harness("files")
    listed = {f["classification"] for f in (await h.call("files_list", {"folder": "/finance"})).data}
    assert listed <= {"public", "internal", "confidential"}


async def test_listing_hides_restricted_names_from_tier_two(harness):
    h = await harness("files")
    for folder in ("/hr", "/finance", "/ops", "/handbook"):
        paths = [f["path"] for f in (await h.call("files_list", {"folder": folder})).data]
        assert "/hr/compensation-bands.md" not in paths
    finance = [f["path"] for f in (await h.call("files_list", {"folder": "/finance"})).data]
    assert finance == ["/finance/q3-forecast.md"]


async def test_each_file_is_judged_by_its_own_label(harness):
    h = await harness("files")
    assert not (await h.call("files_read", {"path": "/handbook/guest-policy.md"}, team="sandbox")).is_error
    assert not (await h.call("files_read", {"path": "/ops/shift-notes.md"}, team="sandbox")).is_error
    confidential = await h.call("files_read", {"path": "/finance/q3-forecast.md"}, team="sandbox")
    assert confidential.error == "policy_denied"
    assert not (
        await h.call("files_read", {"path": "/finance/q3-forecast.md"}, team="finance-reporting", use_case="forecast")
    ).is_error
    restricted = await h.call(
        "files_read", {"path": "/hr/compensation-bands.md"}, team="finance-reporting", use_case="forecast"
    )
    assert restricted.error == "policy_denied"


async def test_an_unknown_path_is_treated_as_restricted(harness):
    h = await harness("files")
    r = await h.call("files_read", {"path": "/nope.md"}, team="ops-insights")
    assert r.error == "policy_denied"  # the lookup failed, so it was judged restricted, and tier two cannot see that


async def test_a_write_needs_the_approval_its_tier_requires(harness, approval):
    backend = FileBackend.seeded()
    h = await harness("files", backend)
    args = {"path": "/finance/q4-notes.md", "content": "Draft notes.", "classification": "confidential"}
    kw = {"team": "finance-reporting", "use_case": "forecast"}
    assert (await h.call("files_write", args, **kw)).error == "approval_required"
    ok = await h.call(
        "files_write",
        args,
        approval=approval("files_write", args, **{"team": "finance-reporting", "use_case": "forecast"}),
        **kw,
    )
    assert not ok.is_error and backend.files["/finance/q4-notes.md"]["classification"] == "confidential"


async def test_a_write_cannot_label_above_the_teams_ceiling(harness, approval):
    h = await harness("files")
    args = {"path": "/finance/x.md", "content": "x", "classification": "restricted"}
    r = await h.call(
        "files_write",
        args,
        team="finance-reporting",
        use_case="forecast",
        approval=approval("files_write", args, team="finance-reporting", use_case="forecast"),
    )
    assert r.error == "policy_denied"


async def test_overwriting_is_judged_by_the_existing_label(harness, approval):
    backend = FileBackend.seeded()
    h = await harness("files", backend)
    args = {"path": "/finance/q3-forecast.md", "content": "downgraded", "classification": "public"}
    kw = {"team": "sandbox", "use_case": "x"}
    r = await h.call("files_write", args, **kw)  # sandbox has no write scope at all
    assert r.error == "policy_denied"
    kw = {"team": "finance-reporting", "use_case": "forecast"}
    ok = await h.call("files_write", args, approval=approval("files_write", args, **kw), **kw)
    assert not ok.is_error
    # finance may handle confidential data, so this overwrite was allowed; the next test shows a team below the
    # file's level cannot do the same
    assert backend.classification_of("/finance/q3-forecast.md") == "public"


async def test_a_team_below_the_files_label_cannot_overwrite_it(harness, approval):
    h = await harness("files")
    args = {"path": "/hr/compensation-bands.md", "content": "x", "classification": "public"}
    kw = {"team": "finance-reporting", "use_case": "forecast"}
    r = await h.call("files_write", args, approval=approval("files_write", args, **kw), **kw)
    assert r.error == "policy_denied"


async def test_paths_with_parent_references_are_refused(harness, approval):
    h = await harness("files")
    args = {"path": "/finance/../hr/x.md", "content": "x", "classification": "internal"}
    kw = {"team": "finance-reporting", "use_case": "forecast"}
    r = await h.call("files_write", args, approval=approval("files_write", args, **kw), **kw)
    assert r.error == "bad_arguments"
