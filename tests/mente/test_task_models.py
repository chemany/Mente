from mente.task_core.models import (
    DispatchMode,
    ExecutionRequest,
    ExecutionResult,
    Task,
    TaskRole,
    TaskStatus,
)


def test_task_defaults():
    task = Task(
        task_id="task_123",
        session_id="session_123",
        task_type="engineering",
        objective="Update a config file",
        user_request="change config",
    )
    assert task.status == TaskStatus.INGESTED
    assert task.acceptance_criteria == []
    assert task.role == TaskRole.WORKER
    assert task.dispatch_mode == DispatchMode.INLINE
    assert task.parent_task_id is None
    assert task.job_id is None
    assert task.worker_lane is None
    assert task.worker_skill_refs == []


def test_execution_result_success_shape():
    result = ExecutionResult(
        status="success",
        summary="done",
        actions_taken=["edited config"],
        changed_files=["config.yaml"],
    )
    assert result.status == "success"


def test_execution_request_minimal_shape():
    request = ExecutionRequest(
        task_id="task_123",
        session_id="session_123",
        task_type="engineering",
        objective="Update a config file",
        user_request="change config",
        workspace=".",
    )
    assert request.workspace == "."
    assert request.role == TaskRole.WORKER
    assert request.dispatch_mode == DispatchMode.INLINE


def test_task_normalizes_coordinator_role_and_background_dispatch():
    task = Task(
        task_id="task_456",
        session_id="session_456",
        task_type="conversation",
        objective="Coordinate a worker task",
        user_request="research this product",
        role="coordinator",
        dispatch_mode="delegate_background",
        parent_task_id="parent_1",
        job_id="job_1",
        worker_lane="research",
        worker_skill_refs=["research/deep-research-pro"],
    )

    assert task.role == TaskRole.COORDINATOR
    assert task.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert task.parent_task_id == "parent_1"
    assert task.job_id == "job_1"
    assert task.worker_lane == "research"
    assert task.worker_skill_refs == ["research/deep-research-pro"]


def test_execution_request_normalizes_worker_role_and_foreground_dispatch():
    request = ExecutionRequest(
        task_id="task_789",
        session_id="session_789",
        task_type="research",
        objective="Run delegated research",
        user_request="compare competitors",
        workspace=".",
        role="worker",
        dispatch_mode="delegate_foreground",
        parent_task_id="coordinator_1",
        job_id="job_2",
        worker_lane="research",
        worker_skill_refs=["research/deep-research-pro"],
    )

    assert request.role == TaskRole.WORKER
    assert request.dispatch_mode == DispatchMode.DELEGATE_FOREGROUND
    assert request.parent_task_id == "coordinator_1"
    assert request.job_id == "job_2"
    assert request.worker_lane == "research"
    assert request.worker_skill_refs == ["research/deep-research-pro"]
