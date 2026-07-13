from __future__ import annotations

import json
from pathlib import Path

from inventory_sentinel.errors import ConfigError
from inventory_sentinel.models import FetchResult, InventoryItem, MonitorManifest


class FixtureAdapter:
    name = "fixture"

    def fetch(self, manifest: MonitorManifest) -> FetchResult:
        raw_path = manifest.target.fixture_path or manifest.target.url
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"Fixture 不存在: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload["items"] if isinstance(payload, dict) else payload
            items = [InventoryItem.model_validate(row) for row in rows]
        except Exception as exc:
            raise ConfigError(f"Fixture 解析失败: {exc}") from exc
        return FetchResult(
            items=items,
            warnings=list(payload.get("warnings", [])) if isinstance(payload, dict) else [],
            diagnostics={"source": "fixture", "path": str(path), "raw_count": len(items)},
            raw_payload=payload,
        )
