from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.model import (  # noqa: E402
    REPLAY_CORPUS_SCHEMA_ID,
    canonical_document_bytes,
    seal_document,
)
from scripts.test_gate.replay import (  # noqa: E402
    REPLAY_CASE_COUNT,
    ReplayCorpusError,
    load_replay_corpus,
)

CORPUS_PATH = REPOSITORY_ROOT / "scripts" / "test-replay-corpus.json"


def _raw_corpus() -> dict[str, object]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _publish_mutation(
    tmp_path: Path,
    mutate,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fields = _raw_corpus()
    fields.pop("schema_id")
    fields.pop("self_digest")
    mutate(fields)
    document = seal_document(REPLAY_CORPUS_SCHEMA_ID, fields)
    path = tmp_path / "corpus.json"
    path.write_bytes(canonical_document_bytes(document))
    return path


def test_replay_corpus_is_exact_immutable_and_source_addressable() -> None:
    corpus = load_replay_corpus(CORPUS_PATH)

    assert len(corpus.cases) == REPLAY_CASE_COUNT
    assert len(corpus.proof_node_ids) == REPLAY_CASE_COUNT
    assert corpus.self_digest == (
        "sha256:136cacea60eb8022fbe58672c0c4801545a381cb00343c455c7a2406f898d202"
    )
    for node_id in corpus.proof_node_ids:
        relative_path, test_name = node_id.split("::", 1)
        source_path = REPOSITORY_ROOT / relative_path
        assert source_path.is_file()
        function_name = test_name.split("[", 1)[0]
        assert f"def {function_name}(" in source_path.read_text(encoding="utf-8")


def test_replay_corpus_closes_against_current_general_collection() -> None:
    corpus = load_replay_corpus(CORPUS_PATH)

    closed = load_replay_corpus(
        CORPUS_PATH,
        collected_nodes=corpus.proof_node_ids,
    )
    assert closed.proof_node_ids == corpus.proof_node_ids

    with pytest.raises(ReplayCorpusError, match="proof nodes drifted"):
        load_replay_corpus(
            CORPUS_PATH,
            collected_nodes=corpus.proof_node_ids[:-1],
        )


def test_replay_corpus_rejects_case_count_order_and_open_green_projection(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReplayCorpusError, match="exactly 20 cases"):
        load_replay_corpus(
            _publish_mutation(
                tmp_path,
                lambda fields: fields["cases"].pop(),  # type: ignore[union-attr]
            )
        )

    def reverse_cases(fields: dict[str, object]) -> None:
        cases = fields["cases"]
        assert isinstance(cases, list)
        cases.reverse()

    with pytest.raises(ReplayCorpusError, match="sorted and unique"):
        load_replay_corpus(
            _publish_mutation(tmp_path / "reverse", reverse_cases)
        )

    def open_green(fields: dict[str, object]) -> None:
        cases = fields["cases"]
        assert isinstance(cases, list)
        first = cases[0]
        assert isinstance(first, dict)
        projection = first["expected_projection"]
        assert isinstance(projection, dict)
        projection["frontend_status"] = "not_run"

    with pytest.raises(ReplayCorpusError, match="not fully closed"):
        load_replay_corpus(
            _publish_mutation(tmp_path / "green", open_green)
        )


def test_replay_corpus_rejects_duplicate_proof_nodes_and_digest_tamper(
    tmp_path: Path,
) -> None:
    def duplicate_proof(fields: dict[str, object]) -> None:
        cases = fields["cases"]
        assert isinstance(cases, list)
        first = cases[0]
        assert isinstance(first, dict)
        nodes = first["proof_node_ids"]
        assert isinstance(nodes, list)
        nodes.append(nodes[0])

    with pytest.raises(ReplayCorpusError, match="not sorted and unique"):
        load_replay_corpus(
            _publish_mutation(tmp_path, duplicate_proof)
        )

    tampered = CORPUS_PATH.read_bytes().replace(
        b"green full-stack source revision",
        b"green full-stack source revisioN",
    )
    path = tmp_path / "tampered.json"
    path.write_bytes(tampered)
    with pytest.raises(ReplayCorpusError, match="self_digest mismatch"):
        load_replay_corpus(path)
