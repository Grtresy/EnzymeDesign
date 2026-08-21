from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from test_gate.config import load_config  # noqa: E402
from test_gate.affected import (  # noqa: E402
    ChangedPathInventory,
    run_affected_scope_diagnostic,
)
from test_gate.diagnostic import (  # noqa: E402
    CONTRACT_GROUPS,
    DiagnosticError,
    expand_focused_selection,
    diagnostic_environment,
    run_focused_diagnostic,
    verify_diagnostic_documents,
    verify_diagnostic_output,
)
from test_gate.diagnostic_guard import (  # noqa: E402
    DiagnosticEffectError,
    DiagnosticEffectGuard,
    _is_loopback_address,
)
from test_gate.model import (  # noqa: E402
    PYTEST_OBSERVATION_SCHEMA_ID,
    RECEIPT_SCHEMA_ID,
    canonical_document_bytes,
    load_canonical_document_bytes,
    seal_document,
)
from test_gate.runner import (  # noqa: E402
    ProcessResult,
    StreamCapture,
    publish_no_replace,
)
from test_gate.source import (  # noqa: E402
    SourceIdentity,
    ToolchainIdentity,
)


CONFIG_PATH = REPOSITORY_ROOT / "scripts/test-gate.toml"
EMPTY_DIGEST = (
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
TEST_NODE = "packages/example/tests/test_unit.py::test_unit"
LIVE_NODE = "packages/example/tests/test_live.py::test_live"


def _source_identity(seed: str = "one") -> SourceIdentity:
    return SourceIdentity(
        commit=seed * 40,
        tracked_diff_digest=f"sha256:diff-{seed}",
        tracked_dirty_paths=(),
        relevant_untracked_sources=(),
        configurations=(),
        locks=(),
        toolchains=tuple(
            ToolchainIdentity(
                name=name,
                executable=f"/bin/{name}",
                version=f"{name}-1",
                available=True,
            )
            for name in ("python", "node", "uv", "npm")
        ),
    )


def _affected_inventory(path: str) -> ChangedPathInventory:
    return ChangedPathInventory(
        base_ref="HEAD",
        base_commit="a" * 40,
        committed=(path,),
        staged=(),
        unstaged=(),
        relevant_untracked=(),
        paths=(path,),
    )


def _process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    outcome: str = "pass",
    exit_code: int | None = 0,
) -> ProcessResult:
    capture = StreamCapture(digest=EMPTY_DIGEST, total_bytes=0, tail="")
    return ProcessResult(
        argv=argv,
        cwd=str(cwd.resolve()),
        outcome=outcome,
        exit_code=exit_code,
        started_monotonic_ns=100,
        duration_ns=200,
        stdout=capture,
        stderr=capture,
        timed_out=False,
        term_sent=False,
        kill_sent=False,
        error=None,
    )


def _phase() -> dict[str, object]:
    return {
        "phase": "call",
        "outcome": "passed",
        "duration_ns": 20,
        "was_xfail": False,
        "failure_digest": None,
    }


def _observation_path(argv: tuple[str, ...]) -> Path:
    index = argv.index("--test-gate-observation")
    return Path(argv[index + 1])


def _write_observation(
    argv: tuple[str, ...],
    *,
    markers: tuple[str, ...] = (),
    deselected: tuple[str, ...] = (),
    deselected_marker_records: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = (),
    execution_outcome: str = "pass",
) -> None:
    mode = argv[argv.index("--test-gate-observation-mode") + 1]
    invocation_id = argv[argv.index("--test-gate-invocation-id") + 1]
    role = argv[argv.index("--test-gate-role") + 1]
    node_results: list[dict[str, object]] = []
    session_exit_code = 0
    if mode == "execute":
        phase = _phase()
        if execution_outcome == "fail":
            phase["outcome"] = "failed"
            session_exit_code = 1
        node_results.append(
            {
                "node_id": TEST_NODE,
                "outcome": execution_outcome,
                "duration_ns": 25,
                "phases": [phase],
            }
        )
    document = seal_document(
        PYTEST_OBSERVATION_SCHEMA_ID,
        {
            "invocation_id": invocation_id,
            "role": role,
            "mode": mode,
            "pytest_argv": list(argv),
            "cwd": str(REPOSITORY_ROOT),
            "collection": [
                {"node_id": TEST_NODE, "markers": sorted(markers)}
            ],
            "deselected": sorted(deselected),
            "deselected_markers": [
                {"node_id": node_id, "markers": sorted(marker_names)}
                for node_id, marker_names in sorted(
                    deselected_marker_records
                )
            ],
            "node_results": node_results,
            "session_exit_code": session_exit_code,
            "started_monotonic_ns": 10,
            "duration_ns": 30,
        },
    )
    publish_no_replace(
        _observation_path(argv),
        canonical_document_bytes(document),
    )


