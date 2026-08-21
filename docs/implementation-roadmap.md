# Crash-Cap 渐进式实施路线图

状态：Phase 0 本地技术验证已完成，允许进入 Phase 1。最后更新：2026-08-21。

本文把 [设计文档](design.md) 拆成可逐项勾选的实施任务。领域语言以 [CONTEXT.md](../CONTEXT.md) 为准，架构与契约冲突时以设计文档、已接受 ADR 和机器可读 Schema 为准；本文只负责实施顺序与完成证据，不重新定义产品规则。

## 1. 使用方式

- `[ ]`：尚未完成；`[x]`：已经完成并有可复核证据。
- 只有满足任务的「完成标准」后才能勾选；仅创建空目录、空接口或手工跑通一次不算完成。
- 每个任务提交时应附上证据：测试命令与结果、产物路径、镜像 digest、对照报告或验收记录。
- 标记为「可并行」的泳道可以同时推进；写明依赖的任务必须等待依赖完成。
- 阶段 Gate 是硬门禁。子任务完成不代表阶段完成，Gate 未通过不得勾选阶段。
- 发现蓝图与实测冲突时，先更新设计文档；满足“难逆转、有真实取舍、未来读者会疑惑”时再补 ADR。

任务泳道：

| 标记 | 泳道 | 主要产物 |
| --- | --- | --- |
| `CORE` | Rust 分析核心 | `dmp-core` CLI、Canonical JSON |
| `FIX` | Golden 样本 | 合成 Dump、manifest、WinDbg/CDB 对照 |
| `SYM` | 符号化运行时 | Symbolicator、Unified 符号布局 |
| `S3` | 对象存储 | RustFS 资格测试、S3 adapter |
| `PLAT` | 平台后端 | FastAPI、Dramatiq Worker、PostgreSQL |
| `UI` | 前端 | React 管理与报告界面 |
| `QA/OPS` | 质量与运维 | 自动化验收、Compose、安全、备份与可观测性 |

## 2. 总体依赖与并行关系

```text
已确认蓝图
   │
   ├──────── CORE ───────┐
   ├──────── FIX ────────┤
   ├──────── SYM ────────┼── Phase 0 Golden Gate ── Phase 1 最小可用平台
   └──────── S3 ─────────┘                                  │
                                                           ├── Phase 2 构建/符号体系
                                                           ├── Phase 3 Family/趋势
                                                           └── Phase 4 Hang/深度分析
```

Phase 0 的 `CORE`、`FIX`、`SYM`、`S3` 可以从第一天并行。`CORE + FIX + SYM` 先汇合成单样本纵向切片，再扩展为 20–50 个 Golden 样本。`S3` 独立验证，最终与 Golden 结果一起组成 Phase 0 Gate。

Phase 1 的完整 Web/API 实现必须等待 Phase 0 Gate。Gate 之前允许完成工具链盘点、接口测试脚手架和 Compose 实验，但不得把尚未验证的 Linux 分析路径包装成产品功能。

## 3. 已完成的设计基线

- [x] **BASE-01｜领域语言已统一**：Workspace、Build、Occurrence、Dump Blob、Analysis Run、Current Analysis、Crash Group 等定义已写入 [CONTEXT.md](../CONTEXT.md)。
- [x] **BASE-02｜Phase 0–1 蓝图已确认**：产品边界、数据模型、API、状态机、安全与验收规则已写入 [设计文档](design.md)。
- [x] **BASE-03｜关键架构取舍已记录**：Linux 原生分析 Core、Occurrence/Blob/Run 分离、匿名可信内网、RustFS S3 契约已有 accepted ADR：
  - [ADR-0001](adr/0001-linux-native-versioned-analysis-core.md)
  - [ADR-0002](adr/0002-separate-occurrences-blobs-and-analysis-runs.md)
  - [ADR-0003](adr/0003-run-anonymously-on-a-trusted-intranet.md)
  - [ADR-0004](adr/0004-use-rustfs-through-the-s3-contract.md)
- [x] **BASE-04｜v0.1 机器契约草案已建立**：[analysis-result-v0](../contracts/analysis-result-v0.schema.json)、[build-manifest-v0](../contracts/build-manifest-v0.schema.json)、[task-message-v0](../contracts/task-message-v0.schema.json) 已存在并通过 JSON 解析、本地 `$ref` 和关键交叉约束检查。
- [x] **BASE-05｜补齐 Schema 元标准验证**：使用支持 JSON Schema Draft 2020-12 的验证器校验 v0.1 与稳定 v1 的六个 Schema，并在 CI 中固定执行。完成标准：无 meta-schema 错误，正反例和跨版本拒绝测试均通过。
- [x] **BASE-06｜盘点开发与验证工具链**：记录 Rust、Cargo、Docker/Compose、Windows MSVC、CMake、CDB/WinDbg、Symbolicator 和 RustFS 的可用版本。完成标准：生成可复跑的环境检查命令与版本记录。
- [x] **BASE-07｜建立持续集成骨架**：至少执行 Markdown 链接检查、Schema 验证、Rust format/lint/test 和后续 Golden harness。完成标准：新提交能自动阻止契约破坏与测试退化。

## 4. Phase 0 — 技术验证

目标：证明 Linux 上的 `rust-minidump + Symbolicator` 能可靠处理目标 DMP，并证明 RustFS 满足平台需要的 S3 契约。此阶段不建设完整 Web 产品。

