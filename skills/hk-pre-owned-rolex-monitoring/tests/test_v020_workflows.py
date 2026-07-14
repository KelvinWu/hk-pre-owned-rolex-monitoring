from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from inventory_sentinel.errors import ConfigError
from inventory_sentinel.market_sources import diagnose_source
from inventory_sentinel.runtime_plan import build_runtime_plan
from inventory_sentinel.service import InventoryService

from conftest import SequenceAdapter, fetch, make_items
from test_service_lifecycle import service_for


def test_monitor_init_writes_safe_draft_without_schedules(tmp_path: Path) -> None:
    destination = tmp_path / "monitor.yaml"
    payload, code = InventoryService.monitor_init(
        output_path=destination,
        monitor_id="my-rolex-monitor",
        display_name="我的香港二手劳力士监控",
        timezone="Asia/Hong_Kong",
        recipient="current-user",
        jobs=[],
        overwrite=False,
    )
    assert code == 0
    assert destination.is_file()
    assert payload["result"]["setup_required"] is True
    assert payload["result"]["manifest"]["schedule"]["jobs"] == []
    assert payload["next_actions"][0]["action"] == "确认配置并创建监控"


def test_market_packet_builder_lifecycle(tmp_path: Path) -> None:
    packet = tmp_path / "packet.json"
    evidence = tmp_path / "evidence.txt"
    authorized_csv = tmp_path / "authorized.csv"
    evidence.write_text("authorized snapshot", encoding="utf-8")
    authorized_csv.write_text(
        "observation_id,source,independence_group,rolex_reference,region,basis,price_hkd,observed_at,year,condition,completeness,evidence_status,acquisition_method,evidence_note\n"
        "obs-2,28watches,28watches,126334,HK,asking_price,102000,2026-07-14T09:30:00+08:00,2022,very_good,full_set,unverified,authorized_export,授权 CSV\n",
        encoding="utf-8",
    )

    created, code = InventoryService.market_packet_init(
        output_path=packet,
        packet_id="packet-v020",
        as_of="2026-07-14T12:00:00+08:00",
        overwrite=False,
    )
    assert code == 0 and created["result"]["observation_count"] == 0

    added, code = InventoryService.market_packet_add(
        file_path=packet,
        observation={
            "observation_id": "obs-1",
            "source": "watchfinder-hk",
            "independence_group": "watchfinder",
            "rolex_reference": "126334",
            "region": "HK",
            "basis": "asking_price",
            "price_hkd": 100000,
            "observed_at": "2026-07-14T09:00:00+08:00",
            "year": 2021,
            "condition": "excellent",
            "completeness": "full_set",
            "evidence_status": "unverified",
            "acquisition_method": "manual_snapshot",
            "evidence_note": "待附加证据",
        },
    )
    assert code == 0 and added["result"]["observation_count"] == 1

    attached, code = InventoryService.market_packet_attach_evidence(
        file_path=packet,
        observation_id="obs-1",
        evidence_file=evidence,
        verified_at="2026-07-14T10:00:00+08:00",
    )
    assert code == 0
    assert attached["result"]["evidence_sha256"].startswith("sha256:")

    imported, code = InventoryService.market_packet_import_csv(
        file_path=packet,
        csv_path=authorized_csv,
        source=None,
    )
    assert code == 0
    assert imported["result"]["imported"] == 1
    assert imported["result"]["observation_count"] == 2

    finalized, code = InventoryService.market_packet_finalize(packet)
    assert code == 0
    assert finalized["result"]["evidence_status_counts"]["verified"] == 1


def test_source_policy_fails_closed_when_review_is_stale() -> None:
    result = diagnose_source(
        "watchcharts",
        mode="automatic",
        intended_use="internal",
        environ={"WATCHCHARTS_API_KEY": "present", "WATCHCHARTS_LICENSE": "internal"},
        today=date(2027, 1, 1),
    )
    assert result["ready"] is False
    assert result["source_status"] == "SOURCE_POLICY_STALE"
    assert result["review_due_at"] is not None


def test_runtime_plan_consumes_retry_delays(manifest) -> None:
    plan = build_runtime_plan(manifest).model_dump(mode="json")
    assert plan["operations"][0]["parameters"]["retry_delays_seconds"] == [120, 300, 600]


def test_outbox_ack_requires_real_delivery_receipt(
    tmp_path: Path, manifest_file: Path
) -> None:
    items = make_items(2)
    adapter = SequenceAdapter([fetch(items), fetch(items), fetch(items)])
    service = service_for(tmp_path, adapter)
    try:
        service.create_monitor(manifest_file)
        service.baseline("test-monitor")
        service.run_monitor("test-monitor", "delivery")
        event_id = service.storage.list_outbox("test-monitor")[0]["event_id"]

        sent, code = service.outbox_ack(
            event_id,
            provider="test-provider",
            external_message_id="message-1",
            delivered_at="2026-07-14T12:00:00+08:00",
            verified=True,
            delivery_error=None,
        )
        assert code == 0
        assert sent["result"]["delivery_status"] == "verified"
        assert sent["result"]["verified"] is True

        duplicate, code = service.outbox_ack(
            event_id,
            provider="test-provider",
            external_message_id="message-1",
            delivered_at="2026-07-14T12:00:00+08:00",
            verified=True,
            delivery_error=None,
        )
        assert code == 0 and duplicate["status"] == "SKIPPED_DUPLICATE"

        with pytest.raises(ConfigError):
            service.outbox_ack(
                "missing-event",
                provider="test-provider",
                external_message_id="message-2",
                delivered_at=None,
                verified=True,
                delivery_error=None,
            )
    finally:
        service.close()


def test_skill_self_test_is_state_free_and_complete() -> None:
    payload, code = InventoryService.self_test()
    assert code == 0
    assert payload["status"] == "NO_CHANGE"
    assert payload["result"]["self_test_status"] == "PASS"
    assert all(check["ok"] for check in payload["result"]["checks"])
