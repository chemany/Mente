import asyncio
import logging
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource
from mente.integrations.bridge import build_gateway_task
from mente.task_core.models import ExecutionMode, ExecutionResult, ExecutionSession, SessionMode
from mente.task_core.repository import SQLiteTaskRepository


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


class _FollowupAdapter(BasePlatformAdapter):
    SUPPORTS_MESSAGE_EDITING = True

    def __init__(self, platform=Platform.FEISHU):
        self.platform = platform
        self.sent = []
        self.typing = []

    @property
    def name(self) -> str:
        return "review-followup"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sent.append(
            {
                "chat_id": chat_id,
                "content": content,
                "reply_to": reply_to,
                "metadata": metadata,
            }
        )
        return SendResult(success=True, message_id="review-followup-1")

    async def edit_message(self, chat_id, message_id, content, *, finalize=False) -> SendResult:
        raise AssertionError("narrow T5 cleanup should not send gateway progress edits")

    async def send_typing(self, chat_id, metadata=None) -> None:
        self.typing.append({"chat_id": chat_id, "metadata": metadata})

    async def stop_typing(self, chat_id) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


class _ProgressAdapter(BasePlatformAdapter):
    SUPPORTS_MESSAGE_EDITING = True

    def __init__(self, platform=Platform.FEISHU):
        self.platform = platform
        self.sent = []
        self.edits = []

    @property
    def name(self) -> str:
        return "progress-adapter"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sent.append(
            {
                "chat_id": chat_id,
                "content": content,
                "reply_to": reply_to,
                "metadata": metadata,
            }
        )
        return SendResult(success=True, message_id="progress-msg-1")

    async def edit_message(self, chat_id, message_id, content, *, finalize=False) -> SendResult:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "content": content,
                "finalize": finalize,
            }
        )
        return SendResult(success=True, message_id=message_id)

    async def send_typing(self, chat_id, metadata=None) -> None:
        return None

    async def stop_typing(self, chat_id) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


