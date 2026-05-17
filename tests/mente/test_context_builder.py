from mente.context_builder.builder import ContextBuilder
from mente.feature_flags import (
    API_SERVER_CONVERSATION_WORKFLOW_ID,
    build_conversation_workflow_contract,
)
from mente.memory.models import MemoryRecord
from mente.memory.policy import MemoryPolicy, MemoryPolicyResolver
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task, TaskRole


def test_context_builder_produces_execution_request():
    builder = ContextBuilder()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="Inspect repository",
    )
    request = builder.build(task)
    assert request.task_id == "task_1"
    assert request.objective == "Inspect repository"


def test_context_builder_preserves_dispatch_fields_in_execution_request():
    builder = ContextBuilder()
    task = Task(
        task_id="task_dispatch",
        session_id="session_dispatch",
        task_type="conversation",
        objective="Coordinate background work",
        user_request="先分派给 research worker",
        parent_task_id="task_parent",
        job_id="job_123",
        role="coordinator",
        dispatch_mode="delegate_background",
        worker_lane="research",
        worker_skill_refs=["research/deep-dive"],
        metadata={"source": "gateway"},
    )

    request = builder.build(task)

    assert request.parent_task_id == "task_parent"
    assert request.job_id == "job_123"
    assert request.role.value == "coordinator"
    assert request.dispatch_mode.value == "delegate_background"
    assert request.worker_lane == "research"
    assert request.worker_skill_refs == ["research/deep-dive"]


def test_context_builder_prepends_retrieved_memory():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
        metadata={"source": "gateway"},
    )
    request = ContextBuilder(memory_repository=memory_repo, memory_limit=5).build(task)
    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]


def test_context_builder_build_with_trace_reports_selected_and_skipped():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_2",
            session_id="session_1",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Session context: existing",
        )
    )

    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
        metadata={"source": "gateway"},
    )

    request, trace = ContextBuilder(
        memory_repository=memory_repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]
    assert trace.injected_count == 1
    assert [item.memory_id for item in trace.selected] == ["mem_1"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_2", "duplicate_existing_fact"),
    ]


def test_context_builder_applies_policy_scope_and_budget():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="A" * 200,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            session_id=None,
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="B" * 200,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_task_type",
            session_id=None,
            task_id="task_old_3",
            task_type="conversation",
            source="gateway",
            scope="task_type",
            fact="should be filtered",
        )
    )

    policy = MemoryPolicy(
        policy_id="gateway:conversation",
        allowed_injection_scopes=["session", "global"],
        max_injected_memories=2,
        max_chars_per_injected_fact=40,
        max_total_injected_chars=70,
        max_promoted_memories=3,
        max_chars_per_promoted_fact=160,
    )
    resolver = MemoryPolicyResolver(
        profiles={"gateway:conversation": policy, "default": policy},
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_policy_resolver=resolver,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: " + ("A" * 37) + "...",
    ]
    assert [item.memory_id for item in trace.selected] == ["mem_session"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_global", "prompt_budget_reached"),
        ("mem_task_type", "scope_filtered"),
    ]
    assert trace.prompt_budget_char_count == len(request.memory_facts[0])
    assert trace.policy_id == "gateway:conversation"


def test_context_builder_source_bounds_api_server_shared_preload():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_gateway_session",
            session_id="api-session-1",
            task_id="task_old_gateway",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Gateway session fact should stay out of api_server preload.",
            score=5.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_api_session",
            session_id="api-session-1",
            task_id="task_old_api_session",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact="API session fact should be selected first.",
            score=4.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_api_global",
            session_id=None,
            task_id="task_old_api_global",
            task_type="conversation",
            source="api_server",
            scope="global",
            fact="API global fact should remain eligible.",
            score=3.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_cron_global",
            session_id=None,
            task_id="task_old_cron_global",
            task_type="conversation",
            source="cron",
            scope="global",
            fact="Cron global fact should stay out of api_server preload.",
            score=2.0,
        )
    )

    task = Task(
        task_id="task_api_source_filter",
        session_id="api-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "api_server"},
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=2,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: API session fact should be selected first.",
        "Memory: API global fact should remain eligible.",
    ]
    assert [item.memory_id for item in trace.selected] == [
        "mem_api_session",
        "mem_api_global",
    ]


def test_context_builder_uses_session_scoped_tui_memory_policy():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_tui_session",
            session_id="tui-session-1",
            task_id="task_old_tui_session",
            task_type="conversation",
            source="tui",
            scope="session",
            fact="TUI session fact should be selected.",
            score=5.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_tui_global",
            session_id=None,
            task_id="task_old_tui_global",
            task_type="conversation",
            source="tui",
            scope="global",
            fact="TUI global fact should remain eligible.",
            score=4.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_tui_task_type",
            session_id=None,
            task_id="task_old_tui_task_type",
            task_type="conversation",
            source="tui",
            scope="task_type",
            fact="TUI task_type fact should be filtered.",
            score=6.0,
        )
    )

    task = Task(
        task_id="task_tui_1",
        session_id="tui-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "tui"},
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: TUI session fact should be selected.",
        "Memory: TUI global fact should remain eligible.",
    ]
    assert [item.memory_id for item in trace.selected] == [
        "mem_tui_session",
        "mem_tui_global",
    ]
    assert ("mem_tui_task_type", "scope_filtered") in [
        (item.memory_id, item.reason) for item in trace.skipped
    ]
    assert trace.policy_id == "tui:conversation"


