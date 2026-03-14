from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .execution import ExecutionResult
    from .plan_runtime import PlanStep


@dataclass(slots=True)
class CapabilityToolDescriptor:
    tool: str
    title: str
    description: str
    input_keys: list[str]
    result_kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilitySummary:
    capability_id: str
    server_name: str
    title: str
    summary: str
    use_when: list[str]
    result_kind: str
    cost_hint: str
    inspect_handle: str
    selectable: bool = True
    tool_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["_meta"] = payload.pop("metadata")
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CapabilitySummary:
        return cls(
            capability_id=str(payload.get("capability_id") or ""),
            server_name=str(payload.get("server_name") or ""),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            use_when=[str(item) for item in payload.get("use_when") or []],
            result_kind=str(payload.get("result_kind") or ""),
            cost_hint=str(payload.get("cost_hint") or ""),
            inspect_handle=str(payload.get("inspect_handle") or ""),
            selectable=bool(payload.get("selectable", True)),
            tool_names=[str(item) for item in payload.get("tool_names") or []],
            metadata=dict(payload.get("_meta") or {}),
        )


@dataclass(slots=True)
class CapabilityDetailContract:
    capability_id: str
    server_name: str
    title: str
    summary: str
    use_when: list[str]
    result_kind: str
    cost_hint: str
    selection_hint: str
    tools: list[CapabilityToolDescriptor]
    resources: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "server_name": self.server_name,
            "title": self.title,
            "summary": self.summary,
            "use_when": self.use_when,
            "result_kind": self.result_kind,
            "cost_hint": self.cost_hint,
            "selection_hint": self.selection_hint,
            "tools": [item.to_dict() for item in self.tools],
            "resources": self.resources,
            "prompts": self.prompts,
            "_meta": self.metadata,
        }


@dataclass(slots=True)
class CapabilityVisibilityScope:
    episode_id: str
    active_state_version: int
    role: str = "host-agent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CapabilityVisibilityScope:
        return cls(
            episode_id=str(payload.get("episode_id") or ""),
            active_state_version=int(payload.get("active_state_version") or 0),
            role=str(payload.get("role") or "host-agent"),
        )


@dataclass(slots=True)
class InspectedCapabilityBinding:
    contract: CapabilityDetailContract
    scope: CapabilityVisibilityScope
    inspected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.to_dict(),
            "scope": self.scope.to_dict(),
            "inspected_at": self.inspected_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InspectedCapabilityBinding:
        return cls(
            contract=CapabilityDetailContract(
                capability_id=str(payload.get("contract", {}).get("capability_id") or ""),
                server_name=str(payload.get("contract", {}).get("server_name") or ""),
                title=str(payload.get("contract", {}).get("title") or ""),
                summary=str(payload.get("contract", {}).get("summary") or ""),
                use_when=[str(item) for item in payload.get("contract", {}).get("use_when") or []],
                result_kind=str(payload.get("contract", {}).get("result_kind") or ""),
                cost_hint=str(payload.get("contract", {}).get("cost_hint") or ""),
                selection_hint=str(payload.get("contract", {}).get("selection_hint") or ""),
                tools=[
                    CapabilityToolDescriptor(
                        tool=str(item.get("tool") or ""),
                        title=str(item.get("title") or ""),
                        description=str(item.get("description") or ""),
                        input_keys=[str(key) for key in item.get("input_keys") or []],
                        result_kind=str(item.get("result_kind") or ""),
                    )
                    for item in payload.get("contract", {}).get("tools") or []
                    if isinstance(item, dict)
                ],
                resources=[str(item) for item in payload.get("contract", {}).get("resources") or []],
                prompts=[str(item) for item in payload.get("contract", {}).get("prompts") or []],
                metadata=dict(payload.get("contract", {}).get("_meta") or {}),
            ),
            scope=CapabilityVisibilityScope.from_dict(dict(payload.get("scope") or {})),
            inspected_at=str(payload.get("inspected_at") or ""),
        )


@dataclass(slots=True)
class WorkflowAuditEvent:
    event_id: str
    event_type: str
    episode_id: str
    state_version: int
    timestamp: str
    role: str = "host-agent"
    refs: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NormalizedExecutionResult:
    capability_id: str
    run_id: str
    status: str
    manifest_payload: dict[str, Any]
    output_refs: list[dict[str, str]] = field(default_factory=list)

    def to_execution_result(self) -> ExecutionResult:
        from .execution import ExecutionResult

        return ExecutionResult(
            run_id=self.run_id,
            status=self.status,
            manifest_payload=self.manifest_payload,
            capability_id=self.capability_id,
            output_refs=list(self.output_refs),
        )


class CapabilityAdapter(Protocol):
    capability_id: str

    def summary(self) -> CapabilitySummary: ...

    def detail_contract(self) -> CapabilityDetailContract: ...

    def supports_tool(self, tool: str) -> bool: ...

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult: ...


