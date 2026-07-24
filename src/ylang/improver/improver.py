"""Propose-only prompt improvement via the core engine."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from ylang.core.engine import Engine
from ylang.core.model_router import resolve_improver_explicit_model
from ylang.core.types import CompletionResult
from ylang.improver.context import ImproveContext, _EMPTY_CONVERSATION
from ylang.improver.mode_optimizer import get_mode_config, improver_timeout_sec
from ylang.improver.parse import _parse_model_output
from ylang.improver.reference import is_reference_only_prompt
from ylang.improver.registry import (
    ResolvedCursorMode,
    default_auto_apply,
    detect_task_class,
    mode_guidance,
    parallelism_directive,
    recommend_parallelism,
    resolve_cursor_mode,
)
from ylang.improver.salvage import (
    _ANCHOR_SALVAGE_REASONS,
    _FALLBACK_REJECTION_REASONS,
    _SALVAGE_VALIDATION_REASONS,
    _TIMEOUT_FALLBACK_MAX_LEN,
    _fallback_short_prompt_expansion,
    _salvage_omitted_changes,
    _try_salvage,
    _try_salvage_parse_failure,
    _try_salvage_validation_failure,
)
from ylang.improver.types import Change, ImprovementResult
from ylang.improver.validate import _safe_result, _validate

# Re-exports for tests and internal callers that import from this module.
from ylang.improver.parse import (  # noqa: F401
    _extract_json_payload,
    _is_model_prose_response,
    _loads_improver_payload,
    _try_parse_plain_spec,
)
from ylang.improver.salvage import (  # noqa: F401
    _is_vague_short_prompt,
    _salvage_result,
)
from ylang.improver.validate import (  # noqa: F401
    _change_before_valid,
    _extract_quoted_spans,
    _intent_preserved,
    _is_restructured_spec,
    _numbers_preserved,
    _quoted_spans_preserved,
    _replay,
)

logger = logging.getLogger(__name__)

_IMPROVE_CACHE_TTL_SEC = 60.0

_DEFAULT_IMPROVER_TIMEOUT_SEC = 12.0

_CRITIQUE_MIN_REMAINING_SEC = 2.0

_CRITIQUE_MIN_REMAINING_FRACTION = 0.2

_improve_cache: dict[str, tuple[float, ImprovementResult]] = {}

_IMPROVE_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="ylang-improve"
)

_TIMEOUT_GRACE_SEC = 2.0

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
14. When a parallelization directive is present, structure the improved spec so Cursor can run independent
    work concurrently (parallel subagents / background agents): add a Workstreams or Parallelization plan
    section, mark which parts run in parallel vs sequentially, and add an integration step. This is a
    format/scope change that reorganizes the user's own work — do not add unrelated tasks.

Respond with JSON only:
{"improved": "...", "changes": [{"kind": "...", "description": "...", "before": "...", "after": "..."}]}
"""

_CRITIQUE_SYSTEM = """\
You review improved AI coding agent prompts for clarity and completeness.
Respond with JSON only: {"improved": "...", "changes": [{"kind": "...", "description": "...", "before": "...", "after": "..."}]}
Preserve intent; fix only clarity, structure, and missing constraints. Do not add unrelated scope.
"""


def _improve_cache_key(text: str, tool: str, mode: str | None) -> str:
    payload = f"{tool}:{mode or ''}:{text.strip()}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_cached_improvement(
    key: str, store: object | None = None
) -> ImprovementResult | None:
    entry = _improve_cache.get(key)
    if entry is not None:
        expires_at, result = entry
        if time.monotonic() <= expires_at:
            return result
        _improve_cache.pop(key, None)
    if store is not None:
        from ylang.improver.cache_store import get_cached_improvement

        persisted = get_cached_improvement(store._connection, key)  # type: ignore[attr-defined]
        if persisted is not None:
            _improve_cache[key] = (
                time.monotonic() + _IMPROVE_CACHE_TTL_SEC,
                persisted,
            )
            return persisted
    return None


