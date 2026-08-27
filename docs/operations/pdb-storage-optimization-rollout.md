# PDB 存储优化上线与回滚手册

本手册覆盖 migration 文件 `0008_artifact_blob_payloads_and_upload_gc.py`（revision
`0008_artifact_payloads_gc`）、`0009_artifact_delivery_v2_wire_identity.py`（revision
`0009_delivery_v2_wire`）、zstd canonical payload、终态 Upload GC 与内部 HTTP symbol source。
逻辑 Blob 身份、Build Manifest、Artifact expectation、Occurrence、Canonical 与 Exact grouping
语义不得改变。

## 安全边界

- 所有开关默认保持 `off`，Gateway source 默认 `filesystem`。
- Writer 进入 active 前，API、全部 Worker、Retention 和运维镜像必须已经支持双格式 Reader。
- raw canonical、legacy per-Build copy、Unified volume 是三套独立回滚源；目标真实 DMP
  等价、恢复演练和至少 14 天/两个发布周期宽限期全部通过前，一个也不删除。
- payload 缺失、stored hash 错、zstd 解码错或 raw size/hash/identity 错必须失败或重试；
  不允许继续符号发布或分析，不允许把错误符号标成 COMPLETE。
- 所有 apply 命令只接受固定确认短语；先保存 dry-run JSON。不得按前缀手工删除共享对象。

## Wave 0：迁移、双读与只读盘点

```powershell
crashcap-migrate
crashcap-ops pdb-storage-inventory `
  --output pdb-storage-before.json `
  --markdown-output pdb-storage-before.md
```

部署时保持：

```text
CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE=off
CRASHCAP_ARTIFACT_BLOB_COMPRESSION_MODE=off
CRASHCAP_ARTIFACT_UPLOAD_GC_MODE=off
WORKSPACE_SOURCE_MODE=filesystem
```

先验证 identity Blob 的发布、reprocess 和真实 DMP Canonical 基线。出现 zstd-only Blob 后不得
downgrade migration，也不得回滚到没有 `BlobMaterializer` 的镜像。

## Wave 1：dedup active、compression shadow、GC dry-run

API 与全部 Worker 一起切换 dedup active 和 compression shadow；Retention 使用 GC dry-run。
服务广告 delivery-v1 与 delivery-v2。shadow 产生 zstd、读回 stored/raw 双 hash 后立即丢弃，
不改变 canonical payload。

```powershell
crashcap-ops gc-upload-payloads --batch-size 100 --output upload-gc-dry-run.json
crashcap-ops backfill-artifact-payloads --batch-size 100 --output payload-dry-run.json
```

阻断条件：任何 silent corruption、identity conflict、未解释 gap、分析字段差异，或 codec RSS/
临时盘越界。

本机冻结语料证据见
[PDB compression benchmark](../evidence/pdb-compression-benchmark-20260827.md)：25 个批准的真实
PE/PDB 产物全部完成 zstd 往返 SHA-256 校验，PDB aggregate stored/raw 为 10.81%，单文件
p95 为 25.02%；341 MiB PDB 单次压缩/解压分别为 2.35/0.81 秒，峰值进程 RSS 约 90 MiB。
这只通过本机 D03/D05 门槛；语料仍缺接近 2 GiB PDB、不可压缩对照和更多产品族，不能替代
目标硬件 D04、真实 DMP 或目标 S3 UAT。

## Wave 2：compression active 与 delivery-v2

仅在批准 Workspace 灰度 `CRASHCAP_ARTIFACT_BLOB_COMPRESSION_MODE=active`。客户端优先协商
delivery-v2；PDB 以 zstd-v1 wire 上传，PE 保持 identity，旧服务或旧客户端继续 delivery-v1。
服务端分别验证 wire size/SHA 与解压后 logical size/SHA/PE-PDB identity。

历史 Blob apply：

```powershell
crashcap-ops backfill-artifact-payloads `
  --batch-size 100 --apply --confirm APPLY_ARTIFACT_PAYLOAD_BACKFILL `
  --output payload-apply.json
```

逐批传递 `next_cursor`。`unresolved_gaps` 必须为零或逐项签收，不能静默跳过。切换后的 raw
canonical 只进入 rollback 表，不立即删除。

## Wave 3：Upload GC active

默认保留 ACCEPTED 24 小时，REJECTED/QUARANTINED 7 天。只有终态 Upload、下游权威对象可
重新 HEAD/验证、无活跃 transfer/task/delete lease 时才可删 payload；Upload 行、状态、reason
和审计继续保留。

```powershell
crashcap-ops gc-upload-payloads `
  --batch-size 100 --apply --confirm DELETE_TERMINAL_UPLOAD_PAYLOADS `
  --output upload-gc-apply.json
```

