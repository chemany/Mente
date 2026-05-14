"""LLM-assisted post-turn memory review worker."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from agent.auxiliary_client import call_llm
from pydantic import BaseModel, Field

from mente.feature_flags import (
    is_llm_memory_review_enabled,
    review_capability_gate,
)
from mente.memory.context import persist_memory_fact
from mente.memory.fact_normalization import normalize_memory_fact_text
from mente.memory.models import MemoryRecord
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import TaskRepository

logger = logging.getLogger(__name__)

_FIRST_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_CONFIDENCE_VALUES = {"low", "medium", "high"}
_ACCEPTED_CONFIDENCE_VALUES = {"medium", "high"}
_MAX_FACTS = 3
_MAX_PROMPT_CHARS = 5000
_LLM_MEMORY_REVIEW_TASK = "llm_memory_review"
_LLM_MEMORY_REVIEW_TIMEOUT_SECONDS = 8.0
_LLM_MEMORY_REVIEW_MAX_TOKENS = 360
_SYSTEM_PROMPT = """你是 Mente 的轻量长期记忆审查器。你只判断本轮对话结束后是否应该沉淀长期记忆。

可以写入记忆的情况：
- 用户表达了稳定偏好、长期规则、纠错、工作方式要求
- assistant/tool outcome 暴露了后续应该记住的稳定执行方式
- 事实对未来会话有复用价值，而不是一次性任务细节

不要写入记忆的情况：
- 一次性任务、普通闲聊、临时状态、纯执行日志
- 密钥、token、密码、账号凭证等敏感内容
- 没有足够证据的猜测

输出要求：
- 只输出一个 JSON object
- 字段：should_write(boolean), facts(array of string), confidence("low"|"medium"|"high"), reason(string)
- facts 最多 3 条，每条必须是简洁、可长期保存的事实
- 不要输出 markdown，不要解释
"""


class LLMMemoryReviewOutcome(BaseModel):
    """Compact outcome for one LLM memory review run."""

    status: str
    reason: str | None = None
    candidate_count: int = 0
    persisted_count: int = 0
    memory_ids: list[str] = Field(default_factory=list)
    confidence: str | None = None


def build_llm_memory_review_artifact(task: Task, result: ExecutionResult) -> dict[str, Any]:
    """Persist bounded inputs for LLM-assisted post-turn memory review."""

    return {
        "status": str(result.status or "")[:64],
        "assistant_summary": str(result.summary or "")[:1000],
        "actions_taken": _normalize_list(result.actions_taken),
        "commands_run": _normalize_list(result.commands_run),
        "tool_calls": _normalize_list(result.tool_calls),
        "artifacts_out": _normalize_list(result.artifacts_out),
        "follow_up_tasks": _normalize_list(result.follow_up_tasks),
    }


class LLMMemoryReviewWorker:
    """Review persisted task artifacts with a lightweight LLM and persist durable facts."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        memory_repository: MemoryRepository,
    ) -> None:
        self.task_repository = task_repository
        self.memory_repository = memory_repository

    def review_task(self, task_id: str) -> LLMMemoryReviewOutcome:
        task = self.task_repository.get(task_id)
        if task is None:
            return LLMMemoryReviewOutcome(status="skipped", reason="missing_artifact")

        existing = task.metadata.get("llm_memory_review")
        if isinstance(existing, dict) and existing.get("status") in {"skipped", "noop", "persisted"}:
            return LLMMemoryReviewOutcome.model_validate(existing)

        enabled, reason = self._review_enabled(task)
        if not enabled:
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(status="skipped", reason=reason or "disabled"),
            )

        artifact = task.metadata.get("llm_memory_review_artifact")
        if not isinstance(artifact, dict):
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(status="skipped", reason="missing_artifact"),
            )

        try:
            decision = self._classify(task, artifact)
        except Exception:
            logger.debug("LLM memory review failed for task %s", task.task_id, exc_info=True)
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(status="skipped", reason="classifier_failed"),
            )

        confidence = str(decision.get("confidence") or "").strip().lower()
        reason = str(decision.get("reason") or "").strip() or None
        candidates = _extract_facts_from_decision(decision)
        if not bool(decision.get("should_write")) or confidence not in _ACCEPTED_CONFIDENCE_VALUES:
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(
                    status="noop",
                    reason=reason or "model_declined",
                    candidate_count=len(candidates),
                    confidence=confidence if confidence in _CONFIDENCE_VALUES else None,
                ),
            )
        if not candidates:
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(status="noop", reason=reason, confidence=confidence),
            )

        persisted: list[MemoryRecord] = []
        duplicate_existing = False
        superseded_existing = False
        source = str(task.metadata.get("source") or "").strip()
        scope = self._target_scope(task)
        for fact in candidates:
            record, write_reason = persist_memory_fact(
                task,
                fact=fact,
                memory_repository=self.memory_repository,
                scope=scope,
                source=source,
                tool_name="mente_llm_memory_review_worker",
                write_origin="post_turn_llm_memory_review",
                memory_id=f"{task.task_id}:llm_review:{len(persisted)}",
            )
            if write_reason == "duplicate_existing":
                duplicate_existing = True
                continue
            if record is None:
                continue
            if write_reason == "superseded_existing":
                superseded_existing = True
            persisted.append(record)

        if not persisted:
            return self._persist_outcome(
                task,
                LLMMemoryReviewOutcome(
                    status="noop",
                    reason="duplicate_existing" if duplicate_existing else reason,
                    candidate_count=len(candidates),
                    confidence=confidence,
                ),
            )

        return self._persist_outcome(
            task,
            LLMMemoryReviewOutcome(
                status="persisted",
                reason="superseded_existing" if superseded_existing else reason,
                candidate_count=len(candidates),
                persisted_count=len(persisted),
                memory_ids=[record.memory_id for record in persisted],
                confidence=confidence,
            ),
        )

    def _review_enabled(self, task: Task) -> tuple[bool, str | None]:
        if not is_llm_memory_review_enabled():
            return False, "disabled"

        source = str(task.metadata.get("source") or "").strip()
        if not source:
            return False, "missing_source"
        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="llm_memory_review",
        )
        if workflow_gate is not None:
            return workflow_gate, workflow_reason
        if task.task_type != "conversation":
            return False, "unsupported_task_type"
        return True, None

    def _classify(self, task: Task, artifact: Mapping[str, Any]) -> dict[str, Any]:
        response = call_llm(
            task=_LLM_MEMORY_REVIEW_TASK,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _render_review_prompt(task, artifact)},
            ],
            temperature=0.0,
            max_tokens=_LLM_MEMORY_REVIEW_MAX_TOKENS,
            timeout=_LLM_MEMORY_REVIEW_TIMEOUT_SECONDS,
        )
        content = response.choices[0].message.content
        return _parse_decision_payload(content)

    def _target_scope(self, task: Task) -> str:
        source = str(task.metadata.get("source") or "").strip()
        if task.task_type == "conversation" and source in {"gateway", "api_server", "tui"}:
            return "session"
        return "task_type"

    def _persist_outcome(self, task: Task, outcome: LLMMemoryReviewOutcome) -> LLMMemoryReviewOutcome:
        try:
            task.metadata["llm_memory_review"] = outcome.model_dump(mode="json")
            self.task_repository.save(task)
        except Exception:
            logger.exception("failed to persist LLM memory review outcome for task %s", task.task_id)
        return outcome


