# QA 全局符号目录：实施设计与评审核查

更新：2026-09-04。本文保留 ADR-0015、0017—0021 对应的实施设计与比较规则。当前首次上线已完成本机验收；交付范围及环境边界见[实施指南](qa-symbol-import-guide.md)，精确字段见[协议约定](qa-symbol-import-protocol.md)与机器契约。此前旧版本兼容、历史回填及分阶段迁移安排不属于首次上线要求。

Q19 的契约决策见 [ADR-0019](adr/0019-version-canonical-symbol-resolution-evidence.md)，Q20 的目录与幂等决策见 [ADR-0020](adr/0020-resolve-global-symbols-with-dump-relevant-evidence.md)，Q21 的 Current 比较规则见 [ADR-0021](adr/0021-promote-current-analysis-by-versioned-evidence.md)。本次确认采用下述设计规则；源服务实现路径仍须资格验证，工程默认值仍须负载验证。

本文件保留技术规则与评审核查。实施路线、准备项、门禁状态、证据和回退统一维护在[方案设计与实施指南](qa-symbol-import-guide.md)，执行时从该指南进入。

## 1. 对收到评审的核查

评审指出的契约、入库表示、幂等、确定性选对与 Current 比较器缺口成立。之前“产品方向已收敛”不能作为可以开始功能编码的依据；该评审促成下述已确认决策和验收门禁，具体契约与验证证据仍需交付。收到的文本有重复与截断，此处按其编号记录可核实的主张。

| 评审项 | 核查与处理 |
| --- | --- |
| 3.1 冲突与 Canonical 契约 | 成立。v1.0 固定 schema_version、模块状态和 warning 枚举，并禁止额外字段。还存在 AnalysisRun 数据库 CHECK、Worker 校验、API 语义校验和 OpenAPI/前端版本绑定，不能只新增 schema 文件。 |
| 3.2 全局库存与幂等 | 风险成立，但全局 revision 入键不会自行启动全平台任务；它会使无关 Occurrence 的后续请求失去旧幂等命中。任务扇出、Run 幂等、符号缓存失效是三件事，必须分别设计。 |
| 3.3 无 Workspace 入库 | 成立。现有 Blob 和 Artifact 的 Workspace/Build 非空约束不适合直接承载新入口；已确认新增全局记录，保留旧表身份。 |
| 3.4 多候选规则 | 采纳，补充顺序：先对实际文件及 DMP 提供的身份做一致性校验，再按 PE/PDB 原始内容哈希分组。检索初选的多个候选不等于多个有效匹配。 |
| 3.5 扇出预算 | 成立。限制每批工作和执行并发；剩余目标持久排队，不截断最终受影响集合。 |
| 3.6 unknown 首报告 | “unknown 故障模块必然低 coverage、Unclassified”不成立。故障模块 matched 且有 Debug ID，再有可靠业务调用帧，就可能具备 Exact 和完整业务覆盖。必须拆成两个验收场景。 |
| 3.7 来源与质量 | 全局化扩大错误证据影响范围的判断成立；matched、Symbolicator found、函数/行号完整程度以及构建来源可信性是不同结论。来源类别可展示审计，不能自动获得匹配优先权。 |
| 3.8 留存 | “Artifact Blob 具有 retention_days/expires_at”不成立。该期限作用于 DumpBlob，现有 canonical Artifact Blob 没有到期删除字段。仍应明确新目录长期留存、逻辑停用与物理清理的界限。 |
| 3.9 Current 比较器 | 成立。除规则外还需要版本化输入、结果原因、不可比与纠正分支，以及专项 Golden 场景。当前 trust 有信息合并，不能直接把数值权重作为可靠性全序。 |

关键事实出处：

