from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from openzyme_host_api import aox_cutover_cli as cli
from openzyme_host_api.aox_architecture_qualification import (
    build_architecture_qualification_receipt,
)
from openzyme_host_api.aox_architecture_qualification import (
    AoxArchitectureQualificationError,
)
from openzyme_host_api.aox_attempt_authority import (
    attempt_authority_consumption_path,
)
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    publish_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_host_api.aox_launch_profile import build_aox_cutover_launch_profile
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy


def _architecture_qualification() -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest="sha256:" + "1" * 64,
        registry_digest="sha256:" + "2" * 64,
        test_manifest_digest="sha256:" + "3" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
        report_schema_id="openzyme_v3_architecture_qualification_report@3",
        run_evidence_digest="sha256:" + "4" * 64,
        source_identity_digest="sha256:" + "5" * 64,
        owner_constraint_registry_digest="sha256:" + "6" * 64,
        transformation_results_digest="sha256:" + "7" * 64,
    )


def _launch_settings() -> OpenZymeSettings:
    settings = OpenZymeSettings.from_env()
    return replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
        ),
    )


def _launch_profile(
    *,
    ledger_path: Path = Path("/tmp/aox-cli-ledger.json"),
) -> dict[str, object]:
    return build_aox_cutover_launch_profile(
        settings=_launch_settings(),
        ledger_path=ledger_path,
        source_commit="a" * 40,
        config_digest="sha256:" + "b" * 64,
        created_at="2026-07-23T00:00:00+00:00",
    )


def test_cli_json_handoff_is_flushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def capture(value: str, *, flush: bool) -> None:
        observed.update(value=value, flush=flush)

    monkeypatch.setattr("builtins.print", capture)
    cli._print({"status": "host_ready"})

    assert observed["flush"] is True
    assert json.loads(str(observed["value"])) == {"status": "host_ready"}


def test_config_contract_help_names_profile_descriptor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(["config-contract", "--help"])

    assert error.value.code == 0
    assert "profile descriptor and candidate lifecycle contract" in " ".join(
        capsys.readouterr().out.split()
    )


def test_decide_accepts_verified_slot_failure_without_attempt_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_path = tmp_path / "formal-slot-failure.json"
    output_path = tmp_path / "campaign-decision.json"
    decision = {
        "schema_id": "aox_blank_world_campaign_failure_decision@1",
        "decision": "NO-GO",
        "decision_digest": "sha256:" + "a" * 64,
    }
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "evaluate_formal_slot_failure",
        lambda path: decision if path == failure_path else None,
    )
    monkeypatch.setattr(
        cli,
        "seal_formal_slot_failure_decision",
        lambda value, destination: observed.update(
            decision=value,
            destination=destination,
        ),
    )
    monkeypatch.setattr(cli, "_print", lambda value: observed.update(output=value))
    args = cli.build_parser().parse_args(
        [
            "decide",
            "--slot-failure",
            str(failure_path),
            "--output",
            str(output_path),
        ]
    )

    assert cli._decide(args) == 2
    assert args.attempt is None
    assert observed == {
        "decision": decision,
        "destination": output_path,
        "output": decision,
    }


def test_decide_accepts_preflight_failure_without_claim_or_launch_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_path = tmp_path / "preflight-failure.json"
    output_path = tmp_path / "campaign-decision.json"
    decision = {
        "schema_id": "aox_blank_world_campaign_preflight_failure_decision@1",
        "decision": "NO-GO",
        "attempt_ids": [],
        "decision_digest": "sha256:" + "a" * 64,
    }
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "evaluate_formal_preflight_failure",
        lambda path: decision if path == failure_path else None,
    )
    monkeypatch.setattr(
        cli,
        "seal_formal_preflight_failure_decision",
        lambda value, destination: observed.update(
            decision=value,
            destination=destination,
        ),
    )
    monkeypatch.setattr(cli, "_print", lambda value: observed.update(output=value))
    args = cli.build_parser().parse_args(
        [
            "decide",
            "--preflight-failure",
            str(failure_path),
            "--output",
            str(output_path),
        ]
    )

    assert cli._decide(args) == 2
    assert args.attempt is None
    assert args.slot_failure is None
    assert "launch_id" not in decision
    assert observed == {
        "decision": decision,
        "destination": output_path,
        "output": decision,
    }


@pytest.fixture(autouse=True)
def _verified_architecture_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        lambda path: _architecture_qualification(),
    )


def _pinned_authority_declarations(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, str], dict[str, str], dict[str, object]]:
    identity_path = tmp_path / "identity.json"
    prerequisite_path = tmp_path / "prerequisites.json"
    identity = {"declared": "identity"}
    prerequisites = {"declared": "prerequisites"}
    launch_profile = _launch_profile()
    cli._write_pin_outputs_atomic_no_replace(
        identity_target=identity_path,
        prerequisites_target=prerequisite_path,
        profile_target=tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME,
        identity=identity,
        prerequisites=prerequisites,
        launch_profile=launch_profile,
        architecture_qualification=_architecture_qualification(),
    )
    return (
        identity_path,
        prerequisite_path,
        identity,
        prerequisites,
        launch_profile,
    )


def _consume_authority_args(
    tmp_path: Path,
    *,
    plan_name: str = "attempt-authority.json",
    include_consumption_assertion: bool = True,
):
    (
        identity_path,
        prerequisite_path,
        identity,
        prerequisites,
        launch_profile,
    ) = _pinned_authority_declarations(tmp_path)
    authority_plan_path = tmp_path / plan_name
    authority_plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=_architecture_qualification(),
        launch_profile=launch_profile,
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=1,
        max_cost_microunits_per_attempt=1,
        max_wall_time_seconds_per_attempt=100_000,
    )
    publish_aox_attempt_authority_plan(authority_plan, authority_plan_path)
    arguments = [
        "consume-authority",
        "--identity",
        str(identity_path),
        "--allowed-prerequisites",
        str(prerequisite_path),
        "--architecture-qualification-report",
        str(tmp_path / "architecture-qualification.json"),
        "--attempt-authority-plan",
        str(authority_plan_path),
    ]
    if include_consumption_assertion:
        arguments.extend(
            [
                "--attempt-authority-consumption",
                str(attempt_authority_consumption_path(authority_plan_path)),
            ]
        )
    return cli.build_parser().parse_args(arguments)


def _pin_args(tmp_path: Path):
    return cli.build_parser().parse_args(
        [
            "pin",
            "--identity-output",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites-output",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
        ]
    )


def _check_config_args(tmp_path: Path):
    return cli.build_parser().parse_args(
        [
            "check-config",
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
        ]
    )


