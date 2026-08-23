import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

from openzyme_contracts import ExternalQualificationError


REPO_ROOT = Path(__file__).resolve().parents[3]


def _repository_pytest_gate():
    spec = importlib.util.spec_from_file_location(
        "openzyme_repository_pytest_gate",
        REPO_ROOT / "conftest.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _preparation_script_module():
    script_path = REPO_ROOT / "scripts/execute-external-identity-preparation.py"
    spec = importlib.util.spec_from_file_location(
        "openzyme_external_identity_preparation_script",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    scripts_path = str(REPO_ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def test_live_marker_requires_independent_global_and_marker_opt_in(
    monkeypatch,
) -> None:
    repository_pytest_gate = _repository_pytest_gate()
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_LLM", "true")
    monkeypatch.delenv("OPENZYME_ALLOW_LIVE", raising=False)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "test-only-placeholder")
    assert "independent operator gate" in (
        repository_pytest_gate._live_skip_reason("live_llm") or ""
    )

    monkeypatch.setenv("OPENZYME_ALLOW_LIVE", "true")
    assert repository_pytest_gate._live_skip_reason("live_llm") is None


def test_required_workflow_is_non_live_and_contains_no_secret_context() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/non-live-qualification-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert 'OPENZYME_ALLOW_LIVE: "0"' in workflow
    assert "check-external-qualification-readiness.sh" in workflow
    assert "secrets." not in workflow
    assert "live_llm" not in workflow
    assert "live_tavily" not in workflow
    assert "live_hpc" not in workflow


def test_live_workflow_is_manual_plan_only_and_has_no_automatic_trigger() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/external-qualification-live.yml"
    ).read_text(encoding="utf-8")
    trigger_prefix = workflow.split("permissions:", maxsplit=1)[0]

    assert "workflow_dispatch:" in trigger_prefix
    assert "pull_request:" not in trigger_prefix
    assert "push:" not in trigger_prefix
    assert "schedule:" not in trigger_prefix
    assert "batch-1" in workflow
    assert "batch-2-alphafold" in workflow
    assert "plan-only" in workflow
    assert "build-external-qualification-dry-plan.py" in workflow
    assert "approved-identity-resolution-selections-20260822.json" in workflow
    assert 'OPENZYME_ALLOW_LIVE: "0"' in workflow
    assert "secrets." not in workflow


def test_local_preparation_entry_refuses_non_live_gate_before_state_access(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "must-not-exist"
    environment = dict(os.environ)
    environment["OPENZYME_ALLOW_LIVE"] = "0"
    environment["OPENZYME_QUALIFICATION_STATE_ROOT"] = str(state_root)
    existing = REPO_ROOT / "pyproject.toml"

    completed = subprocess.run(
        (
            sys.executable,
            str(REPO_ROOT / "scripts/execute-external-identity-preparation.py"),
            str(existing),
            str(existing),
            str(existing),
            str(existing),
        ),
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "OPENZYME_ALLOW_LIVE must be exactly 1" in completed.stderr
    assert not state_root.exists()


def test_preparation_entry_checks_revocation_before_credential_resolution() -> None:
    source = (REPO_ROOT / "scripts/execute-external-identity-preparation.py").read_text(
        encoding="utf-8"
    )

    revocation_guard = source.rindex(
        "verify_external_identity_preparation_authorization_not_revoked("
    )
    resolver_construction = source.index(
        "resolver = ProtectedQualificationCredentialBundleResolver("
    )
    credential_preflight = source.index(
        "preflight_enzymedesign_identity_preparation_credentials("
    )
    terminal_restore = source.rindex("terminal_document = _restore_terminal_private_evidence(")

    assert revocation_guard < terminal_restore < resolver_construction < credential_preflight


def test_terminal_private_evidence_restores_exact_packet_without_regeneration(
    tmp_path: Path,
) -> None:
    preparation = _preparation_script_module()
    evidence_root = tmp_path / "private-evidence"
    evidence_root.mkdir(mode=0o700)
    layout = SimpleNamespace(private_evidence_root=evidence_root)
    authorization = SimpleNamespace(
        authorization_id="authorization.preparation.batch-1",
        authorization_digest="sha256:" + "2" * 64,
    )
    source_identity = {"commit": "abc123"}
    source_identity_digest = "sha256:" + "1" * 64
    prepared_snapshot = {"schema_version": "safe_snapshot@1", "observed_at": "then"}
    document = {
        "schema_version": "enzymedesign_post_preparation_operator_packet@1",
        "claim": "prepared_not_qualified",
        "source_identity": source_identity,
        "source_identity_digest": source_identity_digest,
        "preparation_plan_digest": "sha256:" + "3" * 64,
        "preparation_authorization_digest": authorization.authorization_digest,
        "preparation_result_digests": ["sha256:" + "4" * 64],
        "prepared_snapshot": prepared_snapshot,
        "rediscovery": {"summary": {"batch_1_authorizable": True}},
        "batch_1_qualification_dry_plan_digest": "sha256:" + "5" * 64,
        "credential_material_persisted": False,
        "qualified": False,
        "cutover": False,
        "fallback_performed": False,
    }
    document["packet_digest"] = preparation.canonical_sha256_digest(document)
    preparation._write_private_json(
        evidence_root / "prepared-snapshot-authorization.preparation.batch-1.json",
        prepared_snapshot,
    )
    preparation._write_private_json(
        evidence_root
        / "post-preparation-packet-authorization.preparation.batch-1.json",
        document,
    )

    restored = preparation._restore_terminal_private_evidence(
        layout=layout,
        source_identity=source_identity,
        source_identity_digest=source_identity_digest,
        plan_digest="sha256:" + "3" * 64,
        authorization=authorization,
        result_digests=("sha256:" + "4" * 64,),
        expected_result_count=1,
    )

    assert restored == document


def test_preparation_failure_diagnostic_is_private_bounded_evidence(
    tmp_path: Path,
) -> None:
    preparation = _preparation_script_module()
    evidence_root = tmp_path / "private-evidence"
    layout = SimpleNamespace(private_evidence_root=evidence_root)
    error = ExternalQualificationError(
        "qualification_image_build_failed",
        "public-safe build failure",
        diagnostic_id="diagnostic.preparation.image-base",
    )
    error.component = "openzyme.process.podman"
    error.phase = "qualification-image-build"
    error.effect_certainty = "partial_residual_observed"
    error.mutation_applied = True
    error.returncode = 23
    error.bounded_stdout = "bounded stdout"
    error.bounded_stderr = "private apt dependency detail"
    error.stdout_truncated = False
    error.stderr_truncated = False

    diagnostic_id = preparation._record_private_failure_diagnostic(
        layout=layout,
        source_digest="sha256:" + "1" * 64,
        plan_digest="sha256:" + "2" * 64,
        authorization_digest="sha256:" + "3" * 64,
        error=error,
    )

    evidence_files = tuple(evidence_root.iterdir())
    assert diagnostic_id == "diagnostic.preparation.image-base"
    assert stat.S_IMODE(evidence_root.stat().st_mode) == 0o700
    assert len(evidence_files) == 1
    assert stat.S_IMODE(evidence_files[0].stat().st_mode) == 0o600
    payload = json.loads(evidence_files[0].read_text(encoding="utf-8"))
    assert payload["bounded_stderr"] == "private apt dependency detail"
    assert payload["returncode"] == 23
    assert payload["mutation_applied"] is True
    assert payload["fallback_performed"] is False
    assert payload["retry_performed"] is False
