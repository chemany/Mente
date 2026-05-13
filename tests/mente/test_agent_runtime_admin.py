from __future__ import annotations

from pathlib import Path

import pytest

from mente.agent_runtime_admin import (
    AgentRuntimeAdminError,
    clear_agent_runtime,
    describe_agent_runtime,
    list_agent_inventory,
    reset_agent_execution_context,
    resolve_agent_reference,
)


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_agent_reference_supports_lane_alias(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    resolved = resolve_agent_reference("director")

    assert resolved.agent_id == "executive_office"
    assert resolved.display_name == "Executive Office"
    assert resolved.runtime_home == mente_home / "runtime" / "agents" / "executive_office" / "codex"


def test_describe_agent_runtime_reports_sessions_and_state(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_home = mente_home / "runtime" / "agents" / "executive_office" / "codex"
    _write(runtime_home / "sessions" / "20260513-aaa.jsonl", "{}\n")
    _write(runtime_home / "sessions" / "20260512-bbb.jsonl", "{}\n")
    _write(runtime_home / "state.sqlite", "")
    _write(runtime_home / "logs.sqlite-wal", "")
    _write(runtime_home / "auth.json", "{}")

    overview = describe_agent_runtime("executive_office")

    assert overview.agent.agent_id == "executive_office"
    assert overview.session_count == 2
    assert overview.session_files == ["20260513-aaa.jsonl", "20260512-bbb.jsonl"]
    assert overview.state_files == ["state.sqlite"]
    assert overview.log_files == ["logs.sqlite-wal"]
    assert overview.other_files == ["auth.json"]


def test_reset_agent_execution_context_preserves_auth_and_runtime_root(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_home = mente_home / "runtime" / "agents" / "executive_office" / "codex"
    _write(runtime_home / "sessions" / "20260513-aaa.jsonl", "{}\n")
    _write(runtime_home / "state.sqlite", "")
    _write(runtime_home / "state.sqlite-shm", "")
    _write(runtime_home / "logs.sqlite", "")
    _write(runtime_home / "auth.json", "{}")

    result = reset_agent_execution_context("director")

    assert result.agent.agent_id == "executive_office"
    assert result.runtime_home == runtime_home
    assert result.removed_entries_count == 5
    assert result.runtime_home.exists() is True
    assert (runtime_home / "auth.json").is_file()
    assert not (runtime_home / "sessions").exists()
    assert not (runtime_home / "state.sqlite").exists()
    assert not (runtime_home / "logs.sqlite").exists()


def test_clear_agent_runtime_recreates_empty_runtime_root(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    runtime_home = mente_home / "runtime" / "agents" / "executive_office" / "codex"
    _write(runtime_home / "sessions" / "20260513-aaa.jsonl", "{}\n")
    _write(runtime_home / "auth.json", "{}")
    _write(runtime_home / "nested" / "artifact.txt", "hello")

    result = clear_agent_runtime("executive_office")

    assert result.agent.agent_id == "executive_office"
    assert result.runtime_home == runtime_home
    assert result.runtime_home.is_dir()
    assert list(result.runtime_home.iterdir()) == []


def test_unknown_agent_reference_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))

    with pytest.raises(AgentRuntimeAdminError, match="Unknown agent"):
        resolve_agent_reference("does-not-exist")


def test_list_agent_inventory_includes_soul_runtime_and_aliases(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    executive_dir = mente_home / "agents" / "executive_office"
    executive_dir.mkdir(parents=True, exist_ok=True)
    _write(executive_dir / "soul.md", "Executive office soul from mente home.")

    runtime_home = mente_home / "runtime" / "agents" / "executive_office" / "codex"
    _write(runtime_home / "sessions" / "20260513-aaa.jsonl", "{}\n")
    _write(runtime_home / "state.sqlite", "")
    _write(runtime_home / "auth.json", "{}")

    agents = list_agent_inventory()
    executive = next(agent for agent in agents if agent.agent.agent_id == "executive_office")

    assert executive.agent.display_name == "Executive Office"
    assert executive.lanes == ["coordinator", "director"]
    assert executive.task_profiles == []
    assert executive.soul_text == "Executive office soul from mente home."
    assert executive.soul_excerpt == "Executive office soul from mente home."
    assert executive.runtime.session_count == 1
    assert executive.runtime.state_files == ["state.sqlite"]
    assert executive.runtime.other_files == ["auth.json"]
