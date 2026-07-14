# Changelog

本项目遵循语义化版本。正式 Release 的变更记录以 GitHub Release 和本文件为准。

## [0.2.0] - 2026-07-14

### Added

- 增加 `monitor init`、`monitor list`、`monitor history` 和 `monitor show-run`，新会话可发现现有 Monitor 并按日期或 `run_id` 回放历史。
- 增加 `report build`，把库存变化、具体腕表身份、历史图片和可选行业行情组成可直接交付用户的中文报告。
- 行情比较支持 `--run-id` 与 `--event-id`，下架商品也能使用当时保存的商品资料进行事后比较。
- 增加 Market Packet 的 `init`、`add`、`import-csv`、`attach-evidence` 和 `finalize` 构建流程。
- 增加 `skill self-test`，在临时状态目录用 Fixture 验证基线、无变化、变化、INVALID、Outbox 和数据库完整性，不访问真实网站。
- 所有 CLI JSON 增加机器可读的 `next_actions`。

### Changed

- `SKILL.md` 按用户意图路由，拆分“核心不变量”和由真实失败积累的 `Gotchas`；安装与修复降为条件式能力。
- `agents/openai.yaml` 不再强迫每次库存运行都进入行情来源检查。
- SQLite 状态 Schema 升至 v2，保存运行本地日期和通知 provider、外部消息 ID、送达时间、核验状态与错误。
- 行情来源注册表升至 v3，增加政策复核到期日；过期自动访问返回 `SOURCE_POLICY_STALE` 并失败关闭。
- 图片缓存保存 SHA-256、大小、ETag、Last-Modified 和缓存时间；已校验文件直接复用，避免每次全量下载。
- Runtime Plan 明确消费 Manifest 中的 `retry_delays_seconds`，通知确认命令要求真实送达回执。

### Compatibility

- 版本号升至 `0.2.0`；现有 `monitor run --id ...`、`market compare --id ...` 和旧 JSON 主字段保持兼容。
- `outbox ack` 仍可无回执调用，但只记录为 `sent_unverified`；只有带外部消息 ID 且 `--verified` 才记录为已验证送达。
- 正式发布固定使用 `v0.2.0` tag、Release wheel 和 SHA-256；发布流程必须通过 clean-install 验证。

## [0.1.1] - 2026-07-14

### Added

- 增加纯标准库 `bootstrap.py`，在业务依赖安装前检查 Python、pip、实际依赖下载、安装权限、PATH 和状态目录。
- 增加虚拟环境优先、用户目录回退的结构化安装流程，并在完成后验证 `skill info` 与可选的 `runtime probe`。
- 增加本地 wheel SHA-256 校验、镜像地址脱敏和稳定的 `python -m inventory_sentinel` 回退入口。

### Changed

- 区分默认源超时、配置镜像超时、DNS、TLS、依赖不可用和安装权限错误，不再用包索引首页访问结果代替真实下载检查。
- 生产安装改为固定 Release wheel，不使用 editable install；正式版本为 `0.1.1`。

## [0.1.0] - 2026-07-13

### Added

- 平台中立的 `hk-pre-owned-rolex-monitoring` Agent Skill。
- 东方表行 Rolex CPO Fixture Adapter 与低频只读实站 Adapter。
- 双样本基线、变化确认、INVALID 保护、运行锁、Outbox、备份和恢复。
- 商品图片缓存与下架历史图片保留。
- Market Packet、来源政策注册表、来源诊断和 WatchCharts 用户凭证模式。
- Codex、Claude Code、VS Code / Copilot、Cursor 与 Generic Shell 的安装边界说明。
- 首发候选版本 `0.1.0` 与 MIT License。

### Known boundaries

- 项目封面、图标和运行效果图将在后续版本补充，不影响当前 CLI 与 Agent Skill 安装。
- 东方表行 Adapter 为非官方实现；公开代码与 MIT License 不代表来源方授权自动访问、保存或再分发其内容。
- 当前未在全部宿主产品 UI 中逐一完成发现与交互演练；未实测的宿主只声明结构兼容。
