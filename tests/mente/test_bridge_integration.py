from pathlib import Path
import threading

from gateway.config import Platform
from gateway.session import SessionSource

from mente.integrations import bridge as mente_bridge
from mente.executors import CodexKernelAdapter, ToolExposurePolicy, resolve_tool_exposure_policy
from mente.executors.runtime_config import ModelRuntime, RuntimeConfig
from mente.integrations.bridge import (
    build_api_server_task,
    build_cron_task,
    build_gateway_task,
    build_tui_task,
    extract_execution_session_handoff,
    normalize_api_execution_continuity,
    recover_gateway_content_publishing_artifacts,
    resolve_conversation_route,
    resolve_gateway_task_host_timeout_seconds,
    resolve_gateway_task_notify_interval_seconds,
    run_post_turn_memory_review,
    run_post_turn_skill_review,
    run_api_server_task,
    run_cron_task,
    run_gateway_task,
    run_tui_task,
)
from mente.memory.repository import SQLiteMemoryRepository
from mente.task_core.models import (
    DispatchMode,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    SessionMode,
    TaskRole,
)
from mente.task_core.repository import SQLiteTaskRepository


class _FakeKernelAdapter(CodexKernelAdapter):
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or ExecutionResult(status="success", summary="done")

    def build_request_payload(self, request) -> dict[str, object]:
        return {
            "prompt": request.user_request,
            "workspace": request.workspace,
        }

    def execute(self, request) -> ExecutionResult:
        return self.result


def test_build_cron_task_normalizes_job_into_task(tmp_path):
    task = build_cron_task(
        job={
            "id": "job-1",
            "name": "Nightly Sync",
            "schedule": "0 2 * * *",
            "schedule_display": "daily at 02:00",
            "deliver": "telegram",
        },
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    assert task.task_type == "cron"
    assert task.session_id == "cron_job-1_20260428"
    assert task.user_request == "sync the repo"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "cron"
    assert task.metadata["tool_policy"] == resolve_tool_exposure_policy(
        source="cron", task_type="cron"
    ).as_metadata()
    assert "Cron job ID: job-1" in task.constraints


def test_build_gateway_task_normalizes_context_and_history(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[
            {
                "role": "user",
                "content": "previous question",
                "timestamp": "2026-04-28T12:00:00Z",
            }
        ],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert task.task_type == "conversation"
    assert task.session_id == "session-1"
    assert task.user_request == "latest question"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "gateway"
    assert task.metadata["platform"] == "local"
    assert task.metadata["tool_policy"] == resolve_tool_exposure_policy(
        source="gateway", task_type="conversation"
    ).as_metadata()
    assert task.metadata["lane"] == "director"
    assert task.metadata["workflow_contract"]["lane"] == {
        "name": "director",
        "router": "deterministic_v1",
        "resumable": True,
    }
    assert task.metadata["workflow_contract"]["continuity"]["scope"] == "lane"
    assert task.metadata["workflow_contract"]["continuity"]["lane"] == "director"
    assert any("Session context:" in fact for fact in task.memory_facts)
    assert any("Channel prompt:" in fact for fact in task.memory_facts)
    history_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Conversation history (JSON):")
    )
    assert '"role":"user"' in history_fact
    assert "timestamp" not in history_fact


def test_build_gateway_task_deep_research_uses_configured_output_root(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "mente:",
                "  deep_research:",
                "    output_root: /home/jason/clawd/deep-research",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="调用 research/deep-research-pro 技能，深度研究藜芦醛市场，输出详细报告",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    assert any(
        fact.startswith("Deep research output plan:")
        and "/home/jason/clawd/deep-research" in fact
        for fact in task.memory_facts
    )


def test_build_gateway_task_defaults_director_lane_workspace_under_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    fallback_cwd = tmp_path / "fallback-cwd"
    mente_home.mkdir()
    fallback_cwd.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fallback_cwd))

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="你好，你是谁？",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
    )

    assert task.metadata["lane"] == "director"
    assert task.workspace == str(mente_home / "workspace-director")
    assert Path(task.workspace).is_dir()


def test_build_gateway_task_defaults_engineering_lane_workspace_under_mente_home(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "engineering", "confidence": "high", "reason": "engineering_request"},
    )
    mente_home = tmp_path / ".mente"
    fallback_cwd = tmp_path / "fallback-cwd"
    mente_home.mkdir()
    fallback_cwd.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fallback_cwd))

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="帮我修复 tests/mente/test_bridge_integration.py 失败，跑一下 pytest 看报错",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
    )

    assert task.metadata["lane"] == "engineering"
    assert task.workspace == str(mente_home / "workspace-engineering")
    assert Path(task.workspace).is_dir()


def test_build_gateway_task_preserves_explicit_workspace_over_lane_default(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "engineering", "confidence": "high", "reason": "engineering_request"},
    )
    mente_home = tmp_path / ".mente"
    explicit_workspace = tmp_path / "repo"
    mente_home.mkdir()
    explicit_workspace.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="帮我修复 tests/mente/test_bridge_integration.py 失败，跑一下 pytest 看报错",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        workspace=str(explicit_workspace),
    )

    assert task.metadata["lane"] == "engineering"
    assert task.workspace == str(explicit_workspace)


def test_build_gateway_task_routes_skill_audit_to_installed_skill_workspace(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    fallback_cwd = tmp_path / "fallback-cwd"
    repo_root = tmp_path / "repo"
    installed_skill = mente_home / "skills" / "social-media" / "xhs-daily-news"
    mente_home.mkdir()
    fallback_cwd.mkdir()
    repo_root.mkdir()
    installed_skill.mkdir(parents=True)
    (repo_root / ".git").mkdir()
    (installed_skill / "SKILL.md").write_text("# XHS Daily News\n", encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fallback_cwd))
    monkeypatch.chdir(repo_root)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="查找一下Daily News技能，看看有什么优化项",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
    )

    assert task.metadata["lane"] == "engineering"
    assert task.metadata["task_profile"] == "skill_audit"
    assert task.metadata["skill_refs"] == ["social-media/xhs-daily-news"]
    assert task.workspace == str(installed_skill)
    assert any(
        fact.startswith("Skill audit workflow brief:")
        for fact in task.memory_facts
    )


def test_build_gateway_task_routes_skill_audit_to_repo_workspace_when_skill_missing(
    monkeypatch,
    tmp_path,
):
    mente_home = tmp_path / ".mente"
    fallback_cwd = tmp_path / "fallback-cwd"
    repo_root = tmp_path / "repo"
    mente_home.mkdir()
    fallback_cwd.mkdir()
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fallback_cwd))
    monkeypatch.chdir(repo_root)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="查找一下Daily News技能，看看有什么优化项",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
    )

    assert task.metadata["task_profile"] == "skill_audit"
    assert task.metadata["skill_refs"] == ["social-media/xhs-daily-news"]
    assert task.workspace == str(repo_root)


def test_build_gateway_task_bundle_keeps_skill_audit_worker_sessionful(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    installed_skill = mente_home / "skills" / "social-media" / "xhs-daily-news"
    repo_root = tmp_path / "repo"
    mente_home.mkdir()
    installed_skill.mkdir(parents=True)
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    (installed_skill / "SKILL.md").write_text("# XHS Daily News\n", encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.chdir(repo_root)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    bundle = mente_bridge.build_gateway_task_bundle(
        message="你帮我看看 daily news 技能，看看有哪些方面需要改进",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        workspace=str(repo_root),
    )

    assert bundle.worker_task is not None
    assert bundle.worker_task.metadata["task_profile"] == "skill_audit"
    assert bundle.worker_task.execution_mode is ExecutionMode.SESSIONFUL
    assert bundle.worker_task.execution_session == ExecutionSession(mode=SessionMode.START)


def test_build_gateway_task_injects_recent_task_snapshot_for_continue_request(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="继续刚才的任务",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "帮我定位已部署的 tavily 聚合服务配置，整理出 url、apikey 和最小可用说明。",
            "status": "running",
            "assistant_summary": "已定位到 ~/services/tavily-proxy，下一步读取环境变量和启动参数。",
            "follow_up_tasks": ["读取 .env", "确认对外 URL 和 API key"],
            "metadata": {"task_profile": "investigation"},
        },
    )

    snapshot_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Recent active task snapshot:")
    )
    assert "帮我定位已部署的 tavily 聚合服务配置" in snapshot_fact
    assert "已定位到 ~/services/tavily-proxy" in snapshot_fact
    assert "读取 .env" in snapshot_fact
    assert "running" in snapshot_fact


