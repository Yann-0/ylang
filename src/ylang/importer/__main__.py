"""CLI entry: ``python -m ylang.importer``.

Defaults to a local ``.ylang/library.db`` path; production deployments typically
pass ``--db`` pointing at the shared Ylang storage file.

Internet prompts are imported as **candidates**. Prefer
``ylang prompts refresh prompts-chat``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ylang.importer import import_into_library


def main() -> None:
    """Import a public prompt CSV into candidate quarantine."""
    parser = argparse.ArgumentParser(
        description="Import public prompts as candidates (not auto-promoted)"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".ylang") / "library.db",
        help="SQLite library path (default: .ylang/library.db)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="CSV URL (manual import; never becomes a scheduled source)",
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
    print(
        f"ok={result.ok} imported={result.imported} skipped={result.skipped} "
        f"source={result.source_id} error={result.error or '-'}"
    )


if __name__ == "__main__":
    main()
