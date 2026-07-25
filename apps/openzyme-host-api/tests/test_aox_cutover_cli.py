from __future__ import annotations

import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from openzyme_host_api import aox_closure_stage_live as closure_live
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
from openzyme_host_api.aox_diagnostic_authority import (
    build_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    diagnostic_authority_consumption_path,
)
from openzyme_host_api.aox_diagnostic_authority import (
    publish_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_runtime import OpenZymeSettings


def _architecture_qualification() -> dict[str, str]:
    return build_architecture_qualification_receipt(
        report_payload_digest="sha256:" + "1" * 64,
        registry_digest="sha256:" + "2" * 64,
        test_manifest_digest="sha256:" + "3" * 64,
        profile_id="local_single_process_file_sqlite@1",
        source_commit="a" * 40,
    )


@pytest.fixture(autouse=True)
def _verified_architecture_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        lambda path: _architecture_qualification(),
    )


def _run_live_args(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    prerequisite_path = tmp_path / "prerequisites.json"
    authority_plan_path = tmp_path / "attempt-authority.json"
    cli._write_pin_outputs_atomic_no_replace(
        identity_target=identity_path,
        prerequisites_target=prerequisite_path,
        identity={"declared": "identity"},
        prerequisites={"declared": "prerequisites"},
        architecture_qualification=_architecture_qualification(),
    )
    authority_plan = build_aox_attempt_authority_plan(
        identity={"declared": "identity"},
        allowed_prerequisites={"declared": "prerequisites"},
        architecture_qualification=_architecture_qualification(),
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=1,
        max_cost_microunits_per_attempt=1,
        max_wall_time_seconds_per_attempt=1,
    )
    publish_aox_attempt_authority_plan(
        authority_plan,
        authority_plan_path,
    )
    return cli.build_parser().parse_args(
        [
            "run-live",
            "--campaign-root",
            str(tmp_path / "campaign"),
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
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
            "--approval-mode",
            "chrome-once",
            "--browser-completion-hold-seconds",
            "0",
        ]
    )


def _run_diagnostic_live_args(tmp_path: Path):
    identity_path = tmp_path / "diagnostic-identity.json"
    prerequisite_path = tmp_path / "diagnostic-prerequisites.json"
    authority_plan_path = tmp_path / "diagnostic-authority.json"
    identity = {"git_commit": "a" * 40}
    prerequisites = {"git_commit": "a" * 40}
    cli._write_pin_outputs_atomic_no_replace(
        identity_target=identity_path,
        prerequisites_target=prerequisite_path,
        identity=identity,
        prerequisites=prerequisites,
        architecture_qualification=_architecture_qualification(),
    )
    authority_plan = build_aox_diagnostic_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=_architecture_qualification(),
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=1,
        max_cost_microunits=1,
        max_wall_time_seconds=1,
    )
    publish_aox_diagnostic_authority_plan(
        authority_plan,
        authority_plan_path,
    )
    return cli.build_parser().parse_args(
        [
            "run-diagnostic-live",
            "--diagnostic-root",
            str(tmp_path / str(authority_plan["root_namespace"])),
            "--identity",
            str(identity_path),
            "--allowed-prerequisites",
            str(prerequisite_path),
            "--architecture-qualification-report",
            str(tmp_path / "architecture-qualification.json"),
            "--diagnostic-authority-plan",
            str(authority_plan_path),
            "--diagnostic-authority-consumption",
            str(diagnostic_authority_consumption_path(authority_plan_path)),
            "--ledger-path",
            str(tmp_path / "diagnostic-ledger.sqlite3"),
            "--approval-mode",
            "chrome-once",
            "--browser-completion-hold-seconds",
            "0",
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
            "--approval-mode",
            "chrome-once",
            "--browser-poll-interval-seconds",
            "0.25",
            "--browser-approval-timeout-seconds",
            "301",
            "--browser-completion-hold-seconds",
            "61",
            "--browser-observation-submission-timeout-seconds",
            "181",
            "--timeout-seconds",
            "7201",
            "--max-drains",
            "121",
            "--max-signals-per-drain",
            "1",
            "--max-steps-per-agent",
            "17",
        ]
    )


