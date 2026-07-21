from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib import parse as urllib_parse

import pytest

from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_engines.execution import BioProviderHttpConfig
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_engines.execution import ProviderHttpBioDatabaseAdapter


AOX_REFERENCE_ACCESSIONS = (
    "AAC72747.1",
    "KDQ24956.1",
    "9AVH_A",
    "XP_014653549.1",
    "KIS68002.1",
    "XP_003660923.1",
    "AMW87253.1",
    "AFP17823.1",
    "WP_190019735.1",
    "WP_138089821.1",
    "WP_176407597.1",
    "CAQ19343.1",
    "CAQ19344.1",
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_http"
HMMER_OFFICIAL_RESULT_FIXTURE = FIXTURE_DIR / "ebi_hmmer_refprot_result.json"


class FakeHttpResponse:
    def __init__(
        self,
        *,
        body: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body.encode("utf-8")

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def read(self) -> bytes:
        return self._body


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _canonical_json_digest(value: Any) -> str:
    return _digest(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _fixture_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _artifact(result: Any, relative_path: str) -> Any:
    return next(
        artifact
        for artifact in result.artifacts
        if artifact.relative_path == relative_path
    )


def _raw_response_set(result: Any) -> tuple[Any, dict[str, Any]]:
    matches: list[tuple[Any, dict[str, Any]]] = []
    for artifact in result.artifacts:
        try:
            payload = json.loads(artifact.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema_id") == "provider_raw_http_response_set@1"
        ):
            matches.append((artifact, payload))
    assert len(matches) == 1
    return matches[0]


def _assert_offline_recomputable_raw_responses(
    result: Any,
    *,
    expected_bodies: tuple[str, ...],
) -> dict[str, Any]:
    artifact, payload = _raw_response_set(result)
    assert artifact.metadata["raw_response_schema_id"] == (
        "provider_raw_http_response_set@1"
    )
    assert payload["provider"] == result.provider
    assert payload["operation"] == result.operation
    responses = payload["responses"]
    assert isinstance(responses, list) and responses

    decoded_by_digest: dict[str, bytes] = {}
    for ordinal, response in enumerate(responses, start=1):
        assert response["ordinal"] == ordinal
        assert response["body_encoding"] == "base64"
        decoded = base64.b64decode(response["body_base64"], validate=True)
        recomputed = f"sha256:{hashlib.sha256(decoded).hexdigest()}"
        assert response["body_digest"] == recomputed
        assert response["size_bytes"] == len(decoded)
        decoded_by_digest[recomputed] = decoded

    for body in expected_bodies:
        digest = _digest(body)
        assert decoded_by_digest[digest] == body.encode("utf-8")
    return payload


def _aox_fasta(*, omit: str | None = None, duplicate: str | None = None) -> str:
    lines: list[str] = []
    for index, accession in enumerate(reversed(AOX_REFERENCE_ACCESSIONS)):
        if accession == omit:
            continue
        header = "pdb|9AVH|A" if accession == "9AVH_A" else accession
        lines.extend((f">{header} reference {index}", "M" + "A" * (index + 1)))
        if accession == duplicate:
            lines.extend((f">{header} duplicate", "M" + "A" * (index + 1)))
    return "\n".join(lines) + "\n"


def test_ncbi_aox_references_prove_one_to_one_identity_and_digests() -> None:
    response_body = _aox_fasta()
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=response_body,
            headers={"x-request-id": "ncbi-request-1"},
        ),
        sleep=lambda _seconds: None,
    )

    result = adapter.ncbi_fetch_proteins(
        accessions=AOX_REFERENCE_ACCESSIONS,
        fields=("definition",),
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    metadata_artifact = _artifact(
        result,
        "provider_parsed/proteins.metadata.json",
    )
    metadata = json.loads(metadata_artifact.content)
    assert result.summary["identity_complete"] is True
    assert result.summary["record_count"] == 13
    assert metadata["requested_accessions"] == list(AOX_REFERENCE_ACCESSIONS)
    assert [record["requested_accession"] for record in metadata["records"]] == list(
        AOX_REFERENCE_ACCESSIONS
    )
    pdb_record = next(
        record
        for record in metadata["records"]
        if record["requested_accession"] == "9AVH_A"
    )
    assert pdb_record["resolved_accession"] == "pdb|9AVH|A"
    assert pdb_record["normalized_resolved_accession"] == "9AVH_A"
    assert pdb_record["resolution_rule"] == "ncbi_pdb_chain_pipe@1"
    assert all(
        record["sequence_digest"].startswith("sha256:")
        for record in metadata["records"]
    )
    assert all(
        record["fasta_record_digest"].startswith("sha256:")
        for record in metadata["records"]
    )
    parsed_fasta = _artifact(result, "provider_parsed/proteins.fasta")
    assert parsed_fasta.content.startswith(">AAC72747.1")
    assert metadata["aggregate_fasta_digest"] == _digest(parsed_fasta.content)
    assert parsed_fasta.metadata["aggregate_fasta_digest"] == _digest(
        parsed_fasta.content
    )
    sequence_digest_index = {
        record["requested_accession"]: record["sequence_digest"]
        for record in metadata["records"]
    }
    assert "sequence_digests" not in parsed_fasta.metadata
    assert parsed_fasta.metadata["sequence_digest_count"] == 13
    assert parsed_fasta.metadata["sequence_digest_index_digest"] == (
        _canonical_json_digest(sequence_digest_index)
    )
    assert (
        parsed_fasta.metadata["sequence_digest_index_contract_id"]
        == "canonical_sequence_digest_index@1"
    )
    _assert_offline_recomputable_raw_responses(
        result,
        expected_bodies=(response_body,),
    )


@pytest.mark.parametrize(
    ("body", "detail_key"),
    [
        (_aox_fasta(omit="CAQ19344.1"), "missing_accessions"),
        (_aox_fasta(duplicate="AAC72747.1"), "duplicate_requested_mappings"),
        (
            _aox_fasta().replace(">CAQ19344.1", ">UNEXPECTED.1", 1),
            "unexpected_resolved_accessions",
        ),
    ],
)
def test_ncbi_rejects_incomplete_duplicate_or_mismatched_identity(
    body: str,
    detail_key: str,
) -> None:
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=lambda _request, timeout: FakeHttpResponse(body=body),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.ncbi_fetch_proteins(
            accessions=AOX_REFERENCE_ACCESSIONS,
            fields=(),
            retrieved_at="2026-07-17T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_identity_mismatch"
    assert exc_info.value.stage == "provider_response_validation"
    assert exc_info.value.details[detail_key]
    assert exc_info.value.details["response_digest"].startswith("sha256:")


def _hmm_artifact(tmp_path: Path) -> SessionArtifactRecord:
    content = "HMMER3/f [3.4]\nNAME AOX\n//\n"
    path = tmp_path / "AOX.hmm"
    path.write_text(content, encoding="utf-8")
    return SessionArtifactRecord(
        artifact_id="art_aox_hmm",
        session_id="sess_aox",
        task_id="task_aox",
        lane_id="lane_aox",
        invocation_id="inv_hmmbuild",
        run_id="run_hmmbuild",
        kind=ArtifactKind.RESULT,
        storage_uri=str(path),
        relative_path="aox/AOX.hmm",
        created_at="2026-07-17T00:00:00+00:00",
        metadata={"content_digest": _digest(content)},
    )


def _hmmer_payload(hit: dict[str, Any]) -> str:
    return json.dumps(
        {
            "status": "SUCCESS",
            "page_count": 1,
            "result": {
                "stats": {
                    "nhits": 1,
                    "nreported": 1,
                    "provider_extension": "allowed",
                },
                "hits": [hit],
            },
        }
    )


def _hmmer_adapter(
    result_body: str,
    *,
    requests: list[Any] | None = None,
) -> ProviderHttpBioDatabaseAdapter:
    responses = iter(
        (
            FakeHttpResponse(body='{"id":"fdaf751e-bf95-4e6a-a70a-6eadf2078ae2"}'),
            FakeHttpResponse(
                body=result_body, headers={"x-request-id": "ebi-result-1"}
            ),
            FakeHttpResponse(
                body=result_body, headers={"x-request-id": "ebi-result-page-1"}
            ),
        )
    )

    def urlopen(request: Any, timeout: float) -> FakeHttpResponse:
        del timeout
        if requests is not None:
            requests.append(request)
        return next(responses)

    return ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ebi_hmmer_email="operator@example.test"),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )


def test_ebi_hmmer_submit_uses_official_email_address_field(tmp_path: Path) -> None:
    requests: list[Any] = []
    _hmmer_adapter(
        _fixture_text(HMMER_OFFICIAL_RESULT_FIXTURE),
        requests=requests,
    ).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={},
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    submit_payload = json.loads(requests[0].data.decode("utf-8"))
    assert submit_payload["email_address"] == "operator@example.test"
    assert "email" not in submit_payload


def test_ebi_refprot_accepts_official_shape_and_binds_top_level_accession(
    tmp_path: Path,
) -> None:
    response_body = _fixture_text(HMMER_OFFICIAL_RESULT_FIXTURE)
    result = _hmmer_adapter(response_body).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={"E": "1e-20", "max_hits": 10},
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    parsed = _artifact(result, "provider_parsed/parsed_hits.csv")
    rows = list(__import__("csv").DictReader(parsed.content.splitlines()))
    assert len(rows) == 1
    row = rows[0]
    assert row["accession"] == "P12345"
    assert row["target"] == "AOX_EXAMPLE"
    assert row["evalue"] == "1e-42"
    assert row["evalue_numeric"] == "1E-42"
    assert row["score_numeric"] == "1834.7"
    assert row["raw_page_digest"] == _digest(response_body)
    assert row["raw_hit_digest"].startswith("sha256:")
    assert row["parsed_row_digest"].startswith("sha256:")
    assert parsed.metadata["parsed_hits_digest"] == _digest(parsed.content)
    observation = result.provider_observation or {}
    assert observation["operation"] == "bio.hmmer_search"
    assert observation["request_identity"]["query_hmm_artifact_id"] == "art_aox_hmm"
    assert observation["raw_page_digests"] == {"1": _digest(response_body)}
    assert "candidate_accessions" not in result.summary
    raw_payload = _assert_offline_recomputable_raw_responses(
        result,
        expected_bodies=(
            '{"id":"fdaf751e-bf95-4e6a-a70a-6eadf2078ae2"}',
            response_body,
        ),
    )
    phases = {response["phase"] for response in raw_payload["responses"]}
    assert "submit" in phases
    assert len(phases) >= 2


def test_ebi_refprot_accepts_current_ten_character_metadata_accession(
    tmp_path: Path,
) -> None:
    payload = json.loads(_fixture_text(HMMER_OFFICIAL_RESULT_FIXTURE))
    hit = payload["result"]["hits"][0]
    hit["acc"] = None
    hit["name"] = "087736296"
    hit["metadata"] = {
        "accession": "A0A378ARX6",
        "uniprot_accession": "A0A378ARX6",
        "uniprot_identifier": "A0A378ARX6_KLEPO",
    }
    response_body = json.dumps(payload)

    result = _hmmer_adapter(response_body).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={"max_hits": 1},
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    assert "candidate_accessions" not in result.summary
    parsed = _artifact(result, "provider_parsed/parsed_hits.csv")
    row = next(__import__("csv").DictReader(parsed.content.splitlines()))
    assert row["accession"] == "A0A378ARX6"
    assert row["target"] == "A0A378ARX6_KLEPO"


@pytest.mark.parametrize(
    "hit",
    [
        {
            "name": "hit",
            "acc": "NOT_A_UNIPROT_ACCESSION",
            "evalue": 1e-9,
            "score": 100.0,
        },
        {
            "name": "hit",
            "acc": "P12345",
            "evalue": 1e-9,
            "score": "NaN",
        },
    ],
)
def test_ebi_refprot_rejects_accession_or_numeric_schema_drift(
    tmp_path: Path,
    hit: dict[str, Any],
) -> None:
    with pytest.raises(PipelineSdkFailure) as exc_info:
        _hmmer_adapter(_hmmer_payload(hit)).hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={},
            retrieved_at="2026-07-17T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.sdk_method == "bio.hmmer_search"
    assert exc_info.value.details["provider"] == "ebi_hmmer"


def _hmmer_hits(start: int, count: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"AOX_{index:05d}",
            "acc": f"P{index:05d}",
            "evalue": 1e-20,
            "score": float(10_000 - index),
        }
        for index in range(start, start + count)
    ]


