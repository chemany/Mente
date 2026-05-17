"""Bounded .mente inventory/context helpers for control-plane tasks."""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hermes_constants import get_mente_home, get_skills_dir
from mente.deep_research_paths import resolve_deep_research_output_root
import yaml

_DEFAULT_SKILL_LIMIT = 5
_DEFAULT_CONFIG_KEY_LIMIT = 6
_DEFAULT_JOB_LIMIT = 5
_DEFAULT_ARTIFACT_LIMIT = 5
_ARTIFACT_SUFFIXES = (".md", ".html", ".docx", ".pdf")
_CONTROL_PLANE_TASK_PROFILES = {"self_improvement", "skill_audit", "config_admin"}
_ROUTING_CATEGORIES = ("skills", "config", "automation", "artifacts")


@dataclass(frozen=True)
class SkillsInventory:
    skills_root: Path
    installed_count: int
    installed_refs: tuple[str, ...]
    referenced_refs: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "skills_root": str(self.skills_root),
            "installed_count": self.installed_count,
            "installed_refs": list(self.installed_refs),
            "referenced_refs": list(self.referenced_refs),
        }


@dataclass(frozen=True)
class ConfigInventory:
    config_path: Path
    env_path: Path
    config_exists: bool
    env_exists: bool
    top_level_keys: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "config_path": str(self.config_path),
            "env_path": str(self.env_path),
            "config_exists": self.config_exists,
            "env_exists": self.env_exists,
            "top_level_keys": list(self.top_level_keys),
        }


@dataclass(frozen=True)
class AutomationInventory:
    jobs_file: Path
    total_jobs: int
    enabled_jobs: int
    sampled_jobs: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "jobs_file": str(self.jobs_file),
            "total_jobs": self.total_jobs,
            "enabled_jobs": self.enabled_jobs,
            "sampled_jobs": list(self.sampled_jobs),
        }


@dataclass(frozen=True)
class ArtifactInventory:
    deep_research_output_root: Path
    recent_paths: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "deep_research_output_root": str(self.deep_research_output_root),
            "recent_paths": list(self.recent_paths),
        }


@dataclass(frozen=True)
class MenteInventoryContext:
    mente_home: Path
    skills: SkillsInventory
    config: ConfigInventory
    automation: AutomationInventory
    artifacts: ArtifactInventory

    def as_metadata(self) -> dict[str, object]:
        return {
            "mente_home": str(self.mente_home),
            "skills": self.skills.as_metadata(),
            "config": self.config.as_metadata(),
            "automation": self.automation.as_metadata(),
            "artifacts": self.artifacts.as_metadata(),
        }


@dataclass(frozen=True)
class _RequestLikeInventoryView:
    role: str
    worker_lane: str
    task_profile: str
    skill_refs: tuple[str, ...]


def build_worker_mente_inventory_payload(request_like: Any) -> tuple[str | None, dict[str, object]] | None:
    """Build inventory context for control-plane workers before runtime execution."""
    view = _request_like_inventory_view(request_like)
    if not _should_attach_inventory(view):
        return None
    inventory = build_mente_inventory_context(
        referenced_skill_refs=view.skill_refs,
    )
    metadata = inventory.as_metadata()
    routing_hint = build_mente_inventory_routing_hint(
        task_profile=view.task_profile,
        worker_lane=view.worker_lane,
        skill_refs=view.skill_refs,
        inventory=inventory,
    )
    if routing_hint is not None:
        metadata["routing_hint"] = routing_hint
    return render_mente_inventory_fact(inventory), metadata


def build_mente_inventory_routing_hint(
    *,
    task_profile: str | None,
    worker_lane: str | None,
    skill_refs: list[str] | tuple[str, ...] | None,
    inventory: MenteInventoryContext,
) -> dict[str, object] | None:
    """Build a compact routing hint that downstream workers can reuse."""
    normalized_task_profile = str(task_profile or "").strip().lower()
    normalized_lane = str(worker_lane or "").strip().lower()
    normalized_skill_refs = _normalize_skill_refs(skill_refs)
    category_priority = _build_routing_category_priority(
        task_profile=normalized_task_profile,
        worker_lane=normalized_lane,
        skill_refs=normalized_skill_refs,
        inventory=inventory,
    )
    if not category_priority:
        return None
    selected_category = next(
        (
            str(item["category"])
            for item in category_priority
            if bool(item.get("available"))
        ),
        str(category_priority[0]["category"]),
    )
    return {
        "selected_category": selected_category,
        "category_order": [str(item["category"]) for item in category_priority],
        "category_priority": category_priority,
        "source": {
            "task_profile": normalized_task_profile,
            "worker_lane": normalized_lane,
            "skill_refs": list(normalized_skill_refs),
        },
    }


