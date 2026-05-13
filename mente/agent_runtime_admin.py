"""Administrative helpers for per-agent Codex runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from hermes_constants import get_mente_home
from mente.executors.runtime_config import (
    _AGENT_SOUL_FILENAME,
    _BUILTIN_AGENT_DIR,
    _agent_runtime_home,
    _ensure_mente_home_agent_registry,
)


class AgentRuntimeAdminError(ValueError):
    """Raised when an agent runtime admin action cannot be completed."""


@dataclass(frozen=True)
class ResolvedAgent:
    """Resolved agent metadata for runtime admin operations."""

    agent_id: str
    display_name: str
    runtime_home: Path


@dataclass(frozen=True)
class AgentRuntimeOverview:
    """High-level runtime state for one agent."""

    agent: ResolvedAgent
    session_count: int
    session_files: list[str]
    state_files: list[str]
    log_files: list[str]
    other_files: list[str]

    @property
    def runtime_home(self) -> Path:
        return self.agent.runtime_home


@dataclass(frozen=True)
class AgentRuntimeMutation:
    """Summary of a runtime cleanup action."""

    agent: ResolvedAgent
    runtime_home: Path
    removed_entries: list[str]

    @property
    def removed_entries_count(self) -> int:
        return len(self.removed_entries)


@dataclass(frozen=True)
class AgentInventoryEntry:
    """Combined agent metadata, soul, and runtime state for operators."""

    agent: ResolvedAgent
    agent_dir: Path
    soul_path: Path
    lanes: list[str]
    task_profiles: list[str]
    soul_text: str
    soul_excerpt: str
    runtime: AgentRuntimeOverview


def resolve_agent_reference(agent_ref: str) -> ResolvedAgent:
    """Resolve an agent id, lane, task profile, or display name."""
    mente_home = get_mente_home()
    registry = _ensure_mente_home_agent_registry(mente_home)
    normalized = _normalize_agent_ref(agent_ref)
    if not normalized:
        raise AgentRuntimeAdminError("Unknown agent: empty reference")

    agents = registry.get("agents")
    if not isinstance(agents, dict):
        agents = {}

    resolved_agent_id = _resolve_agent_id(normalized, registry)
    if not resolved_agent_id or resolved_agent_id not in agents:
        raise AgentRuntimeAdminError(
            f"Unknown agent '{agent_ref}'. Available agents: {', '.join(sorted(_known_agent_refs(registry)))}"
        )

    agent_config = agents.get(resolved_agent_id)
    display_name = resolved_agent_id
    if isinstance(agent_config, dict):
        candidate = agent_config.get("display_name")
        if isinstance(candidate, str) and candidate.strip():
            display_name = candidate.strip()

    runtime_home = _agent_runtime_home(mente_home, resolved_agent_id)
    runtime_home.mkdir(parents=True, exist_ok=True)
    return ResolvedAgent(
        agent_id=resolved_agent_id,
        display_name=display_name,
        runtime_home=runtime_home,
    )


def describe_agent_runtime(agent_ref: str, *, session_limit: int = 10) -> AgentRuntimeOverview:
    """Inspect runtime state for one resolved agent."""
    agent = resolve_agent_reference(agent_ref)
    runtime_home = agent.runtime_home
    sessions_dir = runtime_home / "sessions"

    session_paths = sorted(
        sessions_dir.rglob("*.jsonl") if sessions_dir.is_dir() else [],
        key=lambda path: path.name,
        reverse=True,
    )
    state_files = _sorted_names(runtime_home.glob("state*.sqlite*"))
    log_files = _sorted_names(runtime_home.glob("logs*.sqlite*"))

    excluded_names = {"sessions", *state_files, *log_files}
    other_files = sorted(
        entry.name
        for entry in runtime_home.iterdir()
        if entry.name not in excluded_names and entry.is_file()
    ) if runtime_home.is_dir() else []

    return AgentRuntimeOverview(
        agent=agent,
        session_count=len(session_paths),
        session_files=[path.name for path in session_paths[: max(0, session_limit)]],
        state_files=state_files,
        log_files=log_files,
        other_files=other_files,
    )


def reset_agent_execution_context(agent_ref: str) -> AgentRuntimeMutation:
    """Remove session history and sqlite execution state for one agent."""
    agent = resolve_agent_reference(agent_ref)
    runtime_home = agent.runtime_home
    removed_entries: list[str] = []

    sessions_dir = runtime_home / "sessions"
    if sessions_dir.exists():
        removed_entries.extend(_remove_path(runtime_home, sessions_dir))

    for path in sorted(runtime_home.glob("state*.sqlite*")):
        removed_entries.extend(_remove_path(runtime_home, path))
    for path in sorted(runtime_home.glob("logs*.sqlite*")):
        removed_entries.extend(_remove_path(runtime_home, path))

    runtime_home.mkdir(parents=True, exist_ok=True)
    return AgentRuntimeMutation(
        agent=agent,
        runtime_home=runtime_home,
        removed_entries=removed_entries,
    )


def clear_agent_runtime(agent_ref: str) -> AgentRuntimeMutation:
    """Delete one agent runtime's contents and recreate an empty runtime root."""
    agent = resolve_agent_reference(agent_ref)
    runtime_home = agent.runtime_home
    removed_entries: list[str] = []

    for child in sorted(runtime_home.iterdir(), key=lambda entry: entry.name):
        removed_entries.extend(_remove_path(runtime_home, child))

    runtime_home.mkdir(parents=True, exist_ok=True)
    return AgentRuntimeMutation(
        agent=agent,
        runtime_home=runtime_home,
        removed_entries=removed_entries,
    )


