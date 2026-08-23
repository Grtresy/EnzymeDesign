from dataclasses import dataclass

import pytest

from enzymedesign_distribution import SelectedLiveQualificationBridgeFactory
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import canonical_sha256_digest
from openzyme_hpc_ssh import SshWorkspaceRuntimeQualificationIdentity


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


@dataclass(frozen=True)
class _Material:
    locator_id: str
    fields: dict[str, str]
    locator_version: str = "v1"
    material_kind: str = "qualification"

    def field_value(self, field_name: str) -> str:
        return self.fields[field_name]


@dataclass
class _Resolver:
    materials: dict[str, _Material]
    calls: list[str]

    def resolve(self, *, locator_id: str) -> _Material:
        self.calls.append(locator_id)
        return self.materials[locator_id]


def _binding(
    component_id: str,
    operation: str,
    route_id: str,
    locator: str | None = None,
) -> ExternalQualificationBridgeBinding:
    return ExternalQualificationBridgeBinding.create(
        component_id=component_id,
        operation=operation,
        route_id=route_id,
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
        credential_locator_id=locator,
    )


def _workspace_runtime_identity() -> SshWorkspaceRuntimeQualificationIdentity:
    payload = {
        "helper_path": "/home/grtresy/.local/libexec/openzyme-workspace-runtime",
        "workspace_parent": "/home/grtresy/.local/state/openzyme-executor-workspaces",
        "policy_id": "policy.openzyme.hpc.diannan.workspace-runtime",
        "helper_version": "1.0.0",
        "helper_build_digest": "sha256:" + "4" * 64,
        "root_policy_digest": "sha256:" + "5" * 64,
        "principal_identity_digest": "sha256:" + "6" * 64,
        "deployment_plan_digest": "sha256:" + "7" * 64,
        "deployment_receipt_digest": "sha256:" + "8" * 64,
        "native_qualification_digest": "sha256:" + "9" * 64,
        "file_owner": "grtresy",
        "file_group": "grtresy",
        "file_mode": "755",
    }
    return SshWorkspaceRuntimeQualificationIdentity(
        **payload,
        observation_digest=canonical_sha256_digest(payload),
    )


@pytest.fixture
def factory(tmp_path):
    identity = tmp_path / "identity"
    identity.write_text("private-key-placeholder", encoding="utf-8")
    identity.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("diannan ssh-ed25519 placeholder", encoding="utf-8")
    known_hosts.chmod(0o600)
    resolver = _Resolver(
        materials={
            "credential.llm.micuapi.qualification": _Material(
                "credential.llm.micuapi.qualification",
                {"token": "secret", "account_locator_id": "a", "scope_id": "s"},
            ),
            "credential.tavily.qualification": _Material(
                "credential.tavily.qualification",
                {"token": "secret", "account_locator_id": "a", "scope_id": "s"},
            ),
            "credential.hpc.diannan.qualification": _Material(
                "credential.hpc.diannan.qualification",
                {
                    "ssh_host": "diannan",
                    "ssh_user": "grtresy",
                    "ssh_port": "22222",
                    "identity_file": str(identity),
                    "known_hosts_file": str(known_hosts),
                    "workspace_root": (
                        "/home/grtresy/.local/state/openzyme-executor-workspaces"
                    ),
                    "isolation_command": (
                        "/home/grtresy/.local/libexec/openzyme-workspace-runtime"
                    ),
                    "hmmer_sif": "/qualification/containers/hmmer.sif",
                    "vina_sif": "/qualification/containers/vina.sif",
                    "fpocket_sif": "/qualification/containers/fpocket.sif",
                },
            ),
        },
        calls=[],
    )
    repository = tmp_path / "repository.git"
    repository.mkdir(mode=0o700)
    return SelectedLiveQualificationBridgeFactory(
        credential_resolver=resolver,  # type: ignore[arg-type]
        protected_workspace_root=tmp_path / "workspaces",
        private_diagnostic_root=tmp_path / "private-diagnostics",
        git_repository=repository,
        image_digests={
            "base": "sha256:" + "a" * 64,
            "hmmer": "sha256:" + "b" * 64,
            "docking": "sha256:" + "c" * 64,
        },
        hpc_image_digests={
            "hmmer": "sha256:" + "d" * 64,
            "vina": "sha256:" + "e" * 64,
            "fpocket": "sha256:" + "f" * 64,
        },
        workspace_runtime_identity=_workspace_runtime_identity(),
        tavily_deadline_at="2026-08-23T18:30:00+08:00",
    )


