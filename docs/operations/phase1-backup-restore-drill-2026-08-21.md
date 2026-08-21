# Phase 1 G11 PostgreSQL/RustFS 备份恢复演练记录

> 本记录中的 HTTPS/CA 命令是 ADR-0005 之前的历史演练输入；恢复语义、对象哈希和清理证据仍保留。当前 Phase 1 已改为可信内网 HTTP-only，后续复验必须使用 HTTP endpoint 且不配置证书/CA。

日期：2026-08-21（Asia/Shanghai）
证据收集完成：2026-08-21T12:19:36+08:00
责任边界：本次仅由本机运维操作者执行，目标是唯一命名的临时 Docker 网络、容器和卷；没有对现有 `crash-cap-phase1-*` 容器、网络或卷执行写入、停止、删除或恢复。

## 1. 结论

状态：**PASS（隔离、合成 Phase 1 schema 演练）**。

在全新的 PostgreSQL 数据卷和 RustFS 数据卷上，恢复了由 Phase 1 Alembic migration 创建的实际 14 表 schema 及一个合成 Workspace/Build/Occurrence/Current Analysis/Crash Group 数据集。恢复后：

- `occ_g11.current_run_id=run_g11`、Analysis `status=COMPLETE`、`resolved_build_id=bld_g11`；
- Workspace、Build、Dump Blob、Occurrence、eligible Analysis Run、Crash Summary、Group、operation log 计数均与备份前一致（各为 1）；
- RustFS 6 个对象的 SHA-256、长度、HEAD 和 Range GET 均一致；
- `alembic_version=0001_phase1_initial`；
- `G11_POST_RESTORE_ASSERTIONS=PASS ... object_hashes=6 range_get=PASS`。

这不是生产、跨主机、加密密钥轮换、真实业务负载或 RPO/RTO 证明；数据集是合成 fixture，RustFS 使用本次临时栈自签名 CA 和临时凭证。

## 2. 运行边界和资源

宿主机 Docker Desktop：`29.6.1 linux/amd64`，context `desktop-linux`。盘点时已有 Phase 1 栈：PostgreSQL/RustFS healthy，但 API/Worker 正在 restart；它们没有被本演练操作。

宿主机没有 `aws`、`pg_dump`、`pg_restore`。为保持脚本真实执行，使用临时 PostgreSQL 容器内的 PostgreSQL 16 client 和 AWS CLI v2（Debian package 安装后报告 `aws-cli/2.9.19`），不修改宿主机。

本次资源前缀为 `crashcap_g11_drill_20260821_01`：

| 资源 | 名称 |
| --- | --- |
| network | `crashcap_g11_drill_20260821_01_net` |
| source volumes | `..._pg`、`..._rustfs` |
| restore volumes | `..._pg_restore`、`..._rustfs_restore` |
| backup volume | `..._backup` |
| S3 bucket | `crashcap-g11-private` |
| source/restore ports | `127.0.0.1:15433->5432`、`127.0.0.1:19000->9000` |

## 3. 关键命令和结果

### 3.1 真实备份

备份工具容器内的脚本路径为 `/tmp/repo/scripts/phase1/ops_backup_restore.sh`，Compose policy 为 `/tmp/repo/deploy/compose/phase1.yml`，外部秘密均通过 `/tmp/secrets/*` 文件注入。实际调用（秘密值未打印）：

```text
docker exec crashcap_g11_drill_20260821_01_postgres bash -ec \
  'export PGHOST=127.0.0.1 PGPORT=5432 PGDATABASE=crashcap PGUSER=crashcap \
   PG_PASSWORD_FILE=/tmp/secrets/pg_password \
   S3_ENDPOINT=https://g11-rustfs:9000 S3_BUCKET=crashcap-g11-private \
   S3_REGION=us-east-1 S3_ACCESS_KEY_FILE=/tmp/secrets/rustfs_access_key \
   S3_SECRET_KEY_FILE=/tmp/secrets/rustfs_secret_key \
   S3_CA_BUNDLE=/tmp/secrets/rustfs_ca.pem; \
   bash /tmp/repo/scripts/phase1/ops_backup_restore.sh backup /tmp/backup'
```

结果：退出码 0；生成 `/tmp/backup/postgres.dump`、`/tmp/backup/rustfs/`、`/tmp/backup/phase1.yml`、`/tmp/backup/checksums.sha256`。在原始路径执行：

