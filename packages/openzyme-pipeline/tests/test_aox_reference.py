from __future__ import annotations

import hashlib
import json

import pytest

from openzyme_pipeline import aox_reference


def _digest(content: str | bytes) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _sequence(index: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWYBXZJUO"
    return "M" + alphabet[index % len(alphabet) :] + alphabet[: index % len(alphabet)]


def _source_id(accession: str, *, pdb_pipe: bool) -> str:
    if accession == "9AVH_A" and pdb_pipe:
        return "pdb|9AVH|A"
    return accession


def _ncbi_fasta(
    *,
    accessions: tuple[str, ...] = aox_reference.NCBI_REFERENCE_ACCESSIONS,
    pdb_pipe: bool = True,
    reverse: bool = False,
) -> tuple[str, dict[str, str]]:
    ordered = tuple(reversed(accessions)) if reverse else accessions
    sequences = {
        accession: _sequence(index)
        for index, accession in enumerate(aox_reference.NCBI_REFERENCE_ACCESSIONS)
    }
    parts: list[str] = []
    for accession in ordered:
        sequence = sequences.get(accession, _sequence(len(parts) + 20))
        midpoint = max(1, len(sequence) // 2)
        parts.append(
            f">{_source_id(accession, pdb_pipe=pdb_pipe)} NCBI protein {accession}\n"
            f"{sequence[:midpoint]}\n{sequence[midpoint:]}\n"
        )
    return "".join(parts), sequences


def _error_code(
    error: pytest.ExceptionInfo[aox_reference.ScientificPrerequisiteError],
) -> str:
    return error.value.code


def test_contract_ids_accessions_and_payloads_are_fixed() -> None:
    assert aox_reference.HMM_REFERENCE_ACCESSIONS == (
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
    assert aox_reference.SCORING_REFERENCE_ACCESSION == "AAB57849.1"
    assert aox_reference.NCBI_REFERENCE_ACCESSIONS == (
        *aox_reference.HMM_REFERENCE_ACCESSIONS,
        "AAB57849.1",
    )
    assert (
        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
        == "aox_hmm_reference_set_selection@1"
    )
    assert (
        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
        == "aox_reference_selection@1"
    )
    assert (
        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
        == "aox_scoring_input_assembly@1"
    )

    hmm_payload = aox_reference.hmm_reference_set_selection_contract_payload(
        implementation_digest_value="sha256:" + "1" * 64
    )
    scoring_payload = aox_reference.scoring_reference_selection_contract_payload(
        implementation_digest_value="sha256:" + "2" * 64
    )
    assembly_payload = aox_reference.scoring_input_assembly_contract_payload(
        implementation_digest_value="sha256:" + "3" * 64
    )
    assert hmm_payload["selection"] == {
        "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
        "excluded_accessions": ["AAB57849.1"],
        "output_order": "fixed_contract_accession_order",
    }
    assert scoring_payload["selection"] == {
        "selected_accessions": ["AAB57849.1"],
        "excluded_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
        "output_order": "fixed_contract_accession_order",
    }
    assert assembly_payload["inputs"]["post_uniprot_target_fasta"] == {
        "healthy_empty": "zero_bytes",
        "sequence_ids": "unique",
        "reference_accession_forbidden": True,
    }


def test_contract_and_implementation_digests_are_canonical_and_recomputable() -> None:
    implementation_digest = aox_reference.implementation_digest()
    assert implementation_digest == (
        "sha256:a0d2bc834b12bd35bcce9f8231e5100837a6428e77fadada54baf277863f4eca"
    )
    assert (
        aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        == implementation_digest
    )
    assert (
        aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        == implementation_digest
    )
    assert (
        aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        == implementation_digest
    )
    assert aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST == (
        aox_reference.hmm_reference_set_selection_contract_digest(
            implementation_digest_value=implementation_digest
        )
    )
    assert aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST == (
        "sha256:498b11bd7c268529a0f6abb351dfd187a10573b6ebadf15c2110ca01b5bbfac1"
    )
    assert aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST == (
        aox_reference.scoring_reference_selection_contract_digest(
            implementation_digest_value=implementation_digest
        )
    )
    assert aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST == (
        "sha256:953bd9dcf794baeca8aba910b03153fd07dd0531ded4dd31b0133516bc0288be"
    )
    assert aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST == (
        aox_reference.scoring_input_assembly_contract_digest(
            implementation_digest_value=implementation_digest
        )
    )
    assert aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST == (
        "sha256:b94b6077dec93dbb18d26416e2ccb1e9d1bc49cdd8a694b5864ee9542bb989a8"
    )
    for digest in (
        implementation_digest,
        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST,
        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST,
    ):
        assert digest.startswith("sha256:")
        assert len(digest) == 71


def test_hmm_selection_requires_one_exact_14_record_ncbi_set_and_is_canonical() -> None:
    fasta, sequences = _ncbi_fasta(reverse=True)
    result = aox_reference.select_hmm_reference_set(
        fasta,
        expected_input_digest=_digest(fasta),
    )
    expected = "".join(
        f">{accession}\n{sequences[accession]}\n"
        for accession in aox_reference.HMM_REFERENCE_ACCESSIONS
    )
    assert result.to_fasta() == expected
    assert tuple(record.sequence_id for record in result.selected_records) == (
        aox_reference.HMM_REFERENCE_ACCESSIONS
    )
    assert result.selected_records[2].source_id == "pdb|9AVH|A"
    assert (
        result.selected_records[2].identity_resolution_rule
        == "exact_ncbi_pdb_token_pdb|9AVH|A"
    )
    assert all(
        record.sequence_digest == _digest(sequences[record.sequence_id])
        for record in result.selected_records
    )

    metadata = result.metadata()
    assert metadata["contract_id"] == (
        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
    )
    assert metadata["input_digest"] == _digest(fasta)
    assert metadata["output_digest"] == _digest(expected)
    assert metadata["counts"] == {
        "input_record_count": 14,
        "selected_record_count": 13,
        "excluded_record_count": 1,
    }
    assert metadata["selected_accessions"] == list(
        aox_reference.HMM_REFERENCE_ACCESSIONS
    )
    assert metadata["excluded_accessions"] == ["AAB57849.1"]
    assert metadata["identity_replacement_count"] == 0
    assert json.loads(result.metadata_json()) == metadata


def test_hmm_selection_output_is_stable_across_ncbi_record_order_and_headers() -> None:
    ordered, _ = _ncbi_fasta(pdb_pipe=False)
    reversed_fasta, _ = _ncbi_fasta(pdb_pipe=False, reverse=True)
    ordered_result = aox_reference.select_hmm_reference_set(ordered)
    reversed_result = aox_reference.select_hmm_reference_set(reversed_fasta)
    assert ordered_result.to_fasta() == reversed_result.to_fasta()
    assert ordered_result.output_digest == reversed_result.output_digest
    assert ordered_result.input_digest != reversed_result.input_digest


def test_scoring_reference_selection_uses_same_exact_input_and_preserves_sequence() -> None:
    fasta, sequences = _ncbi_fasta()
    result = aox_reference.select_scoring_reference(fasta)
    expected = f">AAB57849.1\n{sequences['AAB57849.1']}\n"
    assert result.to_fasta() == expected
    assert result.reference.sequence_id == "AAB57849.1"
    assert result.reference.source_id == "AAB57849.1"
    assert result.reference.sequence_digest == _digest(sequences["AAB57849.1"])
    assert result.metadata()["counts"] == {
        "input_record_count": 14,
        "selected_record_count": 1,
        "excluded_record_count": 13,
    }
    assert result.metadata()["reference_accession"] == "AAB57849.1"
    assert result.metadata()["output_digest"] == _digest(expected)


@pytest.mark.parametrize(
    ("fasta_factory", "expected_code"),
    [
        (
            lambda: _ncbi_fasta(
                accessions=aox_reference.NCBI_REFERENCE_ACCESSIONS[:-1]
            )[0],
            "aox_ncbi_reference_identity_set_mismatch",
        ),
        (
            lambda: _ncbi_fasta(
                accessions=(
                    *aox_reference.NCBI_REFERENCE_ACCESSIONS,
                    "EXTRA.1",
                )
            )[0],
            "aox_ncbi_reference_identity_set_mismatch",
        ),
        (
            lambda: _ncbi_fasta(
                accessions=(
                    *aox_reference.NCBI_REFERENCE_ACCESSIONS[:-1],
                    aox_reference.NCBI_REFERENCE_ACCESSIONS[0],
                )
            )[0],
            "aox_reference_fasta_duplicate_identity",
        ),
        (
            lambda: _ncbi_fasta()[0].replace(
                ">AAC72747.1 ", ">aac72747.1 ", 1
            ),
            "aox_ncbi_reference_identity_set_mismatch",
        ),
        (
            lambda: _ncbi_fasta()[0].replace(
                ">AAC72747.1 ", ">gb|AAC72747.1| ", 1
            ),
            "aox_ncbi_reference_identity_set_mismatch",
        ),
        (
            lambda: _ncbi_fasta()[0].replace(
                ">pdb|9AVH|A ", ">pdb|9AVH|B ", 1
            ),
            "aox_ncbi_reference_identity_set_mismatch",
        ),
    ],
)
def test_reference_selections_reject_missing_extra_duplicate_or_alias_identity(
    fasta_factory,  # type: ignore[no-untyped-def]
    expected_code: str,
) -> None:
    fasta = fasta_factory()
    for select in (
        aox_reference.select_hmm_reference_set,
        aox_reference.select_scoring_reference,
    ):
        with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
            select(fasta)
        assert _error_code(error) == expected_code


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda value: value.replace("\nM", "\nm", 1),
            "aox_reference_fasta_residue_invalid",
        ),
        (
            lambda value: value.replace("\nM", "\nM*", 1),
            "aox_reference_fasta_residue_invalid",
        ),
        (
            lambda value: value.replace("\nM", "\nM-", 1),
            "aox_reference_fasta_residue_invalid",
        ),
        (
            lambda value: value.replace("\nM", "\n M", 1),
            "aox_reference_fasta_sequence_whitespace",
        ),
        (
            lambda value: "ACDE\n" + value,
            "aox_reference_fasta_sequence_before_header",
        ),
    ],
)
def test_reference_selections_reject_noncanonical_fasta_or_residues(
    mutate,  # type: ignore[no-untyped-def]
    expected_code: str,
) -> None:
    fasta, _ = _ncbi_fasta()
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.select_hmm_reference_set(mutate(fasta))
    assert _error_code(error) == expected_code


