"""Propose-only prompt improvement via the core engine."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter

from ylang.core.engine import Engine
from ylang.improver.context import ImproveContext, _EMPTY_CONVERSATION
from ylang.improver.registry import (
    ResolvedCursorMode,
    default_auto_apply,
    mode_guidance,
    resolve_cursor_mode,
)
from ylang.improver.reference import is_reference_only_prompt, scrub_file_reference_numbers
from ylang.improver.types import Change, ImprovementResult

logger = logging.getLogger(__name__)

_ALLOWED_KINDS: frozenset[str] = frozenset(
    {"clarity", "format", "constraint", "example", "scope"}
)
_NUMBER_RE = re.compile(r"\d+")
_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DOUBLE_QUOTED_RE = re.compile(r'"[^"]*"')
_BACKTICK_QUOTED_RE = re.compile(r"`[^`]*`")
_SINGLE_QUOTED_RE = re.compile(r"(?<![\w])'[^']+'(?![\w])")
_MODAL_RE = re.compile(r"\b(must|should|shall|never|always|may|might|will|won't)\b", re.I)
_SEQ_RE = re.compile(r"\b(first|then|before|after|finally)\b", re.I)
_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\be\.g\.\b|example", re.I)
_WORD_RE = re.compile(r"[a-z0-9']{4,}", re.I)
_SALVAGE_MODES: frozenset[str] = frozenset({"agent", "multitask", "debug"})

_SYSTEM_PROMPT = """\
You turn rough user prompts into clear, actionable full specs for AI coding agents.

Allowed change kinds:
- clarity: fix grammar, spelling, punctuation — preserve substantive terms
- format: add headings, bullets, code fences, numbered steps, output-shape hints
- constraint: add missing output-format or quality constraints (e.g. "return JSON")
- example: add clearly marked placeholders (<filename>, e.g., "example")
- scope: expand vague requests with pertinent deliverables the user implied but did not write
  (e.g. run tests, update docs, lint/typecheck, definition-of-done checklist)
  — only add scope that clearly follows from the request; never invent unrelated work

Full-spec shape (use sections when the prompt is vague or task-like):
## Goal
## Deliverables
## Constraints
## Test plan
## Definition of done

Hard rules:
1. Preserve the user's intent and goals; do not contradict or remove requirements.
2. Do not change numbers, identifiers, file paths, API names, or quoted strings.
3. Do not weaken modal force (must/should/never) already in the input.
4. Do not add tool parameters the user did not imply.
5. Every change must cite an exact "before" substring from the input (use the full input as
   "before" for large scope expansions).
6. List every edit in changes[]; improved must reflect all changes.
7. If the input lacks section headings, always add format/scope changes to structure it —
   even when the content is otherwise detailed.
8. For coding/implementation tasks, add scope items like run tests and update docs when pertinent.
9. Output valid JSON only: escape newlines in improved as \\n; prefer a single-line JSON object.

When optional context blocks are provided (conversation, facts, reference prompts):
10. Use context to clarify intent and suggest structure — never contradict the input text.
11. Do not copy context verbatim into improved unless it directly refines the user's ask.
12. Facts and reference prompts are hints only; the input text remains authoritative.
13. Follow the Cursor mode guidance block; do not apply agent-style implementation scope in ask or plan modes.

Respond with JSON only:
{"improved": "...", "changes": [{"kind": "...", "description": "...", "before": "...", "after": "..."}]}
"""


class Improver:
    """Propose-only improver: returns suggestions, never applies them."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def improve(
        self,
        text: str,
        tool: str,
        *,
        model: str,
        context: ImproveContext | None = None,
        mode: str | None = None,
        accepted: bool = False,
    ) -> ImprovementResult:
        """Propose prompt improvements; log usage; never mutate caller state."""
        resolved = resolve_cursor_mode(tool, text, explicit_mode=mode)
        apply_default = default_auto_apply(tool, resolved.mode)
        if is_reference_only_prompt(text):
            return _safe_result(text, apply_default, resolved=resolved)
        user_content = _build_user_message(text, resolved, context)
        completion = self._engine.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            activity=f"improve:{resolved.mode}",
            model=model,
            response_format={"type": "json_object"},
            improver_fired=True,
            improver_accepted=accepted,
            improver_input_sample=text,
        )
        if not completion.success:
            logger.warning(
                "improve_prompt LLM failed (model=%s): %s",
                completion.model_used,
                completion.error or "unknown error",
            )
            return _safe_result(text, apply_default, resolved=resolved)
        try:
            parsed_improved, changes = _parse_model_output(completion.content)
            result, validated = _validate(
                text,
                parsed_improved,
                changes,
                apply_default,
                resolved=resolved,
            )
            changed = result.improved.strip() != text.strip()
            if validated and changed and not accepted:
                self._engine.store.update_last_improver_accepted(True)
            if not validated:
                salvaged = _try_salvage(text, parsed_improved, apply_default, resolved=resolved)
                if salvaged is not None:
                    logger.info(
                        "improve_prompt salvaged restructured output (model=%s; was: %s)",
                        completion.model_used,
                        result.rejection_reason,
                    )
                    return salvaged
                if result.rejection_reason:
                    logger.warning(
                        "improve_prompt validation rejected model output (model=%s): %s",
                        completion.model_used,
                        result.rejection_reason,
                    )
            return result
        except Exception as exc:
            salvaged = _try_salvage_parse_failure(
                text,
                completion.content,
                apply_default,
                resolved=resolved,
            )
            if salvaged is not None:
                logger.info(
                    "improve_prompt salvaged unparseable model output (model=%s; was: %s)",
                    completion.model_used,
                    exc,
                )
                return salvaged
            logger.warning(
                "improve_prompt failed to parse model output (model=%s): %s",
                completion.model_used,
                exc,
            )
            return _safe_result(
                text,
                apply_default,
                resolved=resolved,
                validated=False,
                rejection_reason=f"parse error: {exc}",
            )