完成记录（2026-08-21）：[Go/No-Go 报告](evidence/phase0-go-no-go.md) 为 **PASS / GO**；[Golden 报告](evidence/phase0-golden-results.md) 为 21/21 PASS；[校准报告](evidence/phase0-calibration.md) 与 [RustFS 资格报告](evidence/rustfs-qualification.md) 均通过。最终固定身份为 Core `sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b`、Symbolicator `sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959`、RustFS `sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831`。这是本地 Windows/MSVC + Docker Desktop/Linux-container 证明；远端 GitHub Actions 未执行，授权真实来源样本也不是 Crash-Cap 生产事故。

### 4.1 P0-A：工程骨架（先行，随后各泳道并行）

- [x] **P0-A01｜建立 Rust workspace** `[CORE]`。创建 `core/`、基础 crate、统一 lint/format/test 配置和锁文件。完成标准：干净环境中 `cargo fmt --check`、`cargo clippy`、`cargo test` 全部通过。
- [x] **P0-A02｜建立 `dmp-core` CLI 外壳** `[CORE]`，依赖 P0-A01。实现 `inspect`、`analyze` 参数、版本输出、结构化错误与设计规定的退出码。完成标准：CLI 参数契约和退出码有自动化测试。
- [x] **P0-A03｜建立 Canonical 类型层** `[CORE]`，依赖 P0-A01。Rust 类型序列化为稳定 `analysis-result-v1`，并保留 v0.1 兼容回归；地址格式、枚举和 `additionalProperties: false` 约束有测试。完成标准：最小合法结果通过本版本 Schema，典型非法与跨版本结果被拒。
- [x] **P0-A04｜建立 Core OCI 镜像** `[CORE/OPS]`，依赖 P0-A02。镜像内仅包含运行所需文件，支持只读根和非 root 运行。完成标准：镜像输出版本、digest 可记录，CLI smoke test 通过。
- [x] **P0-A05｜建立 fixture 目录规范与 harness 外壳** `[FIX/QA]`，可与 P0-A01–A04 并行。完成标准：一个空/占位 fixture 能被发现、执行并生成机器可读汇总，二进制大文件默认不进入版本库。

### 4.2 P0-B：第一个端到端纵向切片

本节是第一目标：先用一个空指针读样本打通整条链路，再扩大覆盖面。

- [x] **P0-B01｜生成第一个 Windows x64/MSVC 样本** `[FIX]`，依赖 BASE-06、P0-A05。生成空指针读的 DMP、匹配 EXE/PDB、构建 manifest 和 CDB/WinDbg 摘要。完成标准：样本可重复构建，异常码、崩溃线程和预期顶部业务帧已记录。
- [x] **P0-B02｜实现 DMP 基础验收** `[CORE]`，依赖 P0-A02。识别 `MDMP`、用户态、x64、截断/损坏输入。完成标准：合法样本进入 inspect，非 Minidump/非 x64/损坏输入分别返回约定错误。
- [x] **P0-B03｜实现 inspect 提取** `[CORE]`，依赖 P0-B02。提取 OS、架构、异常、崩溃线程、全部线程上下文和模块列表。完成标准：P0-B01 的异常码与崩溃线程与参考结果一致。
- [x] **P0-B04｜固定并启动 Symbolicator 版本** `[SYM]`，可与 P0-B02/B03 并行。完成标准：镜像版本与 digest 已记录，健康检查通过，配置不接受请求方任意符号 URL。
- [x] **P0-B05｜建立 Workspace Unified 符号样例** `[SYM]`，依赖 P0-B01、P0-B04。用固定版本 `symsorter` 放置匹配 PE/PDB。完成标准：同一 `debug_id/code_id` 可查询，scope 显式带测试 Workspace。
- [x] **P0-B06｜接入 rust-minidump unwind 与 frame trust** `[CORE]`，依赖 P0-B03、P0-B01。完成标准：崩溃线程输出 frame 及 `context | cfi | frame_pointer | scan | unknown`，原始结果写入 `raw/minidump.json`。
- [x] **P0-B07｜接入 Symbolicator `/symbolicate`** `[CORE/SYM]`，依赖 P0-B04–B06。按模块与 `instruction_addr` 请求并合并函数、文件和行号。完成标准：P0-B01 顶部业务帧可符号化，原始响应写入 `raw/symbolicator.json`。
- [x] **P0-B08｜输出首个 Canonical JSON** `[CORE]`，依赖 P0-A03、P0-B03、P0-B06、P0-B07。完成标准：结果通过稳定 v1 Schema，包含 engine 版本、threads、modules、quality、fingerprints 和 build resolution。
- [x] **P0-B09｜自动对比首个样本** `[QA]`，依赖 P0-B08。完成标准：一条命令完成“样本 → inspect → analyze → canonical → expected 对比”，失败时报告字段级差异。
- [x] **P0-B10｜首个纵向切片完成** `[Gate]`，依赖 P0-B01–B09。证据：可复跑命令、Canonical JSON、raw 输出、Schema 结果和 WinDbg/CDB 对照均归档。

### 4.3 P0-C：Core 能力扩展

P0-C 与 P0-D、P0-E 可并行；每项都应先增加 fixture，再实现或修正能力。

