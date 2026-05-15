"""Thin Mente task bridge helpers."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import threading
import uuid
from typing import Any

from pydantic import ValidationError
from hermes_constants import get_mente_home, get_skills_dir
import yaml

from agent.auxiliary_client import call_llm
from mente.execution_events import ExecutionEventCallback
from mente.context_builder.builder import ContextBuilder
from mente.deep_research_paths import resolve_deep_research_output_root
from mente.executors.bridge_mcp import model_visible_mcp_tool_name, publish_wechat_draft
from mente.executors import CodexKernelAdapter, resolve_tool_exposure_policy
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.executors.prompting import (
    _CANONICAL_MENTE_IDENTITY_SUMMARY,
    _canonical_model_identity_summary,
    _looks_like_chinese_identity_or_greeting_request,
    _looks_like_chinese_model_identity_request,
)
from mente.executors.runtime_config import RuntimeConfig, resolve_runtime_config
from mente.feature_flags import (
    build_api_server_conversation_workflow_contract,
    build_conversation_workflow_contract,
    is_remember_intent_direct_write_enabled,
    review_capability_gate,
)
from mente.memory.context import persist_explicit_memory_write
from mente.memory.fact_normalization import normalize_memory_fact_text
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import SQLiteMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.review.llm_memory_review import LLMMemoryReviewWorker
from mente.review.memory_review import MemoryReviewWorker, build_memory_review_artifact
from mente.review.remember_intent import extract_explicit_remember_intent_facts
from mente.review.session_synthesis import SessionSynthesisWorker, build_session_synthesis_artifact
from mente.review.skill_review import SkillReviewWorker
from mente.task_core.models import (
    DispatchMode,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    Task,
    TaskRole,
    TaskStatus,
)
from mente.task_core.repository import SQLiteTaskRepository

logger = logging.getLogger(__name__)

_WECHAT_PUBLISHER_SKILL_REF = "media/wechat-publisher"
_IMAGEGEN_SKILL_REF = "imagegen"
_DEEP_RESEARCH_SKILL_REF = "research/deep-research-pro"
_MENTE_CONFIG_ADMIN_SKILL_REF = "software-development/mente-config-admin"
DIRECTOR_LANE = "director"
ENGINEERING_LANE = "engineering"
RESEARCH_LANE = "research"
WRITING_LANE = "writing"
CONFIG_ADMIN_LANE = "config_admin"
_KNOWN_LANES = frozenset(
    {
        DIRECTOR_LANE,
        ENGINEERING_LANE,
        RESEARCH_LANE,
        WRITING_LANE,
        CONFIG_ADMIN_LANE,
    }
)
_CONTENT_PUBLISHING_TASK_PROFILE = "content_publishing"
_DEEP_RESEARCH_TASK_PROFILE = "deep_research"
_ARTIFACT_DELIVERY_TASK_PROFILE = "artifact_delivery"
_CONFIG_ADMIN_TASK_PROFILE = "config_admin"
_ARTIFACT_DELIVERY_HOST_TIMEOUT_SECONDS = 180.0
_DEEP_RESEARCH_NOTIFY_INTERVAL_SECONDS = 60.0
_STATUS_FOLLOW_UP_HINTS: tuple[str, ...] = (
    "当前进度",
    "现在进度",
    "进度如何",
    "进展如何",
    "做到哪了",
    "做到了哪",
    "刚才在做什么",
    "目前在做什么",
    "目前情况",
    "现在情况",
    "status",
    "progress",
)
_WECHAT_PUBLISH_HINTS: tuple[str, ...] = (
    "wechat",
    "微信",
    "公众号",
    "草稿",
)
_IMAGEGEN_HINTS: tuple[str, ...] = (
    "配图",
    "插图",
    "封面",
    "海报",
    "图片",
    "image",
)
_DEEP_RESEARCH_HINTS: tuple[str, ...] = (
    "深度研究",
    "深度调研",
    "deep research",
    "deep-research",
)
_CONFIG_ADMIN_ACTION_HINTS: tuple[str, ...] = (
    "改",
    "修改",
    "设置",
    "切换",
    "更新",
    "重启",
    "restart",
    "login",
    "logout",
    "rotate",
    "clear",
    "remove",
)
_CONFIG_ADMIN_TARGET_HINTS: tuple[str, ...] = (
    "config.yaml",
    ".env",
    "api key",
    "apikey",
    "token",
    "oauth",
    "auth.json",
    "gateway",
    "provider",
    "模型配置",
    "登录态",
    "密钥",
    "凭证",
    "terminal.cwd",
    "cwd",
)
_ARTIFACT_DELIVERY_ACTION_HINTS: tuple[str, ...] = (
    "上传",
    "分享",
    "同步",
    "发到",
    "发给",
    "upload",
    "share",
    "send",
    "deliver",
)
_ARTIFACT_DELIVERY_TARGET_HINTS: tuple[str, ...] = (
    "飞书",
    "feishu",
    "lark",
    "云文档",
    "云盘",
    "drive",
    "docs",
)
_OPERATOR_FOLLOW_UP_ACTION_HINTS: tuple[str, ...] = (
    "改",
    "修改",
    "重命名",
    "命名",
    "重新上传",
    "上传",
    "删除",
    "删掉",
    "移除",
    "更新",
    "重新生成",
    "重跑",
    "合并",
    "转换",
    "rename",
    "upload",
    "delete",
    "remove",
    "update",
    "regenerate",
    "rerun",
    "merge",
    "convert",
)
_OPERATOR_FOLLOW_UP_TARGET_HINTS: tuple[str, ...] = (
    "报告",
    "文件",
    "命名",
    "规则",
    "模板",
    "html",
    "docx",
    "md",
    "markdown",
    "飞书",
    "feishu",
    "lark",
    "云文档",
    "skill",
    "技能",
    "脚本",
)
_OPERATOR_FOLLOW_UP_MUTATION_HINTS: tuple[str, ...] = (
    "命名",
    "重命名",
    "规则",
    "模板",
    "删除",
    "删掉",
    "移除",
    "重新生成",
    "重跑",
    "合并",
    "转换",
    "脚本",
    "skill",
    "技能",
    "html",
    "docx",
    "md",
    "markdown",
)
_WECHAT_PUBLISH_BRIDGE_TOOL = "mente_wechat_publish_draft"
_WECHAT_PUBLISH_VISIBLE_TOOL = model_visible_mcp_tool_name("mente", _WECHAT_PUBLISH_BRIDGE_TOOL)
_FAST_PATH_GREETING_PREFIXES: tuple[str, ...] = (
    "hello",
    "hi",
    "hey",
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "哈囉",
)
_FAST_PATH_GREETING_ONLY_PREFIXES: tuple[str, ...] = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "哈囉",
)
_FAST_PATH_IDENTITY_SUFFIXES: tuple[str, ...] = (
    "你是谁",
    "你是誰",
    "介绍一下你自己",
    "介紹一下你自己",
    "自我介绍",
    "自我介紹",
)
_FAST_PATH_MODEL_SUFFIXES: tuple[str, ...] = (
    "你是什么大模型",
    "你是什么模型",
    "你是啥模型",
    "你現在是什么模型",
    "你现在是什么模型",
    "你用的是什么模型",
    "你用的什么模型",
)
_FAST_PATH_STRIP_PATTERN = re.compile(r"[\s,，。.!！?？:：;；~～]+")
_FIRST_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_ENGINEERING_FILE_PATTERN = re.compile(
    r"\b[\w./-]+\.(py|js|jsx|ts|tsx|go|rs|java|rb|php|sh|yml|yaml|json|toml)\b"
)
_ARTIFACT_PATH_PATTERN = re.compile(
    r"(?P<path>(?:~|/)[^\s<>()\[\]{}\"'`]+?\.(?:md|markdown|html|docx|doc|pdf|txt|csv|tsv|xlsx|xls|pptx|json|yaml|yml))",
    re.IGNORECASE,
)
_ARTIFACT_PATH_TRAILING_PUNCTUATION = ".,，。!！?？:：;；)]}>\"'"
_ENGINEERING_STRONG_HINTS: tuple[str, ...] = (
    "pytest",
    "traceback",
    "stack trace",
    "bug",
    "代码",
    "报错",
    "单测",
    "测试失败",
    "仓库",
    "repo",
    "repository",
    "git diff",
    "terminal",
    "bash",
    "shell",
)
_ENGINEERING_ACTION_HINTS: tuple[str, ...] = (
    "修复",
    "fix",
    "debug",
    "排查",
    "实现",
    "implement",
    "重构",
    "refactor",
    "运行",
    "run",
    "测试",
    "test",
    "查看",
    "inspect",
    "读取",
    "read",
)
_ENGINEERING_TARGET_HINTS: tuple[str, ...] = (
    "code",
    "代码",
    "file",
    "文件",
    "函数",
    "function",
    "repo",
    "repository",
    "仓库",
    "pytest",
    "traceback",
    "报错",
    "terminal",
    "shell",
    "bash",
    "git",
    "diff",
    "patch",
)
_LANE_CLASSIFIER_TASK = "lane_routing"
_LANE_CLASSIFIER_TIMEOUT_SECONDS = 8.0
_LANE_CLASSIFIER_MAX_TOKENS = 160
_LANE_CLASSIFIER_SYSTEM_PROMPT = """你是 Mente 的轻量分流器，只负责识别当前这一轮应该进入哪个 lane，不负责执行任务。

分流规则：
- 写代码、改代码、调试、测试、工程实现 -> engineering
- 调研、竞品、资料整理、分析结论 -> research
- 文案、改写、润色、发布内容、社媒稿 -> writing
- 配置、凭证、API key、provider、gateway、环境切换 -> config_admin
- 闲聊、确认、澄清、身份问答、状态跟进、无法确定时 -> director

输出要求：
- 只输出一个 JSON object
- 必须包含 lane, confidence, reason
- lane 只能是 director, engineering, research, writing, config_admin
- confidence 只能是 low, medium, high
- 不要输出 markdown，不要解释
"""
_LANE_CLASSIFIER_CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})
_REMEMBER_INTENT_CLASSIFIER_TASK = "remember_intent_routing"
_REMEMBER_INTENT_CLASSIFIER_TIMEOUT_SECONDS = 6.0
_REMEMBER_INTENT_CLASSIFIER_MAX_TOKENS = 180
_REMEMBER_INTENT_CLASSIFIER_SYSTEM_PROMPT = """你是 Mente 的轻量记忆意图分类器，只负责判断用户这一轮是否要求保存长期记忆或纠错偏好。

需要写入记忆的情况：
- 用户明确说记住、加入记忆、保存到记忆
- 用户纠正 Mente，并表达以后应该如何做
- 用户抱怨 Mente 记不住、忘了、没有遵守既有偏好，且可以抽取出一条稳定偏好/要求
- 用户只说“加入记忆/记住这个/保存一下”等省略表达时，应根据提供的近期上下文归纳要保存的长期事实

不要写入记忆的情况：
- 普通闲聊、一次性任务、状态查询
- 没有可持久化事实的情绪表达
- 密钥、密码、token 等敏感内容

