> **实现与评审请以 [docs/design.md](docs/design.md) 为准。** 本文是历史蓝图，正文不再作为实现依据。契约见 `contracts/`。

# 一、**Core + WebPlatform linux部署 windows应用崩溃解析平台**

- **Core**：负责“这个 DMP 到底发生了什么”，输出稳定、可复现的分析结果。
- **WebPlatform**：负责“文件如何进入、任务如何运行、结果如何检索和展示”。

但如果物理部署时也只拆成两个大服务，会出现几个问题：

1. Web 服务需要直接处理几十 MB 到数 GB 的 DMP/PDB，容易阻塞或 OOM。
2. 符号文件下载、缓存和解析具有独立的资源模型，不适合和普通 API 混在一起。
3. DMP、PDB、PE 都是不可信二进制输入，解析器应在隔离 Worker 中执行。
4. Core 的分析结果要可复现，因此不能完全依赖某个长期运行、状态不透明的 Web 服务。
5. Crash、Hang、Native C++、.NET、内核 Dump 实际是不同分析路径，不应全部塞进一个解析流程。

因此我建议：

> **逻辑上保留 Core + WebPlatform；物理上拆成控制面、文件面、任务面、解析面、符号面、查询展示面，以及可选 Windows 深度分析面。**

第一版明确聚焦：

> **Windows 原生 C/C++ 用户态 DMP，主要支持 x64，运行和解析平台全部部署在 Linux。**

.NET Dump、内核 Dump、完整堆内存和 WinDbg 扩展分析，作为后续独立能力。

---



# 二、一个必须先纠正的输入认知

你说平台可以提供：

- DMP
- PDB

对于简单符号化，这可能够用；但对于可靠的 Windows x64 栈展开，建议把正式输入契约定义成：

- DMP
- 精确匹配的 PDB
- 精确匹配的 EXE/DLL
- 可选源码包
- 构建清单 `build-manifest.json`

原因是：

- PDB 主要负责把地址解析为函数、文件和行号。
- Windows x64 栈展开需要 PE 文件里的 `.pdata/.xdata` unwind 信息。
- PDB 和 EXE/DLL 必须来自同一次构建，不能仅通过文件名或版本号猜测匹配关系。