def test_reference_selection_rejects_non_utf8_and_digest_mismatch() -> None:
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.select_hmm_reference_set(b">AAC72747.1\n\xff\n")
    assert _error_code(error) == "aox_reference_fasta_not_utf8"

    fasta, _ = _ncbi_fasta()
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.select_scoring_reference(
            fasta,
            expected_input_digest="sha256:" + "0" * 64,
        )
    assert _error_code(error) == "aox_reference_input_digest_mismatch"


def test_scoring_input_assembly_is_aab_first_and_targets_are_lexically_stable() -> None:
    ncbi_fasta, sequences = _ncbi_fasta()
    scoring_reference = aox_reference.select_scoring_reference(
        ncbi_fasta
    ).to_fasta()
    target_fasta = ">Q99999 target z\nWWWW\n>P12345 target a\nACDE\n"
    result = aox_reference.assemble_scoring_input(
        scoring_reference,
        target_fasta,
        expected_scoring_reference_input_digest=_digest(scoring_reference),
        expected_target_input_digest=_digest(target_fasta),
    )
    expected = (
        f">AAB57849.1\n{sequences['AAB57849.1']}\n"
        ">P12345\nACDE\n"
        ">Q99999\nWWWW\n"
    )
    assert result.to_fasta() == expected
    assert tuple(record.sequence_id for record in result.records) == (
        "AAB57849.1",
        "P12345",
        "Q99999",
    )
    metadata = result.metadata()
    assert metadata["contract_id"] == (
        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
    )
    assert metadata["input_digests"] == {
        "scoring_reference_fasta": _digest(scoring_reference),
        "post_uniprot_target_fasta": _digest(target_fasta),
    }
    assert metadata["output_digest"] == _digest(expected)
    assert metadata["counts"] == {
        "reference_record_count": 1,
        "target_record_count": 2,
        "output_record_count": 3,
    }
    assert metadata["target_accessions"] == ["P12345", "Q99999"]
    assert metadata["healthy_empty"] is False
    assert json.loads(result.metadata_json()) == metadata