- [x] **P0-C01｜实现 crash/hang/unknown 分类** `[CORE/FIX]`，依赖 P0-B03。只有显式 `capture_profile=hang` 才分类为 hang；无异常且无 Hang 意图为 unknown。完成标准：三类正反例通过。
- [x] **P0-C02｜实现 PE `code_id` 与 PDB/RSDS `debug_id` 提取** `[CORE]`。完成标准：使用二进制真实字段，大小写/格式符合设计，不能从 PDB 反推 `code_id`。
- [x] **P0-C03｜实现 Artifact 精确匹配状态** `[CORE]`，依赖 P0-C02。覆盖 `matched/missing_pe/missing_pdb/pdb_mismatch/pe_mismatch/corrupted/system_symbol_pending/unsupported`。完成标准：禁止按文件名、Version 或“唯一 PDB”猜测。
- [x] **P0-C04｜实现 Build Resolution** `[CORE]`，依赖 P0-C03。覆盖 `reported/auto_unique/manual/ambiguous/unresolved` 和候选证据。完成标准：人工绑定不被静默覆盖，多个 Build 命中时不猜 Version。
- [x] **P0-C05｜完善 unwind 退化处理** `[CORE/FIX]`，依赖 P0-B06。完成标准：缺 PE 产生 `missing_pe_unwind`/PARTIAL 而非 FAILED，scan 帧不会被标成高可信。
- [x] **P0-C06｜实现 Symbolicator 重试语义** `[CORE/SYM]`，依赖 P0-B07。完成标准：处理 pending；pending 后 404 会整单重提，不把 Symbolicator `request_id` 当平台任务 ID；超时可诊断。
- [x] **P0-C07｜实现 Canonical normalizer** `[CORE]`，依赖 P0-C01–C06。完成标准：地址、函数原名/归一名、模块角色、warnings、版本常量稳定输出，raw 引擎字段不会泄漏为对外契约。
- [x] **P0-C08｜实现并校准质量分** `[CORE/QA]`，依赖 P0-C07。完成标准：三个分项、总分和 warnings 可解释；分母为 0 时按规则处理；F04 后冻结稳定 v1 权重。
- [x] **P0-C09｜实现 Exact 指纹算法** `[CORE/QA]`，依赖 P0-C07。完成标准：只有满足 crash、故障业务模块精确匹配、存在非 scan in-app 帧才生成；否则为 null，绝不回退系统帧；F06 后冻结为 `exact-v1.0`。
- [x] **P0-C10｜实现资源与恶意输入边界** `[CORE/QA]`。覆盖 Core v1 模块数上限 4096、超时、内存/临时目录限制、畸形输入。完成标准：异常输入不会导致宿主失控，错误不包含内存正文或机密。

### 4.4 P0-D：Golden Dump 样本集

- [x] **P0-D01｜确定 fixture manifest/expected 格式** `[FIX/QA]`，依赖 P0-A05。每个样本记录来源授权、异常码、崩溃线程、顶部业务帧、code/debug ID、允许差异和预期 warnings。
- [x] **P0-D02｜实现可重复的 Windows 样本生成器** `[FIX]`，依赖 BASE-06。Dump 由独立进程调用 `MiniDumpWriteDump` 采集。完成标准：构建产物、编译参数和采集参数可追溯。
- [x] **P0-D03｜覆盖基础崩溃样本** `[FIX]`，依赖 P0-D02：空指针读、空指针写、非法执行地址、C++ 未捕获异常、`std::terminate/abort`。
- [x] **P0-D04｜覆盖复杂栈样本** `[FIX]`，依赖 P0-D02：栈溢出、多线程崩溃、Release 优化 + inline、异步线程池。
- [x] **P0-D05｜覆盖 Artifact 退化样本** `[FIX]`，依赖 P0-D02：缺失 PDB、错误 PDB、缺失 PE、PE/PDB mismatch。
- [x] **P0-D06｜覆盖拒绝与分类边界** `[FIX]`，依赖 P0-D02：损坏/截断 DMP、非 x64、显式 Hang、无异常但未声明 Hang 的 Unknown。
- [x] **P0-D07｜引入经授权真实样本** `[FIX/QA]`。完成标准：真实二进制仅在私有对象存储，仓库只保留 manifest、expected 和脱敏参考摘要，授权与脱敏可审计。
- [x] **P0-D08｜达到 20–50 个 Golden 样本** `[FIX]`，依赖 P0-D03–D07。完成标准：设计列出的类别均覆盖，样本分布与缺口有清单；Phase 0 实际冻结为 21 个。

### 4.5 P0-E：RustFS S3 资格测试（与 Core/Golden 完全并行）

- [x] **P0-E01｜固定候选 RustFS 镜像 digest** `[S3/OPS]`。记录版本、digest、配置和已知 beta 风险。
- [x] **P0-E02｜建立可替换的 S3 adapter 测试接口** `[S3]`，依赖 P0-E01。完成标准：测试仅调用标准 S3 API，不引用 RustFS 私有 API。
- [x] **P0-E03｜验证私有 Bucket 与凭证隔离** `[S3/QA]`。匿名访问失败；平台服务凭证与浏览器预签名访问分离；Console 不暴露普通网络。
- [x] **P0-E04｜验证预签名 PUT/GET** `[S3/QA]`。覆盖短 TTL、对象/动作限制、过期失败、内网 TLS endpoint。
- [x] **P0-E05｜验证 multipart** `[S3/QA]`。覆盖 complete、abort、失败重试与残留清理。
- [x] **P0-E06｜验证 HEAD、Range GET 与流式 SHA-256** `[S3/QA]`。完成标准：服务端按流计算哈希，不依赖客户端 hint，不把大对象读入 API 内存。
- [x] **P0-E07｜验证生命周期与重启一致性** `[S3/QA]`。覆盖对象过期、服务重启、元数据/对象一致性。
- [x] **P0-E08｜验证 SSE** `[S3/QA]`。完成标准：静态数据加密配置生效并有读取回归测试。
- [x] **P0-E09｜验证备份与恢复** `[S3/OPS]`。完成标准：从备份恢复后哈希、HEAD、Range 与分析对象均一致，恢复步骤可复跑。
- [x] **P0-E10｜形成 RustFS 资格报告** `[S3/QA]`，依赖 P0-E01–E09。明确通过/失败项、性能数据、已知限制与替换条件；未通过不得冻结存储实现。

