import threading
from types import SimpleNamespace

import pytest

from gateway import run as gateway_run
from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_key
from gateway.platforms.base import MessageEvent, MessageType
from mente.task_core.models import DispatchMode, ExecutionResult


def _make_source(chat_id: str = "chat-1") -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat_id,
        chat_type="dm",
        user_id="user-1",
        user_name="tester",
    )


def _make_event(text: str, chat_id: str = "chat-1") -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=_make_source(chat_id),
        message_id="msg-1",
    )


def _make_runner() -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_worker_registry = {}
    runner._busy_ack_ts = {}
    runner._pending_messages = {}
    runner._queued_events = {}
    runner.adapters = {}
    runner.session_store = None
    runner.config = SimpleNamespace()
    runner._draining = False
    return runner


class TestGatewayCoordinatorWorkerConcurrency:
    def test_background_worker_status_follow_up_is_served_from_registry(self):
        runner = _make_runner()
        event = _make_event("当前进度？")
        session_key = build_session_key(event.source)

        runner._register_background_worker_job(
            session_key=session_key,
            session_id="sess-1",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
            summary="Collecting vendor benchmarks",
        )

        response = runner._maybe_handle_background_worker_frontdesk_message(
            event,
            session_key=session_key,
            session_id="sess-1",
        )

        assert response is not None
        assert "research" in response.lower()
        assert "Collecting vendor benchmarks" in response

    def test_background_worker_does_not_block_inline_clarification_turn(self):
        runner = _make_runner()
        event = _make_event("顺便确认一下输出格式要中文 markdown")
        session_key = build_session_key(event.source)

        runner._register_background_worker_job(
            session_key=session_key,
            session_id="sess-1",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
            summary="Collecting vendor benchmarks",
        )

        response = runner._maybe_handle_background_worker_frontdesk_message(
            event,
            session_key=session_key,
            session_id="sess-1",
        )

        assert response is None

    def test_pause_and_cancel_target_active_worker_without_dropping_frontdesk_session(self):
        runner = _make_runner()
        event = _make_event("暂停")
        session_key = build_session_key(event.source)
        cancel_event = threading.Event()

        runner._register_background_worker_job(
            session_key=session_key,
            session_id="sess-1",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
            summary="Collecting vendor benchmarks",
            cancel_event=cancel_event,
        )

        pause_response = runner._maybe_handle_background_worker_frontdesk_message(
            event,
            session_key=session_key,
            session_id="sess-1",
        )
        assert pause_response is not None
        assert "paused" in pause_response.lower()
        paused_job = runner._get_background_worker_job(session_key, lane="research")
        assert paused_job is not None
        assert paused_job.status == "paused"
        assert cancel_event.is_set() is False
        assert session_key not in runner._running_agents

        cancel_response = runner._maybe_handle_background_worker_frontdesk_message(
            _make_event("取消", chat_id=event.source.chat_id),
            session_key=session_key,
            session_id="sess-1",
        )
        assert cancel_response is not None
        assert "cancel" in cancel_response.lower()
        assert cancel_event.is_set() is True
        cancelled_job = runner._get_background_worker_job(session_key, lane="research")
        assert cancelled_job is not None
        assert cancelled_job.status == "cancelled"
        assert session_key not in runner._running_agents

    def test_second_same_lane_complex_request_requires_confirmation(self):
        runner = _make_runner()
        event = _make_event("再深度研究一下另一家供应商")
        session_key = build_session_key(event.source)

        runner._register_background_worker_job(
            session_key=session_key,
            session_id="sess-1",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
            summary="Collecting vendor benchmarks",
        )

        response = runner._maybe_handle_background_worker_frontdesk_message(
            event,
            session_key=session_key,
            session_id="sess-1",
        )

        assert response is not None
        assert "already" in response.lower() or "先取消" in response
        jobs = runner._list_background_worker_jobs(session_key)
        assert [(job.lane, job.job_id) for job in jobs] == [("research", "job-research-1")]

    def test_live_delegated_gateway_turn_registers_worker_and_updates_terminal_status(
        self, monkeypatch
    ):
        runner = _make_runner()
        source = _make_source()
        session_key = build_session_key(source)
        worker_started = threading.Event()
        allow_finish = threading.Event()
        callback_events = []

        def _register_started(payload):
            callback_events.append(("started", payload))
            runner._register_background_worker_job(
                session_key=session_key,
                session_id="sess-1",
                lane=str(payload["lane"]),
                job_id=str(payload["job_id"]),
                task_id=str(payload["task_id"]),
                summary=str(payload.get("summary") or ""),
                status=str(payload.get("status") or "running"),
                metadata=dict(payload.get("metadata") or {}),
                cancel_event=payload.get("cancel_event"),
            )

        def _register_finished(payload):
            callback_events.append(("finished", payload))
            runner._register_background_worker_job(
                session_key=session_key,
                session_id="sess-1",
                lane=str(payload["lane"]),
                job_id=str(payload["job_id"]),
                task_id=str(payload["task_id"]),
                summary=str(payload.get("summary") or ""),
                status=str(payload.get("status") or "completed"),
                metadata=dict(payload.get("metadata") or {}),
                cancel_event=payload.get("cancel_event"),
            )

        fake_bundle = SimpleNamespace(
            worker_task=SimpleNamespace(
                task_id="worker-task-1",
                worker_lane="research",
                metadata={"lane": "research", "task_profile": "deep_research"},
            ),
            coordinator_task=SimpleNamespace(job_id="job-research-1"),
            decision=SimpleNamespace(
                dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
                target_job_lane="research",
                worker_lane="research",
                lane="director",
            ),
        )

        def _fake_build_gateway_task_bundle(**_kwargs):
            return fake_bundle

        def _fake_run_gateway_task(**_kwargs):
            worker_started.set()
            allow_finish.wait(timeout=2.0)
            return ExecutionResult(
                status="success",
                summary="Research finished",
                metadata={
                    "task_id": "worker-task-1",
                    "job_id": "job-research-1",
                    "worker_lane": "research",
                    "dispatch_mode": "delegate_background",
                    "lane": "research",
                    "task_profile": "deep_research",
                },
            )

        monkeypatch.setattr(
            "mente.integrations.bridge.build_gateway_task_bundle",
            _fake_build_gateway_task_bundle,
        )
        monkeypatch.setattr(
            "mente.integrations.bridge.run_gateway_task",
            _fake_run_gateway_task,
        )

        result_holder = {}

        def _run_turn():
            result_holder["result"] = gateway_run._run_mente_gateway_turn(
                message="深度研究一下另一家供应商",
                context_prompt="session context",
                history=[],
                source=source,
                session_id="sess-1",
                session_key=session_key,
                cancel_event=threading.Event(),
                background_worker_started=_register_started,
                background_worker_finished=_register_finished,
            )

        thread = threading.Thread(target=_run_turn, daemon=True)
        thread.start()
        assert worker_started.wait(timeout=1.0)

        live_job = runner._get_background_worker_job(session_key, lane="research")
        assert live_job is not None
        assert live_job.status == "running"
        assert live_job.task_id == "worker-task-1"

        status_response = runner._maybe_handle_background_worker_frontdesk_message(
            _make_event("当前进度？", chat_id=source.chat_id),
            session_key=session_key,
            session_id="sess-1",
        )
        assert status_response is not None
        assert "research" in status_response.lower()

        allow_finish.set()
        thread.join(timeout=2.0)

        finished_job = runner._get_background_worker_job(session_key, lane="research")
        assert finished_job is not None
        assert finished_job.status == "completed"
        assert finished_job.summary == "Research finished"
        assert result_holder["result"]["final_response"] == "Research finished"
        assert [kind for kind, _payload in callback_events] == ["started", "finished"]

    def test_live_gateway_cancel_hits_real_worker_cancel_event(self, monkeypatch):
        runner = _make_runner()
        source = _make_source()
        session_key = build_session_key(source)
        worker_started = threading.Event()
        allow_finish = threading.Event()
        shared_cancel_event = threading.Event()

        fake_bundle = SimpleNamespace(
            worker_task=SimpleNamespace(
                task_id="worker-task-1",
                worker_lane="research",
                metadata={"lane": "research"},
            ),
            coordinator_task=SimpleNamespace(job_id="job-research-1"),
            decision=SimpleNamespace(
                dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
                target_job_lane="research",
                worker_lane="research",
                lane="director",
            ),
        )

        monkeypatch.setattr(
            "mente.integrations.bridge.build_gateway_task_bundle",
            lambda **_kwargs: fake_bundle,
        )

        def _fake_run_gateway_task(**kwargs):
            worker_started.set()
            cancel_event = kwargs["cancel_event"]
            allow_finish.wait(timeout=2.0)
            return ExecutionResult(
                status="failed",
                summary="cancelled",
                failure_reason="interrupted_by_user",
                metadata={
                    "task_id": "worker-task-1",
                    "job_id": "job-research-1",
                    "worker_lane": "research",
                    "dispatch_mode": "delegate_background",
                },
            ) if cancel_event.is_set() else ExecutionResult(status="success", summary="done")

        monkeypatch.setattr(
            "mente.integrations.bridge.run_gateway_task",
            _fake_run_gateway_task,
        )

        def _register_started(payload):
            runner._register_background_worker_job(
                session_key=session_key,
                session_id="sess-1",
                lane=str(payload["lane"]),
                job_id=str(payload["job_id"]),
                task_id=str(payload["task_id"]),
                status="running",
                cancel_event=payload.get("cancel_event"),
            )

        def _register_finished(payload):
            runner._register_background_worker_job(
                session_key=session_key,
                session_id="sess-1",
                lane=str(payload["lane"]),
                job_id=str(payload["job_id"]),
                task_id=str(payload["task_id"]),
                summary=str(payload.get("summary") or ""),
                status=str(payload.get("status") or ""),
                cancel_event=payload.get("cancel_event"),
            )

        thread = threading.Thread(
            target=lambda: gateway_run._run_mente_gateway_turn(
                message="深度研究一下另一家供应商",
                context_prompt="session context",
                history=[],
                source=source,
                session_id="sess-1",
                session_key=session_key,
                cancel_event=shared_cancel_event,
                background_worker_started=_register_started,
                background_worker_finished=_register_finished,
            ),
            daemon=True,
        )
        thread.start()
        assert worker_started.wait(timeout=1.0)

        cancel_response = runner._maybe_handle_background_worker_frontdesk_message(
            _make_event("取消", chat_id=source.chat_id),
            session_key=session_key,
            session_id="sess-1",
        )
        assert cancel_response is not None
        assert shared_cancel_event.is_set() is True

        allow_finish.set()
        thread.join(timeout=2.0)

        cancelled_job = runner._get_background_worker_job(session_key, lane="research")
        assert cancelled_job is not None
        assert cancelled_job.status == "cancelled"

    def test_same_lane_confirmation_prefers_target_job_lane(self, monkeypatch):
        runner = _make_runner()
        event = _make_event("再深度研究一下另一家供应商")
        session_key = build_session_key(event.source)

        runner._register_background_worker_job(
            session_key=session_key,
            session_id="sess-1",
            lane="research",
            job_id="job-research-1",
            task_id="task-research-1",
            summary="Collecting vendor benchmarks",
        )

        monkeypatch.setattr(
            "mente.integrations.bridge.resolve_dispatch_decision",
            lambda **_kwargs: SimpleNamespace(
                dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
                target_job_lane="research",
                worker_lane=None,
                lane="director",
            ),
        )

        response = runner._maybe_handle_background_worker_frontdesk_message(
            event,
            session_key=session_key,
            session_id="sess-1",
        )

        assert response is not None
        assert "already" in response.lower() or "先取消" in response
