from pathlib import Path

from hermes_constants import get_skills_dir
from mente.review.skill_review import SkillReviewWorker
from mente.task_core.models import Task
from mente.task_core.repository import SQLiteTaskRepository


def _build_task(*, skill_refs: list[str] | None = None, source: str = "gateway") -> Task:
    return Task(
        task_id="task_skill_review_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Implemented the requested fix.",
        skill_refs=skill_refs or [],
        metadata={
            "source": source,
            "skill_review_artifact": {
                "assistant_summary": "The task is complete and the workflow is reusable.",
                "status": "success",
            },
        },
    )


def _create_skill(root: Path, rel_path: str) -> Path:
    skill_dir = root / rel_path
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# test\n\nExisting workflow notes.\n",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_review_worker_skips_when_disabled(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    _create_skill(get_skills_dir(), "coding/python-debug")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task = _build_task(skill_refs=["coding/python-debug"])
    task_repo.save(task)
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "0")

    outcome = SkillReviewWorker(task_repository=task_repo).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "disabled",
        "mode": "suggest",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }
    stored_task = task_repo.get(task.task_id)
    assert stored_task is not None
    assert stored_task.metadata["skill_review"]["status"] == "skipped"


def test_skill_review_worker_skips_by_default_until_enabled(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    _create_skill(get_skills_dir(), "coding/python-debug")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repo.save(_build_task(skill_refs=["coding/python-debug"]))

    outcome = SkillReviewWorker(task_repository=task_repo).review_task("task_skill_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "disabled",
        "mode": "suggest",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }


def test_skill_review_worker_noops_when_no_mente_skill_target_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / "mente-home"))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task = _build_task(skill_refs=["kernel/codex/upstream/not-allowed"])
    task_repo.save(task)

    outcome = SkillReviewWorker(task_repository=task_repo).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": None,
        "mode": "suggest",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }


def test_skill_review_worker_persists_suggestion_artifact_for_mente_skill(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    _create_skill(get_skills_dir(), "coding/python-debug")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task = _build_task(skill_refs=["coding/python-debug"])
    task_repo.save(task)
    task.skill_refs = ["ignore-mutated-copy"]

    outcome = SkillReviewWorker(task_repository=task_repo).review_task(task.task_id)

    artifact_path = mente_home / "reviews" / "skills" / "task_skill_review_1.json"
    assert outcome.model_dump(mode="json") == {
        "status": "suggested",
        "reason": None,
        "mode": "suggest",
        "candidate_count": 1,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": "coding/python-debug",
        "artifact_path": str(artifact_path),
        "summary": "Suggested review for skill 'coding/python-debug'.",
    }
    assert artifact_path.is_file()
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "coding/python-debug" in artifact_text
    assert '"target_files"' in artifact_text
    assert '"proposed_changes"' in artifact_text
    assert '"diff"' in artifact_text


def test_skill_review_worker_patch_mode_fails_closed_without_trusted_gate(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    _create_skill(get_skills_dir(), "coding/python-debug")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_MODE", "patch")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repo.save(_build_task(skill_refs=["coding/python-debug"]))

    outcome = SkillReviewWorker(task_repository=task_repo).review_task("task_skill_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "patch_not_allowed",
        "mode": "patch",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }


def test_skill_review_worker_patch_mode_applies_auditable_skill_update(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    skill_dir = _create_skill(get_skills_dir(), "coding/python-debug")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_MODE", "patch")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_PATCH_ENABLED", "1")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repo.save(_build_task(skill_refs=["coding/python-debug"]))

    outcome = SkillReviewWorker(task_repository=task_repo).review_task("task_skill_review_1")

    artifact_path = mente_home / "reviews" / "skills" / "task_skill_review_1.json"
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    artifact_text = artifact_path.read_text(encoding="utf-8")

    assert outcome.model_dump(mode="json") == {
        "status": "patched",
        "reason": None,
        "mode": "patch",
        "candidate_count": 1,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": "coding/python-debug",
        "artifact_path": str(artifact_path),
        "summary": "Applied trusted patch to skill 'coding/python-debug'.",
    }
    assert "MENTE POST-TURN REVIEW" in skill_text
    assert '"applied": true' in artifact_text
    assert '"rollback_hint"' in artifact_text
    assert '"before"' in artifact_text
    assert '"after"' in artifact_text


def test_skill_review_worker_patch_mode_rejects_targets_outside_mente_skills(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_MODE", "patch")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_PATCH_ENABLED", "1")

    outside_skill = tmp_path / "outside-skill"
    outside_skill.mkdir()
    (outside_skill / "SKILL.md").write_text("# external\n", encoding="utf-8")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repo.save(_build_task(skill_refs=[str(outside_skill)]))

    outcome = SkillReviewWorker(task_repository=task_repo).review_task("task_skill_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "patch_not_allowed",
        "mode": "patch",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }


def test_skill_review_worker_create_mode_is_explicitly_deferred(monkeypatch, tmp_path):
    mente_home = tmp_path / "mente-home"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("MENTE_SKILL_REVIEW_ENABLED", "1")
    _create_skill(get_skills_dir(), "coding/python-debug")
    monkeypatch.setenv("MENTE_SKILL_REVIEW_MODE", "create")

    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    task_repo.save(_build_task(skill_refs=["coding/python-debug"]))

    outcome = SkillReviewWorker(task_repository=task_repo).review_task("task_skill_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "create_deferred",
        "mode": "create",
        "candidate_count": 0,
        "source_task_id": "task_skill_review_1",
        "source_session_id": "session_1",
        "target_skill": None,
        "artifact_path": None,
        "summary": None,
    }
