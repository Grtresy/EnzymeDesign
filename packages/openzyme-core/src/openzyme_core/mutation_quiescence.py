from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import AbstractContextManager
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import base64
import re
import sqlite3
from typing import Any
from typing import Mapping
from uuid import uuid4

from openzyme_domain import MutationScope
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriter
from openzyme_domain import MutationWriterKind
from openzyme_domain import MutationWriterState
from openzyme_domain import QuiescenceReceipt
from openzyme_domain import QuiescenceSnapshot

from .mutation_authority import HOST_MUTATION_COVERAGE_DIGEST
from .mutation_authority import HOST_MUTATION_COVERAGE_ENTRIES
from .mutation_authority import HOST_MUTATION_GLOBAL_EXCLUSIONS
from .mutation_authority import HOST_MUTATION_POLICY_DIGEST
from .mutation_authority import HOST_MUTATION_POLICY_ID
from .mutation_authority import HOST_MUTATION_RECEIPT_EVIDENCE_SCHEMA_ID
from .mutation_authority import HOST_MUTATION_SNAPSHOT_SCHEMA_ID
from .mutation_authority import MAX_QUIESCENCE_SNAPSHOT_BYTES
from .mutation_authority import MAX_QUIESCENCE_SNAPSHOT_ROWS
from .mutation_authority import MutationCoverageEntry
from .mutation_authority import MutationResourceCategory
from .mutation_authority import MutationWriteAuthority
from .mutation_authority import bind_mutation_write_authority
from .mutation_authority import canonical_digest
from .mutation_authority import canonical_json_bytes
from .mutation_authority import current_mutation_write_authority
from .mutation_authority import suspend_mutation_write_authority
from .reliability_repositories import CanonicalRecordConflictError
from .repositories import CoreRepositories


_AUTHORITY_TABLES = frozenset(
    {
        "mutation_scope_records",
        "mutation_writer_records",
        "quiescence_receipt_records",
        "quiescence_snapshot_records",
    }
)
_SAFE_BLOCKER_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class MutationScopeError(RuntimeError):
    retryable = False

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.details = {
            "boundary": "host_mutation_quiescence",
            "disposition": "fail_closed",
            "blocker_code": code,
        }


@dataclass(frozen=True, slots=True)
class QuiescenceIssueResult:
    scope: MutationScope
    receipt: QuiescenceReceipt
    snapshot: QuiescenceSnapshot

    def evidence_envelope(self) -> dict[str, Any]:
        return build_quiescence_evidence_envelope(
            receipt=self.receipt,
            snapshot=self.snapshot,
        )


MutationRepositoryScopeFactory = Callable[[], AbstractContextManager[CoreRepositories]]


