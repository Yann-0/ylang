"""Validate improver outputs: anchors, numbers, modals, replay consistency."""

from __future__ import annotations

from collections import Counter
import logging
import re
from difflib import SequenceMatcher

from ylang.improver.reference import scrub_file_reference_numbers
from ylang.improver.registry import ResolvedCursorMode, detect_task_class
from ylang.improver.types import Change, ImprovementResult

logger = logging.getLogger(__name__)

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"clarity", "format", "constraint", "example", "scope"}
)

_NUMBER_RE = re.compile(r"\d+")

_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")

_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_DOUBLE_QUOTED_RE = re.compile(r'"[^"]*"')

_BACKTICK_QUOTED_RE = re.compile(r"`[^`]*`")

_SINGLE_QUOTED_RE = re.compile(r"(?<![\w])'[^']+'(?![\w])")

_MODAL_RE = re.compile(
    r"\b(must|should|shall|never|always|may|might|will|won't)\b", re.I
)

_SEQ_RE = re.compile(r"\b(first|then|before|after|finally)\b", re.I)

_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\be\.g\.\b|example", re.I)

_WORD_RE = re.compile(r"[a-z0-9']{4,}", re.I)

_FUZZY_BEFORE_RATIO = 0.62

_FUZZY_BEFORE_MEDIUM_RATIO = 0.55

_FUZZY_BEFORE_MEDIUM_MIN = 12

_FUZZY_BEFORE_MEDIUM_MAX = 80


def _safe_result(
    text: str,
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
    validated: bool = True,
    rejection_reason: str | None = None,
) -> ImprovementResult:
    return ImprovementResult(
        original=text,
        improved=text,
        changes=[],
        auto_apply_default=auto_apply_default,
        validated=validated,
        rejection_reason=rejection_reason,
        cursor_mode=resolved.mode,
        mode_source=resolved.source,
    )


def _has_scope_changes(changes: list[Change]) -> bool:
    return any(change.kind == "scope" for change in changes)


def _is_restructuring(original: str, improved: str, changes: list[Change]) -> bool:
    """Return True when the model substantially restructured the prompt."""
    if not original:
        return False
    if _has_scope_changes(changes):
        return True
    if any(change.kind == "format" for change in changes):
        return len(improved) > len(original) * 1.2
    return len(improved) > len(original) * 1.5


def _significant_words(text: str) -> set[str]:
    """Return lowercased tokens of four or more characters for intent matching."""
    return set(_WORD_RE.findall(text.lower()))


def _intent_preserved(original: str, improved: str, *, min_ratio: float = 0.55) -> bool:
    """Return True when improved text still reflects the original ask."""
    normalized_original = " ".join(original.split())
    normalized_improved = " ".join(improved.split())
    if normalized_original in normalized_improved:
        return True
    prefix_len = 80 if len(normalized_original) >= 200 else 40
    prefix = normalized_original[: min(len(normalized_original), prefix_len)]
    if prefix and normalized_improved.startswith(prefix):
        return True
    words = _significant_words(original)
    if not words:
        return True
    overlap = len(words & _significant_words(improved)) / len(words)
    return overlap >= min_ratio


def _has_structured_expansion(improved: str) -> bool:
    """Return True when improved text uses headings or list structure."""
    if "##" in improved:
        return True
    if improved.count("\n- ") >= 2:
        return True
    return improved.count("\n1.") >= 1


def _is_restructured_spec(original: str, improved: str) -> bool:
    """Return True when improved looks like a markdown agent spec."""
    if improved == original:
        return False
    if improved.count("##") >= 2:
        return True
    if improved.startswith("## ") or "\n## " in improved:
        return True
    growth_threshold = 1.1 if len(original) >= 300 else 1.2
    if len(improved) <= len(original) * growth_threshold:
        return False
    if len(original) >= 300 and _has_structured_expansion(improved):
        return True
    return False


def _is_minor_clarity_edit(original: str, improved: str) -> bool:
    """Return True for tiny typo/clarity fixes that must cite changes[]."""
    if _has_structured_expansion(improved) and not _has_structured_expansion(original):
        return False
    if improved.count("##") > original.count("##"):
        return False
    ratio = len(improved) / max(len(original), 1)
    if ratio > 1.2 or ratio < 0.8:
        return False
    orig_words = _significant_words(original)
    imp_words = _significant_words(improved)
    if len(orig_words.symmetric_difference(imp_words)) > 3:
        return False
    return True


