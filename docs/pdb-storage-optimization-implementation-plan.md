# PDB 存储优化改造实施计划

状态：实施中（Wave 0–4 代码已落盘；本机主栈已从空卷启用去重/压缩 active 与 HTTP symbol
source 并完成真实生成式 DMP 回归；仓库安全默认仍关闭，目标 UAT/清理 Gate 未执行）。基线为
`main@347ca154bc79`，最后更新：2026-08-27。

本文把 PDB 存储优化拆成可逐项勾选、可并行实施、可独立回滚的任务。实施目标不是删减
Build 的精确 Artifact 清单，也不是用低质量符号替代完整 PDB，而是在保持分析结果、
Workspace 隔离和不可变 Build 语义的前提下，消除重复原始副本，并把唯一 PE/PDB Blob
压缩存储。目标内网真实 UAT 和清理宽限期 Gate 未通过前，不删除任何仍作为回滚来源的
raw/canonical 对象。

关联权威文档：

- [设计文档](design.md)
- [实施路线图](implementation-roadmap.md)
- [ADR-0010：Build 内容身份与 Publication](adr/0010-identify-builds-by-content-and-track-publications.md)
- [ADR-0011：Workspace 范围 Artifact Blob 去重](adr/0011-deduplicate-artifacts-as-workspace-scoped-blobs.md)
- [Artifact Blob 去重上线手册](operations/artifact-blob-dedup-rollout.md)
- [目标内网 UAT 清单](operations/phase1-target-uat-checklist.md)
- [真实大 PDB 本地 UAT](evidence/large-pdb-uat-20260824.md)

若本文与已接受 ADR 或机器契约冲突，以 ADR/契约为准；先更新设计与 ADR，再实施代码。

## 1. 结论与推荐交付边界

推荐分三个可独立产生收益的交付包，不做一次性大切换：

| 交付包 | 主要动作 | 预期收益 | 主要兼容性变化 |
| --- | --- | --- | --- |
| `PDBS-P0` | 启用现有 Blob 去重、清理 legacy、增加终态 Upload GC、收紧下载缓存 | 立即消除暂存和 per-Build 原始副本 | additive DB 生命周期字段，不改变 Blob payload |
| `PDBS-P1` | 引入 `zstd-v1` canonical Blob、双格式 Reader、回填与客户端可选压缩传输 | 唯一 PDB 通常再降低 75%–90% | additive payload 格式与 delivery-v2 |
| `PDBS-P2` | 将 Unified 原始符号目录改为按需物化/HTTP source 和有界缓存 | 消除第二份永久原始 PDB | 改变符号供应路径，保留回退源 |

`PDBS-P0` 可在 `PDBS-P1` ADR 评审期间先行；`PDBS-P2` 必须等待 `PDBS-P1` 真实 DMP
结果等价和恢复演练通过。每个交付包都应单独提交、单独留证、单独作 Go/No-Go。

## 2. 当前事实与容量基线

### 2.1 当前实现

- Artifact Blob 身份是 `(workspace_id, server_verified_sha256)`；不同 Workspace 不复用。
- Artifact/Expectation 仍属于精确 Build；`entrypoint|owned|dependency` 角色和每条期望不得因
  字节复用而删除。
- 当前 canonical key 为
  `artifact-blobs/{workspace_id}/{sha256[:2]}/{sha256}`，内容是未压缩原始 PE/PDB。
- `CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE=off|shadow|active` 和压缩同名开关已实现。2026-08-27
  重建后的本机主栈 API/所有 Worker 运行值均为 `active`，Gateway 使用 HTTP symbol source；
  Compose/应用安全默认仍是 `off|filesystem`，目标环境尚未灰度。
- 当前成功上传会留下 `uploads/` 暂存对象；Artifact 再复制到 `raw-builds/`，Blob 模式再复制
  到 `artifact-blobs/`，`symsorter` 又在 Unified volume 写入原始 PE/PDB。
- legacy copy 只有显式 dry-run/apply 清理；本里程碑没有自动 Artifact Blob GC。
- Symbolicator `downloaded` 与 `derived` 缓存当前都按 30 天未使用时间清理。

### 2.2 2026-08-27 重建前本机只读快照（历史）

以下是全量清卷重建前的 Windows/Docker Desktop 主栈快照，已不代表当前数据量，也不是目标
内网容量证明：

| 层 | 对象/数据量 | 逻辑字节 |
| --- | ---: | ---: |
| RustFS `uploads/` | 15 个终态对象 | 1,214.35 MiB |
| RustFS `raw-builds/` | 22 个对象（含少量 manifest） | 1,210.78 MiB |
| RustFS `artifact-blobs/` | 12 个 verified Blob | 857.45 MiB |
| Unified symbols volume | 6 个已发布 pair 的物化数据 | 约 858 MiB |
| Symbolicator cache volume | downloaded + derived | 约 805 MiB |

数据库中 22 个 verified PE/PDB Artifact 引用 12 个唯一 Blob；6 个 pair 均为 `published`，
未解析 backfill gap 为 0，verified 但未绑定 Blob 的 Artifact 为 0。现有 14 条 retained legacy
copy 约 1,211 MiB。

### 2.3 真实样本基准

`E:\cplus_proj\light-streamer-ng\deploy\bin\lightstreamer.pdb`：

- 原始：357,560,320 B（约 341.0 MiB）。
- NanaZip 6.5 Zstandard 中档实测：37,371,937 B（原始的 10.45%）。
- 本机压缩约 0.50 秒、解压约 0.50 秒，解压 SHA-256 与原始完全一致。
- 另一个 108.2 MiB 的 `xrtc_router.dll.pdb` 压缩后约为原始的 21.86%。
- 两个 341 MiB lightstreamer PDB 做固定块跨版本去重只节省约 28%，不作为首选方案。

该基准仅用于制定初始门槛；正式实现必须使用生产库、真实 20–100 个 Artifact 语料重新测量。

## 3. 必须保持的不变量

以下任一条件被破坏都应立即阻断发布：

1. **Manifest 不变**：每个 Build 继续保留完整、精确、不可变的模块与 Expected Artifact；
   不因共享或压缩删除 `xrtc_router` 等 dependency。
2. **逻辑身份不变**：Blob 的业务身份仍是 Workspace + 解压后原始 SHA-256；压缩字节哈希
   只能用于存储完整性，不能替代 PE/PDB 身份。
