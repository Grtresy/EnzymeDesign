from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import subprocess
from typing import Mapping

from enzymedesign_bio_provider_adapters import BioHttpQualificationProbeBridge
from enzymedesign_bio_provider_adapters import HttpBioProviderAdapter
from enzymedesign_docking_preprocess import PreprocessQualificationProbeBridge
from enzymedesign_hmmer import HmmerQualificationProbeBridge
from enzymedesign_structure import FpocketQualificationProbeBridge
from enzymedesign_vina import VinaQualificationProbeBridge
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_hpc_slurm import OpenSshSlurmQualificationOperation
from openzyme_hpc_slurm import SlurmQualificationProbeBridge
from openzyme_hpc_slurm import SlurmQualificationState
from openzyme_hpc_slurm import SlurmScientificQualificationRoute
from openzyme_hpc_ssh import OpenSshQualificationOperation
from openzyme_hpc_ssh import OpenSshQualificationState
from openzyme_hpc_ssh import SshQualificationProbeBridge
from openzyme_hpc_ssh import SshWorkspaceRuntimeQualificationIdentity
from openzyme_hpc_ssh import SubprocessOpenSshQualificationCommandPort
from openzyme_process_podman import PodmanQualificationProbeBridge
from openzyme_process_podman import PodmanQualificationState
from openzyme_process_podman import PodmanScientificQualificationRoute
from openzyme_process_podman import SubprocessPodmanQualificationCommandPort
from openzyme_process_podman import SubprocessPodmanQualificationOperation
from openzyme_research_tavily import TavilyConfiguration
from openzyme_research_tavily import TavilyQualificationProbeBridge
from openzyme_research_tavily import TavilyResearchProvider
from openzyme_runtime_llm import LangChainProviderBackend
from openzyme_runtime_llm import LlmAdapterConfiguration
from openzyme_runtime_llm import LlmQualificationProbeBridge
from openzyme_workspace_git_lfs import GitLfsQualificationProbeBridge
from openzyme_workspace_git_lfs import LocalGitLfsQualificationOperation
from openzyme_workspace_git_lfs import LocalGitLfsQualificationState
from openzyme_workspace_git_lfs import SubprocessLocalGitLfsQualificationCommandPort

from .qualification_bridges import QualificationProbeBridgeBuilder
from .qualification_compute import FormalComputeScientificQualificationOperation
from .qualification_operator_state import ProtectedQualificationCredentialBundleResolver
from .qualification_operator_state import ProtectedQualificationCredentialMaterial
from .qualification_private_diagnostics import DiagnosticQualificationBridge
from .qualification_private_diagnostics import ProtectedQualificationDiagnosticWriter
from .qualification_private_diagnostics import QualificationDiagnosticContext
from .qualification_private_diagnostics import RecordingGitCommandPort
from .qualification_private_diagnostics import RecordingPodmanCommandPort
from .qualification_private_diagnostics import RecordingSshCommandPort
from .qualification_scientific_workloads import PreprocessScientificQualificationCompiler
from .qualification_scientific_workloads import SCIENTIFIC_QUALIFICATION_INPUTS
from .qualification_scientific_workloads import build_selected_driver_scientific_compiler


_LLM_LOCATOR = "credential.llm.micuapi.qualification"
_TAVILY_LOCATOR = "credential.tavily.qualification"
_HPC_LOCATOR = "credential.hpc.diannan.qualification"


@dataclass(frozen=True, slots=True)
class _ExactTavilySecretResolver:
    material: ProtectedQualificationCredentialMaterial = field(repr=False)

    def resolve(self, secret_locator: str) -> str:
        if secret_locator != self.material.locator_id:
            raise ExternalQualificationError(
                "qualification_tavily_credential_locator_mismatch",
                "Tavily requested a credential outside the exact qualification locator",
            )
        return self.material.field_value("token")


