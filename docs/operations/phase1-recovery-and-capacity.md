# Crash-Cap Phase 1 恢复、Retention 与容量手册

本文件定义可执行步骤和验收证据格式。本机隔离 Compose 的备份恢复、可观测性和容量演练已有记录；目标内网、跨主机灾备和生产数据仍按各节明确的证据边界保持 NOT_PROVEN。

## 1. 备份边界

必须同时备份：

1. PostgreSQL：Workspace、Build/Artifact、Occurrence、Analysis Run、Current Analysis、Group、operation log 及迁移版本；
2. RustFS：raw-builds/、dump-blobs/、analysis/、sym-unified/ 和 uploads/ 对象及其 SHA-256 清单；
3. 配置：phase1.yml 的版本、所有镜像 digest、HTTP endpoint、批准 CIDR/bind、防火墙策略和部署参数（不包括 secret 内容）；
4. 备份本身：访问控制、加密、保留期和离线/异机副本。

PostgreSQL 与 RustFS 必须在同一一致性窗口采集：先暂停新任务并等待 Worker 队列排空，再做 pg_dump 和 S3 object mirror。若无法暂停写入，记录时间窗口和允许的 RPO，不得称为一致快照。

工具 scripts/phase1/ops_backup_restore.sh 使用 PostgreSQL custom dump 和标准 aws s3 sync，不调用 RustFS 私有接口。备份目录必须在仓库之外：

~~~~text
bash scripts/phase1/ops_backup_restore.sh backup /secure/backups/crash-cap/2026-08-21T120000Z
~~~~

脚本要求备份目标尚不存在，避免把新快照混入旧目录；随后写 postgres.dump、rustfs/、不含
secret 的 Compose policy 和 checksums.sha256。checksum 使用相对路径并覆盖 PostgreSQL dump、
Compose policy 与 rustfs/ 下每一个镜像对象，因此可整体移动备份目录后再验证。脚本不会把凭证
打印到终端，也不会将备份写进工作区。

## 2. 恢复演练（必须单独记录）

恢复前由值班运维确认：

- 目标 PostgreSQL/RustFS 是隔离的恢复环境，避免覆盖仍在服务的生产数据；
- 备份目录在仓库外且 checksums.sha256 可验证；
- 负责人、开始时间、目标 RPO/RTO、允许停机窗口和回滚联系人已登记；
- 恢复后不得立即开放匿名内网访问，先做只读检查。

恢复目标的 RustFS Bucket 必须先完成标准 S3 初始化（private ACL、SSE-S3/AES256、凭证和可信内网 HTTP endpoint 可用），并在 restore 前用 `head-bucket` 验证。`ops_backup_restore.sh restore` 只同步对象，不创建 Bucket；若目标 Bucket 不存在，`aws s3 sync` 会返回 `NoSuchBucket`。部署环境应先执行 `ops_storage_init.py --apply` 或等价的标准 S3 初始化步骤，再执行下面的 restore。

执行示例（确认短语必须使用脚本解析出的绝对路径）：

~~~~text
bash scripts/phase1/ops_backup_restore.sh restore /secure/backups/crash-cap/2026-08-21T120000Z \
  --confirm "RESTORE /secure/backups/crash-cap/2026-08-21T120000Z"
~~~~

脚本先在备份目录内执行全量 `sha256sum -c`，任一数据库/配置/对象镜像字节损坏都会在
`pg_restore` 前终止。PostgreSQL `pg_restore --clean --if-exists` 只在精确确认后执行；RustFS
恢复使用 `aws s3 sync --sse AES256` 且不带 `--delete`，所以额外目标对象不会被脚本静默删除，
运维需先审阅再处理。

恢复验收必须给出可复核证据，而不是只看进程为 running：