def _reject_architecture_qualification(path: Path) -> dict[str, str]:
    del path
    raise AoxArchitectureQualificationError(
        "aox_architecture_qualification_report_invalid",
        "invalid report",
    )


def test_pin_rejects_architecture_report_before_settings_or_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _pin_args(tmp_path)
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        _reject_architecture_qualification,
    )
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError(cls))),
    )

    with pytest.raises(AoxArchitectureQualificationError):
        cli._pin(args)

    assert not args.identity_output.exists()
    assert not args.allowed_prerequisites_output.exists()


def test_preflight_rejects_architecture_report_before_attempt_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification.json"),
            "--attempt-authority-plan",
            str(tmp_path / "authority.json"),
            "--attempt-authority-consumption",
            str(tmp_path / "authority.json.consumed.json"),
            "--slot-ordinal",
            "1",
        ]
    )
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        _reject_architecture_qualification,
    )
    monkeypatch.setattr(
        cli,
        "create_blank_world_roots",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError((args, kwargs))),
    )

    with pytest.raises(AoxArchitectureQualificationError):
        cli._preflight(args)

    assert not args.campaign_root.exists()


def test_consume_authority_rejects_architecture_report_before_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _consume_authority_args(tmp_path)
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        _reject_architecture_qualification,
    )

    with pytest.raises(AoxArchitectureQualificationError):
        cli._consume_authority(args)

    assert not args.attempt_authority_consumption.exists()


def test_automatic_live_commands_are_absent() -> None:
    parser = cli.build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    assert "run-live" not in subcommands
    assert "run-diagnostic-live" not in subcommands
    assert "check-config" in subcommands
    assert "consume-authority" in subcommands
    assert "authorize-diagnostic" not in subcommands
    assert "consume-diagnostic-authority" not in subcommands


@pytest.mark.parametrize("command", ["public-host", "grant-task-authority"])
def test_public_response_name_help_is_explicitly_nonsemantic(command: str) -> None:
    parser = cli.build_parser()
    subcommand = parser._subparsers._group_actions[0].choices[command]
    help_text = " ".join(subcommand.format_help().split())
    assert "opaque unique lowercase locator" in help_text
    assert "receipt and response payload determine its semantic role" in help_text


@pytest.mark.parametrize(
    "forwarded",
    [
        pytest.param(["sessions", "show"], id="workspace-read"),
        pytest.param(
            ["sessions", "events", "--after-cursor", "0"],
            id="event-read",
        ),
        pytest.param(["approvals", "pending"], id="approval-read"),
        pytest.param(["scientific", "inspect"], id="scientific-read"),
        pytest.param(
            ["runtime", "status", "--command-id", "runtime-command-test"],
            id="runtime-status",
        ),
        pytest.param(
            [
                "runtime",
                "drain",
                "--max-signals",
                "2",
                "--max-steps-per-agent",
                "16",
                "--idempotency-key",
                "strategy:drain",
            ],
            id="nonhistorical-drain",
        ),
    ],
)
def test_public_host_injects_formal_identity_and_preserves_strategy_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forwarded: list[str],
) -> None:
    preflight = tmp_path / "aox-attempt-preflight.json"
    response = tmp_path / "public-response-final-workspace.json"
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "load_active_public_host_context",
        lambda path: (
            {},
            {
                "project_id": "aox-blank-world-cutover",
                "session_id": "session-formal",
                "receipt_chain_name": "public-api-receipts.jsonl",
            },
            {"base_url": "http://127.0.0.1:41234"},
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        cli,
        "bound_public_response_path",
        lambda **kwargs: response,
    )
    monkeypatch.setattr(
        cli,
        "validate_public_host_command",
        lambda **kwargs: observed.update(validation=kwargs),
    )
    monkeypatch.setattr(
        cli,
        "run_host_cli",
        lambda argv: observed.update(argv=argv) or 0,
    )
    args = SimpleNamespace(
        preflight_receipt=preflight,
        response_name="final-workspace",
        host_cli_args=["--", *forwarded],
    )

    assert cli._public_host(args) == 0
    validation = dict(observed["validation"])
    assert validation["forwarded"] == forwarded
    assert observed["argv"] == [
        "--host",
        "http://127.0.0.1:41234",
        "--project-id",
        "aox-blank-world-cutover",
        "--session-id",
        "session-formal",
        "--format",
        "json",
        "--receipt-chain",
        str(tmp_path / "public-api-receipts.jsonl"),
        "--seal-response",
        str(response),
        *forwarded,
    ]


def test_public_host_rejects_evidence_and_identity_overrides(tmp_path: Path) -> None:
    args = SimpleNamespace(
        preflight_receipt=tmp_path / "aox-attempt-preflight.json",
        response_name="bad",
        host_cli_args=[
            "--",
            "--receipt-chain",
            str(tmp_path / "other"),
            "sessions",
            "show",
        ],
    )

    with pytest.raises(cli.CutoverEvidenceError) as error:
        cli._public_host(args)

    assert error.value.code == "public_conductor_command_boundary_invalid"


