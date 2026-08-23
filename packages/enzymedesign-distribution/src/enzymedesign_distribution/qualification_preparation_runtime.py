from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
import stat

from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import create_external_identity_preparation_success
from openzyme_contracts import verify_external_identity_preparation_occurrence_authorization
from openzyme_hpc import HpcQualificationCredentialMaterial
from openzyme_hpc import HpcQualificationIdentityObservationPort
from openzyme_hpc_ssh import OpenSshHpcQualificationIdentityObservationPort
from openzyme_hpc_ssh import OpenSshAlphaFoldQualificationIdentityObservationPort
from openzyme_hpc_ssh import SubprocessOpenSshQualificationCommandPort
from openzyme_process_podman import PodmanQualificationImagePreparationExecutor
from openzyme_process_podman import SubprocessQualificationImageCommandPort
from openzyme_research_tavily import TavilyQualificationLocatorPreparationExecutor
from openzyme_runtime_llm import LlmQualificationLocatorPreparationExecutor
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger
from openzyme_workspace_git_lfs import LocalIsolatedGitLfsPreparationExecutor
from openzyme_workspace_git_lfs import (
    SubprocessLocalGitLfsPreparationCommandPort,
)

from .qualification_operator_state import (
    ProtectedQualificationCredentialBundleResolver,
)
from .qualification_operator_state import QualificationOperatorStateLayout
from .qualification_planning import PlanOnlyIdentityPreparationBackendFactory
from .qualification_planning import QualificationCredentialMaterialResolver
from .qualification_planning import SafeIdentitySnapshot
from .qualification_planning import apply_external_identity_preparation_results
from .qualification_scientific_workloads import (
    ALPHAFOLD_QUALIFICATION_INPUT_DIGEST,
)


_PREPARATION_CREDENTIAL_REQUIREMENTS: Mapping[
    str, tuple[str, str, tuple[str, ...]]
] = {
    "credential.llm.micuapi.qualification": (
        "bearer-token",
        "v1",
        ("token", "account_locator_id", "scope_id"),
    ),
    "credential.tavily.qualification": (
        "bearer-token",
        "v1",
        ("token", "account_locator_id", "scope_id"),
    ),
    "credential.hpc.diannan.qualification": (
        "openssh-identity",
        "v1",
        (
            "ssh_host",
            "ssh_port",
            "ssh_user",
            "identity_file",
            "known_hosts_file",
            "credential_provider_id",
            "authenticator_id",
            "login_alias",
            "workspace_root",
            "sidecar_root",
            "isolation_command",
            "hmmer_sif",
            "vina_sif",
            "fpocket_sif",
            "slurm_policy_id",
        ),
    ),
}


