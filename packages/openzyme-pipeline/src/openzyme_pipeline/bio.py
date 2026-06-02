from __future__ import annotations

from typing import Any

from .client import call
from .client import controlled_operation
from .client import supervised_sandbox_mode


_ROUTE_POLICY_IDS = {
    "ncbi_fetch_proteins": "bio.ncbi_fetch_proteins.provider:v1",
    "uniprot_fetch": "bio.uniprot_fetch.provider:v1",
    "hmmer_search": "bio.hmmer_search.provider:v1",
}


def _provider_operation(
    *,
    function_name: str,
    params: dict[str, Any],
    output_dir: str,
) -> dict[str, Any]:
    return dict(
        controlled_operation(
            sdk_module="bio",
            function_name=function_name,
            route_policy_id=_ROUTE_POLICY_IDS[function_name],
            params=params,
            expected_outputs={"output_dir": output_dir},
            resource_estimate={"network_io": True},
        )
    )


def ncbi_fetch_proteins(
    *,
    accessions: list[str],
    output_dir: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    params = {
        "accessions": list(accessions),
        "fields": list(fields or []),
        "output_dir": output_dir,
    }
    if supervised_sandbox_mode():
        return _provider_operation(
            function_name="ncbi_fetch_proteins",
            params=params,
            output_dir=output_dir,
        )
    return dict(
        call(
            "bio.ncbi_fetch_proteins",
            params,
        )
    )


def uniprot_fetch(
    *,
    accessions: list[str],
    output_dir: str,
    fields: list[str] | None = None,
    batch_size: int | None = None,
) -> dict[str, Any]:
    params = {
        "accessions": list(accessions),
        "fields": list(fields or []),
        "batch_size": batch_size,
        "output_dir": output_dir,
    }
    if supervised_sandbox_mode():
        return _provider_operation(
            function_name="uniprot_fetch",
            params=params,
            output_dir=output_dir,
        )
    return dict(
        call(
            "bio.uniprot_fetch",
            params,
        )
    )


def hmmer_search(
    *,
    hmm_artifact_id: str,
    database: str,
    output_dir: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "hmm_artifact_id": hmm_artifact_id,
        "database": database,
        "params": dict(params or {}),
        "output_dir": output_dir,
    }
    if supervised_sandbox_mode():
        return _provider_operation(
            function_name="hmmer_search",
            params=payload,
            output_dir=output_dir,
        )
    return dict(
        call(
            "bio.hmmer_search",
            payload,
        )
    )


__all__ = ["hmmer_search", "ncbi_fetch_proteins", "uniprot_fetch"]
