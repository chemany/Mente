"""Vendored execution runner for the Codex kernel slice."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from kernel.codex.bridge.entrypoints import invoke_vendored_front_door
from kernel.codex.runtime.protocol import build_structured_output_schema, parse_structured_output
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.transport import KernelTransport, KernelTransportRequest, KernelTransportResponse
from kernel.codex.sandbox.workspace import prepare_isolated_workspace
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from mente.deep_research_paths import resolve_private_runtime_write_roots
from mente.execution_events import ExecutionEventCallback, emit_execution_event


logger = logging.getLogger(__name__)


def _emit_codex_exec_jsonl_event(
    callback: ExecutionEventCallback | None,
    raw_line: str,
) -> None:
    """Translate one `codex exec --json` line into stable Mente execution events."""
    if callback is None:
        return
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return

    event_type = str(event.get("type") or "")
    if event_type == "thread.started":
        emit_execution_event(
            callback,
            "kernel.codex.thread.started",
            {"thread_id": event.get("thread_id")},
            logger=logger,
        )
        return
    if event_type == "turn.started":
        emit_execution_event(callback, "kernel.codex.turn.started", {}, logger=logger)
        return
    if event_type == "turn.completed":
        emit_execution_event(
            callback,
            "kernel.codex.turn.completed",
            {"usage": event.get("usage")},
            logger=logger,
        )
        return
    if event_type == "turn.failed":
        emit_execution_event(
            callback,
            "kernel.codex.turn.failed",
            {"error": (event.get("error") or {}).get("message")},
            logger=logger,
        )
        return
    if event_type == "error":
        emit_execution_event(
            callback,
            "kernel.codex.error",
            {"message": event.get("message")},
            logger=logger,
        )
        return
    if event_type in {"item.started", "item.updated", "item.completed"}:
        item = event.get("item")
        if isinstance(item, dict):
            _emit_codex_exec_item_event(callback, event_type.rsplit(".", 1)[1], item)


def _emit_codex_exec_item_event(
    callback: ExecutionEventCallback | None,
    phase: str,
    item: dict[str, Any],
) -> None:
    item_type = str(item.get("type") or "")
    base_payload: dict[str, Any] = {
        "item_id": item.get("id"),
        "status": item.get("status"),
    }
    if item_type == "command_execution":
        emit_execution_event(
            callback,
            f"kernel.codex.command.{phase}",
            {
                **base_payload,
                "command": item.get("command"),
                "exit_code": item.get("exit_code"),
                "aggregated_output": item.get("aggregated_output"),
            },
            logger=logger,
        )
        return
    if item_type == "mcp_tool_call":
        emit_execution_event(
            callback,
            f"kernel.codex.mcp_tool.{phase}",
            {
                **base_payload,
                "server": item.get("server"),
                "tool": item.get("tool"),
                "arguments": item.get("arguments"),
                "result": item.get("result"),
                "error": item.get("error"),
            },
            logger=logger,
        )
        return
    if item_type == "todo_list":
        items = item.get("items")
        normalized_items = items if isinstance(items, list) else []
        completed_count = sum(
            1
            for candidate in normalized_items
            if isinstance(candidate, dict) and candidate.get("completed") is True
        )
        emit_execution_event(
            callback,
            f"kernel.codex.todo.{phase}",
            {
                **base_payload,
                "items": normalized_items,
                "total_count": len(normalized_items),
                "completed_count": completed_count,
            },
            logger=logger,
        )
        return
    if item_type == "web_search":
        emit_execution_event(
            callback,
            f"kernel.codex.web_search.{phase}",
            {
                **base_payload,
                "query": item.get("query"),
                "action": item.get("action"),
            },
            logger=logger,
        )
        return
    if item_type == "file_change":
        changes = item.get("changes")
        normalized_changes = changes if isinstance(changes, list) else []
        emit_execution_event(
            callback,
            f"kernel.codex.file_change.{phase}",
            {
                **base_payload,
                "changes": normalized_changes,
                "change_count": len(normalized_changes),
            },
            logger=logger,
        )
        return
    if item_type == "collab_tool_call":
        emit_execution_event(
            callback,
            f"kernel.codex.collab_tool.{phase}",
            {
                **base_payload,
                "tool": item.get("tool"),
                "sender_thread_id": item.get("sender_thread_id"),
                "receiver_thread_ids": item.get("receiver_thread_ids"),
            },
            logger=logger,
        )
        return
    if item_type == "agent_message":
        emit_execution_event(
            callback,
            f"kernel.codex.agent_message.{phase}",
            {
                **base_payload,
                "text": item.get("text"),
            },
            logger=logger,
        )
        return
    if item_type == "reasoning":
        emit_execution_event(
            callback,
            f"kernel.codex.reasoning.{phase}",
            {
                **base_payload,
                "text": item.get("text"),
            },
            logger=logger,
        )
        return
    emit_execution_event(
        callback,
        f"kernel.codex.item.{phase}",
        {
            **base_payload,
            "item_type": item_type or "unknown",
        },
        logger=logger,
    )


def _extract_thread_id_from_jsonl(raw_output: str) -> str | None:
    """Extract the persisted thread id from `codex exec --json` output."""
    for line in raw_output.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            event = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") != "thread.started":
            continue
        thread_id = str(event.get("thread_id") or "").strip()
        if thread_id:
            return thread_id
    return None


class KernelRunner:
    """Own vendored execution orchestration for kernel-backed runs."""

    _DEFAULT_SANDBOX = "workspace-write"
    _DEFAULT_APPROVAL_POLICY = "never"

    def __init__(
        self,
        transport: KernelTransport | None = None,
        *,
        codex_binary: str | None = None,
        sandbox: str | None = None,
        approval_policy: str | None = None,
        event_callback: ExecutionEventCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.transport = transport
        self.codex_binary = codex_binary
        self.sandbox = sandbox
        self.approval_policy = approval_policy
        self.event_callback = event_callback
        self.cancel_event = cancel_event

    def run(
        self,
        *,
        payload,
        session: KernelSessionRequest,
        runtime_config: Any,
    ) -> KernelExecutionResult:
        output_path: Path | None = None
        schema_path: Path | None = None
        runtime_workdir: Path | None = None
        try:
            sandbox = self._resolve_sandbox(runtime_config)
            approval_policy = self._resolve_approval_policy(runtime_config)
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-",
                suffix=".txt",
                delete=False,
            ) as handle:
                output_path = Path(handle.name)
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-schema-",
                suffix=".json",
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(build_structured_output_schema(), handle)
                schema_path = Path(handle.name)

            runtime_workdir = prepare_isolated_workspace()
            runtime_write_roots = [
                str(path) for path in resolve_private_runtime_write_roots(payload.workspace)
            ]
            emit_execution_event(
                self.event_callback,
                "kernel.workspace_prepared",
                {"workdir": str(runtime_workdir)},
                logger=logger,
            )
            if self.transport is not None:
                emit_execution_event(
                    self.event_callback,
                    "kernel.transport_invoking",
                    {"workdir": str(runtime_workdir)},
                    logger=logger,
                )
                response = self.transport.execute(
                    KernelTransportRequest(
                        payload=payload,
                        session=session,
                        runtime_config=runtime_config,
                        sandbox=sandbox,
                        approval_policy=approval_policy,
                        cwd=payload.workspace,
                        workdir=str(runtime_workdir),
                        output_last_message=str(output_path),
                        output_schema=str(schema_path),
                        add_dirs=runtime_write_roots,
                    )
                )
                emit_execution_event(
                    self.event_callback,
                    "kernel.transport_completed",
                    {
                        "returncode": response.returncode,
                        "backend_failure": response.backend_failure,
                    },
                    logger=logger,
                )
            else:
                emit_execution_event(
                    self.event_callback,
                    "kernel.bridge_invoking",
                    {"workdir": str(runtime_workdir)},
                    logger=logger,
                )
                bridge_result = invoke_vendored_front_door(
                    payload=payload,
                    session=session,
                    runtime_config=runtime_config,
                    sandbox=sandbox,
                    approval_policy=approval_policy,
                    cwd=payload.workspace,
                    workdir=str(runtime_workdir),
                    output_last_message=str(output_path),
                    output_schema=str(schema_path),
                    add_dirs=runtime_write_roots,
                    codex_binary_override=self.codex_binary,
                    stdout_line_callback=(
                        lambda raw_line: _emit_codex_exec_jsonl_event(self.event_callback, raw_line)
                    )
                    if self.event_callback is not None
                    else None,
                    cancel_event=self.cancel_event,
                )
                emit_execution_event(
                    self.event_callback,
                    "kernel.bridge_completed",
                    {
                        "returncode": bridge_result.returncode,
                        "backend_failure": bridge_result.backend_failure,
                    },
                    logger=logger,
                )
                response = KernelTransportResponse(
                    command=list(bridge_result.command),
                    returncode=bridge_result.returncode,
                    stdout=bridge_result.stdout,
                    stderr=bridge_result.stderr,
                    raw_output=bridge_result.raw_output,
                    backend_failure=bridge_result.backend_failure,
                )
            result = self._normalize_transport_response(response)
            if (
                session.mode is KernelSessionMode.SESSION
                and session.session_id
                and not result.debug.get("thread_id")
            ):
                result.debug["thread_id"] = session.session_id
            return result
        finally:
            if output_path is not None:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
            if schema_path is not None:
                try:
                    os.unlink(schema_path)
                except FileNotFoundError:
                    pass
            if runtime_workdir is not None:
                shutil.rmtree(runtime_workdir, ignore_errors=True)

    def _resolve_sandbox(self, runtime_config: Any) -> str:
        if isinstance(self.sandbox, str) and self.sandbox.strip():
            return self.sandbox.strip()
        configured = getattr(runtime_config, "sandbox", None)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        return self._DEFAULT_SANDBOX

    def _resolve_approval_policy(self, runtime_config: Any) -> str:
        if isinstance(self.approval_policy, str) and self.approval_policy.strip():
            return self.approval_policy.strip()
        configured = getattr(runtime_config, "approval_policy", None)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        return self._DEFAULT_APPROVAL_POLICY

    def _normalize_transport_response(self, response) -> KernelExecutionResult:
        structured_output = parse_structured_output(response.raw_output)
        memory_candidates: list[str] = []
        assistant_summary = response.raw_output
        completion_status = "success"
        changed_files: list[str] = []
        artifacts_out: list[str] = []
        verification_results: list[str] = []
        follow_up_tasks: list[str] = []
        structured_payload = None
        thread_id = _extract_thread_id_from_jsonl(response.stdout or "")
        if structured_output is not None:
            structured_payload = structured_output.model_dump(mode="json")
            assistant_summary = structured_output.assistant_summary.strip()
            memory_candidates = [
                candidate.strip()
                for candidate in structured_output.memory_candidates
                if candidate.strip()
            ]
            completion_status = structured_output.completion_status
            changed_files = [item.strip() for item in structured_output.changed_files if item.strip()]
            artifacts_out = [item.strip() for item in structured_output.artifacts_out if item.strip()]
            verification_results = [
                item.strip() for item in structured_output.verification_results if item.strip()
            ]
            follow_up_tasks = [item.strip() for item in structured_output.follow_up_tasks if item.strip()]

        if not assistant_summary:
            assistant_summary = (response.stdout or response.stderr or response.backend_failure or "").strip()

        status = completion_status
        backend_failure = response.backend_failure
        if backend_failure:
            status = "failed"
        elif response.returncode not in (0, None):
            status = "failed"
            backend_failure = f"exit_code:{response.returncode}"

        debug = {
            "returncode": response.returncode,
            "stdout": response.stdout,
            "stderr": response.stderr,
            "structured_output": structured_payload,
        }
        if thread_id:
            debug["thread_id"] = thread_id

        return KernelExecutionResult(
            status=status,
            assistant_summary=assistant_summary,
            memory_candidates=memory_candidates,
            commands_run=[shlex.join(response.command)] if response.command else [],
            changed_files=changed_files,
            artifacts_out=artifacts_out,
            verification_results=verification_results,
            follow_up_tasks=follow_up_tasks,
            debug=debug,
            backend_failure=backend_failure,
        )