- [Canonical v1 Schema](../contracts/analysis-result-v1.schema.json)：24 行固定 1.0；258 行 trust；266 行 warning；352 行 module。
- [AnalysisRun 模型](../platform/api/crashcap_api/models.py)：571 行限制 schema_version=1.0；[语义校验](../platform/api/crashcap_api/canonical_semantics.py) 154 行也固定 1.0；[Worker](../platform/worker/crashcap_worker/processor.py) 1961 行选定 v1 Schema。
- [分析创建](../platform/api/crashcap_api/services/analysis.py)：57 行计算键，129 行查询复用，133 行创建 Run，195 行才生成投递消息。
- [质量与 Exact](../core/src/canonical.rs)：704 行起；Exact 在 788 行要求故障模块 matched/Debug ID，在 798—817 行检查业务帧，没有要求故障模块自身 in_app。
- [Blob 模型](../platform/api/crashcap_api/models.py) 289 行、[DMP 到期赋值](../platform/worker/crashcap_worker/processor.py) 374 行、[retention](../platform/worker/crashcap_worker/retention.py) 28 行。
- [trust 映射](../core/src/unwind.rs) 207 行将 CallFrameInfo 与 CfiScan 都映射为 cfi；[帧输出](../core/src/canonical.rs) 中 function_offset 当前赋值为模块相对地址，不能作为函数内部偏移使用。

六条链路必须在启用时一致，不要求在一次不可回退的大部署中同时开发完成。采用先上兼容 Reader/数据库、再建新目录和 shadow 路径、完成资格验证后启用新写入的顺序。

## 2. Q19 已确认：Canonical 1.1 与可解释符号证据

采用新建 Canonical 1.1，保持 1.0 文件及历史结果原样。新 Reader 同时读取 1.0/1.1；旧的 1.0 Reader 不会因为“保留兼容”就能接受 1.1。新写入只能在 Reader、数据库约束、Worker、API/OpenAPI 和前端都准备完成后启用。回退关闭新写入并保留兼容 Reader，不能把 conflict 降级伪装成 missing_pe 来喂给旧 Reader。

已确认需要表达的新增事实如下；精确字段路径、类型、枚举和验证约束在机器可读契约交付时冻结。

| 内容 | 已确认的表达要求 |
| --- | --- |
| 本次分析的身份冲突 | 模块状态增加 symbol_conflict；有类型的 warning 和候选证据引用。 |
| 配对已停用或无法安全取用 | 明确 unavailable 原因；不能一律伪装成缺 PDB，也不能把不可读文件标为 matched。 |
| 确定性选择 | 选择规则版本、相关证据指纹、选中的 pair_id、候选逻辑对集合/计数和冻结证据引用。大候选列表可用带内容摘要的不可变引用，不能省略“集合是否完整”。 |
| 符号获取结果 | 按模块及来源记录阶段、结果和 transient/permanent/unknown 原因。missing 不等于暂时失败，found 不等于完整行号。 |
| 展开依据 | 保留足以区分真实 CFI、CFI scan 等的原始展开方法；现有 trust 继续用于兼容展示，比较器不从折叠后的 cfi 猜测原始方法。 |

Canonical 记录影响本次分析的事实，由 Core 最终生成。导入进度、来源审计、后发生的停用/复核事件属于平台目录状态；可在 UI 中同时展示，但要与该 Run 当时冻结的分析事实区分。Current 晋升理由属于平台决策记录，不在事后改写 Canonical。

实际逐模块/逐来源暂时错误是否可从当前 Symbolicator 响应直接获得，需要资格验证；不足时补 Gateway/源服务可关联的诊断。证据不足时记 unknown，不猜测为 transient。

## 3. Q20 已确认：新增全局目录，保留旧存储身份

增加独立的全局目录记录，不把旧 Blob 的 workspace_id 改为空，也不创建要求 QA 选择的伪 Workspace。下表固定记录职责与关键约束；物理表名、索引和迁移 DDL 随兼容数据模型交付。

| 记录 | 职责与关键约束 |
| --- | --- |
| symbol_imports / items | 无 Workspace 批次及完整配对提交项，逐对验证和结果；半个文件只属于暂存态。 |
| catalog_files | PE/PDB 的内容身份、类型、大小、提取到的身份及验证版本；不依赖 Build 或 Workspace。 |
| catalog_file_locations | 内容的物理出处、payload 编码及校验信息；可指向旧 canonical Blob 或新的平台对象。 |
| catalog_pairs | pair_id = H("pair-v1", pe_raw_sha256, pdb_raw_sha256)，要求两端格式、架构及身份一致。相同字节只产生一份逻辑配对证据。 |
| catalog_pair_origins | 保留多个 Build/Publication/独立导入来源。来源 Workspace 是溯源字段，不成为消费方角色。 |
| catalog_identity_memberships / changes | 身份检索索引、候选成员、准入/停用事件及全局 revision；检索桶不是最终匹配结论。 |
| dump_inspections / dump_symbol_references | 可复用的 DMP inspect 结果及精确模块身份到 Occurrence/Workspace 的倒排索引。 |
| auto_analysis_demands | 持久分析需求、目标证据、合并时间、代次、重试预算、排队状态和处理游标。 |

