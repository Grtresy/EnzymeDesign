from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import RevisionPathEntryKind
from openzyme_domain import RevisionPathRef
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef
from openzyme_domain.control_plane import utc_now_iso

from .agent_capability_service import AgentCapabilityError
from .agent_capsule_runtime import AgentCapsuleRuntimeError
from .agent_capsule_runtime import AgentCapsuleRuntimeService
from .git_lfs_work_products import GitLfsPublicationManifestPolicyValidator
from .git_lfs_work_products import GitLfsWorkProductError
from .git_lfs_repositories import GitLfsRepositoryError
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .workspace_publications import WorkspacePublicationError
from .workspace_publications import WorkspacePublicationService
from .workspace_publications import WorkspacePublishCommand
from .repository_storage import DurableLfsObjectStore
from .repository_storage import DurableRepositoryRootManager
from .revision_path_handoffs import RevisionPathHandoffError
from .revision_path_handoffs import RevisionPathReferenceService
from .native_revision_path_fetch import NativeRevisionPathFetchError
from .native_revision_path_fetch import NativeRevisionPathFetchService


def register_workspace_publication_tools(
    registry: ToolRegistry,
    *,
    agent_id: str | None,
) -> None:
    def publish_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        resolved_agent_id = agent_id or context.agent_id
        route = context.workspace_checkpoint_git_reader
        if resolved_agent_id is None or route is None:
            return _tool_error(
                invocation,
                "workspace_publication_unavailable",
                "workspace.publish requires an exact agent and Host Git route",
            )
        try:
            if not isinstance(route, DurableRepositoryRootManager):
                raise WorkspacePublicationError(
                    "workspace.publish requires the Host durable Git/LFS route"
                )
            command = WorkspacePublishCommand(
                idempotency_key=_required_string(invocation, "idempotency_key"),
                workspace_id=_required_string(invocation, "workspace_id"),
                workspace_generation=_required_integer(
                    invocation,
                    "workspace_generation",
                ),
                expected_head_commit=_required_string(
                    invocation,
                    "expected_head_commit",
                ),
                expected_tree=_required_string(invocation, "expected_tree"),
                declared_base_commit=_required_string(
                    invocation,
                    "declared_base_commit",
                ),
                checkpoint_id=_required_string(invocation, "checkpoint_id"),
                whole_repository=_required_boolean(
                    invocation,
                    "whole_repository",
                ),
                repository_binding_version=_required_integer(
                    invocation,
                    "repository_binding_version",
                ),
                parent_publication_id=_optional_string(
                    invocation,
                    "parent_publication_id",
                ),
                supersedes_publication_id=_optional_string(
                    invocation,
                    "supersedes_publication_id",
                ),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
            state = WorkspacePublicationService(
                repositories=context.repositories,
                git_reader=route,
                remote_route=route,
                manifest_policy=GitLfsPublicationManifestPolicyValidator(
                    repositories=context.repositories.git_lfs,
                    git_reader=route,
                    object_store=DurableLfsObjectStore(route),
                ),
            ).publish(
                session_id=context.snapshot.session.session_id,
                agent_id=resolved_agent_id,
                command=command,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            GitLfsRepositoryError,
            GitLfsWorkProductError,
            WorkspacePublicationError,
        ) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "workspace_publication_rejected"),
                str(exc),
            )
        payload = _safe_state_payload(
            state,
            lfs_proof=context.repositories.git_lfs.get_publication_intent_proof(
                state.intent.intent_id
            ),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=(
                "workspace_publication_materialized"
                if state.revision is not None
                else "workspace_publication_reconcile_required"
            ),
            summary=(
                "Exact immutable workspace publication confirmed."
                if state.revision is not None
                else "Publication outcome remains dispatch-in-doubt; reconcile the same ref."
            ),
            details=payload,
        )

    def fetch_identity_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        route = context.workspace_checkpoint_git_reader
        if route is None:
            return _tool_error(
                invocation,
                "workspace_publication_unavailable",
                "publication fetch identity requires the Host repository service",
            )
        try:
            identity = WorkspacePublicationService(
                repositories=context.repositories,
                git_reader=route,
                remote_route=route,
            ).fetch_identity(_required_string(invocation, "publication_id"))
        except (KeyError, TypeError, ValueError, WorkspacePublicationError) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "workspace_publication_rejected"),
                str(exc),
            )
        payload = {
            "schema_version": identity.schema_version,
            "publication_id": identity.publication_id,
            "repository_binding_id": identity.repository_binding_id,
            "repository_binding_version": identity.repository_binding_version,
            "repository_id": identity.repository_id,
            "publication_ref": identity.publication_ref,
            "commit": identity.commit,
            "tree": identity.tree,
            "manifest_digest": identity.manifest_digest,
            "lfs_closure": context.repositories.git_lfs.publication_closure_projection(
                identity.publication_id
            ),
            "sync_policy": "explicit_fetch_no_checkout_no_merge",
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="workspace_publication_fetch_identity_ready",
            summary="Returned exact immutable publication fetch identity.",
            details=payload,
        )

    def audit_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        route = context.workspace_checkpoint_git_reader
        if route is None:
            return _tool_error(
                invocation,
                "workspace_publication_unavailable",
                "publication audit requires the Host repository service",
            )
        try:
            payload = WorkspacePublicationService(
                repositories=context.repositories,
                git_reader=route,
                remote_route=route,
            ).audit_session_namespace(context.snapshot.session.session_id)
        except WorkspacePublicationError as exc:
            return _tool_error(
                invocation,
                exc.error_code,
                str(exc),
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=bool(payload["ok"]),
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=(
                "workspace_publication_namespace_valid"
                if payload["ok"]
                else "workspace_publication_namespace_drift"
            ),
            summary="Read-only audited canonical publication refs.",
            details=payload,
        )

    def path_ref_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        route = context.workspace_checkpoint_git_reader
        if route is None:
            return _tool_error(
                invocation,
                "workspace_publication_unavailable",
                "revision path reference requires the Host repository identity reader",
            )
        try:
            service = RevisionPathReferenceService(
                context.repositories,
                directory_reader=route,
            )
            entry_kind = str(invocation.arguments.get("entry_kind") or "file")
            values = {
                "publication_id": _required_string(invocation, "publication_id"),
                "path": _required_string(invocation, "path"),
                "ref_id": _required_string(invocation, "ref_id"),
            }
            ref = (
                service.create_directory_ref(**values)
                if entry_kind == "directory"
                else service.create_file_ref(**values)
            )
        except (KeyError, TypeError, ValueError, RevisionPathHandoffError) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "revision_path_handoff_invalid"),
                str(exc),
            )
        task_evidence_ref = (
            None
            if invocation.task_id is None
            else TaskEvidenceRef(
                kind=TaskEvidenceKind.REVISION_PATH,
                project_id=ref.project_id,
                session_id=ref.session_id,
                task_id=invocation.task_id,
                owner_id=ref.ref_id,
                owner_digest=ref.ref_digest,
                revision_path_ref=ref,
            ).to_dict()
        )
        payload = {
            "revision_path_ref": ref.to_dict(),
            "task_evidence_ref": task_evidence_ref,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="revision_path_ref_ready",
            summary="Created an exact immutable revision path reference.",
            details=payload,
        )

    def verify_path_ref_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        route = context.workspace_checkpoint_git_reader
        try:
            raw_ref = invocation.arguments["revision_path_ref"]
            if not isinstance(raw_ref, dict):
                raise TypeError("revision_path_ref must be an object")
            ref = RevisionPathRef.from_dict(raw_ref)
            ref = RevisionPathReferenceService(
                context.repositories,
                directory_reader=route,
            ).require_exact(
                ref,
                project_id=context.snapshot.session.project_id,
                session_id=context.snapshot.session.session_id,
            )
            context.repositories.revision_path_handoffs.add_ref(ref)
        except (KeyError, TypeError, ValueError, RevisionPathHandoffError) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "revision_path_handoff_invalid"),
                str(exc),
            )
        payload = {
            "revision_path_ref": ref.to_dict(),
            "verified": True,
            "fallback_performed": False,
            "content_bytes_returned": False,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="revision_path_ref_verified",
            summary="Verified exact publication, path, and object identity.",
            details=payload,
        )

    def fetch_handoff_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        resolved_agent_id = agent_id or context.agent_id
        if (
            resolved_agent_id is None
            or context.agent_capsule_process_runner is None
            or context.agent_process_credential_router is None
        ):
            return _tool_error(
                invocation,
                "native_revision_path_fetch_unavailable",
                "native handoff fetch requires the exact agent, capsule, and credential router",
            )
        try:
            result = NativeRevisionPathFetchService(
                repositories=context.repositories,
                runtime=AgentCapsuleRuntimeService(
                    repositories=context.repositories,
                    process_runner=context.agent_capsule_process_runner,
                    credential_router=context.agent_process_credential_router,
                ),
            ).fetch_handoff_publication(
                session_id=context.snapshot.session.session_id,
                agent_id=resolved_agent_id,
                handoff_id=_required_string(invocation, "handoff_id"),
                publication_id=_required_string(invocation, "publication_id"),
            )
        except (
            AgentCapabilityError,
            AgentCapsuleRuntimeError,
            KeyError,
            TypeError,
            ValueError,
            NativeRevisionPathFetchError,
        ) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "native_revision_path_fetch_failed"),
                str(exc),
            )
        payload = result.to_dict()
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="native_revision_path_fetch_verified",
            summary=(
                "Fetched and verified the exact immutable Git/Git LFS handoff "
                "without checkout, merge, or task transition."
            ),
            details=payload,
        )

    def index_research_file_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        try:
            invocation_id = _required_string(invocation, "invocation_id")
            engine_invocation = context.repositories.invocations.get(invocation_id)
            if (
                engine_invocation is None
                or engine_invocation.session_id
                != context.snapshot.session.session_id
            ):
                raise RevisionPathHandoffError(
                    "research index invocation does not belong to this session"
                )
            research_task = (
                None
                if engine_invocation.task_id is None
                else context.repositories.tasks.get(engine_invocation.task_id)
            )
            if (
                context.agent_id is None
                or research_task is None
                or research_task.assigned_ref != context.agent_id
            ):
                raise RevisionPathHandoffError(
                    "research file index requires the exact assigned task owner"
                )
            raw_ref = invocation.arguments["revision_path_ref"]
            if not isinstance(raw_ref, dict):
                raise TypeError("revision_path_ref must be an object")
            ref = RevisionPathRef.from_dict(raw_ref)
            ref = RevisionPathReferenceService(
                context.repositories,
                directory_reader=context.workspace_checkpoint_git_reader,
            ).require_exact(
                ref,
                project_id=context.snapshot.session.project_id,
                session_id=context.snapshot.session.session_id,
            )
            summary = str(invocation.arguments.get("summary") or "")
            if len(summary.encode("utf-8")) > 2048:
                raise ValueError("research index summary exceeds 2048 bytes")
            research_kind = _required_string(invocation, "research_kind")
            if research_kind not in {
                "source_snapshot",
                "citations",
                "notes",
                "analysis",
                "dossier",
                "tool_result",
            }:
                raise ValueError("research_kind is not a closed research file kind")
            research_prefix = f"research/{invocation_id}/"
            if research_kind == "tool_result":
                valid_layout = ref.path.startswith(research_prefix) or ref.path.startswith(
                    "work-products/tool-results/"
                )
            else:
                valid_layout = ref.path.startswith(research_prefix)
            if not valid_layout:
                raise RevisionPathHandoffError(
                    "research file path does not match the versioned invocation layout"
                )
            publication = context.repositories.published_revisions.get(
                ref.publication_id
            )
            if (
                context.agent_id is None
                or publication is None
                or publication.publisher_agent_id != context.agent_id
            ):
                raise RevisionPathHandoffError(
                    "research file index must be authored by the exact publication owner"
                )
            if ref.entry_kind not in {
                RevisionPathEntryKind.FILE,
                RevisionPathEntryKind.LFS_FILE,
            }:
                raise RevisionPathHandoffError(
                    "research file index requires a regular or LFS file"
                )
            with context.repositories.atomic(prefix="research_file_index"):
                context.repositories.revision_path_handoffs.add_ref(ref)
                record = (
                    context.repositories.revision_path_handoffs.add_research_index(
                        index_id=str(
                            invocation.arguments.get("index_id")
                            or f"research_index_{uuid4().hex[:12]}"
                        ),
                        project_id=context.snapshot.session.project_id,
                        session_id=context.snapshot.session.session_id,
                        invocation_id=invocation_id,
                        task_id=engine_invocation.task_id,
                        research_kind=research_kind,
                        ref_id=ref.ref_id,
                        bounded_summary=summary,
                        created_at=utc_now_iso(),
                    )
                )
        except (KeyError, TypeError, ValueError, RevisionPathHandoffError) as exc:
            return _tool_error(
                invocation,
                getattr(exc, "error_code", "research_file_index_invalid"),
                str(exc),
            )
        payload = {**record, "revision_path_ref": ref.to_dict()}
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=engine_invocation.task_id,
            lane_id=invocation.lane_id,
            status="research_file_indexed",
            summary="Indexed bounded research metadata against an exact published file.",
            details=payload,
        )

    registry.register("workspace.publish", publish_handler)
    registry.register("workspace.publication.fetch_identity", fetch_identity_handler)
    registry.register("workspace.publication.audit", audit_handler)
    registry.register("workspace.publication.path_ref", path_ref_handler)
    registry.register(
        "workspace.publication.verify_path_ref",
        verify_path_ref_handler,
    )
    registry.register(
        "workspace.publication.fetch_handoff",
        fetch_handoff_handler,
    )
    registry.register(
        "workspace.publication.index_research_file",
        index_research_file_handler,
    )


