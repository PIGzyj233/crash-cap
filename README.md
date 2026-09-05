# Crash-Cap

Windows x64 崩溃分析平台：上传 EXE / DLL / PDB / DMP，按 Workspace 或公共空间管理文件，查看崩溃栈、符号匹配、分析历史与分组。

当前为 **HTTP `/api/v3` + Canonical 2.0**。上传不再要求 Build / Manifest、Git 仓库或源码包。**v3 使用新空库，旧 Build 数据库不能直接升级；API、Worker、Core、前端和 CLI 必须配套使用。**

- [Docker 构建与启动](#docker-构建与启动)
- [本地开发与调试](#本地开发与调试)
- [上传与使用](#上传与使用)
- [构建参数](#构建参数)与[运行环境变量](#运行环境变量)

## Docker 构建与启动

在 **Linux x86_64** 仓库根目录执行。需要 Docker Engine、Compose v2 或更新版本、Bash、curl、OpenSSL 和 `acl` 包（getfacl/setfacl）。用于全新 v3 实例；已有旧版数据时先阅读[部署与回退说明](docs/operations/phase1-deployment.md)。

```bash
bash ./scripts/phase1/deploy_linux.sh
```

脚本自动生成并保留仓库外凭据、构建镜像、绑定 Core 镜像 ID、初始化数据库和存储、启动服务并检查就绪状态。默认打开 **http://127.0.0.1:30080**；API / Swagger 为 `http://127.0.0.1:8080/docs`，S3 Gateway 为 `http://127.0.0.1:59000`。

```bash
# 使用状态目录已保存的配置管理同一个实例
bash ./scripts/phase1/deploy_linux.sh --compose ps --all
bash ./scripts/phase1/deploy_linux.sh --compose logs -f --tail=100 api worker-verify automatic-analysis
bash ./scripts/phase1/deploy_linux.sh --compose stop
# 更新源码后重新构建并启动
bash ./scripts/phase1/deploy_linux.sh
```

默认状态目录为 `${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap`，可用 `CRASHCAP_DEPLOY_STATE_DIR` 指定；后续命令使用同一目录。默认项目为 `crash-cap-phase1`。并行实例还需独立卷、网络和端口，**仅修改项目名不会隔离显式命名的数据卷**。自定义参数、配置文件、远程访问和检查流程见[部署手册](docs/operations/phase1-deployment.md)。

## 本地开发与调试

工具链推荐与 CI 一致：**Rust 1.96.1、Python 3.12 + uv、Node 24.18.0、pnpm 11.10.0**。Python 支持 `>=3.12,<3.15`，Node 要求 `>=24.18.0,<25`；Core 声明最低 Rust 1.88。macOS / Windows 可本机开发前端、Python 和 Rust，完整服务使用 Linux 开发机或 VM。

```bash
# 仓库根目录
cargo build --locked -p dmp-core -p crashcap
cd platform
uv sync --frozen --extra dev
cd frontend
pnpm install --frozen-lockfile
```

前端热更新连接真实后端。**首次部署开发后端**时，从仓库根目录允许 Vite origin：

```bash
CRASHCAP_CORS_ORIGINS='["http://127.0.0.1:5173"]' \
S3_CORS_ALLOWED_ORIGINS='http://127.0.0.1:30080,http://127.0.0.1:5173' \
bash ./scripts/phase1/deploy_linux.sh

cd platform/frontend
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v3 pnpm dev --host 127.0.0.1
```

访问 **http://127.0.0.1:5173**。Vite 没有 API proxy，必须配置包含 `/api/v3` 的后端地址。已有实例需要编辑保存的 `runtime.env` 与 `compose.env` 并应用 CORS，具体命令见[本地开发指南](docs/operations/local-development.md#前端热更新与-cors)。`VITE_USE_MOCK` 当前无效；页面测试用 `createMockApiClient()` 注入测试数据。

```bash
# 仓库根目录：Rust 检查
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --locked --workspace --all-targets

# Python 普通回归
cd platform
uv run ruff check api worker cli tests migrations
uv run mypy api worker cli
uv run pytest -m 'not integration and not compose and not capacity'

# 前端检查与构建
cd frontend
pnpm lint
pnpm openapi:check
pnpm test
pnpm build
```

**API / Worker 源码挂载、热重载、宿主 IDE 进程、断点、Core 调试与真实 fixture 测试**见[本地开发指南](docs/operations/local-development.md)。API 契约变更后运行 `pnpm openapi:generate`；OpenAPI 命令需要已安装 Python 平台依赖。普通测试不代表真实上传和分析闭环通过，完整场景见[v3 验收](scripts/upload_v3/README.md)。

## 上传与使用

打开前端，创建 Workspace，在空间上传页选择文件或在平台上传页选择目标空间。公共空间适合共享 EXE/DLL/PDB，DMP 必须上传到 Workspace。“产物与符号”查看验收/配对状态；DMP 完成分析后从收件箱进入报告。

CLI 可从平台“开发者接入”页面下载，或使用仓库中的 Windows x86_64 / Linux x86_64 预编译文件；本地源码构建结果为 `target/debug/crashcap`（Windows 为 `.exe`）。

```powershell
# 将对应平台的 crashcap 放入 PATH 后执行；默认 Compose API 端口是 8080。
crashcap upload .\Release --workspace light-streamer --build-version 11.0.1.27 --api-url http://127.0.0.1:8080
crashcap upload .\sdk.dll .\sdk.pdb --public --build-version 3.2 --api-url http://127.0.0.1:8080
crashcap upload .\crash.dmp --workspace light-streamer --api-url http://127.0.0.1:8080 --receipt upload.json --json
```

| 选项 | 默认值 / 要求 | 说明 |
| --- | --- | --- |
| `<paths>...` | 至少一个 | 文件或目录；目录递归发现 EXE、DLL、PDB、DMP |
| `--workspace <ID或精确名称>` | 与 `--public` 二选一，必填其一 | Workspace 须预先创建 |
| `--public` | 默认关闭 | 上传到公共空间；含 DMP 时拒绝 |
| `--build-version <LABEL>` | 可省略 | 可选版本标签，不创建 Build，也不参与符号身份匹配 |
| `--api-url <URL>` | 优先于 `CRASHCAP_API_URL`；无隐式默认服务 | 根地址或以 `/api/v3` 结尾；根地址自动补前缀 |
| `--receipt <PATH>` | `crashcap-upload.json` | 逐文件回执文件，多次运行可指定不同路径 |
| `--json` | 默认关闭 | 输出机器可读结果 |
| `-h` / `--help` | — | 命令帮助；顶层 `--version` 查看版本 |

PE/PDB 可分别上传，等待配对也属上传成功。单个文件验收失败不会撤销同批其他成功文件。CLI 退出码：全部成功 `0`，部分文件失败 `1`，参数或整体错误 `2`。不再提供旧 `publish`、Build Manifest 或源码包上传。

## 构建参数

### 部署脚本选项

环境变量放在部署命令前；脚本的 `--help` 可查看用法。`--compose <args...>` 直接运行 Compose 子命令，使用已保存的 `compose.env`，不会执行完整部署步骤。

| 参数 / 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `--help` | — | 显示用法 |
| `--compose <args...>` | — | 管理已初始化实例，如 `ps`、`logs`、`stop`、`build` |
| `CRASHCAP_DEPLOY_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap` | 凭据与持久化配置目录，必须在仓库外 |
| `CRASHCAP_BUILD_PULL` | `1` | 构建时添加 `--pull`，设 `0` 使用已缓存基础镜像 |
| `CRASHCAP_BUILD_NO_CACHE` | `0` | 设 `1` 给 Core 和应用构建添加 `--no-cache` |
| `CRASHCAP_PULL_EXTERNAL_IMAGES` | `1` | 拉取 PostgreSQL、Redis、RustFS、Symbolicator 等服务镜像；设 `0` 跳过主动拉取 |
| `CRASHCAP_START_TIMEOUT_SECONDS` | `300` | 启动就绪等待秒数，至少 30 |

```bash
# 不刷新基础镜像和外部服务镜像（本地须已有所需镜像）
CRASHCAP_BUILD_PULL=0 CRASHCAP_PULL_EXTERNAL_IMAGES=0 bash ./scripts/phase1/deploy_linux.sh
# 排查构建缓存
CRASHCAP_BUILD_NO_CACHE=1 bash ./scripts/phase1/deploy_linux.sh
# 单独重建前端并启动
bash ./scripts/phase1/deploy_linux.sh --compose build frontend
bash ./scripts/phase1/deploy_linux.sh --compose up -d frontend
```

### 前端构建变量

`VITE_API_BASE_URL` 默认 `/api/v3`，`VITE_RAW_DOWNLOAD_ENABLED` 默认 `false`，由 Compose 的 `frontend.build.args` 传给 Dockerfile。例如同时启用页面入口和 API 原始下载：

```bash
VITE_RAW_DOWNLOAD_ENABLED=true CRASHCAP_RAW_DOWNLOAD_ENABLED=true \
bash ./scripts/phase1/deploy_linux.sh
```

**Vite 变量在构建时固化到 JS，修改后必须重新构建前端；仅重启容器无效。** `VITE_USE_MOCK` 不是有效构建参数。Python `CRASHCAP_*` 服务选项则在进程启动时读取。

<details>
<summary>全部 7 个 Dockerfile 自定义 ARG 与直接构建选项</summary>

基础镜像均附带固定 SHA256，下表省略摘要；完整引用见 [API](platform/api/Dockerfile)、[Worker](platform/worker/Dockerfile)、[前端](platform/frontend/Dockerfile)、[Core](deploy/core/Dockerfile)、[S3 Gateway](deploy/s3-gateway/Dockerfile)、[ops-exporter](deploy/ops-exporter/Dockerfile)。

| ARG | 默认值 | 适用镜像 |
| --- | --- | --- |
| `PYTHON_IMAGE` | `python:3.12.11-slim-bookworm@sha256:…` | API、Worker、ops-exporter |
| `UV_IMAGE` | `ghcr.io/astral-sh/uv:0.11.29@sha256:…` | API、Worker |
| `DOCKER_CLI_IMAGE` | `docker:29.6.1-cli@sha256:…` | Worker，提供启动 Core 容器的 Docker CLI |
| `NODE_IMAGE` | `node:24.18.0-bookworm-slim@sha256:…` | 前端构建阶段 |
| `NGINX_IMAGE` | `nginx:1.29.1-alpine@sha256:…` | 前端运行阶段、S3 Gateway |
| `VITE_API_BASE_URL` | `/api/v3` | 前端内嵌 API 地址，绝对 URL 必须包含 `/api/v3` |
| `VITE_RAW_DOWNLOAD_ENABLED` | `false` | 前端是否显示原始下载入口；API 仍是最终依据 |

Core Dockerfile **没有自定义 ARG**，固定使用 Rust 1.96 构建阶段与 distroless 运行阶段。Rust 采用 `--release --locked`，Python 使用 `uv sync --frozen`，前端使用 `pnpm install --frozen-lockfile`。

| Docker 选项 | 作用 |
| --- | --- |
| `-f <Dockerfile>` | 选择 Dockerfile，不改变 context |
| `-t <image:tag>` | 输出镜像名；自定义标签须同步对应 `CRASHCAP_*_IMAGE` |
| 最后一个路径（如 `.`） | 构建 context |
| `--pull` / `--no-cache` | 刷新基础镜像 / 不复用构建步骤缓存 |
| `--build-arg NAME=value` | 覆盖该 Dockerfile 声明的 ARG |
| `--platform linux/amd64` | 构建 x86_64 Linux 镜像，跨架构还需 builder/模拟支持 |

从仓库根目录单独构建：

```bash
docker build -f platform/api/Dockerfile -t crash-cap/api:upload-v3 .
docker build -f platform/worker/Dockerfile -t crash-cap/worker:upload-v3 .
docker build -f platform/frontend/Dockerfile --build-arg VITE_API_BASE_URL=/api/v3 \
  -t crash-cap/frontend:upload-v3 .
docker build -f deploy/core/Dockerfile -t crash-cap/dmp-core:upload-v3 .
docker build -f deploy/s3-gateway/Dockerfile -t crash-cap/s3-gateway:phase1 deploy/s3-gateway
```

API、Worker、前端、Core、ops-exporter 的 context 为仓库根目录。Core 不属于 Compose 常驻服务，手工重建后需更新 `CRASHCAP_CORE_IMAGE_DIGEST` 为 `docker image inspect --format '{{.Id}}' <镜像>` 的结果并重新创建相关容器；完整部署脚本会自动完成。

</details>

## 运行环境变量

部署脚本在状态目录保存两类配置：

- **`compose.env`**：镜像、端口、卷、网络、secret 路径和前端构建参数。`--compose` 自动读取，当前 shell 的同名变量优先。
- **`runtime.env`**（或 `PHASE1_RUNTIME_ENV_FILE`）：数据库、Redis、S3 凭据及 API/Worker 选项。首次生成后复用；更改 CORS 等选项直接编辑此文件。

Compose `environment` 中的显式值优先于 runtime 文件；写死的选项需 override。宿主 Python 不自动读取 `.env`，使用 `export` 或 `uv run --env-file`。列表/对象使用 JSON，布尔值用 `true/false`。配置修改及应用步骤见[部署手册](docs/operations/phase1-deployment.md#配置与修改)。

<details>
<summary>Compose 全部 48 个可插值变量及默认值</summary>

以下是 `deploy/compose/phase1.yml` 的全部 48 个可插值变量。表内为 YAML 默认值；部署脚本会生成凭据路径、计算 socket GID 和 Core 镜像 ID，并保存本次配置。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `crash-cap-phase1` | Compose 项目及监控过滤范围 |
| `PHASE1_RUNTIME_ENV_FILE` | 必填 | 外部服务运行环境文件 |
| `PHASE1_POSTGRES_PASSWORD_FILE` | 必填 | PostgreSQL 密码文件 |
| `PHASE1_REDIS_PASSWORD_FILE` | 必填 | Redis 密码文件 |
| `PHASE1_RUSTFS_ACCESS_KEY_FILE` | 必填 | RustFS access key 文件 |
| `PHASE1_RUSTFS_SECRET_KEY_FILE` | 必填 | RustFS secret key 文件 |
| `PHASE1_RUSTFS_SSE_MASTER_KEY_FILE` | 必填 | base64 编码的 32 字节 SSE-S3 主密钥文件 |
| `POSTGRES_DB` / `POSTGRES_USER` | 均为 `crashcap` | 初始化库名/用户；同时修改连接串 |
| `CRASHCAP_API_IMAGE` | `crash-cap/api:upload-v3` | API、迁移、Symbol Source 镜像 |
| `CRASHCAP_WORKER_IMAGE` | `crash-cap/worker:upload-v3` | Worker、Relay、规划、初始化与清理镜像 |
| `CRASHCAP_FRONTEND_IMAGE` | `crash-cap/frontend:upload-v3` | 前端镜像 |
| `CRASHCAP_CORE_IMAGE` | `crash-cap/dmp-core:upload-v3` | 每次任务启动的 Core 镜像 |
| `CRASHCAP_CORE_IMAGE_DIGEST` | YAML 中的历史 SHA256 | 部署脚本自动保存本次构建的本地 image ID；手工构建须同步 |
| `DOCKER_SOCKET_PATH` / `DOCKER_GID` | `/var/run/docker.sock` / `0` | socket 宿主路径/组；脚本自动探测实际路径及 GID |
| `CRASHCAP_EXTERNAL_BIND_HOST` | `127.0.0.1` | 发布端口的绑定地址 |
| `CRASHCAP_TRUSTED_INTRANET_ACKNOWLEDGED` | `false` | 明确确认内部 DNS 边界，不替代网络限制 |
| `PHASE1_API_PORT` / `PHASE1_WEB_PORT` | `8080` / `30080` | 宿主 API / Web 端口 |
| `PHASE1_S3_GATEWAY_PORT` / `PHASE1_METRICS_PORT` | `59000` / `9108` | 宿主 S3 / metrics 端口 |
| `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` | `http://127.0.0.1:59000` | 客户端可达的签名地址，当前要求 HTTP |
| `CRASHCAP_S3_REGION` / `CRASHCAP_S3_BUCKET` | `us-east-1` / `crashcap-private` | 对象存储 region / bucket |
| `S3_CORS_ALLOWED_ORIGINS` | `http://127.0.0.1:30080` | 逗号分隔的准确 HTTP origin；修改后重跑 storage-init |
| `CRASHCAP_PRESIGN_PUT_TTL_SECONDS` / `CRASHCAP_PRESIGN_GET_TTL_SECONDS` | `900` / `900` | 上传/下载签名有效期，单位秒 |
| `CRASHCAP_RAW_DOWNLOAD_ENABLED` | `false` | API 原始文件下载开关 |
| `VITE_API_BASE_URL` / `VITE_RAW_DOWNLOAD_ENABLED` | `/api/v3` / `false` | 通过 `frontend.build.args` 注入构建；修改后必须重建前端 |
| `CRASHCAP_RETENTION_INTERVAL_SECONDS` / `CRASHCAP_RETENTION_BATCH_SIZE` | `86400` / `1000` | 保留任务间隔/每批上限 |
| `CRASHCAP_ARTIFACT_UPLOAD_GC_MODE` | `off` | 暂存上传清理：`off`、`dry-run`、`active` |
| `CRASHCAP_ARTIFACT_UPLOAD_GC_ACCEPTED_HOURS` / `CRASHCAP_ARTIFACT_UPLOAD_GC_REJECTED_HOURS` | `24` / `168` | 已接受/拒绝上传的暂存保留小时数 |
| `CRASHCAP_ARTIFACT_UPLOAD_GC_CLAIM_SECONDS` | `300` | 清理领取租约秒数 |
| `PHASE1_POSTGRES_VOLUME` / `PHASE1_REDIS_VOLUME` | `crashcap_phase1_postgres` / `crashcap_phase1_redis` | 数据库/队列卷名 |
| `PHASE1_RUSTFS_VOLUME` / `PHASE1_SYMBOLICATOR_VOLUME` | `crashcap_phase1_rustfs` / `crashcap_phase1_symbolicator` | 对象/符号缓存卷名 |
| `PHASE1_EDGE_NETWORK` / `PHASE1_APP_NETWORK` | `crashcap_phase1_edge` / `crashcap_phase1_app` | 入口/应用网络 |
| `PHASE1_DATA_NETWORK` / `PHASE1_ANALYSIS_NETWORK` | `crashcap_phase1_data` / `crashcap_phase1_analysis` | 数据/分析网络 |
| `PHASE1_OBSERVABILITY_NETWORK` | `crashcap_phase1_observability` | 监控网络 |
| `PHASE1_SYMBOLICATOR_EGRESS_NETWORK` | `crashcap_phase1_symbolicator_egress` | Symbolicator 外部符号访问网络 |
| `CRASHCAP_CORE_NETWORK` | `crashcap_phase1_core` | 临时 Core 容器加入的隔离网络 |

只改变绑定端口不会自动改变公开 S3 URL 或 CORS；这三处要一起更新。PostgreSQL、Redis、RustFS 和 Symbol Source 默认不向宿主发布端口。

</details>

<details>
<summary>API / Worker 服务配置、分析资源和默认值</summary>

以下是开发和运行常用选项，更细的校验范围以 [Settings 源码](platform/api/crashcap_api/config.py) 为准。**这里列的是 Python 默认值，Compose 覆盖值另行标注。**

| 变量 | Python 默认值 / 选项 | 含义 |
| --- | --- | --- |
| `CRASHCAP_ENVIRONMENT` | `development`；`development/test/production` | Compose 设为 `production` |
| `CRASHCAP_DATABASE_URL` | `postgresql+psycopg://crashcap@postgres/crashcap` | 真实部署注入带正确凭据的连接串 |
| `CRASHCAP_CREATE_SCHEMA` | `false` | 测试建表；部署用 `crashcap-migrate` |
| `CRASHCAP_REDIS_URL` / `CRASHCAP_QUEUE_MODE` | `redis://redis:6379/0` / `dramatiq` | `memory` 仅用于进程内测试 |
| `CRASHCAP_OBJECT_STORE_BACKEND` | `s3`；`s3/local` | `local` 存储仅允许 test |
| `CRASHCAP_OBJECT_STORE_LOCAL_ROOT` | `.runtime/objects` | 测试对象存储根目录 |
| `CRASHCAP_S3_ENDPOINT_URL` | `http://rustfs:9000` | 服务端访问的内部 S3 地址，当前要求 HTTP |
| `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` | 未设置，回退内部地址 | 客户端地址；Compose 默认 `http://127.0.0.1:59000` |
| `CRASHCAP_S3_ACCESS_KEY` / `CRASHCAP_S3_SECRET_KEY` | 空；S3 模式必填 | 与 RustFS secret 一致 |
| `CRASHCAP_S3_BUCKET` / `CRASHCAP_S3_REGION` / `CRASHCAP_S3_SSE` | `crash-cap` / `us-east-1` / `AES256` | Compose bucket 为 `crashcap-private`；SSE 仅支持 AES256 |
| `CRASHCAP_PRESIGN_PUT_TTL_SECONDS` / `CRASHCAP_PRESIGN_GET_TTL_SECONDS` | `3600` / `300` | 有效范围 60–86400 / 30–3600；Compose 均为 900 |
| `CRASHCAP_CORS_ORIGINS` | `[]` | JSON origin 数组，与存储 CORS 分别配置 |
| `CRASHCAP_LOG_LEVEL` | `INFO` | 开发可设 `DEBUG` |
| `CRASHCAP_SCHEMA_ROOT` | 仓库 `contracts/` | Compose 为 `/opt/crashcap/contracts` |
| `CRASHCAP_TASK_TMP_ROOT` | `.runtime/tasks` | Compose 为 `/var/lib/crashcap/tasks` |
| `PORT` | API `8000`；Symbol Source `8081` | 对应进程端口；`crashcap-api` 默认绑定 `0.0.0.0` |
| `CRASHCAP_MIGRATIONS_ROOT` | 自动寻找迁移目录 | 覆盖 Alembic 目录，不是 Settings 字段 |
| `CRASHCAP_CORE_EXECUTOR` / `CRASHCAP_CORE_COMMAND` | `docker` / `dmp-core` | executor 为 `docker/local/fake`；fake 只允许 test |
| `CRASHCAP_CORE_MEMORY` / `CRASHCAP_CORE_CPUS` | `4g` / `2` | 临时 Core 容器资源，不等于 Worker 容器限制 |
| `CRASHCAP_CORE_PIDS_LIMIT` / `CRASHCAP_CORE_TMPFS_SIZE` | `256` / `512m` | Core 进程数与 tmpfs 限制 |
| `CRASHCAP_CORE_TIMEOUT_SECONDS` | `600` | Core 执行超时；不同队列 Compose 值见下表 |
| `CRASHCAP_CORE_STAGE_TIMEOUT_SECONDS` / `CRASHCAP_CORE_STAGE_MAX_TIMEOUT_SECONDS` | `600` / `1800` | 文件准备阶段最小/最大超时预算 |
| `CRASHCAP_CORE_STAGE_MIN_THROUGHPUT_MIB_S` | `2` | 按文件大小估算准备时间的吞吐率 |
| `CRASHCAP_FROZEN_SYMBOLICATOR_URL` | `http://symbolicator:3021` | 冻结分析使用的直接 Symbolicator 地址 |
| `CRASHCAP_FROZEN_PAIR_SOURCE_ROOT` | `http://symbol-source:8081/v3/pairs` | 已选定配对文件的内容寻址来源 |
| `CRASHCAP_FROZEN_SYMBOLICATOR_IMAGE_DIGEST` | 源码中的固定 SHA256 | 与实际 Symbolicator 镜像一致 |
| `CRASHCAP_FROZEN_PUBLIC_SOURCES` | Microsoft SymStore 来源数组 | JSON 数组，最多 16 个，遵循受管来源格式 |
| `CRASHCAP_FROZEN_ALLOW_LOCAL_CORE_SENTINEL` | `false` | 非生产且 executor=local 时可允许全零 Core 摘要进行本机测试 |
| `CRASHCAP_SYMBOLICATOR_URL` | `http://symbolicator-gateway:3021` | 遗留默认；当前 Compose 显式使用 `http://symbolicator:3021` |
| `CRASHCAP_SYMBOLICATOR_VERSION` / `CRASHCAP_SYMBOLICATOR_TIMEOUT_SECONDS` | `26.7.2` / `30` | 引擎版本与请求超时 |
| `CRASHCAP_SYMBOLICATOR_CACHE_ROOT` | `/var/lib/crashcap/symbolicator-cache` | 符号缓存位置 |
| `CRASHCAP_NORMALIZATION_VERSION` / `CRASHCAP_GROUPING_VERSION` / `CRASHCAP_EXACT_ALGORITHM` | `norm-v1.0` / `group-v1.1` / `exact-v1.0` | 规范化、分组与精确算法版本标识，需与实现配套 |
| `CRASHCAP_TASK_LEASE_SECONDS` | `1500` | 任务租约，应覆盖实际处理时间 |
| `CRASHCAP_RELAY_LEASE_SECONDS` / `CRASHCAP_RELAY_POLL_SECONDS` | `30` / `0.5` | Relay 领取租约/空闲轮询间隔 |
| `CRASHCAP_RELAY_BACKOFF_BASE_SECONDS` / `CRASHCAP_RELAY_BACKOFF_MAX_SECONDS` | `1` / `300` | 投递失败退避 |
| `CRASHCAP_ANALYSIS_MAX_ATTEMPTS` | `3` | 分析最大尝试次数 |
| `CRASHCAP_ANALYSIS_RETRY_BASE_SECONDS` / `CRASHCAP_ANALYSIS_RETRY_MAX_SECONDS` | `30` / `300` | 分析重试退避 |
| `CRASHCAP_CATALOG_SOURCE_MAX_LOCATIONS` / `CRASHCAP_CATALOG_SOURCE_MAX_CONCURRENT` | `32` / `2` | 来源位置数/并发读取限制 |
| `CRASHCAP_AUTOMATIC_ANALYSIS_PAUSED` | `false` | 暂停自动规划，保留恢复处理 |
| `CRASHCAP_AUTOMATIC_ANALYSIS_WORKSPACE_LIMIT` / `CRASHCAP_AUTOMATIC_ANALYSIS_GLOBAL_LIMIT` | `1` / `2` | 每空间/全局自动分析限制 |
| `CRASHCAP_AUTOMATIC_ANALYSIS_CAPACITY` | `2` | 自动分析容量 |
| `CRASHCAP_AUTOMATIC_ANALYSIS_ENUMERATION_LIMIT` / `CRASHCAP_AUTOMATIC_ANALYSIS_RELEASE_LIMIT` | `200` / `50` | 每轮枚举/释放上限 |
| `CRASHCAP_AUTOMATIC_ANALYSIS_PLANNING_LEASE_SECONDS` / `CRASHCAP_AUTOMATIC_ANALYSIS_DELIVERY_TIMEOUT_SECONDS` | `1800` / `1800` | 规划租约/交付超时 |
| `CRASHCAP_WORKER_QUEUES` | `verify,ingest,dump-small,dump-large` | 逗号分隔，只接受这四种队列 |
| `CRASHCAP_WORKER_PROCESSES` / `CRASHCAP_WORKER_THREADS` | `1` / `1` | Worker 进程/线程数，至少为 1 |
| `CRASHCAP_RELAY_OWNER_ID` / `CRASHCAP_AUTOMATIC_ANALYSIS_OWNER_ID` | 自动生成 | 覆盖后台实例标识，多个进程应各自唯一 |
| `CRASHCAP_RETENTION_METRICS_BIND` / `CRASHCAP_RETENTION_METRICS_PORT` | `127.0.0.1` / `9109` | 保留服务指标监听；Compose bind 为 `0.0.0.0` |

`task_handoff_mode=outbox`、`task_receipt_mode=strict`、`canonical_assembly_mode=core-final`、`symbol_projection_mode=projection-read` 及 frozen/catalog/review 等功能已是固定代码配置（`ClassVar`），不是可切换的兼容环境变量。不要添加旧 Build 发布或关闭冻结分析的开关。

Compose 按队列隔离资源。调整这些值需要 override 对应服务的 `environment`；Worker 容器本身的 `mem_limit/cpus` 也需按实际负载同步调整：

| 服务 | 队列 | 进程 × 线程 | Core 内存 / CPU / 超时 |
| --- | --- | --- | --- |
| `worker-verify` | `verify` | 1 × 2 | 2g / 1 / 900 秒 |
| `worker-ingest` | `ingest` | 1 × 1 | 4g / 1 / 900 秒 |
| `worker` | `dump-small` | 1 × 1 | 4g / 2 / 600 秒 |
| `worker-dump-large` | `dump-large` | 1 × 1 | 8g / 2 / 1200 秒 |

</details>

进一步阅读：[当前设计](docs/design.md)、[领域术语](CONTEXT.md)、[上传集成](docs/integration/crashcap.md)、[v3 验收与回退](docs/upload-v3-guide.md)、[ADR-0022](docs/adr/0022-upload-files-with-scoped-symbol-availability.md)、[HTTP OpenAPI](platform/frontend/openapi.json)。