| 检查 | 证据 |
| --- | --- |
| Current Analysis | 随机抽样 occurrence 的 current_run_id、status、Build resolution 与恢复前一致 |
| Canonical/Raw 对象 | 对象 key、长度和 SHA-256 与备份 manifest 一致；Range GET 也可读 |
| 统计 | Workspace/Version/Crash/Unclassified/Hang/Unknown/Rejected 计数与恢复前一致 |
| 符号 | Unified 对应 workspace/debug ID 可读；Symbolicator 重新启动后可重查 |
| 安全边界 | deploy_check.py PASS；无公开数据端口；原始下载仍由开关控制 |
| 时间 | 记录备份耗时、恢复耗时、数据量、RPO、RTO 和未恢复对象 |

本次已完成一次本机、隔离、合成 schema 的 PostgreSQL/RustFS 恢复演练（详见 `phase1-backup-restore-drill-2026-08-21.md`）；生产数据、跨主机灾备、真实一致性窗口和 RPO/RTO 仍为 NOT_PROVEN。生产发布前必须把上述表格、命令输出、抽样 hash 和责任人记录到变更单。

## 3. Retention 语义

- Workspace retention_days 默认 180，只作用于原始 dump-blobs/{workspace_id}/{blob_id}/original.dmp；具体 Workspace 可以调整；
- 到期流程先尝试删除对应 RustFS 对象；删除成功或对象已不存在时，才在 PostgreSQL 将 Blob 标为 deleted 并写 operation_logs（actor=anonymous、request/任务 ID、target、result）。403、超时或存储错误不得提前写入 deleted，Blob 保持可重试；
- Occurrence、Analysis Run、Current Analysis、Canonical 摘要、统计和历史 membership 不因原始 DMP 到期而删除；历史分析若需要原始 Blob，应返回 RAW_BLOB_EXPIRED；
- 不按全桶统一生命周期覆盖 Workspace 级策略；部署脚本只设置私有 ACL/SSE，retention worker 负责按 Workspace 计算 due objects；
- retention worker 的删除必须幂等，超时/403/404 分别记录，不能把对象删除失败伪装成数据库完成。

上线前的验证样本至少包含：默认 180 天、一个自定义保留期、已过期 Blob、未过期 Blob、没有 Current Analysis 的 Occurrence，以及已过期但仍可读 Canonical 的 Occurrence。

## 4. 紧急本地删除

Web/API 没有 DELETE。发生法律、恶意输入或磁盘处置事件时，只能由本机运维运行 scripts/phase1/ops_emergency_delete.py：

~~~~text
python scripts/phase1/ops_emergency_delete.py \
  --object-key dump-blobs/wsp_abc/blob_123/original.dmp \
  --reason "approved security incident INC-123" \
  --audit-log /secure/audit/crash-cap-emergency-delete.jsonl

# 先 dry-run 输出计划；确认 key 无误后才允许：
python scripts/phase1/ops_emergency_delete.py \
  --object-key dump-blobs/wsp_abc/blob_123/original.dmp \
  --reason "approved security incident INC-123" \
  --audit-log /secure/audit/crash-cap-emergency-delete.jsonl \
  --apply \
  --confirm "DELETE dump-blobs/wsp_abc/blob_123/original.dmp"
~~~~

脚本只接受一个精确、Workspace-scoped key，拒绝前缀/递归删除；--apply 必须有仓库外 audit log。删除后会用 HEAD 验证对象不存在，但不会声称数据库已更新：值班人员还必须在平台 operation log 中登记 Blob 状态和原因。对象删除不可撤销，恢复边界是最近一次通过 hash 验证的备份；删除前先确认备份是否含该对象。

## 5. 监控与容量基线

至少暴露以下指标（名称可映射到现有 metrics 命名规范，但语义不可省略）：

