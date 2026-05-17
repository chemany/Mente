from pathlib import Path

from mente.skills import catalog


def _write_skill(
    root: Path,
    ref: str,
    *,
    name: str,
    description: str,
    tags: list[str] | None = None,
    heading: str | None = None,
) -> None:
    skill_dir = root / Path(ref)
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = [
        "---",
        f"name: {name}",
        f'description: "{description}"',
        "metadata:",
        "  hermes:",
        f"    tags: [{', '.join(tags or [])}]",
        "---",
        "",
        f"# {heading or name}",
        "",
        "Body",
    ]
    (skill_dir / "SKILL.md").write_text("\n".join(body), encoding="utf-8")


def test_load_skill_catalog_extracts_metadata_into_searchable_entry(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "research/market-brief",
        name="market-brief",
        description="Turn daily finance headlines into short market briefs.",
        tags=["finance", "news", "brief"],
        heading="Market Brief",
    )

    entries = catalog.load_skill_catalog(str(skills_root))

    assert len(entries) == 1
    entry = entries[0]
    assert entry.ref == "research/market-brief"
    assert entry.name == "market-brief"
    assert entry.heading == "Market Brief"
    assert entry.tags == ("finance", "news", "brief")
    assert "daily finance headlines" in entry.search_text


def test_match_skill_catalog_refs_returns_only_top_scoring_matches(tmp_path):
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "social-media/xhs-daily-news",
        name="xhs-daily-news",
        description="Turn daily global headlines into Xiaohongshu-ready news assets.",
        tags=["daily", "news", "xiaohongshu"],
        heading="Daily News",
    )
    _write_skill(
        skills_root,
        "research/daily-notes",
        name="daily-notes",
        description="Capture miscellaneous daily notes.",
        tags=["daily", "notes"],
        heading="Daily Notes",
    )

    matches = catalog.match_skill_catalog_refs(
        message="调用 Daily News 技能，把今天的国际要闻整理成小红书素材",
        roots=(str(skills_root),),
    )

    assert matches == ("social-media/xhs-daily-news",)


def test_skill_catalog_roots_and_combined_catalog_dedupe_refs(tmp_path):
    mente_root = tmp_path / "mente-skills"
    repo_root = tmp_path / "repo"
    workspace_root = tmp_path / "workspace"
    (repo_root / "skills").mkdir(parents=True, exist_ok=True)
    (workspace_root / "skills").mkdir(parents=True, exist_ok=True)

    _write_skill(
        mente_root,
        "custom/market-brief",
        name="market-brief",
        description="Primary skill entry.",
        tags=["finance"],
    )
    _write_skill(
        repo_root / "skills",
        "custom/market-brief",
        name="market-brief",
        description="Duplicate repo entry that should be ignored after dedupe.",
        tags=["duplicate"],
    )
    _write_skill(
        workspace_root / "skills",
        "custom/earnings-digest",
        name="earnings-digest",
        description="Workspace-local earnings digest skill.",
        tags=["earnings"],
    )

    roots = catalog.skill_catalog_roots(
        mente_skills_dir=mente_root,
        repo_root=repo_root,
        cwd=workspace_root,
    )
    entries = catalog.load_combined_skill_catalog(roots=roots)

    assert roots == (
        str(mente_root.resolve()),
        str((repo_root / "skills").resolve()),
        str((workspace_root / "skills").resolve()),
    )
    assert [entry.ref for entry in entries] == [
        "custom/market-brief",
        "custom/earnings-digest",
    ]
    assert entries[0].description == "Primary skill entry."
