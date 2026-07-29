"""Closed immutable replay corpus for pre-cutover mainline parity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .model import (
    REPLAY_CORPUS_SCHEMA_ID,
    load_canonical_document_bytes,
)

REPLAY_CASE_COUNT = 20
DEFAULT_REPLAY_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "test-replay-corpus.json"
)
_CASE_FIELDS = {
    "case_id",
    "boundary",
    "representative_change_shape",
    "expected_projection",
    "proof_node_ids",
}
_PROJECTION_FIELDS = {
    "terminal_status",
    "coverage_status",
    "qualification_status",
    "frontend_status",
    "first_failing_boundary",
}
_TERMINAL_STATUSES = {"pass", "fail"}
_COVERAGE_STATUSES = {"exact", "not_emitted", "rejected"}
_QUALIFICATION_STATUSES = {"verified", "failed", "not_run"}
_FRONTEND_STATUSES = {"pass", "fail", "not_run"}


class ReplayCorpusError(ValueError):
    """Raised when the agreed replay corpus is open, stale, or malformed."""


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    boundary: str
    representative_change_shape: str
    expected_projection: Mapping[str, object]
    proof_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReplayCorpus:
    corpus_id: str
    equivalence_basis: str
    cases: tuple[ReplayCase, ...]
    self_digest: str

    @property
    def proof_node_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    node_id
                    for case in self.cases
                    for node_id in case.proof_node_ids
                }
            )
        )


def _nonempty_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayCorpusError(f"{context} must be a nonempty string")
    return value


def _projection(value: Any, *, case_id: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _PROJECTION_FIELDS:
        raise ReplayCorpusError(
            f"replay case {case_id!r} expected_projection fields drifted"
        )
    terminal = value["terminal_status"]
    coverage = value["coverage_status"]
    qualification = value["qualification_status"]
    frontend = value["frontend_status"]
    first_failing = value["first_failing_boundary"]
    if terminal not in _TERMINAL_STATUSES:
        raise ReplayCorpusError(
            f"replay case {case_id!r} terminal status is invalid"
        )
    if coverage not in _COVERAGE_STATUSES:
        raise ReplayCorpusError(
            f"replay case {case_id!r} coverage status is invalid"
        )
    if qualification not in _QUALIFICATION_STATUSES:
        raise ReplayCorpusError(
            f"replay case {case_id!r} qualification status is invalid"
        )
    if frontend not in _FRONTEND_STATUSES:
        raise ReplayCorpusError(
            f"replay case {case_id!r} frontend status is invalid"
        )
    if first_failing is not None and (
        not isinstance(first_failing, str) or not first_failing
    ):
        raise ReplayCorpusError(
            f"replay case {case_id!r} first failing boundary is invalid"
        )
    if terminal == "pass":
        if (
            coverage != "exact"
            or qualification != "verified"
            or frontend != "pass"
            or first_failing is not None
        ):
            raise ReplayCorpusError(
                f"green replay case {case_id!r} is not fully closed"
            )
    elif first_failing is None:
        raise ReplayCorpusError(
            f"failing replay case {case_id!r} lacks its first boundary"
        )
    return dict(value)


def load_replay_corpus(
    path: Path,
    *,
    collected_nodes: Sequence[str] | None = None,
) -> ReplayCorpus:
    """Load and close the exact twenty-case parity corpus."""

    if path.is_symlink():
        raise ReplayCorpusError("replay corpus must not be a symlink")
    try:
        document = load_canonical_document_bytes(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReplayCorpusError(f"cannot load replay corpus: {exc}") from exc
    if document.get("schema_id") != REPLAY_CORPUS_SCHEMA_ID:
        raise ReplayCorpusError("replay corpus schema is invalid")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != REPLAY_CASE_COUNT:
        raise ReplayCorpusError(
            f"replay corpus must contain exactly {REPLAY_CASE_COUNT} cases"
        )
    cases: list[ReplayCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict) or set(raw) != _CASE_FIELDS:
            raise ReplayCorpusError(f"replay case {index} fields drifted")
        case_id = _nonempty_string(raw["case_id"], context=f"cases[{index}].case_id")
        proof_node_ids = raw["proof_node_ids"]
        if (
            not isinstance(proof_node_ids, list)
            or not proof_node_ids
            or any(
                not isinstance(node_id, str) or not node_id
                for node_id in proof_node_ids
            )
            or proof_node_ids != sorted(set(proof_node_ids))
        ):
            raise ReplayCorpusError(
                f"replay case {case_id!r} proof nodes are not sorted and unique"
            )
        cases.append(
            ReplayCase(
                case_id=case_id,
                boundary=_nonempty_string(
                    raw["boundary"],
                    context=f"replay case {case_id!r} boundary",
                ),
                representative_change_shape=_nonempty_string(
                    raw["representative_change_shape"],
                    context=f"replay case {case_id!r} change shape",
                ),
                expected_projection=_projection(
                    raw["expected_projection"],
                    case_id=case_id,
                ),
                proof_node_ids=tuple(proof_node_ids),
            )
        )
    case_ids = tuple(case.case_id for case in cases)
    if case_ids != tuple(sorted(set(case_ids))):
        raise ReplayCorpusError("replay case ids must be sorted and unique")
    corpus = ReplayCorpus(
        corpus_id=_nonempty_string(
            document.get("corpus_id"),
            context="corpus_id",
        ),
        equivalence_basis=_nonempty_string(
            document.get("equivalence_basis"),
            context="equivalence_basis",
        ),
        cases=tuple(cases),
        self_digest=str(document["self_digest"]),
    )
    if collected_nodes is not None:
        current = set(collected_nodes)
        missing = sorted(set(corpus.proof_node_ids) - current)
        if missing:
            raise ReplayCorpusError(
                "replay corpus proof nodes drifted from current non-live G: "
                + ", ".join(missing)
            )
    return corpus
