# QA 全局符号：首次上线实施计划

更新：2026-09-04。用户已明确改为首次上线：不保证旧版本、旧数据、混合部署或降级兼容；验收允许删除本项目旧数据卷并彻底重新部署。本计划取代此前 S0—S8 的兼容升级路线。业务语义仍以 design.md、accepted ADR 和本计划为准。

## 交付目标

交付一套从空数据库和空对象存储启动的完整系统：QA 通过浏览器提交 DMP、导入完整 PE/PDB；符号按实际身份供全平台使用；后到符号自动更新受影响报告；角色与业务统计限定 Workspace；冲突、失败、历史候选及 Current 选择可解释。

Windows x64 / MSVC / 完整 PDB 7.0 为首版范围。无需源码、Git 或正式 Build；源码包与 Build 关联不作为独立导入的前置。仍保留同一新版本运行期间的历史 Run、幂等提交和业务计数正确性。

## 删除的交付负担

- 不再验收旧 Canonical 接续、旧客户端、混合镜像、旧数据库升级与降级回退。
- 不再为既有数据执行全量符号回填或保留两个旧版发布周期。
- 验收失败可清空本项目环境重建，不必修复已丢弃的测试数据。
- 不继续新增逐轮 progress/evidence Markdown；过期专项记录删除。运行证据仅保存到 ignored `target/qa-first-launch/`，仓库保留这一份状态台账。
- 已有兼容代码按依赖逐步移除；不为删除代码而重写无关模块。没有生产兼容承诺的原型纠正路径优先清理。

## 必须保留的正确性

1. PE/PDB 必须完整验证；按实际 Code ID/Debug ID/架构及内容哈希匹配，不按文件名、版本标签或最新上传选择。
2. 不完整候选集合不能宣称唯一；同身份不同有效内容必须冲突，公共符号和缓存不能绕过冲突。
3. 同一 Run 的匹配、PE unwind、符号源和 Canonical 使用同一冻结选择。Core 输出最终 Canonical 1.1。
4. 全局符号不带入其他 Workspace 的 owned/dependency、Build 或源码策略。
5. Current、Group、Symbol Health、决策和任务回执一致提交；失败或迟到结果不能倒退 Current。
6. 暂时失败有真实原因和有限预算；业务证据退化保留 Current，符合 Q16 的业务增量可晋升并安排重试；永久/未知失败不冒充暂时失败。
7. 超额工作排队、分页无遗漏，Worker 重启和重复投递不增加领域副作用；耗尽后可明确人工重启。

## 实施顺序与当前状态

| 工作包 | 本轮交付 | 状态 |
| --- | --- | --- |
| A 收缩与清理 | 替换旧路线，清理过期文档，取消兼容专项目标，统一验收场景入口 | 已完成 |
| B 补齐核心缺口 | 规划 I/O 内续租；源错误关联诊断；有界重试/Q16 实际 Worker 闭环；清理预授权纠正双轨 | 本机原生闭环通过 |
| C 首次部署 | 空数据库迁移、API/前端/relay/自动 planner/Worker/材料源/固定 Symbolicator 与 Core 一次部署；生产配置可合法启用 | 本机空卷部署通过 |
| D 同版本验收 | 核对构建与组件摘要，空卷功能、故障和实际浏览器验收；修复后重建并复验受影响路径 | 本机验收通过 |
| E 上线交付 | 确切版本与配置、QA 操作说明、启动/停止/重建命令、健康检查、完整验收摘要 | 本机首次上线交付完成 |

现有实现具备导入、目录、冻结分析、自动调度、Current/历史、角色及复核主链。本机首次上线的全部必需场景已通过，可用于首版 QA；目标内网部署和远端 CI 尚未执行。此前源码快照的测试不作为新版本最终证书。

已删除 42 份过期进度/证据文件，并将结果复核设计中的逐轮记录压缩为当前流程。Worker、冻结 Run 和机器契约中的预授权纠正路径已删除，只允许事后复核。规划任务及等待项后台续租已跨过真实 PostgreSQL 的 30 秒租约边界，并验证竞争调度器和旧令牌拒绝；对应应用及测试文件摘要已核对未变。材料错误区分 422/500/503，Core 只识别经过身份、source、location 校验的固定引擎候选诊断。

当前原生故障专项 9/9 通过：真实双线程 DMP、固定 Symbolicator、Core、PostgreSQL、Redis 与独立 Worker 进程执行 Q7/Q16 和 404/422/500 对照。修复了 Q16 晋升后第二次仍遇 503 却被“等价”比较提前停止重试的问题；已观察到 30/60 秒退避、三次预算耗尽、源恢复后人工重启和幂等回执。