def test_host_operation_queries_without_writes_and_reconciles_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = {
        "project_id": "aox-blank-world-cutover",
        "session_id": "session-formal",
        "receipt_chain_name": "public-api-receipts.jsonl",
        "retirement_readiness_name": "retirement-readiness.json",
    }
    descriptor = {
        "method": "POST",
        "route": "/v3/tasks",
        "request": {
            "session_id": "session-formal",
            "subject": "exact",
            "description": "",
            "priority": "normal",
            "kind": "general",
        },
        "request_body": {
            "session_id": "session-formal",
            "subject": "exact",
            "description": "",
            "priority": "normal",
            "kind": "general",
        },
        "idempotency_key": "task-exact",
        "command_type": "task.create",
        "scope_ref": "session:session-formal",
        "owner_request_digest": "sha256:" + "a" * 64,
        "attempt_id": None,
        "artifact_id": None,
        "original_status_code": 200,
    }
    terminal = {
        "schema_id": "host_mutation_operation_observation@1",
        "session_id": "session-formal",
        "command_type": "task.create",
        "scope_ref": "session:session-formal",
        "idempotency_key": "task-exact",
        "request_digest": "sha256:" + "a" * 64,
        "status": "terminal",
        "response": {"task": {"task_id": "task-exact"}},
        "query_read_only": True,
        "resume_applicable": False,
    }
    outputs: list[dict[str, object]] = []
    client_calls: list[dict[str, object]] = []

    class FakeObservationClient:
        def __init__(self, base_url: str) -> None:
            assert base_url == "http://127.0.0.1:41234"

        def observe_v3_mutation_operation(self, **kwargs):  # type: ignore[no-untyped-def]
            client_calls.append(dict(kwargs))
            return dict(terminal)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        cli,
        "load_active_public_host_context",
        lambda path: (
            {"slot": {}},
            contract,
            {"base_url": "http://127.0.0.1:41234"},
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        cli,
        "describe_public_host_mutation",
        lambda *args, **kwargs: dict(descriptor),
    )
    monkeypatch.setattr(cli, "HostApiClient", FakeObservationClient)
    monkeypatch.setattr(
        cli,
        "validate_public_host_reconciliation",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(cli, "_print", lambda payload: outputs.append(dict(payload)))
    query_args = SimpleNamespace(
        preflight_receipt=tmp_path / "preflight.json",
        action="query",
        response_name=None,
        host_cli_args=["--", "tasks", "create", "--subject", "exact"],
    )

    assert cli._host_operation(query_args) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == []
    assert outputs[-1]["status"] == "terminal"
    assert client_calls[-1]["request_digest"] == descriptor["owner_request_digest"]

    reconcile_args = SimpleNamespace(
        **{**vars(query_args), "action": "reconcile", "response_name": "task-exact"}
    )
    assert cli._host_operation(reconcile_args) == 0
    first_chain = (tmp_path / "public-api-receipts.jsonl").read_bytes()
    first_response = (tmp_path / "public-response-task-exact.json").read_bytes()
    assert outputs[-1]["status"] == "receipt_converged"
    assert cli._host_operation(reconcile_args) == 0
    assert (tmp_path / "public-api-receipts.jsonl").read_bytes() == first_chain
    assert (tmp_path / "public-response-task-exact.json").read_bytes() == first_response


def test_host_operation_unknown_and_digest_drift_fail_without_evidence_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = {
        "project_id": "aox-blank-world-cutover",
        "session_id": "session-formal",
        "receipt_chain_name": "public-api-receipts.jsonl",
        "retirement_readiness_name": "retirement-readiness.json",
    }
    descriptor = {
        "method": "POST",
        "route": "/v3/tasks/task-exact",
        "request": {"status": "in_progress"},
        "request_body": {"status": "in_progress"},
        "idempotency_key": "task-update-exact",
        "command_type": "task.update",
        "scope_ref": "task:task-exact",
        "owner_request_digest": "sha256:" + "a" * 64,
        "attempt_id": None,
        "artifact_id": None,
        "original_status_code": 200,
    }
    observation = {
        "schema_id": "host_mutation_operation_observation@1",
        "session_id": "session-formal",
        "command_type": "task.update",
        "scope_ref": "task:task-exact",
        "idempotency_key": "task-update-exact",
        "request_digest": "sha256:" + "a" * 64,
        "status": "unproven",
        "response": None,
        "query_read_only": True,
        "resume_applicable": False,
    }

    class FakeObservationClient:
        def __init__(self, base_url: str) -> None:
            del base_url

        def observe_v3_mutation_operation(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return dict(observation)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        cli,
        "load_active_public_host_context",
        lambda path: (
            {"slot": {}},
            contract,
            {"base_url": "http://127.0.0.1:41234"},
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        cli,
        "describe_public_host_mutation",
        lambda *args, **kwargs: dict(descriptor),
    )
    monkeypatch.setattr(cli, "HostApiClient", FakeObservationClient)
    monkeypatch.setattr(cli, "_print", lambda payload: None)
    args = SimpleNamespace(
        preflight_receipt=tmp_path / "preflight.json",
        action="reconcile",
        response_name="task-update-exact",
        host_cli_args=["--", "tasks", "update", "--task-id", "task-exact"],
    )

    assert cli._host_operation(args) == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == []

    observation.update(
        status="terminal",
        request_digest="sha256:" + "b" * 64,
        response={"task": {"task_id": "task-exact"}},
    )
    with pytest.raises(cli.CutoverEvidenceError) as error:
        cli._host_operation(args)
    assert error.value.code == "public_conductor_mutation_observation_drift"
    assert sorted(path.name for path in tmp_path.iterdir()) == []


def test_late_bound_grant_derives_canonical_public_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = {
        "workflow_id": "aox_blank_world",
        "grantor_kind": "operator",
        "grantor_ref": "operator:aox-cutover",
        "allowed_scopes": ["formal"],
        "allowed_effect_classes": ["hpc", "provider"],
        "allowed_providers": ["aox-provider-routes@test"],
        "allowed_hpc_targets": ["aox-hpc-routes@test"],
        "max_attempts": 1,
        "max_micu": 100,
        "max_cost_microunits": 1000,
        "max_wall_time_seconds": 600,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "idempotency_key": "aox_campaign_test:authority:1",
    }
    slot = {
        "session_id": "session-formal",
        "root_ref": "formal-slots/aox_campaign_test/1/fixture",
        "authority_policy": policy,
    }
    preflight = {"campaign_id": "aox_campaign_test", "slot": slot}
    contract = {
        "project_id": "aox-blank-world-cutover",
        "session_id": "session-formal",
        "receipt_chain_name": "public-api-receipts.jsonl",
        "retirement_readiness_name": ("aox-public-conductor-retirement-readiness.json"),
    }
    startup = {"base_url": "http://127.0.0.1:41234"}
    response = tmp_path / "public-response-authority-grant.json"
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "resolve_pregrant_execution_task",
        lambda **kwargs: (
            observed.update(binding=kwargs)
            or {"task_id": "task_execution", "kind": "execution"}
        ),
    )
    monkeypatch.setattr(
        cli,
        "bound_public_response_path",
        lambda **kwargs: response,
    )

    result = cli.run_bound_task_authority_grant(
        preflight=preflight,
        contract=contract,
        startup=startup,
        evidence_root=tmp_path,
        response_name="authority-grant",
        task_id="task_execution",
        host_cli_runner=lambda argv: observed.update(argv=argv) or 0,
    )

    assert result == 0
    binding = dict(observed["binding"])
    assert binding["task_id"] == "task_execution"
    argv = list(observed["argv"])
    command_index = argv.index("scientific")
    assert argv[command_index : command_index + 2] == [
        "scientific",
        "authorize",
    ]
    payload_index = argv.index("--payload-json") + 1
    assert json.loads(argv[payload_index]) == cli.authority_grant_payload(
        slot,
        campaign_id="aox_campaign_test",
        task_id="task_execution",
    )
    assert argv[-2:] == [
        "--idempotency-key",
        "aox_campaign_test:authority:1",
    ]


def test_serve_attempt_refuses_retirement_then_reuses_same_host_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lease:
        startup_receipt = {"base_url": "http://127.0.0.1:41234"}
        shutdown_reason = "not_requested"
        supervision_receipt: dict[str, object] | None = None
        wait_count = 0

        def wait(self) -> None:
            self.wait_count += 1
            raise KeyboardInterrupt

    class Supervision:
        def __init__(self, lease: Lease) -> None:
            self.lease = lease

        def __enter__(self) -> Lease:
            return self.lease

        def __exit__(self, *args: object) -> None:
            self.lease.supervision_receipt = {
                "launch_id": "formal-slot-test",
                "shutdown_reason": self.lease.shutdown_reason,
                "receipt_digest": "sha256:" + "a" * 64,
            }

    lease = Lease()
    readiness_checks = 0
    outputs: list[dict[str, object]] = []

    def load_readiness(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal readiness_checks
        readiness_checks += 1
        if readiness_checks == 1:
            raise cli.CutoverEvidenceError(
                "public_conductor_response_set_incomplete",
                "one response is not sealed",
            )
        return {"receipt_digest": "sha256:" + "b" * 64}

    monkeypatch.setattr(
        cli,
        "supervised_attempt_host",
        lambda *args, **kwargs: Supervision(lease),
    )
    monkeypatch.setattr(cli, "load_conductor_retirement_readiness", load_readiness)
    monkeypatch.setattr(cli, "_print", outputs.append)
    args = SimpleNamespace(
        preflight_receipt=tmp_path / "aox-attempt-preflight.json",
        startup_timeout_seconds=1.0,
        term_grace_seconds=1.0,
        kill_grace_seconds=1.0,
    )

    assert cli._serve_attempt(args) == 0
    assert lease.wait_count == 2
    assert readiness_checks == 2
    assert lease.shutdown_reason == "operator_stop"
    assert [item.get("status") for item in outputs] == [
        "ready_for_public_host_cli",
        "host_remains_active",
        "retirement_admitted",
        "retired",
    ]
    assert outputs[1]["failure_code"] == ("public_conductor_response_set_incomplete")


def test_consume_authority_only_seals_consumption_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _consume_authority_args(tmp_path)

    result = cli._consume_authority(args)

    assert result == 0
    assert args.attempt_authority_consumption.is_file()
    assert not (tmp_path / "campaign").exists()
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "consumption_receipt_closed"
    assert output["schema_id"] == "aox_attempt_authority_consume_receipt@2"
    assert output["effect_certainty"] == "terminal_known"
    assert output["retry_eligibility"] == "terminal"
    assert output["terminal_scope"] == "authority_consumption_occurrence"
    assert output["authority_slot_count"] == 3
    assert output["max_attempts_per_slot"] == 1
    assert output["max_micu_per_slot"] == 1
    assert output["max_cost_microunits_per_slot"] == 1
    assert output["max_wall_time_seconds_per_slot"] == 100_000
    assert output["scientific_attempt_counted"] is False

    assert cli._consume_authority(args) == 0
    converged = json.loads(capsys.readouterr().out)
    assert converged["status"] == "consumption_receipt_closed"
    assert converged["consumption_digest"] == output["consumption_digest"]
    assert converged["idempotency_key"] == output["idempotency_key"]


def test_public_authorize_then_consume_derives_target_without_prefill(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity_path, prerequisite_path, *_ = _pinned_authority_declarations(tmp_path)
    qualification_path = tmp_path / "architecture-qualification.json"
    plan_path = tmp_path / "reviewed.formal-plan.json"
    parser = cli.build_parser()
    authorize_args = parser.parse_args(
        [
            "authorize",
            "--identity",
            str(identity_path),
            "--allowed-prerequisites",
            str(prerequisite_path),
            "--architecture-qualification-report",
            str(qualification_path),
            "--output",
            str(plan_path),
            "--expires-at",
            "2099-01-01T00:00:00+00:00",
            "--max-micu-per-attempt",
            "1",
            "--max-cost-microunits-per-attempt",
            "1",
            "--max-wall-time-seconds-per-attempt",
            "100000",
        ]
    )

    assert authorize_args.handler(authorize_args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == ("published_not_consumed")

    consume_args = parser.parse_args(
        [
            "consume-authority",
            "--identity",
            str(identity_path),
            "--allowed-prerequisites",
            str(prerequisite_path),
            "--architecture-qualification-report",
            str(qualification_path),
            "--attempt-authority-plan",
            str(plan_path),
        ]
    )
    expected = attempt_authority_consumption_path(plan_path)

    assert consume_args.attempt_authority_consumption is None
    assert consume_args.handler(consume_args) == 0
    assert expected.is_file()
    assert stat.S_IMODE(expected.stat().st_mode) == 0o400
    assert json.loads(capsys.readouterr().out)["status"] == (
        "consumption_receipt_closed"
    )


@pytest.mark.parametrize(
    "plan_name",
    [
        pytest.param("attempt-authority.json", id="default-json-name"),
        pytest.param("attempt-authority", id="no-suffix"),
        pytest.param("formal.authority.v2.json", id="dotted-nondefault-name"),
    ],
)
def test_consume_authority_derives_full_plan_basename_through_public_parser(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    plan_name: str,
) -> None:
    args = _consume_authority_args(
        tmp_path,
        plan_name=plan_name,
        include_consumption_assertion=False,
    )
    expected = attempt_authority_consumption_path(args.attempt_authority_plan)

    assert args.attempt_authority_consumption is None
    assert args.handler(args) == 0

    assert expected.is_file()
    assert stat.S_IMODE(expected.stat().st_mode) == 0o400
    assert not (tmp_path / "campaign").exists()
    assert json.loads(capsys.readouterr().out)["status"] == (
        "consumption_receipt_closed"
    )


def test_consume_authority_rejects_wrong_compatibility_assertion_without_effect(
    tmp_path: Path,
) -> None:
    args = _consume_authority_args(tmp_path)
    expected = args.attempt_authority_consumption
    wrong = tmp_path / "attempt-authority.consumed.json"
    args.attempt_authority_consumption = wrong

    with pytest.raises(cli.CutoverEvidenceError) as error:
        args.handler(args)

    assert error.value.code == "attempt_authority_consumption_target_mismatch"
    assert not expected.exists()
    assert not wrong.exists()
    assert not (tmp_path / "campaign").exists()


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_consume_authority_rejects_existing_derived_target_without_effect(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    args = _consume_authority_args(
        tmp_path,
        include_consumption_assertion=False,
    )
    target = attempt_authority_consumption_path(args.attempt_authority_plan)
    if existing_kind == "file":
        target.write_bytes(b"preexisting")
    else:
        target.symlink_to(tmp_path / "missing-consumption-target")

    with pytest.raises(cli.CutoverEvidenceError) as error:
        args.handler(args)

    assert error.value.code == "attempt_authority_consumption_unreadable"
    if existing_kind == "file":
        assert target.read_bytes() == b"preexisting"
    else:
        assert target.is_symlink()
    assert not (tmp_path / "campaign").exists()


def test_preflight_config_failure_seals_before_claim_or_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    consume_args = _consume_authority_args(tmp_path)
    assert cli._consume_authority(consume_args) == 0
    capsys.readouterr()
    preflight_args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(consume_args.identity),
            "--allowed-prerequisites",
            str(consume_args.allowed_prerequisites),
            "--architecture-qualification-report",
            str(consume_args.architecture_qualification_report),
            "--attempt-authority-plan",
            str(consume_args.attempt_authority_plan),
            "--slot-ordinal",
            "1",
        ]
    )
    launch_error = AoxCutoverLaunchError(
        "aox_launch_effective_config_schema_invalid",
        "closed preflight failure",
        public_cause={
            "kind": "schema_field",
            "identity": (
                "effective_config.reliability.controlled_operation_owner_policy"
            ),
        },
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "resolve_aox_cutover_launch_profile",
        lambda profile: (object(), tmp_path / "micu-ledger.sqlite3"),
    )
    monkeypatch.setattr(
        cli,
        "prepare_aox_cutover_launch",
        lambda **kwargs: (
            observed.update({"prepare": kwargs}),
            (_ for _ in ()).throw(launch_error),
        )[1],
    )
    monkeypatch.setattr(
        cli,
        "seal_formal_preflight_failure",
        lambda **kwargs: (
            observed.update(kwargs),
            (
                tmp_path / "attempt-authority.json.slot-1.preflight-failure.json",
                "sha256:" + "f" * 64,
            ),
        )[1],
    )
    monkeypatch.setattr(
        cli,
        "claim_aox_attempt_authority_slot",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError(kwargs)),
    )
    monkeypatch.setattr(
        cli,
        "create_blank_world_roots",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError((args, kwargs))),
    )

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._preflight(preflight_args)

    assert error.value is launch_error
    assert observed["slot_ordinal"] == 1
    assert observed["prepare"]["declared_identity"] == observed["identity"]
    assert observed["prepare"]["architecture_qualification_report"] == (
        consume_args.architecture_qualification_report
    )
    assert observed["launch_profile"]["schema_id"] == ("aox_cutover_launch_profile@1")
    assert observed["failure"] == {
        "schema_id": "aox_cutover_launch_failure@4",
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_cause": {
            "kind": "schema_field",
            "identity": (
                "effective_config.reliability.controlled_operation_owner_policy"
            ),
        },
    }
    assert not (tmp_path / "campaign").exists()
    output = json.loads(capsys.readouterr().out)
    assert output["slot_claim_created"] is False
    assert output["campaign_attempt_root_created"] is False
    assert output["scientific_attempt_count"] == 0


