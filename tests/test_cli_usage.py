"""Unit tests for usage CLI commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ylang.cli.usage import print_usage_summary, run_usage_cli
from ylang.usage.aggregates import UsageSummary
from ylang.usage.store import open_store


def test_print_usage_summary(capsys: pytest.CaptureFixture[str]) -> None:
    summary = UsageSummary(
        total_requests=2,
        total_cost=0.15,
        total_tokens=300,
        success_rate=1.0,
        by_activity={"code": 2},
        by_model={"openai/gpt-4o": 2},
        model_costs={"openai/gpt-4o": 0.15},
        model_success_counts={"openai/gpt-4o": 2},
    )
    print_usage_summary(summary)
    captured = capsys.readouterr()
    assert "Requests:     2" in captured.out
    assert "$0.1500" in captured.out
    assert "code" in captured.out


def test_usage_summary_cli(tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "cli.db"  # type: ignore[operator]
    store = open_store(db_path)
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="mcp",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=50,
        cost=0.01,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=5,
        success=True,
        timestamp=now - timedelta(hours=2),
    )
    store.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    exit_code = run_usage_cli(["summary", "--last-hours", "24"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Requests:     1" in captured.out


def test_usage_dashboard_cli(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dash.db"  # type: ignore[operator]
    store = open_store(db_path)
    now = datetime.now(timezone.utc)
    store.write_usage(
        surface="gateway",
        activity="code",
        model_used="openai/gpt-4o",
        prompt_tokens=10,
        cost=0.02,
        improver_fired=False,
        improver_accepted=False,
        latency_ms=3,
        success=True,
        timestamp=now - timedelta(days=1),
    )
    store.close()

    output = tmp_path / "usage.html"  # type: ignore[operator]
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    monkeypatch.setattr("webbrowser.open", lambda _url: None)
    exit_code = run_usage_cli(["dashboard", "--output", str(output), "--last-days", "7"])
    assert exit_code == 0
    html = output.read_text(encoding="utf-8")
    assert "Ylang Usage Dashboard" in html
    assert "Requests" in html
