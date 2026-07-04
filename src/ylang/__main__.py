"""Entry point for ``python -m ylang``.

With no subcommand, starts the MCP server (stdio or HTTP per ``Settings``).
Subcommands: ``usage`` (aggregates and HTML dashboard export) and ``patterns``
(learned-template proposals from improver usage history).
"""

from __future__ import annotations

import argparse
import sys

from ylang.mcp.server import run_server


def main() -> None:
    """Dispatch ``ylang usage``, ``ylang patterns``, or the MCP server."""
    if len(sys.argv) > 1 and sys.argv[1] == "usage":
        from ylang.cli.usage import run_usage_cli

        raise SystemExit(run_usage_cli(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "patterns":
        from ylang.cli.patterns import run_patterns_cli

        raise SystemExit(run_patterns_cli(sys.argv[2:]))

    parser = argparse.ArgumentParser(prog="ylang", description="Ylang MCP server")
    parser.parse_args(sys.argv[1:] if len(sys.argv) > 1 else [])
    run_server()


if __name__ == "__main__":
    main()