目录只引用受保护的 canonical Blob/有效 payload。可能被旧副本清理器删除的对象不能成为唯一出处；若保留此类出处，清理器必须先识别新增引用。目录生效不要求把历史字节搬家或先完成全局物理去重。

## 4. 三类版本与相关证据指纹

| 标识 | 职责 | 不承担的职责 |
| --- | --- | --- |
| catalog_revision | 一致性读取水位、目录事件顺序、补偿游标 | 不直接作为所有 DMP 的语义幂等依赖。 |
| resolution_evidence_fingerprint | 该 DMP 实际相关的选择结果，参与分析幂等 | 不包含无关上传、纯来源追加或全局 revision。 |
| pair/source 内容身份 | 固定符号服务实际返回的 PE/PDB，控制私有缓存 | 不由请求的 Workspace 或最新上传顺序决定。 |

冻结的 resolution manifest 包含 DMP 身份查询、选择规则版本、逐模块 none/unique/conflict/unavailable/indeterminate 状态、排序的有效候选 pair_id、选定 pair、复核依据及目录读取水位。指纹只对影响解释的字段做规范化摘要；整个不可变 manifest 另有完整内容 SHA，不能把这两个摘要混为一谈。

预期结果：

- 无关符号上传、健康配对的同字节多来源追加：相关证据指纹不变。
- 相关缺失变为唯一、出现冲突、配对停用或恢复：相关证据发生变化。
- 本 Workspace 角色、Build 约束、源码策略、引擎与规则变化：通过独立的分析上下文摘要表达。
- 同一身份的初选桶改变，但新增候选与该 DMP 其余身份矛盾：最终候选集合不变，不制造多余 Run。

还要处理 A→A+B 冲突→A 的状态回返。如果已经产生较新的冲突 Run，不能直接返回历史唯一匹配 Run；旧 Run ID 不可重新晋升为较新的 Current。分析需求保留受控 generation：在实际规划的有效目标发生转换时推进，重复事件和无关上传不推进；同一 generation 的相同请求去重，自动重试另用有界 attempt 序号。存在不同目标的较新在途 Run 时，不能仅因当前结果的指纹相同就省略恢复需求。

Run key 由 Occurrence、相关证据指纹、本地分析上下文、契约/算法版本、需求 generation 和受控 attempt 组成，其规范化编码随版本化契约冻结。全局 revision 仅供审计和补偿。原来的随机 force 保留为明确人工操作，不能用它实现无限自动重试。

## 5. 必须调整分析规划时序

当前系统先创建 Run 和幂等键，随后 Worker 才 inspect DMP。按 DMP 计算相关证据指纹，需要提前得到可复用 inspect。

已确认的规划顺序：

```text
接受 DMP / 补符号事件
  → 持久分析需求
  → 获取按 Dump SHA + inspector 版本缓存的 inspect
  → 登记模块倒排索引，并检查并发目录变化
  → 冻结 resolution manifest 与 Workspace 分析上下文
  → 计算相关证据指纹及受控 generation/attempt
  → 创建不可变 Run + durable task intent
  → 物化确定配对、unwind、符号化、Core 输出 Canonical
  → 版本化 Current 决策及事务性投影
```

分析需求可更新目标和进度；已创建 Run 的输入不能再改。UI 在规划阶段显示“准备分析”；原 API/Reader 的兼容路径需要在实现设计中明确，不能先返回一个假冻结 Run 再悄悄补齐输入。

## 6. 多候选判别规则

1. 用 DMP 实际具备的规范化 Code ID/Debug ID/架构初选候选，文件名只用于定位与展示。
2. 对候选实际字节及身份关系校验；DMP 与候选均提供的身份必须相容，PE 与 PDB 必须成对一致。
3. 将有效候选按 (pe_raw_sha256, pdb_raw_sha256) 分组。
4. 零组：按真实原因给出 missing、unavailable 或格式/身份错误。
5. 恰好一组：选该逻辑 pair；多个来源只作为该组的可验证物理出处与溯源记录。
6. 多个不同字节组：symbol_conflict，不选择任意一组。
7. 查询、验证或候选枚举未完成：indeterminate，不得截断后声称“唯一”。