def test_preflight_rejects_wrong_consumption_assertion_before_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    consume_args = _consume_authority_args(tmp_path)
    assert cli._consume_authority(consume_args) == 0
    capsys.readouterr()
    wrong = tmp_path / "attempt-authority.consumed.json"
    args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(consume_args.identity),
            "--allowed-prerequisites",
            str(consume_args.allowed_prerequisites),
            "--architecture-qualification-report",
            str(consume_args.architecture_qualification_report),
            "--attempt-authority-plan",
            str(consume_args.attempt_authority_plan),
            "--attempt-authority-consumption",
            str(wrong),
            "--slot-ordinal",
            "1",
        ]
    )

    with pytest.raises(cli.CutoverEvidenceError) as error:
        args.handler(args)

    assert error.value.code == "attempt_authority_consumption_invalid"
    assert not wrong.exists()
    assert not (tmp_path / "campaign").exists()


def test_preflight_revalidates_actual_launch_immediately_before_slot_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    consume_args = _consume_authority_args(tmp_path)
    assert cli._consume_authority(consume_args) == 0
    capsys.readouterr()
    args = cli.build_parser().parse_args(
        [
            "preflight",
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--identity",
            str(consume_args.identity),
            "--allowed-prerequisites",
            str(consume_args.allowed_prerequisites),
            "--architecture-qualification-report",
            str(consume_args.architecture_qualification_report),
            "--attempt-authority-plan",
            str(consume_args.attempt_authority_plan),
            "--attempt-authority-consumption",
            str(consume_args.attempt_authority_consumption),
            "--slot-ordinal",
            "1",
        ]
    )
    calls: list[str] = []

    class Snapshot:
        effective_config = {"schema_id": "aox_blank_world_runtime_config@5"}

        def assert_unchanged(self) -> None:
            calls.append("guard")

    monkeypatch.setattr(
        cli,
        "resolve_aox_cutover_launch_profile",
        lambda profile: (object(), tmp_path / "micu-ledger.sqlite3"),
    )
    monkeypatch.setattr(
        cli,
        "prepare_aox_cutover_launch",
        lambda **kwargs: (calls.append("prepare"), Snapshot())[1],
    )

    def stop_at_claim(**kwargs: object) -> dict[str, object]:
        assert calls == ["prepare", "guard"]
        raise RuntimeError("stop at slot claim")

    monkeypatch.setattr(cli, "claim_aox_attempt_authority_slot", stop_at_claim)

    with pytest.raises(RuntimeError, match="stop at slot claim"):
        cli._preflight(args)

    assert calls == ["prepare", "guard"]
    assert not (tmp_path / "campaign").exists()


