from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from openzyme_host_api.aox_closure_stage_source import _qualify_event_cut
from openzyme_host_api.aox_closure_stage_source import (
    _qualify_process_retirement,
)
from openzyme_host_api.aox_closure_stage_source import (
    _qualify_scientific_graph,
)
from openzyme_host_api.aox_closure_stage_source import (
    qualify_aox_closure_stage_source,
)
from openzyme_host_api.aox_closure_stage_source import (
    resolve_aox_closure_stage_source_inventory,
)
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError


_R59_DATABASE = Path(
    "/tmp/openzyme-aox-cutover/"
    "r59-aox_campaign_43f2726e7fad2738b135abd1/"
    "positive-c3c2c4cc13a367fb54eec84505a61742/"
    "control-plane.sqlite3"
)
_R59_SOURCE = {
    "attempt_root": str(_R59_DATABASE.parent),
    "session_id": (
        "sess_formal_positive_c3c2c4cc13a367fb54eec84505a61742"
    ),
    "execution_task_id": (
        "aox_execution_cutover_positive_"
        "c3c2c4cc13a367fb54eec84505a61742"
    ),
    "executor_agent_id": "agent:executor:805a9b201353",
    "selection_id": "selection_090ab4b6c30e4839d60dd664",
    "operation_universe_digest": (
        "sha256:f131d838c00f88d55e26c142627153fb"
        "2a7c7d0f03ea69bae4d6b4f87223cb55"
    ),
    "cut_cursor": 614,
    "first_post_cut_cursor": 615,
}


def _source_inventory(tmp_path: Path, *, wal: bytes) -> dict[str, object]:
    campaign_id = "aox_campaign_" + "a" * 24
    attempt_id = "positive-" + "b" * 32
    campaign_root = tmp_path / f"r59-{campaign_id}"
    attempt_root = campaign_root / attempt_id
    attempt_root.mkdir(parents=True)
    database = attempt_root / "control-plane.sqlite3"
    database.write_bytes(b"not-opened-because-wal-gate-runs-first")
    if wal:
        Path(str(database) + "-wal").write_bytes(wal)
    authority_root = tmp_path / "source-authority"
    authority_root.mkdir()
    authority_plan = authority_root / "attempt-authority.json"
    authority_plan.write_bytes(b"source-plan")
    authority_consumption = (
        authority_root / "attempt-authority.json.consumed.json"
    )
    authority_consumption.write_bytes(b"source-consumption")
    return resolve_aox_closure_stage_source_inventory(
        campaign_root=campaign_root,
        attempt_id=attempt_id,
        campaign_id=campaign_id,
        session_id="sess_formal_positive_" + "b" * 32,
        execution_task_id=(
            "aox_execution_cutover_positive_" + "b" * 32
        ),
        executor_agent_id="agent:executor:" + "c" * 12,
        selection_id="selection_" + "d" * 24,
        operation_universe_digest="sha256:" + "e" * 64,
        authority_plan_path=authority_plan,
        authority_consumption_path=authority_consumption,
    )


