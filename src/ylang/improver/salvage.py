"""Salvage and fallback paths when improver validation or parse fails."""

from __future__ import annotations

import logging
import re

from ylang.improver.parse import _is_model_prose_response, _try_parse_plain_spec
from ylang.improver.registry import ResolvedCursorMode
from ylang.improver.types import Change, ImprovementResult
from ylang.improver.validate import (
    _has_structured_expansion,
    _intent_preserved,
    _is_minor_clarity_edit,
    _is_restructuring,
    _is_restructured_spec,
    _length_ok,
    _modals_preserved,
    _numbers_preserved,
    _quoted_spans_preserved,
    _safe_result,
    _substantive_numbers_preserved,
)

logger = logging.getLogger(__name__)

_ANCHOR_SALVAGE_REASONS: frozenset[str] = frozenset(
    {
        "change.before not anchored to original",
        "change replay failed without scope changes",
        "example change missing placeholder",
    }
)

_SALVAGE_VALIDATION_REASONS: frozenset[str] = frozenset(
    {
        "numbers changed",
        "improved text changed but changes[] is empty",
        "change.before not anchored to original",
        "change replay failed without scope changes",
        "example change missing placeholder",
    }
)

_SALVAGE_MODES: frozenset[str] = frozenset({"agent", "multitask", "debug", "plan"})

_SHORT_PROMPT_MAX_LEN = 50

_TIMEOUT_FALLBACK_MAX_LEN = 200

_FALLBACK_REJECTION_REASONS: frozenset[str] = frozenset({"length ratio out of bounds"})

_VAGUE_SHORT_PROMPT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(let'?s\s+)?(do|finish|complete|fix|ship)\s+(all|everything|it|this|them)\.?$",
        re.I,
    ),
    re.compile(
        r"^(what\s+(should|shall)\s+we\s+do|what\s+next|next\s+steps?)\??$", re.I
    ),
    re.compile(r"^(go|continue|proceed)\.?$", re.I),
)


def _try_salvage_parse_failure(
    original: str,
    raw: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
) -> ImprovementResult | None:
    """Salvage structured output when JSON parsing fails."""
    if _is_model_prose_response(raw):
        return _safe_result(original, auto_apply_default, resolved=resolved)
    plain = _try_parse_plain_spec(raw)
    if plain is None:
        return None
    if not _numbers_preserved(original, plain) or not _quoted_spans_preserved(
        original, plain
    ):
        return None
    if _is_restructured_spec(original, plain):
        return _salvage_result(
            original,
            plain,
            auto_apply_default,
            resolved=resolved,
            description="Salvaged markdown spec from non-JSON model output",
        )
    return _try_salvage(original, plain, auto_apply_default, resolved=resolved)


def _salvage_omitted_changes(
    original: str,
    improved: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
) -> ImprovementResult | None:
    """Accept safe model output when the model omitted changes[]."""
    if improved.strip() == original.strip():
        return None
    minor_clarity = _is_minor_clarity_edit(original, improved)
    structured = _has_structured_expansion(improved) and not _has_structured_expansion(
        original
    )
    restructuring = _is_restructured_spec(original, improved) or structured
    if minor_clarity:
        if not _numbers_preserved(original, improved):
            return None
        if not _quoted_spans_preserved(original, improved):
            return None
        if not _modals_preserved(original, improved):
            return None
        if not _length_ok(original, improved, [], resolved=resolved):
            return None
        return _salvage_result(
            original,
            improved,
            auto_apply_default,
            resolved=resolved,
            description="Accepted minor clarity edit with omitted changes[]",
        )
    if restructuring:
        min_ratio = 0.2 if len(original) >= 200 else 0.3
    elif len(original) >= 200:
        min_ratio = 0.25
    else:
        min_ratio = 0.45
    if not _intent_preserved(original, improved, min_ratio=min_ratio):
        return None
    if not _numbers_preserved(original, improved):
        return None
    if not _quoted_spans_preserved(original, improved):
        return None
    if not restructuring and not _modals_preserved(original, improved):
        return None
    if not _length_ok(original, improved, [], resolved=resolved):
        return None
    description = (
        "Accepted restructured spec with omitted changes[]"
        if restructuring
        else "Accepted model output with omitted changes[]"
    )
    return _salvage_result(
        original,
        improved,
        auto_apply_default,
        resolved=resolved,
        description=description,
    )


def _salvage_result(
    original: str,
    improved: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
    description: str = "Restructured prompt into agent spec sections",
) -> ImprovementResult:
    """Build a validated salvage result for a restructured model output."""
    return ImprovementResult(
        original=original,
        improved=improved,
        changes=[
            Change(
                kind="scope",
                description=description,
                before=original,
                after=improved,
            )
        ],
        auto_apply_default=auto_apply_default,
        validated=True,
        rejection_reason=None,
        cursor_mode=resolved.mode,
        mode_source=resolved.source,
    )


