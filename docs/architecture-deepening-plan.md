# Crash-Cap 五项架构深化实施计划

状态：**In progress / G0–G5 已通过本机门禁；G6/G7 实现与一次性依赖门禁通过，长期灰度和目标环境门禁待执行**<br>
基线：`main@f4ee82e`，2026-08-24<br>
范围：Durable Task Handoff、Analysis Run lifecycle、Canonical Analysis Result ownership、HTTP representation、Symbol Health durable projection。

本文只定义实施顺序、依赖、迁移、回滚和完成证据，不修改产品语义。领域语言以 [CONTEXT.md](../CONTEXT.md) 为准；冲突时以 [设计文档](design.md)、accepted ADR 和稳定机器契约为准。原架构报告把前四项评为 Strong、lifecycle 评为 Worth exploring；本轮交叉评审证明 lifecycle 是 outbox 与 Symbol Health 正确性的前置，因此五项均按必做范围规划。

## 1. 目标结果

完成后必须同时满足：

- PostgreSQL 中的业务状态与 task intent 原子提交；Redis 中断不会丢任务。
- 队列保持 at-least-once；重复 delivery、lease reclaim 和迟到 Worker 不能重复产生领域副作用。
- Analysis Run 的 transition、terminal、retry、claim、fencing、Current Analysis promotion 只有一个权威实现。
- Core 一次形成最终 Canonical Analysis Result；Worker 不再事后改写 identity、time、engine 或 `source_context`。
- `/api/v1` 运行时 JSON 保持兼容；关键响应拥有显式、可生成、可跨语言验证的 representation。
- Symbol Health 从 Current Analysis 的 durable projection 读取；OperationLog 仅保留审计职责。
- 所有数据迁移先 additive、再 shadow、后切流；启用后可回滚到兼容镜像，不回滚到不认识新 schema 的旧镜像。

## 2. 不可破坏的不变量

| ID | 不变量 | 硬门禁 |
| --- | --- | --- |
| `INV-01` | 一个不同的 accepted DMP 在 Workspace 中对应一个 Occurrence；重分析只创建新的 Analysis Run。 | reprocess 前后 Occurrence 数量不变。 |
| `INV-02` | Current Analysis 只能指向同一 Occurrence 的 `COMPLETE/PARTIAL` Run。 | 数据库巡检与并发测试均为零违规。 |
| `INV-03` | 历史 Analysis Run、Canonical object 和固定 engine identity 不可原地改写。 | 任何回退都创建新 Run，不修改旧 Run digest。 |
| `INV-04` | `analysis-result-v1`、`task-message-v1` 与 `/api/v1` 保持稳定。 | breaking change 必须停止本计划并另立新版本。 |
| `INV-05` | Crash-Cap Core 拥有 Canonical、quality、Build Resolution 与 grouping 规则。 | 不允许 Worker post-assembly mutation。 |
| `INV-06` | OperationLog 是 append-only audit，不是 task、lifecycle 或 Symbol Health 的当前状态来源。 | 新读路径不得扫描 OperationLog。 |
| `INV-07` | 匿名可信内网、无 DELETE、RustFS S3 adapter、plain HTTP 的 accepted ADR 保持不变。 | perimeter、route 与存储资格门禁继续执行。 |

## 3. 子代理交叉评审结论

### 3.1 已达成共识

- outbox 解决“不丢”，不能提供 exactly-once；consumer claim、lease 和 fencing 是同一交付包的硬前置。
- `attempt_id` 表示 logical attempt；每次 ownership 转移获得单调递增的 generation。
- 所有状态、失败、winner object、Current Analysis、Group 和 Symbol Health projection 写入必须校验当前 generation。
- 长时 Core、RustFS、Symbolicator 工作不得持有数据库锁。
- 每个 generation 写 immutable、generation-scoped Canonical/raw object；stale object 不能成为 winner。
- Worker 的 `_bind_platform_identity` 和 `attach_source_context` 都必须退出最终路径。
- migration 使用 one-shot job；全量 backfill 不放进 Alembic，也不放进 API 启动路径。
- Symbol 双轨期必须比较完整快照，不能把 legacy count 与新 relation 拼成一个响应。
- 五项禁止 big-bang；schema、shadow writer、strict writer、read cutover、cleanup 分版本推进。

### 3.2 明确反对

- 只加 outbox，不做 consumer fencing。
- 用 OperationLog 作为 Symbol projection 的权威回填来源。
- 多个 generation 覆盖同一个固定对象 key。
- Worker 校验前继续“修正”Core 输出。
- 在一个外部响应中混合 legacy/new 两种状态来源。
- Alembic migration 内运行对象存储读取或全库长时 backfill。
- 数据库升级后直接回滚到 `f4ee82e`。
- 较老 Run 迟到后覆盖创建顺序更晚的成功 Current Analysis。

## 4. 评审前必须确认的决策

这些决策进入代码前必须落入新 ADR 或 `docs/design.md`。推荐项写在前面。

