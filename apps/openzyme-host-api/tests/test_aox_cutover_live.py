from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import pickle
import struct
import threading
import time
from types import SimpleNamespace
from typing import get_type_hints
import zlib

from fastapi import FastAPI
import httpx
import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterKind
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_core import DurableEventRecord
from openzyme_core import EngineDocumentRecord
from openzyme_core import MutationScopeService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import ScientificAttemptError
from openzyme_core import scientific_attempt_authorization_identity
from openzyme_core import verify_quiescence_evidence
from openzyme_host_api import aox_cutover_live as live
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_cutover_cli import build_parser
from openzyme_host_api.aox_cutover_evidence import AttemptRunContext
from openzyme_host_api.aox_cutover_evidence import build_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import controlled_operation_digest
from openzyme_host_api.aox_cutover_evidence import (
    create_blank_world_roots as _create_blank_world_roots,
)
from openzyme_host_api.aox_cutover_evidence import safe_micu_ledger_snapshot
from openzyme_host_api.aox_cutover_evidence import seal_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import _report_publish_receipt_is_valid
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)
from openzyme_host_api.aox_runtime_observation import (
    KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS,
)
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import LiveMicuTokenLedger
from openzyme_runtime import MutationClosureMode
from openzyme_runtime import RuntimeDrainContract
from openzyme_host_api import aox_cutover_evidence as cutover_evidence


