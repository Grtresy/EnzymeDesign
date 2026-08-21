from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolInvocation
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import WorkerClaimRequest

from openzyme_research import InMemoryResearchRepository
from openzyme_research import ResearchInvocationStatus
from openzyme_research import ResearchOrchestrationService
from openzyme_research import ResearchProviderReceipt
from openzyme_research import ResearchProviderDescriptor
from openzyme_research import ResearchProviderKind
from openzyme_research import ResearchProviderRequest
from openzyme_research import ResearchProviderSource
from openzyme_research import ResearchStartToolRuntime
from openzyme_research import ResearchWorker
from openzyme_research import SourceRefKind
from openzyme_research import build_research_plugin_runtime_surfaces


DIGEST = "sha256:" + "1" * 64


@dataclass(slots=True)
class CapturingApplicationService:
    commands: list[object]

    def __init__(self) -> None:
        self.commands = []

    def execute(self, command: object) -> KernelMutationReceipt:
        self.commands.append(command)
        context = command.context  # type: ignore[attr-defined]
        operation = command.operation.value  # type: ignore[attr-defined]
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id="test-service",
            operation=operation,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        )


class ContextFactory:
    def create(
        self,
        *,
        request: object,
        command_id: str,
        idempotency_key: str,
        route_id: str,
    ) -> KernelCommandContext:
        return KernelCommandContext(
            command_id=command_id,
            session_id=request.session_id,  # type: ignore[attr-defined]
            actor_id=request.actor_id,  # type: ignore[attr-defined]
            owner_plugin_id="openzyme.research",
            authority_lease_id="lease-research",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=DIGEST,
            capability_binding_digest=DIGEST,
            idempotency_key=idempotency_key,
            correlation_id="correlation-research",
            route_id=route_id,
        )


@dataclass(slots=True)
class FakeProvider:
    lose_response: bool = False
    provider_id: str = "test.research.provider"
    route_id: str = "test.research.provider.route"
    calls: int = 0
    observations: dict[str, ResearchProviderReceipt] | None = None

    def __post_init__(self) -> None:
        self.observations = {}

    @property
    def descriptor(self) -> ResearchProviderDescriptor:
        return ResearchProviderDescriptor(
            adapter_component_id="test.research.adapter",
            provider_id=self.provider_id,
            provider_kind=ResearchProviderKind.WEB,
            contract_digest=DIGEST,
        )

    def dispatch(self, request: ResearchProviderRequest) -> ResearchProviderReceipt:
        self.calls += 1
        timestamp = datetime.now(UTC).isoformat()
        if self.lose_response:
            receipt = ResearchProviderReceipt(
                operation_id=request.operation_id,
                provider_id=self.provider_id,
                provider_operation_id=None,
                request_digest=request.request_digest,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                status="dispatch_in_doubt",
                sources=(),
                summary="response lost after dispatch",
                observed_at=timestamp,
                error_code="provider_response_lost",
            )
        else:
            receipt = ResearchProviderReceipt(
                operation_id=request.operation_id,
                provider_id=self.provider_id,
                provider_operation_id=f"provider-{request.operation_id}",
                request_digest=request.request_digest,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                status="completed",
                sources=(
                    ResearchProviderSource(
                        source_id=f"source-{request.operation_id}",
                        title="Source-bound result",
                        locator="https://example.org/source",
                        kind=SourceRefKind.WEB_PAGE,
                        content_digest=canonical_sha256_digest({"source": request.operation_id}),
                        retrieved_at=timestamp,
                        snippet="bounded content",
                    ),
                ),
                summary="completed",
                observed_at=timestamp,
                response_digest=canonical_sha256_digest({"response": request.operation_id}),
            )
        assert self.observations is not None
        self.observations[request.operation_id] = receipt
        return receipt

    def reconcile(self, operation_id: str) -> ResearchProviderReceipt:
        assert self.observations is not None
        return self.observations[operation_id]


def _runtime(*, lose_response: bool = False):
    repository = InMemoryResearchRepository()
    controlled = CapturingApplicationService()
    invocations = CapturingApplicationService()
    provider = FakeProvider(lose_response=lose_response)
    service = ResearchOrchestrationService(
        repository=repository,
        provider=provider,
        controlled_operations=controlled,
        extension_invocations=invocations,
        context_factory=ContextFactory(),
    )
    return (
        ResearchStartToolRuntime(service),
        ResearchWorker(repository, service),
        repository,
        provider,
        controlled,
        invocations,
    )


def _invoke(runtime: ResearchStartToolRuntime) -> object:
    return runtime.invoke(
        ToolInvocation(
            call_id="call-research-1",
            tool_name="deep_research.start",
            arguments={
                "brief": "Investigate one explicit question.",
                "units": [
                    {"unit_id": "unit-1", "topic": "topic", "query": "query"}
                ],
            },
            session_id="session-1",
            agent_member_id="member-1",
            task_id="task-1",
        )
    )


def test_agent_explicitly_admits_research_and_worker_settles_without_task_finish() -> None:
    runtime, worker, repository, provider, controlled, invocations = _runtime()

    admitted = _invoke(runtime)
    assert admitted.ok is True
    assert admitted.payload["status"] == "admitted"
    assert admitted.payload["task_finished"] is False
    assert provider.calls == 0

    claims = worker.claim(
        WorkerClaimRequest(
            worker_id=worker.worker_id,
            owner_plugin_id="openzyme.research",
            activation_epoch=1,
            max_items=1,
            lease_seconds=30,
        )
    )
    result = worker.run(claims[0])

    record = repository.get("research-call-research-1")
    assert record is not None
    assert record.status is ResearchInvocationStatus.COMPLETED
    assert result.payload["publication_created"] is False
    assert result.payload["task_evidence_created"] is False
    assert result.payload["task_finished"] is False
    assert provider.calls == 1
    assert [command.operation.value for command in controlled.commands] == [
        "admit",
        "observe",
    ]
    assert [command.operation.value for command in invocations.commands] == [
        "start",
        "settle",
    ]