def test_resolve_conversation_route_prefers_active_lane_for_continue_turn():
    route = resolve_conversation_route(
        message="继续刚才的任务",
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert route.lane == "director"
    assert route.reason == "continue_active_job:engineering"


def test_resolve_conversation_route_routes_status_follow_up_to_director():
    route = resolve_conversation_route(
        message="做到哪了？",
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "follow_up_tasks": ["继续修复并跑测试"],
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert route.lane == "director"
    assert route.reason == "status_follow_up:engineering"


def test_resolve_conversation_route_uses_classifier_for_ambiguous_turn(monkeypatch):
    def _classify(**kwargs):
        assert kwargs["message"] == "帮我整理一份竞品对比结论"
        return {
            "lane": "research",
            "confidence": "medium",
            "reason": "competitor_analysis_language",
        }

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    route = resolve_conversation_route(
        message="帮我整理一份竞品对比结论",
        recent_task_snapshot=None,
        active_lane=None,
    )

    assert route.lane == "research"
    assert route.reason == "llm_classifier:research"


def test_resolve_conversation_route_uses_deterministic_engineering_route(
    monkeypatch,
):
    def _classify(**kwargs):
        assert kwargs["message"] == "帮我修复 tests/gateway/test_session.py 的失败并跑 pytest"
        return {
            "lane": "engineering",
            "confidence": "high",
            "reason": "engineering_request",
        }

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    route = resolve_conversation_route(
        message="帮我修复 tests/gateway/test_session.py 的失败并跑 pytest",
        recent_task_snapshot=None,
        active_lane=None,
    )

    assert route.lane == "engineering"
    assert route.reason == "deterministic:engineering"


def test_resolve_conversation_route_classifier_failure_falls_back_to_director(monkeypatch):
    def _raise(**kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _raise)

    route = resolve_conversation_route(
        message="帮我总结一下这个需求要怎么推进",
        recent_task_snapshot=None,
        active_lane=None,
    )

    assert route.lane == "director"
    assert route.reason == "llm_classifier_fallback:director"


def test_resolve_conversation_route_uses_classifier_for_fast_identity_turn(monkeypatch):
    def _classify(**kwargs):
        assert kwargs["message"] == "你好，你是谁？"
        return {
            "lane": "director",
            "confidence": "high",
            "reason": "identity_request",
        }

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    route = resolve_conversation_route(
        message="你好，你是谁？",
        recent_task_snapshot=None,
        active_lane=None,
    )

    assert route.lane == "director"
    assert route.reason == "llm_classifier:director"


def test_resolve_conversation_route_uses_classifier_for_generic_director_chat(
    monkeypatch,
):
    def _classify(**kwargs):
        assert kwargs["message"] == "first question"
        return {
            "lane": "director",
            "confidence": "medium",
            "reason": "generic_chat",
        }

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    route = resolve_conversation_route(
        message="first question",
        recent_task_snapshot=None,
        active_lane=None,
    )

    assert route.lane == "director"
    assert route.reason == "llm_classifier:director"


def test_build_gateway_task_routes_generic_continue_turn_to_coordinator_with_worker_target(
    tmp_path,
):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="继续刚才的任务",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.worker_lane == "engineering"
    assert task.worker_skill_refs == []
    assert task.metadata["lane"] == "director"
    assert task.metadata["dispatch_decision"] == {
        "lane": "director",
        "dispatch_mode": "inline",
        "target_job_lane": "engineering",
        "worker_lane": "engineering",
        "skill_refs": [],
        "worker_skill_refs": [],
        "needs_clarification": False,
        "reason": "continue_active_job:engineering",
    }
    assert task.metadata["workflow_contract"]["lane"] == {
        "name": "director",
        "router": "deterministic_v1",
        "resumable": True,
    }
    assert task.metadata["workflow_contract"]["continuity"]["lane"] == "director"
    assert task.metadata["workflow_contract"]["dispatch"] == {
        "role": "coordinator",
        "mode": "inline",
        "target_job_lane": "engineering",
        "worker_lane": "engineering",
        "needs_clarification": False,
    }


def test_build_gateway_task_preserves_status_follow_up_dispatch_metadata(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="当前进度？",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.worker_lane == "engineering"
    assert task.metadata["lane"] == "director"
    assert task.metadata["dispatch_decision"]["target_job_lane"] == "engineering"
    assert task.metadata["dispatch_decision"]["reason"] == "status_follow_up:engineering"
    assert task.metadata["workflow_contract"]["dispatch"] == {
        "role": "coordinator",
        "mode": "inline",
        "target_job_lane": "engineering",
        "worker_lane": "engineering",
        "needs_clarification": False,
    }


def test_build_gateway_task_injects_lane_handoff_capsule_for_status_follow_up(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="当前进度？",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "follow_up_tasks": ["继续修复并跑测试"],
            "metadata": {
                "lane": "engineering",
                "artifacts_out": ["/tmp/pytest.log"],
            },
        },
        active_lane="engineering",
    )

    capsule_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Active lane handoff capsule:")
    )
    assert task.metadata["lane"] == "director"
    assert "engineering" in capsule_fact
    assert "已定位到失败断言。" in capsule_fact
    assert "继续修复并跑测试" in capsule_fact
    assert "pytest.log" in capsule_fact
    assert not any(
        fact.startswith("Recent active task snapshot:")
        for fact in task.memory_facts
    )


def test_build_gateway_task_routes_ambiguous_skill_request_via_classifier(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "medium", "reason": "generic_skill_request"},
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="调用技能帮我处理一下这个任务",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.worker_lane is None
    assert task.worker_skill_refs == []
    assert task.metadata["lane"] == "director"
    assert task.metadata["dispatch_decision"] == {
        "lane": "director",
        "dispatch_mode": "inline",
        "target_job_lane": None,
        "worker_lane": None,
        "skill_refs": [],
        "worker_skill_refs": [],
        "needs_clarification": False,
        "reason": "llm_classifier:director",
    }
    assert task.metadata["workflow_contract"]["dispatch"] == {
        "role": "coordinator",
        "mode": "inline",
        "target_job_lane": None,
        "worker_lane": None,
        "needs_clarification": False,
    }
    assert "answer the latest user message" in task.objective.lower()


def test_build_tui_task_preserves_continue_dispatch_metadata(tmp_path):
    task = build_tui_task(
        user_message="继续刚才的任务",
        conversation_history=[],
        session_id="tui-session-1",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.worker_lane == "engineering"
    assert task.metadata["lane"] == "director"
    assert task.metadata["dispatch_decision"]["target_job_lane"] == "engineering"
    assert task.metadata["workflow_contract"]["continuity"]["lane"] == "director"
    assert task.metadata["workflow_contract"]["dispatch"] == {
        "role": "coordinator",
        "mode": "inline",
        "target_job_lane": "engineering",
        "worker_lane": "engineering",
        "needs_clarification": False,
    }


def test_build_tui_task_routes_ambiguous_skill_request_via_classifier(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "medium", "reason": "generic_skill_request"},
    )

    task = build_tui_task(
        user_message="调用技能帮我处理一下这个任务",
        conversation_history=[],
        session_id="tui-session-1",
        workspace=str(tmp_path),
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.worker_lane is None
    assert task.worker_skill_refs == []
    assert task.metadata["lane"] == "director"
    assert task.metadata["dispatch_decision"] == {
        "lane": "director",
        "dispatch_mode": "inline",
        "target_job_lane": None,
        "worker_lane": None,
        "skill_refs": [],
        "worker_skill_refs": [],
        "needs_clarification": False,
        "reason": "llm_classifier:director",
    }
    assert task.metadata["workflow_contract"]["dispatch"] == {
        "role": "coordinator",
        "mode": "inline",
        "target_job_lane": None,
        "worker_lane": None,
        "needs_clarification": False,
    }
    assert "answer the latest user message" in task.objective.lower()


def test_build_gateway_task_recent_snapshot_includes_artifact_paths_for_follow_up_delivery(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "artifact_delivery_follow_up"},
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    report_paths = [
        "/home/jason/.mente/deep-research/report.md",
        "/home/jason/.mente/deep-research/report.html",
        "/home/jason/.mente/deep-research/report.docx",
    ]

    task = build_gateway_task(
        message="你刚才完成了丁香酚的深度调研，生成了三个报告。你把这三个报告上传到我的飞书云文档里",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "深度研究下丁香酚，评估愈创木酚合成法成本 技术 供应商 客户，对比天然提取工艺，形成项目深度调研报告",
            "status": "needs_follow_up",
            "assistant_summary": "已生成 Markdown、HTML、DOCX 三份报告。",
            "follow_up_tasks": ["上传这三个报告到飞书云文档"],
            "metadata": {
                "task_profile": "deep_research",
                "artifacts_out": report_paths,
            },
        },
    )

    snapshot_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Recent active task snapshot:")
    )
    assert "report.md" in snapshot_fact
    assert "report.html" in snapshot_fact
    assert "report.docx" in snapshot_fact
    assert task.metadata["lane"] == "research"
    assert task.metadata["task_profile"] == "artifact_delivery"
    assert task.artifacts_in == report_paths
    assert any(
        fact.startswith("Artifact delivery workflow brief:")
        for fact in task.memory_facts
    )
    assert any(
        fact.startswith("Artifact delivery inputs:")
        for fact in task.memory_facts
    )
    assert any(
        "use the provided artifact paths directly" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "upload or share the provided artifact files" in criterion.lower()
        for criterion in task.acceptance_criteria
    )


def test_build_gateway_task_routes_operator_follow_up_to_recent_lane_and_reuses_capsule(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "low", "reason": "fallback"},
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    report_paths = [
        "/home/jason/clawd/deep-research/维拉帕米_20260515/维拉帕米_20260515.md",
        "/home/jason/clawd/deep-research/维拉帕米_20260515/维拉帕米_20260515.html",
        "/home/jason/clawd/deep-research/维拉帕米_20260515/维拉帕米_20260515.docx",
    ]
    skill_entrypoint = str(
        mente_bridge.get_skills_dir() / "research" / "deep-research-pro" / "deep_research_pro.py"
    )

    task = build_gateway_task(
        message="把本地深度调研报告改成 维拉帕米_20260515.md/html/docx 这种命名，然后重新上传到飞书",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "深度研究维拉帕米并生成完整报告，再上传到飞书云文档",
            "status": "needs_follow_up",
            "assistant_summary": "已生成三份报告，但命名规则需要调整后再上传。",
            "follow_up_tasks": ["按命名模板重新生成报告", "重新上传到飞书云文档"],
            "metadata": {
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["research/deep-research-pro"],
                "artifacts_out": report_paths,
                "operator_capsule": {
                    "skill_entrypoint": skill_entrypoint,
                    "allowed_roots": [
                        str(tmp_path),
                        str(mente_bridge.get_skills_dir() / "research" / "deep-research-pro"),
                    ],
                    "naming_template": "<product>_<YYYYMMDD>.(md|html|docx)",
                    "artifact_paths": report_paths,
                    "next_actions": ["按命名模板重新生成报告", "重新上传到飞书云文档"],
                },
            },
        },
    )

    assert task.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert task.metadata["lane"] == "research"
    assert task.metadata["task_profile"] == "deep_research"
    assert task.metadata["dispatch_decision"]["reason"] == "deterministic:operator_follow_up:research"
    assert task.skill_refs == ["research/deep-research-pro"]
    snapshot_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Recent active task snapshot:")
    )
    assert "<product>_<YYYYMMDD>.(md|html|docx)" in snapshot_fact
    assert skill_entrypoint in snapshot_fact
    assert "重新上传到飞书云文档" in snapshot_fact
    assert any(
        "use the recent task capsule entrypoints and artifact paths directly" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "follow the recent task capsule naming template" in criterion.lower()
        for criterion in task.acceptance_criteria
    )


def test_build_gateway_task_skips_recent_task_snapshot_for_new_unrelated_request(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="帮我总结一下今天的会议纪要",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "帮我定位已部署的 tavily 聚合服务配置，整理出 url、apikey 和最小可用说明。",
            "status": "running",
            "assistant_summary": "已定位到 ~/services/tavily-proxy，下一步读取环境变量和启动参数。",
            "follow_up_tasks": ["读取 .env", "确认对外 URL 和 API key"],
        },
    )

    assert not any(
        fact.startswith("Recent active task snapshot:")
        for fact in task.memory_facts
    )


