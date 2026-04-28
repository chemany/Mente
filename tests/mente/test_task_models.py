from mente.task_core.models import ExecutionRequest, ExecutionResult, Task, TaskStatus


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