3. **完整 PDB 不降质**：继续拒绝 FASTLINK；不以 stripped/public-only PDB 替代完整 PDB。
4. **服务端建立信任**：客户端 hash、压缩 header 或 stored hash 都只是 hint；Worker 必须验证
   stored payload、解压后的 size/SHA-256、PE/PDB 格式和 code/debug ID。
5. **Workspace 隔离**：跨 Workspace 不复用、不披露 Blob、对象键、命中状态或 cache key。
6. **Build seal 不回退**：对象丢失或缓存淘汰不能静默 unseal 历史 Build；应报告存储/恢复事件。
7. **Occurrence 语义不变**：符号存储迁移和 reprocess 不得增加 Occurrence/crash 次数。
8. **Canonical 结果不变**：同一 DMP/Build 的异常码、崩溃线程、物理帧、函数、文件、行号、
   inline、quality warning 和 Exact grouping 语义不得因存储编码改变。
9. **回执最小化**：客户端/UI 不返回对象键、压缩临时路径、其他 uploader、凭据或预签名 URL。
10. **删除必须可审计**：只允许精确、状态驱动、默认 dry-run 的清理；不得前缀模糊删除共享 Blob。

## 4. 范围与非目标

### 4.1 本计划范围

- Windows x64 MSVC 完整 PE/PDB。
- Workspace 范围 Artifact Blob 去重的正式启用。
- `uploads/` 终态 payload 生命周期。
- raw canonical Blob 的 Zstandard 存储编码。
- raw/zstd 双读、回填、恢复、清理和回滚窗口。
- `crashcap`/`crashcap-ci` 可选压缩传输能力。
- Workspace Unified symbols 的按需供应和 Symbolicator 缓存治理。
- API、Worker、CLI、运维、指标、前端状态展示和证据产物。

### 4.2 明确非目标

- 不压缩或迁移 DMP、source bundle、analysis JSON、公司公共 SDK、Microsoft 公共符号缓存。
- 不改变 Build content fingerprint、Build resolution、Occurrence/Run/Current Analysis 语义。
- 不做跨 Workspace 去重。
- 不引入 FASTLINK、stripped PDB 或仅凭文件名/Version 的符号匹配。
- 不把 Crash-Cap 变成安装包或通用制品分发服务。
- 第一阶段不做跨版本 delta、内容定义分块或全局 chunk store。
- 不把本地 Docker Desktop 结果表述为目标 Linux/内网或生产证明。

## 5. 目标架构

### 5.1 权威数据与缓存层次

```text
Build Manifest / Expectation（精确且不可变）
                 │
                 ▼
Artifact（Build 范围绑定，投影逻辑 SHA/size/identity）
                 │
                 ▼
Artifact Blob（Workspace + 原始 SHA-256）
  ├─ logical: kind/raw_size/raw_sha256/code_id/debug_id
  └─ payload: encoding/stored_size/stored_sha256/object_key
                 │
                 ▼
RustFS: artifact-blobs-v2/.../{raw_sha256}/zstd-v1
                 │
                 ├── Worker 有界解压、校验、临时物化
                 └── 内部 symbol source 按需流式解压
                                      │
                                      ▼
                         Symbolicator downloaded/derived cache
                         （可删除、可重建、有 TTL/容量告警）
```

### 5.2 建议数据模型

现有 `ArtifactBlob.sha256/size/kind/code_id/debug_id` 保持“原始逻辑字节”语义。新增字段建议：

| 字段 | 语义 |
| --- | --- |
| `payload_encoding` | `identity` 或固定配置的 `zstd-v1` |
| `payload_size` | 对象存储中实际字节数 |
| `payload_sha256` | 对象存储 payload SHA-256 |
| `payload_object_key` | 实际 payload key；不得通过普通 API 暴露 |
| `payload_verified_at` | stored + logical 双重验证完成时间 |
| `payload_format_version` | 显式存储格式版本，首版为 `artifact-blob-payload-v1` |

兼容策略：

- migration 只做 additive 变更；现有行默认 `identity` 并从当前字段回填 payload 元数据。
- 所有 Reader 先支持 `identity|zstd-v1`，Writer 仍保持 `identity`；Reader 部署完成并验证后，
  才允许 Writer 进入 `shadow/active`。
- 现有 `Artifact.object_key` 和 `ArtifactBlob.object_key` 的直接读取必须全部收口到统一
  `BlobMaterializer`；在此之前不得创建只有压缩 payload、没有 raw 回滚副本的 Blob。
- 暂定迁移名为 `0008_artifact_blob_payloads_and_upload_gc.py`；实施时若迁移序号已占用则顺延，
  不改写已发布 migration。

### 5.3 对象键

建议使用新前缀，避免旧 Reader 把压缩对象误当原始 PDB：

```text
artifact-blobs-v2/{workspace_id}/{raw_sha256[:2]}/{raw_sha256}/zstd-v1
```

对象 metadata 只用于诊断/恢复，PostgreSQL 才是权威：

```text
crashcap-payload-format=artifact-blob-payload-v1
crashcap-payload-encoding=zstd-v1
crashcap-raw-sha256=<hex>
crashcap-raw-size=<decimal>
crashcap-payload-sha256=<hex>
```

### 5.4 Zstandard profile

`zstd-v1` 必须冻结下列参数并记录在 ADR/代码常量中：实现库和版本、level、checksum flag、
content-size flag、worker threads、最大窗口、最大逻辑输出和错误语义。对象身份不依赖压缩字节
确定性，但 `payload_sha256` 必须在每次写入后重新计算并落库。

首选中档 streaming profile；LZMA2 只可作为离线冷归档实验，不进入首期在线 ingest。

## 6. 泳道、依赖与并行关系

| 标记 | 泳道 | 主要产物 |
| --- | --- | --- |
| `MODEL` | 数据模型/迁移 | additive migration、约束、backfill checkpoint |
| `STORE` | 对象存储/编码 | codec、materializer、对象键、完整性检查 |
| `PLAT` | API/Worker | delivery、ingest、GC、状态机、任务 fencing |
| `CLI` | 发布客户端 | raw 兼容、压缩传输 v2、回执 |
| `SYM` | 符号运行时 | symsorter、内部 source、缓存、reindex |
| `UI` | 前端 | Build/Artifact 存储状态与节省量展示 |
| `QA/OPS` | 质量与运维 | Gate、UAT、指标、备份恢复、清理与告警 |

总体依赖：