@dataclass(slots=True)
class StaticCapabilityAdapter:
    capability_id: str
    server_name: str
    title: str
    use_when: list[str]
    result_kind: str
    cost_hint: str
    selection_hint: str
    tool_descriptors: list[CapabilityToolDescriptor]
    executor: Any | None = None
    selectable: bool = True
    summary_override: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> CapabilitySummary:
        summary_text = self.summary_override or self._metadata_summary() or self._auto_summary()
        return CapabilitySummary(
            capability_id=self.capability_id,
            server_name=self.server_name,
            title=self.title,
            summary=summary_text,
            use_when=list(self.use_when),
            result_kind=self.result_kind,
            cost_hint=self.cost_hint,
            inspect_handle=self.capability_id,
            selectable=self.selectable,
            tool_names=[item.tool for item in self.tool_descriptors],
            metadata=dict(self.metadata),
        )

    def detail_contract(self) -> CapabilityDetailContract:
        summary = self.summary()
        return CapabilityDetailContract(
            capability_id=self.capability_id,
            server_name=self.server_name,
            title=self.title,
            summary=summary.summary,
            use_when=list(summary.use_when),
            result_kind=summary.result_kind,
            cost_hint=summary.cost_hint,
            selection_hint=self.selection_hint,
            tools=list(self.tool_descriptors),
            metadata=dict(self.metadata),
        )

    def supports_tool(self, tool: str) -> bool:
        return any(item.tool == tool for item in self.tool_descriptors)

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        if self.executor is None:
            raise RuntimeError(f"Capability {self.capability_id} does not execute tools directly.")
        result = self.executor.run_step(project_root, episode_id, step)
        result.capability_id = self.capability_id
        if not result.output_refs:
            refs = result.manifest_payload.get("output_refs")
            if isinstance(refs, list):
                result.output_refs = [dict(item) for item in refs if isinstance(item, dict)]
        return result

    def _auto_summary(self) -> str:
        tools = ", ".join(item.tool for item in self.tool_descriptors[:3])
        return f"{self.title} provides {self.result_kind} workflows via {tools}."

    def _metadata_summary(self) -> str | None:
        summary = self.metadata.get("summary")
        if isinstance(summary, str):
            rendered = summary.strip()
            if rendered:
                return rendered
        return None


class HostCapabilityGateway:
    def __init__(self, adapters: list[CapabilityAdapter] | None = None, *, executor: Any | None = None) -> None:
        if adapters is None:
            adapters = default_capability_adapters()
        self._adapters = {adapter.capability_id: adapter for adapter in adapters}
        self._executor = executor

    def list_summaries(self, *, include_hidden: bool = False) -> list[CapabilitySummary]:
        summaries = [adapter.summary() for adapter in self._adapters.values()]
        if not include_hidden:
            summaries = [item for item in summaries if item.selectable]
        return sorted(summaries, key=lambda item: item.capability_id)

    def inspect(self, capability_id: str) -> CapabilityDetailContract:
        adapter = self._require_adapter(capability_id)
        return adapter.detail_contract()

    def resolve_capability_for_tool(self, tool: str) -> str | None:
        for adapter in self._adapters.values():
            if adapter.supports_tool(tool):
                return adapter.capability_id
        return None

    def supports_tool(self, tool: str) -> bool:
        return self.resolve_capability_for_tool(tool) is not None

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> NormalizedExecutionResult:
        capability_id = self.resolve_capability_for_tool(step.tool)
        if capability_id is None:
            raise RuntimeError(f"Unsupported execution tool: {step.tool}")
        adapter = self._require_adapter(capability_id)
        if self._executor is not None and self._executor.supports(step.tool):
            result = self._executor.run_step(project_root, episode_id, step)
            result.capability_id = capability_id
            if not result.output_refs:
                refs = result.manifest_payload.get("output_refs")
                if isinstance(refs, list):
                    result.output_refs = [dict(item) for item in refs if isinstance(item, dict)]
        else:
            result = adapter.run_step(project_root, episode_id, step)
        output_refs = result.output_refs or [
            dict(item) for item in result.manifest_payload.get("output_refs") or [] if isinstance(item, dict)
        ]
        return NormalizedExecutionResult(
            capability_id=capability_id,
            run_id=result.run_id,
            status=result.status,
            manifest_payload=result.manifest_payload,
            output_refs=output_refs,
        )

    def _require_adapter(self, capability_id: str) -> CapabilityAdapter:
        try:
            return self._adapters[capability_id]
        except KeyError as exc:
            raise RuntimeError(f"Unknown capability: {capability_id}") from exc


