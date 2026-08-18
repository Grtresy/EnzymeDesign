from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
import hashlib
from types import SimpleNamespace

import pytest

from openzyme_core import ResolvedScientificFile
from openzyme_core import ScientificDeliverableFinalizationService
from openzyme_core import ScientificFileDeliverableError
from openzyme_core import ScientificFileEffectAdoptionService
from openzyme_core import ScientificPublishedFileResolver
from openzyme_core import ScientificRoleRequirement
from openzyme_core import bind_mutation_write_authority
from openzyme_core.mutation_authority import MutationWriteAuthority
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificFileStorage
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState
from openzyme_domain import WorkspaceFormalBoundary
from openzyme_domain import WorkspaceJobObservationState


DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 18, tzinfo=UTC)


class _MapRepository:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, identity: str) -> object | None:
        return self.values.get(identity)


class _SelectionRepository(_MapRepository):
    def __init__(self, selection: object, head: object) -> None:
        super().__init__({"selection_1": selection})
        self.head = head

    def resolve_head(self, attempt_id: str) -> object | None:
        return self.head if attempt_id == "attempt_1" else None


class _DispositionRepository:
    def __init__(self, disposition: object) -> None:
        self.disposition = disposition

    def list_by_selection(self, selection_id: str) -> list[object]:
        return [self.disposition] if selection_id == "selection_1" else []


class _WorkspaceRevisionRepository:
    def __init__(self, *, result: object, request: object, link: object) -> None:
        self.result = result
        self.request = request
        self.link = link

    def get_result(self, result_id: str) -> object | None:
        return self.result if result_id == "result_1" else None

    def get_request_by_execution(self, execution_id: str) -> object | None:
        return self.request if execution_id == "execution_1" else None

    def get_result_revision_link(self, result_id: str) -> object | None:
        return self.link if result_id == "result_1" else None


class _GitLfsRepository:
    def __init__(self, closure: object) -> None:
        self.closure = closure

    def get_closure_manifest(self, manifest_digest: str) -> object | None:
        return self.closure if manifest_digest == DIGEST else None

    def get_publication_intent_proof(self, intent_id: str) -> dict[str, object] | None:
        return {"manifest_digest": DIGEST} if intent_id == "intent_1" else None


class _DeliverableRepository:
    def __init__(self) -> None:
        self.adoptions: dict[str, object] = {}
        self.refs: dict[str, object] = {}
        self.bundles: dict[str, object] = {}
        self.receipts: dict[str, object] = {}

    def get_adoption(self, adoption_id: str) -> object | None:
        return self.adoptions.get(adoption_id)

    def add_adoption(self, adoption: object) -> object:
        self.adoptions[getattr(adoption, "adoption_id")] = adoption
        return adoption

    def get_bundle_for_attempt(
        self,
        *,
        attempt_id: str,
        selection_id: str,
        contract_id: str,
    ) -> object | None:
        return next(
            (
                item
                for item in self.bundles.values()
                if item.attempt_id == attempt_id
                and item.selection_id == selection_id
                and item.contract_id == contract_id
            ),
            None,
        )

    def get_receipt_for_bundle(self, bundle_id: str) -> object | None:
        return next(
            (item for item in self.receipts.values() if item.bundle_id == bundle_id),
            None,
        )

    def list_refs_by_bundle(self, bundle_id: str) -> tuple[object, ...]:
        bundle = self.bundles[bundle_id]
        return tuple(self.refs[ref_id] for ref_id in bundle.ref_ids)

    def add_ref(self, ref: object) -> object:
        self.refs[getattr(ref, "ref_id")] = ref
        return ref

    def add_bundle(self, bundle: object, *, refs: tuple[object, ...]) -> object:
        assert tuple(sorted(ref.ref_id for ref in refs)) == bundle.ref_ids
        self.bundles[getattr(bundle, "bundle_id")] = bundle
        return bundle

    def add_receipt(self, receipt: object) -> object:
        self.receipts[getattr(receipt, "receipt_id")] = receipt
        return receipt


