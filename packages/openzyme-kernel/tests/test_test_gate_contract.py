from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.config import (  # noqa: E402
    LEGACY_MAINLINE_STAGE_ORDER,
    ConfigError,
    load_config,
    validate_dispatch_profile,
)
from scripts.test_gate.runner import TestGateRunnerError, validate_new_output_root  # noqa: E402

CHECK_MAINLINE = REPOSITORY_ROOT / "scripts" / "check-mainline.sh"
LEGACY_MAINLINE = REPOSITORY_ROOT / "scripts" / "check-mainline-legacy.sh"
CONFIG_PATH = REPOSITORY_ROOT / "scripts" / "test-gate.toml"
CLI_PATH = REPOSITORY_ROOT / "scripts" / "run-test-gate.py"
MARKER_EXPRESSION = (
    "not integration and not live_llm and not live_tavily and not live_hpc "
    "and not live_e2e and not quality_eval"
)


def test_current_mainline_wrapper_is_the_only_optimized_authority() -> None:
    script = CHECK_MAINLINE.read_text(encoding="utf-8")
    expected_fragments = (
        "set -euo pipefail",
        "usage: $0 [--forced-serial]",
        "openzyme-mainline-authoritative.XXXXXX",
        "CURRENT AUTHORITY: scripts/check-mainline.sh",
        "NO OTHER AUTHORITY:",
        "ROLLBACK COMPARISON: ./scripts/check-mainline-legacy.sh",
        "mainline_authoritative",
        '"${mode_args[@]}"',
        "verify-mainline-authoritative",
        "CURRENT NON-LIVE MERGE AUTHORITY VERIFIED",
    )
    positions = [script.index(fragment) for fragment in expected_fragments]
    assert positions == sorted(positions)
    assert "mode_args=(--workers 4)" in script
    assert "mode_args=(--forced-serial)" in script
    assert "uv run pytest" not in script
    assert "check-v3-architecture-qualification.sh" not in script
    assert CHECK_MAINLINE.stat().st_mode & 0o111