def list_agent_inventory(*, session_limit: int = 10) -> list[AgentInventoryEntry]:
    """Return operator-facing inventory for every registered Mente agent."""
    mente_home = get_mente_home()
    registry = _ensure_mente_home_agent_registry(mente_home)
    agents = registry.get("agents")
    if not isinstance(agents, dict):
        return []

    entries: list[AgentInventoryEntry] = []
    for agent_id in sorted(agents):
        if not isinstance(agent_id, str) or not agent_id.strip():
            continue
        entry = _build_agent_inventory_entry(
            mente_home=mente_home,
            registry=registry,
            agent_id=agent_id.strip(),
            session_limit=session_limit,
        )
        if entry is not None:
            entries.append(entry)
    return entries


def get_agent_inventory_detail(agent_ref: str, *, session_limit: int = 25) -> AgentInventoryEntry:
    """Resolve one agent reference and return its full inventory detail."""
    mente_home = get_mente_home()
    registry = _ensure_mente_home_agent_registry(mente_home)
    resolved = resolve_agent_reference(agent_ref)
    return _build_agent_inventory_entry(
        mente_home=mente_home,
        registry=registry,
        agent_id=resolved.agent_id,
        session_limit=session_limit,
    ) or AgentInventoryEntry(
        agent=resolved,
        agent_dir=mente_home / "agents" / resolved.agent_id,
        soul_path=mente_home / "agents" / resolved.agent_id / _AGENT_SOUL_FILENAME,
        lanes=[],
        task_profiles=[],
        soul_text="",
        soul_excerpt="",
        runtime=describe_agent_runtime(resolved.agent_id, session_limit=session_limit),
    )


def _build_agent_inventory_entry(
    *,
    mente_home: Path,
    registry: dict[str, object],
    agent_id: str,
    session_limit: int,
) -> AgentInventoryEntry | None:
    agents = registry.get("agents")
    if not isinstance(agents, dict):
        return None

    agent_config = agents.get(agent_id)
    if not isinstance(agent_config, dict):
        agent_config = {}

    resolved = resolve_agent_reference(agent_id)
    agent_dir = mente_home / "agents" / agent_id
    soul_path = agent_dir / _AGENT_SOUL_FILENAME
    soul_text = _load_agent_soul_text(agent_id, soul_path)

    return AgentInventoryEntry(
        agent=resolved,
        agent_dir=agent_dir,
        soul_path=soul_path,
        lanes=_string_list(agent_config.get("lanes")),
        task_profiles=_string_list(agent_config.get("task_profiles")),
        soul_text=soul_text,
        soul_excerpt=_build_soul_excerpt(soul_text),
        runtime=describe_agent_runtime(agent_id, session_limit=session_limit),
    )


def _resolve_agent_id(normalized_ref: str, registry: dict[str, object]) -> str | None:
    agents = registry.get("agents")
    if isinstance(agents, dict) and normalized_ref in agents:
        return normalized_ref

    for section_name in ("lanes", "task_profiles"):
        section = registry.get(section_name)
        if not isinstance(section, dict):
            continue
        candidate = section.get(normalized_ref)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    if isinstance(agents, dict):
        for agent_id, agent_config in agents.items():
            if not isinstance(agent_id, str):
                continue
            if _normalize_agent_ref(agent_id) == normalized_ref:
                return agent_id
            if isinstance(agent_config, dict):
                display_name = agent_config.get("display_name")
                if isinstance(display_name, str) and _normalize_agent_ref(display_name) == normalized_ref:
                    return agent_id

    return None


def _known_agent_refs(registry: dict[str, object]) -> set[str]:
    known: set[str] = set()
    for section_name in ("lanes", "task_profiles"):
        section = registry.get(section_name)
        if isinstance(section, dict):
            known.update(str(name).strip() for name in section if str(name).strip())

    agents = registry.get("agents")
    if isinstance(agents, dict):
        for agent_id, agent_config in agents.items():
            if isinstance(agent_id, str) and agent_id.strip():
                known.add(agent_id.strip())
            if isinstance(agent_config, dict):
                display_name = agent_config.get("display_name")
                if isinstance(display_name, str) and display_name.strip():
                    known.add(display_name.strip())
    return known


def _normalize_agent_ref(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _sorted_names(paths: object) -> list[str]:
    return sorted(path.name for path in paths if isinstance(path, Path))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _load_agent_soul_text(agent_id: str, soul_path: Path) -> str:
    try:
        text = soul_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        text = ""
    if text:
        return text
    try:
        return (_BUILTIN_AGENT_DIR / agent_id / _AGENT_SOUL_FILENAME).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _build_soul_excerpt(text: str, *, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _remove_path(runtime_home: Path, path: Path) -> list[str]:
    removed_entries: list[str] = []
    if path.is_dir():
        removed_entries.extend(
            str(child.relative_to(runtime_home))
            for child in sorted(path.rglob("*"), key=lambda child: len(child.parts), reverse=True)
        )
        removed_entries.append(str(path.relative_to(runtime_home)))
        shutil.rmtree(path, ignore_errors=False)
        return removed_entries

    removed_entries.append(str(path.relative_to(runtime_home)))
    path.unlink(missing_ok=True)
    return removed_entries