### 4.6 P0-F：Golden 自动对照与校准

- [x] **P0-F01｜实现全量 Golden runner** `[QA]`，依赖 P0-C07、P0-D08。完成标准：可并行执行样本，保留每个样本的 core/raw/canonical/expected diff。
- [x] **P0-F02｜实现指标计算** `[QA]`，依赖 P0-F01。自动统计异常码正确率、崩溃线程正确率、PDB mismatch 正确率、顶部 3 个业务帧等价率和静默错误符号次数。
- [x] **P0-F03｜校准缺 PE 退化** `[CORE/QA]`。量化相对 WinDbg 的帧丢失与 trust 变化，决定 warning 和质量扣分。
- [x] **P0-F04｜校准质量权重** `[CORE/QA]`。检查大量系统帧、无 in-app 帧等边界，更新权重或保留初值并记录证据。
- [x] **P0-F05｜校准 unwind/符号化对齐** `[CORE/SYM/QA]`。量化模块 + `instruction_addr` 合并错误，确保不会把符号填到错误物理帧。
- [x] **P0-F06｜校准 Exact 的 16 字节分桶** `[CORE/QA]`。检查不同崩溃点误合并与同一崩溃误拆分，任何规则变更都更新 `grouping_version`。
- [x] **P0-F07｜测量 Microsoft 符号路径** `[SYM/QA]`。记录冷/热缓存耗时、失败率和出口 allowlist 行为，不把网络失败误判成业务 PDB mismatch。
- [x] **P0-F08｜冻结 Phase 0 实测结论** `[QA]`，依赖 P0-F02–F07。更新设计中的校准项；如改变 unwind 权威路径，更新设计并记录相应架构决策。

### 4.7 Gate P0：是否允许进入完整 Phase 1

- [x] **GATE-P0-01｜有效完整匹配样本异常码正确率 = 100%**。
- [x] **GATE-P0-02｜有效完整匹配样本崩溃线程正确率 = 100%**。
- [x] **GATE-P0-03｜PDB mismatch 检测正确率 = 100%**。
- [x] **GATE-P0-04｜完整符号样本顶部 3 个业务帧与 WinDbg 等价率 ≥ 95%**。
- [x] **GATE-P0-05｜静默使用错误符号次数 = 0**。
- [x] **GATE-P0-06｜20–50 个 Golden 样本及结果可复跑、可审计**。
- [x] **GATE-P0-07｜RustFS S3 资格测试通过，镜像 digest 已固定**。
- [x] **GATE-P0-08｜发布稳定 v1 机器契约**：从 v0.1 草案发布 `analysis-result-v1`、`build-manifest-v1`、`task-message-v1` 并冻结 `/api/v1` 前缀；提供兼容性/版本测试。以后新增字段必须发布新契约版本并保留旧版读取能力。
- [x] **GATE-P0-09｜作出并记录 Go/No-Go 决策**。若任一硬指标不满足，停止完整 Web Phase 1，回到 unwind 路径或评估 Windows Worker；不得降低“零静默错误符号”门槛。
- [x] **PHASE-0 完成**：仅当 GATE-P0-01–09 全部勾选时勾选。

## 5. Phase 1 — 最小可用平台

进入条件：`PHASE-0 完成`。目标是匿名可信内网中的可用平台：手动上传、可重复分析、按 Workspace/Version 统计、报告与符号健康。Exact Group 是 SHOULD，证据不足的 Crash 保持 Unclassified，不阻塞首版上线。

### 5.1 并行批次

| 批次 | 可并行工作 | 汇合点 |
| --- | --- | --- |
| P1-1 | `PLAT` 工程骨架、数据库迁移、Compose、`UI` mock | Workspace/Build API 契约可用 |
| P1-2 | Artifact 上传/ingest、Dump 上传/去重、前端上传流程、运行隔离 | 可创建 Occurrence 与 Analysis Run |
| P1-3 | Worker/Core 编排、查询读模型、Occurrence 页面、运维监控 | 单个 DMP 端到端完成 |
| P1-4 | 统计、符号健康、可选 Exact Group、安全加固、容量测试 | Phase 1 验收 Gate |

### 5.2 P1-A：平台与数据基础

- [ ] **P1-A01｜建立 `platform/` 工程结构** `[PLAT/UI]`。包含 `api/worker/frontend/cli`，固定 Python、Node 和依赖管理方式。
- [ ] **P1-A02｜建立开发 Compose** `[OPS]`，可与 P1-A01 并行。启动 PostgreSQL、Redis、RustFS、Symbolicator、API、Worker；服务与卷命名稳定。
- [ ] **P1-A03｜实现统一配置与机密注入** `[PLAT/OPS]`。完成标准：凭证不进仓库/日志，默认 `RAW_DOWNLOAD_ENABLED=false`，Microsoft symbols 默认开启但受 allowlist 控制。
- [ ] **P1-A04｜实现带前缀 ULID** `[PLAT]`。覆盖 `wsp_/bld_/mod_/art_/blob_/occ_/run_/grp_/upl_` 并有碰撞/格式测试。
- [ ] **P1-A05｜实现 PostgreSQL 初始迁移** `[PLAT]`。覆盖设计中的全部 Phase 1 表、外键、唯一约束和索引；不得创建 users/roles/tenants/memberships。
- [ ] **P1-A06｜实现状态机约束** `[PLAT]`，依赖 P1-A05。上传状态与 Analysis Run 状态分离，非法跳转被拒绝并有单元测试。
- [ ] **P1-A07｜实现对象 key builder** `[PLAT/S3]`。所有 key 带 `workspace_id`，与设计路径一致，路径穿越输入被拒。
- [ ] **P1-A08｜实现错误响应与请求 ID** `[PLAT]`。覆盖设计通用错误码，错误详情不泄漏内存内容、凭证或完整预签名 URL。