def _hmmer_result_body(
    hits: list[dict[str, Any]],
    *,
    page_count: int,
    nreported: int,
) -> str:
    return json.dumps(
        {
            "status": "SUCCESS",
            "page_count": page_count,
            "result": {
                "stats": {"nhits": nreported, "nreported": nreported},
                "hits": hits,
            },
        }
    )


def test_ebi_hmmer_terminal_poll_is_status_only_and_explicit_pages_are_complete(
    tmp_path: Path,
) -> None:
    terminal_body = _hmmer_result_body(
        _hmmer_hits(0, 50),
        page_count=3,
        nreported=2050,
    )
    page_bodies = [
        _hmmer_result_body(_hmmer_hits(0, 1000), page_count=3, nreported=2050),
        _hmmer_result_body(_hmmer_hits(1000, 1000), page_count=3, nreported=2050),
        _hmmer_result_body(_hmmer_hits(2000, 50), page_count=3, nreported=2050),
    ]
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-complete"}'),
            FakeHttpResponse(body=terminal_body),
            *(FakeHttpResponse(body=body) for body in page_bodies),
        ]
    )
    requested_urls: list[str] = []

    def urlopen(request: Any, timeout: float) -> FakeHttpResponse:
        del timeout
        requested_urls.append(request.full_url)
        return next(responses)

    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={},
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    result_urls = requested_urls[1:]
    assert len(result_urls) == 4
    assert all("page_size=1000" in url for url in result_urls)
    assert "page=1" in result_urls[0]
    assert [
        urllib_parse.parse_qs(urllib_parse.urlparse(url).query)["page"][0]
        for url in result_urls[1:]
    ] == [
        "1",
        "2",
        "3",
    ]
    assert result.summary["reported_hit_count"] == 2050
    assert result.summary["retrieved_raw_hit_count"] == 2050
    assert result.summary["hit_count"] == 2050
    assert "candidate_accessions" not in result.summary
    parsed = _artifact(result, "provider_parsed/parsed_hits.csv")
    rows = list(__import__("csv").DictReader(parsed.content.splitlines()))
    assert len(rows) == 2050
    assert rows[50]["accession"] == "P00050"


