from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pytest

from inventory_sentinel.models import FetchResult, InventoryItem, MonitorManifest


class SequenceAdapter:
    name = "sequence"

    def __init__(self, samples: Iterable[FetchResult] = ()) -> None:
        self.samples = list(samples)
        self.calls = 0

    def extend(self, *samples: FetchResult) -> None:
        self.samples.extend(samples)

    def fetch(self, manifest: MonitorManifest) -> FetchResult:
        self.calls += 1
        if not self.samples:
            raise AssertionError("SequenceAdapter 没有可用样本")
        return self.samples.pop(0)


class NoopImageCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def cache(self, items: list[InventoryItem]) -> list[str]:
        return []

    def close(self) -> None:
        return None


def make_items(count: int = 3, *, price_delta: int = 0) -> list[InventoryItem]:
    return [
        InventoryItem(
            stable_id=f"LOT-{index:03d}",
            source_id=f"LOT-{index:03d}",
            title=f"Watch {index}",
            price=Decimal(10000 + index + price_delta),
            currency="HKD",
            reference=f"REF-{index:03d}",
            detail_url=f"https://example.test/{index}",
            image_url=f"https://img.example.test/{index}.jpg",
        )
        for index in range(1, count + 1)
    ]


def fetch(items: list[InventoryItem], *, warnings: list[str] | None = None) -> FetchResult:
    return FetchResult(items=items, warnings=warnings or [], diagnostics={"source": "test"})


@pytest.fixture
def manifest() -> MonitorManifest:
    return MonitorManifest.model_validate(
        {
            "schema_version": 1,
            "monitor_id": "test-monitor",
            "display_name": "测试监控",
            "target": {"adapter": "sequence", "url": "https://example.test/catalog"},
            "schedule": {
                "timezone": "Asia/Shanghai",
                "jobs": [{"role": "daily", "cron": "0 10 * * *"}],
            },
            "notification": {"include_images": False},
            "validation": {
                "sample_interval_seconds": 0,
                "suspicious_absolute_change": 5,
                "suspicious_percentage_change": 100,
            },
            "state": {"image_cache": False},
        }
    )


@pytest.fixture
def manifest_file(tmp_path: Path, manifest: MonitorManifest) -> Path:
    path = tmp_path / "monitor.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path
