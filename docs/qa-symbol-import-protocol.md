# QA 首次上线协议约定

更新：2026-09-04。适用于[首次上线计划](qa-symbol-import-guide.md)。不承诺旧客户端、旧数据或混合版本兼容。机器协议由 `contracts/`、`contracts/drafts/qa-symbol-import/` 和生成 OpenAPI 共同定义；上线前按同一构建验证并发布，不能把本文当成已经部署的证明。

## 版本与身份

- Canonical `1.1`；Run `analysis-run-v2`；上下文 `analysis-context-v2`；选择清单 `resolution-manifest-v1`；任务消息 `1.2`；比较输入 `comparison-evidence-v1`，规则 `evidence-v1`。
- 原生分组 `group-v1.1` / `exact-v1.1`；`norm-v1.0` 保持函数归一化。CFI scan 不能继承 true-CFI 的可靠性资格。
- `qai-json-v1`：UTF-8 紧凑 JSON，ASCII 对象键排序，字符串不转 Unicode escape、不隐式 NFC，不允许浮点数，整数限 ±(2^53−1)，无尾换行；SHA 为小写十六进制。只用于指定哈希输入，不用于 Canonical 质量浮点值。
- PE Code ID 转小写；PDB Debug ID 为紧凑小写 GUID + 十六进制 age，保留原始提取值。文件名、版本标签不是身份。
- `pair_id = SHA256(JSON(["pair-v1", pe_raw_sha256, pdb_raw_sha256]))`。PE=`a`×64、PDB=`b`×64 的向量为 `47ef4d250a9240d7e9432186ccde2ce0a2ec5f8ba803dc1afea644eecb02c019`。

## 冻结选择

`resolution_evidence_fingerprint` 输入为 `["resolution-evidence-v1", dump_sha256, inspector_version, selection_version, modules]`。模块按 inspect 的 module_index 排序；记录 identity、state、candidates_complete、排序去重的 active/unavailable pair ID、selected_pair_id 和 reason。加载位置由 inspect 固定。

完整 manifest 摘要另外计算，包含 inspect SHA、catalog revision、完整候选校验与复核依据。来源/位置追加不改变相关指纹；有效资格变化改变相关指纹。先排除相矛盾候选，再判定完整集合的唯一或冲突；枚举失败或验证不足为 indeterminate，禁止截断后声称唯一。

上下文包含消费 Workspace、Build/角色/源码策略、capture profile、Core/Symbolicator digest 与算法版本。Run key 为 `["qa-run-key-v1", occurrence_id, fingerprint, context_sha256, "1.1", "evidence-v1", generation, attempt]` 的摘要。

私有 Symbolicator 请求按冻结 pair 分组；每个请求只有该 pair 的源。源协议 `pair-http-v2`；source_policy 同时冻结公共 HTTP 源。blocked 模块不能绕过冲突去访问公共源。保持物理帧 PC/inline 映射，最终汇合成一份 Core Canonical。

Run 同时冻结 result_facts、policy_snapshots 和源码内容位置；独立验证 Run SHA/assignment、manifest/inspect/DMP SHA 与暂存 PE/PDB 字节。Core、Worker、API 使用同一版本，Worker 不改写 Canonical 来补救身份或版本差异。

## API 与导入

新版前端与 API 成套部署，分析与导入能力走 v2。具体路径和字段以当前 OpenAPI 为准；未启用能力要有明确页面状态。DMP 上传复用实际字节校验和 submission 记录，同 Workspace+dump SHA 保持一个 Occurrence。

独立导入没有 Workspace/Build 前置，每项包含完整 PE/PDB。PE 最多 512 MiB，PDB 最多 2 GiB，每批 1—200 对。客户端先配对、服务端按实际文件验证。幂等 key 相同但内容摘要不同返回 409；声明合法不等于字节验证通过。逐对失败不回滚同批有效项，半对不能进入可用目录。

文件位置支持 identity/zstd-v1 与原始/存储哈希，不能以可清理暂存副本作为唯一有效出处。首次部署从空数据开始，不执行旧 Build 全量回填。

## 需求与预算

Demand 先 inspect 和登记倒排，再完整枚举/验证候选，冻结 manifest/context，最终事务复核后原子创建 Run 和 TaskIntent。对象 I/O 不持有长事务。Current、Group、Symbol Health、决策和任务回执必须一致提交。

需求 generation 从 1 起；A→冲突→A 推进为不同代次。retry_attempt 从 0 起；执行租约 generation 和 broker attempt_id 与需求代次分开。迟到结果保留为候选，不倒退 Current。

首次上线采用当前实现的重试约定：`analysis_max_attempts=3` 包含首次尝试；`analysis_retry_base_seconds=30`、`analysis_retry_max_seconds=300`，退避为 min(max, base×2^retry_attempt)，默认两次等待为 30/60 秒。第三次失败进入 retry_exhausted，只有新相关证据或明确人工操作开启新周期。取消旧 S0 的 30/120/600 提案，不再为该差异维持旧协议兼容。

自动执行初值全局 2、每 Workspace 1、容量 2；枚举页 200、放行页 50；合并截止 min(last_event+30s,first_event+60s)。执行期间必须续租，真实失租拒绝迟到提交；不能因长 I/O 无心跳反复空转。

## 比较与复核

故障锚点来自 inspect，保留异常代码/方向/线程/模块实例/RVA/地址；所有可靠物理业务帧按顺序比较并保留递归重复。多解对齐不可比；函数/文件/行从无到有是增量，已有非空解释改变须按原因处理。

暂时业务损失保留 Current 并有限重试；业务严格增量、全部旧锚点保持且其他损失仅 system 并有可核验 transient 证据时采用 Q16。dependency/unknown、missing、格式/完整性错误不属于例外。无关联原因的错误保留 unknown，禁止按文本猜测暂时性。

真实纠正使用[事后结果复核](qa-symbol-import-result-review-design.md)，绑定已经生成的两个报告摘要和不可变依据，允许较低分正确解释接替。不再把预知最终 Canonical 摘要的冻结预授权原型作为首版入口。新版本运行期间仍禁止重写 Run、首次决策或历史报告。

## 验证入口

`build_drafts.py` 维护当前 schema 与根目录 Reader schema；复核/审计 schema 单独维护。`contracts/drafts/qa-symbol-import/` 保留原路径，但其中的文件已被运行时和测试使用，不能作为临时文档删除。`test_protocol.py` 检查具名契约及再生成一致性。契约校验、实际字节验证、原生执行和最终部署验收各有不同职责，结果统一写入 `target/qa-first-launch/`。
