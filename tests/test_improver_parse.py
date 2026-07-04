"""Unit tests for improver JSON parsing."""

from __future__ import annotations

from ylang.improver.improver import (
    _extract_json_payload,
    _parse_model_output,
    _try_parse_plain_spec,
    _try_salvage_parse_failure,
)
from ylang.improver.registry import ResolvedCursorMode

_AGENT = ResolvedCursorMode(mode="agent", source="explicit", tool="Cursor")


def test_extract_json_payload_from_markdown_fence() -> None:
    raw = '```json\n{"improved": "hi", "changes": []}\n```'
    assert _extract_json_payload(raw) == '{"improved": "hi", "changes": []}'


def test_extract_json_payload_plain_json() -> None:
    raw = '{"improved": "hi", "changes": []}'
    assert _extract_json_payload(raw) == raw


def test_parse_model_output_multiline_improved_field() -> None:
    raw = """{
  "improved": "## Goal
what shall we do next?

## Deliverables
- Ranked next steps",
  "changes": [
    {"kind": "scope", "description": "expand", "before": "what shall we do next?", "after": "## Goal\\nwhat shall we do next?"}
  ]
}"""
    improved, changes = _parse_model_output(raw)
    assert "what shall we do next?" in improved
    assert len(changes) == 1
    assert changes[0].kind == "scope"


def test_parse_model_output_from_fenced_json() -> None:
    raw = """```json
{
  "improved": "fix the bug",
  "changes": [
    {"kind": "clarity", "description": "spelling", "before": "teh", "after": "the"}
  ]
}
```"""
    improved, changes = _parse_model_output(raw)
    assert improved == "fix the bug"
    assert len(changes) == 1
    assert changes[0].before == "teh"


def test_parse_model_output_improved_only_broken_json() -> None:
    raw = """{
  "improved": "## Goal
Document prioritisation and configuration.

## Deliverables
- Update docs/configuration.md"
}"""
    improved, changes = _parse_model_output(raw)
    assert "Document prioritisation" in improved
    assert changes == []


def test_parse_model_output_changes_before_improved() -> None:
    raw = """{
  "changes": [
    {"kind": "scope", "description": "expand", "before": "fix bug", "after": "## Goal\\nfix bug"}
  ],
  "improved": "fix the bug with tests"
}"""
    improved, changes = _parse_model_output(raw)
    assert improved == "fix the bug with tests"
    assert len(changes) == 1


def test_try_parse_plain_spec_accepts_markdown_sections() -> None:
    raw = (
        "## Goal\nEnsure docs cover prioritisation.\n\n"
        "## Deliverables\n- Update configuration.md\n- Cross-link from README"
    )
    parsed = _try_parse_plain_spec(raw)
    assert parsed is not None
    assert parsed.startswith("## Goal")


def test_try_parse_plain_spec_rejects_json_like_text() -> None:
    raw = '{"improved": "broken'
    assert _try_parse_plain_spec(raw) is None


def test_salvage_parse_failure_from_plain_markdown() -> None:
    original = (
        "ok ensure it's fully documented for priorisation and other confguration "
        "(not specificaly linked to mistral)"
    )
    raw = (
        "## Goal\n"
        "Ensure prioritisation and general Ylang configuration are fully documented.\n\n"
        "## Deliverables\n"
        "- Expand docs/configuration.md for model prioritisation\n"
        "- Document quality band, budget cap, and routing recipes\n"
        "- Keep examples provider-agnostic (not Mistral-specific)\n\n"
        "## Definition of done\n"
        "- configuration.md covers all YLANG_MODELS_* and tuning vars"
    )
    salvaged = _try_salvage_parse_failure(original, raw, True, resolved=_AGENT)
    assert salvaged is not None
    assert salvaged.validated is True
    assert "prioritisation" in salvaged.improved.lower()
