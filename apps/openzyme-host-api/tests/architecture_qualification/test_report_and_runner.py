from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from openzyme_host_api import architecture_qualification_runner as runner_module
from openzyme_host_api import architecture_qualification_report as report_module
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationOutputError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationReportError,
)
from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationRunActiveError,
)
from openzyme_host_api.architecture_qualification import CollectedQualificationScenario
from openzyme_host_api.architecture_qualification import build_architecture_qualification_report
from openzyme_host_api.architecture_qualification import build_test_manifest
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import (
    canonical_json_document_bytes,
)
from openzyme_host_api.architecture_qualification import (
    collect_architecture_source_identity,
)
from openzyme_host_api.architecture_qualification import (
    load_architecture_qualification_report_bytes,
)
from openzyme_host_api.architecture_qualification import load_invariant_registry
from openzyme_host_api.architecture_qualification import (
    publish_architecture_qualification_report,
)
from openzyme_host_api.architecture_qualification import (
    verify_architecture_qualification_report,
)
from openzyme_host_api.architecture_qualification import (
    validate_architecture_qualification_output_target,
)
from openzyme_host_api.architecture_qualification import (
    ValidatedQualificationOutputTarget,
)
from openzyme_host_api.architecture_qualification_runner import non_live_environment
from openzyme_host_api.architecture_qualification_runner import (
    MAINLINE_ENVIRONMENT_DIGEST_ENV,
)
from openzyme_host_api.architecture_qualification_runner import (
    MAINLINE_INVOCATION_ID_ENV,
)
from openzyme_host_api.architecture_qualification_runner import (
    MAINLINE_PLAN_DIGEST_ENV,
)
from openzyme_host_api.architecture_qualification_runner import (
    MAINLINE_SIDECAR_OUTPUT_ENV,
)
from openzyme_host_api.architecture_qualification_runner import (
    MAINLINE_SOURCE_DIGEST_ENV,
)
from openzyme_host_api.architecture_qualification_runner import (
    MainlineQualificationSidecarRequest,
)
from openzyme_host_api.architecture_qualification_runner import (
    mainline_sidecar_request_from_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = REPO_ROOT / "scripts/v3_architecture_qualification.py"
_EMPTY_DIGEST = f"sha256:{hashlib.sha256(b'').hexdigest()}"
_EVIDENCE_DIGEST = f"sha256:{'a' * 64}"


def _manifest():  # type: ignore[no-untyped-def]
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    raw_scenarios = registry.payload["scenarios"]
    assert isinstance(raw_scenarios, list)
    collected = tuple(
        CollectedQualificationScenario(
            scenario_id=str(item["scenario_id"]),
            family=str(item["family"]),
            node_id=str(item["test_selector"]),
            source_file=str(item["source_files"][0]),
            selections=tuple(str(value) for value in item["selections"]),
        )
        for item in raw_scenarios
    )
    return registry, build_test_manifest(
        registry,
        collected_scenarios=collected,
        repo_root=REPO_ROOT,
    )


def _pass_results(registry, *, selection_id: str) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    raw_scenarios = registry.payload["scenarios"]
    assert isinstance(raw_scenarios, list)
    return [
        {
            "duration_milliseconds": 1,
            "effect_ledger_digests": [_EVIDENCE_DIGEST],
            "external_effects_real": False,
            "failure_digests": [],
            "family": item["family"],
            "observation_digests": [_EVIDENCE_DIGEST],
            "observed_p0_trigger_ids": [],
            "pytest_outcome": "pass",
            "scenario_id": item["scenario_id"],
            "test_selector": item["test_selector"],
        }
        for item in raw_scenarios
        if selection_id in item["selections"]
    ]


def _harness_pass() -> dict[str, object]:
    return {
        "duration_milliseconds": 1,
        "exit_code": 0,
        "outcome": "pass",
        "stderr_digest": _EMPTY_DIGEST,
        "stdout_digest": _EMPTY_DIGEST,
    }


def _clean_source(source: dict[str, object]) -> dict[str, object]:
    return {
        **source,
        "tracked_diff_digest": _EMPTY_DIGEST,
        "tracked_dirty_paths": [],
        "untracked_manifest_digest": f"sha256:{hashlib.sha256(canonical_json_bytes([])).hexdigest()}",
        "untracked_sources": [],
        "worktree_clean": True,
    }


def _closed_p0_report_record() -> dict[str, object]:
    return {
        "change_ref": "fix-v3-durable-supervisor-semantic-progress",
        "closure_commit": str(
            collect_architecture_source_identity(repo_root=REPO_ROOT)["commit"]
        ),
        "invariant_id": "supervisor-progress.semantic-progress",
        "p0_id": "p0.supervisor-progress.semantic-progress",
        "status": "closed",
        "trigger_ids": ["unbounded-progress"],
    }


def _build(mode: str, *, source: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    registry, manifest = _manifest()
    actual_source = dict(
        collect_architecture_source_identity(repo_root=REPO_ROOT)
        if source is None
        else source
    )
    report = build_architecture_qualification_report(
        repo_root=REPO_ROOT,
        runner_path=RUNNER_PATH,
        mode=mode,
        command=["qualification", mode],
        registry=registry,
        test_manifest=manifest,
        source_identity=actual_source,
        harness_result=_harness_pass(),
        scenario_results=_pass_results(
            registry,
            selection_id="premerge_subset" if mode == "premerge_subset" else "full",
        ),
    )
    return report


def test_dirty_diagnostic_binds_source_but_is_never_admissible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = dict(collect_architecture_source_identity(repo_root=REPO_ROOT))
    dirty.update(
        {
            "tracked_diff_digest": _EVIDENCE_DIGEST,
            "tracked_dirty_paths": [
                "apps/openzyme-host-api/tests/architecture_qualification/"
                "test_report_and_runner.py"
            ],
            "worktree_clean": False,
        }
    )
    monkeypatch.setattr(
        report_module,
        "collect_source_identity",
        lambda *, repo_root: dirty,
    )

    report = _build("diagnostic", source=dirty)

    assert report.payload["admission_eligible"] is False
    assert "mode_not_admission" in report.payload["rejection_reasons"]
    assert "source_not_clean" in report.payload["rejection_reasons"]
    verification = verify_architecture_qualification_report(
        report,
        repo_root=REPO_ROOT,
        runner_path=RUNNER_PATH,
    )
    assert verification.admission_eligible is False
    assert verification.payload_digest == report.payload_digest


def test_premerge_subset_remains_non_admissible_when_green() -> None:
    report = _build("premerge_subset")

    assert report.payload["selection"]["selection_id"] == "premerge_subset"  # type: ignore[index]
    assert report.payload["admission_eligible"] is False
    assert "selection_not_full" in report.payload["rejection_reasons"]


def test_admission_requires_clean_full_zero_p0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = dict(collect_architecture_source_identity(repo_root=REPO_ROOT))
    clean = _clean_source(dirty)
    monkeypatch.setattr(
        report_module,
        "collect_source_identity",
        lambda *, repo_root: clean,
    )

    report = _build("admission", source=clean)
    assert report.payload["admission_eligible"] is True
    assert report.payload["rejection_reasons"] == []
    assert len(report.payload["p0_records"]) == 2  # type: ignore[arg-type]
    assert all(
        item["status"] == "closed" for item in report.payload["p0_records"]  # type: ignore[union-attr]
    )
    assert all(
        item["status"] == "satisfied" for item in report.payload["invariants"]  # type: ignore[union-attr]
    )
    verification = verify_architecture_qualification_report(
        report,
        repo_root=REPO_ROOT,
        runner_path=RUNNER_PATH,
    )
    assert verification.admission_eligible is True


def test_non_admission_runner_green_allows_closed_but_not_open_p0() -> None:
    report = _build("diagnostic")

    assert runner_module._qualification_evidence_is_green(report.payload)  # noqa: SLF001

    reopened = deepcopy(report.payload)
    reopened["p0_records"][0]["status"] = "open"  # type: ignore[index]
    assert not runner_module._qualification_evidence_is_green(reopened)  # noqa: SLF001


def test_closed_p0_sidecar_is_canonical_ancestor_bound_and_report_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _ = _manifest()
    report_record = _closed_p0_report_record()
    sidecar_record = {
        **report_record,
        "baseline_report_payload_digest": (
            "sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a"
        ),
        "red_scenario_id": "supervisor-progress.semantic-progress-only",
    }
    sidecar = tmp_path / "p0-closures.json"
    sidecar.write_bytes(
        canonical_json_document_bytes(
            {
                "records": [sidecar_record],
                "schema_id": report_module.P0_CLOSURE_SCHEMA_ID,
            }
        )
    )
    monkeypatch.setattr(report_module, "P0_CLOSURE_RELATIVE_PATH", sidecar)

    assert report_module._load_p0_closure_records(  # noqa: SLF001
        repo_root=REPO_ROOT,
        registry=registry,
    ) == [report_record]

    monkeypatch.setattr(
        report_module,
        "_load_p0_closure_records",
        lambda *, repo_root, registry: [report_record],
    )
    report = _build("diagnostic")
    assert report.payload["p0_records"] == [report_record]
    assert "open_p0" not in report.payload["rejection_reasons"]

    monkeypatch.setattr(
        report_module,
        "_load_p0_closure_records",
        lambda *, repo_root, registry: [],
    )
    with pytest.raises(ArchitectureQualificationReportError, match="P0 closure"):
        verify_architecture_qualification_report(
            report,
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
        )


def test_closed_p0_sidecar_rejects_non_ancestor_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _ = _manifest()
    sidecar = tmp_path / "p0-closures.json"
    sidecar.write_bytes(
        canonical_json_document_bytes(
            {
                "records": [
                    {
                        **_closed_p0_report_record(),
                        "baseline_report_payload_digest": _EVIDENCE_DIGEST,
                        "closure_commit": "f" * 40,
                        "red_scenario_id": (
                            "supervisor-progress.semantic-progress-only"
                        ),
                    }
                ],
                "schema_id": report_module.P0_CLOSURE_SCHEMA_ID,
            }
        )
    )
    monkeypatch.setattr(report_module, "P0_CLOSURE_RELATIVE_PATH", sidecar)

    with pytest.raises(ArchitectureQualificationReportError, match="ancestor"):
        report_module._load_p0_closure_records(  # noqa: SLF001
            repo_root=REPO_ROOT,
            registry=registry,
        )


def test_loader_and_verifier_reject_payload_semantic_and_checkout_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _build("diagnostic")
    payload = dict(report.payload)
    payload["admission_eligible"] = True
    stale_digest = {
        "payload": payload,
        "payload_digest": report.payload_digest,
        "schema_id": report.envelope["schema_id"],
    }
    with pytest.raises(ArchitectureQualificationReportError, match="digest drifted"):
        load_architecture_qualification_report_bytes(
            canonical_json_document_bytes(stale_digest)
        )

    forged = {
        **stale_digest,
        "payload_digest": f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}",
    }
    loaded = load_architecture_qualification_report_bytes(
        canonical_json_document_bytes(forged)
    )
    with pytest.raises(
        ArchitectureQualificationReportError,
        match="admission eligibility drifted",
    ):
        verify_architecture_qualification_report(
            loaded,
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
        )

    changed_source = dict(report.payload["source_identity"])
    changed_source["tracked_diff_digest"] = _EVIDENCE_DIGEST
    monkeypatch.setattr(
        report_module,
        "collect_source_identity",
        lambda *, repo_root: changed_source,
    )
    with pytest.raises(ArchitectureQualificationReportError, match="source identity"):
        verify_architecture_qualification_report(
            report,
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "profile",
        "registry",
        "selection",
        "test_manifest",
        "implementation",
        "invariant",
        "p0",
    ),
)
def test_verifier_recomputes_every_bound_semantic_layer(mutation: str) -> None:
    report = _build("diagnostic")
    payload = deepcopy(report.payload)
    if mutation == "profile":
        payload["profile"]["claims"].append("forged_claim")
        payload["profile"]["claims"].sort()
    elif mutation == "registry":
        payload["registry_digest"] = _EVIDENCE_DIGEST
    elif mutation == "selection":
        payload["selection"]["scenario_ids"].pop()
    elif mutation == "test_manifest":
        payload["test_manifest"]["contract_files"][0][
            "content_digest"
        ] = _EVIDENCE_DIGEST
    elif mutation == "implementation":
        payload["implementation"]["runner"]["content_digest"] = _EVIDENCE_DIGEST
    elif mutation == "invariant":
        payload["invariants"][0]["status"] = "violated"
    elif mutation == "p0":
        payload["p0_records"] = [
            {
                "change_ref": None,
                "closure_commit": None,
                "invariant_id": payload["invariants"][0]["invariant_id"],
                "p0_id": f"p0.{payload['invariants'][0]['invariant_id']}",
                "status": "open",
                "trigger_ids": ["false-success"],
            }
        ]
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)
    forged = {
        "payload": payload,
        "payload_digest": f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}",
        "schema_id": report.envelope["schema_id"],
    }
    loaded = load_architecture_qualification_report_bytes(
        canonical_json_document_bytes(forged)
    )

    with pytest.raises(ArchitectureQualificationReportError):
        verify_architecture_qualification_report(
            loaded,
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
        )


