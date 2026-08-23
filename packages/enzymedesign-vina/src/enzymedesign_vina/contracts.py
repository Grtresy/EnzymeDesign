from __future__ import annotations

from openzyme_contracts import canonical_sha256_digest


VINA_PLUGIN_ID = "enzymedesign.vina"
VINA_PLUGIN_CONTRACT = "enzymedesign.vina@1"
VINA_DOCK_TOOL = "enzymedesign.vina.dock"
VINA_VERSION_SPEC = ">=1.1.2,<2"
VINA_LEGACY_VERSION_SPEC = "==1.1.2"
VINA_MODERN_VERSION_SPEC = ">=1.2,<2"
VINA_LEGACY_WORKLOAD_CONTRACT = "enzymedesign.vina.dock.legacy@1"
VINA_MODERN_WORKLOAD_CONTRACT = "enzymedesign.vina.dock.modern@1"
VINA_LEGACY_RESULT_CONTRACT = "enzymedesign.vina.result.legacy@1"
VINA_MODERN_RESULT_CONTRACT = "enzymedesign.vina.result.modern@1"
VINA_LEGACY_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": VINA_LEGACY_RESULT_CONTRACT,
        "profile": "legacy-log-v1",
        "required": [
            "result_revision_id",
            "poses_path",
            "score_path",
            "result_digest",
            "vina_result_profile",
            "score_semantics",
        ],
        "score_semantics": "legacy-log-file-v1",
        "formal_only_through_compute": True,
        "raw_shell_is_exploratory": True,
    }
)
VINA_MODERN_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": VINA_MODERN_RESULT_CONTRACT,
        "profile": "modern-poses-remark-v1",
        "required": [
            "result_revision_id",
            "poses_path",
            "score_path",
            "result_digest",
            "vina_result_profile",
            "score_semantics",
        ],
        "score_semantics": "poses-remark-derived-file-v1",
        "formal_only_through_compute": True,
        "raw_shell_is_exploratory": True,
    }
)


__all__ = [
    "VINA_DOCK_TOOL",
    "VINA_PLUGIN_CONTRACT",
    "VINA_PLUGIN_ID",
    "VINA_LEGACY_RESULT_CONTRACT",
    "VINA_LEGACY_RESULT_SCHEMA_DIGEST",
    "VINA_LEGACY_VERSION_SPEC",
    "VINA_LEGACY_WORKLOAD_CONTRACT",
    "VINA_MODERN_RESULT_CONTRACT",
    "VINA_MODERN_RESULT_SCHEMA_DIGEST",
    "VINA_MODERN_VERSION_SPEC",
    "VINA_MODERN_WORKLOAD_CONTRACT",
    "VINA_VERSION_SPEC",
]
