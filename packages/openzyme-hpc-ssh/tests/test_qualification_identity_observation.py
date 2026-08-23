from pathlib import Path

import pytest

from openzyme_contracts import ExternalQualificationError
from openzyme_hpc_ssh import OpenSshHpcQualificationIdentityObservationPort


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
