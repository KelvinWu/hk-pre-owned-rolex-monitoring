# 状态、事务与恢复

状态目录与 Skill 安装目录分离，由 `INVENTORY_SENTINEL_HOME`、`--state-dir` 或操作系统用户数据目录确定。Agent 对话不承担任何状态或图片存储。

SQLite Schema v2 保存 monitors、runs、snapshots、changes、outbox、runtime_bindings 和 schema_migrations。run 同时保存 Monitor 时区下的 `local_date`，供 `monitor history --date` 查询；图片、原始诊断与备份使用状态目录子目录。

图片保存位置固定为：

```text
<state-dir>/images/<monitor-id>/<Lot_Number_Code>.<ext>
```

`state.image_cache=true` 时，`monitor baseline` 和每次验证成功的 `monitor run` 下载当前商品图片，校验 HTTP 状态、Content-Type 和文件签名后原子写入。`notification.include_images` 只表示宿主通知是否需要附件，不控制本地缓存。

缓存状态：

- `AVAILABLE`：本次成功下载并校验；
- `REUSED_VERIFIED`：URL 未变且本地文件签名与 SHA-256 校验通过，本次未重新下载；
- `AVAILABLE_FROM_PREVIOUS_RUN`：本次下载失败或没有 URL，但历史文件仍可用；
- `AVAILABLE_HISTORICAL`：商品已下架，使用历史缓存；
- `FAILED`：本次失败且没有历史文件；
- `NO_IMAGE_URL`：站点未提供图片 URL 且没有历史文件；
- `DISABLED`：Manifest 明确关闭缓存；
- `MISSING`：查询下架历史图片时未找到文件。

`cached_image_path` 是当前运行环境的绝对路径；只有 `attachment_ready=true` 才可作为附件读取。历史文件不会因商品下架而删除。图片失败只产生 warning，不改变库存成功/INVALID 判断。

每个缓存文件记录 `sha256`、`byte_size`、`etag`、`last_modified` 和 `cached_at`。元数据保存在同一 Monitor 图片目录的 `.image-metadata.json`，随状态备份；不得仅凭文件名存在就视为完整图片。

本地目录可写不等于云端跨重启持久。宿主必须把 `state-dir` 映射到持久卷，并验证重启后文件仍存在；Runtime Plan 以 `persistent_state=true` 声明此要求。

一次成功运行必须在同一事务中提交：新成功快照、run、Diff 和 Outbox。INVALID 只记录诊断 run 与异常事件，不创建成功快照。

Outbox 状态为 `pending`、`sent_unverified`、`verified` 或 `failed`。只有真实 provider、外部消息 ID 和宿主复查结果才能进入 `verified`；`failed` 与 `sent_unverified` 仍属于待处理事件。

Market Packet 是外部、有时效的证据输入。`market compare` 可在内存中对比最新成功快照、指定 run 的变化商品或指定 Outbox 事件，不写入 snapshots、changes 或 outbox；市场数据无效不能回滚或覆盖库存状态。

备份归档包含数据库、`images/`、`raw/` 和校验清单。恢复前自动创建安全备份；校验、解压或替换失败时不得破坏原状态。
