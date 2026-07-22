from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess

import pytest
from openzyme_runtime import settings as runtime_settings

from .composition import ProductionCompositionFactory
from .safety import QualificationSafetyGuard
from .safety import QualificationSafetyViolation
from .safety import QualificationSourcePolicyError
from .safety import scrubbed_environment
from .safety import validate_qualification_scenario_sources


def _registry() -> dict[str, object]:
    return {
        "external_ports": [
            {
                "effect_ledger_required": True,
                "port_id": "provider.http",
                "production_seams": ["provider"],
                "qualification_mode": "controlled_adapter",
            },
            {
                "effect_ledger_required": True,
                "port_id": "supervision.local_fault_process",
                "production_seams": ["process group"],
                "qualification_mode": "local_fault_process",
            },
        ]
    }


def test_safety_guard_scrubs_credentials_and_blocks_ambient_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-visible")
    monkeypatch.setenv("QUALIFICATION_SAFE_SETTING", "visible")

    with QualificationSafetyGuard(registry=_registry()) as guard:
        assert "OPENAI_API_KEY" not in os.environ
        assert os.environ["QUALIFICATION_SAFE_SETTING"] == "visible"
        with pytest.raises(QualificationSafetyViolation):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(QualificationSafetyViolation):
            subprocess.run(["ssh", "forbidden.invalid"], check=False)

    assert os.environ["OPENAI_API_KEY"] == "must-not-be-visible"
    assert [(item.boundary, item.operation) for item in guard.blocked_invocations] == [
        ("network", "socket.create_connection"),
        ("process", "subprocess"),
    ]


def test_safety_guard_allows_in_process_production_composition(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "guarded-composition")
    composition = factory.build()
    with QualificationSafetyGuard(registry=_registry()) as guard:
        with composition as running:
            assert running.client is not None
            response = running.client.post(
                "/v3/sessions",
                headers={"Idempotency-Key": "qualification:guard:create"},
                json={
                    "session_id": "sess_qualification_guard",
                    "project_id": "proj_architecture_qualification",
                    "objective": "Prove in-process Host composition needs no network.",
                },
            )
            assert response.status_code == 200, response.text
    assert guard.blocked_invocations == ()


def test_scrubbed_environment_removes_generic_secret_names() -> None:
    assert scrubbed_environment(
        {
            "MY_PROVIDER_API_TOKEN": "secret",
            "SERVICE_PASSWORD": "secret",
            "VISIBLE_MODE": "qualification",
        }
    ) == {"VISIBLE_MODE": "qualification"}


def test_safety_guard_prevents_env_files_from_rehydrating_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENZYME_LLM_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with QualificationSafetyGuard(registry=_registry()):
        runtime_settings.load_env_files((".env", ".env.local"))
        assert "OPENZYME_LLM_API_KEY" not in os.environ
        assert "TAVILY_API_KEY" not in os.environ


def test_safety_guard_rejects_an_undeclared_allowed_port() -> None:
    guard = QualificationSafetyGuard(registry=_registry())
    with pytest.raises(QualificationSafetyViolation) as error:
        guard.require_declared_port("runner.hpc", mode="controlled_adapter")
    assert "is not declared" in str(error.value)


def test_scenario_source_policy_rejects_eval_legacy_and_direct_sqlite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "test_forbidden_scenario.py"
    source.write_text(
        "from openzyme_host_api.foundation import build_local_eval_foundation\n"
        "def test_bad(composition):\n"
        "    with composition.dependencies.v3_repository_scope(mode='write') as repos:\n"
        "        repos.connection.execute('UPDATE tasks SET status=success')\n",
        encoding="utf-8",
    )

    with pytest.raises(QualificationSourcePolicyError) as error:
        validate_qualification_scenario_sources(
            repo_root=tmp_path,
            source_files=(source.name,),
        )
    message = str(error.value)
    assert "build_local_eval_foundation" in message
    assert "v3_repository_scope" in message
    assert "execute" in message


def test_scenario_source_policy_allows_public_driver_and_collector(tmp_path: Path) -> None:
    source = tmp_path / "test_public_scenario.py"
    source.write_text(
        "def test_public(driver, collector):\n"
        "    driver.create_session('sess_public')\n"
        "    assert collector.observe('sess_public')\n",
        encoding="utf-8",
    )
    validate_qualification_scenario_sources(
        repo_root=tmp_path,
        source_files=(source.name,),
    )
