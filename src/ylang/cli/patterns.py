"""CLI commands for pattern detection and learned template proposals."""

from __future__ import annotations

import argparse
import sys

from ylang.core.stores import open_stores
from ylang.library.pattern_detector import UsagePatternDetector, propose_template_from_pattern
from ylang.library.patterns import DetectedPattern, TemplateProposal
from ylang.library.store import save_learned_template
from ylang.settings import Settings


def build_patterns_parser() -> argparse.ArgumentParser:
    """Build the ``ylang patterns`` subcommand parser."""
    parser = argparse.ArgumentParser(prog="ylang patterns", description="Pattern detection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    suggest = subparsers.add_parser("suggest", help="Show learned template proposals from usage")
    suggest.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Rolling window in days (default: 30)",
    )

    apply_cmd = subparsers.add_parser(
        "apply",
        help="Save a learned template from a detected pattern proposal",
    )
    apply_cmd.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Rolling window in days (default: 30)",
    )
    apply_cmd.add_argument(
        "--index",
        type=int,
        help="1-based proposal index to apply (interactive when omitted)",
    )
    apply_cmd.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    return parser


def collect_pattern_proposals(
    store: object,
    *,
    window_days: int,
) -> list[tuple[DetectedPattern, TemplateProposal]]:
    """Detect patterns and build template proposals."""
    detector = UsagePatternDetector(store)  # type: ignore[arg-type]
    patterns = detector.detect(window_days=window_days)
    proposals: list[tuple[DetectedPattern, TemplateProposal]] = []
    for pattern in patterns:
        proposal = propose_template_from_pattern(pattern)
        if proposal is not None:
            proposals.append((pattern, proposal))
    return proposals


def print_pattern_proposals(proposals: list[tuple[DetectedPattern, TemplateProposal]]) -> None:
    """Pretty-print detected patterns and template proposals to stdout."""
    if not proposals:
        print("No patterns detected (need ≥3 similar improver prompts in the window).")
        return

    for index, (pattern, proposal) in enumerate(proposals, start=1):
        print(f"--- Proposal {index} ---")
        print(f"Pattern id:    {pattern.pattern_id}")
        print(f"Occurrences:   {pattern.occurrence_count}")
        print(f"Template id:   {proposal.suggested_template_id}")
        print(f"Name:          {proposal.name}")
        print(f"Rationale:     {proposal.rationale}")
        preview = pattern.sample_text[:200].replace("\n", " ")
        print(f"Sample:        {preview}")
        print()


def _prompt_apply_index(count: int) -> int | None:
    """Ask the user which proposal to apply; return 1-based index or None."""
    try:
        raw = input(f"Apply which proposal? [1-{count}, q to cancel]: ").strip()
    except EOFError:
        return None
    if raw.lower() in {"q", "quit", ""}:
        return None
    try:
        index = int(raw)
    except ValueError:
        print("Invalid index.", file=sys.stderr)
        return None
    if index < 1 or index > count:
        print(f"Index must be between 1 and {count}.", file=sys.stderr)
        return None
    return index


def apply_pattern_proposal(
    library: object,
    proposals: list[tuple[DetectedPattern, TemplateProposal]],
    *,
    index: int,
) -> str:
    """Persist the selected proposal as a learned template."""
    pattern, proposal = proposals[index - 1]
    save_learned_template(
        library,  # type: ignore[arg-type]
        proposal.suggested_template_id,
        name=proposal.name,
        body=proposal.body,
        params=proposal.params,
    )
    return proposal.suggested_template_id


def run_patterns_cli(argv: list[str] | None = None) -> int:
    """Entry point for ``ylang patterns`` subcommands."""
    parser = build_patterns_parser()
    args = parser.parse_args(argv)
    settings = Settings.load()
    stores = open_stores(settings.resolved_storage_path())
    try:
        if args.command == "suggest":
            proposals = collect_pattern_proposals(
                stores.store,  # type: ignore[attr-defined]
                window_days=args.window_days,
            )
            print_pattern_proposals(proposals)
            return 0

        if args.command == "apply":
            proposals = collect_pattern_proposals(
                stores.store,  # type: ignore[attr-defined]
                window_days=args.window_days,
            )
            if not proposals:
                print("No patterns detected (need ≥3 similar improver prompts in the window).")
                return 1

            index = args.index
            if index is None:
                print_pattern_proposals(proposals)
                index = _prompt_apply_index(len(proposals))
                if index is None:
                    print("Cancelled.")
                    return 1
            elif index < 1 or index > len(proposals):
                print(f"Index must be between 1 and {len(proposals)}.", file=sys.stderr)
                return 1

            _, proposal = proposals[index - 1]
            if not args.yes:
                answer = input(f"Save template {proposal.suggested_template_id!r}? [y/N]: ").strip()
                if answer.lower() not in {"y", "yes"}:
                    print("Cancelled.")
                    return 1

            template_id = apply_pattern_proposal(
                stores.library,  # type: ignore[attr-defined]
                proposals,
                index=index,
            )
            print(f"Saved learned template: {template_id}")
            return 0
    finally:
        stores.close()  # type: ignore[attr-defined]

    parser.print_help()
    return 1