def test_source_qualification_rejects_nonzero_wal_before_sqlite_open(
    tmp_path: Path,
) -> None:
    inventory = _source_inventory(tmp_path, wal=b"pending-frame")
    database = Path(str(inventory["database_path"]))
    database_digest = str(inventory["database_sha256"])

    with pytest.raises(CutoverEvidenceError) as error:
        qualify_aox_closure_stage_source(
            source_inventory=inventory,
            diagnostic_id="aox_closure_stage_" + "f" * 24,
            process_probe=lambda *args: (_ for _ in ()).throw(
                AssertionError(args)
            ),
        )

    assert error.value.code == "closure_stage_source_wal_not_empty"
    assert str(inventory["database_sha256"]) == database_digest
    assert database.read_bytes() == (
        b"not-opened-because-wal-gate-runs-first"
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("change", "closure_stage_source_inventory_drift"),
        ("remove", "closure_stage_source_path_invalid"),
    ),
)
def test_source_qualification_rejects_inventory_drift_before_sqlite(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    inventory = _source_inventory(tmp_path, wal=b"")
    authority_plan = Path(str(inventory["authority_plan_path"]))
    if mutation == "change":
        authority_plan.write_bytes(b"changed-source-plan")
    else:
        authority_plan.unlink()

    with pytest.raises(CutoverEvidenceError) as error:
        qualify_aox_closure_stage_source(
            source_inventory=inventory,
            diagnostic_id="aox_closure_stage_" + "f" * 24,
        )

    assert error.value.code == expected_code


def test_source_retirement_rejects_live_process_observation(
    tmp_path: Path,
) -> None:
    attempt_id = "positive-" + "a" * 32
    campaign_root = tmp_path / "r59-source"
    attempt_root = campaign_root / attempt_id
    failure_root = campaign_root / "failures"
    evidence_root = attempt_root / "evidence"
    failure_root.mkdir(parents=True)
    evidence_root.mkdir(parents=True)
    (failure_root / f"{attempt_id}.fatal.json").write_text(
        json.dumps(
            {
                "payload": {
                    "schema_id": "aox_live_attempt_fatal@1",
                    "attempt_id": attempt_id,
                    "descendant_retirement_proven": True,
                    "child_pid": 101,
                    "child_pgid": 101,
                    "child_start_time_ticks": 202,
                    "process_epoch": "b" * 32,
                }
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / ".attempt-supervision-result.json").write_text(
        json.dumps(
            {
                "schema_id": "aox_live_attempt_child_result@1",
                "attempt_id": attempt_id,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CutoverEvidenceError) as error:
        _qualify_process_retirement(
            {
                "campaign_root": str(campaign_root),
                "attempt_root": str(attempt_root),
                "attempt_id": attempt_id,
            },
            process_probe=lambda *_args: "live",
        )

    assert error.value.code == "closure_stage_source_process_still_live"


def _copy_r59_database(tmp_path: Path) -> sqlite3.Connection:
    target = tmp_path / "control-plane.sqlite3"
    shutil.copy2(_R59_DATABASE, target)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = OFF")
    trigger_names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    ]
    for trigger_name in trigger_names:
        escaped = trigger_name.replace('"', '""')
        connection.execute(f'DROP TRIGGER "{escaped}"')
    connection.commit()
    return connection


@pytest.mark.integration
@pytest.mark.skipif(
    not _R59_DATABASE.is_file(),
    reason="frozen local r59 source database is unavailable",
)
@pytest.mark.parametrize(
    ("mutation_sql", "expected_code"),
    (
        (
            "DELETE FROM durable_event_records WHERE cursor = 614",
            "closure_stage_source_event_cut_incomplete",
        ),
        (
            "UPDATE durable_event_records "
            "SET event_type = 'tool.completed' WHERE cursor = 614",
            "closure_stage_source_event_cut_mismatch",
        ),
    ),
)
def test_repository_backed_event_cut_rejects_missing_or_changed_boundary(
    tmp_path: Path,
    mutation_sql: str,
    expected_code: str,
) -> None:
    connection = _copy_r59_database(tmp_path)
    try:
        connection.execute(mutation_sql)
        connection.commit()
        with pytest.raises(CutoverEvidenceError) as error:
            _qualify_event_cut(connection, _R59_SOURCE)
    finally:
        connection.close()

    assert error.value.code == expected_code


@pytest.mark.integration
@pytest.mark.skipif(
    not _R59_DATABASE.is_file(),
    reason="frozen local r59 source database is unavailable",
)
@pytest.mark.parametrize(
    ("mutation_sql", "expected_code"),
    (
        (
            "UPDATE controlled_operation_execution_records "
            "SET effect_certainty = 'dispatch_in_doubt' "
            "WHERE operation_id = ("
            "SELECT operation_id "
            "FROM scientific_attempt_operation_bindings "
            "WHERE attempt_id = 'attempt_70e71f2afea317692f8364aa' "
            "ORDER BY operation_id LIMIT 1"
            ")",
            "closure_stage_source_external_effect_unsettled",
        ),
        (
            "UPDATE scientific_chain_selection_records "
            "SET state = 'draft', sealed_at = NULL "
            "WHERE selection_id = 'selection_090ab4b6c30e4839d60dd664'",
            "closure_stage_source_selection_invalid",
        ),
        (
            "INSERT INTO session_runtime_leases ("
            "lease_token, session_id, owner_id, mode, acquired_at, "
            "heartbeat_at, expires_at, released_at, last_error, fencing_token"
            ") VALUES ("
            "'lease_test_active', "
            "'sess_formal_positive_c3c2c4cc13a367fb54eec84505a61742', "
            "'test-owner', 'manual_drain', "
            "'2026-07-26T00:00:00+00:00', "
            "'2026-07-26T00:00:00+00:00', "
            "'2099-01-01T00:00:00+00:00', NULL, NULL, 999"
            ")",
            "closure_stage_source_quiescence_invalid",
        ),
        (
            "INSERT INTO scientific_attempt_closure_request_records ("
            "closure_request_id, attempt_id, selection_id, actor_ref, "
            "idempotency_key, request_digest, created_at"
            ") VALUES ("
            "'closure_request_test', "
            "'attempt_70e71f2afea317692f8364aa', "
            "'selection_090ab4b6c30e4839d60dd664', "
            "'agent:master', 'test-close', "
            "'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaa', "
            "'2026-07-26T00:00:00+00:00'"
            ")",
            "closure_stage_source_quiescence_invalid",
        ),
    ),
)
def test_repository_backed_scientific_graph_rejects_unsafe_source_state(
    tmp_path: Path,
    mutation_sql: str,
    expected_code: str,
) -> None:
    connection = _copy_r59_database(tmp_path)
    try:
        connection.execute(mutation_sql)
        connection.commit()
        cut_created_at = str(
            connection.execute(
                "SELECT created_at FROM durable_event_records "
                "WHERE cursor = 614"
            ).fetchone()[0]
        )
        with pytest.raises(CutoverEvidenceError) as error:
            _qualify_scientific_graph(
                connection,
                _R59_SOURCE,
                cut_created_at=cut_created_at,
            )
    finally:
        connection.close()

    assert error.value.code == expected_code
