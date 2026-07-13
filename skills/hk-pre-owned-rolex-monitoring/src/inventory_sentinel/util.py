from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from .models import InventoryItem


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def items_hash(items: list[InventoryItem]) -> str:
    payload = [item.model_dump(mode="json") for item in sorted(items, key=lambda x: x.stable_id)]
    return "sha256:" + hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()


def state_directory(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("INVENTORY_SENTINEL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return user_data_path(
        "hk-pre-owned-rolex-monitoring",
        "HK Pre-owned Rolex Monitoring",
        ensure_exists=False,
    )


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
