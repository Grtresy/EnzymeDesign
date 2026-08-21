from __future__ import annotations

from openzyme_contracts import canonical_sha256_digest


STRUCTURE_PLUGIN_ID = "enzymedesign.structure"
FPOCKET_TOOL_NAME = "enzymedesign.fpocket.detect"
FPOCKET_VERSION_SPEC = ">=4,<5"
FPOCKET_WORKLOAD_CONTRACT = "enzymedesign.fpocket.workload@1"
FPOCKET_RESULT_CONTRACT = "enzymedesign.fpocket.result@1"
FPOCKET_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": FPOCKET_RESULT_CONTRACT,
        "required": ["result_root", "terminal_receipt", "raw_shell"],
        "raw_shell": False,
        "task_finished": False,
    }
)

__all__ = [
    "FPOCKET_RESULT_CONTRACT",
    "FPOCKET_RESULT_SCHEMA_DIGEST",
    "FPOCKET_TOOL_NAME",
    "FPOCKET_VERSION_SPEC",
    "FPOCKET_WORKLOAD_CONTRACT",
    "STRUCTURE_PLUGIN_ID",
]
