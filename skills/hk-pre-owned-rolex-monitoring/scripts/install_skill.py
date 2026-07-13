#!/usr/bin/env python3
"""把同一个 Skill 包安装到受支持宿主的项目级或用户级目录。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


SKILL_NAME = "hk-pre-owned-rolex-monitoring"
PROJECT_LAYOUTS = {
    "codex": Path(".agents/skills"),
    "claude-code": Path(".claude/skills"),
    "vscode-copilot": Path(".agents/skills"),
    "cursor": Path(".cursor/skills"),
}
USER_LAYOUTS = {
    "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills",
    "claude-code": Path.home() / ".claude/skills",
    "cursor": Path.home() / ".cursor/skills",
}


def resolve_base(host: str, scope: str, project_dir: Path) -> Path:
    if host == "windsurf":
        raise ValueError("Windsurf 原生 Skill 发现路径尚未验证；请安装 Python 包并直接调用 inventoryctl")
    if scope == "project":
        return project_dir.resolve() / PROJECT_LAYOUTS[host]
    if host not in USER_LAYOUTS:
        raise ValueError(f"{host} 的用户级 Agent Skills 路径未纳入第一阶段验证")
    return USER_LAYOUTS[host].expanduser().resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 HK Pre-owned Rolex Monitoring Skill 包")
    parser.add_argument(
        "--host",
        required=True,
        choices=["codex", "claude-code", "vscode-copilot", "cursor", "windsurf"],
    )
    parser.add_argument("--scope", choices=["project", "user"], default="project")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--target-base", help="测试或自定义安装时覆盖宿主基础目录")
    parser.add_argument("--force", action="store_true", help="覆盖已有同名 Skill")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    try:
        base = (
            Path(args.target_base).expanduser().resolve()
            if args.target_base
            else resolve_base(args.host, args.scope, Path(args.project_dir))
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "status": "UNVERIFIED", "error": str(exc)}, ensure_ascii=False))
        return 3

    destination = base / SKILL_NAME
    result = {
        "ok": True,
        "status": "DRY_RUN" if args.dry_run else "INSTALLED",
        "host": args.host,
        "scope": args.scope,
        "source": str(source),
        "destination": str(destination),
    }
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if destination.exists() and not args.force:
        print(
            json.dumps(
                {**result, "ok": False, "status": "EXISTS", "error": "目标 Skill 已存在；使用 --force 覆盖"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3
    base.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".coverage",
            "*.egg-info",
            "build",
            "dist",
        ),
    )
    required = [destination / "SKILL.md", destination / "scripts/inventoryctl.py", destination / "pyproject.toml"]
    if not all(path.is_file() for path in required):
        print(json.dumps({**result, "ok": False, "status": "ERROR", "error": "安装结构校验失败"}, ensure_ascii=False))
        return 4
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