def _repo(root: Path) -> Path:
    repo = root / "repo"
    test_path = repo / "packages/example/tests/test_unit.py"
    source_path = repo / "packages/example/src/example/unit.py"
    test_path.parent.mkdir(parents=True)
    source_path.parent.mkdir(parents=True)
    test_path.write_text("def test_unit():\n    assert True\n", encoding="utf-8")
    source_path.write_text("VALUE = 1\n", encoding="utf-8")
    return repo


def _fake_runner(
    *,
    markers: tuple[str, ...] = (),
    deselected: tuple[str, ...] = (),
    collection_deselected: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = (),
    execution_outcome: str = "pass",
) -> tuple[Callable[..., ProcessResult], list[tuple[str, ...]]]:
    calls: list[tuple[str, ...]] = []

    def run(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        del environment, timeout_seconds
        normalized = tuple(argv)
        calls.append(normalized)
        if "--test-gate-observation" in normalized:
            collecting = "--collect-only" in normalized
            observation_deselected = (
                tuple(node_id for node_id, _ in collection_deselected)
                if collecting
                else deselected
            )
            observation_deselected_markers = (
                collection_deselected
                if collecting
                else tuple((node_id, ()) for node_id in deselected)
            )
            _write_observation(
                normalized,
                markers=markers if collecting else (),
                deselected=observation_deselected,
                deselected_marker_records=(
                    observation_deselected_markers
                ),
                execution_outcome=execution_outcome,
            )
        outcome = (
            "fail"
            if "--collect-only" not in normalized
            and "--test-gate-observation" in normalized
            and execution_outcome == "fail"
            else "pass"
        )
        return _process(
            normalized,
            cwd=cwd,
            outcome=outcome,
            exit_code=0 if outcome == "pass" else 1,
        )

    return run, calls


def test_focused_selection_is_explicit_deduplicated_and_closed(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    selection = expand_focused_selection(
        repo,
        lint_paths=(
            "packages/example/src/example/unit.py",
            "packages/example/src/example/unit.py",
        ),
        pytest_paths=("packages/example/tests/test_unit.py",),
        node_ids=(TEST_NODE,),
    )

    assert selection.lint_paths == ("packages/example/src/example/unit.py",)
    assert selection.pytest_selectors == (
        "packages/example/tests/test_unit.py",
        TEST_NODE,
    )
    assert selection.collection_selectors == (
        "packages/example/tests/test_unit.py",
    )


def test_test_gate_contract_group_covers_every_test_gate_test_module() -> None:
    test_root = REPOSITORY_ROOT / "packages/openzyme-kernel/tests"
    expected = tuple(
        sorted(
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in test_root.glob("test_test_gate_*.py")
        )
    )

    assert CONTRACT_GROUPS["test_gate"].pytest_selectors == expected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "requires at least one"),
        ({"lint_paths": ("../outside.py",)}, "repository-relative"),
        ({"pytest_paths": ("/tmp/outside.py",)}, "repository-relative"),
        ({"pytest_paths": ("missing.py",)}, "does not exist"),
        ({"node_ids": ("packages/example/tests/test_unit.py",)}, "must contain"),
        ({"contract_groups": ("missing",)}, "unknown diagnostic contract"),
    ],
)
def test_focused_selection_rejects_empty_external_missing_and_unknown_inputs(
    tmp_path: Path,
    kwargs: dict[str, tuple[str, ...]],
    message: str,
) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(DiagnosticError, match=message):
        expand_focused_selection(repo, **kwargs)


def test_diagnostic_environment_removes_live_external_and_ambient_pytest_state(
    tmp_path: Path,
) -> None:
    source = {
        "PATH": "/bin",
        "OPENAI_API_KEY": "secret",
        "MICU_API_KEY": "secret",
        "CHROME_REMOTE_DEBUGGING_URL": "http://remote",
        "OPENZYME_HPC_CONFIG": "cluster.toml",
        "SSH_AUTH_SOCK": "/tmp/agent",
        "HTTPS_PROXY": "http://proxy",
        "PYTEST_ADDOPTS": "-m live_hpc",
        "OPENZYME_RUN_LIVE": "1",
    }

    environment = diagnostic_environment(tmp_path, source)

    assert environment["PATH"] == "/bin"
    assert environment["OPENZYME_LOAD_ENV_FILES"] == "0"
    assert environment["OPENZYME_TEST_GATE_DIAGNOSTIC"] == "1"
    assert environment["PYTHONPATH"] == str(tmp_path / "scripts")
    assert not {
        "OPENAI_API_KEY",
        "MICU_API_KEY",
        "CHROME_REMOTE_DEBUGGING_URL",
        "OPENZYME_HPC_CONFIG",
        "SSH_AUTH_SOCK",
        "HTTPS_PROXY",
        "PYTEST_ADDOPTS",
        "OPENZYME_RUN_LIVE",
    } & set(environment)


