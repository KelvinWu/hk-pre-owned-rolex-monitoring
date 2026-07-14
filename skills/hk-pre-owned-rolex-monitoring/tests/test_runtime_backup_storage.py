from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from inventory_sentinel.adapters import AdapterRegistry
from inventory_sentinel.locking import RunLock
from inventory_sentinel.errors import RunLocked
from inventory_sentinel.service import InventoryService
from inventory_sentinel.storage import SCHEMA_VERSION, Storage

from conftest import NoopImageCache, SequenceAdapter, fetch, make_items


def make_service(tmp_path: Path, adapter: SequenceAdapter) -> InventoryService:
    return InventoryService(
        tmp_path / "state",
        adapters=AdapterRegistry({adapter.name: adapter}),
        sleeper=lambda _: None,
        image_cache_factory=NoopImageCache,
    )


def test_runtime_probe_separates_writable_directory_from_verified_persistence(tmp_path: Path) -> None:
    service = make_service(tmp_path, SequenceAdapter())
    try:
        probe, code = service.runtime_probe()
        capabilities = probe["result"]["capabilities"]
        assert code == 0
        assert capabilities["state_directory_writable"] == "supported"
        assert capabilities["persistent_storage"] == "host_verification_required"
    finally:
        service.close()


def test_runtime_plan_requires_verified_external_id(
    tmp_path: Path, manifest_file: Path
) -> None:
    adapter = SequenceAdapter()
    service = make_service(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        plan, _ = service.reconcile_plan("test-monitor")
        runtime_plan = plan["result"]["runtime_plan"]
        assert runtime_plan["operations"][0]["op"] == "schedule.upsert"
        assert runtime_plan["notification"]["delivery"] == "outbox"
        assert runtime_plan["requirements"]["persistent_state"] is True
        logical_id = runtime_plan["operations"][0]["logical_id"]

        result_file = tmp_path / "runtime-result.json"
        result_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "monitor_id": "test-monitor",
                    "results": [{"logical_id": logical_id, "ok": True, "external_id": "task-1", "verified": False}],
                }
            ),
            encoding="utf-8",
        )
        invalid, code = service.apply_runtime_result(result_file)
        assert code == 2 and invalid["status"] == "INVALID"
        doctor, _ = service.doctor("test-monitor")
        assert doctor["result"]["missing_verified_logical_ids"] == [logical_id]

        result_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "monitor_id": "test-monitor",
                    "results": [{"logical_id": logical_id, "ok": True, "external_id": "task-1", "verified": True}],
                }
            ),
            encoding="utf-8",
        )
        applied, code = service.apply_runtime_result(result_file)
        assert code == 0 and applied["ok"]
        doctor, _ = service.doctor("test-monitor")
        assert doctor["result"]["missing_verified_logical_ids"] == []
    finally:
        service.close()


def test_backup_restore_returns_to_verified_state(tmp_path: Path, manifest_file: Path) -> None:
    baseline = make_items(3)
    changed = make_items(3, price_delta=100)
    adapter = SequenceAdapter([fetch(baseline), fetch(baseline), fetch(changed), fetch(changed), fetch(changed)])
    service = make_service(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        expected_hash = service.storage.latest_snapshot("test-monitor")["snapshot_hash"]
        cached_image = service.state_dir / "images/test-monitor/LOT-001.jpg"
        cached_image.parent.mkdir(parents=True, exist_ok=True)
        cached_image.write_bytes(b"\xff\xd8\xfforiginal")
        backup, _ = service.backup("test-monitor")
        archive = Path(backup["result"]["backup_path"])
        cached_image.write_bytes(b"\xff\xd8\xffchanged")
        service.run_monitor("test-monitor", "changed")
        assert service.storage.latest_snapshot("test-monitor")["snapshot_hash"] != expected_hash
        restored, code = service.restore(archive)
        assert code == 0 and restored["result"]["verified"]
        assert service.storage.latest_snapshot("test-monitor")["snapshot_hash"] == expected_hash
        assert cached_image.read_bytes() == b"\xff\xd8\xfforiginal"
        assert Path(restored["result"]["safety_backup"]).is_file()
    finally:
        service.close()


def test_lock_prevents_concurrent_monitor_runs(tmp_path: Path) -> None:
    lock_dir = tmp_path / "locks"
    with RunLock(lock_dir, "same-monitor"):
        with pytest.raises(RunLocked):
            with RunLock(lock_dir, "same-monitor"):
                pass
    with RunLock(lock_dir, "same-monitor"):
        pass


def test_schema_migration_and_future_version_guard(tmp_path: Path) -> None:
    state = tmp_path / "state"
    storage = Storage(state)
    assert storage.integrity()["schema_version"] == SCHEMA_VERSION
    storage.close()
    connection = sqlite3.connect(state / "state.db")
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(RuntimeError, match="高于当前支持版本"):
        Storage(state)


def test_schema_v1_migrates_delivery_receipts_and_local_date(tmp_path: Path) -> None:
    state = tmp_path / "legacy-state"
    state.mkdir()
    connection = sqlite3.connect(state / "state.db")
    connection.executescript(
        """
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE runs(
            run_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, trigger_name TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL, state_modified INTEGER NOT NULL, snapshot_id TEXT,
            result_json TEXT NOT NULL
        );
        CREATE TABLE outbox(
            event_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, run_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, acknowledged_at TEXT
        );
        PRAGMA user_version=1;
        """
    )
    connection.close()

    storage = Storage(state)
    try:
        assert storage.integrity()["schema_version"] == 2
        run_columns = {
            row[1] for row in storage.conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        outbox_columns = {
            row[1] for row in storage.conn.execute("PRAGMA table_info(outbox)").fetchall()
        }
        assert "local_date" in run_columns
        assert {
            "provider",
            "external_message_id",
            "delivered_at",
            "delivery_verified",
            "delivery_error_json",
        }.issubset(outbox_columns)
    finally:
        storage.close()


def test_json_schemas_are_valid_json() -> None:
    schema_dir = Path(__file__).resolve().parents[1] / "assets/schemas"
    files = sorted(schema_dir.glob("*.schema.json"))
    assert len(files) == 5
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"].endswith("2020-12/schema")
