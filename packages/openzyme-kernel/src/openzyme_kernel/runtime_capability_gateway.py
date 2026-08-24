from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Protocol
from typing import TypeAlias

from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_extension_spi import ToolRuntimeContribution
from openzyme_extension_spi import ToolDispatchBinding
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeToolInvocationError
from openzyme_runtime_spi import RuntimeToolRequest

from .affordance import ToolAffordanceContext
from .affordance import model_visible_tool_specs
from .affordance import revalidate_tool_dispatch
from .catalog import DeclaredToolCatalog
from .deployment_activation import DeploymentActivationGate
from .deployment_activation import DeploymentSurface
from .errors import KernelContractError
from .extension_mount import MountedExtensionSurfaces
from .tool_exposure import CommandToolExpansionStorePort
from .tool_exposure import inspect_and_expand_tool_exposure
from .tool_exposure import model_visible_exposed_tool_specs


class KernelToolRuntimeContribution(Protocol):
    """Runtime for one Kernel-owned base tool.

    Kernel base tools share the invocation shape with Plugin tools, but they are
    deliberately identified by ``owner_component_id`` rather than pretending
    that the Kernel is a Plugin.
    """

    @property
    def owner_component_id(self) -> str: ...

    @property
    def runtime_id(self) -> str: ...

    @property
    def contract(self) -> ToolSpec: ...

    def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


MountedToolRuntime: TypeAlias = ToolRuntimeContribution | KernelToolRuntimeContribution


@dataclass(frozen=True, slots=True)
class MountedRuntimeToolSet:
    """Exact runtime closure for one activated declared-tool catalog."""

    activation_digest: str
    declared_tool_catalog_digest: str
    extension_mount_digest: str
    tools: tuple[tuple[str, MountedToolRuntime], ...]
    mount_digest: str

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.tools)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("mounted runtime tool set must be unique and sorted")
        expected = canonical_sha256_digest(self.digest_payload())
        if self.mount_digest != expected:
            raise ValueError("mounted runtime tool set digest drifted")

    def digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_mounted_runtime_tool_set@1",
            "activation_digest": self.activation_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "extension_mount_digest": self.extension_mount_digest,
            "tools": [
                {
                    "tool_name": name,
                    "owner_component_id": _runtime_owner(runtime),
                    "runtime_id": runtime.runtime_id,
                    "contract_digest": runtime.contract.contract_digest,
                }
                for name, runtime in self.tools
            ],
        }


def mount_runtime_tool_set(
    *,
    gate: DeploymentActivationGate,
    catalog: DeclaredToolCatalog,
    kernel_runtimes: tuple[KernelToolRuntimeContribution, ...],
    extension_surfaces: MountedExtensionSurfaces,
) -> MountedRuntimeToolSet:
    """Join Kernel and Plugin runtimes against one exact active catalog."""

    authorization = gate.require_active(DeploymentSurface.RUNTIME)
    epoch = gate.validate_authorization(
        authorization,
        surface=DeploymentSurface.RUNTIME,
    )
    if extension_surfaces.activation_digest != epoch.activation_digest:
        raise KernelContractError(
            "runtime_tool_mount_activation_drift",
            "runtime tools and extension surfaces belong to different activations",
        )
    if catalog.catalog_digest != epoch.release_identity.declared_tool_catalog_digest:
        raise KernelContractError(
            "runtime_tool_catalog_activation_drift",
            "runtime tool catalog differs from the active release identity",
        )
    mounted: dict[str, MountedToolRuntime] = {}
    for runtime in kernel_runtimes:
        name = runtime.contract.tool_name
        if name in mounted:
            raise KernelContractError(
                "tool_runtime_collision",
                "multiple runtimes claim the same canonical tool name",
                details={"tool_name": name},
            )
        mounted[name] = runtime
    for name, runtime in extension_surfaces.tools:
        if name in mounted:
            raise KernelContractError(
                "tool_runtime_collision",
                "Kernel and Plugin runtimes claim the same canonical tool name",
                details={"tool_name": name},
            )
        mounted[name] = runtime

    expected = {entry.contract.tool_name: entry for entry in catalog.entries}
    missing = tuple(sorted(set(expected).difference(mounted)))
    unexpected = tuple(sorted(set(mounted).difference(expected)))
    if missing or unexpected:
        raise KernelContractError(
            "tool_runtime_catalog_mismatch",
            "mounted runtimes do not exactly close the declared tool catalog",
            details={
                "missing_tool_names": missing,
                "unexpected_tool_names": unexpected,
            },
        )
    for name, entry in expected.items():
        runtime = mounted[name]
        if (
            _runtime_owner(runtime) != entry.owner_component_id
            or runtime.runtime_id != entry.runtime_id
            or runtime.contract.contract_digest != entry.contract.contract_digest
        ):
            raise KernelContractError(
                "tool_runtime_contract_drift",
                "mounted runtime differs from the exact declared tool entry",
                details={"tool_name": name},
            )
    tools = tuple((name, mounted[name]) for name in sorted(mounted))
    payload = {
        "schema_version": "openzyme_mounted_runtime_tool_set@1",
        "activation_digest": epoch.activation_digest,
        "declared_tool_catalog_digest": catalog.catalog_digest,
        "extension_mount_digest": extension_surfaces.mount_digest,
        "tools": [
            {
                "tool_name": name,
                "owner_component_id": _runtime_owner(runtime),
                "runtime_id": runtime.runtime_id,
                "contract_digest": runtime.contract.contract_digest,
            }
            for name, runtime in tools
        ],
    }
    return MountedRuntimeToolSet(
        activation_digest=epoch.activation_digest,
        declared_tool_catalog_digest=catalog.catalog_digest,
        extension_mount_digest=extension_surfaces.mount_digest,
        tools=tools,
        mount_digest=canonical_sha256_digest(payload),
    )