```text
PDBS-A 基线/ADR/语料
   ├──────── PDBS-B 现有去重 active + legacy cleanup
   ├──────── PDBS-C Upload GC
   └──────── PDBS-D 双格式 Reader + zstd payload
                          │
                          ├── PDBS-E 历史 Blob 压缩回填/清理
                          ├── PDBS-F 客户端压缩传输（可并行）
                          └── PDBS-G 按需 symbol source/cache
                                                │
                                                └── 第 9–12 节目标 UAT/推广与 FINAL Gate
```

`PDBS-B` 与 `PDBS-C` 可并行；`PDBS-D` 的 ADR/codec/Reader 可与二者并行开发，但压缩 Writer
不得先于双格式 Reader 上线。`PDBS-F` 不是 `PDBS-E` 的前置条件；服务器可先接收 raw 再压缩。

## 7. 实施任务

已勾选项表示代码、契约或本机可复核产物已经落盘并通过对应自动测试；不表示目标环境已灰度。
截至 2026-08-27，已冻结并逐个验证 25 个批准本机真实 PE/PDB 样本；仍缺接近 2 GiB PDB、
不可压缩对照和更多产品族，因此 A03 尚未完成。25 个样本 zstd 往返均通过 SHA-256，PDB
aggregate stored/raw 为 10.81%，单文件 p95 为 25.02%；固定 Symbolicator 镜像 HTTP source
spike 和本机独立 PostgreSQL 16/Redis 7.4 集成已通过。真实 lightstreamer DMP 对照、目标
PostgreSQL/Redis/S3 集成、目标内网备份恢复/UAT 及任何清理 apply 均保持未完成。未通过这些
Gate 前，仓库和未显式配置的部署仍默认 `off|filesystem`，不删除 raw canonical、legacy 或
Unified 回滚数据；本机主栈通过外部运行配置显式启用 `active|http`。
另已用一份真实生成的 x64 MSVC DMP/PE/PDB 在全新 PostgreSQL、zstd-only 对象卷和空
Symbolicator cache 中完成 filesystem 与数据库 HTTP source 对照：除运行时间戳外 Canonical
全量相等，冷缓存实际回源、热缓存零回源；同尺寸单 bit 损坏被连续 503 拒绝，未产生错误业务
函数，并生成 `symbolicator_failed` 使平台判为 PARTIAL。证据见
[PDB storage real-DMP equivalence](evidence/pdb-storage-real-dmp-equivalence-20260827.md)。该样本是
Crash-Cap 生成式 Golden，不是 lightstreamer 产品事故，因此 A05/G01 等目标 Gate 仍不勾选。
同一 Golden 已进一步完成本机备份恢复预演：从 PostgreSQL custom dump 与带逐对象 SHA-256
清单的 zstd-only 对象归档恢复到全新 PostgreSQL/对象/cache/空 Unified 卷，10 项检查全部通过，
恢复前后 Canonical 归一化 SHA-256 相同；归档对象单 bit 损坏被失败原子地拒绝，目标对象卷保持
零文件。证据见 [PDB storage backup/restore real-DMP evidence](evidence/pdb-storage-backup-restore-20260827.md)。
该预演使用本机对象卷而非目标 RustFS，且不是产品事故 DMP，所以 E06/E03/G06/FINAL-07 仍不勾选。
同一 DB-backed zstd-only 路径还完成 source/cache 故障恢复预演：Symbolicator 重启后持久 cache
可在 source 停机时继续生成完全相同的 Canonical；空 cache + source 停机只产生
`symbolicator_failed` 和零业务符号，source 恢复并重建 cache 后再次 206 回源并恢复同一 Canonical。
证据见 [PDB storage source/cache recovery](evidence/pdb-storage-source-recovery-20260827.md)。
本机容量报告已使用主库只读快照在隔离 PostgreSQL 16 中迁移到 0009 后生成，并对实时 RustFS/
volume 只读扫描：Artifact Blob 与 Upload 的 DB/对象字节差均为 0；raw-builds 多出的 2,704 B
来自 8 个 manifest，Unified 多出的 733 B 来自 symsorter 布局元数据。该跨存储快照不是原子
快照，也不是目标环境证据。随后本机主栈已完整删除容器、数据卷、网络与本地镜像并无缓存重建；
在真实发布中两个不同 Build 的同一 PE/PDB 复用 2 个 Blob，PDB zstd payload 为原始的 17.89%，
配套真实生成式 DMP 经 HTTP source 得到 COMPLETE、业务函数和源码行。验收数据随后再次清卷，
当前交付栈为空库/空 RustFS。证据见
[PDB storage main-stack active rebuild](evidence/pdb-storage-main-stack-active-rebuild-20260827.md)。

### 7.1 PDBS-A：决策冻结、容量基线与测试语料

- [x] **PDBS-A01｜记录 ADR-0014** `[MODEL/STORE/SYM]`。冻结 raw identity、payload encoding、
  双读顺序、对象键、删除窗口、symbol source 方案和回滚限制。完成标准：ADR accepted，明确
  `Artifact.object_key` 兼容策略及旧 Worker 不能读取 zstd-only Blob 的风险。
- [x] **PDBS-A02｜建立容量盘点命令** `[QA/OPS]`。只读汇总 PostgreSQL Artifact/Blob 引用、
  RustFS prefix、terminal Upload、legacy copy、Unified volume、Symbolicator downloaded/derived。
  完成标准：输出 JSON + Markdown，按 Workspace/kind/state 聚合，不泄漏对象键或凭据。
- [ ] **PDBS-A03｜冻结 20–100 个真实 Artifact 压缩语料** `[QA]`。至少包含 lightstreamer、
  xrtc、不同版本大 PDB、小 PDB、PE、接近 2 GiB 上限样本和不可压缩对照；仓库只提交
  hash/size/授权/期望，真实二进制留在批准私有位置。
- [x] **PDBS-A04｜建立压缩基准 runner** `[STORE/QA]`。报告 raw/stored ratio、吞吐、CPU、
  峰值 RSS、临时磁盘、解压 SHA 和 identity；失败时输出 bounded error。
- [ ] **PDBS-A05｜冻结分析等价基线** `[CORE/SYM/QA]`。选择全部 Golden 与至少一个真实
  lightstreamer DMP，保存 legacy 路径的 Canonical、raw Symbolicator、函数/文件/行/inline、
  quality、Exact 和耗时作为对照。
