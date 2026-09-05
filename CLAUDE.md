# Crash-Cap 工作约定

先读 [CONTEXT.md](CONTEXT.md) 和 [docs/design.md](docs/design.md)。ADR-0022 取代旧 Build 发布、完整配对和全局非公共符号共享规则。历史文档不覆盖当前设计。

客户端只选择目标空间、上传文件和可选版本。不要重新引入 Build/Manifest/Sealed，也不要要求本地 PE/PDB 配对。公共空间拒绝 DMP。所有 API 为 v3，Canonical 为 2.0。

改符号检索时同时检查候选、物化、Symbolicator 来源、缓存和自动重分析范围。文件名和版本不是身份。不同 Workspace 的非公共文件不得互补；可见同身份不同内容必须报冲突。

保持 Occurrence、DumpBlob、AnalysisRun、Current 和 latest attempt 的区别。版本编辑只改 Occurrence 标签及审计。分析输入固定，历史结果不变，任务回执和执行代次继续保护 Current。

修改后运行对应 Rust、Python、契约和前端检查。真实文件、PostgreSQL、存储及 Symbolicator 的本地验收与目标部署结果分别记录。不要用假解析器或模拟页面证明真实端到端通过。

数据库重置只针对明确枚举的 Crash-Cap 项目资源，先备份数据与配置并保留旧镜像。回退恢复整套旧环境，不执行新库反向迁移。不要推送未授权的 Git 变更。
