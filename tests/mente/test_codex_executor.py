from mente.executors.codex import CodexExecutor
from mente.task_core.models import ExecutionRequest


def test_codex_executor_builds_command():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )
    cmd = executor.build_command(request)
    assert cmd[0] == "codex"
    assert cmd[1] == "exec"
    assert any("Inspect repository" in part for part in cmd)
