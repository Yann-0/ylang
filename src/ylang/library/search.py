"""FTS5-backed template search with TF-IDF semantic fallback."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter

from ylang.library.types import TemplateSummary

_TOKEN_RE = re.compile(r"[a-z0-9']{3,}")


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


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _tfidf_score(query: str, document: str) -> float:
    """Return a simple TF-IDF cosine score between query and document."""
    query_tokens = _tokenize(query)
    doc_tokens = _tokenize(document)
    if not query_tokens or not doc_tokens:
        return 0.0
    query_tf = Counter(query_tokens)
    doc_tf = Counter(doc_tokens)
    doc_total = len(doc_tokens)
    scores: list[float] = []
    for token, q_count in query_tf.items():
        if token not in doc_tf:
            continue
        tf = doc_tf[token] / doc_total
        scores.append((q_count / len(query_tokens)) * tf)
    return sum(scores) / len(scores) if scores else 0.0


def search_templates_semantic(
    summaries: list[TemplateSummary],
    query: str,
    *,
    limit: int = 20,
    recall_body: callable,
) -> list[tuple[str, float]]:
    """Rank templates by TF-IDF overlap when FTS returns no hits."""
    ranked: list[tuple[str, float]] = []
    for summary in summaries:
        template = recall_body(summary.template_id)
        if template is None:
            continue
        document = " ".join(
            [summary.template_id, summary.name, template.body, *summary.tags]
        )
        score = _tfidf_score(query, document)
        if score > 0:
            ranked.append((summary.template_id, score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:limit]


def search_templates_hybrid(
    connection: sqlite3.Connection,
    query: str,
    *,
    summaries: list[TemplateSummary],
    recall_body: callable,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Try FTS first; fall back to TF-IDF semantic ranking."""
    hits = search_templates(connection, query, limit=limit)
    if hits:
        return hits
    return search_templates_semantic(
        summaries,
        query,
        limit=limit,
        recall_body=recall_body,
    )


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
