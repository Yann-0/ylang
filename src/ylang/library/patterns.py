"""Pattern detection registry and propose-only learned-template types.

``UsagePatternDetector`` (see ``library/pattern_detector.py``) is registered at
MCP startup. MCP ``detect_patterns`` and ``ylang patterns suggest`` call
``detect_patterns()`` here.
"""

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


@dataclass(frozen=True, slots=True)
class PatternProposalOutcome:
    """Result of proposing a learned template from a detected pattern."""

    proposal: TemplateProposal | None
    skip_reason: str | None = None


class PatternDetector:
    """Interface for a pattern-detection backend."""

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        """Return detected patterns within the rolling lookback window."""
        raise NotImplementedError(
            "Register a PatternDetector via register_pattern_detector()."
        )


_PATTERN_DETECTOR: PatternDetector | None = None
_PATTERN_DETECTOR_STORE: object | None = None
_REGISTERED_MODE: str | None = None


def register_pattern_detector_store(store: object) -> None:
    """Remember the usage store for hot-reloading the pattern detector."""
    global _PATTERN_DETECTOR_STORE
    _PATTERN_DETECTOR_STORE = store


def register_pattern_detector(detector: PatternDetector) -> None:
    """Attach a detected-pattern → proposal pipeline."""
    global _PATTERN_DETECTOR
    _PATTERN_DETECTOR = detector


def _resolve_pattern_detector_mode() -> str:
    import os

    env_mode = os.environ.get("YLANG_PATTERN_DETECTOR", "lexical").strip().lower()
    if _PATTERN_DETECTOR_STORE is None:
        return env_mode
    from ylang.core.runtime_settings import RuntimeSettingsStore

    override = RuntimeSettingsStore(
        _PATTERN_DETECTOR_STORE._connection  # type: ignore[attr-defined]
    ).get("pattern_detector")
    if override and override.strip():
        return override.strip().lower()
    return env_mode


def ensure_pattern_detector() -> None:
    """Register or refresh the pattern detector from env and runtime settings."""
    global _REGISTERED_MODE
    if _PATTERN_DETECTOR_STORE is None:
        return
    mode = _resolve_pattern_detector_mode()
    if _PATTERN_DETECTOR is not None and mode == _REGISTERED_MODE:
        return
    from ylang.library.semantic_pattern_detector import create_pattern_detector

    register_pattern_detector(
        create_pattern_detector(_PATTERN_DETECTOR_STORE, mode=mode)  # type: ignore[arg-type]
    )
    _REGISTERED_MODE = mode


def propose_template_from_pattern(
    pattern: DetectedPattern,
    *,
    engine: object | None = None,
) -> TemplateProposal | None:
    """Convert a detected pattern into a propose-only learned template."""
    return propose_template_from_pattern_outcome(pattern, engine=engine).proposal


def propose_template_from_pattern_outcome(
    pattern: DetectedPattern,
    *,
    engine: object | None = None,
) -> PatternProposalOutcome:
    """Convert a detected pattern into a proposal outcome with skip reason."""
    from ylang.library.pattern_detector import (
        propose_template_from_pattern_outcome as _propose_outcome,
    )

    return _propose_outcome(pattern, engine=engine)  # type: ignore[arg-type]


def detect_patterns(*, window_days: int = 30) -> list[DetectedPattern]:
    """Run the registered pattern detector, or return an empty list."""
    ensure_pattern_detector()
    if _PATTERN_DETECTOR is None:
        return []
    return _PATTERN_DETECTOR.detect(window_days=window_days)