def test_scoring_input_assembly_healthy_empty_is_exact_reference_only() -> None:
    ncbi_fasta, sequences = _ncbi_fasta()
    scoring_reference = aox_reference.select_scoring_reference(
        ncbi_fasta
    ).to_fasta()
    result = aox_reference.assemble_scoring_input(scoring_reference, b"")
    expected = f">AAB57849.1\n{sequences['AAB57849.1']}\n"
    assert result.to_fasta() == expected
    assert result.targets == ()
    assert result.metadata()["healthy_empty"] is True
    assert result.metadata()["counts"]["output_record_count"] == 1
    assert result.metadata()["input_digests"]["post_uniprot_target_fasta"] == (
        _digest(b"")
    )


@pytest.mark.parametrize(
    ("target_fasta", "expected_code"),
    [
        (">P12345\nACDE\n>P12345\nWWWW\n", "aox_reference_fasta_duplicate_identity"),
        (">AAB57849.1\nACDE\n", "aox_scoring_target_contains_reference"),
        ("\n", "aox_reference_fasta_empty_not_canonical"),
        (">bad/id\nACDE\n", "aox_scoring_target_id_invalid"),
        (">P12345\nAC*E\n", "aox_reference_fasta_residue_invalid"),
    ],
)
def test_scoring_input_assembly_rejects_invalid_targets(
    target_fasta: str,
    expected_code: str,
) -> None:
    ncbi_fasta, _ = _ncbi_fasta()
    scoring_reference = aox_reference.select_scoring_reference(
        ncbi_fasta
    ).to_fasta()
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.assemble_scoring_input(scoring_reference, target_fasta)
    assert _error_code(error) == expected_code


