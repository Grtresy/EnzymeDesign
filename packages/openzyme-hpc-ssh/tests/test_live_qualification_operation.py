from dataclasses import dataclass
from dataclasses import field
import re

from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_hpc_ssh import OpenSshQualificationOperation
from openzyme_hpc_ssh import OpenSshQualificationState


DIGEST = "sha256:" + "1" * 64


@dataclass(frozen=True)
class _Material:
    locator_id: str
    values: dict[str, str]
    locator_version: str = "v1"
    material_kind: str = "ssh"

    def field_value(self, field_name: str) -> str:
        return self.values[field_name]


@dataclass
class _CommandPort:
    response_loss_token: str | None = None
    scripts: list[str] = field(default_factory=list)

    def run(self, argv: tuple[str, ...]):
        script = argv[-1]
        self.scripts.append(script)
        if script == "command -v sh; command -v sha256sum":
            return 0, "/bin/sh\n/usr/bin/sha256sum\n", ""
        if script == "uname -srm":
            return 0, "Linux 6.1 x86_64\n", ""
        if script.endswith("/item") and script.startswith("cat "):
            return 0, "create", ""
        if script == "printf OPENZYME_SSH_OK":
            return 0, "OPENZYME_SSH_OK", ""
        if script.startswith("printf '%s'") and script.endswith("/response-loss"):
            match = re.search(r"printf '%s' ([0-9a-f]{64})", script)
            assert match is not None
            self.response_loss_token = match.group(1)
            return 0, "", ""
        if script.endswith("/response-loss") and script.startswith("cat "):
            return 0, self.response_loss_token or "", ""
        return 0, "", ""


def _request(operation: str) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.ssh.{operation}",
        plan_digest=DIGEST,
        unit_digest=DIGEST,
        operation=operation,
        timeout_seconds=120,
        input_digest=DIGEST,
        expected_result_schema_digest=DIGEST,
        credential_locator_id="credential.hpc.diannan.qualification",
    )


def test_ssh_qualification_runs_exact_port_and_restores_response_loss(tmp_path) -> None:
    identity = tmp_path / "identity"
    identity.write_text("placeholder", encoding="utf-8")
    identity.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("placeholder", encoding="utf-8")
    known_hosts.chmod(0o600)
    command = _CommandPort()
    material = _Material(
        locator_id="credential.hpc.diannan.qualification",
        values={
            "ssh_host": "diannan",
            "ssh_user": "operator",
            "ssh_port": "22222",
            "identity_file": str(identity),
            "known_hosts_file": str(known_hosts),
        },
    )
    state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="batch-1-test",
        command_port=command,
    )
    operation = OpenSshQualificationOperation(
        component_id="openzyme.hpc.ssh",
        route_id="openzyme.hpc.ssh.helper-identity@1",
        subject_digest=DIGEST,
        state=state,
    )
    for operation_id in (
        "helper-identity",
        "version",
        "create",
        "read",
        "update",
        "delete",
        "exec",
    ):
        assert operation.dispatch(_request(operation_id)).succeeded is True

    request = _request("response-loss-reconcile")
    assert operation.dispatch(request).terminal is False
    restored_state = OpenSshQualificationState(
        credential_material=material,
        workspace_id="batch-1-test",
        command_port=command,
    )
    restored = OpenSshQualificationOperation(
        component_id="openzyme.hpc.ssh",
        route_id="openzyme.hpc.ssh.response-loss-reconcile@1",
        subject_digest=DIGEST,
        state=restored_state,
    )
    restored.restore_dispatched_attempt(request)

    assert restored.reconcile(request).succeeded is True
    assert any("-p" in argv for argv in (state._connection_argv(),))
    assert "22222" in state._connection_argv()