Core 匹配、PE unwind 和符号源必须使用同一个冻结选择。冲突模块可以保留来自 Dump 的地址与展开证据，但不能借助任意私有源或公共源把符号冲突绕过成 matched。

2026-09-03 资格进展：新增独立的冻结 PE 展开入口，只将已选择的捕获模块实例传给 provider；新 raw 保留原始 unwind_method，历史折叠 trust 不被补造。旧默认 CLI 尚未切换。见[首次上线计划](qa-symbol-import-guide.md)。

## 7. 确定性符号源及资格验证

优先方案：按内容 pair 建内部 HTTP source，例如 source_id 为 crash-cap:pair:<pair_id>:http-v2，路径只返回该 pair 的固定 PE/PDB。Gateway 从已冻结 manifest 注入部署管理的源，继续拒绝客户端自定义 URL。相同 pair 跨 Workspace 使用相同内容源身份，无关目录 revision 不影响它。

若多 pair sources 的数量和匹配开销不能满足资格门禁，备选是按相关选择内容摘要生成不可变 manifest source；其服务端必须查冻结映射，不能查 latest catalog。该备选也必须经过同一资格门禁后才能定为实现路径。

启用前必须验证真实 Symbolicator 的：多源选择/过滤、源数量上限、相同 pair 跨 Workspace 缓存复用、同 Debug ID 不同字节的隔离、missing→unique 和 unique→conflict 行为、缓存命中时仍遵守冻结选择。现有 Gateway 假上游单测不足以证明这些性质。

首轮真实资格已选定按冻结 pair 分组请求的 HTTP source 方向：同 Debug ID、不同 Code ID 的两个模块在整批双源请求中出现错配；每个私有请求只使用对应 pair source 后，200 个构造模块实例均获得预期函数。整份 Run 仍冻结一个 manifest，Core 汇合所有分组结果后输出一份 Canonical；不是多个报告拼接。没有碰撞分区的整批 manifest source 不采用。具体结果、诊断约束、PC/inline 映射及剩余协议工作见[首次上线计划](qa-symbol-import-guide.md)。

## 8. 扇出与重试预算

Q20 已确认自动执行初值为全局最多 2 个、每 Workspace 最多 1 个，且不得超过部署实际提供的自动执行槽位。每批枚举 200 个目标、每次最多放行 50 个需求作为可配置工程起始值。按 Workspace 公平调度，新 DMP/人工请求优先。数值需要负载验证，不是完成时限承诺。

- 超额目标留在 durable demand 中，显示排队进度；不能超过前 N 个就忽略。
- 先按身份倒排索引定位；新冲突也要覆盖已经使用该身份的报告，不能只查缺符号列表。
- 合并使用 min(最后事件+30秒，首次事件+60秒)。预算排队及执行时间单独展示。
- 在途 Run 不改输入；新事件保留下一轮目标。事件游标推进和需求写入原子完成，重复投递幂等。
- 新 DMP 建索引与符号上传交错时要做 revision 补偿；服务重启、队列重复与 worker 失租不得丢需求或重复晋升。
- 自动重试由需求控制器管理 attempt 和有限预算，不能依赖终态 Run 的 broker 重投。预算耗尽保留诊断；新的相关证据或明确人工操作才能开始新周期。
- 原始 DMP 已过期时标记不可重分析及所需补充材料，不能把该需求记为分析成功。

新路径必须使用 durable handoff/执行 fencing；现有只返回投递消息的 legacy 路径不能承诺持久不丢工作。

## 9. Q21 已确认：evidence-v1 Current 比较器

实现位置保留平台 Current 的单一晋升入口。比较器是纯决策模块，输入两个不可变证据记录，输出 decision/reason/证据差异/版本；最终以 Occurrence 锁与现有执行 fencing 复核 Current，再原子更新 Current、Group、Symbol Health 和审计。候选完成过程中 Current 已改变时必须重新比较。

### 9.1 适用范围

仅对明确的 symbol_refresh 原因使用 Q7/Q16 自动比较。要求同 Occurrence/Dump/inspect，以及兼容的引擎、规范化、分组、角色政策、capture profile、人工 Build 约束和源码政策。兼容性必须由明确版本规则和门禁建立，不能因为新旧都叫 cfi 就假设等价。

