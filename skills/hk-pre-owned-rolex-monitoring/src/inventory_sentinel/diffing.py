from __future__ import annotations

from typing import Any

from .models import InventoryItem
from .presentation import item_change_payload, product_identity


def calculate_diff(previous: list[InventoryItem], current: list[InventoryItem]) -> dict[str, list[dict[str, Any]]]:
    before = {item.stable_id: item for item in previous}
    after = {item.stable_id: item for item in current}

    added = [item_change_payload(after[key]) for key in sorted(after.keys() - before.keys())]
    removed = [item_change_payload(before[key]) for key in sorted(before.keys() - after.keys())]
    modified: list[dict[str, Any]] = []
    for key in sorted(before.keys() & after.keys()):
        old_payload = before[key].business_payload()
        new_payload = after[key].business_payload()
        if old_payload != new_payload:
            fields = sorted(name for name in old_payload if old_payload.get(name) != new_payload.get(name))
            modified.append(
                {
                    "stable_id": key,
                    "product_identity": product_identity(after[key]),
                    "fields": fields,
                    "before": before[key].model_dump(mode="json"),
                    "after": after[key].model_dump(mode="json"),
                }
            )
    return {"added": added, "removed": removed, "modified": modified}


def diff_count(diff: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(values) for values in diff.values())
