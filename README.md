# Crash-Cap

Crash-Cap 是**部署在 Linux 上、解析 Windows 原生崩溃**的 Minidump 分析平台。目标范围是
Windows x64、用户态、MSVC 编译的 C/C++ 程序。

它的产出不是一段格式化调用栈，而是**带证据、质量等级、版本信息与可解释分组依据的结构化事故报告**：
每个 DMP 变成一份版本化的 Canonical JSON，缺失或错配的符号会被明确标注，而不是被静默忽略。

部署形态是**匿名可信内网**：没有登录、没有 RBAC、没有 DELETE 接口、明文 HTTP。这不是遗漏，而是
已记录的架构决策（[ADR-0003](docs/adr/0003-run-anonymously-on-a-trusted-intranet.md)、
[ADR-0005](docs/adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md)）。服务
MUST NOT 暴露公网。

## 组成部分

| 组件 | 目录 | 职责 |
| --- | --- | --- |
| `dmp-core` | `core/` | Rust CLI：`inspect` / `analyze` / `identify`，产出 Canonical v1 |
| `artifact-identity` | `artifact-identity/` | 共享的有界 PE/PDB 身份解析（`code_id` / `debug_id`） |
| `crashcap` | `crashcap-ci/` | Rust 发布器：本地开发机与 CI 都用它发布 Build |
| 契约测试 | `tests/schema/` | Draft 2020-12 契约兼容矩阵 + `validate-instance` |
| 机器契约 | `contracts/` | analysis-result / build-manifest / task-message / publication… |
| API | `platform/api/` | FastAPI 控制面（`crashcap_api`），不接触二进制字节 |
| Worker | `platform/worker/` | Dramatiq 任务面：落盘、起沙箱跑 Core、fenced 回写 |
| 运维 CLI | `platform/cli/` | 仅本地使用的 `crashcap-ops` |
| 前端 | `platform/frontend/` | React 19 + TS + Vite + Ant Design + TanStack Query |
| 迁移 | `platform/migrations/` | 独立 Alembic script location |
| 部署 | `deploy/`、`infra/` | Compose 栈、Dockerfile、Symbolicator gateway、RustFS |

运行时依赖：PostgreSQL、Redis、RustFS（通过标准 S3 契约，
[ADR-0004](docs/adr/0004-use-rustfs-through-the-s3-contract.md)）、单实例 Symbolicator，以及按任务
拉起的一次性 `dmp-core` 容器。

## 一次分析是怎么走完的

```text
浏览器/CLI ──uploads:init──> API ──预签名 URL──> 对象存储（API 不中转字节）
                                │
                          complete ──> 同一 PostgreSQL 事务写业务状态 + task intent
                                            │
                                    relay ──至少一次──> Redis
                                            │
                            Worker（lease + 单调 generation 取得所有权）
                                │  验证：服务端权威 SHA-256（客户端 hash 只是 hint）
                                │  freeze：identity / time / engine / artifact / source facts
                                └──> 一次性 dmp-core 容器 ──> Symbolicator ──> Canonical v1
                                            │
                          Worker 只 stage / 校验 / 存储 / finalize（无 post-assembly mutation）
                                            │
                              Current Analysis 晋升（generation-fenced）→ 统计与分组
```

## 必须先理解的领域区分

规范定义见 [CONTEXT.md](CONTEXT.md)。这几组区分在代码、测试和文档里都必须成立：

- **Occurrence ≠ Analysis Run**：同一 Workspace 内一份内容唯一的、被接受的 DMP 永远只是一个
  Occurrence；重新分析创建新的不可变 Analysis Run，不增加崩溃次数
  （[ADR-0002](docs/adr/0002-separate-occurrences-blobs-and-analysis-runs.md)）。
- **Current Analysis ≠ 最新一次尝试**：只有 `COMPLETE|PARTIAL` 的 Run 能晋升，且按 Run 创建顺序
  单调前进。较新 Run 失败不清空旧成功结果，较老 Run 迟到不覆盖较新成功结果。
- **Build ≠ Version**：Build 是一次精确产物集合，由内容指纹识别
  （`build-content-v1`，[ADR-0010](docs/adr/0010-identify-builds-by-content-and-track-publications.md)）；
  Version 只是用于聚合的人类标签。
- **Artifact ≠ Artifact Blob**：Blob 是 `(Workspace, 服务端验证的 SHA-256)` 标识的不可变字节，
  在 Workspace 内去重；Artifact 仍是 Build 范围的精确期望绑定。信任永不跨 Workspace
  （[ADR-0011](docs/adr/0011-deduplicate-artifacts-as-workspace-scoped-blobs.md)）。