def test_run_mente_gateway_turn_without_continuity_uses_sessionful_start_with_seeded_history(
    monkeypatch,
):
    captured = {}

    def _fake_run_gateway_task(**kwargs):
        captured.update(kwargs)
        return ExecutionResult(status="success", summary="done")

    monkeypatch.setattr("mente.integrations.bridge.run_gateway_task", _fake_run_gateway_task)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    fallback_history_fact = 'Conversation history (JSON):\n[{"role":"user","content":"before"}]'

    result = gateway_run._run_mente_gateway_turn(
        message="latest question",
        context_prompt="session context",
        history=[{"role": "user", "content": "before"}],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=False,
    )

    assert result["final_response"] == "done"
    assert captured["execution_mode"] is ExecutionMode.SESSIONFUL
    assert captured["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert captured["fallback_history_fact"] == fallback_history_fact
    assert captured["replay_history_in_memory_facts"] is False


def test_run_mente_gateway_turn_with_active_continuity_uses_resume_without_history_replay(
    monkeypatch,
):
    captured = {}

    def _fake_run_gateway_task(**kwargs):
        captured.update(kwargs)
        return ExecutionResult(
            status="success",
            summary="done",
            metadata={
                "execution_session": {
                    "mode": "resume",
                    "continuity_id": "thread-123",
                    "continuity_status": "resumed",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setattr("mente.integrations.bridge.run_gateway_task", _fake_run_gateway_task)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = gateway_run._run_mente_gateway_turn(
        message="latest question",
        context_prompt="session context",
        history=[{"role": "user", "content": "before"}],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-123",
        ),
        fallback_history_fact=None,
        replay_history_in_memory_facts=False,
    )

    assert result["final_response"] == "done"
    assert captured["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert captured["fallback_history_fact"] is None
    assert captured["replay_history_in_memory_facts"] is False


def test_run_mente_gateway_turn_threads_cancel_event(monkeypatch):
    captured = {}

    def _fake_run_gateway_task(**kwargs):
        captured.update(kwargs)
        return ExecutionResult(status="success", summary="done")

    monkeypatch.setattr("mente.integrations.bridge.run_gateway_task", _fake_run_gateway_task)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    cancel_event = threading.Event()

    result = gateway_run._run_mente_gateway_turn(
        message="latest question",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        cancel_event=cancel_event,
    )

    assert result["final_response"] == "done"
    assert captured["cancel_event"] is cancel_event


def test_run_mente_gateway_turn_collapses_long_failed_summary(monkeypatch):
    machine_dump = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-123"}',
            '{"type":"turn.started"}',
            '{"type":"turn.failed","error":{"message":"cancelled"}}',
        ]
    )

    def _fake_run_gateway_task(**kwargs):
        return ExecutionResult(
            status="failed",
            summary=machine_dump,
            failure_reason="interrupted_by_user",
        )

    monkeypatch.setattr("mente.integrations.bridge.run_gateway_task", _fake_run_gateway_task)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = gateway_run._run_mente_gateway_turn(
        message="为什么没发布成功",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
    )

    assert result["failed"] is True
    assert result["final_response"] == "⚠️ 任务已取消。"


def test_run_mente_gateway_turn_exposes_task_snapshot_fields(monkeypatch):
    def _fake_run_gateway_task(**kwargs):
        return ExecutionResult(
            status="success",
            summary="已定位服务目录，待读取配置。",
            follow_up_tasks=["读取 .env", "确认 URL"],
            artifacts_out=["/tmp/report.md"],
            memory_candidates=["用户偏好需要自然语言解释"],
            metadata={
                "task_id": "task-123",
                "execution_session": {
                    "mode": "start",
                    "continuity_id": "thread-123",
                    "continuity_status": "started",
                },
                "task_profile": "investigation",
            },
        )

    monkeypatch.setattr("mente.integrations.bridge.run_gateway_task", _fake_run_gateway_task)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = gateway_run._run_mente_gateway_turn(
        message="继续任务",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
    )

    assert result["mente_task_id"] == "task-123"
    assert result["assistant_summary"] == "已定位服务目录，待读取配置。"
    assert result["follow_up_tasks"] == ["读取 .env", "确认 URL"]
    assert result["artifacts_out"] == ["/tmp/report.md"]
    assert result["memory_candidates"] == ["用户偏好需要自然语言解释"]
    assert result["task_profile"] == "investigation"


def test_format_mente_memory_review_outcome_persisted():
    assert gateway_run._format_mente_memory_review_outcome(
        {
            "status": "persisted",
            "persisted_count": 2,
        }
    ) == "💾 记忆复盘已保存（2 条）"


def test_format_mente_memory_review_outcome_noop():
    assert gateway_run._format_mente_memory_review_outcome(
        {
            "status": "noop",
        }
    ) == "🧠 记忆复盘完成，无新增记忆"


def test_format_mente_memory_review_outcome_common_skips_are_silent():
    assert gateway_run._format_mente_memory_review_outcome(
        {
            "status": "skipped",
            "reason": "disabled",
        }
    ) is None
    assert gateway_run._format_mente_memory_review_outcome(
        {
            "status": "skipped",
            "reason": "unsupported_source",
        }
    ) is None


def test_format_mente_skill_review_outcome_suggested():
    assert gateway_run._format_mente_skill_review_outcome(
        {
            "status": "suggested",
            "target_skill": "coding/python-debug",
        }
    ) == "🛠️ 技能复盘已生成建议：coding/python-debug"


def test_format_mente_skill_review_outcome_patched():
    assert gateway_run._format_mente_skill_review_outcome(
        {
            "status": "patched",
            "target_skill": "coding/python-debug",
        }
    ) == "🛠️ 技能复盘已更新：coding/python-debug"


def test_format_mente_skill_review_outcome_noop_is_silent():
    assert gateway_run._format_mente_skill_review_outcome(
        {
            "status": "noop",
        }
    ) is None


def test_format_mente_skill_review_outcome_patch_not_allowed_is_silent():
    assert gateway_run._format_mente_skill_review_outcome(
        {
            "status": "skipped",
            "reason": "patch_not_allowed",
        }
    ) is None


@pytest.mark.asyncio
async def test_run_agent_does_not_register_post_delivery_review_followups_for_gateway_chats(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    review_calls = []
    skill_review_calls = []

    def _fake_review(task_id):
        review_calls.append(task_id)
        return {
            "status": "persisted",
            "candidate_count": 1,
            "persisted_count": 1,
            "memory_ids": ["task-1:review:0"],
        }

    def _fake_skill_review(task_id):
        skill_review_calls.append(task_id)
        return {
            "status": "suggested",
            "mode": "suggest",
            "target_skill": "coding/python-debug",
            "candidate_count": 1,
            "artifact_path": "/tmp/task-1.json",
            "summary": "Suggested review for skill 'coding/python-debug'.",
        }

    monkeypatch.setattr(
        gateway_run,
        "_run_mente_gateway_turn",
        lambda **kwargs: {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        },
        raising=False,
    )
    monkeypatch.setattr(
        gateway_run,
        "_run_mente_post_turn_memory_review",
        _fake_review,
        raising=False,
    )
    monkeypatch.setattr(
        gateway_run,
        "_run_mente_post_turn_skill_review",
        _fake_skill_review,
        raising=False,
    )

    adapter = _FollowupAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="ping",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=7,
    )

    assert result["final_response"] == "done"
    assert review_calls == []
    assert adapter.sent == []

    assert getattr(adapter, "_post_delivery_callbacks", {}) == {}
    assert review_calls == []
    assert skill_review_calls == []
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_run_agent_mente_suppresses_static_progress_protocol_messages_by_default(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        for event_type in (
            "executor.runtime_config_resolved",
            "executor.auth_prepared",
            "kernel.workspace_prepared",
            "kernel.bridge_invoking",
            "kernel.codex.turn.started",
            "kernel.codex.turn.completed",
            "kernel.bridge_completed",
        ):
            event_callback(event_type, {})
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="帮我看看这个项目报错原因",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=9,
    )

    await asyncio.sleep(0.1)

    assert result["final_response"] == "done"
    assert adapter.sent == []
    assert adapter.edits == []


@pytest.mark.asyncio
async def test_run_agent_mente_logs_prompt_and_cache_diagnostics_even_when_progress_disabled(
    monkeypatch, caplog
):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setenv("HERMES_TOOL_PROGRESS_MODE", "off")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "executor.prompt_prepared",
            {
                "task_id": "task-1",
                "session_id": "session-1",
                "prompt_char_count": 812,
                "memory_fact_count": 2,
                "memory_char_count": 120,
                "prompt_fingerprint": "abc123",
            },
        )
        event_callback(
            "kernel.codex.turn.completed",
            {
                "usage": {
                    "input_tokens": 1800,
                    "output_tokens": 30,
                    "cached_input_tokens": 1536,
                    "cache_write_tokens": 0,
                }
            },
        )
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    with caplog.at_level(logging.INFO, logger="gateway.run"):
        result = await runner._run_agent(
            message="测试缓存命中情况",
            context_prompt="session context",
            history=[],
            source=source,
            session_id="session-1",
            session_key="agent:main:feishu:dm:oc_test",
            run_generation=10,
        )

    assert result["final_response"] == "done"
    assert adapter.sent == []
    assert adapter.edits == []
    assert any(
        "prompt_fingerprint=abc123" in record.message
        and "memory_fact_count=2" in record.message
        for record in caplog.records
    )
    assert any(
        "cached_input_tokens=1536" in record.message
        and "session_id=session-1" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_agent_mente_promotes_interruptable_handle_and_shares_cancel_event(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    started = asyncio.Event()
    release = asyncio.Event()
    captured = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["cancel_event"] = kwargs["cancel_event"]
        captured["running_agent"] = runner._running_agents.get(session_key)
        started.set()
        await release.wait()
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _fake_to_thread)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    session_key = "agent:main:feishu:dm:oc_test"
    runner._running_agents[session_key] = gateway_run._AGENT_PENDING_SENTINEL

    task = asyncio.create_task(
        runner._run_agent(
            message="缓存命中测试",
            context_prompt="session context",
            history=[],
            source=source,
            session_id="session-1",
            session_key=session_key,
            run_generation=12,
        )
    )

    await started.wait()

    handle = runner._running_agents[session_key]
    assert handle is not gateway_run._AGENT_PENDING_SENTINEL
    assert handle is captured["running_agent"]
    assert captured["cancel_event"].is_set() is False

    handle.interrupt("stop")
    assert captured["cancel_event"].is_set() is True

    release.set()
    result = await task

    assert result["final_response"] == "done"
    assert session_key not in runner._running_agents


@pytest.mark.asyncio
async def test_run_agent_mente_host_timeout_cancels_stalled_turn(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_mente_gateway_host_timeout_seconds",
        lambda **_kwargs: 0.01,
        raising=False,
    )
    monkeypatch.setattr(
        gateway_run,
        "_MENTE_GATEWAY_CANCEL_GRACE_SECONDS",
        0.01,
        raising=False,
    )

    captured = {}

    async def _fake_to_thread(func, *args, **kwargs):
        captured["cancel_event"] = kwargs["cancel_event"]
        await asyncio.sleep(0.05)
        return {
            "final_response": "late",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _fake_to_thread)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="发布一篇公众号草稿并配图",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=13,
    )

    assert "已取消" in result["final_response"]
    assert result["failed"] is True
    assert captured["cancel_event"].is_set() is True


@pytest.mark.asyncio
async def test_run_agent_mente_passes_content_publishing_timeout_config(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"agent": {"mente_content_publishing_timeout": 321}},
        raising=False,
    )

    captured = {}

    monkeypatch.setattr(
        gateway_run,
        "_resolve_mente_gateway_host_timeout_seconds",
        lambda **kwargs: captured.setdefault(
            "content_publishing_timeout_seconds",
            kwargs.get("content_publishing_timeout_seconds"),
        ),
        raising=False,
    )

    async def _fake_to_thread(func, *args, **kwargs):
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _fake_to_thread)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=13,
    )

    assert result["final_response"] == "done"
    assert captured["content_publishing_timeout_seconds"] == 321


