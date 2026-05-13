from mente.integrations import bridge as mente_bridge
from mente.integrations.bridge import resolve_dispatch_decision
from mente.task_core.models import DispatchMode


def test_resolve_dispatch_decision_routes_deep_research_to_background_worker():
    decision = resolve_dispatch_decision(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "deep_research"
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "task_profile:deep_research"


def test_resolve_dispatch_decision_routes_engineering_request_to_background_worker(
    monkeypatch,
):
    def _fail_if_called(**kwargs):
        raise AssertionError("classifier should not run for obvious engineering requests")

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _fail_if_called)

    decision = resolve_dispatch_decision(
        message="帮我修复 tests/gateway/test_session.py 的失败并跑 pytest",
    )

    assert decision.lane == "engineering"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile is None
    assert decision.skill_refs == ()
    assert decision.target_job_lane == "engineering"
    assert decision.needs_clarification is False
    assert decision.reason == "engineering_heuristic"


def test_resolve_dispatch_decision_keeps_generic_chat_inline(monkeypatch):
    def _fail_if_called(**kwargs):
        raise AssertionError("classifier should not run for generic director chat")

    monkeypatch.setattr(mente_bridge, "_classify_ambiguous_conversation_lane", _fail_if_called)

    decision = resolve_dispatch_decision(message="first question")

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.task_profile is None
    assert decision.skill_refs == ()
    assert decision.target_job_lane is None
    assert decision.needs_clarification is False
    assert decision.reason == "default_director"


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


def test_resolve_dispatch_decision_delegates_known_skill_request():
    decision = resolve_dispatch_decision(
        message="调用深度研究技能，帮我完整调研一个化工路线",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False


def test_resolve_dispatch_decision_requests_clarification_for_ambiguous_skill_request():
    decision = resolve_dispatch_decision(
        message="调用技能帮我处理一下这个任务",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.skill_refs == ()
    assert decision.target_job_lane is None
    assert decision.needs_clarification is True
    assert decision.reason == "ambiguous_skill_request"
