from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from typing import Protocol

import httpx
from openzyme_client import ClientHttpRequest
from openzyme_client import ClientHttpResponse
from openzyme_client import OpenZymeV2Client
from openzyme_client import OpenZymeClientContractError
from openzyme_client import VerifiedServerContract
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS
from openzyme_contracts import (
    FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS,
)
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION
from openzyme_contracts import (
    WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS,
)
from openzyme_contracts import WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS
from openzyme_contracts.identity import require_digest
from openzyme_contracts.identity import require_identifier


CLI_ADMISSION_OBSERVATION_SCHEMA_VERSION = "openzyme_cli_admission_observation@1"


class HttpResponseProtocol(Protocol):
    status_code: int
    content: bytes
    headers: Any


class HttpSessionProtocol(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> HttpResponseProtocol: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionClientTransport:
    session: HttpSessionProtocol

    def send(self, request: ClientHttpRequest) -> ClientHttpResponse:
        response = self.session.request(
            request.method,
            request.path,
            headers=dict(request.headers),
            content=request.body,
        )
        return ClientHttpResponse(
            status_code=response.status_code,
            media_type=str(response.headers.get("content-type") or ""),
            body=bytes(response.content),
            headers={str(name): str(value) for name, value in response.headers.items()},
        )


class HostApiV2Client:
    """Thin CLI delivery wrapper around the shared exact @2 client guard."""

    def __init__(
        self,
        base_url: str,
        *,
        expected_release: LayeredReleaseIdentity,
        auth_token: str | None = None,
        session: HttpSessionProtocol | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session: HttpSessionProtocol = session or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=30.0,
        )
        self._authorization = (
            f"Bearer {auth_token}" if auth_token else "Bearer local-dev"
        )
        self._expected_release = expected_release
        self._client = OpenZymeV2Client(
            transport=SessionClientTransport(self._session),
            expected_release=expected_release,
        )

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def inspect_workspace(
        self,
        session_id: str,
    ) -> tuple[FileWorkspacePublicV2, VerifiedServerContract]:
        projection, verified = self._client.inspect_workspace(
            session_id=session_id,
            authorization=self._authorization,
        )
        _require_current_resident_projection(projection)
        return projection, verified

    def create_session(
        self,
        *,
        project_id: str,
        session_id: str,
        objective: str,
        title: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "session_id": session_id,
            "objective": objective,
            "title": title or objective,
        }
        response = self._client.bootstrap_session(
            authorization=self._authorization,
            idempotency_key=idempotency_key,
            body=json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        _require_admission_status(response.status_code, operation="Session bootstrap")
        receipt = _decode_mutation_body(response.body)
        canonical, _ = self.inspect_workspace(session_id)
        return _admission_observation(
            response_status=response.status_code,
            receipt=receipt,
            canonical=canonical,
        )

    def send_json_mutation(
        self,
        *,
        session_id: str,
        path: str,
        idempotency_key: str,
        payload: dict[str, Any],
        require_resident_ready: bool = False,
    ) -> dict[str, Any]:
        """Admit one mutation, retain its receipt, then re-inspect canonical truth."""

        inspected, verified = self.inspect_workspace(session_id)
        if require_resident_ready:
            _require_resident_ready(inspected)
        return self._send_inspected_json_mutation(
            session_id=session_id,
            path=path,
            idempotency_key=idempotency_key,
            payload=payload,
            inspected=inspected,
            verified=verified,
        )

    def _send_inspected_json_mutation(
        self,
        *,
        session_id: str,
        path: str,
        idempotency_key: str,
        payload: dict[str, Any],
        inspected: FileWorkspacePublicV2,
        verified: VerifiedServerContract,
        receipt_validator: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """POST against one already-inspected exact projection, then re-inspect."""

        response = self._client.send_mutation(
            method="POST",
            path=path,
            authorization=self._authorization,
            idempotency_key=idempotency_key,
            body=json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            verified_contract=verified,
            capability_binding_digest=verified.capability_binding_digest,
            affordance_snapshot_digest=verified.affordance_snapshot_digest,
        )
        _require_admission_status(response.status_code, operation=path)
        receipt = _decode_mutation_body(response.body)
        if receipt_validator is not None:
            receipt_validator(receipt)
        canonical, _ = self.inspect_workspace(session_id)
        return _admission_observation(
            response_status=response.status_code,
            receipt=receipt,
            canonical=canonical,
        )

    def reconcile_workspace_provisioning(
        self,
        session_id: str,
        *,
        expected_intent_version: int | None,
        claim_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Admit one exact dispatch-in-doubt observation without running it inline."""

        if (
            not isinstance(claim_seconds, int)
            or isinstance(claim_seconds, bool)
            or not 1 <= claim_seconds <= 86_400
        ):
            raise OpenZymeClientContractError(
                "cli_workspace_reconciliation_claim_invalid",
                "claim seconds must be between 1 and 86400",
            )
        inspected, verified = self.inspect_workspace(session_id)
        provisioning = _require_workspace_recovery_fact(
            inspected,
            expected_next_action="reconcile_workspace_provisioning",
        )
        intent_id, intent_digest, intent_state_version = _workspace_intent_identity(
            provisioning
        )
        _require_optional_exact_version(
            expected_intent_version,
            current=intent_state_version,
            field_name="expected_intent_version",
        )
        if (
            provisioning.get("status") != "blocked"
            or provisioning.get("effect_certainty") != "dispatch_in_doubt"
            or provisioning.get("mutation_applied") is not None
            or provisioning.get("fallback_performed") is not False
            or provisioning.get("retry_permitted") is not False
            or provisioning.get("reconcile_required") is not True
        ):
            raise OpenZymeClientContractError(
                "cli_workspace_reconciliation_not_admissible",
                "only the exact unresolved dispatch-in-doubt occurrence may be reconciled",
            )
        reconciliation = provisioning.get("reconciliation")
        if reconciliation is not None and (
            not isinstance(reconciliation, Mapping)
            or reconciliation.get("status") != "blocked"
            or reconciliation.get("reconcile_required") is not True
            or reconciliation.get("blocked_intent_state_version")
            != intent_state_version
            or reconciliation.get("blocked_intent_digest") != intent_digest
        ):
            raise OpenZymeClientContractError(
                "cli_workspace_reconciliation_not_admissible",
                "the current reconciliation occurrence is not ready for another observation",
            )
        expected_attempt = 1
        expected_parent_reconciliation_id: str | None = None
        if isinstance(reconciliation, Mapping):
            previous_attempt = reconciliation.get("attempt")
            previous_id = reconciliation.get("reconciliation_id")
            if (
                not isinstance(previous_attempt, int)
                or isinstance(previous_attempt, bool)
                or previous_attempt < 1
                or not isinstance(previous_id, str)
            ):
                raise OpenZymeClientContractError(
                    "cli_workspace_reconciliation_not_admissible",
                    "the previous reconciliation lineage is incomplete",
                )
            expected_attempt = previous_attempt + 1
            expected_parent_reconciliation_id = previous_id

        def require_reconciliation_receipt(receipt: Mapping[str, Any]) -> None:
            _require_workspace_reconciliation_admission_receipt(
                receipt,
                intent_id=intent_id,
                intent_digest=intent_digest,
                expected_intent_version=intent_state_version,
                expected_attempt=expected_attempt,
                expected_parent_reconciliation_id=(expected_parent_reconciliation_id),
                requested_claim_seconds=claim_seconds,
            )

        return self._send_inspected_json_mutation(
            session_id=session_id,
            path=(f"/v3/sessions/{session_id}/workspace/provisioning/reconcile"),
            idempotency_key=idempotency_key,
            payload={
                "intent_id": intent_id,
                "intent_digest": intent_digest,
                "expected_intent_version": intent_state_version,
                "claim_seconds": claim_seconds,
            },
            inspected=inspected,
            verified=verified,
            receipt_validator=require_reconciliation_receipt,
        )

    def create_workspace_provisioning_successor(
        self,
        session_id: str,
        *,
        expected_failed_intent_version: int | None,
        resolved_reconciliation_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create one pending successor generation without running provisioning."""

        inspected, verified = self.inspect_workspace(session_id)
        provisioning = _require_workspace_recovery_fact(
            inspected,
            expected_next_action="create_successor_workspace_generation",
        )
        failed_intent_id, failed_intent_digest, failed_intent_version = (
            _workspace_intent_identity(provisioning)
        )
        workspace_id, failed_generation = _workspace_successor_source_identity(
            provisioning
        )
        _require_optional_exact_version(
            expected_failed_intent_version,
            current=failed_intent_version,
            field_name="expected_failed_intent_version",
        )
        if (
            provisioning.get("status") != "blocked"
            or provisioning.get("fallback_performed") is not False
            or provisioning.get("retry_permitted") is not False
        ):
            raise OpenZymeClientContractError(
                "cli_workspace_successor_not_admissible",
                "successor admission requires one exact failed occurrence",
            )
        reconciliation = provisioning.get("reconciliation")
        projected_reconciliation_id: str | None = None
        if reconciliation is None:
            if provisioning.get("reconcile_required") is not False:
                raise OpenZymeClientContractError(
                    "cli_workspace_successor_not_admissible",
                    "an uncertain provisioning occurrence must be reconciled first",
                )
        elif (
            isinstance(reconciliation, Mapping)
            and reconciliation.get("status") == "blocked"
            and reconciliation.get("reconcile_required") is False
            and reconciliation.get("settled_at") is not None
            and reconciliation.get("blocked_intent_state_version")
            == failed_intent_version
            and reconciliation.get("blocked_intent_digest") == failed_intent_digest
            and isinstance(reconciliation.get("reconciliation_id"), str)
        ):
            projected_reconciliation_id = str(reconciliation["reconciliation_id"])
        else:
            raise OpenZymeClientContractError(
                "cli_workspace_successor_not_admissible",
                "the reconciliation lineage is not terminal and diagnosed",
            )
        if (
            resolved_reconciliation_id is not None
            and resolved_reconciliation_id != projected_reconciliation_id
        ):
            raise OpenZymeClientContractError(
                "cli_workspace_recovery_fence_stale",
                "explicit resolved reconciliation identity differs from projection truth",
            )
        selected_reconciliation_id = (
            projected_reconciliation_id
            if resolved_reconciliation_id is None
            else resolved_reconciliation_id
        )

        def require_successor_receipt(receipt: Mapping[str, Any]) -> None:
            _require_workspace_successor_admission_receipt(
                receipt,
                failed_intent_id=failed_intent_id,
                resolved_reconciliation_id=selected_reconciliation_id,
                workspace_id=workspace_id,
                failed_generation=failed_generation,
            )

        return self._send_inspected_json_mutation(
            session_id=session_id,
            path=(f"/v3/sessions/{session_id}/workspace/provisioning/successor"),
            idempotency_key=idempotency_key,
            payload={
                "failed_intent_id": failed_intent_id,
                "failed_intent_digest": failed_intent_digest,
                "expected_failed_intent_version": failed_intent_version,
                "resolved_reconciliation_id": selected_reconciliation_id,
            },
            inspected=inspected,
            verified=verified,
            receipt_validator=require_successor_receipt,
        )

    def post_message(
        self,
        session_id: str,
        *,
        message: str,
        task_id: str | None,
        lane_id: str | None,
        workflow_refs: tuple[str, ...] = (),
        skill_keys: tuple[str, ...] = (),
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not message or message != message.strip() or len(message) > 131_072:
            raise OpenZymeClientContractError(
                "cli_message_invalid",
                "message must be bounded, non-empty and trimmed",
            )
        if workflow_refs and skill_keys:
            raise OpenZymeClientContractError(
                "cli_workflow_selection_ambiguous",
                "--workflow-ref and compatibility --skill-key are mutually exclusive",
            )
        for field_name, values in (
            ("workflow_refs", workflow_refs),
            ("skill_keys", skill_keys),
        ):
            if any(
                not isinstance(item, str) or not item or item != item.strip()
                for item in values
            ) or values != tuple(sorted(set(values))):
                raise OpenZymeClientContractError(
                    "cli_workflow_selection_invalid",
                    f"{field_name} must be sorted, unique exact identifiers",
                )
            try:
                for item in values:
                    require_identifier(item, field_name=field_name)
            except ValueError as exc:
                raise OpenZymeClientContractError(
                    "cli_workflow_selection_invalid",
                    f"{field_name} contains an invalid exact identifier",
                ) from exc
        for field_name, value in (("task_id", task_id), ("lane_id", lane_id)):
            if value is None:
                continue
            try:
                require_identifier(value, field_name=field_name)
            except ValueError as exc:
                raise OpenZymeClientContractError(
                    "cli_message_scope_invalid",
                    f"{field_name} must be one exact identifier",
                ) from exc
        payload: dict[str, Any] = {"message": message}
        if task_id is not None:
            payload["task_id"] = task_id
        if lane_id is not None:
            payload["lane_id"] = lane_id
        if workflow_refs:
            payload["workflow_refs"] = list(workflow_refs)
        elif skill_keys:
            payload["skill_keys"] = list(skill_keys)
        else:
            payload["workflow_refs"] = []
        return self.send_json_mutation(
            session_id=session_id,
            path=f"/v3/sessions/{session_id}/messages",
            idempotency_key=idempotency_key,
            payload=payload,
            require_resident_ready=True,
        )

    def drain_runtime(
        self,
        session_id: str,
        *,
        max_signals: int,
        max_steps_per_agent: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(max_signals, int)
            or isinstance(max_signals, bool)
            or max_signals < 1
            or not isinstance(max_steps_per_agent, int)
            or isinstance(max_steps_per_agent, bool)
            or max_steps_per_agent < 1
        ):
            raise OpenZymeClientContractError(
                "cli_runtime_budget_invalid",
                "runtime drain budgets must be positive integers",
            )
        return self.send_json_mutation(
            session_id=session_id,
            path=f"/v3/sessions/{session_id}/runtime/drain",
            idempotency_key=idempotency_key,
            payload={
                "max_signals": max_signals,
                "max_steps_per_agent": max_steps_per_agent,
                "auto_enqueue_ready_tasks": False,
            },
            require_resident_ready=True,
        )

    def decide_approval(
        self,
        session_id: str,
        *,
        approval_id: str,
        decision: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        require_identifier(approval_id, field_name="approval_id")
        if decision not in {"approved", "rejected"}:
            raise OpenZymeClientContractError(
                "cli_approval_decision_invalid",
                "approval decision must be approved or rejected",
            )
        projection, _ = self.inspect_workspace(session_id)
        _require_resident_ready(projection)
        matches = tuple(
            item
            for item in projection.core.payload["approvals"]
            if isinstance(item, Mapping) and item.get("approval_id") == approval_id
        )
        if len(matches) != 1 or matches[0].get("status") != "pending":
            raise OpenZymeClientContractError(
                "cli_pending_approval_not_found",
                "one exact pending approval is required",
            )
        intent_digest = matches[0].get("intent_digest")
        if not isinstance(intent_digest, str):
            raise OpenZymeClientContractError(
                "cli_approval_intent_incompatible",
                "pending approval lacks its exact intent digest",
            )
        require_digest(intent_digest, field_name="intent_digest")
        return self.send_json_mutation(
            session_id=session_id,
            path=(f"/v3/sessions/{session_id}/approvals/{approval_id}/decision"),
            idempotency_key=idempotency_key,
            payload={
                "decision": decision,
                "intent_digest": intent_digest,
                "resolution_ref": idempotency_key,
            },
            require_resident_ready=True,
        )

    def inspect_runtime_command(
        self,
        session_id: str,
        *,
        command_id: str,
    ) -> dict[str, Any]:
        """Poll one exact command without replaying the runtime drain."""

        require_identifier(session_id, field_name="session_id")
        require_identifier(command_id, field_name="command_id")
        response = self._session.request(
            "GET",
            f"/v3/sessions/{session_id}/runtime/commands/{command_id}",
            headers={
                "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                "Authorization": self._authorization,
                "OpenZyme-Workspace-Contract": (
                    FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                ),
            },
            content=None,
        )
        if response.status_code != 200:
            raise OpenZymeClientContractError(
                "cli_runtime_command_inspection_failed",
                f"runtime command inspection returned HTTP {response.status_code}",
            )
        if str(response.headers.get("content-type") or "") != (
            FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
        ):
            raise OpenZymeClientContractError(
                "cli_runtime_command_media_type_mismatch",
                "runtime command response is not exact file_workspace_public@2",
            )
        observed_headers = {
            str(name).strip().lower(): str(value).strip()
            for name, value in response.headers.items()
        }
        for header_name, expected in (
            ("openzyme-workspace-contract", FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION),
            ("openzyme-release-digest", self._expected_release.release_digest),
            (
                "openzyme-public-contract-digest",
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
            ),
        ):
            if observed_headers.get(header_name) != expected:
                raise OpenZymeClientContractError(
                    "cli_runtime_command_identity_mismatch",
                    f"runtime command response header {header_name!r} is stale",
                )
        for header_name in (
            "openzyme-projection-digest",
            "openzyme-capability-binding-digest",
            "openzyme-affordance-snapshot-digest",
        ):
            try:
                require_digest(
                    observed_headers.get(header_name, ""),
                    field_name=header_name,
                )
            except ValueError as exc:
                raise OpenZymeClientContractError(
                    "cli_runtime_command_identity_mismatch",
                    f"runtime command response header {header_name!r} is invalid",
                ) from exc
        payload = _decode_query_body(response.content)
        if set(payload) != {
            "schema_version",
            "session_id",
            "command",
            "projection_digest",
            "mutation_applied",
            "fallback_performed",
        }:
            raise OpenZymeClientContractError(
                "cli_runtime_command_payload_invalid",
                "runtime command status response fields are not closed",
            )
        command = payload.get("command")
        if (
            payload.get("schema_version") != "runtime_command_status@1"
            or payload.get("session_id") != session_id
            or payload.get("projection_digest")
            != observed_headers["openzyme-projection-digest"]
            or payload.get("mutation_applied") is not False
            or payload.get("fallback_performed") is not False
            or not isinstance(command, Mapping)
            or command.get("command_id") != command_id
        ):
            raise OpenZymeClientContractError(
                "cli_runtime_command_payload_invalid",
                "runtime command status does not match the requested exact identity",
            )
        try:
            _require_runtime_command_record(command, session_id=session_id)
        except (TypeError, ValueError) as exc:
            raise OpenZymeClientContractError(
                "cli_runtime_command_payload_invalid",
                "runtime command status contains an invalid closed command record",
            ) from exc
        return payload


def _require_admission_status(status_code: int, *, operation: str) -> None:
    if status_code != 202:
        raise OpenZymeClientContractError(
            "cli_admission_status_invalid",
            f"{operation} returned HTTP {status_code}; exact admission requires 202",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        )


def _require_runtime_command_record(
    command: Mapping[str, Any],
    *,
    session_id: str,
) -> None:
    if set(command) != FILE_WORKSPACE_RUNTIME_COMMAND_PUBLIC_FIELDS:
        raise ValueError("runtime command fields are closed")
    if (
        command["schema_version"] != "runtime_command_public@1"
        or command["session_id"] != session_id
        or command["command_type"] != "runtime.drain"
        or command["status"]
        not in {"accepted", "claimed", "completed", "failed", "locked", "cancelled"}
        or not isinstance(command["auto_enqueue_ready_tasks"], bool)
    ):
        raise ValueError("runtime command identity or state is invalid")
    for field_name in ("command_id", "session_id", "idempotency_key", "accepted_at"):
        value = command[field_name]
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        require_identifier(value, field_name=field_name)
    request_digest = command["request_digest"]
    if not isinstance(request_digest, str):
        raise TypeError("request_digest must be a string")
    require_digest(request_digest, field_name="request_digest")
    for field_name in ("max_signals", "max_steps_per_agent", "state_version"):
        value = command[field_name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{field_name} must be positive")
    fence = command["fencing_token"]
    if not isinstance(fence, int) or isinstance(fence, bool) or fence < 0:
        raise ValueError("fencing_token must be non-negative")
    for field_name in (
        "claim_owner",
        "lease_expires_at",
        "failure_id",
        "diagnostic_id",
        "error_code",
        "started_at",
        "completed_at",
    ):
        value = command[field_name]
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or null")
        require_identifier(value, field_name=field_name)
    for field_name in ("safe_error_summary", "safe_retry_hint"):
        value = command[field_name]
        if value is not None and (not isinstance(value, str) or len(value) > 8_192):
            raise TypeError(f"{field_name} must be bounded text or null")
    summary = command["bounded_outcome_summary"]
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise TypeError("bounded_outcome_summary must be an object or null")
        if set(summary) != FILE_WORKSPACE_RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_FIELDS:
            raise ValueError("bounded_outcome_summary fields are closed")
        if (
            summary["schema_version"]
            != RUNTIME_COMMAND_OUTCOME_SUMMARY_PUBLIC_SCHEMA_VERSION
        ):
            raise ValueError("bounded_outcome_summary schema is invalid")
        for field_name in ("processed_signals", "turn_count"):
            value = summary[field_name]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 1_024
            ):
                raise ValueError(f"bounded_outcome_summary {field_name} is invalid")
        if summary["turn_count"] != summary["processed_signals"]:
            raise ValueError("bounded_outcome_summary turn count is inconsistent")
        turns_digest = summary["turns_digest"]
        if not isinstance(turns_digest, str):
            raise TypeError("bounded_outcome_summary turns_digest must be a string")
        require_digest(turns_digest, field_name="turns_digest")
        for field_name in (
            "runtime_executed",
            "task_transition_performed",
            "fallback_performed",
        ):
            if not isinstance(summary[field_name], bool):
                raise TypeError(f"bounded_outcome_summary {field_name} must be boolean")
        if summary["fallback_performed"]:
            raise ValueError("bounded_outcome_summary cannot report fallback")
        if summary["runtime_executed"] != (summary["processed_signals"] > 0):
            raise ValueError("bounded_outcome_summary execution fact is inconsistent")
    if command["status"] == "claimed" and any(
        command[field_name] is None
        for field_name in ("claim_owner", "lease_expires_at", "started_at")
    ):
        raise ValueError("claimed runtime command lacks claim identity")
    if command["status"] in {"completed", "failed", "locked", "cancelled"} and (
        command["completed_at"] is None
    ):
        raise ValueError("terminal runtime command lacks completion identity")
    if command["status"] == "failed":
        if command["failure_id"] is None or command["diagnostic_id"] is None:
            raise ValueError("failed runtime command lacks failure identities")
    elif command["failure_id"] is not None or command["diagnostic_id"] is not None:
        raise ValueError("non-failed runtime command carries failure identities")


def _require_workspace_recovery_fact(
    projection: FileWorkspacePublicV2,
    *,
    expected_next_action: str,
) -> Mapping[str, Any]:
    session = projection.core.payload["session"]
    workspace = projection.core.payload["workspace"]
    readiness = session.get("resident_readiness")
    provisioning = workspace.get("provisioning")
    if (
        not isinstance(readiness, Mapping)
        or readiness.get("readiness") != "blocked"
        or readiness.get("next_action") != expected_next_action
        or not isinstance(provisioning, Mapping)
        or provisioning.get("next_action") != expected_next_action
    ):
        raise OpenZymeClientContractError(
            "cli_workspace_recovery_not_admissible",
            "workspace recovery action differs from the canonical blocked projection",
        )
    return provisioning


def _workspace_intent_identity(
    provisioning: Mapping[str, Any],
) -> tuple[str, str, int]:
    intent_id = provisioning.get("intent_id")
    intent_digest = provisioning.get("intent_digest")
    intent_state_version = provisioning.get("intent_state_version")
    try:
        if not isinstance(intent_id, str) or not isinstance(intent_digest, str):
            raise TypeError("workspace intent identity must be strings")
        require_identifier(intent_id, field_name="intent_id")
        require_digest(intent_digest, field_name="intent_digest")
        if (
            not isinstance(intent_state_version, int)
            or isinstance(intent_state_version, bool)
            or intent_state_version < 1
        ):
            raise ValueError("intent_state_version must be positive")
    except (TypeError, ValueError) as exc:
        raise OpenZymeClientContractError(
            "cli_workspace_recovery_state_incompatible",
            "workspace recovery projection lacks an exact intent fence",
        ) from exc
    return intent_id, intent_digest, intent_state_version


def _workspace_successor_source_identity(
    provisioning: Mapping[str, Any],
) -> tuple[str, int]:
    workspace_id = provisioning.get("workspace_id")
    generation = provisioning.get("workspace_generation")
    try:
        if not isinstance(workspace_id, str):
            raise TypeError("workspace_id must be a string")
        require_identifier(workspace_id, field_name="workspace_id")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise ValueError("workspace_generation must be positive")
    except (TypeError, ValueError) as exc:
        raise OpenZymeClientContractError(
            "cli_workspace_recovery_state_incompatible",
            "workspace recovery projection lacks an exact generation fence",
        ) from exc
    return workspace_id, generation


def _require_optional_exact_version(
    value: int | None,
    *,
    current: int,
    field_name: str,
) -> None:
    if value is None:
        return
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value != current
    ):
        raise OpenZymeClientContractError(
            "cli_workspace_recovery_fence_stale",
            f"{field_name} differs from the current projection fence",
        )


def _require_workspace_successor_admission_receipt(
    receipt: Mapping[str, Any],
    *,
    failed_intent_id: str,
    resolved_reconciliation_id: str | None,
    workspace_id: str,
    failed_generation: int,
) -> None:
    result = receipt.get("result")
    successor_intent_id = (
        result.get("successor_intent_id") if isinstance(result, Mapping) else None
    )
    successor_identity_valid = False
    try:
        if not isinstance(successor_intent_id, str):
            raise TypeError("successor_intent_id must be a string")
        require_identifier(
            successor_intent_id,
            field_name="successor_intent_id",
        )
        if successor_intent_id == failed_intent_id:
            raise ValueError("successor intent must have a fresh identity")
        successor_identity_valid = True
    except (TypeError, ValueError):
        successor_identity_valid = False
    admitted_only = (
        isinstance(result, Mapping)
        and set(result) == WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS
        and receipt.get("operation") == "replace_failed_generation"
        and receipt.get("mutation_applied") is True
        and receipt.get("effect_certainty") == "no_effect"
        and receipt.get("fallback_performed") is False
        and successor_identity_valid
        and result.get("failed_intent_id") == failed_intent_id
        and result.get("resolved_reconciliation_id") == resolved_reconciliation_id
        and result.get("workspace_id") == workspace_id
        and result.get("generation") == failed_generation + 1
        and result.get("readiness") == "provisioning"
        and result.get("successor_intent_created") is True
        and result.get("workspace_generation_reserved") is True
        and result.get("workspace_provisioning_enqueued") is True
        and result.get("adapter_invoked") is False
        and result.get("external_effect_performed") is False
        and result.get("runtime_executed") is False
        and result.get("task_transition_performed") is False
        and result.get("fallback_performed") is False
    )
    if admitted_only:
        return
    mutation_applied = receipt.get("mutation_applied")
    effect_certainty = receipt.get("effect_certainty")
    raise OpenZymeClientContractError(
        "cli_workspace_successor_admission_receipt_invalid",
        "Host successor response is not one admission-only receipt",
        mutation_applied=(
            mutation_applied if isinstance(mutation_applied, bool) else None
        ),
        effect_certainty=(
            effect_certainty
            if isinstance(effect_certainty, str)
            else "dispatch_in_doubt"
        ),
    )


def _require_workspace_reconciliation_admission_receipt(
    receipt: Mapping[str, Any],
    *,
    intent_id: str,
    intent_digest: str,
    expected_intent_version: int,
    expected_attempt: int,
    expected_parent_reconciliation_id: str | None,
    requested_claim_seconds: int,
) -> None:
    result = receipt.get("result")
    identities_valid = False
    attempt = result.get("attempt") if isinstance(result, Mapping) else None
    parent_reconciliation_id = (
        result.get("parent_reconciliation_id") if isinstance(result, Mapping) else None
    )
    try:
        if not isinstance(result, Mapping):
            raise TypeError("result must be an object")
        for field_name in ("reconciliation_id", "source_receipt_id"):
            value = result.get(field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            require_identifier(value, field_name=field_name)
        for field_name in (
            "reconciliation_digest",
            "source_receipt_digest",
            "dispatch_receipt_digest",
        ):
            value = result.get(field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            require_digest(value, field_name=field_name)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be positive")
        if attempt == 1:
            if parent_reconciliation_id is not None:
                raise ValueError("first reconciliation cannot have a parent")
        else:
            if not isinstance(parent_reconciliation_id, str):
                raise TypeError("later reconciliation requires a parent")
            require_identifier(
                parent_reconciliation_id,
                field_name="parent_reconciliation_id",
            )
        reconciliation_id = result.get("reconciliation_id")
        if reconciliation_id in {intent_id, parent_reconciliation_id}:
            raise ValueError("reconciliation identity must be fresh")
        identities_valid = True
    except (TypeError, ValueError):
        identities_valid = False
    admitted_only = (
        isinstance(result, Mapping)
        and set(result) == WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
        and isinstance(receipt.get("mutation_applied"), bool)
        and receipt.get("operation") == "admit_reconciliation"
        and receipt.get("effect_certainty") == "no_effect"
        and receipt.get("fallback_performed") is False
        and identities_valid
        and result.get("intent_id") == intent_id
        and result.get("blocked_intent_digest") == intent_digest
        and result.get("blocked_intent_state_version") == expected_intent_version
        and result.get("attempt") == expected_attempt
        and result.get("parent_reconciliation_id") == expected_parent_reconciliation_id
        and result.get("requested_claim_seconds") == requested_claim_seconds
        and result.get("status") == "pending"
        and result.get("readiness") == "blocked"
        and result.get("historical_intent_preserved") is True
        and result.get("reconciliation_enqueued") is True
        and result.get("workspace_provisioning_reconciliation_enqueued") is True
        and result.get("adapter_invoked") is False
        and result.get("external_effect_performed") is False
        and result.get("runtime_executed") is False
        and result.get("task_transition_performed") is False
        and result.get("fallback_performed") is False
    )
    if admitted_only:
        return
    mutation_applied = receipt.get("mutation_applied")
    effect_certainty = receipt.get("effect_certainty")
    raise OpenZymeClientContractError(
        "cli_workspace_reconciliation_admission_receipt_invalid",
        "Host reconciliation response is not one admission-only receipt",
        mutation_applied=(
            mutation_applied if isinstance(mutation_applied, bool) else None
        ),
        effect_certainty=(
            effect_certainty
            if isinstance(effect_certainty, str)
            else "dispatch_in_doubt"
        ),
    )


def _require_resident_ready(projection: FileWorkspacePublicV2) -> None:
    session = projection.core.payload["session"]
    readiness = session.get("resident_readiness")
    state = readiness.get("readiness") if isinstance(readiness, Mapping) else None
    if state == "ready":
        return
    next_action = (
        readiness.get("next_action") if isinstance(readiness, Mapping) else None
    )
    raise OpenZymeClientContractError(
        "cli_resident_teammate_not_ready",
        "resident teammate is "
        f"{state or 'incompatible'}; next_action={next_action or 'inspect_workspace'}",
    )


def _require_current_resident_projection(projection: FileWorkspacePublicV2) -> None:
    core = projection.core.payload
    session = core["session"]
    workspace = core["workspace"]
    runtime = core["runtime"]
    conversation = core["conversation"]
    reflection = core["tool_reflection"]
    readiness = session.get("resident_readiness")
    provisioning = workspace.get("provisioning")
    workflow_authority = runtime.get("workflow_authority")
    transcript = conversation.get("transcript")
    tool_exposure = reflection.get("tool_exposure")
    compatible = (
        isinstance(readiness, Mapping)
        and readiness.get("schema_version") == "resident_teammate_readiness@1"
        and isinstance(provisioning, Mapping)
        and provisioning.get("schema_version") == "workspace_provisioning_public@2"
        and isinstance(workflow_authority, Mapping)
        and workflow_authority.get("schema_version")
        == "workflow_authority_projection@1"
        and isinstance(runtime.get("commands"), tuple)
        and isinstance(runtime.get("outcomes"), tuple)
        and isinstance(transcript, Mapping)
        and transcript.get("schema_version") == "ordered_transcript@1"
        and isinstance(tool_exposure, Mapping)
        and tool_exposure.get("schema_version") == "tool_exposure_public@1"
        and isinstance(core["failures"].get("observations"), tuple)
    )
    if not compatible:
        raise OpenZymeClientContractError(
            "cli_resident_teammate_state_incompatible",
            "Session lacks one or more current resident teammate inner contracts",
        )
    failure_id = readiness.get("failure_id")
    if failure_id is None:
        return
    failures = core["failures"].get("observations")
    assert isinstance(failures, tuple)
    matches = tuple(
        item
        for item in failures
        if isinstance(item, Mapping) and item.get("failure_id") == failure_id
    )
    if len(matches) != 1:
        raise OpenZymeClientContractError(
            "cli_resident_teammate_state_incompatible",
            "resident teammate blocker does not resolve to one public failure",
        )


def _admission_observation(
    *,
    response_status: int,
    receipt: dict[str, Any],
    canonical: FileWorkspacePublicV2,
) -> dict[str, Any]:
    return {
        "schema_version": CLI_ADMISSION_OBSERVATION_SCHEMA_VERSION,
        "response_status": response_status,
        "receipt": receipt,
        "canonical_workspace": canonical.to_dict(),
    }


def load_expected_release_identity(path: Path) -> LayeredReleaseIdentity:
    """Load one operator-pinned, closed @2 release identity without fallback."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return LayeredReleaseIdentity.from_dict(value)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise OpenZymeClientContractError(
            "cli_release_identity_invalid",
            "configured release identity file is missing or violates the closed contract",
        ) from exc


def _decode_mutation_body(body: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenZymeClientContractError(
            "cli_mutation_response_payload_invalid",
            "Host mutation response is not valid UTF-8 JSON",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        ) from exc
    if not isinstance(decoded, dict):
        raise OpenZymeClientContractError(
            "cli_mutation_response_payload_invalid",
            "Host mutation response is not one JSON object",
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
        )
    return decoded


def _decode_query_body(body: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenZymeClientContractError(
            "cli_query_response_payload_invalid",
            "Host query response is not valid UTF-8 JSON",
        ) from exc
    if not isinstance(decoded, dict):
        raise OpenZymeClientContractError(
            "cli_query_response_payload_invalid",
            "Host query response is not one JSON object",
        )
    return decoded


__all__ = [
    "HostApiV2Client",
    "HttpSessionProtocol",
    "SessionClientTransport",
    "load_expected_release_identity",
]
