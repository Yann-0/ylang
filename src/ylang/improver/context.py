"""Build optional context blocks for context-aware prompt improvement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ylang.core.memory import MemoryStore
from ylang.improver.registry import resolve_cursor_mode
from ylang.library.retrieval import select_reference_prompts
from ylang.library.store import Library

_EMPTY_CONVERSATION = "(No prior conversation provided.)"
_CONVERSATION_TURN_LIMIT = 20
_CONVERSATION_CHAR_LIMIT = 8000
_FACT_LIMIT = 20
_FACT_CHAR_LIMIT = 2000
_REFERENCE_PROMPT_LIMIT = 3
_REFERENCE_PROMPT_CHAR_LIMIT = 4000


@dataclass(frozen=True, slots=True)
class ImproveContext:
    """Optional enrichment blocks passed to the improver."""

    conversation_block: str | None = None
    facts_block: str | None = None
    reference_prompts_block: str | None = None

    @property
    def has_content(self) -> bool:
        """Return True when any context block is populated."""
        return bool(
            self.conversation_block or self.facts_block or self.reference_prompts_block
        )


def build_improve_context(
    text: str,
    tool: str,
    conversation: list[dict[str, Any]] | None,
    library: Library,
    memory: MemoryStore,
    *,
    mode: str | None = None,
) -> ImproveContext:
    """Assemble capped context blocks from conversation, facts, and library prompts."""
    resolved = resolve_cursor_mode(tool, text, explicit_mode=mode)
    return ImproveContext(
        conversation_block=_build_conversation_block(conversation),
        facts_block=_build_facts_block(memory),
        reference_prompts_block=_build_reference_prompts_block(
            text,
            tool,
            library,
            cursor_mode=resolved.mode,
        ),
    )


def _build_conversation_block(conversation: list[dict[str, Any]] | None) -> str:
    if not conversation:
        return _EMPTY_CONVERSATION
    turns = conversation[-_CONVERSATION_TURN_LIMIT:]
    lines: list[str] = []
    used = 0
    for turn in turns:
        role = str(turn.get("role", "user"))
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        line = f"{role}: {content}"
        if used + len(line) + 1 > _CONVERSATION_CHAR_LIMIT:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return _EMPTY_CONVERSATION
    return "\n".join(lines)


def _build_facts_block(memory: MemoryStore) -> str | None:
    facts = memory.recall(limit=_FACT_LIMIT)
    if not facts:
        return None
    lines: list[str] = []
    used = 0
    for fact in facts:
        line = f"- {fact.fact} ({fact.scope})"
        if used + len(line) + 1 > _FACT_CHAR_LIMIT:
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
    cursor_mode: str | None = None,
) -> str | None:
    summaries = select_reference_prompts(
        library,
        text,
        tool,
        cursor_mode=cursor_mode,
        limit=_REFERENCE_PROMPT_LIMIT,
        max_chars=_REFERENCE_PROMPT_CHAR_LIMIT,
    )
    if not summaries:
        return None
    sections: list[str] = []
    used = 0
    for summary in summaries:
        template = library.recall(summary.template_id)
        if template is None:
            continue
        section = (
            f"### {summary.name} ({summary.template_id})\n"
            f"tags: {', '.join(summary.tags) or 'none'}\n"
            f"{template.body}"
        )
        if used + len(section) + 2 > _REFERENCE_PROMPT_CHAR_LIMIT and sections:
            break
        sections.append(section)
        used += len(section) + 2
    if not sections:
        return None
    return "\n\n".join(sections)