def test_ebi_hmmer_rejects_missing_middle_page_by_terminal_count(
    tmp_path: Path,
) -> None:
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-gapped"}'),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=3, nreported=4)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=3, nreported=4)
            ),
            FakeHttpResponse(body=_hmmer_result_body([], page_count=3, nreported=4)),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(3, 1), page_count=3, nreported=4)
            ),
        ]
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(hmmer_page_size=2),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={},
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_partial_result"
    assert exc_info.value.details["page"] == 2
    assert exc_info.value.details["page_count"] == 3
    assert exc_info.value.details["page_size"] == 2
    assert exc_info.value.details["hit_count"] == 0


def test_ebi_hmmer_rejects_short_nonterminal_page_before_max_hits_truncation(
    tmp_path: Path,
) -> None:
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-short-before-limit"}'),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=5, nreported=10)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=5, nreported=10)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(2, 1), page_count=5, nreported=10)
            ),
        ]
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(hmmer_page_size=2, hmmer_max_hits=3),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={},
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_partial_result"
    assert exc_info.value.details["page"] == 2
    assert exc_info.value.details["page_count"] == 5
    assert exc_info.value.details["page_size"] == 2
    assert exc_info.value.details["hit_count"] == 1


def test_ebi_hmmer_rejects_page_count_drift(tmp_path: Path) -> None:
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-page-drift"}'),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=2, nreported=4)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=2, nreported=4)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(2, 2), page_count=3, nreported=4)
            ),
        ]
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(hmmer_page_size=2),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={},
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.details["expected_page_count"] == 2
    assert exc_info.value.details["actual_page_count"] == 3


def test_ebi_hmmer_rejects_result_page_nreported_drift(tmp_path: Path) -> None:
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-nreported-drift"}'),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=2, nreported=4)
            ),
            FakeHttpResponse(
                body=_hmmer_result_body(_hmmer_hits(0, 2), page_count=2, nreported=3)
            ),
        ]
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(hmmer_page_size=2),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={},
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.details["page"] == 1
    assert exc_info.value.details["expected_reported_hit_count"] == 4
    assert exc_info.value.details["actual_reported_hit_count"] == 3


def test_ebi_hmmer_accepts_exact_zero_reported_hits(tmp_path: Path) -> None:
    empty_body = _hmmer_result_body([], page_count=0, nreported=0)
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-empty"}'),
            FakeHttpResponse(body=empty_body),
            FakeHttpResponse(body=empty_body),
        ]
    )
    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    ).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={},
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    assert result.summary["hit_count"] == 0
    assert result.summary["reported_hit_count"] == 0
    assert result.summary["pagination"]["declared_page_count"] == 0
    assert [warning["warning_code"] for warning in result.warnings] == ["empty_results"]


def test_ebi_hmmer_bounded_prefix_marks_truncation_from_terminal_count(
    tmp_path: Path,
) -> None:
    bounded_body = _hmmer_result_body(
        _hmmer_hits(0, 1),
        page_count=1,
        nreported=2,
    )
    responses = iter(
        [
            FakeHttpResponse(body='{"id":"job-bounded-prefix"}'),
            FakeHttpResponse(body=bounded_body),
            FakeHttpResponse(body=bounded_body),
        ]
    )
    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(hmmer_page_size=1, hmmer_max_hits=1),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    ).hmmer_search(
        hmm_artifact=_hmm_artifact(tmp_path),
        database="refprot",
        params={},
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    assert result.summary["reported_hit_count"] == 2
    assert result.summary["retrieved_raw_hit_count"] == 1
    assert result.summary["pagination"]["truncated"] is True
    assert result.warnings == (
        {
            "warning_code": "provider_result_truncated",
            "stage": "provider_pagination",
            "hint": "Only the top S13-capped HMMER hits were artifactized.",
            "limit": 1,
        },
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("max_hits", True),
        ("max_hits", 2.5),
        ("max_hits", []),
        ("page_size", False),
        ("page_size", 1.5),
        ("page_size", {}),
    ],
)
def test_ebi_hmmer_rejects_numeric_params_that_would_be_silently_coerced(
    tmp_path: Path,
    key: str,
    value: object,
) -> None:
    def unexpected_request(_request: Any, timeout: float) -> FakeHttpResponse:
        del timeout
        raise AssertionError("invalid HMMER params must fail before provider I/O")

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=unexpected_request,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.hmmer_search(
            hmm_artifact=_hmm_artifact(tmp_path),
            database="refprot",
            params={key: value},
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_invalid_request"
    assert exc_info.value.stage == "provider_request_validation"
    assert exc_info.value.details == {"provider": "ebi_hmmer", key: str(value)}


def _uniprot_record(
    accession: str,
    sequence: str,
    *,
    secondary_accessions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "entryType": "UniProtKB reviewed (Swiss-Prot)",
        "primaryAccession": accession,
        "secondaryAccessions": secondary_accessions or [],
        "uniProtkbId": f"{accession}_AOX",
        "entryAudit": {"entryVersion": 12, "sequenceVersion": 3},
        "sequence": {"value": sequence, "length": len(sequence)},
    }


def _uniprot_inactive_deleted_record(
    accession: str,
    *,
    deleted_reason: str = "Not part of a reference proteome",
    uniparc_id: str = "UPI000453BEA2",
) -> dict[str, Any]:
    return {
        "entryType": "Inactive",
        "primaryAccession": accession,
        "uniProtkbId": f"{accession}_AOX",
        "inactiveReason": {
            "inactiveReasonType": "DELETED",
            "deletedReason": deleted_reason,
            "providerExtension": "allowed",
        },
        "extraAttributes": {
            "uniParcId": uniparc_id,
            "providerExtension": "allowed",
        },
        "providerExtension": "allowed",
    }


def _uniprot_inactive_merged_record(
    accession: str,
    *,
    replacement_targets: list[str] | None = None,
    uniparc_id: str = "UPI000A0F4040",
) -> dict[str, Any]:
    return {
        "entryType": "Inactive",
        "primaryAccession": accession,
        "uniProtkbId": f"{accession}_AOX",
        "inactiveReason": {
            "inactiveReasonType": "MERGED",
            "mergeDemergeTo": replacement_targets or ["P18173"],
            "providerExtension": "allowed",
        },
        "extraAttributes": {
            "uniParcId": uniparc_id,
            "providerExtension": "allowed",
        },
        "providerExtension": "allowed",
    }


def test_uniprot_batches_one_operation_across_bounded_search_queries() -> None:
    accessions = tuple(f"P{index:05d}" for index in range(205))
    observed_batches: list[tuple[str, ...]] = []
    response_bodies: list[str] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        parsed = urllib_parse.urlparse(request.full_url)
        query = urllib_parse.parse_qs(parsed.query)["query"][0]
        query_accessions = tuple(re.findall(r"accession:([A-Z0-9]+)", query))
        observed_batches.append(query_accessions)
        assert len(request.full_url.encode("utf-8")) < 4096
        body = json.dumps(
            {
                "results": [
                    _uniprot_record(accession, "MPEPTIDE")
                    for accession in query_accessions
                ]
            }
        )
        response_bodies.append(body)
        return FakeHttpResponse(
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        )

    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=accessions,
        fields=(),
        batch_size=100,
        retrieved_at="2026-07-19T00:00:00+00:00",
    )

    metadata = json.loads(_artifact(result, "provider_parsed/metadata.json").content)
    assert [len(batch) for batch in observed_batches] == [100, 100, 5]
    assert (
        tuple(accession for batch in observed_batches for accession in batch)
        == accessions
    )
    assert metadata["requested_accessions"] == list(accessions)
    assert [record["requested_accession"] for record in metadata["records"]] == list(
        accessions
    )
    assert result.summary["accession_count"] == 205
    assert result.summary["identity_complete"] is True
    assert result.summary["pagination"] == {
        "page_count": 3,
        "page_size": 100,
        "page_cap_per_query": 100,
        "query_batch_count": 3,
        "query_batch_size_cap": 100,
    }
    requests = result.provider_observation["requests"]
    assert [request["query_batch_index"] for request in requests] == [1, 2, 3]
    assert [request["query_accession_start"] for request in requests] == [0, 100, 200]
    assert [request["query_accession_count"] for request in requests] == [100, 100, 5]
    assert all(
        str(request["query_accessions_digest"]).startswith("sha256:")
        for request in requests
    )
    _assert_offline_recomputable_raw_responses(
        result,
        expected_bodies=tuple(response_bodies),
    )