def test_pin_uses_policy_free_conductor_and_writes_safe_no_replace_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _pin_args(tmp_path)
    raw_settings = _launch_settings()
    identity = {
        "git_commit": "a" * 40,
        "config_digest": "sha256:" + "b" * 64,
    }
    prerequisites = {
        "credential_slots": {"llm": True, "ncbi": True},
        "ncbi_identity": "sha256:" + "c" * 64,
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: raw_settings),
    )

    def fake_pin(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=_architecture_qualification(),
            effective_settings=raw_settings,
        )

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", fake_pin)

    assert cli._pin(args) == 0

    assert "driver" not in captured
    assert captured["settings"] is raw_settings
    assert captured["ledger_path"] == args.ledger_path
    assert json.loads(args.identity_output.read_text(encoding="utf-8")) == identity
    assert (
        json.loads(args.allowed_prerequisites_output.read_text(encoding="utf-8"))
        == prerequisites
    )
    assert stat.S_IMODE(args.identity_output.stat().st_mode) == 0o600
    assert stat.S_IMODE(args.allowed_prerequisites_output.stat().st_mode) == 0o600
    profile_path = tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["schema_id"] == "aox_cutover_launch_profile@1"
    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600
    commit_path = args.identity_output.parent / cli._PIN_COMMIT_BASENAME
    assert stat.S_IMODE(commit_path.stat().st_mode) == 0o600
    assert cli._load_pinned_declarations(
        args.identity_output,
        args.allowed_prerequisites_output,
    ) == (identity, prerequisites, _architecture_qualification(), profile)
    output = json.loads(capsys.readouterr().out)
    assert output["schema_id"] == "aox_cutover_pin_receipt@3"
    assert output["architecture_qualification"] == _architecture_qualification()
    assert output["status"] == "pinned"
    assert output["git_commit"] == "a" * 40
    assert output["config_digest"] == "sha256:" + "b" * 64
    assert output["declaration_commit_digest"] == cli._canonical_digest(
        json.loads(commit_path.read_text(encoding="utf-8"))
    )
    assert str(tmp_path) not in json.dumps(output, sort_keys=True)


