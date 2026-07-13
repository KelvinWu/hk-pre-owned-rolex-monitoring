# 贡献指南

感谢参与 HK Pre-owned Rolex Monitoring。所有面向人的 Issue、PR 和文档默认使用中文；代码、命令、配置键和 API 名称保持原生形式。

## 开发原则

- 核心逻辑保持平台中立，不导入 Codex、Claude Code、QClaw、Cursor 或其他宿主私有模块。
- stable ID、基线、Diff、INVALID 保护和 Outbox 幂等只在确定性代码中实现，不复制到宿主提示词。
- 新 Bug 必须先补失败测试。
- 默认使用脱敏 Fixture；不要为普通 PR 频繁请求真实网站。
- INVALID、空结果、重复或部分抓取不得覆盖上一份成功基线。
- CLI 输出必须是结构化 JSON；状态变更必须可审计。
- 不提交 Secret、Cookie、用户状态、真实通知标识、下载图片或未脱敏日志。

## 本地验证

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './skills/hk-pre-owned-rolex-monitoring[test]'
.venv/bin/pytest -q skills/hk-pre-owned-rolex-monitoring/tests
.venv/bin/python -m compileall -q skills/hk-pre-owned-rolex-monitoring/src
```

如果本地安装了 `skills-ref`，同时运行：

```bash
.venv/bin/agentskills validate skills/hk-pre-owned-rolex-monitoring
```

## 来源与 Adapter 变更

新增或修改来源前必须：

1. 读取官方接口和条款；
2. 更新来源注册表的状态、URL、核验日期、速率和存储边界；
3. 先补 Fixture 与错误状态测试；
4. 对禁止或待审查状态默认失败关闭；
5. 不提交真实凭证、付费原始数据或未经许可的快照。

技术上可请求不等于允许自动化、保存、公开展示或再销售。PR 必须明确说明其许可边界，不能只说明“网页公开可见”。

## Pull Request 要求

- 说明变更目的和用户可见影响；
- 列出新增或修改的测试；
- 附上实际运行命令和结果；
- 明确是否触及数据库、备份、图片、Outbox、来源政策或宿主兼容性；
- 不把设计目标写成已验证执行结果；
- 不声称未实测宿主已经兼容。

正式 Release 前还必须通过固定 tag 的 clean-install 和 Release 包内容检查。