class _ScientificRepositories(SimpleNamespace):
    @contextmanager
    def atomic(self, *, prefix: str):
        before = (
            dict(self.scientific_deliverables.adoptions),
            dict(self.scientific_deliverables.refs),
            dict(self.scientific_deliverables.bundles),
            dict(self.scientific_deliverables.receipts),
        )
        try:
            yield
        except BaseException:
            (
                self.scientific_deliverables.adoptions,
                self.scientific_deliverables.refs,
                self.scientific_deliverables.bundles,
                self.scientific_deliverables.receipts,
            ) = before
            raise
        assert prefix.startswith("scientific_file_")


def _facts() -> tuple[_ScientificRepositories, MutationWriteAuthority]:
    attempt = SimpleNamespace(
        attempt_id="attempt_1",
        session_id="session_1",
        mutation_scope_id="mutation_scope_1",
        state_version=4,
        status=ScientificAttemptStatus.ACTIVE,
    )
    selection = SimpleNamespace(
        selection_id="selection_1",
        attempt_id="attempt_1",
        state=ScientificSelectionState.DRAFT,
        actor_ref="agent:scientist",
        revision=2,
        adoption_digest=DIGEST,
    )
    head = SimpleNamespace(head=SimpleNamespace(selection_id="selection_1"))
    disposition = SimpleNamespace(
        attempt_id="attempt_1",
        selection_id="selection_1",
        operation_id="operation_1",
        actor_ref="agent:scientist",
        kind=ScientificOperationDispositionKind.ADOPTED,
        workflow_role="role_1",
    )
    operation = SimpleNamespace(
        operation_id="operation_1",
        session_id="session_1",
        status=ControlledOperationStatus.COMPLETED,
    )
    execution = SimpleNamespace(
        execution_id="execution_1",
        operation_id="operation_1",
        session_id="session_1",
        fencing_token=7,
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        result_handle_ref="result_1",
        result_digest=DIGEST,
    )
    result = SimpleNamespace(
        result_id="result_1",
        operation_id="operation_1",
        execution_id="execution_1",
        result_digest=DIGEST,
        terminal_state=WorkspaceJobObservationState.SUCCEEDED,
    )
    request = SimpleNamespace(
        execution_id="execution_1",
        session_id="session_1",
        scientific_basis=SimpleNamespace(
            attempt_id="attempt_1",
            attempt_state_version=4,
        ),
    )
    link = SimpleNamespace(
        result_id="result_1",
        checkpoint_id="checkpoint_1",
        workspace_id="workspace_1",
        result_commit="1" * 40,
        result_tree="2" * 40,
        linked_by_agent_member_id="member_1",
        lfs_closure_manifest_digest=DIGEST,
        link_digest=DIGEST,
    )
    checkpoint = SimpleNamespace(
        checkpoint_id="checkpoint_1",
        boundary=WorkspaceFormalBoundary.EXTERNAL_JOB,
        session_id="session_1",
        workspace_id="workspace_1",
        workspace_generation=1,
        agent_member_id="member_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        commit="1" * 40,
        tree="2" * 40,
    )
    closure = SimpleNamespace(
        manifest_digest=DIGEST,
        binding_id="binding_1",
        binding_version=1,
        repository_id="repository_1",
        commit="1" * 40,
        tree="2" * 40,
        policy_digest=DIGEST,
    )
    repositories = _ScientificRepositories(
        scientific_selections=_SelectionRepository(selection, head),
        scientific_attempts=_MapRepository({"attempt_1": attempt}),
        scientific_dispositions=_DispositionRepository(disposition),
        controlled_operations=_MapRepository({"operation_1": operation}),
        controlled_operation_executions=_MapRepository(
            {"execution_1": execution}
        ),
        workspace_revision_executions=_WorkspaceRevisionRepository(
            result=result,
            request=request,
            link=link,
        ),
        controlled_operation_results=_MapRepository({}),
        verified_workspace_checkpoints=_MapRepository({"checkpoint_1": checkpoint}),
        git_lfs=_GitLfsRepository(closure),
        scientific_deliverables=_DeliverableRepository(),
        published_revisions=_MapRepository({}),
        workspace_publication_remote_receipts=_MapRepository({}),
    )
    authority = MutationWriteAuthority(
        scope_id="mutation_scope_1",
        scope_generation=1,
        scope_fencing_token=1,
        writer_id="controlled-operation-writer",
        writer_fencing_token=7,
        owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
    )
    return repositories, authority


