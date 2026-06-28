"""Future detected-pattern → propose template hook (stub only)."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.library.types import TemplateParam


@dataclass(frozen=True, slots=True)
class DetectedPattern:
    """Placeholder shape for a future detected usage/text pattern."""

    pattern_id: str
    sample_text: str
    occurrence_count: int = 1


@dataclass(frozen=True, slots=True)
class TemplateProposal:
    """Propose-only output from future pattern detection (like improver)."""

    suggested_template_id: str
    name: str
    body: str
    params: list[TemplateParam]
    rationale: str


# ---------------------------------------------------------------------------
# STUB SEAM — Phase 2+
# Future: usage recall + text clustering detects repeated prompt shapes.
# A detector implements PatternDetector and registers via register_pattern_detector().
# On match, propose_template_from_pattern() returns a TemplateProposal;
# the face shows it to the user; on accept, Library.save(..., source="learned").
# DO NOT implement detection in Phase 1.
# ---------------------------------------------------------------------------


class PatternDetector:
    """Interface for a future pattern-detection backend."""

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        raise NotImplementedError("Pattern detection is not implemented in Phase 1.")


_PATTERN_DETECTOR: PatternDetector | None = None


def register_pattern_detector(detector: PatternDetector) -> None:
    """Attach a future detected-pattern → proposal pipeline."""
    global _PATTERN_DETECTOR
    _PATTERN_DETECTOR = detector


def propose_template_from_pattern(pattern: DetectedPattern) -> TemplateProposal | None:
    """STUB: returns None in Phase 1. Future hook converts patterns to propose-only templates."""
    _ = (_PATTERN_DETECTOR, pattern)
    return None