### 5.3 P1-B：Workspace、Build 与 Manifest

- [ ] **P1-B01｜实现 Workspace 创建/列表/详情 API** `[PLAT]`，依赖 P1-A05/A08。无登录，无权限过滤，无 DELETE。
- [ ] **P1-B02｜实现 Build 创建/列表/详情 API** `[PLAT]`。同一 Workspace 允许多个 Build 使用相同 Version，禁止 `UNIQUE(workspace_id, version)`。
- [ ] **P1-B03｜实现 Manifest 校验与保存** `[PLAT]`。依赖稳定 v1 Manifest Schema；至少一个 entrypoint，角色只允许 entrypoint/owned/dependency。
- [ ] **P1-B04｜实现 Build module 入库** `[PLAT]`。entrypoint/owned 默认 in-app，dependency/system 默认 false；Version 只展示、不用于符号匹配。
- [ ] **P1-B05｜为 Workspace/Build API 建立契约测试** `[QA]`。覆盖重复 Version、非法角色、缺 entrypoint、跨 Workspace 查询和无 DELETE 路由。

### 5.4 P1-C：Artifact 上传与符号仓库

- [ ] **P1-C01｜实现预签名上传初始化** `[PLAT/S3]`，依赖 P1-A03/A07、RustFS 资格通过。API 不中转 PE/PDB；校验文件种类和声明大小。
- [ ] **P1-C02｜实现上传 complete 与 HeadObject 校验** `[PLAT/S3]`。只把 ETag 当提示，校验长度后转 VERIFYING。
- [ ] **P1-C03｜实现 Verification Worker** `[PLAT/QA]`。从 RustFS 流式计算 SHA-256，检查魔数、空文件、实际大小和上限。
- [ ] **P1-C04｜实现 PE/PDB ingest** `[PLAT/CORE]`。提取真实 code/debug ID，拒绝 FASTLINK、损坏格式和 mismatch，不信任 manifest 手填 ID。
- [ ] **P1-C05｜实现 raw 与 Unified 双层落库** `[PLAT/SYM/S3]`。只将 verified 工件送入 Workspace-scoped `symsorter` 布局。
- [ ] **P1-C06｜实现 `symbol_inventory_version` 单调递增** `[PLAT]`。只有成功 ingest 才递增，并发更新无丢失。
- [ ] **P1-C07｜实现 Artifact 列表与 reindex API** `[PLAT]`。reindex 异步、幂等并写 operation log。
- [ ] **P1-C08｜实现符号源顺序与隔离测试** `[SYM/QA]`。Workspace 私有 → 公司公共 SDK → Microsoft；禁止请求方 URL，两个 Workspace 同名 PDB 不串扰。

### 5.5 P1-D：Dump、Occurrence 与分析编排

- [ ] **P1-D01｜实现 Dump 上传初始化** `[PLAT/S3]`。>256 MiB 立即拒绝且字节不经 API；记录 capture profile、reported build/time。
- [ ] **P1-D02｜实现 Dump complete 与 Verification Worker** `[PLAT]`。流式 SHA-256、魔数/大小校验，验收状态与 Run 状态分开。
- [ ] **P1-D03｜实现同 Workspace 事务性去重** `[PLAT]`。唯一键 `(workspace_id, sha256)`；重复上传返回相同 Blob/Occurrence；跨 Workspace 创建独立业务对象。
- [ ] **P1-D04｜实现 Occurrence 时间口径** `[PLAT]`。`dump → reported → uploaded → manual`，保存来源；人工修正写 operation log。
- [ ] **P1-D05｜实现不可变 Analysis Run Spec** `[PLAT]`。包含 Blob、Build resolution、artifact IDs/hashes、core digest、Symbolicator/normalization/grouping 版本。
- [ ] **P1-D06｜实现分析幂等键** `[PLAT]`。相同键返回已有 run；force 使用 salt 创建新 run，但不创建新 Occurrence。
- [ ] **P1-D07｜实现最小队列消息** `[PLAT]`。队列只传 `run_id/attempt_id/routing`，Worker 必须从 PostgreSQL 读取不可变快照；通过 task-message v1 校验。
- [ ] **P1-D08｜实现 Dramatiq 队列划分** `[PLAT/OPS]`。`verify/ingest/dump-small/dump-large` 的资源、超时和路由符合设计；>256 MiB 不入队。
- [ ] **P1-D09｜实现隔离 Core 执行器** `[PLAT/OPS]`。非 root、只读根、独立 tmp、无 hostPath、资源/pids/超时限制；Core 仅能访问 Symbolicator。
- [ ] **P1-D10｜实现完整分析状态机编排** `[PLAT]`。inspect → match → analyze → normalize → optional grouping；missing/mismatch 产出 PARTIAL，不误报 FAILED。
- [ ] **P1-D11｜保存 Canonical 与 raw 输出** `[PLAT/S3]`。对象路径包含 Workspace/Occurrence/Run；PG 仅保存摘要与 top 15 crashing frames。
- [ ] **P1-D12｜实现 Current Analysis 切换** `[PLAT]`。只有 COMPLETE/PARTIAL 可成为 current；FAILED/TIMEOUT/OOM 保留但不切换。
- [ ] **P1-D13｜实现 reprocess** `[PLAT]`。补符号/版本变化生成新 run，旧 run 不变；原始 Blob 过期返回 `RAW_BLOB_EXPIRED`。
- [ ] **P1-D14｜实现 Symbolicator 与 Core 故障恢复** `[PLAT/OPS]`。Symbolicator 重启后整单重提；Core 崩溃、超时、OOM 不影响 API 与其他任务。