def default_capability_adapters() -> list[CapabilityAdapter]:
    from .execution import HpcToolContractsExecutor
    from .execution import LocalPreprocessExecutor

    preprocess = StaticCapabilityAdapter(
        capability_id="mcp-preprocess",
        server_name="mcp-preprocess",
        title="Preprocess molecular inputs",
        use_when=[
            "You need to prepare receptor or ligand inputs before downstream analysis.",
            "You need local format conversion or 3D conformer generation.",
        ],
        result_kind="prepared local files",
        cost_hint="local and low-latency",
        selection_hint="Inspect this capability when the next step needs local molecular preprocessing.",
        tool_descriptors=[
            CapabilityToolDescriptor(
                tool="convert_format",
                title="Convert molecular format",
                description="Convert a local molecular file into another supported format.",
                input_keys=["input", "output", "fmt_out"],
                result_kind="converted file",
            ),
            CapabilityToolDescriptor(
                tool="smiles_to_3d",
                title="Generate 3D conformer",
                description="Generate one or more 3D conformers from a SMILES string.",
                input_keys=["smiles", "output", "n_confs"],
                result_kind="3D structure file",
            ),
            CapabilityToolDescriptor(
                tool="prepare_receptor",
                title="Prepare receptor",
                description="Prepare a receptor structure for downstream docking or scoring.",
                input_keys=["input", "output"],
                result_kind="prepared receptor file",
            ),
            CapabilityToolDescriptor(
                tool="prepare_ligand",
                title="Prepare ligand",
                description="Prepare a ligand from an input file or SMILES string.",
                input_keys=["input", "smiles", "output"],
                result_kind="prepared ligand file",
            ),
        ],
        executor=LocalPreprocessExecutor(),
        summary_override="Local molecular preprocessing capability for format conversion, receptor preparation, ligand preparation, and conformer generation.",
    )
    hpc = StaticCapabilityAdapter(
        capability_id="mcp-hpc-tool-contracts",
        server_name="mcp-hpc-tool-contracts",
        title="Run HPC-backed analysis tools",
        use_when=[
            "You need structure analysis, sequence search, prediction, or docking that is routed through the HPC contracts layer.",
            "You need contract-wrapped execution instead of local preprocessing.",
        ],
        result_kind="run manifest and fetched artifacts",
        cost_hint="remote and potentially high-cost",
        selection_hint="Inspect this capability when the next step needs an HPC-backed tool such as fpocket, hhblits, folding, tunnels, or docking.",
        tool_descriptors=[
            CapabilityToolDescriptor(
                tool="fpocket",
                title="Pocket detection",
                description="Run fpocket via the HPC contracts layer.",
                input_keys=["pdb"],
                result_kind="pocket analysis artifacts",
            ),
            CapabilityToolDescriptor(
                tool="hhblits",
                title="Sequence search",
                description="Run hhblits against the configured databases.",
                input_keys=["fasta", "db"],
                result_kind="search results",
            ),
            CapabilityToolDescriptor(
                tool="vina",
                title="Dock ligand",
                description="Run docking through the HPC contracts layer.",
                input_keys=["receptor_pdbqt", "ligand_pdbqt"],
                result_kind="docking artifacts",
            ),
        ],
        executor=HpcToolContractsExecutor(),
        summary_override="HPC-backed capability for structure analysis, sequence search, folding, tunnels, and docking through normalized tool contracts.",
    )
    project_memory = StaticCapabilityAdapter(
        capability_id="mcp-project-memory",
        server_name="mcp-project-memory",
        title="Canonical project memory",
        use_when=[
            "Use indirectly through runtime to read or persist canonical project and episode state.",
        ],
        result_kind="canonical state resources",
        cost_hint="local canonical state service",
        selection_hint="This capability is hidden from default agent tool selection and is used by runtime as the canonical state service boundary.",
        tool_descriptors=[
            CapabilityToolDescriptor(
                tool="update_episode_state",
                title="Update episode state",
                description="Persist the canonical episode state snapshot.",
                input_keys=["project_id", "episode_id", "state"],
                result_kind="state snapshot",
            ),
            CapabilityToolDescriptor(
                tool="record_decision",
                title="Record decision",
                description="Append an auditable decision entry.",
                input_keys=["project_id", "episode_id", "type", "reason", "author"],
                result_kind="decision record",
            ),
        ],
        executor=None,
        selectable=False,
        summary_override="Canonical state and audit service used by runtime and host surfaces.",
    )
    return [preprocess, hpc, project_memory]


def capability_context_payload(
    summaries: list[CapabilitySummary],
    bindings: list[InspectedCapabilityBinding],
) -> dict[str, Any]:
    return {
        "capability_summaries": [item.to_dict() for item in summaries],
        "inspected_capabilities": [item.to_dict() for item in bindings],
    }


def visible_capability_bindings(
    payload: dict[str, Any],
    *,
    episode_id: str,
    active_state_version: int,
    role: str,
) -> list[InspectedCapabilityBinding]:
    bindings = [
        InspectedCapabilityBinding.from_dict(item)
        for item in payload.get("inspected_capabilities") or []
        if isinstance(item, dict)
    ]
    return [
        item
        for item in bindings
        if item.scope.episode_id == episode_id
        and item.scope.active_state_version == active_state_version
        and item.scope.role == role
    ]


def configured_capability_summaries(payload: dict[str, Any]) -> list[CapabilitySummary]:
    return [
        CapabilitySummary.from_dict(item)
        for item in payload.get("capability_summaries") or []
        if isinstance(item, dict)
    ]