def test_report_loader_rejects_noncanonical_and_duplicate_json() -> None:
    report = _build("diagnostic")
    canonical = canonical_json_document_bytes(report.envelope)
    with pytest.raises(ArchitectureQualificationReportError, match="canonical"):
        load_architecture_qualification_report_bytes(canonical[:-1] + b" \n")
    duplicate = canonical.replace(b'{"payload":', b'{"payload":null,"payload":', 1)
    with pytest.raises(ArchitectureQualificationReportError, match="duplicate"):
        load_architecture_qualification_report_bytes(duplicate)


def test_observed_trigger_reopens_closed_p0_without_waiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        report_module,
        "_load_p0_closure_records",
        lambda *, repo_root, registry: [_closed_p0_report_record()],
    )
    registry, manifest = _manifest()
    results = _pass_results(registry, selection_id="full")
    supervisor = next(
        item
        for item in results
        if item["scenario_id"] == "supervisor-progress.semantic-progress-only"
    )
    supervisor["pytest_outcome"] = "fail"
    supervisor["failure_digests"] = [_EVIDENCE_DIGEST]
    supervisor["observed_p0_trigger_ids"] = ["unbounded-progress"]
    source = dict(collect_architecture_source_identity(repo_root=REPO_ROOT))
    report = build_architecture_qualification_report(
        repo_root=REPO_ROOT,
        runner_path=RUNNER_PATH,
        mode="diagnostic",
        command=["qualification", "diagnostic"],
        registry=registry,
        test_manifest=manifest,
        source_identity=source,
        harness_result=_harness_pass(),
        scenario_results=results,
    )

    assert report.payload["p0_records"] == [
        {
            "change_ref": None,
            "closure_commit": None,
            "invariant_id": "supervisor-progress.semantic-progress",
            "p0_id": "p0.supervisor-progress.semantic-progress",
            "status": "open",
            "trigger_ids": ["unbounded-progress"],
        }
    ]