def build_mente_inventory_context(
    *,
    referenced_skill_refs: list[str] | tuple[str, ...] | None = None,
    recent_artifact_paths: list[str] | tuple[str, ...] | None = None,
    skill_limit: int = _DEFAULT_SKILL_LIMIT,
    config_key_limit: int = _DEFAULT_CONFIG_KEY_LIMIT,
    job_limit: int = _DEFAULT_JOB_LIMIT,
    artifact_limit: int = _DEFAULT_ARTIFACT_LIMIT,
) -> MenteInventoryContext:
    """Build one compact, deterministic control-plane inventory snapshot."""
    mente_home = _resolve_path(get_mente_home())
    skills_root = _resolve_path(get_skills_dir())
    config_path = mente_home / "config.yaml"
    env_path = mente_home / ".env"
    deep_research_root = _resolve_path(resolve_deep_research_output_root())

    installed_refs = _discover_installed_skill_refs(skills_root)
    normalized_refs = _normalize_skill_refs(referenced_skill_refs)
    config_keys = _discover_config_top_level_keys(config_path, limit=config_key_limit)
    jobs = _discover_jobs(mente_home / "cron" / "jobs.json")
    recent_paths = _discover_recent_artifacts(
        explicit_paths=recent_artifact_paths,
        deep_research_root=deep_research_root,
        limit=artifact_limit,
    )

    return MenteInventoryContext(
        mente_home=mente_home,
        skills=SkillsInventory(
            skills_root=skills_root,
            installed_count=len(installed_refs),
            installed_refs=tuple(installed_refs[: max(0, skill_limit)]),
            referenced_refs=tuple(normalized_refs[: max(0, skill_limit)]),
        ),
        config=ConfigInventory(
            config_path=config_path,
            env_path=env_path,
            config_exists=config_path.exists(),
            env_exists=env_path.exists(),
            top_level_keys=tuple(config_keys),
        ),
        automation=AutomationInventory(
            jobs_file=mente_home / "cron" / "jobs.json",
            total_jobs=len(jobs),
            enabled_jobs=sum(1 for job in jobs if job.get("enabled") is not False),
            sampled_jobs=tuple(_summarize_job(job) for job in jobs[: max(0, job_limit)]),
        ),
        artifacts=ArtifactInventory(
            deep_research_output_root=deep_research_root,
            recent_paths=tuple(recent_paths[: max(0, artifact_limit)]),
        ),
    )


def render_mente_inventory_fact(inventory: MenteInventoryContext) -> str | None:
    """Render one compact memory fact for Mente control-plane context."""
    if inventory is None:
        return None
    lines = [
        "Mente inventory:",
        f"- Home: {inventory.mente_home}",
        f"- Skills root: {inventory.skills.skills_root}",
        f"- Installed skills: {inventory.skills.installed_count}",
    ]
    if inventory.skills.installed_refs:
        lines.append("- Installed skill sample: " + "; ".join(inventory.skills.installed_refs))
    if inventory.skills.referenced_refs:
        lines.append("- Referenced skills: " + "; ".join(inventory.skills.referenced_refs))
    config_state = "present" if inventory.config.config_exists else "missing"
    env_state = "present" if inventory.config.env_exists else "missing"
    lines.append(f"- Config path: {inventory.config.config_path} ({config_state})")
    if inventory.config.top_level_keys:
        lines.append("- Config sections: " + "; ".join(inventory.config.top_level_keys))
    lines.append(f"- Secrets env path: {inventory.config.env_path} ({env_state})")
    lines.append(
        f"- Automation jobs: {inventory.automation.total_jobs} total, {inventory.automation.enabled_jobs} enabled via {inventory.automation.jobs_file}"
    )
    if inventory.automation.sampled_jobs:
        lines.append("- Automation sample: " + "; ".join(inventory.automation.sampled_jobs))
    lines.append(
        f"- Deep-research output root: {inventory.artifacts.deep_research_output_root}"
    )
    if inventory.artifacts.recent_paths:
        lines.append("- Recent artifacts: " + "; ".join(inventory.artifacts.recent_paths))
    return "\n".join(lines)