def _validate(
    original: str,
    improved: str,
    changes: list[Change],
    auto_apply_default: bool,
    *,
    resolved: ResolvedCursorMode,
) -> tuple[ImprovementResult, bool]:
    """Run safety checks; fall back to original on failure."""
    if original == improved and not changes:
        return _safe_result(original, auto_apply_default, resolved=resolved), True
    if improved != original and not changes:
        from ylang.improver.salvage import _salvage_omitted_changes

        salvaged = _salvage_omitted_changes(
            original,
            improved,
            auto_apply_default,
            resolved=resolved,
        )
        if salvaged is not None:
            return salvaged, True
        return _safe_result(
            original,
            auto_apply_default,
            resolved=resolved,
            validated=False,
            rejection_reason="improved text changed but changes[] is empty",
        ), False
    reason = _validation_failure_reason(original, improved, changes, resolved=resolved)
    if reason is not None:
        return _safe_result(
            original,
            auto_apply_default,
            resolved=resolved,
            validated=False,
            rejection_reason=reason,
        ), False
    try:
        replayed = _replay(original, changes)
    except ValueError:
        if not _has_scope_changes(changes):
            return _safe_result(
                original,
                auto_apply_default,
                resolved=resolved,
                validated=False,
                rejection_reason="change replay failed without scope changes",
            ), False
        replayed = None
    if replayed is not None and replayed != improved:
        logger.debug(
            "improve_prompt: improved differs from replay (%r vs %r); accepting improved",
            replayed,
            improved,
        )
    return ImprovementResult(
        original=original,
        improved=improved,
        changes=changes,
        auto_apply_default=auto_apply_default,
        validated=True,
        rejection_reason=None,
        cursor_mode=resolved.mode,
        mode_source=resolved.source,
    ), True


def _validation_failure_reason(
    original: str,
    improved: str,
    changes: list[Change],
    *,
    resolved: ResolvedCursorMode,
) -> str | None:
    """Return a short reason when validation fails, else None."""
    if improved != original and not changes:
        return "improved text changed but changes[] is empty"
    if not _length_ok(original, improved, changes, resolved=resolved):
        return "length ratio out of bounds"
    if not _numbers_preserved(original, improved):
        return "numbers changed"
    if not _quoted_spans_preserved(original, improved):
        return "quoted spans changed"
    restructuring = _is_restructuring(original, improved, changes)
    if not restructuring:
        if not _modals_preserved(original, improved):
            return "modal verbs changed"
        if not _sequencing_preserved(original, improved, changes):
            return "sequencing words changed"
    for change in changes:
        if change.kind not in _ALLOWED_KINDS:
            return f"invalid change kind: {change.kind}"
        if not _change_before_valid(original, change):
            return "change.before not anchored to original"
        if change.kind == "example" and not _PLACEHOLDER_RE.search(change.after):
            return "example change missing placeholder"
    if not _scope_preserves_intent(original, improved, changes):
        return "scope expansion dropped original intent"
    return None


def _normalize_ws(text: str) -> str:
    """Collapse whitespace for fuzzy substring anchoring."""
    return " ".join(text.split())


def _fuzzy_before_threshold(before_len: int) -> float:
    """Return SequenceMatcher ratio threshold for a ``before`` span length."""
    if _FUZZY_BEFORE_MEDIUM_MIN <= before_len <= _FUZZY_BEFORE_MEDIUM_MAX:
        return _FUZZY_BEFORE_MEDIUM_RATIO
    return _FUZZY_BEFORE_RATIO