- **只做身份匹配**：模块按 `code_id`（仅取自 PE）与 `debug_id`（PDB 7.0 RSDS GUID+age，小写无
  连字符）匹配，绝不按文件名或产品版本号。错误 PDB 是 `pdb_mismatch`，MUST NOT 符号化该模块；
  符号缺失产生 `PARTIAL`，不是 `FAILED`。
- **Hang 必须是采集意图**：没有异常信息本身只能得到 `unknown`。Hang / Unknown / rejected upload
  都不进入 Crash Occurrence 统计。

## 快速上手

前置：Rust 1.80+（CI 固定 1.96.1）、Python 3.12+ 与 uv、Node 24 与 pnpm 11。

Rust 工作空间（仓库根目录，4 个 crate）：

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test -p crash-cap-schema-tests            # 契约兼容矩阵
```

Python 平台（全部在 `platform/` 下运行）：

```bash
uv sync --extra dev
uv run pytest                                   # SQLite + 本地对象存储 + 内存队列
uv run ruff check .
uv run mypy api worker cli                      # strict
python -m alembic -c migrations/alembic.ini upgrade head --sql   # 只渲染 DDL，不需要数据库
```

前端（`platform/frontend/`）：

```bash
pnpm install
pnpm test                  # vitest run
pnpm lint                  # tsc --noEmit
pnpm build
pnpm openapi:check         # 响应模型改动后必须跑，漂移即失败
```

聚合门禁（仓库根目录）——真正决定「做完了」的是这些：

```bash
python scripts/phase2/gate.py        # 当前完整门禁：rust + schema + python + frontend
python scripts/schema/validate.py
python scripts/ci/check_markdown_links.py
python scripts/core/verify_oci.py    # 构建 deploy/core/Dockerfile 并校验固定 digest
```

校验一份产出的 Canonical JSON：

```bash
cargo run -q -p crash-cap-schema-tests --bin validate-instance -- \
  contracts/analysis-result-v1.schema.json path/to/canonical.json
```

## 发布 Build（开发机与 CI）

`crashcap` 把已经编译好的 Windows x64 MSVC EXE/DLL 与完整 PDB 7.0 发布到平台。它不执行
MSBuild/CMake、不克隆仓库、默认不上传源码。已签名的发布产物与校验和位于
[`tools/crashcap/`](tools/crashcap/README.md)：

```text
本机完成 MSVC 编译
  -> crashcap init（首次）
  -> crashcap validate
  -> crashcap doctor
  -> crashcap publish --profile release
  -> crashcap-publication.json + 网页 Ready/Sealed
