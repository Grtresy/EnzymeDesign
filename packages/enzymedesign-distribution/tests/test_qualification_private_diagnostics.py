from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import stat

from enzymedesign_distribution.qualification_private_diagnostics import (
    DiagnosticQualificationBridge,
)
from enzymedesign_distribution.qualification_private_diagnostics import (
    ProtectedQualificationDiagnosticWriter,
)
from enzymedesign_distribution.qualification_private_diagnostics import (
    QualificationDiagnosticContext,
)
from enzymedesign_distribution.qualification_private_diagnostics import (
    RecordingSshCommandPort,
)
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64
SECRET_CANARY = "private-provider-detail-canary"


def _binding() -> ExternalQualificationBridgeBinding:
    return ExternalQualificationBridgeBinding.create(
        component_id="openzyme.hpc.ssh",
        operation="helper-identity",
        route_id="openzyme.hpc.ssh.helper-identity@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
        credential_locator_id="credential.hpc.diannan.qualification",
    )


def _request(binding: ExternalQualificationBridgeBinding) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id="qualification.private-diagnostic-test",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=30,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id=binding.credential_locator_id,
    )


@dataclass(frozen=True)
class _FailingCommand:
    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        del argv
        return 17, "x" * 40_000 + SECRET_CANARY, f"stderr:{SECRET_CANARY}"


@dataclass
class _Bridge:
    binding: ExternalQualificationBridgeBinding
    command_port: RecordingSshCommandPort
    restored: bool = False

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        self.command_port.run(("ssh", "diannan", "false"))
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=ExternalQualificationProbeDisposition.FAILED,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            observed_operation=request.operation,
            output_digest=None,
            observed_result_schema_digest=None,
            backend_receipt_digest=None,
            error_code="qualification_ssh_command_failed",
        )

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self.dispatch(request)

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        del request
        self.restored = True


def test_private_diagnostic_capture_is_bounded_protected_and_not_public(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-diagnostics"
    writer = ProtectedQualificationDiagnosticWriter(root)
    context = QualificationDiagnosticContext(writer)
    binding = _binding()
    delegate = _Bridge(
        binding=binding,
        command_port=RecordingSshCommandPort(_FailingCommand(), context),
    )
    bridge = DiagnosticQualificationBridge(
        delegate=delegate,
        context=context,
        component_id=binding.component_id,
    )
    request = _request(binding)

    outcome = bridge.dispatch(request)
    bridge.restore_dispatched_attempt(request)

    assert bridge.binding.binding_digest == binding.binding_digest
    assert delegate.restored is True
    assert SECRET_CANARY not in json.dumps(outcome.to_dict())
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    records = sorted(root.glob("qualification-diagnostic-*.json"))
    assert len(records) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in records)
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in records]
    command = next(item for item in payloads if item["kind"] == "external-command")
    terminal = next(item for item in payloads if item["kind"] == "terminal-outcome")
    assert command["diagnostic_id"] == f"diagnostic.{request.attempt_id}"
    assert command["bounded_stdout"].endswith(SECRET_CANARY)
    assert len(command["bounded_stdout"].encode("utf-8")) <= 32_768
    assert command["bounded_stderr"] == f"stderr:{SECRET_CANARY}"
    assert terminal["error_code"] == "qualification_ssh_command_failed"