def _closure_stage_source_args(tmp_path: Path) -> list[str]:
    return [
        "--source-campaign-root",
        str(tmp_path / "r59-source"),
        "--source-attempt-id",
        "positive-" + "a" * 32,
        "--source-campaign-id",
        "aox_campaign_" + "b" * 24,
        "--source-session-id",
        "sess_formal_positive_" + "a" * 32,
        "--source-execution-task-id",
        "aox_execution_cutover_positive_" + "a" * 32,
        "--source-executor-agent-id",
        "agent:executor:source",
        "--source-selection-id",
        "selection_" + "c" * 24,
        "--source-operation-universe-digest",
        "sha256:" + "d" * 64,
        "--source-authority-plan",
        str(tmp_path / "source-authority.json"),
        "--source-authority-consumption",
        str(tmp_path / "source-authority.consumed.json"),
    ]


def _authorize_closure_stage_args(tmp_path: Path):
    return cli.build_parser().parse_args(
        [
            "authorize-closure-stage-diagnostic",
            "--target-parent",
            str(tmp_path / "targets"),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification.json"),
            "--output",
            str(tmp_path / "closure-stage-authority.json"),
            "--expires-at",
            "2099-01-01T00:00:00+00:00",
            "--max-micu",
            "20000000",
            "--max-cost-microunits",
            "0",
            "--max-wall-time-seconds",
            "10800",
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
            *_closure_stage_source_args(tmp_path),
        ]
    )


def _run_closure_stage_args(tmp_path: Path):
    return cli.build_parser().parse_args(
        [
            "run-closure-stage-diagnostic-live",
            "--diagnostic-root",
            str(tmp_path / ("aox-closure-stage-" + "e" * 24)),
            "--identity",
            str(tmp_path / "identity.json"),
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification.json"),
            "--closure-stage-authority-plan",
            str(tmp_path / "closure-stage-authority.json"),
            "--closure-stage-authority-consumption",
            str(
                tmp_path
                / (
                    "closure-stage-authority.json"
                    ".closure-stage-consumed.json"
                )
            ),
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
            *_closure_stage_source_args(tmp_path),
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
            "--attempt-kind",
            "positive",
            "--allowed-prerequisites",
            str(tmp_path / "prerequisites.json"),
            "--architecture-qualification-report",
            str(tmp_path / "qualification.json"),
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
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError((args, kwargs))
        ),
    )

    with pytest.raises(AoxArchitectureQualificationError):
        cli._preflight(args)

    assert not args.campaign_root.exists()


def test_run_live_rejects_architecture_report_before_pin_or_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _run_live_args(tmp_path)
    monkeypatch.setattr(
        cli,
        "verify_aox_architecture_qualification_report",
        _reject_architecture_qualification,
    )
    monkeypatch.setattr(
        cli,
        "_load_pinned_declarations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError((args, kwargs))
        ),
    )
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError(cls))),
    )

    with pytest.raises(AoxArchitectureQualificationError):
        cli._run_live(args)

    assert not args.campaign_root.exists()


def test_cli_contract_rejects_missing_report_and_bypass_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "pin",
                "--identity-output",
                str(tmp_path / "identity.json"),
                "--allowed-prerequisites-output",
                str(tmp_path / "prerequisites.json"),
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run-live",
                "--campaign-root",
                str(tmp_path / "campaign"),
                "--identity",
                str(tmp_path / "identity.json"),
                "--allowed-prerequisites",
                str(tmp_path / "prerequisites.json"),
                "--architecture-qualification-report",
                str(tmp_path / "qualification.json"),
                "--force",
            ]
        )


def test_run_live_fails_launch_validation_before_campaign_root_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _run_live_args(tmp_path)
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: SimpleNamespace()),
    )

    def reject_launch(**kwargs):
        del kwargs
        raise AoxCutoverLaunchError(
            "aox_launch_worktree_dirty",
            "dirty checkout",
        )

    monkeypatch.setattr(cli, "prepare_aox_cutover_launch", reject_launch)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._run_live(args)

    assert error.value.code == "aox_launch_worktree_dirty"
    assert not args.campaign_root.exists()
    assert args.attempt_authority_consumption.is_file()