@pytest.mark.parametrize(
    ("pytest_outcome", "expected_status"),
    (
        ("error", "unproven"),
        ("fail", "violated"),
        ("pass", "satisfied"),
        ("skip", "unproven"),
        ("timeout", "unproven"),
        ("xfail", "unproven"),
        ("xpass", "unproven"),
    ),
)
def test_pytest_outcomes_map_fail_closed(
    pytest_outcome: str,
    expected_status: str,
) -> None:
    facts = {
        "duration_milliseconds": 1,
        "effect_ledger_digests": [_EVIDENCE_DIGEST],
        "external_effects_real": False,
        "failure_digests": [],
        "family": "wire-contract",
        "observation_digests": [_EVIDENCE_DIGEST],
        "observed_p0_trigger_ids": [],
        "pytest_outcome": pytest_outcome,
        "scenario_id": "wire-contract.provider-envelope-parity",
        "test_selector": "qualification::scenario",
    }

    status, exceeded = report_module._scenario_status(  # noqa: SLF001
        facts,
        deadline_seconds=1,
    )
    assert status == expected_status
    assert exceeded is False


def test_missing_evidence_and_deadline_exhaustion_stay_unproven() -> None:
    facts = {
        "duration_milliseconds": 1,
        "effect_ledger_digests": [],
        "external_effects_real": False,
        "failure_digests": [],
        "family": "wire-contract",
        "observation_digests": [],
        "observed_p0_trigger_ids": [],
        "pytest_outcome": "pass",
        "scenario_id": "wire-contract.provider-envelope-parity",
        "test_selector": "qualification::scenario",
    }
    assert report_module._scenario_status(  # noqa: SLF001
        facts,
        deadline_seconds=1,
    ) == ("unproven", False)
    facts["duration_milliseconds"] = 1_001
    facts["effect_ledger_digests"] = [_EVIDENCE_DIGEST]
    facts["observation_digests"] = [_EVIDENCE_DIGEST]
    assert report_module._scenario_status(  # noqa: SLF001
        facts,
        deadline_seconds=1,
    ) == ("unproven", True)


