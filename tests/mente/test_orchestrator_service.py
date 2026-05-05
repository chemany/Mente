from mente.context_builder.builder import ContextBuilder
from mente.executors import CodexKernelAdapter
from mente.executors.base import Executor
from mente.feature_flags import build_api_server_conversation_workflow_contract
from mente.memory.models import MemoryBuildTrace, MemoryRecord, MemoryTraceItem
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary="ok")


class _ExecutorWithMemory(Executor):
    def execute(self, request):
        return ExecutionResult(
            status="success",
            summary="ok",
            memory_candidates=["Repository uses uv for Python commands."],
        )


class _KernelStyleExecutor(CodexKernelAdapter):
    def __init__(self) -> None:
        self.last_request = None

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        raise AssertionError("Orchestrator should not inspect adapter payload internals")

    def execute(self, request):
        self.last_request = request
        return ExecutionResult(
            status="success",
            summary="ok",
            memory_candidates=["Repository uses uv for Python commands."],
        )


class _StaticTraceContextBuilder:
    def __init__(self, trace: MemoryBuildTrace) -> None:
        self._trace = trace
        self.memory_policy_resolver = ContextBuilder().memory_policy_resolver

    def build_with_trace(self, task: Task):
        return (
            ExecutionRequest(
                task_id=task.task_id,
                session_id=task.session_id,
                task_type=task.task_type,
                objective=task.objective,
                user_request=task.user_request,
                workspace=task.workspace or ".",
                constraints=task.constraints,
                memory_facts=task.memory_facts,
                skill_refs=task.skill_refs,
                execution_mode=task.execution_mode,
                execution_session=task.execution_session,
                metadata=task.metadata,
            ),
            self._trace,
        )


def test_orchestrator_runs_task():
    repository = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=repository,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    result = orchestrator.run(task)
    assert result.status == "success"
    stored = repository.get("task_1")
    assert stored is not None
    assert stored.status.value == "succeeded"


def test_orchestrator_persists_promoted_memory():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)

    assert result.status == "success"
    rows = memory_repo.list_relevant(
        session_id="session_1",
        task_type="engineering",
        limit=5,
    )
    assert [row.fact for row in rows] == ["Repository uses uv for Python commands."]
    assert result.metadata["promoted_memory_count"] == 1


def test_orchestrator_persists_memory_context_and_promotion_metadata():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(memory_repository=memory_repo),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)
    persisted = task_repo.get("task_1")

    assert result.metadata["memory_context"]["injected_count"] == 1
    assert result.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert result.metadata["memory_promotion"]["promoted_count"] == 1
    assert result.metadata["memory_audit"]["policy_id"] == "gateway:conversation"
    assert result.metadata["memory_audit"]["selected"][0]["memory_id"] == "mem_1"
    assert result.metadata["memory_audit"]["promoted"][0]["memory_id"] == "task_1:memory:0"
    assert result.metadata["memory_audit"]["rejected"] == []
    assert result.metadata["memory_context"]["selected"][0]["kind"] == "fact"
    assert result.metadata["memory_audit"]["selected"][0]["kind"] == "fact"
    assert persisted is not None
    assert persisted.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert persisted.metadata["memory_context"]["selected"][0]["memory_id"] == "mem_1"
    assert persisted.metadata["memory_promotion"]["promoted_memory_ids"] == ["task_1:memory:0"]
    assert persisted.metadata["memory_audit"]["selected"][0]["memory_id"] == "mem_1"


def test_orchestrator_persists_memory_audit_for_skips_and_rejections():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_duplicate",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_selected",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="User likes Markdown bullets.",
        )
    )
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(memory_repository=memory_repo),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Memory: User prefers concise replies."],
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="ok",
        memory_candidates=[
            "Repository uses uv for Python commands.",
            " Repository uses uv for Python commands. ",
            "",
        ],
    )

    class _AuditedExecutor(Executor):
        def execute(self, request):
            return result

    orchestrator.executor = _AuditedExecutor()

    execution_result = orchestrator.run(task)
    persisted = task_repo.get("task_1")

    assert execution_result.metadata["memory_audit"] == {
        "policy_id": "gateway:conversation",
        "selected": [
            {
                "memory_id": "mem_selected",
                "scope": "global",
                "kind": "fact",
                "fact": "User likes Markdown bullets.",
                "reason": "scope_match",
            }
        ],
        "skipped": [
            {
                "memory_id": "mem_duplicate",
                "scope": "session",
                "kind": "fact",
                "fact": "User prefers concise replies.",
                "reason": "duplicate_existing_fact",
            }
        ],
        "promoted": [
            {
                "memory_id": "task_1:memory:0",
                "scope": "session",
                "fact": "Repository uses uv for Python commands.",
                "reason": "executor_memory_candidate",
            }
        ],
        "rejected": [
            {
                "fact": "Repository uses uv for Python commands.",
                "reason": "duplicate_candidate",
                "memory_id": None,
                "scope": None,
            },
            {
                "fact": "",
                "reason": "empty_candidate",
                "memory_id": None,
                "scope": None,
            },
        ],
    }
    assert persisted is not None
    assert persisted.metadata["memory_audit"] == execution_result.metadata["memory_audit"]