| 面 | 指标/维度 | 建议告警 |
| --- | --- | --- |
| 队列 | Dramatiq queue depth、oldest age、verify/dump-small/dump-large/ingest | 深度持续增长、最老任务超过目标 |
| Durable intent | `crashcap_task_intents{task_type,state}`、`crashcap_task_intent_oldest_pending_age_seconds{task_type}` | pending/publishing 持续增长、oldest 越过对应 SLO、dead > 0 |
| Relay | `crashcap_relay_deliveries_total{task_type,outcome}`、`crashcap_relay_backoff_seconds{task_type}`、`crashcap_task_poisoned_total{task_type,source}` | transient error/退避持续增长、permanent error 或 poison > 0 |
| Ownership | `crashcap_task_executions{task_type,outcome}`、`crashcap_task_execution_expired_active{task_type}`、`crashcap_task_claims_total{task_type,outcome}`、`crashcap_task_heartbeats_total{task_type,outcome}` | expired active > 0、lease reclaim 或 rejected heartbeat 异常增长 |
| Lifecycle | `crashcap_analysis_transitions_total{from_state,to_state,outcome}`、`crashcap_current_analysis_promotions_total{outcome,reason}` | rejected transition > 0；promotion skipped 按固定 reason 分流排查 |
| Fencing | `crashcap_fenced_stale_writes_total{task_type,stage}` | 任意增长都要关联 attempt/generation 检查是否为预期 reclaim |
| Canonical | `crashcap_canonical_shadow_results_total{outcome}`、`crashcap_canonical_validation_failures_total{kind}`、`crashcap_canonical_winner_finalizes_total{assembly_mode,status,promotion}` | mismatch 或 validation failure > 0；切流期间 winner finalize 停滞 |
| 状态耗时 | upload verification、queued、running、complete/partial/failed | p95 越过 ≤64MiB 10min 或 64–256MiB 20min |
| 失败 | timeout、OOM、Core exit、PDB mismatch、Symbolicator 4xx/5xx | OOM/timeout 突增，错误符号静默命中必须为 0 |
| 符号 | Microsoft cold-cache 下载次数/耗时、cache hit/miss、pending retry | 冷下载单独计量；外部 Microsoft HTTPS allowlist/证书失败 |
| Symbol projection | `crashcap_symbol_projection_backfill_remaining`、`crashcap_symbol_projection_unresolved_gaps`、`crashcap_symbol_projection_shadow_mismatches_total`、`crashcap_symbol_projection_strict_failures_total{reason}`、`crashcap_symbol_projection_writes_total{mode,outcome}` | read cutover 前 remaining/gap/mismatch 必须为 0；strict failure 立即停止晋级 |
| Generation object | `crashcap_generation_orphan_objects_total{kind}`、`crashcap_generation_orphan_bytes_total{kind}` | 增长后运行引用检查；只按 TTL + audit 清理，禁止因代码回滚直接删除 |
| RustFS | 4xx/5xx、HEAD/Range/multipart 错误、对象 bytes/count、bucket health | 读写错误、增长接近容量 |
| PostgreSQL/Redis | 连接池、事务错误、锁等待、Redis memory/AOF、重连 | 连接耗尽、AOF 错误、队列持久化失败 |
| 主机 | RustFS/PG/符号缓存磁盘、inode、容器 memory/pids/cpu | 80% warning、90% critical（按主机策略调整） |

### 5.1 只读 metrics sidecar

Compose 中的 `ops-exporter` 监听 loopback 发布的 `PHASE1_METRICS_PORT`（默认
`9108`），加入用于受控 host port 的 `edge`、`app` 与专用的 `observability` 网络，不持有 Docker socket、
数据库凭证或 RustFS 凭证。Phase 1 HTTP-only 部署没有 TLS 私钥；RustFS 恢复后必须用精确的 `S3_CORS_ALLOWED_ORIGINS` 重跑 storage bootstrap，Bucket CORS 不在对象镜像中。它抓取 API 和内部 OTel Collector 的
`/metrics`，所以队列深度、Analysis/Upload 状态、状态最老年龄、完成耗时、PostgreSQL
元数据对象 count/bytes，以及 RustFS/Symbolicator 原生 telemetry 都能从同一个
sidecar 端点读取。