### 5.6 P1-E：查询、统计、符号健康与 Exact Group

- [ ] **P1-E01｜实现 Occurrence 详情 API** `[PLAT]`。同时展示 Blob 验收、Current Analysis、latest attempt、Build resolution、quality 和 group，但不混淆各状态。
- [ ] **P1-E02｜实现 Canonical/历史 Run 查询** `[PLAT/S3]`。支持 current 与 `run_id`，流式读取结果，不加载大对象到 API 内存。
- [ ] **P1-E03｜实现 threads/modules 查询** `[PLAT]`。线程、frame trust、模块匹配状态与 Canonical 一致。
- [ ] **P1-E04｜实现 Workspace/Version 统计** `[PLAT]`。只 join `occurrences.current_run_id`；每个 Occurrence 计一次；Version 可聚合多个 Build；ambiguous/unresolved 进入未知版本。
- [ ] **P1-E05｜分离 Crash/Hang/Unknown/Rejected 指标** `[PLAT/QA]`。只有 Current Analysis 确认为 crash 的 Occurrence 进入崩溃次数。
- [ ] **P1-E06｜实现 Symbol Health** `[PLAT]`。按模块聚合 matched/missing/mismatch，null-safe 唯一约束避免重复 missing symbol。
- [ ] **P1-E07｜实现 Exact Fingerprint 入组（SHOULD）** `[PLAT/CORE]`。依赖 P0 校准结论；有指纹才建组，无证据保持 Unclassified，不建伪组。
- [ ] **P1-E08｜实现 Group 查询与非破坏性编辑** `[PLAT]`。支持状态/owner/issue/title；merge/split 返回 501 `NOT_IMPLEMENTED`。
- [ ] **P1-E09｜实现 membership history 与可重建 projection** `[PLAT]`。reprocess 可移动/取消入组，总 Occurrence 数不变，group count 可重建。

### 5.7 P1-F：前端（可在 API 契约稳定后使用 mock 并行）

- [ ] **P1-F01｜建立 React/TypeScript/Vite 工程** `[UI]`。接入 Ant Design、TanStack Query、类型生成与测试；不创建登录页。
- [ ] **P1-F02｜实现 Workspace 列表与概览** `[UI]`。展示 Crash Occurrence、按 Version 计数、Unclassified、Top groups、符号完整率、失败率和耗时；Hang/Unknown/Rejected 分栏。
- [ ] **P1-F03｜实现 Build 页面与 Manifest/Artifact 上传** `[UI]`。展示角色、verification、FASTLINK/mismatch、缺失模块；Phase 1 source bundle 明确显示未启用。
- [ ] **P1-F04｜实现 Dump 上传流程** `[UI]`。浏览器直传 RustFS，显示上传与验证状态，支持 capture profile 和 reported build。
- [ ] **P1-F05｜实现 Occurrence Report** `[UI]`。Overview、Crash Stack、All Threads、Modules、Raw Metadata、Similar Crashes；不实现 Memory 页。
- [ ] **P1-F06｜实现栈与质量展示** `[UI]`。展示绝对/相对地址、debug ID、函数/源码、inline、frame trust；`scan` 有低可信提示；完整显示 `quality.warnings[]`。
- [ ] **P1-F07｜实现 Symbol Health 页面** `[UI]`。missing/mismatch 可下钻到受影响 Occurrence。
- [ ] **P1-F08｜实现 Exact Group 页面（若 P1-E07 完成）** `[UI]`。显示代表栈、first/last seen、Build 分布和 Occurrence；无 Family 图，无 merge/split 按钮。
- [ ] **P1-F09｜实现轮询策略** `[UI]`。分析中 2 秒、排队中 10 秒、页面不可见暂停；终态停止轮询。
- [ ] **P1-F10｜实现原始下载开关体验** `[UI]`。默认隐藏/禁用；API 返回 disabled 时不泄漏 URL；启用时明确提示匿名内网风险。

### 5.8 P1-G：安全、运维与可观测性