def _digest(label: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def test_pinned_scientific_result_accessor_types_match_workflow_facts() -> None:
    text_accessors = (
        aox_reference.HmmReferenceSetSelectionResult.to_fasta,
        aox_reference.HmmReferenceSetSelectionResult.metadata_json,
        aox_reference.ScoringReferenceSelectionResult.to_fasta,
        aox_reference.ScoringReferenceSelectionResult.metadata_json,
        aox_reference.ScoringInputAssemblyResult.to_fasta,
        aox_reference.ScoringInputAssemblyResult.metadata_json,
        aox_hmmer.ScoreFilteredAccessionsResult.to_csv,
        aox_sequence_join.SequenceLengthJoinResult.hits_csv,
        aox_sequence_join.SequenceLengthJoinResult.target_fasta,
        aox_motif.ScoringResult.to_csv,
        aox_similarity.SimilarityGraphResult.nodes_csv,
        aox_similarity.SimilarityGraphResult.edges_csv,
        aox_similarity.SimilarityGraphResult.manifest_json,
    )
    metadata_accessors = (
        aox_hmmer.ScoreFilteredAccessionsResult.metadata,
        aox_sequence_join.SequenceLengthJoinResult.metadata,
        aox_motif.ScoringResult.metadata,
    )

    assert all(get_type_hints(accessor)["return"] is str for accessor in text_accessors)
    assert all(
        get_type_hints(accessor)["return"] == dict[str, object]
        for accessor in metadata_accessors
    )


class _OperationReadProvider:
    """Read-only repository double for the cutover approval budget guard."""

    class _Scope:
        def __init__(
            self,
            operations: tuple[ControlledOperation, ...],
            sandbox_runs: dict[str, object],
        ) -> None:
            self.repositories = SimpleNamespace(
                controlled_operations=SimpleNamespace(
                    list_by_session=lambda _session_id: operations
                ),
                sandbox_runs=SimpleNamespace(
                    get=sandbox_runs.get,
                    list_by_session=lambda _session_id: tuple(sandbox_runs.values()),
                ),
            )

        def __enter__(self) -> _OperationReadProvider._Scope:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def __init__(
        self,
        *operations: ControlledOperation,
        sandbox_runs: tuple[object, ...] = (),
    ) -> None:
        self._operations = tuple(operations)
        self._sandbox_runs = {
            str(getattr(run, "sandbox_run_id")): run for run in sandbox_runs
        }

    def read(self) -> _OperationReadProvider._Scope:
        return self._Scope(self._operations, self._sandbox_runs)


class _SelectedChainApprovalProvider:
    class _Scope:
        def __init__(self, repositories: object) -> None:
            self.repositories = repositories

        def __enter__(self) -> _SelectedChainApprovalProvider._Scope:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def __init__(
        self,
        *,
        operations: tuple[ControlledOperation, ...],
        sandbox_runs: tuple[object, ...],
        attempt: object,
        authority: object,
        executions: dict[str, object],
        operation_attempt_ids: dict[str, str],
        run_attempt_ids: dict[str, str],
        closure_request: object | None = None,
        closure: object | None = None,
    ) -> None:
        runs_by_id = {str(getattr(run, "sandbox_run_id")): run for run in sandbox_runs}
        self._repositories = SimpleNamespace(
            controlled_operations=SimpleNamespace(
                list_by_session=lambda _session_id: operations
            ),
            sandbox_runs=SimpleNamespace(
                get=runs_by_id.get,
                list_by_session=lambda _session_id: sandbox_runs,
            ),
            scientific_attempts=SimpleNamespace(
                list_by_session=lambda _session_id: (attempt,),
                get=lambda attempt_id: (
                    attempt if attempt_id == getattr(attempt, "attempt_id") else None
                ),
            ),
            scientific_attempt_authorizations=SimpleNamespace(
                get=lambda _envelope_id: authority
            ),
            scientific_attempt_closure_requests=SimpleNamespace(
                get_by_attempt=lambda _attempt_id: closure_request
            ),
            scientific_attempt_closures=SimpleNamespace(
                get_by_attempt=lambda _attempt_id: closure
            ),
            controlled_operation_executions=SimpleNamespace(
                get_by_operation_id=executions.get
            ),
            scientific_attempt_bindings=SimpleNamespace(
                attempt_for_operation=operation_attempt_ids.get,
                attempt_for_run=run_attempt_ids.get,
            ),
        )

    def read(self) -> _SelectedChainApprovalProvider._Scope:
        return self._Scope(self._repositories)


class _AuthorityGrantProvider:
    class _Scope:
        def __init__(self, repositories: object) -> None:
            self.repositories = repositories

        def __enter__(self) -> _AuthorityGrantProvider._Scope:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def __init__(
        self,
        *,
        task: object,
        lane: object,
        agent: object,
        existing: object | None = None,
    ) -> None:
        self._repositories = SimpleNamespace(
            tasks=SimpleNamespace(get=lambda _task_id: task),
            lanes=SimpleNamespace(get=lambda _lane_id: lane),
            agents=SimpleNamespace(get=lambda _session_id, _agent_id: agent),
            scientific_attempt_authorizations=SimpleNamespace(
                get=lambda _envelope_id: existing
            ),
        )

    def read(self) -> _AuthorityGrantProvider._Scope:
        return self._Scope(self._repositories)


def _disable_cutover_operation_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep coordination-only tests independent from repository fixtures."""

    monkeypatch.setattr(
        live,
        "_assert_cutover_operation_budget_before_approval",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        live.AoxRuntimeObservationService,
        "has_inflight_mutation_writers",
        lambda *args, **kwargs: False,
    )


def _chrome_effective_config() -> dict[str, object]:
    return {"driver": {"ui_dist_digest": _digest("built-ui-dist")}}


def _public_receipt(
    *,
    sequence: int,
    route: str,
    semantic_value: object,
) -> live.PublicApiReceipt:
    return live.PublicApiReceipt(
        sequence=sequence,
        method="GET",
        route=route,
        status_code=200,
        request_digest=_digest(f"request:{sequence}:{route}"),
        response_digest=_digest(f"response:{sequence}:{route}"),
        response_semantic_digest=live.canonical_digest(semantic_value),
    )


class _ReceiptAwareFake:
    """Small fake-side mirror of the driver's thread-local receipt contract."""

    def __init__(
        self,
        initial_receipts: tuple[live.PublicApiReceipt, ...] = (),
    ) -> None:
        self._receipt_lock = threading.Lock()
        self._receipts = list(initial_receipts)
        self._thread_state = threading.local()
        if initial_receipts:
            self._thread_state.last_receipt = initial_receipts[-1]

    @property
    def receipts(self) -> tuple[live.PublicApiReceipt, ...]:
        with self._receipt_lock:
            return tuple(self._receipts)

    @property
    def last_receipt(self) -> live.PublicApiReceipt:
        receipt = getattr(self._thread_state, "last_receipt", None)
        if not isinstance(receipt, live.PublicApiReceipt):
            raise live.LiveProductPathError(
                "public_api_response_receipt_missing",
                "current fake API thread has no response receipt",
            )
        return receipt

    def _append_receipt(self, receipt: live.PublicApiReceipt) -> None:
        with self._receipt_lock:
            self._receipts.append(receipt)
        self._thread_state.last_receipt = receipt


class _JsonResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> object:
        return self._payload


class _OutOfOrderJsonClient:
    base_url = "http://127.0.0.1:54321"

    def __init__(self) -> None:
        self.routes = (
            "/v3/sessions/sess_receipt_first/workspace",
            "/v3/sessions/sess_receipt_second/workspace",
        )
        self.started = {route: threading.Event() for route in self.routes}
        self.release = {route: threading.Event() for route in self.routes}

    def get(self, route: str) -> _JsonResponse:
        assert route in self.started
        self.started[route].set()
        if not self.release[route].wait(timeout=2.0):
            raise AssertionError(f"test did not release {route}")
        return _JsonResponse({"route": route})


def _approval_projection_response(
    route: str,
    *,
    session_id: str,
    pending_approvals: list[dict[str, object]],
) -> _JsonResponse:
    workspace_route = f"/v3/sessions/{session_id}/workspace"
    compact_route = f"/v3/sessions/{session_id}/pending-approvals"
    assert route in {workspace_route, compact_route}
    payload: dict[str, object] = {"pending_approvals": pending_approvals}
    if route == compact_route:
        payload["session_id"] = session_id
    return _JsonResponse(payload)


def _runtime_command_response(
    *,
    session_id: str,
    status: str,
    command_id: str = "runtime_command_001",
    status_code: int = 200,
) -> _JsonResponse:
    bounded_outcome_summary = None
    if status in {"completed", "locked"}:
        bounded_outcome_summary = {
            "schema_version": "runtime_command_outcome@2",
            "core_receipt_formed": True,
            "scheduler_status": status,
            "processed_signal_count": 0,
            "suspended": False,
            "projection_status": "complete",
            "projection_error_code": None,
            "projection_failed_stage": None,
            "replay_safe": True,
            "output_count": 0,
            "output_ids": [],
            "output_ids_truncated": False,
            "event_count": 0,
            "event_ids": [],
            "event_ids_truncated": False,
        }
    return _JsonResponse(
        {
            "session_id": session_id,
            "command_id": command_id,
            "status": status,
            "status_url": (f"/v3/sessions/{session_id}/runtime/commands/{command_id}"),
            "bounded_outcome_summary": bounded_outcome_summary,
        },
        status_code=status_code,
    )


class _SerialApprovalJsonClient:
    base_url = "http://127.0.0.1:54321"

    def __init__(self, approval_ids: tuple[str, ...]) -> None:
        self.approval_ids = approval_ids
        self._condition = threading.Condition()
        self._current_index: int | None = None
        self._force_release = False
        self._drain_inflight = False
        self.drain_started = threading.Event()
        self.resolve_calls: list[tuple[str, str, bool]] = []
        self.call_order: list[str] = []
        self.drain_payloads: list[dict[str, object]] = []
        self.get_routes: list[str] = []

    def get(self, route: str) -> _JsonResponse:
        self.get_routes.append(route)
        if route == ("/v3/sessions/sess_serial/runtime/commands/runtime_command_001"):
            with self._condition:
                completed = self._force_release or (
                    self._current_index is not None
                    and self._current_index >= len(self.approval_ids)
                )
                if completed:
                    self._drain_inflight = False
            return _runtime_command_response(
                session_id="sess_serial",
                status="completed" if completed else "claimed",
            )
        with self._condition:
            pending: list[dict[str, object]] = []
            if (
                not self._force_release
                and self._current_index is not None
                and self._current_index < len(self.approval_ids)
            ):
                pending = [{"approval_id": self.approval_ids[self._current_index]}]
        return _approval_projection_response(
            route,
            session_id="sess_serial",
            pending_approvals=pending,
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_serial/runtime/drain":
            self.drain_payloads.append(dict(json))
            with self._condition:
                self._current_index = 0
                self._drain_inflight = True
                self.drain_started.set()
                self._condition.notify_all()
            return _runtime_command_response(
                session_id="sess_serial",
                status="accepted",
                status_code=202,
            )

        prefix = "/v3/approvals/"
        suffix = "/resolve"
        assert route.startswith(prefix) and route.endswith(suffix)
        approval_id = route[len(prefix) : -len(suffix)]
        decision = str(json.get("decision") or "")
        with self._condition:
            assert self._current_index is not None
            assert self._current_index < len(self.approval_ids)
            assert approval_id == self.approval_ids[self._current_index]
            self.call_order.append(f"resolve:{approval_id}:{decision}")
            self.resolve_calls.append((approval_id, decision, self._drain_inflight))
            self._current_index += 1
            if decision != "approved":
                self._force_release = True
            self._condition.notify_all()
        return _JsonResponse({"approval_id": approval_id, "decision": decision})

    def release_all(self) -> None:
        with self._condition:
            self._force_release = True
            self._condition.notify_all()


class _TerminalOutcomeJsonClient(_SerialApprovalJsonClient):
    def __init__(self, outcome: object) -> None:
        super().__init__(())
        self.outcome = outcome

    def get(self, route: str) -> _JsonResponse:
        if route == ("/v3/sessions/sess_serial/runtime/commands/runtime_command_001"):
            payload: dict[str, object] = {
                "session_id": "sess_serial",
                "command_id": "runtime_command_001",
                "status": "completed",
                "status_url": (
                    "/v3/sessions/sess_serial/runtime/commands/runtime_command_001"
                ),
            }
            if self.outcome is not None:
                payload["bounded_outcome_summary"] = self.outcome
            return _JsonResponse(payload)
        return super().get(route)


class _FailingDrainJsonClient:
    base_url = "http://127.0.0.1:54321"

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del json, headers
        assert route == "/v3/sessions/sess_failed/runtime/drain"
        raise RuntimeError("private background failure detail")


class _ConcurrentDrainAndWorkspaceFailureJsonClient:
    """Fail command observation, then fail the first cleanup projection."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, *, drain_thread_name: str) -> None:
        self.drain_thread_name = drain_thread_name
        self.workspace_get_started = threading.Event()
        self.drain_failure_started = threading.Event()
        self.command_get_count = 0
        self.workspace_get_count = 0

    def get(self, route: str) -> _JsonResponse:
        if route.endswith("/runtime/commands/runtime_command_001"):
            self.command_get_count += 1
            if self.command_get_count == 1:
                self.drain_failure_started.set()
                raise RuntimeError("private command status failure detail")
            return _runtime_command_response(
                session_id="sess_concurrent_failure",
                status="failed",
            )
        assert route == "/v3/sessions/sess_concurrent_failure/pending-approvals"
        self.workspace_get_started.set()
        self.workspace_get_count += 1
        if self.workspace_get_count == 1:
            raise RuntimeError("private workspace failure detail")
        return _approval_projection_response(
            route,
            session_id="sess_concurrent_failure",
            pending_approvals=[],
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del json, headers
        assert route == ("/v3/sessions/sess_concurrent_failure/runtime/drain")
        return _runtime_command_response(
            session_id="sess_concurrent_failure",
            status="accepted",
            status_code=202,
        )


class _CoordinationCleanupFailureJsonClient:
    """Keep the drain blocked while primary and cleanup reads both fail."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, *, drain_fails: bool) -> None:
        self.drain_fails = drain_fails
        self.release_drain = threading.Event()
        self.cleanup_attempted = threading.Event()
        self.drain_finished = threading.Event()
        self.workspace_get_count = 0
        self.primary_error = live.LiveProductPathError(
            "scientific_primary_failure",
            "formal scientific path failed before cleanup",
            details={"scientific_stage": "motif"},
        )
        self.cleanup_error = RuntimeError("private cleanup failure detail")
        self.drain_error = RuntimeError("private drain failure detail")

    def get(self, route: str) -> _JsonResponse:
        if route.endswith("/runtime/commands/runtime_command_001"):
            terminal = self.release_drain.is_set()
            if terminal:
                self.drain_finished.set()
            return _runtime_command_response(
                session_id="sess_cleanup_precedence",
                status=(
                    "failed"
                    if terminal and self.drain_fails
                    else "completed"
                    if terminal
                    else "claimed"
                ),
            )
        assert route == "/v3/sessions/sess_cleanup_precedence/pending-approvals"
        self.workspace_get_count += 1
        if self.workspace_get_count == 1:
            raise self.primary_error
        if self.workspace_get_count == 2:
            self.cleanup_attempted.set()
            self.release_drain.set()
            raise self.cleanup_error
        return _approval_projection_response(
            route,
            session_id="sess_cleanup_precedence",
            pending_approvals=[],
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del json, headers
        assert route == ("/v3/sessions/sess_cleanup_precedence/runtime/drain")
        return _runtime_command_response(
            session_id="sess_cleanup_precedence",
            status="accepted",
            status_code=202,
        )


class _DelayedCoordinationCleanupApprovalJsonClient:
    """Publish an approval only after failed coordination enters cleanup."""

    base_url = "http://127.0.0.1:54321"

    def __init__(
        self,
        *,
        fail_first_cleanup_read: bool,
        empty_cleanup_reads: int,
    ) -> None:
        self.fail_first_cleanup_read = fail_first_cleanup_read
        self.empty_cleanup_reads = empty_cleanup_reads
        self.approval_id = "approval_delayed_after_coordination_error"
        self.primary_error = live.LiveProductPathError(
            "browser_observation_chain_invalid",
            "formal browser observation chain failed before a later approval",
        )
        self.cleanup_error = RuntimeError("private transient cleanup read detail")
        self.release_drain = threading.Event()
        self.drain_finished = threading.Event()
        self.workspace_get_count = 0
        self.cleanup_read_count = 0
        self.resolve_calls: list[tuple[str, str]] = []

    def get(self, route: str) -> _JsonResponse:
        if route.endswith("/runtime/commands/runtime_command_001"):
            terminal = self.release_drain.is_set()
            if terminal:
                self.drain_finished.set()
            return _runtime_command_response(
                session_id="sess_delayed_cleanup",
                status="failed" if terminal else "claimed",
            )
        assert route == "/v3/sessions/sess_delayed_cleanup/pending-approvals"
        self.workspace_get_count += 1
        if self.workspace_get_count == 1:
            raise self.primary_error

        self.cleanup_read_count += 1
        if self.fail_first_cleanup_read and self.cleanup_read_count == 1:
            raise self.cleanup_error
        successful_cleanup_read = self.cleanup_read_count - int(
            self.fail_first_cleanup_read
        )
        if successful_cleanup_read <= self.empty_cleanup_reads:
            return _approval_projection_response(
                route,
                session_id="sess_delayed_cleanup",
                pending_approvals=[],
            )
        return _approval_projection_response(
            route,
            session_id="sess_delayed_cleanup",
            pending_approvals=[{"approval_id": self.approval_id}],
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_delayed_cleanup/runtime/drain":
            return _runtime_command_response(
                session_id="sess_delayed_cleanup",
                status="accepted",
                status_code=202,
            )

        assert route == f"/v3/approvals/{self.approval_id}/resolve"
        decision = str(json.get("decision") or "")
        self.resolve_calls.append((self.approval_id, decision))
        assert decision == "rejected"
        self.release_drain.set()
        return _JsonResponse({"approval_id": self.approval_id, "decision": decision})


class _DrainReturnsPendingApprovalJsonClient:
    """Expose an approval in the same bounded response that yields for it."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        self.pending = False
        self.drain_returned = threading.Event()
        self.resolve_calls: list[tuple[str, str, bool]] = []

    def get(self, route: str) -> _JsonResponse:
        if route == (
            "/v3/sessions/sess_post_response/runtime/commands/runtime_command_001"
        ):
            return _runtime_command_response(
                session_id="sess_post_response",
                status="completed",
            )
        return _approval_projection_response(
            route,
            session_id="sess_post_response",
            pending_approvals=(
                [{"approval_id": self.approval_id}] if self.pending else []
            ),
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_post_response/runtime/drain":
            self.pending = True
            self.drain_returned.set()
            return _runtime_command_response(
                session_id="sess_post_response",
                status="completed",
                status_code=202,
            )

        expected_route = f"/v3/approvals/{self.approval_id}/resolve"
        assert route == expected_route
        decision = str(json.get("decision") or "")
        self.resolve_calls.append(
            (self.approval_id, decision, self.drain_returned.is_set())
        )
        self.pending = False
        return _JsonResponse({"approval_id": self.approval_id, "decision": decision})


class _TerminalCommandDelayedApprovalJsonClient:
    """Publish an attached approval after the bounded command is terminal."""

    base_url = "http://127.0.0.1:54321"

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        self.pending = False
        self.resolve_calls: list[tuple[str, str]] = []

    def get(self, route: str) -> _JsonResponse:
        if route == (
            "/v3/sessions/sess_terminal_writer/runtime/commands/runtime_command_001"
        ):
            return _runtime_command_response(
                session_id="sess_terminal_writer",
                status="completed",
            )
        return _approval_projection_response(
            route,
            session_id="sess_terminal_writer",
            pending_approvals=(
                [{"approval_id": self.approval_id}] if self.pending else []
            ),
        )

    def post(
        self,
        route: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _JsonResponse:
        del headers
        if route == "/v3/sessions/sess_terminal_writer/runtime/drain":
            return _runtime_command_response(
                session_id="sess_terminal_writer",
                status="completed",
                status_code=202,
            )
        assert route == f"/v3/approvals/{self.approval_id}/resolve"
        decision = str(json.get("decision") or "")
        self.resolve_calls.append((self.approval_id, decision))
        self.pending = False
        return _JsonResponse({"approval_id": self.approval_id, "decision": decision})


def _one_pixel_grayscale_png(
    *,
    filter_byte: int,
    trailing_zlib_bytes: bytes = b"",
) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(bytes((filter_byte, 0))) + trailing_zlib_bytes
    content = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(content).decode("ascii")


def _identity() -> dict[str, str]:
    return {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }


def _attempt_authority(
    roots: cutover_evidence.BlankWorldRoots,
) -> dict[str, object]:
    suffix = roots.attempt_id.replace("-", "_")
    session_id = f"sess_formal_{suffix}"
    task_id = f"aox_execution_cutover_{suffix}"
    lane_id = f"lane_aox_execution_{suffix}"
    scope = "fault" if roots.attempt_kind == "fault" else "formal"
    identity_digest = cutover_evidence.canonical_digest(_identity())
    envelope_id, request_digest, request = scientific_attempt_authorization_identity(
        session_id=session_id,
        task_id=task_id,
        campaign_id="aox_campaign_test",
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        root_ref=f"attempts/{roots.attempt_id}",
        grantor_kind="operator",
        grantor_ref="user:local-dev",
        allowed_scopes=(scope,),
        allowed_effect_classes=("hpc", "provider"),
        allowed_providers=(f"aox-provider-routes@{identity_digest}",),
        allowed_hpc_targets=(f"aox-hpc-routes@{identity_digest}",),
        max_attempts=1,
        max_micu=10_000,
        max_cost_microunits=10_000_000,
        max_wall_time_seconds=3_600,
        expires_at="2099-01-01T00:00:00+00:00",
        idempotency_key=f"{roots.attempt_id}:authority",
    )
    return {
        "ordinal": 1,
        "attempt_kind": roots.attempt_kind,
        "attempt_id": roots.attempt_id,
        "session_id": session_id,
        "task_id": task_id,
        "lane_id": lane_id,
        "scope": scope,
        "authority_request": request,
        "envelope_id": envelope_id,
        "request_digest": request_digest,
    }


def _architecture_qualification() -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest=_digest("qualification-report"),
        registry_digest=_digest("qualification-registry"),
        test_manifest_digest=_digest("qualification-manifest"),
        profile_id="local_single_process_file_sqlite@1",
        source_commit=_identity()["git_commit"],
    )


def create_blank_world_roots(*args, **kwargs):
    kwargs.setdefault("architecture_qualification", _architecture_qualification())
    return _create_blank_world_roots(*args, **kwargs)


def test_live_uniprot_raw_response_parser_is_strict_and_digest_bound() -> None:
    body = b'{"results":[{"primaryAccession":"P12345"}]}\n'
    body_digest = hashlib.sha256(body).hexdigest()
    response = {
        "schema_id": "provider_raw_http_response_set@1",
        "provider": "uniprot",
        "operation": "bio.uniprot_fetch",
        "responses": [
            {
                "ordinal": 1,
                "phase": "page:1",
                "status_code": 200,
                "headers": {},
                "body_encoding": "base64",
                "body_base64": base64.b64encode(body).decode("ascii"),
                "body_digest": f"sha256:{body_digest}",
                "size_bytes": len(body),
            }
        ],
    }
    content = (json.dumps(response, sort_keys=True, indent=2) + "\n").encode()

    assert live._raw_provider_response_digests(content) == (f"sha256:{body_digest}",)

    duplicate_body = (
        b'{"results":[{"primaryAccession":"P12345","primaryAccession":"P12345"}]}\n'
    )
    response["responses"][0].update(
        {
            "body_base64": base64.b64encode(duplicate_body).decode("ascii"),
            "body_digest": "sha256:" + hashlib.sha256(duplicate_body).hexdigest(),
            "size_bytes": len(duplicate_body),
        }
    )
    duplicate_content = (json.dumps(response, sort_keys=True, indent=2) + "\n").encode()

    assert live._raw_provider_response_digests(duplicate_content) == ()


def _allowed_prerequisites() -> dict[str, object]:
    identity = _identity()
    hmmer_digest = _digest("hmmer-sif")
    return {
        "git_commit": identity["git_commit"],
        "config_digest": identity["config_digest"],
        "workflow_ref": identity["workflow_ref"],
        "image_digest": identity["image_digest"],
        "sdk_digest": identity["sdk_digest"],
        "toolchain_image_digests": {
            contract["toolchain_id"]: (
                hmmer_digest
                if tool_name in {"hmmbuild", "hmmalign"}
                else _digest(f"{tool_name}-sif")
            )
            for tool_name, contract in live.AOX_TOOLCHAIN_RUNTIME_CONTRACTS.items()
        },
        "credential_slots": {
            "llm": True,
            "ncbi": True,
            "semantic_scholar": False,
            "tavily": False,
        },
        "ncbi_identity": _digest("ncbi-identity"),
        "prompt_accessions": {
            "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
            "probe_ncbi": list(live.KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "probe_uniprot": list(live.KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
        },
    }


def _operation() -> ControlledOperation:
    material = {
        "schema_version": "s12.adapter_envelope.v1",
        "sandbox_workspace_id": "sandbox_workspace_001",
        "source_snapshot_digest": _digest("source"),
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "params_digest": _digest("params"),
        "input_artifact_ids": ["art_input"],
        "input_artifact_digests": [_digest("input")],
        "placement": "hpc",
        "hpc_workspace_id": "hpcws_001",
        "stage_refs": [
            {
                "kind": "hpc_stage_ref",
                "stage_ref_id": "stage_001",
                "hpc_workspace_id": "hpcws_001",
                "artifact_id": "art_input",
                "artifact_digest": _digest("input"),
                "workspace_relative_path": "inputs/query.fasta",
            }
        ],
        "selected_backend": "hpc",
        "route_reason": "static_policy:v1",
        "route_policy_id": "bio_tools.mafft.hpc:v1",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "provider_config_digest": None,
        "resource_class": "hpc_batch_small",
        "resource_estimate": {
            "placement": "hpc",
            "resource_class": "hpc_batch_small",
        },
        "expected_outputs": {
            "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
        },
        "planned_fetch_intent": {
            "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
        },
        "approval_requirement": {"required": True},
    }
    return ControlledOperation(
        operation_id="op_001",
        session_id="sess_001",
        sandbox_workspace_id="sandbox_workspace_001",
        sandbox_run_id="sandbox_run_001",
        logical_operation_key="bio_tools.mafft:key",
        operation_digest=controlled_operation_digest(material),
        params_digest=_digest("params"),
        backend_category="hpc",
        status=ControlledOperationStatus.COMPLETED,
        created_at="2026-07-17T00:00:00+00:00",
        updated_at="2026-07-17T00:00:01+00:00",
        approval_id="approval_001",
        approval_state="approved",
        route_reason="static_policy:v1",
        input_artifact_digests=(_digest("input"),),
        source_snapshot_artifact_id="art_source",
        source_snapshot_digest=_digest("source"),
        adapter_envelope_schema_version="s12.adapter_envelope.v1",
        sdk_module="bio_tools",
        function_name="mafft",
        route_policy_id="bio_tools.mafft.hpc:v1",
        placement="hpc",
        hpc_workspace_id="hpcws_001",
        selected_backend="hpc",
        resource_class="hpc_batch_small",
        runtime_packaging_id="hpc_apptainer_sif.aox_hmm_2026_05_30",
        toolchain_id="mafft_7.525.hpc_apptainer_sif:v1",
        input_artifact_ids=("art_input",),
        stage_refs=tuple(material["stage_refs"]),
        planned_fetch_intent=dict(material["planned_fetch_intent"]),
        approval_requirement={"required": True},
        adapter_result_envelope={"run_id": "job_001"},
        expected_outputs_summary=dict(material["expected_outputs"]),
        resource_estimate=dict(material["resource_estimate"]),
        result_summary={
            "toolchain_runtime_identity": {
                "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
                "attestation_scope": "same_ssh_login_shell_pre_exec",
                "execution_mode": "ssh",
                "tool_id": "bio_tools.mafft",
                "adapter_id": "bio_tools.mafft",
                "command_template_id": "bio_tools_mafft_sif_v1",
                "runner_contract_digest": _digest("runner-contract"),
                "image_digest": _digest("mafft-sif"),
            }
        },
    )


def _provider_http_operation(
    adapter_result_envelope: dict[str, object],
) -> ControlledOperation:
    operation = _operation()
    material = live.controlled_operation_identity_material(operation)
    material.update(
        {
            "placement": "provider",
            "hpc_workspace_id": None,
            "stage_refs": [],
            "selected_backend": "provider_http",
            "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
            "runtime_packaging_id": "provider_http:v1",
            "toolchain_id": None,
            "provider_config_digest": "provider_config:ncbi:v1",
            "resource_class": "network_io",
            "resource_estimate": {"network_io": True},
        }
    )
    return replace(
        operation,
        operation_digest=controlled_operation_digest(material),
        backend_category="provider_http",
        placement="provider",
        hpc_workspace_id=None,
        stage_refs=(),
        selected_backend="provider_http",
        route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
        runtime_packaging_id="provider_http:v1",
        toolchain_id=None,
        provider_config_digest="provider_config:ncbi:v1",
        resource_class="network_io",
        resource_estimate={"network_io": True},
        adapter_result_envelope=adapter_result_envelope,
    )


def test_live_collector_preserves_exact_control_plane_operation_digest() -> None:
    operation = _operation()
    material = live.controlled_operation_identity_material(operation)
    record = live.operation_evidence_record(
        operation,
        scope="probe",
        inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
        outputs=[{"artifact_id": "art_output", "content_digest": _digest("output")}],
    )

    assert controlled_operation_digest(material) == operation.operation_digest
    assert record["operation_identity_schema"] == (
        "openzyme_controlled_operation_s12@1"
    )
    assert record["operation_identity_digest"] == operation.operation_digest
    assert record["backend_run_id"] == "job_001"


def test_live_collector_rejects_noncanonical_hpc_backend_identity() -> None:
    operation = replace(
        _operation(),
        adapter_result_envelope={"backend_run_id": "job_legacy"},
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live.operation_evidence_record(
            operation,
            scope="probe",
            inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
            outputs=[
                {"artifact_id": "art_output", "content_digest": _digest("output")}
            ],
        )

    assert error.value.code == "controlled_operation_backend_identity_ambiguous"
    assert error.value.details["canonical_field"] == "run_id"


def test_live_collector_requires_current_hpc_run_id_for_completed_operation() -> None:
    operation = replace(_operation(), adapter_result_envelope={})

    with pytest.raises(live.LiveProductPathError) as error:
        live.operation_evidence_record(
            operation,
            scope="probe",
            inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
            outputs=[
                {"artifact_id": "art_output", "content_digest": _digest("output")}
            ],
        )

    assert error.value.code == "controlled_operation_backend_receipt_missing"
    assert error.value.details["canonical_field"] == "run_id"


def test_live_collector_rejects_mismatched_hpc_backend_identities() -> None:
    operation = replace(
        _operation(),
        adapter_result_envelope={
            "run_id": "job_current",
            "backend_run_id": "job_other",
        },
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live.operation_evidence_record(
            operation,
            scope="probe",
            inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
            outputs=[
                {"artifact_id": "art_output", "content_digest": _digest("output")}
            ],
        )

    assert error.value.code == "controlled_operation_backend_identity_mismatch"
    assert error.value.details["conflicting_fields"] == ["backend_run_id"]


def test_live_positive_task_receipts_require_owner_authorship() -> None:
    task_specs = (
        ("task_research", "researcher", "research"),
        ("task_execution", "executor", "execution"),
        ("task_report", "reporter", "reporting"),
    )
    tasks = tuple(
        SimpleNamespace(
            task_id=task_id,
            assigned_ref=f"agent_{role}",
            status=SimpleNamespace(value="completed"),
            kind=kind,
            lane_id=f"lane_{role}",
        )
        for task_id, role, kind in task_specs
    )
    agents = tuple(
        SimpleNamespace(agent_id=f"agent_{role}", role=role)
        for _, role, _ in task_specs
    )
    documents = tuple(
        SimpleNamespace(
            document_id=f"finish_{task_id}",
            document_kind="task_finish",
            payload={
                "task_id": task_id,
                "status": "completed",
                "finished_by": (
                    "agent:master" if role == "executor" else f"agent_{role}"
                ),
                "evidence_refs": [],
            },
        )
        for task_id, role, _ in task_specs
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._task_receipts(
            tasks=tasks,
            agents=agents,
            documents=documents,
        )

    assert error.value.code == "formal_task_finish_invalid"
    assert error.value.details == {
        "task_id": "task_execution",
        "expected_finished_by": "agent_executor",
        "observed_finished_by": "agent:master",
    }


def test_live_fault_task_receipts_require_owner_authorship() -> None:
    task = SimpleNamespace(
        task_id="task_execution",
        assigned_ref="agent_executor",
        status=SimpleNamespace(value="failed"),
        kind="execution",
        lane_id="lane_executor",
    )
    agent = SimpleNamespace(agent_id="agent_executor", role="executor")
    finish = SimpleNamespace(
        document_id="finish_task_execution",
        document_kind="task_finish",
        payload={
            "task_id": "task_execution",
            "status": "failed",
            "finished_by": "agent:master",
            "evidence_refs": [],
        },
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._fault_task_receipts(
            tasks=(task,),
            agents=(agent,),
            documents=(finish,),
            consumer_task_id="task_execution",
        )

    assert error.value.code == "fault_task_business_exit_invalid"
    assert error.value.details == {
        "task_id": "task_execution",
        "expected_finished_by": "agent_executor",
        "observed_finished_by": "agent:master",
    }


def test_live_collector_uses_canonical_provider_http_request_id() -> None:
    operation = _provider_http_operation(
        {"provider_request_id": "provider_request_001"}
    )

    record = live.operation_evidence_record(
        operation,
        scope="probe",
        inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
        outputs=[{"artifact_id": "art_output", "content_digest": _digest("output")}],
    )

    assert record["backend_run_id"] == "provider_request_001"


@pytest.mark.parametrize(
    ("adapter_result_envelope", "expected_code", "conflicting_fields"),
    [
        (
            {"run_id": "legacy_run_001"},
            "controlled_operation_backend_identity_ambiguous",
            ["run_id"],
        ),
        ({}, "controlled_operation_backend_receipt_missing", None),
        (
            {
                "provider_request_id": "provider_request_001",
                "run_id": "other_run_001",
            },
            "controlled_operation_backend_identity_mismatch",
            ["run_id"],
        ),
    ],
)
def test_live_collector_rejects_invalid_provider_http_receipt_identity(
    adapter_result_envelope: dict[str, object],
    expected_code: str,
    conflicting_fields: list[str] | None,
) -> None:
    operation = _provider_http_operation(adapter_result_envelope)

    with pytest.raises(live.LiveProductPathError) as error:
        live.operation_evidence_record(
            operation,
            scope="probe",
            inputs=[{"artifact_id": "art_input", "content_digest": _digest("input")}],
            outputs=[
                {"artifact_id": "art_output", "content_digest": _digest("output")}
            ],
        )

    assert error.value.code == expected_code
    assert error.value.details["canonical_field"] == "provider_request_id"
    if conflicting_fields is not None:
        assert error.value.details["conflicting_fields"] == conflicting_fields


def test_selected_chain_collector_allows_failed_trial_before_adopted_success() -> None:
    failed_trial = replace(
        _operation(),
        operation_id="op_reference_alignment_trial",
        status=ControlledOperationStatus.FAILED,
        operation_digest=_digest("reference-alignment-trial"),
        error_code="known_local_input_failure",
    )
    adopted_operations = (
        replace(
            _operation(),
            operation_id="op_ncbi_fetch_adopted",
            sdk_module="bio",
            function_name="ncbi_fetch_proteins",
            operation_digest=_digest("ncbi-fetch-adopted"),
        ),
        replace(
            _operation(),
            operation_id="op_reference_alignment_adopted",
            operation_digest=_digest("reference-alignment-adopted"),
        ),
        replace(
            _operation(),
            operation_id="op_hmm_build_adopted",
            sdk_module="bio_tools",
            function_name="hmmbuild",
            operation_digest=_digest("hmm-build-adopted"),
        ),
        replace(
            _operation(),
            operation_id="op_hmmer_search_adopted",
            sdk_module="bio",
            function_name="hmmer_search",
            operation_digest=_digest("hmmer-search-adopted"),
        ),
    )
    formal = live.SessionDriveResult(
        session_id="sess_selected_chain",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={},
        workspace_response_binding={},
        event_receipt={},
        drain_count=5,
        approval_ids=(),
        scientific_attempt_control={
            "adoptions": [
                {
                    "workflow_role": role,
                    "operation_id": operation.operation_id,
                }
                for role, operation in zip(
                    (
                        "ncbi_fetch",
                        "reference_alignment",
                        "hmm_build",
                        "hmmer_search",
                    ),
                    adopted_operations,
                    strict=True,
                )
            ]
        },
    )

    selected = live._selected_completed_formal_operations(
        formal,
        operations=(failed_trial, *adopted_operations),
    )

    assert selected["reference_alignment"].operation_id == (
        "op_reference_alignment_adopted"
    )
    assert failed_trial.operation_id not in {
        operation.operation_id for operation in selected.values()
    }


def test_selected_chain_approval_allows_known_failure_but_not_unknown_effect(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    authority = _attempt_authority(roots)
    request = authority["authority_request"]
    assert isinstance(request, dict)
    current = replace(
        _operation(),
        operation_id="op_current_selected_chain",
        session_id=str(authority["session_id"]),
        task_id=str(authority["task_id"]),
        lane_id=str(authority["lane_id"]),
        sandbox_run_id="run_current_selected_chain",
        approval_id="approval_current_selected_chain",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("current-selected-chain"),
    )
    failed = replace(
        _operation(),
        operation_id="op_known_failed_trial",
        session_id=current.session_id,
        task_id=current.task_id,
        lane_id=current.lane_id,
        sandbox_run_id="run_known_failed_trial",
        approval_id="approval_known_failed_trial",
        status=ControlledOperationStatus.FAILED,
        operation_digest=_digest("known-failed-trial"),
        error_code="known_input_error",
    )
    scientific_attempt_id = "scientific_attempt_selected_chain"
    attempt = SimpleNamespace(
        attempt_id=scientific_attempt_id,
        envelope_id=authority["envelope_id"],
        status=ScientificAttemptStatus.ACTIVE,
        task_id=authority["task_id"],
        lane_id=authority["lane_id"],
        root_ref=f"attempts/{authority['attempt_id']}",
        campaign_id=request["campaign_id"],
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        workflow_contract_digest=(live.AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST),
        requested_effect_classes=("hpc", "provider"),
        provider=request["allowed_providers"][0],
        hpc_target=request["allowed_hpc_targets"][0],
        reserved_micu=1_000,
        reserved_cost_microunits=1_000,
        reserved_wall_time_seconds=3_600,
        created_at=datetime.now(UTC).isoformat(),
    )
    stored_authority = SimpleNamespace(
        request_digest=authority["request_digest"],
        root_ref=attempt.root_ref,
        consumed_attempts=1,
        status=SimpleNamespace(value="exhausted"),
        allowed_providers=tuple(request["allowed_providers"]),
        allowed_hpc_targets=tuple(request["allowed_hpc_targets"]),
        expires_at=request["expires_at"],
        max_micu=request["max_micu"],
        max_cost_microunits=request["max_cost_microunits"],
        max_wall_time_seconds=request["max_wall_time_seconds"],
    )
    current_execution = SimpleNamespace(
        lifecycle_state=(ControlledOperationExecutionLifecycle.AWAITING_APPROVAL),
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
    )
    known_failed_execution = SimpleNamespace(
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
    )
    sandbox_runs = (
        SimpleNamespace(
            sandbox_run_id=failed.sandbox_run_id,
            status=SimpleNamespace(value="failed"),
            error_code="known_input_error",
        ),
        SimpleNamespace(
            sandbox_run_id=current.sandbox_run_id,
            status=SimpleNamespace(value="waiting_approval"),
            error_code=None,
        ),
    )

    def provider_for(prior_execution: object) -> object:
        return _SelectedChainApprovalProvider(
            operations=(failed, current),
            sandbox_runs=sandbox_runs,
            attempt=attempt,
            authority=stored_authority,
            executions={
                failed.operation_id: prior_execution,
                current.operation_id: current_execution,
            },
            operation_attempt_ids={
                failed.operation_id: scientific_attempt_id,
                current.operation_id: scientific_attempt_id,
            },
            run_attempt_ids={
                failed.sandbox_run_id: scientific_attempt_id,
                current.sandbox_run_id: scientific_attempt_id,
            },
        )

    live._assert_cutover_operation_budget_before_approval(
        provider_for(known_failed_execution),  # type: ignore[arg-type]
        session_id=current.session_id,
        approval_id=current.approval_id or "",
        attempt_authority=authority,
    )

    closure_requested_provider = _SelectedChainApprovalProvider(
        operations=(failed, current),
        sandbox_runs=sandbox_runs,
        attempt=attempt,
        authority=stored_authority,
        executions={
            failed.operation_id: known_failed_execution,
            current.operation_id: current_execution,
        },
        operation_attempt_ids={
            failed.operation_id: scientific_attempt_id,
            current.operation_id: scientific_attempt_id,
        },
        run_attempt_ids={
            failed.sandbox_run_id: scientific_attempt_id,
            current.sandbox_run_id: scientific_attempt_id,
        },
        closure_request=SimpleNamespace(
            closure_request_id="closure_request_before_late_approval",
            attempt_id=scientific_attempt_id,
            selection_id="selection_before_late_approval",
        ),
    )
    with pytest.raises(live.LiveProductPathError) as late_approval:
        live._assert_cutover_operation_budget_before_approval(
            closure_requested_provider,  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
            attempt_authority=authority,
        )
    assert late_approval.value.code == "scientific_attempt_approval_authority_mismatch"

    dispatch_in_doubt = SimpleNamespace(
        lifecycle_state=(ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED),
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
    )
    with pytest.raises(live.LiveProductPathError) as unresolved:
        live._assert_cutover_operation_budget_before_approval(
            provider_for(dispatch_in_doubt),  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
            attempt_authority=authority,
        )
    assert unresolved.value.code == "scientific_attempt_prior_effect_unresolved"

    unauthorized = replace(
        current,
        sdk_module="bio_tools",
        function_name="blast",
    )
    unauthorized_provider = _SelectedChainApprovalProvider(
        operations=(failed, unauthorized),
        sandbox_runs=sandbox_runs,
        attempt=attempt,
        authority=stored_authority,
        executions={
            failed.operation_id: known_failed_execution,
            unauthorized.operation_id: current_execution,
        },
        operation_attempt_ids={
            failed.operation_id: scientific_attempt_id,
            unauthorized.operation_id: scientific_attempt_id,
        },
        run_attempt_ids={
            failed.sandbox_run_id: scientific_attempt_id,
            unauthorized.sandbox_run_id: scientific_attempt_id,
        },
    )
    with pytest.raises(live.LiveProductPathError) as forbidden_method:
        live._assert_cutover_operation_budget_before_approval(
            unauthorized_provider,  # type: ignore[arg-type]
            session_id=unauthorized.session_id,
            approval_id=unauthorized.approval_id or "",
            attempt_authority=authority,
        )
    assert forbidden_method.value.code == "scientific_attempt_operation_not_authorized"


def test_closed_formal_attempt_rejects_lifecycle_mismatch_immediately() -> None:
    slot_id = f"positive-{'a' * 32}"
    attempt_id = "scientific_attempt_lifecycle_mismatch"
    authority = {
        "attempt_id": slot_id,
        "envelope_id": "attempt_authority_lifecycle_mismatch",
        "task_id": "task_lifecycle_mismatch",
        "lane_id": "lane_lifecycle_mismatch",
    }
    attempt = SimpleNamespace(
        attempt_id=attempt_id,
        envelope_id=authority["envelope_id"],
        task_id=authority["task_id"],
        lane_id=authority["lane_id"],
        root_ref=f"attempts/{slot_id}",
        status=ScientificAttemptStatus.ACTIVE,
    )
    request = SimpleNamespace(
        closure_request_id="closure_request_lifecycle_mismatch",
        attempt_id=attempt_id,
        selection_id="selection_expected",
    )
    closure = SimpleNamespace(
        closure_id="closure_lifecycle_mismatch",
        closure_request_id=request.closure_request_id,
        attempt_id=attempt_id,
        selection_id="selection_other",
    )
    provider = _SelectedChainApprovalProvider(
        operations=(),
        sandbox_runs=(),
        attempt=attempt,
        authority=SimpleNamespace(),
        executions={},
        operation_attempt_ids={},
        run_attempt_ids={},
        closure_request=request,
        closure=closure,
    )

    with pytest.raises(live.LiveProductPathError) as invalid:
        live.LiveAoxAttemptRunner._closed_formal_attempt_control(
            SimpleNamespace(),
            provider,  # type: ignore[arg-type]
            session_id="sess_lifecycle_mismatch",
            authority=authority,
        )

    assert invalid.value.code == "scientific_attempt_lifecycle_invalid"
    assert invalid.value.details == {
        "attempt_id": attempt_id,
        "closure_id": closure.closure_id,
        "closure_request_id": request.closure_request_id,
        "integrity_reason": "closure_selection_mismatch",
        "mutation_applied": False,
    }


def test_closed_formal_attempt_sanitizes_evidence_integrity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slot_id = f"positive-{'b' * 32}"
    attempt_id = "scientific_attempt_evidence_invalid"
    authority = {
        "attempt_id": slot_id,
        "envelope_id": "attempt_authority_evidence_invalid",
        "task_id": "task_evidence_invalid",
        "lane_id": "lane_evidence_invalid",
    }
    attempt = SimpleNamespace(
        attempt_id=attempt_id,
        envelope_id=authority["envelope_id"],
        task_id=authority["task_id"],
        lane_id=authority["lane_id"],
        root_ref=f"attempts/{slot_id}",
        status=ScientificAttemptStatus.ACTIVE,
    )
    request = SimpleNamespace(
        closure_request_id="closure_request_evidence_invalid",
        attempt_id=attempt_id,
        selection_id="selection_evidence_invalid",
    )
    closure = SimpleNamespace(
        closure_id="closure_evidence_invalid",
        closure_request_id=request.closure_request_id,
        attempt_id=attempt_id,
        selection_id=request.selection_id,
    )
    provider = _SelectedChainApprovalProvider(
        operations=(),
        sandbox_runs=(),
        attempt=attempt,
        authority=SimpleNamespace(),
        executions={},
        operation_attempt_ids={},
        run_attempt_ids={},
        closure_request=request,
        closure=closure,
    )

    def reject_evidence(
        _service: object,
        _attempt_id: str,
    ) -> dict[str, object]:
        raise ScientificAttemptError(
            "attempt_evidence_quiescence_missing",
            "missing exact receipt",
            details={
                "closure_id": closure.closure_id,
                "private_host_path": "/private/should-not-project",
            },
        )

    monkeypatch.setattr(
        live.ScientificAttemptService,
        "export_closed_attempt_evidence",
        reject_evidence,
    )

    with pytest.raises(live.LiveProductPathError) as invalid:
        live.LiveAoxAttemptRunner._closed_formal_attempt_control(
            SimpleNamespace(),
            provider,  # type: ignore[arg-type]
            session_id="sess_evidence_invalid",
            authority=authority,
        )

    assert invalid.value.code == "attempt_evidence_quiescence_missing"
    assert invalid.value.details == {
        "attempt_id": attempt_id,
        "closure_id": closure.closure_id,
    }


def test_cutover_operation_budget_accepts_first_method_approval() -> None:
    current = replace(
        _operation(),
        operation_id="op_current",
        approval_id="approval_current",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-current"),
    )
    provider = _OperationReadProvider(current)

    live._assert_cutover_operation_budget_before_approval(
        provider,  # type: ignore[arg-type]
        session_id=current.session_id,
        approval_id=current.approval_id or "",
    )


def test_cutover_operation_budget_rejects_duplicate_method_before_approval() -> None:
    prior = _operation()
    current = replace(
        prior,
        operation_id="op_duplicate",
        approval_id="approval_duplicate",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-duplicate"),
        created_at="2026-07-17T00:00:02+00:00",
        updated_at="2026-07-17T00:00:02+00:00",
    )
    provider = _OperationReadProvider(prior, current)

    with pytest.raises(live.LiveProductPathError) as error:
        live._assert_cutover_operation_budget_before_approval(
            provider,  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
        )

    assert error.value.code == "cutover_operation_budget_exceeded"
    assert error.value.details == {
        "session_id": "sess_001",
        "approval_id": "approval_duplicate",
        "sdk_method": "bio_tools.mafft",
        "operation_count": 2,
        "operations": [
            {"operation_id": "op_001", "status": "completed"},
            {"operation_id": "op_duplicate", "status": "waiting_approval"},
        ],
    }


def test_cutover_operation_budget_accepts_hmmer_with_v2_long_timeout() -> None:
    current = replace(
        _operation(),
        operation_id="op_hmmer",
        approval_id="approval_hmmer",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-hmmer"),
        sdk_module="bio",
        function_name="hmmer_search",
        sandbox_run_id="srun_hmmer",
    )
    run = SimpleNamespace(
        sandbox_run_id="srun_hmmer",
        resource_policy={
            "timeout_seconds": 3_600,
            "exec_policy_version": "s09.exec_policy.v2",
        },
    )
    provider = _OperationReadProvider(current, sandbox_runs=(run,))

    live._assert_cutover_operation_budget_before_approval(
        provider,  # type: ignore[arg-type]
        session_id=current.session_id,
        approval_id=current.approval_id or "",
    )


@pytest.mark.parametrize(
    ("sandbox_runs", "observed_timeout", "observed_version"),
    (
        ((), None, None),
        (
            (
                SimpleNamespace(
                    sandbox_run_id="srun_hmmer",
                    resource_policy={
                        "timeout_seconds": 900,
                        "exec_policy_version": "s09.exec_policy.v1",
                    },
                ),
            ),
            900,
            "s09.exec_policy.v1",
        ),
    ),
)
def test_cutover_operation_budget_rejects_unsafe_hmmer_sandbox_timeout(
    sandbox_runs: tuple[object, ...],
    observed_timeout: int | None,
    observed_version: str | None,
) -> None:
    current = replace(
        _operation(),
        operation_id="op_hmmer",
        approval_id="approval_hmmer",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-hmmer"),
        sdk_module="bio",
        function_name="hmmer_search",
        sandbox_run_id="srun_hmmer",
    )
    provider = _OperationReadProvider(current, sandbox_runs=sandbox_runs)

    with pytest.raises(live.LiveProductPathError) as error:
        live._assert_cutover_operation_budget_before_approval(
            provider,  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
        )

    assert error.value.code == "cutover_hmmer_sandbox_timeout_invalid"
    assert error.value.details == {
        "session_id": "sess_001",
        "approval_id": "approval_hmmer",
        "operation_id": "op_hmmer",
        "expected_timeout_seconds": 3_600,
        "observed_timeout_seconds": observed_timeout,
        "expected_exec_policy_version": "s09.exec_policy.v2",
        "observed_exec_policy_version": observed_version,
    }


def test_cutover_operation_budget_rejects_prior_failed_operation() -> None:
    failed = replace(
        _operation(),
        operation_id="op_failed",
        approval_id="approval_failed",
        sdk_module="bio_tools",
        function_name="hmmbuild",
        status=ControlledOperationStatus.FAILED,
        error_code="hpc_runner_unavailable",
        operation_digest=_digest("op-failed"),
    )
    current = replace(
        _operation(),
        operation_id="op_current",
        approval_id="approval_current",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-current"),
        created_at="2026-07-17T00:00:02+00:00",
        updated_at="2026-07-17T00:00:02+00:00",
    )
    provider = _OperationReadProvider(failed, current)

    with pytest.raises(live.LiveProductPathError) as error:
        live._assert_cutover_operation_budget_before_approval(
            provider,  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
        )

    assert error.value.code == "cutover_operation_history_failed"
    assert error.value.details == {
        "session_id": "sess_001",
        "approval_id": "approval_current",
        "operations": [
            {
                "operation_id": "op_failed",
                "sdk_method": "bio_tools.hmmbuild",
                "status": "failed",
                "error_code": "hpc_runner_unavailable",
            }
        ],
    }


def test_cutover_operation_budget_rejects_prior_failed_sandbox_run() -> None:
    current = replace(
        _operation(),
        operation_id="op_current",
        approval_id="approval_current",
        approval_state="pending",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        operation_digest=_digest("op-current"),
    )
    failed_run = SimpleNamespace(
        sandbox_run_id="srun_failed",
        status=SimpleNamespace(value="failed"),
        error_code="sandbox_exec_nonzero",
        resource_policy={},
    )
    provider = _OperationReadProvider(current, sandbox_runs=(failed_run,))

    with pytest.raises(live.LiveProductPathError) as error:
        live._assert_cutover_operation_budget_before_approval(
            provider,  # type: ignore[arg-type]
            session_id=current.session_id,
            approval_id=current.approval_id or "",
        )

    assert error.value.code == "cutover_sandbox_history_failed"
    assert error.value.details == {
        "session_id": "sess_001",
        "approval_id": "approval_current",
        "sandbox_runs": [
            {
                "sandbox_run_id": "srun_failed",
                "status": "failed",
                "error_code": "sandbox_exec_nonzero",
            }
        ],
    }


def test_public_api_receipt_normalizes_events_query_to_canonical_route() -> None:
    client = live._PublicHostClient(object())

    client._record(
        "GET",
        "/v3/sessions/sess_001/events?replay=1&after_cursor=7",
        None,
        b"data: {}\n",
        200,
    )

    assert (
        client.receipts[0].route
        == "/v3/sessions/sess_001/events?replay=1&after_cursor=7"
    )
    assert client.receipts[0].request_digest == live.canonical_digest(
        {"replay": True, "after_cursor": 7}
    )
    assert client.receipts[0].response_semantic_digest == live.canonical_digest([{}])


def test_public_api_receipts_reserve_at_start_and_seal_in_sequence_order() -> None:
    raw_client = _OutOfOrderJsonClient()
    client = live._PublicHostClient(raw_client)
    results: dict[str, tuple[dict[str, object], live.PublicApiReceipt]] = {}
    errors: dict[str, BaseException] = {}
    finished = {route: threading.Event() for route in raw_client.routes}

    def request(route: str) -> None:
        try:
            payload = client.get_json(route)
            results[route] = (payload, client.last_receipt)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors[route] = exc
        finally:
            finished[route].set()

    first_route, second_route = raw_client.routes
    first = threading.Thread(target=request, args=(first_route,))
    second = threading.Thread(target=request, args=(second_route,))
    first.start()
    try:
        assert raw_client.started[first_route].wait(timeout=1.0)
        second.start()
        assert raw_client.started[second_route].wait(timeout=1.0)

        raw_client.release[second_route].set()
        assert finished[second_route].wait(timeout=1.0)
        assert [receipt.sequence for receipt in client.receipts] == [2]
        with pytest.raises(live.LiveProductPathError) as inflight:
            client.sealed_receipts
        assert inflight.value.code == "public_api_receipt_chain_incomplete"
        with pytest.raises(live.LiveProductPathError) as main_thread:
            client.last_receipt
        assert main_thread.value.code == "public_api_response_receipt_missing"

        raw_client.release[first_route].set()
        assert finished[first_route].wait(timeout=1.0)
    finally:
        for release in raw_client.release.values():
            release.set()
        first.join(timeout=2.0)
        if second.ident is not None:
            second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == {}
    assert [receipt.sequence for receipt in client.sealed_receipts] == [1, 2]
    assert results[first_route][0] == {"route": first_route}
    assert results[first_route][1].sequence == 1
    assert results[first_route][1].route == first_route
    assert results[second_route][0] == {"route": second_route}
    assert results[second_route][1].sequence == 2
    assert results[second_route][1].route == second_route
    assert results[first_route][1].response_semantic_digest == live.canonical_digest(
        results[first_route][0]
    )
    assert results[second_route][1].response_semantic_digest == live.canonical_digest(
        results[second_route][0]
    )


def test_public_api_transport_failure_preserves_completed_failure_receipts() -> None:
    class CompletedThenDisconnectedClient:
        base_url = "http://127.0.0.1:54321"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, route: str) -> _JsonResponse:
            self.calls.append(route)
            if route == "/v3/runtime/health":
                return _JsonResponse({"status": "ready"})
            assert route == "/v3/sessions/sess_transport/workspace"
            raise httpx.ConnectError(
                "deterministic connection failure",
                request=httpx.Request("GET", f"{self.base_url}{route}"),
            )

    raw_client = CompletedThenDisconnectedClient()
    client = live._PublicHostClient(raw_client)

    assert client.get_json("/v3/runtime/health") == {"status": "ready"}
    with pytest.raises(live.LiveProductPathError) as transport_error:
        client.get_json("/v3/sessions/sess_transport/workspace")

    assert transport_error.value.code == "host_public_api_transport_failed"
    assert transport_error.value.details == {
        "route": "/v3/sessions/sess_transport/workspace",
        "failure_type": "ConnectError",
    }
    completed = client.failure_receipts
    assert [receipt.sequence for receipt in completed] == [1]
    assert [receipt.route for receipt in completed] == ["/v3/runtime/health"]
    assert client.failure_receipts == completed
    assert transport_error.value.code == "host_public_api_transport_failed"

    with pytest.raises(live.LiveProductPathError) as sealing_error:
        client.sealed_receipts

    assert sealing_error.value.code == "public_api_receipt_chain_incomplete"
    assert sealing_error.value.details == {
        "inflight_count": 0,
        "failed_count": 1,
    }
    assert client.failure_receipts == completed
    assert raw_client.calls == [
        "/v3/runtime/health",
        "/v3/sessions/sess_transport/workspace",
    ]


def test_toolchain_collector_seals_exact_runner_attested_identity() -> None:
    operation = _operation()

    receipt = live._toolchain_receipt(
        tool_name="mafft",
        operation=operation,
        operation_record={"backend_run_id": "job_001"},
    )

    assert receipt == {
        "toolchain_record_id": "toolchain_record_op_001",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "tool": "mafft",
        "operation_id": "op_001",
        "job_id": "job_001",
        "runtime_identity_schema": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "runner_contract_digest": _digest("runner-contract"),
        "image_digest": _digest("mafft-sif"),
        "status": "completed",
    }


def test_toolchain_collector_rejects_compatibility_or_envelope_fallback() -> None:
    baseline = _operation()
    runtime_identity = dict(
        dict(baseline.result_summary or {})["toolchain_runtime_identity"]
    )
    operation = replace(
        baseline,
        result_summary={
            "compatibility": {"image_digest": runtime_identity["image_digest"]}
        },
        adapter_result_envelope={
            "backend_run_id": "job_001",
            "bounded_summary": {
                "compatibility": {"image_digest": runtime_identity["image_digest"]},
                "toolchain_runtime_identity": runtime_identity,
            },
        },
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._toolchain_receipt(
            tool_name="mafft",
            operation=operation,
            operation_record={"backend_run_id": "job_001"},
        )

    assert error.value.code == "toolchain_image_identity_missing"


def test_live_collector_rejects_approval_identity_drift() -> None:
    operation = replace(_operation(), operation_digest=_digest("drift"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.controlled_operation_identity_material(operation)

    assert error.value.code == "controlled_operation_digest_mismatch"


def test_probe_runtime_completion_requires_the_full_v2_operation_set() -> None:
    assert KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS == {
        ("bio", "ncbi_fetch_proteins"),
        ("bio", "uniprot_fetch"),
        ("bio_tools", "mafft"),
        ("bio_tools", "hmmbuild"),
        ("bio_tools", "cdhit"),
        ("bio_tools", "hmmalign"),
    }


def _ready_health(*, image_digest: str, sdk_digest: str) -> dict[str, object]:
    return {
        "schema_version": "v3.runtime_health.v1",
        "status": "ready",
        "deployment_profile": "local-dev",
        "storage_profile": "single_process_sqlite",
        "components": {
            "model": {"status": "ready", "details": {}},
            "execution": {"status": "ready", "details": {}},
            "bio_research": {"status": "ready", "details": {}},
            "sandbox": {
                "status": "ready",
                "details": {
                    "image_digest": image_digest,
                    "pipeline_sdk_digest": sdk_digest,
                    "runtime_identity_digest": _digest("runtime"),
                    "sandbox_protocol_version": "openzyme-sandbox.v1",
                },
            },
        },
    }


def test_live_runner_bootstraps_verified_sandbox_image_into_fresh_sqlite(
    tmp_path: Path,
) -> None:
    identity = _identity()
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))
    health = _ready_health(
        image_digest=identity["image_digest"],
        sdk_digest=identity["sdk_digest"],
    )

    live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
        provider,
        health=health,
        identity=identity,
    )

    with provider.read() as scope:
        image = scope.repositories.sandbox_images.get_default()
    assert image is not None
    assert image.image_ref == (
        "localhost/openzyme-pipeline-sandbox@" + identity["image_digest"]
    )
    assert image.image_digest == identity["image_digest"]
    assert image.compatibility.value == "compatible"
    assert live._safe_health(health)["sandbox_runtime_identity"] == {
        "image_digest": identity["image_digest"],
        "pipeline_sdk_digest": identity["sdk_digest"],
        "runtime_identity_digest": _digest("runtime"),
        "sandbox_protocol_version": "openzyme-sandbox.v1",
    }


@pytest.mark.parametrize("mismatched_field", ("image_digest", "sdk_digest"))
def test_live_runner_rejects_campaign_sandbox_identity_drift_before_registration(
    tmp_path: Path,
    mismatched_field: str,
) -> None:
    identity = _identity()
    actual = dict(identity)
    actual[mismatched_field] = _digest(f"drift-{mismatched_field}")
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=actual["image_digest"],
                sdk_digest=actual["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "campaign_sandbox_identity_mismatch"
    assert error.value.details == {"mismatched_fields": [mismatched_field]}
    with provider.read() as scope:
        assert scope.repositories.sandbox_images.get_default() is None


@pytest.mark.parametrize("missing_field", ("image_digest", "sdk_digest"))
def test_live_runner_rejects_missing_canonical_sandbox_runtime_identity(
    tmp_path: Path,
    missing_field: str,
) -> None:
    identity = _identity()
    actual = dict(identity)
    actual[missing_field] = "sha256:short"
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=actual["image_digest"],
                sdk_digest=actual["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "sandbox_runtime_identity_missing"
    with provider.read() as scope:
        assert scope.repositories.sandbox_images.get_default() is None


def test_live_runner_rejects_preexisting_sandbox_image_registry_row(
    tmp_path: Path,
) -> None:
    identity = _identity()
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank-world.sqlite3"))
    inherited_digest = _digest("inherited-image")
    with provider.write() as scope:
        scope.repositories.sandbox_images.save(
            live.sandbox_image_record(
                image_ref=live.DEFAULT_SANDBOX_IMAGE_REF,
                image_digest=inherited_digest,
            )
        )

    with pytest.raises(live.LiveProductPathError) as error:
        live.LiveAoxAttemptRunner._bootstrap_sandbox_runtime_identity(
            provider,
            health=_ready_health(
                image_digest=identity["image_digest"],
                sdk_digest=identity["sdk_digest"],
            ),
            identity=identity,
        )

    assert error.value.code == "sandbox_image_registry_not_blank"
    with provider.read() as scope:
        image = scope.repositories.sandbox_images.get_default()
    assert image is not None
    assert image.image_digest == inherited_digest


def test_live_runner_registers_sandbox_identity_before_first_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    ledger_path = tmp_path / "persistent-micu-ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        test=replace(
            settings.test,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=identity,
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
        attempt_authority=_attempt_authority(roots),
    )
    health = _ready_health(
        image_digest=identity["image_digest"],
        sdk_digest=identity["sdk_digest"],
    )

    class Response:
        status_code = 200
        content = b'{"status":"ready"}'

        @staticmethod
        def json() -> dict[str, object]:
            return health

    class Client:
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            del args
            assert not (
                roots.artifact_root / "formal/live-product-path-blocker.json"
            ).exists()

        @staticmethod
        def get(route: str) -> Response:
            assert route == "/v3/runtime/health"
            return Response()

    observed = {"registered_before_session": False}

    def stop_at_first_session(
        self: live.LiveAoxAttemptRunner,
        api: live._PublicHostClient,
        provider: SQLiteRepositoryProvider,
        **kwargs: object,
    ) -> None:
        del self, kwargs
        with provider.read() as scope:
            image = scope.repositories.sandbox_images.get_default()
        observed["registered_before_session"] = (
            image is not None and image.image_digest == identity["image_digest"]
        )
        assert [receipt.route for receipt in api.receipts] == ["/v3/runtime/health"]
        raise live.LiveProductPathError("test_stop", "stop before session creation")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_settings_blocker",
        lambda self, context: None,
    )
    monkeypatch.setattr(live, "build_configured_foundation", lambda **kwargs: object())
    monkeypatch.setattr(live, "create_app", lambda dependencies: object())
    monkeypatch.setattr(live, "_LoopbackHost", lambda **kwargs: Client())
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner, "_run_session", stop_at_first_session
    )
    runner = live.LiveAoxAttemptRunner(settings=settings, ledger_path=ledger_path)

    evidence = runner(context)

    assert observed["registered_before_session"] is True
    assert evidence["scientific_outcome"]["blocker_code"] == "test_stop"


def test_live_session_mutation_scope_seals_real_private_snapshot(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    ledger = LiveMicuTokenLedger(ledger_path)
    reservation = ledger.reserve_attempt(
        scenario="aox_blank_world_cutover",
        purpose="v3_harness_loop",
        kind="tool_calling",
        model="test-model",
        attempt=1,
        estimated_input_tokens=11,
        reserved_output_tokens=13,
    )
    ledger.finalize_estimated(reservation, status="succeeded_estimated")
    provider = SQLiteRepositoryProvider(str(tmp_path / "scope.sqlite3"))
    session = Session.create(
        session_id="sess_probe_r41",
        project_id="aox-blank-world-cutover",
        title="probe",
        objective="prove exact mutation closure",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
    blob_root = tmp_path / "blobs"
    source = blob_root / "sealed" / "result.json"
    source.parent.mkdir(parents=True)
    content = b'{"status":"complete"}'
    source.write_bytes(content)
    projection: dict[str, object] = {}

    with runner._session_mutation_scope(
        provider,
        session_id=session.session_id,
        purpose="probe",
        attempt_id="r41",
        blob_root=blob_root,
        projection=projection,
        require_sealed=True,
    ):
        with runner._provider_repository_scope(provider) as repositories:
            repositories.artifacts.save(
                SessionArtifactRecord(
                    artifact_id="art_probe_result",
                    session_id=session.session_id,
                    task_id=None,
                    lane_id=None,
                    invocation_id=None,
                    run_id=None,
                    kind=ArtifactKind.RESULT,
                    storage_uri=str(source),
                    relative_path="result.json",
                    created_at="2026-07-21T00:00:00+00:00",
                    metadata={
                        "content_digest": "sha256:"
                        + hashlib.sha256(content).hexdigest()
                    },
                )
            )

    assert projection["state"] == "sealed"
    assert projection["active_writer_counts"] == {}
    assert projection["writer_counts"] == {"attempt_driver": 1}
    public_receipt = projection["receipt"]
    assert isinstance(public_receipt, dict)
    with provider.read() as unit_of_work:
        receipt = unit_of_work.repositories.quiescence_receipts.get(
            str(public_receipt["receipt_id"])
        )
        snapshot = unit_of_work.repositories.quiescence_snapshots.get(
            str(public_receipt["snapshot_id"])
        )
    assert receipt is not None
    assert snapshot is not None
    verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)
    external = snapshot.evidence["external_artifact_snapshot"]
    assert isinstance(external, dict)
    assert external["artifact_count"] == 1
    ledger_snapshot = external["live_token_ledger"]
    assert isinstance(ledger_snapshot, dict)
    assert ledger_snapshot["exists"] is True
    assert ledger_snapshot["attempt_count"] == 1
    assert ledger_snapshot["last_record_id"] == reservation.record_id
    records = ledger_snapshot["records"]
    assert isinstance(records, list)
    assert records[0]["status"] == "succeeded_estimated"
    assert str(ledger_path) not in repr(ledger_snapshot)


def test_formal_runtime_observation_binds_and_retires_exact_driver(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "scope.sqlite3"))
    session = Session.create(
        session_id="sess_formal_positive_observer",
        project_id="aox-blank-world-cutover",
        title="formal",
        objective="observe a dynamic scientific-attempt scope",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
    blob_root = tmp_path / "blobs"
    runner._open_pre_attempt_session_scope(
        provider,
        session_id=session.session_id,
        outer_attempt_id="positive-observer",
        blob_root=blob_root,
    )

    observation = runner._observe_session_runtime(
        provider,
        session_id=session.session_id,
        purpose="formal",
        attempt_authority={"attempt_id": "positive-observer"},
    )

    assert observation.state == "incomplete"
    assert observation.barrier.ready
    assert observation.barrier.observer_writer_id is not None
    with provider.read() as unit_of_work:
        scopes = unit_of_work.repositories.mutation_scopes.list_by_session(
            session.session_id
        )
        writers = unit_of_work.repositories.mutation_writers.list_all(
            scopes[0].scope_id
        )
        active_writers = unit_of_work.repositories.mutation_writers.list_active(
            scopes[0].scope_id
        )
    assert len(scopes) == 1
    assert len(writers) == 1
    assert writers[0].writer_id == observation.barrier.observer_writer_id
    assert writers[0].owner_kind.value == "attempt_driver"
    assert writers[0].owner_ref == "aox-attempt-driver:positive-observer:formal"
    assert writers[0].parent_writer_id is None
    assert writers[0].state.value == "retired"
    assert active_writers == []

    sealed = runner._close_session_mutation_scope(
        provider,
        scope_id=scopes[0].scope_id,
        blob_root=blob_root,
    )
    assert sealed["state"] == "sealed"


def test_formal_session_returns_on_first_post_closure_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        max_drains=120,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "terminal.sqlite3"))
    calls = {
        "coordinate": 0,
        "observe": 0,
        "closed": 0,
    }

    def coordinate(
        _self: live.LiveAoxAttemptRunner,
        *_args: object,
        **_kwargs: object,
    ) -> live._DrainCoordinationResult:
        calls["coordinate"] += 1
        if calls["coordinate"] > 1:
            raise AssertionError("post-closure empty drain was issued")
        return live._DrainCoordinationResult(
            workspace={"task_board": {"items": []}},
            workspace_response_binding={"response_digest": _digest("workspace")},
            approval_ids=(),
            browser_approval_receipt=None,
            fault_receipt=None,
        )

    def observe(
        _self: live.LiveAoxAttemptRunner,
        *_args: object,
        **_kwargs: object,
    ) -> object:
        calls["observe"] += 1
        return SimpleNamespace(state="completed", blocker_code=None)

    def closed(
        _self: live.LiveAoxAttemptRunner,
        *_args: object,
        **_kwargs: object,
    ) -> tuple[dict[str, object], dict[str, object]]:
        calls["closed"] += 1
        return (
            {
                "attempt": {"status": "closed"},
                "closure": {"closure_id": "closure_terminal"},
            },
            {"scope_id": "scope_attempt", "state": "sealed"},
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_coordinate_runtime_drain",
        coordinate,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_grant_formal_attempt_authority_if_ready",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_observe_session_runtime",
        observe,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_closed_formal_attempt_control",
        closed,
    )
    api = SimpleNamespace(
        get_event_records=lambda *_args, **_kwargs: (),
        get_events=lambda *_args, **_kwargs: {
            "schema_id": "event_receipt@1",
            "events": [],
        },
    )

    result, fault = runner._run_session_scoped(
        api,  # type: ignore[arg-type]
        provider,
        session_id="sess_closure_terminal",
        purpose="formal",
        message="unused",
        workflow_refs=(),
        fault_enabled=False,
        fault_blob_root=None,
        browser_gate_enabled=False,
        mutation_scope={},
        attempt_authority={
            "attempt_id": "closure-stage-terminal",
            "task_id": "task_terminal",
            "lane_id": "lane_terminal",
            "envelope_id": "attempt_authority_terminal",
        },
        post_entry_message=False,
    )

    assert fault is None
    assert result.state == "completed"
    assert result.drain_count == 1
    assert result.scientific_attempt_control is not None
    assert result.scientific_attempt_control["attempt"]["status"] == "closed"
    assert result.mutation_scope["state"] == "sealed"
    assert calls == {"coordinate": 1, "observe": 1, "closed": 1}


def _stall_test_coordination(
    *,
    workspace: dict[str, object],
    processed_signal_count: int = 0,
    replay_safe: bool = True,
    command_index: int = 1,
) -> live._DrainCoordinationResult:
    return live._DrainCoordinationResult(
        workspace=workspace,
        workspace_response_binding={
            "response_digest": _digest(f"workspace-{command_index}")
        },
        approval_ids=(),
        browser_approval_receipt=None,
        fault_receipt=None,
        command_id=f"runtime_command_{command_index:03d}",
        command_status="completed",
        command_outcome={
            "schema_version": "runtime_command_outcome@2",
            "processed_signal_count": processed_signal_count,
            "replay_safe": replay_safe,
        },
    )


def _no_wakeup_state(
    *,
    actionable_failure: dict[str, str] | None = None,
    pending_signal_ids: tuple[str, ...] = (),
    claimed_signal_ids: tuple[str, ...] = (),
    pending_approval_ids: tuple[str, ...] = (),
    active_invocation_ids: tuple[str, ...] = (),
    active_continuation_ids: tuple[str, ...] = (),
    working_agent_ids: tuple[str, ...] = (),
) -> live._RuntimeWakeState:
    return live._RuntimeWakeState(
        ready_task_ids=("aox_final_source_linked_report",),
        pending_signal_ids=pending_signal_ids,
        claimed_signal_ids=claimed_signal_ids,
        pending_approval_ids=pending_approval_ids,
        active_invocation_ids=active_invocation_ids,
        active_continuation_ids=active_continuation_ids,
        working_agent_ids=working_agent_ids,
        actionable_failure=actionable_failure,
    )


def test_runtime_progress_fingerprint_ignores_observation_noise_only() -> None:
    first = {
        "session": {
            "session_id": "sess_stable",
            "status": "active",
            "updated_at": "first",
        },
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_report",
                        "status": "todo",
                        "updated_at": "first",
                    }
                }
            ]
        },
        "conversation": [{"message_id": "message_1"}],
        "agent_traces": {"harness": [{"step_id": "step_1"}]},
        "activity_feed": [{"event_id": "event_1", "cursor": 10}],
    }
    noisy_second = {
        **first,
        "session": {
            "session_id": "sess_stable",
            "status": "active",
            "updated_at": "second",
        },
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_report",
                        "status": "todo",
                        "updated_at": "second",
                    }
                }
            ]
        },
        "conversation": [{"message_id": "message_2"}],
        "agent_traces": {"harness": [{"step_id": "step_2"}]},
        "activity_feed": [{"event_id": "event_2", "cursor": 11}],
    }
    progressed = {
        **noisy_second,
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_report",
                        "status": "in_progress",
                        "updated_at": "third",
                    }
                }
            ]
        },
    }

    first_digest = live._runtime_progress_fingerprint(first)

    assert live._runtime_progress_fingerprint(noisy_second) == first_digest
    assert live._runtime_progress_fingerprint(progressed) != first_digest


@pytest.mark.parametrize(
    ("actionable_failure", "observation_blocker", "expected_code"),
    (
        (
            {
                "failure_id": "failure_report_delegate",
                "error_code": "workflow_ref_not_authorized",
                "recoverability": "agent_can_replan",
                "task_id": "aox_final_source_linked_report",
            },
            None,
            "formal_agent_recovery_unresolved",
        ),
        (None, None, "formal_runtime_stalled_no_wakeup"),
        (
            None,
            "scientific_attempt_open",
            "scientific_attempt_open_no_wakeup",
        ),
    ),
)
def test_formal_driver_fails_after_two_confirmed_no_wakeup_drains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    actionable_failure: dict[str, str] | None,
    observation_blocker: str | None,
    expected_code: str,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        max_drains=20,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "stall.sqlite3"))
    workspace = {
        "session": {"session_id": "sess_stall", "status": "active"},
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "aox_final_source_linked_report",
                        "status": "todo",
                        "assigned_ref": None,
                        "updated_at": "volatile",
                    }
                }
            ]
        },
    }
    calls = 0

    def coordinate(*_args: object, **_kwargs: object) -> live._DrainCoordinationResult:
        nonlocal calls
        calls += 1
        return _stall_test_coordination(
            workspace=workspace,
            command_index=calls,
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_coordinate_runtime_drain",
        coordinate,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_observe_session_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            state="incomplete",
            blocker_code=observation_blocker,
        ),
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_wake_state",
        lambda *_args, **_kwargs: _no_wakeup_state(
            actionable_failure=actionable_failure
        ),
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_has_inflight_mutation_writers",
        lambda *_args, **_kwargs: False,
    )
    api = SimpleNamespace(
        get_event_records=lambda *_args, **_kwargs: (),
        get_events=lambda *_args, **_kwargs: {
            "schema_id": "event_receipt@1",
            "events": [],
        },
    )

    with pytest.raises(live.LiveProductPathError) as captured:
        runner._run_session_scoped(
            api,  # type: ignore[arg-type]
            provider,
            session_id="sess_stall",
            purpose="formal",
            message="unused",
            workflow_refs=(),
            fault_enabled=False,
            fault_blob_root=None,
            browser_gate_enabled=False,
            mutation_scope={},
            post_entry_message=False,
        )

    assert captured.value.code == expected_code
    assert calls == 2
    assert captured.value.details["confirmation_count"] == 2
    assert captured.value.details["processed_signal_count"] == 0
    assert captured.value.details["replay_safe"] is True


@pytest.mark.parametrize(
    ("wake_state", "inflight_writer"),
    (
        (_no_wakeup_state(pending_signal_ids=("signal_pending",)), False),
        (_no_wakeup_state(claimed_signal_ids=("signal_claimed",)), False),
        (_no_wakeup_state(pending_approval_ids=("approval_pending",)), False),
        (_no_wakeup_state(active_invocation_ids=("invocation_active",)), False),
        (
            _no_wakeup_state(active_continuation_ids=("continuation_active",)),
            False,
        ),
        (_no_wakeup_state(working_agent_ids=("agent:working",)), False),
        (_no_wakeup_state(), True),
    ),
)
def test_formal_driver_does_not_stall_with_eligible_wakeup_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wake_state: live._RuntimeWakeState,
    inflight_writer: bool,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        max_drains=2,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "wakeup.sqlite3"))
    calls = 0

    def coordinate(*_args: object, **_kwargs: object) -> live._DrainCoordinationResult:
        nonlocal calls
        calls += 1
        return _stall_test_coordination(
            workspace={"task_board": {"items": []}},
            command_index=calls,
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_coordinate_runtime_drain",
        coordinate,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_observe_session_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            state="incomplete",
            blocker_code=None,
        ),
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_wake_state",
        lambda *_args, **_kwargs: wake_state,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_has_inflight_mutation_writers",
        lambda *_args, **_kwargs: inflight_writer,
    )
    api = SimpleNamespace(
        get_event_records=lambda *_args, **_kwargs: (),
        get_events=lambda *_args, **_kwargs: {
            "schema_id": "event_receipt@1",
            "events": [],
        },
    )

    result, _fault = runner._run_session_scoped(
        api,  # type: ignore[arg-type]
        provider,
        session_id="sess_wakeup",
        purpose="formal",
        message="unused",
        workflow_refs=(),
        fault_enabled=False,
        fault_blob_root=None,
        browser_gate_enabled=False,
        mutation_scope={},
        post_entry_message=False,
    )

    assert result.state == "incomplete"
    assert result.blocker_code == "formal_runtime_drain_exhausted"
    assert calls == 2


def test_formal_driver_requires_consecutive_unchanged_empty_drains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        max_drains=2,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "transient.sqlite3"))
    calls = 0

    def coordinate(*_args: object, **_kwargs: object) -> live._DrainCoordinationResult:
        nonlocal calls
        calls += 1
        return _stall_test_coordination(
            workspace={
                "task_board": {"items": [{"task": {"task_id": f"task_state_{calls}"}}]}
            },
            processed_signal_count=0 if calls == 1 else 1,
            replay_safe=calls == 1,
            command_index=calls,
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_coordinate_runtime_drain",
        coordinate,
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_observe_session_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            state="incomplete",
            blocker_code=None,
        ),
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_wake_state",
        lambda *_args, **_kwargs: _no_wakeup_state(),
    )
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_has_inflight_mutation_writers",
        lambda *_args, **_kwargs: False,
    )
    api = SimpleNamespace(
        get_event_records=lambda *_args, **_kwargs: (),
        get_events=lambda *_args, **_kwargs: {
            "schema_id": "event_receipt@1",
            "events": [],
        },
    )

    result, _fault = runner._run_session_scoped(
        api,  # type: ignore[arg-type]
        provider,
        session_id="sess_transient",
        purpose="formal",
        message="unused",
        workflow_refs=(),
        fault_enabled=False,
        fault_blob_root=None,
        browser_gate_enabled=False,
        mutation_scope={},
        post_entry_message=False,
    )

    assert result.state == "incomplete"
    assert result.blocker_code == "formal_runtime_drain_exhausted"
    assert calls == 2


def test_formal_writer_settlement_keeps_other_writers_visible_on_real_sqlite(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "scope.sqlite3"))
    session = Session.create(
        session_id="sess_formal_writer_settlement",
        project_id="aox-blank-world-cutover",
        title="formal",
        objective="observe root and child writers during settlement",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
    blob_root = tmp_path / "blobs"
    runner._open_pre_attempt_session_scope(
        provider,
        session_id=session.session_id,
        outer_attempt_id="positive-writer-settlement",
        blob_root=blob_root,
    )
    with runner._provider_repository_scope(provider) as repositories:
        scope = repositories.mutation_scopes.list_by_session(session.session_id)[0]
        service = MutationScopeService(repositories)
        root = service.register_writer(
            scope_id=scope.scope_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="runtime-command:terminal-with-child",
            trusted_root=True,
        )
        child = service.register_writer(
            scope_id=scope.scope_id,
            owner_kind=MutationWriterKind.SANDBOX_PROCESS,
            owner_ref="sandbox:attached-process",
            parent_writer_id=root.writer_id,
            process_epoch=7,
        )

    assert runner._has_inflight_mutation_writers(
        provider,
        session_id=session.session_id,
        purpose="formal",
        attempt_authority={"attempt_id": "positive-writer-settlement"},
    )
    with provider.read() as unit_of_work:
        writers = unit_of_work.repositories.mutation_writers.list_all(scope.scope_id)
        active_writers = unit_of_work.repositories.mutation_writers.list_active(
            scope.scope_id
        )
    observers = [
        writer
        for writer in writers
        if writer.owner_ref == "aox-attempt-driver:positive-writer-settlement:formal"
    ]
    assert len(observers) == 1
    assert observers[0].state.value == "retired"
    assert {writer.writer_id for writer in active_writers} == {
        root.writer_id,
        child.writer_id,
    }

    with runner._provider_repository_scope(provider) as repositories:
        service = MutationScopeService(repositories)
        service.finish_writer_turn(
            root.writer_id,
            terminal_proof={"kind": "runtime_command_returned"},
        )
        service.finish_writer_turn(
            child.writer_id,
            terminal_proof={"kind": "process_exited"},
            expected_process_epoch=7,
        )
    assert not runner._has_inflight_mutation_writers(
        provider,
        session_id=session.session_id,
        purpose="formal",
        attempt_authority={"attempt_id": "positive-writer-settlement"},
    )
    with provider.read() as unit_of_work:
        writers = unit_of_work.repositories.mutation_writers.list_all(scope.scope_id)
        active_writers = unit_of_work.repositories.mutation_writers.list_active(
            scope.scope_id
        )
    observers = [
        writer
        for writer in writers
        if writer.owner_ref == "aox-attempt-driver:positive-writer-settlement:formal"
    ]
    assert len(observers) == 2
    assert all(writer.state.value == "retired" for writer in observers)
    assert active_writers == []

    sealed = runner._close_session_mutation_scope(
        provider,
        scope_id=scope.scope_id,
        blob_root=blob_root,
    )
    assert sealed["state"] == "sealed"


def test_live_fault_scope_fails_without_receipt_when_artifact_bytes_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "scope.sqlite3"))
    session = Session.create(
        session_id="sess_formal_r41",
        project_id="aox-blank-world-cutover",
        title="formal",
        objective="prove fail-closed mutation closure",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
    blob_root = tmp_path / "blobs"
    source = blob_root / "sealed" / "result.json"
    source.parent.mkdir(parents=True)
    original = b'{"status":"complete"}'
    source.write_bytes(original)
    projection: dict[str, object] = {}

    with runner._session_mutation_scope(
        provider,
        session_id=session.session_id,
        purpose="formal",
        attempt_id="r41",
        blob_root=blob_root,
        projection=projection,
        require_sealed=False,
    ):
        with runner._provider_repository_scope(provider) as repositories:
            repositories.artifacts.save(
                SessionArtifactRecord(
                    artifact_id="art_formal_result",
                    session_id=session.session_id,
                    task_id=None,
                    lane_id=None,
                    invocation_id=None,
                    run_id=None,
                    kind=ArtifactKind.RESULT,
                    storage_uri=str(source),
                    relative_path="result.json",
                    created_at="2026-07-21T00:00:00+00:00",
                    metadata={
                        "content_digest": "sha256:"
                        + hashlib.sha256(original).hexdigest()
                    },
                )
            )
        source.write_bytes(b'{"status":"corrupted"}')

    assert projection["state"] == "failed"
    assert projection["blocker_code"] == "artifact_snapshot_digest_mismatch"
    assert projection["receipt"] is None
    assert projection["active_writer_counts"] == {}
    with provider.read() as unit_of_work:
        scope = unit_of_work.repositories.mutation_scopes.get(
            str(projection["scope_id"])
        )
        receipt = unit_of_work.repositories.quiescence_receipts.get_by_scope(
            scope_id=str(projection["scope_id"]),
            seal_generation=int(projection["generation"]),
        )
    assert scope is not None
    assert scope.state.value == "failed"
    assert receipt is None


def test_known_positive_probe_prompt_exposes_fixed_runner_output_contracts(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    prompt = runner._probe_prompt(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=safe_micu_ledger_snapshot(ledger_path),
            attempt_number=1,
        )
    )

    assert "campaign already enforces provider cache bypass" in prompt
    assert "do not invent unsupported cache flags" in prompt
    assert "result_summary.transcript_manifest.files" in prompt
    assert "/provider_parsed/proteins.fasta" in prompt
    assert "/provider_parsed/sequences.fasta" in prompt
    assert "adapter_result_envelope ID lists" in prompt
    assert "artifacts.provider_file_ref" in prompt
    assert "do not call artifacts.registered_artifact_ref" in prompt
    assert "artifacts.fetched_output_ref" in prompt
    assert "Both helpers already return the terminal canonical" in prompt
    assert "never chain selectors" in prompt
    assert "docs.read('artifacts')" in prompt
    assert "docs.read('bio')" in prompt
    assert "docs.read('bio-tools')" in prompt
    assert "docs.read('sdk-overview')" in prompt
    assert "Every otherwise-valid sandbox.exec that reaches source preflight" in prompt
    assert "including Python -c or package/signature inspection" in prompt
    assert "never spend the probe's sole run as a read-only" in prompt
    assert "put it in the explicitly authored operation-bearing source" in prompt
    assert "one operation-bearing sandbox.exec run" in prompt
    assert "Cross-run effect adoption is not available" in prompt
    assert "Persist each completed operation response under /workspace/work" in prompt
    assert "output_dir='/workspace/output/provider/ncbi'" in prompt
    assert "output_dir='/workspace/output/provider/uniprot'" in prompt
    assert "Do not derive either value from an OUT constant" in prompt
    assert "never interpolate a sandbox root constant" in prompt
    assert "raw source snapshot must remain eligible" in prompt.casefold()
    assert "do not start another controlled operation in this attempt" in prompt
    assert "bio_tools/mafft/alignment.fasta" in prompt
    assert "bio_tools/hmmbuild/model.hmm" in prompt
    assert "bio_tools/cdhit/clustered.fasta" in prompt
    assert "bio_tools/cdhit/clusters.csv" in prompt
    assert "bio_tools/hmmalign/aligned.fasta" in prompt
    assert (
        "hmmbuild bio_tools/hmmbuild/model.hmm as kind='result', format='hmm'" in prompt
    )
    assert "Never declare kind='model'" in prompt
    assert "all four run handles, including the terminal HMMalign" in prompt
    assert "unique fetch_refs entry whose declared_output_path" in prompt
    assert "never by registered_artifact_ids or artifacts list order" in prompt


def test_formal_prompt_exposes_host_owned_cache_bypass_contract(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    authority = _attempt_authority(roots)

    prompt = runner._formal_prompt(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=safe_micu_ledger_snapshot(ledger_path),
            attempt_number=1,
            attempt_authority=authority,
        )
    )

    assert "campaign already enforces evidence-bearing provider cache bypass" in prompt
    assert "do not pass or invent unsupported cache flags" in prompt
    legacy_execution_task_id = (
        "aox_execution_cutover_"
        + roots.hpc_workspace_label.removeprefix("aox-cutover-")
    )
    execution_task_id = str(authority["task_id"])
    assert "canonical task ids aox_research_pubmed_evidence" in prompt
    assert execution_task_id in prompt
    assert legacy_execution_task_id not in prompt
    assert str(authority["lane_id"]) in prompt
    assert "call attempt.create with exactly these arguments" in prompt
    assert "aox_final_source_linked_report" in prompt
    assert "reconcile the durable task board and inbox" in prompt
    assert "create only a missing canonical member" in prompt
    assert "advance any existing member" in prompt
    assert "never create another, suffixed, or replacement task id" in prompt
    assert "runtime rejects a noncanonical task id without effect" in prompt
    assert (
        "Scientific closure is owned by the exact scientific attempt task "
        "assignee" in prompt
    )
    assert (
        "Create any missing research and execution tasks before the missing "
        "reporting task" in prompt
    )
    assert "both canonical upstream tasks in blocked_by" in prompt
    assert "do not attempt reporter delegation while either dependency" in prompt
    assert "inspect the canonical task graph" in prompt
    assert "Delegate the reporter only after both dependencies complete" in prompt
    assert (
        "Assistant text alone does not close the attempt or make an incomplete "
        "state acceptance-eligible" in prompt
    )
    assert (
        "scientific.attempt.close never persists a companion assistant response"
        in prompt
    )
    assert "complete final user-facing answer as response text" not in prompt
    assert (
        f"workflow_refs=[{_identity()['workflow_ref']!r}] only to the executor"
        in prompt
    )
    assert "researcher and reporter must omit workflow_refs" in prompt
    assert "openzyme_pipeline.aox_reference.select_hmm_reference_set" in prompt
    assert "openzyme_pipeline.aox_reference.select_scoring_reference" in prompt
    assert "openzyme_pipeline.aox_reference.assemble_scoring_input" in prompt
    assert "openzyme_pipeline.aox_hmmer.parse_and_filter_csv" in prompt
    assert (
        "openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions" in prompt
    )
    assert "openzyme_pipeline.aox_motif.score_aligned_fasta" in prompt
    assert "openzyme_pipeline.aox_similarity.build_similarity_graph" in prompt
    assert "/provider_parsed/proteins.fasta" in prompt
    assert "/provider_parsed/parsed_hits.csv" in prompt
    assert "/provider_parsed/sequences.fasta" in prompt
    assert "/provider_parsed/metadata.json" in prompt
    assert "bio_tools/mafft/alignment.fasta" in prompt
    assert "bio_tools/hmmbuild/model.hmm" in prompt
    assert "bio_tools/cdhit/clustered.fasta" in prompt
    assert "bio_tools/cdhit/clusters.csv" in prompt
    assert "bio_tools/hmmalign/aligned.fasta" in prompt
    assert "bio_tools/hmmbuild/model.hmm as result/hmm" in prompt
    assert "mismatched kind/format values fail before runner dispatch" in prompt
    assert "never declare kind='model'" in prompt
    assert "pass the exact dict returned by ws.stage_artifact(...) unchanged" in prompt
    assert "never reconstruct it, rename its keys" in prompt
    assert "unique fetch_refs entry" in prompt
    assert "artifacts.provider_file_ref" in prompt
    assert "artifacts.registered_artifact_ref" in prompt
    assert "artifacts.fetched_output_ref" in prompt
    assert "only the direct response returned by artifacts.register" in prompt
    assert "never chain selectors, synthesize a registration envelope" in prompt
    assert "docs.read('bio')" in prompt
    assert "docs.read('bio-tools')" in prompt
    assert "docs.read('sdk-overview')" in prompt
    assert "selected pinned AOX/HMM SOP is already present" in prompt
    assert "do not reread it" in prompt
    assert "/workspace/input is a Host-managed read-only mount" in prompt
    assert "never mkdir, write, copy, or pre-create a materialization target" in prompt
    assert (
        "artifacts.materialize itself creates the target and missing parents" in prompt
    )
    assert "use /workspace/work for mutable scratch" in prompt
    assert "Every otherwise-valid sandbox.exec invocation" in prompt
    assert "that reaches source preflight, including Python -c" in prompt
    assert "never use it as a read-only environment-inspection shortcut" in prompt
    assert "first author an explicit inspection source under /workspace/src" in prompt
    assert "known terminal local failure is recoverable" in prompt
    assert "every normalized final FASTA with kind='sequence', format='fasta'" in prompt
    assert "AOX_ref.hmm with kind='result', format='hmm'" in prompt
    assert "every normalized final CSV with kind='result', format='csv'" in prompt
    assert (
        "both normalized final JSON files with kind='result', format='json'" in prompt
    )
    assert "Artifact kind 'model' is invalid" in prompt
    assert "model, alignment, table, or graph belong in format or metadata" in prompt
    assert "zero-record FASTA keeps kind='sequence', format='fasta'" in prompt
    assert "Intermediate paths may fail and be retried" in prompt
    assert "observe each occurrence signature and compatible_roles" in prompt
    assert "The agent, never the Harness, chooses the operation and role" in prompt
    assert "adopted disposition directly" in prompt
    assert "scientific.operation.adopt" in prompt
    assert "scientific.effect.adopt" not in prompt
    assert "scientific.artifact.materialize" in prompt
    assert "Unknown external effect, dispatch-in-doubt" in prompt
    assert "known closed no-effect failure does not poison the attempt" in prompt
    assert (
        "closure_request_ready means the canonical evaluator proves the sealed "
        "current selection"
    ) in prompt
    assert "closure_finalization_ready and the legacy closure_ready field" in prompt
    assert (
        "selection_active_writers therefore does not require the assignee to wait"
        in prompt
    )
    assert "task.finish(status='blocked')" in prompt
    assert "sealed state alone is not readiness" in prompt
    assert "post-seal universe, authority, workflow" in prompt
    assert "must request scientific.attempt.close" in prompt
    assert "ordinary closure notification wakes that same executor" in prompt
    assert (
        "Do not call task.finish(status='completed') before immutable closure" in prompt
    )
    assert "actor rejection is the intended no-effect handoff" not in prompt
    assert "scientific.attempt.close" in prompt
    assert "Persist each completed controlled-operation response" in prompt
    assert "Publish each canonical final deliverable path only once" in prompt
    assert "whose source may reach the real EBI HMMER wait" in prompt
    assert "must use timeout_seconds=3600" in prompt
    assert "Short preflight inspection or post-failure diagnostic commands" in prompt
    assert "Do not shorten the HMM-capable containment timeout" in prompt
    assert "exact fetched hmmbuild artifact id and content digest" in prompt
    assert "validation_profile='fasta_zero_records@1'" in prompt
    assert (
        "join_score_filtered_accessions(score_filtered_csv, uniprot_fasta, "
        "uniprot_metadata_json, ...)" in prompt
    )
    assert (
        "build_similarity_graph(candidate_fasta, cdhit_membership_csv, ...)" in prompt
    )
    assert "exact full pre-CD-HIT AOX_candidates.fasta" in prompt
    assert "full one-row-per-member AOX_candidates_cdhit85.clusters.csv" in prompt
    assert "AOX_candidates_cdhit85.fasta is never a graph input" in prompt
    assert (
        "Every primary payload accessor named by that table returns Python str"
        in prompt
    )
    assert "metadata() returns a dict" in prompt
    assert "Encode payload text exactly once with UTF-8" in prompt
    assert "never pass str to a bytes-only writer" in prompt
    assert "supply every bound expected_*_digest" in prompt
    assert "never reimplement or approximate" in prompt


def test_formal_delegation_workflow_binding_is_exact_and_executor_scoped(
    tmp_path: Path,
) -> None:
    workflow = next(
        manifest
        for manifest in live.default_workflow_registry().list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    )
    identity = {**_identity(), "workflow_ref": workflow.selection_ref}
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites={
            **_allowed_prerequisites(),
            "workflow_ref": workflow.selection_ref,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=identity,
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )
    task_receipts = [
        {
            "task_id": f"task_{role}",
            "role": role,
            "status": "completed",
            "business_exit": "agent_explicit",
            "assigned_ref": f"agent_{role}",
        }
        for role in ("researcher", "executor", "reporter")
    ]
    documents = tuple(
        SimpleNamespace(
            document_id=f"doc_{role}",
            document_kind="delegation_request",
            payload={
                "task_id": f"task_{role}",
                "instructions": f"Complete the canonical {role} task.",
                "role": role,
                "agent_id": f"agent_{role}",
                "nickname": role,
                "display_name": role.capitalize(),
                "handle": f"@{role}",
                "workflow_refs": [workflow.selection_ref] if role == "executor" else [],
                "workflow_manifests": [workflow.to_dict()]
                if role == "executor"
                else [],
            },
        )
        for role in ("researcher", "executor", "reporter")
    )

    bound = live._bind_delegation_workflow_receipts(
        context,
        task_receipts=task_receipts,
        documents=documents,
    )

    by_role = {str(item["role"]): item for item in bound}
    assert by_role["executor"]["workflow_refs"] == [workflow.selection_ref]
    assert by_role["executor"]["workflow_manifests"] == [workflow.to_dict()]
    assert by_role["researcher"]["workflow_refs"] == []
    assert by_role["reporter"]["workflow_refs"] == []
    assert all(item["delegation_request_ref"] for item in bound)
    assert all(item["delegation_request_digest"] for item in bound)
    assert all(
        item["delegation_request"]["document_id"] == item["delegation_request_ref"]
        and item["delegation_request"]["agent_id"] == item["assigned_ref"]
        and live.canonical_digest(item["delegation_request"])
        == item["delegation_request_digest"]
        for item in bound
    )

    drifted = list(documents)
    drifted[0] = SimpleNamespace(
        document_id="doc_researcher",
        document_kind="delegation_request",
        payload={
            **dict(documents[0].payload),
            "workflow_refs": [workflow.selection_ref],
            "workflow_manifests": [workflow.to_dict()],
        },
    )
    with pytest.raises(live.LiveProductPathError) as error:
        live._bind_delegation_workflow_receipts(
            context,
            task_receipts=task_receipts,
            documents=tuple(drifted),
        )
    assert error.value.code == "formal_delegation_workflow_binding_invalid"


def test_catalog_source_snapshot_directory_is_sealed_as_self_verifying_envelope(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    files = {
        "openzyme_pipeline/__init__.py": b"from .worker import run\n",
        "openzyme_pipeline/worker.py": b"def run():\n    return 1\n",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    tree_digest = live.canonical_digest(
        [
            {
                "relative_path": relative_path,
                "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relative_path, content in sorted(files.items())
        ]
    )
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.CODE,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": tree_digest,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
        attempt_authority=_attempt_authority(roots),
    )

    sealed = live._artifact_bytes(context, artifact)
    envelope = cutover_evidence.verify_sealed_source_tree_envelope(
        sealed,
        expected_source_tree_digest=tree_digest,
    )

    assert envelope["schema_id"] == "openzyme_sealed_source_tree@1"
    assert [item["relative_path"] for item in envelope["files"]] == sorted(files)


def test_probe_provider_output_literals_are_self_verifying_source(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "probe-snapshot"
    source_root.mkdir(parents=True)
    content = b"""\
from openzyme_pipeline import artifacts, bio

WORK = "/workspace/work"
OUT = "/workspace/output"

ncbi = bio.ncbi_fetch_proteins(
    accessions=["NP_000509.1", "NP_000549.1"],
    output_dir="/workspace/output/provider/ncbi",
)
ncbi_ref = artifacts.provider_file_ref(
    ncbi,
    relative_path_suffix="/provider_parsed/proteins.fasta",
)
uniprot = bio.uniprot_fetch(
    accessions=["P68871", "P69905"],
    output_dir="/workspace/output/provider/uniprot",
)
uniprot_ref = artifacts.provider_file_ref(
    uniprot,
    relative_path_suffix="/provider_parsed/sequences.fasta",
)
expected_outputs = [
    "bio_tools/mafft/alignment.fasta",
    "bio_tools/hmmbuild/model.hmm",
    "bio_tools/cdhit/clustered.fasta",
    "bio_tools/cdhit/clusters.csv",
    "bio_tools/hmmalign/aligned.fasta",
]
"""
    source_path = source_root / "aox_probe.py"
    source_path.write_bytes(content)
    tree_digest = live.canonical_digest(
        [
            {
                "relative_path": "aox_probe.py",
                "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        ]
    )
    artifact = SimpleNamespace(
        artifact_id="art_probe_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.CODE,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": tree_digest,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )

    sealed = live._artifact_bytes(context, artifact)
    envelope = cutover_evidence.verify_sealed_source_tree_envelope(
        sealed,
        expected_source_tree_digest=tree_digest,
    )

    assert envelope["schema_id"] == "openzyme_sealed_source_tree@1"
    assert envelope["files"][0]["relative_path"] == "aox_probe.py"


def test_catalog_source_snapshot_directory_rejects_metadata_digest_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    source_root.mkdir(parents=True)
    (source_root / "main.py").write_text("value = 1\n", encoding="utf-8")
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.CODE,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": _digest("wrong-tree"),
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._artifact_bytes(context, artifact)

    assert error.value.code == "sealed_source_tree_digest_mismatch"


def test_catalog_source_snapshot_directory_requires_code_kind(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source_root = roots.blob_root / "sealed" / "source" / "snapshot"
    source_root.mkdir(parents=True)
    content = b"value = 1\n"
    (source_root / "main.py").write_bytes(content)
    artifact = SimpleNamespace(
        artifact_id="art_source_snapshot",
        storage_uri=str(source_root),
        kind=ArtifactKind.RESULT,
        metadata={
            "semantic_type": "pipeline_source_snapshot",
            "format": "source_tree",
            "source_tree_digest": live.canonical_digest(
                [
                    {
                        "relative_path": "main.py",
                        "content_digest": "sha256:"
                        + hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                ]
            ),
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._artifact_bytes(context, artifact)

    assert error.value.code == "catalog_artifact_blob_invalid"


def test_catalog_copy_seals_typed_zero_fasta_registration_receipt(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source = roots.blob_root / "sealed" / "empty-target.fasta"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"")
    reason = "no_hmmer_hits"
    derivation = "aox_upstream_empty_materialization@1"
    validation = {
        "status": "passed",
        "format": "fasta",
        "required_columns": [],
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
    }
    artifact = SessionArtifactRecord(
        artifact_id="art_empty_target",
        session_id="session_test",
        task_id="task_test",
        lane_id="lane_test",
        invocation_id=None,
        run_id="run_test",
        kind=ArtifactKind.SEQUENCE,
        storage_uri=str(source),
        relative_path="aox_hmm/target.fasta",
        created_at="2026-07-18T00:00:00+00:00",
        metadata={
            "content_digest": "sha256:" + hashlib.sha256(b"").hexdigest(),
            "format": "fasta",
            "validation_profile": "fasta_zero_records@1",
            "empty_result_reason": reason,
            "derivation_contract_id": derivation,
            "validation": validation,
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    cache: dict[str, live.CatalogArtifactCopy] = {}
    copy = live._copy_catalog_artifact(
        context,
        artifact,
        scope="formal",
        origin="operation",
        provenance={"operation_id": "op_empty"},
        cache=cache,
    )

    assert copy.content == b""
    assert copy.record["registration_validation"] == {
        **copy.record["registration_validation"],
        "schema_id": "openzyme_typed_empty_artifact_validation@1",
        "kind": "sequence",
        "format": "fasta",
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": reason,
        "derivation_contract_id": derivation,
        "catalog_validation_digest": live.canonical_digest(validation),
    }
    assert copy.record["deliverable_path"] == "aox_hmm/target.fasta"
    assert copy.record["deliverable_artifact_contract_id"] == (
        cutover_evidence.AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
    )
    assert copy.record["kind"] == "sequence"
    assert copy.record["format"] == "fasta"

    cache_hit = live._copy_catalog_artifact(
        context,
        artifact,
        scope="formal",
        origin="operation",
        provenance={
            "operation_id": "op_empty",
            "deliverable_path": "aox_hmm/target.fasta",
        },
        cache=cache,
    )

    assert cache_hit is copy
    assert cache_hit.record["provenance"]["deliverable_path"] == (
        "aox_hmm/target.fasta"
    )
    assert (
        cache_hit.record["provenance"]["deliverable_artifact_contract_id"]
        == cutover_evidence.AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
    )


@pytest.mark.parametrize("mismatch", ("kind", "format"))
def test_catalog_copy_rejects_fixed_deliverable_kind_or_format_drift(
    tmp_path: Path,
    mismatch: str,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source = roots.blob_root / "sealed" / "AOX_ref.hmm"
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"HMMER3/f\nNAME  AOX\n//\n"
    source.write_bytes(content)
    artifact = SessionArtifactRecord(
        artifact_id="art_hmm",
        session_id="session_test",
        task_id="task_test",
        lane_id="lane_test",
        invocation_id=None,
        run_id="run_test",
        kind=ArtifactKind.OTHER if mismatch == "kind" else ArtifactKind.RESULT,
        storage_uri=str(source),
        relative_path="aox_hmm/AOX_ref.hmm",
        created_at="2026-07-18T00:00:00+00:00",
        metadata={
            "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "format": "json" if mismatch == "format" else "hmm",
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="operation",
            provenance={
                "operation_id": "op_hmmbuild",
                "deliverable_path": "aox_hmm/AOX_ref.hmm",
            },
            cache={},
        )

    assert error.value.code == "final_deliverable_artifact_contract_mismatch"


def test_catalog_copy_rejects_declared_deliverable_contract_drift(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    source = roots.blob_root / "sealed" / "target.fasta"
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b">candidate\nMSEQ\n"
    source.write_bytes(content)
    artifact = SessionArtifactRecord(
        artifact_id="art_target",
        session_id="session_test",
        task_id="task_test",
        lane_id="lane_test",
        invocation_id=None,
        run_id="run_test",
        kind=ArtifactKind.SEQUENCE,
        storage_uri=str(source),
        relative_path="aox_hmm/target.fasta",
        created_at="2026-07-18T00:00:00+00:00",
        metadata={
            "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "format": "fasta",
        },
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="operation",
            provenance={
                "operation_id": "op_target",
                "deliverable_path": "aox_hmm/target.fasta",
                "deliverable_artifact_contract_id": (
                    "aox_fixed_deliverable_artifact_contract@2"
                ),
            },
            cache={},
        )

    assert error.value.code == "final_deliverable_artifact_contract_mismatch"


def test_fault_target_copy_seals_fixed_deliverable_contract(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="fault",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    original = b">AAB57849.1\nMSEQ\n"
    offset = 15
    corrupted = bytearray(original)
    corrupted[offset] ^= 1
    source = roots.blob_root / "sealed" / "AOX_ref21.fasta"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(bytes(corrupted))
    before_digest = "sha256:" + hashlib.sha256(original).hexdigest()
    after_digest = "sha256:" + hashlib.sha256(bytes(corrupted)).hexdigest()
    artifact = SessionArtifactRecord(
        artifact_id="art_fault_target",
        session_id="session_test",
        task_id="task_test",
        lane_id="lane_test",
        invocation_id=None,
        run_id="run_test",
        kind=ArtifactKind.SEQUENCE,
        storage_uri=str(source),
        relative_path="aox_hmm/AOX_ref21.fasta",
        created_at="2026-07-18T00:00:00+00:00",
        metadata={"content_digest": before_digest, "format": "fasta"},
    )
    fault = replace(
        _minimal_fault_injection_receipt(),
        target_artifact_id=artifact.artifact_id,
        byte_offset=offset,
        before_digest=before_digest,
        after_digest=after_digest,
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )

    copied = live._copy_fault_target(
        context,
        artifact=artifact,
        fault=fault,
        derivation_operation_id="op_reference_selection",
    )

    assert copied.record["deliverable_path"] == "aox_hmm/AOX_ref21.fasta"
    assert copied.record["kind"] == "sequence"
    assert copied.record["format"] == "fasta"
    assert copied.record["deliverable_artifact_contract_id"] == (
        cutover_evidence.AOX_FIXED_DELIVERABLE_ARTIFACT_CONTRACT_ID
    )
    assert copied.record["provenance"]["catalog_relative_path"] == (
        "aox_hmm/AOX_ref21.fasta"
    )


def test_public_driver_route_surface_rejects_debug_shortcut() -> None:
    class Response:
        status_code = 200
        content = b'{"status":"ready"}'

        @staticmethod
        def json() -> dict[str, str]:
            return {"status": "ready"}

    class Client:
        @staticmethod
        def get(route: str) -> Response:
            assert route == "/v3/runtime/health"
            return Response()

    client = live._PublicHostClient(Client())
    assert client.get_json("/v3/runtime/health") == {"status": "ready"}
    with pytest.raises(live.LiveProductPathError) as error:
        client.get_json("/debug/v3-runtime")

    assert error.value.code == "noncanonical_api_route_forbidden"
    assert [receipt.route for receipt in client.receipts] == ["/v3/runtime/health"]


@pytest.mark.parametrize(
    "report_status",
    (SessionReportStatus.READY, SessionReportStatus.PUBLISHED),
)
def test_live_report_collector_binds_successful_report_draft_document_and_events(
    tmp_path: Path,
    report_status: SessionReportStatus,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(tmp_path / "ledger.sqlite3"),
        attempt_number=1,
    )
    report = SessionReportRecord(
        report_id="report_aox",
        session_id="sess_aox",
        task_id="task_report",
        lane_id="lane_report",
        invocation_id=None,
        run_id=None,
        artifact_id=None,
        status=report_status,
        title="AOX report",
        summary="summary",
        stage_summary="stage",
        created_at="2026-07-17T00:00:02+00:00",
        updated_at="2026-07-17T00:00:03+00:00",
    )
    draft = SessionReportDraftRecord(
        draft_id="draft_aox",
        session_id="sess_aox",
        task_id="task_report",
        owner_agent_id="agent_reporter",
        status=SessionReportDraftStatus.PUBLISHED,
        title="AOX report",
        summary="summary",
        content_ref="doc_report_aox",
        published_report_id="report_aox",
        created_at="2026-07-17T00:00:01+00:00",
        updated_at="2026-07-17T00:00:03+00:00",
    )
    markdown = (
        "# AOX report\n\nPMID 12345678 source_pubmed_aox "
        "uses sealed artifact art_science.\n"
    )
    document = EngineDocumentRecord(
        document_id="doc_report_aox",
        session_id="sess_aox",
        invocation_id=None,
        document_kind="report_draft_content",
        payload={"markdown": markdown},
        created_at="2026-07-17T00:00:01+00:00",
        updated_at="2026-07-17T00:00:01+00:00",
    )
    invoked_payload = {
        "call_id": "call_publish",
        "tool_name": "report.publish",
        "task_id": "task_report",
        "lane_id": "lane_report",
        "role": "reporter",
    }
    completed_payload = {
        **invoked_payload,
        "ok": True,
        "status": "ok",
    }
    events = tuple(
        DurableEventRecord(
            event_id=f"event_{cursor}",
            session_id="sess_aox",
            event_type=event_type,
            created_at=f"2026-07-17T00:00:0{cursor - 38}+00:00",
            payload=payload,
            cursor=cursor,
        )
        for cursor, event_type, payload in (
            (40, "tool.invoked", invoked_payload),
            (41, "report_draft.updated", draft.to_dict()),
            (42, "report.generated", report.to_dict()),
            (43, "tool.completed", completed_payload),
        )
    )
    science = live.CatalogArtifactCopy(
        record={
            "artifact_id": "art_science",
            "relative_path": "formal/science.csv",
            "provenance": {"catalog_relative_path": "aox_hmm/science.csv"},
        },
        content=b"result\n",
        content_digest=_digest("science"),
    )

    receipt, artifact, publish_events = live._published_report_receipt(
        context,
        reports=(report,),
        drafts=(draft,),
        documents=(document,),
        durable_events=events,
        pubmed_provider={
            "source_refs": [
                {
                    "source_ref_id": "source_pubmed_aox",
                    "pmid": "12345678",
                }
            ]
        },
        scientific_artifacts=[science],
    )

    assert _report_publish_receipt_is_valid(receipt)
    assert receipt["status"] == report_status.value
    assert receipt["content_document_digest"] != receipt["content_digest"]
    assert receipt["publish_events"] == publish_events
    assert artifact["provenance"]["content_ref"] == "doc_report_aox"
    assert (
        roots.artifact_root / str(artifact["relative_path"])
    ).read_bytes() == markdown.encode("utf-8")


def test_live_runner_seals_exact_no_go_when_live_opt_in_is_absent(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "persistent-micu-ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        test=replace(
            settings.test,
            enable_live_e2e=False,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-no-opt-in",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    before = safe_micu_ledger_snapshot(ledger_path)
    runner = live.LiveAoxAttemptRunner(settings=settings, ledger_path=ledger_path)
    evidence = runner(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=before,
            attempt_number=1,
            attempt_authority=_attempt_authority(roots),
        )
    )

    assert evidence["scientific_outcome"] == {
        "status": "failed",
        "failure_code": "live_e2e_not_enabled",
        "blocker_code": "live_e2e_not_enabled",
        "cutover_eligible": False,
    }
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=before,
        ledger_after=safe_micu_ledger_snapshot(ledger_path),
        artifact_root=roots.artifact_root,
        evidence=evidence,
        sealed_at="2026-07-17T00:00:00+00:00",
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    verification = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)
    assert verification.passed, verification.to_dict()


def test_live_runner_fails_closed_before_settings_without_attempt_authority(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-without-authority",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )

    assert runner._settings_blocker(
        AttemptRunContext(
            roots=roots,
            identity=_identity(),
            ledger_before=safe_micu_ledger_snapshot(ledger_path),
            attempt_number=1,
        )
    ) == {
        "code": "attempt_authority_slot_identity_invalid",
        "message": (
            "formal session does not match its exact predeclared authority slot"
        ),
    }


def test_formal_authority_grant_waits_for_exact_executor_delegation(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    authority = _attempt_authority(roots)
    session_id = str(authority["session_id"])
    task = SimpleNamespace(
        session_id=session_id,
        lane_id=authority["lane_id"],
        assigned_ref="agent:executor:test",
    )
    lane = SimpleNamespace(session_id=session_id, cwd="/workspace")
    agent = SimpleNamespace(
        task_id=authority["task_id"],
        lane_id=authority["lane_id"],
        role="executor",
        status=SimpleNamespace(is_terminal=False),
    )
    provider = _AuthorityGrantProvider(
        task=task,
        lane=lane,
        agent=agent,
    )
    calls: list[tuple[str, dict[str, object], str]] = []

    class Api:
        def post_json(
            self,
            route: str,
            payload: dict[str, object],
            *,
            idempotency_key: str,
        ) -> dict[str, object]:
            calls.append((route, payload, idempotency_key))
            request = authority["authority_request"]
            assert isinstance(request, dict)
            return {
                "record": {
                    "envelope_id": authority["envelope_id"],
                    "request_digest": authority["request_digest"],
                    "session_id": session_id,
                    "task_id": authority["task_id"],
                    "root_ref": request["root_ref"],
                }
            }

    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    assert runner._grant_formal_attempt_authority_if_ready(
        Api(),  # type: ignore[arg-type]
        provider,  # type: ignore[arg-type]
        session_id=session_id,
        authority=authority,
    )
    request = authority["authority_request"]
    assert isinstance(request, dict)
    assert calls == [
        (
            (f"/v3/sessions/{session_id}/scientific-attempt-authorizations"),
            live.authority_grant_payload(authority),
            str(request["idempotency_key"]),
        )
    ]

    invalid_provider = _AuthorityGrantProvider(
        task=task,
        lane=lane,
        agent=SimpleNamespace(
            task_id=authority["task_id"],
            lane_id=authority["lane_id"],
            role="researcher",
            status=SimpleNamespace(is_terminal=False),
        ),
    )
    with pytest.raises(live.LiveProductPathError) as invalid:
        runner._grant_formal_attempt_authority_if_ready(
            Api(),  # type: ignore[arg-type]
            invalid_provider,  # type: ignore[arg-type]
            session_id=session_id,
            authority=authority,
        )
    assert invalid.value.code == "attempt_authority_task_lane_invalid"


def test_live_runner_requires_durable_routes_and_generic_closure_before_cutover(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        llm=replace(settings.llm, api_key="test-live-key"),
        execution=replace(settings.execution, backend="hpc"),
        research=replace(settings.research, pubmed_email="aox@example.org"),
        test=replace(
            settings.test,
            enable_live_e2e=True,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
        attempt_authority=_attempt_authority(roots),
    )

    legacy_runner = live.LiveAoxAttemptRunner(
        settings=settings,
        ledger_path=ledger_path,
    )
    assert legacy_runner._settings_blocker(context) == {
        "code": "aox_durable_operation_ownership_required",
        "message": (
            "AOX cutover requires durable_async_v1 ownership for every provider "
            "and HPC route"
        ),
    }

    durable_settings = replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.DURABLE_ONLY_V1
            ),
        ),
    )
    durable_runner = live.LiveAoxAttemptRunner(
        settings=durable_settings,
        ledger_path=ledger_path,
    )
    assert durable_runner._settings_blocker(context) == {
        "code": "generic_mutation_closure_required",
        "message": "AOX cutover requires generic Host quiescence and sealing",
    }

    ready_settings = replace(
        durable_settings,
        reliability=replace(
            durable_settings.reliability,
            runtime_drain_contract=RuntimeDrainContract.COMMAND_V1,
            mutation_closure_mode=MutationClosureMode.GENERIC_V1,
        ),
    )
    ready_runner = live.LiveAoxAttemptRunner(
        settings=ready_settings,
        ledger_path=ledger_path,
    )
    assert ready_runner._settings_blocker(context) is None


def test_cli_exposes_real_live_campaign_command(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-live",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
            "--attempt-authority-plan",
            str(tmp_path / "attempt-authority-plan.json"),
            "--attempt-authority-consumption",
            str(tmp_path / "attempt-authority-plan.json.consumed.json"),
        ]
    )

    assert args.command == "run-live"
    assert args.approval_mode == "auto"
    assert args.max_drains == 120
    assert args.max_signals_per_drain == 1
    assert args.browser_completion_hold_seconds == 60.0
    assert args.attempt_authority_plan == (tmp_path / "attempt-authority-plan.json")
    assert args.attempt_authority_consumption == (
        tmp_path / "attempt-authority-plan.json.consumed.json"
    )


def _runner_settings(ledger_path: Path) -> OpenZymeSettings:
    settings = OpenZymeSettings.from_env()
    return replace(
        settings,
        test=replace(
            settings.test,
            live_llm=replace(
                settings.test.live_llm,
                token_ledger_path=str(ledger_path),
            ),
        ),
    )


def test_live_runner_settings_are_spawn_pickleable(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=7_200.0,
    )

    restored = pickle.loads(pickle.dumps(runner, protocol=pickle.HIGHEST_PROTOCOL))

    assert isinstance(restored, live.LiveAoxAttemptRunner)
    assert restored.ledger_path == ledger_path
    assert restored.timeout_seconds == 7_200.0


def _minimal_fault_injection_receipt() -> live.FaultInjectionReceipt:
    return live.FaultInjectionReceipt(
        source_artifact_id="art_source",
        source_artifact_digest=_digest("source-artifact"),
        target_artifact_id="art_target",
        target_relative_path="aox_hmm/AOX_ref21.fasta",
        source_operation_id="op_source",
        terminal_failure_operation_id="op_target",
        derivation_id="aox_hmm_reference_set_selection@1",
        derivation_contract_digest=_digest("derivation-contract"),
        derivation_implementation_digest=_digest("derivation-implementation"),
        consumer_tool_id="bio_tools.mafft",
        byte_offset=4,
        before_digest=_digest("before-fault"),
        after_digest=_digest("after-fault"),
        failure_code="artifact_blob_digest_mismatch",
    )


def test_live_runner_preserves_transport_blocker_when_receipt_chain_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-transport-failure",
        allowed_prerequisites=_allowed_prerequisites(),
    )
    context = AttemptRunContext(
        roots=roots,
        identity=_identity(),
        ledger_before=safe_micu_ledger_snapshot(ledger_path),
        attempt_number=1,
        attempt_authority=_attempt_authority(roots),
    )

    class TransportFailingClient:
        base_url = "http://127.0.0.1:54321"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def __enter__(self) -> TransportFailingClient:
            return self

        def __exit__(self, *args: object) -> None:
            del args
            assert not (
                roots.artifact_root / "formal/live-product-path-blocker.json"
            ).exists()

        def get(self, route: str) -> _JsonResponse:
            self.calls.append(route)
            assert route == "/v3/runtime/health"
            raise httpx.ConnectError(
                "deterministic loopback transport failure",
                request=httpx.Request("GET", f"{self.base_url}{route}"),
            )

    raw_client = TransportFailingClient()
    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_settings_blocker",
        lambda self, context: None,
    )
    monkeypatch.setattr(live, "build_configured_foundation", lambda **kwargs: object())
    monkeypatch.setattr(live, "create_app", lambda dependencies: object())
    monkeypatch.setattr(live, "_LoopbackHost", lambda **kwargs: raw_client)
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
    )

    evidence = runner(context)

    assert evidence["scientific_outcome"] == {
        "status": "failed",
        "failure_code": "host_public_api_transport_failed",
        "blocker_code": "host_public_api_transport_failed",
        "cutover_eligible": False,
    }
    assert evidence["report"]["cutover_eligible"] is False
    assert evidence["product_path"]["public_api_receipt_digest"] == (
        live.canonical_digest([])
    )
    blocker_payload = json.loads(
        (roots.artifact_root / "formal/live-product-path-blocker.json").read_text(
            encoding="utf-8"
        )
    )
    assert blocker_payload["blocker"]["code"] == ("host_public_api_transport_failed")
    assert blocker_payload["blocker"]["details"] == {"failure_type": "ConnectError"}
    assert blocker_payload["public_api_receipts"] == []
    assert raw_client.calls == ["/v3/runtime/health"]


def test_runtime_drain_coordinates_three_serial_approvals_while_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_ids = ("approval_serial_1", "approval_serial_2", "approval_serial_3")
    raw_client = _SerialApprovalJsonClient(approval_ids)
    api = live._PublicHostClient(raw_client)

    try:
        coordination = runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_serial",
            purpose="probe",
            drain_number=1,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )
    finally:
        raw_client.release_all()

    assert raw_client.drain_started.is_set()
    assert raw_client.drain_payloads == [
        {
            "max_signals": 1,
            "max_steps_per_agent": 16,
            "auto_enqueue_ready_tasks": False,
        }
    ]
    assert coordination.approval_ids == approval_ids
    assert coordination.workspace == {"pending_approvals": []}
    assert coordination.browser_approval_receipt is None
    assert coordination.fault_receipt is None
    assert raw_client.resolve_calls == [
        (approval_id, "approved", True) for approval_id in approval_ids
    ]
    assert coordination.workspace_response_binding["route"] == (
        "/v3/sessions/sess_serial/workspace"
    )
    assert coordination.workspace_response_binding[
        "response_semantic_digest"
    ] == live.canonical_digest(coordination.workspace)
    assert raw_client.get_routes.count("/v3/sessions/sess_serial/workspace") == 1
    assert (
        "/v3/sessions/sess_serial/runtime/commands/runtime_command_001"
        in raw_client.get_routes
    )
    assert all(
        route
        in {
            "/v3/sessions/sess_serial/pending-approvals",
            "/v3/sessions/sess_serial/runtime/commands/runtime_command_001",
        }
        for route in raw_client.get_routes[:-1]
    )
    sealed = api.sealed_receipts
    assert [receipt.sequence for receipt in sealed] == list(range(1, len(sealed) + 1))
    drain_receipts = [
        receipt
        for receipt in sealed
        if receipt.route == "/v3/sessions/sess_serial/runtime/drain"
    ]
    assert len(drain_receipts) == 1
    assert drain_receipts[0].sequence == 1
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-1"
        for thread in threading.enumerate()
    )


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    (
        (None, "runtime_command_outcome_missing"),
        (
            {"schema_version": "runtime_command_outcome@unsupported"},
            "runtime_command_outcome_invalid",
        ),
    ),
)
def test_runtime_drain_requires_valid_terminal_v2_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
    expected_code: str,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _TerminalOutcomeJsonClient(outcome)
    api = live._PublicHostClient(raw_client)

    with pytest.raises(live.LiveProductPathError) as captured:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_serial",
            purpose="probe",
            drain_number=1,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )

    assert captured.value.code == expected_code


def test_runtime_drain_resolves_approval_exposed_by_waiting_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_after_bounded_drain"
    raw_client = _DrainReturnsPendingApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)

    coordination = runner._coordinate_runtime_drain(
        api,
        object(),  # type: ignore[arg-type]
        session_id="sess_post_response",
        purpose="probe",
        drain_number=2,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset(),
        browser_gate_enabled=False,
        browser_approval_receipt=None,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
    )

    assert raw_client.drain_returned.is_set()
    assert raw_client.resolve_calls == [(approval_id, "approved", True)]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.workspace == {"pending_approvals": []}
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-2"
        for thread in threading.enumerate()
    )


def test_terminal_runtime_command_waits_for_attached_writer_and_late_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_after_terminal_command"
    raw_client = _TerminalCommandDelayedApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)
    writer_checks = 0

    monkeypatch.setattr(
        live,
        "_assert_cutover_operation_budget_before_approval",
        lambda *args, **kwargs: None,
    )

    def has_attached_writer(*args: object, **kwargs: object) -> bool:
        nonlocal writer_checks
        del args, kwargs
        writer_checks += 1
        if writer_checks == 1:
            raw_client.pending = True
            return True
        return False

    monkeypatch.setattr(
        live.AoxRuntimeObservationService,
        "has_inflight_mutation_writers",
        has_attached_writer,
    )

    coordination = runner._coordinate_runtime_drain(
        api,
        object(),  # type: ignore[arg-type]
        session_id="sess_terminal_writer",
        purpose="probe",
        drain_number=5,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset(),
        browser_gate_enabled=False,
        browser_approval_receipt=None,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
    )

    assert writer_checks == 2
    assert raw_client.resolve_calls == [(approval_id, "approved")]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.workspace == {"pending_approvals": []}


def test_formal_terminal_runtime_command_uses_bounded_observer_on_real_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        live,
        "_assert_cutover_operation_budget_before_approval",
        lambda *args, **kwargs: None,
    )
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "scope.sqlite3"))
    session = Session.create(
        session_id="sess_post_response",
        project_id="aox-blank-world-cutover",
        title="formal",
        objective="settle one terminal runtime command",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
    blob_root = tmp_path / "blobs"
    runner._open_pre_attempt_session_scope(
        provider,
        session_id=session.session_id,
        outer_attempt_id="positive-terminal-observer",
        blob_root=blob_root,
    )
    approval_id = "approval_before_terminal_settlement"
    raw_client = _DrainReturnsPendingApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)

    coordination = runner._coordinate_runtime_drain(
        api,
        provider,
        session_id=session.session_id,
        purpose="formal",
        drain_number=6,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset(),
        browser_gate_enabled=False,
        browser_approval_receipt=None,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
        attempt_authority={"attempt_id": "positive-terminal-observer"},
    )

    assert raw_client.resolve_calls == [(approval_id, "approved", True)]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.workspace == {"pending_approvals": []}
    with provider.read() as unit_of_work:
        scopes = unit_of_work.repositories.mutation_scopes.list_by_session(
            session.session_id
        )
        writers = unit_of_work.repositories.mutation_writers.list_all(
            scopes[0].scope_id
        )
        active_writers = unit_of_work.repositories.mutation_writers.list_active(
            scopes[0].scope_id
        )
    assert len(scopes) == 1
    assert len(writers) == 1
    assert (
        writers[0].owner_ref == "aox-attempt-driver:positive-terminal-observer:formal"
    )
    assert writers[0].state.value == "retired"
    assert active_writers == []

    sealed = runner._close_session_mutation_scope(
        provider,
        scope_id=scopes[0].scope_id,
        blob_root=blob_root,
    )
    assert sealed["state"] == "sealed"


class _FormalRolloverState:
    def __init__(self, *, session_id: str, envelope_id: str) -> None:
        self.session_id = session_id
        self.envelope_id = envelope_id
        self.attempt_id = "attempt_terminal_rollover"
        self.phase = "pending"
        self.post_scope_parent_id = f"mutation_scope_{self.attempt_id}"

    def open_post_scope(self, *, parent_scope_id: str | None = None) -> None:
        self.phase = "post"
        if parent_scope_id is not None:
            self.post_scope_parent_id = parent_scope_id

    def repositories(self) -> object:
        attempt_scope = SimpleNamespace(
            scope_id=f"mutation_scope_{self.attempt_id}",
            session_id=self.session_id,
            scope_kind=MutationScopeKind.ATTEMPT,
            scope_ref=self.attempt_id,
            parent_scope_id=None,
            state=(
                MutationScopeState.SEALED
                if self.phase == "post"
                else MutationScopeState.FREEZING
            ),
        )
        attempt = SimpleNamespace(
            attempt_id=self.attempt_id,
            admission_request_id="admission_terminal_rollover",
            envelope_id=self.envelope_id,
            session_id=self.session_id,
            task_id="task_terminal_rollover",
            lane_id="lane_terminal_rollover",
            campaign_id="campaign_terminal_rollover",
            workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
            scope=ScientificAttemptScope.FORMAL,
            root_ref="attempts/terminal-rollover",
            mutation_scope_id=attempt_scope.scope_id,
            status=(
                ScientificAttemptStatus.CLOSED
                if self.phase == "post"
                else ScientificAttemptStatus.ACTIVE
            ),
        )
        request = SimpleNamespace(
            closure_request_id="closure_request_terminal_rollover",
            attempt_id=self.attempt_id,
            selection_id="selection_terminal_rollover",
        )
        closure = (
            None
            if self.phase != "post"
            else SimpleNamespace(
                closure_id="closure_terminal_rollover",
                closure_request_id=request.closure_request_id,
                attempt_id=self.attempt_id,
                selection_id=request.selection_id,
            )
        )
        scopes: tuple[object, ...] = (attempt_scope,)
        if self.phase == "post":
            scopes = (
                attempt_scope,
                SimpleNamespace(
                    scope_id=f"mutation_scope_post_{self.attempt_id}",
                    session_id=self.session_id,
                    scope_kind=MutationScopeKind.SESSION,
                    scope_ref=(f"post-scientific-attempt:{self.attempt_id}"),
                    parent_scope_id=self.post_scope_parent_id,
                    state=MutationScopeState.OPEN,
                ),
            )
        return SimpleNamespace(
            scientific_attempts=SimpleNamespace(
                list_by_session=lambda _session_id: (attempt,)
            ),
            scientific_attempt_closure_requests=SimpleNamespace(
                get_by_attempt=lambda _attempt_id: request
            ),
            scientific_attempt_closures=SimpleNamespace(
                get_by_attempt=lambda _attempt_id: closure
            ),
            mutation_scopes=SimpleNamespace(
                list_by_session=lambda _session_id: scopes,
            ),
        )


def _formal_rollover_provider(
    *,
    session_id: str,
    envelope_id: str,
) -> tuple[object, _FormalRolloverState]:
    state = _FormalRolloverState(
        session_id=session_id,
        envelope_id=envelope_id,
    )
    provider = SimpleNamespace(
        read=lambda: _SelectedChainApprovalProvider._Scope(state.repositories())
    )
    return provider, state


def _formal_rollover_authority(
    *,
    envelope_id: str,
    outer_attempt_id: str,
) -> dict[str, object]:
    return {
        "attempt_id": outer_attempt_id,
        "envelope_id": envelope_id,
        "task_id": "task_terminal_rollover",
        "lane_id": "lane_terminal_rollover",
        "scope": ScientificAttemptScope.FORMAL.value,
        "authority_request": {
            "campaign_id": "campaign_terminal_rollover",
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "root_ref": "attempts/terminal-rollover",
        },
    }


def test_formal_terminal_command_waits_through_exact_scope_rollover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    session_id = "sess_serial"
    envelope_id = "attempt_authority_rollover"
    provider, rollover = _formal_rollover_provider(
        session_id=session_id, envelope_id=envelope_id
    )
    raw_client = _SerialApprovalJsonClient(())
    api = live._PublicHostClient(raw_client)
    observer_checks = 0

    @contextmanager
    def observe_writers(*_args: object, **_kwargs: object):
        nonlocal observer_checks
        observer_checks += 1
        if observer_checks == 1:
            rollover.open_post_scope()
            raise live.AoxRuntimeObservationError(
                "mutation_driver_writer_identity_invalid",
                "runtime coordination lacks one exact outer attempt-driver writer",
                details={
                    "mutation_scope_error_code": ("mutation_writer_admission_closed"),
                    "mutation_writer_admission_reason": "zero_open_scope",
                },
            )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        observe_writers,
    )
    monkeypatch.setattr(
        live.AoxRuntimeObservationService,
        "has_inflight_mutation_writers",
        lambda *_args, **_kwargs: False,
    )

    coordination = runner._coordinate_runtime_drain(
        api,
        provider,  # type: ignore[arg-type]
        session_id=session_id,
        purpose="formal",
        drain_number=1,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset(),
        browser_gate_enabled=False,
        browser_approval_receipt=None,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
        attempt_authority=_formal_rollover_authority(
            envelope_id=envelope_id,
            outer_attempt_id="closure-stage-rollover",
        ),
    )

    assert observer_checks == 2
    assert len(raw_client.drain_payloads) == 1
    assert coordination.command_status == "completed"
    assert coordination.workspace == {"pending_approvals": []}


def test_full_formal_observation_uses_the_same_scope_rollover_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    envelope_id = "attempt_authority_full_observation_rollover"
    provider, rollover = _formal_rollover_provider(
        session_id="sess_formal_rollover", envelope_id=envelope_id
    )
    observer_checks = 0
    expected = SimpleNamespace(state="completed", blocker_code=None)

    @contextmanager
    def observe_writers(*_args: object, **_kwargs: object):
        nonlocal observer_checks
        observer_checks += 1
        if observer_checks == 1:
            raise live.AoxRuntimeObservationError(
                "mutation_driver_writer_identity_invalid",
                "runtime coordination lacks one exact outer attempt-driver writer",
                details={
                    "mutation_scope_error_code": ("mutation_writer_admission_closed"),
                    "mutation_writer_admission_reason": "zero_open_scope",
                },
            )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        observe_writers,
    )
    monkeypatch.setattr(
        live.AoxRuntimeObservationService,
        "observe_session",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(
        live.time,
        "sleep",
        lambda _seconds: rollover.open_post_scope(),
    )

    observation = runner._observe_session_runtime(
        provider,  # type: ignore[arg-type]
        session_id="sess_formal_rollover",
        purpose="formal",
        attempt_authority=_formal_rollover_authority(
            envelope_id=envelope_id,
            outer_attempt_id="closure-stage-full-observation",
        ),
        rollover_deadline=time.monotonic() + 1.0,
    )

    assert observation is expected
    assert observer_checks == 2


def test_formal_terminal_command_does_not_mask_other_observer_identity_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _SerialApprovalJsonClient(())
    api = live._PublicHostClient(raw_client)

    @contextmanager
    def reject_observer(*_args: object, **_kwargs: object):
        raise live.AoxRuntimeObservationError(
            "mutation_driver_writer_identity_invalid",
            "runtime coordination lacks one exact outer attempt-driver writer",
            details={
                "mutation_scope_error_code": ("mutation_writer_parent_scope_mismatch")
            },
        )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        reject_observer,
    )

    with pytest.raises(live.LiveProductPathError) as captured:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_serial",
            purpose="formal",
            drain_number=1,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
            attempt_authority={
                "attempt_id": "closure-stage-parent-mismatch",
                "envelope_id": "attempt_authority_parent_mismatch",
            },
        )

    assert captured.value.code == "mutation_driver_writer_identity_invalid"
    assert captured.value.details == {
        "mutation_scope_error_code": "mutation_writer_parent_scope_mismatch"
    }


def test_formal_rollover_never_retries_ambiguous_original_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )

    @contextmanager
    def reject_ambiguous(*_args: object, **_kwargs: object):
        raise live.AoxRuntimeObservationError(
            "mutation_driver_writer_identity_invalid",
            "runtime coordination lacks one exact outer attempt-driver writer",
            details={
                "mutation_scope_error_code": ("mutation_writer_admission_ambiguous"),
                "mutation_writer_admission_reason": ("ambiguous_open_scopes"),
                "open_scope_count": 2,
            },
        )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        reject_ambiguous,
    )

    with pytest.raises(live.AoxRuntimeObservationError) as captured:
        runner._observe_session_runtime(
            object(),  # type: ignore[arg-type]
            session_id="sess_ambiguous_rollover",
            purpose="formal",
            attempt_authority=_formal_rollover_authority(
                envelope_id="attempt_authority_ambiguous",
                outer_attempt_id="closure-stage-ambiguous",
            ),
            rollover_deadline=time.monotonic() + 1.0,
        )

    assert captured.value.code == "mutation_driver_writer_identity_invalid"
    assert captured.value.details["mutation_writer_admission_reason"] == (
        "ambiguous_open_scopes"
    )
    assert captured.value.details["open_scope_count"] == 2


def test_formal_rollover_invalid_post_parent_fails_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    provider, rollover = _formal_rollover_provider(
        session_id="sess_invalid_post_parent",
        envelope_id="attempt_authority_invalid_post_parent",
    )
    rollover.open_post_scope(parent_scope_id="mutation_scope_wrong_parent")

    @contextmanager
    def reject_observer(*_args: object, **_kwargs: object):
        raise live.AoxRuntimeObservationError(
            "mutation_driver_writer_identity_invalid",
            "runtime coordination lacks one exact outer attempt-driver writer",
            details={
                "mutation_scope_error_code": ("mutation_writer_admission_closed"),
                "mutation_writer_admission_reason": "zero_open_scope",
            },
        )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        reject_observer,
    )

    with pytest.raises(live.AoxRuntimeObservationError) as captured:
        runner._observe_session_runtime(
            provider,  # type: ignore[arg-type]
            session_id="sess_invalid_post_parent",
            purpose="formal",
            attempt_authority=_formal_rollover_authority(
                envelope_id="attempt_authority_invalid_post_parent",
                outer_attempt_id="closure-stage-invalid-post-parent",
            ),
            rollover_deadline=time.monotonic() + 1.0,
        )

    assert captured.value.code == ("scientific_attempt_scope_rollover_invalid")
    assert captured.value.details == {
        "scope_rollover_reason": "post_scope_identity_invalid",
        "scope_state": "sealed",
        "open_scope_count": 1,
    }


def test_runtime_barrier_observer_preserves_atomic_admission_reason(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "observer.sqlite3"))
    session = Session.create(
        session_id="sess_observer_admission_reason",
        project_id="aox-blank-world-cutover",
        title="observer admission reason",
        objective="Preserve the atomic refusal classification",
    )
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(session)
        scope = MutationScopeService(unit_of_work.repositories).open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.SESSION,
            scope_ref=session.session_id,
        )
        MutationScopeService(unit_of_work.repositories).begin_freeze(scope.scope_id)

    with pytest.raises(live.AoxRuntimeObservationError) as captured:
        with runner._runtime_barrier_observer(
            provider,
            session_id=session.session_id,
            purpose="formal",
            attempt_authority={"attempt_id": "closure-stage-observer-reason"},
        ):
            pass

    assert captured.value.details == {
        "mutation_scope_error_code": "mutation_writer_admission_closed",
        "mutation_writer_admission_reason": "zero_open_scope",
        "open_scope_count": 0,
    }


def test_sealed_rollover_details_are_bounded_and_allowlisted() -> None:
    projected = live._sealed_failure_details(
        {
            "mutation_scope_error_code": "mutation_writer_admission_closed",
            "mutation_writer_admission_reason": "zero_open_scope",
            "scope_rollover_phase": "rollover_pending",
            "scope_rollover_reason": "post_scope_identity_invalid",
            "scope_state": "sealed",
            "open_scope_count": 1,
            "scope_id": "/private/mutation_scope_secret",
            "authority_token": "secret",
        }
    )

    assert projected == {
        "mutation_scope_error_code": "mutation_writer_admission_closed",
        "mutation_writer_admission_reason": "zero_open_scope",
        "open_scope_count": "1",
        "scope_rollover_phase": "rollover_pending",
        "scope_rollover_reason": "post_scope_identity_invalid",
        "scope_state": "sealed",
    }
    assert (
        live._sealed_failure_details(
            {
                "open_scope_count": True,
            }
        )
        == {}
    )
    assert (
        live._sealed_failure_details(
            {
                "open_scope_count": live._MAX_SEALED_OPEN_SCOPE_COUNT + 1,
            }
        )
        == {}
    )


def test_formal_scope_rollover_wait_remains_bounded_and_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=0.02,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _SerialApprovalJsonClient(())
    api = live._PublicHostClient(raw_client)
    provider, _rollover = _formal_rollover_provider(
        session_id="sess_serial",
        envelope_id="attempt_authority_stalled",
    )

    @contextmanager
    def reject_observer(*_args: object, **_kwargs: object):
        raise live.AoxRuntimeObservationError(
            "mutation_driver_writer_identity_invalid",
            "runtime coordination lacks one exact outer attempt-driver writer",
            details={
                "mutation_scope_error_code": ("mutation_writer_admission_closed"),
                "mutation_writer_admission_reason": "zero_open_scope",
            },
        )
        yield

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_runtime_barrier_observer",
        reject_observer,
    )
    with pytest.raises(live.LiveProductPathError) as captured:
        runner._coordinate_runtime_drain(
            api,
            provider,  # type: ignore[arg-type]
            session_id="sess_serial",
            purpose="formal",
            drain_number=1,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
            attempt_authority=_formal_rollover_authority(
                envelope_id="attempt_authority_stalled",
                outer_attempt_id="closure-stage-stalled",
            ),
        )

    assert captured.value.code == "scientific_attempt_scope_rollover_stalled"
    assert captured.value.details == {
        "session_id": "sess_serial",
        "scope_rollover_phase": "rollover_pending",
        "scope_state": "freezing",
        "open_scope_count": 0,
    }
    assert len(raw_client.drain_payloads) == 1


def test_later_drain_auto_approves_after_chrome_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_after_chrome_drain"
    raw_client = _DrainReturnsPendingApprovalJsonClient(approval_id)
    api = live._PublicHostClient(raw_client)
    chrome_receipt = {
        "schema_id": live.BROWSER_APPROVAL_RECEIPT_SCHEMA_ID,
        "approval_id": "approval_chrome_first",
    }

    def unexpected_browser_handoff(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("a later drain must not request a second Chrome approval")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_wait_for_browser_approval",
        unexpected_browser_handoff,
    )

    coordination = runner._coordinate_runtime_drain(
        api,
        object(),  # type: ignore[arg-type]
        session_id="sess_post_response",
        purpose="probe",
        drain_number=3,
        started=time.monotonic(),
        pre_event_cursor=0,
        prior_approval_ids=frozenset({"approval_chrome_first"}),
        browser_gate_enabled=True,
        browser_approval_receipt=chrome_receipt,
        fault_enabled=False,
        fault_blob_root=None,
        fault_receipt=None,
    )

    assert raw_client.resolve_calls == [(approval_id, "approved", True)]
    assert coordination.approval_ids == (approval_id,)
    assert coordination.browser_approval_receipt is chrome_receipt
    assert coordination.workspace == {"pending_approvals": []}


def test_same_inflight_drain_uses_chrome_once_then_auto_approves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 4
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_ids = ("approval_chrome_first", "approval_same_drain_second")
    raw_client = _SerialApprovalJsonClient(approval_ids)
    api = live._PublicHostClient(raw_client)
    handoff_calls: list[str] = []
    chrome_receipt = {
        "schema_id": live.BROWSER_APPROVAL_RECEIPT_SCHEMA_ID,
        "approval_id": approval_ids[0],
    }

    def resolve_first_in_browser(
        self: live.LiveAoxAttemptRunner,
        handoff_api: live._PublicHostClient,
        *,
        session_id: str,
        workspace: dict[str, object],
        workspace_receipt: live.PublicApiReceipt,
        pending_approval: dict[str, object],
        started: float,
        pre_event_cursor: int,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del self, workspace, workspace_receipt, started, pre_event_cursor
        approval_id = str(pending_approval.get("approval_id") or "")
        handoff_calls.append(approval_id)
        handoff_api.post_json(
            f"/v3/approvals/{approval_id}/resolve",
            {"decision": "approved"},
            idempotency_key=f"{session_id}:browser-approve:{approval_id}",
        )
        updated_workspace = handoff_api.get_json(f"/v3/sessions/{session_id}/workspace")
        return chrome_receipt, updated_workspace

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_wait_for_browser_approval",
        resolve_first_in_browser,
    )

    try:
        coordination = runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_serial",
            purpose="probe",
            drain_number=drain_number,
            started=time.monotonic(),
            pre_event_cursor=17,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=True,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )
    finally:
        raw_client.release_all()

    assert handoff_calls == [approval_ids[0]]
    assert raw_client.resolve_calls == [
        (approval_id, "approved", True) for approval_id in approval_ids
    ]
    assert coordination.approval_ids == approval_ids
    assert coordination.browser_approval_receipt is chrome_receipt
    assert coordination.workspace == {"pending_approvals": []}
    assert all(
        not thread.is_alive() or thread.name != f"aox-cutover-drain-{drain_number}"
        for thread in threading.enumerate()
    )


def test_runtime_drain_wraps_background_exception_as_stable_failure(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    api = live._PublicHostClient(_FailingDrainJsonClient())

    with pytest.raises(live.LiveProductPathError) as error:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_failed",
            purpose="probe",
            drain_number=7,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )

    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert "private background failure detail" not in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-7"
        for thread in threading.enumerate()
    )


def test_runtime_drain_failure_wins_over_concurrent_workspace_failure(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 10
    drain_thread_name = f"aox-cutover-drain-{drain_number}"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _ConcurrentDrainAndWorkspaceFailureJsonClient(
        drain_thread_name=drain_thread_name
    )
    api = live._PublicHostClient(raw_client)

    with pytest.raises(live.LiveProductPathError) as error:
        runner._coordinate_runtime_drain(
            api,
            object(),  # type: ignore[arg-type]
            session_id="sess_concurrent_failure",
            purpose="probe",
            drain_number=drain_number,
            started=time.monotonic(),
            pre_event_cursor=0,
            prior_approval_ids=frozenset(),
            browser_gate_enabled=False,
            browser_approval_receipt=None,
            fault_enabled=False,
            fault_blob_root=None,
            fault_receipt=None,
        )

    assert raw_client.workspace_get_started.is_set()
    assert raw_client.drain_failure_started.is_set()
    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {
        "command_status": "failed",
        "cleanup_failure_type": "RuntimeError",
    }
    assert error.value.__cause__ is None
    assert "workspace failure" not in str(error.value)
    assert all(
        not thread.is_alive() or thread.name != drain_thread_name
        for thread in threading.enumerate()
    )


def test_runtime_drain_primary_error_wins_over_cleanup_failure(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 11
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _CoordinationCleanupFailureJsonClient(drain_fails=False)
    api = live._PublicHostClient(raw_client)

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_cleanup_precedence",
                purpose="probe",
                drain_number=drain_number,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=False,
                fault_blob_root=None,
                fault_receipt=None,
            )
    finally:
        raw_client.release_drain.set()

    assert error.value.code == "scientific_primary_failure"
    assert error.value.details == {
        "scientific_stage": "motif",
        "cleanup_failure_type": "RuntimeError",
    }
    assert raw_client.cleanup_attempted.is_set()
    assert raw_client.drain_finished.is_set()
    assert "private cleanup failure detail" not in str(error.value)
    assert all(
        not thread.is_alive() or thread.name != f"aox-cutover-drain-{drain_number}"
        for thread in threading.enumerate()
    )


def test_runtime_drain_rejects_approval_delayed_past_old_cleanup_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 13
    clock_lock = threading.Lock()
    clock_value = -20.0

    def stepped_monotonic() -> float:
        nonlocal clock_value
        with clock_lock:
            clock_value += 20.0
            return clock_value

    monkeypatch.setattr(
        live,
        "time",
        SimpleNamespace(monotonic=stepped_monotonic, sleep=lambda _seconds: None),
    )
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1_000.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _DelayedCoordinationCleanupApprovalJsonClient(
        fail_first_cleanup_read=False,
        empty_cleanup_reads=1,
    )
    api = live._PublicHostClient(raw_client)

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_delayed_cleanup",
                purpose="probe",
                drain_number=drain_number,
                started=0.0,
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=False,
                fault_blob_root=None,
                fault_receipt=None,
            )
    finally:
        raw_client.release_drain.set()

    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {"command_status": "failed"}
    assert raw_client.cleanup_read_count >= 2
    assert raw_client.resolve_calls == [(raw_client.approval_id, "rejected")]
    assert raw_client.drain_finished.is_set()
    assert all(
        not thread.is_alive() or thread.name != f"aox-cutover-drain-{drain_number}"
        for thread in threading.enumerate()
    )


def test_runtime_drain_cleanup_read_recovers_and_rejects_later_approval(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 14
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _DelayedCoordinationCleanupApprovalJsonClient(
        fail_first_cleanup_read=True,
        empty_cleanup_reads=1,
    )
    api = live._PublicHostClient(raw_client)

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_delayed_cleanup",
                purpose="probe",
                drain_number=drain_number,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=False,
                fault_blob_root=None,
                fault_receipt=None,
            )
    finally:
        raw_client.release_drain.set()

    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {
        "command_status": "failed",
        "cleanup_failure_type": "RuntimeError",
    }
    assert raw_client.cleanup_read_count >= 3
    assert raw_client.resolve_calls == [(raw_client.approval_id, "rejected")]
    assert raw_client.drain_finished.is_set()
    assert "private transient cleanup read detail" not in str(error.value)
    assert all(
        not thread.is_alive() or thread.name != f"aox-cutover-drain-{drain_number}"
        for thread in threading.enumerate()
    )


def test_runtime_drain_cleanup_failure_without_primary_uses_cleanup_taxonomy() -> None:
    cleanup_error = RuntimeError("private standalone cleanup failure")

    with pytest.raises(live.LiveProductPathError) as error:
        live._raise_runtime_drain_failures(
            drain_errors=[],
            coordination_error=None,
            cleanup_errors=[cleanup_error],
        )

    assert error.value.code == "runtime_drain_coordination_cleanup_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert error.value.__cause__ is cleanup_error
    assert "private standalone cleanup failure" not in str(error.value)


def test_sealed_failure_details_allowlists_only_safe_machine_identifiers() -> None:
    assert live._sealed_failure_details(
        {
            "failure_type": "RuntimeError",
            "command_status": "failed",
            "coordination_failure_type": "LiveProductPathError",
            "cleanup_failure_type": "OSError",
            "route": "/v3/private/runtime/drain",
            "private_locator": "ssh://private-runner",
        }
    ) == {
        "cleanup_failure_type": "OSError",
        "command_status": "failed",
        "coordination_failure_type": "LiveProductPathError",
        "failure_type": "RuntimeError",
    }


def test_runtime_drain_command_failure_wins_over_primary_and_cleanup_failures(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    drain_number = 12
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    raw_client = _CoordinationCleanupFailureJsonClient(drain_fails=True)
    api = live._PublicHostClient(raw_client)

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_cleanup_precedence",
                purpose="probe",
                drain_number=drain_number,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=False,
                fault_blob_root=None,
                fault_receipt=None,
            )
    finally:
        raw_client.release_drain.set()

    assert error.value.code == "runtime_drain_command_failed"
    assert error.value.details == {
        "command_status": "failed",
        "cleanup_failure_type": "RuntimeError",
    }
    assert error.value.__cause__ is None
    assert raw_client.cleanup_attempted.is_set()
    assert raw_client.drain_finished.is_set()
    assert "private cleanup failure detail" not in str(error.value)
    assert "private drain failure detail" not in str(error.value)
    assert all(
        not thread.is_alive() or thread.name != f"aox-cutover-drain-{drain_number}"
        for thread in threading.enumerate()
    )


def test_fault_injection_invariant_failure_rejects_pending_without_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    approval_id = "approval_fault_invariant"
    raw_client = _SerialApprovalJsonClient((approval_id,))
    api = live._PublicHostClient(raw_client)

    def fail_target_invariant(
        self: live.LiveAoxAttemptRunner,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
        blob_root: Path,
    ) -> live.FaultInjectionReceipt | None:
        del self, provider, session_id, blob_root
        raw_client.call_order.append(f"inject:{approval_id}")
        raise live.LiveProductPathError(
            "fault_target_digest_binding_invalid",
            "fault target invariant failed before approval",
        )

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_inject_before_hpc_approval",
        fail_target_invariant,
    )

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_serial",
                purpose="probe",
                drain_number=8,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=True,
                fault_blob_root=tmp_path / "blobs",
                fault_receipt=None,
            )
    finally:
        raw_client.release_all()

    assert error.value.code == "fault_target_digest_binding_invalid"
    assert raw_client.resolve_calls == [(approval_id, "rejected", True)]
    assert not any(
        decision == "approved" for _, decision, _ in raw_client.resolve_calls
    )
    assert raw_client.call_order == [
        f"inject:{approval_id}",
        f"resolve:{approval_id}:rejected",
    ]
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-8"
        for thread in threading.enumerate()
    )


def test_fault_path_rejects_approval_after_target_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cutover_operation_budget(monkeypatch)
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        timeout_seconds=1.0,
        browser_poll_interval_seconds=0.001,
    )
    before_target = "approval_before_fault_target"
    fault_target = "approval_fault_target"
    after_target = "approval_after_fault_target"
    approval_ids = (before_target, fault_target, after_target)
    raw_client = _SerialApprovalJsonClient(approval_ids)
    api = live._PublicHostClient(raw_client)
    receipt = _minimal_fault_injection_receipt()

    def inject_target_only(
        self: live.LiveAoxAttemptRunner,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
        blob_root: Path,
    ) -> live.FaultInjectionReceipt | None:
        del self, provider, session_id, blob_root
        raw_client.call_order.append(f"inject:{approval_id}")
        if approval_id == before_target:
            return None
        if approval_id == fault_target:
            return receipt
        raise AssertionError("additional approval must fail before reinjection")

    monkeypatch.setattr(
        live.LiveAoxAttemptRunner,
        "_inject_before_hpc_approval",
        inject_target_only,
    )

    try:
        with pytest.raises(live.LiveProductPathError) as error:
            runner._coordinate_runtime_drain(
                api,
                object(),  # type: ignore[arg-type]
                session_id="sess_serial",
                purpose="probe",
                drain_number=9,
                started=time.monotonic(),
                pre_event_cursor=0,
                prior_approval_ids=frozenset(),
                browser_gate_enabled=False,
                browser_approval_receipt=None,
                fault_enabled=True,
                fault_blob_root=tmp_path / "blobs",
                fault_receipt=None,
            )
    finally:
        raw_client.release_all()

    assert error.value.code == "fault_path_additional_approval_forbidden"
    assert error.value.details == {"approval_id": after_target}
    assert raw_client.resolve_calls == [
        (before_target, "approved", True),
        (fault_target, "approved", True),
        (after_target, "rejected", True),
    ]
    assert raw_client.call_order == [
        f"inject:{before_target}",
        f"resolve:{before_target}:approved",
        f"inject:{fault_target}",
        f"resolve:{fault_target}:approved",
        f"resolve:{after_target}:rejected",
    ]
    assert all(
        not thread.is_alive() or thread.name != "aox-cutover-drain-9"
        for thread in threading.enumerate()
    )


def test_same_process_loopback_host_serves_exact_app_and_stops() -> None:
    app = FastAPI()

    @app.get("/identity")
    def identity() -> dict[str, int]:
        return {"process_id": os.getpid()}

    host = live._LoopbackHost(app=app, request_timeout_seconds=5.0)
    with host as client:
        response = client.get("/identity")
        assert response.status_code == 200
        assert response.json() == {"process_id": os.getpid()}
        assert host.base_url.startswith("http://127.0.0.1:")

    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_retires_if_ready_record_emission_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    host = live._LoopbackHost(app=app, request_timeout_seconds=5.0)

    def fail_ready_record(payload: object) -> None:
        del payload
        raise RuntimeError("operator stream unavailable")

    monkeypatch.setattr(live, "_emit_operator_record", fail_ready_record)

    with pytest.raises(RuntimeError, match="operator stream unavailable"):
        host.__enter__()

    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_retires_server_thread_after_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingServer:
        started = False
        should_exit = False
        force_exit = False

        def __init__(self, config: object) -> None:
            del config

        @staticmethod
        def run(*, sockets: object) -> None:
            del sockets
            raise RuntimeError("loopback startup failed")

    monkeypatch.setattr(live.uvicorn, "Server", FailingServer)
    host = live._LoopbackHost(app=FastAPI(), request_timeout_seconds=5.0)

    with pytest.raises(live.LiveProductPathError) as error:
        host.__enter__()

    assert error.value.code == "browser_approval_host_start_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert host._thread is not None
    assert host._thread.is_alive() is False


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_loopback_host_retires_server_mutation_after_client_timeout(
    method: str,
) -> None:
    app = FastAPI()
    handler_started = threading.Event()
    handler_finished = threading.Event()

    def blocking_mutation(session_id: str) -> dict[str, str]:
        handler_started.set()
        time.sleep(0.15)
        handler_finished.set()
        return {"session_id": session_id}

    app.add_api_route(
        "/v3/sessions/{session_id}/mutation",
        blocking_mutation,
        methods=[method],
    )
    host = live._LoopbackHost(
        app=app,
        request_timeout_seconds=0.02,
        shutdown_timeout_seconds=1.0,
    )
    with host as client:
        with pytest.raises(httpx.ReadTimeout):
            client.request(method, "/v3/sessions/sess_slow/mutation")
        assert handler_started.wait(timeout=1.0)
        assert handler_finished.is_set() is False

    assert handler_finished.is_set() is True
    assert host._thread is not None
    assert host._thread.is_alive() is False


def test_loopback_host_never_returns_while_server_thread_remains_alive() -> None:
    host = live._LoopbackHost(
        app=FastAPI(),
        request_timeout_seconds=1.0,
        shutdown_timeout_seconds=0.001,
    )
    server = SimpleNamespace(should_exit=False, force_exit=False)
    host._server = server
    finished = threading.Event()

    def linger_past_grace() -> None:
        time.sleep(0.05)
        finished.set()

    thread = threading.Thread(target=linger_past_grace, daemon=False)
    host._thread = thread
    thread.start()

    started = time.monotonic()
    host._retire_server_thread()

    assert time.monotonic() - started >= 0.04
    assert finished.is_set() is True
    assert thread.is_alive() is False
    assert server.should_exit is True
    assert server.force_exit is True


def test_chrome_once_waits_for_exact_public_resolution_events(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation")
    pending = {
        "approval_id": "approval_browser_001",
        "operation": {
            "operation_id": "operation_browser_001",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_001",
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
    }
    pre_workspace = {
        "pending_approvals": [pending],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation_browser_001",
                    "operation_digest": operation_digest,
                    "approval_id": "approval_browser_001",
                    "approval_state": "pending",
                    "status": "waiting_approval",
                }
            ]
        },
    }
    post_workspace = {
        "pending_approvals": [],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation_browser_001",
                    "operation_digest": operation_digest,
                    "approval_id": "approval_browser_001",
                    "approval_state": "approved",
                    "status": "waiting_approval",
                }
            ]
        },
    }
    resolution_events = (
        {
            "cursor": 11,
            "event_id": "event_browser_resolved",
            "session_id": "sess_browser_001",
            "event_type": "approval.resolved",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "actor_ref": "local-user",
            "command_id": "command_browser_resolved",
            "created_at": "2026-07-18T00:00:00+00:00",
            "payload": {
                "approval_id": "approval_browser_001",
                "decision": "approved",
                "actor_ref": "local-user",
            },
        },
        {
            "cursor": 12,
            "event_id": "event_browser_continuation",
            "session_id": "sess_browser_001",
            "event_type": "sdk_controlled_operation.approval_resolved",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "actor_ref": None,
            "command_id": "command_browser_continuation",
            "created_at": "2026-07-18T00:00:01+00:00",
            "payload": {
                "approval_id": "approval_browser_001",
                "operation_id": "operation_browser_001",
                "operation_digest": operation_digest,
                "continuation_id": "continuation_browser_001",
                "decision": "approved",
            },
        },
        {
            "cursor": 13,
            "event_id": "event_browser_projection_backfill",
            "session_id": "sess_browser_001",
            "event_type": "approval.resolved",
            "schema_version": "openzyme.v3.event.v1",
            "visibility": "public",
            "actor_ref": None,
            "command_id": None,
            "created_at": "2026-07-18T00:00:02+00:00",
            "payload": {
                "approval_id": "approval_browser_001",
                "session_id": "sess_browser_001",
                "task_id": "task_browser_001",
                "lane_id": None,
                "kind": "sdk_controlled_operation",
                "requested_action": "Approve browser operation",
                "status": "approved",
                "request_ref": "operation_browser_001",
                "resolution_ref": None,
                "created_at": "2026-07-18T00:00:00+00:00",
                "resolved_at": "2026-07-18T00:00:01+00:00",
            },
        },
    )

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_001/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))
            self.event_reads = 0

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_001"
            assert after_cursor == 10
            self.event_reads += 1
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events?replay=1&after_cursor=10"
                    ),
                    semantic_value=list(resolution_events),
                )
            )
            return resolution_events

        def get_json(
            self,
            route: str,
            *,
            _timeout_seconds: float | None = None,
        ) -> dict[str, object]:
            del _timeout_seconds
            assert route == "/v3/sessions/sess_browser_001/workspace"
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=route,
                    semantic_value=post_workspace,
                )
            )
            return post_workspace

    api = Api()
    receipt, workspace = runner._wait_for_browser_approval(
        api,  # type: ignore[arg-type]
        session_id="sess_browser_001",
        workspace=pre_workspace,
        workspace_receipt=workspace_receipt,
        pending_approval=pending,
        started=time.monotonic(),
        pre_event_cursor=10,
    )

    assert workspace == post_workspace
    assert receipt["operation_digest"] == operation_digest
    assert receipt["driver_resolve_route_absent"] is True
    assert receipt["resolution_event_cursor"] == 11
    assert receipt["continuation_event_cursor"] == 12
    operator_output = capsys.readouterr().err
    assert '"status": "approval_required"' in operator_output
    assert '"status": "approval_observed"' in operator_output
    handoff = next(
        json.loads(line)
        for line in operator_output.splitlines()
        if '"status": "approval_required"' in line
    )
    assert handoff["sealed_page_url"] == live.BROWSER_SEALED_PAGE_URL
    assert handoff["served_ui_dist_digest"] == _digest("built-ui-dist")
    assert (
        handoff["browser_observation_receipt_schema_id"]
        == live.BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID
    )


def test_chrome_once_rejects_explicit_operator_decision(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        timeout_seconds=0.05,
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation")
    pending = {
        "approval_id": "approval_browser_001",
        "operation": {
            "operation_id": "operation_browser_001",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
        "sandbox_run": {"sandbox_run_id": "sandbox_run_browser_001"},
    }
    pre_workspace = {"pending_approvals": [pending]}
    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_001/workspace",
        semantic_value=pre_workspace,
    )
    rejected_event = {
        "cursor": 11,
        "event_id": "event_browser_rejected",
        "session_id": "sess_browser_001",
        "event_type": "approval.resolved",
        "schema_version": "openzyme.v3.event.v1",
        "visibility": "public",
        "actor_ref": "local-user",
        "command_id": "command_browser_rejected",
        "created_at": "2026-07-18T00:00:00+00:00",
        "payload": {
            "approval_id": "approval_browser_001",
            "decision": "rejected",
            "actor_ref": "local-user",
        },
    }

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_001"
            assert after_cursor == 10
            records = (rejected_event,)
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events?replay=1&after_cursor=10"
                    ),
                    semantic_value=list(records),
                )
            )
            return records

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            Api(),  # type: ignore[arg-type]
            session_id="sess_browser_001",
            workspace=pre_workspace,
            workspace_receipt=workspace_receipt,
            pending_approval=pending,
            started=time.monotonic(),
            pre_event_cursor=10,
        )

    assert error.value.code == "browser_approval_rejected"


def test_chrome_once_rejects_continuation_operation_identity_drift(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        timeout_seconds=0.01,
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation")
    pending = {
        "approval_id": "approval_browser_001",
        "operation": {
            "operation_id": "operation_browser_001",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_001",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_001",
        },
    }
    pre_workspace = {"pending_approvals": [pending]}

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_001/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))
            self.event_reads = 0

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_001"
            self.event_reads += 1
            if self.event_reads == 1:
                records: tuple[dict[str, object], ...] = ()
            else:
                records = (
                    {
                        "cursor": 1,
                        "event_id": "event_resolved",
                        "event_type": "approval.resolved",
                        "payload": {
                            "approval_id": "approval_browser_001",
                            "decision": "approved",
                            "actor_ref": "local-user",
                        },
                    },
                    {
                        "cursor": 2,
                        "event_id": "event_continuation",
                        "event_type": "sdk_controlled_operation.approval_resolved",
                        "payload": {
                            "approval_id": "approval_browser_001",
                            "operation_id": "operation_browser_001",
                            "operation_digest": _digest("drift"),
                            "continuation_id": "continuation_browser_001",
                            "decision": "approved",
                        },
                    },
                )
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_001/events"
                        f"?replay=1&after_cursor={after_cursor}"
                    ),
                    semantic_value=list(records),
                )
            )
            return records

    api = Api()
    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            api,  # type: ignore[arg-type]
            session_id="sess_browser_001",
            workspace=pre_workspace,
            workspace_receipt=workspace_receipt,
            pending_approval=pending,
            started=time.monotonic(),
            pre_event_cursor=0,
        )

    assert error.value.code == "browser_approval_operation_identity_drift"


def test_chrome_once_uses_independent_handoff_timeout(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        timeout_seconds=60.0,
        browser_approval_timeout_seconds=0.005,
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
    )
    operation_digest = _digest("browser-operation-timeout")
    pending = {
        "approval_id": "approval_browser_timeout",
        "operation": {
            "operation_id": "operation_browser_timeout",
            "operation_digest": operation_digest,
            "sandbox_workspace_id": "sandbox_workspace_browser_timeout",
        },
        "sandbox_run": {
            "sandbox_run_id": "sandbox_run_browser_timeout",
        },
    }
    pre_workspace = {"pending_approvals": [pending]}

    workspace_receipt = _public_receipt(
        sequence=1,
        route="/v3/sessions/sess_browser_timeout/workspace",
        semantic_value=pre_workspace,
    )

    class Api(_ReceiptAwareFake):
        base_url = "http://127.0.0.1:54321"
        response_binding = staticmethod(live._PublicHostClient.response_binding)

        def __init__(self) -> None:
            super().__init__((workspace_receipt,))

        def get_event_records(
            self,
            session_id: str,
            *,
            after_cursor: int = 0,
            _timeout_seconds: float | None = None,
        ) -> tuple[dict[str, object], ...]:
            del _timeout_seconds
            assert session_id == "sess_browser_timeout"
            assert after_cursor == 7
            self._append_receipt(
                _public_receipt(
                    sequence=len(self.receipts) + 1,
                    route=(
                        "/v3/sessions/sess_browser_timeout/events"
                        "?replay=1&after_cursor=7"
                    ),
                    semantic_value=[],
                )
            )
            return ()

    api = Api()
    started = time.monotonic()
    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_approval(
            api,  # type: ignore[arg-type]
            session_id="sess_browser_timeout",
            workspace=pre_workspace,
            workspace_receipt=workspace_receipt,
            pending_approval=pending,
            started=started,
            pre_event_cursor=7,
        )

    assert error.value.code == "browser_approval_timeout"
    assert time.monotonic() - started < 1.0


def test_chrome_once_gate_is_scoped_to_positive_one(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
        approval_mode="chrome-once",
        browser_completion_hold_seconds=0.0,
    )
    campaign_root = tmp_path / "campaign"
    contexts = []
    for attempt_number, attempt_kind in (
        (1, "positive"),
        (2, "positive"),
        (3, "fault"),
    ):
        roots = create_blank_world_roots(
            campaign_root,
            attempt_kind=attempt_kind,
            allowed_prerequisites=_allowed_prerequisites(),
        )
        contexts.append(
            AttemptRunContext(
                roots=roots,
                identity=_identity(),
                ledger_before=safe_micu_ledger_snapshot(ledger_path),
                attempt_number=attempt_number,
                attempt_authority=_attempt_authority(roots),
            )
        )

    assert [runner._browser_gate_enabled(context) for context in contexts] == [
        True,
        False,
        False,
    ]
    assert runner._settings_blocker(contexts[0]) == {
        "code": "browser_observation_receipt_path_missing",
        "message": "chrome-once requires a fresh observation receipt target before campaign start",
    }

    receipt_path = tmp_path / "browser-observation.json"
    receipt_path.write_text("{}", encoding="utf-8")
    runner.browser_observation_receipt_path = receipt_path
    assert runner._settings_blocker(contexts[0]) == {
        "code": "browser_observation_receipt_path_invalid",
        "message": "Chrome observation target must be absent under an existing writable non-symlink directory",
    }
    assert all(
        (runner._settings_blocker(context) or {}).get("code")
        != "browser_observation_receipt_path_invalid"
        for context in contexts[1:]
    )


def test_chrome_observation_rejects_receipt_written_before_hold_end(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    receipt_path.write_text("{}", encoding="utf-8")
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.05,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-operation")
    approval = {
        "approval_id": "approval_observation_001",
        "operation_id": "operation_observation_001",
        "operation_digest": operation_digest,
    }
    formal = live.SessionDriveResult(
        session_id="sess_observation_001",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [{"report_id": "report_observation_001", "status": "published"}],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_001",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=("approval_observation_001",),
        browser_approval_receipt=approval,
    )
    ready_started = time.monotonic()

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_observation(
            formal,
            observation_ready_started=ready_started,
            observation_ready_wall_ns=time.time_ns(),
        )

    assert error.value.code == "browser_observation_receipt_too_early"


def test_positive_blocker_preserves_formal_failure_before_browser_gate(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(ledger_path),
        ledger_path=ledger_path,
    )
    provider = SQLiteRepositoryProvider(str(tmp_path / "blank.sqlite3"))
    failed_formal = live.SessionDriveResult(
        session_id="sess_formal_failed",
        purpose="formal",
        state="failed",
        blocker_code="workflow_ref_not_authorized",
        workspace={},
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=(),
    )

    assert runner._positive_blocker(
        provider,
        failed_formal,
        browser_gate_required=True,
    ) == {
        "code": "workflow_ref_not_authorized",
        "message": "formal product path did not reach its complete accepted state",
    }

    completed_without_browser = replace(
        failed_formal,
        state="completed",
        blocker_code=None,
    )
    assert runner._positive_blocker(
        provider,
        completed_without_browser,
        browser_gate_required=True,
    ) == {
        "code": "browser_approval_not_observed",
        "message": (
            "first positive formal path did not preserve a Chrome-observed "
            "same-operation approval receipt"
        ),
    }


def test_failed_probe_payload_separates_execution_from_attestation() -> None:
    completed_probe = live.SessionDriveResult(
        session_id="sess_probe_attestation",
        purpose="probe",
        state="completed",
        blocker_code=None,
        workspace={},
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=(),
    )

    completed = live._failed_probe_payload(completed_probe)
    not_started = live._failed_probe_payload(None)

    assert completed["status"] == "failed"
    assert completed["attestation_status"] == "failed"
    assert {check["status"] for check in completed["checks"]} == {"passed"}
    assert {check["attestation_status"] for check in completed["checks"]} == {
        "unavailable"
    }
    assert not_started["attestation_status"] == "not_attempted"
    assert {check["status"] for check in not_started["checks"]} == {"unobserved"}


def _primary_pubmed_fixture(
    *,
    evidence_refs: list[str],
    researcher_lane_id: str | None = None,
    primary_lane_id: str | None = None,
) -> tuple[
    tuple[object, ...],
    dict[str, object],
    dict[str, SessionArtifactRecord],
    list[dict[str, object]],
    dict[str, str],
]:
    task_id = "task_researcher"
    primary_id = "art_pubmed_primary"
    exploratory_id = "art_pubmed_exploratory"
    artifacts = {
        primary_id: SessionArtifactRecord(
            artifact_id=primary_id,
            session_id="session_pubmed_selection",
            task_id=task_id,
            lane_id=primary_lane_id,
            invocation_id="inv_pubmed_primary",
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri="/sealed/pubmed-primary.json",
            relative_path="pubmed-primary.json",
            created_at="2026-07-18T00:00:00+00:00",
            metadata={
                "provider": "pubmed",
                "schema_version": "provider_literature_evidence@1",
                "provider_outcome": "completed",
                "cutover_eligible": True,
            },
        ),
        exploratory_id: SessionArtifactRecord(
            artifact_id=exploratory_id,
            session_id="session_pubmed_selection",
            task_id=task_id,
            lane_id=researcher_lane_id,
            invocation_id="inv_pubmed_exploratory",
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri="/sealed/pubmed-exploratory.json",
            relative_path="pubmed-exploratory.json",
            created_at="2026-07-18T00:00:01+00:00",
            metadata={
                "provider": "pubmed",
                "schema_version": "provider_literature_evidence@1",
                "provider_outcome": "completed",
                "cutover_eligible": True,
            },
        ),
    }
    invocations = {
        "inv_pubmed_primary": SimpleNamespace(
            invocation_id="inv_pubmed_primary",
            engine_name="research_tool",
            status=SimpleNamespace(value="succeeded"),
            task_id=task_id,
            lane_id=primary_lane_id,
            input_ref="doc_pubmed_primary_input",
            output_ref="doc_pubmed_primary_output",
        ),
        "inv_pubmed_exploratory": SimpleNamespace(
            invocation_id="inv_pubmed_exploratory",
            engine_name="research_tool",
            status=SimpleNamespace(value="succeeded"),
            task_id=task_id,
            lane_id=researcher_lane_id,
            input_ref="doc_pubmed_exploratory_input",
            output_ref="doc_pubmed_exploratory_output",
        ),
    }
    sources = (
        SimpleNamespace(
            provider="pubmed",
            pmid="30530468",
            evidence_artifact_id=primary_id,
            invocation_id="inv_pubmed_primary",
            task_id=task_id,
            lane_id=primary_lane_id,
        ),
        SimpleNamespace(
            provider="pubmed",
            pmid="12345678",
            evidence_artifact_id=exploratory_id,
            invocation_id="inv_pubmed_exploratory",
            task_id=task_id,
            lane_id=researcher_lane_id,
        ),
    )
    task_receipts = [
        {
            "task_id": task_id,
            "role": "researcher",
            "lane_id": researcher_lane_id,
            "evidence_refs": evidence_refs,
        }
    ]
    return sources, invocations, artifacts, task_receipts, {"researcher": task_id}


def test_primary_pubmed_selection_allows_iterative_history_and_nullable_lane() -> None:
    fixture = _primary_pubmed_fixture(
        evidence_refs=["artifact:art_pubmed_primary"],
    )

    selected = live._select_primary_pubmed_evidence(
        sources=fixture[0],
        invocations=fixture[1],
        artifacts=fixture[2],
        task_receipts=fixture[3],
        task_ids_by_role=fixture[4],
    )

    assert selected.artifact.artifact_id == "art_pubmed_primary"
    assert selected.invocation.invocation_id == "inv_pubmed_primary"
    assert [source.pmid for source in selected.sources] == ["30530468"]
    assert selected.researcher_task["lane_id"] is None


@pytest.mark.parametrize(
    ("evidence_refs", "error_code"),
    [
        ([], "pubmed_primary_receipt_missing"),
        (
            [
                "artifact:art_pubmed_primary",
                "artifact:art_pubmed_exploratory",
            ],
            "pubmed_primary_receipt_ambiguous",
        ),
    ],
)
def test_primary_pubmed_selection_fails_closed_on_adoption_cardinality(
    evidence_refs: list[str],
    error_code: str,
) -> None:
    fixture = _primary_pubmed_fixture(evidence_refs=evidence_refs)

    with pytest.raises(live.LiveProductPathError) as error:
        live._select_primary_pubmed_evidence(
            sources=fixture[0],
            invocations=fixture[1],
            artifacts=fixture[2],
            task_receipts=fixture[3],
            task_ids_by_role=fixture[4],
        )

    assert error.value.code == error_code


def test_primary_pubmed_selection_rejects_lane_mismatch() -> None:
    fixture = _primary_pubmed_fixture(
        evidence_refs=["artifact:art_pubmed_primary"],
        researcher_lane_id=None,
        primary_lane_id="lane_unbound_to_researcher",
    )

    with pytest.raises(live.LiveProductPathError) as error:
        live._select_primary_pubmed_evidence(
            sources=fixture[0],
            invocations=fixture[1],
            artifacts=fixture[2],
            task_receipts=fixture[3],
            task_ids_by_role=fixture[4],
        )

    assert error.value.code == "pubmed_primary_receipt_invalid"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("failed_artifact", "pubmed_primary_receipt_invalid"),
        ("nonnumeric_pmid", "pubmed_primary_lineage_mismatch"),
        ("source_invocation", "pubmed_primary_lineage_mismatch"),
    ],
)
def test_primary_pubmed_selection_rejects_invalid_selected_receipt(
    mutation: str,
    error_code: str,
) -> None:
    fixture = _primary_pubmed_fixture(
        evidence_refs=["artifact:art_pubmed_primary"],
    )
    if mutation == "failed_artifact":
        metadata = fixture[2]["art_pubmed_primary"].metadata
        assert metadata is not None
        metadata["provider_outcome"] = "failed"
        metadata["cutover_eligible"] = False
    elif mutation == "nonnumeric_pmid":
        fixture[0][0].pmid = "PMID:30530468"
    else:
        fixture[0][0].invocation_id = "inv_pubmed_exploratory"

    with pytest.raises(live.LiveProductPathError) as error:
        live._select_primary_pubmed_evidence(
            sources=fixture[0],
            invocations=fixture[1],
            artifacts=fixture[2],
            task_receipts=fixture[3],
            task_ids_by_role=fixture[4],
        )

    assert error.value.code == error_code


def test_aox_prompt_preserves_iterative_research_and_structured_primary_adoption() -> (
    None
):
    prompt = live.S15_AOX_HMM_FIXED_PROMPT

    assert "Bounded iterative PubMed searches are allowed" in prompt
    assert "exactly one succeeded PubMed evidence artifact" in prompt
    assert "including exactly one PubMed artifact:<id> in evidence_refs" in prompt
    assert "first successful" not in prompt.casefold()


def test_chrome_observation_uses_independent_submission_timeout(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.0,
        browser_observation_submission_timeout_seconds=0.005,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-timeout")
    formal = live.SessionDriveResult(
        session_id="sess_observation_timeout",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_timeout_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [
                {"report_id": "report_observation_timeout", "status": "published"}
            ],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_timeout",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={},
        event_receipt={},
        drain_count=1,
        approval_ids=("approval_observation_timeout",),
        browser_approval_receipt={
            "approval_id": "approval_observation_timeout",
            "operation_id": "operation_observation_timeout",
            "operation_digest": operation_digest,
        },
    )
    started = time.monotonic()

    with pytest.raises(live.LiveProductPathError) as error:
        runner._wait_for_browser_observation(
            formal,
            observation_ready_started=started,
            observation_ready_wall_ns=time.time_ns(),
        )

    assert error.value.code == "browser_observation_receipt_missing"
    assert time.monotonic() - started < 0.5


def test_chrome_observation_accepts_stable_post_hold_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "browser-observation.json"
    runner = live.LiveAoxAttemptRunner(
        settings=_runner_settings(tmp_path / "ledger.sqlite3"),
        ledger_path=tmp_path / "ledger.sqlite3",
        effective_config=_chrome_effective_config(),
        approval_mode="chrome-once",
        browser_poll_interval_seconds=0.001,
        browser_completion_hold_seconds=0.01,
        browser_observation_submission_timeout_seconds=1.0,
        browser_observation_receipt_path=receipt_path,
    )
    operation_digest = _digest("browser-observation-valid")
    approval = {
        "approval_id": "approval_observation_valid",
        "operation_id": "operation_observation_valid",
        "operation_digest": operation_digest,
        "observation_challenge": _digest("browser-challenge"),
        "page_url": live.BROWSER_SEALED_PAGE_URL,
        "host_process_id": os.getpid(),
        "served_ui_dist_digest": _digest("built-ui-dist"),
    }
    formal = live.SessionDriveResult(
        session_id="sess_observation_valid",
        purpose="formal",
        state="completed",
        blocker_code=None,
        workspace={
            "pending_approvals": [],
            "conversation": [
                {
                    "message_id": "msg_observation_valid_final",
                    "role": "assistant",
                    "content": "completed",
                }
            ],
            "reports": [
                {"report_id": "report_observation_valid", "status": "published"}
            ],
            "scientific_evidence": {
                "operations": [
                    {
                        "operation_id": "operation_observation_valid",
                        "operation_digest": operation_digest,
                        "status": "completed",
                    }
                ]
            },
        },
        workspace_response_binding={"sequence": 7},
        event_receipt={
            "event_stream_digest": _digest("browser-events"),
            "last_cursor": 9,
            "public_response_binding": {"sequence": 8},
        },
        drain_count=1,
        approval_ids=("approval_observation_valid",),
        browser_approval_receipt=approval,
    )
    page_target_id = "chrome-page-1"
    page_state = live._terminal_browser_page_state(formal)
    transcript = [
        {
            "sequence": sequence,
            "tool": "chrome_devtools_mcp",
            "method": method,
            "page_target_id": page_target_id,
            "request_digest": _digest(f"request-{method}"),
            "response_digest": _digest(f"response-{method}"),
        }
        for sequence, method in enumerate(
            ("list_console_messages", "evaluate_script", "take_screenshot"),
            start=1,
        )
    ]
    screenshot_base64 = _one_pixel_grayscale_png(filter_byte=0)
    screenshot_bytes = base64.b64decode(screenshot_base64)
    command_id = "chrome-observation-valid"
    command_digest = live.canonical_digest(
        {
            "tool": "chrome_devtools_mcp",
            "command_id": command_id,
            "page_target_id": page_target_id,
            "observation_challenge": approval["observation_challenge"],
            "action": "observe_console_page_state_and_screenshot",
        }
    )
    screenshot_digest = live._sha256(screenshot_bytes)
    response_digest = live.canonical_digest(
        {
            "page_state": page_state,
            "console_entries": [],
            "application_error_count": 0,
            "devtools_transcript_digest": live.canonical_digest(transcript),
            "screenshot_digest": screenshot_digest,
        }
    )
    receipt_path.write_text(
        json.dumps(
            {
                "schema_id": live.BROWSER_OBSERVATION_RECEIPT_SCHEMA_ID,
                "observation_mode": live.BROWSER_OBSERVATION_MODE,
                "observation_challenge": approval["observation_challenge"],
                "session_id": formal.session_id,
                "approval_id": approval["approval_id"],
                "operation_id": approval["operation_id"],
                "page_url": approval["page_url"],
                "host_process_id": approval["host_process_id"],
                "served_ui_dist_digest": approval["served_ui_dist_digest"],
                "page_target_id": page_target_id,
                "observation_window_seconds": 0.01,
                "console_entries": [],
                "console_entries_digest": live.canonical_digest([]),
                "application_error_count": 0,
                "page_state": page_state,
                "page_state_digest": live.canonical_digest(page_state),
                "devtools_command_receipt": {
                    "command_id": command_id,
                    "tool": "chrome_devtools_mcp",
                    "command_digest": command_digest,
                    "response_digest": response_digest,
                    "page_target_id": page_target_id,
                },
                "devtools_transcript": transcript,
                "devtools_transcript_digest": live.canonical_digest(transcript),
                "screenshot_png_base64": screenshot_base64,
                "screenshot_digest": screenshot_digest,
                "screenshot_width": 1,
                "screenshot_height": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    receipt = runner._wait_for_browser_observation(
        formal,
        observation_ready_started=time.monotonic() - 0.02,
        observation_ready_wall_ns=(receipt_path.stat().st_mtime_ns - 20_000_000),
    )

    assert receipt["host_observation_hold_satisfied"] is True
    assert receipt["host_observation_submission_timeout_seconds"] == 1.0
    assert receipt["screenshot_digest"] == screenshot_digest


@pytest.mark.parametrize(
    ("filter_byte", "trailing_zlib_bytes", "valid"),
    ((0, b"", True), (5, b"", False), (0, b"trailing", False)),
)
def test_browser_png_validation_is_decodable_and_bounded(
    filter_byte: int,
    trailing_zlib_bytes: bytes,
    valid: bool,
) -> None:
    encoded = _one_pixel_grayscale_png(
        filter_byte=filter_byte,
        trailing_zlib_bytes=trailing_zlib_bytes,
    )

    assert (live._browser_screenshot_png(encoded) is not None) is valid
    assert (cutover_evidence._validated_browser_png(encoded) is not None) is valid


def test_cli_exposes_chrome_once_mode(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "run-live",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
            "--attempt-authority-plan",
            str(tmp_path / "attempt-authority-plan.json"),
            "--attempt-authority-consumption",
            str(tmp_path / "attempt-authority-plan.json.consumed.json"),
            "--approval-mode",
            "chrome-once",
            "--browser-completion-hold-seconds",
            "0",
            "--browser-approval-timeout-seconds",
            "12",
        ]
    )

    assert args.approval_mode == "chrome-once"
    assert args.browser_completion_hold_seconds == 0.0
    assert args.browser_approval_timeout_seconds == 12.0
