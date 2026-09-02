# Crash-Cap Phase 1 内网部署手册

状态：部署配置、静态门禁、本机隔离恢复演练和 100-DMP 容量门禁均已验证；每个目标部署仍必须按实际网络边界重跑 outside probe 和内部 UAT，不得把另一环境的结果直接外推。

适用 Compose：deploy/compose/phase1.yml。它是匿名可信内网 HTTP 部署：没有登录、RBAC 或用户身份，也不配置 TLS/CA。部署者必须用私网 bind、来源日志和防火墙保证端口不离开批准的可信网络；HTTPS、通配符或公网 bind 都是配置错误。决策边界见 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md)。

## 1. 组件和网络边界

| 网络 | 成员 | 规则 |
| --- | --- | --- |
| edge | API、Frontend、S3 Gateway、ops-exporter | API/Frontend、无凭证 S3 Gateway 与只读 metrics sidecar 发布端口；发布地址必须是 loopback、VPN 或明确的私有地址 |
| app（internal） | API、Worker、ops-exporter、ops-docker-proxy | 控制面、任务面与受限资源观测内部通信 |
| data（internal） | one-shot Migrate、API、Worker、Storage Init、S3 Gateway、PostgreSQL、Redis、RustFS | Migrate 只执行 Alembic 后退出；Gateway 只代理浏览器签名流量；RustFS/PostgreSQL/Redis 无宿主机端口 |
| analysis（internal） | Worker、Symbolicator、Symbolicator Gateway、内部 Symbol Source | Worker 只经 Gateway 请求符号化；HTTP source 只在此网络暴露 |
| core（internal） | Symbolicator；一次性 dmp-core 容器 | Core 只能经 Symbolicator 访问；Core 不加入 data |
| observability（internal） | RustFS、Symbolicator、OTel Collector、ops-exporter | 接收 OTLP/StatsD 并仅由只读 metrics sidecar 重新导出；Collector 不发布宿主机端口 |
| symbolicator-egress | 仅 Symbolicator | 主机防火墙还必须限制到配置的 Microsoft 符号源 |

Worker 虽然有 Docker socket，是为了按任务启动一次性 Core 容器；它本身没有加入 core。Worker 启动 Core 时必须使用 Compose 生成的固定网络名 crashcap_phase1_core（可由 CRASHCAP_CORE_NETWORK 覆盖），并至少包含：

~~~~text
docker run --rm --read-only \
  --network crashcap_phase1_core \
  --memory 512m --cpus 1 --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL --security-opt no-new-privileges \
  <pinned-dmp-core-image> inspect|analyze ...
~~~~

不要将 Core 加入 data，不能给 Core 挂 RustFS、PostgreSQL、Redis 或宿主机路径。Docker socket 是高信任运维边界；应仅让专用 Worker 身份访问，并在主机审计其 docker run 参数。

## 2. 凭证与启动

Compose 中没有凭证默认值。以下文件必须由部署系统在仓库外生成，并限制为部署账户可读：

~~~~text
PHASE1_RUNTIME_ENV_FILE
PHASE1_POSTGRES_PASSWORD_FILE
PHASE1_REDIS_PASSWORD_FILE
PHASE1_RUSTFS_ACCESS_KEY_FILE
PHASE1_RUSTFS_SECRET_KEY_FILE
PHASE1_RUSTFS_SSE_MASTER_KEY_FILE
~~~~

