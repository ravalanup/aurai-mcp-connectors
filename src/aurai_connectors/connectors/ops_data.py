"""Operations data, read-only. The connector has no write tools, and the manifest check keeps it that way."""

from __future__ import annotations

import re

from mcp.server.mcpserver import MCPServer

from ..backends import AREAS, OpsBackend
from ..framework import Governor, require

NAME = "ops-data"
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def build(governor: Governor, backend: OpsBackend | None = None) -> MCPServer:
    backend = backend or OpsBackend()
    server = MCPServer("aurai-ops-data")

    @governor.tool(server, "ops_downtime_summary")
    def ops_downtime_summary(area: str, days: int = 7) -> dict:
        require(area in AREAS, f"area must be one of {AREAS}")
        require(1 <= days <= 90, "days must be between 1 and 90")
        return backend.downtime(area, days)

    @governor.tool(server, "ops_staffing")
    def ops_staffing(area: str, day: str) -> dict:
        require(area in AREAS, f"area must be one of {AREAS}")
        require(bool(DAY.fullmatch(day)), "day must be YYYY-MM-DD")
        return backend.staffing(area, day)

    @governor.tool(server, "ops_incidents")
    def ops_incidents(area: str, days: int = 30) -> list[dict]:
        require(area in AREAS, f"area must be one of {AREAS}")
        require(1 <= days <= 90, "days must be between 1 and 90")
        return backend.incidents(area, days)

    governor.assert_complete()
    return server