`otel-collector` 固定 `otel/opentelemetry-collector-contrib` 0.157.0 digest，只加入
`observability` 内部网络。它接收 RustFS `RUSTFS_OBS_ENDPOINT` 的 OTLP/HTTP
和 Symbolicator `SYMBOLICATOR_STATSD_ADDR` 的 StatsD；`spanmetrics` 按 HTTP method/status
生成请求计数，`count` 将 RustFS OTLP 日志及 ERROR-or-higher 日志转为计数器，Prometheus
exporter 仅在内部 `9464` 暴露。没有 trace/log exporter、host port 或 secret 挂载；
sidecar 重新导出该内部 Prometheus 文本，避免把这些信号伪装为本地探针。

`ops-docker-proxy` 是同一 Compose 的内部 sidecar；它是唯一挂载 Docker socket 的服务，
挂载为 `read_only`，且代码在触碰 socket 前只允许 `GET /containers/json` 和
`GET /containers/{id}/stats?stream=false`，其它路径和写方法均拒绝。Exporter 只通过
该 proxy 读取带 Compose service label 的 CPU、memory、pids 快照；proxy 本身不发布
host port，`deploy_check.py` 会校验这一边界。

sidecar 只对三个 named volume 做 `read_only` 观察：RustFS 数据、Unified symbols
和 Symbolicator cache。`crashcap_ops_filesystem_*` 是 Docker backing filesystem 的
`statvfs` 容量/inode 视图，多个 named volume 可能共享同一 backing filesystem；
`crashcap_ops_volume_logical_bytes` 与 `crashcap_ops_volume_file_count` 则通过不读文件
内容的递归 `lstat` 聚合各卷的逻辑增长，symlink 不跟随。它还读取自身容器的 cgroup v2
CPU、memory、pids 文件。`crashcap_ops_service_resource_supported{service=...}` 对其它
服务在 proxy 不可用或返回缺字段时为 `0`，不会用 exporter 自身 cgroup 值冒充其它
服务。Exporter 自身的 cgroup 指标单独使用 `crashcap_ops_self_resource_*`。

当前 Redis/Dramatiq 消息没有 enqueue timestamp，故
`crashcap_ops_queue_oldest_age_seconds` 明确为 `NaN` 且
`crashcap_ops_queue_oldest_age_supported=0`。当前 API、Gateway 和 Symbolicator 也没有
可供该 sidecar 可靠关联的业务队列 oldest age，故只保留上述 `supported=0`。RustFS
operation 与 Symbolicator cold-cache capability 则根据 OTel Collector 当前输出动态置位：
没有对应原生 metric 时为 `supported=0`/`state="unknown"`，出现 method/status、cache 或
download 信号后才为 `1`；不得把 sidecar 的健康检查或 statvfs 误报为业务请求成功率。
Range/multipart 只有在 RustFS 实际通过 OTLP 暴露可区分维度时才会置位，不能由普通 GET
数量推断。若生产镜像不发送这些信号，保留 `0` 并记录原因。

### 5.2 架构深化业务信号与结构化日志

`crashcap_task_intents`、oldest pending、execution outcome 和 expired active 都从 PostgreSQL
durable state 刷新；Redis queue depth 只说明 broker 当前可见消息，不能替代 intent 是否丢失的判断。
relay、claim、heartbeat、transition、promotion、fencing、Canonical 与 orphan 指标是进程生命周期
counter/histogram，发布或进程重启时必须由监控端持久聚合。`generation_orphan_*` 只统计本进程在
stale-owner fencing 时已知写出的 generation-scoped 对象，不是 RustFS 全量 orphan inventory。

Microsoft 公共缓存验收必须使用两个不同 Workspace 的同一 `debug_id`：第一个请求允许 cold
download，第二个请求应复用稳定 `crash-cap:microsoft` source ID 的缓存。仅看到同一个 named
volume 不算复用证据；还必须确认 Gateway 未向上游转发 Workspace scope、第二次没有新的 Microsoft
download，并且 Workspace 私有 source ID 仍不同。终态 `debug_status=found|unused` 不得留下
`system_symbol_pending`，真实失败才记录 `system_symbol_failed`。