```text
docker exec crashcap_g11_drill_20260821_01_postgres bash -ec \
  'cd /tmp/backup && sha256sum -c checksums.sha256'
```

结果：`/tmp/backup/postgres.dump: OK`、`/tmp/backup/phase1.yml: OK`。

### 3.2 恢复目标和前置条件

停止并删除 source 临时容器后，新建空的 `..._pg_restore`、`..._rustfs_restore` 卷/容器。第一次直接执行 restore 得到：

```text
/tmp/backup/postgres.dump: OK
/tmp/backup/phase1.yml: OK
fatal error: ... (NoSuchBucket) ... The specified bucket does not exist
```

这证明当前 `ops_backup_restore.sh` 不负责创建目标 Bucket。随后在全新 RustFS 卷上使用标准 S3 API 创建 private bucket、配置 SSE-S3 并 `head-bucket` 验证成功，然后重跑同一 restore 命令：

```text
bash /tmp/repo/scripts/phase1/ops_backup_restore.sh restore /tmp/backup \
  --confirm "RESTORE /tmp/backup"
```

结果：checksums 全部 OK，`Restore commands completed`，退出码 0。PG 使用 `pg_restore --clean --if-exists --no-owner`；S3 使用无 `--delete` 的 sync，因此不会静默删除额外目标对象。

注意：`checksums.sha256` 当前保存的是备份时的绝对路径（此处为 `/tmp/backup/...`）。恢复时必须把目录放在相同绝对路径，或由运维重新生成/审核 checksums；仅把目录移动到另一路径会使 `sha256sum -c` 找不到文件。

### 3.3 恢复后读回

使用宿主机 `platform/.venv` 的 SQLAlchemy/psycopg 和 boto3，只读查询恢复后的临时目标：

```text
platform/.venv/Scripts/python.exe - <post-restore verification>
```

验证内容：Current Analysis join、统计计数、`alembic_version`、每个对象的 HEAD/全量 SHA-256、每个对象的 Range `bytes=0-15`。输出：

```text
G11_POST_RESTORE_ASSERTIONS=PASS current_run_id=run_g11 status=COMPLETE resolved_build_id=bld_g11 counts=1,1,1,1 object_hashes=6 range_get=PASS
```

对象 SHA-256 manifest：

| Object key | Size | SHA-256 |
| --- | ---: | --- |
| `analysis/wsp_g11/occ_g11/run_g11/result.json` | 56 | `61436786d0d3418b87eb253dca015abab5985ac030cffccc1f4e89adbebe5098` |
| `dump-blobs/wsp_g11/blob_g11/original.dmp` | 37 | `c3b687ba6338ac6598bc5e09abc10e13fe43a74ba355d564c37f72f0d9202580` |
| `raw-builds/wsp_g11/bld_g11/app.exe` | 14 | `e9626defc87f9a254e9e4a6ee34fc712a33020685e1d55c35520cc648eaf100d` |
| `raw-builds/wsp_g11/bld_g11/app.pdb` | 15 | `ff3ac9e767a7ce7d7e4195f4c4e8e402df60f8b9bf33ed603ee0dc60f63fd021` |
| `raw-builds/wsp_g11/bld_g11/manifest.json` | 46 | `e7eeb7ea405188ae2b54c4f548ae043ba06752d1a0b329c5acce6e0fbb299202` |
| `sym-unified/wsp_g11/G11DEBUG/app.pdb` | 26 | `56fc218ef7f3cfe8b9d24a387af3977e94c63ad940a8e74b1279a12339892722` |

## 4. 清理和未证明项

清理已完成：本次创建的 `crashcap_g11_drill_20260821_01_*` 容器、网络和卷均已删除；`.runtime/phase1-g11-drill-20260821-01/backup-from-script/` 仅作为必要的审计证据保留，临时凭证、证书、payload 和 seed helper 已删除。现有 `crash-cap-phase1-*` 资源仍在运行，未被清理。

本记录不证明：生产 Compose 的 API/Worker 可用性、目标内网部署、跨主机/异机副本、备份加密密钥管理与轮换、自动暂停队列、真实用户数据、100 dumps/day 容量、RPO/RTO、服务启动后 Symbolicator 重查，或 PostgreSQL/RustFS 一致性窗口之外的写入行为。