```

Build Publication 是幂等的，记录 `local` / `ci` 来源；当所有 Expected Artifact 都验证通过后
Build 封存（Sealed），此后 Manifest 与 Artifact 变更 fail closed。完整流程、校验和验证步骤和
故障排查见[发布指南](docs/integration/crashcap.md)。

## 部署

内网 Compose 部署以 `deploy/compose/phase1.yml` 为准，步骤、网络边界、凭证注入、备份恢复见
[Phase 1 内网部署手册](docs/operations/phase1-deployment.md)。

要点：Bucket 必须私有，浏览器只拿短 TTL、限定对象与动作的预签名 URL；Compose 中没有凭证默认值，
全部由部署系统在仓库外注入；Core 容器只能经 Symbolicator 出网，不挂 PostgreSQL / Redis / RustFS /
宿主机路径。

每个有风险的改动都走分级 flag，而不是一次性切换。所有 flag 都是 `CRASHCAP_*` 环境变量，
**API 与每个 Worker 的取值必须一致**：

| Setting | 取值 | 默认 |
| --- | --- | --- |
| `TASK_HANDOFF_MODE` | `legacy` / `shadow` / `outbox` | `legacy` |
| `CANONICAL_ASSEMBLY_MODE` | `legacy` / `shadow` / `core-final` | `legacy` |
| `SYMBOL_PROJECTION_MODE` | `legacy` / `shadow-soft` / `strict-writer` / `projection-read` | `legacy` |
| `ARTIFACT_BLOB_DEDUP_MODE` | `off` / `shadow` / `active` | `off` |
| `ANALYSIS_INPUT_SELECTION_MODE` | `legacy` / `shadow` / `active` | `active` |
| `BUILD_PUBLICATIONS_ENABLED` | bool | `false` |
| `RAW_DOWNLOAD_ENABLED` | bool | `false` |

迁移顺序是先加列、再 shadow、再读切换、最后清理。回滚方式是换回兼容镜像加 `legacy` flag，
**内容写入之后绝不做 schema 降级**。

## 契约与版本纪律

`schema_version 1.0`、`norm-v1.0`、`group-v1.0`、`exact-v1.0`、质量权重 `0.45 / 0.35 / 0.20`
都是**已冻结**的。改一条规则、一个枚举、一项约束或一种分桶方式，意味着发布新的契约/算法版本并
保留旧 reader；给 `additionalProperties: false` 的对象加一个可选属性不是绕过办法。

HTTP 表示的权威是 `platform/api/crashcap_api/response_models.py`：顶层模型 `extra=forbid`，
增删任何 wire 字段都是一次显式评审
（[ADR-0008](docs/adr/0008-use-explicit-http-representations-as-the-api-authority.md)）。
唯一例外是 Canonical——OpenAPI 在构建期按源文件 SHA-256 注入
`contracts/analysis-result-v1.schema.json`。浏览器从 `src/generated/openapi.ts` 取类型别名，
不要手写平行的 wire interface。

## 测试约定

测试断言领域语义，不是 HTTP 200。单元/契约测试通过 `Settings.for_test` 选择**显式**替身：
SQLite、磁盘对象存储、进程内 dispatcher、`core_executor="fake"`、`symbol_ingest_mode="fake"`。
生产路径（PostgreSQL、Redis、RustFS、一次性 `dmp-core` 容器）永不被静默替换。
`platform/tests/conftest.py` 提供 `Phase1Harness`（`create_workspace` / `upload_artifact` /
`upload_dump` / `drain()`），复用它，不要重新推导上传流程。

可选集成泳道**只有**在下列变量指向一次性数据库时才执行：`CRASH_CAP_TEST_DATABASE_URL`
（PostgreSQL）、`CRASHCAP_TEST_REDIS_URL` / `CRASH_CAP_TEST_REDIS_URL`。marker：
`integration`、`compose`、`capacity`。

`fixtures/` 里只有**元数据与期望**；真实 DMP/PE/PDB 字节存放在私有对象存储，不得提交。
`expected.json` 可以为地址、路径、线程 ID 声明 `allowed_differences`，但异常码或 PDB mismatch
永远不是可选项。

`docs/evidence/` 是 Git 忽略的本机输出。门禁脚本诚实报告 `PASS` / `FAIL` / `SKIP`，绝不把 skip
或缺失输入转成 pass。**一次本机门禁通过不等于**远端 CI runner、目标内网 perimeter、生产
PostgreSQL 或真实 DMP 已经跑过同一条路径——写状态时必须保留这条边界。

## 权威顺序

来源冲突时按此顺序解决，不要自行发明产品规则：

1. [`contracts/*.schema.json`](contracts/README.md) —— 机器契约（稳定 `1.0` 不可变）
2. [`docs/design.md`](docs/design.md) —— 实现与评审权威（中文，带 § 编号）
3. [`docs/adr/`](docs/adr/0001-linux-native-versioned-analysis-core.md) —— 已接受的架构决策（ADR-0001 … ADR-0014）
4. [`CONTEXT.md`](CONTEXT.md) —— 规范领域词汇，含应当**避免**的说法
5. [`docs/implementation-roadmap.md`](docs/implementation-roadmap.md)、[`QA 首次上线指南`](docs/qa-symbol-import-guide.md) —— 交付范围与验收；[`QA 操作说明`](docs/qa-symbol-import-qa-operations.md) —— 上传和报告核对
6. [`miniprd.md`](miniprd.md) —— 仅历史蓝图，已被 `docs/design.md` 取代

另有 [任务失败矩阵](docs/architecture/task-failure-matrix.md) 按崩溃点列出失败语义。

## 约定

- Rust：edition 2021，MSRV 1.80，rustfmt `max_width = 100`、`use_small_heuristics = "Max"`。
- Python：3.12+，ruff 行宽 100，启用 `E,F,I,B,UP,SIM,S`（bandit），mypy `strict`。
- 换行由 `.gitattributes` 强制：`.rs/.py/.toml/.json/.yml/.md/.sh` 用 LF，
  **`.ps1/.bat/.cmd` 用 CRLF**。
- `docs/` 以中文为主；代码、标识符、注释与契约用英文。跟随所在文件的语言。
- 提交使用 Conventional Commit 前缀（`feat:`、`fix:`、`docs:`、`chore:`、`feat(ci):`）。
- 绝不记录原始内存、源码文本、token 或完整预签名 URL——`crashcap_api/redaction.py` 与
  `crashcap-ci/src/redaction.rs` 就是为此存在的，且有测试覆盖。

## 不做什么

Phase 1 明确 MUST NOT 实现：.NET dump、内核 dump、完整堆内存分析、WinDbg 扩展与 `!analyze -v`
兼容输出、自研 PDB/unwind 解析器、以 Breakpad `.sym` 为主符号化路径、Windows CDB Worker、
Family 模糊合并与人工 merge/split、回归检测、缺陷系统联动、ClickHouse/OpenSearch/Kubernetes
生产 YAML，以及登录、用户、角色、RBAC、多租户、SSO 与 Web/API 手工删除。

## 许可

MIT（见 `Cargo.toml` 的 `workspace.package.license`）。