def render_mente_inventory_routing_hint(routing_hint: Mapping[str, Any] | None) -> str | None:
    """Render one compact, machine-readable routing hint for prompt consumption."""
    if not isinstance(routing_hint, Mapping):
        return None
    category_priority = routing_hint.get("category_priority")
    if not isinstance(category_priority, list) or not category_priority:
        return None
    lines = ["Mente Inventory Routing Hint:"]
    selected_category = str(routing_hint.get("selected_category") or "").strip()
    if selected_category:
        lines.append(f"- Selected category: {selected_category}")
    category_order = [
        str(item.get("category") or "").strip()
        for item in category_priority
        if isinstance(item, Mapping) and str(item.get("category") or "").strip()
    ]
    if category_order:
        lines.append(f"- Category order: {', '.join(category_order)}")
    for item in category_priority:
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category") or "").strip()
        if not category:
            continue
        recommended_reads = [
            str(read).strip()
            for read in item.get("recommended_reads") or []
            if str(read).strip()
        ]
        if recommended_reads:
            lines.append(f"- Start with {category}: " + "; ".join(recommended_reads))
        else:
            lines.append(f"- Start with {category}")
    if selected_category:
        lines.append("- Use the selected category first; only switch if a concrete blocker remains.")
    return "\n".join(lines)


def should_attach_mente_inventory(request_like: Any) -> bool:
    return _should_attach_inventory(_request_like_inventory_view(request_like))


