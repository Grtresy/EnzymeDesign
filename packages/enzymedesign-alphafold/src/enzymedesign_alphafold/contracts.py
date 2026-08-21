from __future__ import annotations

from openzyme_contracts import canonical_sha256_digest


ALPHAFOLD_PLUGIN_ID = "enzymedesign.alphafold"
ALPHAFOLD_TOOL_NAME = "enzymedesign.alphafold.predict"
ALPHAFOLD_VERSION_SPEC = ">=3,<4"
ALPHAFOLD_WORKLOAD_CONTRACT = "enzymedesign.alphafold.workload@1"
ALPHAFOLD_RESULT_CONTRACT = "enzymedesign.alphafold.result@1"
ALPHAFOLD_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": ALPHAFOLD_RESULT_CONTRACT,
        "required": ["result_root", "terminal_receipt", "raw_shell"],
        "raw_shell": False,
        "task_finished": False,
    }
)

__all__ = [
    "ALPHAFOLD_PLUGIN_ID",
    "ALPHAFOLD_RESULT_CONTRACT",
    "ALPHAFOLD_RESULT_SCHEMA_DIGEST",
    "ALPHAFOLD_TOOL_NAME",
    "ALPHAFOLD_VERSION_SPEC",
    "ALPHAFOLD_WORKLOAD_CONTRACT",
]