def _parse_decision_payload(content: object) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"should_write": False, "facts": [], "confidence": "low", "reason": "empty_response"}
    match = _FIRST_JSON_OBJECT_PATTERN.search(text)
    if match is None:
        return {"should_write": False, "facts": [], "confidence": "low", "reason": "invalid_json"}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"should_write": False, "facts": [], "confidence": "low", "reason": "invalid_json"}
    if not isinstance(payload, dict):
        return {"should_write": False, "facts": [], "confidence": "low", "reason": "invalid_json"}
    return payload


def _extract_facts_from_decision(decision: Mapping[str, Any]) -> list[str]:
    raw_facts = decision.get("facts")
    if isinstance(raw_facts, str):
        values = [raw_facts]
    elif isinstance(raw_facts, list):
        values = raw_facts
    else:
        raw_fact = decision.get("fact")
        values = [raw_fact] if isinstance(raw_fact, str) else []

    facts: list[str] = []
    seen: set[str] = set()
    for value in values:
        fact = normalize_memory_fact_text(str(value or ""))
        if not fact or fact in seen:
            continue
        if _looks_sensitive(fact):
            continue
        seen.add(fact)
        facts.append(fact)
        if len(facts) >= _MAX_FACTS:
            break
    return facts


def _render_review_prompt(task: Task, artifact: Mapping[str, Any]) -> str:
    payload = {
        "user_request": task.user_request,
        "source": task.metadata.get("source"),
        "task_type": task.task_type,
        "assistant_summary": artifact.get("assistant_summary"),
        "status": artifact.get("status"),
        "actions_taken": artifact.get("actions_taken") or [],
        "commands_run": artifact.get("commands_run") or [],
        "tool_calls": artifact.get("tool_calls") or [],
        "artifacts_out": artifact.get("artifacts_out") or [],
        "follow_up_tasks": artifact.get("follow_up_tasks") or [],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:_MAX_PROMPT_CHARS]


def _normalize_list(items: list[Any] | tuple[Any, ...]) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        text = " ".join(str(item or "").strip().split())
        if not text:
            continue
        normalized.append(text[:240])
        if len(normalized) >= 8:
            break
    return normalized


def _looks_sensitive(fact: str) -> bool:
    lowered = fact.lower()
    return any(
        marker in lowered
        for marker in (
            "api key",
            "apikey",
            "token",
            "password",
            "passwd",
            "secret",
            "密钥",
            "密码",
            "令牌",
        )
    )
