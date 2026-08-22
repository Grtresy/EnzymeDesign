from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from typing import TypeAlias

from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
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


MountedToolRuntime: TypeAlias = (
    ToolRuntimeContribution | KernelToolRuntimeContribution
)


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

    def __post_init__(self) -> None:
        if not self.command_id:
            raise ValueError("runtime tool scope command_id must be non-empty")
        if self.snapshot.declared_tool_catalog_digest != self.catalog.catalog_digest:
            raise ValueError("runtime tool scope catalog identity drifted")
        if self.current_context.declared_catalog.catalog_digest != self.catalog.catalog_digest:
            raise ValueError("runtime tool scope current catalog identity drifted")


class RuntimeToolScopeProvider(Protocol):
    """Load one current command scope without exposing repositories to runtimes."""

    def get(self, command_id: str) -> RuntimeToolScope | None: ...


@dataclass(slots=True)
class MountedRuntimeCapabilityGateway(RuntimeCapabilityGateway):
    """Kernel-owned bridge from a pinned turn to exact mounted tool runtimes."""

    scopes: RuntimeToolScopeProvider
    runtimes: tuple[tuple[str, MountedToolRuntime], ...]

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
        if scope.snapshot.snapshot_digest != affordance_snapshot_digest:
            raise KernelContractError(
                "tool_affordance_stale",
                "runtime requested tools from another affordance snapshot",
                details={"command_id": command_id},
            )
        visible = model_visible_tool_specs(
            snapshot=scope.snapshot,
            catalog=scope.catalog,
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

    def invoke(
        self,
        *,
        command_id: str,
        request: RuntimeToolRequest,
    ) -> ToolResult:
        scope = self._scope(command_id)
        invocation = request.invocation
        if (
            request.affordance_snapshot_digest != scope.snapshot.snapshot_digest
            or invocation.affordance_snapshot_digest
            != scope.snapshot.snapshot_digest
            or invocation.session_id != scope.snapshot.session_id
            or invocation.agent_member_id != scope.snapshot.agent_member_id
        ):
            return self._rejected(
                invocation.call_id,
                invocation.tool_name,
                code="tool_affordance_stale",
                summary="Tool request identity drifted from the bounded turn snapshot.",
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
        if runtime is None or declaration is None or (
            runtime.contract.contract_digest != admission.tool_contract_digest
            or runtime.contract.contract_digest
            != declaration.contract.contract_digest
            or _runtime_owner(runtime) != declaration.owner_component_id
            or runtime.runtime_id != declaration.runtime_id
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
        except Exception:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="runtime_contract_failure",
                summary="The mounted tool runtime failed without a terminal receipt.",
                payload={
                    "effect_certainty": "dispatch_in_doubt",
                    "mutation_applied": None,
                    "fallback_performed": False,
                    "retry_performed": False,
                    "reconcile_required": True,
                },
                error_code="extension_tool_runtime_failed",
                hint="Observe or reconcile the same operation identity; do not retry blindly.",
            )
        if result.call_id != invocation.call_id or result.tool_name != invocation.tool_name:
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

    def _scope(self, command_id: str) -> RuntimeToolScope:
        scope = self.scopes.get(command_id)
        if scope is None or scope.command_id != command_id:
            raise KernelContractError(
                "runtime_tool_scope_missing",
                "runtime command has no current tool scope",
                details={"command_id": command_id},
            )
        return scope

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