def test_run_live_passes_canonical_launch_snapshot_to_runner_and_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _run_live_args(tmp_path)
    raw_settings = SimpleNamespace(name="raw")
    effective_settings = SimpleNamespace(name="effective")
    launch_identity = {"declared": "identity"}
    launch_prerequisites = {"declared": "prerequisites"}
    launch_config = {"schema_id": "aox_blank_world_runtime_config@3"}

    def launch_guard() -> None:
        return None

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        OpenZymeSettings,
        "from_env",
        classmethod(lambda cls: raw_settings),
    )

    def prepare_launch(**kwargs):
        captured["prepare"] = kwargs
        return SimpleNamespace(
            effective_settings=effective_settings,
            effective_config=launch_config,
            identity=launch_identity,
            allowed_prerequisites=launch_prerequisites,
            architecture_qualification=_architecture_qualification(),
            assert_unchanged=launch_guard,
        )

    class FakeRunner:
        def __init__(self, **kwargs) -> None:
            captured["runner"] = kwargs

    class FakeSupervisor:
        def __init__(self, **kwargs) -> None:
            captured["supervisor"] = kwargs

    class FakeCampaign:
        def __init__(self, **kwargs) -> None:
            captured["campaign"] = kwargs

        def run(self):
            return (), {
                "decision": "NO-GO",
                "blockers": [],
                "driver_failure_kind": "attempt_supervision_fatal",
            }

    monkeypatch.setattr(cli, "prepare_aox_cutover_launch", prepare_launch)
    monkeypatch.setattr(cli, "AoxCutoverCampaign", FakeCampaign)
    monkeypatch.setattr(
        cli,
        "safe_micu_ledger_snapshot",
        lambda path: (_ for _ in ()).throw(
            AssertionError(f"fatal supervision must not reread {path}")
        ),
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_live.LiveAoxAttemptRunner",
        FakeRunner,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_attempt_supervision.ProcessIsolatedAttemptRunner",
        FakeSupervisor,
    )

    result = cli._run_live(args)

    assert result == 2
    assert captured["prepare"]["settings"] is raw_settings
    assert captured["prepare"]["driver"].approval_mode == "chrome-once"
    assert captured["prepare"]["driver"].timeout_seconds == 7_200.0
    assert captured["runner"]["settings"] is effective_settings
    assert captured["runner"]["effective_config"] is launch_config
    assert captured["supervisor"]["runner"].__class__ is FakeRunner
    assert captured["supervisor"]["ledger_path"] == args.ledger_path
    assert captured["supervisor"]["timeout_seconds"] == 15_000.0
    assert captured["campaign"]["identity"] is launch_identity
    assert captured["campaign"]["allowed_prerequisites"] is launch_prerequisites
    assert captured["campaign"]["architecture_qualification"] == (
        _architecture_qualification()
    )
    assert captured["campaign"]["launch_guard"] is launch_guard
    assert len(captured["campaign"]["attempt_authority_slots"]) == 3
    assert captured["campaign"]["positive_runner"].__class__ is FakeSupervisor
    assert captured["campaign"]["positive_runner"] is captured["campaign"][
        "fault_runner"
    ]
    assert "_allow_unisolated_non_live_test_runner" not in captured["campaign"]
    output = json.loads(capsys.readouterr().out)
    assert output["decision"]["decision"] == "NO-GO"
    assert output["micu_ledger"] == {
        "status": "not_claimed",
        "reason": "attempt_supervision_fatal",
    }


def test_diagnostic_commands_are_explicit_and_not_formal_mode_flags(
    tmp_path: Path,
) -> None:
    diagnostic = _run_diagnostic_live_args(tmp_path)

    assert diagnostic.command == "run-diagnostic-live"
    assert diagnostic.handler is cli._run_diagnostic_live
    assert not hasattr(diagnostic, "attempt_authority_plan")
    assert diagnostic.diagnostic_authority_plan.name == (
        "diagnostic-authority.json"
    )
    assert diagnostic.diagnostic_root.name.startswith("aox-diagnostic-")

    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run-live",
                "--diagnostic",
                "--campaign-root",
                str(tmp_path / "formal"),
            ]
        )


