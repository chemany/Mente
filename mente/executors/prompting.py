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


def render_execution_prompt(request: ExecutionRequest) -> str:
    """Build a stable textual prompt from an execution request."""
    lines = [
        f"Objective: {request.objective}",
        f"Task Type: {request.task_type}",
    ]

    if request.constraints:
        lines.append("Constraints:")
        lines.extend(f"- {item}" for item in request.constraints)
    if request.acceptance_criteria:
        lines.append("Acceptance Criteria:")
        lines.extend(f"- {item}" for item in request.acceptance_criteria)
    if request.memory_facts:
        lines.append("Memory Facts:")
        lines.extend(f"- {item}" for item in request.memory_facts)
    if request.skill_refs:
        lines.append("Skill References:")
        lines.extend(f"- {item}" for item in request.skill_refs)
    lines.extend(
        [
            "Response Contract:",
            "- Return a JSON object that matches the provided output schema.",
            "- assistant_summary: brief final answer for the user.",
            "- memory_candidates: durable user or task facts worth remembering later.",
            "- If no memory facts are provided, do not fabricate prior user preferences or project conventions.",
        ]
    )
    lines.append(f"User Request: {request.user_request}")

    return "\n".join(lines)


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
