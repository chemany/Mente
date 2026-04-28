"""Tests for the Mente task debug API endpoint on the API server adapter."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import (
    APIServerAdapter,
    cors_middleware,
    security_headers_middleware,
)
from mente.task_core.models import Task, TaskStatus


def _make_adapter(api_key: str = "") -> APIServerAdapter:
    extra = {}
    if api_key:
        extra["key"] = api_key
    return APIServerAdapter(PlatformConfig(enabled=True, extra=extra))


def _create_app(adapter: APIServerAdapter) -> web.Application:
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws)
    app["api_server_adapter"] = adapter
    app.router.add_get("/api/debug/tasks", adapter._handle_debug_tasks)
    return app


@pytest.fixture
def adapter():
    return _make_adapter()


@pytest.fixture
def auth_adapter():
    return _make_adapter(api_key="sk-secret")


class TestDebugTasksAPI:
    @pytest.mark.asyncio
    async def test_debug_tasks_returns_recent_filtered_tasks(self, adapter, monkeypatch):
        class _FakeRepo:
            def __init__(self):
                self.closed = False
                self.recent_requests = []
                self.session_requests = []

            def list_recent(self, limit=20, offset=0, source=None, status=None, task_type=None):
                self.recent_requests.append((limit, offset, source, status, task_type))
                return [
                    Task(
                        task_id="mente_cron_succeeded",
                        session_id="cron-session",
                        task_type="cron",
                        objective="Nightly sync",
                        user_request="Nightly sync",
                        status=TaskStatus.SUCCEEDED,
                        metadata={"source": "cron"},
                    )
                ]

            def list_by_session(self, session_id, limit=20, offset=0, source=None, status=None, task_type=None):
                self.session_requests.append((session_id, limit, offset, source, status, task_type))
                return []

            def close(self):
                self.closed = True

        fake_repo = _FakeRepo()
        monkeypatch.setattr(
            "gateway.platforms.api_server.SQLiteTaskRepository",
            lambda: fake_repo,
            raising=False,
        )

        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get(
                "/api/debug/tasks?scope=recent&source=cron&status=succeeded&task_type=cron&limit=1"
            )

            assert resp.status == 200
            data = await resp.json()
            assert data["query"] == {
                "scope": "recent",
                "session_id": None,
                "source": "cron",
                "status": "succeeded",
                "task_type": "cron",
                "limit": 1,
                "offset": 0,
            }
            assert data["count"] == 1
            assert data["pagination"] == {
                "limit": 1,
                "offset": 0,
                "returned": 1,
                "has_more": False,
                "next_offset": None,
                "next_cursor": None,
            }
            assert data["tasks"][0]["task_id"] == "mente_cron_succeeded"
            assert data["tasks"][0]["status"] == "succeeded"
            assert data["tasks"][0]["source"] == "cron"
            assert fake_repo.recent_requests == [(2, 0, "cron", "succeeded", "cron")]
            assert fake_repo.session_requests == []
            assert fake_repo.closed is True

    @pytest.mark.asyncio
    async def test_debug_tasks_returns_session_filtered_tasks(self, adapter, monkeypatch):
        class _FakeRepo:
            def __init__(self):
                self.closed = False
                self.recent_requests = []
                self.session_requests = []

            def list_recent(self, limit=20, offset=0, source=None, status=None, task_type=None):
                self.recent_requests.append((limit, offset, source, status, task_type))
                return []

            def list_by_session(self, session_id, limit=20, offset=0, source=None, status=None, task_type=None):
                self.session_requests.append((session_id, limit, offset, source, status, task_type))
                return [
                    Task(
                        task_id="mente_session_task",
                        session_id=session_id,
                        task_type="conversation",
                        objective="Follow-up",
                        user_request="Follow-up",
                        status=TaskStatus.EXECUTING,
                        metadata={"source": "gateway"},
                    )
                ]

            def close(self):
                self.closed = True

        fake_repo = _FakeRepo()
        monkeypatch.setattr(
            "gateway.platforms.api_server.SQLiteTaskRepository",
            lambda: fake_repo,
            raising=False,
        )

        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get(
                "/api/debug/tasks?scope=session&session_id=sess-123&status=executing&task_type=conversation&limit=2"
            )

            assert resp.status == 200
            data = await resp.json()
            assert data["query"] == {
                "scope": "session",
                "session_id": "sess-123",
                "source": None,
                "status": "executing",
                "task_type": "conversation",
                "limit": 2,
                "offset": 0,
            }
            assert data["count"] == 1
            assert data["pagination"] == {
                "limit": 2,
                "offset": 0,
                "returned": 1,
                "has_more": False,
                "next_offset": None,
                "next_cursor": None,
            }
            assert data["tasks"][0]["session_id"] == "sess-123"
            assert data["tasks"][0]["source"] == "gateway"
            assert fake_repo.session_requests == [("sess-123", 3, 0, None, "executing", "conversation")]
            assert fake_repo.recent_requests == []
            assert fake_repo.closed is True

    @pytest.mark.asyncio
    async def test_debug_tasks_supports_offset_pagination_and_cursor_alias(self, adapter, monkeypatch):
        class _FakeRepo:
            def __init__(self):
                self.closed = False
                self.recent_requests = []

            def list_recent(self, limit=20, offset=0, source=None, status=None, task_type=None):
                self.recent_requests.append((limit, offset, source, status, task_type))
                return [
                    Task(
                        task_id="mente_task_2",
                        session_id="sess-2",
                        task_type="conversation",
                        objective="Task 2",
                        user_request="Task 2",
                        status=TaskStatus.EXECUTING,
                        metadata={"source": "gateway"},
                    ),
                    Task(
                        task_id="mente_task_1",
                        session_id="sess-1",
                        task_type="conversation",
                        objective="Task 1",
                        user_request="Task 1",
                        status=TaskStatus.SUCCEEDED,
                        metadata={"source": "gateway"},
                    ),
                    Task(
                        task_id="mente_task_0",
                        session_id="sess-0",
                        task_type="conversation",
                        objective="Task 0",
                        user_request="Task 0",
                        status=TaskStatus.BLOCKED,
                        metadata={"source": "gateway"},
                    ),
                ]

            def list_by_session(self, session_id, limit=20, offset=0, source=None, status=None, task_type=None):
                raise AssertionError("session query should not be used")

            def close(self):
                self.closed = True

        fake_repo = _FakeRepo()
        monkeypatch.setattr(
            "gateway.platforms.api_server.SQLiteTaskRepository",
            lambda: fake_repo,
            raising=False,
        )

        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/api/debug/tasks?scope=recent&cursor=1&limit=2")

            assert resp.status == 200
            data = await resp.json()
            assert data["query"] == {
                "scope": "recent",
                "session_id": None,
                "source": None,
                "status": None,
                "task_type": None,
                "limit": 2,
                "offset": 1,
            }
            assert data["count"] == 2
            assert data["pagination"] == {
                "limit": 2,
                "offset": 1,
                "returned": 2,
                "has_more": True,
                "next_offset": 3,
                "next_cursor": "3",
            }
            assert [task["task_id"] for task in data["tasks"]] == ["mente_task_2", "mente_task_1"]
            assert fake_repo.recent_requests == [(3, 1, None, None, None)]
            assert fake_repo.closed is True

    @pytest.mark.asyncio
    async def test_debug_tasks_rejects_invalid_status(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/api/debug/tasks?status=not-a-real-state")

            assert resp.status == 400
            data = await resp.json()
            assert "Invalid status" in data["error"]

    @pytest.mark.asyncio
    async def test_debug_tasks_requires_auth_when_api_key_configured(self, auth_adapter):
        app = _create_app(auth_adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.get("/api/debug/tasks")

            assert resp.status == 401
