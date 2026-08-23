from dataclasses import dataclass

from enzymedesign_distribution import FormalComputeScientificQualificationOperation
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationInput
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_contracts import canonical_sha256_digest


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


@dataclass
class _Compiler:
    route_kind: str = "local"
    validations: int = 0

    def compile(self, request):
        return ExternalScientificQualificationWorkload.create(
            workload_id=f"workload.{request.attempt_id}",
            driver_component_id="enzymedesign.hmmer.local",
            operation=request.operation,
            route_kind=self.route_kind,
            argv=("hmmbuild", "--noali", "results/model.hmm", "inputs/a.fasta"),
            cwd="analysis/hmmer",
            inputs=(
                ExternalScientificQualificationInput(
                    path="inputs/a.fasta",
                    content_digest=DIGEST,
                    size_bytes=12,
                ),
            ),
            expected_output_paths=("results/model.hmm",),
            compiled_workload_digest=OTHER_DIGEST,
        )

    def validate_terminal_result(self, workload, outcome):
        assert outcome.workload_digest == workload.workload_digest
        self.validations += 1


@dataclass
class _Route:
    route_kind: str = "local"
    dispatches: int = 0

    def dispatch(self, workload):
        self.dispatches += 1
        payload = {"workload_digest": workload.workload_digest, "result": "ok"}
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
            effect_certainty="terminal_known",
            terminal=True,
            succeeded=True,
            output_digest=canonical_sha256_digest(payload),
            receipt_digest=canonical_sha256_digest({**payload, "receipt": True}),
            error_code=None,
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def reconcile(self, workload):
        raise AssertionError("terminal fake route must not reconcile")


@dataclass
class _InDoubtRoute:
    route_kind: str = "local"

    def dispatch(self, workload):
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
            effect_certainty="dispatch_in_doubt",
            terminal=True,
            succeeded=False,
            output_digest=None,
            receipt_digest=None,
            error_code="qualification_compute_remote_timeout_in_doubt",
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def reconcile(self, workload):
        raise AssertionError("terminal in-doubt route must not redispatch")


def _request() -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id="attempt.hmmer.build",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        operation="hmmbuild",
        timeout_seconds=60,
        input_digest=DIGEST,
        expected_result_schema_digest=OTHER_DIGEST,
        credential_locator_id=None,
    )


def test_formal_compute_operation_compiles_dispatches_and_validates_terminal_result():
    compiler = _Compiler()
    route = _Route()
    operation = FormalComputeScientificQualificationOperation(
        component_id="enzymedesign.hmmer.local",
        route_id="enzymedesign.hmmer.local.hmmbuild@1",
        subject_digest=DIGEST,
        driver_component_id="enzymedesign.hmmer.local",
        workload_input_digest=DIGEST,
        result_schema_digest=OTHER_DIGEST,
        compiler=compiler,
        compute_route=route,
    )

    outcome = operation.dispatch(_request())

    assert outcome.terminal is True
    assert outcome.succeeded is True
    assert outcome.external_effect_performed is True
    assert outcome.fallback_performed is False
    assert compiler.validations == 1
    assert route.dispatches == 1


def test_formal_compute_operation_rejects_route_drift_before_effect():
    compiler = _Compiler(route_kind="hpc-primary")
    route = _Route(route_kind="local")
    operation = FormalComputeScientificQualificationOperation(
        component_id="enzymedesign.hmmer.local",
        route_id="enzymedesign.hmmer.local.hmmbuild@1",
        subject_digest=DIGEST,
        driver_component_id="enzymedesign.hmmer.local",
        workload_input_digest=DIGEST,
        result_schema_digest=OTHER_DIGEST,
        compiler=compiler,
        compute_route=route,
    )

    outcome = operation.dispatch(_request())

    assert outcome.terminal is True
    assert outcome.succeeded is False
    assert outcome.error_code == "qualification_compute_workload_binding_mismatch"
    assert outcome.external_effect_performed is False
    assert route.dispatches == 0


def test_formal_compute_preserves_terminal_dispatch_in_doubt_certainty() -> None:
    operation = FormalComputeScientificQualificationOperation(
        component_id="enzymedesign.hmmer.local",
        route_id="enzymedesign.hmmer.local.hmmbuild@1",
        subject_digest=DIGEST,
        driver_component_id="enzymedesign.hmmer.local",
        workload_input_digest=DIGEST,
        result_schema_digest=OTHER_DIGEST,
        compiler=_Compiler(),
        compute_route=_InDoubtRoute(),
    )

    outcome = operation.dispatch(_request())

    assert outcome.terminal is True
    assert outcome.succeeded is False
    assert outcome.effect_certainty == "dispatch_in_doubt"
    assert outcome.error_code == "qualification_compute_remote_timeout_in_doubt"
