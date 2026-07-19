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
    assert len(parsed_fasta.metadata["sequence_digests"]) == 13
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
            "result": {
                "stats": {"nhits": 1, "provider_extension": "allowed"},
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
    assert result.summary["candidate_accessions"] == ["P12345"]
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

    assert result.summary["candidate_accessions"] == ["A0A378ARX6"]
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
    assert tuple(accession for batch in observed_batches for accession in batch) == accessions
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
    assert all(str(request["query_accessions_digest"]).startswith("sha256:") for request in requests)
    _assert_offline_recomputable_raw_responses(
        result,
        expected_bodies=tuple(response_bodies),
    )


def test_uniprot_real_scale_preflight_is_linear_and_partitions_37722() -> None:
    config = BioProviderHttpConfig()
    adapter = ProviderHttpBioDatabaseAdapter(
        config,
        urlopen=lambda _request, timeout: pytest.fail(  # noqa: ARG005
            "real-scale preflight must not contact UniProt"
        ),
        sleep=lambda _seconds: None,
    )
    accessions = tuple(f"P{index:05d}" for index in range(37_722))

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
    assert len(query_batches[-1]) == 22

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
                f"<https://rest.uniprot.org/uniprotkb/search?cursor={next_ref}>; rel=\"next\""
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
                    "<http://127.0.0.1/uniprotkb/search?cursor=unsafe>; "
                    'rel="next"'
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
