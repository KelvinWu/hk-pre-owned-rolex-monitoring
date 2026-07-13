# Changelog

本项目遵循语义化版本。正式 Release 的变更记录以 GitHub Release 和本文件为准。

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
