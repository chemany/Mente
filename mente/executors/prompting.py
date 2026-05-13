"""Shared prompt rendering helpers for Codex-backed execution."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from mente.executors.bridge_mcp import model_visible_mcp_tool_name
from mente.task_core.models import ExecutionRequest


_USER_FACING_BRAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bI am Claude\b"),
        "I am Mente",
    ),
    (
        re.compile(r"我是 Claude"),
        "我是 Mente",
    ),
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
_CANONICAL_MENTE_MODEL_IDENTITY_SUMMARY_TEMPLATE = (
    "我是 Mente，当前接入的模型是 {model_name}。"
    "我可以通过工具帮你执行代码、操作文件、搜索信息等任务。"
)

_CHINESE_GREETING_OR_IDENTITY_REQUEST = re.compile(
    r"^\s*(?:你是谁|你是誰|介绍一下你自己|介紹一下你自己|自我介绍|自我介紹|你好|您好|嗨|哈喽|哈囉)\s*[!！?？。.\s]*$"
)
_CHINESE_MODEL_IDENTITY_REQUEST = re.compile(
    r"^\s*(?:你是什么(?:大)?模型|你是啥模型|你現在是什么模型|你现在是什么模型|你用的是什么模型|你用的什么模型)\s*[!！?？。.\s]*$"
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
    "当前运行在",
    "帮你执行代码",
    "操作文件",
    "搜索信息",
    "有什么需要帮忙的",
    "大语言模型",
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
_MENTE_WECHAT_PUBLISH_MCP_TOOL = model_visible_mcp_tool_name(
    "mente",
    "mente_wechat_publish_draft",
)
_DEEP_RESEARCH_SKILL_REF = "research/deep-research-pro"
_MENTE_CONFIG_ADMIN_SKILL_REF = "software-development/mente-config-admin"
_DIRECTOR_LANE = "director"
_ENGINEERING_LANE = "engineering"
_RESEARCH_LANE = "research"
_WRITING_LANE = "writing"
_CONFIG_ADMIN_LANE = "config_admin"


def render_execution_prompt(request: ExecutionRequest) -> str:
    """Build a stable textual prompt from an execution request."""
    if uses_thin_conversation_prompt(request):
        return _render_thin_conversation_prompt(request)

    lines = [f"Task: {request.objective}"]
    prompt_lane = _resolved_prompt_lane(request)

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
        lines.append(
            "- When the user already names a concrete file, config key, or workflow entrypoint, open that target before any repository-wide search."
        )
        lines.append(
            "- Read the referenced skill instructions before broad exploration, then execute the skill workflow as directly as possible."
        )
        lines.append(
            "- If the skill documentation names concrete scripts or commands, run the most direct workflow entrypoint first instead of manually reconstructing the workflow."
        )
        lines.append(
            "- If the skill workflow is blocked by a real gap or failure, diagnose the concrete blocker, fix the concrete blocker, and then continue the skill workflow."
        )
        lines.append(
            "- Before finalizing, self-check the referenced skill requirements for required deliverables, files, publish steps, or report formats; do not stop at an intermediate result if the skill clearly expects a completed artifact."
        )
    else:
        lines.append(
            "- If no skill refs are provided and a clearly relevant bundled skill likely exists, do at most one narrow skill check before falling back to general exploration."
        )
        lines.append(
            "- Do not scan the full skills tree unless the user explicitly asks for skill discovery."
        )
    _append_lane_execution_guidance(lines, request, prompt_lane)
    workflow_policy_lines: list[str] = []
    if _is_content_publishing_request(request):
        workflow_policy_lines.extend(
            [
                "- Use the provided publishing skill and bridge tool path directly.",
                "- Do not read large numbers of repository files, skill files, examples, or scripts unless a concrete blocker requires one targeted read.",
                f"- Draft the requested article and assets in the workspace, then call {_MENTE_WECHAT_PUBLISH_MCP_TOOL} to publish.",
                f"- For Mente-managed WeChat publishing tasks, {_MENTE_WECHAT_PUBLISH_MCP_TOOL} is the primary publish entrypoint even if the skill also contains create-article.js or publish.js.",
                "- Treat create-article.js or publish.js as optional reference helpers only; do not keep reading them repeatedly to decide the main flow.",
                "- If one targeted skill read or one targeted script help check is enough to execute, stop exploring and execute the managed flow immediately.",
                "- If key editorial details are unspecified, make reasonable defaults and continue instead of exploring broadly.",
                "- The publish bridge tool is exposed to the model as "
                f"{_MENTE_WECHAT_PUBLISH_MCP_TOOL} (server mente / tool mente_wechat_publish_draft).",
            ]
        )
    if _is_deep_research_request(request):
        workflow_policy_lines.extend(
            [
                "- Use the provided deep-research skill directly and complete the full report workflow in this turn.",
                "- Use delegate_task to launch parallel chapter workers instead of letting one agent serialize the whole report.",
                "- Recommended worker ownership groups: chapter_1 + chapter_4, chapter_2 + chapter_3, chapter_5 + chapter_6 + chapter_7.",
                "- If the skill root exposes a direct parallel report helper or CLI entrypoint, prefer running that managed workflow first instead of hand-rebuilding the 7-chapter loop.",
                "- Keep the parent agent focused on orchestration, integration, and final artifact generation after the worker outputs are available.",
                "- Avoid broad skill-tree, repository, or home-directory scans before delegating work; do at most the narrow reads needed to execute the managed workflow.",
                "- Do not stop at intermediate findings or end by asking whether the user wants the formal report.",
                "- Generate the final report artifacts in Markdown, HTML, and DOCX, then report the exact paths in the final reply.",
                "- Generate the final Markdown, HTML, and DOCX artifacts once from the merged chapter outputs; do not have each worker independently rebuild the full final report.",
                "- If one format generation step fails, fix the concrete blocker when possible and still produce the remaining artifacts instead of stopping early.",
                "- The task is complete only after the report artifacts exist and the final reply includes both the conclusion and the artifact paths.",
            ]
        )
    if _is_artifact_delivery_request(request):
        workflow_policy_lines.extend(
            [
                "- Treat this as a narrow follow-up artifact delivery request, not a new research or debugging task.",
                "- Use the provided artifact paths directly and avoid rediscovering the same report outputs.",
                "- Do not scan large parts of the repository, skills tree, or home directory unless a provided artifact path is missing.",
                "- If the user asked for Feishu/Lark delivery, upload or share the listed files immediately with the available platform flow.",
                "- The task is complete only after the requested artifact delivery is done or a concrete blocker is reported.",
            ]
        )
    if _is_config_admin_request(request):
        workflow_policy_lines.extend(
            [
                "- Resolve the active config, env, or auth path first; for Mente-managed config tasks, prefer `mente config path` and `mente config env-path` before broader searching.",
                "- When the user already named a concrete config file, key, or service action, open that target before any repository-wide search.",
                "- Read only the targeted config, env, or auth files required for the change; do not scan the repository or home directory just to rediscover the setup.",
                "- Patch only the requested keys, preserve unrelated settings, and redact secrets in user-facing confirmations.",
                "- Restart or reload the gateway only if the changed setting requires it, then report exactly what changed.",
            ]
        )
    if workflow_policy_lines:
        lines.append("Workflow Policy:")
        lines.extend(workflow_policy_lines)
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
            '- Use `artifacts_out` for generated files or published outputs, `changed_files` for touched local files, and `verification_results` for checks you actually ran.',
            '- If the requested workflow could not be fully completed, set `completion_status` to `blocked` and explain the concrete blocker in `assistant_summary` and `follow_up_tasks` instead of pretending the task is done.',
        ]
    )
    lines.append(f"User Request: {request.user_request}")

    return "\n".join(lines)


def _render_thin_conversation_prompt(request: ExecutionRequest) -> str:
    """Build a reduced prompt for non-engineering dialogue that still uses the runtime."""

    lines = [
        f"Task: {request.objective}",
        "Conversation Mode:",
        "- Reply directly to the user's latest message.",
        "- Answer directly in the user's language and keep it concise.",
        "- Do not claim prior context, actions, or preferences that are not provided.",
    ]
    if request.memory_facts:
        lines.append("Context:")
        lines.extend(f"- {item}" for item in request.memory_facts)
    lines.extend(
        [
            "Output:",
            "- Return JSON matching the required schema.",
            f"User Request: {request.user_request}",
        ]
    )
    return "\n".join(lines)


def _append_lane_execution_guidance(
    lines: list[str],
    request: ExecutionRequest,
    lane: str | None,
) -> None:
    if lane == _RESEARCH_LANE:
        lines.append("Research Mode:")
        lines.append("- Gather only the evidence needed to answer the request well.")
        lines.append(
            "- Deliver the analysis directly instead of turning it into an engineering workflow."
        )
        lines.append(
            "- If external facts or current information are required, use the minimum necessary retrieval and keep the final answer synthesized."
        )
        return
    if lane == _WRITING_LANE:
        lines.append("Writing Mode:")
        lines.append("- Produce the requested draft or rewrite directly.")
        lines.append(
            "- Prefer delivering the requested wording over engineering-style process narration."
        )
        lines.append(
            "- Keep tone, language, and structure aligned with the user's request, and only ask for clarification when a missing detail blocks delivery."
        )
        return
    if lane == _CONFIG_ADMIN_LANE:
        lines.append("Execution Modes:")
        lines.append(
            "- Deterministic task mode: when the request names a config file, key, env var, service action, or known admin workflow, go directly to that target and verify the exact change."
        )
        lines.append(
            "- Rigorous configuration mode: when the active source of truth, precedence, or restart impact is unclear, inspect the relevant loader or service path before editing."
        )
        return
    lines.append("Execution Modes:")
    lines.append(
        "- Deterministic task mode: when the request is explicit, low-ambiguity, and bounded to a named file, config key, command, or known skill workflow, do one targeted read, execute the change directly, and then run the smallest meaningful verification."
    )
    lines.append(
        "- Rigorous engineering mode: when the request changes code logic, default-value provenance, compatibility behavior, or spans multiple files, inspect the relevant implementation and affected paths before editing."
    )


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
    prompt_lane = _resolved_prompt_lane(request)
    if prompt_lane and prompt_lane != _ENGINEERING_LANE:
        return []
    if not _looks_like_project_development_request(request):
        return []
    explicit = set(explicit_skill_refs)
    return [skill for skill in _MENTE_PROJECT_SUPERPOWERS if skill not in explicit]


def uses_thin_conversation_prompt(request: ExecutionRequest) -> bool:
    """Return whether one request should use the reduced non-engineering dialogue prompt."""

    if str(request.task_type or "").strip().lower() != "conversation":
        return False
    prompt_lane = _resolved_prompt_lane(request)
    if prompt_lane and prompt_lane != _DIRECTOR_LANE:
        return False
    if _task_profile(request):
        return False
    if _normalized_skill_refs(request.skill_refs):
        return False
    if request.artifacts_in:
        return False
    if _looks_like_project_development_request(request):
        return False
    if prompt_lane == _DIRECTOR_LANE:
        return True
    user_request = str(request.user_request or "")
    return _looks_like_chinese_identity_or_greeting_request(
        user_request
    ) or _looks_like_chinese_model_identity_request(user_request)


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


def _request_lane(request: ExecutionRequest) -> str:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    lane = metadata.get("lane")
    if not isinstance(lane, str):
        return ""
    return lane.strip().lower()


def _resolved_prompt_lane(request: ExecutionRequest) -> str | None:
    lane = _request_lane(request)
    if lane in {
        _DIRECTOR_LANE,
        _ENGINEERING_LANE,
        _RESEARCH_LANE,
        _WRITING_LANE,
        _CONFIG_ADMIN_LANE,
    }:
        return lane
    task_profile = _task_profile(request)
    if task_profile == "deep_research":
        return _RESEARCH_LANE
    if task_profile == "content_publishing":
        return _WRITING_LANE
    if task_profile == "config_admin":
        return _CONFIG_ADMIN_LANE
    return None


def _is_content_publishing_request(request: ExecutionRequest) -> bool:
    if _task_profile(request) == "content_publishing":
        return True
    skill_refs = set(_normalized_skill_refs(request.skill_refs))
    return "media/wechat-publisher" in skill_refs


def _is_artifact_delivery_request(request: ExecutionRequest) -> bool:
    return _task_profile(request) == "artifact_delivery"


def _is_deep_research_request(request: ExecutionRequest) -> bool:
    if _task_profile(request) == "deep_research":
        return True
    skill_refs = set(_normalized_skill_refs(request.skill_refs))
    return _DEEP_RESEARCH_SKILL_REF in skill_refs


def _is_config_admin_request(request: ExecutionRequest) -> bool:
    if _task_profile(request) == "config_admin":
        return True
    skill_refs = set(_normalized_skill_refs(request.skill_refs))
    return _MENTE_CONFIG_ADMIN_SKILL_REF in skill_refs


def _looks_like_chinese_identity_or_greeting_request(user_request: str | None) -> bool:
    """Return True for narrow Chinese greeting/identity prompts."""
    if not user_request:
        return False
    return bool(_CHINESE_GREETING_OR_IDENTITY_REQUEST.match(user_request))


def _looks_like_chinese_model_identity_request(user_request: str | None) -> bool:
    """Return True for narrow Chinese model-identity prompts."""
    if not user_request:
        return False
    return bool(_CHINESE_MODEL_IDENTITY_REQUEST.match(user_request))


def _looks_like_chinese_self_intro(summary: str) -> bool:
    """Return True when the summary is a Chinese self-introduction blurb."""
    if not summary or not _CHINESE_SELF_INTRO_PREFIX.search(summary):
        return False
    return any(marker in summary for marker in _CHINESE_SELF_INTRO_MARKERS)


def _canonical_model_identity_summary(model_name: str | None) -> str:
    cleaned = str(model_name or "").strip()
    if not cleaned:
        return _CANONICAL_MENTE_IDENTITY_SUMMARY
    return _CANONICAL_MENTE_MODEL_IDENTITY_SUMMARY_TEMPLATE.format(model_name=cleaned)


def normalize_user_facing_summary(
    summary: str,
    *,
    user_request: str | None = None,
    model_name: str | None = None,
) -> str:
    """Rewrite leaked Codex branding back to the Mente product brand."""
    normalized = summary or ""
    for pattern, replacement in _USER_FACING_BRAND_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    if _looks_like_chinese_model_identity_request(user_request):
        stripped = normalized.lstrip()
        if (
            stripped
            and not stripped.startswith(("⚠️", "⚠", "⏳"))
            and "runtime_not_bootstrapped" not in normalized
        ):
            return _canonical_model_identity_summary(model_name)
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
    extracted_machine_message = _extract_machine_failure_message(normalized)
    if extracted_machine_message:
        if concise_reason == "任务已取消。":
            return concise_reason
        normalized = normalize_user_facing_summary(
            extracted_machine_message,
            user_request=user_request,
        ).strip()

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


def _extract_machine_failure_message(summary: str) -> str | None:
    if not _looks_like_machine_failure_dump(summary):
        return None

    last_error_message: str | None = None
    for raw_line in summary.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "error":
            message = str(payload.get("message") or "").strip()
            if message:
                last_error_message = message
            continue
        if event_type != "turn.failed":
            continue
        error_payload = payload.get("error")
        if not isinstance(error_payload, dict):
            continue
        message = str(error_payload.get("message") or "").strip()
        if message:
            return message

    return last_error_message


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