def test_closure_stage_commands_are_explicit_non_formal_boundaries(
    tmp_path: Path,
) -> None:
    authorize = _authorize_closure_stage_args(tmp_path)
    run = _run_closure_stage_args(tmp_path)

    assert authorize.command == "authorize-closure-stage-diagnostic"
    assert authorize.handler is cli._authorize_closure_stage_diagnostic
    assert run.command == "run-closure-stage-diagnostic-live"
    assert run.handler is cli._run_closure_stage_diagnostic_live
    assert not hasattr(authorize, "attempt_authority_plan")
    assert not hasattr(run, "campaign_root")
    assert not hasattr(run, "promote")
    assert run.max_signals_per_drain == 1
    assert run.max_steps_per_agent == 16

    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run-live",
                "--closure-stage",
                "--campaign-root",
                str(tmp_path / "formal"),
            ]
        )


def test_closure_stage_resource_parity_is_exact() -> None:
    parity = {
        "source": {
            "max_micu": 20_000_000,
            "max_cost_microunits": 0,
            "max_wall_time_seconds": 10_800,
        }
    }

    cli._require_closure_stage_resource_parity(
        parity=parity,
        max_micu=20_000_000,
        max_cost_microunits=0,
        max_wall_time_seconds=10_800,
    )
    with pytest.raises(CutoverEvidenceError) as error:
        cli._require_closure_stage_resource_parity(
            parity=parity,
            max_micu=20_000_001,
            max_cost_microunits=0,
            max_wall_time_seconds=10_800,
        )

    assert getattr(error.value, "code", None) == (
        "closure_stage_resource_parity_mismatch"
    )


def test_closure_stage_browser_receipt_is_plan_bound(
    tmp_path: Path,
) -> None:
    args = _run_closure_stage_args(tmp_path)
    browser_parent = tmp_path / "browser-observations"
    browser_parent.mkdir()
    expected = browser_parent / "closure-stage-observation.json"
    plan = {"browser_observation_receipt": str(expected)}

    args.approval_mode = "chrome-once"
    args.browser_observation_receipt = expected
    browser_target = cli._pin_closure_stage_browser_target(args)
    cli._require_closure_stage_browser_target(
        browser_target=browser_target,
        authority_plan=plan,
    )

    other_parent = tmp_path / "other-browser-observations"
    other_parent.mkdir()
    args.browser_observation_receipt = other_parent / "receipt.json"
    mismatched_target = cli._pin_closure_stage_browser_target(args)
    with pytest.raises(CutoverEvidenceError) as mismatch:
        cli._require_closure_stage_browser_target(
            browser_target=mismatched_target,
            authority_plan=plan,
        )

    assert mismatch.value.code == "closure_stage_browser_target_mismatch"

    args.approval_mode = "auto"
    args.browser_observation_receipt = expected
    with pytest.raises(CutoverEvidenceError) as unexpected:
        cli._pin_closure_stage_browser_target(args)
    assert unexpected.value.code == "closure_stage_browser_target_unexpected"


