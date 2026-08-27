# Artifact Blob 去重上线、回填与回滚手册

本手册适用于 migration `0007_artifact_blob_dedup`。它只改变 Windows x64
PE/PDB 的物理存储复用；Build 的 Manifest、模块和 Expected Artifact 清单仍是精确且
不可变的。`xrtc_router.dll` 与 `xrtc_router.dll.pdb` 即使字节被复用，也必须继续作为
每个 lightstreamer Build 的 dependency 模块和两条期望记录存在。

## 不变量

- Artifact Blob 的身份是 `(workspace_id, server_verified_sha256)`；不同 Workspace 永不复用。
- Artifact 是 Build 范围的期望绑定。Blob-backed Artifact 仍投影 SHA-256、size、PE/PDB
  identity 与 canonical object key。
- canonical key 固定为
  `artifact-blobs/{workspace_id}/{sha256前两位}/{sha256}`。
- 只有 Worker/回填重新读取字节、计算 SHA-256、识别 PE/PDB 且拒绝 FASTLINK 后，Blob
  才能成为 `verified`。
- 符号发布状态属于精确 `(Workspace, PE Blob, PDB Blob)` pair。一个错误 pair 不会污染
  可与其他 PE 正确配对的 PDB Blob。
- content Build 只有所有精确期望及 pair 都 verified/published 后才 seal；首次 seal 只把
  `Workspace.symbol_inventory_version` 加一。
- 本里程碑没有自动 Artifact Blob GC。回滚保留 additive schema 和 canonical objects。

## 1. 升级前检查

先备份 PostgreSQL 与 RustFS，并确认 Compose 使用的是预期命名卷。不得执行 `down -v`、
`docker volume rm` 或用空卷替换现有卷。

```powershell
git status --short --branch
python scripts/phase2/gate.py
python scripts/phase1/deploy_check.py --json --runtime-env-file $env:PHASE1_RUNTIME_ENV_FILE
docker compose -f deploy/compose/phase1.yml config --quiet
docker compose -f deploy/compose/phase1.yml ps --all
```

升级镜像并运行 one-shot migration。普通 `up` 会复用命名卷；仍应先核对 `docker compose
config` 中解析出的卷名，不要加 `--renew-anon-volumes`。

```powershell
docker compose -f deploy/compose/phase1.yml build api worker frontend
docker compose -f deploy/compose/phase1.yml up -d migrate
docker compose -f deploy/compose/phase1.yml wait migrate
docker compose -f deploy/compose/phase1.yml up -d --wait api relay worker worker-verify worker-ingest frontend
```

## 2. 分阶段开关

`CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE` 默认 `off`，API 和 Worker 必须使用同一个值。

| 模式 | 行为 | 客户端能力 |
| --- | --- | --- |
| `off` | 保持 legacy 每 Build 对象与 ingest 行为 | 不广告 delivery-v1 |
| `shadow` | 上传照常进行；Worker 校验并建立 Blob/pair 观测数据 | 不广告 delivery-v1，不跳过上传 |
| `active` | Publication 登记绑定已验证 Blob；启用 claim、wait、reuse | 广告 delivery-v1 与 delivery-v2；旧客户端仍选 v1 |

推荐顺序是 `off -> shadow -> backfill -> active`。每次切换都重建 API 与所有 Worker，随后
检查 `/api/v1/artifact-producers`：只有 active 才应返回
`artifact_delivery_contracts=["artifact-delivery-v1","artifact-delivery-v2"]`。v2 只把 logical raw
身份与 wire encoding/size/SHA 分离，不改变 Workspace Blob claim 身份。

回退只需把模式改回 `off` 并重建 API/Worker。不要降级 migration 0007；存在任何
Blob-backed Artifact 时 migration 会拒绝 downgrade。

## 3. 已验证历史对象回填

命令默认 dry-run，并按 Artifact ID 游标分页。dry-run 也会读取、重新哈希和识别对象，但
不写数据库或复制 canonical object。

```powershell
crashcap-ops backfill-artifact-blobs --batch-size 100 --output artifact-blob-dry-run.json
```

检查每条 `cases[].outcome` 和 `gap_reason`。`object_missing`、`object_corrupt`、
`identity_rejected`、`fastlink` 等 gap 必须由运维确认真实来源；工具不会伪造 Build
fingerprint、Publication 或 seal 状态。

确认后应用同一批次：

