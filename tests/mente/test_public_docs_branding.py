from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_PATHS = (
    REPO_ROOT / "website" / "docs" / "index.md",
    REPO_ROOT / "website" / "docs" / "developer-guide",
    REPO_ROOT / "website" / "docs" / "getting-started",
    REPO_ROOT / "website" / "docs" / "integrations",
    REPO_ROOT / "website" / "docs" / "guides",
    REPO_ROOT / "website" / "docs" / "reference",
    REPO_ROOT / "website" / "docs" / "user-guide",
)
EXCLUDED_PATHS = {
}
FORBIDDEN_STRINGS = (
    "Hermes Agent",
    "Hermes loads",
)
CURATED_BRANDING_SWEEPS = {
    REPO_ROOT / "website" / "docs" / "guides" / "use-mcp-with-hermes.md": ("Hermes",),
    REPO_ROOT / "website" / "docs" / "guides" / "use-voice-mode-with-hermes.md": ("Hermes",),
    REPO_ROOT / "website" / "docs" / "getting-started" / "quickstart.md": ("Hermes",),
    REPO_ROOT / "website" / "docs" / "getting-started" / "termux.md": ("Hermes",),
    REPO_ROOT / "website" / "docs" / "reference" / "tools-reference.md": ("Hermes",),
    REPO_ROOT / "website" / "docs" / "user-guide" / "messaging" / "feishu.md": ("Hermes",),
    REPO_ROOT
    / "website"
    / "docs"
    / "user-guide"
    / "skills"
    / "optional"
    / "productivity"
    / "productivity-telephony.md": ("Hermes",),
    REPO_ROOT
    / "website"
    / "docs"
    / "user-guide"
    / "skills"
    / "optional"
    / "mlops"
    / "mlops-hermes-atropos-environments.md": (
        "Hermes Atropos Environments",
        "Hermes environments are special because they run a **multi-turn agent loop with tool calling**",
    ),
    REPO_ROOT / "website" / "docs" / "index.md": (
        "extend Hermes safely",
        "Use MCP with Hermes",
        "Use Voice Mode with Hermes",
        "Hermes voice workflows",
        "Define Hermes' default voice with a global SOUL.md",
        "get the most out of Hermes",
    ),
    REPO_ROOT / "website" / "docs" / "getting-started" / "installation.md": (
        "Hermes now ships a Termux-aware installer path too:",
    ),
    REPO_ROOT / "website" / "docs" / "getting-started" / "learning-path.md": (
        "Use Voice Mode with Hermes",
        "Run Python scripts that call Hermes tools programmatically",
    ),
    REPO_ROOT / "website" / "docs" / "integrations" / "index.md": (
        "Hermes supports multiple AI inference providers out of the box.",
        "Hermes auto-detects capabilities like vision, streaming, and tool use per provider.",
        "Connect Hermes to external tool servers via Model Context Protocol.",
        "without writing native Hermes tools.",
        "Hermes includes full browser automation",
        "Expose Hermes as an OpenAI-compatible HTTP endpoint.",
        "use Hermes as a backend",
        "Hermes runs as a gateway bot on 15+ messaging platforms",
        "Extend Hermes with custom tools, lifecycle hooks, and CLI commands without modifying core code.",
        "creating Hermes plugins with tools, hooks, and CLI commands.",
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "tips.md": (
        "Want Hermes to have a stable default voice?",
        "Use SOUL.md with Hermes",
        "Hermes reads those too.",
        "Use `/background <prompt>` when you want Hermes to continue working without blocking the current conversation.",
        "Hermes checks every command against a curated list of dangerous patterns before execution.",
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "use-soul-with-hermes.md": (
        "Use SOUL.md with Hermes",
        "your Hermes instance",
        "replace the Hermes persona entirely with your own",
        "how direct or warm Hermes should be",
        "what Hermes should avoid stylistically",
        "how Hermes should relate to uncertainty, disagreement, and ambiguity",
        "who Hermes is and how Hermes speaks",
        "Hermes now uses only the global SOUL file for the current instance:",
        "If you run Hermes with a custom home directory, it becomes:",
        "Hermes automatically seeds a starter `SOUL.md` for you if one does not already exist.",
        "if you already have a `SOUL.md`, Hermes does not overwrite it",
        "if the file exists but is empty, Hermes adds nothing from it to the prompt",
        "## How Hermes uses it",
        "When Hermes starts a session",
        "If SOUL.md is missing, empty, or cannot be loaded, Hermes falls back to a built-in default identity.",
        "how Hermes feels",
        "Hermes already tries to be helpful and clear.",
        "Who Hermes is.",
        "How Hermes should sound.",
        "What Hermes should not do.",
        "How Hermes should behave when ambiguity appears.",
        "Then restart Hermes or start a new session.",
        "Talk to Hermes for a while",
        "I edited SOUL.md but Hermes still sounds the same",
        "Hermes is ignoring parts of my SOUL.md",
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "build-a-hermes-plugin.md": (
        "Build a Hermes Plugin",
        "building a complete Hermes plugin",
        "This guide walks through building a complete Hermes plugin from scratch.",
        'This tells Hermes: "I\'m a plugin called calculator, I provide tools and hooks."',
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "python-library.md": (
        "Using Hermes as a Python Library",
        "Hermes isn't just a CLI tool.",
        "using Hermes as a library",
    ),
    REPO_ROOT / "website" / "docs" / "user-guide" / "tui.md": (
        "Launch the modern terminal UI for Hermes",
        "The TUI is the modern front-end for Hermes",
        "It's the recommended way to run Hermes interactively.",
    ),
    REPO_ROOT / "website" / "docs" / "user-guide" / "messaging" / "index.md": (
        "Chat with Hermes from Telegram, Discord, Slack, WhatsApp, Signal, SMS, Email, Home Assistant, Mattermost, Matrix, DingTalk, Yuanbao, Webhooks, or any OpenAI-compatible frontend via the API server",
        "Chat with Hermes from Telegram, Discord, Slack, WhatsApp, Signal, SMS, Email, Home Assistant, Mattermost, Matrix, DingTalk, Feishu/Lark, WeCom, Weixin, BlueBubbles (iMessage), QQ, Yuanbao, or your browser.",
        "Use Voice Mode with Hermes",
    ),
    REPO_ROOT / "website" / "docs" / "user-guide" / "features" / "plugins.md": (
        "Extend Hermes with custom tools, hooks, and integrations via the plugin system",
        "Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code.",
        "Build a Hermes Plugin",
        "Start Hermes — your tools appear alongside built-in tools.",
    ),
    REPO_ROOT / "website" / "docs" / "user-guide" / "features" / "skins.md": (
        "Customize the Hermes CLI with built-in and user-defined skins",
        "Skins control the **visual presentation** of the Hermes CLI:",
        "Classic Hermes — gold and kawaii",
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "automate-with-cron.md": (
        "Real-world automation patterns using Hermes cron",
        "User-Agent\": \"Hermes-Monitor/1.0\"",
    ),
    REPO_ROOT / "website" / "docs" / "guides" / "work-with-skills.md": (
        "on-demand knowledge that teaches Hermes new workflows",
        "Skills are on-demand knowledge documents that teach Hermes how to handle specific tasks",
        "Every Hermes installation ships with bundled skills.",
    ),
    REPO_ROOT / "website" / "docs" / "reference" / "slash-commands.md": (
        ".hermes/plans/",
    ),
    REPO_ROOT / "website" / "docs" / "reference" / "skills-catalog.md": (
        ".hermes/plans/",
    ),
    REPO_ROOT / "website" / "docs" / "user-guide" / "features" / "skills.md": (
        ".hermes/plans/",
    ),
    REPO_ROOT
    / "website"
    / "docs"
    / "user-guide"
    / "skills"
    / "bundled"
    / "software-development"
    / "software-development-plan.md": (
        ".hermes/plans/",
    ),
    REPO_ROOT
    / "website"
    / "docs"
    / "user-guide"
    / "skills"
    / "bundled"
    / "research"
    / "research-research-paper-writing.md": (
        ".hermes/plans/",
    ),
}


def _iter_target_markdown_files():
    for target in TARGET_PATHS:
        if target.is_file():
            if target not in EXCLUDED_PATHS:
                yield target
            continue
        for path in sorted(target.rglob("*.md")):
            if any(excluded == path or excluded in path.parents for excluded in EXCLUDED_PATHS):
                continue
            yield path


def test_public_user_docs_use_mente_branding():
    for path in _iter_target_markdown_files():
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in text, f"{path} still contains {forbidden!r}"


def test_curated_public_docs_remove_safe_hermes_branding():
    for path, forbidden_strings in CURATED_BRANDING_SWEEPS.items():
        text = path.read_text(encoding="utf-8")
        for forbidden in forbidden_strings:
            assert forbidden not in text, f"{path} still contains {forbidden!r}"