- [x] **PDBS-A06｜定义数据保留值** `[OPS]`。评审并冻结建议初值：ACCEPTED Upload payload
  24 小时、REJECTED/QUARANTINED 7 天、legacy raw 至少两个发布周期且不少于 14 天、
  Symbolicator downloaded 1–3 天、derived 30 天。完成标准：值可配置、有上下界和变更审计。

#### Gate PDBS-A

- [ ] **GATE-PDBS-A01｜ADR、语料、容量基线和 legacy Canonical 对照均可复核**。
- [ ] **GATE-PDBS-A02｜所有删除窗口和目标环境证据责任人已明确**。

### 7.2 PDBS-B：正式启用现有 Workspace Blob 去重

- [ ] **PDBS-B01｜重新运行 dedup 回填 dry-run** `[OPS]`，依赖 GATE-PDBS-A。记录 scanned、
  already_linked、gap、canonical HEAD/size 和当前备份身份。
- [ ] **PDBS-B02｜执行 shadow 观测** `[PLAT/OPS]`。API 与所有 Worker 使用相同模式；检查
  delivery、conflict、verification、backfill 指标，无非预期 gap/identity conflict。
- [ ] **PDBS-B03｜执行 active 并发 UAT** `[CLI/PLAT/QA]`。覆盖 `upload|wait|reused`、lease
  takeover、Build A/B 共享 xrtc、旧客户端兼容、pair idempotency 和 sealed Build。
- [ ] **PDBS-B04｜目标环境 active 灰度** `[OPS]`。先单 Workspace/发布管线，再扩大；保留
  `off` 回退开关，不降级 migration 0007。
- [ ] **PDBS-B05｜legacy cleanup dry-run/apply** `[OPS]`。active UAT 通过后按现有精确记录
  删除 per-Build legacy copy；保留 manifest、canonical Blob 和审计记录。
- [ ] **PDBS-B06｜复核物理空间** `[QA/OPS]`。对象存储实际字节下降应与 dry-run 预测相符，
  差异超过 2% 必须解释；Artifact/Build/Publication/analysis 结果不得变化。
- [ ] **PDBS-B07｜收紧 downloaded cache 保留期** `[SYM/OPS]`。在 Unified raw 仍完整可用时，
  将 downloaded 与 derived 分开定标；先 dry-run/观测 miss 和 refetch，再把 downloaded 调整到
  已评审的 1–3 天，derived 暂保留 30 天。

#### Gate PDBS-B

- [ ] **GATE-PDBS-B01｜所有 API/Worker 均为 active，delivery-v1 广告正确**。
- [ ] **GATE-PDBS-B02｜重复 xrtc 只保留一个 Workspace Blob，两个 Build 仍各有完整期望**。
- [ ] **GATE-PDBS-B03｜目标真实 DMP 的 dependency 函数/文件/行解析无退化**。
- [ ] **GATE-PDBS-B04｜legacy cleanup 后无对象误删，回滚与修复演练通过**。
- [ ] **GATE-PDBS-B05｜downloaded cache 收紧后冷/热分析、refetch 和磁盘下降符合门槛**。

### 7.3 PDBS-C：终态 Upload payload GC

- [x] **PDBS-C01｜增加 Upload payload 生命周期字段** `[MODEL]`。至少记录
  `payload_deleted_at/deletion_reason/deletion_attempts`；数据库 Upload 行和回执继续保留。
- [x] **PDBS-C02｜实现统一 eligibility 判定** `[PLAT]`。只有 terminal Upload 且下游权威对象
  已存在、size/hash/状态一致、无当前 claim/任务 lease 时才可删除；DMP、PE/PDB、source bundle
  分开处理。
- [x] **PDBS-C03｜实现 fenced sweeper** `[PLAT/OPS]`。默认 dry-run，按 ID 游标分页，单条删除，
  删除后事务记录；Worker 在“copy 后 commit 前”“commit 后 delete 前”崩溃均能幂等收敛。
- [x] **PDBS-C04｜为拒绝对象设置取证窗口** `[OPS]`。REJECTED/QUARANTINED 不立即删除；到期后
  仍只删 payload，不删状态、reason 和 operation log。
- [x] **PDBS-C05｜增加指标与告警** `[QA/OPS]`。包括 terminal payload bytes/age、删除 outcome、
  ineligible reason、orphan payload、失败重试；label 不含 Workspace/SHA/文件名。
- [x] **PDBS-C06｜补齐 GC 测试** `[QA]`。覆盖并发 complete、claim takeover、Worker 重启、
  下游对象损坏/缺失、重复 sweeper、跨 Workspace、S3 delete 成功但 DB commit 失败。
- [ ] **PDBS-C07｜历史 Upload dry-run/apply** `[OPS]`。先目标外备份/清单，再分批删除；记录
  删除对象数、字节数、失败项和剩余 age 分布。

#### Gate PDBS-C

- [ ] **GATE-PDBS-C01｜不存在超过保留期且仍有 payload 的 ACCEPTED Upload**。
- [ ] **GATE-PDBS-C02｜删除 payload 后 GET Upload、Build、Occurrence、reprocess 行为符合契约**。
- [ ] **GATE-PDBS-C03｜故障注入中无活跃上传或唯一权威对象被删除**。

### 7.4 PDBS-D：双格式 Reader 与 zstd canonical Writer

- [x] **PDBS-D01｜实现 additive migration** `[MODEL]`。新增 payload 字段、约束、索引和 raw
  rollback-copy 记录；PostgreSQL/SQLite migration 测试通过，存在 zstd-only Blob 时拒绝 downgrade。
- [x] **PDBS-D02｜实现 `ArtifactBlobCodec`** `[STORE]`。streaming identity/zstd encode/decode，
  固定 `zstd-v1` profile，限制最大输出为既有 PE 512 MiB、PDB 2 GiB，拒绝截断、尾随、checksum
  错误、超长输出和声明 size 不一致。
- [x] **PDBS-D03｜实现 `BlobMaterializer`** `[STORE]`。统一处理 HEAD、payload SHA、流式解压、
  raw SHA/size、临时文件原子性和清理；任何调用方不得自行直接下载 `ArtifactBlob.object_key`。
- [x] **PDBS-D04｜迁移全部 Reader** `[PLAT/SYM/OPS]`。至少覆盖 ingest 重试、pair publish、
  reindex、analysis input staging、backfill、emergency impact/delete、导出、恢复与测试 helper。
