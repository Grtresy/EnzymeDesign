from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote
from urllib.parse import urlparse


LIVE_MICU_TOKEN_HARD_LIMIT = 500_000_000
_LEGACY_LIVE_MICU_TOKEN_HARD_LIMIT = 100_000_000
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH = (
    _REPO_ROOT / ".openzyme/live_micu_token_ledger.sqlite3"
)
LIVE_MICU_TOKEN_LEDGER_PATH_ENV = "OPENZYME_TEST_LIVE_LLM_TOKEN_LEDGER_PATH"


class LiveMicuTokenBudgetExceededError(RuntimeError):
    """Raised before a live MICU provider call when its reservation cannot fit."""

    def __init__(
        self,
        *,
        requested_tokens: int,
        remaining_tokens: int,
        hard_limit_tokens: int,
    ) -> None:
        super().__init__(
            "live MICU token budget exhausted: "
            f"requested={requested_tokens} remaining={remaining_tokens} "
            f"hard_limit={hard_limit_tokens}"
        )
        self.requested_tokens = requested_tokens
        self.remaining_tokens = remaining_tokens
        self.hard_limit_tokens = hard_limit_tokens


class LiveMicuTokenReservationConfigurationError(ValueError):
    """Raised when a metered live call lacks a bounded output reservation."""


class LiveMicuTokenPolicyMigrationError(RuntimeError):
    """Raised when the explicit fixed-policy ledger migration cannot apply."""


@dataclass(frozen=True, slots=True)
class LiveMicuTokenReservation:
    record_id: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_tokens: int


