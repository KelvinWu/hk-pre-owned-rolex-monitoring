# Site Adapter 契约

Adapter 只负责取得站点商品、映射字段、判断站点特有完整性、构造详情页和图片地址。Adapter 不负责调度、通知、状态事务或宿主安装。

## 输出

每次 fetch 返回：

- `items`：规范化商品列表；
- `warnings`：不影响身份与完整性的缺字段；
- `diagnostics`：来源、原始数量、去重数量和站点响应信息；
- `raw_payload`：用于脱敏诊断的原始结构。

## 东方表行规则

- 先访问目标页面建立 Cookie 会话，再 POST `rolex.asmx/Rolex_Watches2`。
- 依据 `table_column` 动态映射列。
- `Lot_Number_Code` 映射为 `product_identity.oriental_lot_number`；按官方页面脚本优先使用 `Watch_Reference` 映射 `product_identity.rolex_reference`，仅在兼容旧 Fixture 时回退到 `IF_RL_Watch_Reference_ID`；`Family_txt` 映射为 `product_identity.product_name`。
- `Lot_Number_Code` 是东方表行单件货号，Rolex reference 是腕表型号；两者必须同时保留并明确标注。
- 年份与官方页面保持一致：优先使用非空且不是 `1900` 的 `RL_Date_1`，否则回退到 `RL_Date_2`。同时在 `attributes` 保留 `year_raw_1`、`year_raw_2` 和 `year_source`，不丢弃原始证据。
- `Lot_Number_Code` 缺失或重复、返回 0 条、双层 JSON 损坏、会话失效或错误页均为 INVALID。
- `Family_Code` 等非身份字段缺失只产生警告。
- 需要浏览器或访问被阻止时返回 `BROWSER_REQUIRED`，不得回退为半份库存。
