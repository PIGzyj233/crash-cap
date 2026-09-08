# Crash-Cap 2.0 设计

本文件是当前设计的权威来源。2026-09-05 采用 ADR-0022：选择空间、上传文件、附带可选版本。旧 Build 发布、Manifest、完整配对、全局检索和旧 Canonical 兼容规则全部被取代。旧设计和验收记录仅说明历史，不能作为当前运行约束。

## 用户认证

采用 [ADR-0023](adr/0023-local-identities-and-upload-attribution.md) 和 [认证设计](authentication.md)：人员自助注册，登录后全员跨空间协作；CI 通过平台上传令牌映射到 ci-bot。上传记录保存稳定用户 ID 与提交时名称快照，人工操作记录真实登录身份，后台使用 system。历史匿名记录为 legacy-unknown。HTTP 同源部署，服务端会话配合 CSRF 校验；Jira 个人 PAT 本轮只预留契约。

## 用户模型

用户可以上传 EXE、DLL、PDB 和 Windows x64 用户态 DMP。目标必须是一个明确的 Workspace 或公共空间。公共空间只接收 PE/PDB。版本是可选的普通字符串，不需要登记，不参与身份匹配、文件验收或分析幂等计算。

CLI 只有 `crashcap upload` 上传入口，可接受多个文件或递归目录。`--workspace` 接受 ID 或精确名称；`--public` 选择公共空间；两者互斥且必选一个。不存在的名称报错。`--build-version` 是业务标签，`crashcap --version` 是程序版本。上传不要求 Git、配置文件、模块清单或本地配对。

浏览器 Workspace 上传页直接使用当前空间，平台入口显式选择空间，也可以就地创建 Workspace。整批一个可选版本。开始上传后固定本批目标和标签，清空列表可以开始新批次。每个文件独立验收；一个文件失败不回滚其他文件。

## Workspace 页面组织

主导航为概览、崩溃分析、符号中心。崩溃分析包含记录和精确分组，符号中心包含当前报告中的符号问题和文件库。上传是固定操作入口，CLI 文档归入接入指南；原列表和报告 URL 保留。

概览待处理计数与记录列表共用 Current/Latest 口径。`attention` 快捷筛选、`symbol_issue_id` 精确下钻和 `version_unset` 未声明版本筛选均在服务端执行。暂无样本的耗时返回 null，不用零质量等级代表缺少数据。

`GET /workspaces/{id}/symbol-issues` 及问题详情来自 Current 关系，保留稳定问题 ID、真实原因及去重影响数量；文件可用性不代表报告已更新。按问题请求重分析时，由服务端重新确定当前影响范围。

`GET /workspaces/{id}/artifacts` 及文件详情以当前 Workspace 为消费者，返回本空间和公共归属，并计算消费范围内的配对可用性。平台公共文件库使用 `/public/artifacts`。原 `/artifacts` 与 `/symbols/health`、`/symbols/missing` 接口保留兼容，浏览器不再合并后两个接口。

统一上传页携带来源空间、文件类型、符号问题和返回位置。站内导航保留上传队列，sessionStorage 只保存文件描述和上传回执，不保存文件字节或预签名 URL；刷新后通过上传 ID 恢复验收状态，未完成传输的文件需重新选择。报告首屏展示诊断与崩溃栈，提交历史、分析历史及人工复核归入历史页签。历史 Run 的证据不变。

## 持久化边界

- `CatalogFile`：经过真实解析器验证的不可变 PE/PDB 内容，以文件种类和原始 SHA-256 标识。同字节只保留一份内容。
- `CatalogFileLocation`：内容的物理位置和验收依据。物理复用不会授予新的使用范围。
- `ArtifactEntry`：一次成功上传带来的空间归属、文件名、版本和来源。同一内容可以有多个空间归属和多个标签。
- `Upload`：单文件初始化、传输声明、验收状态和结果。客户端默认等待 `ACCEPTED` 或 `REJECTED`。
- `CatalogPair`：真实 PE Debug ID 与 PDB Debug ID 相等的内容组合；pair ID 由两个内容哈希计算。文件名、版本、上传次序都不参与匹配。
- `DumpBlob`：某 Workspace 对已验收 DMP 内容的引用及保留期限。物理 DMP 字节按 SHA-256 复用，空间引用的过期互不影响。
- `Occurrence`：同 Workspace、同 DMP 内容的一次逻辑崩溃，保存当前版本标签。
- `OccurrenceSubmission`：每次成功提交及当次填写的标签。重传不会增加 Occurrence 次数。
- `OccurrenceVersionAudit`：用户显式编辑当前版本的追加审计。
- `AnalysisDemand`：可恢复、可合并的分析需求及有限重试预算。
- `AnalysisRun`：系统生成的不可变分析输入和一个执行结果。输入固定身份、符号选择、分类、引擎及实际内容引用。
- `CurrentDecision`：候选结果与当前结果的证据比较和采用决定。Current 指针、历史结果和最新尝试是三个不同概念。
- `PublicSymbolJob`：用户请求的独立 Windows PDB 缓存补齐任务。`PublicSymbolRequest` 将重复请求键绑定到同一任务。
- `CrashGroup`：继续使用 Exact Group 算法；当前版本分布查询 Occurrence 当前标签。

