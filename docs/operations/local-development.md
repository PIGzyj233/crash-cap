# 本地开发与调试

日常入口和依赖版本见 [README](../../README.md#本地开发与调试)。本文补充 CORS、Python 源码挂载、宿主 IDE 进程以及真实文件调试。命令默认从仓库根目录开始，完整服务采用 [Linux 部署脚本](phase1-deployment.md)。

## 前端热更新与 CORS

Vite 在 `http://127.0.0.1:5173` 启动，API 使用默认 `http://127.0.0.1:8080`。首次创建开发后端时：

```bash
CRASHCAP_CORS_ORIGINS='["http://127.0.0.1:5173"]' \
S3_CORS_ALLOWED_ORIGINS='http://127.0.0.1:30080,http://127.0.0.1:5173' \
bash ./scripts/phase1/deploy_linux.sh
```

已有实例复用 runtime 文件，不会因上述 shell 值自动修改已有 CORS。找到状态目录（自定义实例沿用 `CRASHCAP_DEPLOY_STATE_DIR`）：

```bash
export CRASHCAP_DEV_STATE="${CRASHCAP_DEPLOY_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap}"
```

编辑该目录中 `compose.env` 的 `PHASE1_RUNTIME_ENV_FILE` 所指文件，添加或更新一次以下键，保留其他有效 origin：

```dotenv
CRASHCAP_CORS_ORIGINS=["http://127.0.0.1:5173"]
```

编辑 `compose.env` 中对应条目：

```dotenv
S3_CORS_ALLOWED_ORIGINS=http://127.0.0.1:30080,http://127.0.0.1:5173
```

应用已有实例的配置：

```bash
bash ./scripts/phase1/deploy_linux.sh --compose up -d --force-recreate api
bash ./scripts/phase1/deploy_linux.sh --compose run --rm storage-init
```

然后在前端目录启动 HMR：

```bash
cd platform/frontend
pnpm install --frozen-lockfile
VITE_API_BASE_URL=http://127.0.0.1:8080/api/v3 pnpm dev --host 127.0.0.1
```

也可复制 `.env.example` 为同目录 `.env.local`，再运行 `pnpm dev --host 127.0.0.1`。Vite 没有内置 API proxy；默认相对 `/api/v3` 用于 Docker Nginx 的同源代理。`VITE_USE_MOCK` 当前不被入口读取，测试中通过 `createMockApiClient()` 注入假数据。

`localhost`、`127.0.0.1` 和不同端口是不同 origin。远程开发需让 API 和 `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 均能被开发者浏览器访问，并把开发 origin 加入 API/S3 CORS。API 允许跨域不代表对象存储也允许。

`pnpm preview --host 127.0.0.1` 在 4173 预览已有 `dist/`，仍使用构建时 API 地址；跨域预览需另将 4173 加入两处 CORS。

## API / Worker 挂载当前源码

保留 Compose 数据库、队列和分析网络，将 Python 源码挂入开发容器，避免手动启动整套依赖。先完成一次部署，在仓库根目录执行：

```bash
export CRASHCAP_DEV_STATE="${CRASHCAP_DEPLOY_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap}"
cat > "$CRASHCAP_DEV_STATE/dev.yml" <<EOF_DEV
x-python-source: &python-source
  volumes:
    - "$PWD:/workspace:ro"
  environment:
    PYTHONPATH: /workspace/platform/api:/workspace/platform/worker:/workspace/platform/cli
    CRASHCAP_SCHEMA_ROOT: /workspace/contracts
    CRASHCAP_LOG_LEVEL: DEBUG
services:
  api:
    <<: *python-source
    entrypoint:
      - uvicorn
      - crashcap_api.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --reload
      - --reload-dir
      - /workspace/platform/api
      - --reload-dir
      - /workspace/platform/worker
  worker:
    <<: *python-source
  worker-verify:
    <<: *python-source
  worker-ingest:
    <<: *python-source
  worker-dump-large:
    <<: *python-source
  automatic-analysis:
    <<: *python-source
  relay:
    <<: *python-source
  symbol-source:
    <<: *python-source
EOF_DEV

bash ./scripts/phase1/deploy_linux.sh --compose -f "$CRASHCAP_DEV_STATE/dev.yml" up -d \
  api worker worker-verify worker-ingest worker-dump-large automatic-analysis relay symbol-source
bash ./scripts/phase1/deploy_linux.sh --compose -f "$CRASHCAP_DEV_STATE/dev.yml" \
  logs -f --tail=100 api worker-verify worker automatic-analysis
```

API 自动重载，其他 Python 进程修改后重启：

```bash
bash ./scripts/phase1/deploy_linux.sh --compose -f "$CRASHCAP_DEV_STATE/dev.yml" restart \
  worker worker-verify worker-ingest worker-dump-large automatic-analysis relay symbol-source
```

override 必须显式列出各服务：后置文件对 `worker` 的改动不会传播给基础文件中已解析的 `extends` 服务。容器以 UID 10001 运行，挂载的源码和目录需允许该 UID 读取；不要给它写权限。依赖变更仍需重建 API/Worker 镜像；修改迁移文件应单独更新迁移镜像并执行迁移，源码挂载不替代此步骤。

调试结束，不带 override 重新创建服务即可恢复镜像代码：

```bash
bash ./scripts/phase1/deploy_linux.sh --compose up -d --force-recreate \
  api worker worker-verify worker-ingest worker-dump-large automatic-analysis relay symbol-source
```

## 宿主 IDE 与 Python 进程

需要 IDE 直接附加本机 Python 时，先在 `platform/` 运行 `uv sync --frozen --extra dev`，另准备仓库外 `runtime.local.env`。不能直接复用容器里的 `postgres` / `redis` 主机名：

- 用开发 override 将 PostgreSQL、Redis、Symbolicator 端口发布到宿主 `127.0.0.1`；数据库与 Redis 连接串改为这些宿主地址及正确凭据。
- `CRASHCAP_ENVIRONMENT=development`；S3 内部和公开端点改为可达的 S3 Gateway，bucket、region 和凭据与部署一致。
- 本地 Core 设置 `CRASHCAP_CORE_EXECUTOR=local`、`CRASHCAP_CORE_COMMAND=/absolute/path/to/target/debug/dmp-core`，并使用可达的 `CRASHCAP_FROZEN_SYMBOLICATOR_URL`。
- `CRASHCAP_FROZEN_PAIR_SOURCE_ROOT` 是 **Symbolicator 访问**的地址。Symbol Source 保留在 Compose 时可继续用 `http://symbol-source:8081/v3/pairs`；若替换为宿主进程，要提供容器可达的宿主地址。
- API、规划器和 Worker 使用一致的数据库与分析配置。停止被替代的容器进程，避免两套实现同时消费同一队列。

每个常驻进程在单独终端运行；迁移命令完成后退出：

```bash
cd platform
uv run --env-file /absolute/path/runtime.local.env crashcap-migrate
uv run --env-file /absolute/path/runtime.local.env uvicorn crashcap_api.main:app \
  --host 127.0.0.1 --port 8000 --reload
uv run --env-file /absolute/path/runtime.local.env crashcap-worker
uv run --env-file /absolute/path/runtime.local.env crashcap-relay
uv run --env-file /absolute/path/runtime.local.env crashcap-auto-analysis
uv run --env-file /absolute/path/runtime.local.env crashcap-symbol-source
```

`Settings` 不自动读取 `.env`，必须使用 `--env-file` 或导出变量。`crashcap-api` 为无自动重载入口，读取 `PORT`（默认 8000）并绑定 `0.0.0.0`；上面显式使用 Uvicorn 的 loopback 热重载。Symbol Source 默认端口为 8081。

本地资格测试可用 `CRASHCAP_FROZEN_ALLOW_LOCAL_CORE_SENTINEL=true` 允许全零 SHA256 Core 摘要，但仅限非生产且 executor 为 local；不能把此身份当作已验证的生产镜像。`local` 对象存储只允许 test，使用 `local-object-store://` 测试协议；`fake` Core 也不是可替代真实上传和分析的开发后端。

## 断点、Core 与真实文件测试

普通检查命令见 [README](../../README.md#本地开发与调试)。针对失败测试进入 Python 调试器：

```bash
cd platform
uv run pytest tests/test_architecture_health_v3.py -x --pdb
```

前端可以使用浏览器开发者工具和 `pnpm test:watch`；修改 API 契约后，先安装 Python 平台依赖，再在 `platform/frontend` 运行 `pnpm openapi:generate` 和 `pnpm openapi:check`。

Core 可以从仓库根目录单独读取文件：

```bash
cargo run --locked -p dmp-core -- inspect --dump /path/to/crash.dmp --output -
cargo run --locked -p dmp-core -- identify --kind pe --artifact /path/to/app.exe --output -
cargo run --locked -p dmp-core -- identify --kind pdb --artifact /path/to/app.pdb --output -
cargo run --locked -p dmp-core -- analyze-frozen --help
```

`analyze-frozen` 需要系统生成的 Run、resolution manifest 和 execution 描述；旧 `analyze` 命令已移除。

真实 PE/PDB/DMP 测试需要 Windows x64、Visual Studio C++ Build Tools / Windows SDK 与 PowerShell。在 Windows 仓库根目录运行：

```powershell
./scripts/fixtures/build_golden.ps1 -Clean
./scripts/fixtures/build_p0_b01.ps1
cargo build --locked -p dmp-core
cd platform
uv run pytest tests/test_upload_v3.py tests/test_upload_v3_retention.py tests/test_upload_v3_failures.py tests/test_native_upload_cli.py -q
```

这些测试缺少生成 fixture 或本地 Core 时可能跳过，需检查测试摘要。PostgreSQL 集成测试使用 `QAI_CATALOG_DATABASE_URL` 指向专用测试库；所需基础设施与测试选择见[当前 CI](../../.github/workflows/qa-symbol-import.yml)。完整 CLI、浏览器、空间隔离和自动分析闭环见[v3 验收](../../scripts/upload_v3/README.md)。
