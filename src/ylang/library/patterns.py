"""Future detected-pattern → propose template hook."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.library.types import TemplateParam


@dataclass(frozen=True, slots=True)
class DetectedPattern:
    """A detected usage/text pattern suitable for template learning."""

    pattern_id: str
    sample_text: str
    occurrence_count: int = 1


@dataclass(frozen=True, slots=True)
class TemplateProposal:
    """Propose-only output from pattern detection (like improver)."""

    suggested_template_id: str
    name: str
    body: str
    params: list[TemplateParam]
    rationale: str


class PatternDetector:
    """Interface for a pattern-detection backend."""

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        raise NotImplementedError("Register a PatternDetector via register_pattern_detector().")


_PATTERN_DETECTOR: PatternDetector | None = None


def register_pattern_detector(detector: PatternDetector) -> None:
    """Attach a detected-pattern → proposal pipeline."""
    global _PATTERN_DETECTOR
    _PATTERN_DETECTOR = detector


def propose_template_from_pattern(pattern: DetectedPattern) -> TemplateProposal | None:
    """Convert a detected pattern into a propose-only learned template."""
    from ylang.library.pattern_detector import propose_template_from_pattern as _propose

    return _propose(pattern)


def detect_patterns(*, window_days: int = 30) -> list[DetectedPattern]:
    """Run the registered pattern detector, or return an empty list."""
    if _PATTERN_DETECTOR is None:
        return []
    return _PATTERN_DETECTOR.detect(window_days=window_days)
