from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
from typing import Any, Literal

from fastapi.testclient import TestClient
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import build_conversation_projection
from openzyme_core import sandbox_image_record
from openzyme_core.sandbox_workspace import DEFAULT_SANDBOX_IMAGE_REF
from openzyme_domain import ControlledOperation
from openzyme_domain import SessionArtifactRecord
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import OpenZymeSettings

from .aox_cutover_evidence import AttemptRunContext
from .aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import controlled_operation_digest
from .aox_cutover_evidence import sandbox_calculation_digest
from .app import HostApiDependencies
from .app import create_app
from .evals import S15_AOX_HMM_FIXED_DELIVERABLES
from .evals import S15_AOX_HMM_FIXED_PROMPT
from .evals import _s15_aox_validate_final_artifacts
from .foundation import build_configured_foundation


LIVE_RUNNER_SCHEMA_ID = "aox_blank_world_live_runner@1"
LIVE_BLOCKER_SCHEMA_ID = "aox_blank_world_live_blocker@1"
KNOWN_POSITIVE_PROBE_ID = "independent_globin_provider_hpc_probe"
KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS = ("NP_000509.1", "NP_000549.1")
KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS = ("P68871", "P69905")
_KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS = frozenset(
    {
        ("bio", "ncbi_fetch_proteins"),
        ("bio", "uniprot_fetch"),
        ("bio_tools", "mafft"),
        ("bio_tools", "hmmbuild"),
        ("bio_tools", "cdhit"),
        ("bio_tools", "hmmalign"),
    }
)
S12_OPERATION_IDENTITY_SCHEMA = "openzyme_controlled_operation_s12@1"
SANDBOX_CALCULATION_IDENTITY_SCHEMA = "openzyme_sandbox_calculation_receipt@1"
HMMER_SCORE_FILTERED_ACCESSIONS_PATH = (
    "aox_hmm/hmmer_score_filtered_accessions.csv"
)
AOX_CANDIDATE_FILTER_ID = "aox_motif_candidate_filter@1"
AOX_CANDIDATE_FILTER_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_CANDIDATE_FILTER_ID,
        "scoring_contract_id": aox_motif.CONTRACT_ID,
        "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
)
AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID = "aox_upstream_empty_materialization@1"
AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        "input_contract_id": aox_hmmer.CONTRACT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "outputs": [
            "aox_hmm/hits_len650_700_200.csv",
            "aox_hmm/target.fasta",
        ],
    }
)
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID = "aox_reference_only_scoring_alignment@1"
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "trigger": "empty_scoring_input_targets",
        "input": "aox_hmm/AOX_scoring_input.fasta",
        "output": "aox_hmm/AOX_scoring_alignment.fasta",
    }
)
AOX_EMPTY_MEMBERSHIP_ID = "canonical_empty_cluster_membership@1"
AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_EMPTY_MEMBERSHIP_ID,
        "membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
        "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
        "output": "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    }
)
AOX_DELIVERABLE_NORMALIZATION_ID = "aox_hmm_deliverable_normalization@1"
AOX_DELIVERABLE_NORMALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_DELIVERABLE_NORMALIZATION_ID,
        "deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
    }
)

_TERMINAL_OPERATION_STATUSES = {"completed", "failed", "recovery_failed"}
_FAILED_OPERATION_STATUSES = {"failed", "recovery_failed"}
_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "blocked"}
_FAILED_TASK_STATUSES = {"failed", "cancelled", "blocked"}
_TERMINAL_SANDBOX_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class LiveProductPathError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class PublicApiReceipt:
    sequence: int
    method: str
    route: str
    status_code: int
    request_digest: str
    response_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "method": self.method,
            "route": self.route,
            "status_code": self.status_code,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
        }


@dataclass(frozen=True, slots=True)
class SessionDriveResult:
    session_id: str
    purpose: Literal["probe", "formal"]
    state: Literal["completed", "failed", "incomplete", "approval_required"]
    blocker_code: str | None
    workspace: dict[str, Any]
    event_receipt: dict[str, object]
    drain_count: int
    approval_ids: tuple[str, ...]

    def safe_summary(self) -> dict[str, object]:
        task_items = list(
            dict(self.workspace.get("task_board") or {}).get("items") or []
        )
        operations = list(
            dict(self.workspace.get("runtime_state") or {}).get("controlled_operations")
            or []
        )
        return {
            "session_id": self.session_id,
            "purpose": self.purpose,
            "state": self.state,
            "blocker_code": self.blocker_code,
            "drain_count": self.drain_count,
            "approval_count": len(self.approval_ids),
            "task_count": len(task_items),
            "projected_operation_count": len(operations),
            "workspace_digest": canonical_digest(self.workspace),
            "event_receipt": dict(self.event_receipt),
        }


@dataclass(frozen=True, slots=True)
class FaultInjectionReceipt:
    target_artifact_id: str
    target_relative_path: str
    source_operation_id: str
    terminal_failure_operation_id: str
    byte_offset: int
    before_digest: str
    after_digest: str
    failure_code: str


@dataclass(frozen=True, slots=True)
class ProbeAttestation:
    probe: dict[str, object]
    approvals: tuple[dict[str, object], ...]
    operations: tuple[dict[str, object], ...]
    artifacts: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class CatalogArtifactCopy:
    record: dict[str, object]
    content: bytes
    content_digest: str


@dataclass(frozen=True, slots=True)
class MicuAttemptReceipt:
    record_id: int
    scenario: str
    model: str

    @property
    def invocation_id(self) -> str:
        return f"micu_ledger_attempt_{self.record_id}"


