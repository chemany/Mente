from pathlib import Path

from mente.mente_inventory import (
    build_mente_inventory_context,
    build_worker_mente_inventory_payload,
    render_mente_inventory_fact,
)


def _write_skill(root: Path, ref: str, *, name: str, description: str) -> None:
    skill_dir = root / ref
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
                description,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_build_mente_inventory_context_summarizes_skills_config_automation_and_recent_artifacts(
    tmp_path, monkeypatch
):
    mente_home = tmp_path / ".mente"
    skills_root = mente_home / "skills"
    cron_dir = mente_home / "cron"
    deep_research_root = tmp_path / "deep-research"
    skills_root.mkdir(parents=True)
    cron_dir.mkdir(parents=True)
    deep_research_root.mkdir(parents=True)

    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))

    _write_skill(
        skills_root,
        "research/deep-research-pro",
        name="deep-research-pro",
        description="Generate long-form research reports.",
    )
    _write_skill(
        skills_root,
        "social-media/xhs-daily-news",
        name="xhs-daily-news",
        description="Produce and publish daily social news content.",
    )

    (mente_home / "config.yaml").write_text(
        "\n".join(
            [
                "agent:",
                "  model: gpt-5.4",
                "gateway:",
                "  platform: feishu",
                "mente:",
                "  deep_research:",
                f"    output_root: {deep_research_root}",
                "scheduler:",
                "  enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    (mente_home / ".env").write_text("OPENAI_API_KEY=redacted\n", encoding="utf-8")
    (cron_dir / "jobs.json").write_text(
        """
{
  "jobs": [
    {
      "id": "job-1",
      "name": "Daily News",
      "enabled": true,
      "schedule": "0 9 * * *"
    },
    {
      "id": "job-2",
      "name": "Weekly Research Digest",
      "enabled": false,
      "schedule": "0 8 * * 1"
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    deep_dir = deep_research_root / "report_a"
    deep_dir.mkdir()
    latest_docx = deep_dir / "report.docx"
    latest_docx.write_text("docx placeholder", encoding="utf-8")
    latest_html = deep_dir / "report.html"
    latest_html.write_text("<html></html>", encoding="utf-8")

    inventory = build_mente_inventory_context(
        referenced_skill_refs=["social-media/xhs-daily-news"],
        recent_artifact_paths=[
            "/tmp/generated/report.md",
            str(latest_docx),
        ],
    )

    assert inventory.skills.skills_root == skills_root.resolve()
    assert inventory.skills.installed_count == 2
    assert inventory.skills.referenced_refs == ("social-media/xhs-daily-news",)
    assert inventory.config.config_path == (mente_home / "config.yaml")
    assert inventory.config.env_path == (mente_home / ".env")
    assert inventory.config.top_level_keys == ("agent", "gateway", "mente", "scheduler")
    assert inventory.automation.jobs_file == (cron_dir / "jobs.json")
    assert inventory.automation.total_jobs == 2
    assert inventory.automation.enabled_jobs == 1
    assert inventory.artifacts.deep_research_output_root == deep_research_root.resolve()
    assert inventory.artifacts.recent_paths[0] == "/tmp/generated/report.md"
    assert str(latest_docx) in inventory.artifacts.recent_paths

    fact = render_mente_inventory_fact(inventory)

    assert fact is not None
    assert fact.startswith("Mente inventory:")
    assert "social-media/xhs-daily-news" in fact
    assert "config.yaml" in fact
    assert "jobs.json" in fact
    assert "Daily News" in fact
    assert "/tmp/generated/report.md" in fact
    assert str(deep_research_root) in fact


def test_build_mente_inventory_context_handles_missing_optional_sources(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))

    inventory = build_mente_inventory_context()

    assert inventory.skills.installed_count == 0
    assert inventory.skills.referenced_refs == ()
    assert inventory.config.config_exists is False
    assert inventory.automation.total_jobs == 0
    assert inventory.artifacts.recent_paths == ()

    fact = render_mente_inventory_fact(inventory)

    assert fact is not None
    assert "Installed skills: 0" in fact
    assert "Automation jobs: 0" in fact


def test_build_worker_mente_inventory_payload_includes_routing_hint(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    skills_root = mente_home / "skills" / "social-media" / "xhs-daily-news"
    cron_dir = mente_home / "cron"
    skills_root.mkdir(parents=True, exist_ok=True)
    cron_dir.mkdir(parents=True, exist_ok=True)
    (skills_root / "SKILL.md").write_text(
        "---\nname: xhs-daily-news\ndescription: Daily news skill.\n---\n",
        encoding="utf-8",
    )
    (mente_home / "config.yaml").write_text("agent:\n  model: gpt-5.4\n", encoding="utf-8")
    (cron_dir / "jobs.json").write_text('{"jobs":[{"id":"job-1","name":"Daily News","enabled":true}]}\n', encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))

    task = type(
        "TaskLike",
        (),
        {
            "role": "worker",
            "worker_lane": "engineering",
            "worker_skill_refs": ["social-media/xhs-daily-news"],
            "skill_refs": [],
            "metadata": {
                "task_profile": "self_improvement",
                "lane": "engineering",
            },
            "user_request": "修改技能和工作流",
            "objective": "Improve Mente's future behavior",
        },
    )()

    payload = build_worker_mente_inventory_payload(task)

    assert payload is not None
    fact, metadata = payload
    assert fact is not None
    assert metadata["routing_hint"]["selected_category"] == "skills"
    assert metadata["routing_hint"]["category_priority"][0]["category"] == "skills"
    assert metadata["routing_hint"]["category_priority"][0]["available"] is True
    assert metadata["routing_hint"]["category_priority"][0]["recommended_reads"]