def _adopt(repositories: _ScientificRepositories, authority: MutationWriteAuthority):
    with bind_mutation_write_authority(authority):
        return ScientificFileEffectAdoptionService(
            repositories,  # type: ignore[arg-type]
            now=lambda: NOW,
        ).adopt(
            selection_id="selection_1",
            operation_id="operation_1",
            execution_id="execution_1",
            result_id="result_1",
            workflow_role="role_1",
            actor_ref="agent:scientist",
            execution_fencing_token=7,
            idempotency_key="adopt-role-1",
        )


def test_adoption_binds_same_attempt_result_and_replays_exactly() -> None:
    repositories, authority = _facts()

    first = _adopt(repositories, authority)
    second = _adopt(repositories, authority)

    assert first == second
    assert first.attempt_id == "attempt_1"
    assert first.result_id == "result_1"
    assert first.effect_certainty == "terminal_known"
    assert len(repositories.scientific_deliverables.adoptions) == 1


@pytest.mark.parametrize(
    "drift",
    ["cross_attempt", "identity", "effect_certainty", "historical_result"],
)
def test_adoption_rejects_cross_attempt_identity_and_noncurrent_result(
    drift: str,
) -> None:
    repositories, authority = _facts()
    if drift == "cross_attempt":
        repositories.workspace_revision_executions.request.scientific_basis.attempt_id = (
            "attempt_other"
        )
    elif drift == "identity":
        repositories.workspace_revision_executions.link.result_commit = "3" * 40
    elif drift == "effect_certainty":
        repositories.controlled_operation_executions.values[
            "execution_1"
        ].effect_certainty = ExternalEffectCertainty.DISPATCH_IN_DOUBT
    else:
        repositories.controlled_operation_results.values["result_1"] = SimpleNamespace()

    with pytest.raises(ScientificFileDeliverableError):
        _adopt(repositories, authority)

    assert repositories.scientific_deliverables.adoptions == {}


class _ResolvedFileResolver:
    def __init__(self, content: bytes = b"scientific-result\n") -> None:
        self.content = content

    def resolve(self, *, publication_id: str, path: str) -> ResolvedScientificFile:
        assert publication_id == "publication_1"
        object_id = hashlib.sha1(
            f"blob {len(self.content)}\0".encode() + self.content,
            usedforsecurity=False,
        ).hexdigest()
        entry = PublicationManifestEntry(
            path=path,
            mode="100644",
            object_kind=PublicationManifestObjectKind.BLOB,
            object_id=object_id,
            size_bytes=len(self.content),
        )
        return ResolvedScientificFile(
            publication_id=publication_id,
            path=path,
            manifest_entry=entry,
            storage=ScientificFileStorage.GIT_BLOB,
            actual_bytes=self.content,
            content_digest="sha256:" + hashlib.sha256(self.content).hexdigest(),
        )


