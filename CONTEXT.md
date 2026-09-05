# Crash-Cap 领域模型

权威设计：[docs/design.md](docs/design.md)，决定：[ADR-0022](docs/adr/0022-upload-files-with-scoped-symbol-availability.md)。

产品入口是“选择空间、上传文件、附带可选版本”。Workspace 是使用范围，public 是公共符号范围，版本只是标签。没有 Build、Manifest 发布、Publication、Expected Artifact、Ready 或 Sealed。

Upload 是单文件提交和验收记录；CatalogFile 是不可变验证内容；ArtifactEntry 是空间归属和标签；CatalogPair 是按真实身份形成的 PE/PDB 内容组合。独立文件成功验收即可保存，配对可以跨批补齐。候选、物化、缓存来源和后台任务都必须尊重 Workspace + public 的范围。

DumpBlob 是 Workspace 对 DMP 字节的引用；Occurrence 是同空间同内容的逻辑崩溃；Submission 记录每次提交标签；Occurrence.version 是用户可编辑的当前标签。物理复用不扩大范围，也不增加同空间崩溃次数。

AnalysisDemand 是分析需求与有限重试；AnalysisRun 是不可变的分析输入和结果；CurrentDecision 决定是否替换当前报告。Latest attempt 可能失败而 Current 仍可用。符号补齐产生新结果，历史不变。Canonical 2.0 不含 Build 解析和版本标签。

本空间产物默认 owned，公共产物默认 dependency，人工分类优先，系统模块排除，无依据为 unknown。Exact Group 按可靠业务帧及精确身份形成，版本分布读取 Occurrence 当前标签。
