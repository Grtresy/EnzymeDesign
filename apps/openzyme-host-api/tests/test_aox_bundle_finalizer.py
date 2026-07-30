from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

import openzyme_host_api.aox_bundle_finalizer as bundle_finalizer
from openzyme_domain import ArtifactKind
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificSelectionState
from openzyme_pipeline import aox_candidate
from openzyme_pipeline import aox_finalization
from openzyme_runtime import ArtifactBoundaryError


SESSION_ID = "session_finalization"
TASK_ID = "task_execution"
ATTEMPT_ID = "attempt_finalization"
SELECTION_ID = "selection_finalization"
AGENT_ID = "agent_executor"
LANE_ID = "lane_execution"
WORKSPACE_ID = "sandbox_workspace"
RUN_ID = "sandbox_run"
SOURCE_ID = "source_snapshot"
SOURCE_DIGEST = "sha256:" + "a" * 64


class _MapRepository:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, identity: str) -> object | None:
        return self.values.get(identity)

    def save(self, value: object) -> None:
        identity = str(
            getattr(value, "document_id", None)
            or getattr(value, "artifact_id", None)
        )
        self.values[identity] = value

    def list_by_session(self, session_id: str) -> tuple[object, ...]:
        return tuple(
            value
            for value in self.values.values()
            if getattr(value, "session_id", None) == session_id
        )


class _FakeRepositories:
    def __init__(self) -> None:
        self.tasks = _MapRepository(
            {
                TASK_ID: SimpleNamespace(
                    task_id=TASK_ID,
                    session_id=SESSION_ID,
                    assigned_ref=AGENT_ID,
                )
            }
        )
        self.scientific_attempts = _MapRepository(
            {
                ATTEMPT_ID: SimpleNamespace(
                    attempt_id=ATTEMPT_ID,
                    session_id=SESSION_ID,
                    task_id=TASK_ID,
                    lane_id=LANE_ID,
                    scope=ScientificAttemptScope.FORMAL,
                    status=ScientificAttemptStatus.ACTIVE,
                    workflow_contract_digest="sha256:" + "b" * 64,
                )
            }
        )
        self.scientific_selections = _MapRepository(
            {
                SELECTION_ID: SimpleNamespace(
                    selection_id=SELECTION_ID,
                    attempt_id=ATTEMPT_ID,
                    state=ScientificSelectionState.SEALED,
                    actor_ref=AGENT_ID,
                    workflow_contract_digest="sha256:" + "b" * 64,
                )
            }
        )
        self.sandbox_runs = _MapRepository(
            {
                RUN_ID: SimpleNamespace(
                    sandbox_run_id=RUN_ID,
                    session_id=SESSION_ID,
                    sandbox_workspace_id=WORKSPACE_ID,
                    agent_id=AGENT_ID,
                    task_id=TASK_ID,
                    lane_id=LANE_ID,
                    source_snapshot_artifact_id=SOURCE_ID,
                    source_tree_digest=SOURCE_DIGEST,
                )
            }
        )
        self.artifacts = _MapRepository(
            {
                SOURCE_ID: SimpleNamespace(
                    artifact_id=SOURCE_ID,
                    session_id=SESSION_ID,
                    relative_path="source",
                    kind=ArtifactKind.CODE,
                    metadata={
                        "semantic_type": "pipeline_source_snapshot",
                        "format": "source_tree",
                        "sandbox_workspace_id": WORKSPACE_ID,
                        "source_tree_digest": SOURCE_DIGEST,
                    },
                )
            }
        )
        self.engine_documents = _MapRepository()

    @contextmanager
    def atomic(self, *, prefix: str):
        assert prefix == "aox_final_deliverable_bundle"
        artifact_snapshot = deepcopy(self.artifacts.values)
        document_snapshot = deepcopy(self.engine_documents.values)
        try:
            yield
        except Exception:
            self.artifacts.values = artifact_snapshot
            self.engine_documents.values = document_snapshot
            raise


def _digest(content: bytes) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _contents() -> dict[str, bytes]:
    values = {
        path: b"fixture\n"
        for path in aox_finalization.FIXED_DELIVERABLE_PATHS
    }
    values["aox_hmm/target.fasta"] = b">target_1\nA\n"
    values["aox_hmm/AOX_candidates.fasta"] = b">target_1\nA\n"
    values["aox_hmm/scored_ref_plus_hits.csv"] = b"canonical-scoring\n"
    return values