数据库从空库基线 `0001_upload_v3_baseline` 开始，后续增量迁移服务于已采用 v3 的部署。不提供旧 Build 数据库和旧客户端迁移/兼容路径。源码包上传和浏览源码包功能随 Build 体系删除。`MissingSymbol` 的主键只有稳定行 ID；Code ID、Debug ID 均可空，保留只有 PE 身份或没有调试身份的模块，禁止伪造 ID 或用空字符串规避约束。

## 文件验收与可用性

单文件验收核对声明长度、SHA-256、真实格式和支持架构。PE/PDB 身份由 Core 解析，拒绝损坏内容及 FASTLINK PDB。有效但没有调试身份的 PE 可以保存，状态为 `no_debug_identity`，不能宣称完整符号可用。

PE 和 PDB 可以按任意顺序分批上传。文件成功验收后即持久保存，缺少另一半是 `waiting_for_pair`，属于上传成功。可见完整组合唯一时为 `symbols_available`；同身份不同有效内容为 `identity_conflict`。同字节候选归并，不按最新上传、本地优先或文件名选择。

HTTP 单文件状态为 `INITIALIZED → UPLOADED → VERIFYING → ACCEPTED/REJECTED`。传输中断、临时存储故障和 Worker 崩溃可重试；终态文件不被后续文件失败撤销。CLI 超时、临时错误或拒收返回非零，receipt 保留已成功文件和资源链接。receipt 不含预签名 URL、Build ID 或 sealed 字段。

预签名 PUT、multipart 与重试只负责传输。CLI 与浏览器调用同一 API，业务验收只有服务端一种实现。公共批次出现 DMP 时客户端在发起任何上传前要求改选 Workspace，服务端也拒绝公共 DMP。

## 空间范围

| PE 归属 | PDB 归属 | 可使用范围 |
|---|---|---|
| 公共 | 公共 | 所有 Workspace |
| A | A | A |
| 公共 | A | A |
| A | 公共 | A |
| A | B | 不可配对 |

每个 Workspace 只检索自身和公共文件。组合的两半分别通过空间可见性判断。身份相同但不可见的内容既不参与候选和冲突，也不能通过物化或 Symbolicator 源变成候选。

Symbolicator 只接收本次系统选定的 pair 源，路径包含 Workspace、pair ID 和 Debug ID。共享缓存的键绑定所选内容；缓存可以复用相同字节，但不能补入范围外符号。已经冻结的来源按同一空间规则读取。外部公共源只能按冻结源策略查询，对冲突或身份不确定的本地选择不能绕过。

文件新归属和配对/复核变化写入顺序 CatalogChange。后台按 DumpSymbolReference 的真实身份分页查找受影响的需求。Workspace 变化只触及本空间；公共变化影响所有有相关身份引用的空间。单文件补传也可能改变默认分类，因此不必等完整配对才通知。重复标签上传不触发分析。

## 版本与统计

产物标签只管理产物，DMP 标签只影响 Occurrence 展示、筛选和崩溃统计，两者不互相推导。未填写时显示“未声明版本”，不存在默认 Build。

重复 DMP：已有非空版本保持不变；为空时允许首次补充；不同标签通过 `version_conflict` 和 `current_version` 提示。每次提交仍保留自己的版本。`PATCH /api/v3/occurrences/{id}/version` 支持明确编辑或清空，追加审计，立即更新列表/总览/Group 分布；不会创建新 AnalysisRun 或改写历史 Canonical。

## 分析准确性与生命周期

本空间产物默认 owned，仅公共产物默认 dependency，没有内容或人工依据的模块为 unknown。系统模块始终不进入业务栈。精确人工模块分类优先于默认分类；Workspace 自身的 in-app 规则继续适用。分类变化仅为相关空间生成新的分析。

Canonical 唯一版本是 **2.0**，没有 `build_resolution`。版本标签随 Occurrence 元数据返回，不加入 Canonical、符号选择或分析幂等键。

Core 的 `analyze-frozen` 接收内部 `analysis-run-v3`、`analysis-context-v3` 和系统生成的符号选择快照。快照绑定逐模块身份、候选是否完整、选择/冲突结果、实际内容和来源策略；用户不生成或填写这些内部对象。栈展开、精确符号匹配、物理帧来源和 Exact 算法继续复用。

