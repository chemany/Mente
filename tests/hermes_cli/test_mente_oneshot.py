from hermes_cli.oneshot import _run_mente, run_oneshot
from mente.task_core.models import ExecutionMode, SessionMode


def test_run_oneshot_routes_through_mente(monkeypatch, capsys):
    bootstrap_calls = []
    monkeypatch.setattr(
        "hermes_cli.oneshot.bootstrap_mente_home",
        lambda: bootstrap_calls.append(True),
    )
    monkeypatch.setattr(
        "hermes_cli.oneshot._run_mente",
        lambda prompt, model=None, provider=None: "via mente",
    )
    rc = run_oneshot("inspect repo")
    captured = capsys.readouterr()
    assert rc == 0
    assert bootstrap_calls == [True]
    assert captured.out == "via mente\n"


def test_run_mente_requests_sessionful_start(monkeypatch):
    captured = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured["orchestrator_kwargs"] = kwargs

        def run(self, task):
            captured["task"] = task
            return type("Result", (), {"summary": "via mente"})()

    monkeypatch.setattr("hermes_cli.oneshot.Orchestrator", _FakeOrchestrator, raising=False)
    monkeypatch.setattr("mente.orchestrator.service.Orchestrator", _FakeOrchestrator)

    result = _run_mente("inspect repo", model="gpt-5.4", provider="openai")

    assert result == "via mente"
    task = captured["task"]
    assert task.metadata["source"] == "oneshot"
    assert task.execution_mode is ExecutionMode.SESSIONFUL
    assert task.execution_session is not None
    assert task.execution_session.mode is SessionMode.START
