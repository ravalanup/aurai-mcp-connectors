"""Audit log: one JSON line per tool call on the `aurai.audit` logger, which the platform ships to its log store.
It records who called what and what was decided. It never records arguments or results: the argument hash lets an
auditor match a line to an approval without copying the data into a log."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

LOGGER_NAME = "aurai.audit"
_logger = logging.getLogger(LOGGER_NAME)

FIELDS = (
    "ts",
    "request_id",
    "connector",
    "tool",
    "action",
    "team",
    "use_case",
    "subject",
    "tier",
    "classification",
    "decision",
    "reasons",
    "approvals_required",
    "approvers",
    "args_hash",
    "outcome",
    "result_bytes",
    "duration_ms",
)


def emit(**event: Any) -> None:
    unknown = set(event) - set(FIELDS)
    if unknown:  # a typo here would silently drop an audit field
        raise ValueError(f"unknown audit fields: {sorted(unknown)}")
    record = {"ts": round(time.time(), 3), **event}
    _logger.info(json.dumps(record, sort_keys=True, default=str))
