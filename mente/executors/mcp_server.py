"""Mente-owned MCP server for host-side bridge capabilities."""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from mente.executors.bridge_mcp import (
    publish_wechat_draft,
    query_mente_memory,
    save_mente_memory,
)

logger = logging.getLogger("mente.executors.mcp_server")

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment]
    _MCP_SERVER_AVAILABLE = False


def create_mcp_server() -> "FastMCP":
    """Create the Mente host-side MCP server."""

    if not _MCP_SERVER_AVAILABLE:
        raise ImportError(
            "Mente MCP bridge requires the 'mcp' package. "
            f"Install it in the active runtime for {sys.executable}."
        )

    mcp = FastMCP(
        "mente",
        instructions=(
            "Mente-managed host-side bridge tools. "
            "Use these tools instead of sandbox shell commands when a "
            "Mente capability is available."
        ),
    )

    @mcp.tool()
    def mente_memory_query(
        memory_scope: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Read Mente-managed memory for the current execution context."""

        return json.dumps(
            query_mente_memory(
                memory_scope=memory_scope,
                limit=limit,
            ),
            ensure_ascii=False,
        )

    @mcp.tool()
    def mente_memory_save(
        fact: str,
        memory_scope: str | None = None,
    ) -> str:
        """Persist an explicit fact into Mente-managed memory for the current execution context."""

        return json.dumps(
            save_mente_memory(
                fact=fact,
                memory_scope=memory_scope,
            ),
            ensure_ascii=False,
        )

    @mcp.tool()
    def mente_wechat_publish_draft(
        article_path: str,
        theme: str = "lapis",
        highlight: str = "solarized-light",
        sync: str | None = None,
    ) -> str:
        """Publish a local markdown file to the user's WeChat draft box."""

        return json.dumps(
            publish_wechat_draft(
                article_path=article_path,
                theme=theme,
                highlight=highlight,
                sync=sync,
            ),
            ensure_ascii=False,
        )

    return mcp


def run_mcp_server() -> None:
    """Run the Mente MCP bridge over stdio."""

    if not _MCP_SERVER_AVAILABLE:
        print(
            "Error: Mente MCP bridge requires the 'mcp' package.",
            file=sys.stderr,
        )
        sys.exit(1)

    server = create_mcp_server()

    async def _run() -> None:
        await server.run_stdio_async()

    asyncio.run(_run())


if __name__ == "__main__":
    run_mcp_server()