def test_build_gateway_task_infers_wechat_content_skills_and_prefers_repo_workspace(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "writing", "confidence": "high", "reason": "content_publishing"},
    )
    project_root = tmp_path / "Mente"
    fake_home = tmp_path / "home"
    project_root.mkdir()
    fake_home.mkdir()
    (project_root / ".git").mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
    )

    assert task.workspace == str(project_root)
    assert task.skill_refs == ["media/wechat-publisher", "imagegen"]
    assert task.metadata["lane"] == "writing"
    assert task.metadata["task_profile"] == "content_publishing"
    assert task.metadata["tool_policy"]["bridge_tools"] == ["mente_wechat_publish_draft"]
    assert any(
        fact.startswith("Publishing workflow brief:")
        for fact in task.memory_facts
    )
    assert any(
        fact.startswith("Publishing output plan:")
        for fact in task.memory_facts
    )
    entrypoint_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Publishing entrypoints:")
    )
    assert "mente_wechat_publish_draft" in entrypoint_fact
    assert "mcp__mente__mente_wechat_publish_draft" in entrypoint_fact
    assert "create-article.js" in entrypoint_fact
    assert "publish.js" in entrypoint_fact
    assert "not treat create-article.js or publish.js as the primary publish path" in entrypoint_fact
    assert any(
        "do not scan the full repository" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "authoritative publish entrypoint" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "use mcp__mente__mente_wechat_publish_draft" in criterion.lower()
        for criterion in task.acceptance_criteria
    )
    assert any(
        "prefer producing the requested article and assets immediately" in criterion.lower()
        for criterion in task.acceptance_criteria
    )


def test_build_gateway_task_does_not_misclassify_xhs_publish_requests_as_wechat_content_publishing(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "Mente"
    mente_home = tmp_path / "mente-home"
    fake_home = tmp_path / "home"
    project_root.mkdir()
    mente_home.mkdir()
    fake_home.mkdir()
    (project_root / ".git").mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="帮我生成小红书每日新闻卡片并发布到 rednote/xhs",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
    )

    assert task.workspace == str(mente_home / "workspace-director")
    assert task.metadata["lane"] == "director"
    assert "media/wechat-publisher" not in task.skill_refs
    assert "task_profile" not in task.metadata
    assert not any(
        fact.startswith("Publishing workflow brief:")
        for fact in task.memory_facts
    )
    assert resolve_gateway_task_host_timeout_seconds(message=task.user_request) is None


def test_build_gateway_task_infers_config_admin_skill_for_direct_mente_config_updates(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "config_admin", "confidence": "high", "reason": "config_update"},
    )
    project_root = tmp_path / "Mente"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    monkeypatch.chdir(project_root)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="把 config.yaml 里的 terminal.cwd 改成 /，然后 restart gateway",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
    )

    assert task.workspace == str(project_root)
    assert task.skill_refs == ["software-development/mente-config-admin"]
    assert task.metadata["lane"] == "config_admin"
    assert task.metadata["task_profile"] == "config_admin"
    assert any(
        fact.startswith("Config-admin workflow brief:")
        for fact in task.memory_facts
    )
    assert any(
        "resolve the active config, env, or auth path first" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "use the provided config-admin skill directly" in criterion.lower()
        for criterion in task.acceptance_criteria
    )
    assert any(
        "exact file, key, and restart action" in criterion.lower()
        for criterion in task.acceptance_criteria
    )


def test_build_gateway_task_routes_persistent_deep_research_upload_preference_to_config_admin(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "low", "reason": "fallback"},
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message=(
            "以后深度研究报告完成后，默认上传到我的飞书云文档这个目录，"
            "写到配置里："
            "https://my.feishu.cn/drive/folder/BGamf6YTllHumVdAdCpcHtlpnhh"
        ),
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "调用技能，深度研究抗氧基BHEB，形成完整调研报告。",
            "status": "needs_follow_up",
            "assistant_summary": "已生成 Markdown、HTML、DOCX 三份报告。",
            "follow_up_tasks": ["上传这三个报告到飞书云文档"],
            "metadata": {
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["research/deep-research-pro"],
                "artifacts_out": [
                    "/tmp/report.md",
                    "/tmp/report.html",
                    "/tmp/report.docx",
                ],
            },
        },
    )

    assert task.skill_refs == ["software-development/mente-config-admin"]
    assert task.metadata["lane"] == "config_admin"
    assert task.metadata["task_profile"] == "config_admin"
    assert task.metadata["dispatch_decision"]["reason"] == "deterministic:owner_lane:config_admin"
    assert any(
        fact.startswith("Config-admin workflow brief:")
        for fact in task.memory_facts
    )


def test_build_gateway_task_routes_self_improvement_skill_change_to_engineering(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "low", "reason": "fallback"},
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message=(
            "根据这次运行情况自我完善。以后深度研究报告完成后默认上传到我的飞书云文档目录，"
            "调用 Codex runtime 去编程修改技能、脚本和工作流，不要只记忆："
            "https://my.feishu.cn/drive/folder/BGamf6YTllHumVdAdCpcHtlpnhh"
        ),
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "调用技能，深度研究抗氧基BHEB，形成完整调研报告。",
            "status": "needs_follow_up",
            "assistant_summary": "已生成 Markdown、HTML、DOCX 三份报告。",
            "follow_up_tasks": ["上传这三个报告到飞书云文档"],
            "metadata": {
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["research/deep-research-pro"],
                "artifacts_out": [
                    "/tmp/report.md",
                    "/tmp/report.html",
                    "/tmp/report.docx",
                ],
            },
        },
    )

    assert task.skill_refs == []
    assert task.metadata["lane"] == "engineering"
    assert task.metadata["task_profile"] == "self_improvement"
    assert task.metadata["dispatch_decision"]["reason"] == "deterministic:self_improvement:engineering"
    assert any(
        fact.startswith("Self-improvement workflow brief:")
        for fact in task.memory_facts
    )
    assert any(
        "do not stop at a memory-only acknowledgement" in constraint.lower()
        for constraint in task.constraints
    )
    assert any(
        "exact files changed and verification performed" in criterion.lower()
        for criterion in task.acceptance_criteria
    )


def test_build_gateway_task_routes_skill_audit_capability_follow_up_to_self_improvement(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "low", "reason": "fallback"},
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="这类问题我倾向mente要会自己解决，你要强化的是mente本身的能力。",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "查找一下Daily News技能，看看有什么优化项",
            "status": "needs_follow_up",
            "assistant_summary": "已列出 workflow、解析和发布顺序方面的改进项。",
            "metadata": {
                "lane": "engineering",
                "task_profile": "skill_audit",
                "skill_refs": ["social-media/xhs-daily-news"],
            },
        },
    )

    assert task.skill_refs == []
    assert task.worker_skill_refs == ["social-media/xhs-daily-news"]
    assert task.metadata["lane"] == "engineering"
    assert task.metadata["task_profile"] == "self_improvement"
    assert task.metadata["dispatch_decision"]["reason"] == "deterministic:self_improvement:engineering"
    assert task.metadata["dispatch_decision"]["worker_skill_refs"] == [
        "social-media/xhs-daily-news"
    ]
    assert any(
        fact.startswith("Self-improvement workflow brief:")
        for fact in task.memory_facts
    )
    assert any(
        "xhs-daily-news" in fact for fact in task.memory_facts
    )


def test_build_gateway_task_injects_mente_inventory_for_self_improvement(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "low", "reason": "fallback"},
    )
    mente_home = tmp_path / ".mente"
    skills_root = mente_home / "skills" / "social-media" / "xhs-daily-news"
    cron_dir = mente_home / "cron"
    deep_research_root = tmp_path / "deep-research"
    skills_root.mkdir(parents=True)
    cron_dir.mkdir(parents=True)
    deep_research_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        "---\nname: xhs-daily-news\ndescription: Daily news skill.\n---\n",
        encoding="utf-8",
    )
    (mente_home / "config.yaml").write_text(
        f"mente:\n  deep_research:\n    output_root: {deep_research_root}\n",
        encoding="utf-8",
    )
    (cron_dir / "jobs.json").write_text(
        '{"jobs":[{"id":"job-1","name":"Daily News","enabled":true,"schedule":"0 9 * * *"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="这类问题我倾向mente要会自己解决，你要强化的是mente本身的能力。",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "查找一下Daily News技能，看看有什么优化项",
            "status": "needs_follow_up",
            "assistant_summary": "已列出 workflow、解析和发布顺序方面的改进项。",
            "metadata": {
                "lane": "engineering",
                "task_profile": "skill_audit",
                "skill_refs": ["social-media/xhs-daily-news"],
                "artifacts_out": [str(deep_research_root / "latest.md")],
            },
        },
    )

    inventory_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Mente inventory:")
    )
    assert "social-media/xhs-daily-news" in inventory_fact
    assert "jobs.json" in inventory_fact
    assert str(deep_research_root) in inventory_fact
    assert task.metadata["mente_inventory"]["skills"]["referenced_refs"] == [
        "social-media/xhs-daily-news"
    ]
    assert task.metadata["mente_inventory"]["automation"]["total_jobs"] == 1
    assert task.metadata["mente_inventory"]["routing_hint"]["selected_category"] == "skills"


def test_build_gateway_task_skips_mente_inventory_for_generic_chat(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="你好，今天怎么样？",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    assert not any(fact.startswith("Mente inventory:") for fact in task.memory_facts)
    assert "mente_inventory" not in task.metadata


def test_build_gateway_task_infers_deep_research_skill_and_delivery_contract(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "deep_research"},
    )
    mente_home = tmp_path / "mente-home"
    mente_home.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="调用深度研究技能，深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
    )

    assert task.skill_refs == ["research/deep-research-pro"]
    assert task.metadata["lane"] == "research"
    assert task.metadata["task_profile"] == "deep_research"
    assert any(
        fact.startswith("Deep research workflow brief:")
        for fact in task.memory_facts
    )
    architecture_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Mente worker architecture context:")
    )
    assert "coordinator owns user turns" in architecture_fact
    skill_context_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Relevant skill context:")
    )
    assert "research/deep-research-pro" in skill_context_fact
    entrypoint_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Deep research execution plan:")
    )
    assert "delegate_task" in entrypoint_fact


def test_build_gateway_task_routes_obvious_coding_request_to_engineering_lane(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "engineering", "confidence": "high", "reason": "engineering_request"},
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="帮我修复 tests/mente/test_bridge_integration.py 失败，跑一下 pytest 看报错",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        workspace=str(tmp_path),
    )

    assert task.metadata["lane"] == "engineering"
    assert "task_profile" not in task.metadata
    assert task.metadata["workflow_contract"]["lane"] == {
        "name": "engineering",
        "router": "deterministic_v1",
        "resumable": True,
    }
    assert task.metadata["workflow_contract"]["continuity"]["lane"] == "engineering"


def test_build_gateway_task_deep_research_parallel_plan_is_workspace_scoped(tmp_path):
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
    )

    entrypoint_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Deep research execution plan:")
    )

    assert str(tmp_path) in entrypoint_fact
    assert "Avoid broad repository or home-directory scans before delegating work." in entrypoint_fact


def test_build_gateway_task_deep_research_plan_points_to_skill_md_and_direct_cli(tmp_path):
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="调用技能，深度研究抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚这一个标准化学品，形成万字调研报告。",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
    )

    entrypoint_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Deep research execution plan:")
    )

    assert "Canonical instructions file:" in entrypoint_fact
    assert "/research/deep-research-pro/SKILL.md" in entrypoint_fact
    assert "Do not probe README.md" in entrypoint_fact
    assert "Managed CLI launch command:" in entrypoint_fact
    assert 'deep_research_pro.py "抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚"' in entrypoint_fact
    assert "--output-dir" in entrypoint_fact
    assert "deep-research" in entrypoint_fact


