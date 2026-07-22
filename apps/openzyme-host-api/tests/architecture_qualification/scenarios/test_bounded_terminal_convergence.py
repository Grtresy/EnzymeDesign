from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openzyme_core import DURABLE_RESULT_ENVELOPE_MAX_BYTES
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.durable_routes import durable_adapter_policy_id

from ..composition import ProductionCompositionFactory
from ..driver import QualificationDriver
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent
from ..probes import probe_bulk_identity_artifactization


_HMMER_ROUTE_ID = "bio.hmmer_search.provider:v1"
_HMMER_COLUMNS = (
    "target",
    "accession",
    "evalue",
    "score",
    "page",
    "hit_index",
    "evalue_numeric",
    "score_numeric",
    "raw_page_digest",
    "raw_hit_digest",
    "parsed_row_digest",
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _bulk_hmmer_result(
    *,
    hmm_artifact_id: str,
    candidate_count: int = 4_096,
) -> tuple[dict[str, object], tuple[str, ...], bytes]:
    candidates = tuple(
        f"QUALIFICATION_{index:05d}_{'A' * 56}" for index in range(candidate_count)
    )
    raw_page_digest = _sha256_bytes(b"qualification-controlled-hmmer-page")
    rows = [",".join(_HMMER_COLUMNS)]
    for index, accession in enumerate(candidates):
        raw_hit_digest = _sha256_bytes(f"raw-hit:{index}".encode("utf-8"))
        row_digest = _sha256_bytes(
            f"{accession}:{index}:{raw_hit_digest}".encode("utf-8")
        )
        rows.append(
            ",".join(
                (
                    accession,
                    accession,
                    "1e-20",
                    "100.0",
                    "1",
                    str(index),
                    "1e-20",
                    "100.0",
                    raw_page_digest,
                    raw_hit_digest,
                    row_digest,
                )
            )
        )
    parsed_csv = ("\n".join(rows) + "\n").encode("utf-8")
    parsed_digest = _sha256_bytes(parsed_csv)
    raw_payload = canonical_json_bytes(
        {
            "provider": "ebi_hmmer",
            "qualification_fixture_non_cutover": True,
            "record_count": candidate_count,
        }
    )
    result = {
        "api_version": "qualification_fixture_non_cutover",
        "artifacts": [
            {
                "content": raw_payload.decode("utf-8"),
                "format": "json",
                "kind": "result",
                "metadata": {
                    "raw_response_schema_id": (
                        "provider_raw_http_response_set@1"
                    ),
                },
                "relative_path": "provider_raw/raw_hits.json",
                "title": "raw_hits.json",
            },
            {
                "content": parsed_csv.decode("utf-8"),
                "format": "csv",
                "kind": "result",
                "metadata": {
                    "parsed_hit_schema_id": "ebi_hmmer_refprot_hit@1",
                    "parsed_hits_digest": parsed_digest,
                    "required_columns": list(_HMMER_COLUMNS),
                },
                "relative_path": "provider_parsed/parsed_hits.csv",
                "title": "parsed_hits.csv",
            },
        ],
        "operation": "bio.hmmer_search",
        "provider": "ebi_hmmer",
        "provider_observation": {
            "pagination": {"page_count": 1, "truncated": False},
            "parsed_hits_digest": parsed_digest,
            "transport": "controlled_non_cutover",
        },
        "summary": {
            "database": "refprot",
            "hit_count": candidate_count,
            "pagination": {
                "page_count": 1,
                "truncated": False,
            },
            "parsed_hit_schema_id": "ebi_hmmer_refprot_hit@1",
            "parsed_hits_digest": parsed_digest,
            "provider": "ebi_hmmer",
            "query_hmm_artifact_id": hmm_artifact_id,
            "warning_count": 0,
        },
        "warnings": [],
    }
    return result, candidates, parsed_csv


def _envelope_with_exact_size(target_size: int) -> dict[str, object]:
    envelope: dict[str, object] = {"payload": [], "status": "succeeded"}
    payload = envelope["payload"]
    assert isinstance(payload, list)
    if target_size < len(canonical_json_bytes(envelope)):
        raise ValueError("target envelope size is too small")
    unit = "x" * 512
    while True:
        current_size = len(canonical_json_bytes(envelope))
        separator_size = 2 if not payload else 3
        remaining_value_size = target_size - current_size - separator_size
        if remaining_value_size <= len(unit):
            if remaining_value_size < 0:
                raise AssertionError("qualification envelope sizing overshot")
            payload.append("x" * remaining_value_size)
            break
        payload.append(unit)
    if len(canonical_json_bytes(envelope)) != target_size:
        raise AssertionError("qualification envelope size calibration drifted")
    return envelope


@pytest.mark.architecture_qualification_scenario(
    scenario_id="bounded-terminal-convergence.bulk-and-invalid-terminal",
    family="bounded-terminal-convergence",
    selections=("full", "premerge_subset"),
)
def test_bulk_identity_stays_compact_and_invalid_terminal_converges_once(
    tmp_path: Path,
) -> None:
    bulk_probe = probe_bulk_identity_artifactization()
    assert bulk_probe.artifact_count == 4_096
    assert bulk_probe.compact_envelope_size < bulk_probe.owner_limit
    assert bulk_probe.expanded_identity_size > bulk_probe.owner_limit
    assert bulk_probe.owner_limit == DURABLE_RESULT_ENVELOPE_MAX_BYTES

    factory = ProductionCompositionFactory.create(tmp_path / "bounded-convergence")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)

        driver.create_session("sess_bounded_bulk")
        hmm_input = driver.seal_external_input(
            session_id="sess_bounded_bulk",
            filename="qualification_model.hmm",
            content=(
                "HMMER3/f [qualification | deterministic]\n"
                "NAME  QUALIFICATION\n"
                "LENG  1\n"
                "//\n"
            ),
            format="hmm",
        )
        hmm_artifact_id = str(hmm_input["artifact_id"])
        bulk_result, candidates, parsed_csv = _bulk_hmmer_result(
            hmm_artifact_id=hmm_artifact_id
        )
        assert len(canonical_json_bytes(list(candidates))) > (
            DURABLE_RESULT_ENVELOPE_MAX_BYTES
        )
        assert len(parsed_csv) > DURABLE_RESULT_ENVELOPE_MAX_BYTES
        bulk_ids = driver.admit_durable_operation(
            session_id="sess_bounded_bulk",
            scenario_key="bulk_hmmer_identity_artifactization",
            route_policy_id=_HMMER_ROUTE_ID,
            selected_backend="provider_http",
            adapter_policy_id=durable_adapter_policy_id(_HMMER_ROUTE_ID),
            backend_category="provider_http",
            sdk_module="bio",
            function_name="hmmer_search",
            request_envelope={
                "adapter_params": {
                    "database": "refprot",
                    "hmm_artifact_id": hmm_artifact_id,
                    "output_dir": "/workspace/output/provider/hmmer",
                    "params": {"max_hits": len(candidates)},
                },
                "schema_version": "s12.adapter_envelope.v1",
            },
        )
        driver.queue_external(
            "bio.provider_http",
            "hmmer_search",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=bulk_result,
            ),
        )
        driver.resolve_approval(bulk_ids.approval_id)
        bulk_ready = driver.run_execution_once(
            bulk_ids.execution_id,
            worker_id="qualification:bounded-bulk",
        )
        bulk_terminal = driver.run_execution_once(
            bulk_ids.execution_id,
            worker_id="qualification:bounded-bulk",
        )
        bulk_records = driver.canonical_records(bulk_ids)

        driver.create_session("sess_bounded_exact_limit")
        exact_ids = driver.admit_durable_operation(
            session_id="sess_bounded_exact_limit",
            scenario_key="exact_result_envelope_limit",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        exact_envelope = _envelope_with_exact_size(
            DURABLE_RESULT_ENVELOPE_MAX_BYTES
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=materialized_observation_response(
                    bounded_result_envelope=exact_envelope,
                    backend_handle_ref=None,
                ),
            ),
        )
        driver.resolve_approval(exact_ids.approval_id)
        exact_ready = driver.run_execution_once(
            exact_ids.execution_id,
            worker_id="qualification:bounded-exact",
        )
        exact_terminal = driver.run_execution_once(
            exact_ids.execution_id,
            worker_id="qualification:bounded-exact",
        )
        exact_records = driver.canonical_records(exact_ids)

        driver.create_session("sess_bounded_invalid_terminal")
        invalid_ids = driver.admit_durable_operation(
            session_id="sess_bounded_invalid_terminal",
            scenario_key="oversized_terminal_observation",
            route_policy_id="qualification.provider:v1",
            selected_backend="qualification_provider",
            adapter_policy_id="qualification_provider_adapter:v1",
        )
        oversized_envelope = _envelope_with_exact_size(
            DURABLE_RESULT_ENVELOPE_MAX_BYTES + 1
        )
        driver.queue_external(
            "bio.provider_http",
            "dispatch",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                effect_attempted=True,
                response=materialized_observation_response(
                    bounded_result_envelope=oversized_envelope,
                    backend_handle_ref=None,
                ),
            ),
        )
        driver.resolve_approval(invalid_ids.approval_id)
        invalid_terminal = driver.run_execution_once(
            invalid_ids.execution_id,
            worker_id="qualification:bounded-invalid-terminal",
        )
        invalid_not_claimable = driver.run_execution_once(
            invalid_ids.execution_id,
            worker_id="qualification:bounded-invalid-terminal",
        )
        invalid_records = driver.canonical_records(invalid_ids)
        observation = collect_observation(
            running,
            session_ids=(
                "sess_bounded_bulk",
                "sess_bounded_exact_limit",
                "sess_bounded_invalid_terminal",
            ),
        )

    assert bulk_ready["action"] == "dispatch"
    assert bulk_ready["lifecycle_state"] == "result_ready"
    assert bulk_terminal["lifecycle_state"] == "terminal"
    bulk_envelope = bulk_records["result"]["bounded_result_envelope"]  # type: ignore[index]
    assert len(canonical_json_bytes(bulk_envelope)) < DURABLE_RESULT_ENVELOPE_MAX_BYTES
    assert "candidate_accessions" not in json.dumps(bulk_envelope, sort_keys=True)
    assert bulk_envelope["bounded_summary"]["hit_count"] == len(candidates)  # type: ignore[index]
    assert bulk_envelope["bounded_summary"]["parsed_hits_digest"] == (  # type: ignore[index]
        _sha256_bytes(parsed_csv)
    )
    parsed_artifact = next(
        artifact
        for artifact in bulk_records["artifacts"]  # type: ignore[union-attr]
        if str(artifact["relative_path"]).endswith("provider_parsed/parsed_hits.csv")
    )
    parsed_bytes = Path(str(parsed_artifact["storage_uri"])).read_bytes()
    assert parsed_bytes == parsed_csv
    assert parsed_artifact["metadata"]["content_digest"] == _sha256_bytes(  # type: ignore[index]
        parsed_bytes
    )
    assert str(parsed_artifact["artifact_id"]) in {
        str(item["artifact_id"])
        for item in bulk_records["result_artifacts"]  # type: ignore[union-attr]
    }

    assert exact_ready["lifecycle_state"] == "result_ready"
    assert exact_terminal["lifecycle_state"] == "terminal"
    assert len(
        canonical_json_bytes(
            exact_records["result"]["bounded_result_envelope"]  # type: ignore[index]
        )
    ) == DURABLE_RESULT_ENVELOPE_MAX_BYTES

    assert invalid_terminal["action"] == "dispatch"
    assert invalid_terminal["lifecycle_state"] == "terminal"
    assert invalid_not_claimable["action"] == "not_claimable"
    assert invalid_records["execution"]["terminal_outcome"] == (  # type: ignore[index]
        "recovery_failed"
    )
    assert invalid_records["execution"]["error_code"] == (  # type: ignore[index]
        "durable_terminal_observation_invalid"
    )
    assert invalid_records["result"]["bounded_result_envelope"][  # type: ignore[index]
        "error_code"
    ] == "durable_terminal_observation_invalid"
    invalid_envelope = {
        "error_code": "durable_terminal_observation_invalid",
        "output_artifact_ids": [],
        "safe_error_summary": (
            "Terminal route observation failed closed validation."
        ),
        "status": "recovery_failed",
    }
    assert invalid_records["result"]["bounded_result_envelope"] == (  # type: ignore[index]
        invalid_envelope
    )
    assert len(invalid_records["events"]) <= 8  # type: ignore[arg-type]
    assert_operation_oracle(
        bulk_records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=bulk_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    assert_operation_oracle(
        exact_records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="succeeded",
        expected_envelope=exact_envelope,
        expected_result_ready_transitions=1,
        expected_terminal_transitions=1,
    )
    assert_operation_oracle(
        invalid_records,
        expected_lifecycle="terminal",
        expected_terminal_outcome="recovery_failed",
        expected_envelope=invalid_envelope,
        expected_result_ready_transitions=0,
        expected_terminal_transitions=1,
    )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "dispatch"): 2,
            ("bio.provider_http", "hmmer_search"): 1,
        },
        expected_effect_count=3,
    )
    assert_public_authority_absent(observation.payload["public_projection"])
