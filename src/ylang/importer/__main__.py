"""CLI: python -m ylang.importer"""

from __future__ import annotations

import argparse
from pathlib import Path

from ylang.importer import DEFAULT_PROMPTS_URL, import_into_library


def main() -> None:
    """Import a public prompt CSV into a local library database."""
    parser = argparse.ArgumentParser(description="Import public prompts into Ylang library")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".ylang") / "library.db",
        help="SQLite library path (default: .ylang/library.db)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PROMPTS_URL,
        help="CSV URL or local file path",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Local CSV file (overrides --url)",
    )
    args = parser.parse_args()
    result = import_into_library(
        args.db,
        url=None if args.csv else args.url,
        csv_path=args.csv,
    )
    print(f"imported={result.imported} skipped={result.skipped}")


if __name__ == "__main__":
    main()
