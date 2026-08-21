# Phase 1 门禁验证记录（2026-08-21）

## 1. 结论与证据边界

本次在 Windows + Docker Desktop/Linux containers 上，以真实 PostgreSQL、Redis、RustFS、Symbolicator、Gateway、API、Workers、Frontend 和合成 DMP/PE/PDB 完成 Phase 1 验证。按 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md)，Phase 1 的 API、Frontend 与对象存储入口只使用 HTTP，不配置 HTTPS/TLS/CA；边界依赖批准私网或 loopback 绑定及网络不可达性。

| 范围 | 结果 |
| --- | --- |
| `GATE-P1-01`–`GATE-P1-14` | **PASS** |
| `GATE-P1-15` 匿名内网 HTTP 边界 | **PASS**；API、Frontend、RustFS 从批准 loopback 源可达，从隔离 outside namespace 对这些 loopback 端点均连接拒绝 |
| `GATE-P1-16` 端到端用户验收 | **PASS**；具名开发执行者完成浏览器流程、后补符号 reprocess 和签署记录 |
| `P1-G09` 监控面 | **PASS** |
| `P1-G10` 容量基线 | **PASS**；100 个唯一 DMP、并发 5、两档大小和冷 Microsoft 符号证据完整 |
| `PHASE-1 完成` | **PASS** |

`GATE-P1-15` 的结论只适用于本次 Docker Desktop host-loopback 目标。它不证明尚未部署、尚未探测的生产防火墙；部署到其他内网主机或集群时，必须针对新目标重跑 perimeter probe 与 UAT。外部 Microsoft 符号源继续使用其供应方 HTTPS，这不是 Crash-Cap 内网入口，也不违反 HTTP-only 决策。

## 2. 固定身份与 HTTP 运行环境

| 项目 | 身份/结果 |
| --- | --- |
| Phase 0 基线提交 | `990144fc506fd9a1cbac7208ce4271e86efa3728`，作者 `eugene.zheng <eugene.zheng@cloudsky.com>` |
| Core | `crash-cap/dmp-core:phase1`，digest `sha256:e75a50bdb953a450185c8d6666d470f9ba7f6985f6dee83e33f7c27d82f7ce9a` |
| Symbolicator | `sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959` |
| RustFS | `sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831` |
| 主验证栈 | Compose project `crash-cap-phase1`，API `http://127.0.0.1:58080`，Frontend `http://127.0.0.1:30080` |
| 容量/UAT 栈 | Compose project `crash-cap-phase1-capacity`，API `http://127.0.0.1:58081`，Frontend `http://127.0.0.1:30081`，RustFS `http://127.0.0.1:59000`，Metrics `http://127.0.0.1:59109` |

运行态共包含 PostgreSQL、Redis、RustFS、Symbolicator、Gateway、API、Frontend、4 类 Worker、Retention 与观测组件。API `/healthz`、`/readyz`、Frontend、RustFS ready 和 metrics 均返回 200。

`deploy_check.py --runtime-env-file .runtime/phase1-compose-gate/runtime.env --json` 为 **PASS / 88 checks**，`warnings=[]`、`errors=[]`。`docker compose ... config --quiet` 通过。检查确认：

- API、Worker、Retention 的 S3 endpoint 和浏览器 presigned endpoint 均为 `http://`；
- RustFS 不挂载证书、私钥或 CA，健康检查使用 HTTP；
- API、Frontend、ops-exporter 的 host port 只绑定 `127.0.0.1`；数据、队列、分析和 Core 网络继续隔离；
- 默认 raw download 关闭，无 DELETE、登录或 RBAC 路由；
- Core 网络探针只允许访问 Gateway，不能访问 PostgreSQL、Redis、RustFS 或公网探针。

## 3. 真实端到端与符号证据

### 3.1 HTTP 浏览器流程

具名执行者 `Codex implementation operator` 在容量/UAT 栈完成：

