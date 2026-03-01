from __future__ import annotations

from pathlib import Path

from mcp_hpc_tool_contracts.constants import (
    CANONICAL_SIF_IMAGES,
    CANONICAL_WRAPPER_ENTRYPOINTS,
)


def _manual_text() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    doc_path = repo_root / "docs" / "HPC服务器调用指南.md"
    return doc_path.read_text(encoding="utf-8")


def test_wrapper_entrypoints_match_manual() -> None:
    manual = _manual_text()
    for entrypoint in CANONICAL_WRAPPER_ENTRYPOINTS.values():
        assert entrypoint in manual


def test_sif_entrypoints_match_manual() -> None:
    manual = _manual_text()
    for image in CANONICAL_SIF_IMAGES.values():
        assert image in manual
    assert "cd-screening" in manual
    assert "caver" in manual