- [x] **PDBS-D05｜实现压缩 shadow Writer** `[STORE/PLAT]`。仍以 identity canonical 为权威，
  旁路生成 zstd payload并完整读回校验；记录 ratio/CPU/failure，不改变 Artifact 绑定。
- [x] **PDBS-D06｜实现压缩 active Writer** `[STORE/PLAT]`。新 verified Blob 写入新 prefix，
  先验证 stored payload，再 materialize raw 做 identity 检查，最后事务性绑定；旧 raw copy 进入
  rollback 表而非立即删除。
- [x] **PDBS-D07｜更新 reuse/claim 判定** `[PLAT]`。`reused` HEAD 检查使用 payload size/hash/
  encoding，不把 compressed HEAD size 与 logical size 比较；claim identity 仍用 raw SHA。
- [x] **PDBS-D08｜更新 pair publish** `[SYM]`。PE/PDB 均通过 materializer；同一 pair 并发只做
  一次发布；临时 raw 在失败/成功后都清理；symsorter 结果仍校验原始 SHA。
- [x] **PDBS-D09｜增加 API/回执/UI 投影** `[PLAT/UI]`。可展示 encoding、logical/stored size、
  savings、materialization/cache 状态；不得暴露 key、临时路径或跨 Workspace 命中信息。
- [x] **PDBS-D10｜增加可观测性** `[QA/OPS]`。压缩/解压 seconds、logical/stored bytes、ratio、
  corruption、materialization、temp bytes、fallback；所有 label 有界。

#### Gate PDBS-D

- [ ] **GATE-PDBS-D01｜双格式 Reader 在 Writer=identity 时完成一个发布周期且零读取差异**。
- [ ] **GATE-PDBS-D02｜shadow 语料 100% 解压 SHA/size/identity 一致，silent corruption=0**。
- [x] **GATE-PDBS-D03｜PDB aggregate stored/raw ≤ 25%，单文件 p95 ≤ 35%**；不满足则评审
  profile/语料，不通过修改统计口径掩盖。
- [ ] **GATE-PDBS-D04｜341 MiB 真实 PDB 的额外 ingest p95 ≤ 5 秒、materialize p95 ≤ 2 秒**；
  目标硬件若不同必须重新定标并记录。
- [x] **GATE-PDBS-D05｜streaming codec 峰值 RSS ≤ 256 MiB，临时磁盘有硬上限与预检查**。

### 7.5 PDBS-E：历史 Blob 压缩回填与 raw canonical 清理

- [x] **PDBS-E01｜实现 Blob 级 backfill** `[STORE/OPS]`。按 `ArtifactBlob.id` 游标分页；dry-run
  也读取 raw、压缩、解压、验证但不写；apply 写 zstd payload、读回双 hash/identity 后切换。
- [x] **PDBS-E02｜实现 checkpoint/gap** `[MODEL/OPS]`。记录 object missing/corrupt、stored corrupt、
  logical mismatch、identity rejected、temp capacity、codec failure；重跑只产生 already-linked 或
  可解释 gap。
- [x] **PDBS-E03｜保留 raw rollback copy** `[OPS]`。切换后的 raw canonical 进入 Blob 级 legacy
  表；至少两个发布周期且不少于 14 天内不得删除。
- [x] **PDBS-E04｜实现 raw cleanup** `[OPS]`。默认 dry-run；只删精确记录且当前 Blob 已为
  verified zstd、zstd 对象可完整 materialize、没有未完成回滚演练时才允许 apply。
- [x] **PDBS-E05｜容量与成本复核** `[QA/OPS]`。按 Workspace/kind 报告 logical、stored、legacy、
  staging、cache；S3 list、DB sum、volume bytes 三者差异必须解释。
- [ ] **PDBS-E06｜备份恢复演练** `[OPS]`。从 PostgreSQL + 仅 zstd canonical RustFS 备份恢复到
  空 Unified/cache volume，重建 symbols 并重跑真实 DMP。
  本机前置演练已用 PostgreSQL custom dump + 带逐对象 SHA-256 清单的 zstd-only 本地对象归档
  恢复到全新卷，并用生成式 Golden DMP 证明 Canonical 等价；仍缺目标 RustFS 和产品事故 DMP。

#### Gate PDBS-E

- [ ] **GATE-PDBS-E01｜所有 eligible Blob 已 zstd 或有已签收 gap，不能静默漏过**。
- [ ] **GATE-PDBS-E02｜raw cleanup 前后 Build/Artifact/Publication/Occurrence/Run 计数一致**。
- [ ] **GATE-PDBS-E03｜恢复后的真实 DMP Canonical 与 legacy 基线语义等价**。
  本机生成式 Golden 的完整 Canonical 已等价；目标产品 DMP 尚未通过，故不勾选。
- [ ] **GATE-PDBS-E04｜raw 删除后只允许回滚到支持双格式 Reader 的镜像**，运行手册已明确。

### 7.6 PDBS-F：客户端压缩传输 v2（可与 E 并行）

- [x] **PDBS-F01｜定义 `artifact-delivery-v2`** `[PLAT/CLI]`。请求显式区分 logical raw
  `size/sha256` 与 wire `encoding/size/sha256`；服务端仍以 logical identity 建 claim。
- [x] **PDBS-F02｜API 支持 raw/zstd 上传** `[PLAT]`。旧 delivery-v1 和普通 upload 继续可用；
  presigned multipart 按 wire size 分片，complete 后同时验证 wire 与 logical。
- [x] **PDBS-F03｜Rust `crashcap` 客户端 streaming 压缩** `[CLI]`。不把整个 PDB 读入内存，
  支持临时空间预检、取消、重试、multipart、敏感信息最小化和 raw fallback。
- [x] **PDBS-F04｜能力协商与降级** `[CLI/PLAT]`。只有服务广告 v2 才发送 zstd；旧服务自动 raw，
  ordinary 4xx 不无限重试，压缩失败可诊断但不伪造成功。
- [ ] **PDBS-F05｜网络基准** `[QA]`。记录 raw 与 v2 的客户端 CPU、临时盘、wire bytes、总发布
  时间和 multipart 数；341 MiB 样本 wire bytes 目标至少降低 80%。

#### Gate PDBS-F

- [ ] **GATE-PDBS-F01｜旧客户端、v1 客户端、v2 客户端发布同一 Build 均成功且回执兼容**。
- [ ] **GATE-PDBS-F02｜wire corruption/截断/伪造 logical hash 均被拒绝且不创建 trusted Blob**。

### 7.7 PDBS-G：按需符号源与有界缓存