@pytest.mark.asyncio
async def test_run_agent_mente_host_timeout_recovers_publishing_draft_when_source_exists(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_mente_gateway_host_timeout_seconds",
        lambda **_kwargs: 0.01,
        raising=False,
    )
    monkeypatch.setattr(
        gateway_run,
        "_MENTE_GATEWAY_CANCEL_GRACE_SECONDS",
        0.01,
        raising=False,
    )

    async def _fake_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0.05)
        return {
            "final_response": "late",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(
        gateway_run,
        "_attempt_mente_gateway_timeout_recovery",
        lambda **_kwargs: {
            "ok": True,
            "final_response": "📰 已根据已生成草稿完成公众号草稿发布。",
            "failed": False,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
        },
        raising=False,
    )

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=14,
    )

    assert result["final_response"] == "📰 已根据已生成草稿完成公众号草稿发布。"
    assert result["failed"] is False


@pytest.mark.asyncio
async def test_run_agent_mente_host_timeout_recovers_after_fast_cancelled_failure(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_mente_gateway_host_timeout_seconds",
        lambda **_kwargs: 0.01,
        raising=False,
    )

    async def _fake_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0.02)
        return {
            "final_response": "⚠️ 任务已取消。",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": True,
        }

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _fake_to_thread)

    captured: dict[str, object] = {}

    def _fake_recovery(**kwargs):
        captured.update(kwargs)
        return {
            "final_response": "📰 已根据已生成草稿完成公众号草稿发布。",
            "failed": False,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
        }

    monkeypatch.setattr(
        gateway_run,
        "_attempt_mente_gateway_timeout_recovery",
        _fake_recovery,
        raising=False,
    )

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=15,
    )

    assert captured["session_id"] == "session-1"
    assert result["final_response"] == "📰 已根据已生成草稿完成公众号草稿发布。"
    assert result["failed"] is False


