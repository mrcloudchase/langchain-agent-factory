"""MCP surface helpers. The Agent Server already serves /mcp; this just shows how to attach.

Claude Code:   claude mcp add --transport http engineering_assistant http://localhost:2024/mcp
Cursor:        add {"url": "http://localhost:2024/mcp"} under mcpServers in settings.
Python client: see `list_remote_tools` below (uses the official MCP SDK over Streamable HTTP).
"""

from __future__ import annotations

import asyncio

from agent_factory.surfaces import deployment_url


async def _list_tools(url: str, headers: dict | None = None) -> list[dict]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [{"name": t.name, "description": t.description} for t in tools.tools]


def list_remote_tools(url: str | None = None, api_key: str | None = None) -> list[dict]:
    """List the factory agents a deployment exposes as MCP tools."""
    headers = {"X-Api-Key": api_key} if api_key else None
    return asyncio.run(_list_tools((url or deployment_url()) + "/mcp", headers))
