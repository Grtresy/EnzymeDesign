from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .aox_motif import ScientificPrerequisiteError


HMM_REFERENCE_ACCESSIONS = (
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
SCORING_REFERENCE_ACCESSION = "AAB57849.1"
NCBI_REFERENCE_ACCESSIONS = HMM_REFERENCE_ACCESSIONS + (
    SCORING_REFERENCE_ACCESSION,
)

HMM_REFERENCE_SET_SELECTION_CONTRACT_ID = (
    "aox_hmm_reference_set_selection@1"
)
SCORING_REFERENCE_SELECTION_CONTRACT_ID = "aox_reference_selection@1"
SCORING_INPUT_ASSEMBLY_CONTRACT_ID = "aox_scoring_input_assembly@1"

HMM_REFERENCE_SET_OUTPUT_NAME = "AOX_ref21.fasta"
SCORING_REFERENCE_OUTPUT_NAME = (
    "AOX_coordinate_reference_AAB57849.1.fasta"
)
SCORING_INPUT_OUTPUT_NAME = "AOX_scoring_input.fasta"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEQUENCE_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$")
_SEQUENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_EXPECTED_NCBI_ACCESSION_SET = frozenset(NCBI_REFERENCE_ACCESSIONS)
_PDB_SOURCE_ID = "pdb|9AVH|A"
_PDB_REQUEST_ID = "9AVH_A"


@dataclass(frozen=True, slots=True)
class FastaRecord:
    sequence_id: str
    source_id: str
    description: str
    sequence: str
    identity_resolution_rule: str

    @property
    def sequence_digest(self) -> str:
        return _sha256(self.sequence.encode("ascii"))

    def canonical_fasta(self) -> str:
        return f">{self.sequence_id}\n{self.sequence}\n"

    def metadata(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "source_id": self.source_id,
            "identity_resolution_rule": self.identity_resolution_rule,
            "identity_replaced": False,
            "sequence_length": len(self.sequence),
            "sequence_digest": self.sequence_digest,
        }


@dataclass(frozen=True, slots=True)
class HmmReferenceSetSelectionResult:
    source_records: tuple[FastaRecord, ...]
    selected_records: tuple[FastaRecord, ...]
    input_digest: str

    def to_fasta(self) -> str:
        return "".join(record.canonical_fasta() for record in self.selected_records)

    @property
    def output_digest(self) -> str:
        return _sha256(self.to_fasta().encode("utf-8"))

    def metadata(self) -> dict[str, object]:
        return {
            "contract_id": HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
            "contract_digest": HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
            "implementation_digest": (
                HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "output_name": HMM_REFERENCE_SET_OUTPUT_NAME,
            "counts": {
                "input_record_count": len(self.source_records),
                "selected_record_count": len(self.selected_records),
                "excluded_record_count": (
                    len(self.source_records) - len(self.selected_records)
                ),
            },
            "input_accessions": [
                record.sequence_id for record in self.source_records
            ],
            "selected_accessions": [
                record.sequence_id for record in self.selected_records
            ],
            "excluded_accessions": [SCORING_REFERENCE_ACCESSION],
            "records": [record.metadata() for record in self.selected_records],
            "identity_replacement_count": 0,
            "healthy_empty": False,
        }

    def metadata_json(self) -> str:
        return _canonical_json_text(self.metadata())


@dataclass(frozen=True, slots=True)
class ScoringReferenceSelectionResult:
    source_records: tuple[FastaRecord, ...]
    reference: FastaRecord
    input_digest: str

    def to_fasta(self) -> str:
        return self.reference.canonical_fasta()

    @property
    def output_digest(self) -> str:
        return _sha256(self.to_fasta().encode("utf-8"))

    def metadata(self) -> dict[str, object]:
        return {
            "contract_id": SCORING_REFERENCE_SELECTION_CONTRACT_ID,
            "contract_digest": SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST,
            "implementation_digest": (
                SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "output_name": SCORING_REFERENCE_OUTPUT_NAME,
            "counts": {
                "input_record_count": len(self.source_records),
                "selected_record_count": 1,
                "excluded_record_count": len(self.source_records) - 1,
            },
            "reference_accession": SCORING_REFERENCE_ACCESSION,
            "record": self.reference.metadata(),
            "identity_replacement_count": 0,
            "healthy_empty": False,
        }

    def metadata_json(self) -> str:
        return _canonical_json_text(self.metadata())


@dataclass(frozen=True, slots=True)
class ScoringInputAssemblyResult:
    reference: FastaRecord
    targets: tuple[FastaRecord, ...]
    scoring_reference_input_digest: str
    target_input_digest: str

    @property
    def records(self) -> tuple[FastaRecord, ...]:
        return (self.reference, *self.targets)

    def to_fasta(self) -> str:
        return "".join(record.canonical_fasta() for record in self.records)

    @property
    def output_digest(self) -> str:
        return _sha256(self.to_fasta().encode("utf-8"))

    def metadata(self) -> dict[str, object]:
        return {
            "contract_id": SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
            "contract_digest": SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST,
            "implementation_digest": SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST,
            "input_digests": {
                "scoring_reference_fasta": self.scoring_reference_input_digest,
                "post_uniprot_target_fasta": self.target_input_digest,
            },
            "output_digest": self.output_digest,
            "output_name": SCORING_INPUT_OUTPUT_NAME,
            "counts": {
                "reference_record_count": 1,
                "target_record_count": len(self.targets),
                "output_record_count": len(self.records),
            },
            "reference_accession": SCORING_REFERENCE_ACCESSION,
            "target_accessions": [record.sequence_id for record in self.targets],
            "records": [record.metadata() for record in self.records],
            "ordering": "AAB57849.1_first_then_target_id_lexical_ascending",
            "healthy_empty": not self.targets,
        }

    def metadata_json(self) -> str:
        return _canonical_json_text(self.metadata())


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_json_text(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    ) + "\n"


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def _selection_contract_payload(
    *,
    contract_id: str,
    selected_accessions: tuple[str, ...],
    output_name: str,
    implementation_digest_value: str,
) -> dict[str, object]:
    excluded_accessions = tuple(
        accession
        for accession in NCBI_REFERENCE_ACCESSIONS
        if accession not in selected_accessions
    )
    return {
        "contract_id": contract_id,
        "scientific_claim": (
            "deterministic AOX reference identity selection from one sealed "
            "NCBI protein FASTA; no sequence identity replacement"
        ),
        "input": {
            "provider": "ncbi",
            "database": "protein",
            "exact_accessions": list(NCBI_REFERENCE_ACCESSIONS),
            "exact_record_count": len(NCBI_REFERENCE_ACCESSIONS),
            "missing_extra_duplicate_records": "rejected",
            "identity_resolution": {
                "default": "exact_header_accession_token",
                "9AVH_A": "exact_ncbi_pdb_token_pdb|9AVH|A",
                "identity_replacement": False,
            },
            "encoding": "strict_utf8",
            "residues": "uppercase_ungapped_IUPAC_protein_without_stop",
        },
        "selection": {
            "selected_accessions": list(selected_accessions),
            "excluded_accessions": list(excluded_accessions),
            "output_order": "fixed_contract_accession_order",
        },
        "output": {
            "name": output_name,
            "format": "canonical_fasta",
            "header": "exact_selected_accession_only",
            "sequence": "uppercase_single_line",
            "terminal_newline": True,
            "sequence_bytes": "unchanged_from_selected_input_record",
        },
        "implementation_digest": implementation_digest_value,
    }


def hmm_reference_set_selection_contract_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    return _selection_contract_payload(
        contract_id=HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        selected_accessions=HMM_REFERENCE_ACCESSIONS,
        output_name=HMM_REFERENCE_SET_OUTPUT_NAME,
        implementation_digest_value=(
            implementation_digest_value or implementation_digest()
        ),
    )


def scoring_reference_selection_contract_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    return _selection_contract_payload(
        contract_id=SCORING_REFERENCE_SELECTION_CONTRACT_ID,
        selected_accessions=(SCORING_REFERENCE_ACCESSION,),
        output_name=SCORING_REFERENCE_OUTPUT_NAME,
        implementation_digest_value=(
            implementation_digest_value or implementation_digest()
        ),
    )


def scoring_input_assembly_contract_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    return {
        "contract_id": SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        "scientific_claim": (
            "deterministic unaligned scoring input assembly; alignment remains a "
            "separate real HMMalign operation"
        ),
        "inputs": {
            "scoring_reference_fasta": {
                "exact_record_count": 1,
                "exact_accession": SCORING_REFERENCE_ACCESSION,
            },
            "post_uniprot_target_fasta": {
                "healthy_empty": "zero_bytes",
                "sequence_ids": "unique",
                "reference_accession_forbidden": True,
            },
            "encoding": "strict_utf8",
            "residues": "uppercase_ungapped_IUPAC_protein_without_stop",
        },
        "output": {
            "name": SCORING_INPUT_OUTPUT_NAME,
            "format": "canonical_fasta",
            "ordering": "AAB57849.1_first_then_target_id_lexical_ascending",
            "header": "exact_sequence_id_only",
            "sequence": "uppercase_single_line",
            "terminal_newline": True,
            "healthy_empty": "reference_only_fasta",
        },
        "implementation_digest": (
            implementation_digest_value or implementation_digest()
        ),
    }


def _contract_digest(payload: dict[str, object]) -> str:
    return _sha256(_canonical_json_bytes(payload))


def hmm_reference_set_selection_contract_digest(
    *, implementation_digest_value: str | None = None
) -> str:
    return _contract_digest(
        hmm_reference_set_selection_contract_payload(
            implementation_digest_value=implementation_digest_value
        )
    )


def scoring_reference_selection_contract_digest(
    *, implementation_digest_value: str | None = None
) -> str:
    return _contract_digest(
        scoring_reference_selection_contract_payload(
            implementation_digest_value=implementation_digest_value
        )
    )


def scoring_input_assembly_contract_digest(
    *, implementation_digest_value: str | None = None
) -> str:
    return _contract_digest(
        scoring_input_assembly_contract_payload(
            implementation_digest_value=implementation_digest_value
        )
    )


def _validate_digest(value: str, *, field: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ScientificPrerequisiteError(
            "aox_reference_bound_digest_invalid",
            "an AOX reference contract or file digest is not canonical sha256",
            details={"field": field, "value": value},
        )


def _verify_contract(
    *,
    label: str,
    expected_contract_id: str,
    expected_contract_digest: str,
    expected_implementation_digest: str,
    actual_contract_id: str,
    actual_contract_digest: str,
    actual_implementation_digest: str,
) -> None:
    _validate_digest(
        expected_contract_digest,
        field=f"{label}.expected_contract_digest",
    )
    _validate_digest(
        expected_implementation_digest,
        field=f"{label}.expected_implementation_digest",
    )
    expected = {
        "contract_id": expected_contract_id,
        "contract_digest": expected_contract_digest,
        "implementation_digest": expected_implementation_digest,
    }
    actual = {
        "contract_id": actual_contract_id,
        "contract_digest": actual_contract_digest,
        "implementation_digest": actual_implementation_digest,
    }
    if expected != actual:
        raise ScientificPrerequisiteError(
            "aox_reference_contract_digest_drift",
            "the bound AOX reference contract does not match the installed implementation",
            details={"label": label, "expected": expected, "actual": actual},
        )


def verify_hmm_reference_set_selection_contract(
    *,
    expected_contract_id: str = HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    _verify_contract(
        label="hmm_reference_set_selection",
        expected_contract_id=expected_contract_id,
        expected_contract_digest=(
            expected_contract_digest
            or HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            expected_implementation_digest
            or HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        actual_contract_id=HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
        actual_contract_digest=HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
        actual_implementation_digest=(
            HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
    )


def verify_scoring_reference_selection_contract(
    *,
    expected_contract_id: str = SCORING_REFERENCE_SELECTION_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    _verify_contract(
        label="scoring_reference_selection",
        expected_contract_id=expected_contract_id,
        expected_contract_digest=(
            expected_contract_digest
            or SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            expected_implementation_digest
            or SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        actual_contract_id=SCORING_REFERENCE_SELECTION_CONTRACT_ID,
        actual_contract_digest=SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST,
        actual_implementation_digest=(
            SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
    )


def verify_scoring_input_assembly_contract(
    *,
    expected_contract_id: str = SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    _verify_contract(
        label="scoring_input_assembly",
        expected_contract_id=expected_contract_id,
        expected_contract_digest=(
            expected_contract_digest or SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        ),
        expected_implementation_digest=(
            expected_implementation_digest
            or SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        actual_contract_id=SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
        actual_contract_digest=SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST,
        actual_implementation_digest=SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST,
    )


def _input_bytes(data: str | bytes) -> bytes:
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def _resolve_ncbi_source_id(source_id: str) -> tuple[str, str]:
    if source_id in _EXPECTED_NCBI_ACCESSION_SET:
        return source_id, "exact_header_accession_token"
    if source_id == _PDB_SOURCE_ID:
        return _PDB_REQUEST_ID, "exact_ncbi_pdb_token_pdb|9AVH|A"
    return source_id, "unrecognized"


def _parse_fasta(
    data: str | bytes,
    *,
    label: str,
    allow_empty: bool,
    resolve_ncbi_ids: bool,
) -> tuple[tuple[FastaRecord, ...], str]:
    raw = _input_bytes(data)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "aox_reference_fasta_not_utf8",
            "an AOX reference FASTA input is not valid UTF-8",
            details={"input": label, "start": exc.start},
        ) from exc

    records: list[FastaRecord] = []
    header: str | None = None
    fragments: list[str] = []

    def finish_record() -> None:
        nonlocal header, fragments
        if header is None:
            return
        source_id, separator, description = header.partition(" ")
        if not source_id:
            raise ScientificPrerequisiteError(
                "aox_reference_fasta_header_empty",
                "an AOX reference FASTA header is empty",
                details={"input": label},
            )
        sequence = "".join(fragments)
        if not sequence:
            raise ScientificPrerequisiteError(
                "aox_reference_fasta_sequence_empty",
                "an AOX reference FASTA record has no sequence",
                details={"input": label, "source_id": source_id},
            )
        if _SEQUENCE_PATTERN.fullmatch(sequence) is None:
            invalid = sorted(set(sequence) - set("ACDEFGHIKLMNPQRSTVWYBXZJUO"))
            raise ScientificPrerequisiteError(
                "aox_reference_fasta_residue_invalid",
                "AOX reference inputs require uppercase ungapped protein residues without stops",
                details={
                    "input": label,
                    "source_id": source_id,
                    "invalid_characters": invalid,
                },
            )
        if resolve_ncbi_ids:
            sequence_id, resolution_rule = _resolve_ncbi_source_id(source_id)
        else:
            sequence_id, resolution_rule = (
                source_id,
                "exact_header_accession_token",
            )
        if not resolve_ncbi_ids and _SEQUENCE_ID_PATTERN.fullmatch(sequence_id) is None:
            raise ScientificPrerequisiteError(
                "aox_scoring_target_id_invalid",
                "a scoring target FASTA identifier is not canonical",
                details={"input": label, "sequence_id": sequence_id},
            )
        records.append(
            FastaRecord(
                sequence_id=sequence_id,
                source_id=source_id,
                description=description if separator else "",
                sequence=sequence,
                identity_resolution_rule=resolution_rule,
            )
        )
        header = None
        fragments = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if raw_line.startswith(">"):
            finish_record()
            header = raw_line[1:]
            if not header or header != header.strip():
                raise ScientificPrerequisiteError(
                    "aox_reference_fasta_header_invalid",
                    "an AOX reference FASTA header is empty or has surrounding whitespace",
                    details={"input": label, "line": line_number},
                )
            fragments = []
            continue
        if header is None:
            raise ScientificPrerequisiteError(
                "aox_reference_fasta_sequence_before_header",
                "AOX reference FASTA sequence data appeared before its header",
                details={"input": label, "line": line_number},
            )
        if raw_line != raw_line.strip() or any(
            character.isspace() for character in raw_line
        ):
            raise ScientificPrerequisiteError(
                "aox_reference_fasta_sequence_whitespace",
                "AOX reference FASTA sequence lines may not contain whitespace",
                details={"input": label, "line": line_number},
            )
        fragments.append(raw_line)
    finish_record()

    if not records and not allow_empty:
        raise ScientificPrerequisiteError(
            "aox_reference_fasta_empty",
            "an AOX reference FASTA input contains no records",
            details={"input": label},
        )
    if not records and raw:
        raise ScientificPrerequisiteError(
            "aox_reference_fasta_empty_not_canonical",
            "a healthy-empty scoring target FASTA must be exactly zero bytes",
            details={"input": label, "input_digest": _sha256(raw)},
        )

    sequence_ids = [record.sequence_id for record in records]
    duplicates = sorted(
        sequence_id
        for sequence_id in set(sequence_ids)
        if sequence_ids.count(sequence_id) > 1
    )
    if duplicates:
        raise ScientificPrerequisiteError(
            "aox_reference_fasta_duplicate_identity",
            "AOX reference and scoring FASTA inputs require unique sequence identities",
            details={"input": label, "sequence_ids": duplicates},
        )
    return tuple(records), _sha256(raw)


def _parse_exact_ncbi_reference_set(
    ncbi_fasta: str | bytes,
    *,
    expected_input_digest: str | None,
) -> tuple[tuple[FastaRecord, ...], str]:
    records, input_digest = _parse_fasta(
        ncbi_fasta,
        label="ncbi_reference_fasta",
        allow_empty=False,
        resolve_ncbi_ids=True,
    )
    if expected_input_digest is not None:
        _validate_digest(expected_input_digest, field="expected_input_digest")
        if input_digest != expected_input_digest:
            raise ScientificPrerequisiteError(
                "aox_reference_input_digest_mismatch",
                "the NCBI reference FASTA does not match its bound file digest",
                details={
                    "expected_input_digest": expected_input_digest,
                    "actual_input_digest": input_digest,
                },
            )
    actual = {record.sequence_id for record in records}
    missing = sorted(_EXPECTED_NCBI_ACCESSION_SET - actual)
    unexpected = sorted(actual - _EXPECTED_NCBI_ACCESSION_SET)
    if (
        len(records) != len(NCBI_REFERENCE_ACCESSIONS)
        or missing
        or unexpected
        or any(record.identity_resolution_rule == "unrecognized" for record in records)
    ):
        raise ScientificPrerequisiteError(
            "aox_ncbi_reference_identity_set_mismatch",
            "the sealed NCBI FASTA must contain exactly the fixed 14 AOX identities",
            details={
                "expected_record_count": len(NCBI_REFERENCE_ACCESSIONS),
                "actual_record_count": len(records),
                "missing_accessions": missing,
                "unexpected_accessions": unexpected,
            },
        )
    return records, input_digest


def select_hmm_reference_set(
    ncbi_fasta: str | bytes,
    *,
    expected_contract_id: str = HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_input_digest: str | None = None,
) -> HmmReferenceSetSelectionResult:
    verify_hmm_reference_set_selection_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    records, input_digest = _parse_exact_ncbi_reference_set(
        ncbi_fasta,
        expected_input_digest=expected_input_digest,
    )
    by_accession = {record.sequence_id: record for record in records}
    selected = tuple(by_accession[accession] for accession in HMM_REFERENCE_ACCESSIONS)
    return HmmReferenceSetSelectionResult(
        source_records=records,
        selected_records=selected,
        input_digest=input_digest,
    )


def select_scoring_reference(
    ncbi_fasta: str | bytes,
    *,
    expected_contract_id: str = SCORING_REFERENCE_SELECTION_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_input_digest: str | None = None,
) -> ScoringReferenceSelectionResult:
    verify_scoring_reference_selection_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    records, input_digest = _parse_exact_ncbi_reference_set(
        ncbi_fasta,
        expected_input_digest=expected_input_digest,
    )
    by_accession = {record.sequence_id: record for record in records}
    return ScoringReferenceSelectionResult(
        source_records=records,
        reference=by_accession[SCORING_REFERENCE_ACCESSION],
        input_digest=input_digest,
    )


def assemble_scoring_input(
    scoring_reference_fasta: str | bytes,
    post_uniprot_target_fasta: str | bytes,
    *,
    expected_contract_id: str = SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_scoring_reference_input_digest: str | None = None,
    expected_target_input_digest: str | None = None,
) -> ScoringInputAssemblyResult:
    verify_scoring_input_assembly_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    references, reference_digest = _parse_fasta(
        scoring_reference_fasta,
        label="scoring_reference_fasta",
        allow_empty=False,
        resolve_ncbi_ids=False,
    )
    targets, target_digest = _parse_fasta(
        post_uniprot_target_fasta,
        label="post_uniprot_target_fasta",
        allow_empty=True,
        resolve_ncbi_ids=False,
    )
    if expected_scoring_reference_input_digest is not None:
        _validate_digest(
            expected_scoring_reference_input_digest,
            field="expected_scoring_reference_input_digest",
        )
        if reference_digest != expected_scoring_reference_input_digest:
            raise ScientificPrerequisiteError(
                "aox_scoring_reference_input_digest_mismatch",
                "the scoring reference FASTA does not match its bound file digest",
                details={
                    "expected_input_digest": expected_scoring_reference_input_digest,
                    "actual_input_digest": reference_digest,
                },
            )
    if expected_target_input_digest is not None:
        _validate_digest(
            expected_target_input_digest,
            field="expected_target_input_digest",
        )
        if target_digest != expected_target_input_digest:
            raise ScientificPrerequisiteError(
                "aox_scoring_target_input_digest_mismatch",
                "the scoring target FASTA does not match its bound file digest",
                details={
                    "expected_input_digest": expected_target_input_digest,
                    "actual_input_digest": target_digest,
                },
            )
    if (
        len(references) != 1
        or references[0].sequence_id != SCORING_REFERENCE_ACCESSION
        or references[0].source_id != SCORING_REFERENCE_ACCESSION
    ):
        raise ScientificPrerequisiteError(
            "aox_scoring_reference_identity_mismatch",
            "the scoring reference input must contain only exact AAB57849.1",
            details={
                "record_count": len(references),
                "sequence_ids": [record.sequence_id for record in references],
            },
        )
    if any(
        target.sequence_id == SCORING_REFERENCE_ACCESSION for target in targets
    ):
        raise ScientificPrerequisiteError(
            "aox_scoring_target_contains_reference",
            "post-UniProt targets may not contain the scoring reference accession",
            details={"reference_accession": SCORING_REFERENCE_ACCESSION},
        )
    canonical_targets = tuple(sorted(targets, key=lambda record: record.sequence_id))
    return ScoringInputAssemblyResult(
        reference=references[0],
        targets=canonical_targets,
        scoring_reference_input_digest=reference_digest,
        target_input_digest=target_digest,
    )


HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST = implementation_digest()
SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST = (
    HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
)
SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST = (
    HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
)
HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST = (
    hmm_reference_set_selection_contract_digest(
        implementation_digest_value=(
            HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        )
    )
)
SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST = (
    scoring_reference_selection_contract_digest(
        implementation_digest_value=(
            SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        )
    )
)
SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST = scoring_input_assembly_contract_digest(
    implementation_digest_value=SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
)


__all__ = [
    "HMM_REFERENCE_ACCESSIONS",
    "HMM_REFERENCE_SET_OUTPUT_NAME",
    "HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST",
    "HMM_REFERENCE_SET_SELECTION_CONTRACT_ID",
    "HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST",
    "NCBI_REFERENCE_ACCESSIONS",
    "SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST",
    "SCORING_INPUT_ASSEMBLY_CONTRACT_ID",
    "SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST",
    "SCORING_INPUT_OUTPUT_NAME",
    "SCORING_REFERENCE_ACCESSION",
    "SCORING_REFERENCE_OUTPUT_NAME",
    "SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST",
    "SCORING_REFERENCE_SELECTION_CONTRACT_ID",
    "SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST",
    "FastaRecord",
    "HmmReferenceSetSelectionResult",
    "ScientificPrerequisiteError",
    "ScoringInputAssemblyResult",
    "ScoringReferenceSelectionResult",
    "assemble_scoring_input",
    "hmm_reference_set_selection_contract_digest",
    "hmm_reference_set_selection_contract_payload",
    "implementation_digest",
    "scoring_input_assembly_contract_digest",
    "scoring_input_assembly_contract_payload",
    "scoring_reference_selection_contract_digest",
    "scoring_reference_selection_contract_payload",
    "select_hmm_reference_set",
    "select_scoring_reference",
    "verify_hmm_reference_set_selection_contract",
    "verify_scoring_input_assembly_contract",
    "verify_scoring_reference_selection_contract",
]