def test_closure_stage_authorize_only_publishes_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _authorize_closure_stage_args(tmp_path)
    args.target_parent.mkdir()
    args.ledger_path.write_bytes(b"ledger")
    browser_parent = tmp_path / "browser-observations"
    browser_parent.mkdir()
    args.approval_mode = "chrome-once"
    args.browser_observation_receipt = (
        browser_parent / "closure-stage-observation.json"
    )
    launch = SimpleNamespace(
        identity={"git_commit": "a" * 40},
        allowed_prerequisites={"provider_cache_mode": "source_copy_read_only"},
        effective_config={"schema_id": "runtime"},
        assert_unchanged=lambda: None,
    )
    plan = {
        "diagnostic_id": "aox_closure_stage_" + "a" * 24,
        "target_root": str(
            args.target_parent / ("aox-closure-stage-" + "a" * 24)
        ),
        "process_epoch": "closure-stage-process-" + "b" * 32,
        "plan_digest": "sha256:" + "c" * 64,
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "_load_live_declarations",
        lambda parsed: (
            launch.identity,
            launch.allowed_prerequisites,
            _architecture_qualification(),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_closure_stage_source_inventory",
        lambda parsed: {"source": "frozen"},
    )
    monkeypatch.setattr(
        cli,
        "_prepare_live_execution",
        lambda parsed, **kwargs: (
            launch,
            _architecture_qualification(),
            parsed.ledger_path,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_closure_stage_runtime_bindings",
        lambda **kwargs: (
            {"contract": "bound"},
            {"runtime": "bound"},
            {"micu": "bound"},
            {
                "source": {
                    "max_micu": 20_000_000,
                    "max_cost_microunits": 0,
                    "max_wall_time_seconds": 10_800,
                },
                "receipt_digest": "sha256:" + "d" * 64,
            },
        ),
    )
    def build_plan(**kwargs: object) -> dict[str, object]:
        captured["build_kwargs"] = kwargs
        return plan

    monkeypatch.setattr(
        cli,
        "build_aox_closure_stage_authority_plan",
        build_plan,
    )

    def publish(payload: object, path: Path) -> None:
        captured["payload"] = payload
        captured["path"] = path
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "publish_aox_closure_stage_authority_plan",
        publish,
    )
    monkeypatch.setattr(
        cli,
        "consume_aox_closure_stage_authority_plan",
        lambda *positional, **keywords: (_ for _ in ()).throw(
            AssertionError((positional, keywords))
        ),
    )
    monkeypatch.setattr(
        cli,
        "reconstruct_aox_closure_stage",
        lambda *positional, **keywords: (_ for _ in ()).throw(
            AssertionError((positional, keywords))
        ),
    )

    assert cli._authorize_closure_stage_diagnostic(args) == 0

    assert captured["payload"] is plan
    assert captured["path"] == args.output
    assert captured["build_kwargs"]["browser_observation_receipt"] == (
        args.browser_observation_receipt.resolve()
    )
    assert not args.browser_observation_receipt.exists()
    assert args.output.is_file()
    assert not Path(str(plan["target_root"])).exists()
    output = json.loads(capsys.readouterr().out)
    assert output["acceptance_eligible"] is False
    assert output["status"] == "published_not_consumed"


def test_closure_stage_run_fails_clean_launch_before_consumption_or_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _run_closure_stage_args(tmp_path)
    monkeypatch.setattr(
        cli,
        "_load_live_declarations",
        lambda parsed: (
            {"git_commit": "a" * 40},
            {"provider_cache_mode": "source_copy_read_only"},
            _architecture_qualification(),
        ),
    )
    monkeypatch.setattr(
        cli,
        "_closure_stage_source_inventory",
        lambda parsed: {"source": "frozen"},
    )

    def reject_launch(*positional: object, **keywords: object) -> object:
        del positional, keywords
        raise AoxCutoverLaunchError(
            "aox_launch_worktree_dirty",
            "dirty checkout",
        )

    monkeypatch.setattr(cli, "_prepare_live_execution", reject_launch)
    monkeypatch.setattr(
        cli,
        "consume_aox_closure_stage_authority_plan",
        lambda *positional, **keywords: (_ for _ in ()).throw(
            AssertionError((positional, keywords))
        ),
    )

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._run_closure_stage_diagnostic_live(args)

    assert error.value.code == "aox_launch_worktree_dirty"
    assert not args.closure_stage_authority_consumption.exists()
    assert not args.diagnostic_root.exists()


@pytest.mark.parametrize(
    ("decision_status", "expected_exit"),
    (("completed", 0), ("failed", 2)),
)
def test_closure_stage_run_consumes_once_and_returns_only_sealed_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    decision_status: str,
    expected_exit: int,
) -> None:
    args = _run_closure_stage_args(tmp_path)
    args.closure_stage_authority_plan.write_text(
        json.dumps({"process_epoch": "closure-process-" + "a" * 32}),
        encoding="utf-8",
    )
    args.ledger_path.write_bytes(b"ledger")
    source_inventory = {"source": "frozen-r59"}
    qualification = _architecture_qualification()
    launch_checks: list[str] = []
    launch = SimpleNamespace(
        effective_settings=SimpleNamespace(name="effective"),
        effective_config={"schema_id": "runtime"},
        identity={"git_commit": "a" * 40},
        allowed_prerequisites={
            "provider_cache_mode": "source_copy_read_only"
        },
        assert_unchanged=lambda: launch_checks.append("checked"),
    )
    parity = {
        "source": {
            "max_micu": 20_000_000,
            "max_cost_microunits": 0,
            "max_wall_time_seconds": 10_800,
        },
        "receipt_digest": "sha256:" + "b" * 64,
    }
    plan = {
        "diagnostic_id": "aox_closure_stage_" + "c" * 24,
        "target_root": str(args.diagnostic_root.resolve()),
        "browser_observation_receipt": None,
        "resources": {
            "max_micu": 20_000_000,
            "max_cost_microunits": 0,
            "max_wall_time_seconds": 10_800,
        },
        "plan_digest": "sha256:" + "d" * 64,
    }
    calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "_load_live_declarations",
        lambda parsed: (
            launch.identity,
            launch.allowed_prerequisites,
            qualification,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_closure_stage_source_inventory",
        lambda parsed: source_inventory,
    )
    monkeypatch.setattr(
        cli,
        "_prepare_live_execution",
        lambda parsed, **kwargs: (
            launch,
            qualification,
            parsed.ledger_path,
        ),
    )
    monkeypatch.setattr(
        cli,
        "_closure_stage_runtime_bindings",
        lambda **kwargs: (
            {"contracts": "bound"},
            {"runtime": "bound"},
            {"micu": "bound"},
            parity,
        ),
    )
    monkeypatch.setattr(
        cli,
        "load_aox_closure_stage_authority_plan",
        lambda *positional, **keywords: plan,
    )

    def consume(
        authority_plan: object,
        *,
        plan_path: Path,
        path: Path,
    ) -> dict[str, object]:
        assert authority_plan is plan
        assert plan_path == args.closure_stage_authority_plan.resolve()
        assert path == args.closure_stage_authority_consumption.resolve()
        calls.append("consume")
        path.write_text("{}\n", encoding="utf-8")
        return {"consumption": "one-use"}

    monkeypatch.setattr(
        cli,
        "consume_aox_closure_stage_authority_plan",
        consume,
    )

    source_manifest = {
        "manifest_digest": "sha256:" + "e" * 64
    }

    def qualify(**kwargs: object) -> dict[str, object]:
        assert kwargs["source_inventory"] is source_inventory
        calls.append("qualify")
        return source_manifest

    monkeypatch.setattr(
        cli,
        "qualify_aox_closure_stage_source",
        qualify,
    )

    def verify_source(manifest: object) -> object:
        assert manifest is source_manifest
        calls.append("verify-source")
        return manifest

    monkeypatch.setattr(
        cli,
        "independently_verify_aox_closure_stage_source_manifest",
        verify_source,
    )

    def reconstruct(**kwargs: object) -> SimpleNamespace:
        assert kwargs["plan"] is plan
        calls.append("reconstruct")
        evidence_root = args.diagnostic_root / "evidence"
        evidence_root.mkdir(parents=True)
        return SimpleNamespace(
            roots=SimpleNamespace(evidence_root=evidence_root),
            receipt={"receipt_digest": "sha256:" + "f" * 64},
        )

    monkeypatch.setattr(
        cli,
        "reconstruct_aox_closure_stage",
        reconstruct,
    )
    monkeypatch.setattr(
        cli,
        "independently_verify_aox_closure_stage_reconstruction",
        lambda *positional, **keywords: calls.append(
            "verify-reconstruction"
        ),
    )

    def seal(_payload: object, path: Path, **_kwargs: object) -> None:
        calls.append(f"seal:{path.name}")
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "seal_aox_closure_stage_source_manifest",
        seal,
    )
    monkeypatch.setattr(
        cli,
        "seal_aox_closure_stage_reconstruction_receipt",
        seal,
    )
    monkeypatch.setattr(
        closure_live,
        "seal_aox_closure_stage_runtime_parity",
        seal,
    )
    runner = object()
    monkeypatch.setattr(
        cli,
        "_build_supervised_closure_stage_runner",
        lambda *positional, **keywords: (
            calls.append("build-runner") or runner
        ),
    )

    class FakeDiagnostic:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["runner"] is runner
            calls.append("construct-diagnostic")

        def run(self) -> dict[str, object]:
            calls.append("run-once")
            return {
                "status": decision_status,
                "acceptance_eligible": False,
                "formal_adoption": False,
            }

    monkeypatch.setattr(
        closure_live,
        "AoxClosureStageDiagnosticRun",
        FakeDiagnostic,
    )
    monkeypatch.setattr(
        cli,
        "safe_micu_ledger_snapshot",
        lambda _path: {"status": "settled"},
    )

    assert cli._run_closure_stage_diagnostic_live(args) == expected_exit

    assert calls.count("consume") == 1
    assert calls.count("run-once") == 1
    assert calls.count("verify-source") == 2
    assert calls.index("consume") < calls.index("qualify")
    assert calls.index("qualify") < calls.index("reconstruct")
    assert calls.index("reconstruct") < calls.index("build-runner")
    assert calls.index("build-runner") < calls.index("run-once")
    assert len(launch_checks) == 2
    assert args.closure_stage_authority_consumption.is_file()
    assert args.diagnostic_root.is_dir()
    output = json.loads(capsys.readouterr().out)
    assert output["decision"]["acceptance_eligible"] is False
    assert output["decision"]["formal_adoption"] is False
    assert "GO" not in output["decision"]


