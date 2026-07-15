from __future__ import annotations

from pathlib import Path

from openzyme_runtime import immutable_source_tree_digest


def test_immutable_source_tree_digest_ignores_bytecode_and_detects_source_drift(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "openzyme_pipeline"
    source_root.mkdir()
    source_file = source_root / "client.py"
    source_file.write_text("PROTOCOL = 'v1'\n", encoding="utf-8")

    initial_digest = immutable_source_tree_digest(source_root)
    cache_dir = source_root / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "client.cpython-312.pyc").write_bytes(b"ephemeral bytecode")
    (source_root / "generated.pyo").write_bytes(b"optimized bytecode")

    assert immutable_source_tree_digest(source_root) == initial_digest

    source_file.write_text("PROTOCOL = 'v2'\n", encoding="utf-8")

    assert immutable_source_tree_digest(source_root) != initial_digest