| ID | 推荐决策 | 未确认时的处理 |
| --- | --- | --- |
| `DEC-01` | Current Analysis 按 Analysis Run 创建顺序单调前进；现有带前缀 ULID 的 `run.id` 作为稳定顺序。较新 Run 失败时，较老但成功的 Run仍可晋升；已经有更晚成功 Run 时，较老 Run 不得回退指针。 | 阻塞 lifecycle finalize 与 Symbol strict writer。 |
| `DEC-02` | Core 是 final Canonical v1 的唯一 owner。平台解析并冻结 identity/time 事实；Worker stage verified artifact；Core 防御性读取 staged source bundle并填充 `source_context`。 | 阻塞 Core-final 实现。 |
| `DEC-03` | Missing Symbol 双空 `debug_id/code_id` 时使用规范化 `debug_file/code_file` 作为 fallback identity；迁移报告必须显式展示被拆分的 legacy 聚合。 | 保持 legacy 合并，仅允许 shadow，不允许 read cutover。 |
| `DEC-04` | `ignored` 是人工处理状态，与 affected count 正交；projection 更新不得自动改回 `open/resolved`。 | 保持 legacy 响应，阻塞 strict writer。 |
| `DEC-05` | source bundle enrich 失败省略可选 `source_context` 并产生稳定 warning/PARTIAL，不把原本可分析的 Dump 升级为 FAILED。 | 阻塞 Canonical parity Gate。 |
| `DEC-06` | reindex 发现 symbol inventory 已变化时 stale-no-op；新 inventory 显式创建新 intent。 | 阻塞 reindex outbox cutover。 |
| `DEC-07` | Rust response model 先做离线、可复现的生成工具 spike；未达标时使用 checked-in typed models + contract fixtures，不替换现有 transport。 | 不阻塞 Python/浏览器 representation 迁移。 |
| `DEC-08` | lease、heartbeat、backoff、orphan TTL 由现有 10/20 分钟 task limit 和容量 Gate 实测确定，不在设计阶段拍固定值。 | 使用 legacy mode，不进入目标部署。 |

建议新增：

- `ADR-0006`：transactional outbox、at-least-once、claim/lease/fencing 与 rollback floor。
- `ADR-0007`：final Canonical assembly ownership，并澄清 ADR-0001。
- `ADR-0008`：stable HTTP representation authority 与兼容规则。
- `ADR-0009`：Current Analysis promotion 与 Symbol Health projection 语义。

## 5. 目标结构与依赖

```text
HTTP adapter / Worker adapter
             │
             ▼
PostgreSQL transaction
  domain state + OperationLog + durable task intent
             │
             ▼
Outbox relay adapter ──► Redis/Dramatiq ──► Worker claim
                                                │
                                     short claim + lease + generation
                                                │
                                      long work outside DB lock
                                                │
                       ┌────────────────────────┴──────────────────────┐
                       ▼                                               ▼
              Core final Canonical                         stale generation discard
                       │
                       ▼
One finalize transaction
  winner result + summary + Current Analysis + Group + Symbol projection + audit
                       │
                       ▼
HTTP representation ──► generated TypeScript / Rust contract fixtures
```

总体依赖：

```text
G0 决策与基线
   │
   ▼
G1 additive migration + rollback-compatible image + one-shot migrate
   │
   ├── LIFE claim/fencing ───────────────┐
   ├── CAN baseline/context/Core final ──┼── winner finalize
   ├── REP inventory/models ─────────────┤
   └── SYM schema/backfill tooling ──────┘
                 │
                 ▼
DTH 分 task type 切流 + Symbol strict writer
                 │
                 ▼
Canonical/HTTP/Symbol shadow parity
                 │
                 ▼
分项 read/write cutover ──► rollback drill ──► cleanup
```

并行泳道：

| 泳道 | 主要范围 | 可以并行的起点 | 必须等待 |
| --- | --- | --- | --- |
| `MIG/OPS` | one-shot migration、additive DDL、兼容镜像 | `G0` 后 | 无 |
| `LIFE` | claim、lease、fencing、真实 milestone、promotion | schema 设计冻结后 | final integration 等 CAN/SYM |
| `DTH` | outbox、relay、poison、producer 转换 | schema 设计冻结后 | analyze/reindex 切流等 LIFE |
| `CAN` | immutable context、Core final、source context | `G0` 后 | cutover 等 LIFE winner |
| `REP` | response model、OpenAPI、客户端 | `G0` 后 | Symbol 外部切流等完整 snapshot |
| `SYM` | durable relation、backfill、shadow read | additive schema 后 | strict writer 等 LIFE/CAN；read cutover 等 REP |
| `QA` | fixtures、故障注入、兼容矩阵、目标验收 | 从基线开始 | 每个 Gate 汇合 |

## 6. Phase A0 — 基线、决策与失败模型

- [x] **ARCH-001｜冻结当前行为基线** `[QA]`

  覆盖 21 个 Golden、source bundle、有/无 reported/manual/dump time、PARTIAL、历史 Run、四类 task、所有关键 HTTP route。分别保存 Core 原始输出和 Worker 当前实际持久化结果。

  完成标准：测试夹具能明确指出现有 post-bind/post-enrich 行为；动态值有书面归一化规则。

- [x] **ARCH-002｜建立 route/consumer inventory** `[REP/QA]`

  盘点 `platform/api/crashcap_api/routes.py` 的全部 route、status/header/error/SSE/Canonical response，以及浏览器和 `crashcap-ci` 的消费者。

  完成标准：每条 route 映射权威 shape、兼容消费者和迁移 wave；不能只统计 `dict[str, Any]` 数量。

