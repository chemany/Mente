"""Resolve runtime home and default output paths for xhs-daily-news."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from hermes_constants import display_hermes_home as display_agent_home
    from hermes_constants import get_hermes_home as get_agent_home
except (ModuleNotFoundError, ImportError):

    def get_agent_home() -> Path:
        """Return the runtime agent home directory."""
        hermes_home = os.environ.get("HERMES_HOME", "").strip()
        if hermes_home:
            return Path(hermes_home).expanduser()

        mente_home = os.environ.get("MENTE_HOME", "").strip()
        if mente_home:
            return Path(mente_home).expanduser()

        return Path.home() / ".mente"

    def display_agent_home() -> str:
        """Return a user-friendly agent home path."""
        home = get_agent_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)


def get_agent_env_path() -> Path:
    """Return the default agent-managed .env path."""
    return get_agent_home() / ".env"


def get_default_output_dir() -> Path:
    """Return the default working directory for generated news artifacts."""
    configured = os.environ.get("XHS_DAILY_NEWS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return get_agent_home() / "xhs-daily-news"