当前部署：系统符号修复后再次删除本项目 6 个命名卷及 2 个独占匿名卷，从空数据库/对象存储启动。Core 镜像为 `sha256:bf43de03bef29cbf7787ac70fd59d456c38aed8773a59c93e4c9a5f28c9effdc`，成套镜像和源码摘要记录在 `target/qa-first-launch/build.json`。真实 HTTP/S3/Worker 主链重新通过：后到完整配对更新 Current、第二 Workspace 无 Build 复用、同批坏 PDB 拒绝与好配对可用、重复 DMP 复用 Occurrence。当前报告 `run_01M1NWZTRGN7K2FTKG8V8RGVDT` 显示 `crashcap::trigger_null_read()`、行号 76；浏览器实际看到 `kernel32!BaseThreadInitThunk` 和 `ntdll!RtlUserThreadStart`，两模块均为 matched，PDB 来源为 Microsoft 官方符号源。修复使身份核验通过的公共 PE 参与本地栈展开，并将 PDB 加载结果与目录配对选择分别显示；冲突模块不使用公共源兜底。未被堆栈请求的模块不会宣称已加载 PDB。

当前构建补验：API/Worker 584 项通过，21 项需独立环境的用例跳过；协议 18 项、前端 105 项通过。前端默认并发曾造成 13 项超时，保持断言和时限、限制两个测试进程后整套通过，CI 已同步并发上限。微软 PE/PDB 冷缓存原生专项通过。存储重启及清空后备份恢复重新通过，恢复 55 张表和 73 个 S3 对象并核对全部对象哈希，恢复后新 Workspace 可直接解析到系统函数。实际冲突恢复重新通过，Current 与历史字节检查有效。CI 已移除旧 Current 接续和兼容迁移门禁，新增 Q16 系统线程夹具、实际源故障与公共 PE/PDB 专项；工作流 YAML 和 Bash 语法检查通过，尚未提交或执行远端 CI。

最终原生矩阵固定当前源码及二进制并在执行后核对摘要，五个场景全部正常退出：源故障 9 项、PostgreSQL 策略 59 项、原生目录/源码隔离 10 项、双 Workspace 后到配对生命周期 5 项、容量专项 5 项均通过。生命周期覆盖配对停用与恢复、事后复核、角色变化，以及 DMP 过期后不新建分析并保留历史报告字节。容量专项在分页 200、全局执行容量 1 下完成 201 个 Workspace 的初始报告和后到符号更新，全部 Current 晋升且旧 Canonical 摘要未变；旧 Core 的容量结果不计入当前构建的验收结论。

浏览器结果复核的响应丢失、整页刷新和原请求重试已通过，数据库只保存一份审核，Current 正确指向候选。实际浏览器已创建 `qa-browser-first-launch` Workspace 并进入上传页。当前部署的不同人工标签重复提交也已核对，保留两份标注且不增加 Occurrence、不改变 Current 和报告字节。手动部署说明已补齐 Core 构建及实际镜像摘要注入，并明确同版本恢复和首次上线清空边界。

浏览器主链已关闭：Chrome 实际上传 DMP，生成 `run_01M1P0HGK6Y0MRSE4H65H4AS5M`，核对函数、源码路径、第 76 行及两个微软系统函数。实际选择完整 PE/PDB 并提交批次 `imp_01M1P0M8729CPEC7RFYQNT5JD4`，配对验证生效、来源记录合并，刷新回执和报告正常。本例复用已有全局配对；从无符号到后到配对的更新由空卷 HTTP 主链及原生矩阵另行证明。

浏览器验收发现并修复前端 Nginx 默认请求体限制导致 9,261,056 字节 PDB 返回 413。仅符号二进制上传路由允许最多 2 GiB 并流式转发；超限和普通 JSON 路由仍被限制。前端已重建部署为 `sha256:538732c14b8a33247318afedee54edc5f6f9fc4e7b8071745dbd60bd8a1eb715`，原批次重试通过。API/Worker/Core 及前端业务代码未变，原生验收保持对应组件摘要，代理配置以实际容器配置、边界请求和真实浏览器补验，不重复清空已验数据。完整结果、镜像修订和逐项对应关系位于 `target/qa-first-launch/result.json`。

报告仍可显示“部分完成”：本 Workspace 尚未声明业务角色或 Build，且未参与堆栈的系统模块未请求材料。这不表示已核对的业务栈或微软 PDB 加载失败，也不宣称所有模块均已加载符号。

## 首次上线验收