- Workspace：`wsp_01M0HKY830RQRRRHKHP4C4BGH2`（`Phase 1 HTTP Capacity`）；
- Build：`bld_01M0HMBJR69GYJABGQ2QRTN8XM`，Version `2026.08.21.http-uat`，Build number `http-uat-001`；
- Manifest、PE、PDB 通过浏览器直接上传 RustFS；PDB debug ID 为 `5295c1f4535d4f8aa0b1989805198bb815`；
- DMP Occurrence：`occ_01M0HMP2J1CY97SJVM2S0KC44F`；
- Analysis Run：`run_01M0HMP2J5WMFRGDBJ8YCNG92R`，`COMPLETE`，quality `1.0`；
- 报告顶帧：`crashcap::trigger_null_read()`，`null_read_target.cpp:76`；Modules 显示 entrypoint、code ID、debug ID 和 Build 匹配；raw download 显示禁用。

首次浏览器直传暴露了真实缺口：RustFS bucket 未配置 CORS，OPTIONS 响应没有 `Access-Control-Allow-Origin`，界面报告“对象存储上传网络错误”。修复后，初始化脚本为 bucket 应用精确的 `S3_CORS_ALLOWED_ORIGINS=http://127.0.0.1:30081`，允许 `GET/HEAD/PUT`，不使用 wildcard origin；浏览器 PE/PDB/DMP 直传随后全部成功。该修复已被离线 HTTP/CORS 测试覆盖，并写入部署与恢复手册。

### 3.2 后补符号与 Current Analysis

容量演练先产生 100 个没有业务符号的 `PARTIAL` / Unclassified Occurrence。上传匹配 Build/PE/PDB 后，对历史 Occurrence `occ_01M0HM00QNE1NQJKRYJBD81XXP` 强制 reprocess：

- 新 Run：`run_01M0HMZ2H6XMM4WFQFWX58ENJM`；
- 结果：`COMPLETE`，quality `1.0`，duration `3953.569 ms`；
- resolved Build：`bld_01M0HMBJR69GYJABGQ2QRTN8XM`；
- Exact Group：`grp_01M0HMP7K569BM7KDHPQK4MF6R`，组内 Occurrence 从 1 变为 2；
- 浏览器 Overview 的 Crash Occurrence 始终为 101，Unclassified 从 100 降为 99，Version 计数从 1 增为 2，Exact Group 总数仍为 1。

这证明 reprocess 创建新 Run、保留 Occurrence 身份、更新 Current Analysis/Build/Group 实时统计，不重复计数。

主验证栈还对既有 Occurrence `occ_01M0H9F7VT8GBSJTYQB62WCZ7X` 完成 HTTP 改造后的强制重处理：`run_01M0HKQAXRJGHBB66Z4D481FWR` 为 `COMPLETE`、quality `1.0`，顶帧仍为 `crashcap::trigger_null_read()` / `null_read_target.cpp:76`，Core digest 未变化。

### 3.3 错误与缺失符号

- 错误 PDB：Workspace `wsp_01M0H9VA33YR935DMDEA48ZF4B`，Artifact `art_01M0H9VFK2AJ534SNQDW7ZN8FJ` 为 `pdb_mismatch`；Run `run_01M0H9WZX0GQNJK54K6XFVCJ30` 为 `PARTIAL`、quality `0.35`，没有静默套用错误函数/file/line。
- PDB-only：Occurrence `occ_01M0H9YFFA4MPKA98NMVYZQDZS` 的初始 Run `run_01M0H9YFFGM7DBSQRBY0EQTEHX` 为 `PARTIAL`、quality `0.095454544`；后补 PE 后的新 Run 为 `COMPLETE`，旧 Run 全部保留，Occurrence 总数不变。

## 4. Gate P1-01–16 逐项结论