class _PublicHostClient:
    """Closed public route surface used by the campaign driver.

    Repository access is deliberately absent.  Durable repositories are read by
    the collector after public commands have completed; they are never used to
    advance a session or manufacture product state.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.receipts: list[PublicApiReceipt] = []

    def get_json(self, route: str) -> dict[str, Any]:
        self._require_route("GET", route)
        response = self._client.get(route)
        self._record("GET", route, None, response.content, response.status_code)
        self._raise_for_status(route, response.status_code, response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise LiveProductPathError(
                "public_api_response_invalid",
                "Host public API returned a non-object response",
                details={"route": route, "status_code": response.status_code},
            )
        return dict(payload)

    def get_events(self, session_id: str) -> dict[str, object]:
        route = f"/v3/sessions/{session_id}/events?replay=1"
        self._require_route("GET", route)
        response = self._client.get(route)
        self._record("GET", route, None, response.content, response.status_code)
        self._raise_for_status(route, response.status_code, response)
        event_types: list[str] = []
        event_ids: list[str] = []
        cursors: list[int] = []
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_types.append(str(event.get("event_type") or ""))
            event_ids.append(str(event.get("event_id") or ""))
            if isinstance(event.get("cursor"), int):
                cursors.append(int(event["cursor"]))
        return {
            "event_stream_digest": _sha256(response.content),
            "event_count": len(event_ids),
            "event_ids_digest": canonical_digest(event_ids),
            "event_types": sorted(set(event_types)),
            "last_cursor": max(cursors, default=0),
        }

    def post_json(
        self,
        route: str,
        payload: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_route("POST", route)
        body = dict(payload)
        response = self._client.post(
            route,
            json=body,
            headers={"Idempotency-Key": idempotency_key},
        )
        self._record("POST", route, body, response.content, response.status_code)
        self._raise_for_status(route, response.status_code, response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise LiveProductPathError(
                "public_api_response_invalid",
                "Host public API returned a non-object response",
                details={"route": route, "status_code": response.status_code},
            )
        return dict(parsed)

    def _record(
        self,
        method: str,
        route: str,
        payload: Mapping[str, object] | None,
        response: bytes,
        status_code: int,
    ) -> None:
        self.receipts.append(
            PublicApiReceipt(
                sequence=len(self.receipts) + 1,
                method=method,
                route=route.split("?", 1)[0],
                status_code=status_code,
                request_digest=canonical_digest({} if payload is None else payload),
                response_digest=_sha256(response),
            )
        )

    def _raise_for_status(self, route: str, status_code: int, response: Any) -> None:
        if status_code < 400:
            return
        error_code = "host_public_api_error"
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict) and error.get("code"):
                    error_code = str(error["code"])
        except (ValueError, TypeError):
            pass
        raise LiveProductPathError(
            error_code,
            "Host public API command failed",
            details={"route": route.split("?", 1)[0], "status_code": status_code},
        )

    @staticmethod
    def _require_route(method: str, route: str) -> None:
        path = route.split("?", 1)[0]
        segments = [segment for segment in path.split("/") if segment]
        permitted = False
        if method == "GET" and path == "/v3/runtime/health":
            permitted = True
        elif method == "POST" and path == "/v3/sessions":
            permitted = True
        elif len(segments) == 4 and segments[:2] == ["v3", "sessions"]:
            permitted = method == "GET" and segments[3] in {"workspace", "events"}
            permitted = permitted or (method == "POST" and segments[3] == "messages")
        elif len(segments) == 5 and segments[:2] == ["v3", "sessions"]:
            permitted = method == "POST" and segments[3:] == ["runtime", "drain"]
        elif len(segments) == 4 and segments[:2] == ["v3", "approvals"]:
            permitted = method == "POST" and segments[3] == "resolve"
        if not permitted:
            raise LiveProductPathError(
                "noncanonical_api_route_forbidden",
                "live cutover driver attempted a noncanonical Host route",
                details={"method": method, "route": path},
            )


@dataclass(slots=True)
class LiveAoxAttemptRunner:
    settings: OpenZymeSettings
    ledger_path: Path
    approval_mode: Literal["auto", "manual"] = "auto"
    timeout_seconds: float = 1_800.0
    max_drains: int = 120
    max_signals_per_drain: int = 10
    max_steps_per_agent: int = 16

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_drains <= 0:
            raise ValueError("live attempt timeout and max_drains must be positive")
        configured_ledger = Path(
            self.settings.test.live_llm.token_ledger_path
        ).expanduser()
        if configured_ledger.resolve() != self.ledger_path.expanduser().resolve():
            raise LiveProductPathError(
                "micu_ledger_configuration_mismatch",
                "campaign ledger must be the exact ledger charged by the live LLM factory",
                details={
                    "configured_ledger_identity": canonical_digest(
                        {"path": str(configured_ledger.resolve())}
                    ),
                    "campaign_ledger_identity": canonical_digest(
                        {"path": str(self.ledger_path.expanduser().resolve())}
                    ),
                },
            )

    def __call__(self, context: AttemptRunContext) -> dict[str, Any]:
        preflight_blocker = self._settings_blocker()
        if preflight_blocker is not None:
            return self._failure_evidence(
                context,
                blocker=preflight_blocker,
                api_receipts=(),
                health={},
                probe=None,
                formal=None,
            )

        micu_record_ids_before = _micu_record_ids(self.ledger_path)
        provider = SQLiteRepositoryProvider(str(context.roots.sqlite_path))
        foundation = build_configured_foundation(
            settings=self.settings,
            token_scenario_override="aox_blank_world_cutover",
        )
        dependencies = HostApiDependencies(
            foundation=foundation,
            v3_repository_provider=provider,
            v3_background_runtime_enabled=False,
            v3_sandbox_workspace_root=context.roots.sandbox_root,
            v3_artifact_blob_root=context.roots.blob_root,
        )
        app = create_app(dependencies)
        probe: SessionDriveResult | None = None
        formal: SessionDriveResult | None = None
        fault: FaultInjectionReceipt | None = None
        health: dict[str, Any] = {}
        with TestClient(app) as raw_client:
            api = _PublicHostClient(raw_client)
            try:
                health = api.get_json("/v3/runtime/health")
                health_blocker = self._health_blocker(health)
                if health_blocker is not None:
                    return self._failure_evidence(
                        context,
                        blocker=health_blocker,
                        provider=provider,
                        api_receipts=tuple(api.receipts),
                        health=_safe_health(health),
                        probe=None,
                        formal=None,
                    )
                self._bootstrap_sandbox_runtime_identity(
                    provider,
                    health=health,
                    identity=context.identity,
                )

                probe_session_id = f"sess_probe_{context.roots.attempt_id}"
                probe = self._run_session(
                    api,
                    provider,
                    session_id=probe_session_id,
                    purpose="probe",
                    objective="Bounded AOX provider and HPC known-positive health probe.",
                    message=self._probe_prompt(context),
                    workflow_refs=(),
                    fault_enabled=False,
                )[0]
                if probe.state != "completed":
                    return self._failure_evidence(
                        context,
                        blocker={
                            "code": probe.blocker_code
                            or "known_positive_probe_incomplete",
                            "message": (
                                "independent NCBI/UniProt and four-tool globin probe "
                                "did not complete"
                            ),
                        },
                        provider=provider,
                        api_receipts=tuple(api.receipts),
                        health=_safe_health(health),
                        probe=probe,
                        formal=None,
                    )

                formal_session_id = f"sess_formal_{context.roots.attempt_id}"
                formal, fault = self._run_session(
                    api,
                    provider,
                    session_id=formal_session_id,
                    purpose="formal",
                    objective=(
                        "Run the canonical blank-world AOX/HMM product path and publish "
                        "a source-linked scientific report."
                    ),
                    message=self._formal_prompt(context),
                    workflow_refs=(context.identity["workflow_ref"],),
                    fault_enabled=context.roots.attempt_kind == "fault",
                )
                if context.roots.attempt_kind == "fault":
                    if fault is not None and formal.state == "failed":
                        return self._fault_evidence(
                            context,
                            provider=provider,
                            api_receipts=tuple(api.receipts),
                            health=_safe_health(health),
                            probe=probe,
                            formal=formal,
                            fault=fault,
                        )
                    return self._failure_evidence(
                        context,
                        blocker={
                            "code": "controlled_fault_not_observed",
                            "message": "formal path did not prove the configured artifact-digest fault",
                        },
                        provider=provider,
                        api_receipts=tuple(api.receipts),
                        health=_safe_health(health),
                        probe=probe,
                        formal=formal,
                    )
                blocker = self._positive_blocker(provider, formal)
                if blocker is not None:
                    return self._failure_evidence(
                        context,
                        blocker=blocker,
                        provider=provider,
                        api_receipts=tuple(api.receipts),
                        health=_safe_health(health),
                        probe=probe,
                        formal=formal,
                    )
                return self._positive_evidence(
                    context,
                    provider=provider,
                    api_receipts=tuple(api.receipts),
                    health=_safe_health(health),
                    probe=probe,
                    formal=formal,
                    micu_record_ids_before=micu_record_ids_before,
                )
            except LiveProductPathError as exc:
                return self._failure_evidence(
                    context,
                    blocker={"code": exc.code, "message": _safe_message(exc)},
                    provider=provider,
                    api_receipts=tuple(api.receipts),
                    health=_safe_health(health) if health else {},
                    probe=probe,
                    formal=formal,
                )

    def _run_session(
        self,
        api: _PublicHostClient,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        purpose: Literal["probe", "formal"],
        objective: str,
        message: str,
        workflow_refs: tuple[str, ...],
        fault_enabled: bool,
    ) -> tuple[SessionDriveResult, FaultInjectionReceipt | None]:
        api.post_json(
            "/v3/sessions",
            {
                "session_id": session_id,
                "project_id": "aox-blank-world-cutover",
                "objective": objective,
                "title": f"AOX blank-world {purpose}",
            },
            idempotency_key=f"{session_id}:create",
        )
        api.post_json(
            f"/v3/sessions/{session_id}/messages",
            {"message": message, "skill_keys": list(workflow_refs)},
            idempotency_key=f"{session_id}:entry-message",
        )
        started = time.monotonic()
        approval_ids: list[str] = []
        fault_receipt: FaultInjectionReceipt | None = None
        last_workspace: dict[str, Any] = {}
        for drain_number in range(1, self.max_drains + 1):
            if time.monotonic() - started > self.timeout_seconds:
                break
            api.post_json(
                f"/v3/sessions/{session_id}/runtime/drain",
                {
                    "max_signals": self.max_signals_per_drain,
                    "max_steps_per_agent": self.max_steps_per_agent,
                    "auto_enqueue_ready_tasks": False,
                },
                idempotency_key=f"{session_id}:drain:{drain_number}",
            )
            last_workspace = api.get_json(f"/v3/sessions/{session_id}/workspace")
            pending = [
                dict(item)
                for item in last_workspace.get("pending_approvals") or []
                if isinstance(item, dict)
            ]
            if pending and self.approval_mode == "manual":
                return (
                    SessionDriveResult(
                        session_id=session_id,
                        purpose=purpose,
                        state="approval_required",
                        blocker_code="manual_approval_required",
                        workspace=last_workspace,
                        event_receipt=api.get_events(session_id),
                        drain_count=drain_number,
                        approval_ids=tuple(approval_ids),
                    ),
                    fault_receipt,
                )
            for approval in pending:
                approval_id = str(approval.get("approval_id") or "")
                if not approval_id:
                    continue
                if fault_enabled and fault_receipt is None:
                    fault_receipt = self._inject_before_hpc_approval(
                        provider,
                        session_id=session_id,
                        approval_id=approval_id,
                    )
                api.post_json(
                    f"/v3/approvals/{approval_id}/resolve",
                    {"decision": "approved"},
                    idempotency_key=f"{session_id}:approve:{approval_id}",
                )
                approval_ids.append(approval_id)
            state, blocker = self._session_state(
                provider,
                session_id=session_id,
                purpose=purpose,
            )
            if state in {"completed", "failed"}:
                if fault_receipt is not None:
                    fault_receipt = self._complete_fault_receipt(
                        provider,
                        fault_receipt,
                    )
                return (
                    SessionDriveResult(
                        session_id=session_id,
                        purpose=purpose,
                        state=state,
                        blocker_code=blocker,
                        workspace=last_workspace,
                        event_receipt=api.get_events(session_id),
                        drain_count=drain_number,
                        approval_ids=tuple(approval_ids),
                    ),
                    fault_receipt,
                )
        if not last_workspace:
            last_workspace = api.get_json(f"/v3/sessions/{session_id}/workspace")
        return (
            SessionDriveResult(
                session_id=session_id,
                purpose=purpose,
                state="incomplete",
                blocker_code=f"{purpose}_runtime_drain_exhausted",
                workspace=last_workspace,
                event_receipt=api.get_events(session_id),
                drain_count=self.max_drains,
                approval_ids=tuple(approval_ids),
            ),
            fault_receipt,
        )

    def _session_state(
        self,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        purpose: Literal["probe", "formal"],
    ) -> tuple[Literal["completed", "failed", "incomplete"], str | None]:
        with provider.read() as scope:
            repositories = scope.repositories
            operations = repositories.controlled_operations.list_by_session(session_id)
            tasks = repositories.tasks.list_by_session(session_id)
            sandbox_runs = repositories.sandbox_runs.list_by_session(session_id)
            artifacts = repositories.artifacts.list_by_session(session_id)
            reports = repositories.reports.list_by_session(session_id)
            drafts = repositories.report_drafts.list_by_session(session_id)
            agents = repositories.agents.list_by_session(session_id)
            messages = build_conversation_projection(repositories, session_id)
        failed_operation = next(
            (
                operation
                for operation in operations
                if operation.status.value in _FAILED_OPERATION_STATUSES
            ),
            None,
        )
        if failed_operation is not None:
            return (
                "failed",
                failed_operation.error_code or "controlled_operation_failed",
            )
        failed_task = next(
            (task for task in tasks if task.status.value in _FAILED_TASK_STATUSES),
            None,
        )
        if failed_task is not None:
            return "failed", f"task_{failed_task.status.value}"
        failed_run = next(
            (
                run
                for run in sandbox_runs
                if run.status.value in (_TERMINAL_SANDBOX_STATUSES - {"completed"})
            ),
            None,
        )
        if failed_run is not None:
            return "failed", failed_run.error_code or "sandbox_run_failed"
        assistant_message = any(message.role == "assistant" for message in messages)
        if purpose == "probe":
            completed_functions = {
                (operation.sdk_module, operation.function_name)
                for operation in operations
                if operation.status.value == "completed"
            }
            tasks_terminal = bool(tasks) and all(
                task.status.value in _TERMINAL_TASK_STATUSES for task in tasks
            )
            if (
                _KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS
                <= completed_functions
                and tasks_terminal
                and assistant_message
            ):
                return "completed", None
            return "incomplete", None
        artifact_paths = {artifact.relative_path for artifact in artifacts}
        task_kinds = {task.kind for task in tasks if task.status.value == "completed"}
        roles = {agent.role for agent in agents}
        report_ready = any(
            report.status.value in {"ready", "published"} for report in reports
        )
        draft_published = any(draft.status.value == "published" for draft in drafts)
        if (
            S15_AOX_HMM_FIXED_DELIVERABLES <= artifact_paths
            and {"research", "execution", "reporting"} <= task_kinds
            and {"researcher", "executor", "reporter"} <= roles
            and report_ready
            and draft_published
            and assistant_message
        ):
            return "completed", None
        return "incomplete", None

    def _settings_blocker(self) -> dict[str, str] | None:
        if self.settings.host_api.deployment_profile != "local-dev":
            return {
                "code": "trusted_local_host_required",
                "message": "same-process blank-world runner requires the local trusted-Host profile",
            }
        if not self.settings.test.enable_live_e2e:
            return {
                "code": "live_e2e_not_enabled",
                "message": "OPENZYME_TEST_ENABLE_LIVE_E2E is not enabled",
            }
        if not self.settings.llm.enabled:
            return {
                "code": "live_llm_not_configured",
                "message": "a real configured LLM is required",
            }
        if self.settings.execution.backend != "hpc":
            return {
                "code": "live_hpc_not_configured",
                "message": "the canonical campaign requires execution.backend=hpc",
            }
        if not self.settings.research.pubmed_email:
            return {
                "code": "ncbi_identity_missing",
                "message": "the existing NCBI email identity is not configured",
            }
        return None

    @staticmethod
    def _health_blocker(health: Mapping[str, object]) -> dict[str, str] | None:
        if (
            health.get("schema_version") != "v3.runtime_health.v1"
            or health.get("deployment_profile") != "local-dev"
            or health.get("storage_profile") != "single_process_sqlite"
        ):
            return {
                "code": "runtime_health_invalid",
                "message": "Host runtime health identity does not match the local SQLite campaign contract",
            }
        components = health.get("components")
        if not isinstance(components, dict):
            return {
                "code": "runtime_health_invalid",
                "message": "Host runtime health projection is missing components",
            }
        required = {"model", "execution", "bio_research", "sandbox"}
        unready = sorted(
            name
            for name in required
            if not isinstance(components.get(name), dict)
            or dict(components[name]).get("status") != "ready"
        )
        if unready:
            return {
                "code": "live_runtime_component_unready",
                "message": "required Host runtime components are not ready: "
                + ", ".join(unready),
            }
        return None

    @staticmethod
    def _bootstrap_sandbox_runtime_identity(
        provider: SQLiteRepositoryProvider,
        *,
        health: Mapping[str, object],
        identity: Mapping[str, object],
    ) -> None:
        components = health.get("components")
        sandbox_component = (
            dict(components.get("sandbox") or {})
            if isinstance(components, dict)
            else {}
        )
        details = dict(sandbox_component.get("details") or {})
        actual = {
            "image_digest": str(details.get("image_digest") or ""),
            "sdk_digest": str(details.get("pipeline_sdk_digest") or ""),
        }
        if any(
            _SHA256_DIGEST_PATTERN.fullmatch(value) is None
            for value in actual.values()
        ):
            raise LiveProductPathError(
                "sandbox_runtime_identity_missing",
                "ready sandbox health lacks canonical image or Pipeline SDK identity",
            )
        expected = {
            "image_digest": str(identity.get("image_digest") or ""),
            "sdk_digest": str(identity.get("sdk_digest") or ""),
        }
        mismatched = sorted(
            key for key, value in actual.items() if expected.get(key) != value
        )
        if mismatched:
            raise LiveProductPathError(
                "campaign_sandbox_identity_mismatch",
                "campaign image or Pipeline SDK identity differs from Host preflight",
                details={"mismatched_fields": mismatched},
            )
        image_ref = (
            f"{DEFAULT_SANDBOX_IMAGE_REF.rsplit(':', maxsplit=1)[0]}@"
            f"{actual['image_digest']}"
        )
        with provider.write() as scope:
            repositories = scope.repositories
            if (
                repositories.sandbox_images.get_default() is not None
                or repositories.sandbox_images.get(DEFAULT_SANDBOX_IMAGE_REF)
                is not None
                or repositories.sandbox_images.get(image_ref) is not None
            ):
                raise LiveProductPathError(
                    "sandbox_image_registry_not_blank",
                    "blank-world SQLite unexpectedly contains a sandbox image identity",
                )
            repositories.sandbox_images.save(
                sandbox_image_record(
                    image_ref=image_ref,
                    image_digest=actual["image_digest"],
                )
            )

    def _positive_blocker(
        self,
        provider: SQLiteRepositoryProvider,
        formal: SessionDriveResult,
    ) -> dict[str, str] | None:
        if formal.state != "completed":
            return {
                "code": formal.blocker_code or "canonical_product_path_incomplete",
                "message": "formal product path did not reach its published-report exit",
            }
        with provider.read() as scope:
            repositories = scope.repositories
            pubmed_sources = [
                source
                for source in repositories.research_source_refs.list_by_session(
                    formal.session_id
                )
                if source.provider == "pubmed" and str(source.pmid or "").isdigit()
            ]
            invocation_ids = {source.invocation_id for source in pubmed_sources}
            invocations = [
                invocation
                for invocation_id in sorted(invocation_ids)
                if (invocation := repositories.invocations.get(invocation_id))
                is not None
            ]
            artifacts = {
                artifact.artifact_id: artifact
                for artifact in repositories.artifacts.list_by_session(
                    formal.session_id
                )
            }
        if not pubmed_sources:
            return {
                "code": "required_pubmed_evidence_missing",
                "message": "formal path has no persisted real PMID evidence",
            }
        if (
            len(invocation_ids) != 1
            or len(invocations) != 1
            or invocations[0].engine_name != "research_tool"
            or invocations[0].status.value != "succeeded"
            or not invocations[0].input_ref
            or not invocations[0].output_ref
            or any(
                not source.evidence_artifact_id
                or source.evidence_artifact_id not in artifacts
                for source in pubmed_sources
            )
        ):
            return {
                "code": "required_pubmed_engine_invocation_missing",
                "message": (
                    "PubMed provenance does not close through one terminal research-tool "
                    "invocation and sealed evidence artifact"
                ),
            }
        return None

    def _probe_prompt(self, context: AttemptRunContext) -> str:
        return (
            "Run only the independent bounded known-positive probe; do not create AOX "
            "candidates, formal result artifacts, or a report. Delegate exactly one execution "
            "task and use one persistent sandbox, one source snapshot, and one Host-supervised "
            "HPC workspace for exactly six controlled operations. With provider cache bypass, "
            "fetch NCBI protein accessions NP_000509.1 and NP_000549.1, then run MAFFT on that "
            "sealed FASTA and hmmbuild on the MAFFT alignment. Independently fetch UniProt "
            "accessions P68871 and P69905, run CD-HIT with identity 1.0 in protein "
            "mode on that sealed FASTA, then run HMMalign with the real hmmbuild model and the "
            "real CD-HIT clustered UniProt FASTA. Do not call any other provider or HPC tool. "
            "Use the unique HPC workspace label "
            f"{context.roots.hpc_workspace_label!r}. Explicitly finish the task and answer with "
            "the observed two provider and four HPC operation identities. Never use fixture "
            "data, copied formal data, or the AOX reference notebook."
        )

    def _formal_prompt(self, context: AttemptRunContext) -> str:
        return (
            S15_AOX_HMM_FIXED_PROMPT
            + " Use evidence-bearing provider cache bypass. Use the unique Host-supervised HPC "
            + f"workspace label {context.roots.hpc_workspace_label!r}. Do not read any prior "
            + "session, historical AOX output, notebook output, fixture, or golden expected result."
        )

    def _positive_evidence(
        self,
        context: AttemptRunContext,
        *,
        provider: SQLiteRepositoryProvider,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult,
        formal: SessionDriveResult,
        micu_record_ids_before: set[int],
    ) -> dict[str, Any]:
        return _collect_positive_evidence(
            context,
            provider=provider,
            api_receipts=api_receipts,
            health=health,
            probe=probe,
            formal=formal,
            ledger_path=self.ledger_path,
            micu_record_ids_before=micu_record_ids_before,
        )

    def _failure_evidence(
        self,
        context: AttemptRunContext,
        *,
        blocker: Mapping[str, object],
        provider: SQLiteRepositoryProvider | None = None,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult | None,
        formal: SessionDriveResult | None,
    ) -> dict[str, Any]:
        blocker_code = str(blocker.get("code") or "live_product_path_failed")
        blocker_payload = {
            "schema_id": LIVE_BLOCKER_SCHEMA_ID,
            "runner_schema_id": LIVE_RUNNER_SCHEMA_ID,
            "attempt_id": context.roots.attempt_id,
            "attempt_kind": context.roots.attempt_kind,
            "observed_at": datetime.now(UTC).isoformat(),
            "blocker": {
                "code": blocker_code,
                "message": str(blocker.get("message") or blocker_code),
            },
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "health": dict(health),
            "probe": None if probe is None else probe.safe_summary(),
            "formal": None if formal is None else formal.safe_summary(),
            "public_api_receipts": [item.to_dict() for item in api_receipts],
        }
        probe_attestation: ProbeAttestation | None = None
        if provider is not None and probe is not None and probe.state == "completed":
            try:
                probe_attestation = _collect_probe_attestation(
                    context,
                    provider=provider,
                    probe=probe,
                )
            except LiveProductPathError as exc:
                blocker_payload["probe_attestation_blocker"] = {
                    "code": exc.code,
                    "message": _safe_message(exc),
                }
        artifact_id = f"art_live_blocker_{_safe_id(context.roots.attempt_id)}"
        relative_path = "formal/live-product-path-blocker.json"
        content = canonical_json_bytes(blocker_payload) + b"\n"
        _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
        probe_payload = (
            _failed_probe_payload(probe)
            if probe_attestation is None
            else probe_attestation.probe
        )
        fault_injection = None
        failure_code = blocker_code
        if context.roots.attempt_kind == "fault":
            failure_code = "campaign_runner_failed"
            fault_injection = {
                "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "reached_target_seam": False,
                "expected_failure_observed": False,
                "failure_code": "campaign_runner_failed",
                "blocker_code": blocker_code,
            }
        return {
            "provider_identities": [],
            "engine_invocations": [],
            "toolchain_identities": [],
            "known_positive_probe": probe_payload,
            "product_path": _product_path_failure_receipt(
                context,
                formal=formal,
                api_receipts=api_receipts,
            ),
            "approvals": []
            if probe_attestation is None
            else list(probe_attestation.approvals),
            "operations": []
            if probe_attestation is None
            else list(probe_attestation.operations),
            "tasks": [],
            "artifacts": [
                *(() if probe_attestation is None else probe_attestation.artifacts),
                {
                    "artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "scope": "formal",
                    "origin": "report",
                    "kind": "failure_evidence",
                    "provenance": {
                        "producer": LIVE_RUNNER_SCHEMA_ID,
                        "blocker_code": blocker_code,
                    },
                },
            ],
            "report": {
                "report_id": f"report_failure_{_safe_id(context.roots.attempt_id)}",
                "status": "failed_evidence",
                "cutover_eligible": False,
                "content_artifact_id": artifact_id,
                "content_digest": _sha256(content),
                "artifact_ids": [artifact_id],
                "source_ref_ids": [],
                "claim_source_links": [],
            },
            "final_answer": {
                "message_id": f"msg_failure_{_safe_id(context.roots.attempt_id)}",
                "content": f"AOX blank-world attempt failed closed: {blocker_code}.",
            },
            "scientific_checks": {},
            "warnings": [],
            "degradations": [blocker_code],
            "scientific_outcome": {
                "status": "failed",
                "failure_code": failure_code,
                "blocker_code": blocker_code,
                "cutover_eligible": False,
            },
            "fault_injection": fault_injection,
        }

    def _fault_evidence(
        self,
        context: AttemptRunContext,
        *,
        provider: SQLiteRepositoryProvider,
        api_receipts: tuple[PublicApiReceipt, ...],
        health: Mapping[str, object],
        probe: SessionDriveResult,
        formal: SessionDriveResult,
        fault: FaultInjectionReceipt,
    ) -> dict[str, Any]:
        if fault.failure_code != "artifact_content_digest_mismatch":
            raise LiveProductPathError(
                "controlled_fault_failure_code_mismatch",
                "controlled byte flip did not terminate with the exact digest mismatch",
                details={"observed_failure_code": fault.failure_code},
            )
        return _collect_fault_evidence(
            context,
            provider=provider,
            api_receipts=api_receipts,
            health=health,
            probe=probe,
            formal=formal,
            fault=fault,
        )

    def _inject_before_hpc_approval(
        self,
        provider: SQLiteRepositoryProvider,
        *,
        session_id: str,
        approval_id: str,
    ) -> FaultInjectionReceipt | None:
        with provider.read() as scope:
            repositories = scope.repositories
            operation = repositories.controlled_operations.get_by_approval_id(
                approval_id
            )
            if (
                operation is None
                or operation.session_id != session_id
                or operation.selected_backend != "hpc"
                or not operation.input_artifact_ids
            ):
                return None
            operations = repositories.controlled_operations.list_by_session(session_id)
            artifacts = {
                artifact.artifact_id: artifact
                for artifact in repositories.artifacts.list_by_session(session_id)
            }
        source_operation: ControlledOperation | None = None
        target: SessionArtifactRecord | None = None
        for artifact_id in operation.input_artifact_ids:
            candidate = artifacts.get(artifact_id)
            if candidate is None:
                continue
            producer = next(
                (
                    item
                    for item in operations
                    if item.selected_backend == "provider_http"
                    and artifact_id in _operation_output_artifact_ids(item)
                    and item.status.value == "completed"
                ),
                None,
            )
            if producer is not None:
                source_operation = producer
                target = candidate
                break
        if source_operation is None or target is None:
            return None
        path = Path(target.storage_uri)
        if not path.is_file() or path.is_symlink():
            return None
        content = path.read_bytes()
        if not content:
            return None
        before_digest = _sha256(content)
        byte_offset = min(4, len(content) - 1)
        mutated = bytearray(content)
        mutated[byte_offset] ^= 1
        path.chmod(0o600)
        try:
            path.write_bytes(bytes(mutated))
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        finally:
            path.chmod(0o444)
        return FaultInjectionReceipt(
            target_artifact_id=target.artifact_id,
            target_relative_path=target.relative_path,
            source_operation_id=source_operation.operation_id,
            terminal_failure_operation_id=operation.operation_id,
            byte_offset=byte_offset,
            before_digest=before_digest,
            after_digest=_sha256(bytes(mutated)),
            failure_code="pending",
        )

    @staticmethod
    def _complete_fault_receipt(
        provider: SQLiteRepositoryProvider,
        receipt: FaultInjectionReceipt,
    ) -> FaultInjectionReceipt:
        with provider.read() as scope:
            operation = scope.repositories.controlled_operations.get(
                receipt.terminal_failure_operation_id
            )
        return FaultInjectionReceipt(
            target_artifact_id=receipt.target_artifact_id,
            target_relative_path=receipt.target_relative_path,
            source_operation_id=receipt.source_operation_id,
            terminal_failure_operation_id=receipt.terminal_failure_operation_id,
            byte_offset=receipt.byte_offset,
            before_digest=receipt.before_digest,
            after_digest=receipt.after_digest,
            failure_code=(
                "operation_missing"
                if operation is None
                else str(operation.error_code or operation.status.value)
            ),
        )


def controlled_operation_identity_material(
    operation: ControlledOperation,
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": operation.adapter_envelope_schema_version,
        "sandbox_workspace_id": operation.sandbox_workspace_id,
        "source_snapshot_digest": operation.source_snapshot_digest,
        "sdk_module": operation.sdk_module,
        "function_name": operation.function_name,
        "params_digest": operation.params_digest,
        "input_artifact_ids": list(operation.input_artifact_ids),
        "input_artifact_digests": list(operation.input_artifact_digests),
        "placement": operation.placement,
        "hpc_workspace_id": operation.hpc_workspace_id,
        "stage_refs": [dict(item) for item in operation.stage_refs],
        "selected_backend": operation.selected_backend,
        "route_reason": operation.route_reason,
        "route_policy_id": operation.route_policy_id,
        "runtime_packaging_id": operation.runtime_packaging_id,
        "toolchain_id": operation.toolchain_id,
        "provider_config_digest": operation.provider_config_digest,
        "resource_class": operation.resource_class,
        "resource_estimate": dict(operation.resource_estimate or {}),
        "expected_outputs": dict(operation.expected_outputs_summary or {}),
        "planned_fetch_intent": dict(operation.planned_fetch_intent or {}),
        "approval_requirement": dict(operation.approval_requirement or {}),
    }
    actual = controlled_operation_digest(material)
    if actual != operation.operation_digest:
        raise LiveProductPathError(
            "controlled_operation_digest_mismatch",
            "durable operation fields do not reproduce the approval-bound S12 digest",
            details={"operation_id": operation.operation_id},
        )
    return material


def operation_evidence_record(
    operation: ControlledOperation,
    *,
    scope: Literal["probe", "formal"],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, str]],
    parameters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    material = controlled_operation_identity_material(operation)
    if [item["artifact_id"] for item in inputs] != list(
        operation.input_artifact_ids
    ) or [item["content_digest"] for item in inputs] != list(
        operation.input_artifact_digests
    ):
        raise LiveProductPathError(
            "controlled_operation_input_projection_mismatch",
            "evidence inputs differ from the approval-bound S12 operation",
            details={"operation_id": operation.operation_id},
        )
    result = dict(operation.adapter_result_envelope or {})
    record: dict[str, object] = {
        "operation_id": operation.operation_id,
        "session_id": operation.session_id,
        "task_id": operation.task_id,
        "sandbox_run_id": operation.sandbox_run_id,
        "source_snapshot_artifact_id": operation.source_snapshot_artifact_id,
        "hpc_workspace_id": operation.hpc_workspace_id,
        "canonical_ref_kind": "controlled_operation",
        "kind": f"{operation.sdk_module}.{operation.function_name}",
        "scope": scope,
        "status": operation.status.value,
        "terminal": operation.status.value in _TERMINAL_OPERATION_STATUSES,
        "failure_code": operation.error_code,
        "operation_identity_schema": S12_OPERATION_IDENTITY_SCHEMA,
        "operation_identity_material": material,
        "operation_identity_digest": operation.operation_digest,
        "params_digest": operation.params_digest,
        "source_snapshot_digest": operation.source_snapshot_digest,
        "route_policy_id": operation.route_policy_id,
        "selected_backend": operation.selected_backend,
        "backend_run_id": result.get("provider_request_id")
        or result.get("backend_run_id"),
        "inputs": [dict(item) for item in inputs],
        "outputs": [dict(item) for item in outputs],
    }
    if parameters is not None:
        normalized_parameters = dict(parameters)
        if canonical_digest(normalized_parameters) != operation.params_digest:
            raise LiveProductPathError(
                "controlled_operation_params_digest_mismatch",
                "sealed provider request parameters do not reproduce params_digest",
                details={"operation_id": operation.operation_id},
            )
        record["parameters"] = normalized_parameters
    return record


def _operation_output_artifact_ids(operation: ControlledOperation) -> tuple[str, ...]:
    envelope = dict(operation.adapter_result_envelope or {})
    summary = dict(operation.result_summary or {})
    values: list[str] = []
    for source in (envelope, summary):
        for key in ("output_artifact_ids", "registered_artifact_ids"):
            for value in source.get(key) or []:
                text = str(value)
                if text and text not in values:
                    values.append(text)
    return tuple(values)


def _micu_record_ids(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id FROM live_micu_token_attempts ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise LiveProductPathError(
            "micu_ledger_schema_unavailable",
            "persistent MICU ledger does not expose attempt receipts",
        ) from exc
    finally:
        connection.close()
    return {int(row[0]) for row in rows}


def _new_micu_attempt_receipts(
    path: Path,
    *,
    before_ids: set[int],
) -> tuple[MicuAttemptReceipt, ...]:
    if not path.is_file():
        raise LiveProductPathError(
            "micu_attempt_receipt_missing",
            "positive live execution did not create the persistent MICU ledger",
        )
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, scenario, model, status
            FROM live_micu_token_attempts
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    terminal_statuses = {
        "succeeded",
        "succeeded_overage",
        "succeeded_limit_breached",
        "succeeded_estimated",
        "failed_estimated",
    }
    new_rows = [row for row in rows if int(row["id"]) not in before_ids]
    if not new_rows:
        raise LiveProductPathError(
            "micu_attempt_receipt_missing",
            "positive live execution has no newly charged MICU attempt",
        )
    scenarios = {str(row["scenario"] or "") for row in new_rows}
    models = {str(row["model"] or "") for row in new_rows}
    invalid_statuses = sorted(
        str(row["status"] or "")
        for row in new_rows
        if str(row["status"] or "") not in terminal_statuses
    )
    if scenarios != {"aox_blank_world_cutover"} or len(models) != 1 or "" in models:
        raise LiveProductPathError(
            "micu_attempt_attribution_mismatch",
            "new MICU ledger rows are not exclusively bound to the AOX campaign",
            details={"scenarios": sorted(scenarios), "models": sorted(models)},
        )
    if invalid_statuses:
        raise LiveProductPathError(
            "micu_attempt_not_terminal",
            "new MICU attempt rows have not reached a terminal ledger status",
            details={"statuses": invalid_statuses},
        )
    return tuple(
        MicuAttemptReceipt(
            record_id=int(row["id"]),
            scenario=str(row["scenario"]),
            model=str(row["model"]),
        )
        for row in new_rows
    )


def _artifact_bytes(
    context: AttemptRunContext,
    artifact: SessionArtifactRecord,
) -> bytes:
    source = Path(artifact.storage_uri)
    if not source.is_file() or source.is_symlink():
        raise LiveProductPathError(
            "catalog_artifact_blob_invalid",
            "cutover evidence requires a sealed regular-file catalog artifact",
            details={"artifact_id": artifact.artifact_id},
        )
    resolved_source = source.resolve()
    resolved_blob_root = context.roots.blob_root.resolve()
    if resolved_blob_root not in resolved_source.parents:
        raise LiveProductPathError(
            "catalog_artifact_blob_unbound",
            "catalog artifact is outside the attempt-scoped immutable blob root",
            details={"artifact_id": artifact.artifact_id},
        )
    content = source.read_bytes()
    metadata = dict(artifact.metadata or {})
    expected = str(
        metadata.get("content_digest") or metadata.get("sealed_digest") or ""
    )
    actual = _sha256(content)
    if expected != actual:
        raise LiveProductPathError(
            "catalog_artifact_digest_mismatch",
            "catalog artifact bytes differ from their immutable metadata digest",
            details={"artifact_id": artifact.artifact_id},
        )
    return content


def _copy_catalog_artifact(
    context: AttemptRunContext,
    artifact: SessionArtifactRecord,
    *,
    scope: Literal["probe", "formal"],
    origin: str,
    provenance: Mapping[str, object],
    cache: dict[str, CatalogArtifactCopy],
) -> CatalogArtifactCopy:
    existing = cache.get(artifact.artifact_id)
    if existing is not None:
        if (
            existing.record.get("scope") != scope
            or existing.record.get("origin") != origin
        ):
            raise LiveProductPathError(
                "catalog_artifact_owner_ambiguous",
                "one catalog artifact cannot be assigned two canonical evidence owners",
                details={"artifact_id": artifact.artifact_id},
            )
        return existing
    content = _artifact_bytes(context, artifact)
    safe_name = _safe_id(PurePosixPath(artifact.relative_path).name)
    relative_path = f"{scope}/catalog/{_safe_id(artifact.artifact_id)}/{safe_name}"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    copied = CatalogArtifactCopy(
        record={
            "artifact_id": artifact.artifact_id,
            "relative_path": relative_path,
            "scope": scope,
            "origin": origin,
            "kind": artifact.kind.value,
            "provenance": {
                **dict(provenance),
                "catalog_artifact_id": artifact.artifact_id,
                "catalog_relative_path": artifact.relative_path,
            },
        },
        content=content,
        content_digest=_sha256(content),
    )
    cache[artifact.artifact_id] = copied
    return copied


def _require_artifact(
    artifacts: Mapping[str, SessionArtifactRecord],
    artifact_id: str,
) -> SessionArtifactRecord:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise LiveProductPathError(
            "catalog_artifact_record_missing",
            "operation references an artifact absent from its durable session catalog",
            details={"artifact_id": artifact_id},
        )
    return artifact


def _artifact_ref(copy: CatalogArtifactCopy) -> dict[str, str]:
    return {
        "artifact_id": str(copy.record["artifact_id"]),
        "content_digest": copy.content_digest,
    }


def _declared_operation_input_refs(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for artifact_id, declared_digest in zip(
        operation.input_artifact_ids,
        operation.input_artifact_digests,
        strict=True,
    ):
        artifact = _require_artifact(artifacts, artifact_id)
        copy = _copy_catalog_artifact(
            context,
            artifact,
            scope=scope,
            origin="operation",
            provenance={"operation_input_for": operation.operation_id},
            cache=copies,
        )
        if copy.content_digest != declared_digest:
            raise LiveProductPathError(
                "controlled_operation_input_digest_mismatch",
                "catalog bytes differ from the approval-bound controlled-operation input",
                details={
                    "operation_id": operation.operation_id,
                    "artifact_id": artifact_id,
                },
            )
        refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
    return refs


def _provider_request_parameters(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
) -> dict[str, object]:
    request_artifacts = [
        artifacts[artifact_id]
        for artifact_id in _operation_output_artifact_ids(operation)
        if artifact_id in artifacts
        and PurePosixPath(artifacts[artifact_id].relative_path).name
        == "provider_request.json"
    ]
    if len(request_artifacts) != 1:
        raise LiveProductPathError(
            "provider_request_artifact_ambiguous",
            "controlled provider operation must have one sealed provider_request.json",
            details={"operation_id": operation.operation_id},
        )
    try:
        payload = json.loads(_artifact_bytes(context, request_artifacts[0]))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveProductPathError(
            "provider_request_artifact_invalid",
            "sealed provider request artifact is not valid JSON",
            details={"operation_id": operation.operation_id},
        ) from exc
    params = payload.get("params") if isinstance(payload, dict) else None
    if (
        not isinstance(params, dict)
        or canonical_digest(params) != operation.params_digest
    ):
        raise LiveProductPathError(
            "provider_request_params_digest_mismatch",
            "sealed provider request parameters do not reproduce the S12 params digest",
            details={"operation_id": operation.operation_id},
        )
    return dict(params)


def _raw_provider_response_digests(content: bytes) -> tuple[str, ...]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_id") != "provider_raw_http_response_set@1"
        or not isinstance(payload.get("responses"), list)
    ):
        return ()
    digests: list[str] = []
    for raw_record in payload["responses"]:
        if not isinstance(raw_record, dict):
            return ()
        try:
            raw = base64.b64decode(
                str(raw_record.get("body_base64") or ""),
                validate=True,
            )
        except ValueError:
            return ()
        digest = _sha256(raw)
        if (
            raw_record.get("body_encoding") != "base64"
            or raw_record.get("size_bytes") != len(raw)
            or raw_record.get("body_digest") != digest
        ):
            return ()
        digests.append(digest)
    return tuple(digests)


def _provider_output_copies(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> tuple[list[CatalogArtifactCopy], str]:
    selected: list[CatalogArtifactCopy] = []
    raw_response_digests: list[str] = []
    for artifact_id in _operation_output_artifact_ids(operation):
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            continue
        name = PurePosixPath(artifact.relative_path).name
        if name in {"provider_request.json", "provider_observation.json"}:
            continue
        copy = _copy_catalog_artifact(
            context,
            artifact,
            scope=scope,
            origin="operation",
            provenance={
                "operation_id": operation.operation_id,
                "provider": operation.function_name,
            },
            cache=copies,
        )
        selected.append(copy)
        raw_response_digests.extend(_raw_provider_response_digests(copy.content))
    if not selected or not raw_response_digests:
        raise LiveProductPathError(
            "provider_response_artifact_missing",
            "provider operation lacks a sealed raw HTTP response receipt",
            details={"operation_id": operation.operation_id},
        )
    return selected, raw_response_digests[-1]


def _tool_output_copies(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
    scope: Literal["probe", "formal"] = "formal",
) -> list[CatalogArtifactCopy]:
    selected = [
        _copy_catalog_artifact(
            context,
            _require_artifact(artifacts, artifact_id),
            scope=scope,
            origin="operation",
            provenance={
                "operation_id": operation.operation_id,
                "tool": operation.function_name,
            },
            cache=copies,
        )
        for artifact_id in _operation_output_artifact_ids(operation)
    ]
    if not selected:
        raise LiveProductPathError(
            "toolchain_output_artifact_missing",
            "completed HPC operation has no sealed declared output",
            details={"operation_id": operation.operation_id},
        )
    return selected


def _approval_record(
    operation: ControlledOperation,
    approvals: Mapping[str, object],
) -> dict[str, object]:
    approval = approvals.get(str(operation.approval_id or ""))
    if (
        approval is None
        or getattr(getattr(approval, "status", None), "value", None) != "approved"
        or getattr(approval, "request_ref", None) != operation.operation_id
    ):
        raise LiveProductPathError(
            "controlled_operation_approval_missing",
            "controlled operation lacks its exact durable approved request",
            details={"operation_id": operation.operation_id},
        )
    return {
        "approval_id": str(operation.approval_id),
        "operation_id": operation.operation_id,
        "operation_identity_digest": operation.operation_digest,
        "decision": "approved",
    }


def _sandbox_calculation_record(
    *,
    run: object,
    role: str,
    calculation_id: str,
    calculation_contract_digest: str,
    calculation_implementation_digest: str,
    parameters: Mapping[str, object],
    inputs: list[dict[str, str]],
    outputs: list[dict[str, str]],
) -> dict[str, object]:
    params = dict(parameters)
    params_digest = canonical_digest(params)
    sandbox_run_id = str(getattr(run, "sandbox_run_id"))
    source_snapshot_artifact_id = str(getattr(run, "source_snapshot_artifact_id") or "")
    source_snapshot_digest = str(getattr(run, "source_tree_digest") or "")
    workspace_id = str(getattr(run, "sandbox_workspace_id") or "")
    if (
        not source_snapshot_artifact_id
        or not source_snapshot_digest
        or not workspace_id
    ):
        raise LiveProductPathError(
            "sandbox_calculation_source_snapshot_missing",
            "sandbox calculation is not bound to its source snapshot",
            details={"sandbox_run_id": sandbox_run_id},
        )
    material = {
        "schema_version": SANDBOX_CALCULATION_IDENTITY_SCHEMA,
        "sandbox_run_id": sandbox_run_id,
        "sandbox_workspace_id": workspace_id,
        "source_snapshot_artifact_id": source_snapshot_artifact_id,
        "source_snapshot_digest": source_snapshot_digest,
        "calculation_id": calculation_id,
        "calculation_contract_digest": calculation_contract_digest,
        "calculation_implementation_digest": calculation_implementation_digest,
        "params_digest": params_digest,
        "input_artifact_ids": [item["artifact_id"] for item in inputs],
        "input_artifact_digests": [item["content_digest"] for item in inputs],
        "output_artifact_ids": [item["artifact_id"] for item in outputs],
        "output_artifact_digests": [item["content_digest"] for item in outputs],
    }
    return {
        "operation_id": f"sandbox_calc_{_safe_id(sandbox_run_id)}_{_safe_id(role)}",
        "canonical_ref_kind": "sandbox_calculation",
        "kind": calculation_id,
        "scope": "formal",
        "status": "completed",
        "terminal": True,
        "failure_code": None,
        "operation_identity_schema": SANDBOX_CALCULATION_IDENTITY_SCHEMA,
        "operation_identity_material": material,
        "operation_identity_digest": sandbox_calculation_digest(material),
        "params_digest": params_digest,
        "parameters": params,
        "source_snapshot_digest": source_snapshot_digest,
        "route_policy_id": "sandbox.calculation:v1",
        "selected_backend": "sandbox_run",
        "backend_run_id": sandbox_run_id,
        "inputs": [dict(item) for item in inputs],
        "outputs": [dict(item) for item in outputs],
    }


def _single_completed_operation(
    operations: tuple[ControlledOperation, ...],
    *,
    sdk_module: str,
    function_name: str,
) -> ControlledOperation:
    matches = [
        operation
        for operation in operations
        if operation.sdk_module == sdk_module
        and operation.function_name == function_name
    ]
    if len(matches) != 1:
        raise LiveProductPathError(
            "formal_operation_receipt_ambiguous",
            "formal product path requires exactly one completed canonical operation",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "completed_count": len(matches),
            },
        )
    if matches[0].status.value != "completed":
        raise LiveProductPathError(
            "formal_required_operation_not_completed",
            "a required scientific operation did not complete",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "status": matches[0].status.value,
            },
        )
    return matches[0]


def _optional_completed_operation(
    operations: tuple[ControlledOperation, ...],
    *,
    sdk_module: str,
    function_name: str,
) -> ControlledOperation | None:
    matches = [
        operation
        for operation in operations
        if operation.sdk_module == sdk_module
        and operation.function_name == function_name
    ]
    if len(matches) > 1:
        raise LiveProductPathError(
            "formal_operation_receipt_ambiguous",
            "formal product path has more than one canonical operation for an optional role",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "operation_count": len(matches),
            },
        )
    if matches and matches[0].status.value != "completed":
        raise LiveProductPathError(
            "formal_optional_operation_not_completed",
            "an attempted optional scientific operation did not complete and cannot be hidden by an empty branch",
            details={
                "sdk_method": f"{sdk_module}.{function_name}",
                "status": matches[0].status.value,
            },
        )
    return None if not matches else matches[0]


def _copy_with_name(
    copies: list[CatalogArtifactCopy],
    *,
    names: set[str],
    identity: str,
) -> CatalogArtifactCopy:
    matches = [
        copy
        for copy in copies
        if PurePosixPath(str(copy.record["relative_path"])).name in names
        or PurePosixPath(
            str(
                dict(copy.record.get("provenance") or {}).get("catalog_relative_path")
                or ""
            )
        ).name
        in names
    ]
    if len(matches) != 1:
        raise LiveProductPathError(
            "formal_artifact_role_ambiguous",
            "formal operation output does not resolve to one required artifact role",
            details={"identity": identity, "matching_count": len(matches)},
        )
    return matches[0]


def _final_deliverable_copies(
    context: AttemptRunContext,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
) -> tuple[
    dict[str, CatalogArtifactCopy],
    dict[str, SessionArtifactRecord],
    dict[str, object],
]:
    by_path: dict[str, list[SessionArtifactRecord]] = {
        path: [] for path in S15_AOX_HMM_FIXED_DELIVERABLES
    }
    for artifact in artifacts.values():
        if artifact.relative_path in by_path:
            by_path[artifact.relative_path].append(artifact)
    ambiguous = {
        path: len(records) for path, records in by_path.items() if len(records) != 1
    }
    if ambiguous:
        raise LiveProductPathError(
            "final_deliverable_catalog_ambiguous",
            "every normalized AOX deliverable must resolve to exactly one catalog artifact",
            details={"path_counts": ambiguous},
        )
    artifact_by_path = {path: records[0] for path, records in by_path.items()}
    text_by_path: dict[str, str] = {}
    metadata_by_path: dict[str, dict[str, object]] = {}
    copy_by_path: dict[str, CatalogArtifactCopy] = {}
    for path, artifact in artifact_by_path.items():
        copied = _copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="operation",
            provenance={
                "calculation_id": AOX_DELIVERABLE_NORMALIZATION_ID,
                "deliverable_path": path,
            },
            cache=copies,
        )
        try:
            text_by_path[path] = copied.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiveProductPathError(
                "final_deliverable_not_utf8",
                "normalized AOX deliverables must be UTF-8 scientific artifacts",
                details={"path": path},
            ) from exc
        metadata_by_path[path] = dict(artifact.metadata or {})
        copy_by_path[path] = copied
    validation = _s15_aox_validate_final_artifacts(
        set(copy_by_path),
        text_by_path,
        metadata_by_path,
    )
    if validation.get("passed") is not True:
        raise LiveProductPathError(
            "final_deliverable_validation_failed",
            "normalized AOX deliverables failed the independent S15 validator",
            details={
                "error_count": len(validation.get("errors") or []),
                "missing_count": len(validation.get("missing_paths") or []),
            },
        )
    return copy_by_path, artifact_by_path, validation


def _sandbox_run_for_final_deliverables(
    final_artifacts: Mapping[str, SessionArtifactRecord],
    sandbox_runs: tuple[object, ...],
) -> object:
    provenance_identities = {
        (
            str(dict(artifact.metadata or {}).get("sandbox_workspace_id") or ""),
            str(dict(artifact.metadata or {}).get("source_snapshot_artifact_id") or ""),
            str(dict(artifact.metadata or {}).get("source_tree_digest") or ""),
        )
        for artifact in final_artifacts.values()
    }
    if len(provenance_identities) != 1:
        raise LiveProductPathError(
            "final_deliverable_run_identity_ambiguous",
            "normalized deliverables do not share one sandbox source identity",
            details={"identity_count": len(provenance_identities)},
        )
    workspace_id, source_artifact_id, source_digest = next(iter(provenance_identities))
    if not workspace_id or not source_artifact_id or not source_digest:
        raise LiveProductPathError(
            "final_deliverable_run_identity_missing",
            "normalized deliverables lack their sandbox source identity",
        )
    candidates = [
        run
        for run in sandbox_runs
        if str(getattr(run, "sandbox_workspace_id", "")) == workspace_id
        and str(getattr(run, "source_snapshot_artifact_id", "")) == source_artifact_id
        and str(getattr(run, "source_tree_digest", "")) == source_digest
        and getattr(getattr(run, "status", None), "value", None) == "completed"
    ]
    if len(candidates) > 1:
        artifact_times = [artifact.created_at for artifact in final_artifacts.values()]
        bounded = [
            run
            for run in candidates
            if str(getattr(run, "started_at", "") or getattr(run, "created_at", ""))
            <= min(artifact_times)
            and str(getattr(run, "ended_at", "") or getattr(run, "updated_at", ""))
            >= max(artifact_times)
        ]
        candidates = bounded
    if len(candidates) != 1:
        raise LiveProductPathError(
            "final_deliverable_run_receipt_ambiguous",
            "normalized deliverables do not resolve to one completed sandbox run",
            details={"matching_run_count": len(candidates)},
        )
    return candidates[0]


def _score_filtered_hmmer_accessions(
    parsed_hits_content: bytes,
    score_filtered_content: bytes,
) -> aox_hmmer.ScoreFilteredAccessionsResult:
    try:
        result = aox_hmmer.parse_and_filter_csv(parsed_hits_content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LiveProductPathError(
            "hmmer_score_filter_invalid",
            "EBI HMMER parsed hits do not satisfy hmmer_score_filtered_accessions@1",
        ) from exc
    expected = result.to_csv().encode("utf-8")
    if score_filtered_content != expected:
        raise LiveProductPathError(
            "hmmer_score_filter_output_mismatch",
            "registered pre-UniProt accession artifact differs from offline recomputation",
            details={
                "expected_digest": _sha256(expected),
                "actual_digest": _sha256(score_filtered_content),
            },
        )
    return result


def _sandbox_source_implementation_digest(run: object, calculation_id: str) -> str:
    return canonical_digest(
        {
            "calculation_id": calculation_id,
            "source_snapshot_artifact_id": str(
                getattr(run, "source_snapshot_artifact_id") or ""
            ),
            "source_snapshot_digest": str(getattr(run, "source_tree_digest") or ""),
        }
    )


def _operation_backend_run_id(operation_record: Mapping[str, object]) -> str:
    backend_run_id = str(operation_record.get("backend_run_id") or "")
    if not backend_run_id:
        raise LiveProductPathError(
            "controlled_operation_backend_receipt_missing",
            "completed controlled operation lacks its canonical backend run identity",
            details={"operation_id": operation_record.get("operation_id")},
        )
    return backend_run_id


def _controlled_provider_receipt(
    *,
    provider_name: str,
    operation: ControlledOperation,
    operation_record: Mapping[str, object],
    output_copies: list[CatalogArtifactCopy],
    response_digest: str,
) -> dict[str, object]:
    invocation_id = _operation_backend_run_id(operation_record)
    return {
        "provider_record_id": f"provider_record_{provider_name}_{_safe_id(operation.operation_id)}",
        "provider": provider_name,
        "status": "completed",
        "canonical_ref_kind": "controlled_operation",
        "invocation_id": invocation_id,
        "operation_id": operation.operation_id,
        "cache_hit": False,
        "request_digest": operation.params_digest,
        "response_digest": response_digest,
        "artifact_ids": [str(copy.record["artifact_id"]) for copy in output_copies],
        "source_ref_ids": [],
    }


def _upstream_empty_provider_receipt(
    context: AttemptRunContext,
    *,
    upstream_provider_record: Mapping[str, object],
    derivation_operation: Mapping[str, object],
    derived_accession_artifact: CatalogArtifactCopy,
    reason: str,
) -> tuple[dict[str, object], dict[str, object]]:
    provider_record_id = (
        f"provider_record_uniprot_upstream_empty_{_safe_id(context.roots.attempt_id)}"
    )
    artifact_id = (
        f"art_uniprot_upstream_empty_{_safe_id(context.roots.attempt_id)}"
    )
    derived_accessions_digest = canonical_digest([])
    decision_material = {
        "reason": reason,
        "upstream_provider_record_id": str(
            upstream_provider_record.get("provider_record_id") or ""
        ),
        "derivation_operation_id": str(
            derivation_operation.get("operation_id") or ""
        ),
        "derived_accession_artifact_id": str(
            derived_accession_artifact.record["artifact_id"]
        ),
        "derived_accession_artifact_digest": (
            derived_accession_artifact.content_digest
        ),
        "derived_accessions_digest": derived_accessions_digest,
    }
    receipt_payload: dict[str, object] = {
        "schema_id": "provider_upstream_empty_receipt@1",
        "provider_record_id": provider_record_id,
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "provider_io_performed": False,
        "cache_consulted": False,
        **decision_material,
        "decision_input_digest": canonical_digest(decision_material),
    }
    receipt_payload["skip_receipt_digest"] = canonical_digest(receipt_payload)
    content = canonical_json_bytes(receipt_payload) + b"\n"
    relative_path = "formal/provider/uniprot-upstream-empty.json"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    artifact_record = {
        "artifact_id": artifact_id,
        "relative_path": relative_path,
        "scope": "formal",
        "origin": "attestation",
        "kind": "provider_receipt",
        "provenance": {
            "provider_record_id": provider_record_id,
            "upstream_provider_record_id": decision_material[
                "upstream_provider_record_id"
            ],
            "derivation_operation_id": decision_material[
                "derivation_operation_id"
            ],
            "skip_receipt_digest": receipt_payload["skip_receipt_digest"],
        },
    }
    provider_record = {
        "provider_record_id": provider_record_id,
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "invocation_id": None,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": None,
        "response_digest": None,
        "artifact_ids": [artifact_id],
        "source_ref_ids": [],
        "reason": reason,
        "skip_receipt_digest": receipt_payload["skip_receipt_digest"],
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    return provider_record, artifact_record


def _toolchain_receipt(
    *,
    tool_name: str,
    operation: ControlledOperation,
    operation_record: Mapping[str, object],
    sandbox_runs: Mapping[str, object],
) -> dict[str, object]:
    run = sandbox_runs.get(operation.sandbox_run_id)
    compatibility = (
        {} if run is None else dict(getattr(run, "compatibility", None) or {})
    )
    image_digest = str(compatibility.get("image_digest") or "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None:
        raise LiveProductPathError(
            "toolchain_image_identity_missing",
            "HPC operation lacks its immutable sandbox image identity",
            details={"operation_id": operation.operation_id},
        )
    return {
        "toolchain_record_id": f"toolchain_record_{_safe_id(operation.operation_id)}",
        "toolchain_id": str(operation.toolchain_id or ""),
        "tool": tool_name,
        "operation_id": operation.operation_id,
        "job_id": _operation_backend_run_id(operation_record),
        "image_digest": image_digest,
        "status": "completed",
    }


def _pubmed_receipts(
    context: AttemptRunContext,
    *,
    sources: tuple[object, ...],
    invocation: object,
    input_document: object,
    output_document: object,
    artifacts: Mapping[str, SessionArtifactRecord],
    copies: dict[str, CatalogArtifactCopy],
) -> tuple[dict[str, object], dict[str, object], CatalogArtifactCopy]:
    invocation_id = str(getattr(invocation, "invocation_id"))
    source_rows = [
        source for source in sources if getattr(source, "provider", None) == "pubmed"
    ]
    if not source_rows or any(
        not str(getattr(source, "pmid", "") or "").isdigit()
        or getattr(source, "invocation_id", None) != invocation_id
        for source in source_rows
    ):
        raise LiveProductPathError(
            "pubmed_source_receipt_invalid",
            "PubMed source rows must bind numeric PMIDs to one research invocation",
        )
    request_digests = {
        str(getattr(source, "request_digest", "") or "") for source in source_rows
    }
    response_digests = {
        str(getattr(source, "response_digest", "") or "") for source in source_rows
    }
    evidence_ids = {
        str(getattr(source, "evidence_artifact_id", "") or "") for source in source_rows
    }
    cache_statuses = {
        str(
            dict(getattr(source, "provider_provenance", None) or {}).get("cache_status")
            or ""
        )
        for source in source_rows
    }
    if (
        len(request_digests) != 1
        or "" in request_digests
        or len(response_digests) != 1
        or "" in response_digests
        or len(evidence_ids) != 1
        or "" in evidence_ids
        or not cache_statuses.issubset({"", "disabled", "bypass", "miss"})
    ):
        raise LiveProductPathError(
            "pubmed_provider_provenance_ambiguous",
            "PubMed source rows do not share one cache-bypassed provider receipt",
        )
    evidence_artifact = _require_artifact(artifacts, next(iter(evidence_ids)))
    evidence_copy = _copy_catalog_artifact(
        context,
        evidence_artifact,
        scope="formal",
        origin="engine_invocation",
        provenance={
            "invocation_id": invocation_id,
            "engine_name": "research_tool",
            "provider": "pubmed",
        },
        cache=copies,
    )
    input_ref = str(getattr(invocation, "input_ref", "") or "")
    output_ref = str(getattr(invocation, "output_ref", "") or "")
    if (
        getattr(invocation, "engine_name", None) != "research_tool"
        or getattr(getattr(invocation, "status", None), "value", None) != "succeeded"
        or not input_ref
        or not output_ref
        or getattr(input_document, "document_id", None) != input_ref
        or getattr(output_document, "document_id", None) != output_ref
    ):
        raise LiveProductPathError(
            "pubmed_engine_invocation_invalid",
            "PubMed evidence does not close through its terminal research invocation",
        )
    source_refs = [
        {
            "source_ref_id": str(getattr(source, "source_ref_id")),
            "pmid": str(getattr(source, "pmid")),
            "title": str(getattr(source, "title", "") or ""),
            "locator": str(getattr(source, "locator", "") or ""),
            "doi": getattr(source, "doi", None),
        }
        for source in source_rows
    ]
    provider_record = {
        "provider_record_id": f"provider_record_pubmed_{_safe_id(invocation_id)}",
        "provider": "pubmed",
        "status": "completed",
        "canonical_ref_kind": "engine_invocation",
        "invocation_id": invocation_id,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": next(iter(request_digests)),
        "response_digest": next(iter(response_digests)),
        "artifact_ids": [str(evidence_copy.record["artifact_id"])],
        "source_ref_ids": [row["source_ref_id"] for row in source_refs],
        "source_refs": source_refs,
    }
    invocation_record = {
        "invocation_id": invocation_id,
        "engine_name": "research_tool",
        "status": "succeeded",
        "task_id": str(getattr(invocation, "task_id") or ""),
        "lane_id": str(getattr(invocation, "lane_id") or ""),
        "input_ref": input_ref,
        "input_document_digest": canonical_digest(getattr(input_document, "payload")),
        "output_ref": output_ref,
        "output_document_digest": canonical_digest(getattr(output_document, "payload")),
        "started_at": str(getattr(invocation, "started_at") or ""),
        "finished_at": str(getattr(invocation, "finished_at") or ""),
        "artifact_refs": [_artifact_ref(evidence_copy)],
    }
    if not invocation_record["task_id"] or not invocation_record["lane_id"]:
        raise LiveProductPathError(
            "pubmed_engine_invocation_scope_missing",
            "PubMed research invocation is not bound to its delegated task and lane",
        )
    return provider_record, invocation_record, evidence_copy


def _task_receipts(
    *,
    tasks: tuple[object, ...],
    agents: tuple[object, ...],
    documents: tuple[object, ...],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    required_roles = {"researcher", "executor", "reporter"}
    agents_by_id = {
        str(getattr(agent, "agent_id")): agent
        for agent in agents
        if str(getattr(agent, "role", "")) in required_roles
    }
    finish_documents: dict[str, list[object]] = {}
    for document in documents:
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        task_id = str(payload.get("task_id") or "")
        if task_id:
            finish_documents.setdefault(task_id, []).append(document)
    receipts: list[dict[str, object]] = []
    role_ids: dict[str, str] = {}
    for task in tasks:
        assigned_ref = str(getattr(task, "assigned_ref", "") or "")
        agent = agents_by_id.get(assigned_ref)
        if agent is None:
            raise LiveProductPathError(
                "formal_task_assignment_invalid",
                "formal product task is not assigned to a required canonical teammate",
                details={"task_id": getattr(task, "task_id", None)},
            )
        role = str(getattr(agent, "role"))
        task_id = str(getattr(task, "task_id"))
        if role in role_ids:
            raise LiveProductPathError(
                "formal_task_role_ambiguous",
                "formal product path has more than one task for a required role",
                details={"role": role},
            )
        finish_matches = finish_documents.get(task_id, [])
        if (
            getattr(getattr(task, "status", None), "value", None) != "completed"
            or len(finish_matches) != 1
        ):
            raise LiveProductPathError(
                "formal_task_finish_missing",
                "required teammate task lacks one explicit completed task.finish receipt",
                details={"task_id": task_id},
            )
        finish = finish_matches[0]
        payload = dict(getattr(finish, "payload", None) or {})
        if (
            payload.get("status") != "completed"
            or not str(payload.get("finished_by") or "").strip()
        ):
            raise LiveProductPathError(
                "formal_task_finish_invalid",
                "task.finish payload does not attest the completed business exit",
                details={"task_id": task_id},
            )
        role_ids[role] = task_id
        receipts.append(
            {
                "task_id": task_id,
                "role": role,
                "kind": str(getattr(task, "kind", "")),
                "status": "completed",
                "business_exit": "agent_explicit",
                "assigned_ref": assigned_ref,
                "lane_id": getattr(task, "lane_id", None),
                "finish_ref": str(getattr(finish, "document_id")),
                "finish_payload_digest": canonical_digest(payload),
                "finished_by": str(payload["finished_by"]),
                "evidence_refs": [
                    str(item) for item in payload.get("evidence_refs") or []
                ],
            }
        )
    if set(role_ids) != required_roles:
        raise LiveProductPathError(
            "formal_task_chain_missing",
            "formal product path lacks one researcher, executor, and reporter task",
            details={"observed_roles": sorted(role_ids)},
        )
    return sorted(receipts, key=lambda item: str(item["task_id"])), role_ids


def _durable_events_by_session(
    repositories: object, session_id: str
) -> tuple[object, ...]:
    events: list[object] = []
    after_cursor = 0
    while True:
        batch = repositories.durable_events.list_by_session(
            session_id,
            after_cursor=after_cursor,
            limit=1_000,
        )
        if not batch:
            break
        events.extend(batch)
        last_cursor = getattr(batch[-1], "cursor", None)
        if not isinstance(last_cursor, int) or last_cursor <= after_cursor:
            raise LiveProductPathError(
                "durable_event_cursor_invalid",
                "durable report event stream did not advance monotonically",
            )
        after_cursor = last_cursor
        if len(batch) < 1_000:
            break
    return tuple(events)


def _report_publish_event_sequence(
    events: tuple[object, ...],
    *,
    report: object,
    draft: object,
) -> list[dict[str, object]]:
    ordered = sorted(events, key=lambda event: int(getattr(event, "cursor") or 0))
    report_payload = getattr(report, "to_dict")()
    draft_payload = getattr(draft, "to_dict")()
    sequences: list[list[object]] = []
    for index, event in enumerate(ordered):
        payload = dict(getattr(event, "payload", None) or {})
        if (
            getattr(event, "event_type", None) != "tool.invoked"
            or payload.get("tool_name") != "report.publish"
            or payload.get("role") != "reporter"
            or not str(payload.get("call_id") or "")
        ):
            continue
        call_id = str(payload["call_id"])
        draft_event = next(
            (
                candidate
                for candidate in ordered[index + 1 :]
                if getattr(candidate, "event_type", None) == "report_draft.updated"
                and dict(getattr(candidate, "payload", None) or {}) == draft_payload
            ),
            None,
        )
        if draft_event is None:
            continue
        draft_index = ordered.index(draft_event)
        report_event = next(
            (
                candidate
                for candidate in ordered[draft_index + 1 :]
                if getattr(candidate, "event_type", None) == "report.generated"
                and dict(getattr(candidate, "payload", None) or {}) == report_payload
            ),
            None,
        )
        if report_event is None:
            continue
        report_index = ordered.index(report_event)
        completed_event = next(
            (
                candidate
                for candidate in ordered[report_index + 1 :]
                if getattr(candidate, "event_type", None) == "tool.completed"
                and dict(getattr(candidate, "payload", None) or {}).get("call_id")
                == call_id
                and dict(getattr(candidate, "payload", None) or {}).get("tool_name")
                == "report.publish"
                and dict(getattr(candidate, "payload", None) or {}).get("role")
                == "reporter"
                and dict(getattr(candidate, "payload", None) or {}).get("ok") is True
            ),
            None,
        )
        if completed_event is not None:
            sequences.append([event, draft_event, report_event, completed_event])
    if len(sequences) != 1:
        raise LiveProductPathError(
            "report_publish_event_receipt_ambiguous",
            "ready report does not resolve to one successful reporter publish sequence",
            details={"matching_sequence_count": len(sequences)},
        )
    return [dict(event.to_dict()) for event in sequences[0]]


def _published_report_receipt(
    context: AttemptRunContext,
    *,
    reports: tuple[object, ...],
    drafts: tuple[object, ...],
    documents: tuple[object, ...],
    durable_events: tuple[object, ...],
    pubmed_provider: Mapping[str, object],
    scientific_artifacts: list[CatalogArtifactCopy],
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    ready_reports = [
        report
        for report in reports
        if getattr(getattr(report, "status", None), "value", None) == "ready"
    ]
    published_drafts = [
        draft
        for draft in drafts
        if getattr(getattr(draft, "status", None), "value", None) == "published"
    ]
    if len(ready_reports) != 1 or len(published_drafts) != 1:
        raise LiveProductPathError(
            "published_report_receipt_ambiguous",
            "formal product path requires exactly one ready report and published draft",
        )
    report = ready_reports[0]
    draft = published_drafts[0]
    if (
        getattr(draft, "published_report_id", None)
        != getattr(report, "report_id", None)
        or not getattr(draft, "content_ref", None)
        or getattr(report, "artifact_id", None) is not None
        or getattr(report, "invocation_id", None) is not None
        or getattr(report, "run_id", None) is not None
    ):
        raise LiveProductPathError(
            "published_report_receipt_invalid",
            "ready report is not the exact product published from its durable draft",
        )
    document_matches = [
        document
        for document in documents
        if getattr(document, "document_id", None) == getattr(draft, "content_ref", None)
    ]
    if (
        len(document_matches) != 1
        or getattr(document_matches[0], "document_kind", None) != "report_draft_content"
        or getattr(document_matches[0], "invocation_id", None) is not None
    ):
        raise LiveProductPathError(
            "published_report_content_document_invalid",
            "published draft content does not resolve to its durable content document",
        )
    content_document = document_matches[0]
    markdown = str(
        dict(getattr(content_document, "payload", None) or {}).get("markdown") or ""
    )
    if not markdown.strip():
        raise LiveProductPathError(
            "published_report_content_empty",
            "published report draft has no markdown content",
        )
    content = markdown.encode("utf-8")
    report_artifact_id = f"art_report_{_safe_id(str(getattr(report, 'report_id')))}"
    relative_path = f"formal/report/{_safe_id(str(getattr(report, 'report_id')))}.md"
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    content_document_digest = canonical_digest(content_document.to_dict())
    report_artifact = {
        "artifact_id": report_artifact_id,
        "relative_path": relative_path,
        "scope": "formal",
        "origin": "report",
        "kind": "report",
        "provenance": {
            "report_id": str(getattr(report, "report_id")),
            "draft_id": str(getattr(draft, "draft_id")),
            "content_ref": str(getattr(draft, "content_ref")),
            "content_document_digest": content_document_digest,
            "draft_published": True,
        },
    }
    source_refs = [
        dict(item)
        for item in pubmed_provider.get("source_refs") or []
        if isinstance(item, dict)
    ]
    matched_sources = [
        row
        for row in source_refs
        if any(
            marker and marker in markdown
            for marker in (
                str(row.get("source_ref_id") or ""),
                str(row.get("pmid") or ""),
                str(row.get("locator") or ""),
            )
        )
    ]
    matched_artifacts = [
        artifact
        for artifact in scientific_artifacts
        if any(
            marker and marker in markdown
            for marker in (
                str(artifact.record.get("artifact_id") or ""),
                str(
                    dict(artifact.record.get("provenance") or {}).get(
                        "catalog_relative_path"
                    )
                    or ""
                ),
                PurePosixPath(
                    str(
                        dict(artifact.record.get("provenance") or {}).get(
                            "catalog_relative_path"
                        )
                        or ""
                    )
                ).name,
            )
        )
    ]
    if not matched_sources or not matched_artifacts:
        raise LiveProductPathError(
            "published_report_claim_lineage_missing",
            "published markdown does not literally identify PubMed and scientific artifacts",
        )
    product_report_record = dict(report.to_dict())
    published_draft_record = dict(draft.to_dict())
    content_document_record = dict(content_document.to_dict())
    publish_events = _report_publish_event_sequence(
        durable_events,
        report=report,
        draft=draft,
    )
    report_record = {
        "report_id": str(getattr(report, "report_id")),
        "session_id": str(getattr(report, "session_id")),
        "task_id": getattr(report, "task_id", None),
        "lane_id": getattr(report, "lane_id", None),
        "status": "ready",
        "invocation_id": None,
        "run_id": None,
        "product_artifact_id": None,
        "draft_id": str(getattr(draft, "draft_id")),
        "draft_status": "published",
        "published_report_id": str(getattr(report, "report_id")),
        "owner_agent_id": getattr(draft, "owner_agent_id", None),
        "content_ref": str(getattr(draft, "content_ref")),
        "content_document_kind": "report_draft_content",
        "content_document_invocation_id": None,
        "content_document_digest": content_document_digest,
        "content_artifact_id": report_artifact_id,
        "content_digest": _sha256(content),
        "publication_action": "report.publish",
        "product_report_record": product_report_record,
        "published_draft_record": published_draft_record,
        "content_document_record": content_document_record,
        "publish_events": publish_events,
        "cutover_eligible": True,
        "artifact_ids": [
            *(str(artifact.record["artifact_id"]) for artifact in matched_artifacts),
            report_artifact_id,
        ],
        "source_ref_ids": [str(row["source_ref_id"]) for row in matched_sources],
        "claim_source_links": [
            {
                "claim_id": "claim_published_aox_result",
                "source_ref_ids": [
                    str(row["source_ref_id"]) for row in matched_sources
                ],
                "artifact_ids": [
                    str(artifact.record["artifact_id"])
                    for artifact in matched_artifacts
                ],
            }
        ],
    }
    return report_record, report_artifact, publish_events


def _attach_product_receipts(
    context: AttemptRunContext,
    evidence: dict[str, Any],
    *,
    report_publish_events: list[dict[str, object]],
) -> None:
    product_path = dict(evidence["product_path"])
    report = dict(evidence["report"])
    operations = [dict(item) for item in evidence["operations"]]
    providers = [dict(item) for item in evidence["provider_identities"]]
    toolchains = [dict(item) for item in evidence["toolchain_identities"]]
    approvals = [dict(item) for item in evidence["approvals"]]
    tasks = [dict(item) for item in evidence["tasks"]]
    final_answer = dict(evidence["final_answer"])
    outcome = dict(evidence["scientific_outcome"])
    workspace_payload = {
        "schema_id": "aox_workspace_projection_receipt@1",
        "session_id": product_path["session_id"],
        "task_ids_by_role": product_path["task_ids_by_role"],
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "provider_invocation_ids": sorted(item["invocation_id"] for item in providers),
        "toolchain_job_ids": sorted(item["job_id"] for item in toolchains),
        "report_id": report["report_id"],
        "final_master_response_id": product_path["final_master_response_id"],
        "root_identity": product_path["launch_receipt"]["root_identity"],
        "runtime_config_digest": product_path["runtime_config_digest"],
        "cache_hit": product_path["cache_hit"],
        "participant_roles": sorted(product_path["participant_roles"]),
        "task_receipts": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "role": item["role"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "report_receipt": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_artifact_id": report["content_artifact_id"],
            "content_digest": report["content_digest"],
        },
        "final_answer_receipt": {
            "message_id": final_answer["message_id"],
            "content_digest": _sha256(final_answer["content"].encode("utf-8")),
        },
        "scientific_outcome": {
            "status": outcome["status"],
            "candidate_count": outcome["candidate_count"],
            "empty_result_reason": outcome.get("empty_result_reason"),
            "cutover_eligible": outcome["cutover_eligible"],
        },
        "micu_scenario": product_path["micu_scenario"],
        "micu_model": product_path["micu_model"],
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
    }
    event_payload = {
        "schema_id": "aox_event_log_receipt@1",
        "session_id": product_path["session_id"],
        "entry_message_id": product_path["entry_message_id"],
        "entry_message_digest": product_path["entry_message_digest"],
        "final_master_response_id": product_path["final_master_response_id"],
        "task_ids": sorted(product_path["task_ids_by_role"].values()),
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "approval_bindings": sorted(
            (
                {
                    "approval_id": item["approval_id"],
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                }
                for item in approvals
            ),
            key=lambda item: item["approval_id"],
        ),
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
        "task_finishes": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "operation_finishes": sorted(
            (
                {
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                    "status": item["status"],
                    "terminal": item["terminal"],
                }
                for item in operations
            ),
            key=lambda item: item["operation_id"],
        ),
        "provider_invocations": sorted(
            (
                {
                    "invocation_id": item["invocation_id"],
                    "operation_id": item["operation_id"],
                    "provider": item["provider"],
                    "status": item["status"],
                }
                for item in providers
            ),
            key=lambda item: item["invocation_id"],
        ),
        "toolchain_jobs": sorted(
            (
                {
                    "job_id": item["job_id"],
                    "operation_id": item["operation_id"],
                    "tool": item["tool"],
                    "status": item["status"],
                }
                for item in toolchains
            ),
            key=lambda item: item["job_id"],
        ),
        "report_publish": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_digest": report["content_digest"],
            "publish_events": [dict(item) for item in report_publish_events],
        },
    }
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    workspace_artifact_id = (
        f"art_workspace_projection_{_safe_id(context.roots.attempt_id)}"
    )
    event_artifact_id = f"art_event_log_{_safe_id(context.roots.attempt_id)}"
    workspace_path = "formal/attestation/workspace-projection.json"
    event_path = "formal/attestation/event-log.json"
    _write_sealed_bytes(context.roots.artifact_root, workspace_path, workspace_bytes)
    _write_sealed_bytes(context.roots.artifact_root, event_path, event_bytes)
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_artifact_id,
                "relative_path": workspace_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {"producer": "host_workspace_projection"},
            },
            {
                "artifact_id": event_artifact_id,
                "relative_path": event_path,
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "host_durable_event_log"},
            },
        ]
    )
    product_path["workspace_projection_artifact_id"] = workspace_artifact_id
    product_path["workspace_projection_digest"] = _sha256(workspace_bytes)
    product_path["event_log_artifact_id"] = event_artifact_id
    product_path["event_log_digest"] = _sha256(event_bytes)
    evidence["product_path"] = product_path


def _collect_positive_evidence(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    api_receipts: tuple[PublicApiReceipt, ...],
    health: Mapping[str, object],
    probe: SessionDriveResult,
    formal: SessionDriveResult,
    ledger_path: Path,
    micu_record_ids_before: set[int],
) -> dict[str, Any]:
    sandbox_preflight_identity = dict(
        _safe_health(health).get("sandbox_runtime_identity") or {}
    )
    probe_attestation = _collect_probe_attestation(
        context,
        provider=provider,
        probe=probe,
    )
    with provider.read() as scope:
        repositories = scope.repositories
        operations = tuple(
            repositories.controlled_operations.list_by_session(formal.session_id)
        )
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(formal.session_id)
        }
        artifacts = {
            artifact.artifact_id: artifact
            for artifact in repositories.artifacts.list_by_session(formal.session_id)
        }
        sandbox_runs = tuple(
            repositories.sandbox_runs.list_by_session(formal.session_id)
        )
        tasks = tuple(repositories.tasks.list_by_session(formal.session_id))
        agents = tuple(repositories.agents.list_by_session(formal.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(formal.session_id)
        )
        reports = tuple(repositories.reports.list_by_session(formal.session_id))
        drafts = tuple(repositories.report_drafts.list_by_session(formal.session_id))
        sources = tuple(
            repositories.research_source_refs.list_by_session(formal.session_id)
        )
        invocations = {
            invocation.invocation_id: invocation
            for invocation in repositories.invocations.list_by_session(
                formal.session_id
            )
        }
        conversation = build_conversation_projection(
            repositories,
            formal.session_id,
        )
        durable_events = _durable_events_by_session(
            repositories,
            formal.session_id,
        )

    operation_by_role = {
        "ncbi_fetch": _single_completed_operation(
            operations,
            sdk_module="bio",
            function_name="ncbi_fetch_proteins",
        ),
        "reference_alignment": _single_completed_operation(
            operations,
            sdk_module="bio_tools",
            function_name="mafft",
        ),
        "hmm_build": _single_completed_operation(
            operations,
            sdk_module="bio_tools",
            function_name="hmmbuild",
        ),
        "hmmer_search": _single_completed_operation(
            operations,
            sdk_module="bio",
            function_name="hmmer_search",
        ),
    }
    for role, sdk_module, function_name in (
        ("uniprot_fetch", "bio", "uniprot_fetch"),
        ("candidate_alignment", "bio_tools", "hmmalign"),
        ("cdhit", "bio_tools", "cdhit"),
    ):
        optional_operation = _optional_completed_operation(
            operations,
            sdk_module=sdk_module,
            function_name=function_name,
        )
        if optional_operation is not None:
            operation_by_role[role] = optional_operation
    copies: dict[str, CatalogArtifactCopy] = {}
    controlled_records: dict[str, dict[str, object]] = {}
    output_copies: dict[str, list[CatalogArtifactCopy]] = {}
    provider_parameters: dict[str, dict[str, object]] = {}
    provider_response_digests: dict[str, str] = {}
    for role, operation in operation_by_role.items():
        inputs = _declared_operation_input_refs(
            context,
            operation,
            artifacts=artifacts,
            copies=copies,
        )
        if role in {"ncbi_fetch", "hmmer_search", "uniprot_fetch"}:
            params = _provider_request_parameters(
                context,
                operation,
                artifacts=artifacts,
            )
            selected_outputs, response_digest = _provider_output_copies(
                context,
                operation,
                artifacts=artifacts,
                copies=copies,
            )
            provider_parameters[role] = params
            provider_response_digests[role] = response_digest
        else:
            params = None
            selected_outputs = _tool_output_copies(
                context,
                operation,
                artifacts=artifacts,
                copies=copies,
            )
        output_copies[role] = selected_outputs
        controlled_records[role] = operation_evidence_record(
            operation,
            scope="formal",
            inputs=inputs,
            outputs=[_artifact_ref(copy) for copy in selected_outputs],
            parameters=params,
        )

    ncbi_provider_sequences = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"proteins.fasta"},
        identity="ncbi_provider_sequences",
    )
    reference_alignment = _copy_with_name(
        output_copies["reference_alignment"],
        names={"alignment.fasta"},
        identity="reference_alignment",
    )
    hmm_model = _copy_with_name(
        output_copies["hmm_build"],
        names={"model.hmm"},
        identity="hmm_model",
    )
    hmmer_response = _copy_with_name(
        output_copies["hmmer_search"],
        names={"raw_hits.json"},
        identity="hmmer_response",
    )
    hmmer_parsed_hits = _copy_with_name(
        output_copies["hmmer_search"],
        names={"parsed_hits.csv"},
        identity="hmmer_parsed_hits",
    )
    final_copies, final_artifacts, final_validation = _final_deliverable_copies(
        context,
        artifacts=artifacts,
        copies=copies,
    )
    calculation_run = _sandbox_run_for_final_deliverables(
        final_artifacts,
        sandbox_runs,
    )
    raw_hits = final_copies["aox_hmm/hits_raw.csv"]
    score_filtered_accessions = final_copies[
        HMMER_SCORE_FILTERED_ACCESSIONS_PATH
    ]
    hmm_reference_set = final_copies["aox_hmm/AOX_ref21.fasta"]
    scoring_reference = final_copies[
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"
    ]
    scoring_input = final_copies["aox_hmm/AOX_scoring_input.fasta"]
    filtered_hits = final_copies["aox_hmm/hits_len650_700_200.csv"]
    target_sequences = final_copies["aox_hmm/target.fasta"]
    motif_scores = final_copies["aox_hmm/scored_ref_plus_hits.csv"]
    candidates = final_copies["aox_hmm/AOX_candidates.fasta"]
    graph_nodes = final_copies["aox_hmm/nodes.csv"]
    graph_edges = final_copies["aox_hmm/edges_similarity.csv"]
    graph_manifest = final_copies["aox_hmm/similarity_graph_manifest.json"]
    final_scoring_alignment = final_copies["aox_hmm/AOX_scoring_alignment.fasta"]
    final_membership = final_copies["aox_hmm/AOX_candidates_cdhit85.clusters.csv"]
    final_representatives = final_copies["aox_hmm/AOX_candidates_cdhit85.fasta"]

    hmm_reference_result = aox_reference.select_hmm_reference_set(
        ncbi_provider_sequences.content,
        expected_contract_id=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
        ),
        expected_contract_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        expected_input_digest=ncbi_provider_sequences.content_digest,
    )
    scoring_reference_result = aox_reference.select_scoring_reference(
        ncbi_provider_sequences.content,
        expected_contract_id=(
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
        ),
        expected_contract_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        expected_input_digest=ncbi_provider_sequences.content_digest,
    )
    if (
        hmm_reference_set.content
        != hmm_reference_result.to_fasta().encode("utf-8")
        or scoring_reference.content
        != scoring_reference_result.to_fasta().encode("utf-8")
    ):
        raise LiveProductPathError(
            "aox_reference_selection_mismatch",
            "sealed model/scoring references differ from the versioned NCBI selection contracts",
        )
    reference_alignment_inputs = {
        str(ref.get("artifact_id") or ""): str(ref.get("content_digest") or "")
        for ref in controlled_records["reference_alignment"].get("inputs") or []
        if isinstance(ref, dict)
    }
    if reference_alignment_inputs != {
        str(hmm_reference_set.record["artifact_id"]): hmm_reference_set.content_digest
    }:
        raise LiveProductPathError(
            "hmm_reference_selection_not_consumed",
            "MAFFT must consume the exact selected 13-reference artifact, not the 14-record provider response",
        )

    if raw_hits.content != hmmer_parsed_hits.content:
        raise LiveProductPathError(
            "hmmer_raw_hit_normalization_drift",
            "normalized hits_raw.csv differs from the sealed EBI parsed-hit bytes",
        )
    score_filter_result = _score_filtered_hmmer_accessions(
        hmmer_parsed_hits.content,
        score_filtered_accessions.content,
    )
    derived_accessions = list(score_filter_result.accessions)
    hmmer_upstream_empty = not derived_accessions
    upstream_empty_reason = (
        "no_hmmer_hits"
        if hmmer_upstream_empty and score_filter_result.input_row_count == 0
        else "no_filtered_hmmer_accessions"
        if hmmer_upstream_empty
        else None
    )
    uniprot_sequences: CatalogArtifactCopy | None = None
    uniprot_metadata: CatalogArtifactCopy | None = None
    sequence_join_result: aox_sequence_join.SequenceLengthJoinResult | None = None
    if hmmer_upstream_empty:
        if "uniprot_fetch" in operation_by_role:
            raise LiveProductPathError(
                "upstream_empty_uniprot_operation_forbidden",
                "UniProt must not be called when the sealed HMMER score filter is empty",
            )
        expected_empty_hits = (
            ",".join(aox_sequence_join.OUTPUT_COLUMNS) + "\n"
        ).encode("utf-8")
        if filtered_hits.content != expected_empty_hits or target_sequences.content:
            raise LiveProductPathError(
                "upstream_empty_materialization_invalid",
                "HMMER upstream-empty branch requires canonical empty joined hits and target FASTA",
            )
    else:
        if "uniprot_fetch" not in operation_by_role:
            raise LiveProductPathError(
                "required_uniprot_operation_missing",
                "nonempty HMMER accessions require one controlled UniProt operation",
            )
        uniprot_sequences = _copy_with_name(
            output_copies["uniprot_fetch"],
            names={"sequences.fasta"},
            identity="uniprot_sequences",
        )
        uniprot_metadata = _copy_with_name(
            output_copies["uniprot_fetch"],
            names={"metadata.json"},
            identity="uniprot_metadata",
        )
        uniprot_params = provider_parameters["uniprot_fetch"]
        source_hit_artifact = dict(uniprot_params.get("source_hit_artifact") or {})
        if sorted(
            str(item).strip().upper()
            for item in uniprot_params.get("accessions") or []
        ) != derived_accessions or source_hit_artifact != {
            "artifact_id": str(score_filtered_accessions.record["artifact_id"]),
            "content_digest": score_filtered_accessions.content_digest,
        }:
            raise LiveProductPathError(
                "hmmer_uniprot_dependency_mismatch",
                "sealed UniProt request does not bind the exact derived HMMER accession artifact",
            )
        try:
            sequence_join_result = aox_sequence_join.join_score_filtered_accessions(
                score_filtered_accessions.content,
                uniprot_sequences.content,
                uniprot_metadata.content,
                expected_contract_id=aox_sequence_join.CONTRACT_ID,
                expected_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
                expected_implementation_digest=(
                    aox_sequence_join.IMPLEMENTATION_DIGEST
                ),
                expected_hmmer_contract_id=aox_hmmer.CONTRACT_ID,
                expected_hmmer_contract_digest=aox_hmmer.CONTRACT_DIGEST,
                expected_hmmer_implementation_digest=(
                    aox_hmmer.IMPLEMENTATION_DIGEST
                ),
                expected_score_filtered_csv_digest=(
                    score_filtered_accessions.content_digest
                ),
                expected_uniprot_fasta_digest=uniprot_sequences.content_digest,
                expected_uniprot_metadata_digest=uniprot_metadata.content_digest,
            )
        except ValueError as exc:
            raise LiveProductPathError(
                "sequence_length_join_invalid",
                "sealed UniProt outputs do not satisfy aox_sequence_length_join@1",
            ) from exc
        if (
            filtered_hits.content
            != sequence_join_result.hits_csv().encode("utf-8")
            or target_sequences.content
            != sequence_join_result.target_fasta().encode("utf-8")
        ):
            raise LiveProductPathError(
                "sequence_length_join_output_mismatch",
                "normalized post-UniProt hits or target FASTA differ from offline recomputation",
            )

    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference.content,
        target_sequences.content,
        expected_contract_id=aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        expected_contract_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        expected_scoring_reference_input_digest=scoring_reference.content_digest,
        expected_target_input_digest=target_sequences.content_digest,
    )
    if scoring_input.content != scoring_input_result.to_fasta().encode("utf-8"):
        raise LiveProductPathError(
            "aox_scoring_input_assembly_mismatch",
            "sealed scoring input differs from the versioned AAB-plus-target assembly contract",
        )

    target_sequences_nonempty = bool(target_sequences.content.strip())
    if target_sequences_nonempty:
        if "candidate_alignment" not in operation_by_role:
            raise LiveProductPathError(
                "required_hmmalign_operation_missing",
                "nonempty post-UniProt targets require one controlled HMMalign operation",
            )
        scoring_alignment = _copy_with_name(
            output_copies["candidate_alignment"],
            names={"aligned.fasta"},
            identity="scoring_alignment",
        )
        if scoring_alignment.content != final_scoring_alignment.content:
            raise LiveProductPathError(
                "scoring_alignment_normalization_drift",
                "normalized scoring alignment differs from the HMMalign output bytes",
            )
        candidate_alignment_inputs = {
            str(ref.get("artifact_id") or ""): str(
                ref.get("content_digest") or ""
            )
            for ref in controlled_records["candidate_alignment"].get("inputs") or []
            if isinstance(ref, dict)
        }
        if candidate_alignment_inputs != {
            str(hmm_model.record["artifact_id"]): hmm_model.content_digest,
            str(scoring_input.record["artifact_id"]): scoring_input.content_digest,
        }:
            raise LiveProductPathError(
                "hmmalign_scoring_input_mismatch",
                "HMMalign must consume the exact HMM plus versioned AAB-and-target scoring input",
            )
    else:
        if "candidate_alignment" in operation_by_role:
            raise LiveProductPathError(
                "empty_target_hmmalign_operation_forbidden",
                "HMMalign must be omitted when the sealed target FASTA is empty",
            )
        scoring_alignment = final_scoring_alignment
        if scoring_alignment.content != scoring_reference.content:
            raise LiveProductPathError(
                "reference_only_scoring_alignment_invalid",
                "empty-target scoring alignment must equal the sealed normalized reference FASTA",
            )

    candidate_count = int(final_validation["candidate_count"])
    if candidate_count:
        if "cdhit" not in operation_by_role:
            raise LiveProductPathError(
                "required_cdhit_operation_missing",
                "nonempty AOX candidates require one controlled CD-HIT operation",
            )
        cdhit_membership = _copy_with_name(
            output_copies["cdhit"],
            names={"clusters.csv"},
            identity="cdhit_membership",
        )
        cdhit_representatives = _copy_with_name(
            output_copies["cdhit"],
            names={"clustered.fasta"},
            identity="cdhit_representatives",
        )
        if (
            cdhit_membership.content != final_membership.content
            or cdhit_representatives.content != final_representatives.content
        ):
            raise LiveProductPathError(
                "cdhit_membership_normalization_drift",
                "normalized CD-HIT outputs differ from the controlled output bytes",
            )
    else:
        if "cdhit" in operation_by_role:
            raise LiveProductPathError(
                "empty_candidate_cdhit_operation_forbidden",
                "CD-HIT must be omitted when the sealed candidate FASTA is empty",
            )
        cdhit_membership = final_membership
        cdhit_representatives = final_representatives

    all_controlled_outputs: list[dict[str, str]] = []
    seen_output_ids: set[str] = set()
    for role in operation_by_role:
        for copy in output_copies[role]:
            artifact_id = str(copy.record["artifact_id"])
            if artifact_id not in seen_output_ids:
                seen_output_ids.add(artifact_id)
                all_controlled_outputs.append(_artifact_ref(copy))
    specialized_paths = {
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
        "aox_hmm/AOX_scoring_input.fasta",
        "aox_hmm/AOX_scoring_alignment.fasta",
        "aox_hmm/hits_len650_700_200.csv",
        "aox_hmm/target.fasta",
        HMMER_SCORE_FILTERED_ACCESSIONS_PATH,
        "aox_hmm/scored_ref_plus_hits.csv",
        "aox_hmm/AOX_candidates.fasta",
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/similarity_graph_manifest.json",
    }
    if not candidate_count:
        specialized_paths.update(
            {
                "aox_hmm/AOX_candidates_cdhit85.fasta",
                "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
            }
        )
    normalization_outputs = [
        _artifact_ref(final_copies[path])
        for path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES - specialized_paths)
    ]
    source_implementation_digest = _sandbox_source_implementation_digest(
        calculation_run,
        AOX_DELIVERABLE_NORMALIZATION_ID,
    )
    normalization_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="deliverable_normalization",
        calculation_id=AOX_DELIVERABLE_NORMALIZATION_ID,
        calculation_contract_digest=AOX_DELIVERABLE_NORMALIZATION_CONTRACT_DIGEST,
        calculation_implementation_digest=source_implementation_digest,
        parameters={"deliverable_count": len(S15_AOX_HMM_FIXED_DELIVERABLES)},
        inputs=all_controlled_outputs,
        outputs=normalization_outputs,
    )
    hmm_reference_selection_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="hmm_reference_set_selection",
        calculation_id=aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
            "identity_replacement": False,
        },
        inputs=[_artifact_ref(ncbi_provider_sequences)],
        outputs=[_artifact_ref(hmm_reference_set)],
    )
    scoring_reference_selection_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="scoring_reference_selection",
        calculation_id=aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            "identity_replacement": False,
        },
        inputs=[_artifact_ref(ncbi_provider_sequences)],
        outputs=[_artifact_ref(scoring_reference)],
    )
    scoring_input_assembly_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="scoring_input_assembly",
        calculation_id=aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        calculation_contract_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        ),
        calculation_implementation_digest=(
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        parameters={
            "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            "target_count": len(scoring_input_result.targets),
        },
        inputs=[_artifact_ref(scoring_reference), _artifact_ref(target_sequences)],
        outputs=[_artifact_ref(scoring_input)],
    )
    pre_uniprot_score_filter_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="pre_uniprot_score_filter",
        calculation_id=aox_hmmer.CONTRACT_ID,
        calculation_contract_digest=aox_hmmer.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
        parameters={"hmm_score_exclusive_gt": aox_hmmer.SCORE_THRESHOLD_DISPLAY},
        inputs=[_artifact_ref(hmmer_parsed_hits)],
        outputs=[_artifact_ref(score_filtered_accessions)],
    )
    post_uniprot_filter_operation: dict[str, object] | None = None
    upstream_empty_materialization_operation: dict[str, object] | None = None
    empty_target_scoring_operation: dict[str, object] | None = None
    if hmmer_upstream_empty:
        upstream_empty_materialization_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="upstream_empty_materialization",
            calculation_id=AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
            calculation_contract_digest=(
                AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST
            ),
            calculation_implementation_digest=_sandbox_source_implementation_digest(
                calculation_run,
                AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
            ),
            parameters={
                "reason": upstream_empty_reason or "",
                "reference_accession": aox_motif.REFERENCE_ACCESSION,
            },
            inputs=[
                _artifact_ref(score_filtered_accessions),
            ],
            outputs=[
                _artifact_ref(filtered_hits),
                _artifact_ref(target_sequences),
            ],
        )
    else:
        assert uniprot_sequences is not None
        assert uniprot_metadata is not None
        post_uniprot_filter_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="post_uniprot_filter",
            calculation_id=aox_sequence_join.CONTRACT_ID,
            calculation_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
            calculation_implementation_digest=aox_sequence_join.IMPLEMENTATION_DIGEST,
            parameters={
                "length_inclusive": [
                    aox_sequence_join.LENGTH_MIN,
                    aox_sequence_join.LENGTH_MAX,
                ],
            },
            inputs=[
                _artifact_ref(score_filtered_accessions),
                _artifact_ref(uniprot_sequences),
                _artifact_ref(uniprot_metadata),
            ],
            outputs=[_artifact_ref(filtered_hits), _artifact_ref(target_sequences)],
        )
    if not target_sequences_nonempty:
        empty_target_scoring_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="empty_target_scoring_materialization",
            calculation_id=AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
            calculation_contract_digest=(
                AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST
            ),
            calculation_implementation_digest=(
                _sandbox_source_implementation_digest(
                    calculation_run,
                    AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
                )
            ),
            parameters={
                "reason": upstream_empty_reason
                or "no_candidates_after_length_filter",
                "reference_accession": aox_motif.REFERENCE_ACCESSION,
            },
            inputs=[
                _artifact_ref(scoring_input),
                _artifact_ref(target_sequences),
            ],
            outputs=[_artifact_ref(scoring_alignment)],
        )
    motif_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="motif_score",
        calculation_id=aox_motif.CONTRACT_ID,
        calculation_contract_digest=aox_motif.CONTRACT_DIGEST,
        calculation_implementation_digest=aox_motif.IMPLEMENTATION_DIGEST,
        parameters={
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
            "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        },
        inputs=[_artifact_ref(scoring_alignment)],
        outputs=[_artifact_ref(motif_scores)],
    )
    candidate_filter_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="candidate_filter",
        calculation_id=AOX_CANDIDATE_FILTER_ID,
        calculation_contract_digest=AOX_CANDIDATE_FILTER_CONTRACT_DIGEST,
        calculation_implementation_digest=_sandbox_source_implementation_digest(
            calculation_run,
            AOX_CANDIDATE_FILTER_ID,
        ),
        parameters={
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
            "threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        },
        inputs=[_artifact_ref(motif_scores), _artifact_ref(target_sequences)],
        outputs=[_artifact_ref(candidates)],
    )
    empty_membership_operation: dict[str, object] | None = None
    if not candidate_count:
        empty_membership_operation = _sandbox_calculation_record(
            run=calculation_run,
            role="empty_membership",
            calculation_id=AOX_EMPTY_MEMBERSHIP_ID,
            calculation_contract_digest=AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST,
            calculation_implementation_digest=_sandbox_source_implementation_digest(
                calculation_run,
                AOX_EMPTY_MEMBERSHIP_ID,
            ),
            parameters={
                "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
            },
            inputs=[_artifact_ref(candidates)],
            outputs=[
                _artifact_ref(cdhit_representatives),
                _artifact_ref(cdhit_membership),
            ],
        )
    similarity_operation = _sandbox_calculation_record(
        run=calculation_run,
        role="similarity",
        calculation_id=aox_similarity.CALCULATION_ID,
        calculation_contract_digest=aox_similarity.CALCULATION_DIGEST,
        calculation_implementation_digest=aox_similarity.IMPLEMENTATION_DIGEST,
        parameters={"threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM},
        inputs=[_artifact_ref(candidates), _artifact_ref(cdhit_membership)],
        outputs=[
            _artifact_ref(graph_nodes),
            _artifact_ref(graph_edges),
            _artifact_ref(graph_manifest),
        ],
    )

    pubmed_source_rows = tuple(
        source for source in sources if getattr(source, "provider", None) == "pubmed"
    )
    pubmed_invocation_ids = {
        str(getattr(source, "invocation_id")) for source in pubmed_source_rows
    }
    if len(pubmed_invocation_ids) != 1:
        raise LiveProductPathError(
            "pubmed_engine_invocation_ambiguous",
            "PubMed source evidence does not resolve to one engine invocation",
        )
    pubmed_invocation = invocations.get(next(iter(pubmed_invocation_ids)))
    if pubmed_invocation is None:
        raise LiveProductPathError(
            "pubmed_engine_invocation_missing",
            "PubMed source evidence references a missing engine invocation",
        )
    document_by_id = {
        str(getattr(document, "document_id")): document for document in documents
    }
    pubmed_input_document = document_by_id.get(
        str(getattr(pubmed_invocation, "input_ref", "") or "")
    )
    pubmed_output_document = document_by_id.get(
        str(getattr(pubmed_invocation, "output_ref", "") or "")
    )
    if pubmed_input_document is None or pubmed_output_document is None:
        raise LiveProductPathError(
            "pubmed_engine_document_missing",
            "PubMed engine invocation lacks its durable input or output document",
        )
    pubmed_provider, pubmed_engine_invocation, literature_evidence = _pubmed_receipts(
        context,
        sources=sources,
        invocation=pubmed_invocation,
        input_document=pubmed_input_document,
        output_document=pubmed_output_document,
        artifacts=artifacts,
        copies=copies,
    )

    ncbi_provider_record = _controlled_provider_receipt(
        provider_name="ncbi",
        operation=operation_by_role["ncbi_fetch"],
        operation_record=controlled_records["ncbi_fetch"],
        output_copies=output_copies["ncbi_fetch"],
        response_digest=provider_response_digests["ncbi_fetch"],
    )
    hmmer_provider_record = _controlled_provider_receipt(
        provider_name="ebi_hmmer",
        operation=operation_by_role["hmmer_search"],
        operation_record=controlled_records["hmmer_search"],
        output_copies=output_copies["hmmer_search"],
        response_digest=provider_response_digests["hmmer_search"],
    )
    upstream_empty_artifact_record: dict[str, object] | None = None
    if hmmer_upstream_empty:
        assert upstream_empty_reason is not None
        uniprot_provider_record, upstream_empty_artifact_record = (
            _upstream_empty_provider_receipt(
                context,
                upstream_provider_record=hmmer_provider_record,
                derivation_operation=pre_uniprot_score_filter_operation,
                derived_accession_artifact=score_filtered_accessions,
                reason=upstream_empty_reason,
            )
        )
    else:
        uniprot_provider_record = _controlled_provider_receipt(
            provider_name="uniprot",
            operation=operation_by_role["uniprot_fetch"],
            operation_record=controlled_records["uniprot_fetch"],
            output_copies=output_copies["uniprot_fetch"],
            response_digest=provider_response_digests["uniprot_fetch"],
        )
    provider_records = [
        pubmed_provider,
        ncbi_provider_record,
        hmmer_provider_record,
        uniprot_provider_record,
    ]
    provider_by_name = {str(item["provider"]): item for item in provider_records}

    sandbox_run_by_id = {
        str(getattr(run, "sandbox_run_id")): run for run in sandbox_runs
    }
    toolchain_records = [
        _toolchain_receipt(
            tool_name=tool_name,
            operation=operation_by_role[role],
            operation_record=controlled_records[role],
            sandbox_runs=sandbox_run_by_id,
        )
        for role, tool_name in (
            ("reference_alignment", "mafft"),
            ("hmm_build", "hmmbuild"),
            ("candidate_alignment", "hmmalign"),
            ("cdhit", "cd-hit"),
        )
        if role in operation_by_role
    ]
    approval_records = [
        _approval_record(operation, approvals)
        for operation in operation_by_role.values()
    ]
    task_records, task_ids_by_role = _task_receipts(
        tasks=tasks,
        agents=agents,
        documents=documents,
    )
    if pubmed_engine_invocation["task_id"] != task_ids_by_role["researcher"]:
        raise LiveProductPathError(
            "pubmed_research_task_mismatch",
            "PubMed invocation is not owned by the formal researcher task",
        )

    scoring_result = aox_motif.score_aligned_fasta(scoring_alignment.content)
    if not target_sequences_nonempty and {
        row.sequence_id for row in scoring_result.rows
    } != {aox_motif.REFERENCE_ACCESSION}:
        raise LiveProductPathError(
            "empty_target_scoring_alignment_invalid",
            "empty-target scoring alignment must contain only the exact AOX reference",
        )
    if motif_scores.content != scoring_result.to_csv().encode("utf-8"):
        raise LiveProductPathError(
            "motif_score_recomputation_mismatch",
            "sealed motif score CSV differs from offline contract recomputation",
        )
    execution_summary = json.loads(
        final_copies["aox_hmm/execution_summary.json"].content
    )
    if not isinstance(execution_summary, dict):
        raise LiveProductPathError(
            "execution_summary_invalid",
            "normalized execution summary must be a JSON object",
        )
    empty_result_reason = None
    if candidate_count == 0:
        empty_payload = execution_summary.get("empty_result")
        empty_result_reason = (
            str(dict(empty_payload).get("reason") or "").strip()
            if isinstance(empty_payload, dict)
            else ""
        )
        if not empty_result_reason:
            raise LiveProductPathError(
                "empty_result_reason_missing",
                "healthy empty AOX result lacks its explicit scientific reason",
            )
        expected_empty_reason = (
            upstream_empty_reason
            if hmmer_upstream_empty
            else "no_candidates_after_length_filter"
            if not target_sequences_nonempty
            else "no_candidates_after_motif_filter"
        )
        if empty_result_reason != expected_empty_reason:
            raise LiveProductPathError(
                "empty_result_reason_mismatch",
                "execution summary empty reason does not match the sealed branch trigger",
                details={
                    "expected": expected_empty_reason,
                    "actual": empty_result_reason,
                },
            )
    graph_result = aox_similarity.validate_graph_artifacts(
        candidates.content,
        cdhit_membership.content,
        graph_nodes.content,
        graph_edges.content,
        graph_manifest.content,
        threshold_ppm=aox_similarity.DEFAULT_THRESHOLD_PPM,
        empty_result_reason=empty_result_reason,
    )
    if len(graph_result.nodes) != candidate_count:
        raise LiveProductPathError(
            "scientific_outcome_graph_mismatch",
            "offline graph node count differs from the validated AOX candidates",
        )

    report_record, report_artifact, report_publish_events = _published_report_receipt(
        context,
        reports=reports,
        drafts=drafts,
        documents=documents,
        durable_events=durable_events,
        pubmed_provider=pubmed_provider,
        scientific_artifacts=list(copies.values()),
    )
    if report_record["task_id"] != task_ids_by_role["reporter"]:
        raise LiveProductPathError(
            "published_report_task_mismatch",
            "published report is not owned by the formal reporter task",
        )

    user_messages = [entry for entry in conversation if entry.role == "user"]
    assistant_messages = [
        entry
        for entry in conversation
        if entry.role == "assistant" and entry.content.strip()
    ]
    message_route = f"/v3/sessions/{formal.session_id}/messages"
    message_receipts = [
        receipt
        for receipt in api_receipts
        if receipt.method == "POST" and receipt.route == message_route
    ]
    if len(user_messages) != 1 or not assistant_messages or len(message_receipts) != 1:
        raise LiveProductPathError(
            "canonical_entry_message_invalid",
            "formal product path must originate from one public user message and produce an answer",
        )
    entry_message = user_messages[0]
    final_message = assistant_messages[-1]
    micu_receipts = _new_micu_attempt_receipts(
        ledger_path,
        before_ids=micu_record_ids_before,
    )
    micu_models = {receipt.model for receipt in micu_receipts}
    if len(micu_models) != 1:
        raise LiveProductPathError(
            "micu_attempt_model_ambiguous",
            "AOX live campaign charged more than one MICU model identity",
        )
    participant_roles = sorted(
        {
            str(getattr(agent, "role"))
            for agent in agents
            if str(getattr(agent, "role", "")) != "master"
        }
    )
    product_path = {
        "entry_message_count": 1,
        "canonical_api_only": True,
        "cache_hit": False,
        "participant_roles": participant_roles,
        "session_id": formal.session_id,
        "entry_message_id": entry_message.message_id,
        "final_master_response_id": final_message.message_id,
        "entry_message_digest": _sha256(entry_message.content.encode("utf-8")),
        "runtime_config_digest": str(context.identity["config_digest"]),
        "micu_scenario": "aox_blank_world_cutover",
        "micu_model": next(iter(micu_models)),
        "micu_invocation_ids": [receipt.invocation_id for receipt in micu_receipts],
        "task_ids_by_role": task_ids_by_role,
        "launch_receipt": {
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "sqlite_initialized_fresh": True,
            "artifact_root_bound": True,
            "blob_root_bound": True,
            "sandbox_root_bound": True,
            "sandbox_runtime_identity": sandbox_preflight_identity,
        },
    }

    formal_operations = [
        *controlled_records.values(),
        normalization_operation,
        hmm_reference_selection_operation,
        scoring_reference_selection_operation,
        scoring_input_assembly_operation,
        pre_uniprot_score_filter_operation,
    ]
    for optional_calculation in (
        post_uniprot_filter_operation,
        upstream_empty_materialization_operation,
        empty_target_scoring_operation,
        empty_membership_operation,
    ):
        if optional_calculation is not None:
            formal_operations.append(optional_calculation)
    formal_operations.extend(
        [
            motif_operation,
            candidate_filter_operation,
            similarity_operation,
        ]
    )
    operation_roles = {
        **{
            role: operation.operation_id
            for role, operation in operation_by_role.items()
        },
        "hmm_reference_set_selection": hmm_reference_selection_operation[
            "operation_id"
        ],
        "scoring_reference_selection": scoring_reference_selection_operation[
            "operation_id"
        ],
        "scoring_input_assembly": scoring_input_assembly_operation[
            "operation_id"
        ],
        "pre_uniprot_score_filter": pre_uniprot_score_filter_operation[
            "operation_id"
        ],
        "motif_score": motif_operation["operation_id"],
        "candidate_filter": candidate_filter_operation["operation_id"],
        "similarity": similarity_operation["operation_id"],
    }
    if post_uniprot_filter_operation is not None:
        operation_roles["post_uniprot_filter"] = post_uniprot_filter_operation[
            "operation_id"
        ]
    if upstream_empty_materialization_operation is not None:
        operation_roles["upstream_empty_materialization"] = (
            upstream_empty_materialization_operation["operation_id"]
        )
    if empty_target_scoring_operation is not None:
        operation_roles["empty_target_scoring_materialization"] = (
            empty_target_scoring_operation["operation_id"]
        )
    if empty_membership_operation is not None:
        operation_roles["empty_membership"] = empty_membership_operation[
            "operation_id"
        ]
    artifact_roles = {
        "literature_evidence": str(literature_evidence.record["artifact_id"]),
        "ncbi_provider_sequences": str(
            ncbi_provider_sequences.record["artifact_id"]
        ),
        "hmm_reference_set": str(hmm_reference_set.record["artifact_id"]),
        "scoring_reference": str(scoring_reference.record["artifact_id"]),
        "scoring_input": str(scoring_input.record["artifact_id"]),
        "reference_alignment": str(reference_alignment.record["artifact_id"]),
        "hmm_model": str(hmm_model.record["artifact_id"]),
        "hmmer_response": str(hmmer_response.record["artifact_id"]),
        "hmmer_parsed_hits": str(hmmer_parsed_hits.record["artifact_id"]),
        "hmmer_score_filtered_accessions": str(
            score_filtered_accessions.record["artifact_id"]
        ),
        "post_uniprot_filtered_hits": str(filtered_hits.record["artifact_id"]),
        "target_sequences": str(target_sequences.record["artifact_id"]),
        "scoring_alignment": str(scoring_alignment.record["artifact_id"]),
        "motif_scores": str(motif_scores.record["artifact_id"]),
        "candidates": str(candidates.record["artifact_id"]),
        "cdhit_membership": str(cdhit_membership.record["artifact_id"]),
        "graph_nodes": str(graph_nodes.record["artifact_id"]),
        "graph_edges": str(graph_edges.record["artifact_id"]),
        "graph_manifest": str(graph_manifest.record["artifact_id"]),
    }
    if uniprot_sequences is not None and uniprot_metadata is not None:
        artifact_roles.update(
            {
                "uniprot_sequences": str(
                    uniprot_sequences.record["artifact_id"]
                ),
                "uniprot_metadata": str(uniprot_metadata.record["artifact_id"]),
            }
        )
    provider_dependency: dict[str, object] = {
        "upstream_provider_record_id": provider_by_name["ebi_hmmer"][
            "provider_record_id"
        ],
        "upstream_response_artifact_ids": [
            str(hmmer_response.record["artifact_id"])
        ],
        "derivation_id": aox_hmmer.CONTRACT_ID,
        "derivation_operation_id": pre_uniprot_score_filter_operation[
            "operation_id"
        ],
        "parsed_hit_artifact_id": str(hmmer_parsed_hits.record["artifact_id"]),
        "parsed_hit_artifact_digest": hmmer_parsed_hits.content_digest,
        "derived_accession_artifact_id": str(
            score_filtered_accessions.record["artifact_id"]
        ),
        "derived_accession_artifact_digest": (
            score_filtered_accessions.content_digest
        ),
        "derivation_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "derivation_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "derived_accessions": derived_accessions,
        "derived_accessions_digest": canonical_digest(derived_accessions),
        "downstream_provider_record_id": provider_by_name["uniprot"][
            "provider_record_id"
        ],
    }
    empty_branch: dict[str, object] | None = None
    if not candidate_count:
        empty_stage = (
            "pre_uniprot_score_filter"
            if hmmer_upstream_empty
            else "sequence_length_join"
            if not target_sequences_nonempty
            else "motif_candidate_filter"
        )
        trigger_copy = (
            score_filtered_accessions
            if hmmer_upstream_empty
            else target_sequences
            if not target_sequences_nonempty
            else candidates
        )
        empty_branch = {
            "schema_id": "aox_empty_branch@1",
            "stage": empty_stage,
            "reason": empty_result_reason or "",
            "trigger_artifact_id": str(trigger_copy.record["artifact_id"]),
            "trigger_artifact_digest": trigger_copy.content_digest,
            "observed_count_before": (
                score_filter_result.input_row_count
                if hmmer_upstream_empty
                else len(sequence_join_result.input_hits)
                if not target_sequences_nonempty and sequence_join_result is not None
                else len(sequence_join_result.hits)
                if sequence_join_result is not None
                else 0
            ),
            "observed_count_after": 0,
            "derivation_operation_id": (
                pre_uniprot_score_filter_operation["operation_id"]
                if hmmer_upstream_empty
                else post_uniprot_filter_operation["operation_id"]
                if not target_sequences_nonempty
                and post_uniprot_filter_operation is not None
                else candidate_filter_operation["operation_id"]
            ),
            "skip_provider_record_id": (
                provider_by_name["uniprot"]["provider_record_id"]
                if hmmer_upstream_empty
                else None
            ),
            "omitted_controlled_roles": [
                role
                for role in ("uniprot_fetch", "candidate_alignment", "cdhit")
                if role not in operation_by_role
            ],
            "empty_materialization_operation_id": (
                upstream_empty_materialization_operation["operation_id"]
                if upstream_empty_materialization_operation is not None
                else empty_target_scoring_operation["operation_id"]
                if empty_target_scoring_operation is not None
                else None
            ),
            "empty_membership_operation_id": (
                None
                if empty_membership_operation is None
                else empty_membership_operation["operation_id"]
            ),
        }
    if hmmer_upstream_empty:
        provider_dependency.update(
            {
                "terminal_empty_reason": upstream_empty_reason,
                "skip_receipt_digest": uniprot_provider_record[
                    "skip_receipt_digest"
                ],
                "skip_artifact_id": uniprot_provider_record["artifact_ids"][0],
            }
        )
    sequence_join_check: dict[str, object] | None = None
    if sequence_join_result is not None:
        assert uniprot_sequences is not None
        assert uniprot_metadata is not None
        sequence_join_check = {
            "score_filtered_artifact_id": str(
                score_filtered_accessions.record["artifact_id"]
            ),
            "uniprot_fasta_artifact_id": str(
                uniprot_sequences.record["artifact_id"]
            ),
            "uniprot_metadata_artifact_id": str(
                uniprot_metadata.record["artifact_id"]
            ),
            "filtered_hits_artifact_id": str(filtered_hits.record["artifact_id"]),
            "target_fasta_artifact_id": str(target_sequences.record["artifact_id"]),
            "contract_id": aox_sequence_join.CONTRACT_ID,
            "contract_digest": aox_sequence_join.CONTRACT_DIGEST,
            "implementation_digest": aox_sequence_join.IMPLEMENTATION_DIGEST,
            "metadata": sequence_join_result.metadata(),
        }
    evidence: dict[str, Any] = {
        "provider_identities": provider_records,
        "engine_invocations": [pubmed_engine_invocation],
        "toolchain_identities": toolchain_records,
        "known_positive_probe": probe_attestation.probe,
        "product_path": product_path,
        "approvals": [*probe_attestation.approvals, *approval_records],
        "operations": [*probe_attestation.operations, *formal_operations],
        "tasks": task_records,
        "artifacts": [
            *probe_attestation.artifacts,
            *(copy.record for copy in copies.values()),
            *(
                []
                if upstream_empty_artifact_record is None
                else [upstream_empty_artifact_record]
            ),
            report_artifact,
        ],
        "report": report_record,
        "final_answer": {
            "message_id": final_message.message_id,
            "content": final_message.content,
        },
        "scientific_checks": {
            "scoring": {
                "alignment_artifact_id": str(scoring_alignment.record["artifact_id"]),
                "scored_artifact_id": str(motif_scores.record["artifact_id"]),
                "scoring_contract_id": aox_motif.CONTRACT_ID,
                "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
                "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
                "input_digest": scoring_result.alignment.input_digest,
            },
            **(
                {}
                if sequence_join_check is None
                else {"sequence_join": sequence_join_check}
            ),
            "similarity": {
                "candidate_fasta_artifact_id": str(candidates.record["artifact_id"]),
                "membership_artifact_id": str(cdhit_membership.record["artifact_id"]),
                "nodes_artifact_id": str(graph_nodes.record["artifact_id"]),
                "edges_artifact_id": str(graph_edges.record["artifact_id"]),
                "manifest_artifact_id": str(graph_manifest.record["artifact_id"]),
                "threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
                "empty_result_reason": empty_result_reason,
                "calculation_id": aox_similarity.CALCULATION_ID,
                "calculation_digest": aox_similarity.CALCULATION_DIGEST,
                "implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
                "candidate_fasta_digest": graph_result.sequences.input_digest,
                "membership_digest": graph_result.membership.input_digest,
            },
            "aox_chain": {
                "literature_provider_record_id": pubmed_provider["provider_record_id"],
                "operation_roles": operation_roles,
                "provider_dependencies": [provider_dependency],
                "artifact_roles": artifact_roles,
                "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
                "empty_branch": empty_branch,
            },
        },
        "warnings": [],
        "degradations": [],
        "scientific_outcome": {
            "status": "discovered" if candidate_count else "empty",
            "candidate_count": candidate_count,
            "empty_result_reason": empty_result_reason,
            "cutover_eligible": True,
        },
        "fault_injection": None,
    }
    _attach_product_receipts(
        context,
        evidence,
        report_publish_events=report_publish_events,
    )
    return evidence


def _copy_fault_target(
    context: AttemptRunContext,
    *,
    artifact: SessionArtifactRecord,
    fault: FaultInjectionReceipt,
) -> CatalogArtifactCopy:
    source = Path(artifact.storage_uri)
    if not source.is_file() or source.is_symlink():
        raise LiveProductPathError(
            "fault_target_blob_invalid",
            "controlled fault target is not a sealed regular-file blob",
        )
    resolved_source = source.resolve()
    if context.roots.blob_root.resolve() not in resolved_source.parents:
        raise LiveProductPathError(
            "fault_target_blob_unbound",
            "controlled fault target is outside the attempt-scoped blob root",
        )
    if artifact.relative_path != fault.target_relative_path:
        raise LiveProductPathError(
            "fault_target_catalog_path_mismatch",
            "controlled fault receipt does not match the catalog target path",
        )
    content = source.read_bytes()
    if (
        not content
        or fault.byte_offset < 0
        or fault.byte_offset >= len(content)
        or _sha256(content) != fault.after_digest
        or str(
            dict(artifact.metadata or {}).get("content_digest")
            or dict(artifact.metadata or {}).get("sealed_digest")
            or ""
        )
        != fault.before_digest
    ):
        raise LiveProductPathError(
            "fault_target_digest_mismatch",
            "controlled fault target bytes do not match the before/after receipt",
        )
    restored = bytearray(content)
    restored[fault.byte_offset] ^= 1
    if _sha256(bytes(restored)) != fault.before_digest:
        raise LiveProductPathError(
            "fault_target_not_single_bit_flip",
            "controlled fault target cannot be restored by the declared one-bit flip",
        )
    relative_path = (
        f"formal/fault/{_safe_id(artifact.artifact_id)}/"
        f"{_safe_id(PurePosixPath(artifact.relative_path).name)}"
    )
    _write_sealed_bytes(context.roots.artifact_root, relative_path, content)
    return CatalogArtifactCopy(
        record={
            "artifact_id": artifact.artifact_id,
            "relative_path": relative_path,
            "scope": "formal",
            "origin": "operation",
            "kind": artifact.kind.value,
            "provenance": {
                "operation_id": fault.source_operation_id,
                "catalog_artifact_id": artifact.artifact_id,
                "catalog_relative_path": artifact.relative_path,
                "controlled_fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
            },
        },
        content=content,
        content_digest=fault.after_digest,
    )


def _fault_operation_input_refs(
    context: AttemptRunContext,
    operation: ControlledOperation,
    *,
    artifacts: Mapping[str, SessionArtifactRecord],
    target_artifact_id: str,
    before_digest: str,
    copies: dict[str, CatalogArtifactCopy],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for artifact_id, declared_digest in zip(
        operation.input_artifact_ids,
        operation.input_artifact_digests,
        strict=True,
    ):
        if artifact_id == target_artifact_id:
            if declared_digest != before_digest:
                raise LiveProductPathError(
                    "fault_failed_input_digest_mismatch",
                    "failed controlled operation was not bound to the pre-fault digest",
                )
            refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
            continue
        artifact = _require_artifact(artifacts, artifact_id)
        copied = _copy_catalog_artifact(
            context,
            artifact,
            scope="formal",
            origin="input",
            provenance={"operation_input_for": operation.operation_id},
            cache=copies,
        )
        if copied.content_digest != declared_digest:
            raise LiveProductPathError(
                "fault_controlled_input_digest_mismatch",
                "unmodified fault-path input differs from its S12 digest",
            )
        refs.append({"artifact_id": artifact_id, "content_digest": declared_digest})
    return refs


def _collect_fault_evidence(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    api_receipts: tuple[PublicApiReceipt, ...],
    health: Mapping[str, object],
    probe: SessionDriveResult,
    formal: SessionDriveResult,
    fault: FaultInjectionReceipt,
) -> dict[str, Any]:
    probe_attestation = _collect_probe_attestation(
        context,
        provider=provider,
        probe=probe,
    )
    with provider.read() as scope:
        repositories = scope.repositories
        operations = {
            operation.operation_id: operation
            for operation in repositories.controlled_operations.list_by_session(
                formal.session_id
            )
        }
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(formal.session_id)
        }
        artifacts = {
            artifact.artifact_id: artifact
            for artifact in repositories.artifacts.list_by_session(formal.session_id)
        }
    source_operation = operations.get(fault.source_operation_id)
    failed_operation = operations.get(fault.terminal_failure_operation_id)
    target_artifact = artifacts.get(fault.target_artifact_id)
    if (
        source_operation is None
        or failed_operation is None
        or target_artifact is None
        or source_operation.operation_id == failed_operation.operation_id
        or source_operation.status.value != "completed"
        or source_operation.selected_backend != "provider_http"
        or failed_operation.status.value not in _FAILED_OPERATION_STATUSES
        or failed_operation.error_code != "artifact_content_digest_mismatch"
        or fault.target_artifact_id
        not in _operation_output_artifact_ids(source_operation)
        or fault.target_artifact_id not in failed_operation.input_artifact_ids
    ):
        raise LiveProductPathError(
            "controlled_fault_operation_receipt_invalid",
            "controlled byte flip does not bind distinct source and terminal failure operations",
        )
    copies: dict[str, CatalogArtifactCopy] = {}
    target_copy = _copy_fault_target(
        context,
        artifact=target_artifact,
        fault=fault,
    )
    source_inputs = _fault_operation_input_refs(
        context,
        source_operation,
        artifacts=artifacts,
        target_artifact_id=fault.target_artifact_id,
        before_digest=fault.before_digest,
        copies=copies,
    )
    failed_inputs = _fault_operation_input_refs(
        context,
        failed_operation,
        artifacts=artifacts,
        target_artifact_id=fault.target_artifact_id,
        before_digest=fault.before_digest,
        copies=copies,
    )
    source_parameters = _provider_request_parameters(
        context,
        source_operation,
        artifacts=artifacts,
    )
    source_record = operation_evidence_record(
        source_operation,
        scope="formal",
        inputs=source_inputs,
        outputs=[
            {
                "artifact_id": fault.target_artifact_id,
                "content_digest": fault.before_digest,
            }
        ],
        parameters=source_parameters,
    )
    failed_record = operation_evidence_record(
        failed_operation,
        scope="formal",
        inputs=failed_inputs,
        outputs=[],
    )
    provider_names = {
        "ncbi_fetch_proteins": "ncbi",
        "hmmer_search": "ebi_hmmer",
        "uniprot_fetch": "uniprot",
    }
    provider_name = provider_names.get(str(source_operation.function_name or ""))
    if provider_name is None:
        raise LiveProductPathError(
            "controlled_fault_provider_invalid",
            "controlled fault source is not a recognized provider operation",
        )
    invocation_id = _operation_backend_run_id(source_record)
    blocker_payload = {
        "schema_id": LIVE_BLOCKER_SCHEMA_ID,
        "runner_schema_id": LIVE_RUNNER_SCHEMA_ID,
        "attempt_id": context.roots.attempt_id,
        "attempt_kind": "fault",
        "observed_at": datetime.now(UTC).isoformat(),
        "failure_code": "artifact_content_digest_mismatch",
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "target_artifact_id": fault.target_artifact_id,
        "source_operation_id": source_operation.operation_id,
        "terminal_failure_operation_id": failed_operation.operation_id,
        "health": dict(health),
        "formal": formal.safe_summary(),
    }
    report_content = canonical_json_bytes(blocker_payload) + b"\n"
    report_artifact_id = f"art_fault_report_{_safe_id(context.roots.attempt_id)}"
    report_path = "formal/fault/fail-closed-report.json"
    _write_sealed_bytes(context.roots.artifact_root, report_path, report_content)
    evidence_relative_path = str(target_copy.record["relative_path"])
    fault_payload = {
        "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "target_artifact_id": fault.target_artifact_id,
        "relative_path": evidence_relative_path,
        "byte_offset": fault.byte_offset,
        "before_digest": fault.before_digest,
        "after_digest": fault.after_digest,
        "source_operation_id": source_operation.operation_id,
        "terminal_failure_operation_id": failed_operation.operation_id,
        "failure_code": "artifact_content_digest_mismatch",
        "reached_target_seam": True,
        "expected_failure_observed": True,
    }
    return {
        "provider_identities": [
            {
                "provider_record_id": f"provider_record_fault_{_safe_id(source_operation.operation_id)}",
                "provider": provider_name,
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": invocation_id,
                "operation_id": source_operation.operation_id,
                "cache_hit": False,
                "request_digest": source_operation.params_digest,
                "response_digest": fault.before_digest,
                "artifact_ids": [fault.target_artifact_id],
                "source_ref_ids": [],
            }
        ],
        "engine_invocations": [],
        "toolchain_identities": [],
        "known_positive_probe": probe_attestation.probe,
        "product_path": _product_path_failure_receipt(
            context,
            formal=formal,
            api_receipts=api_receipts,
        ),
        "approvals": [
            *probe_attestation.approvals,
            _approval_record(source_operation, approvals),
            _approval_record(failed_operation, approvals),
        ],
        "operations": [
            *probe_attestation.operations,
            source_record,
            failed_record,
        ],
        "tasks": [],
        "artifacts": [
            *probe_attestation.artifacts,
            *(copy.record for copy in copies.values()),
            target_copy.record,
            {
                "artifact_id": report_artifact_id,
                "relative_path": report_path,
                "scope": "formal",
                "origin": "report",
                "kind": "failure_evidence",
                "provenance": {
                    "producer": LIVE_RUNNER_SCHEMA_ID,
                    "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                },
            },
        ],
        "report": {
            "report_id": f"report_fault_{_safe_id(context.roots.attempt_id)}",
            "status": "failed_evidence",
            "cutover_eligible": False,
            "content_artifact_id": report_artifact_id,
            "content_digest": _sha256(report_content),
            "artifact_ids": [report_artifact_id, fault.target_artifact_id],
            "source_ref_ids": [],
            "claim_source_links": [],
        },
        "final_answer": {
            "message_id": f"msg_fault_{_safe_id(context.roots.attempt_id)}",
            "content": (
                "AOX blank-world attempt failed closed at the controlled "
                "artifact_content_digest_mismatch seam."
            ),
        },
        "scientific_checks": {},
        "warnings": [],
        "degradations": ["controlled_fault_injection"],
        "scientific_outcome": {
            "status": "failed",
            "failure_code": "artifact_content_digest_mismatch",
            "cutover_eligible": False,
        },
        "fault_injection": fault_payload,
    }


def _collect_probe_attestation(
    context: AttemptRunContext,
    *,
    provider: SQLiteRepositoryProvider,
    probe: SessionDriveResult,
) -> ProbeAttestation:
    with provider.read() as scope:
        repositories = scope.repositories
        operations = tuple(
            repositories.controlled_operations.list_by_session(probe.session_id)
        )
        approvals = {
            approval.approval_id: approval
            for approval in repositories.approvals.list_by_session(probe.session_id)
        }
        artifact_map = {
            artifact.artifact_id: artifact
            for artifact in repositories.artifacts.list_by_session(probe.session_id)
        }
        sandbox_runs = {
            run.sandbox_run_id: run
            for run in repositories.sandbox_runs.list_by_session(probe.session_id)
        }
        tasks = tuple(repositories.tasks.list_by_session(probe.session_id))
        documents = tuple(
            repositories.engine_documents.list_by_session(probe.session_id)
        )

    operation_specs = (
        ("ncbi_fetch", "bio", "ncbi_fetch_proteins"),
        ("reference_alignment", "bio_tools", "mafft"),
        ("hmm_build", "bio_tools", "hmmbuild"),
        ("uniprot_fetch", "bio", "uniprot_fetch"),
        ("candidate_cluster", "bio_tools", "cdhit"),
        ("candidate_alignment", "bio_tools", "hmmalign"),
    )
    operation_by_role: dict[str, ControlledOperation] = {}
    for role, sdk_module, function_name in operation_specs:
        matches = [
            operation
            for operation in operations
            if operation.sdk_module == sdk_module
            and operation.function_name == function_name
        ]
        if len(matches) != 1:
            raise LiveProductPathError(
                "probe_operation_receipt_ambiguous",
                "known-positive probe requires exactly one operation for every fixed role",
                details={
                    "role": role,
                    "sdk_method": f"{sdk_module}.{function_name}",
                    "operation_count": len(matches),
                },
            )
        if matches[0].status.value != "completed":
            raise LiveProductPathError(
                "probe_operation_not_completed",
                "an attempted known-positive probe operation did not complete",
                details={"role": role, "status": matches[0].status.value},
            )
        operation_by_role[role] = matches[0]
    expected_operation_ids = {
        operation.operation_id for operation in operation_by_role.values()
    }
    if len(operations) != len(operation_specs) or {
        operation.operation_id for operation in operations
    } != expected_operation_ids:
        raise LiveProductPathError(
            "probe_operation_surface_invalid",
            "known-positive probe must contain exactly two provider and four HPC operations",
            details={"observed_operation_count": len(operations)},
        )

    task_ids = {str(operation.task_id or "") for operation in operations}
    sandbox_run_ids = {str(operation.sandbox_run_id or "") for operation in operations}
    sandbox_workspace_ids = {
        str(operation.sandbox_workspace_id or "") for operation in operations
    }
    source_snapshot_ids = {
        str(operation.source_snapshot_artifact_id or "") for operation in operations
    }
    source_snapshot_digests = {
        str(operation.source_snapshot_digest or "") for operation in operations
    }
    hpc_workspace_ids = {
        str(operation.hpc_workspace_id or "")
        for role, operation in operation_by_role.items()
        if role
        in {
            "reference_alignment",
            "hmm_build",
            "candidate_cluster",
            "candidate_alignment",
        }
    }
    if any(
        len(values) != 1 or "" in values
        for values in (
            task_ids,
            sandbox_run_ids,
            sandbox_workspace_ids,
            source_snapshot_ids,
            source_snapshot_digests,
            hpc_workspace_ids,
        )
    ):
        raise LiveProductPathError(
            "probe_isolation_scope_invalid",
            "probe operations must share one task, sandbox run/workspace, source snapshot, and HPC workspace",
        )
    task_id = next(iter(task_ids))
    matching_tasks = [task for task in tasks if str(task.task_id) == task_id]
    finish_documents = [
        document
        for document in documents
        if document.document_kind == "task_finish"
        and str(dict(document.payload or {}).get("task_id") or "") == task_id
    ]
    if (
        len(tasks) != 1
        or len(matching_tasks) != 1
        or matching_tasks[0].status.value != "completed"
        or len(finish_documents) != 1
        or dict(finish_documents[0].payload or {}).get("status") != "completed"
    ):
        raise LiveProductPathError(
            "probe_task_finish_invalid",
            "known-positive probe requires one explicitly finished execution task",
        )
    sandbox_run_id = next(iter(sandbox_run_ids))
    sandbox_run = sandbox_runs.get(sandbox_run_id)
    if (
        sandbox_run is None
        or sandbox_run.status.value != "completed"
        or str(sandbox_run.source_snapshot_artifact_id or "")
        != next(iter(source_snapshot_ids))
        or str(sandbox_run.source_tree_digest or "")
        != next(iter(source_snapshot_digests))
    ):
        raise LiveProductPathError(
            "probe_sandbox_receipt_invalid",
            "probe operations do not resolve to one completed persistent sandbox run",
        )

    copies: dict[str, CatalogArtifactCopy] = {}
    output_copies: dict[str, list[CatalogArtifactCopy]] = {}
    operation_records: list[dict[str, object]] = []
    provider_parameters: dict[str, dict[str, object]] = {}
    provider_response_digests: dict[str, str] = {}
    for role, _, _ in operation_specs:
        operation = operation_by_role[role]
        inputs = _declared_operation_input_refs(
            context,
            operation,
            artifacts=artifact_map,
            copies=copies,
            scope="probe",
        )
        if role in {"ncbi_fetch", "uniprot_fetch"}:
            parameters = _provider_request_parameters(
                context,
                operation,
                artifacts=artifact_map,
            )
            selected_outputs, response_digest = _provider_output_copies(
                context,
                operation,
                artifacts=artifact_map,
                copies=copies,
                scope="probe",
            )
            provider_parameters[role] = parameters
            provider_response_digests[role] = response_digest
        else:
            parameters = None
            selected_outputs = _tool_output_copies(
                context,
                operation,
                artifacts=artifact_map,
                copies=copies,
                scope="probe",
            )
        output_copies[role] = selected_outputs
        operation_records.append(
            operation_evidence_record(
                operation,
                scope="probe",
                inputs=inputs,
                outputs=[_artifact_ref(copy) for copy in selected_outputs],
                parameters=parameters,
            )
        )

    source_snapshot = _copy_catalog_artifact(
        context,
        _require_artifact(artifact_map, next(iter(source_snapshot_ids))),
        scope="probe",
        origin="sandbox_run",
        provenance={
            "probe_id": KNOWN_POSITIVE_PROBE_ID,
            "producer": "sandbox_source_snapshot",
            "sandbox_run_id": sandbox_run_id,
            "source_snapshot_digest": next(iter(source_snapshot_digests)),
        },
        cache=copies,
    )
    ncbi_raw = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"ncbi_efetch.response.json"},
        identity="probe_ncbi_raw_response",
    )
    ncbi_fasta = _copy_with_name(
        output_copies["ncbi_fetch"],
        names={"proteins.fasta"},
        identity="probe_ncbi_fasta",
    )
    uniprot_raw = _copy_with_name(
        output_copies["uniprot_fetch"],
        names={"pages.json"},
        identity="probe_uniprot_raw_response",
    )
    uniprot_fasta = _copy_with_name(
        output_copies["uniprot_fetch"],
        names={"sequences.fasta"},
        identity="probe_uniprot_fasta",
    )
    reference_alignment = _copy_with_name(
        output_copies["reference_alignment"],
        names={"alignment.fasta"},
        identity="probe_reference_alignment",
    )
    hmm_model = _copy_with_name(
        output_copies["hmm_build"],
        names={"model.hmm"},
        identity="probe_hmm_model",
    )
    clustered_fasta = _copy_with_name(
        output_copies["candidate_cluster"],
        names={"clustered.fasta"},
        identity="probe_clustered_fasta",
    )
    cluster_membership = _copy_with_name(
        output_copies["candidate_cluster"],
        names={"clusters.csv"},
        identity="probe_cluster_membership",
    )
    candidate_alignment = _copy_with_name(
        output_copies["candidate_alignment"],
        names={"aligned.fasta"},
        identity="probe_candidate_alignment",
    )

    expected_provider_accessions = {
        "ncbi_fetch": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
        "uniprot_fetch": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
    }
    for role, expected_accessions in expected_provider_accessions.items():
        observed_accessions = [
            str(value).strip().upper()
            for value in provider_parameters[role].get("accessions") or []
        ]
        if observed_accessions != expected_accessions:
            raise LiveProductPathError(
                "probe_provider_identity_mismatch",
                "known-positive provider request does not use the fixed globin identities",
                details={
                    "role": role,
                    "expected": expected_accessions,
                    "actual": observed_accessions,
                },
            )

    operation_record_by_role = {
        role: record for (role, _, _), record in zip(operation_specs, operation_records)
    }

    def require_exact_inputs(role: str, expected: list[CatalogArtifactCopy]) -> None:
        actual = {
            str(ref.get("artifact_id") or ""): str(
                ref.get("content_digest") or ""
            )
            for ref in operation_record_by_role[role].get("inputs") or []
            if isinstance(ref, dict)
        }
        wanted = {
            str(copy.record["artifact_id"]): copy.content_digest for copy in expected
        }
        if actual != wanted:
            raise LiveProductPathError(
                "probe_artifact_lineage_invalid",
                "known-positive probe operation inputs do not match the fixed provider/tool DAG",
                details={"role": role},
            )

    require_exact_inputs("reference_alignment", [ncbi_fasta])
    require_exact_inputs("hmm_build", [reference_alignment])
    require_exact_inputs("candidate_cluster", [uniprot_fasta])
    require_exact_inputs("candidate_alignment", [hmm_model, clustered_fasta])

    try:
        ncbi_sequences = aox_similarity.parse_candidate_fasta(ncbi_fasta.content)
        uniprot_sequences = aox_similarity.parse_candidate_fasta(
            uniprot_fasta.content
        )
        clustered_sequences = aox_similarity.parse_candidate_fasta(
            clustered_fasta.content
        )
        membership = aox_similarity.parse_cdhit_membership_csv(
            cluster_membership.content
        )
    except ValueError as exc:
        raise LiveProductPathError(
            "probe_scientific_artifact_invalid",
            "known-positive provider or CD-HIT output is not offline-parseable",
        ) from exc
    ncbi_ids = [record.sequence_id for record in ncbi_sequences.records]
    uniprot_ids = [record.sequence_id for record in uniprot_sequences.records]
    clustered_ids = [record.sequence_id for record in clustered_sequences.records]
    ncbi_sequence_digests = sorted(
        record.sequence_digest for record in ncbi_sequences.records
    )
    uniprot_sequence_digests = sorted(
        record.sequence_digest for record in uniprot_sequences.records
    )
    membership_member_ids = sorted(row.member_id for row in membership.rows)
    if (
        ncbi_ids != list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)
        or uniprot_ids != list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
        or sorted(clustered_ids) != sorted(uniprot_ids)
        or membership_member_ids != sorted(uniprot_ids)
        or len(membership.rows) != 2
        or not all(row.is_representative for row in membership.rows)
        or ncbi_sequence_digests != uniprot_sequence_digests
        or not hmm_model.content.startswith(b"HMMER")
    ):
        raise LiveProductPathError(
            "probe_known_positive_result_invalid",
            "sealed globin identities do not close through both providers and the real toolchain",
        )

    def aligned_sequence_ids(content: bytes) -> list[str]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LiveProductPathError(
                "probe_alignment_not_utf8",
                "known-positive alignment output is not UTF-8",
            ) from exc
        return [
            line[1:].strip().split(maxsplit=1)[0]
            for line in text.splitlines()
            if line.startswith(">")
        ]

    if (
        aligned_sequence_ids(reference_alignment.content)
        != list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)
        or aligned_sequence_ids(candidate_alignment.content)
        != list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
    ):
        raise LiveProductPathError(
            "probe_alignment_identity_mismatch",
            "MAFFT/HMMalign outputs do not preserve the fixed globin member identities",
        )
    cdhit_metadata = dict(
        artifact_map[str(clustered_fasta.record["artifact_id"])].metadata or {}
    )
    cdhit_tool_inputs = dict(cdhit_metadata.get("tool_inputs") or {})
    if (
        float(cdhit_tool_inputs.get("identity") or 0.0) != 1.0
        or cdhit_tool_inputs.get("mode") != "protein"
    ):
        raise LiveProductPathError(
            "probe_cdhit_parameters_invalid",
            "known-positive CD-HIT operation must use identity 1.0 and protein mode",
        )

    sandbox_run_by_id = {sandbox_run_id: sandbox_run}
    provider_receipts: list[dict[str, object]] = []
    for role, provider_name, raw_copy, fasta_copy in (
        ("ncbi_fetch", "ncbi", ncbi_raw, ncbi_fasta),
        ("uniprot_fetch", "uniprot", uniprot_raw, uniprot_fasta),
    ):
        receipt = _controlled_provider_receipt(
            provider_name=provider_name,
            operation=operation_by_role[role],
            operation_record=operation_record_by_role[role],
            output_copies=output_copies[role],
            response_digest=provider_response_digests[role],
        )
        receipt.update(
            {
                "raw_response_artifact_id": str(raw_copy.record["artifact_id"]),
                "parsed_fasta_artifact_id": str(fasta_copy.record["artifact_id"]),
            }
        )
        provider_receipts.append(receipt)
    toolchain_receipts: list[dict[str, object]] = []
    for role, tool_name in (
        ("reference_alignment", "mafft"),
        ("hmm_build", "hmmbuild"),
        ("candidate_cluster", "cd-hit"),
        ("candidate_alignment", "hmmalign"),
    ):
        receipt = _toolchain_receipt(
            tool_name=tool_name,
            operation=operation_by_role[role],
            operation_record=operation_record_by_role[role],
            sandbox_runs=sandbox_run_by_id,
        )
        receipt["artifact_ids"] = [
            str(copy.record["artifact_id"]) for copy in output_copies[role]
        ]
        if role == "candidate_cluster":
            receipt["parameters"] = {"identity": 1.0, "mode": "protein"}
        toolchain_receipts.append(receipt)

    approval_records = [
        _approval_record(operation_by_role[role], approvals)
        for role, _, _ in operation_specs
    ]
    if len({record["approval_id"] for record in approval_records}) != 6:
        raise LiveProductPathError(
            "probe_approval_receipt_missing",
            "known-positive probe requires one distinct approval per controlled operation",
        )
    provider_by_name = {
        str(receipt["provider"]): receipt for receipt in provider_receipts
    }
    toolchain_by_tool = {
        str(receipt["tool"]): receipt for receipt in toolchain_receipts
    }
    artifact_roles = {
        "source_snapshot": str(source_snapshot.record["artifact_id"]),
        "ncbi_raw_response": str(ncbi_raw.record["artifact_id"]),
        "ncbi_fasta": str(ncbi_fasta.record["artifact_id"]),
        "mafft_alignment": str(reference_alignment.record["artifact_id"]),
        "hmm_model": str(hmm_model.record["artifact_id"]),
        "uniprot_raw_response": str(uniprot_raw.record["artifact_id"]),
        "uniprot_fasta": str(uniprot_fasta.record["artifact_id"]),
        "cdhit_clustered_fasta": str(clustered_fasta.record["artifact_id"]),
        "cdhit_membership": str(cluster_membership.record["artifact_id"]),
        "hmmalign_alignment": str(candidate_alignment.record["artifact_id"]),
    }
    operation_roles = {
        role: operation.operation_id
        for role, operation in operation_by_role.items()
    }
    probe_payload = {
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "passed",
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": sorted(copies),
        "operation_roles": operation_roles,
        "artifact_roles": artifact_roles,
        "isolation": {
            "schema_id": "aox_known_positive_probe_isolation@1",
            "session_id": probe.session_id,
            "task_id": task_id,
            "task_finish_ref": str(finish_documents[0].document_id),
            "sandbox_run_id": sandbox_run_id,
            "sandbox_workspace_id": next(iter(sandbox_workspace_ids)),
            "source_snapshot_artifact_id": str(source_snapshot.record["artifact_id"]),
            "source_snapshot_digest": next(iter(source_snapshot_digests)),
            "source_snapshot_artifact_digest": source_snapshot.content_digest,
            "hpc_workspace_id": next(iter(hpc_workspace_ids)),
            "controlled_operation_count": 6,
        },
        "known_positive_identity": {
            "ncbi_accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "uniprot_accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
            "cross_provider_sequence_digest": canonical_digest(
                ncbi_sequence_digests
            ),
        },
        "checks": [
            {
                "check_id": "ncbi_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["ncbi"]["provider_record_id"],
            },
            {
                "check_id": "uniprot_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["uniprot"]["provider_record_id"],
            },
            *(
                {
                    "check_id": f"hpc_{tool_name.replace('-', '')}",
                    "category": "hpc",
                    "status": "passed",
                    "receipt_id": toolchain_by_tool[tool_name][
                        "toolchain_record_id"
                    ],
                }
                for tool_name in ("mafft", "hmmbuild", "cd-hit", "hmmalign")
            ),
        ],
        "provider_receipts": provider_receipts,
        "toolchain_receipts": toolchain_receipts,
    }
    return ProbeAttestation(
        probe=probe_payload,
        approvals=tuple(approval_records),
        operations=tuple(operation_records),
        artifacts=tuple(copy.record for copy in copies.values()),
    )


def _failed_probe_payload(probe: SessionDriveResult | None) -> dict[str, object]:
    state = "failed" if probe is None else probe.state
    return {
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "failed",
        "failure_code": (
            "probe_not_started" if probe is None else "probe_attestation_unavailable"
        ),
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": [],
        "checks": [
            *(
                {
                    "check_id": check_id,
                    "category": "provider",
                    "status": "failed",
                }
                for check_id in (
                    "ncbi_globin_pair",
                    "uniprot_globin_pair",
                )
            ),
            *(
                {
                    "check_id": check_id,
                    "category": "hpc",
                    "status": "failed",
                }
                for check_id in (
                    "hpc_mafft",
                    "hpc_hmmbuild",
                    "hpc_cdhit",
                    "hpc_hmmalign",
                )
            ),
        ],
        "observed_state": state,
    }


def _product_path_failure_receipt(
    context: AttemptRunContext,
    *,
    formal: SessionDriveResult | None,
    api_receipts: tuple[PublicApiReceipt, ...],
) -> dict[str, object]:
    entry_messages = []
    assistant_messages = []
    if formal is not None:
        conversation = list(formal.workspace.get("conversation") or [])
        entry_messages = [
            dict(item)
            for item in conversation
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        assistant_messages = [
            dict(item)
            for item in conversation
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]
    return {
        "entry_message_count": len(entry_messages),
        "canonical_api_only": True,
        "cache_hit": False,
        "participant_roles": [],
        "session_id": None if formal is None else formal.session_id,
        "entry_message_id": None
        if not entry_messages
        else entry_messages[0].get("message_id"),
        "final_master_response_id": None
        if not assistant_messages
        else assistant_messages[-1].get("message_id"),
        "public_api_receipt_digest": canonical_digest(
            [item.to_dict() for item in api_receipts]
        ),
        "launch_receipt": {
            "root_identity": context.roots.proof["root_identity"],
            "hpc_workspace_label": context.roots.hpc_workspace_label,
            "sqlite_initialized_fresh": context.roots.sqlite_path.is_file(),
            "artifact_root_bound": context.roots.artifact_root.is_dir(),
            "blob_root_bound": context.roots.blob_root.is_dir(),
            "sandbox_root_bound": context.roots.sandbox_root.is_dir(),
        },
    }


def _safe_health(health: Mapping[str, object]) -> dict[str, object]:
    components = health.get("components")
    statuses = {
        str(name): str(dict(value).get("status") or "unknown")
        for name, value in (components.items() if isinstance(components, dict) else [])
        if isinstance(value, dict)
    }
    sandbox_component = (
        dict(components.get("sandbox") or {})
        if isinstance(components, dict)
        else {}
    )
    sandbox_details = dict(sandbox_component.get("details") or {})
    sandbox_runtime_identity = {
        key: value
        for key, value in {
            "image_digest": sandbox_details.get("image_digest"),
            "pipeline_sdk_digest": sandbox_details.get("pipeline_sdk_digest"),
            "runtime_identity_digest": sandbox_details.get(
                "runtime_identity_digest"
            ),
            "sandbox_protocol_version": sandbox_details.get(
                "sandbox_protocol_version"
            ),
        }.items()
        if isinstance(value, str) and value
    }
    return {
        "schema_version": health.get("schema_version"),
        "status": health.get("status"),
        "deployment_profile": health.get("deployment_profile"),
        "storage_profile": health.get("storage_profile"),
        "component_statuses": statuses,
        "sandbox_runtime_identity": sandbox_runtime_identity,
    }


def _write_sealed_bytes(root: Path, relative_path: str, content: bytes) -> None:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise LiveProductPathError(
            "collector_artifact_path_invalid",
            "collector artifact path is not a safe relative path",
        )
    target = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_root not in resolved_target.parents or target.exists():
        raise LiveProductPathError(
            "collector_artifact_append_only",
            "collector artifact target escapes its root or already exists",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def _safe_message(error: LiveProductPathError) -> str:
    return str(error).split(": ", 1)[-1][:500]


def _safe_id(value: str) -> str:
    return _SAFE_ID.sub("_", value).strip("._-")[:100] or "attempt"


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "LIVE_RUNNER_SCHEMA_ID",
    "LiveAoxAttemptRunner",
    "LiveProductPathError",
    "PublicApiReceipt",
    "SessionDriveResult",
    "controlled_operation_identity_material",
    "operation_evidence_record",
]