def test_attempt_mente_gateway_timeout_recovery_returns_specific_publish_failure(monkeypatch):
    monkeypatch.setattr(
        gateway_run,
        "logger",
        MagicMock(),
    )

    monkeypatch.setattr(
        "mente.integrations.bridge.recover_gateway_content_publishing_artifacts",
        lambda **_kwargs: {
            "ok": False,
            "reason": "wechat_ip_not_whitelisted",
            "failure_summary": "微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。文章与配图已生成，请在微信公众平台后台将该服务器 IP 加入白名单后重试。",
            "publish_result": {
                "stdout": "🔐 正在获取 access_token...",
                "stderr": "invalid ip 1.2.3.4, not in whitelist",
            },
        },
    )

    result = gateway_run._attempt_mente_gateway_timeout_recovery(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        channel_prompt=None,
        session_id="session-1",
        history_length=0,
    )

    assert result["failed"] is True
    assert result["final_response"] == (
        "⚠️ 微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。文章与配图已生成，请在微信公众平台后台将该服务器 IP 加入白名单后重试。"
    )


@pytest.mark.asyncio
async def test_run_agent_mente_emits_compact_progress_without_raw_command_detail(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    command = "/bin/bash -lc 'sed -n \"1,40p\" README.zh.md'"
    tool_name = "mcp__mente__mente_memory_query"
    agent_message = "先核对技能指引，再读取 README 里的相关部署说明。"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.agent_message.completed",
            {
                "item_id": "msg-1",
                "status": "completed",
                "phase": "commentary",
                "text": agent_message,
            },
        )
        event_callback("kernel.codex.mcp_tool.started", {"tool": tool_name})
        event_callback("kernel.codex.mcp_tool.completed", {"tool": tool_name})
        event_callback("kernel.codex.command.started", {"command": command})
        event_callback(
            "kernel.codex.command.completed",
            {"command": command, "exit_code": 0},
        )
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="帮我看看浏览器在哪",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=10,
    )

    await asyncio.sleep(0.1)

    assert result["final_response"] == "done"
    all_progress_text = "\n".join(
        [entry["content"] for entry in adapter.sent]
        + [entry["content"] for entry in adapter.edits]
    )
    assert "⏳ Mente 正在执行" not in all_progress_text
    assert "🚀 正在调用 Mente runtime" not in all_progress_text
    assert "🤖 Mente 已开始执行" not in all_progress_text
    assert "🧮 Mente 回合完成" not in all_progress_text
    assert "📨 Mente runtime 已返回" not in all_progress_text
    assert agent_message in all_progress_text
    assert "🛠️ 工具：mente_memory_query" in all_progress_text
    assert "✅ 工具完成：mente_memory_query" in all_progress_text
    assert "💻 Bash · sed README.zh.md" in all_progress_text
    assert "✅ Bash · sed README.zh.md 完成" in all_progress_text
    assert command not in all_progress_text
    assert tool_name not in all_progress_text