- [x] **ARCH-003｜建立 task failure matrix** `[DTH/LIFE/QA]`

  对 verify、ingest、reindex、analyze 分别列出 commit 前后、publish 前后、claim 前后、lease expire、long work、object write、finalize 的 crash point 与期望恢复行为。

  完成标准：每个 crash point 都有 expected durable state、自动恢复方式、是否允许 duplicate、stale object 处理。

- [x] **ARCH-004｜建立数据健康基线** `[SYM/LIFE/QA]`

  只读扫描 Current Analysis 合法性、MissingSymbol count 与日志 replay 差异、缺失 Canonical object、双空 identity 和固定 object key 竞争风险。

  完成标准：生成可复核报告；已有数据损坏单独修复，不带病回填。

- [x] **ARCH-005｜评审并接受 DEC-01–08** `[Docs/ADR]`

  完成标准：ADR accepted；`docs/design.md` 明确完整 active-state failure transition、Current Analysis promotion 和 `ignored` 语义。

### Gate G0 — 允许实施

- [x] 基线夹具可重放。
- [x] 四份 ADR 或等价决策记录已 accepted。
- [x] 所有未决项有 owner 与截止点。
- [x] 未通过 G0 不得修改生产路径。

G0 本机证据见 [baseline](architecture/deepening-g0-baseline.md) 与
[machine-readable result](evidence/architecture-g0-local-baseline.json)。目标 PostgreSQL、Redis、
RustFS 与 Canonical object 扫描仍须在迁移前重跑，不由本机 G0 外推。

## 7. Phase A1 — 发布和 additive schema 前置

- [x] **MIG-001｜迁移从 API 启动路径剥离** `[MIG/OPS]`

  修改 `platform/api/Dockerfile:47-50`，API 不再内联 `alembic upgrade head`；在 `platform/pyproject.toml` 增加独立 migration entrypoint；`deploy/compose/phase1.yml` 增加 one-shot `migrate`。

  API、relay、全部 Worker 和 retention 必须依赖 `service_completed_successfully`；`scripts/phase1/deploy_check.py` 验证该拓扑。

  完成标准：Worker 不可能早于 DDL 启动；migration 无 host port、仅连接必要 data network、`restart: "no"`。

- [x] **MIG-002｜新增 durable handoff / execution ownership schema** `[MIG/DTH/LIFE]`

  新增 `platform/migrations/versions/0003_durable_task_handoff.py`，只做 additive DDL：

  - durable task intent：稳定 attempt、task schema、routing、logical target、due/relay lease、attempt count、published/dead 状态；
  - execution ownership：logical task key、active attempt、claim generation、lease、outcome；
  - Analysis Run winner/fencing 所需字段与 generation-scoped object 引用；
  - due、lease-expiry、logical-key、target 的索引和唯一约束。

  完成标准：DDL 不做历史 backfill，不访问 Redis/RustFS。

- [x] **MIG-003｜新增 Symbol projection schema** `[MIG/SYM]`

  采用独立 revision，仅做 additive DDL：

  - `missing_symbols` 增加内部稳定 surrogate identity；
  - 新建 Missing Symbol × Occurrence 当前关系，记录 winner Analysis Run、原因、文件名证据与 observation time；
  - 建立 Workspace、Occurrence、Run、Missing Symbol 的集合式索引；
  - 暂时保留 `affected_occurrence_count` 与 legacy status。

  完成标准：关系中的 Run 必须属于该 Occurrence；应用 finalize 再保证其等于 Current Analysis。

- [x] **MIG-004｜迁移测试与 rollback floor** `[MIG/QA/OPS]`

  扩展 `platform/migrations/tests/test_phase1_migration.py`，覆盖 offline SQL、upgrade/downgrade SQL、PostgreSQL 实际 upgrade、唯一约束、并发 claim 所需索引和 Workspace 隔离。

  完成标准：产出“认识新 revision、全部 feature flag 为 legacy”的 rollback-compatible 镜像；启用后禁止直接回滚到 `f4ee82e`。

### Gate G1 — Schema 与部署前置

- [x] one-shot migration 成功后 API/Worker 才启动。
- [x] migrations 只含 additive、短事务 DDL。
- [x] PostgreSQL 实际集成测试通过；SQLite 证据不可替代。
- [x] rollback-compatible 镜像完成 smoke test。

G1 的本机、PostgreSQL 16 和容器镜像证据见
[machine-readable result](evidence/architecture-g1-local-gate.json)。该证据不包含目标内网部署、
远程 CI 或完整 Redis/RustFS/Core/Symbolicator Compose Gate，不能向这些边界外推。

## 8. Lane LIFE — Analysis Run lifecycle

- [x] **LIFE-001｜建立唯一 lifecycle vocabulary** `[LIFE]`，依赖 `G0`

  新建 `platform/api/crashcap_api/analysis_states.py` 与 `services/analysis_lifecycle.py`，集中 status、transition、terminal、current-eligible、failure classification、retry/reprocess 区别和 promotion 规则。

  完成标准：数据库 CheckConstraint 继续作为存储保护，并有 parity test；它不成为第二份手工语义。

- [x] **LIFE-002｜实现短事务 claim、lease 与 fencing** `[LIFE/DTH]`，依赖 `MIG-002`

  Worker 只在短事务取得 ownership；每次 reclaim generation 单调增加；long work 在事务外；heartbeat 只能延长当前 generation。

  完成标准：两个 Worker 并发只允许一个当前 owner；stale owner 只能记录 `stale-discard`。