观察 retained bytes/oldest age 与 GC outcome；删除失败重跑必须幂等收敛。
Retention 在内部 observability 网络的 `:9109/metrics` 暴露 GC outcome、bounded ineligible reason
和 Upload staging/PostgreSQL reconciliation；只有 `ops-exporter` 汇总该端点，不发布宿主机端口。
将 [PDB storage Prometheus rules](../../deploy/ops-exporter/pdb-storage-alerts.yml) 导入目标监控，
并按实际 retention 配置同步调整 24 小时/7 天告警阈值。任一 orphan、missing retained、
deleted-marker-present 或 size mismatch 都必须先解释，不能用手工删除让告警消失。

## Wave 4：内部 HTTP symbol source

先保持 Unified raw，设置 `WORKSPACE_SOURCE_MODE=http` 做专用 UAT。Gateway 只注入部署拥有的
Workspace + inventory source URL；调用方 sources/scraping 继续被拒绝。内部 source 只接受
当前 Workspace/inventory/debug-id 的 Unified `executable|debuginfo` 路径，通过 materializer
返回 raw 字节。downloaded cache 3 天、derived cache 30 天。

同一 DMP 必须逐字段比较 filesystem 与 HTTP 两条路径：异常码、崩溃线程、frames、函数、文件、
行号、inline、module match、quality warnings、Build resolution 和 Exact fingerprint。任何差异、
source 5xx 或 corruption 都阻断下一波。固定 Symbolicator 26.7.2 的 GET/HEAD/casing/cache 实测
证据必须来自目标镜像，单元测试不能替代。

固定镜像把 `downloaded` 策略应用到 `objects/auxdifs/il2cpp/sourcefiles/proguard`，把
`derived` 策略应用到 `object_meta/symcaches/cficaches/ppdb_caches/sourcemap_caches`；它们不是
名为 `downloaded/derived` 的两个物理目录。ops exporter 按该映射暴露：

```text
crashcap_ops_symbolicator_cache_scan_up{cache_kind}
crashcap_ops_symbolicator_cache_bytes{cache_kind}
crashcap_ops_symbolicator_cache_file_count{cache_kind}
crashcap_ops_symbolicator_cache_oldest_age_seconds{cache_kind}
```

Symbolicator cleanup 原生暴露各物理 cache 的 `symbolicator_caches_size_*`，发生删除时还会产生
`symbolicator_caches_size_files_removed_total`、`...bytes_removed_total` 和
`...metadata_bytes_removed_total`。当前 26.7.2 OTel 实测没有 hit/miss/refetch 计数；exporter 必须把
对应 capability 保持为 `supported=0`，不得把 size gauge 误报为命中率证据。因此 G04 的
hit/miss/refetch 部分和 G05 冷/热结论仍是 NOT_PROVEN。本机只读实测见
[Symbolicator cache governance evidence](../evidence/symbolicator-cache-governance-20260827.md)。
当前容量与 DB/S3/volume 差异解释见
[PDB storage capacity evidence](../evidence/pdb-storage-capacity-20260827.md)；该报告使用主库只读
快照的隔离迁移副本，未升级或修改主栈数据库，也不替代目标环境原子快照。

本机隔离的固定镜像协议 spike 可重复执行；它使用独立 Compose project/volume，结束时只清理
该项目自己的测试资源：

```powershell
python scripts/symbolicator/verify_http_source.py `
  --output docs/evidence/symbolicator-http-source-spike-20260827.json
```

数据库 zstd-only 到真实 Core 的本机预演使用专用 source-empty Symbolicator 配置，不允许静态或
Microsoft source 掩盖数据库失败。它为 filesystem、HTTP zstd 和同尺寸单 bit corruption 各建
独立 PostgreSQL/对象/cache 卷，运行真实生成的 x64 MSVC DMP，并在结束后只删除自己的 Compose
资源：

```powershell
uv run --project platform python `
  scripts/symbolicator/verify_database_zstd_real_dmp.py
```

机器与评审证据见
[PDB storage real-DMP equivalence](../evidence/pdb-storage-real-dmp-equivalence-20260827.md)。完整路径
必须保持 Canonical 全量等价；损坏路径必须由 source 返回 503，Core 不得产生业务函数，并必须
写入 `symbolicator_failed`，由 Worker 的 `symbolicator_` blocking warning 规则形成 PARTIAL。
该预演不替代 lightstreamer 产品 DMP、目标内网备份恢复、并发/重启或清理 UAT。

source/cache 故障恢复预演会验证两条互补路径：冷跑填充 cache 后重启 Symbolicator 并停止内部
source，必须零回源且 Canonical 不变；另一个全新项目在空 cache 时停止 source，必须只产生
`symbolicator_failed`/PARTIAL 证据和零业务符号，随后按精确 Compose 标签重建测试 cache、恢复
source，并再次 206 回源得到同一 Canonical：