该阶段决定能否消除第二份永久原始 PDB。只压缩 RustFS 而永久保留 Unified `debuginfo`，
100 个 341 MiB PDB 仍会在 symbol volume 占约 33.3 GiB。

- [x] **PDBS-G01｜完成 pinned Symbolicator 26.7.2 source spike** `[SYM/QA]`。验证内部 HTTP
  source + unified layout 的 GET/HEAD/path/casing/cache 行为；不得以 master 文档代替固定镜像实测。
- [x] **PDBS-G02｜实现内部 Workspace symbol source** `[SYM/PLAT]`。按 Workspace + debug ID
  解析已发布 pair，通过 materializer 流式返回 raw PE/PDB；服务只在 analysis 网络可达，不接受
  任意对象键或外部 URL。
- [x] **PDBS-G03｜更新 policy gateway** `[SYM]`。继续拒绝请求方 sources/scraping；由网关注入
  deployment-owned HTTP source，source ID 包含 Workspace + inventory version，Microsoft source
  仍使用稳定全局 ID。
- [ ] **PDBS-G04｜缓存治理** `[SYM/OPS]`。downloaded 与 derived 分开 TTL；增加 cache bytes/age/
  eviction/miss/refetch 指标和磁盘高水位告警。缓存删除不得改变 Blob/Build 状态。
  当前已按固定 26.7.2 的物理目录映射提供 downloaded/derived bytes/files/oldest-age/scan 指标、
  TTL 和磁盘告警，并复用原生 `symbolicator_caches_size_*_removed_total` 淘汰计数；但该镜像 OTel
  实测不暴露 hit/miss/refetch，exporter 明确报告 `supported=0`，因此本项仍不勾选。
- [ ] **PDBS-G05｜冷/热性能测试** `[SYM/QA]`。空缓存第一次真实 DMP、同 DMP 热缓存、多个 Build、
  并发请求、Symbolicator 重启、source 重启和网络超时均有记录。
  当前单 Golden 已完成空缓存冷跑、同 DMP 热跑、Symbolicator 重启、source 停机与恢复；持久
  cache 在 source 停机时没有回源且 Canonical 不变。多个 Build、并发、显式网络延迟/超时和目标
  p95 尚未执行，故不勾选。
- [ ] **PDBS-G06｜空 volume 恢复** `[SYM/OPS]`。删除并重建测试环境 Unified/cache volume 后，
  仅凭 PostgreSQL + zstd Blob 完成 symbols 重建和真实 DMP 分析。
  本机全新对象/cache/空 Unified 卷恢复已通过；目标 RustFS 与产品事故 DMP 尚未执行，故不勾选。
- [ ] **PDBS-G07｜Unified raw 清理** `[OPS]`。按 Blob/pair 影响报告和宽限期删除永久物化 raw；
  不删除 company SDK，不删除 Microsoft cache，不按 Workspace 前缀盲删。

#### Gate PDBS-G

- [ ] **GATE-PDBS-G01｜legacy filesystem source 与 HTTP source 的 Golden/真实 DMP 结果等价**。
- [ ] **GATE-PDBS-G02｜空缓存冷分析 p95 回归 ≤ 10% 或 ≤ 2 秒（二者取较宽）**；超出需评审。
- [ ] **GATE-PDBS-G03｜source/cache 故障只产生可诊断 PARTIAL/重试，不产生错误符号**。
  本机单 bit zstd 损坏预演已得到三次 source 503；空 cache + source 停机也得到
  `symbolicator_failed` 和零业务符号，恢复 source/重建 cache 后 Canonical 回到基线。仍缺 cache
  磁盘满、显式网络延迟/超时、并发及目标环境故障注入，故不勾选。
- [ ] **GATE-PDBS-G04｜目标环境 Unified raw 已成为可重建缓存，删除后恢复演练通过**。

### 7.8 预计代码与文档落点

实施前需用当前分支重新确认调用链；下表是本基线的主要落点，不表示每个文件都必须修改：

| 领域 | 主要现有文件/建议新增文件 |
| --- | --- |
| 数据模型 | `platform/api/crashcap_api/models.py`、`platform/migrations/versions/0008_*.py`、migration tests |
| 对象键/存储 | `platform/api/crashcap_api/object_keys.py`、`storage.py`、建议新增 `services/artifact_payloads.py` |
| Blob/上传服务 | `services/artifact_blobs.py`、`services/artifact_blob_backfill.py`、`services/uploads.py` |
| Worker | `platform/worker/crashcap_worker/processor.py`、`symbols.py`、`retention.py`、codec/materializer tests |
| API/指标 | `routes.py`、`response_models.py`、`config.py`、`metrics.py`、OpenAPI/contract tests |
| CLI | `platform/cli/crashcap_cli/main.py`、`crashcap-ci/src/publisher.rs`、release protocol tests |
| Symbolicator | `deploy/symbolicator/gateway.py`、`config.yml`、`deploy/compose/phase1.yml` |
| 前端 | `platform/frontend/src/api/*`、Build/Artifact 页面、generated OpenAPI、frontend tests |
| 运维 | `scripts/phase1/deploy_check.py`、新的容量/GC/backfill runner、rollout/recovery/UAT 文档 |

建议固定以下证据产物，JSON 为机器权威，Markdown 为评审视图：

```text
docs/evidence/pdb-storage-baseline-<date>.json|md
docs/evidence/pdb-compression-benchmark-<date>.json|md
docs/evidence/pdb-storage-golden-equivalence-<date>.json|md
docs/evidence/pdb-storage-backup-restore-<date>.json|md
docs/evidence/pdb-storage-source-recovery-<date>.json|md
docs/evidence/pdb-storage-capacity-<date>.json|md
docs/evidence/symbolicator-cache-governance-<date>.json|md
docs/evidence/pdb-storage-target-uat-<date>.json|md
docs/evidence/pdb-storage-go-no-go-<date>.json|md
```

## 8. 自动验证矩阵

### 8.1 单元与属性测试

