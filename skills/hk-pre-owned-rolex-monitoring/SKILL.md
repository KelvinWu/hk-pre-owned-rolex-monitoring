---
name: hk-pre-owned-rolex-monitoring
description: Monitor Oriental Watch Hong Kong Rolex Certified Pre-Owned listings with verified baselines keyed by Lot_Number_Code; retain listing images for delisting alerts; detect new, removed, price, and detail changes; and compare exact Rolex references plus nearby production years with attested market evidence. Preflight sources, use WatchCharts only with user-owned API credentials and sufficient license, and keep prohibited or unreviewed sources in manual-evidence mode. Use for running or diagnosing this Hong Kong Rolex CPO monitor, image retention, source readiness, Market Packet validation or comparison, Outbox events, backup or restore, and host-neutral runtime plans.
---

# HK Pre-owned Rolex Monitoring

监控香港东方表行公开的 Rolex Certified Pre-Owned（CPO）库存，并用有证据的香港、亚太、大陆和全球二手行情解释价格位置。库存事实与市场参考必须分开报告。所有确定性操作均通过 `scripts/inventoryctl.py` 完成；不要在对话或宿主提示词中重新实现 stable ID、基线、Diff、INVALID 保护、行情聚合、状态提交或通知去重。

## 开始

1. 运行 `python scripts/inventoryctl.py skill info --json` 和 `python scripts/inventoryctl.py runtime probe --json`。
2. 需要行情对比时，先运行 `python scripts/inventoryctl.py market sources --json`，再对目标来源运行 `market source doctor`。
3. 根据用户意图选择 monitor、market、outbox、backup、restore 或 runtime 操作。
4. 只依据 CLI JSON、行情证据和已验证的宿主结果报告状态。

## 创建监控

1. 读取 `references/skill-contract.md`、`references/adapter-contract.md` 和 `references/state-model.md`。
2. 从 `assets/templates/orientalwatch-rolex-cpo.yaml` 复制配置，在 Skill 安装目录之外准备用户 Manifest。
3. 运行 `monitor create`；确认 `state-dir` 位于宿主持久存储。`runtime probe` 只验证当前可写，跨重启持久性仍须宿主确认。
4. 运行 `monitor baseline`，检查 `result.image_cache`；首次基线不得产生上新或下架。
5. 运行 `monitor reconcile-plan`。宿主执行后，把真实结果交给 `monitor apply-runtime-result`。
6. 最后运行 `monitor doctor`，区分已验证能力和未支持能力。

## 运行现有监控

1. 先运行 `monitor status` 或 `monitor doctor`，再运行 `monitor run --id <monitor-id> --trigger <trigger> --json`。
2. `CHANGED` 时直接使用 `result.human_summary_zh` 和每条变化的 `product_identity`，不得自行重算变化。
3. 只有 `attachment_ready=true` 才从 `cached_image_path` 读取附件；下架事件优先使用 `AVAILABLE_HISTORICAL` 图片。
4. `INVALID` 时明确说明上一份成功基线已保留，不能把异常解释成上下架。
5. 通知成功后运行 `outbox ack`；发送失败则保留事件供幂等重试。

## 对比二手 Rolex 行情

1. 读取 `references/source-access-policy.md` 和 `references/market-intelligence.md`。
2. 运行 `market source doctor --source <source> --mode <automatic|manual> --usage <internal|public_display|resale> --json`；只有通过门禁的来源才可自动调用。
3. WatchCharts 仅在用户提供 `WATCHCHARTS_API_KEY` 和足够的 `WATCHCHARTS_LICENSE` 时运行 `market collect`；其 appraisal 是型号级背景，生产年份必须为 `null`。
4. 其他来源只接受授权导出或带快照校验的人工证据，并按 `assets/schemas/market-packet-v1.schema.json` 创建 Market Packet。
5. 依次运行 `market packet validate --file <packet> --json` 和 `market compare --id <monitor-id> --file <packet> --json`。结构校验不等于网页内容或 license 已获独立证明。
6. 直接使用比较结果中的 `human_summary_zh`、`analysis_status`、`benchmark_status`、`product_identity`、`comparison_key`、`reference_cohorts`、`price_basis`、`confidence` 和 `comparability_flags`。
7. 只有 `benchmark_status=VERIFIED` 才能称为已验证参考；其他状态不得报告公允价。价格位置只是同地区、同口径比较，不是买卖或收益承诺。

## 修复、备份与恢复

- 修复前运行 `monitor doctor`；升级或高风险修复前运行 `monitor backup`。
- 只恢复由本 Skill 生成且校验和完整的备份；恢复前保留当前状态备份。
- Runtime 任务缺失时重新生成计划，不要重建无关基线。

## 安全与质量不变量

- 东方表行 Adapter 只使用 `Lot_Number_Code` 作为 stable ID；价格、图片、时间、排序和在售状态不得参与身份计算。
- 面向用户的每条上新、下架、改价和资料变化都必须说明商品名称、Rolex 型号编号和东方表行货号，不能只给 stable ID 或“商品编号”。
- 首次基线不产生业务变化；INVALID、空结果、重复或部分抓取都不得替换上一份成功快照。
- 图片保存在 `state-dir/images/<monitor-id>/`，不进入 Agent 对话或 Skill 目录。成功快照应缓存图片；链接失效或商品下架后保留历史缓存。图片失败只产生警告，不污染库存结果。
- Market Packet 无效、过期或缺失不得改变库存基线，也不得阻止库存事件提交。
- 自动采集必须先通过来源政策诊断。API key 不得出现在命令参数、JSON 输出、状态、备份或 GitHub；禁止或待审查来源必须失败关闭，不能静默改用网页抓取。
- 行情只匹配相同 Rolex reference，并按目标年份窗口筛选，默认前后 2 年；成色优先 `excellent`、`very_good`。地区、价格口径和来源独立性必须按行情协议分组，不能混成一个参考价。
- `fixture` 和 `unverified` 证据不得进入已验证参考；`verified` 必须包含带时区的核验时间和证据 SHA-256。
- 不把挂牌价、估值、指数或拍卖结果混称为真实零售成交价。
- 任务、通知和运行绑定未经宿主重新查询或验证，不得声称完成。
- 不绕过 CAPTCHA、登录、访问控制或地区限制；Skill 更新不得删除用户状态。

## 按需参考

- CLI、结果状态和退出码：`references/skill-contract.md`
- Adapter 输入输出与站点异常：`references/adapter-contract.md`
- Runtime Plan 与宿主回传：`references/runtime-plan-contract.md`
- SQLite、图片、Outbox、备份和恢复：`references/state-model.md`
- 行情匹配、Market Packet、聚合和置信度：`references/market-intelligence.md`
- 来源权限、凭证、license 和接入门禁：`references/source-access-policy.md`
- IDE / Agent 安装位置与验证边界：`references/host-compatibility.md`