def test_report_publication_is_outside_checkout_no_replace_and_no_alias(
    tmp_path: Path,
) -> None:
    report = _build("diagnostic")
    output = tmp_path / "qualification-output"
    path = publish_architecture_qualification_report(
        report,
        output_directory=output,
        repo_root=REPO_ROOT,
    )
    assert path.read_bytes() == canonical_json_document_bytes(report.envelope)
    with pytest.raises(ArchitectureQualificationOutputError, match="already exists"):
        publish_architecture_qualification_report(
            report,
            output_directory=output,
            repo_root=REPO_ROOT,
        )

    with pytest.raises(ArchitectureQualificationOutputError, match="outside"):
        publish_architecture_qualification_report(
            report,
            output_directory=REPO_ROOT / ".qualification-must-not-be-created",
            repo_root=REPO_ROOT,
        )
    assert not (REPO_ROOT / ".qualification-must-not-be-created").exists()

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ArchitectureQualificationOutputError, match="aliases"):
        publish_architecture_qualification_report(
            report,
            output_directory=alias_parent / "output",
            repo_root=REPO_ROOT,
        )

    dangling_output = tmp_path / "dangling-output"
    dangling_output.symlink_to(tmp_path / "missing-output")
    with pytest.raises(ArchitectureQualificationOutputError, match="already exists"):
        publish_architecture_qualification_report(
            report,
            output_directory=dangling_output,
            repo_root=REPO_ROOT,
        )