```powershell
uv run --project platform python `
  scripts/symbolicator/verify_database_zstd_source_recovery.py
```

机器与评审证据见
[PDB storage source/cache recovery](../evidence/pdb-storage-source-recovery-20260827.md)。该预演仍不
替代目标环境的网络延迟/超时、cache 磁盘满、并发、多 Build、p95 或产品事故 DMP UAT。

本机备份恢复预演会先建立 PostgreSQL custom-format dump 和带逐对象 size/SHA-256 清单的
zstd-only 对象归档，再关闭源项目；随后在全新的 PostgreSQL、对象、Symbolicator cache 和空
Unified 卷中恢复，并用同一 DMP 做 Canonical 全量对照。最后对归档对象注入单 bit 损坏，要求
恢复非零退出且目标对象卷零文件。各阶段使用独立 Compose project/volume，结束时只清理自己的
资源：

```powershell
uv run --project platform python `
  scripts/symbolicator/verify_database_zstd_backup_restore.py
```

机器与评审证据见
[PDB storage backup/restore real-DMP evidence](../evidence/pdb-storage-backup-restore-20260827.md)。
该工具是本机 pre-UAT 验证器；其本地对象 tar 不是目标 RustFS/S3 备份方案，也不证明备份保留、
加密、签名、权限、目标网络或灾难恢复。正式 UAT 仍须使用目标备份工具与产品事故 DMP 重跑。
正式入口 `scripts/phase1/ops_backup_restore.sh` 要求全新备份目录，并为 PostgreSQL dump、Compose
policy 和 RustFS 镜像中的每一个对象生成相对路径 SHA-256；restore 必须在任何 DB/S3 写入前
全量验证该清单。目标演练仍需在一致性窗口内暂停写入并记录 RPO/RTO 与实际签署。

## Cleanup 与回滚

备份恢复后，先从 PostgreSQL 选择一个精确 verified `ArtifactBlob.id`，通过统一双格式 Reader
导出并核对 JSON 中 logical/stored 双 hash；命令拒绝覆盖现有目标文件，报告不包含对象键或
临时路径：

```powershell
crashcap-ops materialize-artifact-blob `
  --artifact-blob-id <exact-abl-id> `
  --destination <new-local-pe-or-pdb-path> `
  --output restored-artifact-materialization.json
```

该命令只证明指定 Blob 能完整物化。完整恢复仍必须在空 Unified/cache volume 上执行 reindex，
再用同一真实 DMP 比较 Canonical；不能用“导出 hash 相同”替代崩溃解析等价 Gate。普通 Artifact
预签名下载对 zstd payload 保持 409，避免把压缩字节伪装成原始 PE/PDB。

raw cleanup 在 retained_until 到期后仍先完整 materialize 当前 zstd payload，并确认旧 raw key
没有 Artifact 引用：

```powershell
crashcap-ops cleanup-artifact-payload-raw-copies `
  --batch-size 100 --output raw-cleanup-dry-run.json

crashcap-ops cleanup-artifact-payload-raw-copies `
  --batch-size 100 --apply --confirm DELETE_ARTIFACT_PAYLOAD_RAW_COPIES `
  --output raw-cleanup-apply.json
```

在目标真实 DMP、空 Unified/cache 恢复、备份恢复和宽限期 Gate 通过前禁止执行 apply，也禁止
清理 Unified raw。异常时先停止 compression Writer 与全部 GC/cleanup，把 source 切回
filesystem；`active -> off` 只阻止新压缩写入，不会改写现有 zstd Blob。raw 已清理后只能回滚到
支持 migration 0008/0009 和双格式 Reader 的镜像。

## 必留证据

- 升级前后 PostgreSQL/RustFS/Unified/cache inventory JSON + Markdown。
- compression benchmark、wire bytes、CPU/RSS/temp 和 Publication ready 时间。
- raw/zstd/filesystem/HTTP 的 Canonical 逐字段等价报告及真实 DMP/Build/Run ID。
- 至少一个 `materialize-artifact-blob` 恢复报告，以及其后空 Unified/cache reindex + 真实 DMP
  Canonical 对照。
- corruption、截断、伪造 logical hash、Worker restart、GC 重放和空 volume 恢复结果。
- 所有 dry-run/apply 报告、开关值、镜像 digest、备份 ID、实际 tester 与签署。

本机 fake store、SQLite、生成式 Golden DMP、Compose 静态检查只能证明实现与契约，不能替代
目标 PostgreSQL/S3/Symbolicator/真实 lightstreamer 产品 DMP UAT。