- [x] **LIFE-003｜让状态对应真实 milestone** `[LIFE/CAN]`

  删除 `processor.py:664-673` 的事后 `_advance_to_analyzing`。推荐拆成 durable inspect/preparation 与 final analysis 两段：inspect evidence 持久化后才进入 `INSPECTED`；match 完成后进入 `SYMBOLS_READY`；`QUEUED` 与后继 intent 同事务；final worker claim 后进入 `ANALYZING`。

  完成标准：SSE/轮询只观察已持久化的真实进度；crash 后从 checkpoint 恢复。

- [x] **LIFE-004｜消除所有旁路状态写入** `[LIFE]`

  替换 `services/common.py:34-78`、`processor.py:550-553`、`routes.py:719-725,1261-1286`、`metrics.py` 与客户端 terminal set 的重复规则。

  完成标准：production 中不存在 lifecycle module 外的直接 `AnalysisRun.status` 赋值；非法 transition 不再 fallback 成直接写状态。

- [x] **LIFE-005｜实现 generation-scoped finalize** `[LIFE/CAN/SYM]`

  一个 transaction 内校验 generation，并写 winner `result_object_key`、summary、Current Analysis、Group projection、Symbol projection 与 audit。固定 key 改为 generation-scoped immutable key。

  完成标准：迟到 success/failure 都不能改写 winner 或 Current Analysis；stale object 只进入 orphan inventory。

- [x] **LIFE-006｜落实 Current Analysis 单调 promotion** `[LIFE]`，依赖 `DEC-01`

  finalize 锁定 Occurrence，比较 Run 创建顺序；FAILED/REJECTED/CANCELLED/TIMEOUT/OOM 永不 promotion。

  完成标准：较老 Run 晚完成不回退；较新 Run 失败时保留或允许尚未被更新成功 Run 超越的较老成功 Run 晋升。

### Gate G2 — Lifecycle / fencing

- [x] `_advance_to_analyzing` 与 direct status fallback 从生产路径消失。
- [x] 所有 terminal write、winner write 和 projection write 都校验 generation。
- [x] `COMPLETE → FAILED`、stale overwrite、Current Analysis 回退的并发测试全部通过。
- [x] lifecycle Gate 通过前，analyze/reindex 不得切到 outbox relay。

G2 的本机、generation orphan、PostgreSQL 双 claim/reclaim 与并发 Current Analysis 锁证据见
[machine-readable result](evidence/architecture-g2-local-gate.json)。该 Gate 仍不等价于真实
Core/Symbolicator 长任务、Redis 中断或目标内网负载证据。

## 9. Lane DTH — Durable Task Handoff

- [x] **DTH-001｜建立 deep handoff module** `[DTH]`，依赖 `MIG-002`

  新建 `platform/api/crashcap_api/task_handoff.py`，统一拥有 intent 创建、schema validation、logical 去重、relay claim/backoff/poison、worker claim/reclaim、generation fencing 和 outcome。

  `TaskDispatcher` 只保留 Redis/Dramatiq adapter 身份。

- [x] **DTH-002｜实现独立 relay** `[DTH/OPS]`

  新建 `platform/worker/crashcap_worker/outbox_relay.py`、`relay_main.py`，并加入 `platform/pyproject.toml` 和 Compose。relay 短事务 claim，事务外 publish，再以 relay fencing ack。

  完成标准：publish 后、ack 前 crash 可产生 duplicate，但不会丢 intent，也不会重复领域副作用。

- [x] **DTH-003｜poison 与 legacy compatibility** `[DTH]`

  intent 创建、relay publish、worker consume 前都验证冻结的 `task-message-v1`。网络/Redis 是 transient；未知 schema/task/queue 是 permanent poison。兼容窗口接受无 outbox row 的 legacy v1；旧 backlog 清零后开启 strict receipt。

- [x] **DTH-004｜转换全部 producer** `[DTH]`

  修改 `services/uploads.py`、`services/analysis.py`、`routes.py`、`processor.py`，使“业务状态 + OperationLog + task intent”处于同一 PostgreSQL transaction。

  完成标准：production direct `dispatcher.enqueue` 只存在于 relay adapter；增加 AST 架构门禁。

- [x] **DTH-005｜verify 重复执行规则** `[DTH/LIFE]`

  logical key 按 Upload；只有当前 generation 且仍为 VERIFYING 才 finalize；ACCEPTED 与后继 intent 同事务；重复执行不重复创建 Dump Blob、Occurrence 或 Analysis Run。

- [x] **DTH-006｜ingest 重复执行规则** `[DTH/LIFE]`

  long work 不持行锁；Artifact final status 与 `symbol_inventory_version + 1` 受同一 generation fencing；重复 publish 可吸收，inventory 最多增加一次。

- [x] **DTH-007｜reindex 重复执行规则** `[DTH/LIFE]`，依赖 `DEC-06`

  logical key 包含 Workspace、Build 与 symbol inventory snapshot；旧 inventory intent stale-no-op；同一 snapshot 合并。

- [x] **DTH-008｜analyze 重复执行规则** `[DTH/LIFE/CAN]`，依赖 `G2`

  logical key 按 Analysis Run；reclaim generation 必增；finalize/fail/promotion 都校验 generation；stale result 永远不能成为 winner。

