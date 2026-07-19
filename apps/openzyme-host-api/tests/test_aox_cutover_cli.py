from __future__ import annotations

import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from openzyme_host_api import aox_cutover_cli as cli
from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_runtime import OpenZymeSettings


def _run_live_args(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    prerequisite_path = tmp_path / "prerequisites.json"
    cli._write_pin_outputs_atomic_no_replace(
        identity_target=identity_path,
        prerequisites_target=prerequisite_path,
        identity={"declared": "identity"},
        prerequisites={"declared": "prerequisites"},
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
            "--ledger-path",
            str(tmp_path / "ledger.sqlite3"),
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
            "11",
            "--max-steps-per-agent",
            "17",
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


def test_run_live_passes_canonical_launch_snapshot_to_runner_and_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _run_live_args(tmp_path)
    raw_settings = SimpleNamespace(name="raw")
    effective_settings = SimpleNamespace(name="effective")
    launch_identity = {"git_commit": "a" * 40}
    launch_prerequisites = {"git_commit": "a" * 40}
    launch_config = {"schema_id": "aox_blank_world_runtime_config@1"}

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
            assert_unchanged=launch_guard,
        )

    class FakeRunner:
        def __init__(self, **kwargs) -> None:
            captured["runner"] = kwargs

    class FakeCampaign:
        def __init__(self, **kwargs) -> None:
            captured["campaign"] = kwargs

        def run(self):
            return (), {"decision": "NO-GO", "blockers": []}

    monkeypatch.setattr(cli, "prepare_aox_cutover_launch", prepare_launch)
    monkeypatch.setattr(cli, "AoxCutoverCampaign", FakeCampaign)
    monkeypatch.setattr(
        cli, "safe_micu_ledger_snapshot", lambda path: {"path": str(path)}
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_cutover_live.LiveAoxAttemptRunner",
        FakeRunner,
    )

    result = cli._run_live(args)

    assert result == 2
    assert captured["prepare"]["settings"] is raw_settings
    assert captured["prepare"]["driver"].approval_mode == "chrome-once"
    assert captured["prepare"]["driver"].timeout_seconds == 7_200.0
    assert captured["runner"]["settings"] is effective_settings
    assert captured["runner"]["effective_config"] is launch_config
    assert captured["campaign"]["identity"] is launch_identity
    assert captured["campaign"]["allowed_prerequisites"] is launch_prerequisites
    assert captured["campaign"]["launch_guard"] is launch_guard
    output = json.loads(capsys.readouterr().out)
    assert output["decision"]["decision"] == "NO-GO"


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
    assert driver.max_signals_per_drain == 11
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
    ) == (identity, prerequisites)
    output = json.loads(capsys.readouterr().out)
    assert output["schema_id"] == "aox_cutover_pin_receipt@1"
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
