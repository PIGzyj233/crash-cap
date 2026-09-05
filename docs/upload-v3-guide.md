# 文件上传 v3：使用与维护

产品决策见 [ADR-0022](adr/0022-upload-files-with-scoped-symbol-availability.md)，当前协议以服务端 OpenAPI 和 [设计文档](design.md) 为准。本指南保留使用方式、回归场景和部署约束；每次执行产生的日志、截图和验收结果放在 Git 忽略的 `target/` 或外部记录系统中。

## 使用方式

```powershell
crashcap upload .\Release --workspace light-streamer --build-version 11.0.1.27
crashcap upload .\sdk.dll .\sdk.pdb --public --build-version 3.2
crashcap upload .\crash.dmp --workspace light-streamer --build-version 11.0.1.27
```

目标空间必须明确，版本可省略。目录递归发现 EXE、DLL、PDB、DMP。公共空间只接受产物和符号，DMP 必须属于一个 Workspace。CLI 与浏览器都可以只上传 PE 或 PDB；另一半可以之后上传。

上传验收和符号可用性是两件事：文件可以已经入库但仍等待另一半。文件验收失败不会撤销同批其他文件。符号冲突不通过文件名、版本或上传顺序消解。

浏览器 Workspace 上传页默认当前空间；平台上传页可选择空间或公共区域，整批版本可选。产物列表显示文件状态与符号状态，报告允许明确编辑 DMP 的当前版本。

## 功能边界

- 删除 Build、Manifest、Publication、Expected Artifact、Ready/Sealed、源码包与旧客户端运行路径。
- 分离不可变内容、空间归属、上传记录和可编辑版本标签；同一内容可以关联多个空间和版本。
- 每个消费 Workspace 只选择自身与公共文件，两侧都须满足范围规则；物理去重、物化和缓存不能扩大候选范围。
- 本空间产物默认 owned，公共产物默认 dependency，人工分类优先，系统模块排除，缺乏依据的模块为 unknown。
- 新 Canonical 2.0 删除 Build resolution，保留内部符号选择快照、输入身份、信任与冲突证据。DMP 版本不进入分析指纹。
- 保留不可变 Run、Current 保护、精确 Group、durable task intent、重试及 generation fencing。
- HTTP v3、CLI、浏览器、数据库、Worker 与 Core 同批部署；使用新库，不实施兼容或数据反向迁移。

## 验收矩阵

| 编号 | 场景 | 必须观察的结果 |
| --- | --- | --- |
| U3-01 | 无 Git/配置上传目录或文件 | 不创建 Build，逐文件提供回执 |
| U3-02 | PE 先传、PDB 后传及反向 | 首个文件验收成功，补齐后符号可用 |
| U3-03 | 文件名不同、身份匹配 | 自动配对，版本标签不参与匹配 |
| U3-04 | 两侧公共 | 两个 Workspace 均可使用 |
| U3-05 | 两侧同一 Workspace | 该空间可用，其他空间不可用 |
| U3-06 | 公共 PE + 本空间 PDB，以及反向 | 只对拥有私有半边的空间可用 |
| U3-07 | 两侧来自不同 Workspace | 不可配对；暖缓存也不能改变结果 |
| U3-08 | 同内容重传、改变版本或空间 | 复用内容，保留归属与来源，不越界 |
| U3-09 | 同身份不同有效内容 | 显式冲突，本空间不默认覆盖公共候选 |
| U3-10 | 损坏、哈希不符、FASTLINK | 单文件拒绝，其他成功文件保留 |
| U3-11 | 传输中断、Worker 重试 | 状态可恢复，无重复有效内容或副作用 |
| U3-12 | 无调试身份的有效 PE | 可保存，不能宣称完整符号可用 |
| U3-13 | 公共批次含 DMP | CLI/浏览器上传前提示，API 拒绝 |
| U3-14 | 同 DMP 重传不同版本 | 同一 Occurrence，旧非空标签保留，差异可见 |
| U3-15 | 空版本补充、明确编辑版本 | 列表/总览/Group 统计更新，不新增分析或 Occurrence |
| U3-16 | 默认分类、人工覆盖、系统模块 | 业务栈与分组使用正确分类，仅本空间受影响 |
| U3-17 | 后补符号 | 仅相关空间/身份产生新 Run，历史 Canonical 不变 |
| U3-18 | 错误或暂时退化的新分析 | 按 evidence-v1 保护已有有用 Current |
| U3-19 | 新部署 | 正式表与公开路由无旧 Build 生命周期，上传默认可用 |

每个结果记录输入文件哈希、上传 ID、文件/配对 ID、Workspace、Occurrence、Run、Current、服务镜像和客户端版本。上传 HTTP 成功不能替代字节验收、真实解析或浏览器验证。

## 验证层级

1. Rust、Python、契约、OpenAPI、前端测试和构建：验证实现和协议。
2. 独立 PostgreSQL 与对象存储：验证并发、幂等、物理复用和任务交接。
3. 本机 Compose + 真实 PE/PDB/DMP + 固定 Symbolicator：验证 CLI、浏览器、空间隔离、自动重分析和 Current。
4. 目标环境：独立记录部署、可达性、现场 UAT 与观察。未取得目标环境证据时标为 NOT_PROVEN，不借用本机结果。

## 部署和回退

重置前核对 Compose 项目、卷标签和占用者，保留数据库及对象/符号相关卷备份、运行配置所在位置、旧镜像身份。只有确认属于 Crash-Cap 且未被其他项目使用的资源可重置。

新版本以空库初始化。回退恢复完整旧镜像与对应数据备份，不对已经写入 v3 数据的库执行降级。真实文件与运行凭据只留在 Git 忽略的本地证据目录或外部受控目录。
