import asyncio
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
async def test_run_agent_registers_post_delivery_reviews_and_sends_compact_followups(monkeypatch):
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

    callback = adapter.pop_post_delivery_callback(
        "agent:main:feishu:dm:oc_test",
        generation=7,
    )
    assert callable(callback)

    callback()
    await asyncio.sleep(0)

    assert review_calls == ["task-1"]
    assert skill_review_calls == ["task-1"]
    assert [entry["content"] for entry in adapter.sent] == [
        "💾 记忆复盘已保存（1 条）",
        "🛠️ 技能复盘已生成建议：coding/python-debug",
    ]


@pytest.mark.asyncio
async def test_run_agent_mente_emits_progress_protocol_messages(monkeypatch):
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
    all_progress_text = "\n".join(
        [entry["content"] for entry in adapter.sent]
        + [entry["content"] for entry in adapter.edits]
    )
    assert "🏠 已锁定私有 runtime" in all_progress_text
    assert "🔐 已准备运行时鉴权" in all_progress_text
    assert "📦 已准备隔离工作区" in all_progress_text
    assert "🚀 正在调用 Mente runtime" in all_progress_text
    assert "🤖 Mente 已开始执行" in all_progress_text
    assert "🧮 Mente 回合完成" in all_progress_text
    assert "📨 Mente runtime 已返回" in all_progress_text


@pytest.mark.asyncio
async def test_run_agent_mente_emits_codex_command_detail_progress(monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_EXECUTOR", "mente")
    monkeypatch.setattr(gateway_run.GatewayRunner, "_get_proxy_url", lambda self: None)

    async def _direct_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(gateway_run.asyncio, "to_thread", _direct_to_thread)

    command = "/bin/bash -lc 'which google-chrome'"

    def _fake_mente_turn(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
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
    assert f"💻 执行命令：{command}" in all_progress_text
    assert f"✅ 命令完成：{command}" in all_progress_text


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

    callback = adapter.pop_post_delivery_callback(
        "agent:main:feishu:dm:oc_test",
        generation=8,
    )
    assert callable(callback)

    callback()
    await asyncio.sleep(0)

    assert adapter.sent == []
