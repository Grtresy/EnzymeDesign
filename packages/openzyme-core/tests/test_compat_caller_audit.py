from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit-v3-compat-callers.py"
LEGACY_FIXTURE_REPORT_SHA256 = (
    "9ffb7b619be885645e99e3af54c8057f96ac88f06b691a6a982c99cac185232a"
)
LEGACY_RETIRED_FIXTURE_REPORT_SHA256 = (
    "63ae093d116583c8d83a0c6d84ddf76b46e8e19058cc76dbb5df8aee6a7ebc08"
)


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


def _write_text(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _materialize_complete_fixture(
    root: Path,
    audit: ModuleType,
    *,
    retired_production_callers: bool = False,
) -> None:
    for seam in audit.SEAMS:
        path = root / seam.path
        if path.suffix:
            if not path.exists():
                _write_text(path)
        else:
            path.mkdir(parents=True, exist_ok=True)

    workspace_members = (
        '["legacy/v1"]' if retired_production_callers else '["apps/example"]'
    )
    _write_text(
        root / "pyproject.toml",
        f"[tool.uv.workspace]\nmembers = {workspace_members}\n",
    )
    _write_text(
        root / "apps/openzyme-host-cli/pyproject.toml",
        "[project]\n"
        'name = "fixture-cli"\n'
        'version = "0.0.0"\n'
        "[project.scripts]\n"
        'openzyme = "fixture:main"\n'
        'enzyme = "fixture:main"\n',
    )
    _write_text(
        root / "apps/mcp-hpc-runner/pyproject.toml",
        "[project]\n"
        'name = "fixture-runner"\n'
        'version = "0.0.0"\n'
        "[project.scripts]\n"
        'mcp-hpc-runner = "fixture:main"\n',
    )
    _write_text(
        root / "apps/example/src/example/consumer.py",
        "import openzyme_runtime as runtime\n"
        "from openzyme_engines import PodmanPipelineSandboxRunner\n"
        "from openzyme_execution import HpcRunnerExecutionAdapter\n"
        "from openzyme_runtime import ExecutionAdapter, RuntimeFoundation\n"
        "from openzyme_tools import DefaultHpcExecutionRegistry\n"
        "from openzyme_tools import RepoBackedHpcCatalogProvider\n"
        "\n"
        "def inspect(tool):\n"
        "    runtime.DesignTool\n"
        "    tool.to_openai_tool()\n"
        '    return "execution.pipeline.start"\n',
    )
    _write_text(
        root
        / "packages/openzyme-execution/src/openzyme_execution/outcome_consumer.py",
        "def inspect(outcome, outcome_type):\n"
        "    observed = outcome.job_id\n"
        "    return outcome_type(job_id=observed, remote_run_dir='remote')\n",
    )
    _write_text(
        root / "docs/compatibility.rst",
        "PodmanPipelineSandboxRunner\n"
        "openzyme_runtime.ToolSpec.to_openai_tool\n"
        "openzyme_execution.ExecutionOutcome.job_id\n"
        "execution.pipeline.start\n"
        "legacy/v1\n",
    )
    _write_text(
        root / "apps/example/src/pipeline.ts",
        'export const pipelineTool = "execution.pipeline.start";\n',
    )
    _write_text(
        root / "apps/example/tests/test_legacy_route.py",
        "def test_route(client):\n"
        '    client.get("/v1/test-only")\n',
    )
    _write_text(
        root / "legacy/v1/client.ts",
        'export const archivedRoute = "/v2/archived";\n',
    )
    _write_text(
        root / "scripts/legacy-route.ts",
        'export const auxiliaryRoute = "/v1/auxiliary";\n',
    )
    if retired_production_callers:
        _write_text(
            root / "apps/example/src/example/retired.py",
            "def reintroduce(app, adapter):\n"
            '    app.get("/v1/legacy")\n'
            "    adapter.cancel_execution(job_id='job-raw')\n",
        )


def _canonical_report_bytes(report: dict[str, object]) -> bytes:
    return (
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()


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


def test_repository_index_walks_reads_and_parses_each_candidate_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _load_audit_module()
    _materialize_complete_fixture(tmp_path, audit)
    reader_counts: Counter[str] = Counter()
    python_parse_counts: Counter[str] = Counter()
    toml_parse_counts: Counter[str] = Counter()
    walk_count = 0
    original_walk = audit.os.walk
    original_python_parse = audit.ast.parse
    original_toml_parse = audit.tomllib.loads

    def counted_walk(*args: object, **kwargs: object) -> object:
        nonlocal walk_count
        walk_count += 1
        return original_walk(*args, **kwargs)

    def counted_reader(path: Path) -> str:
        relative = path.relative_to(tmp_path).as_posix()
        reader_counts[relative] += 1
        return path.read_text(encoding="utf-8")

    def counted_python_parse(
        source: str,
        filename: str = "<unknown>",
        mode: str = "exec",
        **kwargs: object,
    ) -> object:
        python_parse_counts[filename] += 1
        return original_python_parse(source, filename, mode, **kwargs)

    def counted_toml_parse(source: str) -> object:
        digest = hashlib.sha256(source.encode()).hexdigest()
        toml_parse_counts[digest] += 1
        return original_toml_parse(source)

    monkeypatch.setattr(audit.os, "walk", counted_walk)
    monkeypatch.setattr(audit.ast, "parse", counted_python_parse)
    monkeypatch.setattr(audit.tomllib, "loads", counted_toml_parse)

    index = audit._build_repository_index(tmp_path, read_text=counted_reader)

    assert walk_count == 1
    assert tuple(reader_counts) == index.inventory
    assert set(reader_counts.values()) == {1}
    assert set(index.read_counts.values()) == {1}
    assert set(python_parse_counts.values()) == {1}
    assert set(toml_parse_counts.values()) == {1}
    assert len(python_parse_counts) == sum(
        path.endswith(".py") for path in index.inventory
    )
    assert len(toml_parse_counts) == sum(
        path.endswith(".toml") for path in index.inventory
    )
    with pytest.raises(TypeError):
        index.read_counts["new.py"] = 2
    with pytest.raises(TypeError):
        index.toml_payloads["pyproject.toml"]["tool"] = {}
    with pytest.raises(FrozenInstanceError):
        index.root = tmp_path / "other"


def test_fixture_report_matches_legacy_canonical_bytes_and_is_repeatable(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    _materialize_complete_fixture(tmp_path, audit)

    first = _canonical_report_bytes(audit.build_report(tmp_path))
    second = _canonical_report_bytes(audit.build_report(tmp_path))

    assert first == second
    assert hashlib.sha256(first).hexdigest() == LEGACY_FIXTURE_REPORT_SHA256


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
    records = {record["symbol"]: record for record in report["seams"]}
    assert {
        caller["classification"]
        for caller in records["runner.raw_lifecycle_arguments"]["callers"]
    } == {"production"}
    assert {
        caller["classification"]
        for caller in records["host_api.v1_v2_product_routes"]["callers"]
    } == {"production"}


def test_retired_fixture_matches_legacy_canonical_bytes(tmp_path: Path) -> None:
    audit = _load_audit_module()
    _materialize_complete_fixture(
        tmp_path,
        audit,
        retired_production_callers=True,
    )

    report = audit.build_report(tmp_path)
    canonical = _canonical_report_bytes(report)

    assert hashlib.sha256(canonical).hexdigest() == (
        LEGACY_RETIRED_FIXTURE_REPORT_SHA256
    )
    assert report["summary"] == {
        "seam_count": 21,
        "violation_count": 3,
        "scan_error_count": 0,
    }


def test_invalid_python_and_toml_are_deterministic_scan_errors(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    _materialize_complete_fixture(tmp_path, audit)
    _write_text(
        tmp_path / "apps/example/src/example/broken.py",
        "def broken(:\n",
    )
    _write_text(
        tmp_path / "apps/example/broken.toml",
        "[broken\n",
    )

    first = audit.build_report(tmp_path)
    second = audit.build_report(tmp_path)

    assert first["scan_errors"] == second["scan_errors"]
    assert [error["path"] for error in first["scan_errors"]] == [
        "apps/example/broken.toml",
        "apps/example/src/example/broken.py",
    ]
    assert first["summary"]["scan_error_count"] == 2


def test_unicode_and_read_failures_are_reported_once_and_fail_closed(
    tmp_path: Path,
) -> None:
    audit = _load_audit_module()
    _materialize_complete_fixture(tmp_path, audit)
    unicode_path = tmp_path / "docs/unreadable.md"
    read_error_path = tmp_path / "scripts/unreadable.ts"
    _write_text(unicode_path, "placeholder")
    _write_text(read_error_path, "placeholder")
    read_counts: Counter[str] = Counter()

    def failing_reader(path: Path) -> str:
        relative = path.relative_to(tmp_path).as_posix()
        read_counts[relative] += 1
        if path == unicode_path:
            raise UnicodeDecodeError(
                "utf-8",
                b"\xff",
                0,
                1,
                "synthetic unicode failure",
            )
        if path == read_error_path:
            raise OSError("synthetic read failure")
        return path.read_text(encoding="utf-8")

    first = audit.build_report(tmp_path, read_text=failing_reader)
    second = audit.build_report(tmp_path, read_text=failing_reader)

    assert first["scan_errors"] == second["scan_errors"]
    assert first["scan_errors"] == [
        {
            "path": "docs/unreadable.md",
            "error": (
                "'utf-8' codec can't decode byte 0xff in position 0: "
                "synthetic unicode failure"
            ),
        },
        {
            "path": "scripts/unreadable.ts",
            "error": "synthetic read failure",
        },
    ]
    assert read_counts["docs/unreadable.md"] == 2
    assert read_counts["scripts/unreadable.ts"] == 2
    assert first["summary"]["scan_error_count"] == 2


@pytest.mark.parametrize(
    ("path", "classification"),
    [
        ("apps/example/src/app.py", "production"),
        ("apps/example/pyproject.toml", "production_config"),
        ("apps/example/tests/test_app.py", "test_only"),
        ("docs/v3/README.md", "docs_only"),
        ("openspec/changes/example/spec.md", "docs_only"),
        ("legacy/v1/client.ts", "archive"),
        ("openspec/changes/archive/old/spec.md", "archive"),
        ("scripts/check-mainline.sh", "auxiliary"),
    ],
)
def test_path_classification_is_stable(path: str, classification: str) -> None:
    audit = _load_audit_module()

    assert audit._classify_path(path) == classification


def test_cli_exit_codes_distinguish_green_violation_and_scan_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit = _load_audit_module()
    green = tmp_path / "green"
    violation = tmp_path / "violation"
    scan_error = tmp_path / "scan-error"
    _materialize_complete_fixture(green, audit)
    _materialize_complete_fixture(
        violation,
        audit,
        retired_production_callers=True,
    )
    _materialize_complete_fixture(scan_error, audit)
    _write_text(
        scan_error / "apps/example/src/example/broken.py",
        "def broken(:\n",
    )

    assert audit.main(["--root", str(green), "--summary"]) == 0
    capsys.readouterr()
    assert audit.main(["--root", str(violation), "--summary"]) == 1
    capsys.readouterr()
    assert audit.main(["--root", str(scan_error), "--summary"]) == 2
