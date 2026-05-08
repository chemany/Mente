import os
import runpy
import stat
import subprocess
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DISCORD_VOICE_DOCTOR = REPO_ROOT / "scripts" / "discord-voice-doctor.py"
BUILD_SKILLS_INDEX = REPO_ROOT / "scripts" / "build_skills_index.py"
BUILD_MODEL_CATALOG = REPO_ROOT / "scripts" / "build_model_catalog.py"
PROFILE_TUI = REPO_ROOT / "scripts" / "profile-tui.py"
NODE_BOOTSTRAP = REPO_ROOT / "scripts" / "lib" / "node-bootstrap.sh"
GH_ENV = REPO_ROOT / "skills" / "github" / "github-auth" / "scripts" / "gh-env.sh"
WHATSAPP_BRIDGE = REPO_ROOT / "scripts" / "whatsapp-bridge" / "bridge.js"
HERMES_GATEWAY = REPO_ROOT / "scripts" / "hermes-gateway"
OPENCLAW_TO_HERMES = (
    REPO_ROOT
    / "optional-skills"
    / "migration"
    / "openclaw-migration"
    / "scripts"
    / "openclaw_to_hermes.py"
)
OPENCLAW_SKILL = (
    REPO_ROOT / "optional-skills" / "migration" / "openclaw-migration" / "SKILL.md"
)
GODMODE_SKILL = REPO_ROOT / "skills" / "red-teaming" / "godmode" / "SKILL.md"
GODMODE_REFUSAL_DOC = (
    REPO_ROOT / "skills" / "red-teaming" / "godmode" / "references" / "refusal-detection.md"
)
GODMODE_TEMPLATES_DOC = (
    REPO_ROOT / "skills" / "red-teaming" / "godmode" / "references" / "jailbreak-templates.md"
)
GOOGLE_WORKSPACE_SKILL = REPO_ROOT / "skills" / "productivity" / "google-workspace" / "SKILL.md"
GITHUB_AUTH_SKILL = REPO_ROOT / "skills" / "github" / "github-auth" / "SKILL.md"
TOUCHDESIGNER_SKILL = (
    REPO_ROOT / "optional-skills" / "creative" / "touchdesigner-mcp" / "SKILL.md"
)
GITHUB_API_CHEATSHEET = (
    REPO_ROOT
    / "skills"
    / "github"
    / "github-repo-management"
    / "references"
    / "github-api-cheatsheet.md"
)
GITHUB_PR_WORKFLOW_SKILL = (
    REPO_ROOT / "skills" / "github" / "github-pr-workflow" / "SKILL.md"
)
GITHUB_CODE_REVIEW_SKILL = (
    REPO_ROOT / "skills" / "github" / "github-code-review" / "SKILL.md"
)
GITHUB_ISSUES_SKILL = REPO_ROOT / "skills" / "github" / "github-issues" / "SKILL.md"
MEMENTO_FLASHCARDS_SKILL = (
    REPO_ROOT / "optional-skills" / "productivity" / "memento-flashcards" / "SKILL.md"
)
TELEPHONY_SKILL = (
    REPO_ROOT / "optional-skills" / "productivity" / "telephony" / "SKILL.md"
)


def _install_fake_skills_hub(monkeypatch):
    fake = types.ModuleType("tools.skills_hub")
    for name in (
        "GitHubAuth",
        "GitHubSource",
        "SkillsShSource",
        "OptionalSkillSource",
        "WellKnownSkillSource",
        "ClawHubSource",
        "ClaudeMarketplaceSource",
        "LobeHubSource",
        "SkillMeta",
    ):
        setattr(fake, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "tools.skills_hub", fake)


def _install_fake_models(monkeypatch):
    fake = types.ModuleType("hermes_cli.models")
    fake.OPENROUTER_MODELS = []
    fake._PROVIDER_MODELS = {}
    monkeypatch.setitem(sys.modules, "hermes_cli.models", fake)


def test_discord_voice_doctor_prefers_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    namespace = runpy.run_path(str(DISCORD_VOICE_DOCTOR), run_name="__test__")

    assert namespace["HERMES_HOME"] == mente_home
    assert namespace["ENV_FILE"] == mente_home / ".env"


