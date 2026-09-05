# Crash-Cap 2.0 设计

本文件是当前设计的权威来源。2026-09-05 采用 ADR-0022：选择空间、上传文件、附带可选版本。旧 Build 发布、Manifest、完整配对、全局检索和旧 Canonical 兼容规则全部被取代。旧设计和验收记录仅说明历史，不能作为当前运行约束。

## 用户模型

用户可以上传 EXE、DLL、PDB 和 Windows x64 用户态 DMP。目标必须是一个明确的 Workspace 或公共空间。公共空间只接收 PE/PDB。版本是可选的普通字符串，不需要登记，不参与身份匹配、文件验收或分析幂等计算。

CLI 只有 `crashcap upload` 上传入口，可接受多个文件或递归目录。`--workspace` 接受 ID 或精确名称；`--public` 选择公共空间；两者互斥且必选一个。不存在的名称报错。`--build-version` 是业务标签，`crashcap --version` 是程序版本。上传不要求 Git、配置文件、模块清单或本地配对。

浏览器 Workspace 上传页直接使用当前空间，平台入口显式选择空间，也可以就地创建 Workspace。整批一个可选版本。开始上传后固定本批目标和标签，清空列表可以开始新批次。每个文件独立验收；一个文件失败不回滚其他文件。

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
- `CrashGroup`：继续使用 Exact Group 算法；当前版本分布查询 Occurrence 当前标签。

数据库只有新的空库基线 `0001_upload_v3_baseline`。不提供旧数据库和旧客户端迁移/兼容路径。源码包上传和浏览源码包功能随 Build 体系删除。

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

## HTTP 与部署

所有客户端 API 使用 `/api/v3`。核心入口：`POST /uploads:init`、`POST /uploads/{id}:complete`、`GET /uploads/{id}`、`GET /artifacts`、`GET /artifacts/{id}`、`PATCH /occurrences/{id}/version`。Workspace、Occurrence、Group、历史与复核接口保留，删除 Build 字段。OpenAPI 由应用生成，浏览器类型从该文件生成。

新部署默认开放上传和自动分析，不存在发布资格或功能启用开关。保留真实 Core、存储、队列和引擎身份的启动检查。Compose 不挂载全 Workspace 共享符号目录，不运行旧 Build 网关。

重置只允许明确列出的 Crash-Cap 项目资源。切换前备份旧库、对象存储及运行配置，保留旧镜像；回退恢复整套旧版本和备份，不对新库反向迁移。独立验收资源不需要重置现有项目。

## 验收记录

具体场景见 [上传 v3 指南](upload-v3-guide.md)。本地代码检查、真实服务端到端验收、浏览器验收和目标环境部署必须分别记录；构建成功不等于目标部署成功，历史验收不证明新体系通过。

上传使默认分类从 unknown 补充为 dependency/owned，或从 dependency 补充为 owned 时，允许在引擎、来源策略和显式分类不变的前提下自动更新 Current。比较仍检查物理栈、故障点、符号解释和退化；显式分类与引擎变化继续需要有依据的审核。历史报告不被改写。