@pytest.mark.asyncio
async def test_run_agent_mente_interrupted_failure_includes_recent_progress_summary(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    command = "/bin/bash -lc 'rg -n \"十三碳二酸|菜籽油\" ~/.mente/logs/agent.log ~/.mente/logs/gateway.log'"
    tool_name = "mcp__mente__mente_memory_query"
    python_command = "/bin/bash -lc \"python3 - <<'PY'\nprint('paper fetch')\nPY\""
    agent_message = "先查日志和记忆线索，再决定要不要继续抓论文。"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.agent_message.completed",
            {
                "item_id": "msg-1",
                "status": "completed",
                "phase": "commentary",
                "text": agent_message,
            },
        )
        event_callback("kernel.codex.mcp_tool.started", {"tool": tool_name})
        event_callback("kernel.codex.command.started", {"command": command})
        event_callback("kernel.codex.command.started", {"command": python_command})
        return {
            "final_response": "⚠️ 任务已取消。",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": True,
            "failure_reason": "interrupted_by_user",
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=11,
    )

    assert result["failed"] is True
    assert "⚠️ 任务已取消。" in result["final_response"]
    assert "已执行到：" in result["final_response"]
    assert agent_message in result["final_response"]
    assert "工具：mente_memory_query" in result["final_response"]
    assert "Bash · rg 十三碳二酸|菜籽油 agent.log" in result["final_response"]
    assert "Bash · Python 脚本（内联）" in result["final_response"]


@pytest.mark.asyncio
async def test_run_agent_mente_long_running_emits_phase_update(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "0.01")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _delayed_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0.03)
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _delayed_to_thread)

    command = "/bin/bash -lc 'rg -n \"十三碳二酸|菜籽油\" ~/.mente/logs/agent.log ~/.mente/logs/gateway.log'"
    tool_name = "mcp__mente__mente_memory_query"
    agent_message = "先整理已有线索，再看日志里是否出现同类工艺关键词。"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.agent_message.completed",
            {
                "item_id": "msg-1",
                "status": "completed",
                "phase": "commentary",
                "text": agent_message,
            },
        )
        event_callback("kernel.codex.mcp_tool.started", {"tool": tool_name})
        event_callback("kernel.codex.command.started", {"command": command})
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": False,
            "failure_reason": None,
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=12,
    )

    assert result["failed"] is False
    phase_updates = [entry["content"] for entry in adapter.sent if "阶段进展" in entry["content"]]
    phase_updates.extend(
        entry["content"] for entry in adapter.edits if "阶段进展" in entry["content"]
    )
    assert phase_updates
    assert any(agent_message in entry for entry in phase_updates)
    assert any("工具：mente_memory_query" in entry for entry in phase_updates)
    assert any("Bash · rg 十三碳二酸|菜籽油 agent.log" in entry for entry in phase_updates)


