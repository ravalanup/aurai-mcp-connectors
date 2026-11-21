from aurai_connectors.backends import MessageBackend
from tests.conftest import needs_opa

pytestmark = needs_opa

DRAFT = {"to": ["maria@amazing-enterprise.example"], "subject": "Coaster update", "body": "Train 2 is back in service."}


async def test_draft_then_send_with_approvals(harness, approval):
    backend = MessageBackend()
    h = await harness("messaging", backend)
    d = await h.call("messages_create_draft", DRAFT, approval=approval("messages_create_draft", DRAFT))
    assert not d.is_error
    draft_id = d.data["id"]
    args = {"draft_id": draft_id}
    blocked = await h.call("messages_send", args)
    assert blocked.error == "approval_required"
    sent = await h.call("messages_send", args, approval=approval("messages_send", args))
    assert sent.data == {"id": draft_id, "status": "sent", "recipients": 1}
    assert len(backend.sent) == 1


async def test_sending_needs_approval_even_with_nothing_else_required(harness):
    """With no token at all, a send is held for approval and nothing is sent."""
    h = await harness("messaging")
    d = await h.call("messages_send", {"draft_id": "DRF-1"})
    assert d.error == "approval_required"


async def test_an_approval_for_one_draft_does_not_send_another(harness, approval):
    backend = MessageBackend()
    h = await harness("messaging", backend)
    one = backend.create_draft(["a@amazing-enterprise.example"], "s", "b")["id"]
    two = backend.create_draft(["b@amazing-enterprise.example"], "s", "b")["id"]
    r = await h.call("messages_send", {"draft_id": two}, approval=approval("messages_send", {"draft_id": one}))
    assert r.error == "approval_invalid" and not backend.sent


async def test_external_recipients_are_refused_even_with_approval(harness, approval):
    h = await harness("messaging")
    args = {**DRAFT, "to": ["someone@elsewhere.example"]}
    r = await h.call("messages_create_draft", args, approval=approval("messages_create_draft", args))
    assert r.error == "bad_arguments" and "amazing-enterprise.example" in r.detail["message"]


async def test_lookalike_domains_are_refused():
    assert not MessageBackend.recipient_allowed("x@amazing-enterprise.example.evil.test")
    assert not MessageBackend.recipient_allowed("x@evil-amazing-enterprise.example")
    assert MessageBackend.recipient_allowed("X@Amazing-Enterprise.example")


async def test_sending_twice_is_refused(harness, approval):
    backend = MessageBackend()
    h = await harness("messaging", backend)
    draft_id = backend.create_draft(["a@amazing-enterprise.example"], "s", "b")["id"]
    args = {"draft_id": draft_id}
    assert not (await h.call("messages_send", args, approval=approval("messages_send", args))).is_error
    again = await h.call("messages_send", args, approval=approval("messages_send", args))
    assert again.error == "bad_arguments" and len(backend.sent) == 1


async def test_a_team_without_messaging_scope_is_denied(harness):
    h = await harness("messaging")
    assert (await h.call("messages_create_draft", DRAFT, team="sandbox")).error == "policy_denied"
