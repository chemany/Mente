from argparse import Namespace
import types
from unittest.mock import patch

from hermes_cli.config import DEFAULT_CONFIG, load_config
from hermes_cli.main import (
    _resolve_dashboard_autostart_enabled,
    _resolve_dashboard_embedded_chat_enabled,
)


def test_dashboard_embedded_chat_default_is_enabled(tmp_path):
    with patch.dict(
        "os.environ",
        {"HERMES_HOME": str(tmp_path), "MENTE_HOME": str(tmp_path)},
        clear=False,
    ):
        cfg = load_config()

    assert DEFAULT_CONFIG["dashboard"]["embedded_chat"] is True
    assert DEFAULT_CONFIG["dashboard"]["autostart_on_chat_launch"] is True
    assert DEFAULT_CONFIG["dashboard"]["host"] == "127.0.0.1"
    assert DEFAULT_CONFIG["dashboard"]["port"] == 9119
    assert cfg["dashboard"]["embedded_chat"] is True
    assert cfg["dashboard"]["autostart_on_chat_launch"] is True
    assert cfg["dashboard"]["host"] == "127.0.0.1"
    assert cfg["dashboard"]["port"] == 9119


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


def test_dashboard_autostart_uses_config_without_overrides(monkeypatch):
    monkeypatch.delenv("HERMES_DASHBOARD_AUTOSTART", raising=False)

    assert (
        _resolve_dashboard_autostart_enabled(
            {"dashboard": {"autostart_on_chat_launch": False}},
        )
        is False
    )
    assert (
        _resolve_dashboard_autostart_enabled(
            {"dashboard": {"autostart_on_chat_launch": True}},
        )
        is True
    )


def test_dashboard_autostart_env_overrides_config(monkeypatch):
    monkeypatch.setenv("HERMES_DASHBOARD_AUTOSTART", "0")
    assert (
        _resolve_dashboard_autostart_enabled(
            {"dashboard": {"autostart_on_chat_launch": True}},
        )
        is False
    )

    monkeypatch.setenv("HERMES_DASHBOARD_AUTOSTART", "1")
    assert (
        _resolve_dashboard_autostart_enabled(
            {"dashboard": {"autostart_on_chat_launch": False}},
        )
        is True
    )


def test_cmd_chat_autostarts_dashboard_before_tui(monkeypatch):
    import hermes_cli.main as main_mod

    calls: list[str] = []

    monkeypatch.setattr(main_mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(main_mod, "_resolve_last_session", lambda source="cli": None)
    monkeypatch.setattr(main_mod, "_resolve_session_by_name_or_id", lambda value: value)
    monkeypatch.setattr(main_mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main_mod.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(main_mod, "_maybe_autostart_dashboard_for_chat", lambda args, use_tui: calls.append("dashboard"))

    def fake_launch_tui(*args, **kwargs):
        calls.append("tui")
        raise SystemExit(0)

    monkeypatch.setattr(main_mod, "_launch_tui", fake_launch_tui)

    args = types.SimpleNamespace(
        continue_last=None,
        resume=None,
        query=None,
        yolo=False,
        ignore_user_config=False,
        ignore_rules=False,
        source=None,
        tui=False,
        tui_dev=False,
        model=None,
        provider=None,
        toolsets=None,
        skills=None,
        verbose=False,
        quiet=False,
        image=None,
        worktree=False,
        checkpoints=False,
        pass_session_id=False,
        max_turns=None,
    )

    with patch.dict("os.environ", {}, clear=False):
        try:
            main_mod.cmd_chat(args)
        except SystemExit:
            pass

    assert calls == ["dashboard", "tui"]


def test_cmd_chat_query_does_not_autostart_dashboard(monkeypatch):
    import hermes_cli.main as main_mod
    import sys

    monkeypatch.setattr(main_mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(main_mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main_mod.sys.stdout, "isatty", lambda: True)

    called = {"dashboard": 0}

    monkeypatch.setattr(
        main_mod,
        "_maybe_autostart_dashboard_for_chat",
        lambda args, use_tui: called.__setitem__("dashboard", called["dashboard"] + 1),
    )

    fake_cli_module = types.SimpleNamespace(main=lambda **kwargs: None)
    monkeypatch.setitem(sys.modules, "cli", fake_cli_module)

    args = types.SimpleNamespace(
        continue_last=None,
        resume=None,
        query="hello",
        yolo=False,
        ignore_user_config=False,
        ignore_rules=False,
        source=None,
        tui=False,
        tui_dev=False,
        model=None,
        provider=None,
        toolsets=None,
        skills=None,
        verbose=False,
        quiet=False,
        image=None,
        worktree=False,
        checkpoints=False,
        pass_session_id=False,
        max_turns=None,
    )

    with patch.dict("os.environ", {}, clear=False):
        main_mod.cmd_chat(args)

    assert called["dashboard"] == 0
