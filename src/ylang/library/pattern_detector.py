"""Usage-based pattern detection for learned template proposals."""

from __future__ import annotations

import re
from collections import Counter

from ylang.library.patterns import DetectedPattern, PatternDetector, TemplateProposal
from ylang.library.types import TemplateParam
from ylang.usage.store import UsageStore, UsageWindow

_MIN_OCCURRENCES = 3
_IMPROVE_ACTIVITY_PREFIX = "improve:"


class UsagePatternDetector(PatternDetector):
    """Detect repeated improver input texts from usage history."""

    def __init__(self, store: UsageStore) -> None:
        self._store = store

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        """Return patterns seen at least three times in improver usage rows."""
        window = UsageWindow.last_days(window_days)
        rows = self._store.recall_usage(window)
        texts: list[str] = []
        for row in rows:
            if not row.improver_fired:
                continue
            if not row.activity.startswith(_IMPROVE_ACTIVITY_PREFIX):
                continue
            normalized = _normalize_text(row.activity)
            if normalized:
                texts.append(normalized)
        counts = Counter(texts)
        patterns: list[DetectedPattern] = []
        for pattern_id, count in counts.items():
            if count >= _MIN_OCCURRENCES:
                patterns.append(
                    DetectedPattern(
                        pattern_id=pattern_id,
                        sample_text=pattern_id,
                        occurrence_count=count,
                    )
                )
        return sorted(patterns, key=lambda item: item.occurrence_count, reverse=True)


def _normalize_text(activity: str) -> str:
    """Extract a stable key from an improve:* activity string."""
    tool = activity.removeprefix(_IMPROVE_ACTIVITY_PREFIX)
    slug = re.sub(r"[^a-z0-9]+", "-", tool.lower()).strip("-")
    return slug or ""


def propose_template_from_pattern(pattern: DetectedPattern) -> TemplateProposal | None:
    """Convert a detected pattern into a propose-only learned template."""
    if pattern.occurrence_count < _MIN_OCCURRENCES:
        return None
    template_id = f"learned-{pattern.pattern_id}"
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
            f"Detected {pattern.occurrence_count} improver calls for tool "
            f"'{pattern.pattern_id}' in the last 30 days."
        ),
    )
