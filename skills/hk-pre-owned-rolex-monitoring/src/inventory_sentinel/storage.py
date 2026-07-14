from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .errors import ConfigError, MonitorNotFound
from .models import InventoryItem, MonitorManifest, RuntimeActionResult
from .util import json_dumps, utc_now


SCHEMA_VERSION = 2


class Storage:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.db_path = state_dir / "state.db"
        for name in ("images", "raw", "logs", "backups", "locks"):
            (state_dir / name).mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        try:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self._migrate()
        except Exception:
            self.conn.close()
            raise

    def _migrate(self) -> None:
        current = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"状态 Schema {current} 高于当前支持版本 {SCHEMA_VERSION}")
        if current < 1:
            with self.conn:
                self.conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS monitors (
                        monitor_id TEXT PRIMARY KEY,
                        manifest_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
                        created_at TEXT NOT NULL,
                        verified INTEGER NOT NULL,
                        item_count INTEGER NOT NULL,
                        snapshot_hash TEXT NOT NULL,
                        items_json TEXT NOT NULL,
                        diagnostics_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS snapshots_monitor_created
                        ON snapshots(monitor_id, created_at DESC);
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
                        trigger_name TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL,
                        state_modified INTEGER NOT NULL,
                        snapshot_id TEXT REFERENCES snapshots(snapshot_id),
                        result_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS runs_monitor_finished
                        ON runs(monitor_id, finished_at DESC);
                    CREATE TABLE IF NOT EXISTS changes (
                        change_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        stable_id TEXT NOT NULL,
                        change_type TEXT NOT NULL,
                        before_json TEXT,
                        after_json TEXT
                    );
                    CREATE TABLE IF NOT EXISTS outbox (
                        event_id TEXT PRIMARY KEY,
                        monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
                        run_id TEXT NOT NULL REFERENCES runs(run_id),
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        acknowledged_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS outbox_monitor_status
                        ON outbox(monitor_id, status, created_at);
                    CREATE TABLE IF NOT EXISTS runtime_bindings (
                        logical_id TEXT PRIMARY KEY,
                        monitor_id TEXT NOT NULL REFERENCES monitors(monitor_id),
                        external_id TEXT,
                        verified INTEGER NOT NULL,
                        result_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, utc_now()),
                )
                self.conn.execute("PRAGMA user_version=1")
            current = 1
        if current < 2:
            with self.conn:
                self.conn.executescript(
                    """
                    ALTER TABLE runs ADD COLUMN local_date TEXT;
                    ALTER TABLE outbox ADD COLUMN provider TEXT;
                    ALTER TABLE outbox ADD COLUMN external_message_id TEXT;
                    ALTER TABLE outbox ADD COLUMN delivered_at TEXT;
                    ALTER TABLE outbox ADD COLUMN delivery_verified INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE outbox ADD COLUMN delivery_error_json TEXT;
                    UPDATE runs
                       SET local_date=substr(finished_at, 1, 10)
                     WHERE local_date IS NULL;
                    """
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, utc_now()),
                )
                self.conn.execute("PRAGMA user_version=2")

    def register_monitor(self, manifest: MonitorManifest) -> bool:
        now = utc_now()
        existing = self.conn.execute(
            "SELECT manifest_json FROM monitors WHERE monitor_id=?", (manifest.monitor_id,)
        ).fetchone()
        payload = manifest.model_dump_json()
        if existing and existing["manifest_json"] == payload:
            return False
        with self.conn:
            if existing:
                self.conn.execute(
                    "UPDATE monitors SET manifest_json=?, updated_at=? WHERE monitor_id=?",
                    (payload, now, manifest.monitor_id),
                )
            else:
                self.conn.execute(
                    "INSERT INTO monitors(monitor_id, manifest_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (manifest.monitor_id, payload, now, now),
                )
        return True

    def get_manifest(self, monitor_id: str) -> MonitorManifest:
        row = self.conn.execute(
            "SELECT manifest_json FROM monitors WHERE monitor_id=?", (monitor_id,)
        ).fetchone()
        if row is None:
            raise MonitorNotFound(f"Monitor 不存在: {monitor_id}")
        return MonitorManifest.model_validate_json(row["manifest_json"])

    def list_monitors(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT monitor_id, manifest_json, created_at, updated_at FROM monitors ORDER BY monitor_id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            manifest = MonitorManifest.model_validate_json(row["manifest_json"])
            status = self.monitor_status(row["monitor_id"])
            result.append(
                {
                    "monitor_id": row["monitor_id"],
                    "display_name": manifest.display_name,
                    "enabled": manifest.enabled,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "latest_verified_snapshot": status["latest_verified_snapshot"],
                    "last_run": status["last_run"],
                    "pending_outbox": status["pending_outbox"],
                }
            )
        return result

    def latest_snapshot(self, monitor_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT snapshot_id, created_at, item_count, snapshot_hash, items_json, diagnostics_json
            FROM snapshots
            WHERE monitor_id=? AND verified=1
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (monitor_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "created_at": row["created_at"],
            "item_count": row["item_count"],
            "snapshot_hash": row["snapshot_hash"],
            "items": [InventoryItem.model_validate(item) for item in json.loads(row["items_json"])],
            "diagnostics": json.loads(row["diagnostics_json"]),
        }

    def _snapshot_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT snapshot_id, monitor_id, created_at, item_count, snapshot_hash,
                   items_json, diagnostics_json
              FROM snapshots WHERE snapshot_id=? AND verified=1
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "monitor_id": row["monitor_id"],
            "created_at": row["created_at"],
            "item_count": row["item_count"],
            "snapshot_hash": row["snapshot_hash"],
            "items": [InventoryItem.model_validate(item) for item in json.loads(row["items_json"])],
            "diagnostics": json.loads(row["diagnostics_json"]),
        }

    def list_runs(
        self,
        monitor_id: str,
        *,
        date: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.get_manifest(monitor_id)
        parameters: list[Any] = [monitor_id]
        where = "monitor_id=?"
        if date:
            where += " AND local_date=?"
            parameters.append(date)
        parameters.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT run_id, monitor_id, trigger_name, status, local_date, started_at,
                   finished_at, state_modified, snapshot_id
              FROM runs WHERE {where}
             ORDER BY finished_at DESC, rowid DESC LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT run_id, monitor_id, trigger_name, idempotency_key, status, local_date,
                   started_at, finished_at, state_modified, snapshot_id, result_json
              FROM runs WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise ConfigError(f"运行记录不存在: {run_id}")
        result = json.loads(row["result_json"])
        return {
            **{key: row[key] for key in row.keys() if key != "result_json"},
            "result": result,
        }

    @staticmethod
    def _item_from_change(value: dict[str, Any]) -> InventoryItem:
        allowed = set(InventoryItem.model_fields)
        return InventoryItem.model_validate({key: item for key, item in value.items() if key in allowed})

    def items_for_run(self, run_id: str, *, changes_only: bool) -> tuple[dict[str, Any], list[InventoryItem]]:
        run = self.get_run(run_id)
        diff = run["result"].get("diff") or {"added": [], "removed": [], "modified": []}
        if changes_only and any(diff.values()):
            items: list[InventoryItem] = []
            items.extend(self._item_from_change(value) for value in diff.get("added", []))
            items.extend(self._item_from_change(value) for value in diff.get("removed", []))
            items.extend(
                self._item_from_change(value["after"])
                for value in diff.get("modified", [])
            )
            unique = {item.stable_id: item for item in items}
            return run, [unique[key] for key in sorted(unique)]
        snapshot_id = run.get("snapshot_id")
        snapshot = self._snapshot_by_id(snapshot_id) if snapshot_id else None
        return run, [] if snapshot is None else snapshot["items"]

    def get_event(self, event_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM outbox WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise ConfigError(f"Outbox 事件不存在: {event_id}")
        return {
            **{
                key: row[key]
                for key in row.keys()
                if key not in {"payload_json", "delivery_error_json"}
            },
            "payload": json.loads(row["payload_json"]),
            "delivery_error": (
                json.loads(row["delivery_error_json"])
                if row["delivery_error_json"]
                else None
            ),
        }

    def items_for_event(self, event_id: str) -> tuple[dict[str, Any], list[InventoryItem]]:
        event = self.get_event(event_id)
        change = event["payload"].get("change")
        if not change:
            return event, []
        if event["event_type"] == "inventory.modified":
            value = change["after"]
        else:
            value = change
        return event, [self._item_from_change(value)]

    def existing_run(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT run_id, status, result_json FROM runs WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if row is None:
            return None
        return {"run_id": row["run_id"], "status": row["status"], "result": json.loads(row["result_json"])}

    def save_baseline(
        self,
        *,
        monitor_id: str,
        run_id: str,
        items: list[InventoryItem],
        snapshot_hash: str,
        diagnostics: dict[str, Any],
        local_date: str,
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        now = utc_now()
        result = {"baseline": {"verified": True, "item_count": len(items), "snapshot_hash": snapshot_hash}}
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO snapshots(snapshot_id, monitor_id, created_at, verified, item_count,
                                      snapshot_hash, items_json, diagnostics_json)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    monitor_id,
                    now,
                    len(items),
                    snapshot_hash,
                    json_dumps([item.model_dump(mode="json") for item in items]),
                    json_dumps(diagnostics),
                ),
            )
            self.conn.execute(
                """
                INSERT INTO runs(run_id, monitor_id, trigger_name, idempotency_key, status,
                                 started_at, finished_at, state_modified, snapshot_id, result_json,
                                 local_date)
                VALUES (?, ?, 'baseline', ?, 'BASELINE_CREATED', ?, ?, 1, ?, ?, ?)
                """,
                (
                    run_id,
                    monitor_id,
                    f"baseline:{run_id}",
                    now,
                    now,
                    snapshot_id,
                    json_dumps(result),
                    local_date,
                ),
            )
        return snapshot_id

    def commit_success(
        self,
        *,
        monitor_id: str,
        run_id: str,
        trigger: str,
        idempotency_key: str,
        local_date: str,
        status: str,
        items: list[InventoryItem],
        snapshot_hash: str,
        diagnostics: dict[str, Any],
        diff: dict[str, list[dict[str, Any]]],
        events: list[dict[str, Any]],
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        now = utc_now()
        result = {"diff": diff, "item_count": len(items), "snapshot_hash": snapshot_hash}
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO snapshots(snapshot_id, monitor_id, created_at, verified, item_count,
                                      snapshot_hash, items_json, diagnostics_json)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    monitor_id,
                    now,
                    len(items),
                    snapshot_hash,
                    json_dumps([item.model_dump(mode="json") for item in items]),
                    json_dumps(diagnostics),
                ),
            )
            self.conn.execute(
                """
                INSERT INTO runs(run_id, monitor_id, trigger_name, idempotency_key, status,
                                 started_at, finished_at, state_modified, snapshot_id, result_json,
                                 local_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    run_id,
                    monitor_id,
                    trigger,
                    idempotency_key,
                    status,
                    now,
                    now,
                    snapshot_id,
                    json_dumps(result),
                    local_date,
                ),
            )
            self._insert_changes(run_id, diff)
            self._insert_events(monitor_id, run_id, events)
        return snapshot_id

    def record_invalid(
        self,
        *,
        monitor_id: str,
        run_id: str,
        trigger: str,
        idempotency_key: str,
        local_date: str,
        error: dict[str, Any],
    ) -> None:
        now = utc_now()
        result = {"last_verified_snapshot_preserved": True, "error": error}
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "monitor.invalid",
            "dedupe_key": f"{idempotency_key}:invalid",
            "payload": result,
        }
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO runs(run_id, monitor_id, trigger_name, idempotency_key, status,
                                 started_at, finished_at, state_modified, snapshot_id, result_json,
                                 local_date)
                VALUES (?, ?, ?, ?, 'INVALID', ?, ?, 0, NULL, ?, ?)
                """,
                (
                    run_id,
                    monitor_id,
                    trigger,
                    idempotency_key,
                    now,
                    now,
                    json_dumps(result),
                    local_date,
                ),
            )
            self._insert_events(monitor_id, run_id, [event])

    def _insert_changes(self, run_id: str, diff: dict[str, list[dict[str, Any]]]) -> None:
        for entry in diff["added"]:
            self.conn.execute(
                "INSERT INTO changes VALUES (?, ?, ?, 'added', NULL, ?)",
                (str(uuid.uuid4()), run_id, entry["stable_id"], json_dumps(entry)),
            )
        for entry in diff["removed"]:
            self.conn.execute(
                "INSERT INTO changes VALUES (?, ?, ?, 'removed', ?, NULL)",
                (str(uuid.uuid4()), run_id, entry["stable_id"], json_dumps(entry)),
            )
        for entry in diff["modified"]:
            self.conn.execute(
                "INSERT INTO changes VALUES (?, ?, ?, 'modified', ?, ?)",
                (
                    str(uuid.uuid4()),
                    run_id,
                    entry["stable_id"],
                    json_dumps(entry["before"]),
                    json_dumps(entry["after"]),
                ),
            )

    def _insert_events(self, monitor_id: str, run_id: str, events: list[dict[str, Any]]) -> None:
        for event in events:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO outbox(event_id, monitor_id, run_id, event_type, payload_json,
                                             status, dedupe_key, created_at, acknowledged_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)
                """,
                (
                    event["event_id"],
                    monitor_id,
                    run_id,
                    event["event_type"],
                    json_dumps(event["payload"]),
                    event["dedupe_key"],
                    utc_now(),
                ),
            )

    def monitor_status(self, monitor_id: str) -> dict[str, Any]:
        manifest = self.get_manifest(monitor_id)
        snapshot = self.latest_snapshot(monitor_id)
        last_run = self.conn.execute(
            "SELECT run_id, status, finished_at, state_modified FROM runs WHERE monitor_id=? ORDER BY finished_at DESC, rowid DESC LIMIT 1",
            (monitor_id,),
        ).fetchone()
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE monitor_id=? AND status!='verified'", (monitor_id,)
        ).fetchone()[0]
        return {
            "manifest": manifest.model_dump(mode="json"),
            "latest_verified_snapshot": None
            if snapshot is None
            else {
                "snapshot_id": snapshot["snapshot_id"],
                "created_at": snapshot["created_at"],
                "item_count": snapshot["item_count"],
                "snapshot_hash": snapshot["snapshot_hash"],
            },
            "last_run": dict(last_run) if last_run else None,
            "pending_outbox": pending,
        }

    def list_outbox(self, monitor_id: str) -> list[dict[str, Any]]:
        self.get_manifest(monitor_id)
        rows = self.conn.execute(
            """
            SELECT event_id, run_id, event_type, payload_json, status, dedupe_key, created_at,
                   acknowledged_at, provider, external_message_id, delivered_at,
                   delivery_verified, delivery_error_json
            FROM outbox WHERE monitor_id=? ORDER BY created_at, rowid
            """,
            (monitor_id,),
        ).fetchall()
        return [
            {
                **{
                    key: row[key]
                    for key in row.keys()
                    if key not in {"payload_json", "delivery_error_json"}
                },
                "payload": json.loads(row["payload_json"]),
                "delivery_error": (
                    json.loads(row["delivery_error_json"])
                    if row["delivery_error_json"]
                    else None
                ),
            }
            for row in rows
        ]

    def ack_outbox(
        self,
        event_id: str,
        *,
        provider: str | None,
        external_message_id: str | None,
        delivered_at: str | None,
        verified: bool,
        delivery_error: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], bool]:
        current = self.get_event(event_id)
        if verified and not external_message_id:
            raise ConfigError("verified=true 时必须提供 external_message_id")
        if (
            current["status"] == "verified"
            and current["external_message_id"] == external_message_id
            and verified
        ):
            return current, False
        status = (
            "failed"
            if delivery_error
            else "verified"
            if verified
            else "sent_unverified"
        )
        acknowledged_at = utc_now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE outbox
                   SET status=?, acknowledged_at=?, provider=?, external_message_id=?,
                       delivered_at=?, delivery_verified=?, delivery_error_json=?
                 WHERE event_id=?
                """,
                (
                    status,
                    acknowledged_at,
                    provider,
                    external_message_id,
                    delivered_at,
                    int(verified and not delivery_error),
                    json_dumps(delivery_error) if delivery_error else None,
                    event_id,
                ),
            )
        return self.get_event(event_id), True

    def apply_runtime_results(self, monitor_id: str, results: list[RuntimeActionResult]) -> None:
        now = utc_now()
        with self.conn:
            for item in results:
                self.conn.execute(
                    """
                    INSERT INTO runtime_bindings(logical_id, monitor_id, external_id, verified, result_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(logical_id) DO UPDATE SET
                        monitor_id=excluded.monitor_id,
                        external_id=excluded.external_id,
                        verified=excluded.verified,
                        result_json=excluded.result_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.logical_id,
                        monitor_id,
                        item.external_id,
                        int(item.ok and item.verified and bool(item.external_id)),
                        item.model_dump_json(),
                        now,
                    ),
                )

    def runtime_bindings(self, monitor_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT logical_id, external_id, verified, updated_at FROM runtime_bindings WHERE monitor_id=? ORDER BY logical_id",
            (monitor_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def integrity(self) -> dict[str, Any]:
        check = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": check == "ok", "message": check, "schema_version": self.conn.execute("PRAGMA user_version").fetchone()[0]}

    def close(self) -> None:
        self.conn.close()
