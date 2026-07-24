"""Audit log for governed console apply actions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ApplyAuditEntry:
    """One recorded apply action."""

    id: int
    timestamp: datetime
    actor: str
    proposal_id: str
    action_type: str
    detail: str


class ApplyAuditStore:
    """Persist who applied which optimization proposal and when."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record(
        self,
        *,
        actor: str,
        proposal_id: str,
        action_type: str,
        detail: str,
    ) -> ApplyAuditEntry:
        """Insert one audit row and return the stored entry."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._connection.execute(
            """
            INSERT INTO apply_audit_log (timestamp, actor, proposal_id, action_type, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, actor, proposal_id, action_type, detail),
        )
        self._connection.commit()
        return ApplyAuditEntry(
            id=int(cursor.lastrowid or 0),
            timestamp=datetime.fromisoformat(now),
            actor=actor,
            proposal_id=proposal_id,
            action_type=action_type,
            detail=detail,
        )

    def recent(self, *, limit: int = 50) -> list[ApplyAuditEntry]:
        """Return the most recent audit entries."""
        cursor = self._connection.execute(
            """
            SELECT id, timestamp, actor, proposal_id, action_type, detail
            FROM apply_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        entries: list[ApplyAuditEntry] = []
        for row_id, ts, actor, proposal_id, action_type, detail in cursor.fetchall():
            entries.append(
                ApplyAuditEntry(
                    id=int(row_id),
                    timestamp=datetime.fromisoformat(str(ts)),
                    actor=str(actor),
                    proposal_id=str(proposal_id),
                    action_type=str(action_type),
                    detail=str(detail),
                )
            )
        return entries

    def applied_proposal_ids(self) -> set[str]:
        """Return distinct proposal ids that have already been applied."""
        cursor = self._connection.execute(
            "SELECT DISTINCT proposal_id FROM apply_audit_log"
        )
        return {str(row[0]) for row in cursor.fetchall()}