所有日志记录固定输出以下字段，未适用时为 `-`：

~~~~text
request_id attempt_id task_type queue logical_target domain_identity
claim_generation from_status to_status outcome reason
~~~~

这些字段及消息参数都经过同一脱敏 filter；不得把异常正文、对象 key、URL、token 或高基数 ID
放进 metric label。排查 stale winner 时先按 `attempt_id + task_type + logical_target +
claim_generation` 聚合，再串联 lifecycle 的 `from_status/to_status` 和低基数 `outcome/reason`。

### 5.3 Symbol Health backfill 与切流

先保持 `CRASHCAP_SYMBOL_PROJECTION_MODE=shadow-soft`，默认只做 dry-run：

~~~~text
crashcap-ops backfill-symbol-projection --limit 100 --output /secure/evidence/symbol-backfill.json
~~~~

目标数据 apply 是写操作，必须在已批准窗口使用精确确认词；命令按 durable checkpoint 续跑：

~~~~text
crashcap-ops backfill-symbol-projection --limit 100 --apply \
  --confirm APPLY_SYMBOL_PROJECTION_BACKFILL \
  --output /secure/evidence/symbol-backfill-apply.json

crashcap-ops backfill-symbol-projection --retry-gaps --limit 100 --apply \
  --confirm APPLY_SYMBOL_PROJECTION_BACKFILL \
  --output /secure/evidence/symbol-backfill-gap-retry.json
~~~~

每批必须保存 `next_cursor`、`backfill_remaining`、`unresolved_gaps` 和逐 Occurrence 原因。object missing/corrupt、schema-invalid、semantic-invalid 与 pointer-changed 都不能静默跳过。只有 remaining=0、unresolved gap=0、完整 shadow snapshot mismatch=0，且至少连续观察 24 小时/100 次 promotion 后，才允许先切 `strict-writer`，稳定后再整组切 `projection-read`。四条读路径不得混用模式。真实回滚演练使用 `legacy` 开关和认识 revision 0005 的兼容镜像；不要 downgrade 数据库。legacy writer、audit 和旧字段至少保留两个发布周期。

手工检查：

~~~~text
curl --fail http://127.0.0.1:${PHASE1_METRICS_PORT:-9108}/healthz
curl --fail http://127.0.0.1:${PHASE1_METRICS_PORT:-9108}/metrics > /secure/metrics/phase1.prom
~~~~

`deploy_check.py` 会校验 sidecar 的 loopback bind、`edge + app + observability` 网络、`cap_drop: ALL`、只读
挂载和无 secret 环境变量。sidecar 可见的容量指标是文件系统观察值，不等于业务容量
基线；100 dumps/day、峰值 5 任务及 p95 仍需按第 5 节末尾的负载演练采集。

路线图容量基线是 100 dumps/day、峰值 5 个任务；≤64 MiB 端到端 p95 目标 10 分钟，64–256 MiB 目标 20 分钟，Microsoft 冷符号首次下载单独计量。它是容量目标，不是业务上限；超出时应排队而非丢弃。`scripts/phase1/capacity_gate.py --workload upload --execute` 负责对真实 Compose 运行该门禁；`--workload reprocess` 仅是明确标记的 smoke。

2026-08-21 已在隔离 Compose 执行 100 个唯一 DMP、5 并发、80 个小桶与 20 个大桶样本。结果为 `PASS`：小桶 p50/p95/p99 为 14.304/16.296/18.405 秒，大桶为 50.105/54.040/54.088 秒；100 个唯一 Blob/Occurrence/SHA、duplicate=0、四队列均有证据。受控空缓存探针另记录 6 次成功 Microsoft 下载、67 次 cache miss 和最长 26.369 秒。仓库外证据位于 `E:\crash-cap-capacity-20260821\evidence\capacity-gate.json`、`capacity-gate.md` 与 `microsoft-cold-cache.json`。该本机隔离结果关闭 P1-G10，但不替代目标硬件或生产流量容量规划。
