"""Synthetic in-memory systems behind the connectors. All people, places and records are invented. A production
connector replaces one of these classes with a client for the real system (a work-management API, an operations
warehouse, a mail service, a document store) and keeps the tool functions, manifest and policy as they are."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

ALLOWED_RECIPIENT_DOMAIN = "amazing-enterprise.example"
TICKET_STATUSES = ("draft", "open", "in_progress", "resolved")
AREAS = ("Harbor Coaster", "Lantern Gardens", "Riverside Rides", "Main Street Shops")


class NotFound(LookupError):
    pass


@dataclass
class TicketBackend:
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    _ids: Any = field(default_factory=lambda: itertools.count(1001))

    @classmethod
    def seeded(cls) -> TicketBackend:
        backend = cls()
        seed = [
            ("Harbor Coaster brake sensor alarm on train 2", "open", "Harbor Coaster"),
            ("Lantern Gardens path lighting out near east gate", "in_progress", "Lantern Gardens"),
            ("Riverside Rides queue display shows wrong wait time", "open", "Riverside Rides"),
            ("Main Street Shops card reader offline at register 4", "resolved", "Main Street Shops"),
            ("Harbor Coaster restraint check procedure update", "resolved", "Harbor Coaster"),
        ]
        for title, status, area in seed:
            backend._add(title, f"Synthetic ticket for {area}.", area, status)
        return backend

    def _add(self, title: str, body: str, area: str, status: str) -> dict[str, Any]:
        ticket = {"id": f"TCK-{next(self._ids)}", "title": title, "body": body, "area": area, "status": status}
        self.tickets[ticket["id"]] = ticket
        return ticket

    def search(self, query: str, status: str | None, limit: int) -> list[dict[str, Any]]:
        words = query.lower().split()
        hits = [
            t
            for t in self.tickets.values()
            if (not status or t["status"] == status) and all(w in (t["title"] + " " + t["area"]).lower() for w in words)
        ]
        return [{k: t[k] for k in ("id", "title", "status", "area")} for t in hits[:limit]]

    def get(self, ticket_id: str) -> dict[str, Any]:
        if ticket_id not in self.tickets:
            raise NotFound(ticket_id)
        return dict(self.tickets[ticket_id])

    def create_draft(self, title: str, body: str, area: str) -> dict[str, Any]:
        return dict(self._add(title, body, area, "draft"))

    def update_status(self, ticket_id: str, status: str) -> dict[str, Any]:
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            raise NotFound(ticket_id)
        ticket["status"] = status
        return dict(ticket)


@dataclass
class OpsBackend:
    """Operations figures. Downtime is internal; staffing and incident detail are confidential."""

    today: date = field(default_factory=date.today)

    def downtime(self, area: str, days: int) -> dict[str, Any]:
        seed = sum(ord(c) for c in area)
        daily = [
            {"date": str(self.today - timedelta(days=i)), "minutes_down": (seed + i * 7) % 41} for i in range(days)
        ]
        return {"area": area, "days": days, "total_minutes_down": sum(d["minutes_down"] for d in daily), "daily": daily}

    def staffing(self, area: str, day: str) -> dict[str, Any]:
        seed = sum(ord(c) for c in area) + sum(ord(c) for c in day)
        return {"area": area, "date": day, "scheduled": 8 + seed % 9, "on_call": 1 + seed % 3, "open_shifts": seed % 4}

    def incidents(self, area: str, days: int) -> list[dict[str, Any]]:
        seed = sum(ord(c) for c in area)
        return [
            {
                "date": str(self.today - timedelta(days=(seed + i * 3) % max(days, 1))),
                "area": area,
                "severity": ("low", "medium", "low")[i % 3],
                "summary": f"Synthetic incident {i + 1} in {area}: guest-safe stop, cleared after inspection.",
            }
            for i in range(2 + seed % 2)
        ]


@dataclass
class MessageBackend:
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    sent: list[dict[str, Any]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    @staticmethod
    def recipient_allowed(address: str) -> bool:
        _, _, domain = address.rpartition("@")
        return bool(domain) and domain.lower() == ALLOWED_RECIPIENT_DOMAIN

    def create_draft(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        draft = {"id": f"DRF-{next(self._ids)}", "to": list(to), "subject": subject, "body": body, "status": "draft"}
        self.drafts[draft["id"]] = draft
        return dict(draft)

    def send(self, draft_id: str) -> dict[str, Any]:
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise NotFound(draft_id)
        if draft["status"] == "sent":
            raise ValueError("this draft was already sent")
        draft["status"] = "sent"
        self.sent.append(dict(draft))
        return {"id": draft["id"], "status": "sent", "recipients": len(draft["to"])}


@dataclass
class FileBackend:
    files: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def seeded(cls) -> FileBackend:
        backend = cls()
        for path, classification, text in [
            ("/handbook/guest-policy.md", "public", "Guests may re-enter the park with a hand stamp."),
            ("/ops/shift-notes.md", "internal", "Harbor Coaster opens 30 minutes early on holiday weekends."),
            ("/finance/q3-forecast.md", "confidential", "Synthetic Q3 forecast: attendance up 4 percent on plan."),
            ("/hr/compensation-bands.md", "restricted", "Synthetic compensation bands for fictional job families."),
        ]:
            backend.files[path] = {"classification": classification, "content": text}
        return backend

    def classification_of(self, path: str) -> str:
        if path not in self.files:
            raise NotFound(path)
        return self.files[path]["classification"]

    def read(self, path: str) -> dict[str, str]:
        if path not in self.files:
            raise NotFound(path)
        return {"path": path, **self.files[path]}

    def list(self, folder: str) -> list[dict[str, str]]:
        prefix = folder.rstrip("/") + "/"
        return [
            {"path": p, "classification": f["classification"]}
            for p, f in sorted(self.files.items())
            if p.startswith(prefix)
        ]

    def write(self, path: str, content: str, classification: str) -> dict[str, Any]:
        self.files[path] = {"classification": classification, "content": content}
        return {"path": path, "classification": classification, "bytes": len(content.encode())}