| 场景 | 必须观察到的结果 |
| --- | --- |
| 从空卷部署 | 所需镜像、服务、迁移、材料源全部就绪；部署模式真实可用，不改 environment 绕过产品限制 |
| 浏览器主链 | 创建 Workspace → 提交真实 DMP → 导入 PE/PDB → 真实 Core 分析 → 函数/文件/行号与身份正确 |
| 微软系统符号 | 公共 PE 经捕获身份核验后参与栈展开；真实报告解析 BaseThreadInitThunk / RtlUserThreadStart，页面区分 PDB 加载和导入配对状态；冲突不走公共兜底 |
| 配对错误隔离 | 同批坏配对失败、好配对成功；半对不可用；同字节多来源不制造额外 Run |
| 后到与无关符号 | 两个 Workspace 的受影响报告自动更新；无关身份不生成新语义需求 |
| 冲突与纠正 | 唯一→冲突→恢复不复用不可晋升结果；核实停用错误配对、事后复核新候选有完整审计 |
| Workspace 隔离 | 同一 pair 的角色与 Build/源码解释分别计算；unknown 可见符号，不虚构业务覆盖 |
| 重复提交与历史 | 标签差异保留，同一 DMP 不增加 Occurrence；新版本运行期间旧 Run 字节不被改写 |
| 暂时与永久失败 | 实际故障注入命中 Q7/Q16；404/损坏不能套用暂时性例外；unknown 明确诊断 |
| 有界执行 | 慢材料 I/O 不因合法租约反复空转；失租、进程中断、重复投递不破坏 Current；耗尽停止并可人工重启 |
| 分页与容量 | 超过 200 个受影响目标且跨至少两个 Workspace，无遗漏、有限并发、公平进展 |
| 真实存储 | 部署所选存储的读写/完整性/重启验证通过；DMP 过期仍能查看已完成报告 |
| 回归与 QA | 当前契约、Core、API/Worker、前端、构建通过；真实浏览器完成入口和失败恢复，不以 mock 代替 |

旧案例 C21（旧版兼容）和 C22（历史回填）退出首次上线门禁。备份恢复不以旧版数据为输入；新部署的数据备份与恢复能力按实际部署栈检查。长期容量观察作为上线后运行工作，不再以旧版回退窗口阻塞首次交付。

## 部署和清空边界

允许删除已核对归属的 Crash-Cap Compose 项目数据卷，丢弃既有测试 DMP、符号、Run 和报告。每次清空前记录实际 Compose 项目、容器标签、卷名与挂载；只删除该项目所属资源。禁止全局 Docker prune，也不删除其他项目的数据卷或来源 PE/PDB/源码文件。

API、前端、Worker 和数据库使用已记录的候选镜像成套部署，不保留混合版本承诺。影响数据模型或分析语义的修复需重新构建并从空卷验收；仅代理配置的修复记录镜像修订并复验浏览器和请求边界，未变组件须核对摘要后保留其验收结果。

首次准备主机与密钥见[部署说明](operations/phase1-deployment.md)。当前本机验收环境使用 `target/qa-first-launch/compose.env`，按以下顺序可重复清空并启动；清空脚本默认只检查归属，只有显式 `--reset-data` 才删除数据，且会拒绝其他项目使用的卷。

```text
python scripts/qa_symbol_import/reset_first_launch.py --env-file target/qa-first-launch/compose.env --reset-data
docker compose --env-file target/qa-first-launch/compose.env -f deploy/compose/phase1.yml -p crash-cap-phase1 up -d --wait --wait-timeout 180
docker compose --env-file target/qa-first-launch/compose.env -f deploy/compose/phase1.yml -p crash-cap-phase1 ps
```

代码变化后先构建镜像再执行上述步骤。Q7/Q16 和 404/422/500 原生故障验收入口为 `python scripts/qa_symbol_import/qualify_catalog_postgres.py --scenario source-failures`；Windows 上用 `scripts/fixtures/build_p0_b01.ps1 -SystemWaitThread` 生成真实双线程 Q16 DMP，首次解析系统线程需要访问 Microsoft 符号源。

## 文档与证据

- 本文：唯一实施状态和交付清单。
- [实施设计](qa-symbol-import-implementation-design.md)和 ADR-0015—0021：保留技术规则与业务决策；逐轮讨论及旧分阶段计划已删除。
- [协议约定](qa-symbol-import-protocol.md)：版本、身份、冻结选择和重试规则，与实际机器契约同步维护。
- [结果复核设计](qa-symbol-import-result-review-design.md)：正式事后复核入口。
- [QA 操作说明](qa-symbol-import-qa-operations.md)：与最终部署可见行为保持一致。

最终验收只输出一份 `target/qa-first-launch/result.json` 和必要日志/截图，包含构建身份、场景、实际结果、失败/跳过和环境。所有必需场景通过、实际浏览器可用、部署命令可复现后完成本目标。不得以“代码已写”或历史专项 PASS 代替。
