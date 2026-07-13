# 宿主兼容性与运行环境安装

Skill 本体遵循 Agent Skills 目录约定，业务能力通过同一 CLI 执行。宿主安装分为两个独立动作：复制 Skill 文件，以及安装 Python 运行环境。复制成功不等于运行依赖已经可用。

## 兼容性边界

| 宿主 | 常见安装位置 | 当前验证边界 |
|---|---|---|
| Codex | `~/.codex/skills/hk-pre-owned-rolex-monitoring/` | 结构与 CLI 验证 |
| Claude Code | `.claude/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| VS Code / Copilot | `.agents/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Cursor | `.cursor/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Windsurf | 使用仓库或 Skill 目录调用 CLI | 原生发现路径未验证 |
| Generic Shell | 任意目录安装并运行 CLI | CLI 验证 |

“结构验证”不等于已在对应产品 UI 中完成实机演练。所有宿主必须把 `runtime-dir` 和 `state-dir` 放在跨任务持久位置，且两者不能相互嵌套；Skill 安装目录只保存 Skill 文件，不保存数据库、图片或运行虚拟环境。

## 依赖安装前诊断

`scripts/bootstrap.py` 只使用 Python 标准库，可以在 `httpx`、`pydantic`、`PyYAML` 和 `platformdirs` 尚未安装时运行：

```bash
python scripts/bootstrap.py doctor \
  --network-check download \
  --runtime-dir /persistent/runtime/venv \
  --state-dir /persistent/state \
  --json
```

`download` 检查通过 pip 实际下载声明的依赖及其 wheel，不能用包索引首页可访问代替。诊断状态包括：

| 状态 / 错误码 | 含义 |
|---|---|
| `READY` | Python、pip、安装目标和实际依赖下载均通过 |
| `READY_WITH_UNVERIFIED_NETWORK` | 跳过了下载检查，不能声称网络已经验证 |
| `DEFAULT_INDEX_DOWNLOAD_TIMEOUT` | 默认 pip 下载链路超时 |
| `CONFIGURED_INDEX_DOWNLOAD_TIMEOUT` | 宿主配置的包源下载超时 |
| `INDEX_DNS_ERROR` / `INDEX_TLS_ERROR` | DNS 或证书链路失败 |
| `DEPENDENCY_NOT_AVAILABLE` | 当前 Python / 平台没有满足约束的依赖包 |
| `NO_WRITABLE_INSTALL_TARGET` | 虚拟环境和用户安装目录均不可用 |
| `STATE_DIR_NOT_WRITABLE` | 指定状态目录当前不可写 |

## 镜像与 Secret

Bootstrap 不内置、不推荐也不静默选择任何第三方镜像。需要镜像时，由用户或宿主在运行环境中配置：

```text
PIP_INDEX_URL
PIP_EXTRA_INDEX_URL
```

配置后重新运行 `bootstrap.py doctor`，只有实际依赖下载成功才可继续。JSON 只显示镜像 origin；用户名、密码、查询参数和路径 token 必须被移除。不要把含凭证的镜像地址写进命令参数、Manifest、日志、状态或 GitHub。

## 安装固定 Release wheel

生产环境使用 GitHub Release 附带的 wheel 和 `SHA256SUMS.txt`，不使用 `pip install -e`：

```bash
python scripts/bootstrap.py install \
  --package /downloads/hk_pre_owned_rolex_monitoring-<version>-py3-none-any.whl \
  --sha256 <SHA-256> \
  --runtime-dir /persistent/runtime/venv \
  --state-dir /persistent/state \
  --json
```

默认 `install-mode=auto`：

1. 优先在 `runtime-dir` 创建独立虚拟环境；
2. 虚拟环境不可用时，仅在 Python user site 已启用且可写的情况下回退用户级安装；
3. 两者均不可用时返回 `INSTALL_BLOCKED`，不尝试提升系统权限；
4. 安装后实际运行 `skill info`；指定 `state-dir` 时同时运行 `runtime probe`；
5. 只有 `INSTALL_VERIFIED` 才算完成。

若用户级 Scripts 目录不在 PATH，使用安装回执返回的绝对路径，或使用稳定模块入口：

```bash
<python-executable> -m inventory_sentinel skill info --json
<python-executable> -m inventory_sentinel --state-dir /persistent/state runtime probe --json
```

安装回执会报告安装模式、Python 路径、`inventoryctl` 路径、模块回退命令、安装包 SHA-256 和验证结果，但不返回 pip 原始错误日志或可能带凭证的 URL。

## 复制 Skill 文件

在 Skill 根目录可以把同一包复制到不同宿主目录：

```bash
python scripts/install_skill.py --host codex --scope project --project-dir /path/to/project
python scripts/install_skill.py --host claude-code --scope project --project-dir /path/to/project
python scripts/install_skill.py --host vscode-copilot --scope project --project-dir /path/to/project
python scripts/install_skill.py --host cursor --scope project --project-dir /path/to/project
```

该脚本只复制 Skill，不安装 Python 依赖，也不写用户状态。Windsurf 当前只保证终端 CLI；取得权威资料或完成实机验证前，不声明原生发现路径。
