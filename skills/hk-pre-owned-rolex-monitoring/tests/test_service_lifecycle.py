from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx

from inventory_sentinel.adapters import AdapterRegistry
from inventory_sentinel.image_cache import ImageCache
from inventory_sentinel.models import FetchResult
from inventory_sentinel.service import InventoryService

from conftest import NoopImageCache, SequenceAdapter, fetch, make_items


def service_for(tmp_path: Path, adapter: SequenceAdapter) -> InventoryService:
    return InventoryService(
        tmp_path / "state",
        adapters=AdapterRegistry({adapter.name: adapter}),
        sleeper=lambda _: None,
        image_cache_factory=NoopImageCache,
    )


def test_full_lifecycle_and_invalid_preserves_verified_snapshot(
    tmp_path: Path, manifest_file: Path
) -> None:
    baseline_items = make_items(3)
    changed_items = make_items(3)
    changed_items[0] = changed_items[0].model_copy(update={"price": Decimal("15000")})
    changed_items.pop()
    changed_items.append(make_items(4)[-1])
    adapter = SequenceAdapter(
        [
            fetch(baseline_items),
            fetch(list(reversed(baseline_items))),
            fetch(baseline_items),
            fetch(changed_items),
            fetch(changed_items),
            fetch(changed_items),
            FetchResult(items=[]),
        ]
    )
    service = service_for(tmp_path, adapter)
    try:
        created, code = service.create_monitor(manifest_file)
        assert code == 0 and created["state_modified"]
        unchanged_manifest, code = service.create_monitor(manifest_file)
        assert code == 0 and unchanged_manifest["state_modified"] is False

        baseline, code = service.baseline("test-monitor")
        assert code == 0
        assert baseline["status"] == "BASELINE_CREATED"
        assert baseline["result"]["baseline"]["samples"] == 2
        assert service.storage.list_outbox("test-monitor") == []

        no_change, code = service.run_monitor("test-monitor", "no-change")
        assert code == 0 and no_change["status"] == "NO_CHANGE"
        assert no_change["result"]["confirmation_samples"] == 1
        event = service.storage.list_outbox("test-monitor")[0]
        assert event["event_type"] == "inventory.no_change"
        acknowledged, code = service.outbox_ack(
            event["event_id"],
            provider="test",
            external_message_id="message-no-change",
            delivered_at="2026-07-14T12:00:00+08:00",
            verified=True,
        )
        assert code == 0 and acknowledged["result"]["verified"] is True
        duplicate, code = service.outbox_ack(
            event["event_id"],
            provider="test",
            external_message_id="message-no-change",
            delivered_at="2026-07-14T12:00:00+08:00",
            verified=True,
        )
        assert code == 0 and duplicate["status"] == "SKIPPED_DUPLICATE"

        changed, code = service.run_monitor("test-monitor", "changed")
        assert code == 0 and changed["status"] == "CHANGED"
        assert changed["result"]["confirmation_samples"] == 3
        assert len(changed["result"]["diff"]["added"]) == 1
        assert len(changed["result"]["diff"]["removed"]) == 1
        assert len(changed["result"]["diff"]["modified"]) == 1
        human_summary = changed["result"]["human_summary_zh"]
        assert human_summary["headline"] == "库存发生 3 项变化：上新 1、下架 1、资料变化 1。"
        price_line = next(line for line in human_summary["changes"] if line.startswith("价格上调："))
        assert "型号 REF-001" in price_line
        assert "东方表行货号 LOT-001" in price_line
        assert "HK$10,001 → HK$15,000" in price_line

        modified_event = next(
            event
            for event in service.storage.list_outbox("test-monitor")
            if event["event_type"] == "inventory.modified"
        )
        assert modified_event["payload"]["change"]["product_identity"]["rolex_reference"] == "REF-001"
        assert "东方表行货号 LOT-001" in modified_event["payload"]["human_summary_zh"]

        verified_hash = service.storage.latest_snapshot("test-monitor")["snapshot_hash"]
        invalid, code = service.run_monitor("test-monitor", "invalid")
        assert code == 2 and invalid["status"] == "INVALID"
        assert invalid["result"]["last_verified_snapshot_preserved"] is True
        assert service.storage.latest_snapshot("test-monitor")["snapshot_hash"] == verified_hash
        assert service.storage.monitor_status("test-monitor")["last_run"]["state_modified"] == 0
    finally:
        service.close()


