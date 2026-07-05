from __future__ import annotations

from typing import Any

from .client import call
from .client import controlled_operation
from .client import supervised_sandbox_mode


_ROUTE_POLICY_IDS = {
    "download_structure": "rcsb_pdb.download_structure.provider:v1",
}


def _default_output_dir(pdb_id: str) -> str:
    safe_id = "".join(char.lower() for char in pdb_id if char.isalnum()) or "structure"
    return f"/workspace/output/rcsb_pdb/{safe_id}"


def download_structure(
    *,
    pdb_id: str,
    format: str = "pdb",
    output_dir: str | None = None,
) -> dict[str, Any]:
    normalized_id = str(pdb_id).strip().upper()
    normalized_format = str(format or "pdb").strip().lower()
    target_output_dir = output_dir or _default_output_dir(normalized_id)
    params = {
        "pdb_id": normalized_id,
        "format": normalized_format,
        "output_dir": target_output_dir,
    }
    if supervised_sandbox_mode():
        return dict(
            controlled_operation(
                sdk_module="rcsb_pdb",
                function_name="download_structure",
                route_policy_id=_ROUTE_POLICY_IDS["download_structure"],
                params=params,
                expected_outputs={"output_dir": target_output_dir},
                resource_estimate={"network_io": True},
            )
        )
    return dict(call("rcsb_pdb.download_structure", params))


__all__ = ["download_structure"]