def _try_salvage(
    original: str,
    improved: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
) -> ImprovementResult | None:
    """Accept a restructured spec when strict change validation is too brittle."""
    if improved == original:
        return None
    structured = _has_structured_expansion(improved)
    restructuring = _is_restructured_spec(original, improved) or (
        structured and not _has_structured_expansion(original)
    )
    if restructuring:
        min_ratio = 0.2 if len(original) >= 200 else 0.3
    elif len(original) >= 200:
        min_ratio = 0.25
    else:
        min_ratio = 0.4
    if not _intent_preserved(original, improved, min_ratio=min_ratio):
        return None
    if not _numbers_preserved(original, improved):
        return None
    if not _quoted_spans_preserved(original, improved):
        return None
    if restructuring:
        return _salvage_result(
            original, improved, auto_apply_default, resolved=resolved
        )
    if resolved.mode in _SALVAGE_MODES:
        if len(improved) >= len(original) * 1.05 and structured:
            return _salvage_result(
                original,
                improved,
                auto_apply_default,
                resolved=resolved,
                description="Salvaged structured expansion for agent prompt",
            )
    return None


def _try_salvage_validation_failure(
    original: str,
    improved: str,
    changes: list[Change],
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
    rejection_reason: str,
) -> ImprovementResult | None:
    """Salvage safe model output for common validation false positives."""
    if rejection_reason in {
        "improved text changed but changes[] is empty",
        "change.before not anchored to original",
        "change replay failed without scope changes",
        "example change missing placeholder",
    }:
        return _salvage_omitted_changes(
            original, improved, auto_apply_default, resolved=resolved
        ) or _try_salvage(original, improved, auto_apply_default, resolved=resolved)
    if rejection_reason != "numbers changed":
        return None
    if not _substantive_numbers_preserved(original, improved):
        return None
    if not _quoted_spans_preserved(original, improved):
        return None
    if not _modals_preserved(original, improved):
        return None
    restructuring = _is_restructuring(original, improved, changes) or _is_restructured_spec(
        original, improved
    )
    min_ratio = 0.25 if len(original) >= 200 else 0.45
    if not _intent_preserved(original, improved, min_ratio=min_ratio):
        return None
    if not _length_ok(original, improved, changes, resolved=resolved):
        return None
    description = (
        "Salvaged restructured output after numbers-changed false positive"
        if restructuring
        else "Salvaged safe edit after numbers-changed false positive"
    )
    return _salvage_result(
        original,
        improved,
        auto_apply_default,
        resolved=resolved,
        description=description,
    )


def _is_vague_short_prompt(text: str) -> bool:
    """Return True for underspecified short asks that need a spec skeleton."""
    stripped = text.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _VAGUE_SHORT_PROMPT_RES)


def _fallback_short_prompt_expansion(
    original: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
    require_vague: bool = False,
    max_len: int = _SHORT_PROMPT_MAX_LEN,
) -> ImprovementResult | None:
    """Build a deterministic spec skeleton for short / underspecified prompts."""
    stripped = original.strip()
    if not stripped or len(stripped) > max_len:
        return None
    if require_vague and not _is_vague_short_prompt(stripped):
        return None
    if resolved.mode in ("ask", "plan"):
        improved = (
            f"## Question\n{original.strip()}\n\n"
            "## Context\n- Expand only what the user asked; do not invent scope.\n\n"
            "## Answer format\n- Direct, concise response"
        )
    elif resolved.mode == "debug":
        improved = (
            f"## Symptom\n{original.strip()}\n\n"
            "## Investigation plan\n"
            "- Reproduce and isolate the failure\n"
            "- Confirm root cause before fixing\n\n"
            "## Success criteria\n- Issue resolved with evidence"
        )
    elif resolved.mode == "multitask":
        improved = (
            f"## Goal\n{original.strip()}\n\n"
            "## Workstreams\n"
            "1. Inventory all work implied by the request\n"
            "2. Execute remaining items in parallel where safe\n\n"
            "## Dependencies\n"
            "- Resolve ambiguous items before parallel execution\n\n"
            "## Definition of done\n"
            "- All implied work complete"
        )
    else:
        improved = (
            f"## Goal\n{original.strip()}\n\n"
            "## Deliverables\n"
            "- Complete all work implied by the request\n\n"
            "## Test plan\n"
            "- Run relevant tests and lint/typecheck when code changes\n\n"
            "## Definition of done\n"
            "- Request fully satisfied with evidence"
        )
    return _salvage_result(
        original,
        improved,
        auto_apply_default,
        resolved=resolved,
        description="Deterministic expansion for short vague prompt",
    )

