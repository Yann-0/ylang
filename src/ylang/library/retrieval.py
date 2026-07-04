"""Score and select reference prompts from the local library."""

from __future__ import annotations

import re

from ylang.library.store import Library
from ylang.library.types import TemplateSummary

_WORD_RE = re.compile(r"\w+")


def _keywords(text: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD_RE.finditer(text) if len(match.group(0)) > 2}


def _template_keywords(summary: TemplateSummary) -> set[str]:
    parts = [summary.template_id, summary.name, *summary.tags]
    keywords: set[str] = set()
    for part in parts:
        keywords.update(_keywords(part.replace("-", " ")))
    return keywords


def _score_template(
    summary: TemplateSummary,
    text: str,
    tool: str,
    cursor_mode: str | None,
) -> tuple[int, int]:
    """Return (score, public_tiebreak) for ranking."""
    score = 0
    if cursor_mode and (cursor_mode == summary.template_id or cursor_mode in summary.tags):
        score += 4
    if tool == summary.template_id or tool in summary.tags:
        score += 3
    text_keywords = _keywords(text)
    overlap = text_keywords & _template_keywords(summary)
    score += 2 * len(overlap)
    public_tiebreak = 1 if summary.visibility == "public" else 0
    return score, public_tiebreak


def select_learned_templates(
    library: Library,
    *,
    limit: int = 2,
    max_chars: int = 4000,
) -> list[TemplateSummary]:
    """Return recently updated learned templates for improver context."""
    summaries = library.list(source="learned")
    ranked = sorted(summaries, key=lambda item: item.updated_at, reverse=True)
    selected: list[TemplateSummary] = []
    used_chars = 0
    for summary in ranked:
        if len(selected) >= limit:
            break
        template = library.recall(summary.template_id)
        if template is None:
            continue
        entry_len = len(template.body) + len(summary.template_id) + len(summary.name) + 32
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
) -> list[TemplateSummary]:
    """Return top-scoring library prompts within a character budget."""
    summaries = library.list()
    ranked = sorted(
        summaries,
        key=lambda summary: _score_template(summary, text, tool, cursor_mode),
        reverse=True,
    )
    selected: list[TemplateSummary] = []
    used_chars = 0
    for summary in ranked:
        if len(selected) >= limit:
            break
        score, _ = _score_template(summary, text, tool, cursor_mode)
        if score <= 0 and selected:
            break
        template = library.recall(summary.template_id)
        if template is None:
            continue
        entry_len = len(template.body) + len(summary.template_id) + len(summary.name) + 32
        remaining = max_chars - used_chars
        if entry_len > remaining:
            continue
        selected.append(summary)
        used_chars += entry_len
    return selected
