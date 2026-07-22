from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_host_api.architecture_qualification import REQUIRED_FAMILIES
from openzyme_host_api.architecture_qualification import load_invariant_registry
from openzyme_host_api.architecture_qualification import resolve_boundary_relation

from ..boundary_probes import probe_artifact_metadata_boundaries
from ..boundary_probes import probe_control_frame_boundary
from ..boundary_probes import probe_dispatch_request_boundary
from ..boundary_probes import (
    probe_durable_result_and_provider_summary_boundaries,
)
from ..boundary_probes import probe_provider_document_boundary
from ..boundary_probes import probe_register_many_aggregate_boundary
from ..composition import ProductionCompositionFactory
from ..driver import QualificationDriver
from ..observation import collect_observation


REPO_ROOT = Path(__file__).resolve().parents[5]
BOUNDARY_IDS = (
    "artifact_metadata_inline_bytes",
    "artifact_metadata_sidecar_bytes",
    "artifact_register_many_metadata_bytes",
    "controlled_operation_dispatch_request_bytes",
    "durable_result_envelope_bytes",
    "provider_control_document_bytes",
    "sandbox_control_frame_bytes",
)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="boundary-scale.symbolic-owner-relations",
    family="boundary-scale",
    selections=("full", "premerge_subset"),
)
def test_all_registered_owner_limits_execute_minus_equal_plus_cases(
    tmp_path: Path,
) -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    assert tuple(registry.payload["required_families"]) == REQUIRED_FAMILIES
    resolved = {
        boundary_id: resolve_boundary_relation(
            registry,
            boundary_id=boundary_id,
            repo_root=REPO_ROOT,
        )
        for boundary_id in BOUNDARY_IDS
    }
    assert tuple(resolved) == BOUNDARY_IDS
    for item in resolved.values():
        assert item.cases == (
            item.owner_value - 1,
            item.owner_value,
            item.owner_value + 1,
        )
        assert item.owner_value > 1
        assert item.seam_values

    factory = ProductionCompositionFactory.create(tmp_path / "boundary-scale")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)
        session_id = "sess_boundary_scale"
        driver.create_session(session_id)
        base_ids = driver.admit_durable_operation(
            session_id=session_id,
            scenario_key="boundary_artifact_workspace",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        metadata = probe_artifact_metadata_boundaries(
            running,
            ids=base_ids,
            inline_cases=resolved["artifact_metadata_inline_bytes"].cases,
            sidecar_cases=resolved["artifact_metadata_sidecar_bytes"].cases,
        )
        aggregate = probe_register_many_aggregate_boundary(
            running,
            ids=base_ids,
            cases=resolved["artifact_register_many_metadata_bytes"].cases,
            metadata_probe=metadata,
        )
        dispatch = probe_dispatch_request_boundary(
            driver,
            session_id_prefix="sess_boundary_dispatch",
            cases=resolved["controlled_operation_dispatch_request_bytes"].cases,
        )
        durable = probe_durable_result_and_provider_summary_boundaries(
            running,
            cases=resolved["durable_result_envelope_bytes"].cases,
        )
        provider_document = probe_provider_document_boundary(
            running,
            root=tmp_path / "provider-documents",
            cases=resolved["provider_control_document_bytes"].cases,
        )
        control_frame = probe_control_frame_boundary(
            root=tmp_path / "control-frames",
            cases=resolved["sandbox_control_frame_bytes"].cases,
        )
        observation = collect_observation(running, session_ids=(session_id,))

    assert metadata.inline_outcomes == {
        "limit_minus_one": {
            "engine": "accepted",
            "host": "accepted",
            "pipeline": "inline",
        },
        "limit": {
            "engine": "accepted",
            "host": "accepted",
            "pipeline": "inline",
        },
        "limit_plus_one": {
            "engine": "rejected:ValueError",
            "host": "rejected:artifact_registration_metadata_inline_too_large",
            "host_sidecar": "accepted",
            "pipeline": "sidecar",
        },
    }
    assert metadata.sidecar_outcomes == {
        "limit_minus_one": {
            "engine": "accepted",
            "host": "accepted",
            "pipeline": "sidecar",
        },
        "limit": {
            "engine": "accepted",
            "host": "accepted",
            "pipeline": "sidecar",
        },
        "limit_plus_one": {
            "engine": (
                "rejected:artifact_registration_metadata_sidecar_too_large"
            ),
            "host": "rejected:artifact_registration_metadata_sidecar_too_large",
            "pipeline": "rejected:artifact_registration_metadata_too_large",
        },
    }
    assert aggregate["limit_minus_one"]["core"] == (
        "downstream:artifact_register_invalid_path"
    )
    assert aggregate["limit"]["core"] == "downstream:artifact_register_invalid_path"
    assert aggregate["limit_plus_one"]["core"] == (
        "rejected:artifact_register_many_metadata_too_large"
    )
    assert "registered artifact does not exist" in (
        aggregate["limit_minus_one"]["engine"]
    )
    assert "registered artifact does not exist" in aggregate["limit"]["engine"]
    assert aggregate["limit_plus_one"]["engine"] == (
        "rejected:artifacts.register_many metadata exceeds its aggregate limit"
    )

    assert dispatch["limit_minus_one"] == "accepted"
    assert dispatch["limit"] == "accepted"
    assert dispatch["limit_plus_one"].startswith(
        "rejected:controlled operation dispatch request exceeds"
    )
    assert durable == {
        "limit_minus_one": {
            "provider_summary": (
                "rejected:durable_provider_result_envelope_too_large"
            ),
            "worker": "accepted",
        },
        "limit": {
            "provider_summary": (
                "rejected:durable_provider_result_envelope_too_large"
            ),
            "worker": "accepted",
        },
        "limit_plus_one": {
            "provider_summary": (
                "rejected:durable_provider_bounded_summary_too_large"
            ),
            "worker": "rejected:durable result envelope exceeds its closed size bound",
        },
    }
    assert provider_document == {
        "limit_minus_one": "accepted",
        "limit": "accepted",
        "limit_plus_one": "rejected:durable_provider_transcript_size_invalid",
    }
    expected_control = {
        "core": "accepted",
        "engine": "accepted",
        "pipeline": "accepted",
    }
    assert control_frame["limit_minus_one"] == expected_control
    assert control_frame["limit"] == expected_control
    assert control_frame["limit_plus_one"] == {
        "core": "rejected:sandbox_transport_request_too_large",
        "engine": "rejected:sandbox_transport_request_too_large",
        "pipeline": "rejected:sandbox_transport_request_too_large",
    }
    assert observation.counts.effect_count == 0
    assert factory.external_effect_ledger.entries() == ()
