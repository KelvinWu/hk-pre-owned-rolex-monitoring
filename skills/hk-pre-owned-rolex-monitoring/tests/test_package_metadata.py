from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from inventory_sentinel.version import __version__


SKILL_ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_source_of_truth() -> None:
    config = tomllib.loads((SKILL_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in config["project"]
    assert config["project"]["dynamic"] == ["version"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "inventory_sentinel.version.__version__"
    }
    assert version("hk-pre-owned-rolex-monitoring") == __version__


def test_test_dependencies_include_only_used_test_tooling() -> None:
    config = tomllib.loads((SKILL_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    test_dependencies = config["project"]["optional-dependencies"]["test"]

    assert all(not dependency.lower().startswith("respx") for dependency in test_dependencies)
