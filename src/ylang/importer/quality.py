"""Explainable static quality triage for public prompt candidates."""

from __future__ import annotations

import re

from ylang.importer.source_types import QualityReport, TaskFamily
from ylang.importer.taxonomy import classify_task_family

_OBJECTIVE = re.compile(
    r"\b(write|create|summarize|extract|analyze|explain|review|implement|"
    r"refactor|translate|classify|plan|debug|list|generate)\b",
    re.I,
)
_OUTPUT = re.compile(
    r"\b(output|format|json|markdown|return only|respond with|schema)\b",
    re.I,
)
_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|\$\{[^}]+\}")
_ACT_AS = re.compile(r"\bact as (a|an|the)\b", re.I)
_STALE_MODEL = re.compile(r"\b(gpt-3(\.5)?|text-davinci|claude-1|claude-2)\b", re.I)
_CONTRADICT = re.compile(r"\balways\b.{0,40}\bnever\b|\bnever\b.{0,40}\balways\b", re.I)


def score_prompt_quality(
    *,
    title: str,
    body: str,
    duplicate: bool = False,
    model_hint: str | None = None,
    metadata: dict[str, object] | None = None,
) -> QualityReport:
    """Return a 0–100 static quality score with reason codes.

    This is triage only. Measured operator outcomes outrank this score.
    """
    reasons: list[str] = []
    score = 40
    body_stripped = body.strip()
    if _OBJECTIVE.search(title) or _OBJECTIVE.search(body_stripped[:400]):
        score += 12
        reasons.append("objective_clarity")
    else:
        reasons.append("weak_objective")
    if _PLACEHOLDER.search(body_stripped):
        score += 10
        reasons.append("variables")
    else:
        reasons.append("no_placeholders")
    if _OUTPUT.search(body_stripped):
        score += 10
        reasons.append("output_contract")
    else:
        reasons.append("no_output_contract")
    if _ACT_AS.search(body_stripped) and len(body_stripped) < 280:
        score -= 12
        reasons.append("persona_fluff")
    if len(body_stripped) > 6000:
        score -= 15
        reasons.append("excessive_verbosity")
    elif len(body_stripped) < 40:
        score -= 10
        reasons.append("too_short")
    else:
        score += 6
        reasons.append("task_specificity")
    if _CONTRADICT.search(body_stripped):
        score -= 8
        reasons.append("contradiction")
    if _STALE_MODEL.search(body_stripped) or (
        model_hint and _STALE_MODEL.search(model_hint)
    ):
        score -= 8
        reasons.append("model_staleness")
    tools = (metadata or {}).get("tools")
    if tools:
        reasons.append("tool_assumptions")
        score -= 4
    if duplicate:
        score -= 20
        reasons.append("duplicate_penalty")
    score = max(0, min(100, score))
    family = classify_task_family(title=title, body=body, metadata=metadata)
    return QualityReport(score=score, reasons=tuple(reasons), task_family=family)


def quality_task_family(
    title: str,
    body: str,
    metadata: dict[str, object] | None = None,
) -> TaskFamily:
    """Classify a candidate into a stable Ylang task family."""
    return classify_task_family(title=title, body=body, metadata=metadata)
