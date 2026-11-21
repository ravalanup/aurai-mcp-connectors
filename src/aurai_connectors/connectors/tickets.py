"""Work management (tickets)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ..backends import AREAS, TICKET_STATUSES, NotFound, TicketBackend
from ..framework import Governor, require

NAME = "tickets"


def build(governor: Governor, backend: TicketBackend | None = None) -> MCPServer:
    backend = backend or TicketBackend.seeded()
    server = MCPServer("aurai-tickets")

    @governor.tool(server, "tickets_search")
    def tickets_search(query: str = "", status: str | None = None, limit: int = 10) -> list[dict]:
        require(status is None or status in TICKET_STATUSES, f"status must be one of {TICKET_STATUSES}")
        require(1 <= limit <= 50, "limit must be between 1 and 50")
        return backend.search(query, status, limit)

    @governor.tool(server, "tickets_get")
    def tickets_get(ticket_id: str) -> dict:
        try:
            return backend.get(ticket_id)
        except NotFound:
            require(False, "no such ticket")
            raise

    @governor.tool(server, "tickets_create_draft")
    def tickets_create_draft(title: str, body: str, area: str) -> dict:
        require(0 < len(title) <= 200, "title must be 1 to 200 characters")
        require(len(body) <= 5000, "body must be at most 5000 characters")
        require(area in AREAS, f"area must be one of {AREAS}")
        return backend.create_draft(title, body, area)

    @governor.tool(server, "tickets_update_status")
    def tickets_update_status(ticket_id: str, status: str) -> dict:
        require(status in TICKET_STATUSES and status != "draft", "status must be open, in_progress or resolved")
        try:
            return backend.update_status(ticket_id, status)
        except NotFound:
            require(False, "no such ticket")
            raise

    governor.assert_complete()
    return server
