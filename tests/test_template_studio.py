"""Tests for template param parsing and AI template improver."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.datastructures import FormData

from ylang.console.template_improver import _parse_improve_response, improve_template_with_ai
from ylang.console.template_params import (
    detect_placeholders,
    merge_detected_params,
    parse_params_from_form,
)
from ylang.core.types import CompletionResult
from ylang.library.types import TemplateParam


def test_parse_params_from_form() -> None:
    form = FormData(
        [
            ("param_name", "task"),
            ("param_description", "What to do"),
            ("param_default", "review code"),
            ("param_name", "lang"),
            ("param_description", ""),
            ("param_default", ""),
        ]
    )
    params = parse_params_from_form(form)
    assert len(params) == 2
    assert params[0].name == "task"
    assert params[0].default == "review code"
    assert params[1].name == "lang"
    assert params[1].default is None


def test_detect_placeholders_single_and_double_brace() -> None:
    body = "Do {task} for {{lang}} then {task} again"
    assert detect_placeholders(body) == ["task", "lang"]


def test_detect_placeholders_ignores_format_specs_and_literals() -> None:
    assert detect_placeholders("plain text") == []
    assert detect_placeholders("literal braces {{ not a name }}") == []
    assert detect_placeholders("{0} {name:02d}") == []


def test_merge_detected_params_preserves_existing() -> None:
    existing = [
        TemplateParam(name="task", description="What to do", default="x"),
        TemplateParam(name="extra", description="keep me", default=None),
    ]
    merged = merge_detected_params(existing, ["task", "lang"])
    assert [item.name for item in merged] == ["task", "extra", "lang"]
    assert merged[0].description == "What to do"
    assert merged[0].default == "x"
    assert merged[2].name == "lang"
    assert merged[2].default is None


def test_parse_improve_response_json() -> None:
    parsed = _parse_improve_response(
        '{"name":"Better","body":"Do {task}","params":[{"name":"task","description":"x","default":null}],"rationale":"clearer"}'
    )
    assert parsed is not None
    assert parsed["body"] == "Do {task}"
    assert parsed["params"][0]["name"] == "task"


def test_improve_template_with_ai_success() -> None:
    engine = MagicMock()
    engine.complete.return_value = CompletionResult(
        content='{"name":"Improved","body":"Run {task}","params":[{"name":"task","description":"d","default":null}],"rationale":"ok"}',
        model_used="test/model",
        prompt_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
        error=None,
    )
    result = improve_template_with_ai(
        name="Old",
        body="Do stuff",
        params=[],
        engine=engine,
    )
    assert result["ok"] is True
    assert result["body"] == "Run {task}"
    call_kwargs = engine.complete.call_args.kwargs
    assert call_kwargs.get("activity") == "reason"
    assert "model" not in call_kwargs
    assert "claude-sonnet" not in str(engine.complete.call_args)
