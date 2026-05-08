from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TARGET_SKILLS = (
    REPO_ROOT / "skills" / "software-development" / "brainstorming" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "using-git-worktrees" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "writing-plans" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "executing-plans" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "plan" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "test-driven-development" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "systematic-debugging" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "requesting-code-review" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "subagent-driven-development" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "verification-before-completion" / "SKILL.md",
    REPO_ROOT / "skills" / "software-development" / "finishing-a-development-branch" / "SKILL.md",
)

FORBIDDEN_SKILL_STRINGS = (
    "Hermes Agent",
    "obra/superpowers",
    "## Hermes Agent Integration",
    "> **For Hermes:**",
)


def test_mente_superpower_skill_sources_are_dehermesized():
    for path in TARGET_SKILLS:
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_SKILL_STRINGS:
            assert forbidden not in text, f"{path} still contains {forbidden!r}"
        assert ".hermes/plans/" not in text, f"{path} still contains '.hermes/plans/'"


def test_skill_doc_generator_uses_mente_branding():
    generator = REPO_ROOT / "website" / "scripts" / "generate-skill-docs.py"
    text = generator.read_text(encoding="utf-8")

    assert "This is what the Mente agent sees as instructions" in text
    assert "This is what the agent sees as instructions when the skill is active." not in text


def test_mente_plan_docs_reference_mente_execution_skills():
    plans_dir = REPO_ROOT / "docs" / "plans"
    for path in sorted(plans_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert "> **For Claude:**" not in text, f"{path} still references Claude"
        assert "superpowers:executing-plans" not in text, f"{path} still references old superpowers namespace"
