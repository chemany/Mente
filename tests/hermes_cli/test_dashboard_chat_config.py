from argparse import Namespace
from unittest.mock import patch

from hermes_cli.config import DEFAULT_CONFIG, load_config
from hermes_cli.main import _resolve_dashboard_embedded_chat_enabled


def test_dashboard_embedded_chat_default_is_enabled(tmp_path):
    with patch.dict(
        "os.environ",
        {"HERMES_HOME": str(tmp_path), "MENTE_HOME": str(tmp_path)},
        clear=False,
    ):
        cfg = load_config()

    assert DEFAULT_CONFIG["dashboard"]["embedded_chat"] is True
    assert cfg["dashboard"]["embedded_chat"] is True


def test_dashboard_embedded_chat_uses_config_without_overrides(monkeypatch):
    monkeypatch.delenv("HERMES_DASHBOARD_TUI", raising=False)

    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=None),
            {"dashboard": {"embedded_chat": False}},
        )
        is False
    )
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=None),
            {"dashboard": {"embedded_chat": True}},
        )
        is True
    )


def test_dashboard_embedded_chat_cli_overrides_config(monkeypatch):
    monkeypatch.delenv("HERMES_DASHBOARD_TUI", raising=False)

    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=True),
            {"dashboard": {"embedded_chat": False}},
        )
        is True
    )
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=False),
            {"dashboard": {"embedded_chat": True}},
        )
        is False
    )


def test_dashboard_embedded_chat_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_TUI", "1")
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=False),
            {"dashboard": {"embedded_chat": True}},
        )
        is False
    )

    monkeypatch.setenv("HERMES_DASHBOARD_TUI", "0")
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=True),
            {"dashboard": {"embedded_chat": False}},
        )
        is True
    )


def test_dashboard_embedded_chat_env_overrides_config(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_TUI", "0")
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=None),
            {"dashboard": {"embedded_chat": True}},
        )
        is False
    )

    monkeypatch.setenv("HERMES_DASHBOARD_TUI", "1")
    assert (
        _resolve_dashboard_embedded_chat_enabled(
            Namespace(tui=None),
            {"dashboard": {"embedded_chat": False}},
        )
        is True
    )
