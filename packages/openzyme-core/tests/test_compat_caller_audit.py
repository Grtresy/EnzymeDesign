from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit-v3-compat-callers.py"


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "openzyme_compat_caller_audit",
        AUDIT_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_compatibility_decisions_are_evidence_backed() -> None:
    audit = _load_audit_module()

    report = audit.build_report(REPOSITORY_ROOT)

    assert report["scan_errors"] == []
    assert report["violations"] == []
    records = {record["symbol"]: record for record in report["seams"]}
    assert records["openzyme_engines.PodmanPipelineSandboxRunner"]["decision"] == "KEEP"
    assert records["openzyme_engines.PodmanPipelineSandboxRunner"][
        "production_caller_count"
    ] > 0
    assert records["openzyme_engines:execution.pipeline.start"]["decision"] == "DEPRECATE"
    assert records["openzyme_runtime.RepoBackedHpcCatalogProvider"]["decision"] == (
        "RETIRE-BLOCKED"
    )
    assert records["openzyme_runtime.RepoBackedHpcCatalogProvider"][
        "external_status"
    ] == "unknown"
    assert records["openzyme_execution.ExecutionOutcome.job_id"]["decision"] == (
        "RETIRE-BLOCKED"
    )
    assert records["runner.raw_lifecycle_arguments"]["decision"] == "RETIRED"
    assert records["runner.raw_lifecycle_arguments"]["production_caller_count"] == 0
    assert records["host_api.v1_v2_product_routes"]["decision"] == "RETIRED"
    assert records["legacy_v1.active_import_or_workspace_member"]["decision"] == (
        "RETIRED"
    )


def test_retired_seams_fail_when_a_production_caller_reappears(tmp_path: Path) -> None:
    audit = _load_audit_module()
    app_path = tmp_path / "apps" / "example" / "src" / "example" / "app.py"
    app_path.parent.mkdir(parents=True)
    app_path.write_text(
        "def reintroduce(app, adapter):\n"
        "    app.get('/v1/legacy')\n"
        "    adapter.cancel_execution(job_id='job-raw')\n",
        encoding="utf-8",
    )
    web_path = tmp_path / "apps" / "web" / "src" / "legacy-client.ts"
    web_path.parent.mkdir(parents=True)
    web_path.write_text(
        "fetch('/v2/sessions');\n"
        "runner.call('job.status', {job_id: 'raw-job'});\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.uv.workspace]\n"
        "members = ['legacy/v1']\n",
        encoding="utf-8",
    )

    report = audit.build_report(tmp_path)

    retired_violations = {
        item["symbol"]
        for item in report["violations"]
        if item["reason"] == "retired seam has an in-repository production caller"
    }
    assert retired_violations == {
        "runner.raw_lifecycle_arguments",
        "host_api.v1_v2_product_routes",
        "legacy_v1.active_import_or_workspace_member",
    }
