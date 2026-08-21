# Phase 1 运维静态验证记录

> 这是实现早期的静态检查快照；后续真实 Compose、PostgreSQL/Redis、备份恢复与分析门禁结果见 [Phase 1 门禁验证记录](phase1-gate-validation-2026-08-21.md)。下文“尚未执行”和 TLS/CA 描述只记录当时的证据边界；当前 Phase 1 传输决策已由 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md) 改为可信内网 HTTP-only。

日期：2026-08-21（Asia/Shanghai）
范围：仅 Compose、运维脚本和 docs/operations；没有修改 platform 源码、implementation-roadmap.md 或已有 phase0 Compose。

## 已执行

| 检查 | 结果 | 证据边界 |
| --- | --- | --- |
| python -m py_compile scripts/phase1/*.py | PASS | 仅 Python 语法 |
| bash -n scripts/phase1/ops_backup_restore.sh | PASS | 仅 shell 语法 |
| python scripts/phase1/deploy_check.py --json | PASS | YAML topology/security static only；默认只警告未读取外部 Settings env |
| deploy_check.py --runtime-env-file -（stdin dummy CRASHCAP_*） | PASS | 验证 CRASHCAP_DATABASE_URL/REDIS_URL/S3 keys 命名；值未打印 |
| platform/.venv Settings smoke with CRASHCAP_* variables | PASS | 实际解析 environment/database/core_network/S3 endpoint/raw-download；没有连接外部服务 |
| docker compose -f deploy/compose/phase1.yml config --quiet | PASS | 使用外部占位 env/cert 路径；没有真实凭证，没有启动容器 |
| python scripts/phase1/ops_storage_init.py | PASS | dry-run；没有连接 RustFS |
| ops_emergency_delete.py dry-run | PASS | 仅精确 key 计划；没有删除对象 |
| ops_log_scan.py（空输入） | PASS | 没有日志内容可供扫描 |
| python scripts/ci/check_markdown_links.py | PASS | 49 个 Markdown 文件、51 个本地链接，无断链 |
| PHASE1_BIND_HOST=0.0.0.0 deploy_check.py | 预期 FAIL | 同时拒绝 API 和 Frontend wildcard bind，退出码 1 |
| emergency delete 错误 confirmation | 预期 FAIL | 退出码 2，没有 S3 请求 |

## 尚未执行

以下项目没有被本记录声称通过：

- Docker image pull/build、Compose up、目标内网 TLS/防火墙或浏览器端到端验收；
- PostgreSQL/RustFS 真实备份、恢复、对象 hash 对照、跨主机灾备或 RPO/RTO；
- 100 dumps/day、峰值 5 并发、10/20 分钟 p95、冷 Microsoft 符号和磁盘增长容量演练；
- 真实 RustFS private bucket/SSE 初始化（已有 Phase 0 RustFS 资格证据不等于本 Compose 已启动）；
- API/Worker/Frontend 的生产实现或无 DELETE 路由测试；Settings 运行时 TLS CA 信任和真实 S3 连通性仍未证明。

下一步由 Phase 1 平台实现合入 Dockerfile/入口后，在目标内网用外部 secret/cert 文件重新执行 Compose config、build/up 和 P1 Gate 端到端检查。
