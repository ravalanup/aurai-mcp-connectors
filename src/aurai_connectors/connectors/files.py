"""File store. Classification is per file, so the tools resolve it from the arguments: a read is classified by the
file being read, a write by the label the caller is applying. A failed lookup counts as restricted."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from ..backends import FileBackend, NotFound
from ..framework import Governor, current, require
from ..models import CLASSIFICATIONS, rank

NAME = "files"
MAX_BYTES = 100_000


def build(governor: Governor, backend: FileBackend | None = None) -> MCPServer:
    backend = backend or FileBackend.seeded()
    server = MCPServer("aurai-files")

    def classify_read(arguments: dict[str, Any]) -> str:
        return backend.classification_of(arguments["path"])

    def classify_write(arguments: dict[str, Any]) -> str:
        label = arguments["classification"]
        existing = backend.files.get(arguments["path"])
        # Overwriting a file never lowers its label: the call is judged by the more sensitive of the two.
        if existing and rank(existing["classification"]) > rank(label):
            return existing["classification"]
        return label

    @governor.tool(server, "files_list")
    def files_list(folder: str = "/") -> list[dict]:
        # The listing is filtered to what the caller's team may see, so file names do not leak either.
        ceiling = rank(current().decision.ceiling)
        return [f for f in backend.list(folder) if rank(f["classification"]) <= ceiling]

    @governor.tool(server, "files_read", classify=classify_read)
    def files_read(path: str) -> dict:
        try:
            return backend.read(path)
        except NotFound:
            require(False, "no such file")
            raise

    @governor.tool(server, "files_write", classify=classify_write)
    def files_write(path: str, content: str, classification: str) -> dict:
        require(path.startswith("/") and ".." not in path, "path must be absolute and free of '..'")
        require(classification in CLASSIFICATIONS, f"classification must be one of {CLASSIFICATIONS}")
        require(len(content.encode()) <= MAX_BYTES, f"content must be at most {MAX_BYTES} bytes")
        return backend.write(path, content, classification)

    governor.assert_complete()
    return server
