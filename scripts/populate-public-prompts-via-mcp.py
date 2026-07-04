#!/usr/bin/env python3
"""Import the public awesome-chatgpt-prompts CSV via the running Ylang MCP server."""

from __future__ import annotations

import argparse
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ylang.importer.convert import convert_rows, parse_csv_rows
from ylang.importer.fetch import DEFAULT_PROMPTS_URL, load_csv_text
from ylang.library.types import TemplateParam


def _serialize_params(params: list[TemplateParam]) -> list[dict[str, str | None]]:
    return [
        {"name": p.name, "description": p.description, "default": p.default}
        for p in params
    ]


async def _populate(*, mcp_url: str, auth_token: str, source_url: str) -> None:
    csv_text = load_csv_text(url=source_url)
    prompts = convert_rows(parse_csv_rows(csv_text))
    print(f"Fetched {len(prompts)} prompts from {source_url}")

    headers = {"Authorization": f"Bearer {auth_token}"}
    imported = 0
    skipped = 0
    errors = 0

    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            existing = await session.call_tool("list_templates", {})
            existing_ids = {
                item["template_id"]
                for item in existing.structuredContent.get("templates", [])
            }

            for spec in prompts:
                if spec.template_id in existing_ids:
                    skipped += 1
                    continue
                result = await session.call_tool(
                    "save_template",
                    {
                        "template_id": spec.template_id,
                        "name": spec.name,
                        "body": spec.body,
                        "params": _serialize_params(spec.params),
                        "visibility": "public",
                        "tags": [spec.template_id.replace("-", " ")],
                    },
                )
                payload = result.structuredContent
                if not payload.get("ok", False):
                    errors += 1
                    print(f"ERROR {spec.template_id}: {payload.get('error', payload)}")
                    continue
                imported += 1
                existing_ids.add(spec.template_id)

    print(f"done imported={imported} skipped={skipped} errors={errors}")


def main() -> None:
    """CLI entry for MCP-based public prompt population."""
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
    parser.add_argument("--url", default=DEFAULT_PROMPTS_URL)
    args = parser.parse_args()
    asyncio.run(_populate(mcp_url=args.mcp_url, auth_token=args.auth_token, source_url=args.url))


if __name__ == "__main__":
    main()