def test_run_diagnostic_live_consumes_only_diagnostic_plan_before_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _run_diagnostic_live_args(tmp_path)
    launch = SimpleNamespace(
        effective_settings=SimpleNamespace(name="effective"),
        effective_config={"schema_id": "aox_blank_world_runtime_config@3"},
        identity={"git_commit": "a" * 40},
        allowed_prerequisites={"git_commit": "a" * 40},
        architecture_qualification=_architecture_qualification(),
        assert_unchanged=lambda: None,
    )
    captured: dict[str, object] = {}
    fake_runner = object()

    monkeypatch.setattr(
        cli,
        "_prepare_live_execution",
        lambda parsed, **kwargs: (
            launch,
            _architecture_qualification(),
            parsed.ledger_path,
        ),
    )

    def build_runner(parsed, **kwargs):
        captured["runner_args"] = parsed
        captured["runner_kwargs"] = kwargs
        return fake_runner

    class FakeDiagnosticRun:
        def __init__(self, **kwargs: object) -> None:
            captured["diagnostic"] = kwargs

        def run(self) -> dict[str, object]:
            return {
                "schema_id": "aox_blank_world_diagnostic_decision@1",
                "status": "completed_product_path",
                "acceptance_eligible": False,
            }

    monkeypatch.setattr(cli, "_build_supervised_live_runner", build_runner)
    monkeypatch.setattr(cli, "AoxDiagnosticRun", FakeDiagnosticRun)
    monkeypatch.setattr(
        cli,
        "safe_micu_ledger_snapshot",
        lambda path: {"ledger": path.name},
    )

    result = cli._run_diagnostic_live(args)

    assert result == 0
    assert captured["runner_kwargs"]["run_class"] is (
        AoxLiveRunClass.DIAGNOSTIC
    )
    diagnostic = captured["diagnostic"]
    assert diagnostic["runner"] is fake_runner
    assert diagnostic["diagnostic_root"] == args.diagnostic_root
    assert diagnostic["authority_plan"]["run_class"] == (
        AoxLiveRunClass.DIAGNOSTIC.value
    )
    assert diagnostic["authority_consumption"]["run_class"] == (
        AoxLiveRunClass.DIAGNOSTIC.value
    )
    assert args.diagnostic_authority_consumption.is_file()
    assert not args.diagnostic_root.exists()
    output = json.loads(capsys.readouterr().out)
    assert output["decision"]["acceptance_eligible"] is False