def test_resolve_gateway_task_host_timeout_seconds_defaults_content_publishing_timeout_off():
    assert (
        resolve_gateway_task_host_timeout_seconds(
            message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        )
        is None
    )
    assert resolve_gateway_task_host_timeout_seconds(message="你好") is None


def test_resolve_gateway_task_host_timeout_seconds_honors_content_publishing_timeout_override():
    assert (
        resolve_gateway_task_host_timeout_seconds(
            message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
            content_publishing_timeout_seconds=420,
        )
        == 420.0
    )


def test_resolve_gateway_task_notify_interval_seconds_caps_deep_research_defaults():
    assert (
        resolve_gateway_task_notify_interval_seconds(
            message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
            configured_seconds=180,
        )
        == 60.0
    )


def test_resolve_gateway_task_notify_interval_seconds_keeps_shorter_custom_interval():
    assert (
        resolve_gateway_task_notify_interval_seconds(
            message="调用深度研究技能，帮我完整调研一个化工路线",
            configured_seconds=45,
        )
        == 45.0
    )


def test_resolve_gateway_task_notify_interval_seconds_leaves_normal_tasks_unchanged():
    assert (
        resolve_gateway_task_notify_interval_seconds(
            message="你好，帮我总结今天的安排",
            configured_seconds=180,
        )
        == 180.0
    )
    assert (
        resolve_gateway_task_notify_interval_seconds(
            message="深度研究一下采用菜籽油制备十三碳二酸的可行性",
            configured_seconds=0,
        )
        is None
    )


def test_recover_gateway_content_publishing_artifacts_finalizes_source_markdown(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "Mente"
    fake_home = tmp_path / "home"
    draft_dir = project_root / ".mente" / "publishing" / "session-1"
    project_root.mkdir()
    fake_home.mkdir()
    (project_root / ".git").mkdir()
    draft_dir.mkdir(parents=True)
    source_path = draft_dir / "source.md"
    source_path.write_text(
        "---\n"
        "title: Mente 发布链收口\n"
        "---\n\n"
        "# Draft\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))
    captured: dict[str, object] = {}

    def _fake_publish_wechat_draft(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "article_path": kwargs["article_path"],
            "finalize_mode": "source_markdown",
        }

    monkeypatch.setattr(mente_bridge, "publish_wechat_draft", _fake_publish_wechat_draft)

    result = recover_gateway_content_publishing_artifacts(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        session_id="session-1",
    )

    assert result["ok"] is True
    assert result["draft_dir"] == str(draft_dir)
    assert result["publish_result"]["finalize_mode"] == "source_markdown"
    assert captured["article_path"] == str(source_path)


def test_recover_gateway_content_publishing_artifacts_publishes_article_markdown(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "Mente"
    fake_home = tmp_path / "home"
    draft_dir = project_root / ".mente" / "publishing" / "session-1"
    project_root.mkdir()
    fake_home.mkdir()
    (project_root / ".git").mkdir()
    draft_dir.mkdir(parents=True)
    article_path = draft_dir / "article.md"
    article_path.write_text("# Draft\n", encoding="utf-8")
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))
    captured: dict[str, object] = {}

    def _fake_publish_wechat_draft(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "article_path": kwargs["article_path"],
            "finalize_mode": "article_markdown",
        }

    monkeypatch.setattr(mente_bridge, "publish_wechat_draft", _fake_publish_wechat_draft)

    result = recover_gateway_content_publishing_artifacts(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        session_id="session-1",
    )

    assert result["ok"] is True
    assert result["recovered_from"] == "article.md"
    assert result["publish_result"]["finalize_mode"] == "article_markdown"
    assert captured["article_path"] == str(article_path)


def test_recover_gateway_content_publishing_artifacts_surfaces_publish_failure_summary(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "Mente"
    fake_home = tmp_path / "home"
    draft_dir = project_root / ".mente" / "publishing" / "session-1"
    project_root.mkdir()
    fake_home.mkdir()
    (project_root / ".git").mkdir()
    draft_dir.mkdir(parents=True)
    article_path = draft_dir / "article.md"
    article_path.write_text("# Draft\n", encoding="utf-8")
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))

    def _fake_publish_wechat_draft(**kwargs):
        return {
            "ok": False,
            "article_path": kwargs["article_path"],
            "error": "wechat_ip_not_whitelisted",
            "failure_summary": "微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。",
            "stderr": "invalid ip 1.2.3.4, not in whitelist",
        }

    monkeypatch.setattr(mente_bridge, "publish_wechat_draft", _fake_publish_wechat_draft)

    result = recover_gateway_content_publishing_artifacts(
        message="调用WeChat技能，帮我写一个文案，做好标题正文配图，发布到我的微信公众号草稿",
        session_id="session-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "wechat_ip_not_whitelisted"
    assert result["failure_summary"] == "微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。"


def test_build_api_server_task_sets_api_server_source(tmp_path):
    task = build_api_server_task(
        user_message="Remember this preference",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Prior reply",
                "timestamp": "2026-04-29T12:00:00Z",
            }
        ],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    assert task.session_id == "api-session-1"
    assert task.task_type == "conversation"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "api_server"
    assert task.metadata["api_mode"] == "chat_completions"
    assert task.metadata["tool_policy"] == resolve_tool_exposure_policy(
        source="api_server", task_type="conversation"
    ).as_metadata()
    history_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Conversation history (JSON):")
    )
    assert '"role":"assistant"' in history_fact
    assert "timestamp" not in history_fact


def test_build_gateway_task_defaults_to_stateless_execution_contract(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        workspace=str(tmp_path),
    )

    assert task.execution_mode is ExecutionMode.STATELESS
    assert task.execution_session is None


def test_build_api_server_task_accepts_explicit_sessionful_opt_in(tmp_path):
    task = build_api_server_task(
        user_message="Remember this preference",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
    )

    assert task.execution_mode is ExecutionMode.SESSIONFUL
    assert task.execution_session == ExecutionSession(mode=SessionMode.START)


def test_build_api_server_task_infers_sessionful_mode_from_execution_session_payload(tmp_path):
    task = build_api_server_task(
        user_message="Remember this preference",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
        execution_session={
            "mode": "resume",
            "continuity_id": "thread-123",
        },
    )

    assert task.execution_mode is ExecutionMode.SESSIONFUL
    assert task.execution_session == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )


def test_normalize_api_execution_continuity_rejects_stateless_execution_session():
    try:
        normalize_api_execution_continuity(
            execution_mode=ExecutionMode.STATELESS,
            execution_session={"mode": "start"},
        )
    except ValueError as exc:
        assert str(exc) == "execution_session is not allowed when execution_mode=stateless"
    else:
        raise AssertionError("expected ValueError")


def test_extract_execution_session_handoff_returns_canonical_payload():
    payload = {
        "mode": "stateless",
        "requested_mode": "resume",
        "effective_mode": "stateless",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "fallback_stateless",
        "fallback_reason": "thread_not_found",
    }

    handoff = extract_execution_session_handoff(
        ExecutionResult(
            status="success",
            summary="done",
            metadata={"execution_session": payload},
        )
    )

    assert handoff == payload


def test_build_orchestrator_includes_memory_stack(monkeypatch):
    captured = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(mente_bridge, "Orchestrator", _FakeOrchestrator)

    mente_bridge._build_orchestrator(".", repository=object())

    assert captured["memory_repository"] is not None
    assert captured["memory_promoter"] is not None
    assert captured["context_builder"] is not None


def test_build_orchestrator_uses_kernel_adapter_factory(monkeypatch):
    captured = {}
    fake_adapter = _FakeKernelAdapter()

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(mente_bridge, "Orchestrator", _FakeOrchestrator)
    monkeypatch.setattr(
        mente_bridge,
        "_build_kernel_adapter",
        lambda workspace, runtime_config=None, memory_repository=None, event_callback=None, cancel_event=None: fake_adapter,
    )

    mente_bridge._build_orchestrator(".", repository=object())

    assert captured["executor"] is fake_adapter


def test_build_kernel_adapter_resolves_private_runtime_config(monkeypatch, tmp_path):
    captured = {}
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-runtime-home")

    class _FakeExecutor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        mente_bridge,
        "_resolve_runtime_config_for_workspace",
        lambda workspace: runtime_config,
    )
    monkeypatch.setattr(mente_bridge, "CodexExecutor", _FakeExecutor)

    adapter = mente_bridge._build_kernel_adapter(str(tmp_path))

    assert adapter is not None
    assert captured["runtime_config"] is runtime_config


def test_build_kernel_adapter_preserves_adapter_only_handoff_after_vendoring(monkeypatch, tmp_path):
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-runtime-home")

    monkeypatch.setattr(
        mente_bridge,
        "_resolve_runtime_config_for_workspace",
        lambda workspace: runtime_config,
    )

    adapter = mente_bridge._build_kernel_adapter(str(tmp_path))
    task = build_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )
    request = ExecutionRequest(
        task_id=task.task_id,
        session_id=task.session_id,
        task_type=task.task_type,
        objective=task.objective,
        user_request=task.user_request,
        workspace=task.workspace or str(tmp_path),
        constraints=task.constraints,
        memory_facts=task.memory_facts,
        tool_policy=task.metadata["tool_policy"],
        metadata=task.metadata,
    )

    payload = adapter.build_request_payload(request)

    assert isinstance(adapter, CodexKernelAdapter)
    assert type(adapter).__name__ == "CodexExecutor"
    assert hasattr(adapter, "_runner")
    assert adapter.supports_kernel_sessions() is False
    assert payload["workspace"] == str(tmp_path)
    assert "command" not in payload
    assert "argv" not in payload


def test_run_api_server_task_uses_private_runtime_config_provider(monkeypatch, tmp_path):
    db_path = tmp_path / "state.db"
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-runtime-home")
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))
    captured = {}

    monkeypatch.setattr(
        mente_bridge,
        "_resolve_runtime_config_for_workspace",
        lambda workspace: runtime_config,
    )

    def _fake_execute(self, request):
        captured["runtime_config"] = self._runtime_config
        return ExecutionResult(status="success", summary="done")

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    result = run_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )

    assert result.status == "success"
    assert captured["runtime_config"] is runtime_config
    assert captured["runtime_config"].runtime_home == tmp_path / "private-runtime-home"