@pytest.mark.parametrize(
    ("action", "runner_method"),
    (
        ("query", "inspect_reserved_execution"),
        ("resume", "resume_reserved_execution"),
        ("reconcile", "recover_reserved_execution_outcome"),
    ),
)
def test_pin_operation_uses_one_exact_reserved_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: str,
    runner_method: str,
) -> None:
    observed: dict[str, object] = {}

    class Runner:
        def __init__(self, config_path: Path) -> None:
            observed["config_path"] = config_path

        def _observe(self, run_id: str, method: str) -> dict[str, object]:
            observed["run_id"] = run_id
            observed["runner_method"] = method
            return {
                "run_id": run_id,
                "status": "reserved",
                "selected_mode": "ssh",
                "phase": "allocated",
                "effect_certainty": "no_effect",
                "retry_eligibility": "same_phase_safe",
                "reconciliation_required": False,
                "retryable": True,
                "runner_attempt_receipt_digest": "sha256:" + "1" * 64,
                "reservation_identity_digest": "sha256:" + "2" * 64,
                "request_digest": "sha256:" + "3" * 64,
                "execution_id": "aox-pin-source",
                "operation_id": "aox-pin-mafft",
                "operation_digest": "sha256:" + "4" * 64,
                "approval_digest": "sha256:" + "5" * 64,
                "route_policy_id": "aox-toolchain-pin",
                "adapter_policy_id": "bio_tools.mafft.hpc:v1",
                "artifacts": {},
            }

        def inspect_reserved_execution(self, run_id: str) -> dict[str, object]:
            return self._observe(run_id, "inspect_reserved_execution")

        def resume_reserved_execution(self, run_id: str) -> dict[str, object]:
            return self._observe(run_id, "resume_reserved_execution")

        def recover_reserved_execution_outcome(self, run_id: str) -> dict[str, object]:
            return self._observe(run_id, "recover_reserved_execution_outcome")

    monkeypatch.setattr(cli, "MCPHpcServer", Runner)
    args = cli.build_parser().parse_args(
        [
            "pin-operation",
            "--action",
            action,
            "--runner-config",
            str(tmp_path / "runner.toml"),
            "--run-id",
            "run_aox_pin_mafft",
        ]
    )

    assert args.handler(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert observed["run_id"] == "run_aox_pin_mafft"
    assert observed["runner_method"] == runner_method
    assert receipt["schema_id"] == "aox_toolchain_pin_public_operation@1"
    assert receipt["effect_certainty"] == "no_effect"
    assert receipt["retry_eligibility"] == "same_phase_safe"
    assert receipt["scientific_attempt_counted"] is False


def test_pin_operation_rejects_removed_recover_alias() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "pin-operation",
                "--action",
                "recover",
                "--runner-config",
                "runner.toml",
                "--run-id",
                "run_aox_pin_mafft",
            ]
        )


def test_config_candidate_outputs_the_exact_persisted_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "candidate.json"
    argv = ["config-candidate", "--output", str(target)]

    assert cli.main(argv) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["schema_id"] == "aox_config_candidate@1"
    assert stdout == json.loads(target.read_text(encoding="utf-8"))

    assert cli.main(argv) == 2
    failure = json.loads(capsys.readouterr().err)
    assert failure["schema_id"] == "aox_cutover_launch_failure@4"
    assert failure["failure_code"] == "aox_config_candidate_output_exists"
    assert failure["failure_occurrence"]["candidate_id"] == stdout["candidate_id"]


def test_config_candidate_preserves_unproven_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_publication(path: Path, payload: object) -> Path:
        del path, payload
        raise cli.AoxConfigContractError(
            "aox_config_candidate_publication_in_doubt",
            "private publication detail",
        )

    monkeypatch.setattr(cli, "publish_aox_config_candidate", reject_publication)

    assert (
        cli.main(
            [
                "config-candidate",
                "--output",
                str(tmp_path / "candidate.json"),
            ]
        )
        == 2
    )
    failure = json.loads(capsys.readouterr().err)
    assert failure["failure_occurrence"]["effect_certainty"] == "unproven"
    assert failure["failure_occurrence"]["retry_eligibility"] == (
        "reconcile_required"
    )
    assert failure["failure_occurrence"]["reconciliation_required"] is True
    assert failure["failure_occurrence"]["terminal_scope"] == (
        "config_candidate_publication_occurrence"
    )
    assert "private publication detail" not in json.dumps(failure)


def test_check_config_uses_public_production_builder_without_runner_or_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _check_config_args(tmp_path)
    raw_settings = SimpleNamespace(
        test=SimpleNamespace(
            live_llm=SimpleNamespace(token_ledger_path=str(args.ledger_path))
        )
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: raw_settings),
    )

    def build_config(settings: object, *, ledger_path: Path) -> SimpleNamespace:
        observed.update(settings=settings, ledger_path=ledger_path)
        return SimpleNamespace(
            payload={"schema_id": "aox_blank_world_runtime_config@5"},
            digest="sha256:" + "a" * 64,
        )

    monkeypatch.setattr(cli, "build_aox_cutover_effective_config", build_config)
    monkeypatch.setattr(
        cli,
        "pin_aox_cutover_launch",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError(kwargs)),
    )

    assert cli._check_config(args) == 0

    assert observed == {
        "settings": raw_settings,
        "ledger_path": args.ledger_path,
    }
    assert not list(tmp_path.iterdir())
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema_id"] == "aox_cutover_config_check@2"
    assert receipt["status"] == "valid"
    assert receipt["effective_config_schema_id"] == ("aox_blank_world_runtime_config@5")
    assert receipt["config_digest"] == "sha256:" + "a" * 64
    assert receipt["candidate_id"].startswith("aox-config-")
    assert receipt["contract_digest"].startswith("sha256:")
    assert receipt["candidate_digest"].startswith("sha256:")


