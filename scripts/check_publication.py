#!/usr/bin/env python3
"""校验仓库级发布包装，并始终输出结构化 JSON。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "hk-pre-owned-rolex-monitoring"
VERSION_FILE = SKILL / "src" / "inventory_sentinel" / "version.py"
PLACEHOLDERS = ("<owner>", "<repo>", "OWNER/REPOSITORY", "<你的 GitHub 用户名>")
FORBIDDEN_DIR_NAMES = {"__pycache__", ".pytest_cache", "build", "dist"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3"}


def check_item(checks: list[dict[str, object]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})


def read_version() -> str | None:
    if not VERSION_FILE.is_file():
        return None
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', VERSION_FILE.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def is_forbidden_public_path(path: Path) -> bool:
    return (
        any(part in FORBIDDEN_DIR_NAMES for part in path.parts)
        or path.suffix in FORBIDDEN_SUFFIXES
        or path.name == ".env"
        or path.name.startswith(".env.")
    )


def publication_candidates() -> tuple[list[Path], str]:
    """返回可能进入 GitHub 的文件，而不是本机全部生成物。"""

    try:
        relative_skill = SKILL.relative_to(ROOT).as_posix()
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                relative_skill,
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        # 尚未初始化 Git 的开发目录只能近似模拟发布面；这些路径会被
        # .gitignore 排除，正式 Release 仍由 git archive 只打包受控文件。
        candidates = [
            path
            for path in SKILL.rglob("*")
            if not any(
                part in FORBIDDEN_DIR_NAMES or part in {".venv", "state", "htmlcov"} or part.endswith(".egg-info")
                for part in path.relative_to(SKILL).parts
            )
            and path.suffix not in FORBIDDEN_SUFFIXES
            and path.name not in {".coverage", ".env"}
            and not path.name.startswith(".env.")
        ]
        return candidates, "filesystem-fallback"

    paths = [ROOT / value.decode() for value in result.stdout.split(b"\0") if value]
    return paths, "git-index-and-untracked"


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 HK Rolex Skill 发布包装")
    parser.add_argument("--mode", choices=("ci", "release"), default="ci")
    parser.add_argument("--tag", help="正式发布时验证的 Git tag，例如 v0.1.0")
    args = parser.parse_args()

    checks: list[dict[str, object]] = []
    common_files = (
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
    )
    missing_common = [name for name in common_files if not (ROOT / name).is_file()]
    check_item(checks, "repository_files", not missing_common, f"missing={missing_common}")

    skill_files = (
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/inventoryctl.py",
        "pyproject.toml",
    )
    missing_skill = [name for name in skill_files if not (SKILL / name).is_file()]
    check_item(checks, "skill_files", not missing_skill, f"missing={missing_skill}")

    skill_text = (SKILL / "SKILL.md").read_text() if (SKILL / "SKILL.md").is_file() else ""
    check_item(
        checks,
        "skill_identity",
        "name: hk-pre-owned-rolex-monitoring" in skill_text,
        "SKILL.md name matches directory",
    )

    readme_text = (ROOT / "README.md").read_text() if (ROOT / "README.md").is_file() else ""
    expected_install_text = (
        "请检查并安装这个 Skill",
        "inventoryctl skill info --json",
        "inventoryctl runtime probe --json",
    )
    missing_install_text = [text for text in expected_install_text if text not in readme_text]
    check_item(checks, "agent_install_contract", not missing_install_text, f"missing={missing_install_text}")

    version = read_version()
    check_item(checks, "version_readable", version is not None, f"version={version}")

    candidates, publication_scope = publication_candidates() if SKILL.is_dir() else ([], "missing-skill")
    forbidden_paths = [str(path.relative_to(ROOT)) for path in candidates if is_forbidden_public_path(path)]
    check_item(
        checks,
        "release_hygiene",
        not forbidden_paths,
        f"scope={publication_scope}, forbidden={forbidden_paths}",
    )

    if args.mode == "release":
        check_item(checks, "license", (ROOT / "LICENSE").is_file(), "LICENSE must exist")
        placeholder_hits = [placeholder for placeholder in PLACEHOLDERS if placeholder in readme_text]
        check_item(checks, "repository_url", not placeholder_hits, f"placeholders={placeholder_hits}")
        stable_version = bool(version and "dev" not in version and "+" not in version)
        check_item(checks, "stable_version", stable_version, f"version={version}")
        if args.tag:
            expected_tag = f"v{version}" if version else None
            check_item(checks, "tag_matches_version", args.tag == expected_tag, f"tag={args.tag}, expected={expected_tag}")
        else:
            check_item(checks, "tag_matches_version", False, "--tag is required in release mode")

    ok = all(bool(item["ok"]) for item in checks)
    payload = {
        "schema_version": 1,
        "ok": ok,
        "operation": "publication.check",
        "status": "PASS" if ok else "FAIL",
        "mode": args.mode,
        "version": version,
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