def test_diagnostic_effect_guard_blocks_remote_network_and_collection_processes() -> None:
    original_popen = subprocess.Popen
    assert _is_loopback_address(("127.0.0.1", 8000))
    assert _is_loopback_address(("::1", 8000))
    assert _is_loopback_address("local.sock")
    assert not _is_loopback_address(("example.com", 443))

    with DiagnosticEffectGuard(block_subprocesses=True):
        with pytest.raises(DiagnosticEffectError, match="remote"):
            socket.create_connection(("example.com", 443))
        with pytest.raises(DiagnosticEffectError, match="child process"):
            subprocess.Popen(("does-not-run",))

    assert subprocess.Popen is original_popen


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "import subprocess\n"
            "subprocess.run(['collection-effect-must-not-run'])\n"
            "def test_never_runs():\n"
            "    assert True\n",
            "blocked a child process during collection",
        ),
        (
            "import socket\n"
            "socket.create_connection(('example.com', 443))\n"
            "def test_never_runs():\n"
            "    assert True\n",
            "blocked remote create_connection",
        ),
    ],
)
def test_real_pytest_collection_rejects_forbidden_effects(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    test_path = tmp_path / "test_forbidden_effect.py"
    test_path.write_text(source, encoding="utf-8")
    environment = diagnostic_environment(REPOSITORY_ROOT)

    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "--rootdir",
            str(tmp_path),
            "-p",
            "test_gate.diagnostic_guard",
            "--test-gate-diagnostic-guard",
            str(test_path),
        ),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
        timeout=30,
    )

    assert result.returncode != 0
    assert message in result.stdout
    assert "test_never_runs" not in result.stdout


