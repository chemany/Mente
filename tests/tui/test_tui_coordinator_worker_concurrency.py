import threading
import types

from mente.execution_events import read_persisted_lane_job
from mente.integrations.bridge import build_tui_task
from tui_gateway import server
from mente.task_core.models import DispatchMode, ExecutionResult
from mente.task_core.models import ExecutionMode, Task, TaskRole, TaskStatus
from mente.task_core.repository import SQLiteTaskRepository


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        **extra,
    }


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _save_worker_task(*, session_id: str, job_id: str, task_id: str) -> None:
    repo = SQLiteTaskRepository()
    repo.save(
        Task(
            task_id=task_id,
            session_id=session_id,
            task_type="conversation",
            objective="Run the delegated worker task.",
            user_request="研究供应商价格",
            status=TaskStatus.EXECUTING,
            role=TaskRole.WORKER,
            dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
            worker_lane="research",
            job_id=job_id,
            execution_mode=ExecutionMode.STATELESS,
            metadata={
                "source": "tui",
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["skills/research/web"],
            },
        )
    )
    repo.close()


def test_prompt_submit_frontdesk_status_uses_worker_registry(monkeypatch):
    emits = []
    server._sessions["sid"] = _session()
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
    )
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "当前进度？"},
            }
        )

        assert resp["result"]["status"] == "complete"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        assert "Collecting vendor benchmarks" in complete_calls[0][2]["text"]
        assert server._sessions["sid"]["running"] is False
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_allows_clarification_turn_while_worker_active(monkeypatch):
    calls = []

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None):
            calls.append(prompt)
            return {
                "final_response": "请按中文 markdown 输出。",
                "messages": [{"role": "assistant", "content": "请按中文 markdown 输出。"}],
            }

    server._sessions["sid"] = _session(agent=_Agent())
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
    )
    emits = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "顺便确认一下输出格式要中文 markdown"},
            }
        )

        assert resp["result"]["status"] == "streaming"
        assert calls == ["顺便确认一下输出格式要中文 markdown"]
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        assert "中文 markdown" in complete_calls[0][2]["text"]
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_worker_control_targets_active_job_without_dropping_session():
    cancel_event = threading.Event()
    server._sessions["sid"] = _session()
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
        cancel_event=cancel_event,
    )
    try:
        pause_resp = server.handle_request(
            {
                "id": "1",
                "method": "worker.control",
                "params": {"session_id": "sid", "action": "pause"},
            }
        )
        assert pause_resp["result"]["status"] == "paused"
        paused = server.get_background_worker_job("sid", lane="research")
        assert paused is not None
        assert paused["status"] == "paused"
        assert cancel_event.is_set() is False
        assert "sid" in server._sessions

        cancel_resp = server.handle_request(
            {
                "id": "2",
                "method": "worker.control",
                "params": {"session_id": "sid", "action": "cancel"},
            }
        )
        assert cancel_resp["result"]["status"] == "cancelled"
        assert cancel_event.is_set() is True
        cancelled = server.get_background_worker_job("sid", lane="research")
        assert cancelled is not None
        assert cancelled["status"] == "cancelled"
        assert "sid" in server._sessions
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_pause_this_research_marks_worker_paused_and_keeps_frontdesk_live(monkeypatch):
    emits = []
    server._sessions["sid"] = _session(running=True)
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
        metadata={"lane": "research", "task_profile": "deep_research"},
    )
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "暂停这个研究"},
            }
        )

        assert resp["result"]["status"] == "complete"
        paused = server.get_background_worker_job("sid", lane="research")
        assert paused is not None
        assert paused["status"] == "paused"
        assert server._sessions["sid"]["running"] is True

        repo = SQLiteTaskRepository()
        persisted = read_persisted_lane_job(
            repo,
            session_id="sid",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
        )
        repo.close()

        assert persisted is not None
        assert persisted["latest_job_state"] == "paused"
        assert persisted["metadata"]["control_contract"]["action"] == "pause"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        assert "Paused" in complete_calls[0][2]["text"]
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_worker_control_cancel_persists_terminal_checkpoint():
    cancel_event = threading.Event()
    server._sessions["sid"] = _session(running=True)
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
        metadata={"lane": "research", "task_profile": "deep_research"},
        cancel_event=cancel_event,
    )
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "worker.control",
                "params": {"session_id": "sid", "action": "cancel"},
            }
        )

        assert resp["result"]["status"] == "cancelled"
        assert cancel_event.is_set() is True

        repo = SQLiteTaskRepository()
        persisted = read_persisted_lane_job(
            repo,
            session_id="sid",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
        )
        repo.close()

        assert persisted is not None
        assert persisted["latest_job_state"] == "cancelled"
        assert persisted["failure_reason"] == "interrupted_by_user"
        assert persisted["metadata"]["final_checkpoint"]["status"] == "cancelled"
        assert persisted["metadata"]["latest_event_type"] == "lane.cancelled"
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_continue_soft_paused_worker_returns_to_running(monkeypatch):
    emits = []
    server._sessions["sid"] = _session(running=True)
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Paused while comparing vendors",
        status="paused",
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "control_contract": {
                "action": "pause",
                "mode": "soft_pause",
                "runtime_mutation_supported": False,
            },
        },
    )
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "继续跑"},
            }
        )

        assert resp["result"]["status"] == "complete"
        resumed = server.get_background_worker_job("sid", lane="research")
        assert resumed is not None
        assert resumed["status"] == "running"

        repo = SQLiteTaskRepository()
        persisted = read_persisted_lane_job(
            repo,
            session_id="sid",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
        )
        repo.close()

        assert persisted is not None
        assert persisted["latest_job_state"] == "running"
        assert persisted["metadata"]["control_contract"]["action"] == "resume"
        assert persisted["metadata"]["control_contract"]["mode"] == "soft_resume"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        assert "Continued" in complete_calls[0][2]["text"]
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_revision_supersedes_worker_and_preserves_lineage(monkeypatch):
    revision = "改成先比较价格，再写结论"
    cancel_event = threading.Event()
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )
    agent = server.MenteTuiAgent(inner, sid="sid", session_key="session-key")
    agent._recent_task_snapshots["research"] = {
        "user_request": "研究三家供应商并写结论",
        "status": "running",
        "assistant_summary": "正在整理供应商资料",
        "follow_up_tasks": ["补齐价格对比"],
        "metadata": {
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
        "updated_at": "2026-05-13T00:00:00",
    }
    server._sessions["sid"] = _session(agent=agent, running=True)
    _save_worker_task(
        session_id="sid",
        job_id="job-research-1",
        task_id="task-research-1",
    )
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
        cancel_event=cancel_event,
    )
    emits = []
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": revision},
            }
        )

        assert resp["result"]["status"] == "complete"
        assert cancel_event.is_set() is True

        queued = server.get_background_worker_job("sid", lane="research")
        assert queued is not None
        assert queued["status"] == "queued"
        assert queued["job_id"] != "job-research-1"
        assert queued["metadata"]["supersedes"]["job_id"] == "job-research-1"
        assert queued["metadata"]["supersedes"]["task_id"] == "task-research-1"
        assert queued["metadata"]["user_revision"] == revision

        snapshot = agent._recent_task_snapshots["research"]
        pending = snapshot["metadata"]["pending_worker_control"]
        assert pending["job_id"] == queued["job_id"]
        assert pending["task_id"] == queued["task_id"]
        assert pending["user_revision"] == revision

        repo = SQLiteTaskRepository()
        old_task = repo.get("task-research-1")
        persisted = read_persisted_lane_job(
            repo,
            session_id="sid",
            lane="research",
            job_id=queued["job_id"],
            task_id=queued["task_id"],
        )
        repo.close()

        assert old_task is not None
        assert old_task.metadata["superseded_by"]["job_id"] == queued["job_id"]
        assert old_task.metadata["superseded_by"]["task_id"] == queued["task_id"]
        assert persisted is not None
        assert persisted["latest_job_state"] == "queued"
        assert persisted["metadata"]["control_contract"]["mode"] == "supersede_worker"

        task = build_tui_task(
            user_message=revision,
            conversation_history=[],
            session_id="sid",
            recent_task_snapshot=snapshot,
            active_lane="research",
        )

        assert task.task_id == queued["task_id"]
        assert task.metadata["job_id"] == queued["job_id"]
        assert task.metadata["supersedes"]["job_id"] == "job-research-1"
        assert task.metadata["supersedes"]["task_id"] == "task-research-1"

        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        assert "superseding worker" in complete_calls[0][2]["text"]
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_same_lane_background_request_requires_confirmation(monkeypatch):
    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None):
            raise AssertionError("same-lane follow-up should not launch a new coordinator turn")

    emits = []
    server._sessions["sid"] = _session(agent=_Agent())
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
    )
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "再深度研究一下另一家供应商"},
            }
        )

        assert resp["result"]["status"] == "complete"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        text = complete_calls[0][2]["text"]
        assert "already" in text.lower() or "先取消" in text
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_live_delegated_prompt_submit_registers_worker_status_and_terminal_update(monkeypatch):
    emits = []
    worker_started = threading.Event()
    allow_finish = threading.Event()
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )
    agent = server.MenteTuiAgent(inner, sid="sid", session_key="session-key")
    server._sessions["sid"] = _session(agent=agent)

    def _fake_build_tui_task(**_kwargs):
        return types.SimpleNamespace(
            dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
            worker_lane="research",
            task_id="mente_tui_worker_1",
            metadata={
                "lane": "research",
                "job_id": "mente_tui_job_1",
                "task_profile": "deep_research",
            },
        )

    def _fake_run_tui_task(**_kwargs):
        worker_started.set()
        allow_finish.wait(timeout=2.0)
        return ExecutionResult(
            status="success",
            summary="Research finished",
            metadata={
                "task_id": "mente_tui_worker_1",
                "job_id": "mente_tui_job_1",
                "worker_lane": "research",
                "dispatch_mode": "delegate_background",
                "lane": "research",
            },
        )

    try:
        monkeypatch.setattr("mente.integrations.bridge.build_tui_task", _fake_build_tui_task)
        monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "深度研究一下另一家供应商",
                },
            }
        )

        assert resp["result"]["status"] == "streaming"
        assert worker_started.wait(timeout=1.0)

        status_resp = server.handle_request(
            {
                "id": "2",
                "method": "worker.status",
                "params": {"session_id": "sid"},
            }
        )
        active = status_resp["result"]["active"]
        assert active is not None
        assert active["lane"] == "research"
        assert active["status"] == "running"

        prompt_status = server.handle_request(
            {
                "id": "3",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "当前进度？"},
            }
        )
        assert prompt_status["result"]["status"] == "complete"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert any("Active research worker" in call[2]["text"] for call in complete_calls)

        allow_finish.set()
        for _ in range(20):
            final_job = server.get_background_worker_job("sid", lane="research")
            if final_job and final_job["status"] == "completed":
                break
            threading.Event().wait(0.05)

        final_job = server.get_background_worker_job("sid", lane="research")
        assert final_job is not None
        assert final_job["status"] == "completed"
        assert final_job["summary"] == "Research finished"
    finally:
        allow_finish.set()
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_live_delegated_prompt_submit_cancel_hits_real_worker_event(monkeypatch):
    worker_started = threading.Event()
    allow_finish = threading.Event()
    captured = {}
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )
    agent = server.MenteTuiAgent(inner, sid="sid", session_key="session-key")
    server._sessions["sid"] = _session(agent=agent)

    def _fake_build_tui_task(**_kwargs):
        return types.SimpleNamespace(
            dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
            worker_lane="research",
            task_id="mente_tui_worker_1",
            metadata={"lane": "research", "job_id": "mente_tui_job_1"},
        )

    def _fake_run_tui_task(**kwargs):
        captured["cancel_event"] = kwargs["cancel_event"]
        worker_started.set()
        allow_finish.wait(timeout=2.0)
        return ExecutionResult(
            status="failed",
            summary="cancelled",
            failure_reason="interrupted_by_user",
            metadata={
                "task_id": "mente_tui_worker_1",
                "job_id": "mente_tui_job_1",
                "worker_lane": "research",
                "dispatch_mode": "delegate_background",
            },
        )

    try:
        monkeypatch.setattr("mente.integrations.bridge.build_tui_task", _fake_build_tui_task)
        monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {
                    "session_id": "sid",
                    "text": "深度研究一下另一家供应商",
                },
            }
        )
        assert resp["result"]["status"] == "streaming"
        assert worker_started.wait(timeout=1.0)

        cancel_resp = server.handle_request(
            {
                "id": "2",
                "method": "worker.control",
                "params": {"session_id": "sid", "action": "cancel"},
            }
        )
        assert cancel_resp["result"]["status"] == "cancelled"
        assert captured["cancel_event"].is_set() is True

        allow_finish.set()
        for _ in range(20):
            final_job = server.get_background_worker_job("sid", lane="research")
            if final_job and final_job["status"] == "cancelled":
                break
            threading.Event().wait(0.05)

        final_job = server.get_background_worker_job("sid", lane="research")
        assert final_job is not None
        assert final_job["status"] == "cancelled"
    finally:
        allow_finish.set()
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")


def test_prompt_submit_same_lane_confirmation_prefers_target_job_lane(monkeypatch):
    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None):
            raise AssertionError("same-lane follow-up should not launch a new coordinator turn")

    emits = []
    server._sessions["sid"] = _session(agent=_Agent())
    server.register_background_worker_job(
        "sid",
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        summary="Collecting vendor benchmarks",
    )
    try:
        monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
        monkeypatch.setattr(
            "mente.integrations.bridge.resolve_dispatch_decision",
            lambda **_kwargs: types.SimpleNamespace(
                dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
                target_job_lane="research",
                worker_lane=None,
                lane="director",
            ),
        )

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "再深度研究一下另一家供应商"},
            }
        )

        assert resp["result"]["status"] == "complete"
        complete_calls = [call for call in emits if call[0] == "message.complete"]
        assert len(complete_calls) == 1
        text = complete_calls[0][2]["text"]
        assert "already" in text.lower() or "先取消" in text
    finally:
        server._sessions.pop("sid", None)
        server.clear_background_worker_job("sid", lane="research")