def test_context_builder_prioritizes_session_summary_before_generic_memories():
    repo = InMemoryMemoryRepository()
    summary_fact = "Session summary: user prefers concise JSON replies."
    session_fact = "Ordinary session fact with higher generic score."
    global_fact = "Ordinary global fact available for backfill."
    summary_prompt = f"Memory: {summary_fact}"

    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="api-session-1",
            task_id="task_old_summary",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact=summary_fact,
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="api-session-1",
            task_id="task_old_session",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact=session_fact,
            score=5.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            session_id=None,
            task_id="task_old_global",
            task_type="conversation",
            source="api_server",
            scope="global",
            fact=global_fact,
            score=4.0,
        )
    )

    policy = MemoryPolicy(
        policy_id="api_server:conversation",
        allowed_injection_scopes=["session", "global"],
        max_injected_memories=3,
        max_chars_per_injected_fact=200,
        max_total_injected_chars=len(summary_prompt),
        max_promoted_memories=3,
        max_chars_per_promoted_fact=160,
    )
    resolver = MemoryPolicyResolver(
        profiles={"api_server:conversation": policy, "default": policy},
    )
    task = Task(
        task_id="task_api_summary_priority",
        session_id="api-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={
            "source": "api_server",
            "workflow_contract": {
                "workflow_id": API_SERVER_CONVERSATION_WORKFLOW_ID,
                "memory_read": {
                    "mode": "runtime_on_demand_query",
                    "enabled": True,
                    "session_summary": {
                        "enabled": True,
                        "scope": "session",
                        "kind": "session_summary",
                        "priority": "before_generic_memories",
                        "max_results": 1,
                        "counts_toward_existing_budgets": True,
                    },
                }
            },
        },
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=5,
        memory_policy_resolver=resolver,
    ).build_with_trace(task)

    assert request.memory_facts == [summary_prompt]
    assert [item.memory_id for item in trace.selected] == ["mem_summary"]
    assert trace.injected_count == 1
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_session", "prompt_budget_reached"),
        ("mem_global", "prompt_budget_reached"),
    ]


def test_context_builder_disabling_session_summary_policy_reverts_to_generic_preload():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="api-session-1",
            task_id="task_old_summary",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Session summary: user prefers concise JSON replies.",
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="api-session-1",
            task_id="task_old_session",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact="Ordinary session fact with higher generic score.",
            score=5.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            session_id=None,
            task_id="task_old_global",
            task_type="conversation",
            source="api_server",
            scope="global",
            fact="Ordinary global fact available for backfill.",
            score=4.0,
        )
    )

    policy = MemoryPolicy(
        policy_id="api_server:conversation",
        allowed_injection_scopes=["session", "global"],
        max_injected_memories=3,
        max_chars_per_injected_fact=200,
        max_total_injected_chars=400,
        max_promoted_memories=3,
        max_chars_per_promoted_fact=160,
    )
    resolver = MemoryPolicyResolver(
        profiles={"api_server:conversation": policy, "default": policy},
    )
    baseline_task = Task(
        task_id="task_api_summary_baseline",
        session_id="api-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "api_server"},
    )
    disabled_task = Task(
        task_id="task_api_summary_disabled",
        session_id="api-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={
            "source": "api_server",
            "workflow_contract": {
                "workflow_id": API_SERVER_CONVERSATION_WORKFLOW_ID,
                "memory_read": {
                    "mode": "runtime_on_demand_query",
                    "enabled": True,
                    "session_summary": {
                        "enabled": False,
                        "scope": "session",
                        "kind": "session_summary",
                        "priority": "before_generic_memories",
                        "max_results": 1,
                        "counts_toward_existing_budgets": True,
                    },
                }
            },
        },
    )

    baseline_request, baseline_trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=5,
        memory_policy_resolver=resolver,
    ).build_with_trace(baseline_task)
    disabled_request, disabled_trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=5,
        memory_policy_resolver=resolver,
    ).build_with_trace(disabled_task)

    baseline_reasons = {
        item.reason for item in [*baseline_trace.selected, *baseline_trace.skipped]
    }
    disabled_reasons = {
        item.reason for item in [*disabled_trace.selected, *disabled_trace.skipped]
    }

    assert disabled_request.memory_facts == []
    assert [item.memory_id for item in disabled_trace.selected] == [
        item.memory_id for item in baseline_trace.selected
    ]
    assert "mem_summary" not in [item.memory_id for item in baseline_trace.selected]
    assert "mem_summary" not in [item.memory_id for item in disabled_trace.selected]
    assert [(item.memory_id, item.reason) for item in disabled_trace.skipped] == [
        (item.memory_id, item.reason) for item in baseline_trace.skipped
    ]
    assert "session_summary_priority" not in baseline_reasons
    assert "session_summary_priority" not in disabled_reasons


