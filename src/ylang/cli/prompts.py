"""CLI commands for prompt sources and candidate review."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from typing import Any

from ylang.core.engine import Engine
from ylang.core.stores import open_stores
from ylang.core.types import CompletionResult, Message
from ylang.importer.evaluate import (
    EvaluationAuthorizationError,
    SimulatedCompleter,
    evaluate_candidate,
    execute_candidate_evaluation,
)
from ylang.importer.metrics import collect_metrics
from ylang.importer.policy import SourcePolicyError
from ylang.importer.promote import (
    PromotionError,
    candidate_diff_text,
    promote_candidate,
    reject_candidate,
    review_candidate,
)
from ylang.importer.refresh import open_source_store, refresh_all_enabled, refresh_source
from ylang.importer.source_types import (
    REVIEW_QUEUE_STATES,
    PromptSource,
    RefreshSummary,
    SourceItem,
)
from ylang.settings import Settings
from ylang.usage.experiments import ExperimentStore

LARGE_CATALOG_WARN_THRESHOLD = 500


def _warn_large_catalog(summary: RefreshSummary) -> None:
    """Warn when a refresh ingested a large candidate set (no silent truncation)."""
    total = summary.new + summary.changed + summary.unchanged
    if total < LARGE_CATALOG_WARN_THRESHOLD:
        return
    print(
        (
            f"warning: {summary.source_id} refresh touched {total} items "
            f"(new={summary.new} changed={summary.changed} unchanged={summary.unchanged}); "
            "large catalogs are fully ingested — review candidates before promoting"
        ),
        file=sys.stderr,
    )


class _EngineCompleter:
    """Adapt ``Engine.complete`` to the evaluation Completer protocol."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def complete(
        self,
        messages: list[Message],
        activity: str,
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        template_version: int | None = None,
    ) -> CompletionResult:
        """Delegate to the shared Engine without granting extra tools."""
        return self._engine.complete(
            messages,
            activity,
            model=model,
            tools=tools,
            template_version=template_version,
        )