| Gate | 结果 | 主要证据 |
| --- | --- | --- |
| `GATE-P1-01` | PASS | 浏览器创建 Workspace/Build、上传 Manifest/PE/PDB/DMP；Run `run_01M0HMP2J5WMFRGDBJ8YCNG92R` 显示真实函数、文件、行号 |
| `GATE-P1-02` | PASS | `pdb_mismatch` Artifact + `PARTIAL` 报告，无静默错误符号 |
| `GATE-P1-03` | PASS | PDB-only Run `run_01M0H9YFFGM7DBSQRBY0EQTEHX` 正确降级 |
| `GATE-P1-04` | PASS | 后补 PE/PDB 后生成新 `COMPLETE` Run，旧历史和 Occurrence 身份保留 |
| `GATE-P1-05` | PASS | `(workspace_id, sha256)` 唯一约束、事务/并发测试与真实数据库核对；跨 Workspace 不共享业务对象 |
| `GATE-P1-06` | PASS | 排队 Run `run_01M0HBAWAEDGR66N73Q055WRCR` 在 API 重启后仍由 Redis 恢复并完成 |
| `GATE-P1-07` | PASS | Symbolicator 停止时新 attempt 失败但 current 保持；恢复后的 `run_01M0HBXRCKX5CAQ31BE2KZ82TA` 独立完成 |
| `GATE-P1-08` | PASS | 受限 Core crash/timeout/OOM 演练分别产生预期 exit/OOM 状态；API/其他 Worker 健康，随后分析完成 |
| `GATE-P1-09` | PASS | 浏览器和容量 runner 均为 presigned 直传；`>256 MiB` 在初始化阶段拒绝且不入队 |
| `GATE-P1-10` | PASS | Gateway 的 6 项测试确认 Workspace 私有源 scope，拒绝请求方指定 source |
| `GATE-P1-11` | PASS | Build resolution 覆盖 unique/ambiguous/conflict/manual/reported，不按 Version 猜测 |
| `GATE-P1-12` | PASS | 无精确非-scan 业务帧保持 Unclassified；100 个容量样本未构造伪 Exact Group |
| `GATE-P1-13` | PASS | 历史 Occurrence reprocess 后总数 101 不变，Unclassified/Version/Group current 统计实时更新 |
| `GATE-P1-14` | PASS | Crash/Hang/Unknown/Rejected 独立统计，只读取 `occurrences.current_run_id` |
| `GATE-P1-15` | PASS | HTTP-only perimeter probe 全部通过；outside namespace 对三类 loopback 入口均连接拒绝；raw=403、无 DELETE/login/RBAC |
| `GATE-P1-16` | PASS | 具名开发执行者完成浏览器流程、CORS 修复后复验、后补符号 reprocess，16 Gate 记录与签署齐全 |

## 5. 容量与可观测性证据

HTTP-only 容量结果保存在仓库外：

- `E:\crash-cap-capacity-http-20260821\evidence\capacity-gate.json`，SHA-256 `88249aed1ef6fc16c3f08e164ec5d8f47fdbac70092613c933f5766b6c4a38da`；
- `E:\crash-cap-capacity-http-20260821\evidence\capacity-gate.md`，SHA-256 `68f73b86f44aa755fa46b23651053a8ce16b50cd5f12b12b2c2ce708bf86aa42`；
- `E:\crash-cap-capacity-http-20260821\evidence\manifest-100.json`，SHA-256 `c9bb26e42eb032f49bd5557f7164da17c5f135ccc8328385fdf06830f8793c92`。

Runner 返回码为 0，顶层 `status=PASS`：

| 桶 | 样本 | p50 | p95 | p99 | 目标 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `<=64 MiB` | 80 | 15.266 s | 30.803 s | 41.641 s | p95 <= 600 s |
| `64–256 MiB` | 20 | 51.978 s | 57.399 s | 60.839 s | p95 <= 1200 s |

- 100/100 upload 为 `ACCEPTED`，100/100 Analysis 为成功终态 `PARTIAL`；没有业务符号时 `PARTIAL` 是预期结果；
- unique Blob、Occurrence、verified SHA-256 均为 100，duplicate upload 为 0；
- requested/local in-flight/queue 峰值均为 5，`verify`、`ingest`、`dump-small`、`dump-large` 四个队列均被采样；
- Core digest 为 **PROVEN**，所有样本只观察到固定 digest `sha256:e75a50...f7ce9a`；
- 四项 gate check `all_successful_terminal`、`p95_targets_met`、`size_buckets_complete`、`zero_loss` 全为 `true`；
- 冷 Microsoft 符号证据为 **PROVEN**：67 cache misses、6 次 HTTP body download、最长 26.369 s；这是外部供应方 HTTPS 依赖的独立测量。