def test_build_skills_index_bootstraps_hermes_home_from_mente(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    _install_fake_skills_hub(monkeypatch)

    runpy.run_path(str(BUILD_SKILLS_INDEX), run_name="__test__")

    assert os.environ["HERMES_HOME"] == str(mente_home)


def test_build_model_catalog_bootstraps_hermes_home_from_mente(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    _install_fake_models(monkeypatch)

    runpy.run_path(str(BUILD_MODEL_CATALOG), run_name="__test__")

    assert os.environ["HERMES_HOME"] == str(mente_home)


def test_profile_tui_defaults_follow_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_PERF_LOG", raising=False)

    namespace = runpy.run_path(str(PROFILE_TUI), run_name="__test__")

    assert namespace["DEFAULT_LOG"] == mente_home / "perf.log"
    assert namespace["DEFAULT_STATE_DB"] == mente_home / "state.db"


def test_node_bootstrap_prefers_mente_home_when_hermes_home_unset(tmp_path):
    mente_home = tmp_path / ".mente"
    command = (
        f'export HOME="{tmp_path}"; '
        f'export MENTE_HOME="{mente_home}"; '
        'unset HERMES_HOME; '
        f'source "{NODE_BOOTSTRAP}"; '
        'printf "%s" "$HERMES_HOME"'
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == str(mente_home)


def test_node_bootstrap_defaults_to_dot_mente_without_envs(tmp_path):
    command = (
        f'export HOME="{tmp_path}"; '
        'unset HERMES_HOME; '
        'unset MENTE_HOME; '
        f'source "{NODE_BOOTSTRAP}"; '
        'printf "%s" "$HERMES_HOME"'
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == str(tmp_path / ".mente")


def test_github_auth_helper_reads_mente_env_when_hermes_env_missing(tmp_path):
    home = tmp_path / "home"
    mente_home = home / ".mente"
    mente_home.mkdir(parents=True)
    (mente_home / ".env").write_text("GITHUB_TOKEN=mente-gh-token\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fake_gh = bin_dir / "gh"
    fake_gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)

    fake_curl = bin_dir / "curl"
    fake_curl.write_text("#!/bin/sh\nprintf '{\"login\":\"stub-user\"}'\n", encoding="utf-8")
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)

    command = (
        f'export HOME="{home}"; '
        f'export MENTE_HOME="{mente_home}"; '
        'unset HERMES_HOME; '
        'unset GITHUB_TOKEN; '
        f'export PATH="{bin_dir}:$PATH"; '
        f'source "{GH_ENV}" >/dev/null; '
        'printf "%s|%s|%s" "$GH_AUTH_METHOD" "$GITHUB_TOKEN" "$GH_USER"'
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == "curl|mente-gh-token|stub-user"


def test_whatsapp_bridge_example_no_longer_hardcodes_dot_hermes():
    content = WHATSAPP_BRIDGE.read_text(encoding="utf-8")

    assert ".hermes', 'whatsapp', 'session'" not in content
    assert "MENTE_HOME" in content or ".mente" in content


def test_hermes_gateway_launchd_logs_follow_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    namespace = runpy.run_path(str(HERMES_GATEWAY), run_name="__test__")
    plist = namespace["generate_launchd_plist"]()

    assert str(mente_home / "logs" / "gateway.log") in plist
    assert str(mente_home / "logs" / "gateway.error.log") in plist


def test_openclaw_migration_default_target_follows_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(sys, "argv", ["openclaw_to_hermes.py"])

    namespace = runpy.run_path(str(OPENCLAW_TO_HERMES), run_name="__test__")
    args = namespace["parse_args"]()

    assert args.target == str(mente_home)


def test_openclaw_skill_docs_no_longer_hardcode_dot_hermes():
    content = OPENCLAW_SKILL.read_text(encoding="utf-8")

    assert "~/.hermes/skills/migration/openclaw-migration/" not in content
    assert "~/.mente/skills/migration/openclaw-migration/" in content or "MENTE_HOME" in content


def test_godmode_docs_no_longer_hardcode_dot_hermes():
    for path in (GODMODE_SKILL, GODMODE_REFUSAL_DOC, GODMODE_TEMPLATES_DOC):
        content = path.read_text(encoding="utf-8")
        assert os.path.expanduser("~/.hermes") not in content
        assert "MENTE_HOME" in content or "~/.mente" in content


def test_google_workspace_skill_uses_mente_root_examples():
    content = GOOGLE_WORKSPACE_SKILL.read_text(encoding="utf-8")

    assert "${HERMES_HOME:-$HOME/.hermes}" not in content
    assert "~/.hermes/google_token.json" not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_github_auth_skill_examples_no_longer_assume_dot_hermes():
    content = GITHUB_AUTH_SKILL.read_text(encoding="utf-8")

    assert "[ -f ~/.hermes/.env ]" not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_touchdesigner_skill_examples_use_active_agent_root():
    content = TOUCHDESIGNER_SKILL.read_text(encoding="utf-8")

    assert "${HERMES_HOME:-$HOME/.hermes}" not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_github_api_cheatsheet_uses_mente_aware_auth_helper():
    content = GITHUB_API_CHEATSHEET.read_text(encoding="utf-8")

    assert '${HERMES_HOME:-$HOME/.hermes}' not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_github_workflow_skills_examples_no_longer_assume_dot_hermes():
    for path in (
        GITHUB_PR_WORKFLOW_SKILL,
        GITHUB_CODE_REVIEW_SKILL,
        GITHUB_ISSUES_SKILL,
    ):
        content = path.read_text(encoding="utf-8")
        assert "[ -f ~/.hermes/.env ]" not in content
        assert "~/.hermes/.env" not in content
        assert "MENTE_HOME" in content or "~/.mente" in content


def test_memento_flashcards_skill_examples_use_mente_root():
    content = MEMENTO_FLASHCARDS_SKILL.read_text(encoding="utf-8")

    assert "~/.hermes/skills/productivity/memento-flashcards/" not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_telephony_skill_examples_use_mente_root():
    content = TELEPHONY_SKILL.read_text(encoding="utf-8")

    assert "~/.hermes/.env" not in content
    assert "~/.hermes/telephony_state.json" not in content
    assert "find ~/.hermes/skills" not in content
    assert "MENTE_HOME" in content or "~/.mente" in content
