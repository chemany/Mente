from mente.integrations.bridge import resolve_dispatch_decision
from mente.task_core.models import DispatchMode


def test_explicit_known_skill_request_resolves_to_one_owner_lane():
    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 技能，帮我完整调研这个市场",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "deep_research"
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "explicit_skill_owner:research"


def test_explicit_multiple_skill_refs_from_same_lane_resolve_cleanly():
    decision = resolve_dispatch_decision(
        message="调用 media/wechat-publisher 和 imagegen 技能，写完并配图后发布到公众号",
    )

    assert decision.lane == "writing"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "content_publishing"
    assert decision.skill_refs == ("media/wechat-publisher", "imagegen")
    assert decision.target_job_lane == "writing"
    assert decision.needs_clarification is False
    assert decision.reason == "explicit_skill_owner:writing"


def test_explicit_skills_crossing_lanes_trigger_clarification():
    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 和 media/wechat-publisher 技能，先研究再发布",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.task_profile == "content_publishing"
    assert decision.skill_refs == (
        "research/deep-research-pro",
        "media/wechat-publisher",
    )
    assert decision.target_job_lane is None
    assert decision.needs_clarification is True
    assert decision.reason == "cross_lane_explicit_skill_request"


def test_unknown_explicit_skill_request_triggers_coordinator_clarification():
    decision = resolve_dispatch_decision(
        message="调用 foobar-agent 技能，帮我处理这个任务",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.task_profile is None
    assert decision.skill_refs == ("foobar-agent",)
    assert decision.target_job_lane is None
    assert decision.needs_clarification is True
    assert decision.reason == "unknown_explicit_skill_request"


def test_explicit_skill_owner_resolution_prefers_skill_owner_over_engineering_hint():
    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 技能，顺便帮我看下 repo 里这个方案怎么实现",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "explicit_skill_owner:research"