输出要求：
- 只输出一个 JSON object
- 字段：should_write(boolean), fact(string), confidence("low"|"medium"|"high"), reason(string)
- fact 必须是可长期保存的一条简洁事实，不要包含“用户说/他骂/这句话”等转述外壳
- 如果只是“你怎么这么笨，啥都记不住？”这类记忆能力抱怨，fact 可归纳为“用户希望 Mente 可靠记住纠错、偏好和长期指令”
- 如果用户省略了事实，只能从 recent_context 中抽取或归纳；上下文不足时 should_write=false
- 不要输出 markdown，不要解释
"""
_REMEMBER_INTENT_CLASSIFIER_HINTS: tuple[str, ...] = (
    "记忆",
    "记住",
    "记不住",
    "记性",
    "忘",
    "忘了",
    "纠正",
    "纠错",
    "你错了",
    "不对",
    "以后",
    "下次",
    "别再",
    "应该",
    "偏好",
    "习惯",
    "remember",
    "memory",
    "forget",
    "forgot",
    "preference",
)
_LANE_CLASSIFIER_REQUEST_HINTS: tuple[str, ...] = (
    "帮我",
    "请",
    "整理",
    "总结",
    "分析",
    "对比",
    "比较",
    "调研",
    "竞品",
    "方案",
    "推进",
    "规划",
    "写",
    "撰写",
    "改写",
    "润色",
    "draft",
    "rewrite",
    "research",
    "analyze",
    "analysis",
    "compare",
    "summary",
    "summarize",
    "plan",
)
_EXPLICIT_SKILL_REQUEST_HINTS: tuple[str, ...] = (
    "调用技能",
    "调用这个技能",
    "用技能",
    "用这个技能",
    "invoke skill",
    "use skill",
)
_EXPLICIT_SKILL_REQUEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"调用.{0,120}?技能"),
    re.compile(r"用.{0,120}?技能"),
    re.compile(r"(?:invoke|use)\s+.{0,120}?skill\b"),
)
_EXPLICIT_SKILL_TOKEN_PATTERN = re.compile(
    r"\b[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)+\b|\b[a-z0-9][a-z0-9_-]*-[a-z0-9][a-z0-9_-]*\b"
)
_EXPLICIT_SKILL_ALIAS_TO_REF: Mapping[str, str] = {
    "deep-research-pro": _DEEP_RESEARCH_SKILL_REF,
    "deep research": _DEEP_RESEARCH_SKILL_REF,
    "deep-research": _DEEP_RESEARCH_SKILL_REF,
    "深度研究技能": _DEEP_RESEARCH_SKILL_REF,
    "深度研究": _DEEP_RESEARCH_SKILL_REF,
    "wechat-publisher": _WECHAT_PUBLISHER_SKILL_REF,
    "公众号发布技能": _WECHAT_PUBLISHER_SKILL_REF,
    "imagegen": _IMAGEGEN_SKILL_REF,
    "mente-config-admin": _MENTE_CONFIG_ADMIN_SKILL_REF,
    "config-admin": _MENTE_CONFIG_ADMIN_SKILL_REF,
}
_DEFAULT_SKILL_OWNER_LANE_BY_REF: Mapping[str, str] = {
    _WECHAT_PUBLISHER_SKILL_REF: WRITING_LANE,
    _IMAGEGEN_SKILL_REF: WRITING_LANE,
    _DEEP_RESEARCH_SKILL_REF: RESEARCH_LANE,
    _MENTE_CONFIG_ADMIN_SKILL_REF: CONFIG_ADMIN_LANE,
}
_AGENT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "agents" / "registry.yaml"


@dataclass(frozen=True)
class ConversationRoute:
    lane: str
    task_profile: str | None
    skill_refs: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DispatchDecision:
    lane: str
    dispatch_mode: DispatchMode
    task_profile: str | None
    skill_refs: tuple[str, ...]
    target_job_lane: str | None
    needs_clarification: bool
    reason: str


@dataclass(frozen=True)
class GatewayTaskBundle:
    coordinator_task: Task
    worker_task: Task | None
    decision: DispatchDecision


@dataclass(frozen=True)
class ExplicitSkillResolution:
    requested_skill_refs: tuple[str, ...]
    known_skill_refs: tuple[str, ...]
    owner_lanes: tuple[str, ...]
    unknown_skill_refs: tuple[str, ...]


def _build_content_publishing_workflow_brief() -> str:
    """Return a compact workflow brief for gateway-authored publishing tasks."""

    return "\n".join(
        [
            "Publishing workflow brief:",
            "1. Use the provided publishing skill refs directly instead of rediscovering the workflow.",
            "2. Draft the requested article and requested assets in the active workspace first.",
            "3. Avoid repository-wide or home-directory scans; only inspect directly relevant files if a concrete blocker appears.",
            f"4. Once the article is ready, use {_WECHAT_PUBLISH_VISIBLE_TOOL} to publish the WeChat draft.",
            "5. If editorial details are missing, choose reasonable defaults and continue.",
        ]
    )


def _build_deep_research_workflow_brief() -> str:
    """Return a compact workflow brief for gateway-authored deep-research tasks."""

    return "\n".join(
        [
            "Deep research workflow brief:",
            "1. Use the provided deep-research skill directly instead of treating this as an open-ended chat turn.",
            "2. Complete the full research-report workflow in this turn rather than stopping at intermediate findings.",
            "3. Do not end with 'if you want, I can continue' when the user already asked for deep research.",
            "4. The task is not complete until the report artifacts are generated and their paths are reported back.",
        ]
    )


def _build_config_admin_workflow_brief() -> str:
    """Return a compact workflow brief for Mente config/admin tasks."""

    return "\n".join(
        [
            "Config-admin workflow brief:",
            "1. Use the provided config-admin skill directly instead of rediscovering the workflow.",
            "2. Resolve the active config or env path first with `mente config path` / `mente config env-path` when relevant.",
            "3. Read only the directly relevant config, env, or auth files needed for the requested change.",
            "4. Preserve unrelated settings, redact secrets in confirmations, and restart services only when required.",
            "5. Final reply should state the exact file, key, and restart action performed, or the concrete blocker.",
        ]
    )


def _build_artifact_delivery_workflow_brief() -> str:
    """Return a compact workflow brief for follow-up artifact delivery tasks."""

    return "\n".join(
        [
            "Artifact delivery workflow brief:",
            "1. Use the provided artifact paths directly instead of rediscovering the prior report outputs.",
            "2. Treat this as a narrow follow-up delivery task, not a new research or debugging session.",
            "3. Avoid repository-wide or home-directory scans unless one provided artifact path is missing.",
            "4. If the user asked for Feishu/Lark delivery, upload or share the listed files with the available platform flow directly.",
            "5. Final reply should confirm which artifacts were delivered and include links or the concrete blocker.",
        ]
    )


def _build_content_publishing_output_plan(*, workspace: str, session_id: str) -> str:
    """Return a deterministic draft output path for publishing workflows."""

    draft_dir = Path(workspace).expanduser() / ".mente" / "publishing" / session_id
    article_path = draft_dir / "article.md"
    return "\n".join(
        [
            "Publishing output plan:",
            f"- Draft directory: {draft_dir}",
            f"- Draft article path: {article_path}",
            f"- Use the planned draft article path when calling {_WECHAT_PUBLISH_VISIBLE_TOOL}.",
        ]
    )


def _build_deep_research_output_plan() -> str:
    """Return the default artifact contract for deep-research workflows."""

    report_root = resolve_deep_research_output_root()
    return "\n".join(
        [
            "Deep research output plan:",
            f"- Output root: {report_root}",
            "- Required artifact formats: Markdown (.md), HTML (.html), DOCX (.docx)",
            "- Final reply requirement: include a concise conclusion plus the generated artifact paths.",
            "- If one format fails, continue producing the remaining artifacts and explain the concrete blocker.",
        ]
    )


def _build_artifact_delivery_inputs_fact(artifact_paths: list[str]) -> str:
    """Return one deterministic artifact-input fact for follow-up delivery tasks."""

    lines = ["Artifact delivery inputs:"]
    lines.extend(f"- {path}" for path in artifact_paths[:10])
    return "\n".join(lines)


def _build_deep_research_execution_plan(*, workspace: str) -> str:
    """Return deterministic orchestration guidance for managed deep research."""

    skill_root = get_skills_dir() / "research" / "deep-research-pro"
    resolved_workspace = Path(workspace).expanduser()
    return "\n".join(
        [
            "Deep research execution plan:",
            "- Prefer one parent orchestrator plus 3 parallel delegate_task workers instead of a single agent writing all 7 chapters serially.",
            "- Recommended worker ownership: chapter_1 + chapter_4; chapter_2 + chapter_3; chapter_5 + chapter_6 + chapter_7.",
            f"- Active workspace: {resolved_workspace}",
            f"- Skill root: {skill_root}",
            f"- Preferred direct parallel entrypoint: {skill_root / 'deep_research_pro.py'}",
            "- Keep exploration scoped to the active workspace and the deep-research skill root.",
            "- Avoid broad repository or home-directory scans before delegating work.",
            "- Each worker should finish its assigned chapters, save intermediate chapter artifacts, and return concise findings plus artifact paths to the parent.",
            "- The parent should merge validated chapter outputs once, then generate the final Markdown, HTML, and DOCX report artifacts.",
        ]
    )


def _build_content_publishing_entrypoint_brief(*, workspace: str, session_id: str) -> str:
    """Return direct, deterministic workflow entrypoints for managed publishing tasks."""

    draft_dir = Path(workspace).expanduser() / ".mente" / "publishing" / session_id
    article_path = draft_dir / "article.md"
    skill_root = get_skills_dir() / "media" / "wechat-publisher"
    create_article = skill_root / "scripts" / "publisher" / "create-article.js"
    publish_script = skill_root / "scripts" / "publisher" / "publish.js"
    return "\n".join(
        [
            "Publishing entrypoints:",
            f"- Managed publish entrypoint: {_WECHAT_PUBLISH_VISIBLE_TOOL}(article_path=<Draft article path>).",
            f"- Underlying bridge mapping: {_WECHAT_PUBLISH_VISIBLE_TOOL} (server mente / tool {_WECHAT_PUBLISH_BRIDGE_TOOL}).",
            f"- Preferred draft-first flow: write the article markdown to {article_path}, generate any requested assets in {draft_dir}, then call {_WECHAT_PUBLISH_VISIBLE_TOOL}.",
            f'- Optional script reference only: node {create_article} "<文章标题>" --from {article_path}',
            f"- Optional publish script reference only: node {publish_script} {article_path}",
            f"- Do not treat create-article.js or publish.js as the primary publish path when {_WECHAT_PUBLISH_VISIBLE_TOOL} is available.",
            "- If you need script details, do at most one targeted help/read check, then execute the managed flow.",
        ]
    )


def _resolve_content_publishing_draft_dir(*, workspace: str, session_id: str) -> Path:
    return Path(workspace).expanduser() / ".mente" / "publishing" / session_id


def _recent_snapshot_artifacts(snapshot: Mapping[str, Any] | None) -> list[str]:
    """Return normalized recent artifact paths from one short-term task snapshot."""

    if not isinstance(snapshot, Mapping):
        return []
    metadata = snapshot.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    artifacts = metadata.get("artifacts_out")
    if not isinstance(artifacts, (list, tuple, set)):
        return []
    normalized: list[str] = []
    for item in artifacts:
        candidate = str(item).strip()
        if candidate:
            normalized.append(candidate)
    return normalized


def _recent_snapshot_follow_up_tasks(snapshot: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, Mapping):
        return []
    return [
        str(item).strip()
        for item in snapshot.get("follow_up_tasks") or []
        if str(item).strip()
    ]


def _recent_snapshot_metadata(
    snapshot: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    metadata = snapshot.get("metadata") if isinstance(snapshot, Mapping) else None
    return metadata if isinstance(metadata, Mapping) else {}


def _recent_snapshot_task_profile(snapshot: Mapping[str, Any] | None) -> str | None:
    metadata = _recent_snapshot_metadata(snapshot)
    task_profile = str(metadata.get("task_profile") or "").strip().lower()
    return task_profile or None


def _normalize_recent_task_operator_capsule(
    value: Mapping[str, Any] | None,
    *,
    artifact_paths: list[str] | None = None,
    next_actions: list[str] | None = None,
    task_profile: str | None = None,
    skill_refs: list[str] | tuple[str, ...] | None = None,
    workspace: str | None = None,
) -> dict[str, Any] | None:
    raw = value if isinstance(value, Mapping) else {}
    capsule: dict[str, Any] = {}

    skill_entrypoint = str(raw.get("skill_entrypoint") or "").strip()
    if not skill_entrypoint:
        normalized_task_profile = str(task_profile or "").strip().lower()
        normalized_skill_refs = _normalize_skill_refs(skill_refs or [])
        if (
            normalized_task_profile == _DEEP_RESEARCH_TASK_PROFILE
            or _DEEP_RESEARCH_SKILL_REF in normalized_skill_refs
        ):
            skill_entrypoint = str(
                get_skills_dir() / "research" / "deep-research-pro" / "deep_research_pro.py"
            )
    if skill_entrypoint:
        capsule["skill_entrypoint"] = skill_entrypoint

    allowed_roots = [
        str(item).strip()
        for item in raw.get("allowed_roots") or []
        if str(item).strip()
    ]
    if not allowed_roots:
        normalized_task_profile = str(task_profile or "").strip().lower()
        normalized_skill_refs = _normalize_skill_refs(skill_refs or [])
        inferred_roots: list[str] = []
        if workspace:
            inferred_roots.append(str(Path(workspace).expanduser()))
        if (
            normalized_task_profile == _DEEP_RESEARCH_TASK_PROFILE
            or _DEEP_RESEARCH_SKILL_REF in normalized_skill_refs
        ):
            inferred_roots.append(str(get_skills_dir() / "research" / "deep-research-pro"))
            inferred_roots.append(str(resolve_deep_research_output_root()))
        allowed_roots = inferred_roots
    if allowed_roots:
        capsule["allowed_roots"] = list(dict.fromkeys(allowed_roots))

    naming_template = str(raw.get("naming_template") or "").strip()
    if not naming_template and str(task_profile or "").strip().lower() == _DEEP_RESEARCH_TASK_PROFILE:
        naming_template = "<product>_<YYYYMMDD>.(md|html|docx)"
    if naming_template:
        capsule["naming_template"] = naming_template

    normalized_artifacts = [
        str(item).strip()
        for item in (artifact_paths or raw.get("artifact_paths") or [])
        if str(item).strip()
    ]
    if normalized_artifacts:
        capsule["artifact_paths"] = normalized_artifacts

    normalized_next_actions = [
        str(item).strip()
        for item in (next_actions or raw.get("next_actions") or [])
        if str(item).strip()
    ]
    if normalized_next_actions:
        capsule["next_actions"] = normalized_next_actions

    return capsule or None


def _recent_snapshot_operator_capsule(
    snapshot: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    metadata = _recent_snapshot_metadata(snapshot)
    return _normalize_recent_task_operator_capsule(
        metadata.get("operator_capsule") if isinstance(metadata, Mapping) else None,
        artifact_paths=_recent_snapshot_artifacts(snapshot),
        next_actions=_recent_snapshot_follow_up_tasks(snapshot),
        task_profile=_recent_snapshot_task_profile(snapshot),
        skill_refs=_recent_snapshot_skill_refs(snapshot),
    )


def _resolve_task_operator_capsule(
    *,
    task_profile: str | None,
    skill_refs: list[str] | tuple[str, ...] | None,
    workspace: str | None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    artifact_paths: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any] | None:
    existing = _recent_snapshot_operator_capsule(recent_task_snapshot)
    return _normalize_recent_task_operator_capsule(
        existing,
        artifact_paths=artifact_paths,
        next_actions=next_actions,
        task_profile=task_profile or _recent_snapshot_task_profile(recent_task_snapshot),
        skill_refs=skill_refs or _recent_snapshot_skill_refs(recent_task_snapshot),
        workspace=workspace,
    )


def looks_like_gateway_recent_artifact_delivery_request(
    *,
    message: str,
    channel_prompt: str | None = None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether the latest message is a narrow follow-up to deliver recent artifacts."""

    artifact_paths = _recent_snapshot_artifacts(recent_task_snapshot)
    if not artifact_paths:
        return False
    haystack = _normalize_text_haystack(message, channel_prompt)
    if not haystack:
        return False
    return (
        any(hint in haystack for hint in _ARTIFACT_DELIVERY_ACTION_HINTS)
        and any(hint in haystack for hint in _ARTIFACT_DELIVERY_TARGET_HINTS)
    )