_EMPTY_FACTS = "(No project facts stored.)"
_EMPTY_REFERENCE_PROMPTS = "(No matching reference prompts found.)"


def _build_user_message(
    text: str,
    resolved: ResolvedCursorMode,
    context: ImproveContext | None,
) -> str:
    """Format the user message with Cursor mode guidance and optional context blocks."""
    parts = [
        f"Tool context: {resolved.tool}",
        mode_guidance(resolved.mode),
        f"Resolved Cursor mode: {resolved.mode} (source: {resolved.source})",
    ]
    if context is not None:
        conversation = context.conversation_block or _EMPTY_CONVERSATION
        facts = context.facts_block or _EMPTY_FACTS
        reference_prompts = context.reference_prompts_block or _EMPTY_REFERENCE_PROMPTS
        parts.append(f"Recent conversation:\n{conversation}")
        parts.append(f"Project facts:\n{facts}")
        parts.append(f"Reference prompts:\n{reference_prompts}")
    parts.append(f"Text:\n{text}")
    return "\n\n".join(parts)


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


def _parse_model_output(raw: str) -> tuple[str, list[Change]]:
    data = _loads_improver_payload(_extract_json_payload(raw))
    improved = str(data.get("improved", ""))
    changes: list[Change] = []
    for item in data.get("changes", []):
        kind = str(item.get("kind", ""))
        if kind not in _ALLOWED_KINDS:
            msg = f"invalid change kind: {kind}"
            raise ValueError(msg)
        changes.append(
            Change(
                kind=kind,  # type: ignore[arg-type]
                description=str(item.get("description", "")),
                before=str(item.get("before", "")),
                after=str(item.get("after", "")),
            )
        )
    return improved, changes


