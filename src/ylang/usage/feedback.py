"""User edit feedback capture for prompt optimization."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from ylang.usage.store import _require_utc, _to_iso


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    """One captured user edit or feedback signal."""

    id: int
    timestamp: datetime
    event_type: str
    original_text: str | None
    submitted_text: str | None
    edit_distance: int | None
    usage_id: int | None
    metadata: dict[str, object]


def _levenshtein(left: str, right: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = prev[j] + 1
            replace_cost = prev[j - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        prev = current
    return prev[-1]


class FeedbackStore:
    """Persist prompt edit feedback events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_edit(
        self,
        *,
        original_text: str,
        submitted_text: str,
        usage_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FeedbackEvent:
        """Record a user edit between improved and submitted prompt text."""
        distance = _levenshtein(original_text.strip(), submitted_text.strip())
        return self._insert(
            event_type="prompt_edit",
            original_text=original_text,
            submitted_text=submitted_text,
            edit_distance=distance,
            usage_id=usage_id,
            metadata=metadata or {},
        )

    def _insert(
        self,
        *,
        event_type: str,
        original_text: str | None,
        submitted_text: str | None,
        edit_distance: int | None,
        usage_id: int | None,
        metadata: dict[str, object],
    ) -> FeedbackEvent:
        when = datetime.now(timezone.utc)
        cursor = self._connection.execute(
            """
            INSERT INTO feedback_events (
                timestamp, event_type, original_text, submitted_text,
                edit_distance, usage_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _to_iso(when),
                event_type,
                original_text,
                submitted_text,
                edit_distance,
                usage_id,
                json.dumps(metadata),
            ),
        )
        self._connection.commit()
        return FeedbackEvent(
            id=int(cursor.lastrowid),
            timestamp=when,
            event_type=event_type,
            original_text=original_text,
            submitted_text=submitted_text,
            edit_distance=edit_distance,
            usage_id=usage_id,
            metadata=metadata,
        )

    def recent(self, *, limit: int = 50) -> list[FeedbackEvent]:
        """Return newest feedback events."""
        cursor = self._connection.execute(
            """
            SELECT id, timestamp, event_type, original_text, submitted_text,
                   edit_distance, usage_id, metadata_json
            FROM feedback_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        events: list[FeedbackEvent] = []
        for row in cursor.fetchall():
            parsed = datetime.fromisoformat(str(row[1]))
            _require_utc(parsed)
            metadata_raw = row[7]
            metadata: dict[str, object] = {}
            if metadata_raw:
                loaded = json.loads(str(metadata_raw))
                if isinstance(loaded, dict):
                    metadata = loaded
            events.append(
                FeedbackEvent(
                    id=int(row[0]),
                    timestamp=parsed,
                    event_type=str(row[2]),
                    original_text=str(row[3]) if row[3] is not None else None,
                    submitted_text=str(row[4]) if row[4] is not None else None,
                    edit_distance=int(row[5]) if row[5] is not None else None,
                    usage_id=int(row[6]) if row[6] is not None else None,
                    metadata=metadata,
                )
            )
        return events