def test_pin_uses_same_driver_bounds_and_writes_safe_no_replace_json(
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

    driver = captured["driver"]
    assert driver.approval_mode == "chrome-once"
    assert driver.browser_poll_interval_seconds == 0.25
    assert driver.browser_approval_timeout_seconds == 301.0
    assert driver.browser_completion_hold_seconds == 61.0
    assert driver.browser_observation_submission_timeout_seconds == 181.0
    assert driver.timeout_seconds == 7201.0
    assert driver.max_drains == 121
    assert driver.max_signals_per_drain == 1
    assert driver.max_steps_per_agent == 17
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


def test_run_live_rejects_uncommitted_or_tampered_pin_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _run_live_args(tmp_path)
    marker = tmp_path / cli._PIN_COMMIT_BASENAME
    marker.unlink()
    called = False

    def fail_if_called(**kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(cli, "prepare_aox_cutover_launch", fail_if_called)

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._run_live(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert called is False

    marker.write_text("{malformed", encoding="utf-8")

    with pytest.raises(AoxCutoverLaunchError) as error:
        cli._run_live(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert called is False

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
        cli._run_live(args)

    assert error.value.code == "aox_launch_pin_commit_invalid"
    assert called is False


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
        "schema_id": "aox_cutover_launch_failure@1",
        "status": "failed",
        "failure_code": "aox_launch_toolchain_pin_execution_failed",
    }


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