@pytest.mark.parametrize(
    ("arguments", "mode_argv"),
    (
        ((), ("--workers", "4")),
        (("--forced-serial",), ("--forced-serial",)),
    ),
)
def test_current_mainline_wrapper_runs_authority_then_pure_verifier(
    tmp_path: Path,
    arguments: tuple[str, ...],
    mode_argv: tuple[str, ...],
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "uv.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$OPENZYME_TEST_GATE_WRAPPER_LOG"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    temporary_root = tmp_path / "tmp"
    temporary_root.mkdir()
    environment = dict(os.environ)
    environment.update(
        {
            "OPENZYME_TEST_GATE_WRAPPER_LOG": str(log_path),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TMPDIR": str(temporary_root),
        }
    )

    completed = subprocess.run(
        (str(CHECK_MAINLINE), *arguments),
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 0
    commands = [line.split() for line in log_path.read_text().splitlines()]
    assert len(commands) == 4
    assert commands[0] == [
        "run",
        "pytest",
        "packages/openzyme-contracts/tests/test_external_qualification.py",
        "packages/openzyme-contracts/tests/test_external_route_qualification.py",
        "packages/enzymedesign-distribution/tests/test_external_qualification.py",
        "packages/enzymedesign-distribution/tests/test_qualification_planning.py",
        "packages/enzymedesign-distribution/tests/test_qualification_operator_state.py",
        "packages/enzymedesign-distribution/tests/test_qualification_bridges.py",
        "packages/enzymedesign-distribution/tests/test_owner_qualification_bridges.py",
        "packages/enzymedesign-distribution/tests/test_qualification_runtime.py",
        "packages/enzymedesign-distribution/tests/test_qualification_admission.py",
        "packages/enzymedesign-distribution/tests/test_qualification_ci_boundary.py",
        "packages/openzyme-store-sqlite/tests/test_external_qualification_ledger.py",
        "packages/openzyme-process-podman/tests/test_qualification_images.py",
        "packages/openzyme-workspace-git-lfs/tests/test_qualification_preparation.py",
        "packages/openzyme-hpc/tests/test_qualification.py",
        "packages/openzyme-hpc-ssh/tests/test_qualification_identity_observation.py",
        "packages/openzyme-runtime-llm/tests/test_qualification_bridge.py",
        "packages/openzyme-research-tavily/tests/test_qualification_bridge.py",
        "packages/enzymedesign-bio-provider-adapters/tests/test_qualification_bridge.py",
        "-q",
    ]
    readiness_report = commands[1][3]
    assert commands[1] == [
        "run",
        "python",
        "scripts/verify-external-qualification-readiness.py",
        readiness_report,
    ]
    evidence_root = commands[2][4]
    assert commands[2] == [
        "run",
        "python",
        "scripts/run-test-gate.py",
        "mainline_authoritative",
        evidence_root,
        *mode_argv,
    ]
    assert commands[3] == [
        "run",
        "python",
        "scripts/run-test-gate.py",
        "verify-mainline-authoritative",
        evidence_root,
    ]
    assert Path(evidence_root).parent.parent == temporary_root
    assert Path(readiness_report).parent == Path(evidence_root).parent
    assert "CURRENT AUTHORITY" in completed.stderr
    assert "NO OTHER AUTHORITY" in completed.stderr
    assert "CURRENT NON-LIVE MERGE AUTHORITY VERIFIED" in completed.stderr


def test_current_mainline_wrapper_rejects_every_other_argument(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        (str(CHECK_MAINLINE), "--workers", "2"),
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "usage:" in completed.stderr


@pytest.mark.parametrize(
    "command",
    ("mainline_authoritative", "verify-mainline-authoritative"),
)
def test_current_authority_cli_commands_are_public_and_strict(
    command: str,
) -> None:
    completed = subprocess.run(
        (sys.executable, str(CLI_PATH), command, "--help"),
        cwd=REPOSITORY_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    assert completed.returncode == 0
    if command == "mainline_authoritative":
        assert "--forced-serial" in completed.stdout
        assert "--workers" in completed.stdout
    else:
        assert "output_root" in completed.stdout


def test_frozen_rollback_runs_the_same_sequence_but_disclaims_authority() -> None:
    script = LEGACY_MAINLINE.read_text(encoding="utf-8")
    expected_fragments = (
        "LEGACY ROLLBACK COMPARISON ONLY",
        "uv run ruff check apps packages",
        "uv run ruff check scripts/audit-v3-compat-callers.py",
        "uv run python scripts/audit-v3-compat-callers.py --summary",
        "./scripts/check-v3-architecture-qualification.sh \\\n"
        "  premerge_subset \\\n"
        '  "$qualification_tmp_root/report"',
        f'uv run pytest -m "{MARKER_EXPRESSION}"',
        "cd apps/openzyme-web-ui",
        "npm test",
        "npm run build",
        "LEGACY ROLLBACK COMPARISON COMPLETE",
    )
    positions = [script.index(fragment) for fragment in expected_fragments]
    assert positions == sorted(positions)
    assert LEGACY_MAINLINE.stat().st_mode & 0o111
    assert "authoritative=true" not in script


def test_versioned_config_matches_every_legacy_mainline_obligation() -> None:
    config = load_config(CONFIG_PATH)
    mainline = config.profile("mainline_authoritative")

    assert mainline.stage_ids == LEGACY_MAINLINE_STAGE_ORDER
    assert config.stage("ruff_source").argv == (
        "uv",
        "run",
        "ruff",
        "check",
        "apps",
        "packages",
    )
    assert config.stage("ruff_compatibility_audit").argv == (
        "uv",
        "run",
        "ruff",
        "check",
        "scripts/audit-v3-compat-callers.py",
    )
    assert config.stage("compatibility_audit").argv == (
        "uv",
        "run",
        "python",
        "scripts/audit-v3-compat-callers.py",
        "--summary",
    )
    qualification = config.stage("architecture_qualification_premerge")
    assert qualification.argv == (
        "./scripts/check-v3-architecture-qualification.sh",
        "premerge_subset",
        "{qualification_output_root}",
    )
    assert qualification.qualification_mode == "premerge_subset"
    assert config.stage("general_non_live_pytest").argv == (
        "uv",
        "run",
        "pytest",
        "-m",
        MARKER_EXPRESSION,
    )
    assert config.stage("web_ui_test").cwd == "apps/openzyme-web-ui"
    assert config.stage("web_ui_test").argv == ("npm", "test")
    assert config.stage("web_ui_build").cwd == "apps/openzyme-web-ui"
    assert config.stage("web_ui_build").argv == ("npm", "run", "build")

    package = json.loads(
        (REPOSITORY_ROOT / "apps/openzyme-web-ui/package.json").read_text(
            encoding="utf-8"
        )
    )
    assert package["scripts"]["test"] == "node --test tests/*.test.js"
    assert package["scripts"]["build"] == "node scripts/build.mjs"


@pytest.mark.parametrize("profile_id", ["architecture_admission", "live_campaign"])
def test_dispatcher_rejects_non_test_gate_authority_profiles(profile_id: str) -> None:
    config = load_config(CONFIG_PATH)
    with pytest.raises(ConfigError, match="outside the test-gate dispatcher"):
        validate_dispatch_profile(config, profile_id)

    completed = subprocess.run(
        (
            sys.executable,
            str(CLI_PATH),
            "--config",
            str(CONFIG_PATH),
            "validate-profile",
            profile_id,
        ),
        cwd=REPOSITORY_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "outside the test-gate dispatcher" in completed.stderr


def test_operator_evidence_cannot_target_product_checkout_state(tmp_path: Path) -> None:
    config = load_config(CONFIG_PATH)
    assert config.evidence_policy.repository_plane_only is True
    assert config.evidence_policy.requires_checkout_external_output_root is True
    assert config.evidence_policy.product_state_writes is False

    with pytest.raises(TestGateRunnerError, match="outside the checkout"):
        validate_new_output_root(
            REPOSITORY_ROOT,
            REPOSITORY_ROOT / "evidence" / "test-gate-receipt",
        )
    assert validate_new_output_root(
        REPOSITORY_ROOT,
        tmp_path / "test-gate-receipt",
    ) == tmp_path / "test-gate-receipt"


def test_operator_package_has_no_product_package_imports_or_composition() -> None:
    for path in sorted((REPOSITORY_ROOT / "scripts/test_gate").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert not [
            module
            for module in imported_modules
            if module == "openzyme" or module.startswith("openzyme_")
        ], path

    forbidden_references: list[Path] = []
    for source_root in (
        REPOSITORY_ROOT / "apps",
        REPOSITORY_ROOT / "packages",
    ):
        for path in source_root.glob("*/src/**/*.py"):
            if "scripts.test_gate" in path.read_text(encoding="utf-8"):
                forbidden_references.append(path)
    assert forbidden_references == []


def test_mainline_receipt_has_no_product_or_scientific_consumer() -> None:
    forbidden_tokens = {
        "openzyme_test_gate_receipt@1",
        "mainline-candidate-receipt.json",
        "mainline-authoritative-receipt.json",
    }
    consumers: list[tuple[Path, str]] = []
    for source_root in (
        REPOSITORY_ROOT / "apps",
        REPOSITORY_ROOT / "packages",
    ):
        for path in source_root.glob("*/src/**/*"):
            if not path.is_file() or path.suffix not in {
                ".js",
                ".jsx",
                ".py",
                ".ts",
                ".tsx",
            }:
                continue
            content = path.read_text(encoding="utf-8")
            consumers.extend(
                (path, token)
                for token in forbidden_tokens
                if token in content
            )
    assert consumers == []
