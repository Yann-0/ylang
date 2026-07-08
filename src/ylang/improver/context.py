"""Build optional context blocks for context-aware prompt improvement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ylang.core.memory import MemoryStore
from ylang.improver.block_assembler import select_blocks
from ylang.improver.mode_optimizer import get_mode_config, handle_mode_switch
from ylang.improver.registry import resolve_cursor_mode
from ylang.library.effectiveness import build_effectiveness_scores
from ylang.library.retrieval import select_learned_templates, select_reference_prompts
from ylang.library.store import Library
from ylang.usage.store import UsageStore

_EMPTY_CONVERSATION = "(No prior conversation provided.)"
_DEFAULT_LEARNED_TEMPLATE_LIMIT = 2


@dataclass(frozen=True, slots=True)
class ImproveContext:
    """Optional enrichment blocks passed to the improver."""

    conversation_block: str | None = None
    facts_block: str | None = None
    reference_prompts_block: str | None = None
    reference_template_ids: tuple[str, ...] = ()
    blocks_block: str | None = None
    mode_handoff: dict[str, str | bool] | None = None

    @property
    def has_content(self) -> bool:
        """Return True when any context block is populated."""
        return bool(
            self.conversation_block
            or self.facts_block
            or self.reference_prompts_block
            or self.blocks_block
        )


def _learned_template_limit(default: int) -> int:
    """Return max learned templates to inject; override via ``YLANG_LEARNED_TEMPLATE_LIMIT``."""
    raw = os.environ.get("YLANG_LEARNED_TEMPLATE_LIMIT")
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _effectiveness_weight() -> float:
    raw = os.environ.get("YLANG_RETRIEVAL_EFFECTIVENESS_WEIGHT", "0.5")
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return 0.5


def build_improve_context(
    text: str,
    tool: str,
    conversation: list[dict[str, Any]] | None,
    library: Library,
    memory: MemoryStore,
    *,
    mode: str | None = None,
    store: UsageStore | None = None,
) -> ImproveContext:
    """Assemble capped context blocks from conversation, facts, and library prompts."""
    resolved = resolve_cursor_mode(tool, text, explicit_mode=mode)
    mode_config = get_mode_config(resolved.mode)
    handoff = handle_mode_switch(resolved.mode)
    effectiveness = build_effectiveness_scores(store) if store is not None else {}
    weight = _effectiveness_weight()

    reference_block, reference_ids = _build_reference_prompts_block(
        text,
        tool,
        library,
        cursor_mode=resolved.mode,
        mode_config=mode_config,
        effectiveness=effectiveness,
        weight=weight,
    )
    blocks_block, block_ids = select_blocks(
        library,
        cursor_mode=resolved.mode,
        max_chars=mode_config.reference_prompt_char_limit,
    )
    all_ids = tuple(dict.fromkeys((*reference_ids, *block_ids)))

    return ImproveContext(
        conversation_block=_build_conversation_block(
            conversation,
            turn_limit=mode_config.conversation_turn_limit,
            char_limit=mode_config.conversation_char_limit,
        ),
        facts_block=_build_facts_block(
            memory,
            fact_limit=mode_config.facts_limit,
            char_limit=mode_config.facts_char_limit,
        ),
        reference_prompts_block=reference_block,
        reference_template_ids=all_ids,
        blocks_block=blocks_block or None,
        mode_handoff=handoff,
    )


def _build_conversation_block(
    conversation: list[dict[str, Any]] | None,
    *,
    turn_limit: int,
    char_limit: int,
) -> str:
    if not conversation:
        return _EMPTY_CONVERSATION
    turns = conversation[-turn_limit:]
    lines: list[str] = []
    used = 0
    for turn in turns:
        role = str(turn.get("role", "user"))
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        line = f"{role}: {content}"
        if used + len(line) + 1 > char_limit:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return _EMPTY_CONVERSATION
    return "\n".join(lines)


def _build_facts_block(
    memory: MemoryStore,
    *,
    fact_limit: int,
    char_limit: int,
) -> str | None:
    facts = memory.recall(limit=fact_limit)
    if not facts:
        return None
    lines: list[str] = []
    used = 0
    for fact in facts:
        line = f"- {fact.fact} ({fact.scope})"
        if used + len(line) + 1 > char_limit:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return None
    return "\n".join(lines)


def _build_reference_prompts_block(
    text: str,
    tool: str,
    library: Library,
    *,
    cursor_mode: str | None,
    mode_config: object,
    effectiveness: dict[str, float],
    weight: float,
) -> tuple[str | None, tuple[str, ...]]:
    from ylang.improver.mode_optimizer import ModeOptimizerConfig

    assert isinstance(mode_config, ModeOptimizerConfig)
    learned = select_learned_templates(
        library,
        limit=_learned_template_limit(mode_config.learned_template_limit),
        max_chars=mode_config.reference_prompt_char_limit,
        effectiveness=effectiveness,
        weight=weight,
    )
    summaries = select_reference_prompts(
        library,
        text,
        tool,
        cursor_mode=cursor_mode,
        limit=mode_config.reference_prompt_limit,
        max_chars=mode_config.reference_prompt_char_limit,
        effectiveness=effectiveness,
        weight=weight,
    )
    seen: set[str] = set()
    ordered: list[object] = []
    for summary in learned + summaries:
        if summary.template_id in seen:
            continue
        seen.add(summary.template_id)
        ordered.append(summary)
    if not ordered:
        return None, ()
    sections: list[str] = []
    used = 0
    template_ids: list[str] = []
    for summary in ordered:
        template = library.recall(summary.template_id)
        if template is None:
            continue
        template_ids.append(summary.template_id)
        section = (
            f"### {summary.name} ({summary.template_id})\n"
            f"tags: {', '.join(summary.tags) or 'none'}\n"
            f"{template.body}"
        )
        if used + len(section) + 2 > mode_config.reference_prompt_char_limit and sections:
            break
        sections.append(section)
        used += len(section) + 2
    if not sections:
        return None, ()
    return "\n\n".join(sections), tuple(template_ids)
