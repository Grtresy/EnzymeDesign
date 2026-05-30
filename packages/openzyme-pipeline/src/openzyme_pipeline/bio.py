from __future__ import annotations

from typing import Any

from .client import call


def ncbi_fetch_proteins(
    *,
    accessions: list[str],
    output_dir: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio.ncbi_fetch_proteins",
            {
                "accessions": list(accessions),
                "fields": list(fields or []),
                "output_dir": output_dir,
            },
        )
    )


def uniprot_fetch(
    *,
    accessions: list[str],
    output_dir: str,
    fields: list[str] | None = None,
    batch_size: int | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio.uniprot_fetch",
            {
                "accessions": list(accessions),
                "fields": list(fields or []),
                "batch_size": batch_size,
                "output_dir": output_dir,
            },
        )
    )


def hmmer_search(
    *,
    hmm_artifact_id: str,
    database: str,
    output_dir: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio.hmmer_search",
            {
                "hmm_artifact_id": hmm_artifact_id,
                "database": database,
                "params": dict(params or {}),
                "output_dir": output_dir,
            },
        )
    )


__all__ = ["hmmer_search", "ncbi_fetch_proteins", "uniprot_fetch"]
