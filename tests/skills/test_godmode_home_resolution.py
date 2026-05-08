import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GODMODE_SCRIPTS_DIR = REPO_ROOT / "skills" / "red-teaming" / "godmode" / "scripts"
LOAD_GODMODE_PATH = GODMODE_SCRIPTS_DIR / "load_godmode.py"
AUTO_JAILBREAK_PATH = GODMODE_SCRIPTS_DIR / "auto_jailbreak.py"
PARSELTONGUE_PATH = GODMODE_SCRIPTS_DIR / "parseltongue.py"
GODMODE_RACE_PATH = GODMODE_SCRIPTS_DIR / "godmode_race.py"


def test_load_godmode_exec_uses_mente_home_when_hermes_home_unset(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    scripts_dir = mente_home / "skills" / "red-teaming" / "godmode" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "parseltongue.py").write_text(
        "LOADED_FROM='mente'\n"
        "def generate_variants(query, tier='standard'):\n"
        "    return [LOADED_FROM, query, tier]\n",
        encoding="utf-8",
    )
    (scripts_dir / "godmode_race.py").write_text(
        "def race_models(query, tier='standard', api_key=None):\n"
        "    return {'query': query, 'tier': tier, 'api_key': api_key, 'loaded_from': 'mente'}\n",
        encoding="utf-8",
    )
    (scripts_dir / "auto_jailbreak.py").write_text(
        "def auto_jailbreak(model=None):\n"
        "    return {'model': model, 'loaded_from': 'mente'}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    exec(LOAD_GODMODE_PATH.read_text(encoding="utf-8"), namespace)

    assert namespace["generate_variants"]("q") == ["mente", "q", "standard"]
    assert namespace["race_models"]("q")["loaded_from"] == "mente"
    assert namespace["auto_jailbreak"]()["loaded_from"] == "mente"


def test_auto_jailbreak_exec_without_file_prefers_mente_home(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    exec(AUTO_JAILBREAK_PATH.read_text(encoding="utf-8"), namespace)

    assert namespace["HERMES_HOME"] == mente_home
    assert namespace["_SKILL_DIR"] == mente_home / "skills" / "red-teaming" / "godmode"


def test_parseltongue_example_no_longer_hardcodes_dot_hermes():
    content = PARSELTONGUE_PATH.read_text(encoding="utf-8")
    assert os.path.expanduser("~/.hermes") not in content
    assert "MENTE_HOME" in content or "~/.mente" in content


def test_godmode_race_example_no_longer_hardcodes_dot_hermes():
    content = GODMODE_RACE_PATH.read_text(encoding="utf-8")
    assert os.path.expanduser("~/.hermes") not in content
    assert "MENTE_HOME" in content or "~/.mente" in content
