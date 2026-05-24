from __future__ import annotations

from typing import Any

from .client import call


def cdhit(
    *,
    input_fasta_artifact_id: str,
    identity: float,
    mode: str = "protein",
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.cdhit",
            {
                "input_fasta_artifact_id": input_fasta_artifact_id,
                "identity": identity,
                "mode": mode,
            },
        )
    )


def mafft(
    *,
    input_fasta_artifact_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.mafft",
            {"input_fasta_artifact_id": input_fasta_artifact_id, "params": dict(params or {})},
        )
    )


def hmmbuild(
    *,
    alignment_artifact_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmbuild",
            {"alignment_artifact_id": alignment_artifact_id, "params": dict(params or {})},
        )
    )


def hmmalign(
    *,
    hmm_artifact_id: str,
    fasta_artifact_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmalign",
            {
                "hmm_artifact_id": hmm_artifact_id,
                "fasta_artifact_id": fasta_artifact_id,
                "params": dict(params or {}),
            },
        )
    )


def hmmer_search_cli(
    *,
    hmm_artifact_id: str,
    target_fasta_artifact_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmer_search_cli",
            {
                "hmm_artifact_id": hmm_artifact_id,
                "target_fasta_artifact_id": target_fasta_artifact_id,
                "params": dict(params or {}),
            },
        )
    )


__all__ = ["cdhit", "hmmalign", "hmmbuild", "hmmer_search_cli", "mafft"]
