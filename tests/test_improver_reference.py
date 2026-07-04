"""Tests for file/terminal reference prompt detection."""

from __future__ import annotations

from ylang.improver.reference import is_reference_only_prompt, scrub_file_reference_numbers


def test_reference_only_terminal_pointer() -> None:
    prompt = r"@\home\yann\.cursor\projects\srv-ylang\terminals\8.txt:7-31"
    assert is_reference_only_prompt(prompt) is True


def test_reference_only_markdown_range() -> None:
    assert is_reference_only_prompt("@ylang-improved-prompt.md (1-20)") is True


def test_task_verb_is_not_reference_only() -> None:
    assert is_reference_only_prompt("fix this : @ylang-improved-prompt.md (1-20)") is False


def test_scrub_file_reference_numbers() -> None:
    text = r"@terminals\8.txt:7-31 fix gateway tests"
    scrubbed = scrub_file_reference_numbers(text)
    assert "8" not in scrubbed
    assert "7" not in scrubbed
    assert "31" not in scrubbed
    assert "gateway" in scrubbed