def looks_like_gateway_recent_operator_follow_up_request(
    *,
    message: str,
    channel_prompt: str | None = None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether the latest message is a narrow operator-style follow-up on one recent task."""

    if _looks_like_status_follow_up_request(message) or _looks_like_continue_task_request(message):
        return False
    capsule = _recent_snapshot_operator_capsule(recent_task_snapshot)
    if not capsule:
        return False
    haystack = _normalize_text_haystack(message, channel_prompt)
    if not haystack:
        return False
    return (
        any(hint in haystack for hint in _OPERATOR_FOLLOW_UP_ACTION_HINTS)
        and any(hint in haystack for hint in _OPERATOR_FOLLOW_UP_TARGET_HINTS)
        and any(hint in haystack for hint in _OPERATOR_FOLLOW_UP_MUTATION_HINTS)
    )


def recover_gateway_content_publishing_artifacts(
    *,
    message: str,
    session_id: str,
    channel_prompt: str | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Finalize a timed-out gateway publishing task from deterministic draft artifacts."""

    inferred_skill_refs = _infer_gateway_skill_refs(message=message, channel_prompt=channel_prompt)
    task_profile = _resolve_gateway_task_profile(inferred_skill_refs)
    if task_profile != _CONTENT_PUBLISHING_TASK_PROFILE:
        return {
            "ok": False,
            "reason": "not_content_publishing",
        }

    resolved_workspace = _resolve_gateway_workspace(
        workspace=workspace,
        message=message,
        channel_prompt=channel_prompt,
        skill_refs=inferred_skill_refs,
    )
    draft_dir = _resolve_content_publishing_draft_dir(
        workspace=resolved_workspace,
        session_id=session_id,
    )
    article_path = draft_dir / "article.md"
    source_path = draft_dir / "source.md"
    publish_target: Path | None = None
    recovered_from = ""
    if article_path.is_file():
        publish_target = article_path
        recovered_from = "article.md"
    elif source_path.is_file():
        publish_target = source_path
        recovered_from = "source.md"
    else:
        return {
            "ok": False,
            "reason": "draft_not_found",
            "workspace": resolved_workspace,
            "draft_dir": str(draft_dir),
            "draft_article_path": str(article_path),
            "draft_source_path": str(source_path),
        }

    publish_result = publish_wechat_draft(article_path=str(publish_target))
    return {
        "ok": bool(publish_result.get("ok")),
        "reason": None if publish_result.get("ok") else str(publish_result.get("error") or "publish_failed"),
        "failure_summary": None if publish_result.get("ok") else publish_result.get("failure_summary"),
        "workspace": resolved_workspace,
        "draft_dir": str(draft_dir),
        "draft_article_path": str(article_path),
        "draft_source_path": str(source_path),
        "recovered_from": recovered_from,
        "publish_result": publish_result,
    }


def _resolve_workspace(workspace: str | None) -> str:
    """Resolve the workspace used for a bridged task."""
    return workspace or os.getenv("TERMINAL_CWD") or os.getcwd()


def _normalize_text_haystack(*parts: str | None) -> str:
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def extract_artifact_paths_from_text(*parts: str | None) -> list[str]:
    """Extract likely artifact file paths from free-form assistant text."""

    extracted: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "")
        if not text:
            continue
        for match in _ARTIFACT_PATH_PATTERN.finditer(text):
            candidate = match.group("path").rstrip(_ARTIFACT_PATH_TRAILING_PUNCTUATION)
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            extracted.append(candidate)
    return extracted


def _compact_simple_conversation_request(message: str | None) -> str:
    """Return a punctuation-free normalized prompt for narrow fast-path matching."""

    return _FAST_PATH_STRIP_PATTERN.sub("", str(message or "").strip().lower())


def _matches_simple_suffix_request(
    message: str | None,
    suffixes: tuple[str, ...],
    *,
    allow_greeting_only: bool = False,
) -> bool:
    compact = _compact_simple_conversation_request(message)
    if not compact:
        return False
    if compact in suffixes:
        return True
    if allow_greeting_only and compact in _FAST_PATH_GREETING_ONLY_PREFIXES:
        return True
    return any(compact == f"{prefix}{suffix}" for prefix in _FAST_PATH_GREETING_PREFIXES for suffix in suffixes)


def _looks_like_fast_identity_request(message: str | None) -> bool:
    """Return whether one prompt qualifies for the local identity fast-path."""

    return _looks_like_chinese_identity_or_greeting_request(message) or _matches_simple_suffix_request(
        message,
        _FAST_PATH_IDENTITY_SUFFIXES,
        allow_greeting_only=True,
    )


def _looks_like_fast_model_identity_request(message: str | None) -> bool:
    """Return whether one prompt qualifies for the local model-identity fast-path."""

    return _looks_like_chinese_model_identity_request(message) or _matches_simple_suffix_request(
        message,
        _FAST_PATH_MODEL_SUFFIXES,
    )


def _resolve_lane_from_task_profile(
    task_profile: str | None,
    *,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> str | None:
    normalized_task_profile = str(task_profile or "").strip().lower()
    if normalized_task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        return WRITING_LANE
    if normalized_task_profile == _DEEP_RESEARCH_TASK_PROFILE:
        return RESEARCH_LANE
    if normalized_task_profile == _CONFIG_ADMIN_TASK_PROFILE:
        return CONFIG_ADMIN_LANE
    if normalized_task_profile != _ARTIFACT_DELIVERY_TASK_PROFILE:
        return None

    snapshot_metadata = recent_task_snapshot.get("metadata") if isinstance(recent_task_snapshot, Mapping) else None
    if isinstance(snapshot_metadata, Mapping):
        snapshot_lane = str(snapshot_metadata.get("lane") or "").strip().lower()
        if snapshot_lane in {
            DIRECTOR_LANE,
            ENGINEERING_LANE,
            RESEARCH_LANE,
            WRITING_LANE,
            CONFIG_ADMIN_LANE,
        }:
            return snapshot_lane
        snapshot_task_profile = str(snapshot_metadata.get("task_profile") or "").strip().lower()
        mapped_lane = _resolve_lane_from_task_profile(snapshot_task_profile)
        if mapped_lane:
            return mapped_lane
    return DIRECTOR_LANE


def _normalize_active_lane_hint(value: str | None) -> str | None:
    lane = str(value or "").strip().lower()
    return lane if lane in _KNOWN_LANES else None


def _resolve_recent_task_snapshot_lane(
    recent_task_snapshot: Mapping[str, Any] | None,
) -> str | None:
    if not isinstance(recent_task_snapshot, Mapping):
        return None
    snapshot_metadata = (
        recent_task_snapshot.get("metadata")
        if isinstance(recent_task_snapshot.get("metadata"), Mapping)
        else None
    )
    if isinstance(snapshot_metadata, Mapping):
        snapshot_lane = _normalize_active_lane_hint(
            str(snapshot_metadata.get("lane") or "")
        )
        if snapshot_lane:
            return snapshot_lane
        snapshot_task_profile = str(snapshot_metadata.get("task_profile") or "").strip().lower()
        mapped_lane = _resolve_lane_from_task_profile(snapshot_task_profile)
        if mapped_lane:
            return mapped_lane
    return None


def _resolve_operator_follow_up_lane(
    *,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    task_profile: str | None = None,
    skill_refs: tuple[str, ...] = (),
) -> str | None:
    snapshot_lane = _resolve_recent_task_snapshot_lane(recent_task_snapshot)
    if snapshot_lane and snapshot_lane != DIRECTOR_LANE:
        return snapshot_lane
    active = _normalize_active_lane_hint(active_lane)
    if active and active != DIRECTOR_LANE:
        return active
    owner_lane = _resolve_skill_owner_lane(
        skill_refs=skill_refs,
        task_profile=task_profile,
        recent_task_snapshot=recent_task_snapshot,
    )
    if owner_lane and owner_lane != DIRECTOR_LANE:
        return owner_lane
    return None


def _looks_like_engineering_request(
    *,
    message: str,
    channel_prompt: str | None = None,
) -> bool:
    haystack = _normalize_text_haystack(message, channel_prompt)
    if not haystack:
        return False
    if any(hint in haystack for hint in _ENGINEERING_STRONG_HINTS):
        return True
    if _ENGINEERING_FILE_PATTERN.search(haystack):
        return True
    return (
        any(hint in haystack for hint in _ENGINEERING_ACTION_HINTS)
        and any(hint in haystack for hint in _ENGINEERING_TARGET_HINTS)
    )


def _resolve_lane_classifier_main_runtime(
    *,
    workspace: str | None = None,
) -> dict[str, str] | None:
    try:
        runtime_config = resolve_runtime_config(_resolve_workspace(workspace))
    except Exception:
        logger.debug("Lane classifier runtime resolution failed", exc_info=True)
        return None
    model_runtime = getattr(runtime_config, "model_runtime", None)
    if model_runtime is None:
        return None
    metadata = model_runtime.to_metadata()
    return metadata if metadata else None


def _parse_lane_classifier_payload(content: object) -> dict[str, str] | None:
    text = str(content or "").strip()
    if not text:
        return None
    match = _FIRST_JSON_OBJECT_PATTERN.search(text)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    lane = _normalize_active_lane_hint(str(payload.get("lane") or ""))
    if lane is None:
        return None
    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence and confidence not in _LANE_CLASSIFIER_CONFIDENCE_VALUES:
        confidence = ""
    reason = str(payload.get("reason") or "").strip()
    result = {"lane": lane}
    if confidence:
        result["confidence"] = confidence
    if reason:
        result["reason"] = reason
    return result


def _parse_remember_intent_classifier_payload(content: object) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    match = _FIRST_JSON_OBJECT_PATTERN.search(text)
    if match is None:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict) or not bool(payload.get("should_write")):
        return []
    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence not in {"medium", "high"}:
        return []
    fact = normalize_memory_fact_text(str(payload.get("fact") or ""))
    return [fact] if fact else []


def _classify_semantic_remember_intent_facts(
    *,
    message: str,
    context_facts: list[str] | tuple[str, ...] | None = None,
    workspace: str | None = None,
) -> list[str]:
    normalized_message = str(message or "").strip()
    if not normalized_message:
        return []
    normalized_context_facts = [
        str(item).strip()
        for item in (context_facts or [])
        if str(item).strip()
    ]
    user_prompt_lines = [f"message: {normalized_message}"]
    if normalized_context_facts:
        context_blob = "\n\n".join(normalized_context_facts[-5:])
        user_prompt_lines.append(f"recent_context:\n{context_blob[:4000]}")
    response = call_llm(
        task=_REMEMBER_INTENT_CLASSIFIER_TASK,
        messages=[
            {"role": "system", "content": _REMEMBER_INTENT_CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_prompt_lines)},
        ],
        temperature=0.0,
        max_tokens=_REMEMBER_INTENT_CLASSIFIER_MAX_TOKENS,
        timeout=_REMEMBER_INTENT_CLASSIFIER_TIMEOUT_SECONDS,
        main_runtime=_resolve_lane_classifier_main_runtime(workspace=workspace),
    )
    content = response.choices[0].message.content
    return _parse_remember_intent_classifier_payload(content)


def _looks_like_semantic_remember_intent_candidate(message: str) -> bool:
    haystack = _normalize_text_haystack(message)
    if not haystack:
        return False
    return any(hint in haystack for hint in _REMEMBER_INTENT_CLASSIFIER_HINTS)


def _resolve_remember_intent_facts(
    *,
    message: str,
    context_facts: list[str] | tuple[str, ...] | None = None,
    workspace: str | None = None,
) -> list[str]:
    explicit_facts = extract_explicit_remember_intent_facts(message)
    if explicit_facts:
        return explicit_facts
    if not _looks_like_semantic_remember_intent_candidate(message):
        return []
    try:
        return _classify_semantic_remember_intent_facts(
            message=message,
            context_facts=context_facts,
            workspace=workspace,
        )
    except Exception:
        logger.debug("Remember-intent classifier fallback failed", exc_info=True)
        return []


def _classify_ambiguous_conversation_lane(
    *,
    message: str,
    channel_prompt: str | None = None,
    workspace: str | None = None,
) -> dict[str, str] | None:
    normalized_message = str(message or "").strip()
    if not normalized_message:
        return None
    user_prompt_lines = [
        "请根据下面这一轮消息做分流，只返回 JSON：",
        f"message: {normalized_message}",
    ]
    normalized_channel_prompt = str(channel_prompt or "").strip()
    if normalized_channel_prompt:
        user_prompt_lines.append(f"channel_prompt: {normalized_channel_prompt}")
    response = call_llm(
        task=_LANE_CLASSIFIER_TASK,
        messages=[
            {"role": "system", "content": _LANE_CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_prompt_lines)},
        ],
        temperature=0.0,
        max_tokens=_LANE_CLASSIFIER_MAX_TOKENS,
        timeout=_LANE_CLASSIFIER_TIMEOUT_SECONDS,
        main_runtime=_resolve_lane_classifier_main_runtime(workspace=workspace),
    )
    content = response.choices[0].message.content
    return _parse_lane_classifier_payload(content)


def _looks_like_lane_classifier_candidate(
    *,
    message: str,
    channel_prompt: str | None = None,
) -> bool:
    if extract_explicit_remember_intent_facts(message):
        return False
    haystack = _normalize_text_haystack(message, channel_prompt)
    return any(hint in haystack for hint in _LANE_CLASSIFIER_REQUEST_HINTS)


def _looks_like_explicit_skill_request(
    *,
    message: str,
    channel_prompt: str | None = None,
) -> bool:
    haystack = _normalize_text_haystack(message, channel_prompt)
    if not haystack:
        return False
    return any(hint in haystack for hint in _EXPLICIT_SKILL_REQUEST_HINTS) or any(
        pattern.search(haystack) for pattern in _EXPLICIT_SKILL_REQUEST_PATTERNS
    )


def _dedupe_skill_refs(skill_refs: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_ref in skill_refs:
        candidate = str(raw_ref).strip().lower()
        if not candidate or candidate in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate)
    return tuple(deduped)


