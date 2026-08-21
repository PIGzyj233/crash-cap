# PILOT-01 主栈浏览器直传验收记录（2026-08-21）

## 1. 结论与证据边界

`PILOT-01｜打通主栈浏览器直传` 在本机主 Compose 栈 `crash-cap-phase1` **PASS**。浏览器从 `http://127.0.0.1:30080` 创建全新 Workspace/Build，经 `http://127.0.0.1:59000` 的无凭证 S3 Gateway 直传 Manifest、PE、PDB、DMP；最终 Analysis 为 `COMPLETE`，顶帧为 `crashcap::trigger_null_read()` / `null_read_target.cpp:76`。浏览器控制台在最终流程中没有 network、CORS、warning 或 error。

本记录只证明 Windows + Docker Desktop/Linux containers 的本机 loopback 主栈。验收基于仓库 HEAD `69426d02ca12e899a958dc8f068af7c15895be12` 加本工作包的当前工作树改动；在改动提交前，不能把该 HEAD 单独当作镜像源码身份。未删除或重建现有 PostgreSQL、Redis、RustFS 卷，也没有把历史容量/UAT 栈 `crash-cap-phase1-capacity` 的直连 RustFS 结果当作本记录证据。真实内网部署必须替换 bind、公共 S3 endpoint 和 CORS origin，并重跑门禁、perimeter probe 与浏览器 UAT。

## 2. 固定配置与运行态拓扑

| 项目 | 本次值/结果 |
| --- | --- |
| Compose project | `crash-cap-phase1` |
| API | `http://127.0.0.1:58080`，`/healthz` = 200 |
| Frontend | `http://127.0.0.1:30080`，`/healthz` = 200 |
| S3 Gateway | `http://127.0.0.1:59000`，`/health/ready` = 200 |
| API 内部 S3 endpoint | `http://rustfs:9000` |
| API 公共预签名 endpoint | `http://127.0.0.1:59000`；不含 `rustfs` |
| S3 Gateway 镜像 | 最终运行容器 `sha256:e0a3feb0ad5851bfe296ca8cb2f5419c5e36a1b9252ccf7bbf30c26c2447ef0c`；base image 使用 Dockerfile 中固定 digest |
| S3 Gateway runtime | user `10001:10001`，read-only rootfs，`127.0.0.1:59000 -> 9000/tcp`，无 secret |
| Storage Init | exited 0；private ACL、SSE-S3/AES256、1 个精确 HTTP CORS origin 均应用成功 |

主栈运行态只发布以下批准端口：

| 服务 | 宿主机端口 |
| --- | --- |
| API | `127.0.0.1:58080` |
| Frontend | `127.0.0.1:30080` |
| S3 Gateway | `127.0.0.1:59000` |
| ops-exporter | `127.0.0.1:59108` |

主栈 RustFS、PostgreSQL、Redis 的 `HostConfig.PortBindings` 均为 `{}`；它们只有容器网络内的 `expose`。API、Frontend、S3 Gateway 面向客户端只使用 HTTP；Gateway 配置中没有证书、CA、HTTPS upstream 或 `--insecure`。

在保留现有卷的情况下执行 `docker compose -f deploy/compose/phase1.yml up -d --wait` 返回 0；长驻服务全部达到 running/healthy，`storage-init` 与 `symbols-init` 以 exit 0 正常结束。

## 3. 静态、构建与平台门禁

| 门禁 | 结果 |
| --- | --- |
| `deploy_check.py --runtime-env-file .runtime/phase1-compose-gate/runtime.env --json` | **PASS**；105 checks，`warnings=[]`，`errors=[]` |
| `docker compose -f deploy/compose/phase1.yml config --quiet` | **PASS** |
| S3 Gateway / Worker / Storage Init image build | **PASS** |
| Platform Pytest | **PASS**；97 passed，2 skipped；skip 仅为需要显式隔离 PostgreSQL/Redis 的既有 integration 项 |
| Ruff（Platform + 本工作包脚本） | **PASS** |
| `mypy --strict`（api/worker/cli） | **PASS**；32 source files |
| Frontend Vitest | **PASS**；10/10 |
| Frontend lint / OpenAPI check / production build | **PASS**；build 仅有既有的 Vite chunk-size 非阻断 warning |

新增负例覆盖公共 endpoint 仍为 Compose 服务名、CORS host/port 错配、RustFS 发布宿主机端口、Gateway wildcard bind，以及 Host/URI、缓冲、256 MiB、HTTP-only 和日志格式指令缺失。Storage Init 测试覆盖 private ACL、AES256、`GET/HEAD/PUT`、`ETag`、精确 origin、无 wildcard origin 及幂等重跑。

## 4. CORS、SigV4 与日志脱敏

真实 Gateway preflight 返回：

```text
HTTP/1.1 200 OK
access-control-allow-origin: http://127.0.0.1:30080
access-control-allow-methods: GET, HEAD, PUT
access-control-allow-headers: *
access-control-max-age: 300
```

使用主栈真实 S3 凭证生成预签名 PUT 后，经 Gateway 上传一个探针对象，脱敏结果为：