- [ ] **P1-G01｜完成 Compose 网络隔离** `[OPS]`。Core 网络仅连 Symbolicator；Worker 才能连 RustFS/PostgreSQL/Redis；默认阻断 Core 公网。
- [ ] **P1-G02｜实现可信内网部署检查** `[OPS]`。检测无认证 + 公网 bind 并给出强错误/警告；反向代理只做 TLS、路由和来源日志。
- [ ] **P1-G03｜锁定 RustFS 安全配置** `[S3/OPS]`。私有 Bucket、SSE、独立服务凭证、短 TTL 预签名、Console 不发布；镜像按通过资格测试的 digest 固定。
- [ ] **P1-G04｜实现匿名 operation log** `[PLAT/OPS]`。记录 actor=anonymous、时间、request ID、IP、User-Agent、动作、目标、结果；不把 IP 当身份。
- [ ] **P1-G05｜实现下载总开关与无 DELETE 保证** `[PLAT/QA]`。默认拒绝 DMP/PE/PDB 下载；API 路由测试证明没有 DELETE endpoint。
- [ ] **P1-G06｜实现 retention** `[PLAT/S3]`。Workspace 默认 180 天；对象过期只标记 Blob deleted，不删除 Occurrence/摘要/历史计数；清理写 operation log。
- [ ] **P1-G07｜实现本地紧急删除 CLI** `[PLAT/OPS]`。仅本机运维使用，精确目标、显式确认、操作日志与恢复边界有文档；不暴露 Web/API。
- [ ] **P1-G08｜实现日志脱敏** `[PLAT/OPS]`。禁止内存字节、源码正文、令牌、存储凭证和完整预签名 URL；用自动测试检查典型泄漏。
- [ ] **P1-G09｜建立监控与容量指标** `[OPS]`。队列深度、各状态耗时、失败/超时/OOM、Symbolicator 冷缓存、RustFS 错误、磁盘与对象增长可观测。
- [ ] **P1-G10｜验证容量基线** `[QA/OPS]`。100 dumps/day、峰值 5 任务下不丢任务；≤64 MiB p95 目标 10 分钟、64–256 MiB 目标 20 分钟，冷 Microsoft 符号单独计量。
- [ ] **P1-G11｜建立 PostgreSQL/RustFS/配置备份恢复演练** `[OPS]`。完成标准：从备份恢复后 Current Analysis、对象哈希和统计一致，步骤有时间与责任边界记录。
- [ ] **P1-G12｜形成内网部署手册** `[OPS]`。包含安装、升级、digest、TLS、网络边界、备份、恢复、retention、紧急 CLI 和回滚。

### 5.9 Gate P1：最小可用平台验收

- [ ] **GATE-P1-01｜正确 DMP + PDB + PE**：输出函数、文件、行号。
- [ ] **GATE-P1-02｜错误 PDB**：明确 mismatch，静默错误符号为 0。
- [ ] **GATE-P1-03｜有 PDB 无 PE**：仍有 PARTIAL 结果，unwind 质量正确下降。
- [ ] **GATE-P1-04｜后补符号 reprocess**：创建新 Run、保留旧 Run、Occurrence 总数不变。
- [ ] **GATE-P1-05｜去重边界**：同 Workspace 同 SHA 返回同一 Blob/Occurrence，跨 Workspace 不共享业务对象。
- [ ] **GATE-P1-06｜API 重启**：Redis 中已入队任务不丢。
- [ ] **GATE-P1-07｜Symbolicator 重启**：平台可重提，不依赖旧 request ID。
- [ ] **GATE-P1-08｜Core 故障隔离**：Core crash/timeout/OOM 不影响 API 和其他任务。
- [ ] **GATE-P1-09｜大文件边界**：DMP 字节不经 API，>256 MiB 被拒且不入队。
- [ ] **GATE-P1-10｜Workspace 符号隔离**：同名 PDB 只按 debug ID 与 Workspace scope 查找。
- [ ] **GATE-P1-11｜Build 歧义**：返回 ambiguous/unresolved，不猜 Version。
- [ ] **GATE-P1-12｜Unclassified**：无精确故障业务模块或非 scan in-app 帧时不构造 Exact。
- [ ] **GATE-P1-13｜Current Analysis 统计**：reprocess 改变 Build/Group 后，实时分类更新但总 Occurrence 数不变。
- [ ] **GATE-P1-14｜统计口径**：Hang/Unknown/Rejected 不进入 Crash Occurrence 数。
- [ ] **GATE-P1-15｜匿名内网边界**：默认原始下载被拒、无 DELETE、无登录/RBAC、不可公网访问。
- [ ] **GATE-P1-16｜端到端用户验收**：在目标内网由非开发人员完成“创建 Workspace → 创建 Build → 上传 Manifest/PE/PDB → 上传 DMP → 查看报告/统计 → 后补符号并 reprocess”。
- [ ] **PHASE-1 完成**：GATE-P1-01–16 全部通过；如果 Exact Group 未实现，发布说明必须明确 Unclassified 为正常路径且不影响统计。

## 6. Phase 2 — CI、符号与构建体系

进入条件：Phase 1 稳定运行并收集到真实的上传/补符号摩擦点。以下工作可按反馈拆分发布，不需要一次完成。

- [ ] **P2-01｜实现 CI 上传 CLI** `[PLAT]`。支持创建/定位 Build、提交 Manifest、分片上传 PE/PDB、等待 verification；命令可重试且幂等。
- [ ] **P2-02｜将 Manifest 从推荐提升为 CI 强校验** `[PLAT/QA]`。错误角色、缺 entrypoint、产物缺失在 CI 阶段失败。
- [ ] **P2-03｜支持 source bundle ingest 与源码上下文** `[PLAT/SYM/UI]`。先定义安全/大小/路径规范和新契约版本，再接入 Symbolicator 与报告。
- [ ] **P2-04｜优化后补符号体验** `[PLAT/UI]`。从 missing symbol 直接定位 Build/模块、上传、批量 reprocess，并明确影响范围。
- [ ] **P2-05｜实现 Workspace 级 in-app 覆盖规则** `[PLAT/CORE]`。规则版本化，变更触发 reprocess；系统模块否认下限不能被普通配置绕过。
- [ ] **P2-06｜增加 SSE 任务进度** `[PLAT/UI]`。保留轮询降级路径，不改变分析状态机语义。
- [ ] **P2-07｜建立 CI 生产者兼容矩阵** `[QA]`。MSVC 完整 PDB 保持基线；clang-cl/Crashpad 只有 fixture 与 Golden 指标通过后才标记支持。
- [ ] **GATE-P2｜Phase 2 验收**：CI 新 Build 可自动登记并上传完整产物；后补符号链路可观测、可恢复；新契约保持旧版可读。

身份与权限不在本阶段默认范围内。若未来决定增加认证/RBAC/SSO，必须先重新确认信任边界并创建新的 ADR，不能直接在当前数据模型中加入半成品权限表。

