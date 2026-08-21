from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import ProjectionResult
from openzyme_extension_spi import WorkerClaim
from openzyme_extension_spi import WorkerClaimRequest


HPC_PROJECTION_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme.hpc@1",
        "safe_fields": [
            "workspace_id",
            "workspace_state",
            "local_workspace_generation",
            "remote_workspace_generation",
            "target_id",
            "target_profile_digest",
            "qualification_digest",
            "inventory_generation",
            "inventory_digest",
            "route_id",
            "operation_id",
            "result_id",
        ],
        "forbidden": [
            "hostname",
            "login_alias",
            "remote_root",
            "credential",
            "scheduler_job_id",
            "raw_log",
        ],
    }
)
HPC_RENDERER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_ui_renderer_contract@1",
        "renderer_id": "openzyme.hpc.renderer@1",
        "section_id": "openzyme.hpc@1",
        "read_only": True,
        "requires_exact_section_contract": HPC_PROJECTION_CONTRACT_DIGEST,
        "mutates_core_state": False,
    }
)
HPC_WORKER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_worker_contract@1",
        "worker_id": "openzyme.hpc.worker@1",
        "owner_plugin_id": "openzyme.hpc",
        "operations": ["cleanup", "observe", "qualify", "reconcile"],
        "bounded_claim": True,
        "fallback": False,
    }
)


class HpcProjectionApplication(Protocol):
    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]: ...


@dataclass(slots=True)
class HpcProjectionContributor:
    application: HpcProjectionApplication
    section_id: str = "openzyme.hpc@1"
    section_contract_digest: str = HPC_PROJECTION_CONTRACT_DIGEST

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        payload, next_cursor = self.application.project(
            session_id=request.context.session_id,
            actor_id=request.context.actor_id,
            max_items=request.max_items,
            cursor=request.cursor,
        )
        bounded = dict(payload)
        if len(str(bounded).encode("utf-8")) > request.max_bytes:
            raise ValueError("HPC projection exceeds the requested byte budget")
        return ProjectionResult(
            section_id=self.section_id,
            section_contract_digest=self.section_contract_digest,
            payload=bounded,
            next_cursor=next_cursor,
            projection_digest=canonical_sha256_digest(
                {
                    "section_id": self.section_id,
                    "section_contract_digest": self.section_contract_digest,
                    "payload": bounded,
                    "next_cursor": next_cursor,
                }
            ),
        )


class HpcWorkerApplication(Protocol):
    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]: ...

    def run(self, claim: WorkerClaim) -> ToolResult: ...


@dataclass(slots=True)
class HpcWorkerContributor:
    application: HpcWorkerApplication
    worker_id: str = "openzyme.hpc.worker@1"

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]:
        if request.owner_plugin_id != "openzyme.hpc":
            return ()
        return self.application.claim(request)

    def run(self, claim: WorkerClaim) -> ToolResult:
        return self.application.run(claim)


__all__ = [
    "HPC_PROJECTION_CONTRACT_DIGEST",
    "HPC_RENDERER_CONTRACT_DIGEST",
    "HPC_WORKER_CONTRACT_DIGEST",
    "HpcProjectionApplication",
    "HpcProjectionContributor",
    "HpcWorkerApplication",
    "HpcWorkerContributor",
]