```json
{"allow_origin":"http://127.0.0.1:30080","contains_container_name":false,"etag_present":true,"expose_headers":"ETag","host":"127.0.0.1","port":59000,"scheme":"http","status":200}
```

Gateway UAT 日志记录了三个对象的 `OPTIONS` 和 `PUT status=200`，路径分别对应最终 PE、PDB、DMP Upload ID。日志格式严格只包含 method、`$uri`、原始 Host、status、bytes；对完整日志扫描 `X-Amz-`、`Signature=`、`Credential=`、`?` 和额外来源地址字段的结果为 `GATEWAY_LOG_MINIMIZATION=PASS`，未保存 query、完整预签名 URL 或额外客户端字段。

```text
PUT /crashcap-private/uploads/wsp_01M0HTJWBDQNA9RFVG5JPPJ3K4/upl_01M0HVYE5EX05Q4HJAHR0Q5XC7/blob host=127.0.0.1:59000 status=200 bytes=0
PUT /crashcap-private/uploads/wsp_01M0HTJWBDQNA9RFVG5JPPJ3K4/upl_01M0HVZKH1QRG89Q0DT0T7757G/blob host=127.0.0.1:59000 status=200 bytes=0
PUT /crashcap-private/uploads/wsp_01M0HTJWBDQNA9RFVG5JPPJ3K4/upl_01M0HW0CP5R3T1FCGF6W13Z9TX/blob host=127.0.0.1:59000 status=200 bytes=0
```

## 5. 全新主栈浏览器 UAT

| 对象 | ID/状态 |
| --- | --- |
| Workspace | `wsp_01M0HTJWBDQNA9RFVG5JPPJ3K4`；`pilot-01-mainstack-20260821-1731` |
| Build | `bld_01M0HTKR588KD3HDRYB3E9NRJ5`；Version `2026.08.21.pilot-01`；Build number `pilot-01-001` |
| Module | `mod_01M0HTMS6A955SMQ4J77P4YCB7`；debug ID `5295c1f4535d4f8aa0b1989805198bb815` |
| PE Upload / Artifact | `upl_01M0HVYE5EX05Q4HJAHR0Q5XC7` / `art_01M0HTN26HJH1F2Q37SZJGQCZT`；`ACCEPTED` / `verified` |
| PDB Upload / Artifact | `upl_01M0HVZKH1QRG89Q0DT0T7757G` / `art_01M0HTPVGCVF8ZDKYP0DN97MKX`；`ACCEPTED` / `verified` |
| DMP Upload / Blob | `upl_01M0HW0CP5R3T1FCGF6W13Z9TX` / `blob_01M0HTRFDZ7RHVGN6YS08MQGAX`；`ACCEPTED` / `accepted` |
| Occurrence | `occ_01M0HTRFF6C4P157F342H6WYXV` |
| Analysis Run | `run_01M0HTRFFCV6Q53HCYVQG8MJC6`；`COMPLETE`；quality `1.0`；duration `6304.448 ms` |
| Exact Group | `grp_01M0HTRPGWHA0CJNW4FE39MK1Z` |
| 报告顶帧 | `crashcap::trigger_null_read()`；`null_read_target.cpp:76` |

浏览器按 Workspace → Build → Manifest → PE → PDB → DMP → Report 顺序操作，并在最终 Frontend/Gateway 镜像上再次直传 PE、PDB、DMP。页面明确显示“浏览器经 S3 Gateway 直传”。最终 Build resolution 为 `reported`，解析到上述 Build；PE/PDB verification 为 `verified` 且 debug ID 匹配。浏览器开发日志查询 `levels=[error,warn]` 返回空数组。

关键截图：

- [Occurrence Overview](evidence/pilot-01/occurrence-overview.png)，SHA-256 `994e67c05b79f2e6dd2b69c2f2263dc2cbea2492aa8533899f1f42ecbda52f7c`；
- [Crash Stack](evidence/pilot-01/occurrence-crash-stack.png)，SHA-256 `e9e67c44347f25471c3062b5a2fea11e64d91eb96839473078dbafb8043b8358`。

## 6. PILOT-01 Gate

| 验收项 | 结果 |
| --- | --- |
| `PILOT-01-E01` 静态与构建门禁 | **PASS** |
| `PILOT-01-E02` 运行态拓扑 | **PASS** |
| `PILOT-01-E03` HTTP/CORS/SigV4 | **PASS** |
| `PILOT-01-E04` 主栈浏览器 UAT | **PASS** |
| `PILOT-01-GATE` | **PASS / CLOSED** |

实施中首次构建暴露了 Storage Init 脚本父目录权限错误；Worker Dockerfile 改为显式创建只读可遍历目录后，镜像重建与一次性初始化通过。主栈升级时 API 容器地址变化还可能使保留中的 Frontend Nginx 持有旧 upstream；部署手册已要求 API 重建后复查 Frontend health，必要时重启无状态 Frontend。两项均已在本次最终运行态复验通过，不是遗留 Gate 失败。
