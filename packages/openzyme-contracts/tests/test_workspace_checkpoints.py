from __future__ import annotations

import pytest

from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import RemotePrivateRefObservation
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspaceFormalBoundary


COMMIT = "a" * 40
TREE = "b" * 40
PRIVATE_REF = "refs/openzyme/private/session_1/member_1/g1/checkpoint-1"


def _observation(**overrides: object) -> RemotePrivateRefObservation:
    values: dict[str, object] = {
        "service_id": "git_service_1",
        "repository_id": "repository_1",
        "private_ref": PRIVATE_REF,
        "prior_commit": None,
        "observed_commit": COMMIT,
        "advance_kind": PrivateRefAdvanceKind.CREATE,
        "observed_at": "2026-08-16T03:00:00+00:00",
    }
    values.update(overrides)
    return RemotePrivateRefObservation(**values)  # type: ignore[arg-type]


def _proof(**overrides: object) -> WorkspaceCheckpointProofInput:
    values: dict[str, object] = {
        "boundary": WorkspaceFormalBoundary.HANDOFF,
        "workspace_id": "workspace_1",
        "session_id": "session_1",
        "agent_member_id": "member_1",
        "agent_id": "agent:researcher",
        "workspace_generation": 1,
        "repository_binding_id": "binding_1",
        "repository_binding_version": 1,
        "commit": COMMIT,
        "tree": TREE,
        "private_ref": PRIVATE_REF,
        "remote_observation": _observation(),
    }
    values.update(overrides)
    return WorkspaceCheckpointProofInput(**values)  # type: ignore[arg-type]


def test_checkpoint_input_binds_exact_generation_commit_tree_and_remote_ref() -> None:
    proof = _proof()

    assert proof.workspace_generation == 1
    assert proof.commit == proof.remote_observation.observed_commit
    assert proof.private_ref == proof.remote_observation.private_ref


def test_checkpoint_input_rejects_mismatched_remote_observation() -> None:
    with pytest.raises(ValueError, match="commit does not match"):
        _proof(remote_observation=_observation(observed_commit="c" * 40))


def test_remote_observation_distinguishes_create_from_fast_forward() -> None:
    with pytest.raises(ValueError, match="requires prior_commit"):
        _observation(advance_kind=PrivateRefAdvanceKind.FAST_FORWARD)