RustFS 使用 _FILE 变量读取访问/秘密密钥，私有 Bucket 使用 SSE-S3/AES256。`PHASE1_RUSTFS_SSE_MASTER_KEY_FILE` 必须包含一个 base64 编码的 32-byte 随机值；Compose 在 RustFS 启动前只从 secret 文件读取它，长度或编码错误会阻止服务启动。该密钥必须与对象备份一同进入受控灾备和轮换流程，丢失后既有 SSE-S3 对象不可恢复。RustFS Console 被禁用且没有端口映射。API/Worker 通过 `CRASHCAP_S3_ENDPOINT_URL=http://rustfs:9000` 访问 S3；浏览器只访问 `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 指向的无凭证 S3 Gateway。Gateway 保留签名 Host/URI、关闭请求缓冲、单请求上限 256 MiB，且日志不记录预签名 query。不配置证书、私钥、CA bundle 或 `--insecure` 绕过项。

Linux Docker Compose 对来源为宿主文件的 secret 使用 bind mount，不能应用 service 中声明的
`uid/gid/mode`。固定 RustFS 镜像和 `storage-init` 都以 UID `10001` 运行；RustFS 读取三个 RustFS
secret，`storage-init` 读取其中的 access/secret key。若宿主文件仅为部署账户所有的 `0600`，容器会
在读取 `/run/secrets/*` 时得到 `Permission denied`。
`deploy_linux.sh` 因此要求 `acl` 包提供 `getfacl/setfacl`，并在三个文件上只增加
`user:10001:r--`，同时强制 `group::---`、`other::---` 和只读 mask。部署账户仍是 owner；`ls -l`
可能显示 `-rw-r-----+`，其中 group 位是 ACL mask，不表示 owning group 可读。脚本在启动 Compose
前还会分别使用实际 RustFS 和 `storage-init` service/user 对各自 bind-mounted secret 执行只读探测，
并拒绝未复审的运行 UID 变化。不要用
`chmod 0644` 绕过此检查。PostgreSQL、Redis 和 `runtime.env` 仍保持普通 `0600` 且没有附加 ACL。

浏览器直传还要求 Bucket CORS。Compose 的一次性 `storage-init` 会在 API/Worker/Retention 启动前执行 `ops_storage_init.py --apply`；`S3_CORS_ALLOWED_ORIGINS` 必须是逗号分隔的精确 HTTP Frontend origin，本机默认 `http://127.0.0.1:30080`。禁止 HTTPS、通配符、userinfo、路径、query 和 fragment。初始化工具只允许 `GET/HEAD/PUT`、暴露 `ETag`，CORS 仅决定浏览器是否可读响应，不替代预签名鉴权或网络防火墙。恢复到新 RustFS 后必须强制重跑该初始化步骤，因为对象镜像不包含 Bucket CORS 配置。

公司公共 SDK 符号源是可选的部署资产。若目标环境有经过审核的 Unified Layout SDK 符号，先把它们放入由 `PHASE1_COMPANY_SDK_VOLUME` 指定的外部/预填充 Docker volume，再设置 `COMPANY_SDK_SYMBOL_PATH=/symbols/company-sdk`；Symbolicator 只读挂载该卷，Gateway 固定生成“当前 Workspace 私有 → 公司 SDK → Microsoft”的 source 顺序。未设置路径时公司 source 被省略，浏览器/API 请求仍不能提交任意 source URL。

Microsoft 公共源固定使用 `https://msdl.microsoft.com/download/symbols/` 与 source ID
`crash-cap:microsoft`。Gateway 消费 Workspace scope 生成私有 source ID，但不会把 scope 转发给
Symbolicator，因此 Microsoft object/SymCache 在 `phase1-symbolicator-cache` 中跨 Workspace 公共
复用。`symbolicator-cleanup` 与主服务使用同一固定镜像和缓存卷，只接入内部 observability 网络
上报指标，每小时执行一次 cleanup。成功下载的 object 与派生 SymCache 不按闲置时间自动淘汰。

固定版本 Symbolicator 的 public-negative TTL 同时覆盖确定性 missing 和 timeout/5xx 等瞬时失败，
不能直接设为永久。Gateway 因此把终态 `debug_status=missing` 按 PDB 名与 Debug ID 追加到同一 named
volume 的 `public-misses-v1.jsonl`；后续请求为 Microsoft source 生成只包含未知模块的
`path_patterns`，若所有可查身份都已确认 missing 则完全省略 Microsoft source。`fetching_failed`、
`timeout`、`malformed` 等状态不会进入该注册表，并仍按一小时 TTL 允许重试；新的 Debug ID 也始终
允许首次探测。部署镜像还包含经目标样本确认的精确 seed；当前仅预置
`nvEncodeAPI64.pdb/20fdb836a38d48478f34329f34a1fe4f1`，不得按厂商名或 DLL 模糊封禁。
Workspace 私有 source 仍排在前面且 source ID 随已验证符号 inventory 递增，因此
后来补传的私有符号不会被公共 missing 注册表挡住。禁止手工把 Microsoft PDB 复制进任一 Workspace
Build Manifest，也不要把缓存卷作为浏览器下载源。升级脚本不会删除数据卷；日常运维不得使用
`docker compose down -v` 或删除 `PHASE1_SYMBOLICATOR_VOLUME`，否则成功缓存和 missing 注册表都会
丢失。缓存改为显式运维生命周期后，必须持续观察 `crashcap_ops_symbolicator_cache_bytes` 与宿主盘
剩余空间，并只在容量维护窗口按精确卷名清理。

API 和 Worker 的 Settings 使用 pydantic-settings 的 CRASHCAP_ 前缀。PHASE1_RUNTIME_ENV_FILE 只能包含外部注入的 Settings 值，至少包括以下名称；不要在 Compose 的 environment mapping 里重复写入带密码的 URL 或 S3 key。one-shot `migrate` 复用该外部文件，但其独立入口只读取 `CRASHCAP_DATABASE_URL`，不会构造应用 Settings：

~~~~text
CRASHCAP_DATABASE_URL
CRASHCAP_REDIS_URL
CRASHCAP_S3_ACCESS_KEY
CRASHCAP_S3_SECRET_KEY
~~~~

Compose 显式配置的非秘密字段也全部使用 CRASHCAP_*，例如 CRASHCAP_S3_ENDPOINT_URL、CRASHCAP_S3_PUBLIC_ENDPOINT_URL、CRASHCAP_RAW_DOWNLOAD_ENABLED、CRASHCAP_CORE_IMAGE、CRASHCAP_CORE_IMAGE_DIGEST 和 CRASHCAP_CORE_NETWORK。Artifact Blob rollout 使用 `CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE=off|shadow|active`（默认 off）、`CRASHCAP_ARTIFACT_BLOB_COMPRESSION_MODE=off|shadow|active`（默认 off）、`CRASHCAP_ARTIFACT_UPLOAD_GC_MODE=off|dry-run|active`（默认 off）与有界 lease；API、Retention 和所有 Worker 的值必须一致。Gateway 的 `WORKSPACE_SOURCE_MODE=filesystem|http` 默认 filesystem；HTTP source 通过固定的 `http://symbol-source:8081` 提供且不发布宿主机端口。完整步骤见 [PDB 存储优化上线手册](pdb-storage-optimization-rollout.md)。Analysis 输入选择使用 `CRASHCAP_ANALYSIS_INPUT_SELECTION_MODE=legacy|shadow|active`（Compose 默认 active）；紧急回滚可先切到 legacy，shadow 会计算并记录选择结果但仍物化完整库存。Docker 工作目录复制使用 `CRASHCAP_CORE_STAGE_TIMEOUT_SECONDS`、`CRASHCAP_CORE_STAGE_MIN_THROUGHPUT_MIB_S` 和 `CRASHCAP_CORE_STAGE_MAX_TIMEOUT_SECONDS` 计算有界 deadline，与 `CRASHCAP_CORE_TIMEOUT_SECONDS` 的 Core 执行 deadline 分离。CRASHCAP_CORE_NETWORK 默认是 crashcap_phase1_core，必须与 Compose 的 internal core 网络名一致。Frontend 的构建期变量是 VITE_API_BASE_URL/VITE_USE_MOCK/VITE_RAW_DOWNLOAD_ENABLED，不使用 API_BASE_URL。

分析输入上线后应观察 `crashcap_analysis_input_artifacts{scope="inventory|selected|materialized"}`、`crashcap_analysis_input_bytes{scope="inventory|selected|materialized"}` 和 `crashcap_analysis_failures_total{phase,code}`。DMP 未提供 Build ID 是正常路径；若 `inventory` 随历史增长而 `materialized` 仍只包含 identity 候选，说明选择生效。`CORE_STAGE_TIMEOUT` 表示 Docker 输入/结果准备失败，`CORE_EXECUTION_TIMEOUT` 表示 Core 已启动但执行超时；前端都允许创建新的强制 reprocess Run，旧失败 Run 保留。

`CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 本机默认是 `http://127.0.0.1:59000`，对应 S3 Gateway，而不是 RustFS 容器名。目标部署必须把 `CRASHCAP_EXTERNAL_BIND_HOST`、该公共端点和 `S3_CORS_ALLOWED_ORIGINS` 一起替换为一致的批准私网 IP/端口。`deploy_check.py` 会拒绝 HTTPS、容器服务名、userinfo、通配符/公网入口、错误端口或与 Frontend origin 不一致的 CORS。

Windows PowerShell 启动时，将变量指向外部 env 文件或 secret manager 的文件路径；不要把真正的值写入 phase1.yml、仓库 .env、命令历史或日志。示例仅展示路径，不展示秘密内容：

~~~~powershell
$env:PHASE1_POSTGRES_PASSWORD_FILE = 'C:\secure\crash-cap\postgres_password'
$env:PHASE1_REDIS_PASSWORD_FILE = 'C:\secure\crash-cap\redis_password'
$env:PHASE1_RUSTFS_ACCESS_KEY_FILE = 'C:\secure\crash-cap\rustfs_access_key'
$env:PHASE1_RUSTFS_SECRET_KEY_FILE = 'C:\secure\crash-cap\rustfs_secret_key'
$env:PHASE1_RUSTFS_SSE_MASTER_KEY_FILE = 'C:\secure\crash-cap\rustfs_sse_s3_master_key'
$env:PHASE1_RUNTIME_ENV_FILE = 'C:\secure\crash-cap\crashcap-runtime.env'
$env:PHASE1_COMPANY_SDK_VOLUME = 'crashcap_company_sdk_approved' # 可选；预填充的 Unified Layout volume
$env:COMPANY_SDK_SYMBOL_PATH = '/symbols/company-sdk'            # 仅在配置上述可选 volume 时设置
$env:CRASHCAP_EXTERNAL_BIND_HOST = '10.20.30.40' # 本机验证用 127.0.0.1；目标部署使用批准私网 IP
$env:PHASE1_S3_GATEWAY_PORT = '59000'
$env:PHASE1_WEB_PORT = '30080'
$env:CRASHCAP_S3_PUBLIC_ENDPOINT_URL = 'http://10.20.30.40:59000'
$env:S3_CORS_ALLOWED_ORIGINS = 'http://10.20.30.40:30080'
~~~~

Linux 单机部署可直接使用仓库提供的一键入口。宿主机还必须安装 Docker Compose v2、`curl`、
`openssl` 和 POSIX ACL 工具；Ubuntu/Debian 可运行 `sudo apt-get install -y acl`。首次运行会在仓库外的
`${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap` 生成初始 mode-0600 secret 和 runtime env，随后仅给
三个 RustFS secret 增加 UID `10001` 的只读 ACL；其余文件继续保持普通 `0600`，脚本接着会
构建当前 checkout 的 Core/应用镜像、注入实际 Core OCI image ID、运行静态部署门禁、
启动 Compose，并等待初始化任务、容器 healthcheck 与 HTTP endpoint 就绪：

~~~~bash
bash ./scripts/phase1/deploy_linux.sh
~~~~

默认只绑定 `127.0.0.1`。需要提供给批准内网时，必须显式传入本机实际拥有的私网 IPv4；
脚本会据此同步生成浏览器 S3 endpoint 和精确 Frontend CORS origin，并由
`deploy_check.py` 拒绝通配符或公网地址：

~~~~bash
CRASHCAP_EXTERNAL_BIND_HOST=10.20.30.40 \
  bash ./scripts/phase1/deploy_linux.sh
~~~~

可用 `CRASHCAP_DEPLOY_STATE_DIR=/secure/path` 更改秘密目录，也可继续使用上文的
`PHASE1_*_FILE` 指向运维系统管理的已有文件。显式文件必须位于仓库外；除上述三个 RustFS
文件允许脚本管理的 UID `10001` 只读 ACL 外，不能授予 group/other 或其他 named-user 权限。
脚本可以重复运行用于升级，但绝不自动删除或重建数据卷；若发现已有
PostgreSQL、Redis 或 RustFS 卷而对应默认密钥缺失，它会拒绝生成新密钥，以免现有数据
不可访问。完整变量列表运行 `bash ./scripts/phase1/deploy_linux.sh --help` 查看。

先执行静态门禁。它只解析 YAML，不启动容器，也不打印解析后的环境值：

~~~~powershell
python scripts/phase1/deploy_check.py --json --runtime-env-file C:\secure\crash-cap\crashcap-runtime.env
~~~~

本次落盘验证结果：PASS，覆盖服务集合、network membership、internal 网络、RustFS/Symbolicator/OTel 固定 digest、无数据服务端口、metrics loopback bind、可信 API/Frontend/S3 Gateway bind、Gateway Host/URI 透传与最小化日志、精确 CORS、HTTP-only S3、短 TTL、默认关闭原始下载、CRASHCAP_* 命名、CRASHCAP_CORE_NETWORK 对齐和 Core 拒绝数据服务。脚本明确注明这是 static only；未提供 runtime env 文件时只会警告而不读取秘密。

仓库已提供 platform/api/Dockerfile、platform/worker/Dockerfile、platform/frontend/Dockerfile 和对应入口。API 镜像启动时不再隐式执行 DDL；Compose 先运行 `crashcap-migrate` one-shot job，只有其成功退出后才允许 API、全部 Worker 与 Retention 启动。使用不输出解析后秘密的 Compose 命令校验、构建和启动：

~~~~powershell
docker compose -f deploy/compose/phase1.yml config --quiet
docker compose -f deploy/compose/phase1.yml build --pull
docker compose -f deploy/compose/phase1.yml up -d --wait
docker compose -f deploy/compose/phase1.yml ps
~~~~

升级场景中若 API 容器被重建而既有 Frontend 容器未重建，Frontend Nginx 可能仍持有旧的 API 容器地址。`up --wait` 后必须再次请求 Frontend `/healthz`；若返回 502，执行 `docker compose -f deploy/compose/phase1.yml restart frontend`，再复查 API、Frontend 与 S3 Gateway 三个 health endpoint。Frontend 无状态，这一步不涉及数据卷。

`docker compose config` 若因为缺少外部 secret 文件失败，应修正部署环境；不要为通过校验而把秘密改成 YAML 明文。Retention 的 `:9109/metrics` 只接入内部 observability 网络，由 ops-exporter 汇总；目标 Prometheus 应加载 `deploy/ops-exporter/pdb-storage-alerts.yml`，不要直接发布 retention 端口。Compose 中 RustFS digest 来自 Phase 0 P0-E01 资格报告：

~~~~text
ghcr.io/rustfs/rustfs@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831
~~~~

注意：应以 Compose 和资格报告中的完整 digest 为准；替换 RustFS digest 必须重新跑完整 S3 资格测试。Symbolicator 使用 P0-B01 固定 digest，升级也需要重新记录查询/源 allowlist 证据。

## 3. RustFS 初始化与 CORS 修复

`docker compose up` 会运行一次性 `storage-init`，成功后才启动 API/Worker/Retention。该服务只接入 data 网络、只从 Compose secret 文件读取 S3 凭证，并使用 boto3 标准 S3 操作；不要使用 RustFS Console、管理 API 或请求方提供的 URL。恢复或修改 CORS 后显式重跑：

~~~~text
docker compose -f deploy/compose/phase1.yml run --rm storage-init
~~~~

脚本不会安装全桶 180 天生命周期规则，因为 Workspace 可以配置不同 retention_days；全桶规则会提前删除合法保留对象。RustFS 资格报告已证明标准 put_bucket_acl、put_bucket_encryption、预签名、Range、multipart 和生命周期接口可用；平台代码仍只依赖这些标准 S3 操作。

## 4. 可信内网检查和回滚

每次启动或变更 bind 时重新运行 deploy_check.py。以下均是阻断项：

- API/Frontend/S3 Gateway 映射到 0.0.0.0、::、通配符或公网地址；
- PostgreSQL、Redis、RustFS、Symbolicator 出现宿主机 ports；
- RAW_DOWNLOAD_ENABLED=true 却没有明确的可信内网风险确认；
- S3 endpoint 不是 HTTP、公共端点仍包含 `rustfs`、公共 host/port 与 Gateway 不一致、CORS 不含精确 Frontend origin、预签名 TTL 超过 900 秒，或凭证变成 YAML 字符串；
- Core network 被改成非 internal，或 Worker 加入 Core network。

升级前先做 PostgreSQL/RustFS 备份（见[恢复、Retention 与容量手册](phase1-recovery-and-capacity.md)），保存当前 Compose 文件和镜像 digest。变更后先在隔离工作空间做 health/read-only smoke test，再放行内网流量。回滚使用已保存的旧 Compose 和 digest，不能用 latest 代替回滚版本；数据库迁移必须有向后兼容或经过验证的回滚步骤。

目标部署完成后运行[目标内网 HTTP perimeter probe](phase1-target-perimeter-probe.md)，由目标网段外的探针机或隔离网络命名空间提供不可达证据；随后按[内部 UAT 清单](phase1-target-uat-checklist.md)由具名开发或运维执行者执行并签字。没有这两组目标环境证据时，不得关闭 `GATE-P1-15/16`。

## 5. 备份、恢复、Retention 与紧急删除

完整操作步骤统一放在[恢复、Retention 与容量手册](phase1-recovery-and-capacity.md)：

- 备份同时覆盖 PostgreSQL、RustFS 对象、Compose/digest 和不含 secret 的配置清单；
- restore 需要精确确认短语、仓库外备份目录和校验和，且不得用 `--delete` 静默删除目标对象；
- Workspace 默认 `retention_days=180`，只清理到期 raw DMP，对象删除成功后才更新 Blob 状态，Occurrence、Canonical、统计和 membership history 保留；
- 紧急删除只允许本机 CLI 针对一个精确 Workspace-scoped object key，必须先 dry-run，再提供显式确认、原因和仓库外审计日志；
- 容量门禁要求真实 100 个唯一 DMP、峰值并发 5、两档 p95 与独立 Microsoft cold-cache 证据。

本机隔离恢复的命令、对象 SHA-256、数据库抽样和清理结果见[2026-08-21 恢复演练记录](phase1-backup-restore-drill-2026-08-21.md)；真实容量结果与证据哈希见[Phase 1 门禁验证记录](phase1-gate-validation-2026-08-21.md)；主栈 S3 Gateway 与浏览器直传证据见 [PILOT-01 主栈验收记录](pilot-01-mainstack-browser-uat-2026-08-21.md)。这些本机证据不替代生产数据、跨主机 RPO/RTO 或目标硬件容量规划。

## 6. 日志脱敏

API、Worker、Symbolicator 和运维工具不得记录：内存字节、源码正文、完整预签名 URL、Bearer/云凭证、私钥。可以记录 request ID、actor=anonymous、来源 IP、User-Agent、动作、目标 object key 和结果，但来源 IP 不是身份。部署后对导出的日志运行：

~~~~powershell
python scripts/phase1/ops_log_scan.py .\path\to\api.log .\path\to\worker.log
~~~~

扫描器只输出文件、行号和类别，不回显命中的日志内容；它不能替代二进制内存审计。
