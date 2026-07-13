# HK Pre-owned Rolex Monitoring

[![CI](https://github.com/KelvinWu/hk-pre-owned-rolex-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/KelvinWu/hk-pre-owned-rolex-monitoring/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/KelvinWu/hk-pre-owned-rolex-monitoring)](https://github.com/KelvinWu/hk-pre-owned-rolex-monitoring/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个平台中立的 Agent Skill，用于监控香港东方表行公开的 Rolex Certified Pre-Owned（CPO）库存，保留商品图片，并用经过来源门禁的市场证据解释价格位置。

> 非官方项目，与 Rolex、东方表行、WatchCharts 或其他数据来源不存在隶属、授权或认可关系。不得使用本项目绕过登录、CAPTCHA、访问控制、地区限制或来源许可。

## 当前状态

- Skill 本体、离线 Fixture、结构化 CLI、状态保护、图片缓存、Market Packet 和来源诊断已经实现。
- 当前正式版本为 `0.1.1`；生产安装固定使用 `v0.1.1` tag，不跟随漂移的 `main`。
- 东方表行 Adapter 已完成技术验证，但公共发布与无人值守自动化仍须完成来源政策复核。
- 未经真实产品 UI 演练的宿主只标记为结构兼容，不声称已实测。

## 它能做什么

- 使用东方表行 `Lot_Number_Code` 建立稳定商品身份。
- 建立可信基线，检测上新、下架、改价和资料变化。
- 对异常、空结果、重复或部分抓取返回 `INVALID`，不覆盖上一份成功基线。
- 缓存当前和历史商品图片，为下架通知保留可用附件。
- 使用 SQLite、运行锁、Outbox、幂等键、备份和安全恢复保存可审计状态。
- 在自动调用行情来源前检查凭证、License、用途和来源政策。
- 将库存事实与市场参考分开；证据不足时不输出所谓“公允价”。

## 推荐安装方式：把固定 Release 链接交给 Agent

正式发布后，把下面内容复制给 Codex、Claude Code、Cursor、GitHub Copilot 或其他支持 Agent Skills 的宿主：

```text
请检查并安装这个 Skill：

https://github.com/KelvinWu/hk-pre-owned-rolex-monitoring/tree/v0.1.1/skills/hk-pre-owned-rolex-monitoring

要求：

1. 先读取 SKILL.md 和仓库 README.md，检查来源与安装要求；
2. 告诉我准备写入的 Skill 目录、运行环境和文件；
3. 不使用 sudo，不覆盖其他 Skill，不把用户状态放进 Skill 安装目录；
4. 生产环境使用该 Release 附带的 wheel 和 SHA256SUMS.txt，不使用 pip install -e；
5. 安装前检查真实依赖下载、安装权限和命令 PATH；不能用 pypi.org 首页可访问代替包下载验证；
6. 默认包源超时时，只使用我或宿主配置的可信 PIP_INDEX_URL，不静默选择第三方镜像；
7. 优先使用持久位置的独立虚拟环境；无法使用时才回退用户目录，不提升系统权限；
8. 安装后运行 inventoryctl skill info --json 和 inventoryctl runtime probe --json；
9. 告诉我实际使用的 Python、安装模式、入口路径、状态目录和结构化验收结果。
```

这个方案是“发布和分发”，不是托管服务。代码保存在 GitHub；Skill 安装和执行发生在使用者自己的 Agent 环境中。本项目不要求维护者提供公共服务器。

## 安装验收

Agent 完成安装后，至少应返回两份结构化 JSON：

```bash
inventoryctl skill info --json
inventoryctl runtime probe --json
```

验收时确认：

- `skill.info` 返回正确名称、版本和 `platform_neutral=true`；
- `runtime probe` 只证明当前目录可写，不等于已经验证跨重启持久；
- Skill 安装目录只保存代码；数据库、图片、备份和运行锁位于独立 `state-dir`；
- 没有请求或打印 Cookie、Token、API Key、真实通知标识或私人状态。

## Bootstrap

从 `0.1.1` 开始，Skill 包内提供一个不依赖 `httpx`、`pydantic`、`PyYAML` 或 `platformdirs` 的预安装入口：

```bash
python scripts/bootstrap.py doctor \
  --network-check download \
  --runtime-dir /persistent/runtime/venv \
  --state-dir /persistent/state \
  --json

python scripts/bootstrap.py install \
  --package /downloads/hk_pre_owned_rolex_monitoring-<version>-py3-none-any.whl \
  --sha256 <SHA-256> \
  --runtime-dir /persistent/runtime/venv \
  --state-dir /persistent/state \
  --json
```

`doctor` 真实下载声明的依赖 wheel，并区分默认源超时、已配置镜像超时、DNS、TLS、平台无可用依赖和权限错误。镜像仅从宿主环境的 `PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL` 读取，输出时只保留 origin。只有 `INSTALL_VERIFIED` 才代表安装和运行入口已经验证。

生产安装固定使用 `v0.1.1` Release 的 wheel 和 `SHA256SUMS.txt`；旧版可回滚到 `v0.1.0`。

## 宿主兼容性

| 宿主 | 常见 Skill 目录 | 当前验证边界 |
|---|---|---|
| Codex | `~/.codex/skills/hk-pre-owned-rolex-monitoring/` | 结构与 CLI 验证 |
| Claude Code | `.claude/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| VS Code / Copilot | `.agents/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Cursor | `.cursor/skills/hk-pre-owned-rolex-monitoring/` | 结构验证 |
| Windsurf | 从仓库或 Skill 目录调用 CLI | 原生发现路径未验证 |
| Generic Shell | 任意目录安装 Python 包 | CLI 验证 |

“结构验证”不等于已在对应产品 UI 中完成发现、启用和交互演练。完整边界见 [`references/host-compatibility.md`](skills/hk-pre-owned-rolex-monitoring/references/host-compatibility.md)。

## 本地开发验证

最低环境为 Python 3.11。开发者可以在仓库根目录运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './skills/hk-pre-owned-rolex-monitoring[test]'
.venv/bin/pytest -q skills/hk-pre-owned-rolex-monitoring/tests
.venv/bin/inventoryctl skill info --json
```

macOS/Linux 示例使用 `.venv/bin/`；Windows 请使用虚拟环境中对应的 Python 和命令入口。

## 首次使用

1. 运行 `inventoryctl market sources --json`，了解来源状态和接入方式。
2. 复制并填写 `assets/templates/orientalwatch-rolex-cpo.yaml`，不要把用户配置提交到仓库。
3. 为 `--state-dir` 或 `INVENTORY_SENTINEL_HOME` 选择跨任务持久目录。
4. 运行 `monitor create`，再使用两份一致的成功快照建立基线。
5. 生成 Runtime Plan；定时和通知由宿主执行，Skill 不伪造任务 ID 或发送结果。

完整操作约定见 [`SKILL.md`](skills/hk-pre-owned-rolex-monitoring/SKILL.md) 和 [`references/skill-contract.md`](skills/hk-pre-owned-rolex-monitoring/references/skill-contract.md)。

## 行情来源与 Secret

WatchCharts 自动调用只使用用户自己的凭证：

```text
WATCHCHARTS_API_KEY
WATCHCHARTS_LICENSE
```

Secret 只能由使用者放入自己的环境变量或 Secret Manager，不得进入命令参数、GitHub、JSON 输出、状态或备份。Wristcheck、Chrono24 和其他尚未确认自动化权限的来源默认只接受人工证据或授权导出。完整门禁见 [`references/source-access-policy.md`](skills/hk-pre-owned-rolex-monitoring/references/source-access-policy.md)。

## 更新、备份和卸载

- 更新时把新 Release 的固定目录链接交给当前 Agent，让它先定位正在加载的 Skill，再覆盖同一目录。
- 更新前运行 `monitor backup`；安装新版本后重新运行 `skill info`、`runtime probe` 和 `monitor doctor`。
- Skill 代码与用户状态分离；覆盖或删除 Skill 目录不得删除用户状态。
- 卸载代码前先确认是否保留数据库、图片和备份。删除用户状态必须是单独、明确的操作。
- 正式 Release 必须提供回滚目标 tag，不使用漂移的 `main` 作为生产安装源。

## 安全与限制

- 不绕过 CAPTCHA、登录、访问控制、地区限制或来源条款。
- `401`、`403`、`429`、验证页或来源 Schema 变化必须失败关闭。
- 不提交真实快照、付费原始数据、下载图片、Cookie、Token、用户状态或未脱敏日志。
- 市场比较是带证据的价格位置说明，不是投资建议、买卖建议或收益承诺。
- 来源政策和 API 能力会变化；发布或升级 Adapter 前必须重新复核。

安全问题请按 [`SECURITY.md`](SECURITY.md) 报告。贡献约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 仓库结构

```text
skills/hk-pre-owned-rolex-monitoring/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
├── references/
├── assets/
├── src/
└── tests/
```

仓库级 README、CI、Release 和贡献文档服务于人类发布与分发；Skill 目录本身只保留 Agent 执行所需的内容。

## License

本项目采用 [MIT License](LICENSE)，允许使用、复制、修改和再分发，但必须保留版权与许可声明。软件按“原样”提供，不附带担保。
