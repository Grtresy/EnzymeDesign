from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_process_podman import PodmanQualificationState
from openzyme_process_podman import SubprocessPodmanQualificationOperation


DIGEST = "sha256:" + "1" * 64


@dataclass
class _CommandPort:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, argv: tuple[str, ...]):
        self.calls.append(argv)
        if "inspect" in argv:
            return 0, '[{"Destination":"/qualification"}]', ""
        if argv[-2:] == ("cat", "/qualification/item"):
            return 0, "create", ""
        if argv[-2:] == ("printf", "OPENZYME_PODMAN_OK"):
            return 0, "OPENZYME_PODMAN_OK", ""
        if "timeout" in argv:
            return 124, "", ""
        return 0, "", ""


def _request(operation: str) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.podman.{operation}",
        plan_digest=DIGEST,
        unit_digest=DIGEST,
        operation=operation,
        timeout_seconds=120,
        input_digest=DIGEST,
        expected_result_schema_digest=DIGEST,
        credential_locator_id=None,
    )


def test_podman_qualification_operation_uses_exact_isolated_lifecycle(tmp_path) -> None:
    command = _CommandPort()
    state = PodmanQualificationState(
        image_digest="sha256:" + "a" * 64,
        container_name="openzyme-qualification-test",
        workspace=tmp_path / "workspace",
        command_port=command,
    )
    operation = SubprocessPodmanQualificationOperation(
        component_id="openzyme.process.podman",
        route_id="openzyme.process.podman.container-start@1",
        subject_digest=DIGEST,
        state=state,
    )

    for operation_id in (
        "container-start",
        "mount",
        "create",
        "read",
        "update",
        "delete",
        "exec",
        "timeout",
        "retire",
    ):
        outcome = operation.dispatch(_request(operation_id))
        assert outcome.succeeded is True
        assert outcome.fallback_performed is False

    start = command.calls[0]
    assert "--network" in start and "none" in start
    assert "--memory" in start and "2g" in start
    assert state.cleanup()["container_absent"] is True