def test_output_target_is_prevalidated_and_rechecked_for_mid_run_races(
    tmp_path: Path,
) -> None:
    report = _build("diagnostic")
    output = tmp_path / "qualification-output"
    validated = validate_architecture_qualification_output_target(
        output_directory=output,
        repo_root=REPO_ROOT,
    )
    assert validated.target_directory == output

    output.mkdir()
    with pytest.raises(
        ArchitectureQualificationOutputError,
        match="already exists",
    ):
        publish_architecture_qualification_report(
            report,
            output_directory=output,
            repo_root=REPO_ROOT,
        )


def test_output_rejection_performs_no_collection_harness_or_scenario_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def forbidden_run(**_kwargs: object) -> None:
        nonlocal invoked
        invoked = True
        raise AssertionError("qualification work must not start")

    monkeypatch.setattr(
        runner_module,
        "_run_qualification_locked",
        forbidden_run,
    )
    with pytest.raises(
        ArchitectureQualificationOutputError,
        match="parent is unavailable",
    ) as error:
        runner_module.run_qualification(
            repo_root=REPO_ROOT,
            runner_path=RUNNER_PATH,
            mode="diagnostic",
            output_directory=tmp_path / "missing-parent" / "output",
            command=("qualification", "diagnostic"),
        )
    assert error.value.code == "architecture_qualification_output_invalid"
    assert invoked is False


