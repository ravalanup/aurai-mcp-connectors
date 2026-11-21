from tests.conftest import needs_opa

pytestmark = needs_opa


async def test_read_tools_work_for_a_team_in_scope(harness):
    h = await harness("tickets")
    found = await h.call("tickets_search", {"query": "coaster"})
    assert not found.is_error
    assert {t["id"] for t in found.data} >= {"TCK-1001"}
    got = await h.call("tickets_get", {"ticket_id": "TCK-1001"})
    assert got.data["title"].startswith("Harbor Coaster")


async def test_tools_list_is_the_manifest(harness, private_key):
    from tests.conftest import mint

    h = await harness("tickets")
    response = await h.rpc("tools/list", token=mint(private_key))
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert names == {"tickets_search", "tickets_get", "tickets_create_draft", "tickets_update_status"}
    schema = next(t for t in response.json()["result"]["tools"] if t["name"] == "tickets_search")
    assert "ctx" not in schema["inputSchema"]["properties"]


async def test_write_needs_approval_at_tier_two(harness):
    h = await harness("tickets")
    args = {"title": "Fix lantern", "body": "East gate", "area": "Lantern Gardens"}
    result = await h.call("tickets_create_draft", args)
    assert result.is_error and result.error == "approval_required"
    assert result.detail["approvals_required"] == 1
    assert len(result.detail["args_hash"]) == 64


async def test_write_runs_with_a_matching_approval(harness, approval):
    h = await harness("tickets")
    args = {"title": "Fix lantern", "body": "East gate", "area": "Lantern Gardens"}
    result = await h.call("tickets_create_draft", args, approval=approval("tickets_create_draft", args))
    assert not result.is_error
    assert result.data["status"] == "draft"


async def test_tier_one_write_needs_no_approval(harness):
    h = await harness("tickets")
    args = {"title": "Printer jam", "body": "Back office", "area": "Main Street Shops"}
    result = await h.call("tickets_create_draft", args, team="internal-help", use_case="helpdesk")
    assert not result.is_error


async def test_team_without_write_scope_is_denied(harness):
    h = await harness("tickets")
    result = await h.call("tickets_update_status", {"ticket_id": "TCK-1001", "status": "resolved"}, team="sandbox")
    assert result.is_error and result.error == "policy_denied"


async def test_bad_arguments_are_a_clear_error(harness):
    h = await harness("tickets")
    result = await h.call("tickets_search", {"query": "x", "limit": 500})
    assert result.is_error and result.error == "bad_arguments"
