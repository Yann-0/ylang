"""CLI commands for usage analytics."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from datetime import datetime, timezone

from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.core.stores import open_stores
from ylang.library.pattern_detector import (
    UsagePatternDetector,
    propose_template_from_pattern,
)
from ylang.settings import Settings
from ylang.usage.aggregates import daily_usage_buckets, rolling_cost, summarize_usage
from ylang.usage.dashboard import render_usage_dashboard_html
from ylang.usage.feedback import FeedbackStore
from ylang.usage.improver_analytics import summarize_improver, summarize_improver_quality
from ylang.usage.optimizer import generate_optimization_suggestions
from ylang.usage.store import UsageWindow


def build_usage_parser() -> argparse.ArgumentParser:
    """Build the ``ylang usage`` subcommand parser."""
    parser = argparse.ArgumentParser(prog="ylang usage", description="Usage analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="Print aggregated usage statistics")
    window = summary.add_mutually_exclusive_group()
    window.add_argument("--last-days", type=int, help="Rolling window in days")
    window.add_argument("--last-hours", type=int, help="Rolling window in hours")

    digest = subparsers.add_parser(
        "digest",
        help="Pretty usage digest with top patterns and budget warning",
    )
    digest_window = digest.add_mutually_exclusive_group()
    digest_window.add_argument("--last-days", type=int, help="Rolling window in days")
    digest_window.add_argument("--last-hours", type=int, help="Rolling window in hours")
    digest_notify = digest.add_mutually_exclusive_group()
    digest_notify.add_argument(
        "--notify",
        action="store_true",
        help="Attempt a desktop notification via notify-send (Linux)",
    )
    digest_notify.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip desktop notification even when usage_digest_enabled is on",
    )

    dashboard = subparsers.add_parser(
        "dashboard", help="Generate a static HTML usage dashboard"
    )
    dashboard.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/ylang-usage.html"),
        help="Output HTML file path",
    )
    dash_window = dashboard.add_mutually_exclusive_group()
    dash_window.add_argument("--last-days", type=int, help="Rolling window in days")
    dash_window.add_argument("--last-hours", type=int, help="Rolling window in hours")

    improver_report = subparsers.add_parser(
        "improver-report",
        help="Print improver funnel and template effectiveness report",
    )
    report_window = improver_report.add_mutually_exclusive_group()
    report_window.add_argument("--last-days", type=int, help="Rolling window in days")
    report_window.add_argument("--last-hours", type=int, help="Rolling window in hours")

    return parser


def _resolve_window(args: argparse.Namespace) -> UsageWindow:
    if args.last_hours is not None:
        return UsageWindow.last_hours(args.last_hours)
    days = getattr(args, "last_days", None)
    if days is not None:
        return UsageWindow.last_days(days)
    return UsageWindow.last_days(7)


def _open_stores_from_settings() -> tuple[object, Settings]:
    settings = Settings.load()
    path = settings.resolved_storage_path()
    return open_stores(path), settings


def _digest_enabled(runtime: RuntimeSettingsStore) -> bool:
    """Return True when the console/runtime digest flag is on."""
    raw = runtime.get("usage_digest_enabled")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def try_desktop_notify(title: str, body: str) -> bool:
    """Best-effort Linux desktop notification via ``notify-send``.

    Skips gracefully when no display session is available, ``notify-send`` is
    missing, or the subprocess fails. Returns ``True`` only when the notify
    command was invoked successfully (exit code 0).
    """
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    notify = shutil.which("notify-send")
    if notify is None:
        return False
    try:
        completed = subprocess.run(
            [notify, "--app-name=Ylang", title, body],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _digest_summary_line(summary: object, *, days: int) -> str:
    """Build a short notification body from a usage summary."""
    from ylang.usage.aggregates import UsageSummary

    assert isinstance(summary, UsageSummary)
    return (
        f"Last {days}d: {summary.total_requests} requests, "
        f"${summary.total_cost:.2f}, "
        f"{summary.success_rate * 100:.0f}% success"
    )


def print_usage_summary(summary: object) -> None:
    """Pretty-print a UsageSummary to stdout."""
    from ylang.usage.aggregates import UsageSummary

    assert isinstance(summary, UsageSummary)
    print(f"Requests:     {summary.total_requests}")
    print(f"Total cost:   ${summary.total_cost:.4f}")
    print(f"Tokens:       {summary.total_tokens:,}")
    print(f"Success rate: {summary.success_rate * 100:.1f}%")
    if summary.by_activity:
        print("\nBy activity:")
        for activity, count in sorted(
            summary.by_activity.items(), key=lambda item: item[1], reverse=True
        ):
            print(f"  {activity:30} {count:>6}")
    if summary.by_model:
        print("\nBy model:")
        for model, count in sorted(
            summary.by_model.items(), key=lambda item: item[1], reverse=True
        ):
            cost = summary.model_costs.get(model, 0.0)
            print(f"  {model:40} {count:>6}  ${cost:.4f}")


def print_usage_digest(
    summary: object,
    *,
    settings: Settings,
    store: object,
    window: UsageWindow,
) -> None:
    """Pretty-print a weekly-style digest with patterns and budget warning."""
    from ylang.usage.aggregates import UsageSummary

    assert isinstance(summary, UsageSummary)
    days = max(1, int((window.until - window.since).total_seconds() // 86400))
    print(f"=== Ylang usage digest (last {days} day{'s' if days != 1 else ''}) ===\n")
    print_usage_summary(summary)

    if settings.daily_budget_usd is not None:
        spent = rolling_cost(store, UsageWindow.last_hours(24))  # type: ignore[arg-type]
        budget = settings.daily_budget_usd
        pct = (spent / budget * 100) if budget else 0.0
        print(f"\nRolling 24h spend: ${spent:.2f} / ${budget:.2f} ({pct:.0f}%)")
        if spent >= budget:
            print("⚠ Budget exceeded — cloud models are filtered from routing.")
        elif spent >= budget * 0.8:
            print("⚠ Approaching daily budget cap (≥80%).")

    detector = UsagePatternDetector(store)  # type: ignore[arg-type]
    patterns = detector.detect(window_days=days)
    proposals = [
        proposal
        for pattern in patterns
        if (proposal := propose_template_from_pattern(pattern)) is not None
    ]
    print("\nTop learned-template patterns:")
    if not proposals:
        print("  (none — need ≥3 similar improver prompts in the window)")
    else:
        for index, proposal in enumerate(proposals[:5], start=1):
            print(f"  {index}. {proposal.suggested_template_id} — {proposal.rationale}")
            print(f"     apply: ylang patterns apply --index {index} --yes")

    from ylang.usage.optimizer import serialize_suggestion

    feedback = FeedbackStore(store._connection)  # type: ignore[attr-defined]
    suggestions = generate_optimization_suggestions(
        store,  # type: ignore[arg-type]
        window,
        feedback=feedback,
    )
    print("\nOptimization suggestions:")
    if not suggestions:
        print("  (none — need more improver usage data)")
    else:
        for index, suggestion in enumerate(suggestions[:5], start=1):
            serialized = serialize_suggestion(suggestion)
            print(f"  {index}. [{serialized['priority']}] {serialized['title']}")
            print(f"     {serialized['evidence']}")


def print_improver_report(store: object, window: UsageWindow) -> None:
    """Pretty-print improver funnel and template effectiveness."""
    from ylang.usage.feedback import FeedbackStore
    from ylang.usage.improver_analytics import template_effectiveness
    from ylang.usage.optimizer import serialize_funnel, serialize_template_row

    feedback = FeedbackStore(store._connection)  # type: ignore[attr-defined]
    report = summarize_improver_quality(store, window, feedback)  # type: ignore[arg-type]
    serialized = serialize_funnel(report.funnel, report.quality)
    print("=== Improver funnel ===")
    print(f"Fired:      {serialized['total_fired']}")
    print(
        f"Validated:  {serialized['total_validated']} ({serialized['validation_rate']:.0%})"
    )
    print(
        f"Changed:    {serialized['total_changed']} ({serialized['change_rate']:.0%})"
    )
    print(
        f"Accepted:   {serialized['total_accepted']} ({serialized['accept_rate']:.0%})"
    )
    polish = serialized.get("polish_ratio")
    performance = serialized.get("performance_ratio")
    polish_txt = f"{polish:.0%}" if isinstance(polish, float) else "—"
    perf_txt = f"{performance:.0%}" if isinstance(performance, float) else "—"
    print(f"Polish:     {polish_txt} (n={serialized.get('polish_sample_count', 0)})")
    print(f"Performance:{perf_txt}")
    if serialized["by_mode"]:
        print("\nBy mode:")
        for mode, stats in serialized["by_mode"].items():
            print(
                f"  {mode:12} fired={stats['fired']:>4} "
                f"accept={stats['accept_rate']:.0%} "
                f"avg_cost=${stats['avg_cost']:.4f}"
            )
    rows = template_effectiveness(store, window)  # type: ignore[arg-type]
    print("\nTemplate effectiveness (min 3 injections):")
    if not rows:
        print("  (none)")
    else:
        for row in rows[:10]:
            item = serialize_template_row(row)
            print(
                f"  {item['template_id']:30} "
                f"injections={item['injections']:>3} "
                f"accept={item['accept_rate']:.0%}"
            )


def run_usage_cli(argv: list[str] | None = None) -> int:
    """Entry point for ``ylang usage`` subcommands."""
    parser = build_usage_parser()
    args = parser.parse_args(argv)
    stores, settings = _open_stores_from_settings()
    try:
        window = _resolve_window(args)
        summary = summarize_usage(stores.store, window)  # type: ignore[attr-defined]
        buckets = daily_usage_buckets(stores.store, window)  # type: ignore[attr-defined]

        if args.command == "summary":
            print_usage_summary(summary)
            return 0

        if args.command == "digest":
            print_usage_digest(
                summary,
                settings=settings,
                store=stores.store,  # type: ignore[attr-defined]
                window=window,
            )
            runtime = RuntimeSettingsStore(stores.store._connection)  # type: ignore[attr-defined]
            runtime.set("usage_digest_last_at", datetime.now(timezone.utc).isoformat())
            want_notify = False
            if getattr(args, "no_notify", False):
                want_notify = False
            elif getattr(args, "notify", False):
                want_notify = True
            else:
                want_notify = _digest_enabled(runtime)
            if want_notify:
                days = max(
                    1, int((window.until - window.since).total_seconds() // 86400)
                )
                notified = try_desktop_notify(
                    "Ylang usage digest",
                    _digest_summary_line(summary, days=days),
                )
                if notified:
                    print("\nDesktop notification sent (notify-send).", file=sys.stderr)
                else:
                    print(
                        "\nDesktop notification skipped "
                        "(need DISPLAY/WAYLAND_DISPLAY + notify-send).",
                        file=sys.stderr,
                    )
            return 0

        if args.command == "dashboard":
            funnel = summarize_improver(stores.store, window)  # type: ignore[attr-defined]
            html = render_usage_dashboard_html(
                summary,
                title="Ylang Usage Dashboard",
                daily_buckets=buckets,
                improver_funnel=funnel,
            )
            args.output.write_text(html, encoding="utf-8")
            print(f"Wrote dashboard to {args.output.resolve()}", file=sys.stderr)
            try:
                webbrowser.open(args.output.resolve().as_uri())
            except OSError:
                pass
            return 0

        if args.command == "improver-report":
            print_improver_report(stores.store, window)  # type: ignore[attr-defined]
            return 0
    finally:
        stores.close()  # type: ignore[attr-defined]

    parser.print_help()
    return 1
