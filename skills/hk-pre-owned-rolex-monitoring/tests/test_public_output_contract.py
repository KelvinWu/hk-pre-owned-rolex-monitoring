from __future__ import annotations

from inventory_sentinel.output import result_envelope
from inventory_sentinel.presentation import build_human_summary_zh, change_summary_zh
from inventory_sentinel.service import InventoryService
from inventory_sentinel.version import __version__


def test_result_envelope_public_contract_is_stable() -> None:
    payload = result_envelope(
        operation="monitor.run",
        status="CHANGED",
        ok=True,
        monitor_id="monitor-1",
        run_id="run-1",
        state_modified=True,
        result={"human_summary_zh": {"headline": "发现变化。", "changes": []}},
        warnings=["图片缓存失败，不影响库存结果。"],
    )

    assert payload == {
        "schema_version": 1,
        "ok": True,
        "operation": "monitor.run",
        "status": "CHANGED",
        "skill_version": __version__,
        "monitor_id": "monitor-1",
        "run_id": "run-1",
        "state_modified": True,
        "result": {"human_summary_zh": {"headline": "发现变化。", "changes": []}},
        "warnings": ["图片缓存失败，不影响库存结果。"],
        "error": None,
    }


def test_price_change_human_summary_names_the_watch_and_lot_number() -> None:
    change = {
        "product_identity": {
            "product_name": "Datejust 41",
            "rolex_reference": "126334",
            "oriental_lot_number": "LOT-001",
            "year": 2021,
        },
        "fields": ["price"],
        "before": {"price": "100000", "currency": "HKD"},
        "after": {"price": "95000", "currency": "HKD"},
    }

    assert change_summary_zh("modified", change) == (
        "价格下调：Rolex Datejust 41（型号 126334；东方表行货号 LOT-001；年份 2021），"
        "HK$100,000 → HK$95,000（-HK$5,000，-5.00%）。"
    )


def test_no_change_human_summary_public_contract_is_stable() -> None:
    assert build_human_summary_zh(
        "NO_CHANGE",
        {"added": [], "removed": [], "modified": []},
        84,
    ) == {"headline": "库存无变化，当前共 84 只。", "changes": []}


def test_skill_info_public_contract_is_stable() -> None:
    payload, exit_code = InventoryService.skill_info()

    assert exit_code == 0
    assert payload == {
        "schema_version": 1,
        "ok": True,
        "operation": "skill.info",
        "status": "NO_CHANGE",
        "skill_version": __version__,
        "monitor_id": None,
        "run_id": None,
        "state_modified": False,
        "result": {
            "name": "hk-pre-owned-rolex-monitoring",
            "version": __version__,
            "manifest_schema_version": 1,
            "market_packet_schema_version": 1,
            "market_source_registry_version": 2,
            "state_schema_version": 1,
            "platform_neutral": True,
            "host_actions_executed": False,
        },
        "warnings": [],
        "error": None,
    }
