# Skill 与 CLI 契约

## CLI 原则

- 所有操作均输出单个 JSON 对象；`--json` 为显式兼容参数，省略时仍输出 JSON。
- 宿主必须读取 `ok`、`status`、`state_modified` 和 `error.code`，不得解析日志文本。
- 退出码：`0` 成功或幂等跳过；`2` 不可信数据；`3` 配置错误；`4` 网络、存储或内部错误。

## 统一结果字段

`schema_version`、`ok`、`operation`、`status`、`skill_version`、`monitor_id`、`run_id`、`state_modified`、`result`、`warnings`、`error`、`next_actions`。

`next_actions` 是带条件的机器可读建议，每项包含 `action`、命令数组 `command` 和 `condition`。宿主不能把建议等同于已经执行，也不能跳过需要用户确认或宿主能力验证的条件。

主要状态：

- `BASELINE_CREATED`：可信基线已创建，未产生业务 Diff。
- `CHANGED`：变化已确认并原子提交。
- `NO_CHANGE`：当前可信快照与上一成功快照一致。
- `SKIPPED_DUPLICATE`：同一 monitor、日期和 trigger 已完成。
- `INVALID`：本次数据不可信，成功基线保留。
- `ERROR`：配置、网络、存储或内部操作失败。

## 面向用户的腕表身份

`stable_id` 是系统去重和审计字段。宿主不得只把它显示为“商品编号”。每条 `added`、`removed`、`modified` 和市场对比结果都必须包含 `product_identity`：

- `product_name`：东方表行返回的系列或商品名称；
- `rolex_reference`：Rolex 型号编号，例如 `124060`；
- `oriental_lot_number`：东方表行 `Lot_Number_Code`，也是当前 Adapter 的 stable ID；
- `year`、`diameter`、`material`、`bracelet`：站点存在时保留；
- `detail_url`：具体商品详情页；
- `display_name`：供人直接识别的完整名称。

`monitor run` 的 `result.human_summary_zh` 包含一行总览和逐只腕表的中文变化说明。改价必须写成“商品名称 + Rolex 型号 + 东方表行货号 + 原价 → 新价 + 金额/百分比”，不能只输出内部 ID。Outbox 每个变化事件也必须携带相同的 `product_identity` 和 `human_summary_zh`。

## 图片缓存输出

`monitor baseline` 和 `monitor run` 的 `result.image_cache` 返回 `enabled`、`cache_root`、`items_considered`、`attempted`、`available`、`downloaded`、`reused`、`failed` 和 `without_image_url`。

每条 `added`、`removed`、`modified` 及对应 Outbox change 都包含：

- `cache_status`：本次或历史缓存状态；
- `original_image_url`：网站原始图片地址；
- `cached_image_path`：当前运行环境中的绝对文件路径；
- `content_type`：已校验的图片类型；
- `attachment_ready`：是否可以安全读取为通知附件。
- `sha256`、`byte_size`、`etag`、`last_modified`、`cached_at`：缓存完整性与复用元数据。

宿主不得只看到非空路径就假设文件可用，必须检查 `attachment_ready=true`。商品下架后使用 `AVAILABLE_HISTORICAL`；若为 `FAILED`、`MISSING`、`NO_IMAGE_URL` 或 `DISABLED`，发送无图通知并保留原因。

## 稳定命令

入口与参数以 `inventoryctl --help` 为准。发布后的命令名不得无迁移策略地修改。

历史和报告命令：

```text
inventoryctl monitor list --json
inventoryctl monitor history --id <monitor-id> [--date YYYY-MM-DD] [--limit 50] --json
inventoryctl monitor show-run --run-id <run-id> --json
inventoryctl report build --run-id <run-id> [--market-packet <file>] --json
```

`monitor history --date` 使用 Monitor 配置时区下保存的 `local_date`。`show-run` 和 `report build` 读取已保存运行，不重新访问网站。组合报告的 `user_report_zh.text` 可直接交付用户，附件仍须检查 `attachment_ready=true`。

行情命令：

```text
inventoryctl market sources --json
inventoryctl market source doctor --source <source> --mode <automatic|manual> --usage <internal|public_display|resale> --json
inventoryctl market collect --source watchcharts --reference <reference> --target-year <year> --region <APAC|GLOBAL> --completeness <full_set|watch_only> --usage <internal|public_display|resale> [--license <type>] [--output <file>] --json
inventoryctl market packet init --output <packet> --packet-id <id> --as-of <ISO-8601> --json
inventoryctl market packet add --file <packet> ... --json
inventoryctl market packet import-csv --file <packet> --csv <authorized-export.csv> [--source <source>] --json
inventoryctl market packet attach-evidence --file <packet> --observation-id <id> --evidence-file <file> --verified-at <ISO-8601> --json
inventoryctl market packet finalize --file <packet> --json
inventoryctl market packet validate --file <market-packet> --json
inventoryctl market compare --id <monitor-id> --file <market-packet> --json
inventoryctl market compare --run-id <run-id> --file <market-packet> --json
inventoryctl market compare --event-id <event-id> --file <market-packet> --json
```

`market source doctor` 不访问网络；它检查注册表、凭证存在性和用户 license 声明，返回 `result.source_status`。`market collect` 当前只实现 WatchCharts 正式 API；无凭证、license 不足、API 限流或响应结构变化均返回结构化错误。API key 只从 `WATCHCHARTS_API_KEY` 读取，不得出现在 JSON。

`market packet validate` 和 `finalize` 只校验 Packet 结构、证据状态和核验声明，不证明网页、导出内容或 license 声明真实。`market compare --id` 读取最新成功快照；`--run-id` 读取该次变化中的商品，包含下架商品；`--event-id` 只比较一个 Outbox 事件。三种模式都不修改 SQLite 库存基线。

## 通知送达回执

宿主发送成功后执行：

```text
inventoryctl outbox ack --event-id <id> --provider <provider> --external-message-id <id> --delivered-at <ISO-8601> --verified --json
```

没有外部消息 ID 或未重新查询宿主状态时，只能记为 `sent_unverified`。失败写入 `delivery_error` 并保留重试资格；相同已验证回执再次提交返回 `SKIPPED_DUPLICATE`。

来源错误码：`SOURCE_AUTH_REQUIRED`、`SOURCE_LICENSE_NOT_CONFIRMED`、`SOURCE_AUTOMATION_PROHIBITED`、`SOURCE_TERMS_REVIEW_REQUIRED`、`SOURCE_POLICY_STALE`、`SOURCE_RATE_LIMITED`、`SOURCE_API_ACCESS_DENIED`、`SOURCE_SCHEMA_CHANGED`。
