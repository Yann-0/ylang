"""Tests for improver input sample persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from ylang.usage.sample import truncate_improver_input_sample
from ylang.usage.store import UsageWindow, open_store


def test_truncate_improver_input_sample() -> None:
    short = "fix the bug"
    assert truncate_improver_input_sample(short) == short
    long_text = "x" * 250
    truncated = truncate_improver_input_sample(long_text)
    assert truncated is not None
    assert len(truncated) == 200
    assert truncated.endswith("...")


def test_write_usage_stores_improver_input_sample(tmp_path: object) -> None:
    store = open_store(tmp_path / "sample.db")  # type: ignore[operator]
    store.write_usage(
        surface="mcp",
        activity="improve:agent",
        model_used="m",
        prompt_tokens=1,
        cost=0.0,
        improver_fired=True,
        improver_accepted=False,
        latency_ms=1,
        success=True,
        timestamp=datetime.now(timezone.utc),
        improver_input_sample="Refactor auth module",
    )
    rows = store.recall_usage(UsageWindow.last_days(1))
    assert len(rows) == 1
    assert rows[0].improver_input_sample == "Refactor auth module"