def test_checkout_single_flight_rejects_same_output_different_output_and_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    invoked = False

    def validated_target(
        *,
        output_directory: Path,
        repo_root: Path,
    ) -> ValidatedQualificationOutputTarget:
        assert repo_root.resolve(strict=True) == checkout
        return ValidatedQualificationOutputTarget(
            repo_root=checkout,
            parent=output_directory.parent,
            target_directory=output_directory,
        )

    def forbidden_run(**_kwargs: object) -> None:
        nonlocal invoked
        invoked = True
        raise AssertionError("qualification work must not start")

    monkeypatch.setattr(
        runner_module,
        "validate_architecture_qualification_output_target",
        validated_target,
    )
    monkeypatch.setattr(
        runner_module,
        "_run_qualification_locked",
        forbidden_run,
    )
    monkeypatch.setattr(
        runner_module,
        "_secure_qualification_lock_root",
        lambda: lock_root,
    )
    cases = (
        ("diagnostic", tmp_path / "same-output"),
        ("diagnostic", tmp_path / "different-output"),
        ("premerge_subset", tmp_path / "cross-mode-output"),
    )
    with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
        for mode, output in cases:
            with pytest.raises(ArchitectureQualificationRunActiveError) as error:
                runner_module.run_qualification(
                    repo_root=checkout,
                    runner_path=RUNNER_PATH,
                    mode=mode,
                    output_directory=output,
                    command=("qualification", mode),
                )
            assert error.value.code == "architecture_qualification_run_active"
    assert invoked is False


def test_single_flight_collides_across_checkout_symlink_aliases_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    alias = tmp_path / "checkout-alias"
    alias.symlink_to(checkout, target_is_directory=True)
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    monkeypatch.setattr(
        runner_module,
        "_secure_qualification_lock_root",
        lambda: lock_root,
    )

    with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
        with pytest.raises(ArchitectureQualificationRunActiveError):
            with runner_module._qualification_single_flight(alias):  # noqa: SLF001
                raise AssertionError("aliased checkout must not acquire a second lock")

    with runner_module._qualification_single_flight(alias):  # noqa: SLF001
        pass


def test_single_flight_kernel_lock_releases_after_process_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    monkeypatch.setattr(
        runner_module,
        "_secure_qualification_lock_root",
        lambda: lock_root,
    )
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
            os.write(write_descriptor, b"1")
            os._exit(73)
    os.close(write_descriptor)
    try:
        assert os.read(read_descriptor, 1) == b"1"
    finally:
        os.close(read_descriptor)
    waited, status = os.waitpid(child, 0)
    assert waited == child
    assert os.waitstatus_to_exitcode(status) == 73

    with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
        pass


def test_single_flight_is_kernel_visible_to_a_concurrent_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    monkeypatch.setattr(
        runner_module,
        "_secure_qualification_lock_root",
        lambda: lock_root,
    )
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(ready_read)
        os.close(release_write)
        with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
            os.write(ready_write, b"1")
            os.read(release_read, 1)
        os._exit(0)
    os.close(ready_write)
    os.close(release_read)
    try:
        assert os.read(ready_read, 1) == b"1"
        with pytest.raises(ArchitectureQualificationRunActiveError):
            with runner_module._qualification_single_flight(checkout):  # noqa: SLF001
                raise AssertionError("concurrent checkout lock must be rejected")
    finally:
        os.close(ready_read)
        try:
            os.write(release_write, b"1")
        except BrokenPipeError:
            pass
        os.close(release_write)
        waited, status = os.waitpid(child, 0)
        assert waited == child
        assert os.waitstatus_to_exitcode(status) == 0


def test_non_live_environment_scrubs_credentials_and_live_opt_ins() -> None:
    environment = non_live_environment(
        {
            "OPENAI_API_KEY": "secret",
            "OPENZYME_LIVE_E2E": "1",
            "PATH": "/usr/bin",
            "PYTEST_ADDOPTS": "-m live_e2e",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
        }
    )

    assert environment["PATH"] == "/usr/bin"
    assert environment["OPENZYME_ARCHITECTURE_QUALIFICATION"] == "1"
    assert environment["OPENZYME_LOAD_ENV_FILES"] == "0"
    assert "OPENAI_API_KEY" not in environment
    assert "OPENZYME_LIVE_E2E" not in environment
    assert "PYTEST_ADDOPTS" not in environment
    assert "SSH_AUTH_SOCK" not in environment


