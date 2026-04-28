import asyncio
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource


def _make_runner():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner.session_store = None
    runner.config = None
    runner._voice_mode = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._show_reasoning = False
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._service_tier = None
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_tasks = set()
    runner._session_db = None
    runner._session_model_overrides = {}
    runner._session_reasoning_overrides = {}
    runner._pending_model_notes = {}
    runner._pending_approvals = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._draining = False
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.hooks.loaded_hooks = []
    return runner


@pytest.mark.asyncio
async def test_run_agent_routes_to_mente_when_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    mente_result = {
        "final_response": "via mente",
        "last_reasoning": None,
        "messages": [],
        "api_calls": 0,
        "tools": [],
        "history_offset": 0,
        "last_prompt_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model": "gpt-5-codex",
        "session_id": "session-1",
        "response_previewed": False,
    }
    monkeypatch.setattr(
        gateway_run,
        "_run_mente_gateway_turn",
        lambda **kwargs: mente_result,
        raising=False,
    )

    fake_run_agent = types.ModuleType("run_agent")

    class _ExplodingAgent:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy AIAgent path should not be used")

    fake_run_agent.AIAgent = _ExplodingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    runner = _make_runner()
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="ping",
        context_prompt="session context",
        history=[{"role": "user", "content": "earlier"}],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
    )

    assert result == mente_result

