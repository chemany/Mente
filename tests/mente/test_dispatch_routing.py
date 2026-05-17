from mente.integrations import bridge as mente_bridge
from mente.integrations.bridge import resolve_dispatch_decision
from mente.task_core.models import DispatchMode


def test_resolve_dispatch_decision_routes_deep_research_to_background_worker_via_owner_lane(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "deep_research"},
    )

    decision = resolve_dispatch_decision(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "deep_research"
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:research"


def test_resolve_dispatch_decision_routes_engineering_request_to_background_worker_deterministically(
    monkeypatch,
):
    def _classify(**kwargs):
        assert kwargs["message"] == "帮我修复 tests/gateway/test_session.py 的失败并跑 pytest"
        return {
            "lane": "engineering",
            "confidence": "high",
            "reason": "engineering_request",
        }

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    decision = resolve_dispatch_decision(
        message="帮我修复 tests/gateway/test_session.py 的失败并跑 pytest",
    )

    assert decision.lane == "engineering"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile is None
    assert decision.skill_refs == ()
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:engineering"


def test_resolve_dispatch_decision_keeps_generic_chat_inline(monkeypatch):
    def _classify(**kwargs):
        assert kwargs["message"] == "first question"
        return {"lane": "director", "confidence": "medium", "reason": "generic_chat"}

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _classify)

    decision = resolve_dispatch_decision(message="first question")

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.task_profile is None
    assert decision.skill_refs == ()
    assert decision.target_job_lane is None
    assert decision.needs_clarification is False
    assert decision.reason == "llm_classifier:director"


def test_resolve_dispatch_decision_routes_status_follow_up_to_inline_coordinator():
    decision = resolve_dispatch_decision(
        message="做到哪了？",
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "status_follow_up:engineering"


def test_resolve_dispatch_decision_delegates_known_skill_request(monkeypatch):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "skill_request"},
    )

    decision = resolve_dispatch_decision(
        message="调用深度研究技能，帮我完整调研一个化工路线",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False


def test_resolve_dispatch_decision_routes_self_improvement_skill_change_to_engineering():
    decision = resolve_dispatch_decision(
        message=(
            "根据这次运行情况自我完善。以后深度研究报告完成后默认上传到飞书，"
            "调用 Codex runtime 去编程修改技能、脚本和工作流，不要只记忆。"
        ),
        recent_task_snapshot={
            "user_request": "调用深度研究技能，研究一个化工路线并输出完整报告",
            "status": "needs_follow_up",
            "assistant_summary": "已生成 Markdown、HTML、DOCX 三份报告。",
            "metadata": {
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["research/deep-research-pro"],
            },
        },
    )

    assert decision.lane == "engineering"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "self_improvement"
    assert decision.skill_refs == ()
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:self_improvement:engineering"


def test_resolve_dispatch_decision_routes_skill_audit_request_to_engineering():
    decision = resolve_dispatch_decision(
        message="查找一下Daily News技能，看看有什么优化项",
    )

    assert decision.lane == "engineering"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "skill_audit"
    assert decision.skill_refs == ("social-media/xhs-daily-news",)
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:skill_audit:engineering"


def test_resolve_dispatch_decision_routes_skill_audit_capability_follow_up_to_self_improvement():
    decision = resolve_dispatch_decision(
        message="这类问题我倾向mente要会自己解决，你要强化的是mente本身的能力。",
        recent_task_snapshot={
            "user_request": "查找一下Daily News技能，看看有什么优化项",
            "status": "needs_follow_up",
            "assistant_summary": "已列出 workflow、解析和发布顺序方面的改进项。",
            "metadata": {
                "lane": "engineering",
                "task_profile": "skill_audit",
                "skill_refs": ["social-media/xhs-daily-news"],
            },
        },
    )

    assert decision.lane == "engineering"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "self_improvement"
    assert decision.skill_refs == ()
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:self_improvement:engineering"


def test_resolve_dispatch_decision_routes_ambiguous_skill_request_to_director_via_classifier(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "medium", "reason": "generic_skill_request"},
    )

    decision = resolve_dispatch_decision(
        message="调用技能帮我处理一下这个任务",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.skill_refs == ()
    assert decision.target_job_lane is None
    assert decision.needs_clarification is False
    assert decision.reason == "llm_classifier:director"
