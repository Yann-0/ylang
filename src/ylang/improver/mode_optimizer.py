"""Mode-aware optimization configuration for the improver stack."""

from __future__ import annotations

import os
from dataclasses import dataclass

from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.improver.registry import CursorMode, mode_guidance
from ylang.usage.store import UsageStore

_FAST_PATH_TIMEOUT_THRESHOLD_SEC = 18.0
_DEFAULT_IMPROVER_TIMEOUT_SEC = 12.0


@dataclass(frozen=True, slots=True)
class ModeOptimizerConfig:
    """Per-mode optimization settings beyond static LLM guidance."""

    mode: CursorMode
    conversation_turn_limit: int
    conversation_char_limit: int
    facts_limit: int
    facts_char_limit: int
    reference_prompt_limit: int
    reference_prompt_char_limit: int
    learned_template_limit: int
    validation_strict: bool
    include_test_plan_scope: bool
    encourage_parallelism: bool
    guidance: str


_MODE_CONFIGS: dict[CursorMode, ModeOptimizerConfig] = {
    "agent": ModeOptimizerConfig(
        mode="agent",
        conversation_turn_limit=18,
        conversation_char_limit=7000,
        facts_limit=15,
        facts_char_limit=1800,
        reference_prompt_limit=2,
        reference_prompt_char_limit=3000,
        learned_template_limit=1,
        validation_strict=True,
        include_test_plan_scope=True,
        encourage_parallelism=False,
        guidance=mode_guidance("agent"),
    ),
    "plan": ModeOptimizerConfig(
        mode="plan",
        conversation_turn_limit=15,
        conversation_char_limit=6000,
        facts_limit=15,
        facts_char_limit=1500,
        reference_prompt_limit=2,
        reference_prompt_char_limit=3000,
        learned_template_limit=1,
        validation_strict=False,
        include_test_plan_scope=False,
        encourage_parallelism=True,
        guidance=mode_guidance("plan"),
    ),
    "debug": ModeOptimizerConfig(
        mode="debug",
        conversation_turn_limit=10,
        conversation_char_limit=5000,
        facts_limit=10,
        facts_char_limit=1200,
        reference_prompt_limit=2,
        reference_prompt_char_limit=2500,
        learned_template_limit=1,
        validation_strict=True,
        include_test_plan_scope=False,
        encourage_parallelism=False,
        guidance=mode_guidance("debug"),
    ),
    "ask": ModeOptimizerConfig(
        mode="ask",
        conversation_turn_limit=10,
        conversation_char_limit=4000,
        facts_limit=10,
        facts_char_limit=1000,
        reference_prompt_limit=1,
        reference_prompt_char_limit=2000,
        learned_template_limit=0,
        validation_strict=True,
        include_test_plan_scope=False,
        encourage_parallelism=False,
        guidance=mode_guidance("ask"),
    ),
    "multitask": ModeOptimizerConfig(
        mode="multitask",
        conversation_turn_limit=20,
        conversation_char_limit=8000,
        facts_limit=15,
        facts_char_limit=1800,
        reference_prompt_limit=2,
        reference_prompt_char_limit=3500,
        learned_template_limit=1,
        validation_strict=True,
        include_test_plan_scope=True,
        encourage_parallelism=True,
        guidance=mode_guidance("multitask"),
    ),
}

_previous_mode: CursorMode | None = None


def get_mode_config(mode: CursorMode) -> ModeOptimizerConfig:
    """Return optimization config for a Cursor mode."""
    return _MODE_CONFIGS[mode]


def improver_timeout_sec(store: UsageStore | None = None) -> float:
    """Return improver LLM wall-clock budget from runtime, env, or default."""
    if store is not None:
        override = RuntimeSettingsStore(store._connection).get("improver_timeout_sec")
        if override is not None and override.strip():
            try:
                return max(0.0, float(override.strip()))
            except ValueError:
                pass
    raw = os.environ.get("YLANG_IMPROVER_TIMEOUT_SEC", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return _DEFAULT_IMPROVER_TIMEOUT_SEC


def apply_fast_path_config(
    config: ModeOptimizerConfig,
    *,
    timeout_sec: float | None = None,
) -> ModeOptimizerConfig:
    """Tighten context caps when improver wall-clock budget is tight."""
    if timeout_sec is None:
        timeout_sec = _DEFAULT_IMPROVER_TIMEOUT_SEC
    if timeout_sec <= 0 or timeout_sec > _FAST_PATH_TIMEOUT_THRESHOLD_SEC:
        return config
    # Ultra-tight when budget ≤12s (BL-010 p50 target is 8s).
    if timeout_sec <= 12:
        return ModeOptimizerConfig(
            mode=config.mode,
            conversation_turn_limit=min(config.conversation_turn_limit, 6),
            conversation_char_limit=min(config.conversation_char_limit, 2500),
            facts_limit=min(config.facts_limit, 5),
            facts_char_limit=min(config.facts_char_limit, 500),
            reference_prompt_limit=min(config.reference_prompt_limit, 1),
            reference_prompt_char_limit=min(config.reference_prompt_char_limit, 1200),
            learned_template_limit=0,
            validation_strict=config.validation_strict,
            include_test_plan_scope=config.include_test_plan_scope,
            encourage_parallelism=config.encourage_parallelism,
            guidance=config.guidance,
        )
    return ModeOptimizerConfig(
        mode=config.mode,
        conversation_turn_limit=min(config.conversation_turn_limit, 10),
        conversation_char_limit=min(config.conversation_char_limit, 4000),
        facts_limit=min(config.facts_limit, 8),
        facts_char_limit=min(config.facts_char_limit, 800),
        reference_prompt_limit=min(config.reference_prompt_limit, 1),
        reference_prompt_char_limit=min(config.reference_prompt_char_limit, 1500),
        learned_template_limit=min(config.learned_template_limit, 1),
        validation_strict=config.validation_strict,
        include_test_plan_scope=config.include_test_plan_scope,
        encourage_parallelism=config.encourage_parallelism,
        guidance=config.guidance,
    )


def handle_mode_switch(new_mode: CursorMode) -> dict[str, str | bool]:
    """Record mode switch and return handoff metadata (non-destructive)."""
    global _previous_mode
    previous = _previous_mode
    _previous_mode = new_mode
    return {
        "previous_mode": previous or "",
        "current_mode": new_mode,
        "handoff_preserved": True,
    }


def reset_mode_state() -> None:
    """Reset mode-switch tracking (primarily for tests)."""
    global _previous_mode
    _previous_mode = None
