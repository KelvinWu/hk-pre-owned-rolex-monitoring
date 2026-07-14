# 行情来源接入政策

## 目的

本文件定义 Skill 在取得二手 Rolex 行情前必须执行的来源检查。网页公开可见、技术上可请求、允许自动采集、允许保存、允许向第三方展示是不同问题；任何一项未确认都不能被描述成“已授权自动来源”。本政策是工程门禁，不替代安装者自己的法律或合同判断。

## 机器可读入口

```text
inventoryctl market sources --json
inventoryctl market source doctor --source <source> --mode <automatic|manual> --usage <internal|public_display|resale> --json
```

`market sources` 返回 `automation_status`、`adapter_status`、凭证环境变量名、license 环境变量名、条款 URL、`checked_at`、`review_due_at`、速率与存储边界。它永远不返回 Secret 值。

`source doctor` 不发起网络请求、不消耗 API credits，也不证明用户输入的 license 声明真实。它只判断当前来源政策、凭证存在性和用户声明的用途是否满足运行前提。

## 自动化状态

- `SUPPORTED_WITH_USER_CREDENTIALS`：存在正式接口；用户仍须提供自己的凭证和足够 license。
- `PROHIBITED_WITHOUT_WRITTEN_PERMISSION`：官方条款要求自动化访问取得明确许可；默认不得写网页抓取 Adapter。
- `TERMS_REVIEW_REQUIRED`：尚未确认自动化权限；只能使用人工证据或授权导出。
- `PUBLIC_RELEASE_REVIEW_REQUIRED`：技术 Adapter 已存在，但在公共发布和无人值守调度前仍须完成来源政策审查。
- `MANUAL_ONLY`：来源类别过宽或没有统一政策，只接受具体人工证据。

## 诊断状态

- `SOURCE_READY`：就注册表检查而言可以进入自动调用；不代表远端 API 一定成功。
- `MANUAL_EVIDENCE_READY`：可以创建人工证据，但不得据此切换为自动抓取。
- `SOURCE_AUTH_REQUIRED`：缺少正式接口所需凭证。
- `SOURCE_LICENSE_NOT_CONFIRMED`：缺少 license 声明，或声明不足以覆盖 `public_display` / `resale`。
- `SOURCE_AUTOMATION_PROHIBITED`：默认自动访问被来源政策阻止。
- `SOURCE_TERMS_REVIEW_REQUIRED`：来源尚未完成自动化条款审查。
- `SOURCE_POLICY_STALE`：距离 `checked_at` 已超过 90 天；自动访问失败关闭，必须重新核验官方条款并更新注册表。
- `SOURCE_RATE_LIMITED`：正式 API 达到频率或 credits 限制。
- `SOURCE_API_ACCESS_DENIED`：正式 API 拒绝访问；检查 key、订阅级别和 credits。
- `SOURCE_SCHEMA_CHANGED`：正式接口结构不符合已验证契约，结果不得进入 Market Packet。

## 当前来源矩阵

### WatchCharts

- 接入方式：正式 API。
- 自动化状态：`SUPPORTED_WITH_USER_CREDENTIALS`。
- 凭证：`WATCHCHARTS_API_KEY`。
- license 声明：`WATCHCHARTS_LICENSE=internal|distribution|resale`。
- 官方 API 文档说明请求使用 API key、data credits，并限制每个 key 的请求速率；官方 license 页面区分内部使用、分发和再销售。
- `internal` 不能通过本 Skill 自动升级为公开展示许可；`public_display` 至少声明 `distribution`，`resale` 必须声明 `resale`。
- 条款与能力来源：[API Getting Started](https://watchcharts.com/api)、[API Documentation](https://watchcharts.com/api/documentation)、[License Types](https://watchcharts.com/api/license)。

当前采集器调用 exact-reference 搜索和型号级 `watch/appraisal`，请求 HKD、used、附件状态以及 APAC 或 GLOBAL 地区。该 appraisal 不接收腕表生产年份：输出 observation 的 `year` 必须为 `null`，只作型号级背景，不能冒充目标年份或进入年份窗口参考价。

示例：

```text
export WATCHCHARTS_API_KEY=<user-owned-key>
export WATCHCHARTS_LICENSE=internal
inventoryctl market source doctor --source watchcharts --mode automatic --usage internal --json
inventoryctl market collect --source watchcharts --reference 126334 --target-year 2021 --region APAC --completeness full_set --usage internal --output ./watchcharts-126334.json --json
```

API key 不得出现在命令参数、日志、Market Packet、备份或 GitHub。`WATCHCHARTS_LICENSE` 是安装者声明，不是 Skill 对合同权限的保证。

### Wristcheck

- 自动化状态：`PROHIBITED_WITHOUT_WRITTEN_PERMISSION`。
- 官方条款限制未经明确许可使用 robot、spider、scraper 或其他自动方式监控、复制平台内容。
- 当前只接受 `manual_snapshot`、`manual_url` 或 `authorized_export`；取得可验证书面许可前不实现自动 Adapter。
- 条款来源：[Wristcheck Terms and Conditions](https://wristcheck.com/terms-and-conditions)。

### Chrono24

- 自动化状态：`TERMS_REVIEW_REQUIRED`。
- 当前未确认适用于本 Skill 的公开市场数据 API。
- 官方 Legal Notice 对数据库存储、发布、商业使用和第三方披露设置许可边界；当前只接受人工估值证据或授权导出。
- 来源：[Chrono24 Legal Notice](https://about.chrono24.com/en/imprint)、[Chrono24 Valuation](https://www.chrono24.com/info/valuation.htm)。

### 香港商户、拍卖和大陆平台

28Watches、Ken's Watches、Watchfinder Hong Kong、拍卖结果以及大陆平台在当前版本中只支持人工证据。每个未来 Adapter 必须单独记录正式接口或书面许可、条款 URL、核验日期、频率、存储和再分发边界，不能因为同属“公开网页”而共享许可结论。

## 东方表行库存 Adapter 的发布边界

东方表行是库存来源，不计入独立市场参考源。当前 Adapter 已完成技术与 Fixture 验证，但公开发布授权仍标记为待复核：官方条款包含个人、非商业使用及知识产权限制。低频、缓存和不绕过 CAPTCHA 是技术安全措施，不等于取得许可。

在完成发布审查前：

- 不宣称该 Adapter 得到东方表行授权或认可；
- 不绕过登录、CAPTCHA、访问控制或地区限制；
- 收到 `401`、`403`、`429` 或验证页时停止并返回结构化错误；
- 不把原始接口数据或图片打包进 GitHub；
- 若公开自动运行不适合，改用用户主动导出、用户触发的单次读取、官方提醒或书面许可 feed。

官方条款来源：[Oriental Watch Terms and Conditions](https://www.orientalwatch.com/owh/article.aspx?id=50038&lang=eng)。

## 更新规则

来源条款和 API 能力会变化。任何 Adapter 发布或升级时必须：

1. 重新读取官方条款和接口文档；
2. 更新注册表中的 `checked_at` 与 `review_status`；
3. 先补 Fixture 和错误状态测试；
4. 禁止状态变化时默认失败关闭；
5. 不把 Secret、付费原始数据或未经许可的真实快照提交到仓库。
