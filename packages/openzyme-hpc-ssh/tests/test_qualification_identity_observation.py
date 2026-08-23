from pathlib import Path

from openzyme_hpc_ssh import OpenSshHpcQualificationIdentityObservationPort


class _Material:
    locator_id = "credential.hpc.diannan.qualification"
    locator_version = "v1"
    material_kind = "openssh-identity"

    def __init__(self, identity_file: Path, known_hosts_file: Path) -> None:
        self._values = {
            "ssh_host": "diannan.internal",
            "ssh_user": "qualification",
            "identity_file": str(identity_file),
            "known_hosts_file": str(known_hosts_file),
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
            "Linux 6.1 x86_64\n3090\nHMMER 3.4\nAutoDock Vina v1.2.7\nfpocket 4.2.3\n",
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
    assert observation.partition == "3090"
    assert observation.inventory_generation_digest.startswith("sha256:")
    assert commands.argv[:3] == ("ssh", "-F", "/dev/null")
    assert "BatchMode=yes" in commands.argv
    assert "IdentitiesOnly=yes" in commands.argv
    assert f"IdentityFile={identity_file}" in commands.argv
    assert f"UserKnownHostsFile={known_hosts_file}" in commands.argv