@pytest.mark.asyncio
async def test_run_agent_mente_long_running_reuses_editable_phase_update_message(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "0.01")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _delayed_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0.045)
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _delayed_to_thread)

    command = "/bin/bash -lc 'rg -n \"邻苯二酚|环氧异丁烷\" ~/.mente/logs/agent.log'"
    agent_message = "先确认公开路线，再判断一锅法是否值得继续投入。"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.agent_message.completed",
            {
                "item_id": "msg-1",
                "status": "completed",
                "phase": "commentary",
                "text": agent_message,
            },
        )
        event_callback("kernel.codex.command.started", {"command": command})
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": False,
            "failure_reason": None,
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="我们公司有环氧异丁烷这个产品，成本接近0,我想开发邻苯二酚和环氧异丁烷开环/脱水/重排/关环制备呋喃酚的工艺，你帮我深度研究下可行性，工艺流程越简单越好。",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=13,
    )

    assert result["failed"] is False
    phase_sends = [entry for entry in adapter.sent if "阶段进展" in entry["content"]]
    phase_edits = [entry for entry in adapter.edits if "阶段进展" in entry["content"]]
    assert len(phase_sends) == 1
    assert phase_edits


@pytest.mark.asyncio
async def test_run_agent_mente_progress_details_include_command_explanation(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _delayed_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0.03)
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _delayed_to_thread)

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.command.started",
            {"command": "/bin/bash -lc 'sed -n \"1,200p\" SKILL.md'"},
        )
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": False,
            "failure_reason": None,
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="检查一个技能工作流",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=14,
    )

    assert result["failed"] is False
    progress_text = "\n".join(
        [entry["content"] for entry in adapter.sent] + [entry["content"] for entry in adapter.edits]
    )
    assert "先读取 SKILL.md，确认当前技能指引和执行入口。" in progress_text
    assert "💻 Bash · sed SKILL.md" in progress_text


@pytest.mark.asyncio
async def test_run_agent_mente_surfaces_lane_progress_in_director_voice(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.mcp_tool.started",
            {"tool": "mcp__mente__mente_memory_query"},
        )
        event_callback(
            "kernel.codex.command.started",
            {"command": "/bin/bash -lc 'rg -n \"十三碳二酸\" agent.log'"},
        )
        return {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": False,
            "failure_reason": None,
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=15,
    )

    assert result["failed"] is False
    progress_text = "\n".join(
        [entry["content"] for entry in adapter.sent] + [entry["content"] for entry in adapter.edits]
    )
    assert "市场部正在调用工具：mente_memory_query" in progress_text
    assert "市场部正在执行：Bash · rg 十三碳二酸 agent.log" in progress_text
    assert "kernel.codex.command.started" not in progress_text


def test_resolve_mente_gateway_progress_detail_surfaces_commentary_agent_message_text():
    detail = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.agent_message.completed",
        {
            "item_id": "msg-1",
            "status": "completed",
            "phase": "commentary",
            "text": "先确认 SSH 别名，再上远端看实际部署目录。",
        },
    )

    assert detail == "先确认 SSH 别名，再上远端看实际部署目录。"


def test_resolve_mente_gateway_progress_detail_surfaces_updated_agent_message_text():
    detail = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.agent_message.updated",
        {
            "item_id": "msg-1",
            "status": "in_progress",
            "text": "我先读取技能说明，确认这个工作流的标准入口。",
            "phase": "commentary",
        },
    )

    assert detail == "我先读取技能说明，确认这个工作流的标准入口。"


def test_resolve_mente_gateway_progress_detail_ignores_non_commentary_agent_message():
    detail = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.agent_message.completed",
        {
            "item_id": "msg-1",
            "status": "completed",
            "text": "我是 Claude，由 Anthropic 开发的大语言模型。",
        },
    )

    assert detail is None