def test_run_post_turn_memory_review_reads_persisted_task_and_writes_memory(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "0")
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    task_repository.save(
        build_gateway_task(
            message="Remember that I prefer terse replies.",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.LOCAL,
                chat_id="cli",
                chat_name="CLI",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:local:dm",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "mente_gateway_reviewseed",
                "metadata": {
                    "source": "gateway",
                    "memory_review_artifact": {
                        "assistant_summary": "Acknowledged.",
                        "status": "success",
                    },
                },
            }
        )
    )
    task_repository.close()

    outcome = run_post_turn_memory_review(task_id="mente_gateway_reviewseed")

    stored_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_gateway_reviewseed:review:0"
    )

    assert outcome == {
        "status": "persisted",
        "reason": None,
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["mente_gateway_reviewseed:review:0"],
    }
    assert stored_memory is not None
    assert stored_memory.fact == "I prefer terse replies."
    assert stored_memory.metadata["write_origin"] == "post_turn_memory_review"


def test_run_post_turn_memory_review_persists_explicit_chinese_remember_intent(
    monkeypatch,
    tmp_path,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    task_repository.save(
        build_gateway_task(
            message="记住我喜欢简洁回答",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.LOCAL,
                chat_id="cli",
                chat_name="CLI",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:local:dm",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "mente_gateway_reviewseed_cn",
                "metadata": {
                    "source": "gateway",
                    "memory_review_artifact": {
                        "assistant_summary": "记下了。",
                        "status": "success",
                    },
                },
            }
        )
    )
    task_repository.close()

    outcome = run_post_turn_memory_review(task_id="mente_gateway_reviewseed_cn")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    stored_task = task_repository.get("mente_gateway_reviewseed_cn")
    stored_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_gateway_reviewseed_cn:review:0"
    )

    assert outcome == {
        "status": "persisted",
        "reason": None,
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["mente_gateway_reviewseed_cn:review:0"],
    }
    assert stored_task is not None
    assert stored_task.metadata["memory_review"]["status"] == "persisted"
    assert stored_memory is not None
    assert stored_memory.fact == "我喜欢简洁回答"
    assert stored_memory.metadata["write_origin"] == "post_turn_memory_review"
    assert stored_memory.metadata["tool_name"] == "mente_memory_review_worker"
    assert stored_memory.metadata["promotion_reason"] == "post_turn_memory_review"


def test_run_post_turn_memory_review_keeps_pure_criticism_as_noop(
    monkeypatch,
    tmp_path,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    task_repository.save(
        build_gateway_task(
            message="你错了",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.LOCAL,
                chat_id="cli",
                chat_name="CLI",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:local:dm",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "mente_gateway_reviewseed_cn_noop",
                "metadata": {
                    "source": "gateway",
                    "memory_review_artifact": {
                        "assistant_summary": "我会注意。",
                        "status": "success",
                    },
                },
            }
        )
    )
    task_repository.close()

    outcome = run_post_turn_memory_review(task_id="mente_gateway_reviewseed_cn_noop")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    stored_task = task_repository.get("mente_gateway_reviewseed_cn_noop")
    memory_repository = SQLiteMemoryRepository(db_path=memory_db_path)

    assert outcome == {
        "status": "noop",
        "reason": None,
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert stored_task is not None
    assert stored_task.metadata["memory_review"]["status"] == "noop"
    assert memory_repository.get("mente_gateway_reviewseed_cn_noop:review:0") is None
    assert memory_repository.list_recent() == []


def test_run_post_turn_skill_review_reads_persisted_task_and_writes_review_artifact(
    monkeypatch,
    tmp_path,
):
    task_db_path = tmp_path / "tasks.db"
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    skills_dir = mente_home / "skills" / "coding" / "python-debug"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# test\n", encoding="utf-8")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    task_repository.save(
        build_gateway_task(
            message="Review the reusable workflow.",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.LOCAL,
                chat_id="cli",
                chat_name="CLI",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:local:dm",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "mente_gateway_skill_reviewseed",
                "skill_refs": ["coding/python-debug"],
                "metadata": {
                    "source": "gateway",
                    "skill_review_artifact": {
                        "assistant_summary": "This workflow should be reusable.",
                        "status": "success",
                    },
                },
            }
        )
    )
    task_repository.close()

    outcome = run_post_turn_skill_review(task_id="mente_gateway_skill_reviewseed")

    assert outcome["status"] == "suggested"
    assert outcome["target_skill"] == "coding/python-debug"
    artifact_path = Path(outcome["artifact_path"])
    assert artifact_path.is_file()
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert '"proposed_changes"' in artifact_text
    assert '"diff"' in artifact_text


def test_run_post_turn_skill_review_applies_trusted_patch_when_enabled(
    monkeypatch,
    tmp_path,
):
    task_db_path = tmp_path / "tasks.db"
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_MODE", "patch")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_PATCH_ENABLED", "1")
    skills_dir = mente_home / "skills" / "coding" / "python-debug"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# test\n", encoding="utf-8")

    task_repository = SQLiteTaskRepository(db_path=task_db_path)
    task_repository.save(
        build_gateway_task(
            message="Apply the narrow trusted update.",
            context_prompt="session summary",
            history=[],
            source=SessionSource(
                platform=Platform.LOCAL,
                chat_id="cli",
                chat_name="CLI",
                chat_type="dm",
                user_id="user-1",
            ),
            session_id="session-1",
            session_key="agent:main:local:dm",
            workspace=str(tmp_path),
        ).model_copy(
            update={
                "task_id": "mente_gateway_skill_patchseed",
                "skill_refs": ["coding/python-debug"],
                "metadata": {
                    "source": "gateway",
                    "skill_review_artifact": {
                        "assistant_summary": "This workflow should be reusable.",
                        "status": "success",
                        "commands_run": ["rg skill", "sed -n 1,80p SKILL.md"],
                        "skill_refs": ["coding/python-debug"],
                    },
                },
            }
        )
    )
    task_repository.close()

    outcome = run_post_turn_skill_review(task_id="mente_gateway_skill_patchseed")

    assert outcome["status"] == "patched"
    assert "MENTE POST-TURN REVIEW" in (skills_dir / "SKILL.md").read_text(encoding="utf-8")


def test_api_server_isolation_executor_preserves_kernel_adapter_contract():
    request = build_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=".",
    )
    inner = _FakeKernelAdapter(
        result=ExecutionResult(
            status="success",
            summary="done",
            memory_candidates=["User previously said they prefer terse replies."],
        )
    )

    executor = mente_bridge._APIServerIsolationExecutor(inner=inner)

    payload = executor.build_request_payload(request)
    result = executor.execute(request)

    assert payload == {
        "prompt": request.user_request,
        "workspace": request.workspace,
    }
    assert executor.supports_kernel_sessions() is False
    assert result.summary == "done"
    assert result.memory_candidates == []


def test_second_run_receives_first_run_memory(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    seen_requests = []

    def _fake_execute(self, request):
        seen_requests.append(request)
        if len(seen_requests) == 1:
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers concise replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="first question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )
    run_gateway_task(
        message="second question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert len(seen_requests) == 2
    assert "Memory: User prefers concise replies." not in seen_requests[1].memory_facts
    assert seen_requests[1].tool_policy["bridge_tools"] == [
        "mente_memory_query",
        "mente_memory_save",
    ]


def test_worker_lane_second_run_receives_persisted_worker_summary_cache(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    seen_requests = []

    def _fake_execute(self, request):
        seen_requests.append(request)
        if len(seen_requests) == 1:
            return ExecutionResult(
                status="success",
                summary="Built the current supplier shortlist and captured pricing gaps.",
                actions_taken=["Compared three suppliers", "Captured pricing gaps"],
                follow_up_tasks=["Validate the shortlisted suppliers"],
                changed_files=["reports/suppliers.md"],
                artifacts_out=["reports/suppliers.md"],
            )
        return ExecutionResult(status="success", summary="follow-up worker run")

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )
    worker_prompt = "深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告"

    first_result = run_gateway_task(
        message=worker_prompt,
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        request_id="workercacheseed",
    )
    memory_id = "worker_lane_summary:gateway:session-1:research"
    seeded_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(memory_id)
    run_gateway_task(
        message=worker_prompt,
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        request_id="workercachefollowup",
    )

    assert len(seen_requests) == 2
    assert first_result.metadata["worker_summary_cache"] == {
        "status": "persisted",
        "memory_id": memory_id,
        "kind": "worker_lane_summary:research",
        "lane": "research",
    }
    assert seeded_memory is not None
    assert seeded_memory.kind == "worker_lane_summary:research"
    assert seeded_memory.scope == "session"
    assert "Built the current supplier shortlist and captured pricing gaps." in seeded_memory.fact
    assert "Compared three suppliers" in seeded_memory.fact
    assert "Validate the shortlisted suppliers" in seeded_memory.fact
    assert seen_requests[1].role == TaskRole.WORKER
    assert seen_requests[1].worker_lane == "research"
    assert seen_requests[1].memory_facts[0].startswith("Memory: Worker lane summary (research):")
    assert "Built the current supplier shortlist and captured pricing gaps." in seen_requests[1].memory_facts[0]


def test_gateway_runs_persist_memory_observability_metadata(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "0")

    def _fake_execute(self, request):
        if request.task_id.endswith("gatewayfirst"):
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers concise replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    first_result = run_gateway_task(
        message="first question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
        request_id="gatewayfirst",
    )
    second_result = run_gateway_task(
        message="second question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
        request_id="gatewaysecond",
    )

    repository = SQLiteTaskRepository(db_path=task_db_path)
    second_task = repository.get("mente_gateway_gatewaysecond")

    assert first_result.metadata["memory_promotion"]["promoted_memory_ids"] == [
        "mente_gateway_gatewayfirst:memory:0"
    ]
    assert second_result.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert second_result.metadata["memory_context"]["injected_count"] == 0
    assert second_result.metadata["memory_audit"]["policy_id"] == "gateway:conversation"
    assert second_result.metadata["memory_audit"]["selected"][0]["memory_id"] == (
        "mente_gateway_gatewayfirst:memory:0"
    )
    assert second_task is not None
    assert second_task.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert second_task.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_gateway_gatewayfirst:memory:0"
    )
    assert second_task.metadata["memory_audit"]["selected"][0]["memory_id"] == (
        "mente_gateway_gatewayfirst:memory:0"
    )


def test_gateway_adopted_second_run_surfaces_session_summary_in_memory_context_and_memory_audit(
    monkeypatch,
    tmp_path,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_SOURCES", "gateway")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", "1")

    def _fake_execute(self, request):
        if request.task_id.endswith("gatewaysummaryseed"):
            return ExecutionResult(
                status="success",
                summary="Remember that I prefer concise replies in this chat.",
            )
        return ExecutionResult(
            status="success",
            summary="Using the prior session summary.",
        )

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    first_result = run_gateway_task(
        message="Remember that I prefer concise replies in this chat.",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
        request_id="gatewaysummaryseed",
    )
    second_result = run_gateway_task(
        message="Use my prior preference.",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
        request_id="gatewaysummaryfollowup",
    )

    summary_id = "session_summary:gateway:session-1:gateway_conversation"
    stored_task = SQLiteTaskRepository(db_path=task_db_path).get(
        "mente_gateway_gatewaysummaryfollowup"
    )
    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(summary_id)
    selected = second_result.metadata["memory_context"]["selected"]
    audit_selected = second_result.metadata["memory_audit"]["selected"]
    summary_item = selected[0]
    audit_summary_item = audit_selected[0]

    assert first_result.metadata["session_synthesis"]["status"] == "persisted"
    assert summary_item["memory_id"] == summary_id
    assert summary_item["kind"] == "session_summary"
    assert summary_item["reason"] == "session_summary_priority"
    assert audit_summary_item["memory_id"] == summary_id
    assert audit_summary_item["kind"] == "session_summary"
    assert audit_summary_item["reason"] == "session_summary_priority"
    assert audit_summary_item["fact"] == summary_item["fact"]
    assert summary_memory is not None
    assert summary_memory.source == "gateway"
    assert summary_memory.task_type == "conversation"
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"][0] == summary_item
    assert stored_task.metadata["memory_audit"]["selected"][0] == audit_summary_item
    assert second_result.metadata["workflow_contract"]["memory_read"]["session_summary"] == {
        "enabled": True,
        "scope": "session",
        "kind": "session_summary",
        "priority": "before_generic_memories",
        "max_results": 1,
        "counts_toward_existing_budgets": True,
    }


def test_run_cron_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "cronfixed"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )

    result = run_cron_task(
        job={"id": "job-1", "name": "Nightly Sync"},
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_cron_job-1_cronfixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "cron"
    assert stored.status.value == "succeeded"


def test_run_gateway_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "gatewayfixed"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_gateway_gatewayfixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "gateway"
    assert stored.status.value == "succeeded"


def test_run_gateway_task_returns_task_profile_in_result_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(tmp_path / "state.db"))

    class _FakeUuid:
        hex = "gatewayprofile"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
    )

    assert result.status == "success"
    assert result.metadata["task_profile"] == "deep_research"