@dataclass(frozen=True, slots=True)
class MutationWriterTurnFactory:
    """Bind one logical Host writer across all of its short DB scopes."""

    repository_scope_factory: MutationRepositoryScopeFactory

    @contextmanager
    def open(
        self,
        *,
        session_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> Iterator[MutationWriteAuthority | None]:
        parent_authority = current_mutation_write_authority()
        writer: MutationWriter | None = None
        authority: MutationWriteAuthority | None = None
        with suspend_mutation_write_authority():
            with self.repository_scope_factory() as repositories:
                service = MutationScopeService(repositories)
                scopes = repositories.mutation_scopes.list_by_session(session_id)
                if not scopes:
                    pass
                else:
                    open_scopes = [
                        scope
                        for scope in scopes
                        if scope.state is MutationScopeState.OPEN
                    ]
                    if len(open_scopes) != 1:
                        raise MutationScopeError(
                            "mutation_writer_admission_closed",
                            "session mutation authority is frozen, sealed, or ambiguous",
                        )
                    scope = open_scopes[0]
                    parent_writer_id = None
                    trusted_root = True
                    if parent_authority is not None:
                        if parent_authority.scope_id != scope.scope_id:
                            raise MutationScopeError(
                                "mutation_writer_parent_scope_mismatch",
                                "nested writer crossed its parent mutation scope",
                            )
                        parent_writer_id = parent_authority.writer_id
                        trusted_root = False
                    writer = service.register_writer(
                        scope_id=scope.scope_id,
                        owner_kind=owner_kind,
                        owner_ref=owner_ref,
                        parent_writer_id=parent_writer_id,
                        process_epoch=process_epoch,
                        trusted_root=trusted_root,
                    )
                    authority = service.authority_for_writer(writer.writer_id)
        if writer is None or authority is None:
            yield None
            return
        try:
            with bind_mutation_write_authority(authority):
                yield authority
        except BaseException as exc:
            try:
                with suspend_mutation_write_authority():
                    with self.repository_scope_factory() as repositories:
                        MutationScopeService(repositories).reject_writer(
                            writer.writer_id,
                            blocker_code="mutation_writer_turn_failed",
                        )
            except BaseException as retirement_error:
                exc.add_note(
                    "mutation writer rejection also failed: "
                    f"{type(retirement_error).__name__}"
                )
            raise
        else:
            with suspend_mutation_write_authority():
                with self.repository_scope_factory() as repositories:
                    MutationScopeService(repositories).finish_writer_turn(
                        writer.writer_id,
                        terminal_proof={
                            "kind": "bounded_writer_turn_returned",
                            "owner_kind": owner_kind.value,
                        },
                        expected_process_epoch=process_epoch,
                    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_snapshot_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "content": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_snapshot_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_snapshot_value(item) for item in value]
    raise MutationScopeError(
        "snapshot_value_unsupported",
        f"unsupported canonical snapshot value type: {type(value).__name__}",
    )


def _quoted_identifier(value: str) -> str:
    if not value or not all(
        character.isalnum() or character == "_" for character in value
    ):
        raise MutationScopeError(
            "coverage_identifier_invalid", "invalid coverage identifier"
        )
    return f'"{value}"'


def _receipt_identity_payload(receipt: QuiescenceReceipt) -> dict[str, object]:
    return {
        "schema_version": receipt.SCHEMA_VERSION,
        "receipt_id": receipt.receipt_id,
        "scope_id": receipt.scope_id,
        "seal_generation": receipt.seal_generation,
        "policy_digest": receipt.policy_digest,
        "coverage_digest": receipt.coverage_digest,
        "writer_set_digest": receipt.writer_set_digest,
        "terminal_proof_digest": receipt.terminal_proof_digest,
        "sqlite_high_watermark": receipt.sqlite_high_watermark,
        "event_high_watermark": receipt.event_high_watermark,
        "artifact_high_watermark": receipt.artifact_high_watermark,
        "snapshot_digest": receipt.snapshot_digest,
        "issued_at": receipt.issued_at,
    }


def quiescence_receipt_digest(receipt: QuiescenceReceipt) -> str:
    return canonical_digest(_receipt_identity_payload(receipt))


def build_quiescence_evidence_envelope(
    *,
    receipt: QuiescenceReceipt,
    snapshot: QuiescenceSnapshot,
) -> dict[str, Any]:
    return {
        "schema_id": HOST_MUTATION_RECEIPT_EVIDENCE_SCHEMA_ID,
        "receipt": receipt.to_dict(),
        "snapshot": snapshot.to_private_dict(),
    }


def verify_quiescence_evidence(
    *,
    receipt: QuiescenceReceipt,
    snapshot: QuiescenceSnapshot,
) -> None:
    if (
        snapshot.receipt_id != receipt.receipt_id
        or snapshot.scope_id != receipt.scope_id
        or snapshot.seal_generation != receipt.seal_generation
    ):
        raise MutationScopeError(
            "quiescence_identity_mismatch",
            "receipt and sealed snapshot identities do not match",
        )
    evidence = snapshot.evidence
    if evidence.get("schema_id") != HOST_MUTATION_SNAPSHOT_SCHEMA_ID:
        raise MutationScopeError(
            "quiescence_snapshot_schema_invalid",
            "sealed snapshot has an unsupported schema",
        )
    if (
        receipt.policy_digest != HOST_MUTATION_POLICY_DIGEST
        or receipt.coverage_digest != HOST_MUTATION_COVERAGE_DIGEST
    ):
        raise MutationScopeError(
            "quiescence_contract_digest_unsupported",
            "receipt policy or coverage digest is not the supported closed contract",
        )
    if canonical_digest(evidence) != snapshot.evidence_digest:
        raise MutationScopeError(
            "quiescence_snapshot_digest_mismatch",
            "sealed snapshot bytes do not reproduce their digest",
        )
    if snapshot.evidence_digest != receipt.snapshot_digest:
        raise MutationScopeError(
            "quiescence_receipt_snapshot_mismatch",
            "receipt does not bind the sealed snapshot digest",
        )
    scope_identity = evidence.get("scope")
    if not isinstance(scope_identity, dict) or (
        scope_identity.get("scope_id") != receipt.scope_id
        or scope_identity.get("generation") != receipt.seal_generation
    ):
        raise MutationScopeError(
            "quiescence_scope_identity_mismatch",
            "snapshot does not bind the receipt scope generation",
        )
    expected_fields = {
        "policy_digest": receipt.policy_digest,
        "coverage_digest": receipt.coverage_digest,
        "writer_set_digest": receipt.writer_set_digest,
        "terminal_proof_digest": receipt.terminal_proof_digest,
        "sqlite_high_watermark": receipt.sqlite_high_watermark,
        "event_high_watermark": receipt.event_high_watermark,
        "artifact_high_watermark": receipt.artifact_high_watermark,
    }
    for field_name, expected in expected_fields.items():
        if evidence.get(field_name) != expected:
            raise MutationScopeError(
                "quiescence_evidence_field_mismatch",
                f"snapshot field {field_name} does not match its receipt",
            )
    resources = evidence.get("resources")
    writers = evidence.get("writers")
    if not isinstance(resources, list) or not isinstance(writers, list):
        raise MutationScopeError(
            "quiescence_snapshot_shape_invalid",
            "snapshot resource or writer evidence is not a closed list",
        )
    expected_resource_identities = {
        (
            entry.table_name,
            entry.resource_category.value,
            entry.session_binding,
        )
        for entry in HOST_MUTATION_COVERAGE_ENTRIES
    }
    actual_resource_identities: set[tuple[object, object, object]] = set()
    for resource in resources:
        if not isinstance(resource, dict):
            raise MutationScopeError(
                "quiescence_resource_invalid",
                "snapshot resource entry is malformed",
            )
        rows = resource.get("rows")
        if not isinstance(rows, list) or canonical_digest(rows) != resource.get(
            "rows_digest"
        ):
            raise MutationScopeError(
                "quiescence_resource_digest_mismatch",
                "snapshot resource rows do not reproduce their digest",
            )
        if resource.get("row_count") != len(rows):
            raise MutationScopeError(
                "quiescence_resource_count_mismatch",
                "snapshot resource count does not match its rows",
            )
        actual_resource_identities.add(
            (
                resource.get("table_name"),
                resource.get("resource_category"),
                resource.get("session_binding"),
            )
        )
    if actual_resource_identities != expected_resource_identities or len(
        resources
    ) != len(expected_resource_identities):
        raise MutationScopeError(
            "quiescence_resource_coverage_mismatch",
            "snapshot resources do not match the closed coverage manifest",
        )
    high_watermarks = {
        category.value: canonical_digest(
            [
                {
                    "table_name": resource["table_name"],
                    "row_count": resource["row_count"],
                    "rows_digest": resource["rows_digest"],
                }
                for resource in resources
                if resource["resource_category"] == category.value
            ]
        )
        for category in MutationResourceCategory
    }
    recomputed_sqlite_high_watermark = canonical_digest(
        {
            category.value: high_watermarks[category.value]
            for category in (
                MutationResourceCategory.CANONICAL_SQLITE,
                MutationResourceCategory.REPORT_PUBLICATION,
                MutationResourceCategory.LEDGER,
            )
        }
    )
    recomputed_artifact_high_watermark = canonical_digest(
        {
            "catalog": high_watermarks[
                MutationResourceCategory.ARTIFACT_PUBLICATION.value
            ],
            "external": evidence.get("external_artifact_snapshot"),
        }
    )
    if (
        recomputed_sqlite_high_watermark != receipt.sqlite_high_watermark
        or high_watermarks[MutationResourceCategory.EVENT_OUTBOX.value]
        != receipt.event_high_watermark
        or recomputed_artifact_high_watermark != receipt.artifact_high_watermark
    ):
        raise MutationScopeError(
            "quiescence_high_watermark_digest_mismatch",
            "snapshot resources do not reproduce declared high-watermarks",
        )
    writer_set = [
        {
            key: writer.get(key)
            for key in (
                "writer_id",
                "owner_kind",
                "owner_ref_digest",
                "parent_writer_id",
                "process_epoch",
                "state",
                "terminal_proof_digest",
            )
        }
        for writer in writers
        if isinstance(writer, dict)
    ]
    if (
        len(writer_set) != len(writers)
        or canonical_digest(writer_set) != receipt.writer_set_digest
    ):
        raise MutationScopeError(
            "quiescence_writer_set_digest_mismatch",
            "snapshot writers do not reproduce their set digest",
        )
    terminal_proofs = [
        {
            "writer_id": writer["writer_id"],
            "state": writer["state"],
            "terminal_proof_digest": writer["terminal_proof_digest"],
        }
        for writer in writer_set
    ]
    if canonical_digest(terminal_proofs) != receipt.terminal_proof_digest:
        raise MutationScopeError(
            "quiescence_terminal_proof_digest_mismatch",
            "snapshot writer proofs do not reproduce their aggregate digest",
        )
    if quiescence_receipt_digest(receipt) != receipt.receipt_digest:
        raise MutationScopeError(
            "quiescence_receipt_digest_mismatch",
            "receipt fields do not reproduce the receipt digest",
        )


def verify_quiescence_evidence_envelope(envelope: Mapping[str, object]) -> None:
    if envelope.get("schema_id") != HOST_MUTATION_RECEIPT_EVIDENCE_SCHEMA_ID:
        raise MutationScopeError(
            "quiescence_evidence_schema_invalid",
            "quiescence evidence envelope has an unsupported schema",
        )
    receipt_payload = envelope.get("receipt")
    snapshot_payload = envelope.get("snapshot")
    if not isinstance(receipt_payload, dict) or not isinstance(snapshot_payload, dict):
        raise MutationScopeError(
            "quiescence_evidence_shape_invalid",
            "quiescence evidence envelope is malformed",
        )
    receipt_fields = dict(receipt_payload)
    snapshot_fields = dict(snapshot_payload)
    if receipt_fields.pop("schema_version", None) != QuiescenceReceipt.SCHEMA_VERSION:
        raise MutationScopeError(
            "quiescence_receipt_schema_invalid",
            "receipt has an unsupported schema",
        )
    if snapshot_fields.pop("schema_version", None) != QuiescenceSnapshot.SCHEMA_VERSION:
        raise MutationScopeError(
            "quiescence_snapshot_record_schema_invalid",
            "snapshot record has an unsupported schema",
        )
    try:
        receipt = QuiescenceReceipt(**receipt_fields)
        snapshot = QuiescenceSnapshot(**snapshot_fields)
    except (TypeError, ValueError) as exc:
        raise MutationScopeError(
            "quiescence_evidence_shape_invalid",
            "quiescence evidence fields do not match the closed schema",
        ) from exc
    verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)


