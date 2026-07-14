from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPOSITORY_ROOT / "scripts" / "check_publication.py"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def load_check_module():
    spec = importlib.util.spec_from_file_location("check_publication", CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_minimal_repository(root: Path) -> Path:
    skill = root / "skills" / "hk-pre-owned-rolex-monitoring"
    for relative in (
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("publication fixture\n")

    (root / "README.md").write_text(
        "请检查并安装这个 Skill\n"
        "inventoryctl skill info --json\n"
        "inventoryctl runtime probe --json\n"
    )
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.py[cod]\n")

    required = {
        "SKILL.md": "---\nname: hk-pre-owned-rolex-monitoring\n---\n",
        "agents/openai.yaml": "interface: {}\n",
        "scripts/bootstrap.py": "",
        "scripts/inventoryctl.py": "",
        "pyproject.toml": "",
        "src/inventory_sentinel/version.py": '__version__ = "0.1.0.dev0"\n',
    }
    for relative, content in required.items():
        path = skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return skill


def test_ignored_test_caches_are_not_publication_content(tmp_path, monkeypatch, capsys):
    module = load_check_module()
    skill = make_minimal_repository(tmp_path)
    cache_file = skill / "tests" / "__pycache__" / "test_example.cpython-313.pyc"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"generated")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SKILL", skill)
    monkeypatch.setattr(module, "VERSION_FILE", skill / "src/inventory_sentinel/version.py")
    monkeypatch.setattr(sys, "argv", [str(CHECK_SCRIPT), "--mode", "ci"])

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"


def test_release_archives_only_version_controlled_skill_files():
    workflow = RELEASE_WORKFLOW.read_text()
    assert "git archive" in workflow
    assert "tar -C skills" not in workflow


def test_publication_requires_dependency_free_bootstrap(tmp_path, monkeypatch, capsys):
    module = load_check_module()
    skill = make_minimal_repository(tmp_path)
    (skill / "scripts/bootstrap.py").unlink()

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SKILL", skill)
    monkeypatch.setattr(module, "VERSION_FILE", skill / "src/inventory_sentinel/version.py")
    monkeypatch.setattr(sys, "argv", [str(CHECK_SCRIPT), "--mode", "ci"])

    assert module.main() == 1
    payload = json.loads(capsys.readouterr().out)
    skill_files = next(check for check in payload["checks"] if check["name"] == "skill_files")
    assert skill_files["ok"] is False
    assert "scripts/bootstrap.py" in skill_files["detail"]


def test_v020_local_code_preserves_mit_and_published_v011_url():
    license_text = (REPOSITORY_ROOT / "LICENSE").read_text()
    package = tomllib.loads(
        (REPOSITORY_ROOT / "skills/hk-pre-owned-rolex-monitoring/pyproject.toml").read_text()
    )
    version_text = (
        REPOSITORY_ROOT
        / "skills/hk-pre-owned-rolex-monitoring/src/inventory_sentinel/version.py"
    ).read_text()
    readme = (REPOSITORY_ROOT / "README.md").read_text()

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 KelvinWu" in license_text
    assert package["project"]["license"] == "MIT"
    assert '__version__ = "0.2.0"' in version_text
    assert "当前正式版本为 `0.2.0`" in readme
    assert "https://github.com/KelvinWu/hk-pre-owned-rolex-monitoring/tree/v0.2.0/" in readme


def test_workflows_use_node24_compatible_setup_python():
    for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        workflow = (REPOSITORY_ROOT / relative).read_text()
        assert "actions/setup-python@v6" in workflow
        assert "actions/setup-python@v5" not in workflow


def test_release_workflow_verifies_the_bootstrap_installer():
    workflow = RELEASE_WORKFLOW.read_text()

    assert "scripts/bootstrap.py" in workflow
    assert " install --package " in workflow
