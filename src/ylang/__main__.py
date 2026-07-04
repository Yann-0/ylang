"""Entry point for `python -m ylang`."""

from __future__ import annotations

import argparse
import sys

from ylang.mcp.server import run_server


def main() -> None:
    """Start the ylang MCP server or run CLI subcommands."""
    if len(sys.argv) > 1 and sys.argv[1] == "usage":
        from ylang.cli.usage import run_usage_cli

        raise SystemExit(run_usage_cli(sys.argv[2:]))

    parser = argparse.ArgumentParser(prog="ylang", description="Ylang MCP server")
    parser.parse_args(sys.argv[1:] if len(sys.argv) > 1 else [])
    run_server()


if __name__ == "__main__":
    main()