class _FakeArtifactBoundary:
    def __init__(
        self,
        repositories: _FakeRepositories,
        *,
        fail_registration_at: int | None = None,
    ) -> None:
        self.repositories = repositories
        self.contents = _contents()
        self.fail_registration_at = fail_registration_at
        self.register_calls = 0

    def read_registration_draft(
        self,
        *,
        path: str,
        kind: str,
        format: str,
        metadata: dict[str, object],
        source_snapshot_artifact_id: str,
        **_: object,
    ) -> SimpleNamespace:
        relative_path = path.removeprefix("/workspace/output/")
        content = self.contents[relative_path]
        return SimpleNamespace(
            public_path=path,
            relative_path=relative_path,
            content=content,
            content_digest=_digest(content),
            kind=ArtifactKind(kind),
            metadata={**metadata, "format": format},
            validation={"status": "passed"},
            source_snapshot_artifact_id=source_snapshot_artifact_id,
            source_tree_digest=SOURCE_DIGEST,
        )

    def register(
        self,
        *,
        path: str,
        kind: str,
        _resolved_metadata: dict[str, object],
        **_: object,
    ) -> SimpleNamespace:
        self.register_calls += 1
        if self.register_calls == self.fail_registration_at:
            raise ArtifactBoundaryError(
                "artifact_register_failed",
                "injected registration failure",
            )
        relative_path = path.removeprefix("/workspace/output/")
        content_digest = _digest(self.contents[relative_path])
        artifact_id = f"artifact_{self.register_calls:02d}"
        artifact = SimpleNamespace(
            artifact_id=artifact_id,
            session_id=SESSION_ID,
            relative_path=relative_path,
            kind=ArtifactKind(kind),
            metadata={
                **_resolved_metadata,
                "content_digest": content_digest,
            },
        )
        self.repositories.artifacts.save(artifact)
        return SimpleNamespace(
            artifact=artifact,
            content_digest=content_digest,
            tree_digest=None,
        )


def _candidate_result(
    contents: dict[str, bytes],
) -> aox_candidate.CandidateFilterResult:
    target = aox_candidate.TargetSequence(
        sequence_id="target_1",
        description="",
        sequence="A",
    )
    return aox_candidate.CandidateFilterResult(
        target_input_digest=_digest(contents["aox_hmm/target.fasta"]),
        scoring_input_digest=_digest(
            contents["aox_hmm/scored_ref_plus_hits.csv"]
        ),
        targets=(target,),
        candidates=(target,),
    )


def _candidate_receipt(contents: dict[str, bytes]) -> dict[str, object]:
    return _candidate_result(contents).calculation_receipt()


@pytest.fixture(autouse=True)
def _exact_candidate_recalculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bundle_finalizer.aox_candidate,
        "filter_motif_candidates",
        lambda *_args, **_kwargs: _candidate_result(_contents()),
    )


def _params(service: _FakeArtifactBoundary) -> dict[str, object]:
    items = []
    for path in aox_finalization.FIXED_DELIVERABLE_PATHS:
        suffix = path.rsplit(".", maxsplit=1)[-1]
        items.append(
            {
                "path": f"/workspace/output/{path}",
                "relative_path": path,
                "kind": "sequence" if suffix == "fasta" else "result",
                "format": suffix,
                "validation_profile": None,
                "metadata": {},
            }
        )
    return {
        "profile_id": aox_finalization.FINAL_BUNDLE_PROFILE_ID,
        "attempt_id": ATTEMPT_ID,
        "selection_id": SELECTION_ID,
        "execution_task_id": TASK_ID,
        "items": items,
        "calculation_receipts": [
            _candidate_receipt(service.contents),
            aox_finalization.finalization_calculation_receipt(),
        ],
    }


def _passed_validation() -> dict[str, object]:
    return {
        "passed": True,
        "missing_paths": [],
        "legacy_paths": [],
        "errors": [],
        "errors_digest": _digest(b"[]"),
        "earliest_error": None,
        "earliest_error_code": None,
        "candidate_count": 1,
        "representative_count": 1,
        "graph_node_count": 1,
        "graph_edge_count": 0,
        "scientific_outcome": "discovered",
        "scientific_branch": "nonempty",
        "omitted_operation_roles": [],
    }


@pytest.mark.parametrize(
    ("candidate_count", "branch", "expected_calculations"),
    [
        (1, "nonempty", set()),
        (
            0,
            "motif_filter_empty",
            {aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID},
        ),
        (
            0,
            "length_filter_empty",
            {
                aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
                aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
            },
        ),
        (
            0,
            "hmmer_upstream_empty",
            {
                aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
                aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
                aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID,
            },
        ),
    ],
)
def test_finalizer_requires_exact_conditional_receipts_for_each_branch(
    candidate_count: int,
    branch: str,
    expected_calculations: set[str],
) -> None:
    paths = bundle_finalizer.required_aox_conditional_output_paths(
        {
            "candidate_count": candidate_count,
            "scientific_branch": branch,
        }
    )

    assert set(paths) == expected_calculations