- [x] **DTH-009｜收紧 retry-dispatch** `[DTH/LIFE]`

  active lease 或 pending intent 返回现有 attempt；只有未领取、已修复 DEAD、lease-expired 且无 active owner 才能恢复。终态 immutable Run 不得复活，只能 reprocess 创建新 Run。

- [x] **DTH-010｜历史 reconciliation 工具** `[DTH/OPS]`

  新增 dry-run 优先、可续跑的内部 CLI，仅扫描无 active ownership 的 VERIFYING Upload、pending Artifact、UPLOADED/QUEUED Run；不创建 Occurrence/Run，不放进 Alembic。

  实际目标环境 apply 属于写操作，必须另行审批。

### Gate G3 — Handoff

- [x] DB commit 后 Redis 下线，恢复后自动投递。
- [x] publish 后、ack 前 crash；双 relay；双 Worker；lease reclaim；迟到 owner 全部通过故障注入。
- [x] poison 进入 dead 并告警，不无限 retry。
- [x] verify/ingest/reindex/analyze duplicate 不产生重复领域副作用。
- [x] production producer 不再直接调用 Redis adapter。

G3 的本机回归、PostgreSQL 16 并发、隔离 Redis 中断恢复、静态 producer 边界与
reconciliation 安全证据见 [machine-readable result](evidence/architecture-g3-local-gate.json)。
该 Gate 证明的是本机与一次性依赖上的 handoff 语义；默认配置仍为 legacy/compat，尚未完成
目标内网 outbox/strict 切换、真实 Core/Symbolicator/RustFS 长任务或生产观察。

## 10. Lane CAN — Canonical single ownership

- [x] **CAN-001｜冻结 final-v1 parity corpus** `[CAN/QA]`，依赖 `ARCH-001`

  将当前“Core 输出 + identity/time/engine bind + source context enrich”后的最终 v1 作为兼容基线；同时保留 Core 原始输出，防止比较错对象。

- [x] **CAN-002｜持久化真实 inspect evidence** `[CAN/LIFE]`

  Core inspect 成功后写 deterministic immutable checkpoint；平台据 dump evidence、reported/uploaded/manual facts 解析最终时间，再冻结到 immutable Run context。

  完成标准：同一 Run 重放时间字段完全一致，Core 不再使用当前时钟生成平台时间。

- [x] **CAN-003｜增加 versioned internal analysis context** `[CAN]`

  context 包含最终 identity/time/engine facts、固定 artifact/source bundle、policy versions；旧 Run 由兼容 adapter 从数据库事实构造，不修改历史 Run Spec。

  完成标准：新 Worker 可处理历史 Run；旧 Worker 忽略 additive context。

- [x] **CAN-004｜Core 接管 identity/time/engine** `[CAN/CORE]`

  删除 dump SHA 派生的临时平台 identity 与当前时钟语义；Core 校验实际 engine pin 和输入 context，不允许 Worker静默覆盖 mismatch。

- [x] **CAN-005｜Core 接管 source context** `[CAN/CORE]`，依赖 `DEC-02/05`

  Worker 只 stage verified、已固定进 Run Spec 的 bundle；Core 防御性验证哈希、路径、压缩预算和 policy version，并在获得 frame file/line 后填充 `source_context`。

  完成标准：ZIP bomb、path traversal、损坏或替换对象不越界；enrich failure 按决策退化。

- [x] **CAN-006｜增加 semantic validator** `[CAN/QA]`

  在 JSON Schema 之外验证 identity、blob digest/size、resolved time、engine pin、算法版本、Run/Occurrence 对应关系。

  完成标准：删除 `_bind_platform_identity` 后，错误 identity/time 不可能通过 Gate。

- [x] **CAN-007｜shadow parity** `[CAN/QA]`

  同一输入生成 legacy-bound/enriched v1 与 Core-final v1，主路径仍持久化 legacy。覆盖 Golden、source bundle、历史 Run、时间优先级和 PARTIAL。

  完成标准：字段、enum、nullability、quality、fingerprint、source context 100% 语义一致；确定性部分字节一致。

- [x] **CAN-008｜切到 Core-final** `[CAN/LIFE]`，依赖 `CAN-007/G2`

  Worker 只验证和存储；`_bind_platform_identity`、`attach_source_context` 从 final path 删除。semantic mismatch 阻止 promotion，禁止静默修正。

- [x] **CAN-009｜历史与 rollback compatibility** `[CAN/OPS]`

  旧 v1 保持可读；Run Spec 固定 Core digest 与 assembly mode。shadow/切换期保留 legacy path 一个明确观察窗口；回退只切新 Run 的 mode，既有 Run 仍按固定 digest 执行，或新建 reanalysis。

### 不触发 `analysis-result-v2` 的判据

- 字段集合、requiredness、nullability、enum 和含义不变。
- `schema_version` 仍为 `1.0`。
- time precedence、Build Resolution、quality、fingerprint 算法语义不变。
- `source_context` 只填充 v1 已预留字段。
- 变化只涉及内部 context、执行顺序和 owner。

任一外部字段新增、类型变化、已有字段重新解释或算法语义改变，立即停止 v1 迁移并另行设计 v2。

### Gate G4 — Canonical ownership

