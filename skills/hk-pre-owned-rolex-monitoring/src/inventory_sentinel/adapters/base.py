from __future__ import annotations

from typing import Protocol

from inventory_sentinel.models import FetchResult, MonitorManifest


class SiteAdapter(Protocol):
    name: str

    def fetch(self, manifest: MonitorManifest) -> FetchResult: ...
