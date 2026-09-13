#!/usr/bin/env python3
"""Refresh a public prompt CSV into candidate quarantine via the running MCP server.

Does not auto-promote. Review with ``ylang prompts candidates list``.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def _populate(*, mcp_url: str, auth_token: str, source_url: str | None) -> None:
    headers = {"Authorization": f"Bearer {auth_token}"}
    arguments: dict[str, str] = {}
    if source_url:
        arguments["url"] = source_url

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("import_public_prompts", arguments)
            payload = result.structuredContent or {}
            print(payload)


def main() -> None:
    """CLI entry for MCP-based public prompt candidate refresh."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mcp-url",
        default=os.environ.get("YLANG_MCP_URL", "http://127.0.0.1:8787/mcp"),
    )
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("YLANG_AUTH_TOKEN"),
        required=os.environ.get("YLANG_AUTH_TOKEN") is None,
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Optional one-shot CSV URL (never becomes a scheduled source)",
    )
    args = parser.parse_args()
    asyncio.run(
        _populate(mcp_url=args.mcp_url, auth_token=args.auth_token, source_url=args.url)
    )


if __name__ == "__main__":
    main()
