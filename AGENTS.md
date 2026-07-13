# HK Pre-owned Rolex Monitoring 项目规则

- 所有面向人的文件和说明默认使用中文；命令、路径、配置键和 API 名称保持原生形式。
- 先阅读 `PROJECT_OBJECTIVES.md` 和 `skills/hk-pre-owned-rolex-monitoring/SKILL.md`。
- 核心逻辑必须平台中立，不得导入 QClaw、Codex、Claude Code、Cursor 或其他宿主私有模块。
- 不得把 stable ID、基线、Diff、INVALID 保护或通知幂等复制到宿主提示词。
- 任何 INVALID 快照不得覆盖上一份成功基线。
- 新 Bug 必须先补失败测试；默认测试使用脱敏 Fixture，不频繁请求真实网站。
- CLI 必须输出结构化 JSON；状态变更必须可审计。
- 不得提交 Secret、Cookie、用户状态、真实通知标识或未脱敏日志。
- 发布前必须执行 clean-install；未实际验证的宿主不得声称兼容已实测。