@dataclass(frozen=True, slots=True)
class RuntimeToolScope:
    command_id: str
    catalog: DeclaredToolCatalog
    snapshot: ToolAffordanceSnapshot
    current_context: ToolAffordanceContext
    exposure_snapshot: ToolExposureSnapshot | None = None
    current_workflow_authority: WorkflowAuthorityBinding | None = None

    def __post_init__(self) -> None:
        if not self.command_id:
            raise ValueError("runtime tool scope command_id must be non-empty")
        if self.snapshot.declared_tool_catalog_digest != self.catalog.catalog_digest:
            raise ValueError("runtime tool scope catalog identity drifted")
        if (
            self.current_context.declared_catalog.catalog_digest
            != self.catalog.catalog_digest
        ):
            raise ValueError("runtime tool scope current catalog identity drifted")
        if (self.exposure_snapshot is None) != (
            self.current_workflow_authority is None
        ):
            raise ValueError(
                "runtime tool scope exposure and workflow authority must be complete"
            )
        if self.exposure_snapshot is not None:
            exposure = self.exposure_snapshot
            mismatches = (
                exposure.session_id != self.snapshot.session_id,
                exposure.agent_member_id != self.snapshot.agent_member_id,
                exposure.turn_id != self.snapshot.turn_id,
                exposure.affordance_snapshot_id != self.snapshot.snapshot_id,
                exposure.affordance_snapshot_digest != self.snapshot.snapshot_digest,
            )
            if any(mismatches):
                raise ValueError("runtime tool scope exposure identity drifted")


class RuntimeToolScopeProvider(Protocol):
    """Load one current command scope without exposing repositories to runtimes."""

    def get(self, command_id: str) -> RuntimeToolScope | None: ...


