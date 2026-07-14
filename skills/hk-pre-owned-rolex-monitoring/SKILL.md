---
name: hk-pre-owned-rolex-monitoring
description: Monitor and explain Oriental Watch Hong Kong Rolex Certified Pre-Owned inventory with auditable history, retained listing images, and documented HK, APAC, Mainland China, or global market evidence. Use when a user asks whether 东方表行 or Oriental Watch Hong Kong pre-owned Rolex listings have new, removed, price, or detail changes; asks to review yesterday or a prior run; wants a delisted watch image; wants to compare an exact Rolex reference and nearby production years; or needs to initialize, diagnose, or repair this specific monitor. Do not use for generic inventory websites, new-retail Rolex pricing, or investment advice.
---

# HK Pre-owned Rolex Monitoring

监控香港东方表行 Rolex CPO，以可审计历史回答上新、下架、改价和资料变化，并在证据充足时解释香港、亚太、大陆或全球二手行情。库存事实与市场参考始终分开。所有确定性操作均调用 `scripts/inventoryctl.py`；不得在宿主提示词中重写基线、Diff、INVALID、行情聚合或通知幂等。

## 按意图路由

| 用户意图 | 操作 |
|---|---|
| 首次安装或 PyPI / PATH 故障 | 读取 `references/host-compatibility.md`，运行 `scripts/bootstrap.py doctor`；只有 `INSTALL_VERIFIED` 才算完成 |
| 创建监控 | 读取 `references/skill-contract.md`、`adapter-contract.md`、`state-model.md`；先运行 `monitor init`，确认问题后再 `monitor create` 和 `monitor baseline` |
| 查看今天或执行监控 | 运行 `monitor status`，再运行 `monitor run`；使用返回的 `human_summary_zh`、`product_identity` 和 `next_actions` |
| 查看昨天或历史结果 | 运行 `monitor history` 和 `monitor show-run`；不要重新抓取网站代替历史记录 |
| 生成用户报告 | 运行 `report build --run-id <run-id>`；需要行情时增加 `--market-packet <file>` |
| 行情对比 | 读取 `references/source-access-policy.md` 和 `market-intelligence.md`；先做来源诊断，再收集或构建 Market Packet |
| 通知 | 运行 `outbox list`；发送后用真实 provider、外部消息 ID 和核验结果执行 `outbox ack` |
| 修复、升级或恢复 | 先运行 `monitor doctor`；高风险操作前备份，只恢复校验通过的备份 |

CLI 每次只输出一个 JSON。优先执行回执中的 `next_actions`，但仍根据用户意图、宿主能力和是否需要用户确认选择下一步。

## 核心不变量

- 东方表行 stable ID 只能是 `Lot_Number_Code`；价格、图片、排序、时间和在售状态不得参与身份计算。
- 用户看到的每条变化必须包含商品名称、Rolex 型号和东方表行货号，不能只显示 stable ID。
- 首次基线不产生变化；INVALID、空结果、重复 ID 或部分抓取不得替换上一份成功快照。
- 图片存入 `state-dir/images/<monitor-id>/`，不存入对话或 Skill 目录；下架后保留历史图片。图片失败只产生警告。
- 行情失败、过期或证据不足不得修改库存基线；只有 `benchmark_status=VERIFIED` 才能称为已验证参考价。
- 宿主任务和通知未经重新查询或真实回执验证，不得声称已经完成。

## 常见踩坑（Gotchas）

- 包索引首页能打开不代表依赖能够下载；必须让 Bootstrap 实际下载依赖并分别报告 DNS、TLS、`PIP_INDEX_URL` / `PIP_EXTRA_INDEX_URL`、权限和 PATH。
- `stable_id` 是内部审计键，不是用户能感知的腕表名称；直接使用 CLI 返回的 `product_identity`。
- 商品链接和原图会下线；成功快照时就缓存图片，不要等到下架后再下载。
- 空列表或临时漏项不是“全部下架”；返回 INVALID 并保留成功基线。
- WatchCharts 型号估值没有生产年份，不能放入年份窗口 cohort；只能作为型号背景。
- 用户问“昨天”时读取保存的 run；重新运行得到的是今天，不是昨天。
- `outbox ack` 没有外部消息 ID或未经宿主复查时只能记为未验证，不能视为送达。

## 稳定入口

```text
python scripts/inventoryctl.py skill info --json
inventoryctl skill info --json
inventoryctl skill self-test --json
inventoryctl monitor init --output <manifest> --json
inventoryctl monitor list --json
inventoryctl monitor history --id <id> [--date YYYY-MM-DD] --json
inventoryctl monitor show-run --run-id <run-id> --json
inventoryctl monitor run --id <id> --trigger <name> --json
inventoryctl market packet init|add|import-csv|attach-evidence|finalize ... --json
inventoryctl market compare --id <id>|--run-id <run-id>|--event-id <event-id> --file <packet> --json
inventoryctl report build --run-id <run-id> [--market-packet <packet>] --json
```

完整参数以 `inventoryctl --help` 为准。

## 按需参考

- CLI、结果、历史查询、报告和退出码：`references/skill-contract.md`
- Adapter 数据完整性：`references/adapter-contract.md`
- Runtime Plan 与宿主回传：`references/runtime-plan-contract.md`
- SQLite、图片、Outbox、备份和恢复：`references/state-model.md`
- Market Packet、年份匹配、聚合与报告：`references/market-intelligence.md`
- 来源权限、license 和时效门禁：`references/source-access-policy.md`
- 安装、镜像和 IDE / Agent 边界：`references/host-compatibility.md`
