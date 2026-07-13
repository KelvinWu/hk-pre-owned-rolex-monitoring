from __future__ import annotations

from decimal import Decimal

import pytest

from inventory_sentinel.diffing import calculate_diff, diff_count
from inventory_sentinel.errors import InvalidSnapshot
from inventory_sentinel.models import FetchResult, InventoryItem, ValidationConfig
from inventory_sentinel.validation import is_suspicious, same_id_set, validate_fetch

from conftest import make_items


def test_price_and_image_changes_are_modified_not_new_identity() -> None:
    before = make_items(2)
    after = make_items(2)
    after[0] = after[0].model_copy(
        update={"price": Decimal("12000"), "image_url": "https://img.example.test/new.jpg"}
    )
    diff = calculate_diff(before, list(reversed(after)))
    assert not diff["added"]
    assert not diff["removed"]
    assert diff_count(diff) == 1
    assert diff["modified"][0]["stable_id"] == "LOT-001"
    assert diff["modified"][0]["product_identity"] == {
        "brand": "Rolex",
        "product_name": "Watch 1",
        "rolex_reference": "REF-001",
        "oriental_lot_number": "LOT-001",
        "year": None,
        "diameter": None,
        "material": None,
        "bracelet": None,
        "detail_url": "https://example.test/1",
        "display_name": "Rolex Watch 1｜型号 REF-001｜东方表行货号 LOT-001",
    }
    assert diff["modified"][0]["fields"] == ["image_url", "price"]
    assert same_id_set(before, after)


@pytest.mark.parametrize(
    "items, reason",
    [
        ([], "EMPTY_SNAPSHOT"),
        ([InventoryItem(stable_id="", source_id="x")], "MISSING_STABLE_ID"),
        (
            [InventoryItem(stable_id="A", source_id="A"), InventoryItem(stable_id="A", source_id="A")],
            "DUPLICATE_STABLE_ID",
        ),
    ],
)
def test_invalid_snapshots_are_rejected(items: list[InventoryItem], reason: str) -> None:
    with pytest.raises(InvalidSnapshot) as caught:
        validate_fetch(FetchResult(items=items))
    assert caught.value.details["reason"] == reason


def test_suspicious_threshold_uses_total_changed_items() -> None:
    config = ValidationConfig(suspicious_absolute_change=5, suspicious_percentage_change=10)
    assert is_suspicious(5, 100, config)
    assert is_suspicious(4, 20, config)
    assert not is_suspicious(4, 100, config)