- [x] 21/21 Golden、source bundle、时间优先级、历史 v1、PARTIAL parity 全通过。
- [x] 删除任一 Worker post-assembly mutation 后，结果仍正确且 semantic validator 可拦截错误事实。
- [x] 两个 generation 生成不同结果时，只有 winner 可被 HTTP 与 backfill 读取。
- [x] 旧 Core digest 回滚演练完成。

G4 的当前 Core 21/21 Golden、frozen-context parity、source-bundle 防御、semantic fencing 与
按新 Run 回退 mode/digest 的证据见 [machine-readable result](evidence/architecture-g4-local-gate.json)。
该 Gate 没有把 Windows debug Core、fake-Core 平台测试或隔离 Symbolicator外推为 Linux OCI、
RustFS、目标内网部署或生产 shadow 观察；仓库默认仍为 `legacy`。

## 11. Lane REP — HTTP representation

- [x] **REP-001｜建立 response baseline fixtures** `[REP/QA]`，依赖 `ARCH-002`

  覆盖成功、分页、202、错误、SSE、下载、预签名和 Canonical；固定 `X-Request-ID`、content type 与错误 envelope。

- [x] **REP-002｜显式 response models，先 shadow validate** `[REP]`

  关键 route 逐波建模，先校验现有返回，不立即让 FastAPI 过滤。Canonical response 直接引用 `analysis-result-v1.schema.json`；SSE 使用独立 event fixtures，不复制成普通 JSON model。

- [x] **REP-003｜Wave 1：crashcap-ci 路径** `[REP/CI]`

  Workspace、Build、upload、producer、CI-status。激活前证明旧/new server 与旧/new `crashcap-ci` 四象限兼容。

- [x] **REP-004｜Wave 2：Occurrence/Analysis 路径** `[REP/UI]`

  Occurrence、Analysis、threads、modules、events；不得改变 Current Analysis 语义或 Canonical payload。

- [x] **REP-005｜Wave 3：overview/group/Symbol 路径** `[REP/SYM/UI]`

  overview、group、Symbol Health、in-app、download。Symbol projection 迁移字段不得暴露给 `/api/v1`。

- [x] **REP-006｜强化 OpenAPI generation** `[REP/QA]`

  迁移 route 生成 named response，不再退化为 `unknown`；保留 reproducible `openapi:check`，增加 operation identity、schema reference 与 generated drift Gate。

- [x] **REP-007｜浏览器迁移** `[REP/UI]`

  endpoint-by-endpoint 使用 generated wire types；manual types 先变兼容 alias，类型等价后删除。multipart 使用服务端 `part_size`，旧 server 缺字段继续回退 64 MiB。

- [x] **REP-008｜Rust typed decode spike 与迁移** `[REP/CI]`，依赖 `DEC-07`

  保留当前 retry、redaction 和 transport；只替换手写字段读取。decoder 对未知字段宽容，对缺 required/type/enum 严格。

### Gate G5 — Representation compatibility

- [x] 每个 wave 的 wire JSON、status、header 无非预期变化。
- [x] 新客户端 + 旧 server、旧客户端 + 新 server 四象限通过。
- [x] `multipart.part_size` 浏览器行为和 Rust 行为一致。
- [x] 关键 response 不再生成 `unknown`；Canonical 不存在第二套复制模型。

G5 的本机 response baseline、三波 activated model、OpenAPI operation/schema reference、浏览器
generated-type、Rust typed decode 与 `multipart.part_size` 四象限 fixture 证据见
[machine-readable result](evidence/architecture-g5-local-gate.json)。该 Gate 没有外推为真实历史
二进制跨版本联调、浏览器人工 UAT、远端 CI 或目标内网部署；兼容结论限于 checked-in fixture、
本机 API/前端/Rust 测试与 production frontend build。

## 12. Lane SYM — Symbol Health durable projection

- [x] **SYM-001｜冻结 projection 语义** `[SYM/ADR]`，依赖 `DEC-01/03/04`

  明确 Current Analysis ordering、双空 identity、`ignored` 与 affected count 的关系。

- [x] **SYM-002｜实现 deep projection module，shadow-soft** `[SYM]`，依赖 `MIG-003`

  module 只负责从 final Canonical v1 得到 current missing set、按 Occurrence 替换关系、维护 first/last seen、保持人工 triage 状态、写 audit 和提供集合式查询。

  legacy log/count 继续写；新 projection 在独立 savepoint 中 shadow 写，失败只记录 mismatch，不阻断仍依赖 legacy 的 promotion。

- [x] **SYM-003｜实现可续跑 backfill** `[SYM/OPS]`

  权威来源是每个 Occurrence 的 Current Analysis winner Canonical object，不是 OperationLog。每批读取指针快照、验证 v1、短事务锁 Occurrence、再次确认指针未变、幂等 replace、记录 checkpoint。

  object 缺失/损坏/schema-invalid 记录 gap 并阻断切流；raw Dump 已过期不影响从 Canonical 回填。

- [x] **SYM-004｜完整 shadow compare** `[SYM/QA]`

  新旧路径各自产生完整 snapshot，比较 identity 集合、Occurrence 集合、count、winner Run、Workspace 隔离、Build/Artifact 聚合、排序与外部 JSON。

- [x] **SYM-005｜实现 strict writer 切换路径** `[SYM/LIFE]`，依赖 `G2/G4`

  projection、Current Analysis、Group 与 winner 在一个 finalize transaction；projection 失败使 promotion 整体回滚，旧 Current Analysis 保持。

