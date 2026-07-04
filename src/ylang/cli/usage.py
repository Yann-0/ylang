"""CLI commands for usage analytics."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from ylang.core.stores import open_stores
from ylang.settings import Settings
from ylang.usage.aggregates import daily_usage_buckets, summarize_usage
from ylang.usage.dashboard import render_usage_dashboard_html
from ylang.usage.store import UsageWindow


def build_usage_parser() -> argparse.ArgumentParser:
    """Build the ``ylang usage`` subcommand parser."""
    parser = argparse.ArgumentParser(prog="ylang usage", description="Usage analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="Print aggregated usage statistics")
    window = summary.add_mutually_exclusive_group()
    window.add_argument("--last-days", type=int, help="Rolling window in days")
    window.add_argument("--last-hours", type=int, help="Rolling window in hours")

    dashboard = subparsers.add_parser("dashboard", help="Generate a static HTML usage dashboard")
    dashboard.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/ylang-usage.html"),
        help="Output HTML file path",
    )
    dash_window = dashboard.add_mutually_exclusive_group()
    dash_window.add_argument("--last-days", type=int, help="Rolling window in days")
    dash_window.add_argument("--last-hours", type=int, help="Rolling window in hours")

    return parser


def _resolve_window(args: argparse.Namespace) -> UsageWindow:
    if args.last_hours is not None:
        return UsageWindow.last_hours(args.last_hours)
    days = getattr(args, "last_days", None)
    if days is not None:
        return UsageWindow.last_days(days)
    return UsageWindow.last_days(7)


def _open_stores_from_settings() -> tuple[object, object]:
    settings = Settings.load()
    path = settings.resolved_storage_path()
    return open_stores(path), settings


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
        for activity, count in sorted(summary.by_activity.items(), key=lambda item: item[1], reverse=True):
            print(f"  {activity:30} {count:>6}")
    if summary.by_model:
        print("\nBy model:")
        for model, count in sorted(summary.by_model.items(), key=lambda item: item[1], reverse=True):
            cost = summary.model_costs.get(model, 0.0)
            print(f"  {model:40} {count:>6}  ${cost:.4f}")


def run_usage_cli(argv: list[str] | None = None) -> int:
    """Entry point for ``ylang usage`` subcommands."""
    parser = build_usage_parser()
    args = parser.parse_args(argv)
    stores, _settings = _open_stores_from_settings()
    try:
        window = _resolve_window(args)
        summary = summarize_usage(stores.store, window)  # type: ignore[attr-defined]
        buckets = daily_usage_buckets(stores.store, window)  # type: ignore[attr-defined]

        if args.command == "summary":
            print_usage_summary(summary)
            return 0

        if args.command == "dashboard":
            html = render_usage_dashboard_html(
                summary,
                title="Ylang Usage Dashboard",
                daily_buckets=buckets,
            )
            args.output.write_text(html, encoding="utf-8")
            print(f"Wrote dashboard to {args.output.resolve()}", file=sys.stderr)
            try:
                webbrowser.open(args.output.resolve().as_uri())
            except OSError:
                pass
            return 0
    finally:
        stores.close()  # type: ignore[attr-defined]

    parser.print_help()
    return 1
