# 宿主兼容性

Skill 本体遵循 Agent Skills 目录约定，并通过同一 CLI 执行确定性逻辑。

| 宿主 | 常见安装位置 | 第一阶段状态 |
|---|---|---|
| Codex | `~/.codex/skills/hk-pre-owned-rolex-monitoring/` | 结构与 CLI 验证 |
| Claude Code | `.claude/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| VS Code / Copilot | `.agents/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Cursor | `.cursor/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Windsurf | 使用仓库或 Skill 目录调用 CLI | 原生发现路径未验证 |
| Generic Shell | 任意目录安装并运行 `inventoryctl` | CLI 验证 |

“结构验证”不等于已在对应产品 UI 中完成实机演练。

所有宿主都必须为 `--state-dir` 或 `INVENTORY_SENTINEL_HOME` 提供跨任务持久目录。项目级 Skill 安装目录只保存代码，不保存数据库或图片；临时工作区、一次性容器和 Agent 对话附件区不能作为长期状态目录。

## 项目级安装

在 Skill 根目录运行：

```bash
python scripts/install_skill.py --host codex --scope project --project-dir /path/to/project
python scripts/install_skill.py --host claude-code --scope project --project-dir /path/to/project
python scripts/install_skill.py --host vscode-copilot --scope project --project-dir /path/to/project
python scripts/install_skill.py --host cursor --scope project --project-dir /path/to/project
```

安装脚本只复制同一个 Skill 包，不生成宿主专用业务逻辑。Python 包仍需在宿主可调用的环境中安装：

```bash
python -m pip install /path/to/hk-pre-owned-rolex-monitoring
inventoryctl skill info --json
```

Windsurf 第一阶段只保证终端 CLI；在权威文档或实机验证完成前，不声明原生发现路径。
