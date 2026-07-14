from __future__ import annotations

from datetime import datetime
from pathlib import Path

from inventory_sentinel.adapters import AdapterRegistry
from inventory_sentinel.models import MarketPacket
from inventory_sentinel.service import InventoryService

from conftest import NoopImageCache, SequenceAdapter, fetch, make_items


def _service(tmp_path: Path, adapter: SequenceAdapter) -> InventoryService:
    return InventoryService(
        tmp_path / "state",
        adapters=AdapterRegistry({adapter.name: adapter}),
        sleeper=lambda _: None,
        image_cache_factory=NoopImageCache,
    )


def _packet() -> MarketPacket:
    return MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "history-market",
            "as_of": "2026-07-14T12:00:00+08:00",
            "observations": [
                {
                    "observation_id": "hk-a",
                    "source": "watchfinder-hk",
                    "independence_group": "watchfinder",
                    "rolex_reference": "REF-003",
                    "region": "HK",
                    "basis": "asking_price",
                    "price_hkd": 12000,
                    "observed_at": "2026-07-13T12:00:00+08:00",
                    "year": 2021,
                    "condition": "excellent",
                    "evidence_status": "verified",
                    "acquisition_method": "manual_snapshot",
                    "evidence_note": "授权快照 A",
                    "evidence_verified_at": "2026-07-14T10:00:00+08:00",
                    "evidence_sha256": "sha256:" + "a" * 64,
                },
                {
                    "observation_id": "hk-b",
                    "source": "28watches",
                    "independence_group": "28watches",
                    "rolex_reference": "REF-003",
                    "region": "HK",
                    "basis": "asking_price",
                    "price_hkd": 14000,
                    "observed_at": "2026-07-13T12:00:00+08:00",
                    "year": 2022,
                    "condition": "very_good",
                    "evidence_status": "verified",
                    "acquisition_method": "manual_snapshot",
                    "evidence_note": "授权快照 B",
                    "evidence_verified_at": "2026-07-14T10:00:00+08:00",
                    "evidence_sha256": "sha256:" + "b" * 64,
                },
            ],
        }
    )


def test_history_and_report_can_replay_a_removed_watch(
    tmp_path: Path, manifest_file: Path
) -> None:
    baseline = [item.model_copy(update={"year": 2021}) for item in make_items(3)]
    changed = baseline[:2]
    adapter = SequenceAdapter(
        [fetch(baseline), fetch(baseline), fetch(changed), fetch(changed)]
    )
    service = _service(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        result, code = service.run_monitor("test-monitor", "history")
        assert code == 0 and result["status"] == "CHANGED"

        monitors, code = service.monitor_list()
        assert code == 0
        assert monitors["result"]["monitors"][0]["monitor_id"] == "test-monitor"

        history, code = service.monitor_history("test-monitor", limit=10)
        assert code == 0
        assert any(row["run_id"] == result["run_id"] for row in history["result"]["runs"])

        shown, code = service.show_run(result["run_id"])
        assert code == 0
        assert shown["result"]["human_summary_zh"]["changes"][0].startswith("已下架：")

        compared, code = service.market_compare(None, _packet(), run_id=result["run_id"])
        assert code == 0
        assert compared["result"]["selection"]["mode"] == "run_changes"
        assert [row["stable_id"] for row in compared["result"]["comparisons"]] == ["LOT-003"]
        assert compared["result"]["comparisons"][0]["benchmark_status"] == "VERIFIED"

        report, code = service.report_build(result["run_id"], market_packet=_packet())
        assert code == 0
        assert "已下架" in report["result"]["user_report_zh"]["text"]
        assert "行业行情" in report["result"]["user_report_zh"]["text"]
    finally:
        service.close()


def test_history_date_is_monitor_local_date(tmp_path: Path, manifest_file: Path) -> None:
    items = make_items(2)
    adapter = SequenceAdapter([fetch(items), fetch(items), fetch(items)])
    service = _service(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        result, _ = service.run_monitor("test-monitor", "dated")
        local_date = datetime.now().astimezone().date().isoformat()
        history, code = service.monitor_history("test-monitor", date=local_date, limit=10)
        assert code == 0
        assert any(row["run_id"] == result["run_id"] for row in history["result"]["runs"])
    finally:
        service.close()