def _loads_improver_payload(payload: str) -> dict[str, object]:
    """Parse improver JSON, with a regex fallback for multiline model output."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = _extract_improver_fields(payload)
    if not isinstance(data, dict):
        msg = "model output must be a JSON object"
        raise ValueError(msg)
    return data


def _decode_improved_json_string(raw: str) -> str:
    """Unescape a JSON string value recovered from broken model output."""
    return raw.replace("\\n", "\n").replace('\\"', '"')


def _extract_changes_array(payload: str) -> tuple[list[object], int | None]:
    """Return (changes, match_start) from broken JSON; empty list when absent."""
    for pattern in (
        r'"changes"\s*:\s*(\[[\s\S]*?\])\s*,\s*"improved"\s*:',
        r'"changes"\s*:\s*(\[[\s\S]*?\])\s*\}',
        r'"changes"\s*:\s*(\[[\s\S]*\])\s*\}?\s*$',
    ):
        match = re.search(pattern, payload)
        if match is not None:
            return json.loads(match.group(1)), match.start()
    return [], None


def _extract_improved_from_payload(payload: str, *, before: str | None = None) -> str | None:
    """Extract the improved string from a (possibly broken) JSON payload."""
    head = before if before is not None else payload
    improved_match = re.search(
        r'"improved"\s*:\s*"(.*?)"\s*,\s*"changes"\s*:',
        head,
        re.DOTALL,
    )
    if improved_match is not None:
        return _decode_improved_json_string(improved_match.group(1))
    improved_match = re.search(
        r'"changes"\s*:\s*\[[\s\S]*?\]\s*,\s*"improved"\s*:\s*"(.*?)"\s*\}?\s*$',
        payload,
        re.DOTALL,
    )
    if improved_match is not None:
        return _decode_improved_json_string(improved_match.group(1))
    loose = re.search(r'"improved"\s*:\s*"([\s\S]*)', head)
    if loose is None:
        return None
    improved_raw = loose.group(1)
    for sentinel in ('",\n  "changes"', '", "changes"', '",\n"changes"', '",'):
        if sentinel in improved_raw:
            improved_raw = improved_raw.split(sentinel, 1)[0]
            break
    improved_raw = improved_raw.rstrip('"')
    if not improved_raw:
        return None
    return _decode_improved_json_string(improved_raw)


def _extract_improver_fields(payload: str) -> dict[str, object]:
    """Recover improved/changes when json.loads fails on multiline strings."""
    changes, changes_start = _extract_changes_array(payload)
    head = payload[:changes_start] if changes_start is not None else payload
    improved = _extract_improved_from_payload(payload, before=head)
    if improved is None:
        msg = "could not locate improved field in model output"
        raise ValueError(msg)
    return {"improved": improved, "changes": changes}


def _try_parse_plain_spec(raw: str) -> str | None:
    """Return markdown spec text when the model skipped JSON entirely."""
    text = _extract_json_payload(raw).strip()
    if text.startswith("{") or text.startswith("["):
        return None
    if text.startswith("## ") or "\n## " in text:
        if _has_structured_expansion(text):
            return text
    return None


def _is_model_prose_response(raw: str) -> bool:
    """Return True when the model replied in plain prose instead of JSON or a spec."""
    text = _extract_json_payload(raw).strip()
    if not text:
        return False
    if text.startswith("{") or text.startswith("["):
        return False
    if text.startswith("## ") or "\n## " in text:
        return False
    return True


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
    if not _numbers_preserved(original, plain) or not _quoted_spans_preserved(original, plain):
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


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _extract_json_payload(raw: str) -> str:
    """Strip markdown fences and whitespace so json.loads can parse model output."""
    text = raw.strip()
    if not text:
        msg = "model returned empty content"
        raise ValueError(msg)
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


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
    growth_threshold = 1.1 if len(original) >= 300 else 1.2
    if len(improved) <= len(original) * growth_threshold:
        return False
    if improved.count("##") >= 2:
        return True
    if len(original) >= 300 and _has_structured_expansion(improved):
        return True
    return improved.startswith("## ") or "\n## " in improved


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
    min_ratio = 0.25 if len(original) >= 200 else 0.45
    if not _intent_preserved(original, improved, min_ratio=min_ratio):
        return None
    if not _numbers_preserved(original, improved):
        return None
    if not _quoted_spans_preserved(original, improved):
        return None
    if _is_restructured_spec(original, improved):
        return _salvage_result(original, improved, auto_apply_default, resolved=resolved)
    if resolved.mode in _SALVAGE_MODES and len(original) >= 200:
        if len(improved) >= len(original) * 1.05 and _has_structured_expansion(improved):
            return _salvage_result(
                original,
                improved,
                auto_apply_default,
                resolved=resolved,
                description="Salvaged structured expansion for long agent prompt",
            )
    return None


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
        if (
            _is_restructured_spec(original, improved)
            and _numbers_preserved(original, improved)
            and _quoted_spans_preserved(original, improved)
        ):
            return (
                _salvage_result(
                    original,
                    improved,
                    auto_apply_default,
                    resolved=resolved,
                    description="Accepted restructured spec with omitted changes[]",
                ),
                True,
            )
        return _safe_result(
            original,
            auto_apply_default,
            resolved=resolved,
            validated=False,
            rejection_reason="improved text changed but changes[] is empty",
        ), False
    reason = _validation_failure_reason(original, improved, changes)
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
) -> str | None:
    """Return a short reason when validation fails, else None."""
    if improved != original and not changes:
        return "improved text changed but changes[] is empty"
    if not _length_ok(original, improved, changes):
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


def _change_before_valid(original: str, change: Change) -> bool:
    """Return True when change.before anchors to the original text."""
    if change.kind == "scope" and change.before == original:
        return True
    if not change.before:
        return False
    return change.before in original


def _scope_preserves_intent(original: str, improved: str, changes: list[Change]) -> bool:
    """Ensure scope expansions keep the original ask visible in improved."""
    if not _has_scope_changes(changes):
        return True
    if any(
        change.kind == "scope" and change.before.strip() == original.strip()
        for change in changes
    ):
        return True
    min_ratio = 0.45 if len(original) >= 200 else 0.55
    return _intent_preserved(original, improved, min_ratio=min_ratio)


def _length_ok(original: str, improved: str, changes: list[Change]) -> bool:
    """Allow generous growth for spec rewrites; keep tight bounds for minor edits."""
    if not original:
        return True
    if len(improved) > 16_000:
        return False
    ratio = len(improved) / len(original)
    restructuring = _is_restructuring(original, improved, changes) or _is_restructured_spec(
        original, improved
    )
    if restructuring:
        max_ratio = min(16_000 / len(original), 200.0)
        min_ratio = 0.25 if len(original) < 80 else 0.4
        return min_ratio <= ratio <= max_ratio
    if len(original) < 80:
        return 0.5 <= ratio <= 3.0
    return 0.8 <= ratio <= 1.5


def _extract_numbers(text: str) -> list[str]:
    """Extract numeric literals, ignoring timestamps and HTML comment metadata."""
    scrubbed = _HTML_COMMENT_RE.sub("", text)
    scrubbed = _ISO_TIMESTAMP_RE.sub("", scrubbed)
    return _NUMBER_RE.findall(scrubbed.replace(",", ""))


def _numbers_preserved(original: str, improved: str) -> bool:
    """Ensure improved text does not drop or alter numeric literals from the original."""
    orig = Counter(_extract_numbers(scrub_file_reference_numbers(original)))
    imp = Counter(_extract_numbers(improved))
    return all(imp.get(num, 0) >= count for num, count in orig.items())


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