def test_check_config_source_drift_rejects_the_supplied_candidate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _check_config_args(tmp_path)
    candidate = cli.build_aox_config_candidate(
        ledger_path=args.ledger_path,
        environ={"OPENZYME_TEST_ENABLE_LIVE_E2E": "0"},
    )
    candidate_path = tmp_path / "candidate.json"
    cli.publish_aox_config_candidate(candidate_path, candidate)
    args.candidate = candidate_path
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_E2E", "1")

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._check_config(args)

    assert error.value.code == "aox_config_candidate_source_drift"
    assert error.value.public_occurrence["candidate_id"] == (
        candidate["candidate_id"]
    )
    assert error.value.public_occurrence["exact_handle"] == candidate["candidate_id"]

    malformed = tmp_path / "malformed-candidate.json"
    malformed.write_text("not-json\n", encoding="utf-8")
    args.candidate = malformed
    with pytest.raises(AoxCutoverLaunchError) as malformed_error:
        cli._check_config(args)
    assert malformed_error.value.code == "aox_config_candidate_unreadable"
    assert malformed_error.value.public_occurrence == {}


def test_check_config_preserves_candidate_occurrence_and_schema_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    raw_settings = SimpleNamespace(
        test=SimpleNamespace(
            live_llm=SimpleNamespace(token_ledger_path=str(ledger_path))
        )
    )
    private_value = "private-effective-config-value"
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: raw_settings),
    )

    def reject_config(settings: object, *, ledger_path: Path) -> object:
        del settings, ledger_path
        raise AoxCutoverLaunchError(
            "aox_launch_effective_config_schema_invalid",
            "safe schema failure",
            details={"private": private_value},
            public_cause={
                "kind": "schema_field",
                "identity": "effective_config.reliability.owner_policy",
                "missing": ["enabled"],
            },
        )

    monkeypatch.setattr(cli, "build_aox_cutover_effective_config", reject_config)

    assert (
        cli.main(["check-config", "--ledger-path", str(ledger_path)])
        == 2
    )
    failure = json.loads(capsys.readouterr().err)
    assert failure["schema_id"] == "aox_cutover_launch_failure@4"
    assert failure["failure_occurrence"]["kind"] == "config_candidate"
    assert failure["failure_occurrence"]["phase"] == "validation"
    assert failure["failure_occurrence"]["effect_certainty"] == "no_effect"
    assert failure["failure_occurrence"]["terminal_scope"] == (
        "config_candidate_occurrence"
    )
    assert failure["failure_cause"] == {
        "kind": "schema_field",
        "identity": "effective_config.reliability.owner_policy",
        "missing": ["enabled"],
    }
    assert private_value not in json.dumps(failure)


