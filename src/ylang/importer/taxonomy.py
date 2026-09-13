"""Stable task-family classification. Model names are never categories."""

from __future__ import annotations

import re
from typing import Any

from ylang.importer.source_types import TaskFamily

_RULES: tuple[tuple[TaskFamily, tuple[str, ...]], ...] = (
    ("debugging", ("debug", "stack trace", "traceback", "bugfix", "bug fix")),
    ("architecture", ("architecture", "system design", "adrs", "tradeoff")),
    ("evaluation", ("code review", "review this", "evaluate", "critique", "rubric")),
    ("summarization", ("summarize", "summary", "tldr", "tl;dr")),
    ("extraction", ("extract", "named entit", "pull out", "structured data")),
    ("transformation", ("translate", "convert", "rewrite as", "transform")),
    ("data-analysis", ("data analysis", "dataframe", "csv", "pandas", "sql query")),
    ("planning", ("plan", "roadmap", "step-by-step plan", "work breakdown")),
    ("reasoning", ("reason step", "chain of thought", "think step")),
    ("research", ("research", "search the web", "investigate", "literature")),
    ("writing", ("write a", "blog", "essay", "documentation", "copywriting")),
    (
        "agent-orchestration",
        ("orchestrat", "multi-agent", "tool calling", "function call"),
    ),
    ("code", ("code", "function", "refactor", "implement", "python", "typescript")),
)


def classify_task_family(
    *,
    title: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> TaskFamily:
    """Classify into a stable family. Upstream model/tool hints stay separate."""
    blob = f"{title}\n{body[:1500]}".lower()
    path = str((metadata or {}).get("path") or (metadata or {}).get("pattern") or "")
    path_l = path.lower()
    if "extract" in path_l:
        return "extraction"
    if "summar" in path_l:
        return "summarization"
    if any(part in path_l for part in ("prompt", "code", ".prompt.md")):
        if "review" in path_l or "review" in blob:
            return "evaluation"
        if "debug" in path_l:
            return "debugging"
    tools = (metadata or {}).get("tools")
    if tools:
        if re.search(r"\b(agent|orchestrat|multi-agent)\b", blob):
            return "agent-orchestration"
        return "code"
    for family, needles in _RULES:
        if any(needle in blob for needle in needles):
            return family
    return "other"
