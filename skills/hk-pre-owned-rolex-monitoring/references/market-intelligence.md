# 二手 Rolex 市场情报契约

## 目的

把东方表行 Rolex CPO 的公开要价放进香港、亚太和全球二手市场语境，同时保留每条数据的来源、时间、地区、价格口径、成色和附件条件。市场参考是解释层，不是库存事实，也不是投资建议。

## 来源分级

每次接入前先读取 `source-access-policy.md`，并使用 `market source doctor`。来源等级描述数据用途，不能替代访问、保存或分发许可。

### Tier A：模型估值、交易指数或可核验成交

- [WatchCharts API](https://watchcharts.com/api/documentation)：正式 API，可返回型号市场价格、经销商价格、波动率和挂牌中位数；需要用户自己的 API key、credits 和足够 license。当前自动采集的 appraisal 不含生产年份，只作型号级背景，不能进入年份窗口参考价。
- [Chrono24 Valuation](https://www.chrono24.com/info/valuation.htm)：全球平台估值、平均价和区间；主要基于可比平台数据，不要自动称为最终成交价。
- [ChronoPulse](https://about.chrono24.com/en/press/chrono24-unveils-chronopulse-the-first-luxury-watch-market-index-founded-on-real-transaction-data-as-it-celebrates-20-years)：基于 Chrono24 交易数据的市场/品牌指数，适合判断大盘和品牌趋势，不替代单表 exact-reference 对比。
- [Wristcheck Watch Index](https://wristcheck.com/us/about-us)：Wristcheck 声明其指数由实时交易数据驱动；其条款同时说明可能包含假定流动价格，录入时必须保留原始口径。
- 香港拍卖成交：仅在 Rolex reference、年代、成色、附件、币种和买家佣金口径可比时使用。

### Tier B：香港及专业平台挂牌/报价

- [Wristcheck Hong Kong](https://wristcheck.com/us/store/hong-kong)：香港本地、经认证和评级的挂牌样本。
- [28Watches](https://en.28watches.com/)：香港实体商户挂牌或报价。
- [Ken's Watches](https://kenwatches.com/aboutUs)：香港多店二手名表挂牌或报价。
- [Watchfinder Hong Kong](https://www.watchfinder.hk/)：专业二手平台的香港挂牌价格。

Tier B 反映买方当下可见要价，不等于成交价。议价空间、保修、认证、税费和商户利润可能造成溢价。

### Tier C：大陆个人平台或其他未统一来源

大陆个人/综合平台的真实性、成色、附件、税费、是否真实成交和重复发布难以统一。此类样本以 `mainland-marketplace` 或 `other` 录入，只作上下文；无论数量多少，都不能单独形成 `VERIFIED` 参考。

## Market Packet 必填信息

优先使用 CLI 构建 Packet，不要让 Agent 手工拼整份 JSON：

```text
market packet init → add 或 import-csv → attach-evidence → finalize
```

`import-csv` 只接受本协议字段名的授权导出或人工整理表。`attach-evidence` 对本地证据文件计算 SHA-256 并把 observation 标记为 `verified`；这代表使用者完成了证据核验，不代表 Skill 自动证明来源内容或许可。`finalize` 前允许 observations 为空，finalize 后必须满足完整 Market Packet Schema。

每条 observation 必须包含：

- 唯一 `observation_id`；
- 来源和可选的来源 listing ID；
- 精确 Rolex reference；
- `HK`、`MAINLAND_CN`、`APAC` 或 `GLOBAL` 地区；
- `market_estimate`、`transaction_index`、`asking_price`、`auction_result` 或 `dealer_quote` 价格口径；
- 已换算的 `price_hkd`；
- 带时区的 `observed_at`；
- 该行情对应腕表的年份；未知年份必须显式写 `null`，且不能进入年份窗口参考价；
- 成色、附件状态；成色可以是 `unknown`，但必须显式提供；
- `evidence_url` 或人工证据说明。

为了区分“有文字”和“已核验”，同时记录：

- `evidence_status`：`fixture`、`unverified` 或 `verified`；
- `acquisition_method`：`official_api`、`authorized_export`、`manual_url`、`manual_snapshot` 或 `fixture`；
- `evidence_verified_at`：已验证证据的核验时间；
- `evidence_sha256`：已保存证据响应、导出文件或快照的 SHA-256；
- `independence_group`：数据真正所属的独立来源；同一 Dealer 跨平台发布时使用同一值；
- `underlying_listing_id`：可识别同一底层挂牌的 ID，用于跨平台去重。

`verified` 必须同时提供 `evidence_verified_at` 和 `evidence_sha256`。这是上游证据核验声明，不表示 Skill 凭空证明网页内容；使用 `market packet validate` 时仍要区分“契约有效”和“商业事实真实”。

不得让 Skill 猜测汇率。不同币种必须在生成 Market Packet 时换算成 HKD，并在证据说明中保留汇率来源和时间。

## 聚合规则

1. 仅匹配完全相同的规范化 Rolex reference。
2. 目标库存必须有年份；没有年份时返回 `TARGET_YEAR_UNKNOWN`，不得形成已验证参考价。
3. 使用 `comparison.year_window` 过滤年份，默认值为 2。例如目标为 2021 年时，只纳入 2019–2023 年；范围外及年份未知的行情只保留为不可比证据。
4. 排除超过 `max_age_days` 的样本和明显晚于 packet `as_of` 的样本。
5. `fixture`、`unverified` 和 Tier C 不进入已验证参考价计算。
6. 用 `underlying_listing_id` 排除跨平台重复挂牌，并用 `independence_group` 确保同一真实数据来源只计一个独立来源。
7. 在每个 Tier A/B 独立来源内部优先选择 `excellent`、`very_good`；若没有，才使用 `good` 或 `unknown` 并返回 `CONDITION_FALLBACK_USED`。`unworn` 只作价格上界背景；`fair` 不进入参考价。
8. 把香港、亚太、全球和大陆地区与 `ASKING`、`VALUATION`、`AUCTION` 口径组合成独立 `reference_cohorts`；不得跨 cohort 混合求均值。
9. 每个独立来源先按年份计算算术均值，再对各年份均价计算算术均值，最后对同 cohort 的独立来源均价求均值。
10. 单个价格偏离来源中位数达 `outlier_warning_percent`（默认 30%）时返回 `OUTLIER_PRICE_DETECTED`；只打标，不在没有审核的情况下自动删除。
11. 同一 cohort 至少达到 `minimum_independent_sources`（默认 2）才返回 `VERIFIED`。两个不同 cohort 各有一个来源不得凑成两个来源。
12. 三个以上独立来源、至少一个 Tier A 且主 cohort 为香港/亚太时，置信度才可为 `HIGH`。
13. 附件、税费和其他可比性不一致时保留 `comparability_flags`，不得静默调整。

## 输出解释

- `comparison_key`：实际使用的 Rolex reference、目标年份和年份窗口。
- `analysis_status`：整份结果是 `FULLY_VERIFIED`、`PARTIALLY_VERIFIED`、`DEMO_ONLY`、`UNVERIFIED_EVIDENCE` 或 `INSUFFICIENT_EVIDENCE`。
- `reference_cohorts`：按地区与价格口径分开的参考组。
- `primary_cohort_id`：实际用于与东方表行挂牌价比较的 cohort，优先香港 `ASKING`。
- `reference_price_hkd`：主 cohort 内各独立来源年份平衡均价再次求均值，不是保证成交价。
- `reference_low_hkd` / `reference_high_hkd`：各来源均价范围。
- `aggregation_method=SOURCE_YEAR_BALANCED_MEAN`：先来源内按年份均值，再跨年份和跨独立来源均值。
- `condition_policy=PREFER_EXCELLENT_VERY_GOOD_PER_SOURCE`：成色用于独立来源内优先级，而不是目标腕表的硬性匹配 key。
- `target_premium_percent`：东方表行价格相对来源平衡参考价的差异。
- `price_basis=HK_ASKING` 等值：主 cohort 的地区和价格口径；`NO_REFERENCE_DATA` 表示没有同 cohort 达到门槛。
- `BELOW_REFERENCE` / `WITHIN_REFERENCE_BAND` / `ABOVE_REFERENCE`：相对位置，不是购买建议。

选择范围由 `result.selection.mode` 明确记录：

- `latest_snapshot`：比较当前成功库存；
- `run_changes`：比较指定 run 的上新、下架和改价商品，适合“昨天的结果”；
- `outbox_event`：只比较一个通知事件。

市场对比命令只读成功库存快照，不写快照、Diff 或 Outbox。行情失败或证据不足时，库存监控仍按原流程运行。
