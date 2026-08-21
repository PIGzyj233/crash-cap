# Phase 1 真实容量门禁 Runner

`scripts/phase1/capacity_gate.py` 是真实 API/Compose 负载工具。默认是
dry-run；只有显式 `--execute` 才会访问 API。工具不启动本地 FastAPI、不创建
SQLite/内存数据，也不会输出 HTTP 响应体、Presigned URL 或任何凭证。
按 ADR-0005，Runner 对 API、metrics 和 presigned upload URL 严格要求 `http://`，
拒绝 HTTPS、userinfo 和其它 scheme。

## PASS 工作负载

P1-G10 的 PASS 只能使用 `--workload upload`。该模式从仓库外的清单读取真实
DMP 文件，经 API 的 presigned PUT/multipart 上传，等待 `ACCEPTED`，再等待每个
Occurrence 的分析达到终态。报告必须证明：

- 恰好 100 个任务，客户端最大并发 5；
- 每个任务生成一个唯一 Blob 和一个唯一 Occurrence，且没有 duplicate upload；
- 每个 ACCEPTED 上传返回唯一 verified SHA-256，作为内容唯一性的附加核对；
- 样本同时覆盖 `<=64 MiB` 和 `64–256 MiB`（边界包含 64 MiB、256 MiB）；
- 两个分桶分别记录端到端 p50/p95/p99，p95 目标分别为 10 分钟、20 分钟；
- 记录实际队列深度峰值、terminal statuses、分析返回的 Core image digest；
- Microsoft cold-cache 有独立的外部证据文件。没有该证据时字段保持
  `NOT_PROVEN`，不能由总延迟或缓存命中推断。

`--workload reprocess` 只适合小样本真实队列 smoke。它复用已有
`/occurrences/{id}/reprocess`，即使所有任务成功，报告也固定为
`NOT_PROVEN`，因为它没有创建 100 个唯一 Dump/Blob。

## 输入清单

上传清单是 JSON、JSONL 或 CSV。每条上传任务至少需要已有 Workspace 和仓库外
真实 DMP 文件；推荐同时填入已登记 Build：

```json
{
  "tasks": [
    {
      "task_id": "small-0001",
      "workspace_id": "wsp_...",
      "reported_build_id": "bld_...",
      "payload_path": "/secure/capacity-dumps/small-0001.dmp",
      "capture_profile": "rich-crash"
    },
    {
      "task_id": "large-0001",
      "workspace_id": "wsp_...",
      "reported_build_id": "bld_...",
      "payload_path": "/secure/capacity-dumps/large-0001.dmp",
      "capture_profile": "rich-crash"
    }
  ]
}
```

必须准备 100 个内容真正不同的 DMP。小 DMP 可以在不影响解析的尾部加入唯一
标记；大桶样本必须是真实文件并大于 64 MiB、不得超过 256 MiB。重复使用同一
字节内容会触发平台去重，Runner 将因 Blob/Occurrence 不唯一而失败。若要验证
符号质量，清单中的 Build/Manifest/PE/PDB 应在隔离 Compose 环境中预先准备好；
Runner 不伪造这些生产前置数据。

仓库提供确定性的清单/样本生成器。它只读取一个仓库外的合法 DMP 模板，在尾部
写入唯一 marker，并为大桶创建超过 64 MiB 的逻辑填充；不会覆盖已有文件，也不会
删除样本。默认生成 80 个 small + 20 个 large，输出目录和清单必须放在仓库外：

```text
python scripts/phase1/capacity_fixture.py \
  --template /secure/fixtures/valid.dmp \
  --output-dir /secure/capacity-dumps/2026-08-21 \
  --manifest /secure/capacity/manifest-100.json \
  --workspace-id wsp_... \
  --build-id bld_...
```

如需调整分桶，`--small-count` 与 `--large-count` 仍必须合计 100，
`--large-size-bytes` 必须在 `(64 MiB, 256 MiB]`。该工具只生成上传输入，不能
替代真实 API、Blob、Occurrence、队列或分析证据。

Microsoft 证据文件必须由独立的 Symbolicator/Gateway 冷缓存观测生成，至少包含：

```json
{
  "status": "PROVEN",
  "cold_cache_downloads": 1,
  "cold_cache_duration_ms": 12345,
  "cache_hits": 99,
  "cache_misses": 1,
  "source_kind": "microsoft_symbol_server",
  "controlled_cache_reset_method": "isolated-cache-volume-recreated",
  "measurement_source": "Symbolicator Microsoft symbol download counters",
  "evidence_ref": "INC-123/cold-cache-2026-08-21",
  "observed_at": "2026-08-21T12:00:00Z"
}
```

## 运行命令

先做无副作用计划（不会访问 API）：

```text
python scripts/phase1/capacity_gate.py \
  --workload upload \
  --manifest /secure/capacity/manifest-100.json \
  --json-out /secure/capacity/capacity-gate.json \
  --markdown-out /secure/capacity/capacity-gate.md
```

在隔离的真实 Compose 环境中执行：

```text
python scripts/phase1/capacity_gate.py \
  --workload upload \
  --execute \
  --manifest /secure/capacity/manifest-100.json \
  --base-url http://phase1-intranet.example/api/v1 \
  --metrics-url http://phase1-intranet.example/metrics \
  --core-digest sha256:<64-hex-digest> \
  --microsoft-evidence /secure/capacity/microsoft-cold-cache.json \
  --json-out /secure/capacity/capacity-gate.json \
  --markdown-out /secure/capacity/capacity-gate.md
```

`--core-digest` 是可选的期望值；Runner 仍会从 Canonical analysis 的
`engine.core_image_digest` 收集实际观测值。JSON/Markdown 输出应保存在仓库外的
变更单或容量证据目录，避免把真实样本和运行数据写入工作区。若 Compose 只在
容器网络发布 RustFS，容量演练应使用隔离的临时 override 发布一个只绑定
loopback/批准私网且受防火墙限制的 HTTP 入口，并让
`CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 指向该入口。不要把 RustFS 公开到公网。

小样本 reprocess smoke 示例：

```text
python scripts/phase1/capacity_gate.py \
  --workload reprocess \
  --execute \
  --count 5 \
  --manifest /secure/capacity/reprocess-smoke.json \
  --base-url http://phase1-intranet.example/api/v1 \
  --json-out /secure/capacity/reprocess-smoke.json.report \
  --markdown-out /secure/capacity/reprocess-smoke.md
```

该命令的 `NOT_PROVEN` 是预期结果，不得作为 P1-G10 关闭证据。
执行模式下 `NOT_PROVEN`/`FAIL` 返回非零退出码；只有 `PASS` 返回零，dry-run
计划返回零。

## 结果解释

- `DRY_RUN`：只完成输入与分桶计划；没有网络或任务证据。
- `NOT_PROVEN`：没有丢失结论，但缺少真实两桶、队列、digest 或 cold-cache 证据，
  或使用了 reprocess smoke/非 100 任务范围。
- `FAIL`：出现 API/上传/分析丢失、非成功终态、重复 Blob/Occurrence、超过并发、
  或 p95 超标。
- `PASS`：仅在真实 upload workload 满足全部门禁条件后出现。
