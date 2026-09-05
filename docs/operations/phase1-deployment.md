# Crash-Cap 内网部署

本手册适用于 `deploy/compose/phase1.yml` 的上传 v3 服务。API、Worker、Core、前端和数据库必须使用同一版本；新基线只接受空库。旧 Build 数据不能直接升级或反向迁移。空间与上传规则见 [上传指南](../upload-v3-guide.md)。

## Linux 启动

需要 Linux x86_64、Docker Engine/Compose v2、curl、OpenSSL，以及 `acl` 包的 getfacl/setfacl。启动入口会生成外部凭据、构建镜像、初始化存储和数据库，然后启动服务：

```bash
CRASHCAP_CORE_IMAGE=crash-cap/dmp-core:upload-v3 \
CRASHCAP_EXTERNAL_BIND_HOST=127.0.0.1 \
bash ./scripts/phase1/deploy_linux.sh
```

该脚本使用 `crash-cap-phase1` 项目名，默认端口为 API 8080、前端 30080、S3 Gateway 59000、metrics 9108。它不会删除数据卷。已有旧版项目时，必须先核对资源与备份，再为 v3 准备新空库及对象存储；并行部署使用显式 Compose 项目名、独立卷/网络与端口覆写，不能仅改项目名却复用显式命名的旧卷。

`deploy_linux.sh --help` 列出端口、部署状态目录和构建参数。默认状态目录为 `${XDG_STATE_HOME:-$HOME/.local/state}/crash-cap`，位于仓库之外。自管凭据需提供以下文件：

```text
PHASE1_RUNTIME_ENV_FILE
PHASE1_POSTGRES_PASSWORD_FILE
PHASE1_REDIS_PASSWORD_FILE
PHASE1_RUSTFS_ACCESS_KEY_FILE
PHASE1_RUSTFS_SECRET_KEY_FILE
PHASE1_RUSTFS_SSE_MASTER_KEY_FILE
```

运行环境文件包含 `CRASHCAP_DATABASE_URL`、`CRASHCAP_REDIS_URL`、`CRASHCAP_S3_ACCESS_KEY` 和 `CRASHCAP_S3_SECRET_KEY`。不要把凭据、带密码的 URL 或配置副本提交到 Git。RustFS SSE 主密钥必须是 base64 编码的 32 字节随机值，并与对象备份一起保管。

宿主凭据通常保持部署账户所有、权限 0600。Linux Compose 文件型 secret 不能靠容器配置变更宿主权限；启动脚本只为 RustFS UID 10001 添加所需文件的读取 ACL，并检查实际服务能读取对应 secret，禁止用全局可读权限绕过。

## 网络与浏览器直传

本产品按 [ADR-0003](../adr/0003-run-anonymously-on-a-trusted-intranet.md) 和 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md) 在可信内网匿名运行。发布端口绑定 loopback 或批准的私网地址，通过主机防火墙限制来源。PostgreSQL、Redis、RustFS 和内部 Symbol Source 不直接向用户发布端口。

浏览器使用 `CRASHCAP_S3_PUBLIC_ENDPOINT_URL` 指向的 S3 Gateway；服务端使用内部 RustFS。`S3_CORS_ALLOWED_ORIGINS` 必须与前端 origin 精确匹配。更换端口、域名或恢复到新存储后，需要重跑 `storage-init`，不能假设对象备份包含 Bucket CORS。

Worker 在隔离的 Core 网络启动一次性分析容器。实际镜像 ID 通过 `CRASHCAP_CORE_IMAGE_DIGEST` 绑定；自管 Compose 部署也必须同步该值。Core 不加入数据库网络。Symbolicator 只接收系统生成的已冻结来源；候选、文件物化和缓存不能引入其他 Workspace 的私有内容。不要配置旧 Workspace 文件目录、Build 源顺序或兼容开关。

## 检查与回退

启动后检查 Compose 服务状态、`/healthz`、`/api/v3/capabilities`、存储初始化和 Worker 日志，再运行 [可复现上传检查](../../scripts/upload_v3/README.md)。浏览器必须实际完成文件选择、S3 传输和验收状态展示。每次日志、截图和验收结果放在忽略的 `target/` 或外部变更系统中。

重置前明确列出 Crash-Cap 项目、卷、网络及占用者，备份数据库、对象/符号卷、运行配置和 SSE 密钥，保留旧镜像。不要执行跨项目清理。回退恢复整套旧版本及对应备份，不对 v3 数据库执行 downgrade。备份恢复操作见 [恢复与容量说明](phase1-recovery-and-capacity.md)；本机检查不证明其他目标环境已通过。