def _persist_exact_alphafold_config(
    path: Path,
    config: Mapping[str, object],
) -> str | None:
    """Create or compare-and-replace one exact protected AF3 config."""

    parent = path.parent
    if parent.exists() or parent.is_symlink():
        metadata = parent.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ExternalQualificationError(
                "qualification_operator_state_permissions_unsafe",
                "AlphaFold qualification config parent is unsafe",
            )
    else:
        parent.mkdir(mode=0o700, parents=False)

    expected = dict(config)
    expected_digest = expected.get("config_digest")
    unsigned_expected = dict(expected)
    unsigned_expected.pop("config_digest", None)
    if expected_digest != canonical_sha256_digest(unsigned_expected):
        raise ExternalQualificationError(
            "qualification_alphafold_config_digest_invalid",
            "AlphaFold qualification config digest is invalid",
        )

    prior_digest: str | None = None
    replace_existing = False
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ExternalQualificationError(
                "qualification_operator_state_permissions_unsafe",
                "AlphaFold qualification config is unsafe",
            )
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExternalQualificationError(
                "qualification_alphafold_config_reconcile_failed",
                "AlphaFold qualification config cannot be reconciled",
            ) from exc
        if not isinstance(loaded, dict):
            raise ExternalQualificationError(
                "qualification_alphafold_config_reconcile_failed",
                "AlphaFold qualification config is not one object",
            )
        prior_digest_value = loaded.get("config_digest")
        unsigned_loaded = dict(loaded)
        unsigned_loaded.pop("config_digest", None)
        if prior_digest_value != canonical_sha256_digest(unsigned_loaded):
            raise ExternalQualificationError(
                "qualification_alphafold_config_reconcile_failed",
                "AlphaFold qualification config integrity failed",
            )
        transient_fields = {
            "preparation_authorization_digest",
            "preparation_plan_digest",
        }
        stable_loaded = {
            key: value
            for key, value in unsigned_loaded.items()
            if key not in transient_fields
        }
        stable_expected = {
            key: value
            for key, value in unsigned_expected.items()
            if key not in transient_fields
        }
        if stable_loaded != stable_expected:
            raise ExternalQualificationError(
                "qualification_alphafold_config_subject_drift",
                "AlphaFold qualification resource config differs from observation",
            )
        prior_digest = str(prior_digest_value)
        if loaded == expected:
            return prior_digest
        replace_existing = True

    encoded = (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode()
    target = path
    if replace_existing:
        target = parent / (
            f".{path.name}.{str(expected_digest).removeprefix('sha256:')[:16]}.tmp"
        )
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if replace_existing:
        os.replace(target, path)
    directory = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return prior_digest


@dataclass(frozen=True, slots=True)
class _PreloadedQualificationCredentialResolver:
    materials: Mapping[str, object] = field(repr=False)

    def resolve(self, *, locator_id: str) -> object:
        try:
            return self.materials[locator_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_credential_locator_mismatch",
                "credential resolver rejects an unplanned locator",
            ) from exc


def preflight_enzymedesign_identity_preparation_credentials(
    *,
    plan: ExternalIdentityPreparationPlan,
    resolver: ProtectedQualificationCredentialBundleResolver,
) -> QualificationCredentialMaterialResolver:
    """Read and validate every exact locator after authorization, before mutation."""

    materials: dict[str, object] = {}
    for locator_id in plan.credential_locator_ids:
        try:
            material_kind, locator_version, required_fields = (
                _PREPARATION_CREDENTIAL_REQUIREMENTS[locator_id]
            )
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_credential_locator_mismatch",
                "preparation plan contains an unsupported credential locator",
            ) from exc
        material = resolver.resolve(locator_id=locator_id)
        if (
            material.material_kind != material_kind
            or material.locator_version != locator_version
        ):
            raise ExternalQualificationError(
                "qualification_credential_material_kind_mismatch",
                "credential material kind or version differs from the exact owner contract",
            )
        for field_name in required_fields:
            material.field_value(field_name)
        materials[locator_id] = material
    return _PreloadedQualificationCredentialResolver(materials)


@dataclass(frozen=True, slots=True)
class EnzymeDesignIdentityPreparationBatchExecution:
    plan_digest: str
    authorization_digest: str
    results: tuple[ExternalIdentityPreparationResult, ...]
    prepared_snapshot: SafeIdentitySnapshot


