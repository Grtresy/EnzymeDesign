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
