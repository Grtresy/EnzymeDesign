from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_probe_request_binding


class BioProviderQualificationOperations(Protocol):
    def lookup_uniprot(self, *, accession: str) -> object: ...

    def search_rcsb_pdb(self, *, query: str, limit: int = 5) -> tuple[object, ...]: ...

    def query_interpro(self, *, accession: str, limit: int = 10) -> object: ...


@dataclass(slots=True)
class BioHttpQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    adapter: BioProviderQualificationOperations
    provider_id: str
    _outcomes: dict[str, ExternalQualificationProbeOutcome] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.binding.component_id != "enzymedesign.bio-provider-http":
            raise ValueError("Bio HTTP bridge requires the selected Adapter binding")
        if self.binding.operation != "read-smoke":
            raise ValueError("Bio HTTP bridge supports only read-smoke")
        if self.provider_id not in {"uniprot", "rcsb", "interpro"}:
            raise ValueError("Bio HTTP bridge provider is unsupported")
        if self.binding.route_id != (
            f"enzymedesign.bio-provider-http.{self.provider_id}.read@1"
        ):
            raise ValueError(
                "Bio HTTP bridge requires the exact selected Provider route"
            )
        if self.binding.credential_locator_id is not None:
            raise ValueError(
                "public Bio HTTP qualification must not receive credentials"
            )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        if request.attempt_id in self._outcomes:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "Bio HTTP qualification attempt cannot be dispatched twice",
            )
        try:
            if self.provider_id == "uniprot":
                result: object = self.adapter.lookup_uniprot(accession="P69905")
            elif self.provider_id == "rcsb":
                result = self.adapter.search_rcsb_pdb(query="1CRN", limit=1)
                if len(result) != 1:
                    raise ValueError("RCSB qualification requires one result")
            else:
                result = self.adapter.query_interpro(accession="P69905", limit=1)
            payload = self._payload(result)
            receipt_digest = canonical_sha256_digest(
                {"provider_id": self.provider_id, "result": payload}
            )
            outcome = ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                observed_operation=request.operation,
                output_digest=canonical_sha256_digest(
                    {"backend_receipt_digest": receipt_digest}
                ),
                observed_result_schema_digest=request.expected_result_schema_digest,
                backend_receipt_digest=receipt_digest,
                external_effect_performed=True,
                credential_material_accessed=False,
                fallback_performed=False,
            )
        except (OSError, RuntimeError, ValueError):
            outcome = ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.FAILED,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                observed_operation=None,
                output_digest=None,
                observed_result_schema_digest=None,
                backend_receipt_digest=None,
                error_code="qualification_bio_http_read_failed",
                external_effect_performed=True,
                credential_material_accessed=False,
                fallback_performed=False,
            )
        self._outcomes[request.attempt_id] = outcome
        return outcome

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        try:
            return self._outcomes[request.attempt_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "Bio HTTP reconcile requires the same prior attempt",
            ) from exc

    @staticmethod
    def _payload(result: object) -> object:
        if isinstance(result, tuple):
            return [asdict(item) for item in result]
        return asdict(result)  # type: ignore[arg-type]


__all__ = ["BioHttpQualificationProbeBridge"]