@pytest.mark.asyncio
async def test_run_agent_mente_does_not_emit_non_commentary_agent_message_as_progress(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    final_agent_message = "我是 Claude，由 Anthropic 开发的大语言模型。"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.agent_message.completed",
            {
                "item_id": "msg-1",
                "status": "completed",
                "text": final_agent_message,
            },
        )
        return {
            "final_response": "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
            "failed": False,
            "failure_reason": None,
        }

    monkeypatch.setattr(gateway_run, "_run_mente_gateway_turn", _fake_mente_turn, raising=False)

    adapter = _ProgressAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="你是什么大模型",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=15,
    )

    await asyncio.sleep(0.1)

    assert result["final_response"].startswith("我是 Mente")
    progress_text = "\n".join(
        [entry["content"] for entry in adapter.sent] + [entry["content"] for entry in adapter.edits]
    )
    assert final_agent_message not in progress_text


def test_resolve_mente_gateway_progress_explanation_explains_skill_reads():
    detail = gateway_run._resolve_mente_gateway_progress_explanation(
        "kernel.codex.command.started",
        {"command": "/bin/bash -lc 'sed -n \"1,200p\" SKILL.md'"},
    )

    assert detail == "先读取 SKILL.md，确认当前技能指引和执行入口。"


def test_resolve_mente_gateway_progress_detail_summarizes_python_commands():
    started = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.command.started",
        {"command": "/bin/bash -lc \"python3 - <<'PY'\nprint('hi')\nPY\""},
    )
    completed = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.command.completed",
        {
            "command": "/bin/bash -lc \"python3 - <<'PY'\nprint('hi')\nPY\"",
            "exit_code": 0,
        },
    )

    assert started == "🐍 Bash · Python 脚本（内联）"
    assert completed == "✅ Bash · Python 脚本（内联） 完成"


def test_resolve_mente_gateway_progress_detail_summarizes_rg_queries():
    started = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.command.started",
        {
            "command": (
                "/bin/bash -lc "
                "\"rg -n '十三碳二酸|菜籽油' ~/.mente/logs/agent.log ~/.mente/logs/gateway.log\""
            )
        },
    )
    completed = gateway_run._resolve_mente_gateway_progress_detail(
        "kernel.codex.command.completed",
        {
            "command": (
                "/bin/bash -lc "
                "\"rg -n '十三碳二酸|菜籽油' ~/.mente/logs/agent.log ~/.mente/logs/gateway.log\""
            ),
            "exit_code": 0,
        },
    )

    assert started == "💻 Bash · rg 十三碳二酸|菜籽油 agent.log"
    assert completed == "✅ Bash · rg 十三碳二酸|菜籽油 agent.log 完成"


@pytest.mark.asyncio
async def test_run_agent_flag_off_post_delivery_reviews_stay_silent_and_do_not_break_main_reply(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / "mente-home"))
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    skills_dir = tmp_path / "mente-home" / "skills" / "coding" / "python-debug"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# test\n", encoding="utf-8")

    task_repository = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repository.save(
        build_gateway_task(
            message="Remember that I prefer terse replies.",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.FEISHU,
                chat_id="oc_test",
                chat_name="Feishu",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:feishu:dm:oc_test",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "task-1",
                "skill_refs": ["coding/python-debug"],
                "metadata": {
                    "source": "gateway",
                    "memory_review_artifact": {
                        "assistant_summary": "Acknowledged.",
                        "status": "success",
                    },
                    "skill_review_artifact": {
                        "assistant_summary": "This workflow should be reusable.",
                        "status": "success",
                        "skill_refs": ["coding/python-debug"],
                    },
                },
            }
        )
    )
    task_repository.close()

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)
    monkeypatch.setattr(
        gateway_run,
        "_run_mente_gateway_turn",
        lambda **kwargs: {
            "final_response": "done",
            "last_reasoning": None,
            "messages": [],
            "api_calls": 0,
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "session_id": "session-1",
            "response_previewed": False,
            "mente_task_id": "task-1",
        },
        raising=False,
    )

    adapter = _FollowupAdapter()
    runner = _make_runner()
    runner.adapters = {Platform.FEISHU: adapter}
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = await runner._run_agent(
        message="ping",
        context_prompt="session context",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        run_generation=8,
    )

    assert result["final_response"] == "done"

    assert getattr(adapter, "_post_delivery_callbacks", {}) == {}
    assert adapter.sent == []
