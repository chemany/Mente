"""Prompt-context helpers for skill-aware worker turns."""

from __future__ import annotations

from mente.executors.runtime_config import MENTE_SELF_KNOWLEDGE
from mente.skills.catalog import load_combined_skill_catalog


def build_worker_architecture_fact() -> str:
    return "\n".join(
        [
            "Mente worker architecture context:",
            f"- {MENTE_SELF_KNOWLEDGE}",
        ]
    )


def build_relevant_skill_context_fact(
    skill_refs: list[str] | tuple[str, ...] | None,
    *,
    roots: tuple[str, ...] | None = None,
    limit: int = 3,
) -> str | None:
    normalized_refs: list[str] = []
    for raw_ref in skill_refs or ():
        ref = str(raw_ref or "").strip().lower()
        if ref and ref not in normalized_refs:
            normalized_refs.append(ref)
    if not normalized_refs:
        return None

    entries_by_ref = {
        entry.ref: entry
        for entry in load_combined_skill_catalog(roots=roots)
    }
    lines = ["Relevant skill context:"]
    for ref in normalized_refs[:limit]:
        entry = entries_by_ref.get(ref)
        if entry is None:
            lines.append(f"- {ref}: Use the referenced skill directly and inspect its SKILL.md before improvising.")
            continue
        descriptor = entry.description or entry.heading or entry.name or ref
        lines.append(f"- {ref}: {descriptor}")
    return "\n".join(lines)
