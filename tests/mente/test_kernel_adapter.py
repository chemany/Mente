from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors import CodexKernelAdapter, ToolExposurePolicy
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


DOC_PATH = Path("docs/plans/2026-04-29-mente-codex-native-runtime-design.md")


class _FakeKernelAdapter(CodexKernelAdapter):
    def __init__(self, *, session_capable: bool = False) -> None:
        self._session_capable = session_capable

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        return {
            "prompt": request.user_request,
            "workspace": request.workspace,
        }

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            status="success",
            summary=f"handled:{request.task_id}",
            memory_candidates=["Repository uses uv for Python commands."],
        )

    def supports_kernel_sessions(self) -> bool:
        return self._session_capable


def test_fake_kernel_adapter_can_replace_cli_backed_executor():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_FakeKernelAdapter(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)

    assert result.status == "success"
    assert result.summary == "handled:task_1"
    assert result.memory_candidates == ["Repository uses uv for Python commands."]
    assert result.metadata["promoted_memory_count"] == 1


def test_kernel_adapter_session_capability_flag_is_optional():
    stateless = _FakeKernelAdapter()
    session_capable = _FakeKernelAdapter(session_capable=True)

    assert stateless.supports_kernel_sessions() is False
    assert session_capable.supports_kernel_sessions() is True


def test_kernel_adapter_exposes_resolved_tool_policy_from_request():
    adapter = _FakeKernelAdapter()
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        workspace=".",
        tool_policy=ToolExposurePolicy(
            policy_id="gateway:engineering",
            source="gateway",
            native_tools=["shell"],
            bridge_tools=[],
            session_capable=False,
        ),
    )

    assert adapter.resolve_tool_policy(request) == {
        "policy_id": "gateway:engineering",
        "source": "gateway",
        "native_tools": ["shell"],
        "bridge_tools": [],
        "session_capable": False,
    }


def test_native_runtime_design_declares_adapter_handoff_boundary():
    document = DOC_PATH.read_text(encoding="utf-8")

    assert "CodexKernelAdapter is the supported handoff point for the future controlled fork." in document
    assert "Upper layers should not grow new direct dependencies on CLI-specific details." in document


def test_phase_c2_manifest_declares_adapter_seam_remains_the_only_upper_layer_boundary():
    document = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c2-kernel-runner-manifest.md"
    ).read_text(encoding="utf-8")

    assert "CodexKernelAdapter remains the only upper-layer handoff seam." in document
    assert "runner + CLI transport backend + result normalization" in document
    assert "runtime config resolution" in document
    assert "private runtime home" in document