def _prepare_finalization(
    repositories: _ScientificRepositories,
    authority: MutationWriteAuthority,
) -> tuple[object, ScientificRoleRequirement]:
    adoption = _adopt(repositories, authority)
    selection = repositories.scientific_selections.values["selection_1"]
    selection.state = ScientificSelectionState.SEALED
    revision = SimpleNamespace(
        publication_id="publication_1",
        intent_id="intent_1",
        project_id="project_1",
        session_id="session_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        commit="1" * 40,
        tree="2" * 40,
        publisher_agent_member_id="member_1",
        publisher_workspace_id="workspace_1",
        publisher_workspace_generation=1,
        publication_ref="refs/openzyme/publications/publication_1",
        repository_policy_digest=DIGEST,
        revision_digest=DIGEST,
        controlled_execution_id="publication_execution_1",
        remote_receipt_id="publication_receipt_1",
    )
    publication_execution = SimpleNamespace(
        execution_id="publication_execution_1",
        session_id="session_1",
        fencing_token=9,
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        result_handle_ref="publication:publication_1",
    )
    publication_receipt = SimpleNamespace(
        publication_id="publication_1",
        intent_id="intent_1",
        execution_id="publication_execution_1",
        execution_fencing_token=9,
        new_commit="1" * 40,
        new_tree="2" * 40,
        server_observed_commit="1" * 40,
    )
    repositories.published_revisions.values["publication_1"] = revision
    repositories.controlled_operation_executions.values[
        "publication_execution_1"
    ] = publication_execution
    repositories.workspace_publication_remote_receipts.values[
        "publication_receipt_1"
    ] = publication_receipt
    requirement = ScientificRoleRequirement(
        scientific_role="role_1",
        path="science/result.txt",
        format_contract_id="text@1",
        format_contract_digest=DIGEST,
        producer_adoption_id=adoption.adoption_id,
        validate_bytes=lambda content: None if content else pytest.fail("empty"),
    )
    return adoption, requirement


def test_finalization_persists_atomic_revision_bound_set_without_task_authority() -> None:
    repositories, authority = _facts()
    _adoption, requirement = _prepare_finalization(repositories, authority)

    with bind_mutation_write_authority(authority):
        result = ScientificDeliverableFinalizationService(
            repositories=repositories,  # type: ignore[arg-type]
            resolver=_ResolvedFileResolver(),  # type: ignore[arg-type]
            now=lambda: NOW,
        ).finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            contract_id="scientific-contract@1",
            contract_digest=DIGEST,
            requirements=(requirement,),
        )

    assert len(result.refs) == 1
    assert result.refs[0].published_commit == "1" * 40
    assert result.refs[0].producer_adoption_id == requirement.producer_adoption_id
    assert result.bundle.ref_ids == (result.refs[0].ref_id,)
    assert result.receipt.verified_ref_digests == (result.refs[0].ref_digest,)
    assert not hasattr(repositories, "tasks")


def test_finalization_rejects_missing_adoption_without_partial_rows() -> None:
    repositories, authority = _facts()
    _adoption, requirement = _prepare_finalization(repositories, authority)
    repositories.scientific_deliverables.adoptions.clear()

    with bind_mutation_write_authority(authority):
        with pytest.raises(ScientificFileDeliverableError, match="adoption chain"):
            ScientificDeliverableFinalizationService(
                repositories=repositories,  # type: ignore[arg-type]
                resolver=_ResolvedFileResolver(),  # type: ignore[arg-type]
                now=lambda: NOW,
            ).finalize(
                publication_id="publication_1",
                attempt_id="attempt_1",
                selection_id="selection_1",
                actor_ref="agent:scientist",
                execution_fencing_token=9,
                contract_id="scientific-contract@1",
                contract_digest=DIGEST,
                requirements=(requirement,),
            )

    assert repositories.scientific_deliverables.refs == {}
    assert repositories.scientific_deliverables.bundles == {}
    assert repositories.scientific_deliverables.receipts == {}