def test_pin_refuses_existing_output_before_runner_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _pin_args(tmp_path)
    args.identity_output.write_text("do-not-replace\n", encoding="utf-8")
    called = False

    def fail_if_called(**kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", fail_if_called)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._pin(args)

    assert error.value.code == "aox_launch_pin_output_exists"
    assert args.identity_output.read_text(encoding="utf-8") == "do-not-replace\n"
    assert called is False


def test_atomic_pin_pair_rolls_back_first_link_if_second_target_races(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_target = tmp_path / "identity.json"
    prerequisites_target = tmp_path / "prerequisites.json"
    profile_target = tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
    real_link = cli.os.link
    links = 0

    def racing_link(*args: object, **kwargs: object) -> None:
        nonlocal links
        links += 1
        if links == 2:
            raise FileExistsError("simulated race")
        real_link(*args, **kwargs)

    monkeypatch.setattr(cli.os, "link", racing_link)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._write_pin_outputs_atomic_no_replace(
            identity_target=identity_target,
            prerequisites_target=prerequisites_target,
            profile_target=profile_target,
            identity={"git_commit": "a" * 40},
            prerequisites={"git_commit": "a" * 40},
            launch_profile=_launch_profile(),
            architecture_qualification=_architecture_qualification(),
        )

    assert error.value.code == "aox_launch_pin_output_exists"
    assert not identity_target.exists()
    assert not prerequisites_target.exists()
    assert not profile_target.exists()
    assert not list(tmp_path.glob(".openzyme-aox-pin-*.tmp"))


def test_pin_staging_failure_cleans_already_staged_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stage = cli._stage_pin_json
    calls = 0

    def fail_second_stage(target: Path, payload: object) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second staging failure")
        return real_stage(target, payload)

    monkeypatch.setattr(cli, "_stage_pin_json", fail_second_stage)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._write_pin_outputs_atomic_no_replace(
            identity_target=tmp_path / "identity.json",
            prerequisites_target=tmp_path / "prerequisites.json",
            profile_target=(tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME),
            identity={"git_commit": "a" * 40},
            prerequisites={"git_commit": "a" * 40},
            launch_profile=_launch_profile(),
            architecture_qualification=_architecture_qualification(),
        )

    assert error.value.code == "aox_launch_pin_output_write_failed"
    assert not list(tmp_path.iterdir())


def test_consume_authority_rejects_uncommitted_or_tampered_pin(
    tmp_path: Path,
) -> None:
    args = _consume_authority_args(tmp_path)
    marker = tmp_path / cli._PIN_COMMIT_BASENAME
    marker.unlink()

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._consume_authority(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert not args.attempt_authority_consumption.exists()

    marker.write_text("{malformed", encoding="utf-8")

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._consume_authority(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert not args.attempt_authority_consumption.exists()

    marker_payload = cli._pin_commit_payload(
        identity_target=args.identity,
        prerequisites_target=args.allowed_prerequisites,
        profile_target=tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME,
        identity={"declared": "identity"},
        prerequisites={"declared": "prerequisites"},
        launch_profile=json.loads(
            (tmp_path / cli.AOX_CUTOVER_LAUNCH_PROFILE_FILENAME).read_text(
                encoding="utf-8"
            )
        ),
        architecture_qualification=_architecture_qualification(),
    )
    marker_payload["identity_digest"] = "sha256:" + "f" * 64
    marker.write_text(json.dumps(marker_payload), encoding="utf-8")

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._consume_authority(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert not args.attempt_authority_consumption.exists()


def test_pin_rejects_outputs_in_different_transaction_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    args = _pin_args(first)
    args.allowed_prerequisites_output = second / "prerequisites.json"
    called = False

    def fail_if_called(**kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", fail_if_called)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._pin(args)

    assert error.value.code == "aox_launch_pin_output_parent_mismatch"
    assert called is False


def test_cli_redacts_chained_launch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_value = "private-runner-locator-and-credential"

    def reject_pin(**kwargs: object) -> object:
        del kwargs
        try:
            raise RuntimeError(private_value)
        except RuntimeError as exc:
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_execution_failed",
                "safe boundary message",
                details={"private": private_value},
                public_cause={
                    "kind": "schema_field",
                    "identity": "effective_config.llm",
                    "private": private_value,
                },
            ) from exc

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", reject_pin)

    result = cli.main(
        [
            "pin",
            "--identity-output",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites-output",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert private_value not in captured.err
    assert json.loads(captured.err) == {
        "schema_id": "aox_cutover_launch_failure@4",
        "status": "failed",
        "failure_code": "aox_launch_toolchain_pin_execution_failed",
    }


def test_cli_projects_only_explicit_public_launch_failure_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_value = "private-config-value"

    def reject_pin(**kwargs: object) -> object:
        del kwargs
        raise AoxCutoverLaunchError(
            "aox_launch_effective_config_schema_invalid",
            "safe boundary message",
            details={
                "identity": "effective_config.llm",
                "private": private_value,
            },
            public_cause={
                "kind": "schema_field",
                "identity": "effective_config.llm",
                "missing": ["enabled"],
                "unexpected": ["legacy_flag"],
            },
        )

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", reject_pin)

    result = cli.main(
        [
            "pin",
            "--identity-output",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites-output",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert private_value not in captured.err
    assert json.loads(captured.err) == {
        "schema_id": "aox_cutover_launch_failure@4",
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_cause": {
            "kind": "schema_field",
            "identity": "effective_config.llm",
            "missing": ["enabled"],
            "unexpected": ["legacy_flag"],
        },
    }


def test_cli_projects_only_closed_runner_occurrence_and_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject_pin(**kwargs: object) -> object:
        del kwargs
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_execution_failed",
            "safe boundary message",
            details={"private": "runner-private-path"},
            public_occurrence={
                "kind": "runner_attestation",
                "tool_id": "bio_tools.mafft",
                "stage": "runner_result",
                "phase": "terminal",
                "effect_certainty": "no_effect",
                "retry_eligibility": "terminal",
                "reconciliation_required": False,
                "terminal_scope": "runner_operation_occurrence",
                "authority_scope": "preparation_only",
                "scientific_attempt_counted": False,
                "runner_run_id": "run_aox_pin_mafft",
                "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
            },
            public_cause={
                "kind": "runner_error",
                "failure_code": "SSH_CONNECTION_TIMEOUT",
            },
        )

    monkeypatch.setattr(cli, "pin_aox_cutover_launch", reject_pin)

    result = cli.main(
        [
            "pin",
            "--identity-output",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites-output",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "runner-private-path" not in captured.err
    assert json.loads(captured.err) == {
        "schema_id": "aox_cutover_launch_failure@4",
        "status": "failed",
        "failure_code": "aox_launch_toolchain_pin_execution_failed",
        "failure_occurrence": {
            "kind": "runner_attestation",
            "tool_id": "bio_tools.mafft",
            "stage": "runner_result",
            "phase": "terminal",
            "effect_certainty": "no_effect",
            "retry_eligibility": "terminal",
            "reconciliation_required": False,
            "terminal_scope": "runner_operation_occurrence",
            "authority_scope": "preparation_only",
            "scientific_attempt_counted": False,
            "runner_run_id": "run_aox_pin_mafft",
            "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
        },
        "failure_cause": {
            "kind": "runner_error",
            "failure_code": "SSH_CONNECTION_TIMEOUT",
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runner_run_id", "../../private"),
        ("runner_attempt_receipt_digest", "sha256:not-a-digest"),
    ],
)
def test_cli_rejects_unclosed_runner_occurrence(
    field: str,
    value: str,
) -> None:
    details: dict[str, object] = {
        "kind": "runner_attestation",
        "tool_id": "bio_tools.mafft",
        "stage": "runner_result",
        "effect_certainty": "no_effect",
        "runner_run_id": "run_aox_pin_mafft",
        "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
        "phase": "terminal",
        "retry_eligibility": "terminal",
        "reconciliation_required": False,
        "terminal_scope": "runner_operation_occurrence",
        "authority_scope": "preparation_only",
        "scientific_attempt_counted": False,
    }
    details[field] = value
    error = AoxCutoverLaunchError(
        "aox_launch_toolchain_pin_execution_failed",
        "safe boundary message",
        public_occurrence=details,
        public_cause={
            "kind": "runner_error",
            "failure_code": "transport_connect_failed",
        },
    )

    payload = cli.aox_cutover_launch_failure_payload(error)
    assert "failure_occurrence" not in payload
    assert payload["failure_cause"]["failure_code"] == "transport_connect_failed"


def test_cli_redacts_unexpected_settings_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_value = "private-malformed-environment-value"

    def reject_settings(cls) -> object:
        del cls
        raise ValueError(private_value)

    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(reject_settings),
    )

    result = cli.main(
        [
            "pin",
            "--identity-output",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites-output",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert private_value not in captured.err
    assert "Traceback" not in captured.err
    assert json.loads(captured.err) == {
        "schema_id": "aox_cutover_cli_failure@1",
        "status": "failed",
        "command": "pin",
        "failure_code": "aox_cutover_cli_unhandled_failure",
    }


def test_cli_redacts_unexpected_offline_verify_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_value = "private-offline-artifact-path"

    def reject_verify(*args, **kwargs) -> object:
        del args, kwargs
        raise ValueError(private_value)

    monkeypatch.setattr(cli, "verify_attempt_bundle", reject_verify)

    result = cli.main(
        [
            "verify",
            "--bundle",
            str(tmp_path / "bundle.json"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert private_value not in captured.err
    assert "Traceback" not in captured.err
    assert json.loads(captured.err) == {
        "schema_id": "aox_cutover_cli_failure@1",
        "status": "failed",
        "command": "verify",
        "failure_code": "aox_cutover_cli_unhandled_failure",
    }


def test_cli_does_not_catch_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*args, **kwargs) -> object:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "verify_attempt_bundle", interrupt)

    with pytest.raises(KeyboardInterrupt):
        cli.main(
            [
                "verify",
                "--bundle",
                str(tmp_path / "bundle.json"),
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )
