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
        model_improver_accepted_counts={},
    )
    print_usage_summary(summary)
    captured = capsys.readouterr()
    assert "Requests:     2" in captured.out
    assert "$0.1500" in captured.out
    assert "code" in captured.out


def test_usage_summary_cli(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    exit_code = run_usage_cli(
        ["dashboard", "--output", str(output), "--last-days", "7"]
    )
    assert exit_code == 0
    html = output.read_text(encoding="utf-8")
    assert "Ylang Usage Dashboard" in html
    assert "Requests" in html
    assert "chart.umd.min.js" in html
    assert "costChart" in html


def test_usage_digest_cli(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "digest.db"  # type: ignore[operator]
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
        timestamp=now - timedelta(days=1),
    )
    store.close()

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    exit_code = run_usage_cli(["digest", "--last-days", "7"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Ylang usage digest" in captured.out
    assert "Requests:" in captured.out
    assert "Top learned-template patterns" in captured.out


def test_try_desktop_notify_skips_without_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ylang.cli.usage import try_desktop_notify

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert try_desktop_notify("title", "body") is False


def test_try_desktop_notify_invokes_notify_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ylang.cli.usage import try_desktop_notify

    calls: list[list[str]] = []

    class _Result:
        returncode = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("ylang.cli.usage.shutil.which", lambda _name: "/usr/bin/notify-send")
    monkeypatch.setattr("ylang.cli.usage.subprocess.run", fake_run)
    assert try_desktop_notify("Ylang usage digest", "summary") is True
    assert calls
    assert calls[0][0] == "/usr/bin/notify-send"
    assert "Ylang usage digest" in calls[0]


def test_usage_digest_cli_notify_flag(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "digest-notify.db"  # type: ignore[operator]
    store = open_store(db_path)
    store.close()

    notified: list[tuple[str, str]] = []

    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    monkeypatch.setattr(
        "ylang.cli.usage.try_desktop_notify",
        lambda title, body: notified.append((title, body)) or True,
    )
    exit_code = run_usage_cli(["digest", "--last-days", "7", "--notify"])
    assert exit_code == 0
    assert len(notified) == 1
    assert notified[0][0] == "Ylang usage digest"