def execute_enzymedesign_identity_preparation_batch(
    *,
    plan: ExternalIdentityPreparationPlan,
    authorization: ExternalIdentityPreparationOccurrenceAuthorization,
    snapshot: SafeIdentitySnapshot,
    factory: PlanOnlyIdentityPreparationBackendFactory,
    clock: Callable[[], str],
    existing_results: tuple[ExternalIdentityPreparationResult, ...] = (),
) -> EnzymeDesignIdentityPreparationBatchExecution:
    """Execute each exact preparation action once; no retry or fallback is possible."""

    if plan.batch_id not in {"batch-1", "batch-2-alphafold"}:
        raise ExternalQualificationError(
            "blocked_identity",
            "the preparation executor received an unsupported batch",
        )
    verify_external_identity_preparation_occurrence_authorization(
        plan,
        authorization,
        observed_at=clock(),
    )
    action_by_id = {item.action_id: item for item in plan.actions}
    completed: dict[str, ExternalIdentityPreparationResult] = {}
    for result in existing_results:
        action = action_by_id.get(result.action_id)
        if (
            action is None
            or result.action_id in completed
            or result.preparation_plan_digest != plan.preparation_plan_digest
            or result.authorization_digest != authorization.authorization_digest
            or result.owner_component_id != action.owner_component_id
            or result.input_binding_digest != action.input_binding_digest
        ):
            raise ExternalQualificationError(
                "qualification_preparation_resume_binding_mismatch",
                "stored preparation result cannot resume this exact batch authority",
            )
        completed[result.action_id] = result

    for action in plan.actions:
        if action.action_id in completed:
            continue
        occurrence_id = f"{authorization.authorization_id}.{action.action_id}"
        result = factory.build(
            plan=plan,
            authorization=authorization,
            observed_at=clock(),
            occurrence_id=occurrence_id,
            action_id=action.action_id,
            input_binding_digest=action.input_binding_digest,
            locator_id=action.credential_locator_id,
        )
        if not isinstance(result, ExternalIdentityPreparationResult):
            raise ExternalQualificationError(
                "qualification_preparation_result_type_invalid",
                "preparation factory returned an unsupported result",
            )
        completed[action.action_id] = result

    results = tuple(completed[item.action_id] for item in plan.actions)
    prepared_snapshot = apply_external_identity_preparation_results(
        snapshot=snapshot,
        preparation_plan=plan,
        results=results,
        observed_at=clock(),
    )
    return EnzymeDesignIdentityPreparationBatchExecution(
        plan_digest=plan.preparation_plan_digest,
        authorization_digest=authorization.authorization_digest,
        results=results,
        prepared_snapshot=prepared_snapshot,
    )