def test_orchestrator_serializes_session_summary_kind_in_memory_context_and_audit():
    task_repo = InMemoryTaskRepository()
    trace = MemoryBuildTrace(
        policy_id="api_server:conversation",
        retrieved_count=2,
        injected_count=1,
        prompt_budget_char_count=44,
        selected=[
            MemoryTraceItem(
                memory_id="session_summary:api_server:session_1:api_server_conversation",
                scope="session",
                kind="session_summary",
                fact="Session summary: user prefers terse JSON replies.",
                reason="session_summary_priority",
            )
        ],
        skipped=[
            MemoryTraceItem(
                memory_id="mem_global",
                scope="global",
                fact="Generic global fact for backfill.",
                reason="prompt_budget_reached",
            )
        ],
    )
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=_StaticTraceContextBuilder(trace),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_summary_trace",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={
            "source": "api_server",
            "workflow_contract": build_api_server_conversation_workflow_contract(
                environment={
                    "MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED": "1",
                    "MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED": "1",
                }
            ),
        },
    )

    result = orchestrator.run(task)
    stored = task_repo.get("task_summary_trace")

    assert result.metadata["memory_context"]["selected"] == [
        {
            "memory_id": "session_summary:api_server:session_1:api_server_conversation",
            "scope": "session",
            "kind": "session_summary",
            "fact": "Session summary: user prefers terse JSON replies.",
            "reason": "session_summary_priority",
        }
    ]
    assert result.metadata["memory_context"]["skipped"] == [
        {
            "memory_id": "mem_global",
            "scope": "global",
            "fact": "Generic global fact for backfill.",
            "reason": "prompt_budget_reached",
        }
    ]
    assert result.metadata["memory_audit"]["selected"] == [
        {
            "memory_id": "session_summary:api_server:session_1:api_server_conversation",
            "scope": "session",
            "kind": "session_summary",
            "fact": "Session summary: user prefers terse JSON replies.",
            "reason": "session_summary_priority",
        }
    ]
    assert result.metadata["memory_audit"]["skipped"] == [
        {
            "memory_id": "mem_global",
            "scope": "global",
            "fact": "Generic global fact for backfill.",
            "reason": "prompt_budget_reached",
        }
    ]
    assert stored is not None
    assert stored.metadata["memory_context"] == result.metadata["memory_context"]
    assert stored.metadata["memory_audit"] == result.metadata["memory_audit"]


def test_orchestrator_persists_memory_review_artifact():
    task_repo = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Remember that I prefer terse replies.",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)
    stored = task_repo.get("task_1")

    assert result.metadata["memory_review_artifact"] == {
        "assistant_summary": "ok",
        "status": "success",
    }
    assert stored is not None
    assert stored.metadata["memory_review_artifact"] == {
        "assistant_summary": "ok",
        "status": "success",
    }


def test_orchestrator_persists_skill_review_artifact():
    task_repo = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Capture the reusable workflow.",
        skill_refs=["coding/python-debug"],
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)
    stored = task_repo.get("task_1")

    assert result.metadata["skill_review_artifact"] == {
        "assistant_summary": "ok",
        "status": "success",
        "commands_run": [],
        "skill_refs": ["coding/python-debug"],
    }
    assert stored is not None
    assert stored.metadata["skill_review_artifact"] == {
        "assistant_summary": "ok",
        "status": "success",
        "commands_run": [],
        "skill_refs": ["coding/python-debug"],
    }