## 7. Phase 3 — Family Group 与趋势

- [ ] **P3-01｜建立 Family 算法训练/验证数据集** `[FIX/QA]`。使用历史 DMP 标注同根因/不同根因，覆盖跨 Build、inline、编译器编号和异步包装。
- [ ] **P3-02｜定义版本化 Family 特征与契约** `[CORE]`。去除 build-specific ID/绝对地址等，保留异常类别、逻辑模块和归一化函数序列；不得直接照搬未校准阈值。
- [ ] **P3-03｜校准相似度阈值** `[CORE/QA]`。分别报告误合并和误拆分；不满足安全阈值时允许保持 Unclassified。
- [ ] **P3-04｜实现 Family 自动分组与证据** `[CORE/PLAT]`。每次自动决策写 `grouping_evidence_json` 和算法版本。
- [ ] **P3-05｜实现人工 merge/split** `[PLAT/UI]`。保留历史、可逆、写 operation log，不篡改 Analysis Run。
- [ ] **P3-06｜实现趋势与回归检测** `[PLAT/UI]`。按 Occurrence 的 Current Analysis 计算，明确时间窗、Build/Version 口径和基线。
- [ ] **P3-07｜实现 Issue 链接与状态流转** `[PLAT/UI]`。先做链接与自由文本，不暗示已有用户身份或权限。
- [ ] **GATE-P3｜Phase 3 验收**：Family 误合并率满足经确认的门槛，所有自动/人工分组可解释、可追溯、可重建。

## 8. Phase 4 — Hang 与深度分析

Phase 4 不是对现有 crash 路径的无条件扩展；每一种新输入类型都要有独立契约、引擎边界和验收数据。

- [ ] **P4-01｜定义多 Dump Hang Session 领域模型**。Session 与 Occurrence/Analysis Run 的关系先写入 CONTEXT/设计，避免把多个 DMP 错计为一个或多个 Crash Occurrence。
- [ ] **P4-02｜实现 Hang 多次采样采集规范** `[FIX]`。记录间隔、线程身份稳定性、采集失败和终止条件。
- [ ] **P4-03｜实现线程签名多重集合与 Hang 对照** `[CORE/QA]`。只报告证据，不把静态栈自动宣传为死锁证明。
- [ ] **P4-04｜评估并隔离 Windows CDB Worker** `[OPS/QA]`。明确哪些样本 Linux 路径不足、数据如何传输、凭证与网络如何隔离、成本是否可接受。
- [ ] **P4-05｜为 .NET Dump 建立独立引擎路径**。不得复用 Native C++ 结论或宣称现有 Schema 自动兼容。
- [ ] **P4-06｜为内核 Dump 建立独立引擎路径**。先重新定义安全、体积、保留和访问控制；当前匿名平台边界不得直接承载。
- [ ] **GATE-P4｜Phase 4 验收**：每个已发布的深度分析类型都有独立支持矩阵、Golden 数据、失败语义和安全审查。

## 9. 持续性清单（每个阶段都执行）

以下项目不是一次性勾选后永久结束；每次依赖、契约或部署变更都要复核。

- [ ] **CONT-01｜契约兼容性**：稳定 v1 之后新增字段也发布新版本，保留旧 reader 与回归样本。
- [ ] **CONT-02｜依赖与镜像固定**：Core、Symbolicator、RustFS、基础镜像均记录版本和 digest；升级先跑 Golden/S3 回归。
- [ ] **CONT-03｜零静默错误符号**：任何 release 都必须保持该指标为 0。
- [ ] **CONT-04｜统计不重复**：任何 reprocess、迁移、重放、恢复测试都验证每个 Occurrence 只计一次。
- [ ] **CONT-05｜Workspace 不串扰**：对象 key、数据库查询、Symbolicator scope、缓存和统计均有跨 Workspace 负例。
- [ ] **CONT-06｜匿名内网边界**：无登录不等于无边界；每次部署确认没有公网暴露、长期客户端凭证或默认 raw 下载。
- [ ] **CONT-07｜恶意输入回归**：DMP/PDB/PE/ZIP 模糊测试、大小/数量/路径/超时边界持续运行。
- [ ] **CONT-08｜备份恢复演练**：按运行制度周期执行并记录恢复时间、数据缺口与哈希一致性。
- [ ] **CONT-09｜文档同步**：实现行为、设计、Schema、OpenAPI、CLI help 和部署手册保持一致。

## 10. 当前可立即领取的工作包

没有额外产品决策阻塞以下工作，可直接并行开工：

1. `CORE`：BASE-06 → P0-A01 → P0-A02/P0-A03 → P0-B02/P0-B03。
2. `FIX`：BASE-06 → P0-A05 → P0-B01 → P0-D01/P0-D02。
3. `SYM`：P0-B04；拿到首个 PE/PDB 后继续 P0-B05。
4. `S3`：P0-E01 → P0-E02 → P0-E03–E09。
5. `QA/OPS`：BASE-05/BASE-07、Core 镜像与 fixture harness 的 CI 骨架。

第一个可演示里程碑不是网页，而是：

```text
一个可重复生成的 x64/MSVC 空指针 DMP
  + 精确匹配 EXE/PDB
  → dmp-core inspect
  → rust-minidump unwind/trust
  → Symbolicator symbolicate
  → analysis-result-v0.1 Canonical JSON
  → 自动与 WinDbg/CDB expected 对比通过
```

完成该里程碑后勾选 P0-B10，再扩大 Golden 集；不要提前把一次性样例当作 Phase 0 已完成。
