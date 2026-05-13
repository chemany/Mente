"""Regression coverage for TUI agent bootstrap runtime resolution."""

from unittest.mock import MagicMock, patch

from mente.executors.runtime_config import ModelRuntime, RuntimeConfig


def test_make_agent_uses_mente_runtime_config_instead_of_runtime_provider():
    """TUI session bootstrap must read runtime details from Mente's own config
    surface rather than Hermes runtime_provider."""

    fake_runtime = RuntimeConfig(
        runtime_home=MagicMock(),
        model_runtime=ModelRuntime(
            model="mimo-v2.5-pro",
            provider="xiaomi",
            base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
            api_mode="anthropic_messages",
            source="mente_model_settings",
        ),
        subprocess_env={"MENTE_CODEX_API_KEY": "tp-test-key"},
    )

    fake_cfg = {
        "model": {"default": "mimo-v2.5-pro", "provider": "xiaomi"},
        "agent": {"system_prompt": "test"},
    }

    with (
        patch("tui_gateway.server._load_cfg", return_value=fake_cfg),
        patch("tui_gateway.server._get_db", return_value=MagicMock()),
        patch("tui_gateway.server._load_tool_progress_mode", return_value="compact"),
        patch("tui_gateway.server._load_reasoning_config", return_value=None),
        patch("tui_gateway.server._load_service_tier", return_value=None),
        patch("tui_gateway.server._load_enabled_toolsets", return_value=None),
        patch("tui_gateway.server._resolve_mente_tui_runtime", return_value=fake_runtime) as mock_resolve,
        patch("run_agent.AIAgent") as mock_agent,
    ):
        from tui_gateway.server import _make_agent

        _make_agent("sid-1", "key-1")

        mock_resolve.assert_called_once_with()

        call_kwargs = mock_agent.call_args
        assert call_kwargs.kwargs["provider"] == "xiaomi"
        assert call_kwargs.kwargs["base_url"] == "https://token-plan-cn.xiaomimimo.com/anthropic"
        assert call_kwargs.kwargs["api_key"] == "tp-test-key"
        assert call_kwargs.kwargs["api_mode"] == "anthropic_messages"


def test_make_agent_ignores_display_personality_without_system_prompt():
    """The TUI matches the classic CLI: personality only becomes active once
    it has been saved to agent.system_prompt."""

    fake_runtime = RuntimeConfig(
        runtime_home=MagicMock(),
        model_runtime=ModelRuntime(
            model="glm-5",
            provider="openrouter",
            base_url="https://api.synthetic.new/v1",
            api_mode="chat_completions",
            source="mente_model_settings",
        ),
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-test"},
    )
    fake_cfg = {
        "agent": {
            "system_prompt": "",
            "personalities": {"kawaii": "sparkle system prompt"},
        },
        "display": {"personality": "kawaii"},
        "model": {"default": "glm-5"},
    }

    with (
        patch("tui_gateway.server._load_cfg", return_value=fake_cfg),
        patch("tui_gateway.server._get_db", return_value=MagicMock()),
        patch("tui_gateway.server._resolve_mente_tui_runtime", return_value=fake_runtime),
        patch("run_agent.AIAgent") as mock_agent,
    ):
        from tui_gateway.server import _make_agent

        _make_agent("sid-default-personality", "key-default-personality")

        assert mock_agent.call_args.kwargs["ephemeral_system_prompt"] is None


def test_probe_config_health_flags_null_sections():
    """Bare YAML keys (`agent:` with no value) parse as None and silently
    drop nested settings; probe must surface them so users can fix."""
    from tui_gateway.server import _probe_config_health

    assert _probe_config_health({"agent": {"x": 1}}) == ""
    assert _probe_config_health({}) == ""

    msg = _probe_config_health({"agent": None, "display": None, "model": {}})
    assert "agent" in msg and "display" in msg
    assert "model" not in msg


def test_probe_config_health_flags_null_personalities_with_active_personality():
    from tui_gateway.server import _probe_config_health

    msg = _probe_config_health(
        {
            "agent": {"personalities": None},
            "display": {"personality": "kawaii"},
            "model": {},
        }
    )
    assert "display.personality" in msg
    assert "agent.personalities" in msg


def test_make_agent_tolerates_null_config_sections():
    """Bare `agent:` / `display:` keys in ~/.hermes/config.yaml parse as
    None. cfg.get("agent", {}) returns None (default only fires on missing
    key), so downstream .get() chains must be guarded. Reported via Twitter
    against the new TUI."""

    fake_runtime = RuntimeConfig(
        runtime_home=MagicMock(),
        model_runtime=ModelRuntime(
            model="glm-5",
            provider="openrouter",
            base_url="https://api.synthetic.new/v1",
            api_mode="chat_completions",
            source="mente_model_settings",
        ),
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-test"},
    )
    null_cfg = {"agent": None, "display": None, "model": {"default": "glm-5"}}

    with (
        patch("tui_gateway.server._load_cfg", return_value=null_cfg),
        patch("tui_gateway.server._get_db", return_value=MagicMock()),
        patch("tui_gateway.server._resolve_mente_tui_runtime", return_value=fake_runtime),
        patch("run_agent.AIAgent") as mock_agent,
    ):

        from tui_gateway.server import _make_agent

        _make_agent("sid-null", "key-null")

        assert mock_agent.called


def test_make_agent_tolerates_null_personalities_with_active_personality():
    fake_runtime = RuntimeConfig(
        runtime_home=MagicMock(),
        model_runtime=ModelRuntime(
            model="glm-5",
            provider="openrouter",
            base_url="https://api.synthetic.new/v1",
            api_mode="chat_completions",
            source="mente_model_settings",
        ),
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-test"},
    )
    cfg = {
        "agent": {"personalities": None},
        "display": {"personality": "kawaii"},
        "model": {"default": "glm-5"},
    }

    with (
        patch("tui_gateway.server._load_cfg", return_value=cfg),
        patch("tui_gateway.server._get_db", return_value=MagicMock()),
        patch("cli.load_cli_config", return_value={"agent": {"personalities": None}}),
        patch("tui_gateway.server._resolve_mente_tui_runtime", return_value=fake_runtime),
        patch("run_agent.AIAgent") as mock_agent,
    ):
        from tui_gateway.server import _make_agent

        _make_agent("sid-null-personality", "key-null-personality")

        assert mock_agent.called
        assert mock_agent.call_args.kwargs["ephemeral_system_prompt"] is None
