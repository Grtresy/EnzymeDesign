from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_core import BioProviderPort
from openzyme_contracts import ToolResult
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRouteInvocation


BIO_PROVIDER_PLUGIN_ID = "enzymedesign.bio-providers"
BIO_PROVIDER_ROUTE_IDS = {
    "enzymedesign.provider.interpro": "enzymedesign.interpro.http@1",
    "enzymedesign.provider.rcsb": "enzymedesign.rcsb.http@1",
    "enzymedesign.provider.uniprot": "enzymedesign.uniprot.http@1",
}


@dataclass(slots=True)
class BioProviderCapabilityRouteRuntime:
    route_id: str
    capability_id: str
    provider: BioProviderPort
    owner_plugin_id: str = BIO_PROVIDER_PLUGIN_ID
    driver_id: str | None = None

    def invoke(self, invocation: CapabilityRouteInvocation) -> ToolResult:
        if (
            invocation.route_id != self.route_id
            or invocation.capability_id != self.capability_id
        ):
            return self._rejected(invocation, "bio_provider_route_identity_invalid")
        try:
            payload = self._invoke_provider(dict(invocation.payload))
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "bio_provider_request_invalid"),
                str(exc),
            )
        payload.update(
            {
                "route_id": self.route_id,
                "fallback_performed": False,
                "publication_created": False,
                "scientific_evidence_created": False,
                "task_finished": False,
            }
        )
        return ToolResult(
            call_id=invocation.context.command_id,
            tool_name=invocation.capability_id,
            ok=True,
            status="completed",
            summary="The exact EnzymeDesign Provider route completed without fallback.",
            payload=payload,
        )

    def _invoke_provider(self, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        operation = str(payload["operation"])
        if self.capability_id == "enzymedesign.provider.uniprot":
            accession = str(payload["accession"])
            if operation == "lookup":
                record = self.provider.lookup_uniprot(accession=accession)
                return {
                    "state": "completed",
                    "provider": "uniprot",
                    "operation": operation,
                    "records": [record.to_dict()],
                    "item_count": 1,
                }
            if operation == "download_fasta":
                asset = self.provider.download_uniprot_fasta(accession=accession)
                return {
                    "state": "completed",
                    "provider": "uniprot",
                    "operation": operation,
                    "asset": asset.to_safe_dict(),
                    "item_count": 1,
                }
        elif self.capability_id == "enzymedesign.provider.rcsb":
            if operation == "search":
                records = self.provider.search_rcsb_pdb(
                    query=str(payload["query"]), limit=int(payload.get("limit", 5))
                )
                return {
                    "state": "completed",
                    "provider": "rcsb",
                    "operation": operation,
                    "records": [item.to_dict() for item in records],
                    "item_count": len(records),
                }
            if operation == "download_structure":
                asset = self.provider.download_rcsb_structure(
                    pdb_id=str(payload["pdb_id"]),
                    file_format=str(payload.get("file_format", "pdb")),
                )
                return {
                    "state": "completed",
                    "provider": "rcsb",
                    "operation": operation,
                    "asset": asset.to_safe_dict(),
                    "item_count": 1,
                }
        elif (
            self.capability_id == "enzymedesign.provider.interpro"
            and operation == "query"
        ):
            record = self.provider.query_interpro(
                accession=str(payload["accession"]),
                limit=int(payload.get("limit", 10)),
            )
            return {
                "state": "completed",
                "provider": "interpro",
                "operation": operation,
                "records": [record.to_dict()],
                "item_count": 1,
            }
        raise ValueError(
            "operation is not supported by the exact selected Provider route"
        )

    @staticmethod
    def _rejected(
        invocation: CapabilityRouteInvocation,
        error_code: str,
        summary: str = "EnzymeDesign Provider route rejected the request.",
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.context.command_id,
            tool_name=invocation.capability_id,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "publication_created": False,
                "scientific_evidence_created": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


def build_bio_provider_route_runtimes(
    provider: BioProviderPort,
) -> tuple[BioProviderCapabilityRouteRuntime, ...]:
    return tuple(
        BioProviderCapabilityRouteRuntime(
            route_id=route_id,
            capability_id=capability_id,
            provider=provider,
        )
        for capability_id, route_id in sorted(BIO_PROVIDER_ROUTE_IDS.items())
    )


__all__ = [
    "BIO_PROVIDER_PLUGIN_ID",
    "BIO_PROVIDER_ROUTE_IDS",
    "BioProviderCapabilityRouteRuntime",
    "build_bio_provider_route_runtimes",
]