| 编号 | 场景 | 必须断言 |
| --- | --- | --- |
| AUTO-01 | identity/zstd round-trip | raw size/SHA 完全一致，临时文件清理 |
| AUTO-02 | zstd 截断、尾随、checksum 错误 | bounded rejection，不产生 Blob |
| AUTO-03 | 声明 2 GiB、实际超长输出 | 在上限前终止，内存/磁盘受限 |
| AUTO-04 | stored hash 正确、raw hash 错误 | integrity conflict，不能 trusted |
| AUTO-05 | 同 raw SHA、不同 kind/size/identity | hard conflict，不覆盖既有 Blob |
| AUTO-06 | mixed identity/zstd 数据库 | 所有 Reader 行为一致 |
| AUTO-07 | 两个 uploader 首次同 Blob | 一个 upload、一个 wait，最终同一 `abl_` |
| AUTO-08 | claim owner 中断 | lease 后 fenced takeover，无双 Blob |
| AUTO-09 | GC 与 verify/retry 并发 | 活跃 payload/唯一权威对象不被删 |
| AUTO-10 | S3 delete 成功、DB commit 失败 | 重跑幂等收敛并保留审计 |
| AUTO-11 | Workspace A/B 同 raw SHA | 两个独立 Blob，不披露命中 |
| AUTO-12 | emergency delete/restore | 影响报告完整，sealed Build 不静默回退 |
| AUTO-13 | HTTP source 路径穿越/错误 scope | 400/404，不跨 Workspace 读取 |
| AUTO-14 | raw/zstd 客户端能力协商 | 旧服务/旧客户端兼容 |
| AUTO-15 | 对象备份路径/size/SHA 篡改 | 非规范路径拒绝；恢复失败后目标零对象 |

### 8.2 仓库 Gate

每个实施提交至少执行与改动相符的子集；最终 Gate 必须全部执行：

```text
python scripts/phase0/gate.py
python scripts/phase1/deploy_check.py --json --runtime-env-file <external-env>
python scripts/phase2/gate.py
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
python -m ruff check platform
python -m mypy platform/api platform/worker platform/cli
python -m pytest platform/tests platform/migrations/tests
pnpm --dir platform/frontend lint
pnpm --dir platform/frontend test -- --run
pnpm --dir platform/frontend build
pnpm openapi:check
```

命令名称应在实施时按仓库当前脚本复核；不得把因缺少 PostgreSQL/Redis/S3 环境而 skipped 的
测试表述为已执行。

### 8.3 Golden/Canonical 等价

对 legacy raw、zstd materialize、HTTP source 三条路径分别运行同一 fixture/DMP：

- 异常码、崩溃线程正确率必须 100%。
- PDB mismatch 检测必须 100%。
- 静默使用错误符号次数必须 0。
- 完整匹配样本顶部 3 个业务帧等价率不得低于既有 Gate。
- 函数原名/归一名、文件、行号、inline、frame trust、module match 状态逐字段比较。
- quality score/warnings、Build resolution、Exact fingerprint/grouping 语义一致。
- raw 引擎输出允许 request/cache/timing 等非语义字段变化，允许差异必须白名单化。

### 8.4 容量与性能

至少使用以下矩阵：

| 维度 | 样本 |
| --- | --- |
| 大小 | <16 MiB、16–64 MiB、64–512 MiB、512 MiB–2 GiB |
| 类型 | lightstreamer PDB、xrtc PDB、不同版本 PDB、PE、不可压缩随机对照 |
| 温度 | 首次压缩、首次解压、热 OS cache、冷 Symbolicator cache |
| 并发 | 1、2、5 个 publisher/materializer |
| 故障 | Worker kill、S3 timeout、磁盘不足、codec corruption、cache/source restart |

必须记录：logical/stored/wire bytes、压缩/解压吞吐、p50/p95、CPU、RSS、temp peak、队列等待、
Publication ready 时间、冷/热 DMP 分析时间和对象/卷真实字节。

## 9. 真实 UAT 计划

UAT 必须在目标内网实际执行；本地 Compose UAT 只能作为预演。涉及 corruption、volume 清空、
raw/legacy 删除的步骤必须在专用 UAT Workspace/卷或经批准的恢复副本上执行，不得直接破坏生产
唯一数据。每一步填写 `PASS|FAIL|NOT_PROVEN`、tester、目标、时间、
Build/Publication/Artifact/Blob/Occurrence/Run ID、截图/JSON/日志引用。

| Gate | 操作 | 必须保留的证据 |
| --- | --- | --- |
| UAT-PDBS-01 | 升级前只读容量快照与备份 | DB/RustFS/卷字节、镜像 digest、备份 ID |
| UAT-PDBS-02 | Build A 发布完整 lightstreamer + xrtc 四产物 | raw SHA/size、Blob/pair、Ready/Sealed |
| UAT-PDBS-03 | Build B 仅改变 lightstreamer，复用 xrtc | xrtc=`reused`，各 Build expectation 完整 |
| UAT-PDBS-04 | 两客户端并发首次发布同新 Blob | upload/wait、lease/takeover、唯一 Blob |
| UAT-PDBS-05 | 旧客户端 raw 上传 | v1/legacy 兼容、最终 zstd canonical |
| UAT-PDBS-06 | 新客户端 zstd 上传 | wire/logical 双 hash、网络节省、回执 |
| UAT-PDBS-07 | reported Build 真实 DMP | 函数、文件、行、inline、quality 对照 |
| UAT-PDBS-08 | 无 Build ID 真实 DMP | auto_unique/ambiguous 行为与 baseline 一致 |
| UAT-PDBS-09 | 错 PDB/缺 PE/FASTLINK | 拒绝或 PARTIAL，无静默错误符号 |
| UAT-PDBS-10 | 清空测试 Unified/cache 后分析 | 仅凭 zstd Blob 自动恢复，结果等价 |
| UAT-PDBS-11 | 压缩对象单 bit corruption | 拒绝、告警、恢复，不使用错误符号 |
| UAT-PDBS-12 | Worker 在压缩/commit/GC 各阶段重启 | 重放收敛、无孤儿/误删/重复 Blob |
| UAT-PDBS-13 | 两 Workspace 同 SHA/同文件名 | 不复用、不串符号、不披露 |
| UAT-PDBS-14 | legacy/upload/raw cleanup dry-run/apply | 预测/实际字节、删除清单、计数不变 |
| UAT-PDBS-15 | 浏览器 Build/Artifact 页面 | encoding/savings 正确，无 key/URL/凭据 |
| UAT-PDBS-16 | 100 Artifact 容量与并发测试 | ratio、p95、CPU/RSS/temp、失败率 |
| UAT-PDBS-17 | `active -> off` 行为回退（raw 尚保留） | 新旧读取、Publication、分析正常 |
| UAT-PDBS-18 | raw 已清理后的新 Reader 回滚演练 | 明确只能回滚到双格式 Reader 镜像 |
| UAT-PDBS-19 | PostgreSQL + RustFS 备份恢复 | 空 cache/symbol volume 下结果等价 |
| UAT-PDBS-20 | 实际执行者签署 | 完整证据索引和非自动签名引用 |

