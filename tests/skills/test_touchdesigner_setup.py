from pathlib import Path


SETUP_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "creative"
    / "touchdesigner-mcp"
    / "scripts"
    / "setup.sh"
)


def test_touchdesigner_setup_uses_mente_home_fallback():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert 'HERMES_HOME:-$HOME/.hermes' not in content
    assert "MENTE_HOME" in content
    assert ".mente" in content
