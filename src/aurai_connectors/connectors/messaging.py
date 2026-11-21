"""Messaging. The model can draft a message; sending always needs a human approval, whatever the team's tier. Recipients
are limited to the company domain here in the tool, as a second control beside policy."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ..backends import ALLOWED_RECIPIENT_DOMAIN, MessageBackend, NotFound
from ..framework import Governor, require

NAME = "messaging"


def build(governor: Governor, backend: MessageBackend | None = None) -> MCPServer:
    backend = backend or MessageBackend()
    server = MCPServer("aurai-messaging")

    @governor.tool(server, "messages_create_draft")
    def messages_create_draft(to: list[str], subject: str, body: str) -> dict:
        require(0 < len(to) <= 10, "to must list 1 to 10 recipients")
        require(
            all(backend.recipient_allowed(a) for a in to),
            f"recipients must be @{ALLOWED_RECIPIENT_DOMAIN} addresses",
        )
        require(0 < len(subject) <= 200 and 0 < len(body) <= 10000, "subject and body are required and must be short")
        return backend.create_draft(to, subject, body)

    @governor.tool(server, "messages_send")
    def messages_send(draft_id: str) -> dict:
        try:
            draft = backend.drafts[draft_id]
        except KeyError:
            require(False, "no such draft")
            raise
        require(
            all(backend.recipient_allowed(a) for a in draft["to"]), "draft has a recipient outside the allowed domain"
        )
        try:
            return backend.send(draft_id)
        except NotFound:
            require(False, "no such draft")
            raise
        except ValueError as exc:
            require(False, str(exc))
            raise

    governor.assert_complete()
    return server
