from __future__ import annotations

from openzyme_contracts import canonical_sha256_digest


VINA_PLUGIN_ID = "enzymedesign.vina"
VINA_PLUGIN_CONTRACT = "enzymedesign.vina@1"
VINA_DOCK_TOOL = "enzymedesign.vina.dock"
VINA_WORKLOAD_CONTRACT = "enzymedesign.vina.dock@1"
VINA_RESULT_CONTRACT = "enzymedesign.vina.result@1"
VINA_VERSION_SPEC = ">=1.2,<2"
VINA_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": VINA_RESULT_CONTRACT,
        "required": ["result_revision_id", "poses_path", "score_path", "result_digest"],
        "formal_only_through_compute": True,
        "raw_shell_is_exploratory": True,
    }
)


__all__ = [
    "VINA_DOCK_TOOL",
    "VINA_PLUGIN_CONTRACT",
    "VINA_PLUGIN_ID",
    "VINA_RESULT_CONTRACT",
    "VINA_RESULT_SCHEMA_DIGEST",
    "VINA_VERSION_SPEC",
    "VINA_WORKLOAD_CONTRACT",
]
