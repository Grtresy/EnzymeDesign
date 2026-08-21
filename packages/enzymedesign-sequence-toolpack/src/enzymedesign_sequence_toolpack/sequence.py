from __future__ import annotations

from dataclasses import dataclass
import re

from openzyme_contracts import canonical_sha256_digest


_SEQUENCE_RE = re.compile(r"[A-Za-z*.-]+")
_ALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ*.-")


@dataclass(frozen=True, slots=True)
class SequenceRecord:
    record_id: str
    description: str
    sequence: str
    sequence_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "description": self.description,
            "sequence": self.sequence,
            "length": len(self.sequence),
            "sequence_digest": self.sequence_digest,
        }


def _normalize_sequence(value: str) -> str:
    sequence = "".join(value.split()).upper()
    if not sequence or _SEQUENCE_RE.fullmatch(sequence) is None:
        raise ValueError("sequence must contain one non-empty bounded residue string")
    invalid = sorted(set(sequence) - _ALLOWED)
    if invalid:
        raise ValueError("sequence contains unsupported residue symbols")
    if len(sequence) > 10_000_000:
        raise ValueError("sequence exceeds the bounded parser limit")
    return sequence


def parse_sequence_text(value: str, *, format_name: str) -> tuple[SequenceRecord, ...]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 12_000_000:
        raise ValueError("sequence input exceeds the bounded parser limit")
    if format_name == "plain":
        sequence = _normalize_sequence(value)
        return (
            SequenceRecord(
                record_id="sequence-1",
                description="",
                sequence=sequence,
                sequence_digest=canonical_sha256_digest(
                    {"alphabet": "protein-or-nucleic@1", "sequence": sequence}
                ),
            ),
        )
    if format_name != "fasta":
        raise ValueError("format_name must be fasta or plain")
    records: list[SequenceRecord] = []
    current_header: str | None = None
    current_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_header is not None:
                records.append(_build_record(current_header, current_lines))
            current_header = line[1:].strip()
            current_lines = []
            if not current_header:
                raise ValueError("FASTA header must be non-empty")
        else:
            if current_header is None:
                raise ValueError("FASTA sequence data must follow a header")
            current_lines.append(line)
    if current_header is not None:
        records.append(_build_record(current_header, current_lines))
    if not records or len(records) > 10_000:
        raise ValueError("FASTA record count is outside the bounded parser limit")
    identifiers = [record.record_id for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("FASTA record identifiers must be unique")
    return tuple(records)


def _build_record(header: str, lines: list[str]) -> SequenceRecord:
    record_id, _, description = header.partition(" ")
    sequence = _normalize_sequence("".join(lines))
    return SequenceRecord(
        record_id=record_id,
        description=description.strip(),
        sequence=sequence,
        sequence_digest=canonical_sha256_digest(
            {"alphabet": "protein-or-nucleic@1", "sequence": sequence}
        ),
    )


__all__ = ["SequenceRecord", "parse_sequence_text"]