```powershell
crashcap-ops backfill-artifact-blobs `
  --batch-size 100 `
  --apply `
  --confirm APPLY_ARTIFACT_BLOB_BACKFILL `
  --output artifact-blob-apply.json
```

若 `has_more=true`，把 `next_cursor` 原样传给下一次 `--cursor`。对同一批次重跑必须只
得到 `already_linked` 或已知 gap；canonical object 丢失时，只能从仍保留且重新验证
通过的旧对象修复。回填不删除旧对象。

## 4. active UAT

使用现有 lightstreamer Workspace 和真实 Build 输出做非破坏验收：

1. 先回填当前 `xrtc_router.dll` 与 `xrtc_router.dll.pdb`；记录 Artifact ID、Blob ID、
   SHA-256 和回填 JSON。
2. 发布 Build A：清单必须包含 lightstreamer EXE/PDB 与 xrtc DLL/PDB 共四条期望。
3. 发布 Build B：只改变 lightstreamer EXE/PDB，保持两个 xrtc 文件字节不变。
4. Build B 的回执和页面必须仍显示四条期望；lightstreamer 两条为 `uploaded`，xrtc 两条
   为 `reused`，最终 `ready=true` 且有 `sealed_at`。
5. 按 Workspace+SHA 查询 `artifact_blobs`，每个 xrtc SHA 必须恰好一行；两个 Build 的
   Artifact 绑定指向相同 `abl_`，但各自的 module/expectation 行都存在。
6. 两个 1.1.0 客户端同时发布首次出现的同一 Blob：一个 init 得到 `upload`，另一个得到
   `wait`；首个完成后两者绑定同一 `abl_`。中断首个 multipart 并让 lease 过期时，等待方
   必须能重新 init 并 takeover。
7. 若现有数据中有适配 Build 的真实 DMP，再执行 reported 与 auto-unique 分析并确认 xrtc
   函数/文件/行解析。没有合适 DMP 时必须把该项记录为未执行，不能用合成 fixture 替代。

安全回执只能包含 `artifact_blob_id` 与 `delivery=uploaded|reused|backfilled`；不得包含
canonical/legacy object key、其他 uploader、凭据或预签名 URL。

## 5. 指标与告警

以下指标的 label 均为有界枚举，不得加入 Workspace、SHA、文件名或 uploader：

- `crashcap_artifact_blob_deliveries_total{mode,disposition}`
- `crashcap_artifact_blob_bytes_total{disposition}`
- `crashcap_artifact_blob_claim_takeovers_total`
- `crashcap_artifact_blob_conflicts_total{reason}`
- `crashcap_artifact_blob_verification_seconds{kind,outcome}`
- `crashcap_artifact_blob_backfill_total{outcome}`

active UAT 至少要看到 xrtc 对应的 skipped bytes 增量。claim takeover、identity conflict、
backfill gap 或 verification failure 的非预期增长应阻断扩大流量。

## 6. 旧副本清理与紧急删除

UAT 完成前禁止删除 per-Build 旧对象。清理是独立命令，默认 dry-run；它只处理回填时
记录的 legacy copy，永不匹配 `artifact-blobs/` canonical key。

```powershell
crashcap-ops cleanup-artifact-blob-legacy-copies --batch-size 100 --output cleanup-dry-run.json
crashcap-ops cleanup-artifact-blob-legacy-copies `
  --batch-size 100 `
  --apply `
  --confirm DELETE_ARTIFACT_BLOB_LEGACY_COPIES `
  --output cleanup-apply.json
```

普通 `emergency-delete --artifact-id ...` 会拒绝 Blob-backed Artifact。共享 Blob 必须先取
impact report，再以包含精确 `abl_` ID 的确认短语执行；该操作会影响报告中的所有 Build：

```powershell
crashcap-ops emergency-delete-artifact-blob --artifact-blob-id abl_...
crashcap-ops emergency-delete-artifact-blob `
  --artifact-blob-id abl_... `
  --apply `
  --confirm "DELETE_SHARED_ARTIFACT_BLOB abl_..."
```

共享删除只标记 Blob `missing` 并保留关系/审计记录；后续必须通过已验证旧副本回填修复或
按新的未封存 Build 重新上传，不能静默 unseal 历史 Build。

## 证据边界

本机 SQLite/fake-core、Rust/frontend 测试和 Compose 静态检查只证明实现与契约。目标
PostgreSQL 并发、目标内网 S3 multipart、真实 lightstreamer/xrtc 字节、真实 DMP 符号解析、
浏览器展示和生产指标都必须在对应环境单独留证。