角色变更、引擎/契约升级、人工纠正使用各自明确的处理原因；不兼容基线按不可比处理。首次上线不迁移旧 1.0 Current，新版本内的历史报告仍须保持不可变和可追溯。

### 9.2 保护锚点与改善

- 故障锚点：异常代码、访问方向、线程、指令所属模块实例与精确 RVA。Canonical crash.address 是指令地址；访问违例目标地址应从 inspect 的 fault_address/parameters 取证。
- 业务锚点：旧 Current 崩溃线程中可验证的可靠物理 in-app 帧；首版保护全部此类锚点，不仅比较 Exact 取样的前五帧。
- 按模块身份、模块实例、精确 RVA 做有序对齐并保留递归重复。显示 index、函数名、16 字节分桶及当前 function_offset 不能充当锚点。对齐不唯一即不可比。
- 旧锚点既有函数/文件/行号不能变空；非空值改成其他非空值属于解释改变，需要原因，不能当作改善。
- 不按权重推导 trust 全序；首版要求旧保护锚点的可验证展开依据保持。CFI scan 等原始依据要保留，旧契约缺少依据时明确限制比较能力。
- 严格增量可以是新增可靠业务帧、已有业务锚点补出函数/文件/行号，或相关模块从缺产物变为唯一精确配对；同时旧保护锚点须保留。coverage 因分母减少而上升不算改善。

### 9.3 决策结果

| 条件 | 已确认处理 |
| --- | --- |
| 尚无 Current，候选成功/部分成功且证据可用 | 成为首个 Current。unknown 业务归属不阻断函数/行号展示。 |
| 可比且等价/改善，无证据退化 | 按创建顺序晋升。 |
| 明确暂时失败导致关键证据退化 | 保留旧 Current，记录新 Run 并有界重试。 |
| 严格业务增量且旧锚点保留；其余丢失仅限明确 system 且非业务的符号信息，并有相应暂时故障证据 | 按 Q16 晋升，显示暂缺信息并继续有界重试。dependency/unknown 不能统称系统。 |
| 对齐、来源原因或比较上下文不充分 | 标为不可比，保留原 Current 与新候选，明确需核对的差异。不能无限重试或用总分自动决定。 |
| 有已核实的新证据纠正、身份冲突或旧配对停用依据 | 进入可审计的 evidence_correction 路径；允许较低分的新可靠解释接替旧结论，旧结果留历史。不得把已证伪结论保护为仍可信。 |

暂时错误必须有来源依据；system_symbol_failed、PARTIAL 或一次未知原因失败本身不够。真正 missing、格式损坏和完整性失败不能混进 Q16 的暂时系统退化例外。

Q21 已确认不可比候选保留旧 Current 并展示差异、真实纠正走独立审计路径。不能补造记录缺失的 trust 信息，无法建立比较依据时按不可比处理并明确显示原因。原始 DMP 已过期而旧依据又被停用时，应明确显示“依据已停用、无法重算”，保留历史可追溯性；不得继续把它呈现为已复核的当前结论。

## 10. 来源、验证与生命周期

展示来源类别：可追溯的 Build Publication（含 local/ci 声明、Build 是否封存）或独立导入；另外显示字节/配对验证结果、符号可用能力和人工复核记录。当前匿名系统中的“已封存 Build”证明期望集合与字节对齐，不等于经过身份认证的可信构建。不得以来源类型覆盖同身份内容冲突。

Q20 已确认符号内容长期留存，本次不引入用户物理删除或自动符号 GC。错误配对可以逻辑隔离/停用，保留字节和审计依据；这不要求先制造第二个冲突候选。复核后恢复或替换可用资格，触发受影响需求。暂存上传副本清理、原始 DMP retention 和符号证据留存分别管理。

## 11. 实施路线、门禁与准备项

验收要求、部署边界和交付状态集中维护在[实施指南](qa-symbol-import-guide.md)。本文不维护逐轮进度；旧 S0—S8 兼容升级路线已退出首次上线范围。

全局范围、完整配对和 owned/dependency 语义以 accepted ADR 为准。验证若证明必须改变这些边界，应记录具体证据并修订决策；没有实施证据的路径不得标为可用。
