from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import time

from openzyme_host_api.architecture_qualification import load_invariant_registry

from .composition import ProductionCompositionFactory
from .driver import QualificationDriver
from .driver import materialized_observation_response
from .external_ports import ControlledPortOutcome
from .external_ports import EffectAcceptance
from .fault_process import FAULT_CHILD_MODES
from .fault_process import build_fault_ready_frame
from .safety import QualificationSafetyGuard
from .safety import is_credential_name


_CONTROL_FD_ENV = "OPENZYME_QUALIFICATION_CONTROL_FD"
_LAUNCH_NONCE_ENV = "OPENZYME_QUALIFICATION_LAUNCH_NONCE"
_SCENARIO_ROOT_ENV = "OPENZYME_QUALIFICATION_SCENARIO_ROOT"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SANITIZER_SCALE_INPUT_BYTES = 64 * 1024


def _credential_names() -> list[str]:
    return sorted(key for key in os.environ if is_credential_name(key))


def _emit_ready(
    descriptor: int,
    *,
    mode: str,
    launch_nonce: str,
    payload: dict[str, object],
) -> None:
    content = build_fault_ready_frame(
        mode=mode,
        launch_nonce=launch_nonce,
        payload=payload,
    )
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]
    os.close(descriptor)


def _wait_with_default_signal_semantics(
    descriptor: int,
    *,
    mode: str,
    launch_nonce: str,
    payload: dict[str, object],
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    _emit_ready(
        descriptor,
        mode=mode,
        launch_nonce=launch_nonce,
        payload=payload,
    )
    while True:
        signal.pause()


def _run_host_dispatch_in_doubt(
    descriptor: int,
    *,
    launch_nonce: str,
) -> None:
    root_text = os.environ.get(_SCENARIO_ROOT_ENV)
    if root_text is None:
        raise RuntimeError("qualification Host child scenario root is absent")
    factory = ProductionCompositionFactory.create(Path(root_text))
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        session_id = "sess_operator_process_signal"
        driver.create_session(session_id)
        ids = driver.admit_durable_operation(
            session_id=session_id,
            scenario_key="operator_process_signal",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        response = materialized_observation_response(
            bounded_result_envelope={
                "bounded_summary": {"status": "completed"},
                "output_artifact_ids": [],
                "registered_artifact_ids": [],
                "status": "succeeded",
            },
            backend_handle_ref=None,
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.ACCEPTED,
                effect_attempted=True,
                response=response,
                error_code="simulated_lost_callback",
            ),
        )
        driver.resolve_approval(ids.approval_id)
        in_doubt = driver.run_execution_once(
            ids.execution_id,
            worker_id="qualification:operator-process-child",
        )
        records = driver.canonical_records(ids)
        ledger = factory.external_effect_ledger.snapshot()
        payload: dict[str, object] = {
            "before_signal": {
                "approval_count": len(records["approvals"]),
                "approval_status": records["approval"]["status"],  # type: ignore[index]
                "lifecycle_state": in_doubt["lifecycle_state"],
                "result_present": records["result"] is not None,
                "task_count": len(records["tasks"]),
                "terminal_outcome": records["execution"]["terminal_outcome"],  # type: ignore[index]
            },
            "credential_names": _credential_names(),
            "effect_ledger": ledger,
            "ids": {
                "approval_id": ids.approval_id,
                "continuation_id": ids.continuation_id,
                "execution_id": ids.execution_id,
                "operation_id": ids.operation_id,
                "sandbox_run_id": ids.sandbox_run_id,
                "sandbox_workspace_id": ids.sandbox_workspace_id,
                "session_id": ids.session_id,
            },
        }
        _wait_with_default_signal_semantics(
            descriptor,
            mode="host_dispatch_in_doubt",
            launch_nonce=launch_nonce,
            payload=payload,
        )


def _run(mode: str, descriptor: int, launch_nonce: str) -> None:
    common = {"credential_names": _credential_names()}
    if mode == "host_dispatch_in_doubt":
        _run_host_dispatch_in_doubt(descriptor, launch_nonce=launch_nonce)
        return
    if mode == "wait":
        _wait_with_default_signal_semantics(
            descriptor,
            mode=mode,
            launch_nonce=launch_nonce,
            payload=common,
        )
        return
    if mode == "ignore_term":
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _emit_ready(
            descriptor,
            mode=mode,
            launch_nonce=launch_nonce,
            payload=common,
        )
        while True:
            signal.pause()
    if mode == "early_exit":
        _emit_ready(
            descriptor,
            mode=mode,
            launch_nonce=launch_nonce,
            payload=common,
        )
        time.sleep(0.1)
        os._exit(23)
    if mode == "sanitize_long_scalar":
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        _emit_ready(
            descriptor,
            mode=mode,
            launch_nonce=launch_nonce,
            payload={
                **common,
                "input_byte_length": _SANITIZER_SCALE_INPUT_BYTES,
            },
        )
        from openzyme_runtime import sanitize_public_diagnostic_text

        sanitized = sanitize_public_diagnostic_text(
            "a" * _SANITIZER_SCALE_INPUT_BYTES
        )
        if len(sanitized) != _SANITIZER_SCALE_INPUT_BYTES:
            raise RuntimeError("public diagnostic sanitizer changed an allowed scalar")
        os._exit(0)
    if mode == "descendant_residue":
        descendant_pid = os.fork()
        if descendant_pid == 0:
            os.close(descriptor)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                signal.pause()
        _emit_ready(
            descriptor,
            mode=mode,
            launch_nonce=launch_nonce,
            payload={**common, "descendant_pid": descendant_pid},
        )
        time.sleep(0.1)
        os._exit(0)
    raise AssertionError(f"unhandled fault child mode {mode!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(FAULT_CHILD_MODES), required=True)
    arguments = parser.parse_args()
    descriptor_text = os.environ.get(_CONTROL_FD_ENV)
    launch_nonce = os.environ.get(_LAUNCH_NONCE_ENV)
    if descriptor_text is None or launch_nonce is None:
        raise RuntimeError("qualification fault child control identity is absent")
    if os.getpgrp() != os.getpid():
        raise RuntimeError("qualification fault child lacks a dedicated process group")
    registry = load_invariant_registry(repo_root=_REPO_ROOT)
    with QualificationSafetyGuard(registry=registry.payload):
        _run(arguments.mode, int(descriptor_text), launch_nonce)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
