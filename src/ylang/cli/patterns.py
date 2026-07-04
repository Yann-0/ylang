"""CLI commands for pattern detection and learned template proposals."""

from __future__ import annotations

import argparse

from ylang.core.stores import open_stores
from ylang.library.pattern_detector import UsagePatternDetector, propose_template_from_pattern
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
    return parser


def print_pattern_proposals(proposals: list[tuple[object, object]]) -> None:
    """Pretty-print detected patterns and template proposals to stdout."""
    from ylang.library.patterns import DetectedPattern, TemplateProposal

    if not proposals:
        print("No patterns detected (need ≥3 similar improver prompts in the window).")
        return

    for index, (pattern, proposal) in enumerate(proposals, start=1):
        assert isinstance(pattern, DetectedPattern)
        assert isinstance(proposal, TemplateProposal)
        print(f"--- Proposal {index} ---")
        print(f"Pattern id:    {pattern.pattern_id}")
        print(f"Occurrences:   {pattern.occurrence_count}")
        print(f"Template id:   {proposal.suggested_template_id}")
        print(f"Name:          {proposal.name}")
        print(f"Rationale:     {proposal.rationale}")
        preview = pattern.sample_text[:200].replace("\n", " ")
        print(f"Sample:        {preview}")
        print()


def run_patterns_cli(argv: list[str] | None = None) -> int:
    """Entry point for ``ylang patterns`` subcommands."""
    parser = build_patterns_parser()
    args = parser.parse_args(argv)
    settings = Settings.load()
    stores = open_stores(settings.resolved_storage_path())
    try:
        if args.command == "suggest":
            detector = UsagePatternDetector(stores.store)  # type: ignore[attr-defined]
            patterns = detector.detect(window_days=args.window_days)
            proposals: list[tuple[object, object]] = []
            for pattern in patterns:
                proposal = propose_template_from_pattern(pattern)
                if proposal is not None:
                    proposals.append((pattern, proposal))
            print_pattern_proposals(proposals)
            return 0
    finally:
        stores.close()  # type: ignore[attr-defined]

    parser.print_help()
    return 1