def test_orchestrator_persists_session_synthesis_artifact(monkeypatch):
    task_repo = InMemoryTaskRepository()
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")

    long_summary = "summary " * 80
    long_action = "action " * 40
    long_follow_up = "follow-up " * 40
    long_memory_candidate = "memory " * 40

    class _ArtifactExecutor(Executor):
        def execute(self, request):
            return ExecutionResult(
                status="success",
                summary=long_summary,
                actions_taken=[
                    long_action,
                    "created artifact",
                    "persisted metadata",
                    "verified output",
                    "extra action 1",
                    "extra action 2",
                ],
                follow_up_tasks=[
                    long_follow_up,
                    "check worker in Task 2",
                    "wire bridge in Task 3",
                    "keep rollout fail-closed",
                    "extra follow-up 1",
                    "extra follow-up 2",
                ],
                memory_candidates=[
                    long_memory_candidate,
                    "User prefers concise replies.",
                    "Use deterministic builders.",
                    "Persist stable memory ids.",
                    "Avoid transcript coupling.",
                    "extra candidate",
                ],
                raw_transcript_ref="transcript://should-not-leak",
                metadata={
                    "execution_session": {
                        "requested_mode": "resume",
                        "continuity_status": "resumed",
                    }
                },
            )

    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_ArtifactExecutor(),
        memory_repository=InMemoryMemoryRepository(),
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Capture bounded session synthesis inputs.",
        execution_mode="sessionful",
        metadata={
            "source": "api_server",
            "workflow_contract": build_api_server_conversation_workflow_contract(
                execution_mode="sessionful"
            ),
        },
    )

    result = orchestrator.run(task)
    stored = task_repo.get("task_1")

    expected_artifact = {
        "artifact_version": "v1",
        "status": "success",
        "assistant_summary": long_summary[:240].rstrip(),
        "actions_taken": [
            long_action[:160].rstrip(),
            "created artifact",
            "persisted metadata",
            "verified output",
            "extra action 1",
        ],
        "follow_up_tasks": [
            long_follow_up[:160].rstrip(),
            "check worker in Task 2",
            "wire bridge in Task 3",
            "keep rollout fail-closed",
            "extra follow-up 1",
        ],
        "memory_candidates": [
            long_memory_candidate[:160].rstrip(),
            "User prefers concise replies.",
            "Use deterministic builders.",
            "Persist stable memory ids.",
            "Avoid transcript coupling.",
        ],
        "promoted_memory_ids": ["task_1:memory:0", "task_1:memory:1", "task_1:memory:2"],
        "requested_execution_mode": "sessionful",
        "continuity_status": "resumed",
    }

    assert result.metadata["session_synthesis_artifact"] == expected_artifact
    assert "raw_transcript_ref" not in result.metadata["session_synthesis_artifact"]
    assert stored is not None
    assert stored.metadata["session_synthesis_artifact"] == expected_artifact


def test_orchestrator_skips_session_synthesis_artifact_outside_adopted_api_server_conversation():
    task_repo = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )

    for task in (
        Task(
            task_id="gateway_task",
            session_id="session_1",
            task_type="conversation",
            objective="Reply",
            user_request="Reply",
            metadata={"source": "gateway"},
        ),
        Task(
            task_id="cron_task",
            session_id="session_1",
            task_type="cron",
            objective="Run",
            user_request="Run",
            metadata={"source": "cron"},
        ),
        Task(
            task_id="api_server_not_adopted",
            session_id="session_1",
            task_type="conversation",
            objective="Reply",
            user_request="Reply",
            metadata={"source": "api_server"},
        ),
    ):
        result = orchestrator.run(task)
        stored = task_repo.get(task.task_id)

        assert "session_synthesis_artifact" not in result.metadata
        assert stored is not None
        assert "session_synthesis_artifact" not in stored.metadata


def test_orchestrator_runs_with_kernel_adapter_without_cli_details():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_KernelStyleExecutor(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)

    assert result.status == "success"
    assert result.memory_candidates == ["Repository uses uv for Python commands."]
    assert result.metadata["promoted_memory_count"] == 1


def test_orchestrator_threads_tool_policy_into_request_and_observability():
    task_repo = InMemoryTaskRepository()
    executor = _KernelStyleExecutor()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=executor,
        memory_repository=InMemoryMemoryRepository(),
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={
            "source": "gateway",
            "tool_policy": {
                "policy_id": "gateway:conversation",
                "source": "gateway",
                "native_tools": [],
                "bridge_tools": ["mente_memory_query"],
                "session_capable": False,
            },
        },
    )

    result = orchestrator.run(task)
    persisted = task_repo.get("task_1")

    assert executor.last_request is not None
    assert executor.last_request.tool_policy == {
        "policy_id": "gateway:conversation",
        "source": "gateway",
        "native_tools": [],
        "bridge_tools": ["mente_memory_query"],
        "session_capable": False,
    }
    assert result.metadata["tool_policy"] == executor.last_request.tool_policy
    assert persisted is not None
    assert persisted.metadata["tool_policy"] == executor.last_request.tool_policy