@dataclass(slots=True)
class MountedRuntimeCapabilityGateway(RuntimeCapabilityGateway):
    """Kernel-owned bridge from a pinned turn to exact mounted tool runtimes."""

    scopes: RuntimeToolScopeProvider
    runtimes: tuple[tuple[str, MountedToolRuntime], ...]
    expansions: CommandToolExpansionStorePort | None = None
    clock: ClockPort | None = None

    def __post_init__(self) -> None:
        names = [name for name, _ in self.runtimes]
        if names != sorted(names) or len(set(names)) != len(names):
            raise ValueError("mounted runtime tools must be unique and sorted")
        for name, runtime in self.runtimes:
            if runtime.contract.tool_name != name:
                raise ValueError("mounted runtime tool identity drifted")

    def list_tools(
        self,
        *,
        command_id: str,
        affordance_snapshot_digest: str,
    ) -> tuple[ToolSpec, ...]:
        scope = self._scope(command_id)
        self._validate_current_turn_scope(scope)
        if scope.snapshot.snapshot_digest != affordance_snapshot_digest:
            raise KernelContractError(
                "tool_affordance_stale",
                "runtime requested tools from another affordance snapshot",
                details={"command_id": command_id},
            )
        if scope.exposure_snapshot is None:
            visible = model_visible_tool_specs(
                snapshot=scope.snapshot,
                catalog=scope.catalog,
            )
        else:
            expansion = (
                None if self.expansions is None else self.expansions.get(command_id)
            )
            visible = model_visible_exposed_tool_specs(
                catalog=scope.catalog,
                affordance_snapshot=scope.snapshot,
                exposure_snapshot=scope.exposure_snapshot,
                expansion=expansion,
            )
        mounted = dict(self.runtimes)
        missing = sorted(
            spec.tool_name for spec in visible if spec.tool_name not in mounted
        )
        if missing:
            raise KernelContractError(
                "tool_runtime_not_mounted",
                "one or more visible tools lack an exact mounted runtime",
                details={"tool_names": missing},
            )
        return visible

    def revalidate_provider_step(
        self,
        *,
        command_id: str,
        workflow_authority_id: str,
        workflow_authority_epoch: int,
        workflow_authority_digest: str,
        tool_exposure_snapshot_id: str,
        tool_exposure_snapshot_digest: str,
    ) -> None:
        """Fence every provider step against current workflow and exposure state."""

        scope = self._scope(command_id)
        exposure = scope.exposure_snapshot
        if exposure is None:
            raise KernelContractError(
                "runtime_tool_exposure_scope_missing",
                "Runtime command has no exact tool exposure scope",
                details={"command_id": command_id, "fallback_performed": False},
            )
        supplied = (
            workflow_authority_id,
            workflow_authority_epoch,
            workflow_authority_digest,
            tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest,
        )
        expected = (
            exposure.workflow_authority_id,
            exposure.workflow_authority_epoch,
            exposure.workflow_authority_digest,
            exposure.exposure_snapshot_id,
            exposure.exposure_snapshot_digest,
        )
        if supplied != expected:
            raise KernelContractError(
                "runtime_turn_fence_stale",
                "Provider step identities differ from the exact runtime command scope",
                details={"command_id": command_id, "fallback_performed": False},
            )
        self._validate_current_turn_scope(scope)

    def invoke(
        self,
        *,
        command_id: str,
        request: RuntimeToolRequest,
    ) -> ToolResult:
        scope = self._scope(command_id)
        invocation = request.invocation
        try:
            self._validate_current_turn_scope(scope)
        except KernelContractError as exc:
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code=exc.code,
                summary=str(exc),
            )
        if (
            request.affordance_snapshot_digest != scope.snapshot.snapshot_digest
            or invocation.affordance_snapshot_digest != scope.snapshot.snapshot_digest
            or invocation.session_id != scope.snapshot.session_id
            or invocation.agent_member_id != scope.snapshot.agent_member_id
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="tool_affordance_stale",
                summary="Tool request identity drifted from the bounded turn snapshot.",
            )
        if scope.exposure_snapshot is not None:
            try:
                presented = self._is_presented(scope, invocation.tool_name)
            except KernelContractError as exc:
                return self._rejected(
                    invocation.call_id,
                    invocation.tool_name,
                    code=exc.code,
                    summary=str(exc),
                )
            if not presented:
                return self._undisclosed_rejection(
                    invocation.call_id,
                    code="tool_not_exposed",
                    summary="The requested tool is not exposed in this runtime command.",
                )
        try:
            admission = revalidate_tool_dispatch(
                snapshot=scope.snapshot,
                context=scope.current_context,
                tool_name=invocation.tool_name,
                selected_route_id=invocation.route_id,
            )
        except KernelContractError as exc:
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code=exc.code,
                summary=str(exc),
            )
        runtime = dict(self.runtimes).get(invocation.tool_name)
        declaration = scope.catalog.get(invocation.tool_name)
        if (
            runtime is None
            or declaration is None
            or (
                runtime.contract.contract_digest != admission.tool_contract_digest
                or runtime.contract.contract_digest
                != declaration.contract.contract_digest
                or _runtime_owner(runtime) != declaration.owner_component_id
                or runtime.runtime_id != declaration.runtime_id
            )
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="tool_runtime_not_mounted",
                summary="The exact admitted tool runtime is not mounted.",
            )
        route = next(
            (
                item
                for item in scope.current_context.capability_registry.route_refs
                if item.route_id == admission.route_id
            ),
            None,
        )
        if admission.route_id is not None and (
            route is None
            or route.route_digest != admission.route_digest
            or route.driver_id != admission.driver_id
            or route.target_id != admission.target_id
            or route.inventory_generation != admission.inventory_generation
            or route.capability_proof_digest != admission.capability_proof_digest
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="tool_affordance_stale",
                summary="The admitted route proof changed before Plugin dispatch.",
            )
        if invocation.tool_name == "capabilities.inspect":
            return self._inspect_capabilities(scope, invocation)
        try:
            admitted_invoke = getattr(runtime, "invoke_admitted", None)
            if callable(admitted_invoke):
                dispatch = ToolDispatchBinding(
                    tool_name=admission.tool_name,
                    tool_contract_digest=admission.tool_contract_digest,
                    affordance_snapshot_digest=admission.snapshot_digest,
                    capability_binding_digest=admission.capability_binding_digest,
                    extension_bundle_digest=(
                        scope.current_context.capability_binding.extension_bundle_digest
                    ),
                    authority_lease_id=scope.current_context.authority_lease.lease_id,
                    authority_lease_digest=admission.authority_lease_digest,
                    authority_generation=(
                        scope.current_context.authority_lease.generation
                    ),
                    authority_fence=scope.current_context.authority_lease.fence,
                    workspace_generation=admission.workspace_generation,
                    route_id=None if route is None else route.route_id,
                    route_digest=None if route is None else route.route_digest,
                    provider_component_id=(
                        None if route is None else route.provider_component_id
                    ),
                    driver_id=None if route is None else route.driver_id,
                    target_id=None if route is None else route.target_id,
                    inventory_generation=(
                        None if route is None else route.inventory_generation
                    ),
                    inventory_digest=(
                        None if route is None else route.inventory_digest
                    ),
                    qualification_digest=(
                        None if route is None else route.capability_proof_digest
                    ),
                    capability_proof_digest=(
                        None if route is None else route.capability_proof_digest
                    ),
                )
                result = admitted_invoke(invocation, dispatch)
            else:
                result = runtime.invoke(invocation)
        except RuntimeToolInvocationError as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status=exc.status,
                summary=exc.summary,
                payload={
                    "effect_certainty": exc.effect_certainty.value,
                    "mutation_applied": exc.mutation_applied,
                    "fallback_performed": False,
                    "retry_performed": False,
                    "reconcile_required": exc.reconcile_required,
                    "diagnostic_id": exc.diagnostic_id,
                },
                error_code=exc.code,
                hint=exc.hint,
            )
        except Exception as exc:
            return self._unclassified_runtime_failure(
                scope=scope,
                invocation=invocation,
                runtime=runtime,
                error=exc,
            )
        if (
            result.call_id != invocation.call_id
            or result.tool_name != invocation.tool_name
        ):
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="runtime_contract_failure",
                summary="The mounted tool runtime returned a mismatched receipt identity.",
                payload={
                    "effect_certainty": "dispatch_in_doubt",
                    "mutation_applied": None,
                    "fallback_performed": False,
                    "retry_performed": False,
                    "reconcile_required": True,
                },
                error_code="extension_tool_receipt_identity_mismatch",
                hint="Observe or reconcile the original operation identity.",
            )
        return result

    def _validate_current_turn_scope(self, scope: RuntimeToolScope) -> None:
        if scope.current_context.authority_lease.state.value != "active":
            raise KernelContractError(
                "tool_affordance_stale",
                "Current agent authority lease is not active",
                details={"command_id": scope.command_id, "fallback_performed": False},
            )
        exposure = scope.exposure_snapshot
        if exposure is None:
            return
        authority = scope.current_workflow_authority
        if authority is None:
            raise KernelContractError(
                "workflow_authority_scope_missing",
                "Runtime command has no current workflow authority binding",
                details={"command_id": scope.command_id, "fallback_performed": False},
            )
        mismatches = {
            "authority_status": authority.status is not WorkflowAuthorityStatus.ACTIVE,
            "authority_id": authority.authority_id != exposure.workflow_authority_id,
            "authority_epoch": authority.epoch != exposure.workflow_authority_epoch,
            "authority_digest": (
                authority.binding_digest != exposure.workflow_authority_digest
            ),
            "session": authority.session_id != exposure.session_id,
            "actor": authority.authorized_actor_id != exposure.agent_member_id,
            "capability_binding": (
                scope.current_context.capability_binding.binding_digest
                != exposure.capability_binding_digest
            ),
        }
        drifted = sorted(name for name, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "runtime_turn_fence_stale",
                "Current workflow or capability fences differ from the runtime command",
                details={
                    "command_id": scope.command_id,
                    "drifted_fields": drifted,
                    "fallback_performed": False,
                },
            )

    def _is_presented(self, scope: RuntimeToolScope, tool_name: str) -> bool:
        exposure = scope.exposure_snapshot
        assert exposure is not None
        decision = next(
            (item for item in exposure.decisions if item.tool_name == tool_name),
            None,
        )
        if decision is None or decision.exposure is ToolExposure.HIDDEN:
            return False
        if decision.exposure is ToolExposure.DIRECT:
            return True
        expansion = (
            None if self.expansions is None else self.expansions.get(scope.command_id)
        )
        if expansion is None:
            return False
        # The shared model-visible resolver validates the expansion's exact
        # command/exposure/workflow closure before we rely on its names.
        model_visible_exposed_tool_specs(
            catalog=scope.catalog,
            affordance_snapshot=scope.snapshot,
            exposure_snapshot=exposure,
            expansion=expansion,
        )
        return tool_name in expansion.expanded_tool_names

    def _inspect_capabilities(
        self,
        scope: RuntimeToolScope,
        invocation: ToolInvocation,
    ) -> ToolResult:
        exposure = scope.exposure_snapshot
        if exposure is None or self.expansions is None or self.clock is None:
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="tool_exposure_expansion_unavailable",
                summary="The exact command-scoped exposure state is unavailable.",
            )
        arguments = dict(invocation.arguments)
        unexpected = set(arguments).difference(
            {"query", "expand_tool_names", "max_items"}
        )
        if unexpected:
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="invalid_tool_arguments",
                summary=f"capabilities.inspect arguments are closed: {sorted(unexpected)}",
            )
        query = arguments.get("query")
        raw_names = arguments.get("expand_tool_names", ())
        max_items = arguments.get("max_items", 50)
        if query is not None and not isinstance(query, str):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="invalid_tool_arguments",
                summary="capabilities.inspect query must be a string or null.",
            )
        if not isinstance(raw_names, tuple | list) or any(
            not isinstance(item, str) for item in raw_names
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="invalid_tool_arguments",
                summary="expand_tool_names must be an array of exact tool names.",
            )
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= 200
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="invalid_tool_arguments",
                summary="max_items must be an integer between 1 and 200.",
            )
        current = self.expansions.get(scope.command_id)
        try:
            inspection = inspect_and_expand_tool_exposure(
                command_id=scope.command_id,
                catalog=scope.catalog,
                affordance_snapshot=scope.snapshot,
                exposure_snapshot=exposure,
                current_expansion=current,
                requested_tool_names=tuple(raw_names),
                query=query,
                max_items=max_items,
                created_at=self.clock.now_iso(),
            )
            next_expansion = inspection.expansion
            changed = next_expansion is not None and (
                current is None
                or next_expansion.expansion_digest != current.expansion_digest
            )
            if changed:
                assert next_expansion is not None
                self.expansions.put(
                    next_expansion,
                    expected_revision=(
                        0 if current is None else current.expansion_revision
                    ),
                )
        except (KernelContractError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, KernelContractError)
                else "invalid_tool_arguments"
            )
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code=code,
                summary=str(exc),
            )
        except Exception:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="runtime_contract_failure",
                summary="Command-scoped tool expansion could not be settled.",
                payload={
                    "effect_certainty": "dispatch_in_doubt",
                    "mutation_applied": None,
                    "fallback_performed": False,
                    "retry_performed": False,
                    "reconcile_required": True,
                },
                error_code="tool_expansion_settlement_failed",
                hint="Observe the exact command expansion before retrying.",
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="capabilities_inspected",
            summary="Inspected bounded non-Hidden capabilities for this command.",
            payload={
                "inspection": inspection.to_dict(),
                "command_scope_expansion_applied": changed,
                "mutation_applied": changed,
                "task_transition_performed": False,
                "authority_widened": False,
                "route_changed": False,
                "fallback_performed": False,
            },
        )

    def _scope(self, command_id: str) -> RuntimeToolScope:
        scope = self.scopes.get(command_id)
        if scope is None or scope.command_id != command_id:
            raise KernelContractError(
                "runtime_tool_scope_missing",
                "runtime command has no current tool scope",
                details={"command_id": command_id},
            )
        return scope

    def _unclassified_runtime_failure(
        self,
        *,
        scope: RuntimeToolScope,
        invocation: ToolInvocation,
        runtime: MountedToolRuntime,
        error: Exception,
    ) -> ToolResult:
        occurrence_digest = canonical_sha256_digest(
            {
                "command_id": scope.command_id,
                "call_id": invocation.call_id,
                "tool_name": invocation.tool_name,
                "runtime_id": runtime.runtime_id,
                "contract_digest": runtime.contract.contract_digest,
                "error_code": "extension_tool_runtime_failed",
            }
        ).removeprefix("sha256:")[:24]
        component = _runtime_owner(runtime)
        operation = (
            "invoke_admitted"
            if callable(getattr(runtime, "invoke_admitted", None))
            else "invoke"
        )
        identities = {
            "command_id": scope.command_id,
            "component_id": component,
        }
        if invocation.route_id is not None:
            identities["route_id"] = invocation.route_id
        records = observe_structured_failure(
            error,
            context=StructuredFailureContext(
                failure_id=f"failure_{occurrence_digest}",
                diagnostic_id=f"diagnostic_{occurrence_digest}",
                session_id=invocation.session_id,
                component=component,
                operation=operation,
                phase="tool_dispatch",
                source_kind="mounted_tool_runtime",
                source_ref=invocation.call_id,
                source_version=runtime.contract.contract_digest,
                created_at=(
                    self.clock.now_iso()
                    if self.clock is not None
                    else datetime.now(UTC).isoformat()
                ),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                agent_id=scope.current_context.authority_lease.agent_id,
                correlation_id=scope.command_id,
            ),
            failure_class=FailureClass.TOOL,
            recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            actor_kind=FailureActorKind.HARNESS,
            error_code="extension_tool_runtime_failed",
            safe_summary=(
                "The mounted tool runtime failed after dispatch began without "
                "a terminal receipt."
            ),
            safe_hint=(
                "Observe or reconcile the same operation identity; do not retry blindly."
            ),
            next_action="reconcile_exact_tool_dispatch",
            mutation_applied=None,
            fallback_performed=False,
            reconcile_required=True,
            identities=identities,
            likely_causes=(
                "The mounted runtime raised before producing a typed terminal receipt.",
            ),
            private_context={
                "command_id": scope.command_id,
                "invocation": invocation.to_dict(),
                "owner_component_id": component,
                "runtime_id": runtime.runtime_id,
            },
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="runtime_contract_failure",
            summary=records.public.safe_summary,
            payload={
                "effect_certainty": "dispatch_in_doubt",
                "mutation_applied": None,
                "fallback_performed": False,
                "retry_performed": False,
                "reconcile_required": True,
                "diagnostic_id": records.public.diagnostic_id,
            },
            error_code=records.public.error_code,
            hint=records.public.safe_hint,
            failure_observation=records.public.to_dict(),
            terminates_turn=True,
            private_diagnostic=records.private,
        )

    @staticmethod
    def _rejected(
        call_id: str,
        tool_name: str,
        *,
        code: str,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "effect_certainty": "no_effect",
                "mutation_applied": False,
                "fallback_performed": False,
                "retry_performed": False,
                "reconcile_required": False,
            },
            error_code=code,
        )

    @staticmethod
    def _undisclosed_rejection(
        call_id: str,
        *,
        code: str,
        summary: str,
    ) -> ToolResult:
        """Reject an unexposed guess without echoing its Hidden/unknown name."""

        return ToolResult(
            call_id=call_id,
            tool_name="unexposed.tool",
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "effect_certainty": "no_effect",
                "mutation_applied": False,
                "fallback_performed": False,
                "retry_performed": False,
                "reconcile_required": False,
            },
            error_code=code,
        )


def _runtime_owner(runtime: MountedToolRuntime) -> str:
    owner = getattr(runtime, "owner_component_id", None)
    if isinstance(owner, str):
        return owner
    owner = getattr(runtime, "owner_plugin_id", None)
    if isinstance(owner, str):
        return owner
    raise ValueError("mounted runtime has no component owner identity")


__all__ = [
    "KernelToolRuntimeContribution",
    "MountedRuntimeCapabilityGateway",
    "MountedRuntimeToolSet",
    "RuntimeToolScope",
    "RuntimeToolScopeProvider",
    "mount_runtime_tool_set",
]
