"""FTS5-backed template search."""

from __future__ import annotations

import sqlite3

from ylang.library.types import TemplateSummary


def ensure_fts_index(connection: sqlite3.Connection) -> None:
    """Create the FTS virtual table if missing (migration may have already)."""
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS templates_fts USING fts5(
            template_id UNINDEXED,
            name,
            body,
            tags,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )


def index_template(
    connection: sqlite3.Connection,
    *,
    template_id: str,
    name: str,
    body: str,
    tags: list[str],
) -> None:
    """Upsert one template row in the FTS index."""
    ensure_fts_index(connection)
    connection.execute(
        "DELETE FROM templates_fts WHERE template_id = ?",
        (template_id,),
    )
    connection.execute(
        """
        INSERT INTO templates_fts (template_id, name, body, tags)
        VALUES (?, ?, ?, ?)
        """,
        (template_id, name, body, " ".join(tags)),
    )


def search_templates(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Return ``(template_id, rank)`` pairs for an FTS query."""
    ensure_fts_index(connection)
    stripped = query.strip()
    if not stripped:
        return []
    cursor = connection.execute(
        """
        SELECT template_id, rank
        FROM templates_fts
        WHERE templates_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (stripped, limit),
    )
    return [(str(row[0]), float(row[1])) for row in cursor.fetchall()]


def rebuild_fts_from_library(
    connection: sqlite3.Connection,
    summaries: list[TemplateSummary],
    *,
    recall_body: callable,
) -> None:
    """Rebuild the FTS index from all templates (maintenance helper)."""
    ensure_fts_index(connection)
    connection.execute("DELETE FROM templates_fts")
    for summary in summaries:
        template = recall_body(summary.template_id)
        if template is None:
            continue
        index_template(
            connection,
            template_id=template.template_id,
            name=template.name,
            body=template.body,
            tags=list(template.tags),
        )