def _finalize(
    repositories: _FakeRepositories,
    service: _FakeArtifactBoundary,
) -> dict[str, object]:
    return bundle_finalizer.finalize_aox_deliverable_bundle(
        repositories=repositories,
        artifact_boundary_service=service,
        session_id=SESSION_ID,
        sandbox_workspace_id=WORKSPACE_ID,
        sandbox_run_id=RUN_ID,
        agent_id=AGENT_ID,
        task_id=TASK_ID,
        lane_id=LANE_ID,
        source_snapshot_artifact_id=SOURCE_ID,
        source_tree_digest=SOURCE_DIGEST,
        params=_params(service),
    )


def test_finalizer_prevalidation_preserves_earliest_r65_cause_without_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _FakeRepositories()
    service = _FakeArtifactBoundary(repositories)
    monkeypatch.setattr(
        bundle_finalizer,
        "validate_aox_final_artifacts",
        lambda *_args, **_kwargs: {
            **_passed_validation(),
            "passed": False,
            "errors": [
                {
                    "error_code": "candidate_membership_mismatch",
                    "expected_count": 516,
                    "actual_count": 0,
                }
            ],
            "errors_digest": _digest(b"r65-errors"),
            "earliest_error": {
                "error_code": "candidate_membership_mismatch",
                "expected_count": 516,
                "actual_count": 0,
            },
            "earliest_error_code": "candidate_membership_mismatch",
        },
    )

    with pytest.raises(
        bundle_finalizer.AoxBundleFinalizationError
    ) as error:
        _finalize(repositories, service)

    assert error.value.error_code == "aox_final_deliverable_validation_failed"
    assert error.value.details["earliest_error_code"] == (
        "candidate_membership_mismatch"
    )
    assert service.register_calls == 0
    assert set(repositories.artifacts.values) == {SOURCE_ID}
    assert repositories.engine_documents.values == {}


def test_finalizer_commits_exact_bundle_and_source_bound_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _FakeRepositories()
    service = _FakeArtifactBoundary(repositories)
    monkeypatch.setattr(
        bundle_finalizer,
        "validate_aox_final_artifacts",
        lambda *_args, **_kwargs: _passed_validation(),
    )

    response = _finalize(repositories, service)
    payload = bundle_finalizer.validate_persisted_aox_finalization_receipt(
        repositories,
        session_id=SESSION_ID,
        execution_task_id=TASK_ID,
        receipt_id=str(response["receipt_id"]),
        attempt_id=ATTEMPT_ID,
        selection_id=SELECTION_ID,
    )

    assert response["status"] == "passed"
    assert len(response["artifact_refs"]) == 17
    assert len(repositories.artifacts.values) == 18
    assert payload["source_snapshot_artifact_id"] == SOURCE_ID
    assert payload["source_tree_digest"] == SOURCE_DIGEST
    assert payload["agent_id"] == AGENT_ID
    assert set(payload["validation_metadata"]) == set(
        aox_finalization.FIXED_DELIVERABLE_PATHS
    )


def test_persisted_receipt_rejects_agent_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _FakeRepositories()
    service = _FakeArtifactBoundary(repositories)
    monkeypatch.setattr(
        bundle_finalizer,
        "validate_aox_final_artifacts",
        lambda *_args, **_kwargs: _passed_validation(),
    )
    response = _finalize(repositories, service)
    repositories.tasks.values[TASK_ID].assigned_ref = "agent_other"

    with pytest.raises(
        bundle_finalizer.AoxBundleFinalizationError
    ) as error:
        bundle_finalizer.validate_persisted_aox_finalization_receipt(
            repositories,
            session_id=SESSION_ID,
            execution_task_id=TASK_ID,
            receipt_id=str(response["receipt_id"]),
        )

    assert error.value.error_code == (
        "aox_finalization_receipt_lifecycle_drift"
    )


def test_finalizer_rolls_back_all_visible_rows_on_registration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _FakeRepositories()
    service = _FakeArtifactBoundary(
        repositories,
        fail_registration_at=5,
    )
    monkeypatch.setattr(
        bundle_finalizer,
        "validate_aox_final_artifacts",
        lambda *_args, **_kwargs: _passed_validation(),
    )

    with pytest.raises(
        bundle_finalizer.AoxBundleFinalizationError
    ) as error:
        _finalize(repositories, service)

    assert error.value.error_code == "artifact_register_failed"
    assert service.register_calls == 5
    assert set(repositories.artifacts.values) == {SOURCE_ID}
    assert repositories.engine_documents.values == {}
