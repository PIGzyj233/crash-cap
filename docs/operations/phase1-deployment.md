# Crash-Cap 内网部署

本手册适用于 `deploy/compose/phase1.yml` 的上传 v3 服务。**新部署使用空库；旧 Build 数据库不能直接升级。** API、Worker、Core、前端和 CLI 必须使用配套版本。上传规则见[使用指南](../upload-v3-guide.md)，本地源码调试见[开发指南](local-development.md)。

## Linux 构建与启动

需要 Linux x86_64、Docker Engine、Compose v2 或更新版本、Bash、curl、OpenSSL，以及 `acl` 包中的 getfacl/setfacl；脚本还使用常见的 realpath/stat 工具。Docker 必须运行 Linux 容器，部署账户须能访问本机 Unix Docker socket。

从仓库根目录执行：

```bash
bash ./scripts/phase1/deploy_linux.sh
```

入口自动生成仓库外凭据、处理 RustFS secret 读取权限、构建 Core 和应用镜像、记录真实 Core 镜像 ID、执行部署检查、初始化存储与数据库，再启动并等待服务就绪。不需要手写密码文件或 Compose 包装函数。

| 入口 | 默认地址 |
| --- | --- |
| 浏览器 | `http://127.0.0.1:30080` |
| API / Swagger | `http://127.0.0.1:8080/docs` |
| S3 Gateway | `http://127.0.0.1:59000` |
| Metrics | `http://127.0.0.1:9108/metrics` |

重复运行同一部署命令会复用凭据和运行配置、构建当前源码并更新服务，不删除数据卷。此行为用于同一 v3 实例更新，不会把旧 Build 数据转换成 v3。

## 常用管理命令

`--compose` 使用状态目录中的 `compose.env` 执行 Compose 命令，不重新生成凭据、不运行完整构建和部署检查。首次先执行一次部署命令以保存配置。

```bash
bash ./scripts/phase1/deploy_linux.sh --compose ps --all
bash ./scripts/phase1/deploy_linux.sh --compose logs --tail=100 migrate storage-init cache-init
bash ./scripts/phase1/deploy_linux.sh --compose logs -f --tail=100 api relay automatic-analysis worker-verify worker
bash ./scripts/phase1/deploy_linux.sh --compose stop
bash ./scripts/phase1/deploy_linux.sh --compose up -d

# 只重建并更新前端
bash ./scripts/phase1/deploy_linux.sh --compose build frontend
bash ./scripts/phase1/deploy_linux.sh --compose up -d frontend
```

`migrate`、`storage-init`、`cache-init` 是一次性服务，退出码 0 为正常完成；其余服务应运行，有 healthcheck 的服务应 healthy。Core 按任务临时启动，不会作为常驻服务出现在列表中。

## 配置与修改

默认状态目录为 `${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap`，位于仓库外。设置自定义目录后，后续部署及 `--compose` 命令都使用相同设置：

```bash
export CRASHCAP_DEPLOY_STATE_DIR=/secure/path/crash-cap
bash ./scripts/phase1/deploy_linux.sh
bash ./scripts/phase1/deploy_linux.sh --compose ps --all
```

| 文件 / 配置 | 用途 |
| --- | --- |
| `compose.env` | 持久化 Compose 插值，包括项目、镜像、端口、卷、网络、secret 路径与 Vite 构建变量 |
| `runtime.env` | API/Worker 运行选项以及数据库、Redis、S3 凭据；首次生成后不覆盖 |
| `postgres_password`、`redis_password` | 数据库和队列密码 |
| `rustfs_access_key`、`rustfs_secret_key` | 存储凭据 |
| `rustfs_sse_s3_master_key` | base64 编码的 32 字节 SSE-S3 主密钥，必须随对象备份保留 |

运行文件可由 `PHASE1_RUNTIME_ENV_FILE` 指向其他外部文件。不要把凭据、带密码的 URL 或配置副本提交到 Git。不要重新生成密钥指向已有数据卷。

更改配置时区分三种情况：