def _set_cached_improvement(
    key: str, result: ImprovementResult, store: object | None = None
) -> None:
    _improve_cache[key] = (time.monotonic() + _IMPROVE_CACHE_TTL_SEC, result)
    if store is not None:
        from ylang.improver.cache_store import set_cached_improvement

        set_cached_improvement(store._connection, key, result)  # type: ignore[attr-defined]


def clear_improve_cache() -> None:
    """Clear the in-memory improver result cache (primarily for tests)."""
    _improve_cache.clear()


def _critique_enabled(store: object | None = None) -> bool:
    if store is not None:
        from ylang.core.runtime_settings import RuntimeSettingsStore, _parse_bool

        override = RuntimeSettingsStore(store._connection).get("improver_critique")  # type: ignore[attr-defined]
        parsed = _parse_bool(override)
        if parsed is not None:
            return parsed
    return os.environ.get("YLANG_IMPROVER_CRITIQUE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _improver_timeout_sec(store: object | None = None) -> float:
    """Return improver LLM wall-clock budget in seconds (0 disables)."""
    if store is not None:
        from ylang.usage.store import UsageStore

        if isinstance(store, UsageStore):
            return improver_timeout_sec(store)
    return improver_timeout_sec(None)


def _experiments_enabled(store: object | None = None) -> bool:
    if store is not None:
        from ylang.core.runtime_settings import RuntimeSettingsStore, _parse_bool

        override = RuntimeSettingsStore(store._connection).get("experiments")  # type: ignore[attr-defined]
        parsed = _parse_bool(override)
        if parsed is not None:
            return parsed
    return os.environ.get("YLANG_EXPERIMENTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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
            return self._finalize(
                _safe_result(text, apply_default, resolved=resolved),
                text,
                resolved=resolved,
            )
        cache_key = _improve_cache_key(text, tool, mode)
        if not accepted:
            cached = _get_cached_improvement(cache_key, self._engine.store)
            if cached is not None:
                return cached
        user_content = _build_user_message(text, resolved, context)
        experiment_variant, system_prompt = self._resolve_experiment(resolved.mode)
        timeout_sec = _improver_timeout_sec(self._engine.store)
        deadline = time.monotonic() + timeout_sec if timeout_sec > 0 else None
        activity = f"improve:{resolved.mode}"
        completion = self._run_improve_completion(
            text=text,
            model=model,
            accepted=accepted,
            apply_default=apply_default,
            resolved=resolved,
            system_prompt=system_prompt,
            user_content=user_content,
            timeout_sec=timeout_sec,
            activity=activity,
            experiment_variant=experiment_variant,
        )
        if isinstance(completion, ImprovementResult):
            return completion
        if not completion.success:
            logger.warning(
                "improve_prompt LLM failed (model=%s): %s",
                completion.model_used,
                completion.error or "unknown error",
            )
            return self._finalize(
                _safe_result(text, apply_default, resolved=resolved),
                text,
                resolved=resolved,
                experiment_variant=experiment_variant,
            )
        return self._process_improve_completion(
            text=text,
            completion=completion,
            apply_default=apply_default,
            resolved=resolved,
            model=model,
            accepted=accepted,
            cache_key=cache_key,
            deadline=deadline,
            timeout_sec=timeout_sec,
            experiment_variant=experiment_variant,
        )

    def _run_improve_completion(
        self,
        *,
        text: str,
        model: str,
        accepted: bool,
        apply_default: bool,
        resolved: ResolvedCursorMode,
        system_prompt: str,
        user_content: str,
        timeout_sec: float,
        activity: str,
        experiment_variant: str | None,
    ) -> CompletionResult | ImprovementResult:
        """Call the engine with optional timeout/grace; may return a timeout result."""
        usage_cancelled = threading.Event()

        def _complete() -> CompletionResult:
            return self._engine.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                activity=activity,
                model=resolve_improver_explicit_model(model),
                response_format={"type": "json_object"},
                improver_fired=True,
                improver_accepted=accepted,
                improver_input_sample=text,
                usage_cancelled=usage_cancelled,
            )

        if timeout_sec <= 0:
            return _complete()
        future = _IMPROVE_EXECUTOR.submit(_complete)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeoutError:
            usage_cancelled.set()
            grace = min(_TIMEOUT_GRACE_SEC, max(0.5, timeout_sec * 0.15))
            try:
                completion = future.result(timeout=grace)
                logger.info(
                    "improve_prompt accepted late completion within %.1fs grace "
                    "(budget=%.1fs)",
                    grace,
                    timeout_sec,
                )
                return completion
            except FuturesTimeoutError:
                return self._timeout_result(
                    text,
                    apply_default,
                    resolved=resolved,
                    model=model,
                    accepted=accepted,
                    timeout_sec=timeout_sec,
                    activity=activity,
                    experiment_variant=experiment_variant,
                    future=future,
                )

    def _process_improve_completion(
        self,
        *,
        text: str,
        completion: CompletionResult,
        apply_default: bool,
        resolved: ResolvedCursorMode,
        model: str,
        accepted: bool,
        cache_key: str,
        deadline: float | None,
        timeout_sec: float,
        experiment_variant: str | None,
    ) -> ImprovementResult:
        """Parse, validate, salvage, critique, and cache a successful completion."""
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
                salvaged = self._salvage_invalid_result(
                    text=text,
                    parsed_improved=parsed_improved,
                    changes=changes,
                    apply_default=apply_default,
                    resolved=resolved,
                    result=result,
                    model_used=completion.model_used,
                    experiment_variant=experiment_variant,
                )
                if salvaged is not None:
                    return salvaged
            elif not changed and _is_vague_short_prompt(text):
                fallback = _fallback_short_prompt_expansion(
                    text,
                    apply_default,
                    resolved=resolved,
                    require_vague=True,
                )
                if fallback is not None:
                    logger.info(
                        "improve_prompt expanded unchanged short prompt (model=%s)",
                        completion.model_used,
                    )
                    return self._finalize(
                        fallback,
                        text,
                        resolved=resolved,
                        experiment_variant=experiment_variant,
                    )
            result = self._finalize(
                result, text, resolved=resolved, experiment_variant=experiment_variant
            )
            final = self._maybe_critique(
                text,
                result,
                resolved,
                model,
                deadline=deadline,
                timeout_sec=timeout_sec,
            )
            if not accepted:
                _set_cached_improvement(cache_key, final, self._engine.store)
            return final
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return self._handle_improve_parse_error(
                text=text,
                completion=completion,
                apply_default=apply_default,
                resolved=resolved,
                experiment_variant=experiment_variant,
                exc=exc,
            )
        except Exception as exc:
            # Model output can raise unexpected parse/shape errors; keep fail-open.
            logger.debug("improve_prompt unexpected parse error", exc_info=True)
            return self._handle_improve_parse_error(
                text=text,
                completion=completion,
                apply_default=apply_default,
                resolved=resolved,
                experiment_variant=experiment_variant,
                exc=exc,
            )

    def _salvage_invalid_result(
        self,
        *,
        text: str,
        parsed_improved: str,
        changes: list[Change],
        apply_default: bool,
        resolved: ResolvedCursorMode,
        result: ImprovementResult,
        model_used: str,
        experiment_variant: str | None,
    ) -> ImprovementResult | None:
        """Attempt salvage/fallback paths for a validation failure."""
        salvaged = _try_salvage(
            text, parsed_improved, apply_default, resolved=resolved
        )
        if salvaged is None and result.rejection_reason in _ANCHOR_SALVAGE_REASONS:
            salvaged = _salvage_omitted_changes(
                text,
                parsed_improved,
                apply_default,
                resolved=resolved,
            )
        if salvaged is None and result.rejection_reason in _SALVAGE_VALIDATION_REASONS:
            salvaged = _try_salvage_validation_failure(
                text,
                parsed_improved,
                changes,
                apply_default,
                resolved=resolved,
                rejection_reason=result.rejection_reason,
            )
        if salvaged is not None:
            logger.info(
                "improve_prompt salvaged restructured output (model=%s; was: %s)",
                model_used,
                result.rejection_reason,
            )
            return self._finalize(
                salvaged,
                text,
                resolved=resolved,
                experiment_variant=experiment_variant,
            )
        if result.rejection_reason in _FALLBACK_REJECTION_REASONS:
            fallback = _fallback_short_prompt_expansion(
                text,
                apply_default,
                resolved=resolved,
                require_vague=False,
            )
            if fallback is not None:
                logger.info(
                    "improve_prompt applied short-prompt fallback (model=%s; was: %s)",
                    model_used,
                    result.rejection_reason,
                )
                return self._finalize(
                    fallback,
                    text,
                    resolved=resolved,
                    experiment_variant=experiment_variant,
                )
        if result.rejection_reason:
            logger.warning(
                "improve_prompt validation rejected model output (model=%s): %s",
                model_used,
                result.rejection_reason,
            )
        return None

    def _handle_improve_parse_error(
        self,
        *,
        text: str,
        completion: CompletionResult,
        apply_default: bool,
        resolved: ResolvedCursorMode,
        experiment_variant: str | None,
        exc: BaseException,
    ) -> ImprovementResult:
        """Salvage or fail-open when model output cannot be parsed."""
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
            return self._finalize(
                salvaged,
                text,
                resolved=resolved,
                experiment_variant=experiment_variant,
            )
        logger.warning(
            "improve_prompt failed to parse model output (model=%s): %s",
            completion.model_used,
            exc,
        )
        return self._finalize(
            _safe_result(
                text,
                apply_default,
                resolved=resolved,
                validated=False,
                rejection_reason=f"parse error: {exc}",
            ),
            text,
            resolved=resolved,
            experiment_variant=experiment_variant,
        )

    def _timeout_result(
        self,
        text: str,
        apply_default: bool,
        *,
        resolved: ResolvedCursorMode,
        model: str,
        accepted: bool,
        timeout_sec: float,
        activity: str,
        experiment_variant: str | None,
        future: Future[CompletionResult],
    ) -> ImprovementResult:
        """Record a clean timeout usage row and scrub any late orphan writes."""
        logger.warning(
            "improve_prompt timed out after %.1fs (model=%s)",
            timeout_sec,
            model,
        )
        self._engine.store.write_usage(
            surface=self._engine._surface,  # noqa: SLF001
            activity=activity,
            model_used=model,
            prompt_tokens=0,
            cost=0.0,
            improver_fired=True,
            improver_accepted=accepted,
            improver_input_sample=text,
            latency_ms=max(0, int(timeout_sec * 1000)),
            success=False,
            improver_validated=False,
            improver_changed=False,
            improver_rejection_reason="improver timeout",
            improver_task_class=detect_task_class(text),
            cursor_mode=resolved.mode,
            experiment_variant=experiment_variant,
        )
        timeout_row_id = self._engine.store.latest_usage_id() or 0

        def _scrub_orphan(done: Future[CompletionResult]) -> None:
            try:
                done.result()
            except Exception:
                logger.debug(
                    "timed-out improve worker finished with error", exc_info=True
                )
            try:
                self._engine.store.mark_late_improver_orphans(after_id=timeout_row_id)
            except Exception:
                logger.debug(
                    "failed to scrub late improver timeout orphan", exc_info=True
                )

        future.add_done_callback(_scrub_orphan)
        # On timeout prefer a deterministic skeleton for short/medium prompts so
        # the user still gets a usable agent spec instead of a hard rejection.
        fallback = _fallback_short_prompt_expansion(
            text,
            apply_default,
            resolved=resolved,
            require_vague=False,
            max_len=_TIMEOUT_FALLBACK_MAX_LEN,
        )
        if fallback is not None:
            logger.info(
                "improve_prompt timeout: applied prompt fallback after %.1fs",
                timeout_sec,
            )
            return self._finalize(
                fallback,
                text,
                resolved=resolved,
                experiment_variant=experiment_variant,
            )
        return self._finalize(
            _safe_result(
                text,
                apply_default,
                resolved=resolved,
                validated=False,
                rejection_reason="improver timeout",
            ),
            text,
            resolved=resolved,
            experiment_variant=experiment_variant,
        )

    def _resolve_experiment(self, mode: str) -> tuple[str | None, str]:
        """Return assigned variant id and system prompt (with experiment suffix)."""
        if not _experiments_enabled(self._engine.store):
            return None, _SYSTEM_PROMPT
        from ylang.usage.experiment_config import resolve_experiment_config
        from ylang.usage.experiments import ExperimentStore

        store = ExperimentStore(self._engine.store._connection)
        variant = store.assign_variant(f"improver-{mode}")
        if variant is None:
            return None, _SYSTEM_PROMPT
        config = resolve_experiment_config(variant.config_hash)
        system_prompt = _SYSTEM_PROMPT + config.system_prompt_suffix
        return variant.variant_id, system_prompt

    def _finalize(
        self,
        result: ImprovementResult,
        original_text: str,
        *,
        resolved: ResolvedCursorMode,
        experiment_variant: str | None = None,
    ) -> ImprovementResult:
        """Persist improver outcome metadata on the latest usage row."""
        changed = result.improved.strip() != original_text.strip()
        self._engine.store.update_last_improver_outcome(
            validated=result.validated,
            changed=changed,
            rejection_reason=result.rejection_reason,
            task_class=detect_task_class(original_text),
            cursor_mode=resolved.mode,
            experiment_variant=experiment_variant,
        )
        return result

    def _maybe_critique(
        self,
        text: str,
        result: ImprovementResult,
        resolved: ResolvedCursorMode,
        model: str,
        *,
        deadline: float | None = None,
        timeout_sec: float = _DEFAULT_IMPROVER_TIMEOUT_SEC,
    ) -> ImprovementResult:
        """Optional second-pass critique for validated improvements."""
        if not _critique_enabled(self._engine.store) or not result.validated:
            return result
        if result.improved.strip() == text.strip():
            return result
        if deadline is not None:
            remaining = deadline - time.monotonic()
            min_remaining = max(
                _CRITIQUE_MIN_REMAINING_SEC,
                timeout_sec * _CRITIQUE_MIN_REMAINING_FRACTION,
            )
            if remaining < min_remaining:
                logger.info(
                    "improve_prompt skipping critique; %.1fs left of timeout budget "
                    "(need %.1fs)",
                    max(0.0, remaining),
                    min_remaining,
                )
                return result
        completion = self._engine.complete(
            [
                {"role": "system", "content": _CRITIQUE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"{mode_guidance(resolved.mode)}\n\n"
                        f"Original:\n{text}\n\nImproved draft:\n{result.improved}"
                    ),
                },
            ],
            activity=f"improve:{resolved.mode}",
            model=resolve_improver_explicit_model(model),
            response_format={"type": "json_object"},
            improver_fired=False,
        )
        if not completion.success:
            return result
        try:
            parsed_improved, changes = _parse_model_output(completion.content)
            critiqued, validated = _validate(
                text,
                parsed_improved,
                changes,
                result.auto_apply_default,
                resolved=resolved,
            )
            if validated:
                return critiqued
        except Exception:
            logger.debug(
                "critique pass failed; keeping original improvement", exc_info=True
            )
        return result


