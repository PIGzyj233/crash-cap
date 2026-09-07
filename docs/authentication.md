# 用户认证与上传归属

平台使用本地账号密码、数据库会话和独立的上传令牌。用户自行注册，登录后可以在所有 Workspace 协作；管理员额外管理账号和 CI 令牌。没有空间成员权限、邮箱验证、SSO 或 Jira 运行时依赖。

## HTTP 内网部署

前端与 `/api/v3` 必须通过同一个 HTTP 域名访问。配置 `CRASHCAP_AUTH_ORIGIN=http://crashcap.example.internal`（包含实际端口，不带路径或结尾斜杠）；这是严格的 Origin 校验值，不从请求 Host 或转发头推断。Compose 默认使用 `http://127.0.0.1:30080`，修改外部地址或端口时必须一起修改该值。Vite 开发代理使用 `http://127.0.0.1:8000` 作为 API 上游，API 的 Origin 设置为浏览器实际使用的 `http://localhost:5173`。

Cookie 为 `crashcap_session`，设置 `HttpOnly; SameSite=Lax; Path=/api`，不设置 Domain、Secure 或 HSTS。SSE 连接每次发送前重新验证凭据，不延长空闲会话；失效时通知浏览器回到登录。Cookie 写请求必须携带准确 Origin 和 `/auth/me` 或登录返回的 `X-CSRF-Token`。浏览器凭据不存 localStorage，CSRF proof 只保存在内存。登录、注册只接受同源 JSON。过期恢复保留当前账号的草稿和上传记录；主动退出或切换账号会停止旧操作并清除旧页面状态。标签页通过仅包含用户 ID 和事件类型的 BroadcastChannel 同步登录与退出，不广播凭据。上传队列按用户 ID 分区保存在 sessionStorage。