def test_uniprot_large_sequence_index_stays_out_of_fasta_artifact_metadata() -> None:
    accessions = tuple(f"P{index:05d}" for index in range(5_000))

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        parsed = urllib_parse.urlparse(request.full_url)
        query = urllib_parse.parse_qs(parsed.query)["query"][0]
        query_accessions = tuple(re.findall(r"accession:([A-Z0-9]+)", query))
        return FakeHttpResponse(
            body=json.dumps(
                {
                    "results": [
                        _uniprot_record(accession, "MPEPTIDE")
                        for accession in query_accessions
                    ]
                }
            ),
            headers={"x-uniprot-release": "2026_03"},
        )

    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=accessions,
        fields=(),
        batch_size=100,
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    metadata_payload = json.loads(
        _artifact(result, "provider_parsed/metadata.json").content
    )
    sequence_digest_index = {
        record["primary_accession"]: record["sequence_digest"]
        for record in metadata_payload["records"]
    }
    fasta_artifact = _artifact(result, "provider_parsed/sequences.fasta")
    encoded_fasta_metadata = json.dumps(
        fasta_artifact.metadata,
        sort_keys=True,
    ).encode("utf-8")

    assert len(metadata_payload["records"]) == 5_000
    assert len(sequence_digest_index) == 5_000
    assert len(json.dumps(sequence_digest_index).encode("utf-8")) > 256 * 1024
    assert len(encoded_fasta_metadata) < 256 * 1024
    assert "sequence_digests" not in fasta_artifact.metadata
    assert fasta_artifact.metadata["sequence_digest_count"] == 5_000
    assert fasta_artifact.metadata["sequence_digest_index_digest"] == (
        _canonical_json_digest(sequence_digest_index)
    )
    assert (
        fasta_artifact.metadata["sequence_digest_index_contract_id"]
        == "canonical_sequence_digest_index@1"
    )


def test_uniprot_real_scale_preflight_is_linear_and_partitions_37772() -> None:
    config = BioProviderHttpConfig()
    adapter = ProviderHttpBioDatabaseAdapter(
        config,
        urlopen=lambda _request, timeout: pytest.fail(  # noqa: ARG005
            "real-scale preflight must not contact UniProt"
        ),
        sleep=lambda _seconds: None,
    )
    accessions = tuple(f"P{index:05d}" for index in range(37_772))

    normalized = adapter._normalize_accessions(
        accessions,
        provider="uniprot",
        sdk_method="bio.uniprot_fetch",
        accession_cap=config.uniprot_operation_accession_cap,
    )
    query_batches = tuple(
        normalized[offset : offset + config.batch_size_cap]
        for offset in range(0, len(normalized), config.batch_size_cap)
    )

    assert normalized == accessions
    assert len(query_batches) == 378
    assert all(len(batch) == 100 for batch in query_batches[:-1])
    assert len(query_batches[-1]) == 72

    with pytest.raises(PipelineSdkFailure) as duplicate_error:
        adapter._normalize_accessions(
            (*accessions[:-1], accessions[0]),
            provider="uniprot",
            sdk_method="bio.uniprot_fetch",
            accession_cap=config.uniprot_operation_accession_cap,
        )

    assert duplicate_error.value.error_type == "provider_duplicate_identity"
    assert duplicate_error.value.details["duplicate_accessions"] == ["P00000"]