def _build_user_message(
    text: str,
    resolved: ResolvedCursorMode,
    context: ImproveContext | None,
) -> str:
    """Format the user message with Cursor mode guidance and optional context blocks."""
    mode_config = get_mode_config(resolved.mode)
    parts = [
        f"Tool context: {resolved.tool}",
        mode_config.guidance,
        f"Resolved Cursor mode: {resolved.mode} (source: {resolved.source})",
    ]
    if mode_config.encourage_parallelism or recommend_parallelism(text):
        parts.append(parallelism_directive())
    if context is not None and context.mode_handoff:
        previous = context.mode_handoff.get("previous_mode")
        if previous:
            parts.append(f"Mode handoff: previous={previous}, current={resolved.mode}")
    if context is not None:
        if (
            context.conversation_block
            and context.conversation_block != _EMPTY_CONVERSATION
        ):
            parts.append(f"Recent conversation:\n{context.conversation_block}")
        if context.facts_block:
            parts.append(f"Project facts:\n{context.facts_block}")
        if context.reference_prompts_block:
            parts.append(f"Reference prompts:\n{context.reference_prompts_block}")
        if context.blocks_block:
            parts.append(f"Prompt blocks:\n{context.blocks_block}")
    parts.append(f"Text:\n{text}")
    return "\n\n".join(parts)