HTTP 无法防止链路窃听、凭据重放或页面篡改。本部署将内网传输视为信任前提；密码哈希、CSRF 与 Cookie 属性不能提供链路加密。参见 [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。原始文件下载仍由原有开关控制。Compose 的 API 宿主机端口固定绑定 `127.0.0.1`，外部浏览器和 CLI 均通过前端域名访问 `/api/v3`；前端拒绝 `/metrics`。运维采集从容器内部网络直接读取 API 指标，健康检查仍可用。

## 账号与凭据生命周期

- 用户名为 3～64 位 ASCII 字母、数字、`.`、`_`、`-`，以字母或数字开头。统一转为小写，不允许修改；显示名支持中文且可修改。
- 密码为 12～128 字符，Argon2id 使用 19 MiB 内存、2 次迭代、1 个并行通道；没有字符组合规则。
- 会话空闲默认 7200 秒、最长 43200 秒，分别由 `CRASHCAP_SESSION_IDLE_SECONDS` 和 `CRASHCAP_SESSION_MAX_SECONDS` 配置。
- 注册和登录共用数据库限流，按客户端 IP 与规范化用户名分别计数；默认每五分钟每个键 30 次，通过 `CRASHCAP_AUTH_RATE_LIMIT` 配置。API 默认忽略转发头。使用前端反向代理时，将 `CRASHCAP_TRUSTED_PROXY_IPS` 设置为实际代理 IP 或它所在的受控私有子网 JSON 数组；不得填写通配符或 `0.0.0.0/0`。Nginx 用连接来源重写 `X-Forwarded-For`，不透传客户端伪造的地址。
- 改密、管理员重置、禁用及角色调整撤销全部会话和平台令牌。退出只撤销当前会话。
- 重置生成一次性临时密码；第一次成功登录即消耗临时密码，所得会话只允许查看本人、设置新密码和退出。关闭会话而未完成改密时需再次联系管理员。
- 账号只禁用、不物理删除。不能禁用或降级最后一名启用的管理员，服务账号不能成为管理员。

初始化管理员（迁移后，在 API 所在环境运行）：

```sh
crashcap-ops create-admin --username admin --display-name 管理员
```

命令交互读取并确认密码，不接受明文命令行密码。注册者不会自动成为管理员。管理员页面为 `/admin/users`，个人账号页面为 `/account`。

## 上传令牌和 CI

`ci-bot`（ID `usr_ci`）是内置服务账号，没有登录密码。管理员为每条流水线创建独立上传令牌，仍统一归属 CI；审计可区分签发人和令牌 ID。普通用户在个人页面创建的令牌归属本人。

令牌仅允许初始化／完成上传、查询自己的上传记录与状态、查询 Workspace；不允许读取分析报告、人工审核、创建空间或管理账号。令牌默认有效期 90 天，可设置为 1～365 天，原文仅在签发响应中显示，数据库只存摘要。显式传入无效 Authorization 时不会回退到有效 Cookie。

```sh
# CRASHCAP_TOKEN 由 CI 密钥变量注入，不把密钥写进命令或仓库。
crashcap upload ./Release --workspace my-workspace --api-url http://crashcap.example.internal

# 个人使用时也可从文件读取；此参数优先于环境变量。
crashcap upload ./app.exe ./app.pdb --workspace my-workspace --token-file /path/to/token.txt
```

配置 `CRASHCAP_TOKEN` 或 `--token-file` 是必需的；没有共享默认密钥或匿名 CI 降级。令牌只附加到平台 API 请求；对象存储 PUT 不带平台 Authorization，不跟随重定向。轮换时先签发新令牌并更新流水线，验证后撤销旧令牌。

## 身份与审计

`Principal` 向业务层提供用户 ID、账号类型、角色、认证方式及凭据 ID。上传初始化固定用户 ID、用户名／显示名快照和令牌 ID。API 不接受上传人字段。只有上传者或管理员可以完成上传；验收、重试、配对、文件回收不改变上传归属。

`ArtifactEntry` 与 `OccurrenceSubmission` 从其 Upload 读取 `uploaded_by`。多人提交同一内容可以物理去重，但每次上传有独立归属。失败和未完成上传也保留记录；`GET /uploads` 与 `/uploads` 页面可按上传人筛选，产物列表同样支持 `uploaded_by_user_id`。

历史匿名记录回填为不可登录的 `legacy-unknown`，不会因为来源是 CLI 而推断为 CI。后台执行使用不可登录的 `system` 身份，与请求／任务 ID 关联。人工审核请求不接受 `reviewer` 或 `reviewed_by`，服务端在新证据中写入稳定用户 ID，同时在审核记录保存名称快照。历史证据字节、哈希和声明保持原样；不同操作者不能重放别人的幂等审核请求。

分组的 `owner_user_id` 指向平台用户；历史 owner 文本只作展示，不按同名用户自动绑定。上传者、审核者与负责人是不同关系，不自动赋值。

## Jira 后续契约

本版没有 Jira 表、PAT 输入页面、占位接口或同步任务。后续模块需要以下关系：

- `ExternalIdentity(user_id, instance_id, external_user_id)`：通过本人 PAT 校验得到稳定 Jira 用户标识，禁止按同名用户名或显示名自动绑定。每个实例内的外部身份不能绑定多个平台用户。
- `ExternalCredential(external_identity_id, ciphertext, key_version, expires_at, status)`：个人 Jira PAT 使用可解密的认证加密存储；密钥独立于数据库，前端只能读取绑定状态。它与仅存摘要的平台上传令牌完全分离。
- `IssueLink(problem_id, instance_id, external_issue_id, issue_key)`：稳定 Jira issue ID 为身份，issue key 和 URL 为展示。独立问题对象应能够承载后续重新归组，不能把一个分析分组永久等同于一个问题。

Jira 模块未来对平台提供“校验本人身份、读取问题、执行明确操作”的接口，内部负责 Server/Data Center 版本差异、PAT 状态和请求失败。后台同步必须记录所用凭据的归属，不能借用任意用户 PAT。认定人、负责人、修复状态变更人分别记录；Jira 状态映射和“修复已验证”的判断在集成阶段单独确定。Jira 不可用不会阻断本地登录和上传。

Server/Data Center PAT 使用 `Authorization: Bearer`，Jira Software 官方支持从 8.14 起；实际集成时核验安装版本和管理员配置。[Atlassian PAT 文档](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html)

## 上线与回滚

1. 备份数据库和对象存储，暂停新上传并排空验收任务。
2. 执行 `crashcap-migrate`，应用增量 `0002_user_auth`。迁移回填历史用户，再添加非空外键；临时停用历史审核触发器仅限迁移事务内，随后恢复。上传归属由数据库触发器保护。
3. 运行 `create-admin`，配置准确 Origin 和可信代理地址，同步发布后端、前端和新版 CLI。例如 `CRASHCAP_TRUSTED_PROXY_IPS='["172.20.0.4"]'` 中的地址必须替换为实际前端代理地址；容器重建后重新核对，或为代理配置固定地址。未配置时不会信任转发头，限流会按代理连接地址聚合。
4. 通过管理员页面签发 CI 令牌，更新流水线；验证注册、登录、上传人展示及令牌撤销后恢复流量。

旧匿名客户端不再可写。回滚必须恢复旧程序与数据备份；禁止将新的身份记录逆向压回匿名模式。

## 本地认证测试

`platform/tests/test_authentication.py` 覆盖认证与归属接口。PostgreSQL 并发测试使用 `QAI_CATALOG_DATABASE_URL` 指向独立测试数据库，并为每项测试创建、清理独立 schema。

真实文件归属测试为 `platform/tests/test_authentication_native.py`。Windows CI 使用已有 golden 样本；本地可通过 `CRASHCAP_AUTH_TEST_CORE`、`CRASHCAP_AUTH_TEST_EXE`、`CRASHCAP_AUTH_TEST_DLL`、`CRASHCAP_AUTH_TEST_PDB`、`CRASHCAP_AUTH_TEST_DMP` 指定 Core 和真实文件，再运行：

```sh
uv run --project platform pytest platform/tests/test_authentication_native.py -q
```