@dataclass(slots=True)
class MutationScopeService:
    repositories: CoreRepositories
    now: Callable[[], str] = _utc_now_iso
    id_factory: Callable[[], str] = lambda: uuid4().hex
    artifact_snapshot_provider: Callable[[str], Mapping[str, object]] | None = None

    @property
    def _connection(self) -> sqlite3.Connection:
        return self.repositories.tasks.connection

    @contextmanager
    def writer_turn(
        self,
        *,
        session_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> Iterator[MutationWriteAuthority | None]:
        """Register, bind, and retire a writer on the caller-owned connection."""

        parent_authority = current_mutation_write_authority()
        scopes = self.repositories.mutation_scopes.list_by_session(session_id)
        if not scopes:
            yield None
            return
        open_scopes = [
            scope for scope in scopes if scope.state is MutationScopeState.OPEN
        ]
        if len(open_scopes) != 1:
            raise MutationScopeError(
                "mutation_writer_admission_closed",
                "session mutation authority is frozen, sealed, or ambiguous",
            )
        scope = open_scopes[0]
        parent_writer_id = None
        trusted_root = True
        if parent_authority is not None:
            if parent_authority.scope_id != scope.scope_id:
                raise MutationScopeError(
                    "mutation_writer_parent_scope_mismatch",
                    "nested writer crossed its parent mutation scope",
                )
            parent_writer_id = parent_authority.writer_id
            trusted_root = False
        writer = self.register_writer(
            scope_id=scope.scope_id,
            owner_kind=owner_kind,
            owner_ref=owner_ref,
            parent_writer_id=parent_writer_id,
            process_epoch=process_epoch,
            trusted_root=trusted_root,
        )
        authority = self.authority_for_writer(writer.writer_id)
        try:
            with bind_mutation_write_authority(authority):
                with self.repositories.mutation_write_authority(authority):
                    yield authority
        except BaseException:
            self.reject_writer(
                writer.writer_id,
                blocker_code="mutation_writer_turn_failed",
            )
            raise
        else:
            self.finish_writer_turn(
                writer.writer_id,
                terminal_proof={
                    "kind": "bounded_writer_turn_returned",
                    "owner_kind": owner_kind.value,
                },
                expected_process_epoch=process_epoch,
            )

    def open_scope(
        self,
        *,
        session_id: str,
        scope_kind: MutationScopeKind,
        scope_ref: str,
        parent_scope_id: str | None = None,
        policy_id: str = HOST_MUTATION_POLICY_ID,
        coverage_digest: str = HOST_MUTATION_COVERAGE_DIGEST,
        scope_id: str | None = None,
    ) -> MutationScope:
        if not isinstance(scope_kind, MutationScopeKind):
            raise MutationScopeError(
                "mutation_scope_kind_unsupported",
                "mutation scope kind is not in the closed schema",
            )
        if policy_id != HOST_MUTATION_POLICY_ID:
            raise MutationScopeError(
                "mutation_scope_policy_unsupported",
                "mutation scope policy is not supported",
            )
        if coverage_digest != HOST_MUTATION_COVERAGE_DIGEST:
            raise MutationScopeError(
                "mutation_scope_coverage_unsupported",
                "mutation scope coverage manifest is incomplete or unknown",
            )
        if not session_id.strip() or not scope_ref.strip():
            raise MutationScopeError(
                "mutation_scope_identity_invalid",
                "session and scope references must be non-empty",
            )
        with self.repositories.atomic(prefix="mutation_scope_open"):
            if self.repositories.sessions.get(session_id) is None:
                raise MutationScopeError(
                    "mutation_scope_session_missing",
                    "mutation scope session does not exist",
                )
            active = [
                scope
                for scope in self.repositories.mutation_scopes.list_by_session(
                    session_id
                )
                if scope.state
                in {
                    MutationScopeState.OPEN,
                    MutationScopeState.FREEZING,
                    MutationScopeState.QUIESCENT,
                }
            ]
            if active:
                raise MutationScopeError(
                    "mutation_scope_session_already_active",
                    "session already has an open, freezing, or quiescent scope",
                )
            latest = self.repositories.mutation_scopes.latest_by_ref(
                scope_kind=scope_kind,
                scope_ref=scope_ref,
            )
            if latest is None:
                generation = 1
            else:
                if not latest.state.is_terminal:
                    raise MutationScopeError(
                        "mutation_scope_previous_generation_active",
                        "previous scope generation is not terminal",
                    )
                if parent_scope_id != latest.scope_id:
                    raise MutationScopeError(
                        "mutation_scope_generation_link_missing",
                        "follow-up generation must link the exact previous scope",
                    )
                if latest.session_id != session_id:
                    raise MutationScopeError(
                        "mutation_scope_session_mismatch",
                        "follow-up generation crossed its session boundary",
                    )
                generation = latest.generation + 1
            if parent_scope_id is not None:
                parent = self.repositories.mutation_scopes.get(parent_scope_id)
                if parent is None or parent.session_id != session_id:
                    raise MutationScopeError(
                        "mutation_scope_parent_invalid",
                        "mutation scope parent is missing or belongs to another session",
                    )
                if not parent.state.is_terminal:
                    raise MutationScopeError(
                        "mutation_scope_parent_active",
                        "mutation scope parent must be terminal before follow-up work",
                    )
            scope = MutationScope(
                scope_id=scope_id or f"mutation_scope_{self.id_factory()}",
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                session_id=session_id,
                parent_scope_id=parent_scope_id,
                state=MutationScopeState.OPEN,
                generation=generation,
                mutation_fencing_token=1,
                state_version=1,
                policy_id=policy_id,
                writer_coverage_manifest_digest=coverage_digest,
                opened_at=self.now(),
            )
            try:
                return self.repositories.mutation_scopes.add(scope)
            except CanonicalRecordConflictError as exc:
                raise MutationScopeError(
                    "mutation_scope_admission_conflict",
                    "mutation scope identity or active session authority raced",
                ) from exc

    def register_writer(
        self,
        *,
        scope_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        parent_writer_id: str | None = None,
        process_epoch: int | None = None,
        trusted_root: bool = False,
        writer_id: str | None = None,
    ) -> MutationWriter:
        if not isinstance(owner_kind, MutationWriterKind):
            raise MutationScopeError(
                "mutation_writer_kind_unsupported",
                "mutation writer kind is not in the closed coverage manifest",
            )
        if not owner_ref.strip() or len(owner_ref) > 512:
            raise MutationScopeError(
                "mutation_writer_identity_invalid",
                "mutation writer owner reference is empty or exceeds its bound",
            )
        if process_epoch is not None and process_epoch < 1:
            raise MutationScopeError(
                "mutation_writer_process_epoch_invalid",
                "mutation writer process epoch must be positive",
            )
        with self.repositories.atomic(prefix="mutation_writer_register"):
            scope = self._require_supported_scope(scope_id)
            if scope.state is not MutationScopeState.OPEN:
                raise MutationScopeError(
                    "mutation_writer_admission_closed",
                    "mutation writer admission is closed for this scope",
                )
            if parent_writer_id is None and not trusted_root:
                raise MutationScopeError(
                    "mutation_writer_root_not_authorized",
                    "detached mutation writer requires explicit trusted-root authority",
                )
            if parent_writer_id is not None:
                parent = self.repositories.mutation_writers.get(parent_writer_id)
                if (
                    parent is None
                    or parent.scope_id != scope.scope_id
                    or parent.scope_generation != scope.generation
                    or parent.fencing_token != scope.mutation_fencing_token
                    or parent.state is not MutationWriterState.REGISTERED
                ):
                    raise MutationScopeError(
                        "mutation_writer_parent_not_active",
                        "nested writer parent does not hold current active authority",
                    )
            writer = MutationWriter(
                writer_id=writer_id or f"mutation_writer_{self.id_factory()}",
                scope_id=scope.scope_id,
                scope_generation=scope.generation,
                owner_kind=owner_kind,
                owner_ref=owner_ref,
                process_epoch=process_epoch,
                state=MutationWriterState.REGISTERED,
                parent_writer_id=parent_writer_id,
                fencing_token=scope.mutation_fencing_token,
                state_version=1,
                registered_at=self.now(),
            )
            try:
                return self.repositories.mutation_writers.add(writer)
            except CanonicalRecordConflictError as exc:
                raise MutationScopeError(
                    "mutation_writer_admission_conflict",
                    "writer registration lost a freeze or identity race",
                ) from exc

    def authority_for_writer(self, writer_id: str) -> MutationWriteAuthority:
        writer = self.repositories.mutation_writers.get(writer_id)
        if writer is None or writer.state is not MutationWriterState.REGISTERED:
            raise MutationScopeError(
                "mutation_writer_not_active",
                "mutation writer is missing or no longer registered",
            )
        scope = self._require_supported_scope(writer.scope_id)
        if (
            scope.state is not MutationScopeState.OPEN
            or scope.generation != writer.scope_generation
            or scope.mutation_fencing_token != writer.fencing_token
        ):
            raise MutationScopeError(
                "mutation_writer_authority_stale",
                "mutation writer no longer matches open scope authority",
            )
        return MutationWriteAuthority(
            scope_id=scope.scope_id,
            scope_generation=scope.generation,
            scope_fencing_token=scope.mutation_fencing_token,
            writer_id=writer.writer_id,
            writer_fencing_token=writer.fencing_token,
            owner_kind=writer.owner_kind,
        )

    def begin_freeze(self, scope_id: str) -> MutationScope:
        with self.repositories.atomic(prefix="mutation_scope_freeze"):
            scope = self._require_supported_scope(scope_id)
            if scope.state is MutationScopeState.FREEZING:
                return scope
            if scope.state is not MutationScopeState.OPEN:
                raise MutationScopeError(
                    "mutation_scope_not_open",
                    "only an open mutation scope can begin freezing",
                )
            freezing = replace(
                scope,
                state=MutationScopeState.FREEZING,
                mutation_fencing_token=scope.mutation_fencing_token + 1,
                state_version=scope.state_version + 1,
                freeze_requested_at=self.now(),
            )
            return self.repositories.mutation_scopes.replace_if_version(
                freezing,
                expected_state_version=scope.state_version,
                expected_fencing_token=scope.mutation_fencing_token,
            )

    def retire_writer(
        self,
        writer_id: str,
        *,
        terminal_proof: Mapping[str, object],
        expected_process_epoch: int | None = None,
    ) -> MutationWriter:
        with self.repositories.atomic(prefix="mutation_writer_retire"):
            writer = self.repositories.mutation_writers.get(writer_id)
            if writer is None:
                raise MutationScopeError(
                    "mutation_writer_missing",
                    "mutation writer does not exist",
                )
            if writer.state is MutationWriterState.RETIRED:
                return writer
            if writer.state is MutationWriterState.REJECTED:
                raise MutationScopeError(
                    "mutation_writer_rejected",
                    "rejected mutation writer cannot be retired as successful",
                )
            scope = self._require_supported_scope(writer.scope_id)
            if scope.state not in {
                MutationScopeState.OPEN,
                MutationScopeState.FREEZING,
            }:
                raise MutationScopeError(
                    "mutation_writer_retirement_closed",
                    "writer retirement is closed after quiescence or failure",
                )
            active_children = [
                child
                for child in self.repositories.mutation_writers.list_children(writer_id)
                if not child.state.is_terminal
            ]
            if active_children:
                raise MutationScopeError(
                    "mutation_writer_children_active",
                    "writer cannot retire before every child is terminal",
                )
            if expected_process_epoch is not None and (
                writer.process_epoch != expected_process_epoch
            ):
                raise MutationScopeError(
                    "mutation_writer_process_epoch_mismatch",
                    "process retirement proof does not match the exact writer epoch",
                )
            proof_payload = {
                "schema_id": "mutation_writer_terminal_proof@1",
                "writer_id": writer.writer_id,
                "scope_id": writer.scope_id,
                "scope_generation": writer.scope_generation,
                "process_epoch": writer.process_epoch,
                "proof": _normalize_snapshot_value(terminal_proof),
            }
            retired = replace(
                writer,
                state=MutationWriterState.RETIRED,
                state_version=writer.state_version + 1,
                retired_at=self.now(),
                terminal_proof_digest=canonical_digest(proof_payload),
                safe_error_summary=None,
            )
            stored = self.repositories.mutation_writers.replace_if_version(
                retired,
                expected_state_version=writer.state_version,
                expected_fencing_token=writer.fencing_token,
            )
            self._cascade_retiring_parents(writer.parent_writer_id)
            return stored

    def finish_writer_turn(
        self,
        writer_id: str,
        *,
        terminal_proof: Mapping[str, object],
        expected_process_epoch: int | None = None,
    ) -> MutationWriter:
        """Retire now, or remain explicitly retiring until children terminate."""

        with self.repositories.atomic(prefix="mutation_writer_turn_finish"):
            writer = self.repositories.mutation_writers.get(writer_id)
            if writer is None:
                raise MutationScopeError(
                    "mutation_writer_missing",
                    "mutation writer does not exist",
                )
            if writer.state is MutationWriterState.RETIRED:
                return writer
            if writer.state is not MutationWriterState.REGISTERED:
                raise MutationScopeError(
                    "mutation_writer_turn_not_registered",
                    "only a registered writer can finish its bounded turn",
                )
            if expected_process_epoch is not None and (
                writer.process_epoch != expected_process_epoch
            ):
                raise MutationScopeError(
                    "mutation_writer_process_epoch_mismatch",
                    "process retirement proof does not match the exact writer epoch",
                )
            proof_digest = canonical_digest(
                {
                    "schema_id": "mutation_writer_terminal_proof@1",
                    "writer_id": writer.writer_id,
                    "scope_id": writer.scope_id,
                    "scope_generation": writer.scope_generation,
                    "process_epoch": writer.process_epoch,
                    "proof": _normalize_snapshot_value(terminal_proof),
                }
            )
            active_children = [
                child
                for child in self.repositories.mutation_writers.list_children(writer_id)
                if not child.state.is_terminal
            ]
            terminal_now = not active_children
            updated = replace(
                writer,
                state=(
                    MutationWriterState.RETIRED
                    if terminal_now
                    else MutationWriterState.RETIRING
                ),
                state_version=writer.state_version + 1,
                retired_at=self.now() if terminal_now else None,
                terminal_proof_digest=proof_digest,
                safe_error_summary=None,
            )
            stored = self.repositories.mutation_writers.replace_if_version(
                updated,
                expected_state_version=writer.state_version,
                expected_fencing_token=writer.fencing_token,
            )
            if terminal_now:
                self._cascade_retiring_parents(writer.parent_writer_id)
            return stored

    def reject_writer(self, writer_id: str, *, blocker_code: str) -> MutationWriter:
        blocker = self._normalize_blocker_code(blocker_code)
        with self.repositories.atomic(prefix="mutation_writer_reject"):
            writer = self.repositories.mutation_writers.get(writer_id)
            if writer is None:
                raise MutationScopeError(
                    "mutation_writer_missing",
                    "mutation writer does not exist",
                )
            if writer.state is MutationWriterState.REJECTED:
                return writer
            if writer.state is MutationWriterState.RETIRED:
                raise MutationScopeError(
                    "mutation_writer_already_retired",
                    "retired mutation writer cannot be rewritten as rejected",
                )
            children = self.repositories.mutation_writers.list_children(writer_id)
            active_children = [
                child for child in children if not child.state.is_terminal
            ]
            proof = canonical_digest(
                {
                    "schema_id": "mutation_writer_rejection@1",
                    "writer_id": writer.writer_id,
                    "blocker_code": blocker,
                }
            )
            rejected = replace(
                writer,
                state=(
                    MutationWriterState.RETIRING
                    if active_children
                    else MutationWriterState.REJECTED
                ),
                state_version=writer.state_version + 1,
                retired_at=None if active_children else self.now(),
                terminal_proof_digest=proof,
                safe_error_summary=blocker,
            )
            stored = self.repositories.mutation_writers.replace_if_version(
                rejected,
                expected_state_version=writer.state_version,
                expected_fencing_token=writer.fencing_token,
            )
            if not active_children:
                self._cascade_retiring_parents(writer.parent_writer_id)
            return stored

    def issue_quiescence_receipt(
        self,
        scope_id: str,
        *,
        stability_probe: Callable[[], None] | None = None,
    ) -> QuiescenceIssueResult:
        with self.repositories.atomic(prefix="mutation_scope_quiescence"):
            scope = self._require_supported_scope(scope_id)
            existing_receipt = self.repositories.quiescence_receipts.get_by_scope(
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
            )
            if existing_receipt is not None:
                existing_snapshot = (
                    self.repositories.quiescence_snapshots.get_by_receipt(
                        existing_receipt.receipt_id
                    )
                )
                if existing_snapshot is None:
                    raise MutationScopeError(
                        "quiescence_snapshot_missing",
                        "persisted receipt has no immutable snapshot",
                    )
                verify_quiescence_evidence(
                    receipt=existing_receipt,
                    snapshot=existing_snapshot,
                )
                return QuiescenceIssueResult(
                    scope=scope,
                    receipt=existing_receipt,
                    snapshot=existing_snapshot,
                )
            if scope.state is not MutationScopeState.FREEZING:
                raise MutationScopeError(
                    "mutation_scope_not_freezing",
                    "quiescence requires a freezing scope",
                )
            active_writers = self.repositories.mutation_writers.list_active(
                scope.scope_id
            )
            if active_writers:
                raise MutationScopeError(
                    "mutation_writers_still_active",
                    "quiescence cannot be issued while registered writers remain",
                )
            self._assert_coverage_installed()
            first = self._capture_snapshot(scope)
            if stability_probe is not None:
                stability_probe()
            second = self._capture_snapshot(scope)
            if canonical_digest(first) != canonical_digest(second):
                raise MutationScopeError(
                    "mutation_high_watermark_unstable",
                    "covered canonical state changed during final verification",
                )
            issued_at = self.now()
            receipt_id = f"quiescence_receipt_{self.id_factory()}"
            snapshot_digest = canonical_digest(second)
            receipt = QuiescenceReceipt(
                receipt_id=receipt_id,
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
                policy_digest=str(second["policy_digest"]),
                coverage_digest=str(second["coverage_digest"]),
                writer_set_digest=str(second["writer_set_digest"]),
                terminal_proof_digest=str(second["terminal_proof_digest"]),
                sqlite_high_watermark=str(second["sqlite_high_watermark"]),
                event_high_watermark=str(second["event_high_watermark"]),
                artifact_high_watermark=str(second["artifact_high_watermark"]),
                snapshot_digest=snapshot_digest,
                receipt_digest="",
                issued_at=issued_at,
            )
            receipt = replace(
                receipt,
                receipt_digest=quiescence_receipt_digest(receipt),
            )
            snapshot = QuiescenceSnapshot(
                snapshot_id=f"quiescence_snapshot_{self.id_factory()}",
                receipt_id=receipt.receipt_id,
                scope_id=scope.scope_id,
                seal_generation=scope.generation,
                evidence=second,
                evidence_digest=snapshot_digest,
                created_at=issued_at,
            )
            self.repositories.quiescence_receipts.save_once(receipt)
            self.repositories.quiescence_snapshots.save_once(snapshot)
            quiescent = replace(
                scope,
                state=MutationScopeState.QUIESCENT,
                state_version=scope.state_version + 1,
                quiescent_at=issued_at,
            )
            stored_scope = self.repositories.mutation_scopes.replace_if_version(
                quiescent,
                expected_state_version=scope.state_version,
                expected_fencing_token=scope.mutation_fencing_token,
            )
            verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)
            return QuiescenceIssueResult(
                scope=stored_scope,
                receipt=receipt,
                snapshot=snapshot,
            )

    def seal_scope(self, scope_id: str, *, receipt_id: str) -> MutationScope:
        with self.repositories.atomic(prefix="mutation_scope_seal"):
            scope = self._require_supported_scope(scope_id)
            receipt = self.repositories.quiescence_receipts.get(receipt_id)
            snapshot = self.repositories.quiescence_snapshots.get_by_receipt(receipt_id)
            if (
                receipt is None
                or snapshot is None
                or receipt.scope_id != scope.scope_id
                or receipt.seal_generation != scope.generation
            ):
                raise MutationScopeError(
                    "quiescence_receipt_not_exact",
                    "seal request does not reference the exact scope generation receipt",
                )
            verify_quiescence_evidence(receipt=receipt, snapshot=snapshot)
            if scope.state is MutationScopeState.SEALED:
                if scope.sealed_receipt_digest == receipt.receipt_digest:
                    return scope
                raise MutationScopeError(
                    "mutation_scope_seal_conflict",
                    "sealed scope is bound to a different receipt",
                )
            if scope.state is not MutationScopeState.QUIESCENT:
                raise MutationScopeError(
                    "mutation_scope_not_quiescent",
                    "only the exact quiescent scope generation can be sealed",
                )
            current = self._capture_snapshot(scope)
            if canonical_digest(current) != snapshot.evidence_digest:
                raise MutationScopeError(
                    "mutation_snapshot_changed_before_seal",
                    "canonical state changed after receipt issuance",
                )
            sealed = replace(
                scope,
                state=MutationScopeState.SEALED,
                state_version=scope.state_version + 1,
                sealed_at=self.now(),
                sealed_receipt_digest=receipt.receipt_digest,
            )
            return self.repositories.mutation_scopes.replace_if_version(
                sealed,
                expected_state_version=scope.state_version,
                expected_fencing_token=scope.mutation_fencing_token,
            )

    def fail_scope(self, scope_id: str, *, blocker_code: str) -> MutationScope:
        blocker = self._normalize_blocker_code(blocker_code)
        with self.repositories.atomic(prefix="mutation_scope_fail"):
            scope = self._require_supported_scope(scope_id)
            if scope.state is MutationScopeState.FAILED:
                return scope
            if scope.state is MutationScopeState.SEALED:
                raise MutationScopeError(
                    "mutation_scope_already_sealed",
                    "sealed mutation scope cannot be changed to failed",
                )
            failed = replace(
                scope,
                state=MutationScopeState.FAILED,
                mutation_fencing_token=(
                    scope.mutation_fencing_token + 1
                    if scope.state is MutationScopeState.OPEN
                    else scope.mutation_fencing_token
                ),
                state_version=scope.state_version + 1,
                failed_at=self.now(),
                safe_error_summary=blocker,
            )
            return self.repositories.mutation_scopes.replace_if_version(
                failed,
                expected_state_version=scope.state_version,
                expected_fencing_token=scope.mutation_fencing_token,
            )

    def project_scope(self, scope_id: str) -> dict[str, object]:
        scope = self._require_supported_scope(scope_id)
        writers = self.repositories.mutation_writers.list_all(scope.scope_id)
        receipt = self.repositories.quiescence_receipts.get_by_scope(
            scope_id=scope.scope_id,
            seal_generation=scope.generation,
        )
        snapshot = (
            None
            if receipt is None
            else self.repositories.quiescence_snapshots.get_by_receipt(
                receipt.receipt_id
            )
        )
        active_counts = Counter(
            writer.owner_kind.value
            for writer in writers
            if not writer.state.is_terminal
        )
        total_counts = Counter(writer.owner_kind.value for writer in writers)
        blocker = (
            scope.safe_error_summary
            if scope.safe_error_summary is not None
            and _SAFE_BLOCKER_CODE.fullmatch(scope.safe_error_summary)
            else None
        )
        return {
            "schema_version": "mutation_scope_projection@1",
            "scope_id": scope.scope_id,
            "scope_kind": scope.scope_kind.value,
            "state": scope.state.value,
            "generation": scope.generation,
            "policy_digest": HOST_MUTATION_POLICY_DIGEST,
            "coverage_digest": scope.writer_coverage_manifest_digest,
            "opened_at": scope.opened_at,
            "freeze_requested_at": scope.freeze_requested_at,
            "quiescent_at": scope.quiescent_at,
            "sealed_at": scope.sealed_at,
            "failed_at": scope.failed_at,
            "writer_counts": dict(sorted(total_counts.items())),
            "active_writer_counts": dict(sorted(active_counts.items())),
            "blocker_code": blocker,
            "receipt": (
                None
                if receipt is None
                else {
                    "receipt_id": receipt.receipt_id,
                    "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
                    "receipt_digest": receipt.receipt_digest,
                    "snapshot_digest": receipt.snapshot_digest,
                    "issued_at": receipt.issued_at,
                }
            ),
        }

    def _require_supported_scope(self, scope_id: str) -> MutationScope:
        scope = self.repositories.mutation_scopes.get(scope_id)
        if scope is None:
            raise MutationScopeError(
                "mutation_scope_missing",
                "mutation scope does not exist",
            )
        if (
            scope.session_id is None
            or scope.policy_id != HOST_MUTATION_POLICY_ID
            or scope.writer_coverage_manifest_digest != HOST_MUTATION_COVERAGE_DIGEST
        ):
            raise MutationScopeError(
                "mutation_scope_authority_unsupported",
                "mutation scope is legacy, unbound, or uses unsupported authority",
            )
        return scope

    def _cascade_retiring_parents(self, parent_writer_id: str | None) -> None:
        current_parent_id = parent_writer_id
        while current_parent_id is not None:
            parent = self.repositories.mutation_writers.get(current_parent_id)
            if parent is None or parent.state is not MutationWriterState.RETIRING:
                return
            children = self.repositories.mutation_writers.list_children(
                parent.writer_id
            )
            if any(not child.state.is_terminal for child in children):
                return
            terminal_state = (
                MutationWriterState.REJECTED
                if parent.safe_error_summary is not None
                else MutationWriterState.RETIRED
            )
            terminal = replace(
                parent,
                state=terminal_state,
                state_version=parent.state_version + 1,
                retired_at=self.now(),
            )
            self.repositories.mutation_writers.replace_if_version(
                terminal,
                expected_state_version=parent.state_version,
                expected_fencing_token=parent.fencing_token,
            )
            current_parent_id = parent.parent_writer_id

    def _assert_coverage_installed(self) -> None:
        actual_tables = {
            str(row[0])
            for row in self._connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        expected_tables = (
            {entry.table_name for entry in HOST_MUTATION_COVERAGE_ENTRIES}
            | {item["table_name"] for item in HOST_MUTATION_GLOBAL_EXCLUSIONS}
            | _AUTHORITY_TABLES
        )
        if actual_tables != expected_tables:
            raise MutationScopeError(
                "mutation_coverage_incomplete",
                "canonical schema contains missing or unclassified mutation resources",
            )
        trigger_names = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
        missing_guards = sorted(
            f"mutation_guard_{entry.table_name}_{event}"
            for entry in HOST_MUTATION_COVERAGE_ENTRIES
            for event in ("insert", "update", "delete")
            if f"mutation_guard_{entry.table_name}_{event}" not in trigger_names
        )
        if missing_guards:
            raise MutationScopeError(
                "mutation_coverage_guard_missing",
                "one or more covered mutation resources lacks a database guard",
            )

    def _capture_snapshot(self, scope: MutationScope) -> dict[str, object]:
        if scope.session_id is None:
            raise MutationScopeError(
                "mutation_scope_session_unbound",
                "cannot snapshot an unbound mutation scope",
            )
        resources: list[dict[str, object]] = []
        total_rows = 0
        for entry in HOST_MUTATION_COVERAGE_ENTRIES:
            rows = self._resource_rows(entry, session_id=scope.session_id)
            total_rows += len(rows)
            if total_rows > MAX_QUIESCENCE_SNAPSHOT_ROWS:
                raise MutationScopeError(
                    "mutation_snapshot_row_limit_exceeded",
                    "bounded quiescence snapshot row limit was exceeded",
                )
            resources.append(
                {
                    "table_name": entry.table_name,
                    "resource_category": entry.resource_category.value,
                    "session_binding": entry.session_binding,
                    "row_count": len(rows),
                    "rows_digest": canonical_digest(rows),
                    "rows": rows,
                }
            )
        writers = [
            self._writer_snapshot(writer)
            for writer in self.repositories.mutation_writers.list_all(scope.scope_id)
        ]
        if any(
            writer["state"]
            not in {
                MutationWriterState.RETIRED.value,
                MutationWriterState.REJECTED.value,
            }
            or not writer["terminal_proof_digest"]
            for writer in writers
        ):
            raise MutationScopeError(
                "mutation_writer_terminal_proof_incomplete",
                "writer set contains a nonterminal or unproven writer",
            )
        writer_set_digest = canonical_digest(writers)
        terminal_proof_digest = canonical_digest(
            [
                {
                    "writer_id": writer["writer_id"],
                    "state": writer["state"],
                    "terminal_proof_digest": writer["terminal_proof_digest"],
                }
                for writer in writers
            ]
        )
        external_artifact_snapshot = _normalize_snapshot_value(
            (
                self.artifact_snapshot_provider(scope.session_id)
                if self.artifact_snapshot_provider is not None
                else {
                    "schema_id": "artifact_catalog_commit_markers@1",
                    "publication_contract": "atomic_bytes_before_catalog_row",
                }
            )
        )
        high_watermarks = {
            category.value: canonical_digest(
                [
                    {
                        "table_name": resource["table_name"],
                        "row_count": resource["row_count"],
                        "rows_digest": resource["rows_digest"],
                    }
                    for resource in resources
                    if resource["resource_category"] == category.value
                ]
            )
            for category in MutationResourceCategory
        }
        artifact_high_watermark = canonical_digest(
            {
                "catalog": high_watermarks[
                    MutationResourceCategory.ARTIFACT_PUBLICATION.value
                ],
                "external": external_artifact_snapshot,
            }
        )
        sqlite_high_watermark = canonical_digest(
            {
                category.value: high_watermarks[category.value]
                for category in (
                    MutationResourceCategory.CANONICAL_SQLITE,
                    MutationResourceCategory.REPORT_PUBLICATION,
                    MutationResourceCategory.LEDGER,
                )
            }
        )
        snapshot: dict[str, object] = {
            "schema_id": HOST_MUTATION_SNAPSHOT_SCHEMA_ID,
            "scope": {
                "scope_id": scope.scope_id,
                "session_id_digest": canonical_digest(scope.session_id),
                "scope_kind": scope.scope_kind.value,
                "scope_ref_digest": canonical_digest(scope.scope_ref),
                "generation": scope.generation,
            },
            "policy_digest": HOST_MUTATION_POLICY_DIGEST,
            "coverage_digest": HOST_MUTATION_COVERAGE_DIGEST,
            "writer_set_digest": writer_set_digest,
            "terminal_proof_digest": terminal_proof_digest,
            "sqlite_high_watermark": sqlite_high_watermark,
            "event_high_watermark": high_watermarks[
                MutationResourceCategory.EVENT_OUTBOX.value
            ],
            "artifact_high_watermark": artifact_high_watermark,
            "resources": resources,
            "writers": writers,
            "external_artifact_snapshot": external_artifact_snapshot,
        }
        if len(canonical_json_bytes(snapshot)) > MAX_QUIESCENCE_SNAPSHOT_BYTES:
            raise MutationScopeError(
                "mutation_snapshot_byte_limit_exceeded",
                "bounded quiescence snapshot byte limit was exceeded",
            )
        return snapshot

    def _resource_rows(
        self,
        entry: MutationCoverageEntry,
        *,
        session_id: str,
    ) -> list[dict[str, object]]:
        table = _quoted_identifier(entry.table_name)
        columns = [
            str(row[1])
            for row in self._connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        ]
        if not columns:
            raise MutationScopeError(
                "mutation_coverage_table_missing",
                "covered mutation table is absent",
            )
        order = ", ".join(
            f"resource.{_quoted_identifier(column)}" for column in columns
        )
        if entry.session_binding == "direct_session_id":
            sql = (
                f"SELECT resource.* FROM {table} AS resource "
                f"WHERE resource.session_id = ? ORDER BY {order}"
            )
        elif entry.session_binding == "task_id_to_tasks":
            sql = (
                f"SELECT resource.* FROM {table} AS resource "
                "JOIN tasks AS owner ON owner.task_id = resource.task_id "
                f"WHERE owner.session_id = ? ORDER BY {order}"
            )
        elif entry.session_binding == "sandbox_workspace_id_to_workspace":
            sql = (
                f"SELECT resource.* FROM {table} AS resource "
                "JOIN sandbox_workspace_records AS owner "
                "ON owner.sandbox_workspace_id = resource.sandbox_workspace_id "
                f"WHERE owner.session_id = ? ORDER BY {order}"
            )
        elif entry.session_binding == "attempt_id_to_scientific_attempts":
            sql = (
                f"SELECT resource.* FROM {table} AS resource "
                "JOIN scientific_attempt_records AS owner "
                "ON owner.attempt_id = resource.attempt_id "
                f"WHERE owner.session_id = ? ORDER BY {order}"
            )
        else:
            raise MutationScopeError(
                "mutation_coverage_binding_unsupported",
                "covered mutation resource has an unknown session binding",
            )
        return [
            {column: _normalize_snapshot_value(row[column]) for column in columns}
            for row in self._connection.execute(sql, (session_id,)).fetchall()
        ]

    @staticmethod
    def _writer_snapshot(writer: MutationWriter) -> dict[str, object]:
        return {
            "writer_id": writer.writer_id,
            "owner_kind": writer.owner_kind.value,
            "owner_ref_digest": canonical_digest(writer.owner_ref),
            "parent_writer_id": writer.parent_writer_id,
            "process_epoch": writer.process_epoch,
            "state": writer.state.value,
            "terminal_proof_digest": writer.terminal_proof_digest,
        }

    @staticmethod
    def _normalize_blocker_code(value: str) -> str:
        normalized = value.strip().casefold()
        if _SAFE_BLOCKER_CODE.fullmatch(normalized) is None:
            raise MutationScopeError(
                "mutation_blocker_code_invalid",
                "closure blocker must be a bounded machine-safe code",
            )
        return normalized


__all__ = [
    "MutationScopeError",
    "MutationScopeService",
    "MutationWriterTurnFactory",
    "QuiescenceIssueResult",
    "build_quiescence_evidence_envelope",
    "quiescence_receipt_digest",
    "verify_quiescence_evidence",
    "verify_quiescence_evidence_envelope",
]