def build_prompts_parser() -> argparse.ArgumentParser:
    """Build the ``ylang prompts`` subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="ylang prompts",
        description="Prompt intelligence: sources, refresh, and candidate review",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    sources = groups.add_parser("sources", help="List or enable allowlisted sources")
    sources_sub = sources.add_subparsers(dest="command", required=True)
    sources_sub.add_parser("list", help="List sources and last refresh")
    enable = sources_sub.add_parser("enable", help="Enable scheduled refresh for a source")
    enable.add_argument("source_id")
    disable = sources_sub.add_parser("disable", help="Disable scheduled refresh")
    disable.add_argument("source_id")

    refresh = groups.add_parser("refresh", help="Refresh candidates from a source")
    refresh.add_argument("source_id", nargs="?", help="Source id (omit with --all)")
    refresh.add_argument(
        "--all",
        action="store_true",
        dest="refresh_all",
        help="Refresh all enabled scheduled sources that are due",
    )
    refresh.add_argument(
        "--force",
        action="store_true",
        help="Ignore per-source refresh intervals (scheduled --all only)",
    )

    candidates = groups.add_parser("candidates", help="Review quarantined candidates")
    cand_sub = candidates.add_subparsers(dest="command", required=True)
    list_cmd = cand_sub.add_parser("list", help="List candidates")
    list_cmd.add_argument("--state", default=None)
    list_cmd.add_argument("--source", default=None)
    show = cand_sub.add_parser("show", help="Show one candidate")
    show.add_argument("item_id")
    diff = cand_sub.add_parser("diff", help="Diff candidate vs previous/local body")
    diff.add_argument("item_id")
    review = cand_sub.add_parser("review", help="Mark reviewed without promoting")
    review.add_argument("item_id")
    reject = cand_sub.add_parser("reject", help="Reject; unchanged hash will not resurface")
    reject.add_argument("item_id")
    promote = cand_sub.add_parser("promote", help="Promote to an immutable local template")
    promote.add_argument("item_id")
    promote.add_argument("--acknowledge-risk", action="store_true")
    promote.add_argument("--template-id", default=None)
    evaluate = cand_sub.add_parser(
        "evaluate",
        help="Inspect (default, zero paid calls) or execute a bounded Engine comparison",
    )
    evaluate.add_argument("item_id")
    evaluate.add_argument("--vs", dest="vs_template_id", default=None)
    evaluate.add_argument(
        "--fixture-file",
        default=None,
        help="Optional local sample. Inspect stores it locally; execute sends only this operator fixture",
    )
    evaluate.add_argument(
        "--mode",
        choices=("inspect", "execute"),
        default="inspect",
        help="inspect = static/observational (default). execute requires authorization.",
    )
    evaluate.add_argument(
        "--authorize-paid",
        action="store_true",
        help="Required for --mode execute against a real provider",
    )
    evaluate.add_argument(
        "--budget-usd",
        type=float,
        default=0.0,
        help="Hard spend cap for --mode execute (default 0 = refuse paid calls)",
    )
    evaluate.add_argument("--model", default=None, help="Explicit model for execute")
    evaluate.add_argument(
        "--simulated",
        action="store_true",
        help="Use a local simulated completer (mechanics only, not prompt quality)",
    )

    groups.add_parser("metrics", help="Local source/candidate and promoted-usage metrics")
    return parser


def _print_source_row(source: PromptSource) -> None:
    enabled = "on" if getattr(source, "enabled") else "off"
    compat = source.compatibility_status
    print(
        f"{source.source_id:28} {enabled:3} {source.license_spdx:8} "
        f"compat={compat:13} "
        f"rev={source.last_revision or '-'} "
        f"err={source.last_error or '-'}"
    )


def _print_item(item: SourceItem, *, verbose: bool = False) -> None:
    print(
        f"{item.item_id}\n"
        f"  title={item.title}\n"
        f"  state={item.candidate_state} risk={item.risk_level} "
        f"quality={item.quality_score} task={item.task_family}\n"
        f"  source={item.source_id} rev={item.source_revision or '-'}\n"
        f"  hash={item.content_hash[:12]} dup={item.duplicate_of_item_id or '-'}"
    )
    if verbose:
        print(f"  risk_reasons={','.join(item.risk_reasons) or '-'}")
        print(f"  quality_reasons={','.join(item.quality_reasons)}")
        print(f"  url={item.canonical_url or '-'}")
        print(f"  linked={item.linked_template_id or '-'}@{item.linked_template_version or '-'}")
        print("--- body ---")
        print(item.body)


def run_prompts_cli(argv: list[str] | None = None) -> int:
    """Run ``ylang prompts`` against local SQLite."""
    parser = build_prompts_parser()
    args = parser.parse_args(argv)
    settings = Settings.load()
    stores = open_stores(settings.resolved_storage_path())
    try:
        source_store = open_source_store(stores.library)
        group = args.group
        if group == "sources":
            if args.command == "list":
                for source in source_store.list_sources():
                    _print_source_row(source)
                return 0
            if args.command == "enable":
                try:
                    updated = source_store.set_enabled(args.source_id, True)
                except SourcePolicyError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                if updated is None:
                    print(f"unknown source: {args.source_id}", file=sys.stderr)
                    return 1
                print(f"enabled {args.source_id} (scheduled refresh still opt-in via cron/timer)")
                return 0
            updated = source_store.set_enabled(args.source_id, False)
            if updated is None:
                print(f"unknown source: {args.source_id}", file=sys.stderr)
                return 1
            print(f"disabled {args.source_id}")
            return 0
        if group == "refresh":
            if args.refresh_all:
                summaries = refresh_all_enabled(
                    source_store, stores.library, force=args.force
                )
                if not summaries:
                    print("No enabled scheduled sources. Enable with: ylang prompts sources enable <id>")
                    return 0
                for summary in summaries:
                    print(json.dumps(asdict(summary), default=str))
                    _warn_large_catalog(summary)
                return 0 if all(item.status != "error" for item in summaries) else 1
            if not args.source_id:
                parser.error("source_id or --all is required")
            summary = refresh_source(source_store, stores.library, args.source_id)
            print(json.dumps(asdict(summary), default=str))
            _warn_large_catalog(summary)
            return 0 if summary.status in {"success", "unchanged"} else 1
        if group == "metrics":
            metrics = collect_metrics(
                source_store, stores.store, library=stores.library
            )
            print(json.dumps(asdict(metrics), indent=2))
            return 0
        command = args.command
        if command == "list":
            states = (args.state,) if args.state else tuple(REVIEW_QUEUE_STATES)
            items = source_store.list_items(
                source_id=args.source,
                states=states,
            )
            if not items:
                print("No candidates.")
                return 0
            for item in items:
                _print_item(item)
            return 0
        item = source_store.get_item(args.item_id)
        if item is None:
            print(f"unknown candidate: {args.item_id}", file=sys.stderr)
            return 1
        if command == "show":
            _print_item(item, verbose=True)
            return 0
        if command == "diff":
            print(candidate_diff_text(item, stores.library))
            return 0
        try:
            if command == "review":
                review_candidate(source_store, args.item_id)
                print(f"reviewed {args.item_id}")
                return 0
            if command == "reject":
                reject_candidate(source_store, args.item_id)
                print(f"rejected {args.item_id}")
                return 0
            if command == "promote":
                template = promote_candidate(
                    source_store,
                    stores.library,
                    args.item_id,
                    acknowledge_risk=args.acknowledge_risk,
                    template_id=args.template_id,
                    usage_store=stores.store,
                )
                print(
                    f"promoted {args.item_id} -> {template.template_id} v{template.version}"
                )
                return 0
            if command == "evaluate":
                fixture_input = None
                if args.fixture_file:
                    fixture_path = Path(args.fixture_file)
                    if not fixture_path.is_file():
                        print(f"fixture file not found: {fixture_path}", file=sys.stderr)
                        return 1
                    fixture_input = fixture_path.read_text(encoding="utf-8")
                if args.mode == "inspect":
                    if args.authorize_paid or args.simulated or args.budget_usd:
                        print(
                            "inspect mode ignores --authorize-paid/--budget-usd/--simulated; "
                            "it never makes provider calls",
                            file=sys.stderr,
                        )
                    report = evaluate_candidate(
                        item,
                        stores.library,
                        ExperimentStore(stores.store._connection),
                        stores.store,
                        vs_template_id=args.vs_template_id,
                        fixture_input=fixture_input,
                        source_store=source_store,
                    )
                    print(json.dumps(asdict(report), default=str, indent=2))
                    return 0
                try:
                    completer: SimulatedCompleter | _EngineCompleter
                    if args.simulated:
                        completer = SimulatedCompleter()
                    else:
                        completer = _EngineCompleter(
                            Engine.from_settings(
                                stores.store, surface="eval", settings=settings
                            )
                        )
                    run = execute_candidate_evaluation(
                        item,
                        stores.library,
                        completer=completer,
                        fixtures=[fixture_input] if fixture_input else [],
                        source_store=source_store,
                        vs_template_id=args.vs_template_id,
                        authorize_paid=args.authorize_paid,
                        budget_usd=args.budget_usd,
                        model=args.model,
                        simulated=args.simulated,
                    )
                except EvaluationAuthorizationError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                print(json.dumps(asdict(run), default=str, indent=2))
                return 0
        except PromotionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        parser.error(f"unknown command {command}")
        return 2
    finally:
        stores.close()