以下不能替代 UAT：单元测试、fake object store、合成 JSON、只检查 Build Ready、只检查解压 hash、
自动生成签名或本地 Docker Desktop 截图。

## 10. 发布、灰度与回滚

### 10.1 建议开关

```text
CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE=off|shadow|active
CRASHCAP_ARTIFACT_BLOB_COMPRESSION_MODE=off|shadow|active
CRASHCAP_ARTIFACT_UPLOAD_GC_MODE=off|dry-run|active
CRASHCAP_WORKSPACE_SYMBOL_SOURCE_MODE=filesystem|shadow-http|http
```

API、所有 Worker、ops job 对同一语义开关必须一致；deploy check 应拒绝不一致组合。

### 10.2 发布波次

1. **Wave 0**：部署 additive migration、双格式 Reader、指标；Writer/GC/source 全部 off。
2. **Wave 1**：dedup active；Upload GC dry-run；compression shadow；filesystem source。
3. **Wave 2**：Upload GC active；compression active 仅一个 Workspace；保留所有 raw rollback copy。
4. **Wave 3**：扩大 compression active；客户端 v2 灰度；HTTP source shadow 对照。
5. **Wave 4**：HTTP source active；缩短 downloaded TTL；Unified raw 仍保留。
6. **Wave 5**：两个发布周期和目标 UAT 全通过后，分批清理 raw canonical/Unified/legacy。

### 10.3 回滚原则

- 任意业务/完整性异常：先停止 Writer 和删除任务，保留数据，切回已部署的双格式 Reader 路径。
- compression `active -> off` 只阻止新压缩写入，不删除或降级已有 zstd Blob。
- HTTP source 可切回 filesystem，前提是 raw Unified 尚保留或已先重建。
- migration 不 downgrade；存在 zstd-only/Blob-backed 数据时旧 schema 无法安全表达。
- raw cleanup 后不能回滚到不支持 zstd Reader 的旧镜像；运行手册必须列出最老可回滚 digest。
- sealed Build 不因缓存/对象事故静默改写；修复通过恢复 payload、重新物化或显式新 Publication。

## 11. 可观测性与告警

建议新增有界指标：

```text
crashcap_artifact_payload_bytes_total{encoding,kind,state}
crashcap_artifact_payload_codec_seconds{operation,encoding,outcome}
crashcap_artifact_payload_ratio{kind,encoding}
crashcap_artifact_materializations_total{encoding,outcome}
crashcap_artifact_materialization_seconds{encoding,kind,outcome}
crashcap_upload_payload_gc_total{kind,outcome}
crashcap_upload_payload_bytes{state,age_bucket}
crashcap_artifact_legacy_bytes{legacy_kind,state}
crashcap_symbol_source_requests_total{filetype,outcome,cache_state}
crashcap_symbol_source_bytes_total{filetype,outcome}
crashcap_symbol_cache_bytes{cache_kind}
```

禁止把 Workspace、Build、SHA、文件名、uploader 或对象键放入 label。建议告警：

- stored/raw ratio 连续偏离基线或压缩失败率非零。
- decompression corruption、raw hash mismatch、identity conflict 任一出现。
- terminal Upload payload 超过保留期。
- raw legacy 超过两个发布周期仍未签收处理。
- materialize p95、temp usage、Worker queue age 或 HTTP source 5xx 超阈值。
- cache/Unified/RustFS volume 达 70%/85% 高水位。
- PostgreSQL 记录与 S3 HEAD/list 字节差异未解释。

## 12. 完成定义与最终 Gate

- [ ] **GATE-PDBS-FINAL-01｜契约与迁移**：ADR accepted，additive migration、OpenAPI、CLI capability
  和旧客户端兼容测试通过。
- [ ] **GATE-PDBS-FINAL-02｜完整性**：语料中 stored/raw 双 hash、size、identity 100% 一致，
  silent corruption=0。
- [ ] **GATE-PDBS-FINAL-03｜分析质量**：Golden 与真实 DMP 的函数/文件/行/inline/quality/grouping
  达到等价门槛，错误符号次数=0。
- [ ] **GATE-PDBS-FINAL-04｜空间**：PDB aggregate stored/raw ≤25%；terminal Upload、过期 legacy、
  永久 Unified raw 均达到计划状态；实际物理字节与报告一致。
- [ ] **GATE-PDBS-FINAL-05｜性能**：压缩、materialize、冷/热 symbolication、100 Artifact 容量
  指标全部满足冻结门槛。
- [ ] **GATE-PDBS-FINAL-06｜并发与故障**：single-flight、takeover、重启、S3/codec corruption、
  磁盘不足和删除 fencing 全部通过。
- [ ] **GATE-PDBS-FINAL-07｜恢复**：PostgreSQL + RustFS 备份可在空 Unified/cache 环境恢复并
  重现真实 DMP 结果。
- [ ] **GATE-PDBS-FINAL-08｜目标 UAT**：UAT-PDBS-01–20 全部 PASS，实际 tester 和签署证据完整。
- [ ] **GATE-PDBS-FINAL-09｜运维**：指标、告警、容量盘点、dry-run cleanup、最老可回滚镜像和
  紧急修复手册已交付。
- [ ] **PDB 存储优化完成**：仅当 FINAL-01–09 全部勾选时勾选；本地 PASS 不替代目标 UAT。

## 13. 建议提交与证据边界

建议至少拆成以下提交，便于回滚和评审：

1. `docs: decide compressed artifact blob payloads`
2. `feat: add upload payload lifecycle and dry-run gc`
3. `feat: add dual-format artifact blob readers`
4. `feat: store verified artifact blobs with zstd`
5. `feat: backfill and clean legacy artifact payloads`
6. `feat: add compressed artifact delivery v2`
7. `feat: serve workspace symbols from compressed blobs`
8. `ops: complete pdb storage rollout gates`

每个提交应记录：commit SHA、迁移版本、镜像 digest、开关值、测试命令与结果、实际/跳过项、
UAT 或 benchmark 报告路径、对象/卷前后字节以及是否 push。不得把包含对象键、预签名 URL、
凭据或未脱敏本地路径的运行回执提交到仓库。