def test_uniprot_page_cap_is_per_query_not_global() -> None:
    accessions = tuple(f"P{index:05d}" for index in range(4))
    responses = iter(
        [
            (_uniprot_record("P00000", "MPEPTIDE"), "batch-1-page-2"),
            (_uniprot_record("P00001", "MPEPTIDE"), None),
            (_uniprot_record("P00002", "MPEPTIDE"), "batch-2-page-2"),
            (_uniprot_record("P00003", "MPEPTIDE"), None),
        ]
    )

    def urlopen(_request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        record, next_ref = next(responses)
        headers = {"x-uniprot-release": "2026_03"}
        if next_ref is not None:
            headers["link"] = (
                f'<https://rest.uniprot.org/uniprotkb/search?cursor={next_ref}>; rel="next"'
            )
        return FakeHttpResponse(
            body=json.dumps({"results": [record]}),
            headers=headers,
        )

    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(
            batch_size_cap=2,
            uniprot_operation_accession_cap=10,
            uniprot_page_cap_per_query=2,
        ),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=accessions,
        fields=(),
        batch_size=1,
        retrieved_at="2026-07-19T00:00:00+00:00",
    )

    assert result.summary["pagination"] == {
        "page_count": 4,
        "page_size": 1,
        "page_cap_per_query": 2,
        "query_batch_count": 2,
        "query_batch_size_cap": 2,
    }
    assert [
        (request["query_batch_index"], request["page_in_query"])
        for request in result.provider_observation["requests"]
    ] == [(1, 1), (1, 2), (2, 1), (2, 2)]


