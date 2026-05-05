"""Mente-owned post-turn skill review worker."""

from __future__ import annotations

import json
import logging
import os
from difflib import unified_diff
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hermes_constants import get_mente_home, get_skills_dir
from mente.feature_flags import (
    is_skill_review_enabled,
    parse_allowed_sources,
    review_capability_gate,
)
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import TaskRepository

logger = logging.getLogger(__name__)

_FINAL_STATUSES = {"skipped", "noop", "suggested", "patched"}
_SUPPORTED_MODES = {"suggest", "patch", "create"}
_PATCH_TRUSTED_SOURCES = {"gateway"}
_PATCH_REVIEW_START = "<!-- MENTE POST-TURN REVIEW START -->"
_PATCH_REVIEW_END = "<!-- MENTE POST-TURN REVIEW END -->"
_PATCH_MAX_DIFF_LINES = 80


class SkillReviewOutcome(BaseModel):
    """Compact outcome for one post-turn skill review run."""

    status: str
    reason: str | None = None
    mode: str = "suggest"
    candidate_count: int = 0
    source_task_id: str | None = None
    source_session_id: str | None = None
    target_skill: str | None = None
    artifact_path: str | None = None
    summary: str | None = None


def build_skill_review_artifact(task: Task, result: ExecutionResult) -> dict[str, Any]:
    """Persist the minimal task/result fields needed for post-turn skill review."""

    return {
        "assistant_summary": result.summary,
        "status": result.status,
        "commands_run": list(result.commands_run),
        "skill_refs": list(task.skill_refs),
    }