def test_run_gateway_task_threads_cancel_event_into_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(tmp_path / "memory.db"))

    captured = {}

    class _FakeOrchestrator:
        def run(self, task):
            captured["task"] = task
            return ExecutionResult(status="success", summary="done")

    def _fake_build_orchestrator(*args, **kwargs):
        captured["cancel_event"] = kwargs.get("cancel_event")
        return _FakeOrchestrator()

    monkeypatch.setattr(mente_bridge, "_build_orchestrator", _fake_build_orchestrator)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )
    cancel_event = threading.Event()

    result = run_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        cancel_event=cancel_event,
    )

    assert result.status == "success"
    assert captured["task"].metadata["source"] == "gateway"
    assert captured["cancel_event"] is cancel_event


def test_run_gateway_task_fast_paths_simple_model_identity_requests(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "gatewayfastmodel"

    def _fail_build_orchestrator(*args, **kwargs):
        raise AssertionError("fast-path requests must not build the orchestrator")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(mente_bridge, "_build_orchestrator", _fail_build_orchestrator)
    monkeypatch.setattr(
        mente_bridge,
        "_resolve_runtime_config_for_workspace",
        lambda workspace: RuntimeConfig(
            runtime_home=tmp_path / "runtime-home",
            model_runtime=ModelRuntime(model="mimo-v2.5-pro"),
        ),
    )

    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="你是什么大模型",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_gateway_gatewayfastmodel")
    assert result.status == "success"
    assert (
        result.summary
        == "我是 Mente，当前接入的模型是 mimo-v2.5-pro。我可以通过工具帮你执行代码、操作文件、搜索信息等任务。"
    )
    assert result.metadata["fast_path"]["kind"] == "model_identity"
    assert stored is not None
    assert stored.status.value == "succeeded"
    assert stored.metadata["fast_path"]["kind"] == "model_identity"


def test_run_tui_task_fast_paths_simple_identity_requests(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "tuifastidentity"

    def _fail_build_orchestrator(*args, **kwargs):
        raise AssertionError("fast-path requests must not build the orchestrator")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(mente_bridge, "_build_orchestrator", _fail_build_orchestrator)

    result = run_tui_task(
        user_message="你是谁",
        conversation_history=[],
        session_id="tui-session-1",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_tui_tuifastidentity")
    assert result.status == "success"
    assert result.summary == "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。"
    assert result.metadata["fast_path"]["kind"] == "identity"
    assert stored is not None
    assert stored.status.value == "succeeded"
    assert stored.metadata["fast_path"]["kind"] == "identity"


def test_run_api_server_task_fast_paths_simple_model_identity_requests(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "apifastmodel"

    def _fail_build_orchestrator(*args, **kwargs):
        raise AssertionError("fast-path requests must not build the orchestrator")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(mente_bridge, "_build_orchestrator", _fail_build_orchestrator)
    monkeypatch.setattr(
        mente_bridge,
        "_resolve_runtime_config_for_workspace",
        lambda workspace: RuntimeConfig(
            runtime_home=tmp_path / "runtime-home",
            model_runtime=ModelRuntime(model="mimo-v2.5-pro"),
        ),
    )

    result = run_api_server_task(
        user_message="你是什么大模型",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_api_server_apifastmodel")
    assert result.status == "success"
    assert (
        result.summary
        == "我是 Mente，当前接入的模型是 mimo-v2.5-pro。我可以通过工具帮你执行代码、操作文件、搜索信息等任务。"
    )
    assert result.metadata["fast_path"]["kind"] == "model_identity"
    assert stored is not None
    assert stored.status.value == "succeeded"
    assert stored.metadata["fast_path"]["kind"] == "model_identity"


def test_run_gateway_task_direct_writes_explicit_chinese_remember_intent_when_flag_enabled(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "1")

    class _FakeUuid:
        hex = "gatewayremember"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="记下了。"),
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="加入记忆：我更喜欢中文回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewayremember")
    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session("session-1", limit=10)

    assert result.status == "success"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert stored is not None
    assert stored.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "我更喜欢中文回答"
    assert memories[0].metadata["write_origin"] == "explicit_remember_intent"
    assert memories[0].metadata["tool_name"] == "mente_remember_intent_direct_write"
    assert memories[0].metadata["promotion_reason"] == "explicit_remember_intent"


def test_run_gateway_task_fast_paths_explicit_remember_intent_without_executor_by_default(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.delenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", raising=False)

    class _FakeUuid:
        hex = "gatewayrememberfast"

    def _fail_if_executor_runs(self, request):
        raise AssertionError("explicit remember-intent should not boot the executor")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fail_if_executor_runs)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="你错了，记住以后回答要先说结论",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewayrememberfast")
    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session("session-1", limit=10)

    assert result.status == "success"
    assert result.summary == "已写入记忆：以后回答要先说结论"
    assert result.metadata["fast_path"]["kind"] == "remember_intent_direct_write"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert stored is not None
    assert stored.metadata["fast_path"]["kind"] == "remember_intent_direct_write"
    assert stored.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "以后回答要先说结论"


def test_run_gateway_task_uses_llm_classifier_for_semantic_memory_complaints(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.delenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", raising=False)

    class _FakeUuid:
        hex = "gatewaysemanticremember"

    def _classify(*, message, context_facts=None, workspace=None):
        assert message == "你怎么这么笨，啥都记不住？"
        return ["用户希望 Mente 可靠记住纠错、偏好和长期指令"]

    def _fail_if_executor_runs(self, request):
        raise AssertionError("semantic remember-intent should not boot the executor")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge._classify_semantic_remember_intent_facts",
        _classify,
    )
    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fail_if_executor_runs)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="你怎么这么笨，啥都记不住？",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session("session-1", limit=10)

    assert result.status == "success"
    assert result.metadata["fast_path"]["kind"] == "remember_intent_direct_write"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "用户希望 Mente 可靠记住纠错、偏好和长期指令"


def test_run_gateway_task_summarizes_recent_context_for_bare_remember_intent(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.delenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", raising=False)

    class _FakeUuid:
        hex = "gatewaycontextremember"

    def _classify(*, message, context_facts=None, workspace=None):
        assert message == "加入记忆"
        context_blob = "\n".join(context_facts or [])
        assert "直接调用 rednote CLI 脚本发布小红书" in context_blob
        return ["发布小红书内容时直接调用 rednote CLI 脚本，不走 MCP"]

    def _fail_if_executor_runs(self, request):
        raise AssertionError("contextual remember-intent should not boot the executor")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge._classify_semantic_remember_intent_facts",
        _classify,
    )
    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fail_if_executor_runs)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="加入记忆",
        context_prompt="User corrected the agent: 直接调用 rednote CLI 脚本发布小红书，不走 MCP。",
        history=[
            {
                "role": "user",
                "content": "以后发布小红书，直接调用 rednote CLI 脚本，不走 MCP。",
            },
            {"role": "assistant", "content": "明白，下次直接调用脚本。"},
        ],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewaycontextremember")
    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session("session-1", limit=10)

    assert result.status == "success"
    assert result.summary == "已写入记忆：发布小红书内容时直接调用 rednote CLI 脚本，不走 MCP"
    assert result.metadata["fast_path"]["kind"] == "remember_intent_direct_write"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert stored is not None
    assert stored.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"


def test_run_gateway_task_runs_llm_memory_review_when_enabled(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")

    class _FakeUuid:
        hex = "gatewayllmmemory"

    def _fake_execute(self, request):
        return ExecutionResult(
            status="success",
            summary="Confirmed future Rednote publishing should use the CLI script rather than MCP.",
            commands_run=["rednote publish --draft article.md"],
        )

    def _fake_call_llm(**kwargs):
        prompt = kwargs["messages"][1]["content"]
        assert "rednote publish --draft article.md" in prompt

        class _Message:
            content = (
                '{"should_write": true, "facts": ["发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"], '
                '"confidence": "high", "reason": "stable workflow preference"}'
            )

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)
    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fake_call_llm)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="以后发布小红书直接用脚本，不要走 MCP。",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewayllmmemory")
    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session("session-1", limit=10)

    assert result.status == "success"
    assert result.metadata["llm_memory_review"]["status"] == "persisted"
    assert result.metadata["llm_memory_review"]["confidence"] == "high"
    assert stored is not None
    assert stored.metadata["llm_memory_review"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"
    assert memories[0].metadata["write_origin"] == "post_turn_llm_memory_review"


def test_remember_intent_classifier_parser_requires_write_and_confidence():
    assert mente_bridge._parse_remember_intent_classifier_payload(
        '{"should_write": true, "fact": " 用户希望以后直接调用脚本 ", "confidence": "high", "reason": "preference"}'
    ) == ["用户希望以后直接调用脚本"]

    assert mente_bridge._parse_remember_intent_classifier_payload(
        '{"should_write": true, "fact": "用户临时问天气", "confidence": "low", "reason": "weak"}'
    ) == []
    assert mente_bridge._parse_remember_intent_classifier_payload(
        '{"should_write": false, "fact": "不要写", "confidence": "high", "reason": "chat"}'
    ) == []


def test_remember_intent_resolver_skips_llm_classifier_for_ordinary_messages(monkeypatch):
    def _fail_classifier(*, message, workspace=None):
        raise AssertionError("ordinary messages should not call the remember-intent classifier")

    monkeypatch.setattr(
        "mente.integrations.bridge._classify_semantic_remember_intent_facts",
        _fail_classifier,
    )

    assert mente_bridge._resolve_remember_intent_facts(
        message="帮我写一篇产品介绍",
        workspace=None,
    ) == []


def test_run_tui_task_fast_paths_semantic_remember_intent_without_executor(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.delenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", raising=False)

    class _FakeUuid:
        hex = "tuisemanticremember"

    def _classify(*, message, context_facts=None, workspace=None):
        assert message == "你怎么这么笨，啥都记不住？"
        return ["用户希望 Mente 可靠记住纠错、偏好和长期指令"]

    def _fail_if_executor_runs(self, request):
        raise AssertionError("semantic remember-intent should not boot the TUI executor")

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge._classify_semantic_remember_intent_facts",
        _classify,
    )
    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fail_if_executor_runs)

    result = run_tui_task(
        user_message="你怎么这么笨，啥都记不住？",
        conversation_history=[],
        session_id="tui-session-1",
        workspace=str(tmp_path),
    )

    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "tui-session-1",
        limit=10,
        source="tui",
    )

    assert result.status == "success"
    assert result.metadata["fast_path"]["kind"] == "remember_intent_direct_write"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert len(memories) == 1
    assert memories[0].fact == "用户希望 Mente 可靠记住纠错、偏好和长期指令"


