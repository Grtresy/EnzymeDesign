from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from .client import call
from .client import controlled_operation
from .client import supervised_sandbox_mode


_ROUTE_POLICY_IDS = {
    "ncbi_fetch_proteins": "bio.ncbi_fetch_proteins.provider:v1",
    "uniprot_fetch": "bio.uniprot_fetch.provider:v1",
    "hmmer_search": "bio.hmmer_search.provider:v1",
}

_SHA256_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _validated_provider_output_dir(output_dir: str) -> str:
    if (
        not isinstance(output_dir, str)
        or not output_dir
        or output_dir != output_dir.strip()
        or any(character in output_dir for character in ("\\", "\n", "\r", "\0"))
    ):
        raise ValueError(
            "bio provider output_dir must be a canonical absolute path under "
            "/workspace/output, for example /workspace/output/bio/ncbi"
        )
    path = PurePosixPath(output_dir)
    parts = path.parts
    if (
        not path.is_absolute()
        or len(parts) < 4
        or parts[:3] != ("/", "workspace", "output")
        or any(part in {"", ".", ".."} for part in parts[3:])
    ):
        raise ValueError(
            "bio provider output_dir must be a canonical absolute path under "
            "/workspace/output, for example /workspace/output/bio/ncbi"
        )
    return output_dir


def _validated_provider_input_refs(
    input_refs: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    refs: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    artifact_digests: list[str] = []
    for raw_item in input_refs or []:
        item = dict(raw_item)
        if set(item) != {"artifact_id", "content_digest"}:
            raise ValueError(
                "provider input refs require exactly artifact_id and content_digest"
            )
        artifact_id = item.get("artifact_id")
        content_digest = item.get("content_digest")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or artifact_id != artifact_id.strip()
        ):
            raise ValueError(
                "provider input refs require a non-empty canonical artifact_id"
            )
        if not isinstance(content_digest, str) or not _SHA256_DIGEST_PATTERN.fullmatch(
            content_digest
        ):
            raise ValueError(
                "provider input refs require content_digest as sha256:<64 lowercase hex>"
            )
        artifact_ids.append(artifact_id)
        artifact_digests.append(content_digest)
        refs.append(
            {
                "artifact_id": artifact_id,
                "content_digest": content_digest,
            }
        )
    return refs, artifact_ids, artifact_digests


def _provider_operation(
    *,
    function_name: str,
    params: dict[str, Any],
    output_dir: str,
    input_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refs, artifact_ids, artifact_digests = _validated_provider_input_refs(input_refs)
    return dict(
        controlled_operation(
            sdk_module="bio",
            function_name=function_name,
            route_policy_id=_ROUTE_POLICY_IDS[function_name],
            params=params,
            expected_outputs={"output_dir": output_dir},
            resource_estimate={"network_io": True},
            input_artifact_ids=artifact_ids,
            input_artifact_digests=artifact_digests,
            stage_refs=refs,
        )
    )


def ncbi_fetch_proteins(
    *,
    accessions: list[str],
    output_dir: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch NCBI proteins into an absolute directory below ``/workspace/output``."""

    output_dir = _validated_provider_output_dir(output_dir)
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
    source_sequence_identities: dict[str, dict[str, str]] | None = None,
    sequence_mismatch_choices: dict[str, str] | None = None,
    source_hit_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch UniProt records below ``/workspace/output`` with source identity bound."""

    output_dir = _validated_provider_output_dir(output_dir)
    source_refs, _, _ = _validated_provider_input_refs(
        [] if source_hit_artifact is None else [dict(source_hit_artifact)]
    )
    canonical_source_hit_artifact = source_refs[0] if source_refs else {}
    params = {
        "accessions": list(accessions),
        "fields": list(fields or []),
        "batch_size": batch_size,
        "source_sequence_identities": dict(source_sequence_identities or {}),
        "sequence_mismatch_choices": dict(sequence_mismatch_choices or {}),
        "source_hit_artifact": canonical_source_hit_artifact,
        "output_dir": output_dir,
    }
    if supervised_sandbox_mode():
        return _provider_operation(
            function_name="uniprot_fetch",
            params=params,
            output_dir=output_dir,
            input_refs=source_refs,
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
    hmm_artifact_digest: str | None = None,
    database: str,
    output_dir: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the provider HMMER search with output below ``/workspace/output``."""

    output_dir = _validated_provider_output_dir(output_dir)
    payload = {
        "hmm_artifact_id": hmm_artifact_id,
        "hmm_artifact_digest": hmm_artifact_digest,
        "database": database,
        "params": dict(params or {}),
        "output_dir": output_dir,
    }
    if supervised_sandbox_mode():
        return _provider_operation(
            function_name="hmmer_search",
            params=payload,
            output_dir=output_dir,
            input_refs=[
                {
                    "artifact_id": hmm_artifact_id,
                    "content_digest": hmm_artifact_digest,
                }
            ],
        )
    return dict(
        call(
            "bio.hmmer_search",
            payload,
        )
    )


__all__ = ["hmmer_search", "ncbi_fetch_proteins", "uniprot_fetch"]
