from pathlib import Path

import pytest

from openzyme_contracts import ExternalQualificationError
from openzyme_hpc_ssh import OpenSshAlphaFoldQualificationIdentityObservationPort
from openzyme_hpc_ssh import OpenSshHpcQualificationIdentityObservationPort
from openzyme_hpc_ssh import OpenSshQualificationState
from openzyme_hpc_ssh import observe_diannan_workspace_runtime_identity


class _Material:
    locator_id = "credential.hpc.diannan.qualification"
    locator_version = "v1"
    material_kind = "openssh-identity"

    def __init__(self, identity_file: Path, known_hosts_file: Path) -> None:
        self._values = {
            "ssh_host": "diannan.internal",
            "ssh_port": "22222",
            "ssh_user": "qualification",
            "identity_file": str(identity_file),
            "known_hosts_file": str(known_hosts_file),
            "hmmer_sif": "/home/qualification/containers/hmmer_3.4.sif",
            "vina_sif": "/home/qualification/containers/vina.sif",
            "fpocket_sif": "/home/qualification/containers/fpocket.sif",
        }

    def field_value(self, field_name: str) -> str:
        return self._values[field_name]


class _Commands:
    def __init__(self) -> None:
        self.argv: tuple[str, ...] = ()

    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        self.argv = argv
        return (
            0,
            "Linux 6.1 x86_64\n"
            "3090\n"
            "apptainer version 1.4.5\n"
            f"{'a' * 64}\n"
            "# HMMER 3.4 (Aug 2023); http://hmmer.org/\n"
            f"{'b' * 64}\n"
            "AutoDock Vina 1.1.2 (May 11, 2011)\n"
            f"{'c' * 64}\n"
            ":||: fpocket 4.0 :||:\n",
            "",
        )


class _AlphaFoldCommands:
    def __init__(self, *, malformed: bool = False) -> None:
        self.argv: tuple[str, ...] = ()
        self.malformed = malformed

    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        self.argv = argv
        fields = (
            "3.0.1",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 40,
            "0" * 64,
            "apptainer version 1.4.5",
        )
        if self.malformed:
            fields = (*fields[:-1], "unexpected runtime")
        return 0, "\n".join(fields) + "\n", ""


