from __future__ import annotations

import json

import httpx
import pytest

from inventory_sentinel.adapters.orientalwatch import OrientalWatchAdapter
from inventory_sentinel.errors import BrowserRequired, InvalidSnapshot
from inventory_sentinel.models import MonitorManifest


def make_manifest() -> MonitorManifest:
    return MonitorManifest.model_validate(
        {
            "schema_version": 1,
            "monitor_id": "orientalwatch-test",
            "display_name": "东方表行测试",
            "target": {
                "adapter": "orientalwatch-rolex-cpo",
                "url": "https://www.orientalwatch.com/zh-hant/rolex-certified-pre-owned/watches/",
            },
            "validation": {"sample_interval_seconds": 0},
        }
    )


def build_client(payload: dict, *, page_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                page_status,
                text='<script src="/js/rcpo_watches.js?20250909"></script>',
                headers={"set-cookie": "ASP.NET_SessionId=test; Path=/"},
                request=request,
            )
        assert request.headers.get("cookie") == "ASP.NET_SessionId=test"
        return httpx.Response(200, json={"d": json.dumps(payload)}, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_dynamic_columns_and_double_json_are_supported() -> None:
    payload = {
        "table_column": "Currency_Code,Lot_Number_Code,Family_txt,List_Price,Family_Code,RL_Date_1,RL_Date_2,Watch_Reference",
        "ds": {
            "filter_result": [
                ["HKD", "LOT-A", "Datejust", 108000, "datejust", 2020, 2019, "126334"]
            ]
        },
    }
    adapter = OrientalWatchAdapter(client=build_client(payload))
    result = adapter.fetch(make_manifest())
    assert result.items[0].stable_id == "LOT-A"
    assert str(result.items[0].price) == "108000"
    assert result.items[0].family_code == "datejust"
    assert result.items[0].year == 2020
    assert result.items[0].reference == "126334"
    assert result.items[0].condition == "unknown"
    assert result.items[0].attributes["year_raw_1"] == 2020
    assert result.items[0].attributes["year_raw_2"] == 2019
    assert result.items[0].attributes["year_source"] == "RL_Date_1"
    assert result.items[0].attributes["reference_source"] == "Watch_Reference"
    assert result.items[0].detail_url.endswith("/datejust/LOT-A/")


def test_missing_non_identity_fields_warn_but_keep_item() -> None:
    payload = {
        "table_column": "Lot_Number_Code,Family_Code,Family_txt,List_Price,Currency_Code",
        "ds": {"filter_result": [["LOT-B", None, None, None, None]]},
    }
    adapter = OrientalWatchAdapter(client=build_client(payload))
    result = adapter.fetch(make_manifest())
    assert [item.stable_id for item in result.items] == ["LOT-B"]
    assert result.items[0].price is None
    assert result.warnings


@pytest.mark.parametrize(
    "rows, reason",
    [
        ([], "EMPTY_SNAPSHOT"),
        ([["", "family", "Watch", 1, "HKD"]], "MISSING_STABLE_ID"),
        (
            [["LOT-C", "family", "Watch", 1, "HKD"], ["LOT-C", "family", "Watch", 1, "HKD"]],
            "DUPLICATE_STABLE_ID",
        ),
    ],
)
def test_empty_missing_or_duplicate_identity_is_invalid(rows: list, reason: str) -> None:
    payload = {
        "table_column": "Lot_Number_Code,Family_Code,Family_txt,List_Price,Currency_Code",
        "ds": {"filter_result": rows},
    }
    adapter = OrientalWatchAdapter(client=build_client(payload))
    with pytest.raises(InvalidSnapshot) as caught:
        adapter.fetch(make_manifest())
    assert caught.value.details["reason"] == reason


def test_error_page_requires_browser_instead_of_partial_parse() -> None:
    adapter = OrientalWatchAdapter(client=build_client({}, page_status=403))
    with pytest.raises(BrowserRequired):
        adapter.fetch(make_manifest())


def test_malformed_double_json_is_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text="rcpo_watches.js", request=request)
        return httpx.Response(200, json={"d": "not-json"}, request=request)

    adapter = OrientalWatchAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(InvalidSnapshot) as caught:
        adapter.fetch(make_manifest())
    assert caught.value.details["reason"] == "MALFORMED_JSON"
