from __future__ import annotations

import json
import sqlite3

import pytest

from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import ExtensionStateStoreError
from openzyme_store_sqlite import SQLiteExtensionStateProjectionQuery


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE openzyme_store_extension_state_records (
            namespace TEXT NOT NULL,
            entity_kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            state_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            record_digest TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, entity_kind, entity_id)
        )
        """
    )
    return connection


def _insert(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    entity_kind: str,
    entity_id: str,
    session_id: str,
) -> None:
    payload = {"session_id": session_id, "state": "open"}
    digest = canonical_sha256_digest(
        {
            "namespace": namespace,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "state_version": 1,
            "payload": payload,
        }
    )
    connection.execute(
        """
        INSERT INTO openzyme_store_extension_state_records (
            namespace, entity_kind, entity_id, state_version,
            payload_json, record_digest, updated_at
        ) VALUES (?, ?, ?, 1, ?, ?, ?)
        """,
        (
            namespace,
            entity_kind,
            entity_id,
            json.dumps(payload, sort_keys=True),
            digest,
            "2026-08-21T00:00:00+00:00",
        ),
    )
    connection.commit()


def test_projection_query_is_session_namespace_and_cursor_bound() -> None:
    connection = _connection()
    for entity_kind, entity_id, session_id in (
        ("attempt", "attempt-1", "session-1"),
        ("attempt", "attempt-2", "session-2"),
        ("selection", "selection-1", "session-1"),
    ):
        _insert(
            connection,
            namespace="openzyme_science",
            entity_kind=entity_kind,
            entity_id=entity_id,
            session_id=session_id,
        )
    _insert(
        connection,
        namespace="openzyme_reporting",
        entity_kind="report",
        entity_id="report-1",
        session_id="session-1",
    )
    query = SQLiteExtensionStateProjectionQuery.create(
        connection,
        allowed_namespaces=("openzyme_science",),
    )

    first, cursor = query.list_session_records(
        namespace="openzyme_science",
        session_id="session-1",
        entity_kinds=("attempt", "selection"),
        after_cursor=None,
        limit=1,
    )
    second, final_cursor = query.list_session_records(
        namespace="openzyme_science",
        session_id="session-1",
        entity_kinds=("attempt", "selection"),
        after_cursor=cursor,
        limit=1,
    )

    assert [(item.entity_kind, item.entity_id) for item in first] == [
        ("attempt", "attempt-1")
    ]
    assert cursor is not None
    assert [(item.entity_kind, item.entity_id) for item in second] == [
        ("selection", "selection-1")
    ]
    assert final_cursor is None

    with pytest.raises(ExtensionStateStoreError) as raised:
        query.list_session_records(
            namespace="openzyme_reporting",
            session_id="session-1",
            entity_kinds=("report",),
            after_cursor=None,
            limit=20,
        )
    assert raised.value.phase == "projection_namespace"


def test_projection_query_rejects_cursor_from_another_entity_family() -> None:
    connection = _connection()
    _insert(
        connection,
        namespace="openzyme_science",
        entity_kind="attempt",
        entity_id="attempt-1",
        session_id="session-1",
    )
    _insert(
        connection,
        namespace="openzyme_science",
        entity_kind="attempt",
        entity_id="attempt-2",
        session_id="session-1",
    )
    query = SQLiteExtensionStateProjectionQuery.create(
        connection,
        allowed_namespaces=("openzyme_science",),
    )
    _, cursor = query.list_session_records(
        namespace="openzyme_science",
        session_id="session-1",
        entity_kinds=("attempt",),
        after_cursor=None,
        limit=1,
    )
    assert cursor is not None

    with pytest.raises(ValueError, match="cursor"):
        query.list_session_records(
            namespace="openzyme_science",
            session_id="session-1",
            entity_kinds=("selection",),
            after_cursor=cursor,
            limit=1,
        )


def test_exact_extension_record_query_is_session_and_namespace_bound() -> None:
    connection = _connection()
    _insert(
        connection,
        namespace="openzyme_science",
        entity_kind="attempt",
        entity_id="attempt-1",
        session_id="session-1",
    )
    query = SQLiteExtensionStateProjectionQuery.create(
        connection,
        allowed_namespaces=("openzyme_science",),
    )

    record = query.get_session_record(
        namespace="openzyme_science",
        session_id="session-1",
        entity_kind="attempt",
        entity_id="attempt-1",
    )

    assert record is not None
    assert record.entity_id == "attempt-1"
    assert (
        query.get_session_record(
            namespace="openzyme_science",
            session_id="session-2",
            entity_kind="attempt",
            entity_id="attempt-1",
        )
        is None
    )
    with pytest.raises(ExtensionStateStoreError) as raised:
        query.get_session_record(
            namespace="openzyme_reporting",
            session_id="session-1",
            entity_kind="attempt",
            entity_id="attempt-1",
        )
    assert raised.value.phase == "projection_namespace"
