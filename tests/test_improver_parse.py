"""Unit tests for improver JSON parsing."""

from __future__ import annotations

from ylang.improver.improver import _extract_json_payload, _parse_model_output


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
