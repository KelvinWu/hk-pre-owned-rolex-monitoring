# Runtime Plan 契约

Runtime Plan 是宿主中立的声明式操作列表。Skill 只生成计划，不直接创建系统任务或发送宿主通知。

每项 operation 包含：`op`、`logical_id`、`required_capability`、`idempotency_key`、`parameters` 和 `verification`。

v1 的 `operations` 支持：

- `schedule.upsert`：创建或更新定时调用；

`notification` 描述 Outbox 交付方式、事件类型以及 list/ack 命令；`requirements` 声明宿主必须提供的能力，其中 `persistent_state=true` 要求 `state-dir` 跨任务和重启保留数据库与图片。所有 `schedule.upsert` 操作都内含重新查询验证要求，Skill 本身不会直接执行宿主动作或发送通知。

`runtime probe` 只能验证状态目录当前可写，并返回 `persistent_storage=host_verification_required`；宿主必须通过自身持久卷配置或重启后复查确认持久性，不得把一次写入成功描述成持久存储已验证。

若宿主需要行业对比，由宿主通过正式 API、授权导出或人工证据生成 Market Packet，再调用 `market compare`。Runtime Plan 不授权宿主绕过第三方登录、订阅、反自动化或使用条款。

宿主回传必须包含 `logical_id`、`ok`、`external_id`、`verified` 和可选 `error`。只有 `ok=true`、`verified=true` 且 `external_id` 非空时，绑定才算验证成功。
