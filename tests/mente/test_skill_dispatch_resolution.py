from mente.integrations import bridge as mente_bridge
from mente.integrations.bridge import resolve_dispatch_decision
from mente.skills import catalog as skill_catalog
from mente.task_core.models import DispatchMode


def test_explicit_known_skill_request_preserves_skill_ref_and_prefers_owner_lane(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "explicit_skill"},
    )

    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 技能，帮我完整调研这个市场",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "deep_research"
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:research"


def test_explicit_multiple_skill_refs_from_same_lane_preserve_metadata_and_prefer_owner_lane(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "writing", "confidence": "high", "reason": "publish_flow"},
    )

    decision = resolve_dispatch_decision(
        message="调用 media/wechat-publisher 和 imagegen 技能，写完并配图后发布到公众号",
    )

    assert decision.lane == "writing"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "content_publishing"
    assert decision.skill_refs == ("media/wechat-publisher", "imagegen")
    assert decision.target_job_lane == "writing"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:writing"


def test_cross_lane_explicit_skill_message_prefers_owner_lane_and_keeps_skill_refs(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "writing", "confidence": "medium", "reason": "publish_first"},
    )

    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 和 media/wechat-publisher 技能，先研究再发布",
    )

    assert decision.lane == "writing"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile == "content_publishing"
    assert decision.skill_refs == (
        "media/wechat-publisher",
        "research/deep-research-pro",
    )
    assert decision.target_job_lane == "writing"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:writing"


def test_unknown_explicit_skill_request_falls_back_to_director_but_keeps_requested_ref(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "director", "confidence": "medium", "reason": "unknown_skill"},
    )

    decision = resolve_dispatch_decision(
        message="调用 foobar-agent 技能，帮我处理这个任务",
    )

    assert decision.lane == "director"
    assert decision.dispatch_mode == DispatchMode.INLINE
    assert decision.task_profile is None
    assert decision.skill_refs == ("foobar-agent",)
    assert decision.target_job_lane is None
    assert decision.needs_clarification is False
    assert decision.reason == "llm_classifier:director"


def test_explicit_skill_message_with_engineering_words_still_prefers_owner_lane(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "research", "confidence": "high", "reason": "research_over_repo_words"},
    )

    decision = resolve_dispatch_decision(
        message="调用 research/deep-research-pro 技能，顺便帮我看下 repo 里这个方案怎么实现",
    )

    assert decision.lane == "research"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.skill_refs == ("research/deep-research-pro",)
    assert decision.target_job_lane == "research"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:research"


def test_explicit_natural_language_skill_request_resolves_from_skill_catalog(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "_classify_ambiguous_conversation_lane",
        lambda **kwargs: {"lane": "writing", "confidence": "high", "reason": "catalog_skill"},
    )

    decision = resolve_dispatch_decision(
        message="调用 Daily News 技能，把今天的国际要闻整理成小红书素材",
    )

    assert decision.lane == "writing"
    assert decision.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert decision.task_profile is None
    assert decision.skill_refs == ("social-media/xhs-daily-news",)
    assert decision.target_job_lane == "writing"
    assert decision.needs_clarification is False
    assert decision.reason == "deterministic:owner_lane:writing"


def test_skill_catalog_match_uses_directory_metadata_not_hardcoded(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "custom" / "market-brief"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: market-brief",
                'description: "Turn daily finance headlines into short market briefs."',
                "metadata:",
                "  hermes:",
                "    tags: [finance, news, brief]",
                "---",
                "",
                "# Market Brief",
            ]
        ),
        encoding="utf-8",
    )
    skill_catalog.clear_skill_catalog_caches()

    try:
        matches = skill_catalog.match_skill_catalog_refs(
            message="调用 market brief 技能，把今天的财经新闻整理一下",
            roots=(str(skills_root),),
        )
    finally:
        skill_catalog.clear_skill_catalog_caches()

    assert matches == ("custom/market-brief",)
