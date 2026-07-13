from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = SKILL_ROOT / "scripts/install_skill.py"
LAYOUTS = {
    "codex": Path(".agents/skills/hk-pre-owned-rolex-monitoring"),
    "claude-code": Path(".claude/skills/hk-pre-owned-rolex-monitoring"),
    "vscode-copilot": Path(".agents/skills/hk-pre-owned-rolex-monitoring"),
    "cursor": Path(".cursor/skills/hk-pre-owned-rolex-monitoring"),
}


@pytest.mark.parametrize("host", sorted(LAYOUTS))
def test_same_skill_package_installs_into_host_layout(tmp_path: Path, host: str) -> None:
    project = tmp_path / host
    completed = subprocess.run(
        [sys.executable, str(INSTALLER), "--host", host, "--scope", "project", "--project-dir", str(project)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    installed = project / LAYOUTS[host]
    assert (installed / "SKILL.md").is_file()
    assert (installed / "scripts/bootstrap.py").is_file()
    assert (installed / "scripts/inventoryctl.py").is_file()
    assert (installed / "pyproject.toml").is_file()

    info = subprocess.run(
        [sys.executable, str(installed / "scripts/inventoryctl.py"), "skill", "info", "--json"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert info.returncode == 0
    assert json.loads(info.stdout)["result"]["name"] == "hk-pre-owned-rolex-monitoring"


def test_windsurf_native_discovery_is_explicitly_unverified(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(INSTALLER), "--host", "windsurf", "--project-dir", str(tmp_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["status"] == "UNVERIFIED"


def test_skill_frontmatter_is_open_agent_skills_compatible() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 500
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == SKILL_ROOT.name


def test_skill_package_has_no_later_phase_product_specific_code() -> None:
    text_files = [
        path
        for path in SKILL_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".md", ".yaml", ".yml", ".json", ".toml"}
    ]
    later_phase_product = "qc" + "law"
    matches = [
        path
        for path in text_files
        if later_phase_product in path.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert matches == []
