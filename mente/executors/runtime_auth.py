"""Private runtime auth materialization for Mente-backed Codex execution."""

from __future__ import annotations

import json
from pathlib import Path

from hermes_cli.auth import resolve_codex_runtime_credentials


def write_private_runtime_auth(runtime_home: Path) -> str:
    """Write the minimal private auth payload required by the vendored runtime."""
    creds = resolve_codex_runtime_credentials(refresh_if_expiring=True)
    auth_path = runtime_home / "auth.json"
    auth_path.write_text(
        json.dumps({"OPENAI_API_KEY": creds["api_key"]}),
        encoding="utf-8",
    )
    auth_path.chmod(0o600)
    return "hermes-auth-store"