@dataclass(frozen=True, slots=True)
class EnzymeDesignHpcIdentityPreparationExecutor:
    private_config_path: Path = field(repr=False)
    observation_port: HpcQualificationIdentityObservationPort = field(repr=False)
    alphafold_private_config_path: Path | None = field(default=None, repr=False)
    alphafold_observation_port: (
        OpenSshAlphaFoldQualificationIdentityObservationPort | None
    ) = field(default=None, repr=False)

    def __post_init__(self) -> None:
        path = self.private_config_path.absolute()
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("qualification-only HPC config path must be absolute and direct")
        object.__setattr__(self, "private_config_path", path)
        if self.alphafold_private_config_path is not None:
            alphafold_path = self.alphafold_private_config_path.absolute()
            if not alphafold_path.is_absolute() or alphafold_path.is_symlink():
                raise ValueError(
                    "AlphaFold qualification config path must be absolute and direct"
                )
            object.__setattr__(self, "alphafold_private_config_path", alphafold_path)

    def __call__(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: HpcQualificationCredentialMaterial,
    ) -> ExternalIdentityPreparationResult:
        if action.effect_id == "hpc.alphafold3.resource-identity.observe":
            return self._observe_alphafold(
                plan=plan,
                authorization=authorization,
                action=action,
                occurrence_id=occurrence_id,
                request_digest=request_digest,
                credential_material=credential_material,
            )
        if (
            action.owner_component_id != "openzyme.hpc"
            or action.effect_id != "hpc.executor-workspace-v2.identity-resolve"
            or credential_material.locator_id != action.credential_locator_id
        ):
            raise ExternalQualificationError(
                "qualification_hpc_preparation_binding_mismatch",
                "HPC identity preparation differs from the exact planned action",
            )
        if plan.batch_id != "batch-1":
            raise ExternalQualificationError(
                "blocked_identity",
                "AlphaFold Batch 2 resources remain separately unprovisioned",
            )
        if self.private_config_path.exists() or self.private_config_path.is_symlink():
            raise ExternalQualificationError(
                "qualification_hpc_config_already_exists",
                "qualification-only HPC config already requires operator reconciliation",
            )
        config_parent = self.private_config_path.parent
        if config_parent.exists() or config_parent.is_symlink():
            metadata = config_parent.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ExternalQualificationError(
                    "qualification_operator_state_permissions_unsafe",
                    "qualification-only HPC config parent is unsafe",
                )
        observation = self.observation_port.observe(
            host_alias="Diannan",
            partition="3090",
            credential_material=credential_material,
        )
        credential_provider_id = credential_material.field_value(
            "credential_provider_id"
        )
        authenticator_id = credential_material.field_value("authenticator_id")
        login_alias = credential_material.field_value("login_alias")
        workspace_root = credential_material.field_value("workspace_root")
        sidecar_root = credential_material.field_value("sidecar_root")
        isolation_command = credential_material.field_value("isolation_command")
        slurm_policy_id = credential_material.field_value("slurm_policy_id")
        scientific_images = {
            software_id: {
                "path": credential_material.field_value(field_name),
                "digest": observation.software_image_digest(software_id),
                "version": observation.software_version(software_id),
            }
            for software_id, field_name in (
                ("software.hmmer", "hmmer_sif"),
                ("software.vina", "vina_sif"),
                ("software.fpocket", "fpocket_sif"),
            )
        }
        private_payload = {
            "schema_version": "enzymedesign_qualification_hpc_config@1",
            "occurrence_id": occurrence_id,
            "preparation_plan_digest": plan.preparation_plan_digest,
            "authorization_digest": authorization.authorization_digest,
            "action_id": action.action_id,
            "request_digest": request_digest,
            "configuration_mode": "qualification-only",
            "deployment_id": "aox-qualification-diannan",
            "target_alias": observation.host_alias,
            "ssh_port": observation.ssh_port,
            "partition": observation.partition,
            "credential_locator_id": credential_material.locator_id,
            "executor_workspace": {
                "schema_version": "executor_workspace@2",
                "activated": False,
                "target_profile_id": "diannan-3090-qualification",
                "workspace_root": workspace_root,
                "sidecar_root": sidecar_root,
                "isolation_command": isolation_command,
                "credential_provider_id": credential_provider_id,
                "authenticator_id": authenticator_id,
                "login_alias": login_alias,
                "inventory_generation_digest": observation.inventory_generation_digest,
            },
            "scientific_images": scientific_images,
            "apptainer_version": observation.apptainer_version,
            "scheduler_submit_enabled": False,
            "slurm_policy_id": slurm_policy_id,
        }
        config_parent.mkdir(mode=0o700, parents=False, exist_ok=True)
        temporary = self.private_config_path.with_suffix(".tmp")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(
                descriptor,
                json.dumps(
                    private_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.private_config_path)
        profile_digest = canonical_sha256_digest(private_payload)
        software_facts = {
            software_id: canonical_sha256_digest(
                {
                    "software": software_id,
                    "version": observation.software_version(software_id),
                    "image_digest": observation.software_image_digest(software_id),
                    "runtime": observation.apptainer_version,
                    "environment": observation.environment_digest,
                }
            )
            for software_id in (
                "software.fpocket",
                "software.hmmer",
                "software.vina",
            )
        }
        fields = tuple(
            SafeIdentityField(field_id, value)
            for field_id, value in sorted(
                (
                    ("authenticator_identity", authenticator_id),
                    ("credential_locator_id", credential_material.locator_id),
                    ("credential_provider_identity", credential_provider_id),
                    ("executor_workspace_v2_profile", profile_digest),
                    ("fpocket_software_fact", software_facts["software.fpocket"]),
                    (
                        "fpocket_sif_digest",
                        observation.software_image_digest("software.fpocket"),
                    ),
                    ("hmmer_software_fact", software_facts["software.hmmer"]),
                    (
                        "hmmer_sif_digest",
                        observation.software_image_digest("software.hmmer"),
                    ),
                    (
                        "hpc_inventory_generation_digest",
                        observation.inventory_generation_digest,
                    ),
                    (
                        "inventory_generation_digest",
                        observation.inventory_generation_digest,
                    ),
                    ("slurm_account_or_qos_policy", slurm_policy_id),
                    ("vina_software_fact", software_facts["software.vina"]),
                    (
                        "vina_sif_digest",
                        observation.software_image_digest("software.vina"),
                    ),
                )
            )
        )
        return create_external_identity_preparation_success(
            occurrence_id=occurrence_id,
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,
            owner_component_id=action.owner_component_id,
            effect_id=action.effect_id,
            input_binding_digest=action.input_binding_digest,
            request_digest=request_digest,
            safe_identity_fields=fields,
            receipt_payload={
                "schema_version": "hpc_identity_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "target_alias": observation.host_alias,
                "partition": observation.partition,
                "profile_digest": profile_digest,
                "inventory_generation_digest": observation.inventory_generation_digest,
                "credential_locator_id": credential_material.locator_id,
            },
            external_effect_performed=True,
            credential_material_accessed=True,
        )

    def _observe_alphafold(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: HpcQualificationCredentialMaterial,
    ) -> ExternalIdentityPreparationResult:
        if (
            plan.batch_id != "batch-2-alphafold"
            or action.owner_component_id != "openzyme.hpc"
            or credential_material.locator_id != action.credential_locator_id
            or action.mutating
            or action.cleanup_action_id is not None
        ):
            raise ExternalQualificationError(
                "qualification_alphafold_preparation_binding_mismatch",
                "AlphaFold preparation differs from the exact read-only Batch-2 action",
            )
        if (
            self.alphafold_private_config_path is None
            or self.alphafold_observation_port is None
        ):
            raise ExternalQualificationError(
                "qualification_alphafold_preparation_owner_unavailable",
                "AlphaFold preparation owner is not configured",
            )
        observation = self.alphafold_observation_port.observe(
            host_alias="Diannan",
            partition="3090",
            credential_material=credential_material,
        )
        config = {
            "schema_version": "enzymedesign_alphafold_qualification_config@1",
            "target_alias": observation.host_alias,
            "partition": observation.partition,
            "wrapper_path": "/opt/tools/alphafold3",
            "image_path": "/opt/tools_env/alphafold3/alphafold3.sif",
            "model_path": "/opt/tools_env/alphafold3/models/af3.bin",
            "database_path": "/data/tools/alphafold3",
            "alphafold_version": observation.alphafold_version,
            "wrapper_digest": observation.wrapper_digest,
            "image_digest": observation.image_digest,
            "model_parameters_digest": observation.model_parameters_digest,
            "database_closure_digest": observation.database_closure_digest,
            "gpu_capability_digest": observation.gpu_capability_digest,
            "source_commit": observation.source_commit,
            "source_dirty_digest": observation.source_dirty_digest,
            "apptainer_version": observation.apptainer_version,
            "inventory_generation_digest": observation.inventory_generation_digest,
            "fixed_monomer_input_digest": ALPHAFOLD_QUALIFICATION_INPUT_DIGEST,
            "fixed_seed": 20260824,
            "gpu_count": 1,
            "gpu_time_hard_limit_minutes": 30,
            "max_retries": 0,
            "fallback_allowed": False,
            "license_acceptance_performed": False,
            "preparation_plan_digest": plan.preparation_plan_digest,
            "preparation_authorization_digest": authorization.authorization_digest,
        }
        config["config_digest"] = canonical_sha256_digest(config)
        path = self.alphafold_private_config_path
        prior_config_digest = _persist_exact_alphafold_config(path, config)
        fields = tuple(
            SafeIdentityField(field_id, value)
            for field_id, value in sorted(
                {
                    "alphafold_gpu_image_digest": observation.image_digest,
                    "model_parameters_digest": observation.model_parameters_digest,
                    "database_closure_digest": observation.database_closure_digest,
                    "gpu_capability_fact": observation.gpu_capability_digest,
                    "fixed_monomer_input_digest": ALPHAFOLD_QUALIFICATION_INPUT_DIGEST,
                    "alphafold_version": observation.alphafold_version,
                    "alphafold_wrapper_digest": observation.wrapper_digest,
                    "alphafold_source_commit": observation.source_commit,
                    "alphafold_source_dirty_digest": observation.source_dirty_digest,
                    "alphafold_inventory_generation_digest": (
                        observation.inventory_generation_digest
                    ),
                    "credential_locator_id": credential_material.locator_id,
                }.items()
            )
        )
        return create_external_identity_preparation_success(
            occurrence_id=occurrence_id,
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,
            owner_component_id=action.owner_component_id,
            effect_id=action.effect_id,
            input_binding_digest=action.input_binding_digest,
            request_digest=request_digest,
            safe_identity_fields=fields,
            receipt_payload={
                "schema_version": "alphafold_identity_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "inventory_generation_digest": observation.inventory_generation_digest,
                "config_digest": config["config_digest"],
                "prior_config_digest": prior_config_digest,
                "config_reconciled": prior_config_digest is not None,
                "license_acceptance_performed": False,
            },
            external_effect_performed=True,
            credential_material_accessed=True,
        )


@dataclass(slots=True)
class _LazyProtectedPreparationResultRecorder:
    database_path: Path = field(repr=False)
    _ledger: SQLiteProtectedQualificationLedger | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __call__(self, result: ExternalIdentityPreparationResult) -> None:
        if self._ledger is None:
            if self.database_path.is_symlink():
                raise ExternalQualificationError(
                    "qualification_operator_state_symlink_forbidden",
                    "protected qualification ledger cannot use a symlink",
                )
            if not self.database_path.exists():
                descriptor = os.open(
                    self.database_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.close(descriptor)
            metadata = self.database_path.stat()
            if (
                metadata.st_uid != os.getuid()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise ExternalQualificationError(
                    "qualification_operator_state_permissions_unsafe",
                    "protected qualification ledger ownership or mode is unsafe",
                )
            self._ledger = SQLiteProtectedQualificationLedger(self.database_path)
        self._ledger.record_preparation_result(result)


def build_enzymedesign_identity_preparation_backend_factory(
    *,
    layout: QualificationOperatorStateLayout,
    allowed_locator_ids: tuple[str, ...],
    credential_resolver: QualificationCredentialMaterialResolver | None = None,
    result_recorder: Callable[[ExternalIdentityPreparationResult], None]
    | None = None,
) -> PlanOnlyIdentityPreparationBackendFactory:
    """Assemble exact owners without reading credentials or performing effects."""

    exact_resolver = credential_resolver or ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=allowed_locator_ids,
    )
    hpc_observer = OpenSshHpcQualificationIdentityObservationPort(
        command_port=SubprocessOpenSshQualificationCommandPort()
    )
    alphafold_observer = OpenSshAlphaFoldQualificationIdentityObservationPort(
        command_port=SubprocessOpenSshQualificationCommandPort(timeout_seconds=600)
    )
    return PlanOnlyIdentityPreparationBackendFactory(
        credential_resolver=exact_resolver,
        owner_builders={
            "openzyme.runtime.llm": LlmQualificationLocatorPreparationExecutor(),
            "openzyme.research.tavily": (
                TavilyQualificationLocatorPreparationExecutor()
            ),
            "openzyme.workspace.git.lfs": LocalIsolatedGitLfsPreparationExecutor(
                repository_root=layout.root / "git-lfs",
                command_port=SubprocessLocalGitLfsPreparationCommandPort(),
            ),
            "openzyme.process.podman": PodmanQualificationImagePreparationExecutor(
                command_port=SubprocessQualificationImageCommandPort()
            ),
            "openzyme.hpc": EnzymeDesignHpcIdentityPreparationExecutor(
                private_config_path=layout.root
                / "hpc-qualification"
                / "config.json",
                observation_port=hpc_observer,
                alphafold_private_config_path=layout.root
                / "alphafold-qualification"
                / "config.json",
                alphafold_observation_port=alphafold_observer,
            ),
        },
        result_recorder=(
            _LazyProtectedPreparationResultRecorder(layout.ledger_path)
            if result_recorder is None
            else result_recorder
        ),
    )


__all__ = [
    "EnzymeDesignIdentityPreparationBatchExecution",
    "EnzymeDesignHpcIdentityPreparationExecutor",
    "build_enzymedesign_identity_preparation_backend_factory",
    "execute_enzymedesign_identity_preparation_batch",
    "preflight_enzymedesign_identity_preparation_credentials",
]
