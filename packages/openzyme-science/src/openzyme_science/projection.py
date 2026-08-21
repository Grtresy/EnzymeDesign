from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ExtensionStateRecord

from .transaction import SCIENCE_STATE_NAMESPACE


SCIENCE_COLLECTIONS = (
    ("attempt", "attempts"),
    ("selection", "selections"),
    ("disposition", "dispositions"),
    ("effect_adoption", "adoptions"),
    ("deliverable", "deliverables"),
    ("attempt_closure", "closures"),
)


class ScienceProjectionStateQuery(Protocol):
    """Authorized Session query; implementations never expose their storage handle."""

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
class ScienceExtensionStateProjectionApplication:
    query: ScienceProjectionStateQuery

    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]:
        if not actor_id:
            raise ValueError("Science projection requires an authenticated actor")
        if not 1 <= max_items <= 200:
            raise ValueError("Science projection item budget is invalid")
        records, next_cursor = self.query.list_session_records(
            namespace=SCIENCE_STATE_NAMESPACE,
            session_id=session_id,
            entity_kinds=tuple(kind for kind, _ in SCIENCE_COLLECTIONS),
            after_cursor=cursor,
            limit=max_items,
        )
        collection_by_kind = dict(SCIENCE_COLLECTIONS)
        payload: dict[str, JsonValue] = {
            collection: [] for _, collection in SCIENCE_COLLECTIONS
        }
        for record in records:
            collection = collection_by_kind.get(record.entity_kind)
            if collection is None:
                raise ValueError("Science projection query returned an unknown entity kind")
            if record.namespace != SCIENCE_STATE_NAMESPACE:
                raise ValueError("Science projection query crossed its namespace")
            if record.payload.get("session_id") != session_id:
                raise ValueError("Science projection query crossed its Session")
            row = {
                "entity_id": record.entity_id,
                "state_version": record.state_version,
                "record_digest": record.record_digest,
                **dict(record.payload),
            }
            cast_collection = payload[collection]
            assert isinstance(cast_collection, list)
            cast_collection.append(row)
        payload["task_finished"] = False
        return payload, next_cursor


@dataclass(frozen=True, slots=True)
class ScienceUiRenderer:
    """Read-only renderer owned by Science; it never mutates Core UI state."""

    renderer_id: str = "openzyme.science.renderer@1"

    def render(self, payload: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        expected = {collection for _, collection in SCIENCE_COLLECTIONS} | {
            "task_finished"
        }
        if set(payload) != expected or payload.get("task_finished") is not False:
            raise ValueError("Science renderer payload contract drifted")
        rendered: dict[str, JsonValue] = {
            "renderer_id": self.renderer_id,
            "task_finished": False,
        }
        for _, collection in SCIENCE_COLLECTIONS:
            records = payload[collection]
            if not isinstance(records, list):
                raise ValueError("Science renderer collection is not a list")
            rendered[f"{collection}_count"] = len(records)
            rendered[collection] = records
        return rendered


__all__ = [
    "SCIENCE_COLLECTIONS",
    "ScienceExtensionStateProjectionApplication",
    "ScienceProjectionStateQuery",
    "ScienceUiRenderer",
]
