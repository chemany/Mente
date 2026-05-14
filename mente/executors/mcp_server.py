"""Mente-owned MCP server for host-side bridge capabilities."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path
import sys

from mente.executors.bridge_mcp import (
    publish_wechat_draft,
    query_mente_memory,
    save_mente_memory,
)
from hermes_constants import get_skills_dir

logger = logging.getLogger("mente.executors.mcp_server")

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore[assignment]
    _MCP_SERVER_AVAILABLE = False


_TEXT_RESOURCE_SUFFIXES = {
    "",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_MAX_RESOURCE_FILE_BYTES = 512 * 1024


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

    _register_local_skill_resources(mcp)

    return mcp


def _register_local_skill_resources(mcp: "FastMCP") -> None:
    """Expose local skill files as MCP resources for the private Codex runtime."""

    for path in _iter_local_skill_resource_files():
        uri = path.resolve().as_uri()
        mime_type = mimetypes.guess_type(str(path))[0] or "text/plain"

        @mcp.resource(  # type: ignore[misc]
            uri,
            name=path.name,
            title=path.name,
            mime_type=mime_type,
            description=f"Local skill resource at {path}",
        )
        def _read_resource(_path: Path = path) -> str:
            return _path.read_text(encoding="utf-8", errors="replace")


def _iter_local_skill_resource_files() -> list[Path]:
    """Return a de-duplicated list of local skill files safe to expose as resources."""

    roots: list[Path] = [get_skills_dir()]

    seen_roots: set[Path] = set()
    resource_files: list[Path] = []
    seen_files: set[Path] = set()
    for root in roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if resolved_root in seen_roots or not resolved_root.is_dir():
            continue
        seen_roots.add(resolved_root)
        for candidate in resolved_root.rglob("*"):
            if not candidate.is_file():
                continue
            suffix = candidate.suffix.lower()
            if suffix not in _TEXT_RESOURCE_SUFFIXES:
                continue
            try:
                resolved_candidate = candidate.resolve()
                if resolved_candidate.stat().st_size > _MAX_RESOURCE_FILE_BYTES:
                    continue
            except OSError:
                continue
            if resolved_candidate in seen_files:
                continue
            seen_files.add(resolved_candidate)
            resource_files.append(resolved_candidate)
    return resource_files


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