- [x] **SYM-006｜实现整条 read cutover** `[SYM/REP]`，依赖 `G5`

  `/symbols/health`、`/symbols/missing`、Build view 和 batch reprocess 同批切换；禁止部分路径继续 replay。

- [x] **SYM-007｜删除业务 replay，延迟删除 legacy 字段** `[SYM/Cleanup]`

  删除 `active_missing_occurrences` 的业务调用；OperationLog 继续审计。legacy count、旧 writer 与回退开关至少保留两个发布周期并完成真实回滚演练，随后独立 migration 才可删除 shadow 字段。

### Gate G6 — Symbol projection

- [ ] backfill remaining = 0，unresolved gap = 0。
- [ ] relation/current mismatch = 0，shadow mismatch = 0。
- [ ] 至少观察 24 小时且完成至少 100 次 Current Analysis promotion；流量不足用等价并发负载补足。
- [ ] 新读路径不读取 OperationLog，SQL query 数量不随结果行数增长。
- [ ] PostgreSQL 代表性规模 `EXPLAIN` 与外部 JSON parity 通过。

G6 的代码路径、本机 11 项投影/回填测试、一次性 PostgreSQL 16 并发 upsert、真实锁内
pointer recheck、复合索引 `EXPLAIN` 与完整外部 JSON parity 证据见
[machine-readable result](evidence/architecture-g6-local-gate.json)。其中本机合成数据已证明
`backfill_remaining=0`、`unresolved_gap=0`、relation/current mismatch=0 与 shadow mismatch=0；
上面的 G6 发布门禁仍保持未勾选，因为目标数据 backfill、连续 24 小时/100 次 promotion、
目标内网 strict/read 切换和两个发布周期回滚观察均未执行，不能用本机夹具替代。

## 13. 故障与兼容验收矩阵

建议新增：

- `platform/tests/test_task_handoff.py`
- `platform/tests/test_task_handoff_postgres.py`
- `platform/tests/test_outbox_relay.py`
- `platform/tests/test_analysis_lifecycle.py`
- `platform/tests/test_analysis_fencing.py`
- `platform/tests/test_canonical_semantics.py`
- `platform/tests/test_symbol_projection.py`
- `platform/tests/test_symbol_projection_postgres.py`
- `platform/tests/test_http_representation.py`

必须覆盖：

- [x] DB commit 后 Redis 下线，恢复后投递。
- [x] relay publish 后、ack 前 crash。
- [x] 双 relay、双 Worker、lease reclaim、heartbeat 丢失。
- [x] 新 owner 成功后旧 owner 迟到 success/failure。
- [x] duplicate verify 不重复创建 Blob/Occurrence/Run。
- [x] duplicate ingest 只增加一次 symbol inventory version。
- [x] stale reindex 不伪装成新 inventory 完成。
- [x] active lease 下 retry-dispatch 不创建第二 owner。
- [x] unknown schema/task/queue 进入 poison dead。
- [x] 两个 generation 产生不同 Canonical，只有 winner 可读。
- [x] source bundle corrupt、hash mismatch、ZIP bomb、path traversal。
- [x] manual/reported/dump/uploaded time precedence 重放一致。
- [x] missing → matched、matched → missing、missing A → missing B。
- [x] reprocess FAILED、历史 Run 查询不改变 projection。
- [x] 较老 Run 晚完成、两个 Run 并发完成、backfill 与 promotion 竞争。
- [x] backfill 中断/重启/重复运行；Current Canonical 缺失/损坏。
- [x] 双空 identity、同 ID 不同文件名、多 Module 同名、Workspace 隔离。
- [x] legacy/new HTTP 与浏览器/`crashcap-ci` 四象限兼容。
- [ ] migration/relay/Worker/container 重启后的恢复。

上述已勾选项由本机 fixture 或明确命名的隔离 PostgreSQL/Redis 依赖覆盖；最后一项仍缺目标
Compose 中 Worker/container 进程级重启演练，不能用 Redis dispatcher 重建或 relay 容器重启代替。

## 14. 自动化门禁

### 14.1 本机静态与单元门禁

```powershell
cargo fmt --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
python scripts/schema/validate.py

cd platform
uv run ruff check api worker cli tests migrations
uv run mypy api worker cli
uv run pytest -q tests migrations/tests

cd frontend
pnpm openapi:check
pnpm test
pnpm lint
pnpm build
```

### 14.2 聚合与真实依赖门禁

```powershell
python scripts/phase0/verify.py --output phase0-verification.json
python scripts/phase2/gate.py
```

另行执行 PostgreSQL + Redis + RustFS + Core + Symbolicator Compose Gate。SQLite、MemoryTaskDispatcher 或 fake Core 通过不能替代真实依赖证据。

### 14.3 架构静态门禁

- production `dispatcher.enqueue` 只允许在 relay adapter。
- production `AnalysisRun.status` 写入只允许在 lifecycle module。
- Worker final path 不引用 `_bind_platform_identity` 或 `attach_source_context`。
- HTTP/Symbol/Build/reprocess 路径不调用 `active_missing_occurrences`。
- 关键 route 不再返回未建模的 `dict[str, Any]`。
- generated OpenAPI 中关键 response 不含 `unknown`。

## 15. 可观测性