def test_same_monitor_date_and_trigger_is_idempotent(tmp_path: Path, manifest_file: Path) -> None:
    items = make_items(3)
    adapter = SequenceAdapter([fetch(items), fetch(items), fetch(items)])
    service = service_for(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        first, _ = service.run_monitor("test-monitor", "manual")
        events_before_retry = len(service.storage.list_outbox("test-monitor"))
        second, code = service.run_monitor("test-monitor", "manual")
        assert first["status"] == "NO_CHANGE"
        assert code == 0 and second["status"] == "SKIPPED_DUPLICATE"
        assert second["run_id"] == first["run_id"]
        assert len(service.storage.list_outbox("test-monitor")) == events_before_retry
        assert adapter.calls == 3
    finally:
        service.close()


def test_cache_paths_are_reported_and_removed_item_uses_historical_image(
    tmp_path: Path, manifest
) -> None:
    configured = manifest.model_copy(
        update={
            "state": manifest.state.model_copy(update={"image_cache": True}),
            "notification": manifest.notification.model_copy(update={"include_images": False}),
        }
    )
    config = tmp_path / "image-monitor.json"
    config.write_text(configured.model_dump_json(indent=2), encoding="utf-8")
    baseline_items = make_items(3)
    changed_items = baseline_items[:2]
    adapter = SequenceAdapter(
        [fetch(baseline_items), fetch(baseline_items), fetch(changed_items), fetch(changed_items)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\xff\xd8\xffimage",
            headers={"content-type": "image/jpeg"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = InventoryService(
        tmp_path / "state",
        adapters=AdapterRegistry({adapter.name: adapter}),
        sleeper=lambda _: None,
        image_cache_factory=lambda root: ImageCache(root, client=client),
    )
    try:
        service.create_monitor(config)
        baseline, code = service.baseline("test-monitor")
        assert code == 0
        assert baseline["result"]["image_cache"]["available"] == 3

        changed, code = service.run_monitor("test-monitor", "image-history")
        assert code == 0 and changed["status"] == "CHANGED"
        assert changed["result"]["image_cache"]["enabled"] is True
        assert changed["result"]["image_cache"]["available"] == 2
        removed = changed["result"]["diff"]["removed"][0]
        assert removed["image_cache"]["cache_status"] == "AVAILABLE_HISTORICAL"
        assert Path(removed["image_cache"]["cached_image_path"]).is_file()

        event = next(
            event
            for event in service.storage.list_outbox("test-monitor")
            if event["event_type"] == "inventory.removed"
        )
        assert event["payload"]["change"]["image_cache"] == removed["image_cache"]
    finally:
        service.close()
        client.close()


def test_five_modified_items_require_three_consistent_samples(
    tmp_path: Path, manifest_file: Path
) -> None:
    baseline_items = make_items(10)
    changed_items = make_items(10, price_delta=500)
    adapter = SequenceAdapter(
        [fetch(baseline_items), fetch(baseline_items), fetch(changed_items), fetch(changed_items), fetch(changed_items)]
    )
    service = service_for(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        result, code = service.run_monitor("test-monitor", "suspicious")
        assert code == 0 and result["status"] == "CHANGED"
        assert result["result"]["change_count"] == 10
        assert result["result"]["confirmation_samples"] == 3
    finally:
        service.close()


def test_inconsistent_change_is_invalid(tmp_path: Path, manifest_file: Path) -> None:
    baseline_items = make_items(3)
    changed_a = make_items(3, price_delta=1)
    changed_b = make_items(3, price_delta=2)
    changed_c = make_items(3, price_delta=3)
    adapter = SequenceAdapter(
        [fetch(baseline_items), fetch(baseline_items), fetch(changed_a), fetch(changed_b), fetch(changed_c)]
    )
    service = service_for(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        before = service.storage.latest_snapshot("test-monitor")["snapshot_hash"]
        result, code = service.run_monitor("test-monitor", "inconsistent")
        assert code == 2 and result["status"] == "INVALID"
        assert result["error"]["details"]["reason"] == "SNAPSHOT_INCONSISTENT"
        assert service.storage.latest_snapshot("test-monitor")["snapshot_hash"] == before
    finally:
        service.close()