def _resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _request_like_inventory_view(request_like: Any) -> _RequestLikeInventoryView:
    metadata = getattr(request_like, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    role = str(getattr(request_like, "role", "") or metadata.get("role") or "").strip().lower()
    worker_lane = str(
        getattr(request_like, "worker_lane", "")
        or metadata.get("lane")
        or ""
    ).strip().lower()
    task_profile = str(
        metadata.get("task_profile")
        or getattr(request_like, "task_profile", "")
        or ""
    ).strip().lower()
    skill_refs = _normalize_skill_refs(
        getattr(request_like, "worker_skill_refs", None)
        or getattr(request_like, "skill_refs", None)
        or metadata.get("skill_refs")
    )
    return _RequestLikeInventoryView(
        role=role,
        worker_lane=worker_lane,
        task_profile=task_profile,
        skill_refs=tuple(skill_refs),
    )


def _build_routing_category_priority(
    *,
    task_profile: str,
    worker_lane: str,
    skill_refs: list[str],
    inventory: MenteInventoryContext,
) -> list[dict[str, object]]:
    if task_profile == "config_admin":
        ordered_categories = ("config", "skills", "automation", "artifacts")
    elif task_profile == "skill_audit":
        ordered_categories = ("skills", "config", "automation", "artifacts")
    elif task_profile == "self_improvement":
        ordered_categories = ("skills", "config", "automation", "artifacts")
    else:
        ordered_categories = _ROUTING_CATEGORIES

    if worker_lane == "config_admin" and ordered_categories[0] != "config":
        ordered_categories = (
            "config",
            *tuple(item for item in ordered_categories if item != "config"),
        )
    if (
        worker_lane == "engineering"
        and task_profile in {"", "self_improvement", "skill_audit"}
        and "skills" in ordered_categories
    ):
        ordered_categories = (
            "skills",
            *tuple(item for item in ordered_categories if item != "skills"),
        )

    category_priority: list[dict[str, object]] = []
    for category in ordered_categories:
        category_priority.append(
            {
                "category": category,
                "available": _routing_category_available(category, inventory, skill_refs),
                "recommended_reads": _routing_category_recommended_reads(category, inventory, skill_refs),
                "reason": _routing_category_reason(category, task_profile, worker_lane, skill_refs),
            }
        )
    return category_priority


def _routing_category_available(
    category: str,
    inventory: MenteInventoryContext,
    skill_refs: list[str],
) -> bool:
    if category == "skills":
        return bool(inventory.skills.installed_count or inventory.skills.referenced_refs or skill_refs)
    if category == "config":
        return bool(inventory.config.config_exists or inventory.config.env_exists)
    if category == "automation":
        return bool(inventory.automation.total_jobs or inventory.automation.enabled_jobs)
    if category == "artifacts":
        return bool(inventory.artifacts.recent_paths)
    return False


def _routing_category_recommended_reads(
    category: str,
    inventory: MenteInventoryContext,
    skill_refs: list[str],
) -> list[str]:
    if category == "skills":
        refs = list(skill_refs or inventory.skills.referenced_refs or inventory.skills.installed_refs)
        return [str(inventory.skills.skills_root / ref / "SKILL.md") for ref in refs[:3]]
    if category == "config":
        reads: list[str] = []
        if inventory.config.config_exists:
            reads.append(str(inventory.config.config_path))
        if inventory.config.env_exists:
            reads.append(str(inventory.config.env_path))
        return reads
    if category == "automation":
        return [str(inventory.automation.jobs_file)] if inventory.automation.jobs_file else []
    if category == "artifacts":
        return list(inventory.artifacts.recent_paths[:3])
    return []


def _routing_category_reason(
    category: str,
    task_profile: str,
    worker_lane: str,
    skill_refs: list[str],
) -> str:
    if category == "skills":
        if skill_refs:
            return "explicit skill refs and workflow changes point to skill files first"
        return f"task_profile={task_profile or 'unknown'}; start from the skill inventory"
    if category == "config":
        return "provider, gateway, or env behavior usually starts in config.yaml and .env"
    if category == "automation":
        return "scheduled or repeated behavior usually starts in cron jobs and scheduler state"
    if category == "artifacts":
        return "recent outputs and delivery targets explain what the previous run already produced"
    return f"worker_lane={worker_lane or 'unknown'}"


def _should_attach_inventory(view: _RequestLikeInventoryView) -> bool:
    if view.role != "worker":
        return False
    if view.worker_lane not in {"engineering", "config_admin"}:
        return False
    return view.task_profile in _CONTROL_PLANE_TASK_PROFILES


def _normalize_skill_refs(skill_refs: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for raw_ref in skill_refs or ():
        ref = str(raw_ref or "").strip().lower()
        if ref and ref not in normalized:
            normalized.append(ref)
    return normalized


def _discover_installed_skill_refs(skills_root: Path) -> list[str]:
    if not skills_root.exists():
        return []
    refs: list[str] = []
    for skill_md in sorted(skills_root.rglob("SKILL.md")):
        try:
            ref = skill_md.parent.relative_to(skills_root).as_posix().lower()
        except ValueError:
            continue
        if ref:
            refs.append(ref)
    return refs


def _discover_config_top_level_keys(config_path: Path, *, limit: int) -> list[str]:
    if not config_path.exists():
        return []
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(parsed, dict):
        return []
    keys: list[str] = []
    for key in parsed:
        text = str(key or "").strip()
        if text:
            keys.append(text)
        if len(keys) >= max(0, limit):
            break
    return keys


def _discover_jobs(jobs_file: Path) -> list[dict[str, Any]]:
    if not jobs_file.exists():
        return []
    try:
        parsed = json.loads(jobs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_jobs = parsed.get("jobs") if isinstance(parsed, dict) else []
    if not isinstance(raw_jobs, list):
        return []
    jobs: list[dict[str, Any]] = []
    for item in raw_jobs:
        if isinstance(item, dict):
            jobs.append(item)
    return jobs


def _summarize_job(job: dict[str, Any]) -> str:
    name = str(job.get("name") or job.get("id") or "unnamed").strip() or "unnamed"
    schedule = (
        str(job.get("schedule_display") or "").strip()
        or str(job.get("schedule") or "").strip()
        or "unscheduled"
    )
    return f"{name} [{schedule}]"


def _discover_recent_artifacts(
    *,
    explicit_paths: list[str] | tuple[str, ...] | None,
    deep_research_root: Path,
    limit: int,
) -> list[str]:
    recent: list[str] = []
    seen: set[str] = set()
    for raw_path in explicit_paths or ():
        normalized = _normalize_artifact_path(raw_path)
        if normalized and normalized not in seen:
            recent.append(normalized)
            seen.add(normalized)
        if len(recent) >= max(0, limit):
            return recent

    if not deep_research_root.exists():
        return recent

    candidates: list[tuple[float, str]] = []
    for path in deep_research_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _ARTIFACT_SUFFIXES:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, str(path.resolve())))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    for _, normalized in candidates:
        if normalized in seen:
            continue
        recent.append(normalized)
        seen.add(normalized)
        if len(recent) >= max(0, limit):
            break
    return recent


def _normalize_artifact_path(raw_path: Any) -> str | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    try:
        if path.exists():
            return str(path.resolve())
    except OSError:
        return text
    return text if path.is_absolute() else str(path)