def test_lost_provider_response_requires_reconciliation_without_redispatch() -> None:
    runtime, worker, repository, provider, controlled, _ = _runtime(
        lose_response=True
    )
    _invoke(runtime)
    first_claim = worker.claim(
        WorkerClaimRequest(
            worker_id=worker.worker_id,
            owner_plugin_id="openzyme.research",
            activation_epoch=1,
            max_items=1,
            lease_seconds=30,
        )
    )[0]
    first_result = worker.run(first_claim)

    assert first_result.status == "dispatch_in_doubt"
    assert provider.calls == 1
    record = repository.get("research-call-research-1")
    assert record is not None
    assert record.status is ResearchInvocationStatus.DISPATCH_IN_DOUBT

    second_claim = worker.claim(
        WorkerClaimRequest(
            worker_id=worker.worker_id,
            owner_plugin_id="openzyme.research",
            activation_epoch=1,
            max_items=1,
            lease_seconds=30,
        )
    )[0]
    second_result = worker.run(second_claim)

    assert second_result.status == "dispatch_in_doubt"
    assert provider.calls == 1
    assert all(command.payload["fallback_performed"] is False for command in controlled.commands[1:])


def test_runtime_surfaces_mount_exact_tool_worker_and_namespaced_projection() -> None:
    _, _, repository, provider, controlled, invocations = _runtime()
    service = ResearchOrchestrationService(
        repository=repository,
        provider=provider,
        controlled_operations=controlled,
        extension_invocations=invocations,
        context_factory=ContextFactory(),
    )
    surfaces = build_research_plugin_runtime_surfaces(
        repository=repository,
        service=service,
    )

    assert [tool.contract.tool_name for tool in surfaces.tools] == [
        "deep_research.start"
    ]
    assert [worker.worker_id for worker in surfaces.workers] == [
        "openzyme.research.worker@1"
    ]
    assert [projection.section_id for projection in surfaces.projections] == [
        "openzyme.research@1"
    ]


def test_research_projection_is_session_scoped_bounded_and_cursor_stable() -> None:
    runtime, worker, repository, _, _, _ = _runtime()
    first = _invoke(runtime)
    assert first.ok is True
    second = runtime.invoke(
        ToolInvocation(
            call_id="call-research-2",
            tool_name="deep_research.start",
            arguments={
                "brief": "Investigate another explicit question.",
                "units": [
                    {"unit_id": "unit-2", "topic": "topic", "query": "query"}
                ],
            },
            session_id="session-1",
            agent_member_id="member-1",
            task_id="task-1",
        )
    )
    assert second.ok is True
    claims = worker.claim(
        WorkerClaimRequest(
            worker_id=worker.worker_id,
            owner_plugin_id="openzyme.research",
            activation_epoch=1,
            max_items=2,
            lease_seconds=30,
        )
    )
    for claim in claims:
        worker.run(claim)

    projection = build_research_plugin_runtime_surfaces(
        repository=repository,
        service=runtime.service,
    ).projections[0]
    context = KernelQueryContext(
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.research",
        authority_lease_id="lease-research",
        extension_bundle_digest=DIGEST,
        capability_binding_digest=DIGEST,
        correlation_id="correlation-research",
    )
    first_page = projection.project(
        ProjectionRequest(
            context=context,
            section_id="openzyme.research@1",
            max_items=1,
            max_bytes=16_384,
        )
    )
    assert len(first_page.payload["invocations"]) == 1
    assert first_page.next_cursor == "research-call-research-1"
    assert "provider_transcript" not in str(first_page.payload)

    second_page = projection.project(
        ProjectionRequest(
            context=context,
            section_id="openzyme.research@1",
            max_items=1,
            max_bytes=16_384,
            cursor=first_page.next_cursor,
        )
    )
    assert [
        item["invocation_id"] for item in second_page.payload["invocations"]
    ] == ["research-call-research-2"]
    assert second_page.next_cursor is None


def test_research_handoff_requires_explicit_immutable_revision_path_ref() -> None:
    runtime, worker, repository, _, _, _ = _runtime()
    _invoke(runtime)
    claim = worker.claim(
        WorkerClaimRequest(
            worker_id=worker.worker_id,
            owner_plugin_id="openzyme.research",
            activation_epoch=1,
            max_items=1,
            lease_seconds=30,
        )
    )[0]
    worker.run(claim)
    before = repository.get("research-call-research-1")
    assert before is not None
    assert before.publication_ref is None

    published = RevisionPathRef.create(
        ref_id="research-summary-ref",
        publication_id="publication-1",
        project_id="project-1",
        session_id="session-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit="a" * 40,
        tree="b" * 40,
        path="research/summary.md",
        entry_kind=RevisionPathEntryKind.FILE,
        object_id="c" * 40,
        size_bytes=128,
        lfs_oid=None,
        lfs_size_bytes=None,
        path_manifest_digest=None,
        created_at="2026-08-19T00:00:00+00:00",
    )
    linked = runtime.service.link_publication(
        invocation_id=before.invocation_id,
        publication_ref=published,
    )

    assert linked.publication_ref == published
    assert linked.status is ResearchInvocationStatus.COMPLETED
