"""Task class detection for improver tuning."""

from __future__ import annotations

from ylang.improver.registry import detect_task_class


def test_detect_analysis_task() -> None:
    assert detect_task_class("do a deep dive and prepare a product backlog") == "analysis"


def test_detect_implementation_task() -> None:
    assert detect_task_class("implement dark mode toggle with tests") == "implementation"


def test_detect_structural_default() -> None:
    assert detect_task_class("fix typo in readme") == "structural"
