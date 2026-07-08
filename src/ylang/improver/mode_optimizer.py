"""Mode-aware optimization configuration for the improver stack."""

from __future__ import annotations

from dataclasses import dataclass

from ylang.improver.registry import CursorMode, mode_guidance


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
        conversation_turn_limit=20,
        conversation_char_limit=8000,
        facts_limit=20,
        facts_char_limit=2000,
        reference_prompt_limit=3,
        reference_prompt_char_limit=4000,
        learned_template_limit=2,
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
        conversation_turn_limit=25,
        conversation_char_limit=10000,
        facts_limit=20,
        facts_char_limit=2000,
        reference_prompt_limit=3,
        reference_prompt_char_limit=4000,
        learned_template_limit=2,
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