@lru_cache(maxsize=1)
def _load_skill_owner_lane_by_ref() -> dict[str, str]:
    mapping = {key.lower(): value for key, value in _DEFAULT_SKILL_OWNER_LANE_BY_REF.items()}
    try:
        raw_registry = yaml.safe_load(_AGENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return mapping
    if not isinstance(raw_registry, dict):
        return mapping

    agents = raw_registry.get("agents")
    if not isinstance(agents, dict):
        return mapping

    for agent_config in agents.values():
        if not isinstance(agent_config, dict):
            continue
        lane_candidates = [
            lane
            for lane in (
                _normalize_active_lane_hint(str(raw_lane or ""))
                for raw_lane in agent_config.get("lanes", [])
            )
            if lane
        ]
        if not lane_candidates:
            continue
        owner_lane = next((lane for lane in lane_candidates if lane != DIRECTOR_LANE), lane_candidates[0])
        for skill_ref in _normalize_skill_refs(agent_config.get("skill_owners")):
            mapping[skill_ref.lower()] = owner_lane
    return mapping


def _normalize_explicit_skill_candidate(token: str) -> str | None:
    candidate = str(token or "").strip().lower().strip("`'\".,，。!！?？:：;；()[]{}<>")
    if not candidate:
        return None
    alias_ref = _EXPLICIT_SKILL_ALIAS_TO_REF.get(candidate)
    if alias_ref:
        return alias_ref
    if candidate in _load_skill_owner_lane_by_ref():
        return candidate
    return None


def _resolve_explicit_skill_request(
    *,
    message: str,
    channel_prompt: str | None = None,
    inferred_skill_refs: tuple[str, ...] = (),
) -> ExplicitSkillResolution:
    haystack = _normalize_text_haystack(message, channel_prompt)
    known_skill_refs: list[str] = []
    unknown_skill_refs: list[str] = []

    for raw_token in _EXPLICIT_SKILL_TOKEN_PATTERN.findall(haystack):
        normalized = _normalize_explicit_skill_candidate(raw_token)
        if normalized:
            known_skill_refs.append(normalized)
        else:
            unknown_skill_refs.append(raw_token.strip().lower())

    for alias, skill_ref in _EXPLICIT_SKILL_ALIAS_TO_REF.items():
        if alias in haystack:
            known_skill_refs.append(skill_ref)

    known_skill_refs_tuple = _dedupe_skill_refs(known_skill_refs)
    unknown_skill_refs_tuple = _dedupe_skill_refs(unknown_skill_refs)
    if not known_skill_refs_tuple and inferred_skill_refs:
        known_skill_refs_tuple = _dedupe_skill_refs(inferred_skill_refs)

    requested_skill_refs = _dedupe_skill_refs(
        [*known_skill_refs_tuple, *unknown_skill_refs_tuple]
    )
    owner_lanes = _dedupe_skill_refs(
        [
            owner_lane
            for owner_lane in (
                _load_skill_owner_lane_by_ref().get(skill_ref)
                for skill_ref in known_skill_refs_tuple
            )
            if owner_lane
        ]
    )
    return ExplicitSkillResolution(
        requested_skill_refs=requested_skill_refs,
        known_skill_refs=known_skill_refs_tuple,
        owner_lanes=owner_lanes,
        unknown_skill_refs=unknown_skill_refs_tuple,
    )


def _resolve_skill_owner_lane(
    *,
    skill_refs: tuple[str, ...],
    task_profile: str | None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> str | None:
    lane = _resolve_lane_from_task_profile(
        task_profile,
        recent_task_snapshot=recent_task_snapshot,
    )
    if lane:
        return lane
    owner_lanes = {
        _load_skill_owner_lane_by_ref().get(skill_ref.lower())
        for skill_ref in skill_refs
        if _load_skill_owner_lane_by_ref().get(skill_ref.lower())
    }
    if len(owner_lanes) != 1:
        return None
    return next(iter(owner_lanes))


def _build_inline_dispatch_decision(
    *,
    lane: str = DIRECTOR_LANE,
    task_profile: str | None,
    skill_refs: tuple[str, ...],
    target_job_lane: str | None = None,
    needs_clarification: bool = False,
    reason: str,
) -> DispatchDecision:
    return DispatchDecision(
        lane=lane,
        dispatch_mode=DispatchMode.INLINE,
        task_profile=task_profile,
        skill_refs=skill_refs,
        target_job_lane=target_job_lane,
        needs_clarification=needs_clarification,
        reason=reason,
    )


def _build_background_dispatch_decision(
    *,
    lane: str,
    task_profile: str | None,
    skill_refs: tuple[str, ...],
    reason: str,
) -> DispatchDecision:
    return DispatchDecision(
        lane=lane,
        dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
        task_profile=task_profile,
        skill_refs=skill_refs,
        target_job_lane=lane,
        needs_clarification=False,
        reason=reason,
    )


def _resolve_pending_worker_control_payload(
    *,
    message: str,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(recent_task_snapshot, Mapping):
        return None
    metadata = recent_task_snapshot.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    payload = metadata.get("pending_worker_control")
    if not isinstance(payload, Mapping):
        return None
    user_revision = str(payload.get("user_revision") or "").strip()
    if user_revision and user_revision != str(message or "").strip():
        return None
    return dict(payload)


def resolve_dispatch_decision(
    *,
    message: str,
    channel_prompt: str | None = None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    workspace: str | None = None,
) -> DispatchDecision:
    """Resolve one deterministic-first dispatch decision for a conversation turn."""

    inferred_skill_refs = tuple(
        _infer_gateway_skill_refs(message=message, channel_prompt=channel_prompt)
    )
    if _looks_like_explicit_skill_request(
        message=message,
        channel_prompt=channel_prompt,
    ):
        explicit_skill_resolution = _resolve_explicit_skill_request(
            message=message,
            channel_prompt=channel_prompt,
            inferred_skill_refs=inferred_skill_refs,
        )
        inferred_skill_refs = _dedupe_skill_refs(
            [*inferred_skill_refs, *explicit_skill_resolution.requested_skill_refs]
        )
    task_profile = _resolve_gateway_task_profile(list(inferred_skill_refs))
    operator_follow_up = looks_like_gateway_recent_operator_follow_up_request(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
    )
    if operator_follow_up:
        task_profile = _recent_snapshot_task_profile(recent_task_snapshot) or task_profile
        if not inferred_skill_refs:
            inferred_skill_refs = tuple(_recent_snapshot_skill_refs(recent_task_snapshot))
    elif looks_like_gateway_recent_artifact_delivery_request(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
    ):
        task_profile = _ARTIFACT_DELIVERY_TASK_PROFILE

    status_follow_up_lane = _resolve_status_follow_up_target_lane(
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
    )
    if _looks_like_status_follow_up_request(message) and status_follow_up_lane:
        return _build_inline_dispatch_decision(
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
            target_job_lane=status_follow_up_lane,
            reason=f"status_follow_up:{status_follow_up_lane}",
        )

    pending_worker_control = _resolve_pending_worker_control_payload(
        message=message,
        recent_task_snapshot=recent_task_snapshot,
    )
    if pending_worker_control is not None:
        control_lane = str(pending_worker_control.get("lane") or "").strip().lower()
        if control_lane and control_lane in _KNOWN_LANES and control_lane != DIRECTOR_LANE:
            control_task_profile = str(
                pending_worker_control.get("task_profile") or task_profile or ""
            ).strip() or None
            control_skill_refs = _normalize_skill_refs(
                pending_worker_control.get("skill_refs") or inferred_skill_refs
            )
            return _build_background_dispatch_decision(
                lane=control_lane,
                task_profile=control_task_profile,
                skill_refs=tuple(control_skill_refs),
                reason=f"worker_control:{pending_worker_control.get('action') or 'follow_up'}:{control_lane}",
            )

    continue_request = _looks_like_continue_task_request(message)
    if continue_request:
        continuation_lane = (
            _normalize_active_lane_hint(active_lane)
            or _resolve_recent_task_snapshot_lane(recent_task_snapshot)
        )
        if continuation_lane:
            return _build_inline_dispatch_decision(
                task_profile=task_profile,
                skill_refs=inferred_skill_refs,
                target_job_lane=continuation_lane,
                reason=f"continue_active_job:{continuation_lane}",
            )

    if operator_follow_up:
        operator_lane = _resolve_operator_follow_up_lane(
            recent_task_snapshot=recent_task_snapshot,
            active_lane=active_lane,
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
        )
        if operator_lane and operator_lane != DIRECTOR_LANE:
            return _build_background_dispatch_decision(
                lane=operator_lane,
                task_profile=task_profile,
                skill_refs=inferred_skill_refs,
                reason=f"deterministic:operator_follow_up:{operator_lane}",
            )

    owner_lane = _resolve_skill_owner_lane(
        skill_refs=inferred_skill_refs,
        task_profile=task_profile,
        recent_task_snapshot=recent_task_snapshot,
    )
    if owner_lane and owner_lane != DIRECTOR_LANE:
        return _build_background_dispatch_decision(
            lane=owner_lane,
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
            reason=f"deterministic:owner_lane:{owner_lane}",
        )

    if _looks_like_engineering_request(
        message=message,
        channel_prompt=channel_prompt,
    ):
        return _build_background_dispatch_decision(
            lane=ENGINEERING_LANE,
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
            reason="deterministic:engineering",
        )

    try:
        classified_route = _classify_ambiguous_conversation_lane(
            message=message,
            channel_prompt=channel_prompt,
            workspace=workspace,
        )
    except Exception:
        logger.debug("Lane classifier fallback failed", exc_info=True)
        classified_route = None

    classified_lane = None if classified_route is None else classified_route.get("lane")
    if classified_lane == DIRECTOR_LANE:
        return _build_inline_dispatch_decision(
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
            reason="llm_classifier:director",
        )
    if classified_lane in _KNOWN_LANES:
        return _build_background_dispatch_decision(
            lane=classified_lane,
            task_profile=task_profile,
            skill_refs=inferred_skill_refs,
            reason=f"llm_classifier:{classified_lane}",
        )

    return _build_inline_dispatch_decision(
        task_profile=task_profile,
        skill_refs=inferred_skill_refs,
        reason="llm_classifier_fallback:director",
    )


def resolve_conversation_route(
    *,
    message: str,
    channel_prompt: str | None = None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    workspace: str | None = None,
) -> ConversationRoute:
    """Resolve one deterministic-first lane decision for a conversation turn."""
    decision = resolve_dispatch_decision(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    return ConversationRoute(
        lane=decision.lane,
        task_profile=decision.task_profile,
        skill_refs=decision.skill_refs,
        reason=decision.reason,
    )


def _recent_snapshot_skill_refs(
    recent_task_snapshot: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(recent_task_snapshot, Mapping):
        return []
    metadata = recent_task_snapshot.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    raw_refs = metadata.get("skill_refs")
    if not isinstance(raw_refs, (list, tuple, set)):
        return []
    return _normalize_skill_refs(raw_refs)


def _resolve_worker_skill_refs(
    *,
    decision: DispatchDecision,
    recent_task_snapshot: Mapping[str, Any] | None = None,
) -> list[str]:
    normalized_skill_refs = _normalize_skill_refs(decision.skill_refs)
    if normalized_skill_refs:
        return normalized_skill_refs
    return _recent_snapshot_skill_refs(recent_task_snapshot)


def _resolve_worker_lane_for_dispatch(decision: DispatchDecision) -> str | None:
    if decision.target_job_lane:
        return decision.target_job_lane
    if decision.dispatch_mode is DispatchMode.DELEGATE_BACKGROUND and decision.lane != DIRECTOR_LANE:
        return decision.lane
    return None


def _build_dispatch_metadata(
    *,
    decision: DispatchDecision,
    worker_lane: str | None,
    worker_skill_refs: list[str],
) -> dict[str, Any]:
    return {
        "lane": decision.lane,
        "dispatch_mode": decision.dispatch_mode.value,
        "target_job_lane": decision.target_job_lane,
        "worker_lane": worker_lane,
        "skill_refs": list(decision.skill_refs),
        "worker_skill_refs": list(worker_skill_refs),
        "needs_clarification": decision.needs_clarification,
        "reason": decision.reason,
    }


def _build_workflow_dispatch_contract(
    *,
    decision: DispatchDecision,
    worker_lane: str | None,
) -> dict[str, Any]:
    return {
        "role": TaskRole.COORDINATOR.value,
        "mode": decision.dispatch_mode.value,
        "target_job_lane": decision.target_job_lane,
        "worker_lane": worker_lane,
        "needs_clarification": decision.needs_clarification,
    }


def _infer_gateway_skill_refs(*, message: str, channel_prompt: str | None = None) -> list[str]:
    """Infer narrow skill refs for gateway-authored workflows."""

    haystack = _normalize_text_haystack(message, channel_prompt)
    inferred: list[str] = []
    if any(hint in haystack for hint in _WECHAT_PUBLISH_HINTS):
        inferred.append(_WECHAT_PUBLISHER_SKILL_REF)
    if any(hint in haystack for hint in _IMAGEGEN_HINTS):
        inferred.append(_IMAGEGEN_SKILL_REF)
    if any(hint in haystack for hint in _DEEP_RESEARCH_HINTS):
        inferred.append(_DEEP_RESEARCH_SKILL_REF)
    if (
        any(hint in haystack for hint in _CONFIG_ADMIN_ACTION_HINTS)
        and any(hint in haystack for hint in _CONFIG_ADMIN_TARGET_HINTS)
        and _MENTE_CONFIG_ADMIN_SKILL_REF not in inferred
    ):
        inferred.append(_MENTE_CONFIG_ADMIN_SKILL_REF)
    return inferred


def _resolve_gateway_task_profile(skill_refs: list[str]) -> str | None:
    """Return a narrow execution profile for gateway requests when recognized."""

    if _WECHAT_PUBLISHER_SKILL_REF in skill_refs:
        return _CONTENT_PUBLISHING_TASK_PROFILE
    if _DEEP_RESEARCH_SKILL_REF in skill_refs:
        return _DEEP_RESEARCH_TASK_PROFILE
    if _MENTE_CONFIG_ADMIN_SKILL_REF in skill_refs:
        return _CONFIG_ADMIN_TASK_PROFILE
    return None


def resolve_gateway_task_host_timeout_seconds(
    *,
    message: str,
    channel_prompt: str | None = None,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    content_publishing_timeout_seconds: float | int | None = None,
) -> float | None:
    """Return a host-side timeout for recognized gateway task profiles."""

    skill_refs = _infer_gateway_skill_refs(message=message, channel_prompt=channel_prompt)
    if looks_like_gateway_recent_artifact_delivery_request(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
    ):
        return _ARTIFACT_DELIVERY_HOST_TIMEOUT_SECONDS
    task_profile = _resolve_gateway_task_profile(skill_refs)
    if task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        if content_publishing_timeout_seconds is None:
            return None
        try:
            timeout = float(content_publishing_timeout_seconds)
        except (TypeError, ValueError):
            return None
        return timeout if timeout > 0 else None
    return None


def resolve_gateway_task_notify_interval_seconds(
    *,
    message: str,
    configured_seconds: float | int | None,
    channel_prompt: str | None = None,
) -> float | None:
    """Return the effective progress-heartbeat interval for gateway tasks."""

    if configured_seconds is None:
        return None
    interval = float(configured_seconds)
    if interval <= 0:
        return None

    skill_refs = _infer_gateway_skill_refs(message=message, channel_prompt=channel_prompt)
    task_profile = _resolve_gateway_task_profile(skill_refs)
    if task_profile == _DEEP_RESEARCH_TASK_PROFILE:
        return min(interval, _DEEP_RESEARCH_NOTIFY_INTERVAL_SECONDS)
    return interval


def _resolve_gateway_workspace(
    *,
    workspace: str | None,
    message: str,
    channel_prompt: str | None,
    skill_refs: list[str],
    task_profile: str | None = None,
    lane: str | None = None,
) -> str:
    """Resolve one default workspace for a routed gateway/TUI task."""

    resolved_workspace = _resolve_workspace(workspace)
    effective_task_profile = task_profile or _resolve_gateway_task_profile(skill_refs)
    if _has_explicit_workspace_override(workspace):
        return resolved_workspace

    if effective_task_profile in {
        _CONTENT_PUBLISHING_TASK_PROFILE,
        _ARTIFACT_DELIVERY_TASK_PROFILE,
        _CONFIG_ADMIN_TASK_PROFILE,
    }:
        return _prefer_repo_workspace_for_scoped_task(resolved_workspace)

    effective_lane = _normalize_active_lane_hint(lane) or _resolve_lane_from_task_profile(
        effective_task_profile
    )
    if effective_lane:
        return _ensure_lane_workspace(effective_lane)
    return resolved_workspace


def _has_explicit_workspace_override(workspace: str | None) -> bool:
    explicit_workspace = str(workspace or "").strip()
    return bool(explicit_workspace and explicit_workspace not in {".", "auto", "cwd"})


def _prefer_repo_workspace_for_scoped_task(resolved_workspace: str) -> str:
    current_cwd = os.getcwd()
    home_dir = str(Path.home())
    current_cwd_path = Path(current_cwd)
    if resolved_workspace in {"", ".", "auto", "cwd"}:
        return current_cwd
    if resolved_workspace == home_dir and current_cwd and current_cwd != home_dir:
        return current_cwd
    if current_cwd and current_cwd != resolved_workspace and (current_cwd_path / ".git").exists():
        return current_cwd
    return resolved_workspace


def _ensure_lane_workspace(lane: str) -> str:
    workspace_dir = get_mente_home() / f"workspace-{lane}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return str(workspace_dir)


def _resolve_tool_policy(
    *,
    source: str,
    task_type: str,
    task_profile: str | None = None,
) -> dict[str, object]:
    """Resolve a deterministic Mente-owned tool exposure policy."""
    kwargs: dict[str, object] = {
        "source": source,
        "task_type": task_type,
    }
    if task_profile is not None:
        kwargs["task_profile"] = task_profile
    return resolve_tool_exposure_policy(
        **kwargs,
    ).as_metadata()


def _build_task_repository() -> SQLiteTaskRepository:
    """Create the default persistent task repository."""
    return SQLiteTaskRepository()


def _build_memory_repository() -> SQLiteMemoryRepository:
    """Create the default persistent memory repository."""
    return SQLiteMemoryRepository()


def _resolve_runtime_config_for_workspace(workspace: str) -> RuntimeConfig:
    """Resolve the private runtime config for a Mente workspace."""
    return resolve_runtime_config(workspace)


def _build_kernel_adapter(
    workspace: str,
    runtime_config: RuntimeConfig | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
) -> CodexKernelAdapter:
    """Create the default Codex-backed kernel adapter."""
    return CodexExecutor(
        runtime_config=runtime_config or _resolve_runtime_config_for_workspace(workspace),
        memory_repository=memory_repository,
        event_callback=event_callback,
        cancel_event=cancel_event,
    )


def _build_orchestrator(
    workspace: str,
    repository,
    memory_repository: SQLiteMemoryRepository | None = None,
    executor: Executor | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
) -> Orchestrator:
    """Create the default Phase 2 orchestrator stack."""
    memory_repository = memory_repository or _build_memory_repository()
    return Orchestrator(
        repository=repository,
        context_builder=ContextBuilder(
            default_workspace=workspace,
            memory_repository=memory_repository,
            memory_limit=5,
        ),
        executor=executor
        or _build_kernel_adapter(
            workspace,
            memory_repository=memory_repository,
            event_callback=event_callback,
            cancel_event=cancel_event,
        ),
        memory_repository=memory_repository,
        memory_promoter=MemoryPromoter(),
    )


def _run_task(task: Task) -> ExecutionResult:
    """Run a task through the default Phase 2 runtime and close resources."""
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        return _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
        ).run(task)
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def _is_unbacked_prior_claim(candidate: str) -> bool:
    """Return True when a candidate claims prior preferences without provided memory."""
    normalized = " ".join(candidate.lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "earlier",
            "previously",
            "previous ",
            "prior ",
            "before",
            "already mentioned",
        )
    )


class _APIServerIsolationExecutor(CodexKernelAdapter):
    """Wrap Codex execution with empty-session isolation for API server turns."""

    def __init__(
        self,
        inner: CodexKernelAdapter | None = None,
        workspace: str | None = None,
        runtime_config: RuntimeConfig | None = None,
        memory_repository: SQLiteMemoryRepository | None = None,
    ) -> None:
        self._inner = inner or _build_kernel_adapter(
            workspace or ".",
            runtime_config=runtime_config,
            memory_repository=memory_repository,
        )

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        return self._inner.build_request_payload(request)

    def supports_kernel_sessions(self) -> bool:
        return self._inner.supports_kernel_sessions()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        result = self._inner.execute(request)
        if request.memory_facts:
            return result

        result.memory_candidates = [
            candidate
            for candidate in result.memory_candidates
            if not _is_unbacked_prior_claim(candidate)
        ]
        return result


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip unstable fields from gateway history before serialization."""
    normalized: list[dict[str, Any]] = []
    for message in history or []:
        if not isinstance(message, dict):
            continue
        entry = {
            key: value
            for key, value in sorted(message.items())
            if key != "timestamp"
        }
        normalized.append(entry)
    return normalized


def _build_conversation_history_fact(history: list[dict[str, Any]]) -> str | None:
    """Serialize conversation history deterministically for task memory facts."""
    if not history:
        return None
    serialized_history = json.dumps(
        _normalize_history(history),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"Conversation history (JSON):\n{serialized_history}"


def _looks_like_continue_task_request(message: str) -> bool:
    """Return whether the latest user message likely asks to resume prior work."""
    normalized = " ".join(str(message or "").strip().lower().split())
    if not normalized:
        return False
    phrases = (
        "continue",
        "resume",
        "pick up",
        "继续",
        "接着",
        "继续任务",
        "继续刚才",
        "继续上一个",
        "刚才的任务",
        "上一条任务",
        "上一个任务",
    )
    return any(phrase in normalized for phrase in phrases)


def _looks_like_status_follow_up_request(message: str) -> bool:
    """Return whether the latest user message asks for current task status only."""
    normalized = " ".join(str(message or "").strip().lower().split())
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _STATUS_FOLLOW_UP_HINTS)


def _resolve_status_follow_up_target_lane(
    *,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
) -> str | None:
    candidate = _normalize_active_lane_hint(active_lane)
    if candidate and candidate != DIRECTOR_LANE:
        return candidate
    snapshot_lane = _resolve_recent_task_snapshot_lane(recent_task_snapshot)
    if snapshot_lane and snapshot_lane != DIRECTOR_LANE:
        return snapshot_lane
    return None


def looks_like_gateway_status_follow_up_request(
    *,
    message: str,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
) -> bool:
    """Return whether one status follow-up should use thin director-lane handling."""
    return _looks_like_status_follow_up_request(message) and bool(
        _resolve_status_follow_up_target_lane(
            recent_task_snapshot=recent_task_snapshot,
            active_lane=active_lane,
        )
    )


def _build_recent_task_snapshot_fact(snapshot: Mapping[str, Any]) -> str | None:
    """Render one bounded short-term task snapshot as a memory fact."""
    user_request = str(snapshot.get("user_request") or "").strip()
    if not user_request:
        return None
    status = str(snapshot.get("status") or "").strip() or "running"
    assistant_summary = str(snapshot.get("assistant_summary") or "").strip()
    follow_up_tasks = [
        str(item).strip()
        for item in snapshot.get("follow_up_tasks") or []
        if str(item).strip()
    ]
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), Mapping) else {}
    lines = [
        "Recent active task snapshot:",
        f"- Status: {status}",
        f"- Original request: {user_request}",
    ]
    if assistant_summary:
        lines.append(f"- Latest progress summary: {assistant_summary}")
    if follow_up_tasks:
        lines.append(
            "- Pending follow-up: " + "; ".join(follow_up_tasks[:3])
        )
    task_profile = str(metadata.get("task_profile") or "").strip()
    if task_profile:
        lines.append(f"- Task profile: {task_profile}")
    artifact_paths = _recent_snapshot_artifacts(snapshot)
    if artifact_paths:
        lines.append("- Recent artifacts: " + "; ".join(artifact_paths[:5]))
    operator_capsule = _recent_snapshot_operator_capsule(snapshot)
    if operator_capsule:
        skill_entrypoint = str(operator_capsule.get("skill_entrypoint") or "").strip()
        if skill_entrypoint:
            lines.append(f"- Preferred entrypoint: {skill_entrypoint}")
        naming_template = str(operator_capsule.get("naming_template") or "").strip()
        if naming_template:
            lines.append(f"- Naming template: {naming_template}")
        allowed_roots = [
            str(item).strip()
            for item in operator_capsule.get("allowed_roots") or []
            if str(item).strip()
        ]
        if allowed_roots:
            lines.append("- Allowed roots: " + "; ".join(allowed_roots[:4]))
        next_actions = [
            str(item).strip()
            for item in operator_capsule.get("next_actions") or []
            if str(item).strip()
        ]
        if next_actions:
            lines.append("- Preferred next actions: " + "; ".join(next_actions[:4]))
    lines.append(
        "- If the user asks to continue or resume the previous task, continue from this snapshot instead of claiming the prior task is unavailable."
    )
    return "\n".join(lines)


def _build_active_lane_handoff_capsule_fact(snapshot: Mapping[str, Any]) -> str | None:
    """Render one thinner lane handoff capsule for status-style follow-up turns."""
    user_request = str(snapshot.get("user_request") or "").strip()
    assistant_summary = str(snapshot.get("assistant_summary") or "").strip()
    status = str(snapshot.get("status") or "").strip() or "running"
    follow_up_tasks = [
        str(item).strip()
        for item in snapshot.get("follow_up_tasks") or []
        if str(item).strip()
    ]
    artifact_paths = _recent_snapshot_artifacts(snapshot)
    lane = _resolve_recent_task_snapshot_lane(snapshot) or DIRECTOR_LANE
    if not (user_request or assistant_summary or follow_up_tasks or artifact_paths):
        return None
    lines = [
        "Active lane handoff capsule:",
        f"- Lane: {lane}",
        f"- Status: {status}",
    ]
    if assistant_summary:
        lines.append(f"- Latest summary: {assistant_summary}")
    if follow_up_tasks:
        lines.append("- Pending next steps: " + "; ".join(follow_up_tasks[:3]))
    if artifact_paths:
        lines.append("- Recent artifacts: " + "; ".join(artifact_paths[:5]))
    if user_request:
        lines.append(f"- Original request: {user_request}")
    lines.append(
        "- Answer the user's status question directly from this capsule unless they explicitly ask to continue execution."
    )
    return "\n".join(lines)


def _build_fast_path_result(task: Task) -> ExecutionResult | None:
    """Return a local short-circuit result for narrow simple conversation turns."""

    if task.task_type != "conversation":
        return None
    if (
        task.execution_mode is not ExecutionMode.STATELESS
        or task.skill_refs
        or task.worker_skill_refs
    ):
        return None

    fast_path_kind = ""
    summary = ""
    model_name = ""
    remember_facts = _resolve_remember_intent_facts(
        message=task.user_request,
        context_facts=task.memory_facts,
        workspace=task.workspace,
    )

    if remember_facts:
        enabled, _reason = _remember_intent_direct_write_enabled(task)
        if not enabled:
            return None
        fast_path_kind = "remember_intent_direct_write"
        summary = f"已写入记忆：{remember_facts[0]}"
        task.metadata["remember_intent_direct_write"] = {
            "facts": remember_facts,
            "source": "fast_path",
        }
    elif _looks_like_fast_model_identity_request(task.user_request):
        try:
            runtime_config = _resolve_runtime_config_for_workspace(task.workspace or ".")
        except Exception:
            return None
        fast_path_kind = "model_identity"
        model_name = str(runtime_config.model_runtime.model or "").strip()
        summary = _canonical_model_identity_summary(model_name or None)
    elif _looks_like_fast_identity_request(task.user_request):
        fast_path_kind = "identity"
        summary = _CANONICAL_MENTE_IDENTITY_SUMMARY
    else:
        return None

    metadata: dict[str, Any] = {
        "kind": fast_path_kind,
        "source": str(task.metadata.get("source") or "").strip() or "unknown",
    }
    if model_name:
        metadata["model"] = model_name
    memory_candidates = remember_facts if fast_path_kind == "remember_intent_direct_write" else []
    return ExecutionResult(
        status="success",
        summary=summary,
        memory_candidates=memory_candidates,
        metadata={"fast_path": metadata},
    )


def _persist_fast_path_task_result(task: Task, result: ExecutionResult) -> ExecutionResult:
    """Persist one fast-path conversation turn without booting the full runtime."""

    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        fast_path_metadata = result.metadata.get("fast_path")
        if isinstance(fast_path_metadata, dict):
            task.metadata["fast_path"] = dict(fast_path_metadata)
            if fast_path_metadata.get("kind") == "remember_intent_direct_write":
                memory_review_artifact = build_memory_review_artifact(task, result)
                task.metadata["memory_review_artifact"] = memory_review_artifact
                result.metadata["memory_review_artifact"] = memory_review_artifact
                _persist_remember_intent_direct_write(
                    task=task,
                    result=result,
                    repository=repository,
                    memory_repository=memory_repository,
                )
                source = str(task.metadata.get("source") or "").strip()
                workflow_gate, _ = review_capability_gate(
                    source=source,
                    task_type=task.task_type,
                    metadata=task.metadata,
                    capability="session_synthesis",
                )
                if workflow_gate is True:
                    session_synthesis_artifact = build_session_synthesis_artifact(task, result)
                    task.metadata["session_synthesis_artifact"] = session_synthesis_artifact
                    result.metadata["session_synthesis_artifact"] = session_synthesis_artifact
                    repository.save(task)
                _apply_post_turn_conversation_workflow_contract(
                    task=task,
                    result=result,
                    repository=repository,
                    memory_repository=memory_repository,
                )
                memory_review = result.metadata.get("memory_review")
                if isinstance(memory_review, dict):
                    task.metadata["memory_review"] = dict(memory_review)
        task.metadata["assistant_summary"] = result.summary
        task.status = TaskStatus.SUCCEEDED
        repository.save(task)
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def _resolve_final_task_status(result: ExecutionResult) -> TaskStatus:
    """Map one executor result onto the persisted task lifecycle state."""

    if result.status == "success":
        return TaskStatus.SUCCEEDED
    if result.status == "blocked":
        return TaskStatus.BLOCKED
    return TaskStatus.FAILED


def _normalize_skill_refs(skill_refs: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize caller-provided skill refs into a stable list."""
    normalized: list[str] = []
    for raw_ref in skill_refs or ():
        candidate = str(raw_ref).strip()
        if candidate:
            normalized.append(candidate)
    return normalized


def normalize_api_execution_continuity(
    *,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
) -> tuple[ExecutionMode, ExecutionSession | None]:
    """Normalize one caller continuity request into the canonical bridge contract."""
    normalized_mode = ExecutionMode.STATELESS
    if execution_mode not in (None, ""):
        candidate = str(execution_mode).strip().lower()
        if candidate == "session":
            candidate = ExecutionMode.SESSIONFUL.value
        normalized_mode = ExecutionMode(candidate)

    normalized_session: ExecutionSession | None = None
    if execution_session is not None:
        try:
            normalized_session = ExecutionSession.model_validate(execution_session)
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            msg = str(first_error.get("msg") or str(exc))
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, ") :]
            raise ValueError(msg) from exc
        if execution_mode in (None, ""):
            normalized_mode = ExecutionMode.SESSIONFUL

    if normalized_mode is ExecutionMode.STATELESS and normalized_session is not None:
        msg = "execution_session is not allowed when execution_mode=stateless"
        raise ValueError(msg)

    return normalized_mode, normalized_session


def extract_execution_session_handoff(result: ExecutionResult) -> dict[str, Any] | None:
    """Return the canonical continuity handoff payload from a Mente execution result."""
    payload = result.metadata.get("execution_session")
    if not isinstance(payload, dict):
        return None
    return dict(payload)


def build_cron_task(
    *,
    job: dict[str, Any],
    prompt: str,
    session_id: str,
    workspace: str | None = None,
) -> Task:
    """Create a normalized Mente task for a cron execution."""
    resolved_workspace = _resolve_workspace(workspace)
    schedule = job.get("schedule_display") or job.get("schedule") or "N/A"
    job_id = str(job.get("id") or "cron_job")
    job_name = str(job.get("name") or job_id)

    return Task(
        task_id=f"mente_cron_{job_id}_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="cron",
        objective=f"Execute scheduled job '{job_name}' and return a concise result.",
        user_request=prompt,
        workspace=resolved_workspace,
        constraints=[
            f"Cron job ID: {job_id}",
            f"Cron job name: {job_name}",
            f"Cron schedule: {schedule}",
        ],
        acceptance_criteria=[
            "Return a concise user-facing result for cron delivery.",
        ],
        execution_mode=ExecutionMode.STATELESS,
        metadata={
            "source": "cron",
            "tool_policy": _resolve_tool_policy(source="cron", task_type="cron"),
            "job": {
                "id": job.get("id"),
                "name": job.get("name"),
                "deliver": job.get("deliver"),
                "schedule": job.get("schedule"),
                "schedule_display": job.get("schedule_display"),
                "model": job.get("model"),
                "provider": job.get("provider"),
                "workdir": job.get("workdir"),
            },
        },
    )


def run_cron_task(
    *,
    job: dict[str, Any],
    prompt: str,
    session_id: str,
    workspace: str | None = None,
) -> ExecutionResult:
    """Execute a cron task through Mente."""
    task = build_cron_task(
        job=job,
        prompt=prompt,
        session_id=session_id,
        workspace=workspace,
    )
    return _run_task(task)


def build_gateway_task(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    decision: DispatchDecision | None = None,
    task_id: str | None = None,
) -> Task:
    """Create a normalized Mente task for a gateway turn."""
    decision = decision or resolve_dispatch_decision(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    inferred_skill_refs = list(decision.skill_refs)
    task_profile = decision.task_profile
    lane = decision.lane
    worker_lane = _resolve_worker_lane_for_dispatch(decision)
    worker_skill_refs = _resolve_worker_skill_refs(
        decision=decision,
        recent_task_snapshot=recent_task_snapshot,
    )
    resolved_workspace = _resolve_gateway_workspace(
        workspace=workspace,
        message=message,
        channel_prompt=channel_prompt,
        skill_refs=inferred_skill_refs,
        task_profile=task_profile,
        lane=lane,
    )
    memory_facts: list[str] = []
    artifact_inputs = _recent_snapshot_artifacts(recent_task_snapshot)
    operator_follow_up = looks_like_gateway_recent_operator_follow_up_request(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
    )
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    if context_prompt:
        memory_facts.append(f"Session context:\n{context_prompt}")
    if channel_prompt:
        memory_facts.append(f"Channel prompt:\n{channel_prompt}")
    history_fact = _build_conversation_history_fact(history)
    if history_fact and replay_history_in_memory_facts:
        memory_facts.append(history_fact)
    if recent_task_snapshot and looks_like_gateway_status_follow_up_request(
        message=message,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
    ):
        capsule_fact = _build_active_lane_handoff_capsule_fact(recent_task_snapshot)
        if capsule_fact:
            memory_facts.append(capsule_fact)
    elif recent_task_snapshot and (
        _looks_like_continue_task_request(message)
        or task_profile == _ARTIFACT_DELIVERY_TASK_PROFILE
        or operator_follow_up
    ):
        snapshot_fact = _build_recent_task_snapshot_fact(recent_task_snapshot)
        if snapshot_fact:
            memory_facts.append(snapshot_fact)

    platform = source.platform.value if hasattr(source.platform, "value") else str(source.platform)
    metadata = {
        "source": "gateway",
        "tool_policy": _resolve_tool_policy(
            source="gateway",
            task_type="conversation",
            task_profile=task_profile,
        ),
        "workflow_contract": build_conversation_workflow_contract(
            source="gateway",
            skill_refs=inferred_skill_refs,
            execution_mode=normalized_execution_mode.value,
            lane=lane,
        ),
        "lane": lane,
        "dispatch_decision": _build_dispatch_metadata(
            decision=decision,
            worker_lane=worker_lane,
            worker_skill_refs=worker_skill_refs,
        ),
        "platform": platform,
        "session_key": session_key,
        "user_id": getattr(source, "user_id", None),
        "user_name": getattr(source, "user_name", None),
        "chat_id": getattr(source, "chat_id", None),
        "chat_name": getattr(source, "chat_name", None),
        "chat_type": getattr(source, "chat_type", None),
        "thread_id": getattr(source, "thread_id", None),
        "skill_refs": list(inferred_skill_refs),
    }
    operator_capsule = _resolve_task_operator_capsule(
        task_profile=task_profile,
        skill_refs=inferred_skill_refs,
        workspace=resolved_workspace,
        recent_task_snapshot=recent_task_snapshot,
        artifact_paths=artifact_inputs,
        next_actions=_recent_snapshot_follow_up_tasks(recent_task_snapshot),
    )
    if operator_capsule:
        metadata["operator_capsule"] = operator_capsule
    metadata["workflow_contract"]["dispatch"] = _build_workflow_dispatch_contract(
        decision=decision,
        worker_lane=worker_lane,
    )
    if task_profile is not None:
        metadata["task_profile"] = task_profile
    if fallback_history_fact:
        metadata["fallback_history_fact"] = fallback_history_fact

    constraints: list[str] = []
    acceptance_criteria = [
        "Respond directly to the latest user message.",
    ]
    objective = "Continue the active conversation and answer the latest user message."
    if decision.needs_clarification:
        objective = "Clarify the exact skill or worker owner needed before dispatching the user's request."
        constraints.append(
            "Do not start specialist execution until one missing skill or owner detail is clarified."
        )
        acceptance_criteria.append(
            "Ask one targeted clarification that identifies the missing skill or owning lane needed to continue."
        )
    if task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        memory_facts.append(_build_content_publishing_workflow_brief())
        memory_facts.append(
            _build_content_publishing_output_plan(
                workspace=resolved_workspace,
                session_id=session_id,
            )
        )
        memory_facts.append(
            _build_content_publishing_entrypoint_brief(
                workspace=resolved_workspace,
                session_id=session_id,
            )
        )
        constraints.append(
            "Prefer the active workspace and provided conversation context; avoid broad scans outside the workspace unless the user explicitly asks."
        )
        constraints.append(
            "Do not scan the full repository or home directory just to rediscover the publishing process."
        )
        constraints.append(
            f"Treat {_WECHAT_PUBLISH_VISIBLE_TOOL} as the authoritative publish entrypoint for this task; do not replace it with ad hoc script reconstruction."
        )
        acceptance_criteria.append(
            f"If the user asked for a WeChat draft workflow, create the requested article/assets in the workspace and use {_WECHAT_PUBLISH_VISIBLE_TOOL} to publish the draft."
        )
        acceptance_criteria.append(
            "Use the provided skills directly instead of rediscovering the workflow."
        )
        acceptance_criteria.append(
            "Prefer producing the requested article and assets immediately; inspect only a small number of directly relevant files when necessary."
        )
    if task_profile == _ARTIFACT_DELIVERY_TASK_PROFILE:
        memory_facts.append(_build_artifact_delivery_workflow_brief())
        if artifact_inputs:
            memory_facts.append(_build_artifact_delivery_inputs_fact(artifact_inputs))
        constraints.append(
            "Use the provided artifact paths directly when fulfilling this follow-up delivery request."
        )
        constraints.append(
            "Do not scan the full repository, skill tree, or home directory just to rediscover recently generated files."
        )
        acceptance_criteria.append(
            "Upload or share the provided artifact files for the user-requested destination before replying, unless a concrete blocker prevents delivery."
        )
        acceptance_criteria.append(
            "Final reply must identify which artifact paths were delivered and include links or the precise blocker."
        )
    if operator_follow_up and operator_capsule:
        constraints.append(
            "Use the recent task capsule entrypoints and artifact paths directly before exploring unrelated files or directories."
        )
        constraints.append(
            "Keep any verification, rename, regenerate, or upload work scoped to the allowed roots captured in the recent task capsule unless a concrete blocker requires more."
        )
        if str(operator_capsule.get("naming_template") or "").strip():
            acceptance_criteria.append(
                "Follow the recent task capsule naming template when renaming or regenerating report artifacts."
            )
    if task_profile == _CONFIG_ADMIN_TASK_PROFILE:
        memory_facts.append(_build_config_admin_workflow_brief())
        constraints.append(
            "Resolve the active config, env, or auth path first for Mente config/admin tasks; avoid repository-wide scans unless a concrete blocker requires them."
        )
        constraints.append(
            "Read only the directly relevant config, env, or auth files until a concrete blocker requires more context."
        )
        acceptance_criteria.append(
            "Use the provided config-admin skill directly instead of rediscovering the workflow."
        )
        acceptance_criteria.append(
            "If any settings change, the final reply must state the exact file, key, and restart action performed, with secrets redacted."
        )
    if _DEEP_RESEARCH_SKILL_REF in inferred_skill_refs:
        memory_facts.append(_build_deep_research_workflow_brief())
        memory_facts.append(_build_deep_research_execution_plan(workspace=resolved_workspace))
        memory_facts.append(_build_deep_research_output_plan())
        constraints.append(
            "Do not stop after intermediate findings; complete the full deep-research report workflow in this turn."
        )
        constraints.append(
            "Do not ask whether the user wants a formal report when the request already asked for deep research."
        )
        acceptance_criteria.append(
            "Generate the final deep-research report artifacts in Markdown, HTML, and DOCX formats under the MENTE_HOME deep-research output root."
        )
        acceptance_criteria.append(
            "Final reply must summarize the conclusion and list the generated report artifact paths."
        )
        acceptance_criteria.append(
            "Treat the task as incomplete until the report artifacts exist, unless a concrete blocker prevents generation."
        )

    return Task(
        task_id=task_id or f"mente_gateway_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective=objective,
        user_request=message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        skill_refs=inferred_skill_refs,
        artifacts_in=artifact_inputs,
        constraints=constraints,
        acceptance_criteria=acceptance_criteria,
        role=TaskRole.COORDINATOR,
        dispatch_mode=decision.dispatch_mode,
        worker_lane=worker_lane,
        worker_skill_refs=worker_skill_refs,
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata=metadata,
    )


def build_coordinator_task(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    decision: DispatchDecision | None = None,
    task_id: str | None = None,
    job_id: str | None = None,
) -> Task:
    """Create the thin coordinator task for one gateway ingress turn."""
    decision = decision or resolve_dispatch_decision(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    inferred_skill_refs = list(decision.skill_refs)
    task_profile = decision.task_profile
    worker_lane = _resolve_worker_lane_for_dispatch(decision)
    worker_skill_refs = _resolve_worker_skill_refs(
        decision=decision,
        recent_task_snapshot=recent_task_snapshot,
    )
    resolved_workspace = _resolve_gateway_workspace(
        workspace=workspace,
        message=message,
        channel_prompt=channel_prompt,
        skill_refs=inferred_skill_refs,
        task_profile=task_profile,
        lane=worker_lane or DIRECTOR_LANE,
    )
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    memory_facts: list[str] = []
    operator_follow_up = looks_like_gateway_recent_operator_follow_up_request(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
    )
    if context_prompt:
        memory_facts.append(f"Session context:\n{context_prompt}")
    if channel_prompt:
        memory_facts.append(f"Channel prompt:\n{channel_prompt}")
    history_fact = _build_conversation_history_fact(history)
    if history_fact and replay_history_in_memory_facts:
        memory_facts.append(history_fact)
    if recent_task_snapshot and looks_like_gateway_status_follow_up_request(
        message=message,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
    ):
        capsule_fact = _build_active_lane_handoff_capsule_fact(recent_task_snapshot)
        if capsule_fact:
            memory_facts.append(capsule_fact)
    elif recent_task_snapshot and (
        _looks_like_continue_task_request(message)
        or task_profile == _ARTIFACT_DELIVERY_TASK_PROFILE
        or operator_follow_up
    ):
        snapshot_fact = _build_recent_task_snapshot_fact(recent_task_snapshot)
        if snapshot_fact:
            memory_facts.append(snapshot_fact)

    dispatch_summary_lines = [
        "Coordinator dispatch plan:",
        f"- Mode: {decision.dispatch_mode.value}",
        f"- Resolved lane: {decision.lane}",
        f"- Worker lane: {worker_lane or 'none'}",
    ]
    if task_profile:
        dispatch_summary_lines.append(f"- Task profile: {task_profile}")
    if worker_skill_refs:
        dispatch_summary_lines.append("- Worker skill refs: " + ", ".join(worker_skill_refs))
    if decision.reason:
        dispatch_summary_lines.append(f"- Reason: {decision.reason}")
    memory_facts.append("\n".join(dispatch_summary_lines))

    platform = source.platform.value if hasattr(source.platform, "value") else str(source.platform)
    metadata = {
        "source": "gateway",
        "job_id": job_id,
        "tool_policy": _resolve_tool_policy(
            source="gateway",
            task_type="conversation",
        ),
        "workflow_contract": build_conversation_workflow_contract(
            source="gateway",
            skill_refs=inferred_skill_refs,
            execution_mode=normalized_execution_mode.value,
            lane=DIRECTOR_LANE,
        ),
        "lane": DIRECTOR_LANE,
        "dispatch_decision": _build_dispatch_metadata(
            decision=decision,
            worker_lane=worker_lane,
            worker_skill_refs=worker_skill_refs,
        ),
        "platform": platform,
        "session_key": session_key,
        "user_id": getattr(source, "user_id", None),
        "user_name": getattr(source, "user_name", None),
        "chat_id": getattr(source, "chat_id", None),
        "chat_name": getattr(source, "chat_name", None),
        "chat_type": getattr(source, "chat_type", None),
        "thread_id": getattr(source, "thread_id", None),
        "skill_refs": list(inferred_skill_refs),
    }
    operator_capsule = _resolve_task_operator_capsule(
        task_profile=task_profile,
        skill_refs=inferred_skill_refs,
        workspace=resolved_workspace,
        recent_task_snapshot=recent_task_snapshot,
        artifact_paths=_recent_snapshot_artifacts(recent_task_snapshot),
        next_actions=_recent_snapshot_follow_up_tasks(recent_task_snapshot),
    )
    if operator_capsule:
        metadata["operator_capsule"] = operator_capsule
    metadata["workflow_contract"]["dispatch"] = _build_workflow_dispatch_contract(
        decision=decision,
        worker_lane=worker_lane,
    )
    if task_profile is not None:
        metadata["task_profile"] = task_profile
    if fallback_history_fact:
        metadata["fallback_history_fact"] = fallback_history_fact

    constraints: list[str] = []
    acceptance_criteria = [
        "Respond directly to the latest user message.",
    ]
    objective = "Continue the active conversation and answer the latest user message."
    if decision.needs_clarification:
        objective = "Clarify the exact skill or worker owner needed before dispatching the user's request."
        constraints.append(
            "Do not start specialist execution until one missing skill or owner detail is clarified."
        )
        acceptance_criteria.append(
            "Ask one targeted clarification that identifies the missing skill or owning lane needed to continue."
        )
    elif decision.dispatch_mode is DispatchMode.DELEGATE_BACKGROUND and worker_lane:
        objective = f"Coordinate delegation to the {worker_lane} worker, record the job, and stay ready for follow-up."
        constraints.append(
            "Do not perform heavy specialist execution yourself when a background worker will handle the task."
        )
        acceptance_criteria = [
            "Record the dispatch decision, job id, and worker lineage for this turn.",
            "Preserve enough context to answer later status or clarification follow-ups.",
        ]

    return Task(
        task_id=task_id or f"mente_gateway_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective=objective,
        user_request=message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        skill_refs=inferred_skill_refs,
        constraints=constraints,
        acceptance_criteria=acceptance_criteria,
        job_id=job_id,
        role=TaskRole.COORDINATOR,
        dispatch_mode=decision.dispatch_mode,
        worker_lane=worker_lane,
        worker_skill_refs=worker_skill_refs,
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata=metadata,
    )


def build_worker_task_from_dispatch(
    *,
    coordinator_task: Task,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    decision: DispatchDecision | None = None,
    task_id: str | None = None,
) -> Task | None:
    """Build the specialist worker task for one delegated gateway ingress turn."""
    decision = decision or resolve_dispatch_decision(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    worker_lane = _resolve_worker_lane_for_dispatch(decision)
    if decision.dispatch_mode is not DispatchMode.DELEGATE_BACKGROUND or not worker_lane:
        return None

    task = build_gateway_task(
        message=message,
        context_prompt=context_prompt,
        history=history,
        source=source,
        session_id=session_id,
        session_key=session_key,
        channel_prompt=channel_prompt,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        decision=decision,
        task_id=task_id,
    )
    # Background workers report progress and lifecycle through persisted job/task state.
    # They do not need gateway runtime continuity, and fail-closed to stateless execution
    # to avoid session-mode replay hazards in tool-heavy specialist runs.
    task.execution_mode = ExecutionMode.STATELESS
    task.execution_session = None
    task.role = TaskRole.WORKER
    task.parent_task_id = coordinator_task.task_id
    task.job_id = coordinator_task.job_id
    task.worker_lane = worker_lane
    task.worker_skill_refs = _resolve_worker_skill_refs(
        decision=decision,
        recent_task_snapshot=recent_task_snapshot,
    )
    task.metadata["job_id"] = task.job_id
    task.metadata["parent_task_id"] = task.parent_task_id
    workflow_contract = task.metadata.get("workflow_contract")
    if isinstance(workflow_contract, dict):
        workflow_contract["dispatch"] = {
            "role": TaskRole.WORKER.value,
            "mode": task.dispatch_mode.value,
            "target_job_lane": decision.target_job_lane,
            "worker_lane": worker_lane,
            "needs_clarification": False,
        }
    return task


def build_gateway_task_bundle(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    request_id: str | None = None,
) -> GatewayTaskBundle:
    """Build the coordinator task and optional worker task for one gateway turn."""
    decision = resolve_dispatch_decision(
        message=message,
        channel_prompt=channel_prompt,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    pending_worker_control = _resolve_pending_worker_control_payload(
        message=message,
        recent_task_snapshot=recent_task_snapshot,
    )
    request_id = str(
        request_id
        or (
            pending_worker_control.get("request_id")
            if isinstance(pending_worker_control, Mapping)
            else None
        )
        or uuid.uuid4().hex
    )
    worker_lane = _resolve_worker_lane_for_dispatch(decision)
    needs_worker = (
        decision.dispatch_mode is DispatchMode.DELEGATE_BACKGROUND
        and bool(worker_lane)
    )
    reserved_job_id = (
        str(pending_worker_control.get("job_id") or "").strip()
        if isinstance(pending_worker_control, Mapping)
        else ""
    )
    reserved_coordinator_task_id = (
        str(pending_worker_control.get("coordinator_task_id") or "").strip()
        if isinstance(pending_worker_control, Mapping)
        else ""
    )
    reserved_worker_task_id = (
        str(pending_worker_control.get("task_id") or "").strip()
        if isinstance(pending_worker_control, Mapping)
        else ""
    )
    job_id = reserved_job_id or (f"mente_gateway_job_{request_id}" if needs_worker else None)
    if needs_worker:
        coordinator_task_id = reserved_coordinator_task_id or f"mente_gateway_coordinator_{request_id}"
    else:
        coordinator_task_id = f"mente_gateway_{request_id}"
    coordinator_task = build_coordinator_task(
        message=message,
        context_prompt=context_prompt,
        history=history,
        source=source,
        session_id=session_id,
        session_key=session_key,
        channel_prompt=channel_prompt,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        decision=decision,
        task_id=coordinator_task_id,
        job_id=job_id,
    )

    worker_task = None
    if needs_worker:
        worker_task = build_worker_task_from_dispatch(
            coordinator_task=coordinator_task,
            message=message,
            context_prompt=context_prompt,
            history=history,
            source=source,
            session_id=session_id,
            session_key=session_key,
            channel_prompt=channel_prompt,
            workspace=workspace,
            execution_mode=execution_mode,
            execution_session=execution_session,
            fallback_history_fact=fallback_history_fact,
            replay_history_in_memory_facts=replay_history_in_memory_facts,
            recent_task_snapshot=recent_task_snapshot,
            active_lane=active_lane,
            decision=decision,
            task_id=reserved_worker_task_id or f"mente_gateway_{request_id}",
        )
        if worker_task is not None:
            coordinator_task.metadata["worker_task_id"] = worker_task.task_id
            coordinator_task.metadata["child_task_ids"] = [worker_task.task_id]
    if isinstance(pending_worker_control, Mapping):
        lineage = (
            pending_worker_control.get("supersedes")
            if isinstance(pending_worker_control.get("supersedes"), Mapping)
            else {}
        )
        control_metadata = {
            "control_contract": {
                "action": str(pending_worker_control.get("action") or "").strip() or "reprioritize",
                "mode": str(pending_worker_control.get("mode") or "").strip() or "supersede_worker",
                "runtime_mutation_supported": bool(
                    pending_worker_control.get("runtime_mutation_supported", False)
                ),
            },
            "supersedes": dict(lineage),
            "supersedes_job_id": str(
                pending_worker_control.get("supersedes_job_id")
                or lineage.get("job_id")
                or ""
            ).strip(),
            "supersedes_task_id": str(
                pending_worker_control.get("supersedes_task_id")
                or lineage.get("task_id")
                or ""
            ).strip(),
            "previous_job_id": str(
                pending_worker_control.get("previous_job_id")
                or lineage.get("job_id")
                or ""
            ).strip(),
            "previous_task_id": str(
                pending_worker_control.get("previous_task_id")
                or lineage.get("task_id")
                or ""
            ).strip(),
            "user_revision": str(pending_worker_control.get("user_revision") or "").strip(),
            "supersede_reason": str(pending_worker_control.get("reason") or "").strip() or "user_revision",
        }
        coordinator_task.metadata.update(control_metadata)
        if worker_task is not None:
            worker_task.metadata.update(control_metadata)

    return GatewayTaskBundle(
        coordinator_task=coordinator_task,
        worker_task=worker_task,
        decision=decision,
    )


def build_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    skill_refs: list[str] | tuple[str, ...] | None = None,
) -> Task:
    """Create a normalized Mente task for an API server request."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []
    normalized_skill_refs = _normalize_skill_refs(skill_refs)
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    history_fact = _build_conversation_history_fact(conversation_history)
    if history_fact:
        memory_facts.append(history_fact)

    return Task(
        task_id=f"mente_api_server_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective="Continue the active API conversation and answer the latest user message.",
        user_request=user_message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        skill_refs=normalized_skill_refs,
        acceptance_criteria=[
            "Respond directly to the latest user message.",
        ],
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata={
            "source": "api_server",
            "api_mode": api_mode,
            "tool_policy": _resolve_tool_policy(source="api_server", task_type="conversation"),
            "workflow_contract": build_api_server_conversation_workflow_contract(
                skill_refs=normalized_skill_refs,
                execution_mode=normalized_execution_mode.value,
            ),
        },
    )


def build_tui_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    request_id: str | None = None,
) -> Task:
    """Create a normalized Mente task for one TUI conversation turn."""
    memory_facts: list[str] = []
    decision = resolve_dispatch_decision(
        message=user_message,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        workspace=workspace,
    )
    pending_worker_control = _resolve_pending_worker_control_payload(
        message=user_message,
        recent_task_snapshot=recent_task_snapshot,
    )
    inferred_skill_refs = list(decision.skill_refs)
    task_profile = decision.task_profile
    lane = decision.lane
    worker_lane = _resolve_worker_lane_for_dispatch(decision)
    request_id = str(
        request_id
        or (
            pending_worker_control.get("request_id")
            if isinstance(pending_worker_control, Mapping)
            else None
        )
        or uuid.uuid4().hex
    )
    reserved_job_id = (
        str(pending_worker_control.get("job_id") or "").strip()
        if isinstance(pending_worker_control, Mapping)
        else ""
    )
    reserved_task_id = (
        str(pending_worker_control.get("task_id") or "").strip()
        if isinstance(pending_worker_control, Mapping)
        else ""
    )
    worker_skill_refs = _resolve_worker_skill_refs(
        decision=decision,
        recent_task_snapshot=recent_task_snapshot,
    )
    resolved_workspace = _resolve_gateway_workspace(
        workspace=workspace,
        message=user_message,
        channel_prompt=None,
        skill_refs=inferred_skill_refs,
        task_profile=task_profile,
        lane=lane,
    )
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    operator_follow_up = looks_like_gateway_recent_operator_follow_up_request(
        message=user_message,
        recent_task_snapshot=recent_task_snapshot,
    )
    history_fact = _build_conversation_history_fact(conversation_history)
    if history_fact and replay_history_in_memory_facts:
        memory_facts.append(history_fact)
    if recent_task_snapshot and looks_like_gateway_status_follow_up_request(
        message=user_message,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
    ):
        capsule_fact = _build_active_lane_handoff_capsule_fact(recent_task_snapshot)
        if capsule_fact:
            memory_facts.append(capsule_fact)
    elif recent_task_snapshot and (
        _looks_like_continue_task_request(user_message) or operator_follow_up
    ):
        snapshot_fact = _build_recent_task_snapshot_fact(recent_task_snapshot)
        if snapshot_fact:
            memory_facts.append(snapshot_fact)

    metadata = {
        "source": "tui",
        "tool_policy": _resolve_tool_policy(
            source="tui",
            task_type="conversation",
            task_profile=task_profile,
        ),
        "workflow_contract": build_conversation_workflow_contract(
            source="tui",
            skill_refs=inferred_skill_refs,
            execution_mode=normalized_execution_mode.value,
            lane=lane,
        ),
        "lane": lane,
        "dispatch_decision": _build_dispatch_metadata(
            decision=decision,
            worker_lane=worker_lane,
            worker_skill_refs=worker_skill_refs,
        ),
        "skill_refs": list(inferred_skill_refs),
    }
    operator_capsule = _resolve_task_operator_capsule(
        task_profile=task_profile,
        skill_refs=inferred_skill_refs,
        workspace=resolved_workspace,
        recent_task_snapshot=recent_task_snapshot,
        artifact_paths=_recent_snapshot_artifacts(recent_task_snapshot),
        next_actions=_recent_snapshot_follow_up_tasks(recent_task_snapshot),
    )
    if operator_capsule:
        metadata["operator_capsule"] = operator_capsule
    metadata["workflow_contract"]["dispatch"] = _build_workflow_dispatch_contract(
        decision=decision,
        worker_lane=worker_lane,
    )
    if task_profile is not None:
        metadata["task_profile"] = task_profile
    if fallback_history_fact:
        metadata["fallback_history_fact"] = fallback_history_fact
    if decision.dispatch_mode is DispatchMode.DELEGATE_BACKGROUND and worker_lane:
        metadata["job_id"] = reserved_job_id or f"mente_tui_job_{request_id}"
    if isinstance(pending_worker_control, Mapping):
        lineage = (
            pending_worker_control.get("supersedes")
            if isinstance(pending_worker_control.get("supersedes"), Mapping)
            else {}
        )
        metadata.update(
            {
                "control_contract": {
                    "action": str(pending_worker_control.get("action") or "").strip() or "reprioritize",
                    "mode": str(pending_worker_control.get("mode") or "").strip() or "supersede_worker",
                    "runtime_mutation_supported": bool(
                        pending_worker_control.get("runtime_mutation_supported", False)
                    ),
                },
                "supersedes": dict(lineage),
                "supersedes_job_id": str(
                    pending_worker_control.get("supersedes_job_id")
                    or lineage.get("job_id")
                    or ""
                ).strip(),
                "supersedes_task_id": str(
                    pending_worker_control.get("supersedes_task_id")
                    or lineage.get("task_id")
                    or ""
                ).strip(),
                "previous_job_id": str(
                    pending_worker_control.get("previous_job_id")
                    or lineage.get("job_id")
                    or ""
                ).strip(),
                "previous_task_id": str(
                    pending_worker_control.get("previous_task_id")
                    or lineage.get("task_id")
                    or ""
                ).strip(),
                "user_revision": str(pending_worker_control.get("user_revision") or "").strip(),
                "supersede_reason": str(pending_worker_control.get("reason") or "").strip() or "user_revision",
            }
        )

    objective = "Continue the active TUI conversation and answer the latest user message."
    acceptance_criteria = [
        "Respond directly to the latest user message.",
    ]
    if decision.needs_clarification:
        objective = "Clarify the exact skill or worker owner needed before dispatching the user's request."
        acceptance_criteria.append(
            "Ask one targeted clarification that identifies the missing skill or owning lane needed to continue."
        )

    return Task(
        task_id=reserved_task_id or f"mente_tui_{request_id}",
        session_id=session_id,
        task_type="conversation",
        objective=objective,
        user_request=user_message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        skill_refs=inferred_skill_refs,
        acceptance_criteria=acceptance_criteria,
        role=TaskRole.COORDINATOR,
        dispatch_mode=decision.dispatch_mode,
        worker_lane=worker_lane,
        worker_skill_refs=worker_skill_refs,
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata=metadata,
    )


def run_gateway_task(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
    request_id: str | None = None,
) -> ExecutionResult:
    """Execute a gateway turn through Mente."""
    task_bundle = build_gateway_task_bundle(
        message=message,
        context_prompt=context_prompt,
        history=history,
        source=source,
        session_id=session_id,
        session_key=session_key,
        channel_prompt=channel_prompt,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        request_id=request_id,
    )
    if task_bundle.worker_task is None:
        task = build_gateway_task(
            message=message,
            context_prompt=context_prompt,
            history=history,
            source=source,
            session_id=session_id,
            session_key=session_key,
            channel_prompt=channel_prompt,
            workspace=workspace,
            execution_mode=execution_mode,
            execution_session=execution_session,
            fallback_history_fact=fallback_history_fact,
            replay_history_in_memory_facts=replay_history_in_memory_facts,
            recent_task_snapshot=recent_task_snapshot,
            active_lane=active_lane,
            decision=task_bundle.decision,
            task_id=task_bundle.coordinator_task.task_id,
        )
    else:
        task = task_bundle.worker_task
    fast_path_result = _build_fast_path_result(task)
    if fast_path_result is not None:
        return _persist_fast_path_task_result(task, fast_path_result)
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    effective_cancel_event = cancel_event or threading.Event()
    try:
        coordinator_task = task_bundle.coordinator_task if task_bundle.worker_task is not None else None
        if task_bundle.worker_task is not None:
            coordinator_task.status = TaskStatus.EXECUTING
            repository.save(coordinator_task)
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            event_callback=event_callback,
            cancel_event=effective_cancel_event,
        ).run(task)
        _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        _apply_post_turn_conversation_workflow_contract(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        lane = task.metadata.get("lane")
        if isinstance(lane, str) and lane.strip():
            result.metadata.setdefault("lane", lane.strip())
        task_profile = task.metadata.get("task_profile")
        if isinstance(task_profile, str) and task_profile.strip():
            result.metadata.setdefault("task_profile", task_profile.strip())
        if task.skill_refs:
            result.metadata.setdefault("skill_refs", list(task.skill_refs))
        operator_capsule = task.metadata.get("operator_capsule")
        if isinstance(operator_capsule, dict) and operator_capsule:
            result.metadata.setdefault("operator_capsule", dict(operator_capsule))
        result.metadata.setdefault("task_id", task.task_id)
        result.metadata.setdefault(
            "dispatch_mode",
            task.dispatch_mode.value if hasattr(task.dispatch_mode, "value") else str(task.dispatch_mode),
        )
        if task.worker_lane:
            result.metadata.setdefault("worker_lane", task.worker_lane)
        job_id = task.job_id or (task.metadata.get("job_id") if isinstance(task.metadata, dict) else None)
        if job_id:
            result.metadata.setdefault("job_id", job_id)
        if coordinator_task is not None:
            coordinator_task.status = _resolve_final_task_status(result)
            coordinator_task.metadata["assistant_summary"] = result.summary
            coordinator_task.metadata["worker_status"] = result.status
            if result.failure_reason:
                coordinator_task.metadata["worker_failure_reason"] = result.failure_reason
            repository.save(coordinator_task)
            result.metadata.setdefault("worker_status", result.status)
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    skill_refs: list[str] | tuple[str, ...] | None = None,
) -> ExecutionResult:
    """Execute an API server turn through Mente."""
    task = build_api_server_task(
        user_message=user_message,
        conversation_history=conversation_history,
        session_id=session_id,
        api_mode=api_mode,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        skill_refs=skill_refs,
    )
    fast_path_result = _build_fast_path_result(task)
    if fast_path_result is not None:
        return _persist_fast_path_task_result(task, fast_path_result)
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        runtime_config = _resolve_runtime_config_for_workspace(task.workspace or ".")
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            executor=_APIServerIsolationExecutor(
                workspace=task.workspace or ".",
                runtime_config=runtime_config,
                memory_repository=memory_repository,
            ),
        ).run(task)
        result.metadata["remember_intent_direct_write"] = _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        _apply_post_turn_conversation_workflow_contract(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_tui_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    recent_task_snapshot: Mapping[str, Any] | None = None,
    active_lane: str | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
    request_id: str | None = None,
) -> ExecutionResult:
    """Execute one TUI turn through Mente."""
    task = build_tui_task(
        user_message=user_message,
        conversation_history=conversation_history,
        session_id=session_id,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
        recent_task_snapshot=recent_task_snapshot,
        active_lane=active_lane,
        request_id=request_id,
    )
    fast_path_result = _build_fast_path_result(task)
    if fast_path_result is not None:
        return _persist_fast_path_task_result(task, fast_path_result)
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            event_callback=event_callback,
            cancel_event=cancel_event,
        ).run(task)
        _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        _apply_post_turn_conversation_workflow_contract(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        lane = task.metadata.get("lane")
        if isinstance(lane, str) and lane.strip():
            result.metadata.setdefault("lane", lane.strip())
        task_profile = task.metadata.get("task_profile")
        if isinstance(task_profile, str) and task_profile.strip():
            result.metadata.setdefault("task_profile", task_profile.strip())
        if task.skill_refs:
            result.metadata.setdefault("skill_refs", list(task.skill_refs))
        operator_capsule = task.metadata.get("operator_capsule")
        if isinstance(operator_capsule, dict) and operator_capsule:
            result.metadata.setdefault("operator_capsule", dict(operator_capsule))
        result.metadata.setdefault("task_id", task.task_id)
        result.metadata.setdefault(
            "dispatch_mode",
            task.dispatch_mode.value if hasattr(task.dispatch_mode, "value") else str(task.dispatch_mode),
        )
        if task.worker_lane:
            result.metadata.setdefault("worker_lane", task.worker_lane)
        job_id = task.job_id or (task.metadata.get("job_id") if isinstance(task.metadata, dict) else None)
        if job_id:
            result.metadata.setdefault("job_id", job_id)
        result.metadata.setdefault("worker_status", result.status)
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def _persist_remember_intent_direct_write(
    *,
    task: Task,
    result: ExecutionResult,
    repository: SQLiteTaskRepository,
    memory_repository: SQLiteMemoryRepository,
) -> dict[str, Any]:
    """Persist a narrow explicit remember-intent fact through the existing write seam."""

    outcome: dict[str, Any] = {
        "status": "noop",
        "reason": None,
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    existing = task.metadata.get("remember_intent_direct_write")
    if isinstance(existing, dict) and existing.get("status") in {"skipped", "noop", "persisted"}:
        result.metadata["remember_intent_direct_write"] = dict(existing)
        return dict(existing)

    if result.status != "success":
        outcome["status"] = "skipped"
        outcome["reason"] = "upstream_not_success"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    enabled, reason = _remember_intent_direct_write_enabled(task)
    if not enabled:
        outcome["status"] = "skipped"
        outcome["reason"] = reason or "disabled"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    preset_facts = existing.get("facts") if isinstance(existing, dict) else None
    candidates = [
        normalize_memory_fact_text(str(item))
        for item in (preset_facts or [])
        if normalize_memory_fact_text(str(item))
    ]
    if not candidates:
        candidates = extract_explicit_remember_intent_facts(task.user_request)
    outcome["candidate_count"] = len(candidates)
    if not candidates:
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    record, write_reason = persist_explicit_memory_write(
        task,
        fact=candidates[0],
        memory_repository=memory_repository,
        tool_name="mente_remember_intent_direct_write",
        write_origin="explicit_remember_intent",
    )
    if record is None:
        outcome["status"] = "skipped"
        outcome["reason"] = write_reason or "write_failed"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    if write_reason == "duplicate_existing":
        outcome["reason"] = "duplicate_existing"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    outcome["status"] = "persisted"
    outcome["reason"] = write_reason
    outcome["persisted_count"] = 1
    outcome["memory_ids"] = [record.memory_id]
    return _persist_task_result_metadata(
        task=task,
        result=result,
        repository=repository,
        metadata_key="remember_intent_direct_write",
        metadata_value=outcome,
    )


def _apply_post_turn_conversation_workflow_contract(
    *,
    task: Task,
    result: ExecutionResult,
    repository: SQLiteTaskRepository,
    memory_repository: SQLiteMemoryRepository,
) -> None:
    """Apply contract-driven post-turn review hooks for conversation tasks."""

    workflow_contract = dict(task.metadata.get("workflow_contract") or {})
    if not workflow_contract:
        return

    result.metadata["workflow_contract"] = workflow_contract

    memory_review_contract = workflow_contract.get("memory_review")
    if isinstance(memory_review_contract, dict) and bool(memory_review_contract.get("enabled")):
        result.metadata["memory_review"] = run_post_turn_memory_review(
            task_id=task.task_id,
            repository=repository,
            memory_repository=memory_repository,
        )
    llm_memory_review_contract = workflow_contract.get("llm_memory_review")
    if isinstance(llm_memory_review_contract, dict) and bool(
        llm_memory_review_contract.get("enabled")
    ):
        result.metadata["llm_memory_review"] = run_post_turn_llm_memory_review(
            task_id=task.task_id,
            repository=repository,
            memory_repository=memory_repository,
        )
    skill_review_contract = workflow_contract.get("skill_review")
    if isinstance(skill_review_contract, dict) and bool(skill_review_contract.get("enabled")):
        result.metadata["skill_review"] = run_post_turn_skill_review(
            task_id=task.task_id,
            repository=repository,
        )
    session_synthesis_contract = workflow_contract.get("session_synthesis")
    if isinstance(session_synthesis_contract, dict) and bool(
        session_synthesis_contract.get("enabled")
    ):
        result.metadata["session_synthesis"] = run_post_turn_session_synthesis(
            task_id=task.task_id,
            repository=repository,
            memory_repository=memory_repository,
        )


def _remember_intent_direct_write_enabled(task: Task) -> tuple[bool, str | None]:
    """Return whether this task may use the direct-write remember-intent path."""

    if not is_remember_intent_direct_write_enabled():
        return False, "disabled"

    source = str(task.metadata.get("source") or "").strip()
    if not source:
        return False, "missing_source"
    if task.task_type != "conversation":
        return False, "unsupported_task_type"
    if (
        task.execution_mode is not ExecutionMode.STATELESS
        or task.skill_refs
        or task.worker_skill_refs
    ):
        return False, "executor_review_required"
    if source == "api_server":
        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="remember_intent_direct_write",
        )
        if workflow_gate is not None:
            return workflow_gate, workflow_reason
    if source not in {"gateway", "api_server", "tui"}:
        return False, "unsupported_source"
    return True, None


def _persist_task_result_metadata(
    *,
    task: Task,
    result: ExecutionResult,
    repository: SQLiteTaskRepository,
    metadata_key: str,
    metadata_value: dict[str, Any],
) -> dict[str, Any]:
    """Persist one metadata payload onto both task and result surfaces."""

    payload = dict(metadata_value)
    task.metadata[metadata_key] = payload
    result.metadata[metadata_key] = payload
    repository.save(task)
    return payload


def run_post_turn_memory_review(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn memory review worker for one task."""
    owned_repository = repository is None
    owned_memory_repository = memory_repository is None
    repository = repository or _build_task_repository()
    memory_repository = memory_repository or _build_memory_repository()
    try:
        outcome = MemoryReviewWorker(
            task_repository=repository,
            memory_repository=memory_repository,
        ).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        for repo, owned in (
            (memory_repository, owned_memory_repository),
            (repository, owned_repository),
        ):
            if not owned:
                continue
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_post_turn_llm_memory_review(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted LLM-assisted post-turn memory review worker for one task."""
    owned_repository = repository is None
    owned_memory_repository = memory_repository is None
    repository = repository or _build_task_repository()
    memory_repository = memory_repository or _build_memory_repository()
    try:
        outcome = LLMMemoryReviewWorker(
            task_repository=repository,
            memory_repository=memory_repository,
        ).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        for repo, owned in (
            (memory_repository, owned_memory_repository),
            (repository, owned_repository),
        ):
            if not owned:
                continue
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_post_turn_skill_review(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn skill review worker for one task."""
    owned_repository = repository is None
    repository = repository or _build_task_repository()
    try:
        outcome = SkillReviewWorker(task_repository=repository).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        if owned_repository:
            close = getattr(repository, "close", None)
            if callable(close):
                close()


def run_post_turn_session_synthesis(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn session synthesis worker for one task."""
    owned_repository = repository is None
    owned_memory_repository = memory_repository is None
    repository = repository or _build_task_repository()
    memory_repository = memory_repository or _build_memory_repository()
    try:
        outcome = SessionSynthesisWorker(
            task_repository=repository,
            memory_repository=memory_repository,
        ).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        for repo, owned in (
            (memory_repository, owned_memory_repository),
            (repository, owned_repository),
        ):
            if not owned:
                continue
            close = getattr(repo, "close", None)
            if callable(close):
                close()
