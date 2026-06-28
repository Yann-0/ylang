"""Entry point for `python -m ylang`."""

from ylang.mcp.server import run_server


def main() -> None:
    """Start the ylang MCP server."""
    run_server()


if __name__ == "__main__":
    main()