class SkillReviewWorker:
    """Review persisted task artifacts and emit governed Mente skill review outputs."""

    def __init__(self, *, task_repository: TaskRepository) -> None:
        self.task_repository = task_repository

    def review_task(self, task_id: str) -> SkillReviewOutcome:
        """Review one persisted task and persist a compact skill review outcome."""

        task = self.task_repository.get(task_id)
        if task is None:
            return SkillReviewOutcome(status="skipped", reason="missing_artifact")

        existing = task.metadata.get("skill_review")
        if isinstance(existing, dict) and existing.get("status") in _FINAL_STATUSES:
            return SkillReviewOutcome.model_validate(existing)

        outcome = self._review_task(task)
        return self._persist_outcome(task, outcome)

    def _review_task(self, task: Task) -> SkillReviewOutcome:
        enabled, reason = self._review_enabled(task)
        if not enabled:
            return self._base_outcome(task, status="skipped", reason=reason or "disabled")

        artifact = task.metadata.get("skill_review_artifact")
        if not isinstance(artifact, dict):
            return self._base_outcome(task, status="skipped", reason="missing_artifact")

        mode = self._resolve_mode()
        if mode not in _SUPPORTED_MODES:
            return self._base_outcome(task, status="skipped", reason="unsupported_mode", mode="suggest")
        if mode == "create":
            return self._base_outcome(task, status="skipped", reason="create_deferred", mode=mode)

        if str(artifact.get("status") or "").strip().lower() != "success":
            return self._base_outcome(task, status="noop", mode=mode)

        targets = self._resolve_targets(task, artifact)
        if not targets:
            if mode == "patch":
                return self._base_outcome(task, status="skipped", reason="patch_not_allowed", mode=mode)
            return self._base_outcome(task, status="noop", mode=mode)

        proposal = self._build_proposal(task, artifact, targets[0])
        if proposal is None:
            if mode == "patch":
                return self._base_outcome(task, status="skipped", reason="patch_not_allowed", mode=mode)
            return self._base_outcome(task, status="noop", mode=mode)

        primary_target = proposal["target_skill"]
        artifact_path = self._persist_review_artifact(
            task,
            payload=self._build_review_payload(
                task,
                artifact=artifact,
                proposal=proposal,
                mode=mode,
                status="suggested",
                applied=False,
                summary=f"Suggested review for skill '{primary_target}'.",
            ),
        )
        if artifact_path is None:
            return self._base_outcome(
                task,
                status="skipped",
                reason="artifact_persist_failed",
                mode=mode,
            )

        if mode == "suggest":
            return self._base_outcome(
                task,
                status="suggested",
                mode=mode,
                candidate_count=1,
                target_skill=primary_target,
                artifact_path=str(artifact_path),
                summary=f"Suggested review for skill '{primary_target}'.",
            )

        if not self._patch_allowed(task, proposal):
            return self._base_outcome(task, status="skipped", reason="patch_not_allowed", mode=mode)

        if not self._apply_patch(proposal):
            return self._base_outcome(task, status="skipped", reason="patch_not_allowed", mode=mode)

        artifact_path = self._persist_review_artifact(
            task,
            payload=self._build_review_payload(
                task,
                artifact=artifact,
                proposal=proposal,
                mode=mode,
                status="patched",
                applied=True,
                summary=f"Applied trusted patch to skill '{primary_target}'.",
            ),
        )
        if artifact_path is None:
            return self._base_outcome(
                task,
                status="skipped",
                reason="artifact_persist_failed",
                mode=mode,
            )

        return self._base_outcome(
            task,
            status="patched",
            mode=mode,
            candidate_count=1,
            target_skill=primary_target,
            artifact_path=str(artifact_path),
            summary=f"Applied trusted patch to skill '{primary_target}'.",
        )

    def _review_enabled(self, task: Task) -> tuple[bool, str | None]:
        if not is_skill_review_enabled():
            return False, "disabled"

        source = str(task.metadata.get("source") or "").strip()
        if not source:
            return False, "missing_source"

        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="skill_review",
        )
        if workflow_gate is not None:
            return workflow_gate, workflow_reason

        allowed_sources = parse_allowed_sources(
            "MENTE_SKILL_REVIEW_SOURCES",
            default_sources=("gateway",),
        )
        if source not in allowed_sources:
            return False, "unsupported_source"

        if task.task_type != "conversation":
            return False, "unsupported_task_type"
        return True, None

    def _resolve_mode(self) -> str:
        return os.getenv("MENTE_SKILL_REVIEW_MODE", "suggest").strip().lower() or "suggest"

    def _resolve_targets(self, task: Task, artifact: dict[str, Any]) -> list[str]:
        raw_refs = artifact.get("skill_refs")
        if not isinstance(raw_refs, list):
            raw_refs = task.skill_refs

        resolved: list[str] = []
        seen: set[str] = set()
        for raw_ref in raw_refs:
            target = self._resolve_skill_ref(raw_ref)
            if target is None or target in seen:
                continue
            seen.add(target)
            resolved.append(target)
        return resolved

    def _build_proposal(
        self,
        task: Task,
        artifact: dict[str, Any],
        target_skill: str,
    ) -> dict[str, Any] | None:
        target_file = get_skills_dir() / target_skill / "SKILL.md"
        if not target_file.is_file():
            return None

        try:
            before_text = target_file.read_text(encoding="utf-8")
        except OSError:
            return None

        review_block = self._build_review_block(task, artifact)
        after_text = self._merge_review_block(before_text, review_block)
        diff = self._build_diff(before_text, after_text, target_file)
        if not diff:
            return None
        if len(diff.splitlines()) > _PATCH_MAX_DIFF_LINES:
            return None

        return {
            "target_skill": target_skill,
            "target_file": target_file,
            "target_file_display": str(target_file),
            "before_text": before_text,
            "after_text": after_text,
            "diff": diff,
            "review_block": review_block,
        }

    def _resolve_skill_ref(self, raw_ref: Any) -> str | None:
        if not isinstance(raw_ref, str):
            return None
        ref = raw_ref.strip()
        if not ref:
            return None

        skills_dir = get_skills_dir().resolve()
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            candidate = skills_dir / candidate

        try:
            resolved_candidate = candidate.resolve(strict=False)
        except OSError:
            return None

        skill_md = resolved_candidate
        if skill_md.name != "SKILL.md":
            skill_md = resolved_candidate / "SKILL.md"
        if not skill_md.is_file():
            return None

        try:
            skill_dir = skill_md.parent.resolve()
            relative_skill = skill_dir.relative_to(skills_dir)
        except (OSError, ValueError):
            return None
        return relative_skill.as_posix()

    def _build_review_block(self, task: Task, artifact: dict[str, Any]) -> str:
        commands = [str(item).strip() for item in artifact.get("commands_run") or [] if str(item).strip()]
        lines = [
            _PATCH_REVIEW_START,
            "## MENTE POST-TURN REVIEW",
            f"- Source task: `{task.task_id}`",
            f"- Source session: `{task.session_id}`",
            f"- Review mode: `{self._resolve_mode()}`",
            f"- Assistant summary: {str(artifact.get('assistant_summary') or '').strip() or 'N/A'}",
        ]
        if commands:
            lines.append("- Commands observed:")
            lines.extend(f"  - `{command}`" for command in commands[:5])
        lines.append("- Proposed change: capture the reusable workflow from this successful task in a bounded review block.")
        lines.append(_PATCH_REVIEW_END)
        return "\n".join(lines)

    def _merge_review_block(self, before_text: str, review_block: str) -> str:
        normalized = before_text.rstrip()
        start = normalized.find(_PATCH_REVIEW_START)
        end = normalized.find(_PATCH_REVIEW_END)
        if start != -1 and end != -1 and end >= start:
            end_index = end + len(_PATCH_REVIEW_END)
            merged = normalized[:start].rstrip()
            return f"{merged}\n\n{review_block}\n"
        if not normalized:
            return f"{review_block}\n"
        return f"{normalized}\n\n{review_block}\n"

    def _build_diff(self, before_text: str, after_text: str, target_file: Path) -> str:
        return "\n".join(
            unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=str(target_file),
                tofile=str(target_file),
                lineterm="",
            )
        )

    def _build_review_payload(
        self,
        task: Task,
        *,
        artifact: dict[str, Any],
        proposal: dict[str, Any],
        mode: str,
        status: str,
        applied: bool,
        summary: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "mode": mode,
            "source_task_id": task.task_id,
            "source_session_id": task.session_id,
            "source": str(task.metadata.get("source") or ""),
            "target_skill": proposal["target_skill"],
            "target_files": [proposal["target_file_display"]],
            "candidate_count": 1,
            "applied": applied,
            "summary": summary,
            "commands_run": list(artifact.get("commands_run") or []),
            "rollback_hint": (
                f"Restore {proposal['target_file_display']} from the recorded 'before' snapshot in this artifact."
            ),
            "proposed_changes": [
                {
                    "file": proposal["target_file_display"],
                    "change_type": "replace_review_block",
                    "diff": proposal["diff"],
                    "before": proposal["before_text"],
                    "after": proposal["after_text"],
                }
            ],
            "task_artifact": {
                "assistant_summary": artifact.get("assistant_summary"),
                "status": artifact.get("status"),
                "commands_run": list(artifact.get("commands_run") or []),
            },
        }

    def _persist_review_artifact(
        self,
        task: Task,
        *,
        payload: dict[str, Any],
    ) -> Path | None:
        artifact_path = get_mente_home() / "reviews" / "skills" / f"{task.task_id}.json"
        try:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("failed to persist skill review artifact for task %s", task.task_id)
            return None
        return artifact_path

    def _patch_allowed(self, task: Task, proposal: dict[str, Any]) -> bool:
        if os.getenv("MENTE_SKILL_REVIEW_PATCH_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            return False
        source = str(task.metadata.get("source") or "").strip()
        if source not in _PATCH_TRUSTED_SOURCES:
            return False
        target_file = proposal.get("target_file")
        if not isinstance(target_file, Path):
            return False
        skills_dir = get_skills_dir().resolve()
        try:
            resolved_target = target_file.resolve()
            resolved_target.relative_to(skills_dir)
        except (OSError, ValueError):
            return False
        if resolved_target.name != "SKILL.md":
            return False
        return True

    def _apply_patch(self, proposal: dict[str, Any]) -> bool:
        target_file = proposal.get("target_file")
        after_text = proposal.get("after_text")
        if not isinstance(target_file, Path) or not isinstance(after_text, str):
            return False
        try:
            target_file.write_text(after_text, encoding="utf-8")
        except OSError:
            logger.exception("failed to apply trusted skill review patch to %s", target_file)
            return False
        return True

    def _base_outcome(
        self,
        task: Task,
        *,
        status: str,
        reason: str | None = None,
        mode: str = "suggest",
        candidate_count: int = 0,
        target_skill: str | None = None,
        artifact_path: str | None = None,
        summary: str | None = None,
    ) -> SkillReviewOutcome:
        return SkillReviewOutcome(
            status=status,
            reason=reason,
            mode=mode,
            candidate_count=candidate_count,
            source_task_id=task.task_id,
            source_session_id=task.session_id,
            target_skill=target_skill,
            artifact_path=artifact_path,
            summary=summary,
        )

    def _persist_outcome(self, task: Task, outcome: SkillReviewOutcome) -> SkillReviewOutcome:
        try:
            task.metadata["skill_review"] = outcome.model_dump(mode="json")
            self.task_repository.save(task)
        except Exception:
            logger.exception("failed to persist skill review outcome for task %s", task.task_id)
        return outcome
