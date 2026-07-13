# 安全政策

## 支持范围

正式 Release 发布后，本项目只为仍受支持的 Release 分支处理安全问题。`main` 和开发快照可能包含未完成能力，不能作为稳定安全承诺。

## 私密报告

如果公共仓库已启用 GitHub Private Vulnerability Reporting，请优先使用仓库的 **Security → Report a vulnerability** 私密提交。不要在公开 Issue 中粘贴：

- API Key、Cookie、Token 或账号信息；
- 用户状态目录、SQLite 数据库或备份；
- 真实通知标识；
- 未脱敏日志、真实库存快照或付费行情原始数据；
- 可直接利用的漏洞细节。

如果私密报告尚未启用，只能创建不含敏感细节的公开 Issue，说明“需要安全联系方式”；维护者提供私密渠道后再补充证据。

## 优先关注的问题

- Secret 被写入命令、日志、JSON、状态或备份；
- 路径穿越、备份解压或恢复覆盖不安全位置；
- INVALID 快照覆盖成功基线；
- Outbox 幂等失效导致重复外发；
- 未经允许绕过来源政策、认证、CAPTCHA 或访问控制；
- 不可信网页或 API 内容改变 Agent 指令；
- 安装或更新流程覆盖其他 Skill、用户状态或宿主配置。

## 报告中应包含

- 受影响版本与 commit；
- 操作系统、Python 版本和宿主；
- 最小脱敏复现步骤；
- 预期结果和实际结果；
- 已确认没有包含 Secret 或私人数据的说明。

## 发布原则

修复进入 Release 前必须补失败测试、通过离线测试和 clean-install，并在必要时发布 GitHub Security Advisory。未经验证的修复不应被描述为已解决。