- **服务选项**：编辑 `runtime.env`；例如 `CRASHCAP_CORS_ORIGINS=["http://127.0.0.1:5173"]`。Compose `environment` 的显式值优先，写死的选项需要 override。
- **Compose 插值**：编辑 `compose.env`，或在命令前设置同名变量；当前 shell 优先。更改端口后同步公开 S3 URL 和 origin。
- **前端选项**：`VITE_API_BASE_URL` 与 `VITE_RAW_DOWNLOAD_ENABLED` 由 Compose 传入 build args，改动后必须重建前端。仅重启 Nginx 不会修改已生成的 JS。

```bash
# runtime.env 里的 API 设置变更后
bash ./scripts/phase1/deploy_linux.sh --compose up -d --force-recreate api
# 同时影响其他 Python 服务时，重新创建这些服务
bash ./scripts/phase1/deploy_linux.sh --compose up -d --force-recreate \
  api relay automatic-analysis worker worker-verify worker-ingest worker-dump-large symbol-source retention
# 修改 compose.env 中 S3_CORS_ALLOWED_ORIGINS 后更新桶设置
bash ./scripts/phase1/deploy_linux.sh --compose run --rm storage-init
```

单纯 `restart` 不会重新加载 Compose 环境。首次生成 runtime 文件时可以从 shell 提供 `CRASHCAP_CORS_ORIGINS`；已有文件须直接编辑，重复部署不会替你覆盖此项。前端热更新的完整 CORS 步骤见[开发指南](local-development.md#前端热更新与-cors)。

全部 Docker ARG、Compose 变量与服务默认值见 [README 参数参考](../../README.md#构建参数)。脚本常用构建控制如下：

```bash
# 保留缓存，不主动刷新已有镜像
CRASHCAP_BUILD_PULL=0 CRASHCAP_PULL_EXTERNAL_IMAGES=0 bash ./scripts/phase1/deploy_linux.sh
# Core 与应用镜像均不用构建缓存
CRASHCAP_BUILD_NO_CACHE=1 bash ./scripts/phase1/deploy_linux.sh
# 初次启动较慢时延长就绪等待，单位秒
CRASHCAP_START_TIMEOUT_SECONDS=600 bash ./scripts/phase1/deploy_linux.sh
```

跳过主动拉取不等于离线构建：本机仍需已有所需镜像，构建中依赖安装也可能访问网络。`--compose build` 直接接受 Docker Compose 自身选项，如 `--no-cache`、`--pull`、`--build-arg`；它不使用完整部署入口的 `CRASHCAP_BUILD_*` 控制。

### 自管凭据

若由运维管理凭据，可以提供以下仓库外文件，文件须事先存在：

```text
PHASE1_RUNTIME_ENV_FILE
PHASE1_POSTGRES_PASSWORD_FILE
PHASE1_REDIS_PASSWORD_FILE
PHASE1_RUSTFS_ACCESS_KEY_FILE
PHASE1_RUSTFS_SECRET_KEY_FILE
PHASE1_RUSTFS_SSE_MASTER_KEY_FILE
```

运行文件至少包含 `CRASHCAP_DATABASE_URL`、`CRASHCAP_REDIS_URL`、`CRASHCAP_S3_ACCESS_KEY` 和 `CRASHCAP_S3_SECRET_KEY`；连接串需与数据库/队列凭据一致。自定义数据库用户或库名时同步 `POSTGRES_USER`、`POSTGRES_DB` 与数据库 URL。

宿主凭据通常保持部署账户所有、权限 0600。Linux Compose 文件型 secret 保留宿主权限，脚本为 RustFS 和 storage-init 所用 UID 10001 添加必要读取 ACL，并在启动前验证。不要将 secret 改成全局可读，也不要在脚本添加 ACL 后统一执行 `chmod 600`，这会取消该 UID 的有效读取权限。

## 网络与浏览器直传

本产品按 [ADR-0003](../adr/0003-run-anonymously-on-a-trusted-intranet.md) 和 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md) 在可信内网匿名运行。默认绑定 loopback。内网访问时用实际私网 IPv4，例如：

```bash
CRASHCAP_EXTERNAL_BIND_HOST=10.20.30.40 bash ./scripts/phase1/deploy_linux.sh
```

同时检查已保存的公开 URL 与 CORS 配置：浏览器/CLI 通过 `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 访问 S3 Gateway，服务端通过内部 RustFS 地址读写；`S3_CORS_ALLOWED_ORIGINS` 是逗号分隔的准确 HTTP origin，API 的 `CRASHCAP_CORS_ORIGINS` 为 JSON 数组。浏览器无法访问容器内部主机名，远程浏览器也不能用部署机器的 loopback URL。

PostgreSQL、Redis、RustFS 和内部 Symbol Source 默认不发布宿主端口。Worker 在隔离的 Core 网络启动一次性分析容器，Core 不加入数据库网络。实际 Core 镜像 ID 由部署脚本同步；手工重建 Core 后必须更新 `CRASHCAP_CORE_IMAGE_DIGEST` 并重新创建使用该配置的服务。

### 并行部署独立实例

默认项目为 `crash-cap-phase1`，可用 `COMPOSE_PROJECT_NAME` 覆盖。**只改项目名不足以隔离数据**：Compose 显式命名了卷和网络。并行实例需新的状态目录、项目、四个卷、七个网络及可用端口。例如从仓库根目录、没有旧数据的新实例开始：

```bash
export CRASHCAP_DEPLOY_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap-v3-dev"
export COMPOSE_PROJECT_NAME=crash-cap-v3-dev
export PHASE1_POSTGRES_VOLUME=crashcap_v3_dev_postgres
export PHASE1_REDIS_VOLUME=crashcap_v3_dev_redis
export PHASE1_RUSTFS_VOLUME=crashcap_v3_dev_rustfs
export PHASE1_SYMBOLICATOR_VOLUME=crashcap_v3_dev_symbolicator
export PHASE1_EDGE_NETWORK=crashcap_v3_dev_edge
export PHASE1_APP_NETWORK=crashcap_v3_dev_app
export PHASE1_DATA_NETWORK=crashcap_v3_dev_data
export PHASE1_ANALYSIS_NETWORK=crashcap_v3_dev_analysis
export PHASE1_OBSERVABILITY_NETWORK=crashcap_v3_dev_observability
export PHASE1_SYMBOLICATOR_EGRESS_NETWORK=crashcap_v3_dev_symbolicator_egress
export CRASHCAP_CORE_NETWORK=crashcap_v3_dev_core
export PHASE1_API_PORT=18080 PHASE1_WEB_PORT=30081
export PHASE1_S3_GATEWAY_PORT=59001 PHASE1_METRICS_PORT=19108
export CRASHCAP_S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:59001
export S3_CORS_ALLOWED_ORIGINS=http://127.0.0.1:30081
bash ./scripts/phase1/deploy_linux.sh
```

端口和资源名必须未被其他实例占用；更新不同版本的并行实例时，还应为 `CRASHCAP_API_IMAGE`、`CRASHCAP_WORKER_IMAGE`、`CRASHCAP_FRONTEND_IMAGE` 和 `CRASHCAP_CORE_IMAGE` 设置各自标签。参数会保存到该实例的 `compose.env`；后续管理继续选择它的状态目录。

## 检查与回退

部署完成后先检查服务、日志和接口，再实际上传 PE/PDB/DMP：

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/v3/capabilities
bash ./scripts/phase1/deploy_linux.sh --compose ps --all
```

就绪接口成功不等于真实解析和分析通过。按照[可复现上传检查](../../scripts/upload_v3/README.md)验证浏览器文件选择、S3 传输、验收状态、符号可用性与报告。日志、截图和验收结果放在忽略的 `target/` 或外部变更系统中。

重置前明确列出项目、卷、网络及占用者，备份数据库、对象/符号卷、运行配置、SSE 密钥和旧镜像。停止实例使用 `--compose stop`；不要用 `down -v` 清理需保留的数据。回退恢复整套旧版本及对应备份，不对 v3 数据库执行 downgrade。操作细节见[恢复与容量说明](phase1-recovery-and-capacity.md)；本机检查不证明其他目标环境已通过。