def test_run_gateway_task_direct_write_flag_off_preserves_baseline_behavior(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "0")

    class _FakeUuid:
        hex = "gatewayrememberoff"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="记下了。"),
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="记住我喜欢简洁回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewayrememberoff")

    assert result.status == "success"
    assert result.metadata["remember_intent_direct_write"]["status"] == "skipped"
    assert result.metadata["remember_intent_direct_write"]["reason"] == "disabled"
    assert stored is not None
    assert stored.metadata["remember_intent_direct_write"]["status"] == "skipped"
    assert SQLiteMemoryRepository(db_path=memory_db_path).list_recent() == []


def test_run_gateway_task_does_not_direct_write_pure_criticism_when_flag_enabled(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "1")

    class _FakeUuid:
        hex = "gatewaycriticism"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="我会注意。"),
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="你错了",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_gateway_gatewaycriticism")

    assert result.status == "success"
    assert result.metadata["remember_intent_direct_write"]["status"] == "noop"
    assert stored is not None
    assert stored.metadata["remember_intent_direct_write"]["status"] == "noop"
    assert SQLiteMemoryRepository(db_path=memory_db_path).list_recent() == []


def test_run_gateway_task_direct_write_normalizes_whitespace_and_fullwidth_punctuation_before_dedup(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "1")

    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="记下了。"),
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="加入记忆：我更喜欢中文回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        request_id="gatewayremembernorm1",
    )
    run_gateway_task(
        message="加入记忆:  我更喜欢中文回答  ",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        request_id="gatewayremembernorm2",
    )

    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "session-1",
        limit=10,
        source="gateway",
    )

    assert [memory.fact for memory in memories] == ["我更喜欢中文回答"]


def test_run_gateway_task_direct_write_supersedes_prior_active_preference_in_same_session(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "1")

    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="记下了。"),
    )

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="加入记忆：我喜欢英文回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        request_id="gatewayprefold",
    )
    run_gateway_task(
        message="加入记忆：我更喜欢中文回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
        request_id="gatewayprefnew",
    )

    repository = SQLiteMemoryRepository(db_path=memory_db_path)
    active_rows = repository.list_by_session(
        "session-1",
        limit=10,
        source="gateway",
    )
    superseded_rows = repository.list_by_session(
        "session-1",
        limit=10,
        source="gateway",
        include_inactive=True,
    )

    assert [row.fact for row in active_rows] == ["我更喜欢中文回答"]
    assert [row.fact for row in superseded_rows if row.active is False] == ["我喜欢英文回答"]


def test_run_api_server_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "apifixed"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="done",
            memory_candidates=["User prefers JSON-first replies."],
        ),
    )

    result = run_api_server_task(
        user_message="latest question",
        conversation_history=[{"role": "assistant", "content": "Prior reply"}],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_api_server_apifixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "api_server"
    assert stored.metadata["api_mode"] == "responses"
    assert stored.status.value == "succeeded"


def test_run_api_server_task_direct_write_prevents_duplicate_memory_review(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED", "1")

    class _FakeUuid:
        hex = "apidirectwrite"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="记下了。"),
    )

    result = run_api_server_task(
        user_message="记住我喜欢简洁回答",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apidirectwrite")
    memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "api-session-1",
        limit=10,
        source="api_server",
    )

    assert result.status == "success"
    assert result.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert result.metadata["memory_review"]["status"] == "noop"
    assert stored is not None
    assert stored.metadata["remember_intent_direct_write"]["status"] == "persisted"
    assert stored.metadata["memory_review"]["status"] == "noop"
    assert stored.metadata["memory_review"]["reason"] == "duplicate_existing"
    assert len(memories) == 1
    assert memories[0].fact == "我喜欢简洁回答"
    assert memories[0].metadata["write_origin"] == "explicit_remember_intent"


def test_run_api_server_task_persists_execution_session_audit_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "apiaudit"

    audit_payload = {
        "mode": "resume",
        "requested_mode": "resume",
        "effective_mode": "resume",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": "thread-123",
        "continuity_status": "resumed",
        "fallback_reason": None,
    }

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        mente_bridge,
        "_APIServerIsolationExecutor",
        lambda **kwargs: _FakeKernelAdapter(
            result=ExecutionResult(
                status="success",
                summary="done",
                metadata={"execution_session": audit_payload},
            )
        ),
    )

    result = run_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-123",
        ),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_api_server_apiaudit")
    assert result.status == "success"
    assert result.metadata["execution_session"] == audit_payload
    assert stored is not None
    assert stored.metadata["execution_session"] == audit_payload


def test_run_api_server_task_persists_execution_session_fallback_audit_metadata(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "apifallbackaudit"

    audit_payload = {
        "mode": "stateless",
        "requested_mode": "resume",
        "effective_mode": "stateless",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "fallback_stateless",
        "fallback_reason": "thread_not_found",
    }

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        mente_bridge,
        "_APIServerIsolationExecutor",
        lambda **kwargs: _FakeKernelAdapter(
            result=ExecutionResult(
                status="success",
                summary="done",
                metadata={"execution_session": audit_payload},
            )
        ),
    )

    result = run_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-stale",
        ),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_api_server_apifallbackaudit")
    assert result.status == "success"
    assert result.metadata["execution_session"] == audit_payload
    assert stored is not None
    assert stored.metadata["execution_session"] == audit_payload


def test_run_api_server_task_adoption_contract_persists_review_outcomes_and_continuity_audit(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", "1")

    skills_dir = mente_home / "skills" / "coding" / "python-debug"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("# test\n", encoding="utf-8")

    class _FakeUuid:
        hex = "apiadoption"

    audit_payload = {
        "mode": "resume",
        "requested_mode": "resume",
        "effective_mode": "resume",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": "thread-123",
        "continuity_status": "resumed",
        "fallback_reason": None,
    }

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="Remember that I prefer concise JSON responses.",
            commands_run=["sed -n 1,40p skills/coding/python-debug/SKILL.md"],
            memory_candidates=["User prefers JSON-first replies."],
            metadata={"execution_session": audit_payload},
        ),
    )

    result = run_api_server_task(
        user_message="Remember that I prefer concise JSON responses.",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-123",
        ),
        skill_refs=["coding/python-debug"],
    )

    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apiadoption")
    review_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_api_server_apiadoption:review:0"
    )
    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "session_summary:api_server:api-session-1:api_server_conversation"
    )

    assert result.metadata["execution_session"] == audit_payload
    assert result.metadata["workflow_contract"]["session_synthesis"] == {
        "mode": "post_turn_periodic",
        "enabled": True,
        "turn_interval": 1,
        "summary_scope": "session",
        "summary_kind": "session_summary",
        "summary_memory_id_mode": "stable_latest_per_session",
        "builder": "deterministic_v1",
    }
    assert result.metadata["memory_review"]["status"] == "persisted"
    assert result.metadata["skill_review"]["status"] == "suggested"
    assert result.metadata["session_synthesis"]["status"] == "persisted"
    assert stored_task is not None
    assert stored_task.metadata["workflow_contract"]["workflow_id"] == "api_server_conversation"
    assert stored_task.metadata["workflow_contract"]["adoption_enabled"] is True
    assert stored_task.metadata["workflow_contract"]["session_synthesis"] == {
        "mode": "post_turn_periodic",
        "enabled": True,
        "turn_interval": 1,
        "summary_scope": "session",
        "summary_kind": "session_summary",
        "summary_memory_id_mode": "stable_latest_per_session",
        "builder": "deterministic_v1",
    }
    assert stored_task.metadata["memory_review"]["status"] == "persisted"
    assert stored_task.metadata["skill_review"]["status"] == "suggested"
    assert stored_task.metadata["session_synthesis"]["status"] == "persisted"
    assert stored_task.metadata["execution_session"] == audit_payload
    assert review_memory is not None
    assert review_memory.fact == "I prefer concise JSON responses."
    assert review_memory.metadata["write_origin"] == "post_turn_memory_review"
    assert summary_memory is not None
    assert summary_memory.kind == "session_summary"
    assert summary_memory.metadata["write_origin"] == "session_synthesis"


