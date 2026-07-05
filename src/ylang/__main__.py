"""Entry point for ``python -m ylang``.

With no subcommand, starts the MCP server (stdio or HTTP per ``Settings``).
Subcommands: ``usage``, ``patterns``, ``backup``, ``export``, ``import``, ``doctor``.
"""

from __future__ import annotations

import argparse
import sys

from ylang.mcp.server import run_server


def main() -> None:
    """Dispatch CLI subcommands or the MCP server."""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "usage":
            from ylang.cli.usage import run_usage_cli

            raise SystemExit(run_usage_cli(sys.argv[2:]))
        if command == "patterns":
            from ylang.cli.patterns import run_patterns_cli

            raise SystemExit(run_patterns_cli(sys.argv[2:]))
        if command == "backup":
            from ylang.cli.ops import run_backup_cli

            raise SystemExit(run_backup_cli(sys.argv[2:]))
        if command == "export":
            from ylang.cli.ops import run_export_cli

            raise SystemExit(run_export_cli(sys.argv[2:]))
        if command == "import":
            from ylang.cli.ops import run_import_cli

            raise SystemExit(run_import_cli(sys.argv[2:]))
        if command == "doctor":
            from ylang.cli.ops import run_doctor_cli

            raise SystemExit(run_doctor_cli(sys.argv[2:]))

    parser = argparse.ArgumentParser(prog="ylang", description="Ylang MCP server")
    parser.parse_args(sys.argv[1:] if len(sys.argv) > 1 else [])
    run_server()


if __name__ == "__main__":
    main()