def test_openssh_identity_observation_uses_exact_files_without_ambient_fallback(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    commands = _Commands()
    port = OpenSshHpcQualificationIdentityObservationPort(command_port=commands)

    observation = port.observe(
        host_alias="Diannan",
        partition="3090",
        credential_material=_Material(identity_file, known_hosts_file),
    )

    assert observation.host_alias == "Diannan"
    assert observation.ssh_port == 22222
    assert observation.partition == "3090"
    assert observation.inventory_generation_digest.startswith("sha256:")
    assert observation.software_image_digest("software.hmmer") == (
        "sha256:" + "a" * 64
    )
    assert observation.software_version("software.hmmer") == "3.4"
    assert observation.software_version("software.vina") == "1.1.2"
    assert observation.software_version("software.fpocket") == "4.0"
    assert observation.apptainer_version == "apptainer version 1.4.5"
    assert commands.argv[:3] == ("ssh", "-F", "/dev/null")
    assert commands.argv[3:5] == ("-p", "22222")
    assert "BatchMode=yes" in commands.argv
    assert "IdentitiesOnly=yes" in commands.argv
    assert f"IdentityFile={identity_file}" in commands.argv
    assert f"UserKnownHostsFile={known_hosts_file}" in commands.argv
    assert commands.argv[-3:-1] == ("bash", "-lc")


def test_openssh_identity_observation_rejects_invalid_port_before_command(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    material = _Material(identity_file, known_hosts_file)
    material._values["ssh_port"] = "65536"
    commands = _Commands()
    port = OpenSshHpcQualificationIdentityObservationPort(command_port=commands)

    with pytest.raises(ExternalQualificationError) as error:
        port.observe(
            host_alias="Diannan",
            partition="3090",
            credential_material=material,
        )

    assert error.value.error_code == "qualification_hpc_credential_identity_invalid"
    assert commands.argv == ()


def test_openssh_identity_observation_rejects_unparseable_software_version(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    commands = _Commands()
    original_run = commands.run

    def malformed(argv: tuple[str, ...]) -> tuple[int, str, str]:
        returncode, stdout, stderr = original_run(argv)
        return returncode, stdout.replace("AutoDock Vina 1.1.2", "Vina unknown"), stderr

    commands.run = malformed  # type: ignore[method-assign]
    port = OpenSshHpcQualificationIdentityObservationPort(command_port=commands)

    with pytest.raises(ExternalQualificationError) as error:
        port.observe(
            host_alias="Diannan",
            partition="3090",
            credential_material=_Material(identity_file, known_hosts_file),
        )

    assert error.value.error_code == (
        "qualification_hpc_software_version_unparseable"
    )


def test_alphafold_identity_observation_binds_exact_admin_resource_closure(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    commands = _AlphaFoldCommands()
    port = OpenSshAlphaFoldQualificationIdentityObservationPort(
        command_port=commands
    )

    observation = port.observe(
        host_alias="Diannan",
        partition="3090",
        credential_material=_Material(identity_file, known_hosts_file),
    )

    assert observation.alphafold_version == "3.0.1"
    assert observation.wrapper_digest == "sha256:" + "a" * 64
    assert observation.image_digest == "sha256:" + "b" * 64
    assert observation.model_parameters_digest == "sha256:" + "c" * 64
    assert observation.database_closure_digest == "sha256:" + "d" * 64
    assert observation.gpu_capability_digest == "sha256:" + "e" * 64
    assert observation.source_commit == "f" * 40
    assert observation.source_dirty_digest == "sha256:" + "0" * 64
    assert observation.inventory_generation_digest.startswith("sha256:")
    assert commands.argv[:5] == ("ssh", "-F", "/dev/null", "-p", "22222")
    assert "/opt/tools_env/alphafold3" in commands.argv[-1]
    assert "sinfo -h -p 3090" in commands.argv[-1]


def test_alphafold_identity_observation_rejects_shape_drift(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    port = OpenSshAlphaFoldQualificationIdentityObservationPort(
        command_port=_AlphaFoldCommands(malformed=True)
    )

    with pytest.raises(ExternalQualificationError) as error:
        port.observe(
            host_alias="Diannan",
            partition="3090",
            credential_material=_Material(identity_file, known_hosts_file),
        )

    assert error.value.error_code == (
        "qualification_alphafold_identity_observation_failed"
    )


class _WorkspaceCommands:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        assert argv[-3:-1] == ("bash", "-lc")
        return (
            0,
            "VERSION=1.0.0\n"
            f"BUILD=sha256:{'d' * 64}\n"
            f"ROOT_POLICY=sha256:{'e' * 64}\n"
            f"PRINCIPAL=sha256:{'f' * 64}\n"
            "OWNER=grtresy\nGROUP=grtresy\nMODE=755\n",
            "",
        )


def test_workspace_runtime_identity_observation_binds_deployment_evidence(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "id_ed25519"
    identity_file.write_text("fake-test-key", encoding="utf-8")
    identity_file.chmod(0o600)
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("fake-test-host-key", encoding="utf-8")
    material = _Material(identity_file, known_hosts_file)
    material._values["workspace_root"] = "/qualification/workspaces"
    state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="workspace-runtime-observation",
        command_port=_WorkspaceCommands(),
    )

    observation = observe_diannan_workspace_runtime_identity(
        state=state,
        deployment_plan_digest="sha256:" + "1" * 64,
        deployment_receipt_digest="sha256:" + "2" * 64,
        native_qualification_digest="sha256:" + "3" * 64,
    )

    assert observation.helper_path == (
        "/home/grtresy/.local/libexec/openzyme-workspace-runtime"
    )
    assert observation.helper_build_digest == "sha256:" + "d" * 64
    assert observation.root_policy_digest == "sha256:" + "e" * 64
    assert observation.principal_identity_digest == "sha256:" + "f" * 64
    assert observation.observation_digest.startswith("sha256:")
