from __future__ import annotations

from inventory_sentinel.errors import ConfigError

from .base import SiteAdapter
from .fixture import FixtureAdapter
from .orientalwatch import OrientalWatchAdapter


class AdapterRegistry:
    def __init__(self, adapters: dict[str, SiteAdapter] | None = None) -> None:
        self._adapters: dict[str, SiteAdapter] = adapters or {
            FixtureAdapter.name: FixtureAdapter(),
            OrientalWatchAdapter.name: OrientalWatchAdapter(),
        }

    def get(self, name: str) -> SiteAdapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise ConfigError(f"未安装 Site Adapter: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._adapters)