def test_finalization_rolls_back_partial_ref_set_on_bundle_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, authority = _facts()
    _adoption, requirement = _prepare_finalization(repositories, authority)

    def fail_bundle(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected bundle write failure")

    monkeypatch.setattr(
        repositories.scientific_deliverables,
        "add_bundle",
        fail_bundle,
    )
    with bind_mutation_write_authority(authority):
        with pytest.raises(RuntimeError, match="bundle write failure"):
            ScientificDeliverableFinalizationService(
                repositories=repositories,  # type: ignore[arg-type]
                resolver=_ResolvedFileResolver(),  # type: ignore[arg-type]
                now=lambda: NOW,
            ).finalize(
                publication_id="publication_1",
                attempt_id="attempt_1",
                selection_id="selection_1",
                actor_ref="agent:scientist",
                execution_fencing_token=9,
                contract_id="scientific-contract@1",
                contract_digest=DIGEST,
                requirements=(requirement,),
            )

    assert repositories.scientific_deliverables.refs == {}
    assert repositories.scientific_deliverables.bundles == {}
    assert repositories.scientific_deliverables.receipts == {}


class _PublishedReader:
    def __init__(self, blobs: dict[str, bytes], lfs: dict[str, bytes] | None = None) -> None:
        self.blobs = blobs
        self.lfs = lfs or {}

    def read_git_blob(self, *, path: str, **_: object) -> bytes:
        return self.blobs[path]

    def read_lfs_object(self, *, path: str, **_: object) -> bytes:
        return self.lfs[path]


def test_published_file_resolver_rejects_blob_and_lfs_identity_drift() -> None:
    blob = b"blob-content"
    pointer = b"version https://git-lfs.github.com/spec/v1\n"
    lfs = b"large-scientific-content"
    blob_entry = PublicationManifestEntry(
        path="science/blob.txt",
        mode="100644",
        object_kind=PublicationManifestObjectKind.BLOB,
        object_id=hashlib.sha1(
            f"blob {len(blob)}\0".encode() + blob,
            usedforsecurity=False,
        ).hexdigest(),
        size_bytes=len(blob),
    )
    lfs_entry = PublicationManifestEntry(
        path="science/large.bin",
        mode="100644",
        object_kind=PublicationManifestObjectKind.BLOB,
        object_id=hashlib.sha1(
            f"blob {len(pointer)}\0".encode() + pointer,
            usedforsecurity=False,
        ).hexdigest(),
        size_bytes=len(pointer),
        lfs_oid="sha256:" + hashlib.sha256(lfs).hexdigest(),
        lfs_size_bytes=len(lfs),
    )
    revision = SimpleNamespace(
        repository_binding_id="binding_1",
        repository_binding_version=1,
        publication_ref="refs/openzyme/publications/publication_1",
        commit="1" * 40,
        manifest=SimpleNamespace(entries=(blob_entry, lfs_entry)),
    )
    repositories = SimpleNamespace(
        published_revisions=_MapRepository({"publication_1": revision})
    )

    blob_resolver = ScientificPublishedFileResolver(
        repositories,  # type: ignore[arg-type]
        _PublishedReader({"science/blob.txt": b"drifted"}),
    )
    with pytest.raises(ScientificFileDeliverableError, match="blob bytes drifted"):
        blob_resolver.resolve(publication_id="publication_1", path="science/blob.txt")

    lfs_resolver = ScientificPublishedFileResolver(
        repositories,  # type: ignore[arg-type]
        _PublishedReader(
            {"science/large.bin": pointer},
            {"science/large.bin": b"drifted"},
        ),
    )
    with pytest.raises(ScientificFileDeliverableError, match="actual size drifted"):
        lfs_resolver.resolve(publication_id="publication_1", path="science/large.bin")

    with pytest.raises(ScientificFileDeliverableError, match="not an ordinary file"):
        lfs_resolver.resolve(publication_id="publication_1", path="science/missing.bin")

    with pytest.raises(ScientificFileDeliverableError, match="unknown immutable"):
        lfs_resolver.resolve(
            publication_id="publication_other",
            path="science/large.bin",
        )