Windows PE 和 PDB 使用不同的内容标识：PE 有 Code ID，PDB 有 Debug ID；PDB Debug ID 通常由签名/GUID 和 age 构成。平台应按这些标识精确匹配，而不是按 `app.pdb` 这个文件名匹配。([Microsoft Learn](https://learn.microsoft.com/en-us/cpp/build/exception-handling-x64?view=msvc-170&utm_source=chatgpt.com))

因此推荐上传形式为：

```text
build-package/
├── build-manifest.json
├── bin/
│   ├── app.exe
│   ├── engine.dll
│   └── network.dll
├── symbols/
│   ├── app.pdb
│   ├── engine.pdb
│   └── network.pdb
└── source-bundle.zip          # 可选
```

示例 `build-manifest.json`：

```json
{
  "product": "cloud-game-client",
  "version": "3.12.0",
  "channel": "production",
  "commit": "a81fa5e3...",
  "build_number": "20260818.1042",
  "architecture": "x86_64",
  "compiler": "msvc",
  "modules": [
    {
      "code_file": "app.exe",
      "debug_file": "app.pdb"
    },
    {
      "code_file": "engine.dll",
      "debug_file": "engine.pdb"
    }
  ]
}
```

平台解析文件后，再把真实的 `code_id`、`debug_id`、SHA-256 补入数据库。

另外，CI 应产出完整 PDB。不要把 `/DEBUG:FASTLINK` PDB 当作正式归档符号，因为它可能依赖构建机上散落的对象文件和中间 PDB；微软已经弃用 FASTLINK，并在 Visual Studio 2026 中移除该模式，正式归档应使用完整 PDB。([Microsoft Learn](https://learn.microsoft.com/en-us/cpp/build/reference/debug-generate-debug-info?view=msvc-170&utm_source=chatgpt.com))

---



# 三、推荐总体架构

```text
                         ┌───────────────────────┐
                         │ CI 构建流水线          │
                         │ PE / PDB / Manifest    │
                         └───────────┬───────────┘
                                     │
                                     v
┌──────────────┐             ┌───────────────┐
│ Browser / CLI│────────────>│ API Gateway   │
└──────────────┘             │ Auth / RBAC   │
                             └───────┬───────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
                 v                   v                   v
          ┌────────────┐      ┌────────────┐      ┌────────────┐
          │ PostgreSQL │      │ S3 / MinIO │      │ Job Queue  │
          │ 元数据/索引 │      │ DMP/PDB/PE │      │ Redis/MQ   │
          └────────────┘      └──────┬─────┘      └─────┬──────┘
                                     │                  │
                                     └────────┬─────────┘
                                              v
                              ┌────────────────────────┐
                              │ Linux Analysis Worker  │
                              │ rootless + sandbox     │
                              └───────────┬────────────┘
                                          │
                                          v
                               ┌──────────────────────┐
                               │ dmp-core             │
                               │                      │
                               │ 1. inspect           │
                               │ 2. match             │
                               │ 3. symbolicate       │
                               │ 4. normalize         │
                               │ 5. fingerprint       │
                               └───────┬───────┬──────┘
                                       │       │
                         ┌─────────────┘       └─────────────┐
                         v                                   v
               ┌──────────────────┐                ┌──────────────────┐
               │ rust-minidump    │                │ Symbolicator     │
               │ DMP原始解析/栈质量 │                │ PDB/PE符号化     │
               └──────────────────┘                └────────┬─────────┘
                                                           │
                                  ┌────────────────────────┼─────────────┐
                                  v                        v             v
                           私有符号仓库             Microsoft符号源    本地缓存

                                      可选
                                       │
                                       v
                           ┌──────────────────────┐
                           │ Windows CDB Worker   │
                           │ 深度内存/.NET/内核分析 │
                           └──────────────────────┘
```

推荐原则是：

> **Symbolicator 和 rust-minidump 是 Core 的内部依赖，不是平台对外的数据契约。**

平台最终只暴露你自己定义的规范化 JSON。以后更换 Symbolicator 版本、调整栈展开实现或者增加 Windows Worker，都不会破坏 WebPlatform。

---



# 四、Core 应当如何设计



## 4.1 Core 不建议一开始做成常驻 HTTP 服务

第一版建议把 Core 实现成：

- 一个 Rust CLI；
- 一个固定版本 OCI/Docker 镜像；
- 输入为本地暂存文件和分析参数；
- 输出为版本化 JSON。

例如：

```bash
dmp-core inspect \
  --dump /work/input.dmp \
  --output /work/inspect.json

dmp-core analyze \
  --dump /work/input.dmp \
  --project cloud-game-client \
  --symbolicator http://symbolicator:3021 \
  --output /work/result.json
```

相比直接做 Core HTTP 服务，这样有几个优势：

- 每个任务可以启动独立沙箱。
- 更容易限制 CPU、内存、文件大小和运行时间。
- 输入输出明确，容易做回归测试。
- Core 镜像 digest 可以写入分析记录，确保结果可复现。
- Worker 可以对进程崩溃、超时、OOM 做明确归类。

后续任务量很大时，再增加长驻 Worker 或内部 gRPC 接口。

---



## 4.2 Core 内部模块

建议拆成六个模块。

### 1. `dump-inspector`

职责：

- 判断是否为支持的用户态 Minidump。
- 提取 dump streams。
- 获取架构、操作系统、进程信息。
- 获取异常线程和异常代码。
- 获取模块列表。
- 获取所有线程上下文。
- 获取 Dump 类型、内存区域、句柄等可用信息。
- 判断是 crash dump、疑似 hang dump，还是未知类型。
- 识别损坏、截断或不完整 DMP。

用户态 Minidump 本身是“尽力而为”的格式，具体能分析出多少内容取决于生成 Dump 时选取了哪些 `MINIDUMP_TYPE` 标志；普通 Minidump 可以包含线程栈，而 Full Memory Dump 会包含大量进程内存，文件可能非常大。([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/debug/minidump-files?utm_source=chatgpt.com))

建议用 Rust 的 `minidump` / `minidump-processor` 生态实现这一层。`minidump-stackwalk` 已支持机器可读 JSON，而 `minidump-processor` 的 JSON 模式以兼容性为目标，但字段应视为可选，因为 DMP 本身可能缺失对应数据。([GitHub](https://github.com/rust-minidump/rust-minidump))

---



### 2. `artifact-matcher`

职责是把 Dump 中的模块和符号仓库中的构建产物匹配起来。

对于每个模块记录：

```json
{
  "code_file": "app.exe",
  "code_id": "67A1B92301F000",
  "debug_file": "app.pdb",
  "debug_id": "B0C27C20A4704C4FA6F2B706D29F7E031",
  "image_base": "0x00007ff712340000",
  "image_size": 2031616,
  "status": "matched"
}
```

状态至少包括：

```text
matched
missing_pe
missing_pdb
pdb_mismatch
pe_mismatch
corrupted
system_symbol_pending
unsupported
```

必须遵守：

- 不根据文件名自动判定匹配。
- 不根据产品版本自动判定匹配。
- 不因为某个版本只有一个 PDB 就强行使用。
- 错误 PDB 要明确报错，不能静默解析成看似合理的栈。
- 同一个 `3.12.0` 版本允许存在多个重新构建结果。

平台的“版本”用于产品展示；真正决定符号匹配的是模块级 `code_id/debug_id`。

---



### 3. `symbolication-adapter`

建议把 Sentry Symbolicator 作为主要符号化引擎。

Symbolicator 可以独立运行，提供 Minidump 处理和原生栈符号化接口，可以解析函数名、文件、行号和源码上下文，也支持配置 HTTP、S3、GCS 等符号来源及多种符号服务器布局。([Sentry](https://getsentry.github.io/symbolicator/))

Core 不应把 Symbolicator 原始返回值直接存成最终业务结构，而应执行：

```text
Symbolicator response
        +
rust-minidump raw metadata
        +
平台 build/symbol metadata
        ↓
Canonical Analysis Result
```

尤其要注意：Symbolicator 的请求状态本身是临时状态，不能把 Symbolicator 返回的 request ID 当成平台的持久任务 ID。平台必须自己维护任务状态，并能在 Symbolicator 重启或请求丢失时重新提交。([Sentry](https://getsentry.github.io/symbolicator/api/response/?utm_source=chatgpt.com))

---



### 4. `stack-quality-evaluator`

除了输出调用栈，还必须告诉用户：

> 这条栈到底有多可信。

每个 frame 应记录 unwind trust：

```text
context
cfi
frame_pointer
scan
unknown
```

一般可以认为：

```text
context / cfi > frame_pointer > scan
```

`scan` 通常只是从栈内存中猜测一个可能的返回地址，不应与基于寄存器上下文或 unwind 信息得到的帧同等看待。rust-minidump 本身也会输出这些 frame trust 信息。([Docs.rs](https://docs.rs/minidump-processor))

可以计算三个质量指标：

```text
symbol_coverage
  = 已符号化业务帧数 / 可识别业务帧数

unwind_reliability
  = Σ frame_trust_weight / frame_count

artifact_completeness
  = 精确匹配的业务模块数 / DMP中的业务模块数
```

例如：

```text
context       1.00
cfi           1.00
frame_pointer 0.75
scan          0.20
unknown       0.00
```

综合评分可以是：

```text
quality_score =
    0.45 * symbol_coverage
  + 0.35 * unwind_reliability
  + 0.20 * artifact_completeness
```

UI 上不要只展示“A/B/C”，还应展示扣分原因：

```text
分析质量：B，82分

- app.exe 精确匹配
- engine.dll 缺少 PE，部分 x64 栈无法可靠展开
- 4 个帧通过 stack scan 推测
- 第三方 video_sdk.dll 缺少 PDB
```

---



### 5. `normalizer`

它负责把不同解析器输出统一成平台的稳定数据结构。

建议 Canonical JSON：

```json
{
  "schema_version": "1.0",
  "analysis_id": "an_01J...",
  "engine": {
    "core_version": "1.0.0",
    "core_image_digest": "sha256:...",
    "symbolicator_version": "...",
    "grouping_version": "group-v1"
  },
  "dump": {
    "dump_id": "dmp_01J...",
    "sha256": "...",
    "kind": "user_minidump",
    "size": 48230481,
    "capture_profile": "rich-crash"
  },
  "process": {
    "pid": 1234,
    "architecture": "x86_64",
    "os": "Windows",
    "os_version": "10.0.26100",
    "uptime_seconds": 2419
  },
  "crash": {
    "type": "crash",
    "thread_id": 6228,
    "exception_code": "0xc0000005",
    "exception_name": "EXCEPTION_ACCESS_VIOLATION",
    "access_type": "read",
    "address": "0x0000000000000018",
    "fault_module": "engine.dll"
  },
  "threads": [
    {
      "id": 6228,
      "name": "RenderThread",
      "is_crashing": true,
      "frames": [
        {
          "index": 0,
          "instruction_addr": "0x00007ff7...",
          "module": "engine.dll",
          "module_debug_id": "...",
          "relative_addr": "0x192a0",
          "function": "Renderer::SubmitFrame",
          "function_offset": 48,
          "file": "renderer.cpp",
          "line": 437,
          "trust": "context",
          "in_app": true
        }
      ]
    }
  ],
  "modules": [],
  "quality": {
    "score": 0.82,
    "symbol_coverage": 0.91,
    "unwind_reliability": 0.85,
    "artifact_completeness": 0.67,
    "warnings": []
  },
  "fingerprints": {
    "exact": "...",
    "family": "...",
    "algorithm": "group-v1"
  }
}
```

注意：

- 地址统一存十六进制字符串，避免 JavaScript 大整数精度问题。
- 原始地址和模块相对地址都要保存。
- 原始函数名与归一化函数名都要保存。
- Raw Symbolicator JSON、Raw rust-minidump JSON 单独保存，不和业务 Schema 混合。
- Schema 只能向后兼容扩展，字段不可随意改名。

---



### 6. `fingerprint-and-cluster`

这是平台能否真正帮助排查问题的关键，而不是单纯“展示一条栈”。

应同时维护两类指纹。

#### 精确指纹 Exact Fingerprint

用于判断：

> 同一个构建中的相同崩溃。

可采用：

```text
product
+ exception_code
+ access_type
+ fault_module.debug_id
+ top 5 reliable in-app frames
```

Frame Token：

```text
module_debug_id
+ normalized_function
+ relative_instruction_bucket
```

例如：

```python
exact_fingerprint = sha256(
    product
    + exception_code
    + access_type
    + fault_module_debug_id
    + frame_token_0
    + frame_token_1
    + frame_token_2
    + frame_token_3
    + frame_token_4
)
```



#### 家族指纹 Family Fingerprint

用于判断：

> 不同版本、重新编译、少量异步调用差异下，是否属于同一类问题。

它应去掉：

- Debug ID。
- 绝对地址。
- 行号。
- 函数偏移。
- 编译器生成的无意义编号。
- 一部分公共异步包装层。

保留：

- 异常类别。
- 业务模块逻辑名。
- 归一化函数序列。
- 关键调用关系。

例如：

```text
EXCEPTION_ACCESS_VIOLATION:read
engine!Renderer::SubmitFrame
engine!RenderLoop::Tick
app!GameSession::Run
```

---



# 五、崩溃聚类不能只看“栈顶函数”

你之前提到“顶层函数相似但异步细节略有差异”，这类场景不能直接用：

```text
exception_code + frame[0].function
```

因为常见栈顶可能是：

```text
ntdll!RtlReportFatalFailure
ucrtbase!abort
vcruntime!terminate
kernelbase!RaiseException
std::thread::_Invoke
asio::detail::executor_function
```

这些函数区分度很低。

建议聚类流程如下。

## 第一阶段：确定有效业务栈

依次过滤：

1. 操作系统入口和异常转发帧。
2. CRT、标准库、协程、线程池公共包装。
3. 纯日志、assert、abort 包装。
4. unwind trust 为 `scan` 且无法被上下文佐证的帧。
5. 重复的 inline/physical frame。

然后找到第一个高可信的业务帧。

## 第二阶段：构造序列

例如原栈：

```text
ntdll!RtlRaiseException
kernelbase!RaiseException
ucrtbase!abort
app!CrashHandler::Abort
engine!Renderer::SubmitFrame
engine!RenderLoop::Tick
task!ThreadPool::Invoke
```

归一化后：

```text
engine!Renderer::SubmitFrame
engine!RenderLoop::Tick
```



## 第三阶段：保守模糊匹配

对两个 Stack Sequence 计算：

```text
similarity =
    0.50 * weighted_sequence_similarity
  + 0.25 * function_jaccard
  + 0.15 * exception_similarity
  + 0.10 * module_similarity
```

Frame 权重按深度衰减：

```text
frame 0: 1.00
frame 1: 0.80
frame 2: 0.64
frame 3: 0.51
...
```

同时乘以 trust 权重。

建议：

- 高于 0.90：自动合并。
- 0.75～0.90：标记候选，由人工确认。
- 低于 0.75：不自动合并。

阈值必须通过你的历史 DMP 调整，不能直接照搬固定值。

每次自动合并都保存证据：

```json
{
  "decision": "auto_merge",
  "similarity": 0.934,
  "matched_frames": [
    "Renderer::SubmitFrame",
    "RenderLoop::Tick"
  ],
  "different_frames": [
    "ThreadPool::Invoke",
    "CoroutineExecutor::Resume"
  ],
  "algorithm": "group-v2"
}
```

这样以后算法升级时，可以重新聚类，也能解释“为什么这两个 Dump 被归在一起”。

---



# 六、Hang Dump 应作为单独模型

Crash 通常有异常线程；Hang 通常没有明确异常线程。因此不能复用同一种 fingerprint。

Hang 分析建议输出：

- 所有线程的栈。
- 线程名。
- 持续等待模式。
- 可能的主线程、渲染线程、网络线程。
- Wait、Sleep、Join、锁等待、消息循环、同步 I/O 等分类。
- 多次采样间保持不变的调用栈。
- 可疑线程之间的等待关系。

Hang 指纹建议采用“线程签名多重集合”：

```text
MainThread:
  app!MainLoop::WaitForFrame
  engine!Renderer::Present

RenderThread:
  kernelbase!WaitForSingleObject
  engine!Fence::Wait

NetworkThread x 4:
  ws2_32!recv
  network!Socket::Read
```

生成：

```text
process_hang_signature = sort([
  "MainThread:MainLoop::WaitForFrame>Renderer::Present",
  "RenderThread:Fence::Wait",
  "NetworkThread:Socket::Read x4"
])
```

更可靠的 Hang 采集方式是连续生成 2～3 个间隔采样的 Dump：

```text
hang-001.dmp
hang-002.dmp
hang-003.dmp
```

平台比较同一线程在多个采样中的调用栈：

- 一直停在同一锁等待：高度可疑。
- 调用栈持续变化：线程可能仍在正常工作。
- 主线程固定等待某个工作线程：重点分析工作线程。
- 多个线程形成稳定等待链：疑似死锁。

但要注意：

> 仅凭普通栈并不总能证明锁的所有者或完整死锁链。

需要句柄、锁对象、内存和运行时内部数据时，通常要依靠更丰富的 Dump，甚至 Windows CDB/WinDbg 深度分析。

---



# 七、解析引擎的辩证选择


| 方案                        | Linux 原生 | PDB/PE  | 栈展开      | 深度内存分析 | 建议                     |
| ------------------------- | -------- | ------- | -------- | ------ | ---------------------- |
| Sentry Symbolicator       | 是        | 强       | 强        | 较弱     | 主符号化引擎                 |
| rust-minidump             | 是        | 需结合符号来源 | 强，且元数据透明 | 较弱     | 原始解析与质量评估              |
| 完整 Sentry 平台              | 是        | 强       | 强        | 较弱     | 除非需要完整 Sentry 工作流，否则过重 |
| Windows CDB/WinDbg Worker | 否        | 最强      | 最强       | 强      | 可选深度分析                 |
| 自研 PDB + unwind 解析器       | 是        | 可做      | 工程风险很高   | 取决于投入  | 第一版不建议                 |
| Breakpad `.sym` 路线        | 是        | 需要预转换   | 成熟       | 较弱     | 有跨平台 Crashpad 体系时适用    |




## 推荐组合

```text
Symbolicator
  负责：PDB、PE、符号服务器、函数/行号/源码上下文

rust-minidump
  负责：DMP stream、线程、异常、原始栈、frame trust、诊断元数据

dmp-core
  负责：合并、校验、归一化、质量评分、fingerprint、平台稳定Schema
```

Symbolicator 会缓存原始调试文件以及派生的符号缓存。需要注意，它的官方生产级共享缓存支持有限，文档中共享缓存主要面向 GCS；如果你的原始文件放在 S3/MinIO，不代表 Symbolicator 多实例缓存也能直接共享到 MinIO。更实际的做法是每个 Symbolicator 实例挂持久化本地 NVMe/PVC，并通过一致性路由尽量提高缓存局部性。([Sentry](https://getsentry.github.io/symbolicator/advanced/shared-cache/?utm_source=chatgpt.com))

---



# 八、符号仓库设计

符号仓库不要简单设计成：

```text
/project/version/app.pdb
```

因为同一版本可能被重复构建，文件名也可能相同。

建议分两层。

## 8.1 原始构建产物仓库

存放用户或 CI 上传的原始文件：

```text
raw-builds/
  {tenant_id}/
    {build_id}/
      manifest.json
      files/
        {sha256}
```

数据库保存：

```text
logical_name: app.pdb
sha256: ...
object_key: raw-builds/.../files/...
```



## 8.2 Symbolicator 符号仓库

由 `symsorter` 或自定义 ingest 程序把 PDB/PE 排列成 Symbolicator 支持的统一符号服务器布局。

流程：

```text
上传 PE/PDB
   ↓
读取 Code ID / Debug ID
   ↓
校验 PE 与 PDB
   ↓
计算 SHA-256
   ↓
写入原始对象仓库
   ↓
生成 Symbolicator 兼容目录
   ↓
登记 symbol inventory
```

Symbolicator 支持多种符号源和符号服务器布局，统一布局适合作为新平台内部规范。它也支持源码 bundle，从而在符号化结果中显示源码上下文。([Sentry](https://getsentry.github.io/symbolicator/advanced/symbol-server-compatibility/?utm_source=chatgpt.com))

建议符号来源优先级：

```text
1. 当前项目私有符号
2. 公司公共 SDK 符号
3. 第三方受信符号仓库
4. Microsoft 公共符号
```

不能把用户在请求里提交的任意 URL 直接转交给 Symbolicator。符号源必须由管理员预配置和 allowlist，避免 SSRF、内网探测和恶意大文件下载。Symbolicator 本身提供保留地址访问限制等安全配置；解析服务仍应在网络层限制出口。([Sentry](https://getsentry.github.io/symbolicator/?utm_source=chatgpt.com))

---



# 九、WebPlatform 详细设计

WebPlatform 应负责：

```text
认证与权限
项目管理
构建管理
大文件上传
任务编排
状态机
结果持久化
搜索与趋势
Crash Group管理
重新分析
符号缺失管理
前端展示
审计
```

不负责：

```text
直接解析DMP
直接解析PDB
直接执行调试器
在API进程内下载符号
在请求线程中生成完整报告
```

---



## 9.1 上传流程

不要让 DMP 经过 FastAPI/Nginx 应用进程中转。

推荐：

```text
POST /uploads/init
       ↓
返回 S3/MinIO presigned URL
       ↓
客户端直接上传对象存储
       ↓
POST /uploads/{id}/complete
       ↓
服务端校验对象大小/hash
       ↓
创建分析任务
```

对于大文件，支持 multipart upload。

上传状态：

```text
INITIALIZED
UPLOADING
UPLOADED
VERIFYING
QUARANTINED
ACCEPTED
REJECTED
```

每个上传记录：

```text
tenant_id
project_id
object_key
original_filename
content_length
sha256
upload_user
upload_time
file_kind
verification_status
```

---



## 9.2 任务状态机

建议状态机：

```text
UPLOADED
    ↓
VALIDATING
    ↓
INSPECTED
    ↓
MATCHING_SYMBOLS
    ├── WAITING_FOR_SYMBOLS
    └── SYMBOLS_READY
             ↓
QUEUED
    ↓
ANALYZING
    ↓
NORMALIZING
    ↓
GROUPING
    ↓
COMPLETE
```

异常终态：

```text
PARTIAL
FAILED
REJECTED
CANCELLED
TIMEOUT
OOM
```

`PARTIAL` 是正常业务状态，不要将“缺失某个第三方 PDB”一律视为失败。

例如：

```text
PARTIAL

已解析异常线程和 18 个调用帧；
app.exe 与 engine.dll 符号完整；
third_party_codec.dll 缺少 PDB；
2 个系统模块符号下载失败。
```

---



## 9.3 重新分析机制

以下变化都应允许触发 reprocess：

- 后续补传 PDB。
- 后续补传 EXE/DLL。
- Core 升级。
- Symbolicator 升级。
- grouping 算法升级。
- 修改业务模块识别规则。
- 修改函数归一化规则。
- 新增源码 bundle。

一个 DMP 对应多个不可变的 `analysis_run`：

```text
dump
 ├── analysis_run_v1
 ├── analysis_run_v2
 └── analysis_run_v3 ← current
```

不要覆盖旧分析结果，这样才能：

- 比较解析器升级差异。
- 回滚。
- 审计。
- 对历史数据重新聚类。
- 判断某个版本改变是否造成分组漂移。

建议幂等键：

```text
sha256(
    dump_sha256
  + symbol_inventory_version
  + core_image_digest
  + symbolicator_version
  + normalization_version
  + grouping_version
)
```

相同幂等键不重复分析。

---



# 十、数据库模型

推荐 PostgreSQL 作为第一阶段主数据库。

## `projects`

```text
id
tenant_id
name
platform
default_architecture
retention_policy
created_at
```



## `builds`

```text
id
project_id
version
build_number
commit_sha
channel
architecture
toolchain
manifest_object_key
created_at
```

注意：

```text
UNIQUE(project_id, version)
```

不够，应使用平台生成的 build ID；同版本允许多次构建。

## `artifacts`

```text
id
build_id
kind                 # PE / PDB / SOURCE_BUNDLE
logical_name
sha256
size
object_key
code_id
debug_id
verification_status
created_at
```



## `dumps`

```text
id
project_id
build_id             # 允许为空，由系统推断
sha256
size
object_key
dump_kind
architecture
capture_time
upload_user
status
created_at
```



## `analysis_runs`

```text
id
dump_id
core_version
core_image_digest
symbolicator_version
schema_version
grouping_version
status
quality_score
result_object_key
started_at
finished_at
error_code
error_detail
```



## `analysis_summaries`

保存查询常用字段：

```text
analysis_run_id
exception_code
exception_name
access_type
crash_address
crashing_thread_id
fault_module
top_function
top_source_file
top_source_line
symbol_coverage
unwind_reliability
exact_fingerprint
family_fingerprint
```



## `crash_groups`

```text
id
project_id
group_type              # exact / family / hang
fingerprint
representative_run_id
title
status                   # open / investigating / fixed / ignored
first_seen
last_seen
occurrence_count
first_build_id
last_build_id
owner
issue_url
```



## `group_occurrences`

```text
group_id
dump_id
analysis_run_id
similarity
grouping_evidence_json
created_at
```



## `missing_symbols`

```text
project_id
code_file
code_id
debug_file
debug_id
first_seen
last_seen
affected_dump_count
status
```

完整线程、frame 和模块数据不一定要全部拆成关系表。

推荐：

- PostgreSQL：摘要、分组、顶部 frame、索引字段。
- S3/MinIO：完整规范化 JSON、原始引擎输出。
- 后续数据量很大：增加 ClickHouse 做趋势分析。
- 只有需要复杂全文搜索时才增加 OpenSearch。

第一版不要同时引入 PostgreSQL、ClickHouse、OpenSearch 三套系统。

---



# 十一、Web API 蓝图



## 项目和构建

```http
POST /api/v1/projects
GET  /api/v1/projects/{project_id}

POST /api/v1/projects/{project_id}/builds
GET  /api/v1/projects/{project_id}/builds
GET  /api/v1/builds/{build_id}
```



## 构建产物上传

```http
POST /api/v1/builds/{build_id}/artifacts/uploads:init
POST /api/v1/uploads/{upload_id}/complete
GET  /api/v1/builds/{build_id}/symbols
```



## DMP 上传和分析

```http
POST /api/v1/projects/{project_id}/dumps/uploads:init
POST /api/v1/uploads/{upload_id}/complete

GET  /api/v1/dumps/{dump_id}
GET  /api/v1/dumps/{dump_id}/analysis
GET  /api/v1/dumps/{dump_id}/threads
GET  /api/v1/dumps/{dump_id}/modules

POST /api/v1/dumps/{dump_id}/reprocess
```



## Crash Group

```http
GET   /api/v1/projects/{project_id}/groups
GET   /api/v1/groups/{group_id}
PATCH /api/v1/groups/{group_id}
POST  /api/v1/groups/{group_id}/merge
POST  /api/v1/groups/{group_id}/split
```



## Symbol Health

```http
GET /api/v1/projects/{project_id}/symbols/health
GET /api/v1/projects/{project_id}/symbols/missing
POST /api/v1/projects/{project_id}/symbols/reindex
```



## 状态推送

前端不必持续高频轮询，可以使用：

- SSE：首选，简单且符合单向状态推送。
- WebSocket：只有需要双向交互时再使用。

---



# 十二、前端页面



## 1. 项目概览

展示：

- 最近崩溃数。
- 新增 Crash Group。
- 按版本趋势。
- Top Crash Groups。
- 符号完整率。
- 解析失败率。
- 平均分析时长。



## 2. Build 页面

展示：

- 版本、commit、build number。
- PE/PDB 数量。
- 精确匹配状态。
- FASTLINK 或异常 PDB 警告。
- 缺失模块。
- 源码包状态。
- 当前版本影响的 Crash Groups。



## 3. Dump Report 页面

建议布局：

```text
┌─────────────────────────────────────────────┐
│ EXCEPTION_ACCESS_VIOLATION / Read 0x18       │
│ engine.dll!Renderer::SubmitFrame             │
│ Build 3.12.0 / x64 / Quality B 82            │
└─────────────────────────────────────────────┘

[Overview] [Crash Stack] [All Threads] [Modules]
[Memory] [Raw Metadata] [Similar Crashes]
```

Crash Stack 表格：

```text
#  Module       Function                   Source               Trust
0  engine.dll   Renderer::SubmitFrame      renderer.cpp:437     context
1  engine.dll   RenderLoop::Tick           render_loop.cpp:88   cfi
2  app.exe      GameSession::Run           game_session.cpp:211 cfi
3  kernel32     BaseThreadInitThunk         -                    cfi
```

对每个 frame 提供：

- 原始地址。
- 模块相对地址。
- Debug ID。
- 函数偏移。
- inline 信息。
- unwind trust。
- 源码上下文。
- “复制 WinDbg 风格栈”。
- “按此函数搜索历史 Dump”。



## 4. Symbol Health 页面

这是非常重要但容易被忽略的页面：

```text
app.exe                   matched       328 dumps
engine.dll                matched       327 dumps
video_sdk.dll             missing PDB    76 dumps
third_party_audio.dll     PDB mismatch   19 dumps
ntdll.dll                 remote ready  328 dumps
```

支持点击某个 missing symbol 查看受影响 Dump。

## 5. Crash Group 页面

展示：

- 代表性调用栈。
- 首次/最近出现时间。
- 按构建版本分布。
- 发生次数趋势。
- Exact Group 与 Family Group 的关系。
- 组内栈差异。
- 新增、恢复、回归状态。
- 责任人和外部 Issue 链接。

---



# 十三、Dump 采集策略也应纳入平台规范

解析质量很大程度取决于客户端如何采集 Dump。

可以定义几种 capture profile。

## Light Crash

适合大量自动上报：

```text
线程上下文
线程栈
模块列表
异常信息
线程附加信息
卸载模块信息
内存区域描述
```



## Rich Crash

额外包含：

```text
句柄信息
间接引用内存
更多进程和线程数据
```



## Hang

倾向包含：

```text
所有线程
句柄
内存区域
必要的进程内存
连续多次采样
```



## Full Memory

仅用于少量深度分析：

```text
整个可访问用户态进程内存
```

Full Memory Dump 可能包含访问令牌、业务数据、用户输入、密钥和其他敏感内容，而且体积可能非常大。即使使用减少可选数据的 Dump 标志，微软也明确指出这不能保证排除所有私密信息，因此必须配套严格权限和短保留期。([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/minidumpapiset/ne-minidumpapiset-minidump_type))

客户端生成 DMP 时，最好由独立进程或专门的 crash handler 执行 Dump 写入，避免在已经损坏的崩溃进程上下文中继续执行复杂逻辑。微软对 `MiniDumpWriteDump` 也建议尽可能从单独进程调用。([Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/minidumpapiset/nf-minidumpapiset-minidumpwritedump?utm_source=chatgpt.com))

---



# 十四、安全设计

DMP、PDB、PE 以及压缩包均应视为恶意输入。

## Worker 隔离

每个分析任务：

```text
非 root 用户
只读根文件系统
独立临时目录
禁止 hostPath
限制 CPU
限制内存
限制临时磁盘
限制进程数
限制执行时长
seccomp / AppArmor
默认禁止出网
```

只有 Symbolicator 可以访问预配置符号源；普通 Core Worker 不应直接访问互联网。

## 文件限制

至少检查：

```text
文件大小
实际格式头
压缩层数
解压后总大小
文件数量
路径穿越
符号文件声明大小与实际大小
重复对象
异常解析耗时
```

避免：

```text
ZIP bomb
路径穿越
构造型超大 PDB
恶意损坏 DMP
大量模块导致资源耗尽
```



## 数据保护

- DMP、PDB、源码 bundle 加密存储。
- 按项目和租户隔离对象路径。
- 临时文件任务结束后立即清理。
- Full Memory Dump 设置短保留期。
- 下载 DMP 需要更高权限。
- 分析报告权限和原始 Dump 下载权限分离。
- 审计上传、下载、查看源码和删除操作。
- 日志中禁止打印原始内存、完整路径、令牌和源码内容。

---



# 十五、可选 Windows 深度分析面

Linux 原生流程能很好地覆盖：

- 原生 C/C++ 用户态 crash。
- 调用栈。
- 异常代码。
- 模块和符号状态。
- 基本 Hang 线程分析。
- 聚类与版本趋势。

但不应宣传为“完全替代 WinDbg”。

以下场景建议进入可选 Windows Worker：

- `!analyze -v` 级别的兼容输出。
- 复杂堆损坏。
- 句柄和同步对象深度分析。
- Windows Runtime 内部对象。
- .NET SOS 分析。
- 内核 Dump。
- 特定 WinDbg 扩展。
- 需要完整变量、局部对象和内存表达式求值。

CDB/WinDbg 使用 Windows 调试引擎，可以进行比普通符号化更深入的内存、变量和扩展命令分析；.NET Dump 通常还需要匹配 CLR 的 SOS、DAC 等组件。因此 .NET 和内核分析应作为单独引擎路径，而不是强行塞进第一版 Linux Native Core。([Microsoft Learn](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/debugging-using-cdb-and-ntsd?utm_source=chatgpt.com))

可选路径：

```text
Linux WebPlatform
        ↓
任务标记 needs_deep_analysis
        ↓
Windows VM Worker
        ↓
CDB 脚本化分析
        ↓
生成结构化结果
        ↓
回传 Linux 平台
```

Windows Worker 应在隔离 VM 中运行，不建议为了省机器而直接在主业务 Windows 服务器执行不可信 Dump 分析。

---



# 十六、推荐技术栈

结合开发复杂度、后期维护和你的 Python/C++ 背景，推荐：

## Core

```text
Rust
rust-minidump
Symbolicator adapter
symbolic 相关库
Serde JSON
Tokio
```

Core 使用 Rust，而不是 Python，主要因为：

- 有成熟的 minidump 生态。
- 处理二进制格式更合适。
- 单文件 CLI 易部署。
- 内存安全性优于自研 C/C++ parser。
- 性能和资源使用更稳定。



## Web Backend

```text
Python 3.13+
FastAPI
Pydantic
SQLAlchemy
Alembic
Celery 或 Dramatiq
Redis 或 RabbitMQ
```

推荐取舍：

- MVP 简化：FastAPI + Dramatiq + Redis。
- 生产任务复杂：FastAPI + Celery + RabbitMQ。
- Redis 仍可用于状态缓存和分布式锁。



## Storage

```text
PostgreSQL
MinIO / S3
Redis
```



## Frontend

```text
React
TypeScript
Vite
Ant Design 或 MUI
TanStack Query
TanStack Table / 虚拟列表
```



## Deployment

MVP Docker Compose：

```text
frontend
gateway
api
worker
symbolicator
postgres
redis
minio
```

生产 Kubernetes：

```text
api deployment
small-dump worker pool
large-dump worker pool
full-memory worker pool
symbolicator pool
persistent local symbol cache
postgres HA
external S3-compatible object store
RabbitMQ / Redis
```

不同大小 Dump 应进入不同队列，避免一个 8 GB Full Dump 阻塞大量 20 MB Crash Dump。

---



# 十七、推荐仓库结构

```text
dmp-platform/
├── core/
│   ├── Cargo.toml
│   ├── crates/
│   │   ├── dump-inspect/
│   │   ├── artifact-match/
│   │   ├── symbolicator-client/
│   │   ├── stack-normalize/
│   │   ├── quality-evaluator/
│   │   ├── fingerprint/
│   │   └── analysis-schema/
│   └── bins/
│       └── dmp-core/
│
├── platform/
│   ├── api/
│   │   ├── app/
│   │   ├── migrations/
│   │   └── tests/
│   ├── worker/
│   ├── frontend/
│   └── cli/
│
├── contracts/
│   ├── analysis-result-v1.schema.json
│   ├── build-manifest-v1.schema.json
│   └── task-message-v1.schema.json
│
├── fixtures/
│   ├── access-violation/
│   ├── cpp-exception/
│   ├── stack-overflow/
│   ├── missing-pdb/
│   ├── mismatched-pdb/
│   └── hang/
│
├── deploy/
│   ├── compose/
│   └── kubernetes/
│
└── docs/
    ├── architecture.md
    ├── capture-profiles.md
    ├── symbol-ingestion.md
    └── grouping-algorithm.md
```

Core 和 Platform 可以放在同一个 monorepo，但分别构建和发布。

---



# 十八、测试与验收标准

不要仅测试“接口返回 200”，必须建立一套 Golden Dump。

## Golden Dump 类型

至少包含：

```text
x64 空指针读
x64 空指针写
非法执行地址
C++ 未捕获异常
std::terminate
assert / abort
栈溢出
多线程崩溃
缺失 PDB
错误 PDB
缺失 EXE/DLL
损坏 DMP
截断 DMP
Release 优化构建
含 inline 函数
异步线程池调用
死锁/疑似 Hang
```

后续增加：

```text
x86
ARM64
不同 MSVC 版本
第三方 DLL
Full Memory Dump
```



## 与 WinDbg 对照

对每个 Golden Dump，保存：

- WinDbg/CDB 参考输出。
- 预期异常代码。
- 预期崩溃线程。
- 预期顶部业务帧。
- 预期模块 Code ID/Debug ID。
- 允许存在差异的帧。
- 预期质量警告。

验收不必要求文本逐字一致，而应要求：

```text
异常代码一致
崩溃线程一致
业务栈前 N 帧一致或等价
错误 PDB 被拒绝
缺失符号被明确标记
栈扫描帧不会被标成高可信
```



## 关键验收用例

1. 正确 DMP + 正确 PDB + 正确 PE：得到函数、文件、行号。
2. 正确 DMP + 错误 PDB：明确 `pdb_mismatch`，不能错误符号化。
3. 正确 DMP + PDB、缺少 PE：允许部分解析，但降低 x64 unwind 质量。
4. 后补传符号：受影响 Dump 可批量重新处理。
5. 同一 Dump 重复上传：按 SHA-256 去重。
6. API 服务重启：任务状态不丢失。
7. Symbolicator 重启：平台可重新提交，不依赖临时 request ID。
8. 解析器崩溃：不影响 API 和其他 Worker。
9. 超大 Full Dump：不会经过 API 内存，不阻塞普通队列。
10. 两个租户使用同名项目和同名 PDB：数据完全隔离。

---



# 十九、分阶段落地路线



## Phase 0：技术验证

目标不是先写 Web，而是确认 Linux 栈解析质量。

准备一批真实样本：

```text
20～50 个 DMP
对应的准确 PDB
对应的 EXE/DLL
WinDbg 参考结果
```

验证：

- Symbolicator 对 PDB/PE 的解析质量。
- rust-minidump 的线程、异常、frame trust。
- 优化构建下调用栈差异。
- 没有 PE 时的实际退化程度。
- 系统符号获取。
- 错误符号识别。
- Canonical JSON 是否足够表达结果。

Phase 0 完成后再冻结 `analysis-result-v1`。

## Phase 1：最小可用平台

仅支持：

```text
Native C++
Windows user-mode
x64
单项目或简单多项目
DMP + PE + PDB
Crash Stack
全部线程
模块/符号状态
手动上传
Docker Compose
```

这一阶段先不做：

```text
模糊聚类
.NET
内核 Dump
复杂 Heap
Windows Worker
OpenSearch
Kubernetes
```



## Phase 2：符号和构建体系

增加：

- CI 自动上传。
- Build Manifest。
- Symbol Health。
- PDB/PE 精确校验。
- Source Bundle。
- 后补符号重新分析。
- 多租户和 RBAC。



## Phase 3：Crash Group 与趋势

增加：

- Exact Fingerprint。
- Family Fingerprint。
- 跨版本归类。
- 手动 merge/split。
- 趋势图。
- 回归检测。
- 与缺陷系统关联。



## Phase 4：Hang 与深度分析

增加：

- 多 Dump Hang Session。
- 线程签名多重集合。
- 稳定栈识别。
- Windows CDB Worker。
- .NET 独立路径。
- 内核 Dump 独立路径。

---



# 二十、最终推荐决策

建议把最终方案定为：

```text
逻辑架构：
Core + WebPlatform

物理架构：
API
Object Storage
PostgreSQL
Queue
Linux Analysis Worker
Symbolicator
Frontend
可选 Windows Deep Worker
```

核心技术决策：

1. **第一版只做原生 C/C++ 用户态 x64 DMP。**
2. **正式输入要求 DMP + 精确 PDB + 精确 EXE/DLL。**
3. **Symbolicator 作为主要符号化引擎。**
4. **rust-minidump 负责原始解析、线程信息和栈可信度。**
5. **自研 dmp-core 负责规范化、质量评分和聚类，而不是从零重写 PDB 解析器。**
6. **Core 第一版做成版本化 CLI/OCI 镜像，由隔离 Worker 调用。**
7. **Web API 不直接接收和解析大文件，使用对象存储预签名上传。**
8. **分析结果不可变并版本化，支持后补符号后重新分析。**
9. **同时建立 Exact Group 和跨版本 Family Group。**
10. **Hang 使用多线程、多采样模型，不与 Crash 强行共用一个 fingerprint。**
11. **.NET、内核 Dump、Heap 深度分析通过可选 Windows Worker 扩展。**
12. **平台必须展示解析质量和缺失符号，不能只输出一条看似完整的调用栈。**

其中最重要的架构思想是：

> **Core 的真正产品不是一段格式化调用栈，而是“具有证据、质量等级、版本信息和可解释分组依据的结构化事故报告”。**

这会让平台从一个简单的 DMP 在线查看器，演进为真正可用于版本质量分析、Crash 趋势跟踪、回归识别和问题闭环的工程系统。