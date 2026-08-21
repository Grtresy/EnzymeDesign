from __future__ import annotations

from enum import StrEnum

from openzyme_contracts import canonical_sha256_digest


HMMER_PLUGIN_ID = "enzymedesign.hmmer"
HMMER_PLUGIN_CONTRACT = "enzymedesign.hmmer@1"
HMMER_BUILD_TOOL = "enzymedesign.hmmer.build"
HMMER_SEARCH_TOOL = "enzymedesign.hmmer.search"
HMMER_BUILD_WORKLOAD_CONTRACT = "enzymedesign.hmmer.build@1"
HMMER_SEARCH_WORKLOAD_CONTRACT = "enzymedesign.hmmer.search@1"
HMMER_RESULT_CONTRACT = "enzymedesign.hmmer.result@1"
HMMER_VERSION_SPEC = ">=3.3,<4"

HMMER_RESULT_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "contract_id": HMMER_RESULT_CONTRACT,
        "required": [
            "operation",
            "result_revision_id",
            "result_root",
            "result_digest",
        ],
        "formal_only_through_compute": True,
        "raw_shell_is_exploratory": True,
    }
)


class HmmerOperation(StrEnum):
    BUILD = "build"
    SEARCH = "search"

    @property
    def executable(self) -> str:
        return "hmmbuild" if self is HmmerOperation.BUILD else "hmmsearch"

    @property
    def workload_contract(self) -> str:
        return (
            HMMER_BUILD_WORKLOAD_CONTRACT
            if self is HmmerOperation.BUILD
            else HMMER_SEARCH_WORKLOAD_CONTRACT
        )


__all__ = [
    "HMMER_BUILD_TOOL",
    "HMMER_BUILD_WORKLOAD_CONTRACT",
    "HMMER_PLUGIN_CONTRACT",
    "HMMER_PLUGIN_ID",
    "HMMER_RESULT_CONTRACT",
    "HMMER_RESULT_SCHEMA_DIGEST",
    "HMMER_SEARCH_TOOL",
    "HMMER_SEARCH_WORKLOAD_CONTRACT",
    "HMMER_VERSION_SPEC",
    "HmmerOperation",
]
