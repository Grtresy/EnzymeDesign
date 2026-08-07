from __future__ import annotations

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
from openzyme_runtime import OpenZymeSettings


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


@pytest.fixture(autouse=True)
def _verified_architecture_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        lambda path: _architecture_qualification(),
    )


def _consume_authority_args(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    prerequisite_path = tmp_path / "prerequisites.json"
    authority_plan_path = tmp_path / "attempt-authority.json"
    identity = {"declared": "identity"}
    prerequisites = {"declared": "prerequisites"}
    cli._write_pin_outputs_atomic_no_replace(
        identity_target=identity_path,
        prerequisites_target=prerequisite_path,
        identity=identity,
        prerequisites=prerequisites,
        architecture_qualification=_architecture_qualification(),
    )
    authority_plan = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=_architecture_qualification(),
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=1,
        max_cost_microunits_per_attempt=1,
        max_wall_time_seconds_per_attempt=1,
    )
    publish_aox_attempt_authority_plan(authority_plan, authority_plan_path)
    return cli.build_parser().parse_args(
        [
            "consume-authority",
            "--identity",
            str(identity_path),
            "--allowed-prerequisites",
            str(prerequisite_path),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
            "--attempt-authority-plan",
            str(authority_plan_path),
            "--attempt-authority-consumption",
            str(attempt_authority_consumption_path(authority_plan_path)),
        ]
    )


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


def test_public_host_owns_receipt_response_and_formal_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "aox-attempt-preflight.json"
    response = tmp_path / "public-response-final-workspace.json"
    captured: dict[str, object] = {}
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
    monkeypatch.setattr(cli, "public_response_path", lambda *args: response)
    monkeypatch.setattr(
        cli,
        "run_host_cli",
        lambda argv: captured.update(argv=argv) or 0,
    )
    args = SimpleNamespace(
        preflight_receipt=preflight,
        response_name="final-workspace",
        host_cli_args=["--", "sessions", "show"],
    )

    assert cli._public_host(args) == 0
    assert captured["argv"] == [
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
        "sessions",
        "show",
    ]


def test_public_host_rejects_evidence_and_identity_overrides(tmp_path: Path) -> None:
    args = SimpleNamespace(
        preflight_receipt=tmp_path / "aox-attempt-preflight.json",
        response_name="bad",
        host_cli_args=["--", "--receipt-chain", str(tmp_path / "other"), "sessions", "show"],
    )

    with pytest.raises(cli.CutoverEvidenceError) as error:
        cli._public_host(args)

    assert error.value.code == "public_conductor_command_boundary_invalid"


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
    assert outputs[1]["failure_code"] == (
        "public_conductor_response_set_incomplete"
    )


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
    assert output["status"] == "consumed_without_execution"
    assert output["schema_id"] == "aox_attempt_authority_consume_receipt@1"


def test_pin_uses_policy_free_conductor_and_writes_safe_no_replace_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _pin_args(tmp_path)
    raw_settings = SimpleNamespace(name="raw")
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
    commit_path = args.identity_output.parent / cli._PIN_COMMIT_BASENAME
    assert stat.S_IMODE(commit_path.stat().st_mode) == 0o600
    assert cli._load_pinned_declarations(
        args.identity_output,
        args.allowed_prerequisites_output,
    ) == (identity, prerequisites, _architecture_qualification())
    output = json.loads(capsys.readouterr().out)
    assert output["schema_id"] == "aox_cutover_pin_receipt@2"
    assert output["architecture_qualification"] == _architecture_qualification()
    assert output["status"] == "pinned"
    assert output["git_commit"] == "a" * 40
    assert output["config_digest"] == "sha256:" + "b" * 64
    assert output["declaration_commit_digest"] == cli._canonical_digest(
        json.loads(commit_path.read_text(encoding="utf-8"))
    )
    assert str(tmp_path) not in json.dumps(output, sort_keys=True)


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
    assert json.loads(capsys.readouterr().out) == {
        "schema_id": "aox_cutover_config_check@1",
        "status": "valid",
        "effective_config_schema_id": "aox_blank_world_runtime_config@5",
        "config_digest": "sha256:" + "a" * 64,
    }


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
            identity={"git_commit": "a" * 40},
            prerequisites={"git_commit": "a" * 40},
            architecture_qualification=_architecture_qualification(),
        )

    assert error.value.code == "aox_launch_pin_output_exists"
    assert not identity_target.exists()
    assert not prerequisites_target.exists()
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
            identity={"git_commit": "a" * 40},
            prerequisites={"git_commit": "a" * 40},
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
        identity={"declared": "identity"},
        prerequisites={"declared": "prerequisites"},
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
                public_details={
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
        "schema_id": "aox_cutover_launch_failure@3",
        "status": "failed",
        "failure_code": "aox_launch_toolchain_pin_execution_failed",
    }


def test_cli_projects_only_explicit_public_launch_failure_details(
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
            public_details={
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
        "schema_id": "aox_cutover_launch_failure@3",
        "status": "failed",
        "failure_code": "aox_launch_effective_config_schema_invalid",
        "failure_details": {
            "kind": "schema_field",
            "identity": "effective_config.llm",
            "missing": ["enabled"],
            "unexpected": ["legacy_flag"],
        },
    }


def test_cli_projects_only_closed_runner_attestation_details(
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
            public_details={
                "kind": "runner_attestation",
                "tool_id": "bio_tools.mafft",
                "stage": "runner_result",
                "effect_certainty": "no_effect",
                "runner_run_id": "run_aox_pin_mafft",
                "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
                "runner_error_code": "SSH_CONNECTION_TIMEOUT",
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
        "schema_id": "aox_cutover_launch_failure@3",
        "status": "failed",
        "failure_code": "aox_launch_toolchain_pin_execution_failed",
        "failure_details": {
            "kind": "runner_attestation",
            "tool_id": "bio_tools.mafft",
            "stage": "runner_result",
            "effect_certainty": "no_effect",
            "runner_run_id": "run_aox_pin_mafft",
            "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
            "runner_error_code": "SSH_CONNECTION_TIMEOUT",
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runner_error_code", "Private_Path"),
        ("runner_run_id", "../../private"),
        ("runner_attempt_receipt_digest", "sha256:not-a-digest"),
    ],
)
def test_cli_rejects_unclosed_runner_attestation_details(
    field: str,
    value: str,
) -> None:
    details: dict[str, object] = {
        "kind": "runner_attestation",
        "tool_id": "bio_tools.mafft",
        "stage": "runner_result",
        "effect_certainty": "no_effect",
        "runner_error_code": "transport_connect_failed",
        "runner_run_id": "run_aox_pin_mafft",
        "runner_attempt_receipt_digest": "sha256:" + "b" * 64,
    }
    details[field] = value
    error = AoxCutoverLaunchError(
        "aox_launch_toolchain_pin_execution_failed",
        "safe boundary message",
        public_details=details,
    )

    assert cli._public_launch_failure_details(error) is None


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