def _safe_state_payload(
    state: object,
    *,
    lfs_proof: dict[str, object] | None,
) -> dict[str, object]:
    intent = getattr(state, "intent")
    execution = getattr(state, "execution")
    revision = getattr(state, "revision")
    return {
        "publication_id": intent.publication_id,
        "intent_id": intent.intent_id,
        "repository_binding_id": intent.repository_binding_id,
        "repository_binding_version": intent.repository_binding_version,
        "commit": intent.expected_head_commit,
        "tree": intent.expected_tree,
        "publication_ref": intent.publication_ref,
        "manifest_digest": intent.manifest.manifest_digest,
        "lfs_closure_manifest_digest": (
            None if lfs_proof is None else lfs_proof["manifest_digest"]
        ),
        "lfs_closure_verification_id": (
            None if lfs_proof is None else lfs_proof["verification_id"]
        ),
        "lfs_closure_verification_digest": (
            None if lfs_proof is None else lfs_proof["verification_digest"]
        ),
        "execution_id": execution.execution_id,
        "execution_state": execution.lifecycle_state.value,
        "effect_certainty": execution.effect_certainty.value,
        "retry_eligibility": execution.retry_eligibility.value,
        "materialized": revision is not None,
        "revision_digest": None if revision is None else revision.revision_digest,
        "automatic_retry_performed": False,
        "human_approval_requested": False,
    }


def _required_string(invocation: ToolInvocation, field_name: str) -> str:
    value = invocation.arguments[field_name]
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _optional_string(
    invocation: ToolInvocation,
    field_name: str,
) -> str | None:
    value = invocation.arguments.get(field_name)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or null")
    return value


def _required_integer(invocation: ToolInvocation, field_name: str) -> int:
    value = invocation.arguments[field_name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _required_boolean(invocation: ToolInvocation, field_name: str) -> bool:
    value = invocation.arguments[field_name]
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _tool_error(
    invocation: ToolInvocation,
    error_code: str,
    message: str,
) -> ToolResult:
    payload = {
        "error_code": error_code,
        "message": message,
        "retry_performed": False,
        "fallback_performed": False,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status="workspace_publication_rejected",
        summary=message,
        error_code=error_code,
        details=payload,
    )


__all__ = ["register_workspace_publication_tools"]