def test_api_server_adopted_second_run_surfaces_session_summary_in_memory_context_and_memory_audit(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", "1")

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("apisummaryseed"), _FakeUuid("apisummaryfollowup")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))

    def _fake_execute(self, request):
        if request.task_id.endswith("apisummaryseed"):
            return ExecutionResult(
                status="success",
                summary="Remember that I prefer concise JSON responses.",
            )
        return ExecutionResult(
            status="success",
            summary="Using the prior session summary.",
        )

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    first_result = run_api_server_task(
        user_message="Remember that I prefer concise JSON responses.",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )
    second_result = run_api_server_task(
        user_message="Use my prior preference.",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    summary_id = "session_summary:api_server:api-session-1:api_server_conversation"
    stored_task = SQLiteTaskRepository(db_path=task_db_path).get(
        "mente_api_server_apisummaryfollowup"
    )
    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(summary_id)
    selected = second_result.metadata["memory_context"]["selected"]
    audit_selected = second_result.metadata["memory_audit"]["selected"]
    summary_item = selected[0]
    audit_summary_item = audit_selected[0]

    assert first_result.metadata["session_synthesis"]["status"] == "persisted"
    assert summary_item["memory_id"] == summary_id
    assert summary_item["kind"] == "session_summary"
    assert summary_item["reason"] == "session_summary_priority"
    assert audit_summary_item["memory_id"] == summary_id
    assert audit_summary_item["kind"] == "session_summary"
    assert audit_summary_item["reason"] == "session_summary_priority"
    assert audit_summary_item["fact"] == summary_item["fact"]
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"][0] == summary_item
    assert stored_task.metadata["memory_audit"]["selected"][0] == audit_summary_item
    assert summary_memory is not None
    assert summary_memory.source == "api_server"
    assert summary_memory.task_type == "conversation"
    assert second_result.metadata["workflow_contract"]["memory_read"]["session_summary"] == {
        "enabled": True,
        "scope": "session",
        "kind": "session_summary",
        "priority": "before_generic_memories",
        "max_results": 1,
        "counts_toward_existing_budgets": True,
    }


def test_api_server_session_synthesis_refreshes_stable_summary_row_in_sqlite_e2e(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", "1")
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "0")

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("apisummarysame1"), _FakeUuid("apisummarysame2")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="Captured the rollout constraints.",
        ),
    )

    first_result = run_api_server_task(
        user_message="first",
        conversation_history=[],
        session_id="api-session-same-summary",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )
    summary_id = "session_summary:api_server:api-session-same-summary:api_server_conversation"
    first_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(summary_id)

    second_result = run_api_server_task(
        user_message="second",
        conversation_history=[],
        session_id="api-session-same-summary",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(summary_id)
    session_rows = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "api-session-same-summary",
        source="api_server",
        task_type="conversation",
        memory_scope="session",
    )

    assert first_result.metadata["session_synthesis"]["status"] == "persisted"
    assert second_result.metadata["session_synthesis"]["status"] == "persisted"
    assert first_memory is not None
    assert summary_memory is not None
    assert summary_memory.memory_id == summary_id
    assert summary_memory.fact == first_memory.fact
    assert summary_memory.task_id == "mente_api_server_apisummarysame2"
    assert summary_memory.metadata["source_task_id"] == "mente_api_server_apisummarysame2"
    assert summary_memory.metadata["window_task_ids"] == ["mente_api_server_apisummarysame2"]
    assert len(session_rows) == 1


def test_api_server_second_run_with_summary_flag_off_fails_closed_to_baseline(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", "1")

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("apisummaryseedoff"), _FakeUuid("apisummaryfollowupoff")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))

    def _fake_execute(self, request):
        if request.task_id.endswith("apisummaryseedoff"):
            return ExecutionResult(
                status="success",
                summary="Remember that I prefer concise JSON responses.",
            )
        return ExecutionResult(
            status="success",
            summary="I do not have any stored summary for this turn.",
        )

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    first_result = run_api_server_task(
        user_message="Remember that I prefer concise JSON responses.",
        conversation_history=[],
        session_id="api-session-flag-off",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )
    monkeypatch.setenv("MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED", "0")
    second_result = run_api_server_task(
        user_message="Use my prior preference.",
        conversation_history=[],
        session_id="api-session-flag-off",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    summary_id = "session_summary:api_server:api-session-flag-off:api_server_conversation"
    stored_task = SQLiteTaskRepository(db_path=task_db_path).get(
        "mente_api_server_apisummaryfollowupoff"
    )
    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(summary_id)

    assert first_result.metadata["session_synthesis"]["status"] == "persisted"
    assert summary_memory is not None
    assert all(
        item["kind"] != "session_summary"
        for item in second_result.metadata["memory_context"]["selected"]
    )
    assert all(
        item["kind"] != "session_summary"
        for item in second_result.metadata["memory_audit"]["selected"]
    )
    assert second_result.metadata["workflow_contract"]["memory_read"]["session_summary"] == {
        "enabled": False,
        "scope": "session",
        "kind": "session_summary",
        "priority": "before_generic_memories",
        "max_results": 1,
        "counts_toward_existing_budgets": True,
    }
    assert stored_task is not None
    assert all(
        item["kind"] != "session_summary"
        for item in stored_task.metadata["memory_context"]["selected"]
    )
    assert all(
        item["kind"] != "session_summary"
        for item in stored_task.metadata["memory_audit"]["selected"]
    )


def test_run_api_server_task_adoption_contract_with_flag_off_skips_review_side_effects(
    tmp_path,
    monkeypatch,
):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")

    class _FakeUuid:
        hex = "apinoadopt"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="done",
            memory_candidates=["User prefers terse replies."],
        ),
    )

    result = run_api_server_task(
        user_message="Remember that I prefer terse replies.",
        conversation_history=[],
        session_id="api-session-2",
        api_mode="chat_completions",
        workspace=str(tmp_path),
        skill_refs=["coding/python-debug"],
    )

    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apinoadopt")
    review_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_api_server_apinoadopt:review:0"
    )
    summary_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "session_summary:api_server:api-session-2:api_server_conversation"
    )

    assert result.metadata["workflow_contract"]["adoption_enabled"] is False
    assert result.metadata["workflow_contract"]["session_synthesis"] == {
        "mode": "post_turn_periodic",
        "enabled": False,
        "turn_interval": 5,
        "summary_scope": "session",
        "summary_kind": "session_summary",
        "summary_memory_id_mode": "stable_latest_per_session",
        "builder": "deterministic_v1",
    }
    assert "session_synthesis_artifact" not in result.metadata
    assert "memory_review" not in result.metadata
    assert "skill_review" not in result.metadata
    assert "session_synthesis" not in result.metadata
    assert stored_task is not None
    assert stored_task.metadata["workflow_contract"]["adoption_enabled"] is False
    assert stored_task.metadata["workflow_contract"]["session_synthesis"] == {
        "mode": "post_turn_periodic",
        "enabled": False,
        "turn_interval": 5,
        "summary_scope": "session",
        "summary_kind": "session_summary",
        "summary_memory_id_mode": "stable_latest_per_session",
        "builder": "deterministic_v1",
    }
    assert "session_synthesis_artifact" not in stored_task.metadata
    assert "memory_review" not in stored_task.metadata
    assert "skill_review" not in stored_task.metadata
    assert "session_synthesis" not in stored_task.metadata
    assert review_memory is None
    assert summary_memory is None


def test_api_server_second_run_selects_session_memory(tmp_path, monkeypatch):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("apifirst"), _FakeUuid("apisecond")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))

    def _fake_execute(self, request):
        if request.task_id.endswith("apifirst"):
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers JSON-first replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.bridge.CodexExecutor.execute", _fake_execute)

    first_result = run_api_server_task(
        user_message="Remember this preference",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )
    second_result = run_api_server_task(
        user_message="What do I prefer?",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    stored_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_api_server_apifirst:memory:0"
    )
    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apisecond")

    assert first_result.metadata["memory_promotion"]["promoted_memory_ids"] == [
        "mente_api_server_apifirst:memory:0"
    ]
    assert stored_memory is not None
    assert stored_memory.scope == "session"
    assert stored_memory.session_id == "api-session-1"
    assert second_result.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_api_server_apifirst:memory:0"
    )
    assert second_result.metadata["memory_context"]["selected"][0]["kind"] == "fact"
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_api_server_apifirst:memory:0"
    )
    assert all(
        item["kind"] != "session_summary"
        for item in second_result.metadata["memory_context"]["selected"]
    )


def test_api_server_fresh_session_does_not_promote_fabricated_prior_preferences(tmp_path, monkeypatch):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        hex = "apiisolated"

    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="You mentioned earlier that you prefer terse replies.",
            memory_candidates=["User previously said they prefer terse replies."],
        ),
    )

    result = run_api_server_task(
        user_message="What preferences did I mention earlier?",
        conversation_history=[],
        session_id="api-session-empty",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apiisolated")
    session_memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "api-session-empty",
        source="api_server",
        task_type="conversation",
        memory_scope="session",
    )

    assert result.metadata["memory_context"]["selected"] == []
    assert result.metadata["memory_promotion"]["promoted_memory_ids"] == []
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"] == []
    assert stored_task.metadata["memory_promotion"]["promoted_memory_ids"] == []
    assert session_memories == []


def test_run_cron_task_closes_repository(monkeypatch, tmp_path):
    class _FakeRepo:
        def __init__(self):
            self.closed = False

        def save(self, task):
            return None

        def get(self, task_id):
            return None

        def close(self):
            self.closed = True

    fake_repo = _FakeRepo()
    monkeypatch.setattr(
        "mente.integrations.bridge.SQLiteTaskRepository",
        lambda: fake_repo,
    )
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )

    run_cron_task(
        job={"id": "job-1", "name": "Nightly Sync"},
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    assert fake_repo.closed is True


def test_run_gateway_task_closes_repository(monkeypatch, tmp_path):
    class _FakeRepo:
        def __init__(self):
            self.closed = False

        def save(self, task):
            return None

        def get(self, task_id):
            return None

        def close(self):
            self.closed = True

    fake_repo = _FakeRepo()
    monkeypatch.setattr(
        "mente.integrations.bridge.SQLiteTaskRepository",
        lambda: fake_repo,
    )
    monkeypatch.setattr(
        "mente.integrations.bridge.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert fake_repo.closed is True



def test_cutover_manifest_records_bridge_owned_boundary():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    assert "vendored codex bridge is now the main execution path" in content
    assert "selected front door" in content
    assert "tools/plugins/skills migration remains deferred" in content


def test_gateway_task_resolves_policy_in_mente_ingress(monkeypatch, tmp_path):
    captured = {}

    def _fake_resolve(
        *,
        source: str,
        task_type: str,
        task_profile: str | None = None,
    ) -> ToolExposurePolicy:
        captured["source"] = source
        captured["task_type"] = task_type
        captured["task_profile"] = task_profile
        return ToolExposurePolicy(
            policy_id=f"{source}:{task_type}",
            source=source,
            native_tools=["exec_command"],
            bridge_tools=["mente_memory_query"],
            session_capable=False,
            native_tool_source="kernel/codex/upstream/codex-rs/tools/src/lib.rs",
            bridge_tool_source="mente/executors/bridge_tools.py",
        )

    monkeypatch.setattr(mente_bridge, "resolve_tool_exposure_policy", _fake_resolve)

    task = build_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=SessionSource(
            platform=Platform.LOCAL,
            chat_id="cli",
            chat_name="CLI",
            chat_type="dm",
            user_id="user-1",
        ),
        session_id="session-1",
        workspace=str(tmp_path),
    )

    assert captured == {"source": "gateway", "task_type": "conversation", "task_profile": None}
    assert task.metadata["tool_policy"] == _fake_resolve(
        source="gateway", task_type="conversation", task_profile=None
    ).as_metadata()
