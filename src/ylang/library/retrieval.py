"""Score and select reference prompts from the local library."""

from __future__ import annotations

import re
import sqlite3

from ylang.library.effectiveness import (
    blend_retrieval_score,
    retrieval_blocked_template_ids,
)
from ylang.library.search import search_templates_hybrid
from ylang.library.store import Library
from ylang.library.types import TemplateSummary
from ylang.usage.store import UsageStore

_WORD_RE = re.compile(r"\w+")
_LINKED_SKILL_BOOST = 4
_MAX_LINKED_SKILL_INJECTIONS = 2


def _keywords(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _WORD_RE.finditer(text)
        if len(match.group(0)) > 2
    }


def _template_keywords(summary: TemplateSummary) -> set[str]:
    parts = [summary.template_id, summary.name, *summary.tags]
    keywords: set[str] = set()
    for part in parts:
        keywords.update(_keywords(part.replace("-", " ")))
    return keywords


def _fts_query(text: str, tool: str) -> str:
    tokens = sorted(_keywords(text) | _keywords(tool) | _keywords(tool.replace("_", " ")))
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def _provenance_linked_template_ids(connection: sqlite3.Connection) -> frozenset[str]:
    if not connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='template_provenance'"
    ).fetchone():
        return frozenset()
    rows = connection.execute(
        "SELECT DISTINCT template_id FROM template_provenance"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def _fts_rank_map(
    library: Library,
    summaries: list[TemplateSummary],
    text: str,
    tool: str,
) -> dict[str, float]:
    query = _fts_query(text, tool)
    if not query:
        return {}
    hits = search_templates_hybrid(
        library._connection,
        query,
        summaries=summaries,
        recall_body=library.recall,
        limit=max(20, len(summaries)),
    )
    if not hits:
        return {}
    return {template_id: max(0.0, -rank) for template_id, rank in hits}


def _score_template(
    summary: TemplateSummary,
    text: str,
    tool: str,
    cursor_mode: str | None,
    *,
    effectiveness: dict[str, float] | None = None,
    weight: float = 0.5,
    preferred_ids: frozenset[str] | None = None,
    linked_skill_ids: frozenset[str] | None = None,
    fts_rank: float = 0.0,
) -> tuple[float, int]:
    """Return (score, public_tiebreak) for ranking."""
    score = 0
    if preferred_ids and summary.template_id in preferred_ids:
        score += 5
    if linked_skill_ids and summary.template_id in linked_skill_ids:
        score += _LINKED_SKILL_BOOST
    if cursor_mode and (
        cursor_mode == summary.template_id or cursor_mode in summary.tags
    ):
        score += 4
    if tool == summary.template_id or tool in summary.tags:
        score += 3
    text_keywords = _keywords(text)
    overlap = text_keywords & _template_keywords(summary)
    score += 2 * len(overlap)
    if fts_rank > 0:
        score += int(min(6.0, fts_rank * 2.0))
    blended = blend_retrieval_score(
        score,
        summary.template_id,
        effectiveness or {},
        weight=weight,
    )
    public_tiebreak = 1 if summary.visibility == "public" else 0
    return blended, public_tiebreak


def _exclude_retrieval_blocked_templates(
    summaries: list[TemplateSummary],
    *,
    effectiveness: dict[str, float] | None = None,
    store: UsageStore | None = None,
) -> list[TemplateSummary]:
    """Drop zero-accept templates (min samples) and other retrieval blocks."""
    blocked = retrieval_blocked_template_ids(store, effectiveness)
    if not blocked:
        return summaries
    return [summary for summary in summaries if summary.template_id not in blocked]


def select_learned_templates(
    library: Library,
    *,
    limit: int = 2,
    max_chars: int = 4000,
    effectiveness: dict[str, float] | None = None,
    weight: float = 0.5,
    store: UsageStore | None = None,
) -> list[TemplateSummary]:
    """Return learned templates ranked by effectiveness or recency."""
    summaries = _exclude_retrieval_blocked_templates(
        library.list(source="learned"),
        effectiveness=effectiveness,
        store=store,
    )
    if effectiveness:
        ranked = sorted(
            summaries,
            key=lambda item: (
                effectiveness.get(item.template_id, 0.0),
                item.updated_at.timestamp(),
            ),
            reverse=True,
        )
    else:
        ranked = sorted(summaries, key=lambda item: item.updated_at, reverse=True)
    selected: list[TemplateSummary] = []
    used_chars = 0
    for summary in ranked:
        if len(selected) >= limit:
            break
        template = library.recall(summary.template_id)
        if template is None:
            continue
        entry_len = (
            len(template.body) + len(summary.template_id) + len(summary.name) + 32
        )
        if used_chars + entry_len > max_chars and selected:
            break
        selected.append(summary)
        used_chars += entry_len
    return selected


def select_reference_prompts(
    library: Library,
    text: str,
    tool: str,
    *,
    cursor_mode: str | None = None,
    limit: int = 3,
    max_chars: int = 4000,
    effectiveness: dict[str, float] | None = None,
    weight: float = 0.5,
    store: UsageStore | None = None,
    preferred_ids: frozenset[str] | None = None,
    linked_skill_ids: frozenset[str] | None = None,
    max_skill_injections: int = _MAX_LINKED_SKILL_INJECTIONS,
) -> list[TemplateSummary]:
    """Return top-scoring library prompts within a character budget."""
    summaries = _exclude_retrieval_blocked_templates(
        library.list(),
        effectiveness=effectiveness,
        store=store,
    )
    linked = linked_skill_ids
    if linked is None:
        linked = _provenance_linked_template_ids(library._connection)
    fts_ranks = _fts_rank_map(library, summaries, text, tool)
    ranked = sorted(
        summaries,
        key=lambda summary: _score_template(
            summary,
            text,
            tool,
            cursor_mode,
            effectiveness=effectiveness,
            weight=weight,
            preferred_ids=preferred_ids,
            linked_skill_ids=linked,
            fts_rank=fts_ranks.get(summary.template_id, 0.0),
        ),
        reverse=True,
    )
    selected: list[TemplateSummary] = []
    used_chars = 0
    skill_injected = 0
    skill_cap = max(1, min(max_skill_injections, limit))
    for summary in ranked:
        if len(selected) >= limit:
            break
        score, _ = _score_template(
            summary,
            text,
            tool,
            cursor_mode,
            effectiveness=effectiveness,
            weight=weight,
            preferred_ids=preferred_ids,
            linked_skill_ids=linked,
            fts_rank=fts_ranks.get(summary.template_id, 0.0),
        )
        if score <= 0 and selected:
            break
        is_linked_skill = linked and summary.template_id in linked
        if is_linked_skill and skill_injected >= skill_cap:
            continue
        template = library.recall(summary.template_id)
        if template is None:
            continue
        entry_len = (
            len(template.body) + len(summary.template_id) + len(summary.name) + 32
        )
        remaining = max_chars - used_chars
        if entry_len > remaining:
            continue
        selected.append(summary)
        used_chars += entry_len
        if is_linked_skill:
            skill_injected += 1
    return selected