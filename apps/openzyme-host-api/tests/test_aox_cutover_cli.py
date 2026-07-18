from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_host_api import aox_cutover_cli as cli
from openzyme_host_api.aox_cutover_launch import AoxCutoverLaunchError
from openzyme_runtime import OpenZymeSettings


def _run_live_args(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    prerequisite_path = tmp_path / "prerequisites.json"
    identity_path.write_text(json.dumps({"declared": "identity"}), encoding="utf-8")
    prerequisite_path.write_text(
        json.dumps({"declared": "prerequisites"}),
        encoding="utf-8",
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
    assert captured["runner"]["settings"] is effective_settings
    assert captured["runner"]["effective_config"] is launch_config
    assert captured["campaign"]["identity"] is launch_identity
    assert captured["campaign"]["allowed_prerequisites"] is launch_prerequisites
    assert captured["campaign"]["launch_guard"] is launch_guard
    output = json.loads(capsys.readouterr().out)
    assert output["decision"]["decision"] == "NO-GO"
