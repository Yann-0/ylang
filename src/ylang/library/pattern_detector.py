"""Usage-based pattern detection for learned template proposals."""

from __future__ import annotations

import difflib
import hashlib
import re

from ylang.library.patterns import DetectedPattern, PatternDetector, TemplateProposal
from ylang.library.types import TemplateParam
from ylang.usage.store import UsageStore, UsageWindow

_MIN_OCCURRENCES = 3
_IMPROVE_ACTIVITY_PREFIX = "improve:"
_SIMILARITY_THRESHOLD = 0.85


class UsagePatternDetector(PatternDetector):
    """Detect repeated improver input texts from usage history."""

    def __init__(self, store: UsageStore) -> None:
        self._store = store

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        """Return prompt patterns seen at least three times in improver usage rows."""
        window = UsageWindow.last_days(window_days)
        rows = self._store.recall_usage(window)
        texts: list[str] = []
        for row in rows:
            if not row.improver_fired:
                continue
            if not row.activity.startswith(_IMPROVE_ACTIVITY_PREFIX):
                continue
            sample = row.improver_input_sample
            if sample:
                normalized = normalize_prompt_text(sample)
                if normalized:
                    texts.append(sample)
        clusters = cluster_prompt_texts(texts)
        patterns: list[DetectedPattern] = []
        for cluster in clusters:
            if len(cluster) < _MIN_OCCURRENCES:
                continue
            representative = cluster[0]
            pattern_id = pattern_id_from_text(representative)
            patterns.append(
                DetectedPattern(
                    pattern_id=pattern_id,
                    sample_text=representative,
                    occurrence_count=len(cluster),
                )
            )
        return sorted(patterns, key=lambda item: item.occurrence_count, reverse=True)


def normalize_prompt_text(text: str) -> str:
    """Lowercase and collapse whitespace for prompt similarity grouping."""
    return " ".join(text.lower().split())


def pattern_id_from_text(text: str) -> str:
    """Stable slug id from normalized prompt prefix."""
    normalized = normalize_prompt_text(text)
    prefix = normalized[:80]
    slug = re.sub(r"[^a-z0-9]+", "-", prefix).strip("-")
    if len(slug) >= 8:
        return slug[:48]
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:12]
    return f"prompt-{digest}"


def cluster_prompt_texts(texts: list[str]) -> list[list[str]]:
    """Group similar prompt texts using normalized difflib ratio."""
    clusters: list[list[str]] = []
    for text in texts:
        normalized = normalize_prompt_text(text)
        if not normalized:
            continue
        matched = False
        for cluster in clusters:
            representative = normalize_prompt_text(cluster[0])
            ratio = difflib.SequenceMatcher(None, normalized, representative).ratio()
            if ratio >= _SIMILARITY_THRESHOLD:
                cluster.append(text)
                matched = True
                break
        if not matched:
            clusters.append([text])
    return clusters


def propose_template_from_pattern(pattern: DetectedPattern) -> TemplateProposal | None:
    """Convert a detected pattern into a propose-only learned template."""
    if pattern.occurrence_count < _MIN_OCCURRENCES:
        return None
    template_id = f"learned-{pattern.pattern_id}"
    preview = pattern.sample_text[:120].replace("\n", " ")
    return TemplateProposal(
        suggested_template_id=template_id,
        name=f"Learned: {pattern.pattern_id.replace('-', ' ').title()}",
        body="Reuse the prompt pattern detected from your improver history:\n\n{sample}",
        params=[
            TemplateParam(
                name="sample",
                description="Example text from detected pattern",
                default=pattern.sample_text,
            )
        ],
        rationale=(
            f"Detected {pattern.occurrence_count} similar improver prompts "
            f"(e.g. \"{preview}\") in the last 30 days."
        ),
    )
