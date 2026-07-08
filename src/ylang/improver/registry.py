"""Tool registry, Cursor mode resolution, and auto-apply defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CursorMode = Literal["agent", "plan", "debug", "ask", "multitask"]
ModeSource = Literal["explicit", "tool", "prompt", "default"]
TaskClass = Literal["structural", "analysis", "implementation"]

PRECISION_TOOLS: frozenset[str] = frozenset(
    {
        "run_command",
        "edit_file",
        "execute_sql",
    }
)

_CANONICAL_MODES: frozenset[str] = frozenset({"agent", "plan", "debug", "ask", "multitask"})

_TOOL_ALIASES: dict[str, CursorMode] = {
    "agent": "agent",
    "cursor-agent": "agent",
    "cursor": "agent",
    "cursor_agent": "agent",
    "implementation": "agent",
    "plan": "plan",
    "planning": "plan",
    "plan-mode": "plan",
    "plan_mode": "plan",
    "debug": "debug",
    "debug-mode": "debug",
    "debug_mode": "debug",
    "troubleshoot": "debug",
    "ask": "ask",
    "ask-mode": "ask",
    "ask_mode": "ask",
    "question": "ask",
    "multitask": "multitask",
    "multitask-mode": "multitask",
    "multitask_mode": "multitask",
    "multi-task": "multitask",
}

_MCP_TOOL_DEFAULT_MODE: dict[str, CursorMode] = {
    "edit_file": "agent",
    "run_command": "agent",
    "execute_sql": "agent",
    "grep": "agent",
    "read_file": "ask",
    "search": "ask",
    "analyze": "plan",
}

_PROMPT_MODE_PATTERNS: tuple[tuple[re.Pattern[str], CursorMode, int], ...] = (
    (re.compile(r"\b(deep dive|backlog|roadmap|architecture|gap analysis|adr|product owner)\b", re.I), "plan", 4),
    (re.compile(r"\b(debug|fix the bug|stack trace|reproduc|root cause|failing test)\b", re.I), "debug", 3),
    (re.compile(r"\b(plan|roadmap|architecture|design approach|trade-?offs?)\b", re.I), "plan", 2),
    (re.compile(r"\b(explain|what is|how does|why does|describe|clarify)\b", re.I), "ask", 2),
    (
        re.compile(
            r"\b(parallel|multitask|workstreams?|sub-?agents?|background agents?|"
            r"concurrent(?:ly)?|simultaneous(?:ly)?|in parallel|at the same time|fan[- ]?out)\b",
            re.I,
        ),
        "multitask",
        3,
    ),
    (re.compile(r"\b(implement|refactor|add feature|build|write tests?|fix)\b", re.I), "agent", 2),
)

# Signals that a request contains multiple independent deliverables worth
# parallelizing across Cursor subagents / background agents.
_PARALLEL_KEYWORD_RE = re.compile(
    r"\b(parallel|in parallel|concurrent(?:ly)?|simultaneous(?:ly)?|at the same time|"
    r"multitask|sub-?agents?|background agents?|fan[- ]?out|each of|for each|"
    r"across (?:all|multiple)|batch)\b",
    re.I,
)
_ACTION_VERB_RE = re.compile(
    r"\b(implement|add|fix|refactor|write|build|create|update|migrate|test|document|"
    r"remove|delete|rename|optimize|integrate|deploy)\b",
    re.I,
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S", re.M)

_MODE_GUIDANCE: dict[CursorMode, str] = {
    "agent": (
        "Cursor mode: agent — expand into an implementation-ready spec. "
        "Use Goal / Deliverables / Constraints / Test plan / Definition of done when helpful. "
        "Implementation, tests, and docs scope are allowed when implied. "
        "If the work has independent parts, note which can run as parallel subagents."
    ),
    "plan": (
        "Cursor mode: plan — planning only, no implementation or side effects. "
        "Prefer Goal / Context / Exploration (read-only) / Options (with trade-offs) / "
        "Recommended approach / Phased roadmap / Risks / Open questions. "
        "Begin with read-only exploration before proposing; compare at least two options with trade-offs. "
        "In the phased roadmap, mark which phases or tasks are parallelizable vs sequential so execution "
        "can later fan out to parallel workers. "
        "For analysis or backlog tasks, add Deliverables, Epic roadmap, and Definition of done sections. "
        "Do not add code edits, file changes, or run-test deliverables unless the user asked to plan them."
    ),
    "ask": (
        "Cursor mode: ask — clarify and sharpen the question; optimize for a direct answer. "
        "Prefer Question / Context / Answer format / Constraints. "
        "Do not expand into implementation specs, deliverables, or definition-of-done checklists."
    ),
    "debug": (
        "Cursor mode: debug — hypothesis-driven troubleshooting. "
        "Prefer Symptom / Repro steps / Expected vs actual / Hypotheses / Investigation plan / Success criteria. "
        "Keep scope tight; avoid unrelated feature work."
    ),
    "multitask": (
        "Cursor mode: multitask — decompose the work into independent, parallelizable workstreams that "
        "map to Cursor's parallel subagents / background agents. "
        "Structure with: Goal / Workstreams / Parallelization plan / Dependencies / Integration / Done criteria. "
        "Give each workstream a short id and make it independently actionable. "
        "In the Parallelization plan, state explicitly which workstreams can run concurrently (spawn parallel "
        "subagents or background agents) and which must run sequentially due to dependencies. "
        "Recommend batching independent tool calls in a single step to cut latency, and add an Integration/merge "
        "step that reconciles parallel results. "
        "Optimize for wall-clock time: prefer concurrency for independent work; keep shared-file edits sequential."
    ),
}

_PARALLELISM_DIRECTIVE = (
    "Parallelization directive: this request contains multiple independent deliverables. "
    "Structure the improved spec to activate Cursor's multitask / parallel subagents when it speeds delivery:\n"
    "- group genuinely independent work into concurrently-runnable workstreams;\n"
    "- mark dependencies that force sequential execution;\n"
    "- recommend spawning parallel or background subagents and batching independent tool calls;\n"
    "- add an integration step that merges parallel results and resolves conflicts.\n"
    "Only parallelize independent work; keep edits to shared files sequential. Do not invent unrelated work."
)


@dataclass(frozen=True, slots=True)
class ResolvedCursorMode:
    """A normalized Cursor interaction mode and how it was chosen."""

    mode: CursorMode
    source: ModeSource
    tool: str


def is_precision_tool(tool: str) -> bool:
    """Return True when the tool must never auto-apply improvements."""
    return _normalize_key(tool) in PRECISION_TOOLS


def detect_task_class(text: str) -> TaskClass:
    """Classify prompt intent for improver validation tuning."""
    lowered = text.lower()
    if re.search(
        r"\b(deep dive|backlog|roadmap|gap analysis|architecture review|product owner|adr)\b",
        lowered,
    ):
        return "analysis"
    if re.search(r"\b(implement|refactor|add feature|build|write tests?|fix bug)\b", lowered):
        return "implementation"
    return "structural"


def default_auto_apply(tool: str, mode: CursorMode) -> bool:
    """Return the default auto-apply hint for a tool and Cursor mode."""
    if is_precision_tool(tool) or mode in ("debug", "plan"):
        return False
    return True


def mode_guidance(mode: CursorMode) -> str:
    """Return LLM guidance for optimizing prompts in the given Cursor mode."""
    return _MODE_GUIDANCE[mode]


def recommend_parallelism(text: str) -> bool:
    """Return True when a prompt has multiple independent deliverables worth parallelizing.

    Detects explicit parallel keywords, multiple enumerated list items, or several
    distinct action verbs — signals that Cursor's multitask / parallel subagents
    would deliver faster results.
    """
    if _PARALLEL_KEYWORD_RE.search(text):
        return True
    if len(_LIST_ITEM_RE.findall(text)) >= 2:
        return True
    distinct_verbs = {match.group(0).lower() for match in _ACTION_VERB_RE.finditer(text)}
    return len(distinct_verbs) >= 3


def parallelism_directive() -> str:
    """Return the directive instructing the improver to activate parallel workstreams."""
    return _PARALLELISM_DIRECTIVE


def resolve_cursor_mode(
    tool: str,
    text: str,
    *,
    explicit_mode: str | None = None,
) -> ResolvedCursorMode:
    """Resolve Cursor mode from explicit hint, tool name, or prompt content."""
    if explicit_mode is not None:
        normalized = _normalize_key(explicit_mode)
        if normalized in _CANONICAL_MODES:
            return ResolvedCursorMode(
                mode=normalized,  # type: ignore[arg-type]
                source="explicit",
                tool=tool,
            )
        if normalized in _TOOL_ALIASES:
            return ResolvedCursorMode(
                mode=_TOOL_ALIASES[normalized],
                source="explicit",
                tool=tool,
            )

    tool_key = _normalize_key(tool)
    if tool_key in _TOOL_ALIASES:
        return ResolvedCursorMode(mode=_TOOL_ALIASES[tool_key], source="tool", tool=tool)
    if tool_key in _MCP_TOOL_DEFAULT_MODE:
        return ResolvedCursorMode(
            mode=_MCP_TOOL_DEFAULT_MODE[tool_key],
            source="tool",
            tool=tool,
        )

    inferred = _infer_mode_from_prompt(text)
    if inferred is not None:
        return ResolvedCursorMode(mode=inferred, source="prompt", tool=tool)

    return ResolvedCursorMode(mode="agent", source="default", tool=tool)


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _infer_mode_from_prompt(text: str) -> CursorMode | None:
    """Score prompt keywords and return the best matching mode, if any."""
    scores: dict[CursorMode, int] = {
        "agent": 0,
        "plan": 0,
        "debug": 0,
        "ask": 0,
        "multitask": 0,
    }
    for pattern, mode, weight in _PROMPT_MODE_PATTERNS:
        if pattern.search(text):
            scores[mode] += weight
    best_mode = max(scores, key=lambda key: scores[key])
    if scores[best_mode] <= 0:
        return None
    return best_mode