任务通过事务 outbox 发布，Worker 只接受已持久化回执。执行代次、租约和结果对象前缀隔离旧 Worker 写入；任务重试受需求预算约束。结果先作为不可变候选保存，再按证据规则决定 Current。缺失、降级或冲突不能靠“最新结果”覆盖 Current。人工复核引用精确历史字节和提供方证据。

公共源传输超时或可恢复 HTTP 失败时，Core 保留已完成的业务符号与栈展开证据，输出部分报告。未执行请求使用 `unknown` 和 `source_budget_exhausted_before_request`，真实请求失败使用相关诊断的 `failed/transient`；两者均不能声称 PDB 在服务器不存在。损坏 DMP、身份不一致、越界来源和无效响应仍失败。首次部分报告也启动有限重试，默认最多三次分析；符号已完整的模块不会因未使用的备用源失败而反复重试。

源总预算默认 120 秒，逐分区最多 60 秒，单次 HTTP 交换最多 10 秒，轮询次数由期限决定。Core 总执行期限独立配置。报告页将报告可用性与后台更新状态同时展示；Worker 持久化实际阶段和完成项数，失败清理前保留源请求诊断。历史报告未记录的阶段保持未知。重新分析说明可省略，仍保存用户身份、默认说明、请求键和原始失败记录。

“补齐 Windows 公共符号”调用 `POST /api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/public-symbol-jobs`，`GET` 同一路径读取最近任务。任务读取 Current 的缺失情况；没有 Current 时读取冻结的失败 Run 检查结果。仅 `none` 选择且具有精确 PDB 文件名和 GUID/Age 的模块可进入下载，私有冲突、不可用选择和缺少调试身份的模块跳过。独立 `public-symbols` 队列默认总预算 600 秒、单文件 90 秒、最多 256 个下载目标；重复点击和失联重投绑定同一任务。任务只调用 Microsoft 专用 [Symbolicator PDB 代理](https://getsentry.github.io/symbolicator/api/proxy/)，从其持久缓存获取或下载原始字节，经过 Core 验证身份后才标记已补齐。代理无法提供上游缓存命中证明，因此 UI 的“已补齐并校验”不承诺发生了新的微软网络下载。此操作不生成 AnalysisRun/AnalysisDemand、不改 Current/报告历史、不清缓存，也不将微软 PDB 发布为用户产物。

PDB 身份使用 GUID 和 DBI 中的原始链接 Age；DBI 没有 Age 时回退到 PDB 信息流的 Age。后处理工具可能增加信息流 Age，因此不能把它直接当作 PE 的链接 Age；这遵循 [PDB 解析库的匹配规则](https://github.com/getsentry/pdb/pull/44)。GUID 和选定的链接 Age 均须精确匹配，不以文件名或更大的 Age 代替身份校验。

私有 pair 源采用单进程管理的磁盘内容缓存：按原始 SHA-256 复用，每次请求先检查 Workspace 可见性；缓存命中不授予范围。首次物化校验存储和原始哈希，进程重启或文件变化后重新校验。相同内容的并发请求合并，物化按字节和任务数限流，下载使用独立并发容量；HTTP 读取期间固定文件，淘汰只触及空闲内容。目标 Compose 默认磁盘预算 16 GiB、同时物化预算 4 GiB、两项物化和 16 个下载，PDB 数据不放入 tmpfs。

## HTTP 与部署

所有客户端 API 使用 `/api/v3`。核心入口：`POST /uploads:init`、`POST /uploads/{id}:complete`、`GET /uploads/{id}`、`GET /artifacts`、`GET /artifacts/{id}`、`PATCH /occurrences/{id}/version`。Workspace、Occurrence、Group、历史与复核接口保留，删除 Build 字段。OpenAPI 由应用生成，浏览器类型从该文件生成。

新部署默认开放上传和自动分析，不存在发布资格或功能启用开关。保留真实 Core、存储、队列和引擎身份的启动检查。Compose 不挂载全 Workspace 共享符号目录，不运行旧 Build 网关。

重置只允许明确列出的 Crash-Cap 项目资源。切换前备份旧库、对象存储及运行配置，保留旧镜像；回退恢复整套旧版本和备份，不对新库反向迁移。独立验收资源不需要重置现有项目。

## 验收记录

具体场景见 [上传 v3 指南](upload-v3-guide.md)。本地代码检查、真实服务端到端验收、浏览器验收和目标环境部署必须分别记录；构建成功不等于目标部署成功，历史验收不证明新体系通过。

上传使默认分类从 unknown 补充为 dependency/owned，或从 dependency 补充为 owned 时，允许在引擎、来源策略和显式分类不变的前提下自动更新 Current。比较仍检查物理栈、故障点、符号解释和退化；显式分类与引擎变化继续需要有依据的审核。历史报告不被改写。