def test_mainline_sidecar_request_is_optional_and_all_or_nothing(
    tmp_path: Path,
) -> None:
    assert mainline_sidecar_request_from_environment({}) is None
    with pytest.raises(
        ArchitectureQualificationReportError,
        match="binding is incomplete",
    ):
        mainline_sidecar_request_from_environment(
            {MAINLINE_SIDECAR_OUTPUT_ENV: str(tmp_path / "sidecar.json")}
        )

    source = {
        MAINLINE_SIDECAR_OUTPUT_ENV: str(tmp_path / "sidecar.json"),
        MAINLINE_INVOCATION_ID_ENV: "invocation-1",
        MAINLINE_PLAN_DIGEST_ENV: "sha256:" + "1" * 64,
        MAINLINE_SOURCE_DIGEST_ENV: "sha256:" + "2" * 64,
        MAINLINE_ENVIRONMENT_DIGEST_ENV: "sha256:" + "3" * 64,
    }
    request = mainline_sidecar_request_from_environment(source)
    assert request == MainlineQualificationSidecarRequest(
        output_path=tmp_path / "sidecar.json",
        invocation_id="invocation-1",
        plan_digest="sha256:" + "1" * 64,
        source_identity_digest="sha256:" + "2" * 64,
        environment_digest="sha256:" + "3" * 64,
    )
    scrubbed = non_live_environment({**source, "PATH": "/usr/bin"})
    assert scrubbed["PATH"] == "/usr/bin"
    assert not set(source) & set(scrubbed)


def test_mainline_private_sidecar_is_canonical_bound_and_no_replace(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "qualification-report.json"
    report_path.write_text("{}\n", encoding="utf-8")
    request = MainlineQualificationSidecarRequest(
        output_path=tmp_path / "qualification-sidecar.json",
        invocation_id="invocation-1",
        plan_digest="sha256:" + "1" * 64,
        source_identity_digest="sha256:" + "2" * 64,
        environment_digest="sha256:" + "3" * 64,
    )
    harness = [
        {
            "duration_ns": 2,
            "markers": [],
            "node_id": "tests/test_b.py::test_b",
            "outcome": "pass",
            "phases": [],
        },
        {
            "duration_ns": 1,
            "markers": ["parametrize"],
            "node_id": "tests/test_a.py::test_a",
            "outcome": "pass",
            "phases": [],
        },
    ]
    scenarios = [
        {
            "duration_ns": 3,
            "markers": ["architecture_qualification_scenario"],
            "node_id": "tests/scenarios/test_c.py::test_c",
            "outcome": "pass",
            "phases": [],
        }
    ]
    path = runner_module._publish_mainline_sidecar(  # noqa: SLF001
        repo_root=REPO_ROOT,
        request=request,
        mode="premerge_subset",
        report_path=report_path,
        report_payload_digest="sha256:" + "4" * 64,
        harness_records=harness,
        scenario_records=scenarios,
    )
    content = path.read_bytes()
    payload = json.loads(content)
    assert content == canonical_json_document_bytes(payload)
    self_digest = payload.pop("self_digest")
    assert self_digest == f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"
    assert [item["node_id"] for item in payload["node_results"]] == [
        "tests/scenarios/test_c.py::test_c",
        "tests/test_a.py::test_a",
        "tests/test_b.py::test_b",
    ]
    with pytest.raises(
        ArchitectureQualificationOutputError,
        match="already exists",
    ):
        runner_module._publish_mainline_sidecar(  # noqa: SLF001
            repo_root=REPO_ROOT,
            request=request,
            mode="premerge_subset",
            report_path=report_path,
            report_payload_digest="sha256:" + "4" * 64,
            harness_records=harness,
            scenario_records=scenarios,
        )


def test_mainline_node_hook_records_exact_harness_node(
    tmp_path: Path,
) -> None:
    output = tmp_path / "node-output.json"
    environment = dict(os.environ)
    environment[runner_module._MAINLINE_NODE_OUTPUT_ENV] = str(output)  # noqa: SLF001
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            (
                "apps/openzyme-host-api/tests/architecture_qualification/"
                "test_collection.py::"
                "test_collection_derives_source_and_keeps_stable_id_"
                "separate_from_node_id"
            ),
            "--rootdir=.",
            "-q",
            "-p",
            "no:cacheprovider",
        ),
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8",
        errors="replace",
    )
    records = runner_module._load_mainline_node_records(output)  # noqa: SLF001
    assert len(records) == 1
    assert records[0]["node_id"].endswith(
        "::test_collection_derives_source_and_keeps_stable_id_separate_from_node_id"
    )
    assert records[0]["outcome"] == "pass"
    assert records[0]["duration_ns"] >= 0
