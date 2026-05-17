"""Directory-driven skill catalog loading and natural-language matching."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from hermes_constants import get_skills_dir
import yaml

_SKILL_CATALOG_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+")


@dataclass(frozen=True)
class SkillCatalogEntry:
    ref: str
    name: str
    description: str
    heading: str
    tags: tuple[str, ...]
    search_text: str


def extract_skill_frontmatter(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return {}
    payload = "\n".join(lines[1:closing_index]).strip()
    if not payload:
        return {}
    try:
        parsed = yaml.safe_load(payload)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_skill_heading(raw_text: str) -> str:
    for line in str(raw_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def normalize_skill_catalog_text(*parts: str) -> str:
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def tokenize_skill_catalog_text(text: str) -> list[str]:
    return _SKILL_CATALOG_TOKEN_PATTERN.findall(str(text or "").lower())


def _normalize_skill_root(candidate: str | Path, *, append_skills: bool = False) -> str | None:
    path = Path(candidate).expanduser()
    if append_skills and path.name != "skills":
        path = path / "skills"
    try:
        return str(path.resolve())
    except OSError:
        return None


def skill_catalog_roots(
    *,
    mente_skills_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    cwd: str | Path | None = None,
) -> tuple[str, ...]:
    roots: list[str] = []
    candidates = (
        _normalize_skill_root(mente_skills_dir or get_skills_dir()),
        _normalize_skill_root(repo_root or Path(__file__).resolve().parents[2], append_skills=True),
        _normalize_skill_root(cwd or Path.cwd(), append_skills=True),
    )
    for resolved in candidates:
        if resolved and resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


@lru_cache(maxsize=16)
def load_skill_catalog(skills_root: str) -> tuple[SkillCatalogEntry, ...]:
    root = Path(skills_root).expanduser()
    if not root.exists():
        return ()
    entries: list[SkillCatalogEntry] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        try:
            raw_text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        rel_dir = skill_md.parent.relative_to(root)
        skill_ref = rel_dir.as_posix().lower()
        frontmatter = extract_skill_frontmatter(raw_text)
        name = str(frontmatter.get("name") or rel_dir.name).strip()
        description = str(frontmatter.get("description") or "").strip()
        heading = extract_skill_heading(raw_text)
        metadata = frontmatter.get("metadata")
        hermes_meta = metadata.get("hermes") if isinstance(metadata, Mapping) else None
        raw_tags = hermes_meta.get("tags") if isinstance(hermes_meta, Mapping) else ()
        tags = tuple(
            str(tag).strip().lower()
            for tag in raw_tags
            if str(tag).strip()
        ) if isinstance(raw_tags, (list, tuple, set)) else ()
        search_text = normalize_skill_catalog_text(
            skill_ref.replace("/", " "),
            rel_dir.name.replace("-", " ").replace("_", " "),
            name.replace("-", " ").replace("_", " "),
            description,
            heading,
            " ".join(tags),
        )
        entries.append(
            SkillCatalogEntry(
                ref=skill_ref,
                name=name,
                description=description,
                heading=heading,
                tags=tags,
                search_text=search_text,
            )
        )
    return tuple(entries)


@lru_cache(maxsize=8)
def load_combined_skill_catalog(
    *,
    roots: tuple[str, ...] | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    combined: list[SkillCatalogEntry] = []
    seen: set[str] = set()
    effective_roots = roots or skill_catalog_roots()
    for root in effective_roots:
        for entry in load_skill_catalog(root):
            if entry.ref in seen:
                continue
            combined.append(entry)
            seen.add(entry.ref)
    return tuple(combined)


def match_skill_catalog_refs(
    *,
    message: str,
    channel_prompt: str | None = None,
    limit: int = 3,
    roots: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    haystack = normalize_skill_catalog_text(message, channel_prompt or "")
    if not haystack:
        return ()
    message_tokens = [
        token
        for token in tokenize_skill_catalog_text(haystack)
        if len(token) >= 2 and token not in {"skill", "skills"}
    ]
    if not message_tokens:
        return ()
    catalog = load_combined_skill_catalog(roots=roots)
    scored: list[tuple[int, str]] = []
    for entry in catalog:
        entry_tokens = set(tokenize_skill_catalog_text(entry.search_text))
        overlap = [token for token in message_tokens if token in entry_tokens]
        if not overlap:
            continue
        score = len(set(overlap))
        normalized_name = normalize_skill_catalog_text(entry.name.replace("-", " ").replace("_", " "))
        normalized_ref_tail = normalize_skill_catalog_text(entry.ref.split("/")[-1].replace("-", " ").replace("_", " "))
        if normalized_name and normalized_name in haystack:
            score += 6
        if normalized_ref_tail and normalized_ref_tail in haystack:
            score += 5
        if entry.description and any(token in normalize_skill_catalog_text(entry.description) for token in overlap):
            score += 1
        if score >= 2:
            scored.append((score, entry.ref))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return ()
    best_score = scored[0][0]
    seen: list[str] = []
    for score, ref in scored:
        if score != best_score:
            break
        if ref not in seen:
            seen.append(ref)
        if len(seen) >= limit:
            break
    return tuple(seen)


def clear_skill_catalog_caches() -> None:
    load_skill_catalog.cache_clear()
    load_combined_skill_catalog.cache_clear()
