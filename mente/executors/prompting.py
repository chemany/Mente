"""Shared prompt rendering helpers for Codex-backed execution."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from mente.task_core.models import ExecutionRequest


_USER_FACING_BRAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bI am Codex\b"),
        "I am Mente",
    ),
    (
        re.compile(r"我是 Codex"),
        "我是 Mente",
    ),
    (
        re.compile(r"Codex runtime"),
        "Mente runtime",
    ),
    (
        re.compile(r"Codex 已开始执行"),
        "Mente 已开始执行",
    ),
    (
        re.compile(r"Codex 回合完成"),
        "Mente 回合完成",
    ),
    (
        re.compile(r"\bpublic codex fallback is disabled\b"),
        "public runtime fallback is disabled",
    ),
    (
        re.compile(r"\bCodex\b"),
        "Mente",
    ),
)

_CANONICAL_MENTE_IDENTITY_SUMMARY = (
    "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。"
)

_CHINESE_GREETING_OR_IDENTITY_REQUEST = re.compile(
    r"^\s*(?:你是谁|你是誰|介绍一下你自己|介紹一下你自己|自我介绍|自我介紹|你好|您好|嗨|哈喽|哈囉)\s*[!！?？。.\s]*$"
)

_CHINESE_SELF_INTRO_PREFIX = re.compile(r"^\s*(?:你好[，,。!！\s]*)?我是 Mente")

_CHINESE_SELF_INTRO_MARKERS: tuple[str, ...] = (
    "AI 助手",
    "GPT-5",
    "智能 AI 助手",
    "我可以直接帮你做这些事",
    "我可以直接帮你做这些",
    "会思考 + 动手执行",
    "一句话：我是来替你干活的",
    "这台机器上",
)

_MENTE_PROJECT_SUPERPOWERS: tuple[str, ...] = (
    "brainstorming",
    "using-git-worktrees",
    "writing-plans",
    "executing-plans",
    "test-driven-development",
    "systematic-debugging",
    "requesting-code-review",
    "verification-before-completion",
    "finishing-a-development-branch",
)

_PROJECT_DEVELOPMENT_KEYWORDS: tuple[str, ...] = (
    "engineering",
    "coding",
    "development",
    "implementation",
    "implement",
    "build feature",
    "feature",
    "refactor",
    "bugfix",
    "fix bug",
    "repository",
    "repo",
    "codebase",
    "项目",
    "开发",
    "功能",
    "代码",
    "重构",
    "修复",
    "测试",
)

_MACHINE_FAILURE_DUMP_MARKERS: tuple[str, ...] = (
    '"type":"thread.started"',
    '"type":"turn.started"',
    '"type":"turn.completed"',
    '"type":"turn.failed"',
    '"type":"error"',
    '"assistant_summary"',
    '"memory_candidates"',
)


def render_execution_prompt(request: ExecutionRequest) -> str:
    """Build a stable textual prompt from an execution request."""
    lines = [f"Task: {request.objective}"]

    if request.constraints:
        lines.append("Constraints:")
        lines.extend(f"- {item}" for item in request.constraints)
    if request.acceptance_criteria:
        lines.append("Acceptance:")
        lines.extend(f"- {item}" for item in request.acceptance_criteria)
    explicit_skill_refs = _normalized_skill_refs(request.skill_refs)
    if explicit_skill_refs:
        lines.append(f"Skills: {', '.join(explicit_skill_refs)}")
    lines.append("Skill Policy:")
    if explicit_skill_refs:
        lines.append(
            "- Use the provided skill refs first and follow their workflow; do not do broad workspace exploration before checking them."
        )
        lines.append(
            "- Do not rediscover a workflow that is already covered by the provided skill refs."
        )
    else:
        lines.append(
            "- If no skill refs are provided and a clearly relevant bundled skill likely exists, do at most one narrow skill check before falling back to general exploration."
        )
        lines.append(
            "- Do not scan the full skills tree unless the user explicitly asks for skill discovery."
        )
    if _is_content_publishing_request(request):
        lines.append("Workflow Policy:")
        lines.append("- Use the provided publishing skill and bridge tool path directly.")
        lines.append(
            "- Do not read large numbers of repository files, skill files, examples, or scripts unless a concrete blocker requires one targeted read."
        )
        lines.append(
            "- Draft the requested article and assets in the workspace, then call mente_wechat_publish_draft to publish."
        )
        lines.append(
            "- If key editorial details are unspecified, make reasonable defaults and continue instead of exploring broadly."
        )
    recommended_superpowers = _recommended_mente_superpowers(request, explicit_skill_refs)
    if recommended_superpowers:
        lines.append(f"Mente Superpowers: {', '.join(recommended_superpowers)}")
    if request.memory_facts:
        lines.append("Context:")
        lines.extend(f"- {item}" for item in request.memory_facts)
    lines.append("Memory Access:")
    if _tool_policy_has_bridge_tool(request, "mente_memory_query"):
        lines.append("- Use mente_memory_query only when prior user or project context is needed.")
    lines.append("- Do not invent prior preferences, prior decisions, or missing history.")
    lines.extend(
        [
            "Output:",
            "- Return JSON matching the required schema.",
        ]
    )
    lines.append(f"User Request: {request.user_request}")

    return "\n".join(lines)


def _normalized_skill_refs(skill_refs: object) -> list[str]:
    if not isinstance(skill_refs, (list, tuple, set)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in skill_refs:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _recommended_mente_superpowers(request: ExecutionRequest, explicit_skill_refs: list[str]) -> list[str]:
    if _is_content_publishing_request(request):
        return []
    if not _looks_like_project_development_request(request):
        return []
    explicit = set(explicit_skill_refs)
    return [skill for skill in _MENTE_PROJECT_SUPERPOWERS if skill not in explicit]


def _looks_like_project_development_request(request: ExecutionRequest) -> bool:
    haystack = " ".join(
        str(value or "").strip().lower()
        for value in (request.task_type, request.objective, request.user_request)
    )
    if not haystack:
        return False
    return any(keyword in haystack for keyword in _PROJECT_DEVELOPMENT_KEYWORDS)


def _tool_policy_has_bridge_tool(request: ExecutionRequest, tool_name: str) -> bool:
    tool_policy = request.tool_policy if isinstance(request.tool_policy, dict) else None
    if tool_policy is None:
        return False
    bridge_tools = tool_policy.get("bridge_tools")
    if not isinstance(bridge_tools, (list, tuple, set)):
        return False
    return tool_name in {
        str(item).strip()
        for item in bridge_tools
        if str(item).strip()
    }


def _task_profile(request: ExecutionRequest) -> str:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    profile = metadata.get("task_profile")
    if not isinstance(profile, str):
        return ""
    return profile.strip().lower()


def _is_content_publishing_request(request: ExecutionRequest) -> bool:
    if _task_profile(request) == "content_publishing":
        return True
    skill_refs = set(_normalized_skill_refs(request.skill_refs))
    return "media/wechat-publisher" in skill_refs


def _looks_like_chinese_identity_or_greeting_request(user_request: str | None) -> bool:
    """Return True for narrow Chinese greeting/identity prompts."""
    if not user_request:
        return False
    return bool(_CHINESE_GREETING_OR_IDENTITY_REQUEST.match(user_request))


def _looks_like_chinese_self_intro(summary: str) -> bool:
    """Return True when the summary is a Chinese self-introduction blurb."""
    if not summary or not _CHINESE_SELF_INTRO_PREFIX.search(summary):
        return False
    return any(marker in summary for marker in _CHINESE_SELF_INTRO_MARKERS)


def normalize_user_facing_summary(summary: str, *, user_request: str | None = None) -> str:
    """Rewrite leaked Codex branding back to the Mente product brand."""
    normalized = summary or ""
    for pattern, replacement in _USER_FACING_BRAND_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    if _looks_like_chinese_identity_or_greeting_request(user_request):
        stripped = normalized.lstrip()
        if (
            stripped
            and not stripped.startswith(("⚠️", "⚠", "⏳"))
            and "runtime_not_bootstrapped" not in normalized
            and _looks_like_chinese_self_intro(normalized)
        ):
            return _CANONICAL_MENTE_IDENTITY_SUMMARY
    return normalized


def normalize_user_facing_failure_summary(
    summary: str,
    *,
    failure_reason: str | None = None,
    user_request: str | None = None,
) -> str:
    """Collapse backend-heavy failures into short user-facing summaries."""

    normalized = normalize_user_facing_summary(summary, user_request=user_request).strip()
    concise_reason = _concise_failure_reason(failure_reason)

    if _looks_like_machine_failure_dump(normalized):
        return concise_reason or "任务执行失败。"
    if not normalized:
        return concise_reason or "任务执行失败。"
    if len(normalized) > 1200 and concise_reason:
        return concise_reason
    if len(normalized) > 1200:
        return normalized[:1197].rstrip() + "..."
    return normalized


def _looks_like_machine_failure_dump(summary: str) -> bool:
    if not summary:
        return False
    lowered = summary.lower()
    if len(summary) > 4000:
        return True
    return any(marker in lowered for marker in _MACHINE_FAILURE_DUMP_MARKERS)


def _concise_failure_reason(failure_reason: str | None) -> str | None:
    value = str(failure_reason or "").strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered == "interrupted_by_user":
        return "任务已取消。"
    if lowered.startswith("exit_code:"):
        return f"任务执行失败（{value}）。"
    if lowered.startswith("spawn_error:"):
        return f"任务执行失败（{value}）。"
    if lowered.startswith("runtime_not_bootstrapped:"):
        return value
    return value if len(value) <= 160 else value[:157].rstrip() + "..."


def build_prompt_fingerprint(prompt: str) -> str:
    """Return a stable fingerprint for a rendered prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def build_prompt_metrics(request: ExecutionRequest) -> dict[str, Any]:
    """Compute prompt metrics from the actual rendered prompt."""
    prompt = render_execution_prompt(request)
    return {
        "prompt_char_count": len(prompt),
        "memory_fact_count": len(request.memory_facts),
        "memory_char_count": sum(len(fact) for fact in request.memory_facts),
        "prompt_fingerprint": build_prompt_fingerprint(prompt),
    }