def test_focused_run_publishes_and_verifies_non_authoritative_evidence(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    output_root = tmp_path / "evidence"
    runner, calls = _fake_runner()
    identity = _source_identity()

    result = run_focused_diagnostic(
        repo_root=repo,
        output_root=output_root,
        config=load_config(CONFIG_PATH),
        invocation_id="focused-one",
        lint_paths=("packages/example/src/example/unit.py",),
        pytest_paths=("packages/example/tests/test_unit.py",),
        process_runner=runner,
        source_collector=lambda root: identity,
    )

    assert result.terminal_status == "pass"
    assert len(calls) == 3
    assert result.receipt["authoritative"] is False
    assert result.receipt["admission_eligible"] is False
    assert result.receipt["live_eligible"] is False
    assert result.receipt["diagnostic_selection"]["frontend"] == {
        "included": False,
        "stage_ids": [],
        "frontend_omission": "diagnostic_only",
        "reason": "focused selection does not infer affected frontend closure",
    }
    plan, receipt = verify_diagnostic_output(
        plan_path=output_root / "diagnostic-plan.json",
        receipt_path=output_root / "diagnostic-receipt.json",
        current_source_identity_digest=identity.digest,
    )
    assert plan["self_digest"] == result.plan["self_digest"]
    assert receipt["self_digest"] == result.receipt["self_digest"]


def test_focused_run_rejects_forbidden_marker_before_execution(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    runner, calls = _fake_runner(markers=("integration", "live_hpc"))

    with pytest.raises(DiagnosticError, match=TEST_NODE):
        run_focused_diagnostic(
            repo_root=repo,
            output_root=tmp_path / "evidence",
            config=load_config(CONFIG_PATH),
            invocation_id="focused-live",
            pytest_paths=("packages/example/tests/test_unit.py",),
            process_runner=runner,
            source_collector=lambda root: _source_identity(),
        )

    assert len(calls) == 1
    assert "--collect-only" in calls[0]
    assert not (tmp_path / "evidence/diagnostic-plan.json").exists()


def test_focused_run_rejects_collection_deselection_before_execution(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    runner, calls = _fake_runner(
        collection_deselected=((LIVE_NODE, ("integration",)),)
    )

    with pytest.raises(DiagnosticError, match="unexpectedly deselected"):
        run_focused_diagnostic(
            repo_root=repo,
            output_root=tmp_path / "evidence",
            config=load_config(CONFIG_PATH),
            invocation_id="focused-hidden-live",
            pytest_paths=("packages/example/tests/test_unit.py",),
            process_runner=runner,
            source_collector=lambda root: _source_identity(),
        )

    assert len(calls) == 1
    assert "-m" not in calls[0]


def test_focused_run_rejects_unexpected_deselection_and_source_drift(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    runner, _ = _fake_runner(
        deselected=("packages/example/tests/test_other.py::test_other",)
    )
    stable = _source_identity()

    with pytest.raises(DiagnosticError, match="unexpectedly deselected"):
        run_focused_diagnostic(
            repo_root=repo,
            output_root=tmp_path / "deselected",
            config=load_config(CONFIG_PATH),
            invocation_id="focused-deselected",
            pytest_paths=("packages/example/tests/test_unit.py",),
            process_runner=runner,
            source_collector=lambda root: stable,
        )

    drift_runner, calls = _fake_runner()
    identities = iter((_source_identity("a"), _source_identity("b")))
    with pytest.raises(Exception, match="source identity drifted"):
        run_focused_diagnostic(
            repo_root=repo,
            output_root=tmp_path / "drift",
            config=load_config(CONFIG_PATH),
            invocation_id="focused-drift",
            pytest_paths=("packages/example/tests/test_unit.py",),
            process_runner=drift_runner,
            source_collector=lambda root: next(identities),
        )
    assert len(calls) == 1


def test_diagnostic_verifier_rejects_authority_upgrade_and_missing_stage(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    runner, _ = _fake_runner()
    identity = _source_identity()
    result = run_focused_diagnostic(
        repo_root=repo,
        output_root=tmp_path / "evidence",
        config=load_config(CONFIG_PATH),
        invocation_id="focused-tamper",
        pytest_paths=("packages/example/tests/test_unit.py",),
        process_runner=runner,
        source_collector=lambda root: identity,
    )
    receipt_fields: dict[str, Any] = {
        key: value
        for key, value in result.receipt.items()
        if key not in {"schema_id", "self_digest"}
    }
    receipt_fields["authoritative"] = True
    upgraded = seal_document(RECEIPT_SCHEMA_ID, receipt_fields)
    stage_documents = {
        stage_id: load_canonical_document_bytes(path.read_bytes())
        for stage_id, path in {
            "focused_pytest_collection": (
                tmp_path
                / "evidence/focused_pytest_collection-stage.json"
            ),
            "focused_pytest_execution": (
                tmp_path
                / "evidence/focused_pytest_execution-stage.json"
            ),
        }.items()
    }

    with pytest.raises(DiagnosticError, match="authority upgrade"):
        verify_diagnostic_documents(
            plan=result.plan,
            receipt=upgraded,
            stage_documents=stage_documents,
        )
    with pytest.raises(DiagnosticError, match="stage output is missing"):
        verify_diagnostic_documents(
            plan=result.plan,
            receipt=result.receipt,
            stage_documents={},
        )
    plan_fields: dict[str, Any] = {
        key: value
        for key, value in result.plan.items()
        if key not in {"schema_id", "self_digest"}
    }
    plan_fields["profile_id"] = "mainline_authoritative"
    attempted_mainline_reuse = seal_document(
        result.plan["schema_id"],
        plan_fields,
    )
    with pytest.raises(DiagnosticError, match="not a diagnostic profile"):
        verify_diagnostic_documents(
            plan=attempted_mainline_reuse,
            receipt=result.receipt,
            stage_documents=stage_documents,
        )


def test_affected_run_executes_owner_local_selection_and_verifies(
    tmp_path: Path,
) -> None:
    runner, calls = _fake_runner()
    identity = _source_identity()
    changed_path = "apps/mcp-hpc-runner/src/mcp_hpc_runner/server.py"

    result = run_affected_scope_diagnostic(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "affected",
        config=load_config(CONFIG_PATH),
        invocation_id="affected-owner",
        base_ref="HEAD",
        process_runner=runner,
        source_collector=lambda root: identity,
        inventory_collector=lambda root, base_ref: _affected_inventory(
            changed_path
        ),
    )

    assert result.terminal_status == "pass"
    assert result.plan["profile_id"] == "affected_scope_diagnostic"
    assert result.plan["diagnostic_selection"]["matched_rules"] == [
        "mcp-hpc-runner-owner"
    ]
    assert result.plan["diagnostic_selection"]["frontend"][
        "frontend_omission"
    ] == "diagnostic_only"
    assert len(calls) == 3
    verify_diagnostic_output(
        plan_path=tmp_path / "affected/diagnostic-plan.json",
        receipt_path=tmp_path / "affected/diagnostic-receipt.json",
        current_source_identity_digest=identity.digest,
    )


def test_affected_frontend_only_and_complete_fallback_remain_diagnostic(
    tmp_path: Path,
) -> None:
    identity = _source_identity()
    frontend_runner, frontend_calls = _fake_runner()
    frontend = run_affected_scope_diagnostic(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "frontend",
        config=load_config(CONFIG_PATH),
        invocation_id="affected-frontend",
        base_ref="HEAD",
        process_runner=frontend_runner,
        source_collector=lambda root: identity,
        inventory_collector=lambda root, base_ref: _affected_inventory(
            "apps/openzyme-web-ui/src/view.js"
        ),
    )
    fallback_runner, fallback_calls = _fake_runner(
        collection_deselected=(
            (
                LIVE_NODE,
                ("integration", "live_hpc"),
            ),
        )
    )
    fallback = run_affected_scope_diagnostic(
        repo_root=REPOSITORY_ROOT,
        output_root=tmp_path / "fallback",
        config=load_config(CONFIG_PATH),
        invocation_id="affected-fallback",
        base_ref="HEAD",
        process_runner=fallback_runner,
        source_collector=lambda root: identity,
        inventory_collector=lambda root, base_ref: _affected_inventory(
            "unknown/public-shape.json"
        ),
    )

    assert [call[:3] for call in frontend_calls] == [
        ("npm", "test"),
        ("npm", "run", "build"),
    ]
    assert frontend.receipt["coverage"]["collected_nodes"] == []
    assert frontend.receipt["frontend"]["outcomes"] == {
        "web_ui_test": "pass",
        "web_ui_build": "pass",
    }
    frontend_stage_documents = {
        stage_id: load_canonical_document_bytes(
            (
                tmp_path
                / "frontend"
                / f"{stage_id}-stage.json"
            ).read_bytes()
        )
        for stage_id in ("web_ui_test", "web_ui_build")
    }
    tampered_fields = {
        key: value
        for key, value in frontend.receipt.items()
        if key not in {"schema_id", "self_digest"}
    }
    tampered_fields["frontend"] = {
        **frontend.receipt["frontend"],
        "outcomes": {"web_ui_test": "pass"},
    }
    tampered_frontend = seal_document(RECEIPT_SCHEMA_ID, tampered_fields)
    with pytest.raises(DiagnosticError, match="frontend stage closure"):
        verify_diagnostic_documents(
            plan=frontend.plan,
            receipt=tampered_frontend,
            stage_documents=frontend_stage_documents,
        )
    assert fallback.plan["diagnostic_selection"][
        "fallback_complete_safe"
    ] is True
    assert fallback.plan["diagnostic_selection"][
        "collection_deselection_policy"
    ] == "exclude_declared_non_live_markers"
    assert fallback.plan["diagnostic_selection"][
        "policy_deselected_nodes"
    ] == [
        {
            "node_id": LIVE_NODE,
            "markers": ["integration", "live_hpc"],
        }
    ]
    collection_call = fallback_calls[0]
    assert collection_call[collection_call.index("-m") + 1].startswith(
        "not integration"
    )
    execution_call = fallback_calls[2]
    assert LIVE_NODE not in execution_call
    assert len(fallback_calls) == 5
    for result in (frontend, fallback):
        assert result.receipt["authoritative"] is False
        assert result.receipt["admission_eligible"] is False
        assert result.receipt["live_eligible"] is False


def test_affected_collection_rejects_non_policy_deselection(
    tmp_path: Path,
) -> None:
    runner, calls = _fake_runner(
        collection_deselected=(
            (
                "packages/example/tests/test_other.py::test_other",
                ("slow",),
            ),
        )
    )

    with pytest.raises(
        DiagnosticError,
        match="unexpectedly deselected a non-live node",
    ):
        run_affected_scope_diagnostic(
            repo_root=REPOSITORY_ROOT,
            output_root=tmp_path / "affected",
            config=load_config(CONFIG_PATH),
            invocation_id="affected-unexpected-deselect",
            base_ref="HEAD",
            process_runner=runner,
            source_collector=lambda root: _source_identity(),
            inventory_collector=lambda root, base_ref: _affected_inventory(
                "unknown/public-shape.json"
            ),
        )

    assert len(calls) == 1
