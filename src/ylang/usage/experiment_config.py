"""Experiment config variants applied via ``config_hash``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Overrides applied when an experiment variant is assigned."""

    config_hash: str
    system_prompt_suffix: str
    validation_strict: bool | None = None
    include_test_plan_scope: bool | None = None


_VARIANTS: dict[str, ExperimentConfig] = {
    "control": ExperimentConfig(
        config_hash="control",
        system_prompt_suffix="",
    ),
    "concise": ExperimentConfig(
        config_hash="concise",
        system_prompt_suffix=(
            "\n\nExperiment variant (concise): Prefer shorter improved prompts. "
            "Use at most three sections when structuring vague tasks."
        ),
        include_test_plan_scope=False,
    ),
    "verbose": ExperimentConfig(
        config_hash="verbose",
        system_prompt_suffix=(
            "\n\nExperiment variant (verbose): Always include Definition of done "
            "and Test plan sections for implementation tasks."
        ),
        include_test_plan_scope=True,
    ),
}


def resolve_experiment_config(config_hash: str) -> ExperimentConfig:
    """Return experiment overrides for a ``config_hash``; unknown hashes map to control."""
    return _VARIANTS.get(config_hash, _VARIANTS["control"])


def list_known_config_hashes() -> list[str]:
    """Return registered experiment config hash identifiers."""
    return list(_VARIANTS.keys())