@pytest.mark.parametrize(
    "reference_fasta",
    [
        ">WRONG.1\nACDE\n",
        ">AAB57849.1\nACDE\n>P12345\nWWWW\n",
        ">pdb|AAB5|A\nACDE\n",
    ],
)
def test_scoring_input_assembly_requires_one_exact_aab_reference(
    reference_fasta: str,
) -> None:
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.assemble_scoring_input(reference_fasta, b"")
    assert _error_code(error) in {
        "aox_scoring_reference_identity_mismatch",
        "aox_scoring_target_id_invalid",
    }


def test_scoring_input_assembly_binds_both_input_digests() -> None:
    ncbi_fasta, _ = _ncbi_fasta()
    scoring_reference = aox_reference.select_scoring_reference(
        ncbi_fasta
    ).to_fasta()
    for field in (
        "expected_scoring_reference_input_digest",
        "expected_target_input_digest",
    ):
        with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
            aox_reference.assemble_scoring_input(
                scoring_reference,
                b"",
                **{field: "sha256:" + "0" * 64},
            )
        assert _error_code(error).endswith("input_digest_mismatch")


@pytest.mark.parametrize(
    ("function", "kwargs"),
    [
        (
            aox_reference.verify_hmm_reference_set_selection_contract,
            {"expected_contract_id": "wrong@1"},
        ),
        (
            aox_reference.verify_scoring_reference_selection_contract,
            {"expected_contract_digest": "sha256:" + "0" * 64},
        ),
        (
            aox_reference.verify_scoring_input_assembly_contract,
            {"expected_implementation_digest": "sha256:" + "0" * 64},
        ),
    ],
)
def test_contract_verification_fails_closed_on_drift(
    function,  # type: ignore[no-untyped-def]
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        function(**kwargs)
    assert _error_code(error) == "aox_reference_contract_digest_drift"


def test_contract_verification_rejects_noncanonical_digest() -> None:
    with pytest.raises(aox_reference.ScientificPrerequisiteError) as error:
        aox_reference.verify_scoring_input_assembly_contract(
            expected_contract_digest="not-a-digest"
        )
    assert _error_code(error) == "aox_reference_bound_digest_invalid"