@dataclass(frozen=True, slots=True)
class UsageTokenCounts:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LiveMicuTokenLedger:
    path: Path | str
    hard_limit_tokens: int = LIVE_MICU_TOKEN_HARD_LIMIT

    def __post_init__(self) -> None:
        requested_limit = int(self.hard_limit_tokens)
        if requested_limit <= 0:
            raise ValueError("hard_limit_tokens must be positive")
        object.__setattr__(
            self,
            "hard_limit_tokens",
            min(requested_limit, LIVE_MICU_TOKEN_HARD_LIMIT),
        )
        object.__setattr__(self, "path", Path(self.path))

    def reserve_attempt(
        self,
        *,
        scenario: str,
        purpose: str,
        kind: str,
        model: str | None,
        attempt: int,
        estimated_input_tokens: int,
        reserved_output_tokens: int | None,
    ) -> LiveMicuTokenReservation:
        input_tokens = max(1, int(estimated_input_tokens))
        if reserved_output_tokens is None or int(reserved_output_tokens) <= 0:
            raise LiveMicuTokenReservationConfigurationError(
                "metered live MICU calls require a positive reserved output token budget"
            )
        output_tokens = int(reserved_output_tokens)
        requested_tokens = input_tokens + output_tokens
        connection = self._connect_for_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            hard_limit = self._effective_limit(connection)
            charged = self._charged_tokens(connection)
            remaining = max(0, hard_limit - charged)
            if requested_tokens > remaining:
                connection.rollback()
                raise LiveMicuTokenBudgetExceededError(
                    requested_tokens=requested_tokens,
                    remaining_tokens=remaining,
                    hard_limit_tokens=hard_limit,
                )
            now = _utc_now_iso()
            cursor = connection.execute(
                """
                INSERT INTO live_micu_token_attempts (
                    scenario,
                    purpose,
                    kind,
                    model,
                    attempt,
                    input_tokens,
                    output_tokens,
                    charged_tokens,
                    estimated,
                    status,
                    cumulative_tokens,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'reserved', ?, ?, ?)
                """,
                (
                    scenario,
                    purpose,
                    kind,
                    model,
                    int(attempt),
                    input_tokens,
                    output_tokens,
                    requested_tokens,
                    charged + requested_tokens,
                    now,
                    now,
                ),
            )
            record_id = int(cursor.lastrowid)
            connection.commit()
            return LiveMicuTokenReservation(
                record_id=record_id,
                reserved_input_tokens=input_tokens,
                reserved_output_tokens=output_tokens,
                reserved_tokens=requested_tokens,
            )
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile_success(
        self,
        reservation: LiveMicuTokenReservation,
        usage: dict[str, Any] | None,
    ) -> None:
        counts = usage_token_counts(usage)
        if counts is None:
            self.finalize_estimated(reservation, status="succeeded_estimated")
            return
        connection = self._connect_for_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT charged_tokens FROM live_micu_token_attempts WHERE id = ?",
                (reservation.record_id,),
            ).fetchone()
            if previous is None:
                raise KeyError(f"unknown token reservation {reservation.record_id}")
            charged_before = self._charged_tokens(connection)
            charged_after = charged_before - int(previous[0]) + counts.total_tokens
            hard_limit = self._effective_limit(connection)
            reservation_overage = max(
                0,
                counts.total_tokens - reservation.reserved_tokens,
            )
            hard_limit_breached = int(charged_after > hard_limit)
            status = (
                "succeeded_limit_breached"
                if hard_limit_breached
                else "succeeded_overage"
                if reservation_overage
                else "succeeded"
            )
            connection.execute(
                """
                UPDATE live_micu_token_attempts
                SET input_tokens = ?,
                    output_tokens = ?,
                    charged_tokens = ?,
                    estimated = 0,
                    status = ?,
                    reservation_overage_tokens = ?,
                    hard_limit_breached = ?,
                    cumulative_tokens = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    counts.input_tokens,
                    counts.output_tokens,
                    counts.total_tokens,
                    status,
                    reservation_overage,
                    hard_limit_breached,
                    charged_after,
                    _utc_now_iso(),
                    reservation.record_id,
                ),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def finalize_estimated(
        self,
        reservation: LiveMicuTokenReservation,
        *,
        status: str,
    ) -> None:
        if status not in {"succeeded_estimated", "failed_estimated"}:
            raise ValueError(f"unsupported estimated status: {status}")
        connection = self._connect_for_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cumulative = self._charged_tokens(connection)
            cursor = connection.execute(
                """
                UPDATE live_micu_token_attempts
                SET status = ?, estimated = 1, cumulative_tokens = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, cumulative, _utc_now_iso(), reservation.record_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown token reservation {reservation.record_id}")
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def summary(self) -> dict[str, Any]:
        return summarize_live_micu_token_ledger(
            self.path,
            fallback_hard_limit=self.hard_limit_tokens,
        )

    def list_attempts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        path = Path(self.path)
        if not path.exists():
            return []
        connection = _connect_read_only(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, scenario, purpose, kind, model, attempt,
                       input_tokens, output_tokens, charged_tokens, estimated,
                       status, reservation_overage_tokens, hard_limit_breached,
                       cumulative_tokens, created_at, updated_at
                FROM live_micu_token_attempts
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def _connect_for_write(self) -> sqlite3.Connection:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(_SCHEMA)
        _ensure_attempt_columns(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO live_micu_token_state (id, hard_limit_tokens)
            VALUES (1, ?)
            """,
            (self.hard_limit_tokens,),
        )
        connection.execute(
            """
            UPDATE live_micu_token_state
            SET hard_limit_tokens = MIN(hard_limit_tokens, ?)
            WHERE id = 1
            """,
            (self.hard_limit_tokens,),
        )
        return connection

    def _effective_limit(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT hard_limit_tokens FROM live_micu_token_state WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("live MICU token ledger state is missing")
        return min(int(row[0]), self.hard_limit_tokens, LIVE_MICU_TOKEN_HARD_LIMIT)

    @staticmethod
    def _charged_tokens(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COALESCE(SUM(charged_tokens), 0) FROM live_micu_token_attempts"
        ).fetchone()
        return 0 if row is None else int(row[0])


def configured_live_micu_token_ledger_path() -> Path:
    configured = os.getenv(LIVE_MICU_TOKEN_LEDGER_PATH_ENV)
    if not configured:
        return DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH
    path = Path(configured)
    return path if path.is_absolute() else _REPO_ROOT / path


def migrate_legacy_live_micu_token_policy(
    path: Path | str,
) -> dict[str, Any]:
    """Explicitly migrate the canonical fixed 100M policy to the fixed 500M policy.

    Historical rows and charged usage are untouched.  The operation is
    idempotent at 500M and refuses every other stored limit.  In particular,
    normal ledger construction and read-only summaries never invoke this
    migration, so caller-selected lower limits remain fail-closed until an
    operator explicitly authorizes this exact transition.
    """

    ledger_path = Path(path)
    if not ledger_path.exists():
        raise LiveMicuTokenPolicyMigrationError(
            "live MICU token ledger does not exist for policy migration"
        )
    connection = sqlite3.connect(ledger_path, timeout=30.0, isolation_level=None)
    migrated = False
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            state = connection.execute(
                "SELECT hard_limit_tokens FROM live_micu_token_state WHERE id = 1"
            ).fetchone()
            connection.execute(
                "SELECT COUNT(*) FROM live_micu_token_attempts"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise LiveMicuTokenPolicyMigrationError(
                "live MICU token ledger does not have the canonical ledger schema"
            ) from exc
        if state is None:
            raise LiveMicuTokenPolicyMigrationError(
                "live MICU token ledger state is missing"
            )
        stored_limit = int(state[0])
        if stored_limit == LIVE_MICU_TOKEN_HARD_LIMIT:
            connection.commit()
        elif stored_limit != _LEGACY_LIVE_MICU_TOKEN_HARD_LIMIT:
            raise LiveMicuTokenPolicyMigrationError(
                "live MICU token ledger is not on the exact legacy fixed 100M policy"
            )
        else:
            cursor = connection.execute(
                """
                UPDATE live_micu_token_state
                SET hard_limit_tokens = ?
                WHERE id = 1 AND hard_limit_tokens = ?
                """,
                (
                    LIVE_MICU_TOKEN_HARD_LIMIT,
                    _LEGACY_LIVE_MICU_TOKEN_HARD_LIMIT,
                ),
            )
            if cursor.rowcount != 1:
                raise LiveMicuTokenPolicyMigrationError(
                    "live MICU token ledger policy changed during migration"
                )
            connection.commit()
            migrated = True
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    summary = summarize_live_micu_token_ledger(ledger_path)
    summary["policy_migrated"] = migrated
    return summary


def is_micu_provider_url(base_url: str | None) -> bool:
    hostname = urlparse(base_url or "").hostname
    normalized = (hostname or "").lower().rstrip(".")
    return normalized == "micuapi.ai" or normalized.endswith(".micuapi.ai")


def estimate_llm_request_tokens(request: dict[str, Any]) -> int:
    """Conservatively bound request tokens without persisting request content."""
    encoded = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return max(1, len(encoded) + 256)


def usage_token_counts(usage: dict[str, Any] | None) -> UsageTokenCounts | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = _first_non_negative_int(
        usage,
        "input_tokens",
        "prompt_tokens",
        "input_token_count",
    )
    output_tokens = _first_non_negative_int(
        usage,
        "output_tokens",
        "completion_tokens",
        "output_token_count",
    )
    total_tokens = _first_non_negative_int(usage, "total_tokens", "total_token_count")
    if input_tokens is not None and output_tokens is not None:
        return UsageTokenCounts(input_tokens=input_tokens, output_tokens=output_tokens)
    if total_tokens is not None and input_tokens is not None and total_tokens >= input_tokens:
        return UsageTokenCounts(
            input_tokens=input_tokens,
            output_tokens=total_tokens - input_tokens,
        )
    if total_tokens is not None and output_tokens is not None and total_tokens >= output_tokens:
        return UsageTokenCounts(
            input_tokens=total_tokens - output_tokens,
            output_tokens=output_tokens,
        )
    return None


def summarize_live_micu_token_ledger(
    path: Path | str | None = None,
    *,
    fallback_hard_limit: int = LIVE_MICU_TOKEN_HARD_LIMIT,
) -> dict[str, Any]:
    ledger_path = Path(path or configured_live_micu_token_ledger_path())
    fallback_limit = min(int(fallback_hard_limit), LIVE_MICU_TOKEN_HARD_LIMIT)
    if not ledger_path.exists():
        return _empty_summary(ledger_path, fallback_limit)
    connection = _connect_read_only(ledger_path)
    connection.row_factory = sqlite3.Row
    try:
        state = connection.execute(
            "SELECT hard_limit_tokens FROM live_micu_token_state WHERE id = 1"
        ).fetchone()
        hard_limit = fallback_limit if state is None else min(int(state[0]), fallback_limit)
        totals = connection.execute(
            """
            SELECT COUNT(*) AS attempt_count,
                   COALESCE(SUM(charged_tokens), 0) AS charged_tokens,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN input_tokens ELSE 0 END), 0)
                       AS actual_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN output_tokens ELSE 0 END), 0)
                       AS actual_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN input_tokens ELSE 0 END), 0)
                       AS estimated_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN output_tokens ELSE 0 END), 0)
                       AS estimated_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN 1 ELSE 0 END), 0)
                       AS estimated_attempt_count,
                   COALESCE(SUM(reservation_overage_tokens), 0)
                       AS reservation_overage_tokens,
                   COALESCE(SUM(hard_limit_breached), 0) AS hard_limit_breach_count
            FROM live_micu_token_attempts
            """
        ).fetchone()
        by_scenario = connection.execute(
            """
            SELECT scenario,
                   COUNT(*) AS attempt_count,
                   COALESCE(SUM(charged_tokens), 0) AS charged_tokens,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN input_tokens ELSE 0 END), 0)
                       AS actual_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN output_tokens ELSE 0 END), 0)
                       AS actual_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN input_tokens ELSE 0 END), 0)
                       AS estimated_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN output_tokens ELSE 0 END), 0)
                       AS estimated_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN 1 ELSE 0 END), 0)
                       AS estimated_attempt_count,
                   COALESCE(SUM(reservation_overage_tokens), 0)
                       AS reservation_overage_tokens,
                   COALESCE(SUM(hard_limit_breached), 0) AS hard_limit_breach_count
            FROM live_micu_token_attempts
            GROUP BY scenario
            ORDER BY scenario
            """
        ).fetchall()
        by_model = connection.execute(
            """
            SELECT model,
                   COUNT(*) AS attempt_count,
                   COALESCE(SUM(charged_tokens), 0) AS charged_tokens,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN input_tokens ELSE 0 END), 0)
                       AS actual_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 0 THEN output_tokens ELSE 0 END), 0)
                       AS actual_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN input_tokens ELSE 0 END), 0)
                       AS estimated_input_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN output_tokens ELSE 0 END), 0)
                       AS estimated_output_tokens,
                   COALESCE(SUM(CASE WHEN estimated = 1 THEN 1 ELSE 0 END), 0)
                       AS estimated_attempt_count,
                   COALESCE(SUM(reservation_overage_tokens), 0)
                       AS reservation_overage_tokens,
                   COALESCE(SUM(hard_limit_breached), 0) AS hard_limit_breach_count
            FROM live_micu_token_attempts
            GROUP BY model
            ORDER BY model
            """
        ).fetchall()
        charged = int(totals["charged_tokens"])
        return {
            "path": str(ledger_path),
            "hard_limit_tokens": hard_limit,
            "charged_tokens": charged,
            "remaining_tokens": max(0, hard_limit - charged),
            "hard_limit_overage_tokens": max(0, charged - hard_limit),
            "attempt_count": int(totals["attempt_count"]),
            "estimated_attempt_count": int(totals["estimated_attempt_count"]),
            "input_tokens": int(totals["input_tokens"]),
            "output_tokens": int(totals["output_tokens"]),
            "actual_input_tokens": int(totals["actual_input_tokens"]),
            "actual_output_tokens": int(totals["actual_output_tokens"]),
            "estimated_input_tokens": int(totals["estimated_input_tokens"]),
            "estimated_output_tokens": int(totals["estimated_output_tokens"]),
            "reservation_overage_tokens": int(totals["reservation_overage_tokens"]),
            "hard_limit_breach_count": int(totals["hard_limit_breach_count"]),
            "by_scenario": [dict(row) for row in by_scenario],
            "by_model": [dict(row) for row in by_model],
        }
    finally:
        connection.close()


def _empty_summary(path: Path, hard_limit: int) -> dict[str, Any]:
    return {
        "path": str(path),
        "hard_limit_tokens": hard_limit,
        "charged_tokens": 0,
        "remaining_tokens": hard_limit,
        "hard_limit_overage_tokens": 0,
        "attempt_count": 0,
        "estimated_attempt_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "actual_input_tokens": 0,
        "actual_output_tokens": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
        "by_scenario": [],
        "by_model": [],
    }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30.0)


def _first_non_negative_int(mapping: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and int(value) == value and int(value) >= 0:
            return int(value)
    return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_attempt_columns(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(live_micu_token_attempts)")
    }
    if "reservation_overage_tokens" not in columns:
        connection.execute(
            """
            ALTER TABLE live_micu_token_attempts
            ADD COLUMN reservation_overage_tokens INTEGER NOT NULL DEFAULT 0
            """
        )
    if "hard_limit_breached" not in columns:
        connection.execute(
            """
            ALTER TABLE live_micu_token_attempts
            ADD COLUMN hard_limit_breached INTEGER NOT NULL DEFAULT 0
            """
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_micu_token_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    hard_limit_tokens INTEGER NOT NULL CHECK (hard_limit_tokens > 0)
);

CREATE TABLE IF NOT EXISTS live_micu_token_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario TEXT NOT NULL,
    purpose TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    charged_tokens INTEGER NOT NULL CHECK (charged_tokens >= 0),
    estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
    status TEXT NOT NULL,
    reservation_overage_tokens INTEGER NOT NULL DEFAULT 0
        CHECK (reservation_overage_tokens >= 0),
    hard_limit_breached INTEGER NOT NULL DEFAULT 0
        CHECK (hard_limit_breached IN (0, 1)),
    cumulative_tokens INTEGER NOT NULL CHECK (cumulative_tokens >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_micu_token_attempts_scenario
ON live_micu_token_attempts (scenario, id);
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect the live MICU token ledger.")
    parser.add_argument(
        "--path",
        type=Path,
        default=configured_live_micu_token_ledger_path(),
        help=f"ledger path (default: ${LIVE_MICU_TOKEN_LEDGER_PATH_ENV} or built-in path)",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=0,
        help="include up to this many recent attempt records in the read-only output",
    )
    parser.add_argument(
        "--migrate-legacy-fixed-policy",
        action="store_true",
        help=(
            "explicitly migrate an existing exact legacy fixed 100M policy to "
            "the compiled-in 500M policy without changing usage rows"
        ),
    )
    args = parser.parse_args(argv)
    summary = (
        migrate_legacy_live_micu_token_policy(args.path)
        if args.migrate_legacy_fixed_policy
        else summarize_live_micu_token_ledger(args.path)
    )
    if args.attempts > 0:
        summary["attempts"] = LiveMicuTokenLedger(args.path).list_attempts(
            limit=args.attempts
        )
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH",
    "LIVE_MICU_TOKEN_HARD_LIMIT",
    "LiveMicuTokenBudgetExceededError",
    "LiveMicuTokenLedger",
    "LiveMicuTokenPolicyMigrationError",
    "LiveMicuTokenReservation",
    "LiveMicuTokenReservationConfigurationError",
    "UsageTokenCounts",
    "configured_live_micu_token_ledger_path",
    "estimate_llm_request_tokens",
    "is_micu_provider_url",
    "migrate_legacy_live_micu_token_policy",
    "summarize_live_micu_token_ledger",
    "usage_token_counts",
]