统一 metrics 端点暴露队列深度、各状态时延/失败、Core 状态、RustFS OTLP/错误、Symbolicator StatsD/cold-cache、卷/磁盘/inode 和 Compose 服务资源指标；metrics、collector 与 Docker proxy 均保持只读/内网隔离。

## 6. HTTP 边界与 UAT 记录

`target_perimeter_probe.py` 结果写入 `.runtime/phase1-http-acceptance/perimeter-probe.json`，顶层为 `PASS`、`hard_failures=[]`、`not_proven=[]`。关键观察：

- 批准源 `127.0.0.1` 属于 `127.0.0.0/8`，API、Frontend、RustFS HTTP read-only 探针均返回 200；
- OpenAPI 共 26 条 path，无 DELETE 和 identity route；
- 指定 Occurrence 的 raw download 返回 403，并出现预期 error code；
- 隔离 bridge `crashcap_phase1_outside_probe_20260821` 中，来源 `192.168.32.2/3` 对 `127.0.0.1:58081`、`:30081`、`:59000` 均为 connection refused；
- outside 证据明确签署并声明只证明 Docker Desktop host-loopback 边界。

UAT 输入、结果与报告分别为：

- `.runtime/phase1-http-acceptance/uat-answers.json`；
- `.runtime/phase1-http-acceptance/uat-result.json`；
- `.runtime/phase1-http-acceptance/uat-report.md`；
- 无凭证的提交内副本：[Phase 1 HTTP UAT Sign-off](phase1-http-uat-signoff-2026-08-21.md)。

`uat_runner.py` 结果为 `PASS`，16/16 Gate 显式 `PASS`，`errors=[]`、`warnings=[]`、`pending_gates=[]`，`signoff_status=ATTESTATION_PRESENT`。执行人与签署人为同一具名开发执行者，符合当前“开发或运维均可验收”的口径。

## 7. 自动化与静态回归

| 命令/范围 | 结果 |
| --- | --- |
| Platform `pytest -q tests migrations/tests` | `85 passed, 2 skipped`；skip 仅为需要显式隔离 PostgreSQL/Redis 的集成项 |
| PostgreSQL 16 migration integration | `4 passed`；upgrade/downgrade、表/约束/null-safe unique 均通过；一次性容器已移除 |
| Redis 7.4 persistence integration | `1 passed`；dispatcher 重建后消息仍可消费；一次性容器已移除 |
| Platform `ruff check .` / `ruff format --check .` | PASS / 49 files |
| 本次修改的 6 个 Phase 1 Python 脚本 Ruff | PASS / formatted |
| `mypy --strict api worker cli` | PASS / 32 source files |
| `cargo test --workspace` | PASS / 63 tests |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo fmt --all -- --check` | PASS |
| Gateway unittest | PASS / 6 tests |
| Frontend Vitest | PASS / 10 tests |
| Frontend `pnpm lint` / `pnpm openapi:check` | PASS |
| Frontend `pnpm build` | PASS；仅 Vite chunk-size 非阻断 warning |
| `deploy_check.py --runtime-env-file ... --json` | PASS / 88 checks，0 warning，0 error |
| `docker compose ... config --quiet` | PASS |
| `bash -n scripts/phase1/ops_backup_restore.sh` | PASS（Git for Windows Bash） |

## 8. 后续部署要求

Phase 1 代码门禁已关闭，但每个新的内网部署目标仍必须：

1. 仅发布 HTTP，并把 API、Frontend、RustFS 限定在批准私网/loopback；
2. 以精确 origin 配置 RustFS bucket CORS，不允许 wildcard origin；
3. 从目标网段验证可达、从非目标网段验证不可达，并保存真实防火墙/来源证据；
4. 由具名开发或运维执行者对固定镜像/Compose 身份重跑 UAT；
5. 不把本机回归记录当作其他网络环境的自动授权。
