"""Unit tests for advisor reply parsing and model routing."""

from __future__ import annotations

from ylang.console.advisor import AdvisorReply, _parse_advisor_content, generate_advisor_reply
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.core.types import CompletionResult
from ylang.mcp.deps import YlangDeps
from ylang.settings import Settings


class _FakeEngine:
    """Minimal engine stub returning a fixed advisor completion."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.last_kwargs: dict[str, object] = {}

    def complete(
        self, messages: list[dict[str, str]], activity: str, **kwargs: object
    ) -> CompletionResult:
        self.last_kwargs = {"activity": activity, **kwargs}
        return CompletionResult(
            content=self.content,
            model_used="openai/gpt-4o",
            prompt_tokens=1,
            completion_tokens=1,
            cost=0.0,
            latency_ms=1,
            success=True,
            error=None,
            tool_calls=[],
        )


def test_parse_advisor_setting_changes() -> None:
    raw = (
        "Summary: Accept rate is low.\n"
        "Recommendations: Enable critique.\n"
        '{"setting_changes":[{"key":"improver_critique","value":"true","rationale":"Low accept"}]}'
    )
    text, proposals = _parse_advisor_content(raw)
    assert "Accept rate is low" in text
    assert "setting_changes" not in text
    assert len(proposals) == 1
    assert proposals[0].proposal_id == "setting:improver_critique=true"
    assert proposals[0].setting_key == "improver_critique"
    assert proposals[0].setting_value == "true"


def test_parse_advisor_ignores_invalid_keys() -> None:
    raw = (
        "Ok.\n"
        '{"setting_changes":[{"key":"auth_token","value":"secret","rationale":"nope"},'
        '{"key":"experiments","value":"true","rationale":"enable"}]}'
    )
    _, proposals = _parse_advisor_content(raw)
    assert len(proposals) == 1
    assert proposals[0].setting_key == "experiments"


def test_generate_advisor_reply_uses_reason_activity_without_forced_model(
    ylang_deps: YlangDeps,
) -> None:
    engine = _FakeEngine(
        'Summary: fine.\n{"setting_changes":[{"key":"edit_feedback","value":"true","rationale":"track edits"}]}'
    )
    runtime = RuntimeSettingsStore(ylang_deps.store._connection)
    result = generate_advisor_reply(
        "What should I change?",
        store=ylang_deps.store,
        engine=engine,  # type: ignore[arg-type]
        settings=Settings(),
        runtime_store=runtime,
    )
    assert isinstance(result, AdvisorReply)
    assert engine.last_kwargs.get("activity") == "reason"
    assert engine.last_kwargs.get("model") is None
    assert any(p.setting_key == "edit_feedback" for p in result.setting_proposals)
