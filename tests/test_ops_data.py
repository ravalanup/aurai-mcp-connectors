from tests.conftest import needs_opa

pytestmark = needs_opa


async def test_downtime_is_internal_and_open_to_ops_insights(harness):
    h = await harness("ops-data")
    r = await h.call("ops_downtime_summary", {"area": "Harbor Coaster", "days": 3})
    assert not r.is_error and len(r.data["daily"]) == 3


async def test_confidential_tools_need_tier_two_or_above(harness):
    h = await harness("ops-data")
    assert not (await h.call("ops_staffing", {"area": "Harbor Coaster", "day": "2026-11-20"})).is_error
    assert not (await h.call("ops_incidents", {"area": "Harbor Coaster"})).is_error


async def test_a_team_without_the_connector_is_denied(harness):
    h = await harness("ops-data")
    r = await h.call("ops_downtime_summary", {"area": "Harbor Coaster"}, team="internal-help")
    assert r.is_error and r.error == "policy_denied"


async def test_the_connector_has_no_write_tools(harness, private_key):
    from tests.conftest import mint

    h = await harness("ops-data")
    tools = (await h.rpc("tools/list", token=mint(private_key))).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"ops_downtime_summary", "ops_staffing", "ops_incidents"}


async def test_input_is_validated(harness):
    h = await harness("ops-data")
    assert (await h.call("ops_staffing", {"area": "Harbor Coaster", "day": "tomorrow"})).error == "bad_arguments"
    assert (await h.call("ops_downtime_summary", {"area": "Nowhere"})).error == "bad_arguments"
