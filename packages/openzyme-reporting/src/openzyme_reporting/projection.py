from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionStateRecord

from .transaction import REPORTING_STATE_NAMESPACE


REPORTING_COLLECTIONS = (
    ("draft", "drafts"),
    ("report_version", "reports"),
    ("render_receipt", "renders"),
    ("validation_receipt", "validations"),
)


class ReportingProjectionStateQuery(Protocol):
    """Authorized Session query that never exposes its Store handle."""

    def list_session_records(
        self,
        *,
        namespace: str,
        session_id: str,
        entity_kinds: tuple[str, ...],
        after_cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ExtensionStateRecord, ...], str | None]: ...


@dataclass(slots=True)
class ReportingExtensionStateProjectionApplication:
    query: ReportingProjectionStateQuery

    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]:
        if not actor_id:
            raise ValueError("Reporting projection requires an authenticated actor")
        if not 1 <= max_items <= 200:
            raise ValueError("Reporting projection item budget is invalid")
        records, next_cursor = self.query.list_session_records(
            namespace=REPORTING_STATE_NAMESPACE,
            session_id=session_id,
            entity_kinds=tuple(kind for kind, _ in REPORTING_COLLECTIONS),
            after_cursor=cursor,
            limit=max_items,
        )
        collection_by_kind = dict(REPORTING_COLLECTIONS)
        payload: dict[str, JsonValue] = {
            collection: [] for _, collection in REPORTING_COLLECTIONS
        }
        for record in records:
            collection = collection_by_kind.get(record.entity_kind)
            if collection is None:
                raise ValueError(
                    "Reporting projection query returned an unknown entity kind"
                )
            if record.namespace != REPORTING_STATE_NAMESPACE:
                raise ValueError("Reporting projection query crossed its namespace")
            if record.payload.get("session_id") != session_id:
                raise ValueError("Reporting projection query crossed its Session")
            row = {
                "entity_id": record.entity_id,
                "state_version": record.state_version,
                "record_digest": record.record_digest,
                **dict(record.payload),
            }
            target = payload[collection]
            assert isinstance(target, list)
            target.append(row)
        payload["task_finished"] = False
        return payload, next_cursor


@dataclass(frozen=True, slots=True)
class ReportingUiRenderer:
    """Read-only Reporting renderer; Core UI never interprets its payload."""

    renderer_id: str = "openzyme.reporting.renderer@1"

    def render(self, payload: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        expected = {collection for _, collection in REPORTING_COLLECTIONS} | {
            "task_finished"
        }
        if set(payload) != expected or payload.get("task_finished") is not False:
            raise ValueError("Reporting renderer payload contract drifted")
        rendered: dict[str, JsonValue] = {
            "renderer_id": self.renderer_id,
            "task_finished": False,
        }
        for _, collection in REPORTING_COLLECTIONS:
            records = payload[collection]
            if not isinstance(records, list):
                raise ValueError("Reporting renderer collection is not a list")
            rendered[f"{collection}_count"] = len(records)
            rendered[collection] = records
        return rendered


__all__ = [
    "REPORTING_COLLECTIONS",
    "ReportingExtensionStateProjectionApplication",
    "ReportingProjectionStateQuery",
    "ReportingUiRenderer",
]