def _fuzzy_before_in_original(original: str, before: str) -> bool:
    """Return True when ``before`` approximately matches a span of ``original``."""
    collapsed_before = _normalize_ws(before)
    collapsed_orig = _normalize_ws(original)
    if not collapsed_before or len(collapsed_before) < 4:
        return False
    if collapsed_before in collapsed_orig:
        return True
    # Case-insensitive containment after whitespace normalize.
    if collapsed_before.casefold() in collapsed_orig.casefold():
        return True
    before_words = _significant_words(before)
    if before_words:
        overlap = len(before_words & _significant_words(original)) / len(before_words)
        if overlap >= 0.55:
            return True
    # Sliding-window similarity for clarity/format anchors (looser for medium spans).
    window = len(collapsed_before)
    threshold = _fuzzy_before_threshold(window)
    folded_before = collapsed_before.casefold()
    folded_orig = collapsed_orig.casefold()
    if window > len(folded_orig):
        return SequenceMatcher(None, folded_before, folded_orig).ratio() >= threshold
    best = 0.0
    step = max(1, window // 4)
    for start in range(0, len(folded_orig) - window + 1, step):
        chunk = folded_orig[start : start + window]
        best = max(best, SequenceMatcher(None, folded_before, chunk).ratio())
        if best >= threshold:
            return True
    return False


def _change_before_valid(original: str, change: Change) -> bool:
    """Return True when change.before anchors to the original text.

    Accepts exact substring matches, whitespace-normalized containment, fuzzy
    span matches, and scope changes whose ``before`` still reflects the original
    ask (models often paraphrase the full prompt as before).
    """
    if change.kind == "scope" and change.before.strip() == original.strip():
        return True
    if not change.before:
        return False
    if change.before in original:
        return True
    collapsed_before = _normalize_ws(change.before)
    collapsed_orig = _normalize_ws(original)
    if collapsed_before and collapsed_before in collapsed_orig:
        return True
    if collapsed_before and collapsed_before.casefold() in collapsed_orig.casefold():
        return True
    if _fuzzy_before_in_original(original, change.before):
        return True
    # Non-scope paraphrases of the full ask (common with small models).
    if len(change.before.strip()) >= 12 and len(change.before) <= max(
        80, int(len(original) * 1.35)
    ):
        if _intent_preserved(original, change.before, min_ratio=0.5):
            return True
    if change.kind == "scope" and len(change.before.strip()) >= 8:
        return _intent_preserved(original, change.before, min_ratio=0.45)
    return False


def _scope_preserves_intent(
    original: str, improved: str, changes: list[Change]
) -> bool:
    """Ensure scope expansions keep the original ask visible in improved."""
    if not _has_scope_changes(changes):
        return True
    if any(
        change.kind == "scope" and change.before.strip() == original.strip()
        for change in changes
    ):
        return True
    min_ratio = 0.35 if len(original) >= 200 else 0.45
    return _intent_preserved(original, improved, min_ratio=min_ratio)


def _length_ok(
    original: str,
    improved: str,
    changes: list[Change],
    *,
    resolved: ResolvedCursorMode,
) -> bool:
    """Allow generous growth for spec rewrites; keep tight bounds for minor edits."""
    if not original:
        return True
    if len(improved) > 16_000:
        return False
    ratio = len(improved) / len(original)
    task_class = detect_task_class(original)
    structured_expansion = _has_structured_expansion(
        improved
    ) and not _has_structured_expansion(original)
    restructuring = (
        _is_restructuring(original, improved, changes)
        or _is_restructured_spec(original, improved)
        or structured_expansion
    )
    if restructuring or task_class == "analysis" or resolved.mode == "plan":
        max_ratio = min(16_000 / len(original), 200.0)
        min_ratio = 0.2 if len(original) < 80 else 0.35
        return min_ratio <= ratio <= max_ratio
    if len(original) < 80:
        # Minor clarity edits can shorten informal prompts (e.g. "let's do all" → "do all").
        min_ratio = 0.25 if changes else 0.5
        return min_ratio <= ratio <= 3.0
    return 0.8 <= ratio <= 1.5


def _extract_numbers(text: str) -> list[str]:
    """Extract numeric literals, ignoring timestamps, HTML comments, and list markers."""
    scrubbed = _HTML_COMMENT_RE.sub("", text)
    scrubbed = _ISO_TIMESTAMP_RE.sub("", scrubbed)
    scrubbed = _LIST_MARKER_RE.sub("", scrubbed)
    scrubbed = re.sub(r"(?m)^#+\s*\d+[.)]\s+", "", scrubbed)
    return _NUMBER_RE.findall(scrubbed.replace(",", ""))


def _substantive_numbers(text: str) -> set[str]:
    """Return numeric literals that must survive restructuring (exclude list markers)."""
    return set(_extract_numbers(scrub_file_reference_numbers(text)))


def _substantive_numbers_preserved(original: str, improved: str) -> bool:
    """Ensure substantive numeric literals from the original appear in improved."""
    orig_nums = _substantive_numbers(original)
    if not orig_nums:
        return True
    imp_nums = set(_extract_numbers(improved))
    return orig_nums <= imp_nums


def _numbers_preserved(original: str, improved: str) -> bool:
    """Ensure every substantive numeric literal from the original still appears in improved.

    Ordered-list markers (``1.``, ``2)``) and numbered headings are ignored so
    restructuring into a different outline does not false-positive as ``numbers changed``.
    """
    return _substantive_numbers_preserved(original, improved)


def _extract_quoted_spans(text: str) -> list[str]:
    """Extract double-quoted, backtick, and single-quoted spans (not contractions)."""
    spans: list[str] = []
    spans.extend(_DOUBLE_QUOTED_RE.findall(text))
    spans.extend(_BACKTICK_QUOTED_RE.findall(text))
    spans.extend(_SINGLE_QUOTED_RE.findall(text))
    return spans


def _quoted_spans_preserved(original: str, improved: str) -> bool:
    """Ensure quoted/backtick spans from the original still appear in improved."""
    orig = Counter(_extract_quoted_spans(original))
    if not orig:
        return True
    imp = Counter(_extract_quoted_spans(improved))
    return all(imp[span] >= count for span, count in orig.items())


def _modals_preserved(original: str, improved: str) -> bool:
    orig = [word.lower() for word in _MODAL_RE.findall(original)]
    imp = [word.lower() for word in _MODAL_RE.findall(improved)]
    return sorted(orig) == sorted(imp)


def _sequencing_preserved(
    original: str,
    improved: str,
    changes: list[Change],
) -> bool:
    orig = [word.lower() for word in _SEQ_RE.findall(original)]
    imp = [word.lower() for word in _SEQ_RE.findall(improved)]
    if sorted(orig) == sorted(imp):
        return True
    return all(change.kind in ("format", "scope") for change in changes)


def _replay(original: str, changes: list[Change]) -> str:
    result = original
    non_scope = [change for change in changes if change.kind != "scope"]
    ordered = sorted(
        non_scope,
        key=lambda change: (len(change.before), original.find(change.before)),
    )
    for change in ordered:
        if change.before not in result:
            msg = "change.before not found during replay"
            raise ValueError(msg)
        result = result.replace(change.before, change.after, 1)
    for change in changes:
        if change.kind == "scope" and change.before == original:
            result = change.after
            break
    return result

