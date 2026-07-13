from __future__ import annotations

from .errors import InvalidSnapshot
from .models import FetchResult, InventoryItem, ValidationConfig


def validate_fetch(fetch: FetchResult) -> None:
    if not fetch.items:
        raise InvalidSnapshot("站点返回 0 条商品", details={"reason": "EMPTY_SNAPSHOT"})
    ids = [item.stable_id.strip() for item in fetch.items]
    if any(not stable_id for stable_id in ids):
        raise InvalidSnapshot("商品缺少 stable ID", details={"reason": "MISSING_STABLE_ID"})
    duplicates = sorted({stable_id for stable_id in ids if ids.count(stable_id) > 1})
    if duplicates:
        raise InvalidSnapshot(
            "快照包含重复 stable ID",
            details={"reason": "DUPLICATE_STABLE_ID", "stable_ids": duplicates},
        )


def same_snapshot(left: list[InventoryItem], right: list[InventoryItem]) -> bool:
    left_map = {item.stable_id: item.model_dump(mode="json") for item in left}
    right_map = {item.stable_id: item.model_dump(mode="json") for item in right}
    return left_map == right_map


def same_id_set(left: list[InventoryItem], right: list[InventoryItem]) -> bool:
    return {item.stable_id for item in left} == {item.stable_id for item in right}


def is_suspicious(change_count: int, previous_count: int, config: ValidationConfig) -> bool:
    percentage = (change_count / previous_count * 100) if previous_count else 100
    return (
        change_count >= config.suspicious_absolute_change
        or percentage >= config.suspicious_percentage_change
    )
