"""Propose-only structural text improvement via LiteLLM."""

from __future__ import annotations

import json
import re
import time
import litellm

from ylang.improver.registry import default_auto_apply
from ylang.improver.types import Change, ImprovementResult
from ylang.usage.store import UsageStore

_ALLOWED_KINDS: frozenset[str] = frozenset({"clarity", "format", "constraint", "example"})
_NUMBER_RE = re.compile(r"\d+")
_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`')
_MODAL_RE = re.compile(r"\b(must|should|shall|never|always|may|might|will|won't)\b", re.I)
_SEQ_RE = re.compile(r"\b(first|then|before|after|finally)\b", re.I)
_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\be\.g\.\b|example", re.I)

_SYSTEM_PROMPT = """\
You improve user text for AI tools. Your job is STRUCTURAL ONLY.

Allowed change kinds:
- clarity: grammar, spelling, run-on splits — never reword substantive terms
- format: headings, bullets, code fences, output-shape hints
- constraint: surface missing output-format constraints (e.g. "return JSON") only
- example: add clearly marked placeholders (<filename>, e.g., "example")

Hard rules:
1. Preserve the user's intent, goals, and requirements exactly.
2. Do not add, remove, or alter substantive claims or scope.
3. Do not change numbers, identifiers, file paths, API names, or quoted strings.
4. Do not change modal force (must/should/never) or tone.
5. Do not add tool parameters or tasks the user did not write.
6. If the text is already clear, return improved equal to the input and changes [].
7. Every change must cite an exact "before" substring from the input.

Respond with JSON only:
{"improved": "...", "changes": [{"kind": "...", "description": "...", "before": "...", "after": "..."}]}
"""


class Improver:
    """Propose-only improver: returns suggestions, never applies them."""

    def __init__(self, store: UsageStore, *, surface: str) -> None:
        self._store = store
        self._surface = surface

    def improve(
        self,
        text: str,
        tool: str,
        *,
        model: str,
    ) -> ImprovementResult:
        """Propose structural improvements; log usage; never mutate caller state."""
        apply_default = default_auto_apply(tool)
        started = time.perf_counter()
        result = _safe_result(text, apply_default)
        model_used = model
        prompt_tokens = 0
        cost = 0.0
        success = False
        try:
            raw, model_used, prompt_tokens, cost = _call_litellm(text, tool, model=model)
            parsed_improved, changes = _parse_model_output(raw)
            result, success = _validate(text, parsed_improved, changes, apply_default)
        except Exception:
            success = False
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._store.write_usage(
            surface=self._surface,
            activity=f"improve:{tool}",
            model_used=model_used,
            prompt_tokens=prompt_tokens,
            cost=cost,
            improver_fired=True,
            improver_accepted=False,
            latency_ms=latency_ms,
            success=success,
        )
        return result


def _safe_result(text: str, auto_apply_default: bool) -> ImprovementResult:
    return ImprovementResult(
        original=text,
        improved=text,
        changes=[],
        auto_apply_default=auto_apply_default,
    )


def _call_litellm(text: str, tool: str, *, model: str) -> tuple[str, str, int, float]:
    """Call LiteLLM and return raw JSON content plus usage metadata."""
    response = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Tool context: {tool}\n\nText:\n{text}"},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    model_used = getattr(response, "model", None) or model
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    hidden = getattr(response, "_hidden_params", {}) or {}
    cost = float(hidden.get("response_cost", 0.0) or 0.0)
    return content, str(model_used), prompt_tokens, cost


def _parse_model_output(raw: str) -> tuple[str, list[Change]]:
    data = json.loads(raw)
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


def _validate(
    original: str,
    improved: str,
    changes: list[Change],
    auto_apply_default: bool,
) -> tuple[ImprovementResult, bool]:
    """Run structural safety checks; fall back to original on failure."""
    if original == improved and not changes:
        return _safe_result(original, auto_apply_default), True
    if not _length_ok(original, improved):
        return _safe_result(original, auto_apply_default), False
    if not _numbers_preserved(original, improved):
        return _safe_result(original, auto_apply_default), False
    if not _quoted_spans_preserved(original, improved):
        return _safe_result(original, auto_apply_default), False
    if not _modals_preserved(original, improved):
        return _safe_result(original, auto_apply_default), False
    if not _sequencing_preserved(original, improved, changes):
        return _safe_result(original, auto_apply_default), False
    for change in changes:
        if change.kind not in _ALLOWED_KINDS:
            return _safe_result(original, auto_apply_default), False
        if not change.before or change.before not in original:
            return _safe_result(original, auto_apply_default), False
        if change.kind == "example" and not _PLACEHOLDER_RE.search(change.after):
            return _safe_result(original, auto_apply_default), False
    try:
        replayed = _replay(original, changes)
    except ValueError:
        return _safe_result(original, auto_apply_default), False
    if replayed != improved:
        return _safe_result(original, auto_apply_default), False
    return ImprovementResult(
        original=original,
        improved=improved,
        changes=changes,
        auto_apply_default=auto_apply_default,
    ), True


def _length_ok(original: str, improved: str) -> bool:
    if not original:
        return True
    ratio = len(improved) / len(original)
    if len(original) < 80:
        return 0.5 <= ratio <= 2.0
    return 0.8 <= ratio <= 1.5


def _numbers_preserved(original: str, improved: str) -> bool:
    return sorted(_NUMBER_RE.findall(original)) == sorted(_NUMBER_RE.findall(improved))


def _quoted_spans_preserved(original: str, improved: str) -> bool:
    return sorted(_QUOTED_RE.findall(original)) == sorted(_QUOTED_RE.findall(improved))


def _modals_preserved(original: str, improved: str) -> bool:
    return sorted(_MODAL_RE.findall(original)) == sorted(_MODAL_RE.findall(improved))


def _sequencing_preserved(
    original: str,
    improved: str,
    changes: list[Change],
) -> bool:
    if sorted(_SEQ_RE.findall(original)) == sorted(_SEQ_RE.findall(improved)):
        return True
    return all(change.kind == "format" for change in changes)


def _replay(original: str, changes: list[Change]) -> str:
    result = original
    for change in changes:
        if change.before not in result:
            msg = "change.before not found during replay"
            raise ValueError(msg)
        result = result.replace(change.before, change.after, 1)
    return result