修改 `platform/api/crashcap_api/metrics.py` 与 `docs/operations/phase1-recovery-and-capacity.md`，至少增加：

- task intent：pending/publishing/published/dead、oldest pending age；
- relay：delivery attempts/result、poison、backoff；
- ownership：active/expired claim、generation takeover、heartbeat；
- lifecycle：transition accepted/rejected、terminal、Current Analysis promotion accepted/skipped；
- fencing：stale write discard；
- Canonical：shadow mismatch、semantic validation failure、winner finalize；
- Symbol：backfill remaining/gap、shadow mismatch、strict writer failure；
- object：generation-scoped orphan count/bytes。

结构化日志固定包含 `attempt_id`、task type/queue、logical target、request ID、领域 identity、claim generation、from/to status 和低基数 outcome/reason。异常正文不得进入 metric label。

G7 本地实现把 durable intent/execution gauge 与 relay、ownership、lifecycle、fencing、Canonical、
Symbol 和 generation-orphan counter/histogram 接入统一 `/metrics`，并用固定字段脱敏 formatter
覆盖全部日志记录。机器可读本地证据见
[architecture-g7-local-gate.json](evidence/architecture-g7-local-gate.json)；这些进程内 counter
不能替代监控后端持久聚合，generation orphan counter 也不能替代 RustFS 全量 inventory。

## 16. 灰度、回滚与清理

建议 feature modes：

| 范围 | 模式顺序 | 回滚动作 |
| --- | --- | --- |
| task handoff | `legacy → shadow → outbox` | 保留 intent；只回到兼容镜像与 legacy consumer，不能丢弃 pending intent。 |
| task receipt | `compat → strict` | strict 前必须排空 legacy Redis backlog。 |
| Canonical | `legacy → shadow → core-final` | 新 Run 切回 legacy；历史 Run 按固定 digest/mode 重放。 |
| Symbol projection | `legacy → shadow-soft → strict-writer → projection-read` | 整条 read 回退 legacy；不能混合两种 snapshot。 |
| HTTP representation | route wave 1 → 2 → 3 | 每 wave 独立提交和回滚，wire shape 不变。 |

部署顺序：

1. 备份并记录现有 VERIFYING/pending/UPLOADED、Current Analysis、Redis backlog 和 MissingSymbol 基线。
2. 运行 one-shot additive migration。
3. 部署 rollback-compatible Worker，legacy support 开、strict receipt 关。
4. 部署 relay 空跑并观察。
5. 排空旧 Worker，确认没有旧进程。
6. 先启用 durable verify，再启用 ingest；两类分别完成 duplicate/failure 观察。
7. 开启 Core shadow 与 response-model shadow；运行 Canonical/HTTP parity。
8. 执行 Symbol backfill 与完整 shadow compare。
9. lifecycle/fencing Gate 通过后依次启用 dump-small → dump-large → reindex；Canonical parity 通过后再切 Core-final。
10. Symbol 先 strict writer，稳定后整条 read 切换。
11. 旧 Redis backlog 清零后开启 strict receipt。
12. 每项完成真实 rollback drill；至少保留两个发布周期后再 cleanup。

回滚规则：

- relay 故障时继续写 outbox并修复 relay；不得立即直写 Redis 制造无审计 duplicate。
- 启用后只回滚到认识新 revision、支持 fencing/outbox 且 flags 为 legacy 的兼容镜像。
- 不做紧急数据库 downgrade；首次切流版本不删除表或 legacy 字段。
- 已固定新 Core digest 的 Run 继续使用该 digest，或终止后新建固定旧 digest 的 reanalysis。
- orphan cleanup 独立执行，按 TTL、引用检查和 audit；代码 rollback 时不删除对象。
- 目标环境 reconciliation/backfill apply、数据修复与 orphan 删除均需独立审批。

## 17. 总体完成定义

- [ ] `G0–G6` 全部通过并留存机器可读证据。
- [x] 五项 deletion test 均通过：旧浅 seam 删除后系统仍由唯一 deep module维持正确行为。
- [ ] 故障注入证明零 lost intent、零 duplicate side effect、零 stale winner overwrite。
- [ ] Canonical v1、`/api/v1`、旧浏览器与旧 `crashcap-ci` 兼容矩阵通过。
- [ ] Current Analysis、Group、Symbol projection 的并发不变量零违规。
- [x] OperationLog 不再承担当前状态读取。
- [ ] one-shot migration、兼容回滚、真实 rollback drill 均完成。
- [ ] 本机 Gate、真实 Compose Gate、目标内网 pilot、浏览器 UAT 分开报告；不得用本机结果代替远端或目标证据。
- [ ] cleanup 只在两个发布周期、零 mismatch、零 unresolved gap、回滚演练完成后执行。

## 18. 推荐领取顺序

1. `ARCH-001–005`：冻结语义、失败模型和 ADR。
2. `MIG-001–004`：one-shot migration、additive schema、兼容镜像。
3. 并行领取：`LIFE-001/002`、`DTH-001/002/003`、`CAN-001/002/003`、`REP-001/002`、`SYM-001/002/003`。
4. 汇合：`LIFE-005/006` + `CAN-004–007` + Symbol shadow compare。
5. 分 task type 切 outbox，再切 Core-final、HTTP waves、Symbol strict/read。
6. 目标 Gate、rollback drill、两个发布周期观察后 cleanup。