def test_context_builder_prioritizes_worker_lane_summary_before_session_summary_and_task_memory():
    repo = InMemoryMemoryRepository()
    worker_summary_fact = "Worker lane summary (research): supplier shortlist and open risks."
    session_summary_fact = "Session summary: user wants a concise sourcing memo."
    generic_session_fact = "Ordinary session fact that should stay out of the thin prompt."
    task_memory_fact = "Task brief: extend the supplier comparison with pricing notes."

    repo.save(
        MemoryRecord(
            memory_id="mem_worker_summary",
            session_id="gateway-session-1",
            task_id="task_old_worker_summary",
            task_type="conversation",
            source="gateway",
            scope="session",
            kind="worker_lane_summary:research",
            fact=worker_summary_fact,
            score=1.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_session_summary",
            session_id="gateway-session-1",
            task_id="task_old_session_summary",
            task_type="conversation",
            source="gateway",
            scope="session",
            kind="session_summary",
            fact=session_summary_fact,
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_generic_session",
            session_id="gateway-session-1",
            task_id="task_old_generic_session",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact=generic_session_fact,
            score=5.0,
        )
    )

    task = Task(
        task_id="task_worker_summary_priority",
        session_id="gateway-session-1",
        task_type="conversation",
        objective="Continue the delegated research worker run",
        user_request="Continue the delegated research worker run",
        role=TaskRole.WORKER,
        worker_lane="research",
        memory_facts=[task_memory_fact],
        metadata={
            "source": "gateway",
            "workflow_contract": build_conversation_workflow_contract(
                source="gateway",
                lane="research",
                environment={
                    "MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED": "1",
                },
            ),
        },
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        f"Memory: {worker_summary_fact}",
        f"Memory: {session_summary_fact}",
        task_memory_fact,
    ]
    assert [item.memory_id for item in trace.selected[:3]] == [
        "mem_worker_summary",
        "mem_session_summary",
        "mem_generic_session",
    ]
    assert [item.reason for item in trace.selected[:3]] == [
        "worker_lane_summary_priority",
        "session_summary_priority",
        "scope_match",
    ]


def test_context_builder_injects_mente_inventory_for_self_improvement_worker(tmp_path, monkeypatch):
    mente_home = tmp_path / ".mente"
    skill_root = mente_home / "skills" / "social-media" / "xhs-daily-news"
    cron_dir = mente_home / "cron"
    deep_research_root = tmp_path / "deep-research"
    skill_root.mkdir(parents=True, exist_ok=True)
    cron_dir.mkdir(parents=True, exist_ok=True)
    deep_research_root.mkdir(parents=True, exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: xhs-daily-news\ndescription: Daily news skill.\n---\n",
        encoding="utf-8",
    )
    (mente_home / "config.yaml").write_text(
        f"mente:\n  deep_research:\n    output_root: {deep_research_root}\n",
        encoding="utf-8",
    )
    (cron_dir / "jobs.json").write_text(
        '{"jobs":[{"id":"job-1","name":"Daily News","enabled":true,"schedule":"0 9 * * *"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))

    task = Task(
        task_id="task_worker_inventory",
        session_id="gateway-session-1",
        task_type="conversation",
        objective="Improve Mente's future behavior",
        user_request="调用 Codex runtime 去编程修改技能和工作流，不要只记忆。",
        role=TaskRole.WORKER,
        worker_lane="engineering",
        worker_skill_refs=["social-media/xhs-daily-news"],
        metadata={
            "source": "gateway",
            "lane": "engineering",
            "task_profile": "self_improvement",
        },
    )

    request = ContextBuilder().build(task)

    inventory_fact = next(
        fact for fact in request.memory_facts if fact.startswith("Mente inventory:")
    )
    assert "social-media/xhs-daily-news" in inventory_fact
    assert "jobs.json" in inventory_fact
    assert request.metadata["mente_inventory"]["automation"]["total_jobs"] == 1
    assert request.metadata["mente_inventory"]["routing_hint"]["selected_category"] == "skills"


def test_context_builder_memory_context_ignores_superseded_records():
    repo = InMemoryMemoryRepository()
    # Quality contract: retrieval should only inject active rows unless an
    # operator/debug path explicitly asks for superseded records.
    repo.save(
        MemoryRecord(
            memory_id="mem_old",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢英文回答",
            score=5.0,
            slot_key="preference:response_language",
            fact_key="fact-old",
            active=False,
            superseded_by_memory_id="mem_new",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_new",
            session_id="session_1",
            task_id="task_new",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我更喜欢中文回答",
            score=1.0,
            slot_key="preference:response_language",
            fact_key="fact-new",
            active=True,
        )
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    request = ContextBuilder(memory_repository=repo, memory_limit=5).build(task)

    assert request.memory_facts == ["Memory: 我更喜欢中文回答"]