def test_uniprot_rejects_cross_query_batch_identity_swap() -> None:
    responses = iter(
        [
            _uniprot_record("P00001", "MPEPTIDE"),
            _uniprot_record("P00000", "MPEPTIDE"),
        ]
    )

    def urlopen(_request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        return FakeHttpResponse(
            body=json.dumps({"results": [next(responses)]}),
            headers={"x-uniprot-release": "2026_03"},
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(
            batch_size_cap=1,
            uniprot_operation_accession_cap=10,
        ),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P00000", "P00001"),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-19T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_identity_mismatch"
    assert exc_info.value.details["matched_requested_accessions"] == ["P00001"]
    assert exc_info.value.details["query_batch_index"] == 1
    assert exc_info.value.details["query_accession_start"] == 0
    assert exc_info.value.details["query_accession_count"] == 1


def test_uniprot_rejects_query_that_still_has_next_page_at_cap() -> None:
    call_count = 0

    def urlopen(_request, timeout):  # type: ignore[no-untyped-def]
        nonlocal call_count
        del timeout
        call_count += 1
        return FakeHttpResponse(
            body=json.dumps(
                {"results": [_uniprot_record(f"P{call_count - 1:05d}", "MPEPTIDE")]}
            ),
            headers={
                "x-uniprot-release": "2026_03",
                "link": (
                    "<https://rest.uniprot.org/uniprotkb/search?cursor=still-more>; "
                    'rel="next"'
                ),
            },
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(
            batch_size_cap=2,
            uniprot_operation_accession_cap=10,
            uniprot_page_cap_per_query=2,
        ),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P00000", "P00001"),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-19T00:00:00+00:00",
        )

    assert call_count == 2
    assert exc_info.value.error_type == "provider_partial_result"
    assert exc_info.value.details == {
        "provider": "uniprot",
        "page_cap": 2,
        "query_batch_index": 1,
        "query_accession_count": 2,
    }


def test_uniprot_rejects_pagination_outside_pinned_https_endpoint() -> None:
    call_count = 0

    def urlopen(_request, timeout):  # type: ignore[no-untyped-def]
        nonlocal call_count
        del timeout
        call_count += 1
        return FakeHttpResponse(
            body=json.dumps({"results": [_uniprot_record("P00000", "MPEPTIDE")]}),
            headers={
                "x-uniprot-release": "2026_03",
                "link": (
                    '<http://127.0.0.1/uniprotkb/search?cursor=unsafe>; rel="next"'
                ),
            },
        )

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P00000",),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-19T00:00:00+00:00",
        )

    assert call_count == 1
    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.details["expected_endpoint"] == (
        "https://rest.uniprot.org/uniprotkb/search"
    )
    assert str(exc_info.value.details["next_link_digest"]).startswith("sha256:")


def test_ncbi_total_accession_cap_remains_100_before_http() -> None:
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(ncbi_email="operator@example.test"),
        urlopen=lambda _request, timeout: pytest.fail(  # noqa: ARG005
            "oversized NCBI request must fail before HTTP"
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.ncbi_fetch_proteins(
            accessions=tuple(f"NCBI{index}" for index in range(101)),
            fields=(),
            retrieved_at="2026-07-19T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_invalid_request"
    assert exc_info.value.details == {"accession_count": 101, "limit": 100}


def test_uniprot_preserves_primary_review_release_versions_and_digests() -> None:
    body = json.dumps({"results": [_uniprot_record("P12345", "MPEPTIDE")]})
    requested_urls: list[str] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        del timeout
        requested_urls.append(request.full_url)
        return FakeHttpResponse(
            body=body,
            headers={
                "x-uniprot-release": "2026_03",
                "x-uniprot-release-date": "15-July-2026",
            },
        )

    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=("P12345",),
        fields=("length",),
        batch_size=10,
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    metadata = json.loads(_artifact(result, "provider_parsed/metadata.json").content)
    record = metadata["records"][0]
    assert record["requested_accession"] == "P12345"
    assert record["primary_accession"] == "P12345"
    assert record["reviewed"] is True
    assert record["uniprot_release"] == "2026_03"
    assert record["uniprot_release_date"] == "15-July-2026"
    assert record["retrieved_at"] == "2026-07-17T00:00:00+00:00"
    assert record["entry_version"] == 12
    assert record["sequence_version"] == 3
    assert record["response_digest"] == _digest(body)
    assert record["sequence_digest"] == _digest("MPEPTIDE")
    assert record["mapping_annotations"] == [
        {
            "annotation_type": "provider_identity_mapping",
            "identity_replaced": False,
            "relationship": "resolves_to_primary_accession",
            "source_accession": "P12345",
            "source_database": "requested_identifier",
            "target_accession": "P12345",
            "target_database": "uniprotkb",
        }
    ]
    assert result.summary["uniprot_release"] == "2026_03"
    assert result.summary["identity_complete"] is True
    assert "sequence_version" in requested_urls[0]
    assert "version" in requested_urls[0]
    assert "reviewed" in requested_urls[0]
    _assert_offline_recomputable_raw_responses(
        result,
        expected_bodies=(body,),
    )


def test_uniprot_rejects_partial_optional_release_date_provenance() -> None:
    responses = iter(
        [
            FakeHttpResponse(
                body=json.dumps({"results": [_uniprot_record("P12345", "MPEPTIDE")]}),
                headers={
                    "x-uniprot-release": "2026_03",
                    "x-uniprot-release-date": "15-July-2026",
                },
            ),
            FakeHttpResponse(
                body=json.dumps({"results": [_uniprot_record("Q8XYZ1", "MPEPTIDE")]}),
                headers={"x-uniprot-release": "2026_03"},
            ),
        ]
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(batch_size_cap=1),
        urlopen=lambda _request, timeout: next(responses),  # noqa: ARG005
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345", "Q8XYZ1"),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.details["header"] == "x-uniprot-release-date"
    assert exc_info.value.details["missing_pages"] == [2]


def test_uniprot_partitions_active_deleted_and_merged_inactive_records() -> None:
    active = _uniprot_record("P12345", "MPEPTIDE")
    deleted = _uniprot_inactive_deleted_record("Q8XYZ1")
    merged = _uniprot_inactive_merged_record("A0A2U8U0K3")
    second_merged = _uniprot_inactive_merged_record(
        "A0A8N4L368",
        replacement_targets=["A0A034VJ86"],
        uniparc_id="UPI001114BBC8",
    )
    body = json.dumps({"results": [active, deleted, merged, second_merged]})
    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={
                "x-uniprot-release": "2026_03",
                "x-uniprot-release-date": "15-July-2026",
            },
        ),
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=("P12345", "Q8XYZ1", "A0A2U8U0K3", "A0A8N4L368"),
        fields=(),
        batch_size=100,
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    metadata = json.loads(_artifact(result, "provider_parsed/metadata.json").content)
    assert metadata["identity_contract_id"] == "uniprot_primary_sequence_identity@2"
    assert metadata["active_record_count"] == 1
    assert metadata["inactive_record_count"] == 3
    assert metadata["inactive_deleted_record_count"] == 1
    assert metadata["inactive_merged_record_count"] == 2
    assert [record["requested_accession"] for record in metadata["records"]] == [
        "P12345"
    ]
    deleted_record = metadata["inactive_records"][0]
    assert deleted_record == {
        "requested_accession": "Q8XYZ1",
        "primary_accession": "Q8XYZ1",
        "uniprot_identifier": "Q8XYZ1_AOX",
        "entry_type": "Inactive",
        "inactive_reason": {
            "inactive_reason_type": "DELETED",
            "deleted_reason": "Not part of a reference proteome",
        },
        "uniparc_id": "UPI000453BEA2",
        "uniprot_release": "2026_03",
        "uniprot_release_date": "15-July-2026",
        "retrieved_at": "2026-07-20T00:00:00+00:00",
        "response_digest": _digest(body),
        "record_digest": _digest(json.dumps(deleted, sort_keys=True, indent=2) + "\n"),
        "provider_metadata": deleted,
    }
    merged_record = metadata["inactive_records"][1]
    assert merged_record["requested_accession"] == "A0A2U8U0K3"
    assert merged_record["primary_accession"] == "A0A2U8U0K3"
    assert merged_record["uniparc_id"] == "UPI000A0F4040"
    assert merged_record["inactive_reason"] == {
        "inactive_reason_type": "MERGED",
        "replacement_target_annotations": [
            {
                "annotation_type": "provider_inactive_replacement",
                "source_database": "uniprotkb",
                "source_accession": "A0A2U8U0K3",
                "target_database": "uniprotkb",
                "target_accession": "P18173",
                "relationship": "merged_into",
                "identity_replaced": False,
                "target_followed": False,
            }
        ],
    }
    assert (
        metadata["inactive_records"][2]["inactive_reason"][
            "replacement_target_annotations"
        ][0]["target_accession"]
        == "A0A034VJ86"
    )
    parsed_fasta = _artifact(result, "provider_parsed/sequences.fasta")
    assert parsed_fasta.content.startswith(">P12345")
    assert "Q8XYZ1" not in parsed_fasta.content
    assert "A0A2U8U0K3" not in parsed_fasta.content
    assert "P18173" not in parsed_fasta.content
    assert "A0A8N4L368" not in parsed_fasta.content
    assert "A0A034VJ86" not in parsed_fasta.content
    assert parsed_fasta.metadata["database"] == "uniprotkb"
    assert parsed_fasta.metadata["uniprot_release"] == "2026_03"
    assert (
        parsed_fasta.metadata["identity_contract_id"]
        == "uniprot_primary_sequence_identity@2"
    )
    assert "sequence_digests" not in parsed_fasta.metadata
    assert parsed_fasta.metadata["sequence_digest_count"] == 1
    assert (
        parsed_fasta.metadata["sequence_digest_count"]
        + metadata["inactive_record_count"]
        == len(metadata["requested_accessions"])
        == 4
    )
    assert parsed_fasta.metadata["sequence_digest_index_digest"] == (
        _canonical_json_digest({"P12345": _digest("MPEPTIDE")})
    )
    assert (
        parsed_fasta.metadata["sequence_digest_index_contract_id"]
        == "canonical_sequence_digest_index@1"
    )
    assert result.summary["identity_complete"] is True
    assert result.summary["active_record_count"] == 1
    assert result.summary["inactive_record_count"] == 3
    assert result.summary["inactive_deleted_record_count"] == 1
    assert result.summary["inactive_merged_record_count"] == 2
    assert result.provider_observation["inactive_accessions"] == [
        "Q8XYZ1",
        "A0A2U8U0K3",
        "A0A8N4L368",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.update(
            {"entryType": "Future active entry", "reviewed": True}
        ),
        lambda record: record.update({"reviewed": False}),
        lambda record: record.update(
            {
                "inactiveReason": {
                    "inactiveReasonType": "FUTURE",
                    "providerExtension": "must not bypass inactive union",
                }
            }
        ),
    ],
)
def test_uniprot_active_identity_requires_exact_entry_type_and_no_inactive_reason(
    mutation,
) -> None:  # type: ignore[no-untyped-def]
    record = _uniprot_record("P12345", "MPEPTIDE")
    mutation(record)
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.stage == "provider_response_validation"


def test_uniprot_accepts_exact_unreviewed_active_entry_type() -> None:
    record = _uniprot_record("Q8XYZ1", "MPEPTIDE")
    record["entryType"] = "UniProtKB unreviewed (TrEMBL)"
    record["reviewed"] = False
    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=("Q8XYZ1",),
        fields=(),
        batch_size=None,
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    metadata = json.loads(_artifact(result, "provider_parsed/metadata.json").content)
    assert metadata["records"][0]["reviewed"] is False
    assert metadata["records"][0]["entry_type"] == ("UniProtKB unreviewed (TrEMBL)")


@pytest.mark.parametrize(
    ("body", "duplicate_key", "accession"),
    [
        (
            '{"results":[{"entryType":"Future active entry",'
            '"entryType":"UniProtKB reviewed (Swiss-Prot)",'
            '"primaryAccession":"P12345","secondaryAccessions":[],'
            '"uniProtkbId":"P12345_AOX",'
            '"entryAudit":{"entryVersion":12,"sequenceVersion":3},'
            '"sequence":{"value":"MPEPTIDE","length":8}}]}',
            "entryType",
            "P12345",
        ),
        (
            '{"results":[{"entryType":"Inactive",'
            '"primaryAccession":"A0A034VJ94",'
            '"uniProtkbId":"A0A034VJ94_AOX",'
            '"inactiveReason":{"inactiveReasonType":"MERGED",'
            '"inactiveReasonType":"DELETED",'
            '"deletedReason":"Not part of a reference proteome"},'
            '"extraAttributes":{"uniParcId":"UPI000453BEA2"}}]}',
            "inactiveReasonType",
            "A0A034VJ94",
        ),
    ],
)
def test_uniprot_rejects_duplicate_json_keys_before_normalization(
    body: str,
    duplicate_key: str,
    accession: str,
) -> None:
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=(accession,),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.details["duplicate_key_digest"] == _digest(duplicate_key)
    assert exc_info.value.details["duplicate_key_explanation"] == (
        "A JSON object repeated one member name."
    )
    assert "duplicate_key" not in exc_info.value.details
    assert duplicate_key not in str(exc_info.value)
    assert exc_info.value.details["response_digest"] == _digest(body)


def test_uniprot_duplicate_json_key_diagnostics_are_bounded() -> None:
    duplicate_key = "provider-secret-" + ("x" * 4096)
    body = f'{{"{duplicate_key}":1,"{duplicate_key}":2}}'
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    failure = exc_info.value
    public_diagnostic = json.dumps(
        {
            "message": failure.message,
            "hint": failure.hint,
            "details": failure.details,
        },
        sort_keys=True,
    )
    assert failure.details["duplicate_key_digest"] == _digest(duplicate_key)
    assert duplicate_key not in public_diagnostic
    assert len(public_diagnostic) < 1024


def test_uniprot_all_deleted_records_emit_typed_zero_record_fasta() -> None:
    body = json.dumps({"results": [_uniprot_inactive_deleted_record("A0A034VJ94")]})
    result = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    ).uniprot_fetch(
        accessions=("A0A034VJ94",),
        fields=(),
        batch_size=None,
        retrieved_at="2026-07-20T00:00:00+00:00",
    )

    fasta = _artifact(result, "provider_parsed/sequences.fasta")
    assert fasta.content == ""
    assert fasta.metadata["validation_profile"] == "fasta_zero_records@1"
    assert fasta.metadata["empty_result_reason"] == (
        "uniprot_no_active_sequence_records"
    )
    assert fasta.metadata["derivation_contract_id"] == (
        "uniprot_primary_sequence_identity@2"
    )
    assert "sequence_digests" not in fasta.metadata
    assert fasta.metadata["sequence_digest_count"] == 0
    assert fasta.metadata["sequence_digest_index_digest"] == (
        _canonical_json_digest({})
    )
    assert (
        fasta.metadata["sequence_digest_index_contract_id"]
        == "canonical_sequence_digest_index@1"
    )
    assert result.summary["record_count"] == 1
    assert result.summary["active_record_count"] == 0
    assert result.summary["inactive_record_count"] == 1
    assert result.summary["inactive_deleted_record_count"] == 1
    assert result.summary["inactive_merged_record_count"] == 0


def test_uniprot_inactive_identity_rejects_source_sequence_assertion() -> None:
    body = json.dumps({"results": [_uniprot_inactive_merged_record("A0A2U8U0K3")]})
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("A0A2U8U0K3",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
            source_sequence_identities={
                "A0A2U8U0K3": {
                    "source_database": "ebi_hmmer_refprot",
                    "source_accession": "A0A2U8U0K3",
                    "sequence_digest": _digest("HMMER-SEQUENCE-MUST-NOT-BE-USED"),
                }
            },
        )

    assert exc_info.value.error_type == "provider_invalid_request"
    assert "inactive records" in exc_info.value.hint
    assert "deleted records" not in exc_info.value.hint
    assert exc_info.value.details["inactive_source_identity_accessions"] == [
        "A0A2U8U0K3"
    ]


def test_uniprot_merged_target_cannot_satisfy_its_own_requested_identity() -> None:
    body = json.dumps({"results": [_uniprot_inactive_merged_record("A0A2U8U0K3")]})
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("A0A2U8U0K3", "P18173"),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_identity_mismatch"
    assert exc_info.value.details["missing_accessions"] == ["P18173"]
    assert exc_info.value.details["resolved_accessions"] == ["A0A2U8U0K3"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record["inactiveReason"].update(
            {"inactiveReasonType": "MERGED"}
        ),
        lambda record: record["inactiveReason"].update(
            {"inactiveReasonType": "DEMERGED"}
        ),
        lambda record: record["inactiveReason"].update(
            {"deletedReason": " Not canonical "}
        ),
        lambda record: record["inactiveReason"].update(
            {"deletedReason": "Not canonical\nreason"}
        ),
        lambda record: record.update({"uniProtkbId": "A0A034VJ94\nBAD"}),
        lambda record: record["inactiveReason"].pop("deletedReason"),
        lambda record: record["extraAttributes"].update({"uniParcId": "bad"}),
        lambda record: record.update({"sequence": {"value": "AAAA", "length": 4}}),
        lambda record: record.update(
            {"entryAudit": {"entryVersion": 1, "sequenceVersion": 1}}
        ),
    ],
)
def test_uniprot_rejects_malformed_inactive_deleted_record(mutation) -> None:  # type: ignore[no-untyped-def]
    record = _uniprot_inactive_deleted_record("A0A034VJ94")
    mutation(record)
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("A0A034VJ94",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.stage == "provider_response_validation"


@pytest.mark.parametrize(
    "replacement_targets",
    [[], ["P18173", "P18173"], ["bad target"], ["A0A2U8U0K3"]],
)
def test_uniprot_rejects_malformed_merged_replacement_targets(
    replacement_targets: list[str],
) -> None:
    record = _uniprot_inactive_merged_record("A0A2U8U0K3")
    record["inactiveReason"]["mergeDemergeTo"] = replacement_targets
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("A0A2U8U0K3",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.stage == "provider_response_validation"


def test_uniprot_inactive_record_never_follows_secondary_identity() -> None:
    record = _uniprot_inactive_deleted_record("P12345")
    record["secondaryAccessions"] = ["Q8XYZ1"]
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("Q8XYZ1",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_identity_mismatch"
    assert exc_info.value.details["selection_required"] is False


def test_uniprot_inactive_record_is_bound_to_its_producing_query_batch() -> None:
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(batch_size_cap=1),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [_uniprot_inactive_deleted_record("Q8XYZ1")]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345", "Q8XYZ1"),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_identity_mismatch"
    assert exc_info.value.details["primary_accession"] == "Q8XYZ1"
    assert exc_info.value.details["query_batch_index"] == 1
    assert exc_info.value.details["query_accession_start"] == 0
    assert exc_info.value.details["query_accession_count"] == 1


def test_uniprot_http_failure_preserves_safe_query_batch_coordinates() -> None:
    calls = 0

    def urlopen(_request: Any, timeout: float) -> FakeHttpResponse:
        nonlocal calls
        del timeout
        calls += 1
        if calls == 1:
            return FakeHttpResponse(
                body=json.dumps({"results": [_uniprot_record("P00000", "MPEPTIDE")]}),
                headers={"x-uniprot-release": "2026_03"},
            )
        raise OSError("safe network failure")

    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(batch_size_cap=1, max_retries=2),
        urlopen=urlopen,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P00000", "P00001"),
            fields=(),
            batch_size=1,
            retrieved_at="2026-07-20T00:00:00+00:00",
        )

    assert calls == 4
    assert exc_info.value.error_type == "provider_unavailable"
    assert exc_info.value.details == {
        "reason_digest": _digest("safe network failure"),
        "query_batch_index": 2,
        "query_batch_count": 2,
        "query_accession_start": 1,
        "query_accession_count": 1,
        "query_accessions_digest": _digest(
            json.dumps(["P00001"], sort_keys=True, indent=2) + "\n"
        ),
        "completed_page_count": 1,
        "completed_pages_in_query": 0,
        "requested_page_in_query": 1,
    }
    assert not any(
        unsafe in json.dumps(exc_info.value.details)
        for unsafe in ("rest.uniprot.org", "cursor=", "accession:P00001")
    )


def test_uniprot_secondary_mapping_is_annotation_not_identity_overwrite() -> None:
    body = json.dumps(
        {
            "results": [
                _uniprot_record(
                    "P12345",
                    "MPEPTIDE",
                    secondary_accessions=["Q8XYZ1"],
                )
            ]
        }
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    result = adapter.uniprot_fetch(
        accessions=("Q8XYZ1",),
        fields=(),
        batch_size=None,
        retrieved_at="2026-07-17T00:00:00+00:00",
    )

    record = json.loads(_artifact(result, "provider_parsed/metadata.json").content)[
        "records"
    ][0]
    assert record["requested_accession"] == "Q8XYZ1"
    assert record["primary_accession"] == "P12345"
    assert record["mapping_annotations"][0]["identity_replaced"] is False
    assert _artifact(result, "provider_parsed/sequences.fasta").content.startswith(
        ">P12345"
    )


def test_uniprot_sequence_conflict_fails_with_explicit_selection_evidence() -> None:
    body = json.dumps(
        {
            "results": [
                _uniprot_record("P12345", "MPEPTIDE"),
                _uniprot_record("P12345", "MCONFLICT"),
            ]
        }
    )
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-17T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_sequence_identity_conflict"
    assert exc_info.value.details["selection_required"] is True
    assert exc_info.value.details["identities"] == ["P12345", "P12345"]
    assert sorted(exc_info.value.details["sequence_digests"]) == sorted(
        (_digest("MPEPTIDE"), _digest("MCONFLICT"))
    )


def test_uniprot_empty_results_fail_closed() -> None:
    body = json.dumps({"results": []})
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-17T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_empty_result"
    assert exc_info.value.stage == "provider_response_validation"
    assert exc_info.value.retryable is False
    assert exc_info.value.details["requested_accessions"] == ["P12345"]
    assert exc_info.value.details["response_digests"] == [_digest(body)]


def _source_sequence_identity(sequence: str) -> dict[str, dict[str, str]]:
    return {
        "P12345": {
            "source_database": "ebi_hmmer_refprot",
            "source_accession": "P12345",
            "sequence_digest": _digest(sequence),
        }
    }


def _uniprot_single_record_adapter(sequence: str) -> ProviderHttpBioDatabaseAdapter:
    body = json.dumps({"results": [_uniprot_record("P12345", sequence)]})
    return ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=body,
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )


def test_uniprot_source_sequence_mismatch_requires_explicit_choice() -> None:
    with pytest.raises(PipelineSdkFailure) as exc_info:
        _uniprot_single_record_adapter("MPEPTIDE").uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-17T00:00:00+00:00",
            source_sequence_identities=_source_sequence_identity("MCONFLICT"),
        )

    assert exc_info.value.error_type == "provider_sequence_identity_conflict"
    assert exc_info.value.stage == "provider_response_validation"
    assert exc_info.value.retryable is False
    assert exc_info.value.details["requested_accession"] == "P12345"
    assert exc_info.value.details["selection_required"] is True
    assert exc_info.value.details["allowed_choice"] == "accept_uniprot"
    assert exc_info.value.details["source_identity"] == {
        "source_accession": "P12345",
        "source_database": "ebi_hmmer_refprot",
        "sequence_digest": _digest("MCONFLICT"),
    }
    assert sorted(exc_info.value.details["sequence_digests"]) == sorted(
        (_digest("MCONFLICT"), _digest("MPEPTIDE"))
    )


def test_uniprot_explicit_accept_choice_records_sequence_mismatch_annotation() -> None:
    result = _uniprot_single_record_adapter("MPEPTIDE").uniprot_fetch(
        accessions=("P12345",),
        fields=(),
        batch_size=None,
        retrieved_at="2026-07-17T00:00:00+00:00",
        source_sequence_identities=_source_sequence_identity("MCONFLICT"),
        sequence_mismatch_choices={"P12345": "accept_uniprot"},
    )

    record = json.loads(_artifact(result, "provider_parsed/metadata.json").content)[
        "records"
    ][0]
    annotation = next(
        item
        for item in record["mapping_annotations"]
        if item.get("explicit_choice") == "accept_uniprot"
    )
    assert annotation == {
        "annotation_type": "cross_database_sequence_identity",
        "explicit_choice": "accept_uniprot",
        "identity_replaced": False,
        "relationship": "sequence_mismatch_explicitly_resolved",
        "source_accession": "P12345",
        "source_database": "ebi_hmmer_refprot",
        "source_sequence_digest": _digest("MCONFLICT"),
        "target_accession": "P12345",
        "target_database": "uniprotkb",
        "target_sequence_digest": _digest("MPEPTIDE"),
    }


@pytest.mark.parametrize(
    "record_mutation",
    [
        {"entryType": ""},
        {"entryAudit": {}},
        {"sequence": {"value": "MPEPTIDE", "length": 999}},
    ],
)
def test_uniprot_rejects_review_version_or_sequence_schema_drift(
    record_mutation: dict[str, Any],
) -> None:
    record = _uniprot_record("P12345", "MPEPTIDE")
    record.update(record_mutation)
    adapter = ProviderHttpBioDatabaseAdapter(
        BioProviderHttpConfig(),
        urlopen=lambda _request, timeout: FakeHttpResponse(  # noqa: ARG005
            body=json.dumps({"results": [record]}),
            headers={"x-uniprot-release": "2026_03"},
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(PipelineSdkFailure) as exc_info:
        adapter.uniprot_fetch(
            accessions=("P12345",),
            fields=(),
            batch_size=None,
            retrieved_at="2026-07-17T00:00:00+00:00",
        )

    assert exc_info.value.error_type == "provider_schema_drift"
    assert exc_info.value.sdk_method == "bio.uniprot_fetch"
