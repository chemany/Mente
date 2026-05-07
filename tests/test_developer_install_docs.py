from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_contributing_uses_mente_and_run_tests_wrapper():
    content = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert 'ln -sf "$(pwd)/venv/bin/mente" ~/.local/bin/mente' in content
    assert "mente doctor" in content
    assert 'mente chat -q "Hello"' in content
    assert "scripts/run_tests.sh" in content
    assert "venv/bin/hermes" not in content
    assert "~/.local/bin/hermes" not in content
    assert "pytest tests/ -v" not in content