@dataclass(slots=True)
class SelectedLiveQualificationBridgeFactory:
    """Compose exact owner bridges after occurrence authorization verification."""

    credential_resolver: ProtectedQualificationCredentialBundleResolver = field(
        repr=False
    )
    protected_workspace_root: Path = field(repr=False)
    private_diagnostic_root: Path = field(repr=False)
    git_repository: Path = field(repr=False)
    image_digests: Mapping[str, str]
    hpc_image_digests: Mapping[str, str]
    workspace_runtime_identity: SshWorkspaceRuntimeQualificationIdentity
    tavily_deadline_at: str
    _git_state: LocalGitLfsQualificationState | None = field(
        default=None, init=False, repr=False
    )
    _podman_state: PodmanQualificationState | None = field(
        default=None, init=False, repr=False
    )
    _ssh_state: OpenSshQualificationState | None = field(
        default=None, init=False, repr=False
    )
    _scientific_ssh_state: OpenSshQualificationState | None = field(
        default=None, init=False, repr=False
    )
    _slurm_state: SlurmQualificationState | None = field(
        default=None, init=False, repr=False
    )
    _authorization_digest: str | None = field(default=None, init=False, repr=False)
    _diagnostic_context: QualificationDiagnosticContext = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        required = {"base", "hmmer", "docking"}
        if set(self.image_digests) != required:
            raise ValueError("live qualification requires exact base/hmmer/docking images")
        if set(self.hpc_image_digests) != {"hmmer", "vina", "fpocket"}:
            raise ValueError("live qualification requires exact HPC scientific images")
        root = self.protected_workspace_root.absolute()
        if root.is_symlink():
            raise ValueError("qualification workspace root cannot be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        self.protected_workspace_root = root
        self.git_repository = self.git_repository.absolute()
        self._diagnostic_context = QualificationDiagnosticContext(
            ProtectedQualificationDiagnosticWriter(self.private_diagnostic_root)
        )

    def builders(self) -> Mapping[str, QualificationProbeBridgeBuilder]:
        raw = {
            "openzyme.runtime.llm": self._llm,
            "openzyme.research.tavily": self._tavily,
            "enzymedesign.bio-provider-http": self._bio,
            "openzyme.workspace.git.lfs": self._git,
            "openzyme.process.podman": self._podman,
            "openzyme.hpc.ssh": self._ssh,
            "openzyme.hpc.slurm": self._slurm,
            "enzymedesign.hmmer.local": self._scientific,
            "enzymedesign.hmmer.hpc": self._scientific,
            "enzymedesign.vina.local": self._scientific,
            "enzymedesign.vina.hpc": self._scientific,
            "enzymedesign.fpocket.local": self._scientific,
            "enzymedesign.fpocket.hpc": self._scientific,
            "enzymedesign.docking.preprocess": self._preprocess,
        }
        return {
            component_id: self._diagnostic_builder(component_id, builder)
            for component_id, builder in raw.items()
        }

    def _diagnostic_builder(
        self,
        component_id: str,
        builder: QualificationProbeBridgeBuilder,
    ) -> QualificationProbeBridgeBuilder:
        def build(binding: ExternalQualificationBridgeBinding):
            return DiagnosticQualificationBridge(
                delegate=builder(binding),
                context=self._diagnostic_context,
                component_id=component_id,
            )

        return build

    def cleanup(self) -> Mapping[str, dict[str, object]]:
        receipts: dict[str, dict[str, object]] = {}
        for component_id, state in (
            ("openzyme.workspace.git.lfs", self._git_state),
            ("openzyme.process.podman", self._podman_state),
            ("openzyme.hpc.slurm", self._slurm_state),
            ("openzyme.hpc.ssh", self._ssh_state),
        ):
            if state is not None:
                try:
                    receipts[component_id] = state.cleanup()
                except (ExternalQualificationError, OSError, subprocess.TimeoutExpired) as exc:
                    receipts[component_id] = {
                        "cleanup_attempted": True,
                        "cleanup_succeeded": False,
                        "error_code": getattr(
                            exc,
                            "error_code",
                            "qualification_cleanup_command_failed",
                        ),
                        "exception_type": type(exc).__name__,
                    }
        return receipts

    def _bind_authorization(self, binding: ExternalQualificationBridgeBinding) -> str:
        if self._authorization_digest is None:
            self._authorization_digest = binding.authorization_digest
        elif self._authorization_digest != binding.authorization_digest:
            raise ExternalQualificationError(
                "qualification_live_factory_authorization_drift",
                "one live bridge factory cannot span qualification authorizations",
            )
        return binding.authorization_digest.removeprefix("sha256:")[:20]

    def _llm(self, binding: ExternalQualificationBridgeBinding):
        self._bind_authorization(binding)
        material = self.credential_resolver.resolve(locator_id=_LLM_LOCATOR)
        configuration = LlmAdapterConfiguration(
            provider_id="micuapi",
            model="gpt-5.5",
            base_url="https://www.micuapi.ai/v1",
            credential_slot=_LLM_LOCATOR,
            timeout_seconds=60,
            max_retries=0,
            context_window_units=128_000,
            default_output_units=256,
            provider_options={"langchain_model_provider": "openai"},
        )
        backend = LangChainProviderBackend(
            configuration=configuration,
            api_key=material.field_value("token"),
        )
        return LlmQualificationProbeBridge(
            binding=binding,
            backend=backend,
            provider_id="micuapi",
            model="gpt-5.5",
            expected_backend_identity_digest=backend.backend_identity_digest,
            timeout_seconds=60,
        )

    def _tavily(self, binding: ExternalQualificationBridgeBinding):
        self._bind_authorization(binding)
        material = self.credential_resolver.resolve(locator_id=_TAVILY_LOCATOR)
        provider = TavilyResearchProvider(
            configuration=TavilyConfiguration(
                secret_locator=_TAVILY_LOCATOR,
                max_results=3,
                include_raw_content=False,
                timeout_seconds=30,
            ),
            secret_resolver=_ExactTavilySecretResolver(material),
        )
        return TavilyQualificationProbeBridge(
            binding=binding,
            provider=provider,
            deadline_at=self.tavily_deadline_at,
        )

    def _bio(self, binding: ExternalQualificationBridgeBinding):
        self._bind_authorization(binding)
        provider_id = binding.route_id.split(".")[2]
        return BioHttpQualificationProbeBridge(
            binding=binding,
            adapter=HttpBioProviderAdapter(),
            provider_id=provider_id,
        )

    def _git(self, binding: ExternalQualificationBridgeBinding):
        suffix = self._bind_authorization(binding)
        if self._git_state is None:
            self._git_state = LocalGitLfsQualificationState(
                repository=self.git_repository,
                workspace=self.protected_workspace_root / f"git-lfs-{suffix}",
                command_port=RecordingGitCommandPort(
                    SubprocessLocalGitLfsQualificationCommandPort(),
                    self._diagnostic_context,
                ),
            )
        return GitLfsQualificationProbeBridge(
            binding=binding,
            operation_port=LocalGitLfsQualificationOperation(
                component_id=binding.component_id,
                route_id=binding.route_id,
                subject_digest=binding.subject_digest,
                state=self._git_state,
            ),
        )

    def _podman(self, binding: ExternalQualificationBridgeBinding):
        suffix = self._bind_authorization(binding)
        if self._podman_state is None:
            self._podman_state = PodmanQualificationState(
                image_digest=self.image_digests["base"],
                container_name=f"openzyme-qualification-{suffix}",
                workspace=self.protected_workspace_root / f"podman-{suffix}",
                command_port=RecordingPodmanCommandPort(
                    SubprocessPodmanQualificationCommandPort(),
                    self._diagnostic_context,
                ),
            )
        return PodmanQualificationProbeBridge(
            binding=binding,
            operation_port=SubprocessPodmanQualificationOperation(
                component_id=binding.component_id,
                route_id=binding.route_id,
                subject_digest=binding.subject_digest,
                state=self._podman_state,
            ),
        )

    def _hpc_material(self) -> ProtectedQualificationCredentialMaterial:
        return self.credential_resolver.resolve(locator_id=_HPC_LOCATOR)

    def _ensure_ssh(
        self, binding: ExternalQualificationBridgeBinding
    ) -> OpenSshQualificationState:
        suffix = self._bind_authorization(binding)
        if self._ssh_state is None:
            material = self._hpc_material()
            expected = self.workspace_runtime_identity
            actual_workspace_root = material.field_value("workspace_root")
            actual_helper_path = material.field_value("isolation_command")
            actual_user = material.field_value("ssh_user")
            if (
                actual_workspace_root != expected.workspace_parent
                or actual_helper_path != expected.helper_path
                or actual_user != expected.file_owner
            ):
                raise ExternalQualificationError(
                    "qualification_hpc_workspace_runtime_binding_mismatch",
                    "HPC credential material differs from the qualified workspace runtime",
                )
            self._ssh_state = OpenSshQualificationState(
                credential_material=material,
                workspace_id=f"batch-1-{suffix}",
                command_port=RecordingSshCommandPort(
                    SubprocessOpenSshQualificationCommandPort(),
                    self._diagnostic_context,
                ),
                workspace_runtime_identity=self.workspace_runtime_identity,
            )
        return self._ssh_state

    def _ssh(self, binding: ExternalQualificationBridgeBinding):
        state = self._ensure_ssh(binding)
        return SshQualificationProbeBridge(
            binding=binding,
            operation_port=OpenSshQualificationOperation(
                component_id=binding.component_id,
                route_id=binding.route_id,
                subject_digest=binding.subject_digest,
                state=state,
            ),
        )

    def _ensure_slurm(self, binding: ExternalQualificationBridgeBinding) -> SlurmQualificationState:
        ssh_state = self._ensure_ssh(binding)
        if self._slurm_state is None:
            self._slurm_state = SlurmQualificationState(
                workspace=ssh_state.remote_workspace,
                partition="3090",
                command_port=ssh_state,
            )
        return self._slurm_state

    def _ensure_scientific_ssh(
        self,
        binding: ExternalQualificationBridgeBinding,
    ) -> OpenSshQualificationState:
        adapter_state = self._ensure_ssh(binding)
        if self._scientific_ssh_state is None:
            self._scientific_ssh_state = OpenSshQualificationState(
                credential_material=adapter_state.credential_material,
                workspace_id=adapter_state.workspace_id,
                command_port=RecordingSshCommandPort(
                    SubprocessOpenSshQualificationCommandPort(timeout_seconds=600),
                    self._diagnostic_context,
                ),
                workspace_runtime_identity=self.workspace_runtime_identity,
            )
        return self._scientific_ssh_state

    def _slurm(self, binding: ExternalQualificationBridgeBinding):
        state = self._ensure_slurm(binding)
        return SlurmQualificationProbeBridge(
            binding=binding,
            operation_port=OpenSshSlurmQualificationOperation(
                component_id=binding.component_id,
                route_id=binding.route_id,
                subject_digest=binding.subject_digest,
                state=state,
            ),
        )

    def _scientific(self, binding: ExternalQualificationBridgeBinding):
        suffix = self._bind_authorization(binding)
        route_kind = "hpc-primary" if binding.component_id.endswith(".hpc") else "local"
        compiler = build_selected_driver_scientific_compiler(
            component_id=binding.component_id,
            operation=binding.operation,
            route_kind=route_kind,
        )
        if route_kind == "hpc-primary":
            ssh_state = self._ensure_scientific_ssh(binding)
            if binding.component_id.startswith("enzymedesign.hmmer."):
                image_group = "hmmer"
            elif binding.component_id.startswith("enzymedesign.vina."):
                image_group = "vina"
            else:
                image_group = "fpocket"
            route = SlurmScientificQualificationRoute(
                workspace_root=ssh_state.remote_workspace,
                partition="3090",
                command_port=ssh_state,
                input_resolver=SCIENTIFIC_QUALIFICATION_INPUTS,
                software_image_path=self._hpc_material().field_value(
                    f"{image_group}_sif"
                ),
                software_image_digest=self.hpc_image_digests[image_group],
            )
        else:
            image_group = (
                "hmmer"
                if binding.component_id.startswith("enzymedesign.hmmer.")
                else "docking"
            )
            route = PodmanScientificQualificationRoute(
                image_digest=self.image_digests[image_group],
                workspace_root=self.protected_workspace_root / f"science-{suffix}",
                command_port=RecordingPodmanCommandPort(
                    SubprocessPodmanQualificationCommandPort(),
                    self._diagnostic_context,
                ),
                input_resolver=SCIENTIFIC_QUALIFICATION_INPUTS,
            )
        port = FormalComputeScientificQualificationOperation(
            component_id=binding.component_id,
            route_id=binding.route_id,
            subject_digest=binding.subject_digest,
            driver_component_id=binding.component_id,
            workload_input_digest=binding.input_digest,
            result_schema_digest=binding.expected_result_schema_digest,
            compiler=compiler,
            compute_route=route,
        )
        if binding.component_id.startswith("enzymedesign.hmmer."):
            return HmmerQualificationProbeBridge(binding=binding, operation_port=port)
        if binding.component_id.startswith("enzymedesign.vina."):
            return VinaQualificationProbeBridge(binding=binding, operation_port=port)
        return FpocketQualificationProbeBridge(binding=binding, operation_port=port)

    def _preprocess(self, binding: ExternalQualificationBridgeBinding):
        suffix = self._bind_authorization(binding)
        software = binding.route_id.split(".")[3]
        route = PodmanScientificQualificationRoute(
            image_digest=self.image_digests["docking"],
            workspace_root=self.protected_workspace_root / f"science-{suffix}",
            command_port=RecordingPodmanCommandPort(
                SubprocessPodmanQualificationCommandPort(),
                self._diagnostic_context,
            ),
            input_resolver=SCIENTIFIC_QUALIFICATION_INPUTS,
        )
        port = FormalComputeScientificQualificationOperation(
            component_id=binding.component_id,
            route_id=binding.route_id,
            subject_digest=binding.subject_digest,
            driver_component_id=binding.component_id,
            workload_input_digest=binding.input_digest,
            result_schema_digest=binding.expected_result_schema_digest,
            compiler=PreprocessScientificQualificationCompiler(
                operation=binding.operation,
                software=software,
            ),
            compute_route=route,
        )
        return PreprocessQualificationProbeBridge(
            binding=binding,
            operation_port=port,
        )


__all__ = ["SelectedLiveQualificationBridgeFactory"]
