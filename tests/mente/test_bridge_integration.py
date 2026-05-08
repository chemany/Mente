from pathlib import Path

from gateway.config import Platform
from gateway.session import SessionSource

from mente.integrations import bridge as mente_bridge
from mente.executors import CodexKernelAdapter, ToolExposurePolicy, resolve_tool_exposure_policy
from mente.executors.runtime_config import RuntimeConfig
from mente.integrations.bridge import (
    build_api_server_task,
    build_cron_task,
    build_gateway_task,
    extract_execution_session_handoff,
    normalize_api_execution_continuity,
    run_post_turn_memory_review,
    run_post_turn_skill_review,
    run_api_server_task,
    run_cron_task,
    run_gateway_task,
)
from mente.memory.repository import SQLiteMemoryRepository
from mente.task_core.models import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    SessionMode,
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
    assert any("Session context:" in fact for fact in task.memory_facts)
    assert any("Channel prompt:" in fact for fact in task.memory_facts)
    history_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Conversation history (JSON):")
    )
    assert '"role":"user"' in history_fact
    assert "timestamp" not in history_fact


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
    assert "mente_memory_query" in seen_requests[1].tool_policy["bridge_tools"]


def test_gateway_runs_persist_memory_observability_metadata(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("gatewayfirst"), _FakeUuid("gatewaysecond")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))

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

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("gatewayremembernorm1"), _FakeUuid("gatewayremembernorm2")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))
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
    )
    run_gateway_task(
        message="加入记忆:  我更喜欢中文回答  ",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
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

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("gatewayprefold"), _FakeUuid("gatewayprefnew")))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: next(uuids))
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
    )
    run_gateway_task(
        message="加入记忆：我更喜欢中文回答",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        workspace=str(tmp_path),
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
    assert second_result.metadata["memory_context"]["selected"] == []
    assert second_result.metadata["memory_audit"]["selected"] == []
    assert second_result.metadata["workflow_contract"]["memory_read"]["session_summary"] == {
        "enabled": False,
        "scope": "session",
        "kind": "session_summary",
        "priority": "before_generic_memories",
        "max_results": 1,
        "counts_toward_existing_budgets": True,
    }
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"] == []
    assert stored_task.metadata["memory_audit"]["selected"] == []


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

    def _fake_resolve(*, source: str, task_type: str) -> ToolExposurePolicy:
        captured["source"] = source
        captured["task_type"] = task_type
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

    assert captured == {"source": "gateway", "task_type": "conversation"}
    assert task.metadata["tool_policy"] == _fake_resolve(
        source="gateway", task_type="conversation"
    ).as_metadata()