@pytest.mark.parametrize(
    ("component_id", "operation", "route_id", "locator"),
    (
        (
            "openzyme.runtime.llm",
            "bounded-turn",
            "openzyme.runtime.llm.turn@1",
            "credential.llm.micuapi.qualification",
        ),
        (
            "openzyme.research.tavily",
            "bounded-query",
            "openzyme.research.tavily.query@1",
            "credential.tavily.qualification",
        ),
        (
            "enzymedesign.bio-provider-http",
            "read-smoke",
            "enzymedesign.bio-provider-http.uniprot.read@1",
            None,
        ),
        (
            "openzyme.workspace.git.lfs",
            "clone",
            "openzyme.workspace.git.lfs.clone@1",
            None,
        ),
        (
            "openzyme.process.podman",
            "container-start",
            "openzyme.process.podman.container-start@1",
            None,
        ),
        (
            "openzyme.hpc.ssh",
            "helper-identity",
            "openzyme.hpc.ssh.helper-identity@1",
            "credential.hpc.diannan.qualification",
        ),
        (
            "openzyme.hpc.slurm",
            "submit",
            "openzyme.hpc.slurm.submit@1",
            "credential.hpc.diannan.qualification",
        ),
        (
            "enzymedesign.hmmer.local",
            "hmmbuild",
            "enzymedesign.hmmer.local.hmmbuild@1",
            None,
        ),
        (
            "enzymedesign.vina.hpc",
            "dock",
            "enzymedesign.vina.hpc-primary.dock@1",
            "credential.hpc.diannan.qualification",
        ),
        (
            "enzymedesign.fpocket.local",
            "detect",
            "enzymedesign.fpocket.local.detect@1",
            None,
        ),
        (
            "enzymedesign.docking.preprocess",
            "smiles_to_3d",
            "enzymedesign.docking.preprocess.rdkit.smiles_to_3d@1",
            None,
        ),
    ),
)
def test_live_factory_builds_exact_owner_bridge_without_performing_effect(
    factory,
    component_id: str,
    operation: str,
    route_id: str,
    locator: str | None,
) -> None:
    binding = _binding(component_id, operation, route_id, locator)

    bridge = factory.builders()[component_id](binding)

    assert bridge.binding.binding_digest == binding.binding_digest


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("workspace_root", "/data/openzyme/qualification/workspaces"),
        ("isolation_command", "/usr/local/libexec/openzyme-workspace-isolation"),
        ("ssh_user", "different-principal"),
    ),
)
def test_live_factory_rejects_hpc_material_outside_qualified_workspace_runtime(
    factory,
    field_name: str,
    field_value: str,
) -> None:
    material = factory.credential_resolver.materials[
        "credential.hpc.diannan.qualification"
    ]
    material.fields[field_name] = field_value
    binding = _binding(
        "openzyme.hpc.ssh",
        "helper-identity",
        "openzyme.hpc.ssh.helper-identity@1",
        "credential.hpc.diannan.qualification",
    )

    with pytest.raises(
        ExternalQualificationError,
        match="differs from the qualified workspace runtime",
    ) as error:
        factory.builders()[binding.component_id](binding)
    assert error.value.error_code == (
        "qualification_hpc_workspace_runtime_binding_mismatch"
    )
