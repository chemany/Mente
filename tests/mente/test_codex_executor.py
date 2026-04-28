from mente.executors.prompting import build_prompt_fingerprint, render_execution_prompt
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


def test_render_execution_prompt_and_fingerprint_are_stable():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        workspace=".",
        memory_facts=["Memory: User prefers concise replies."],
    )

    prompt = render_execution_prompt(request)
    fingerprint = build_prompt_fingerprint(prompt)

    assert "Memory Facts:" in prompt
    assert fingerprint == build_prompt_fingerprint(prompt)
    assert len(fingerprint) == 64
