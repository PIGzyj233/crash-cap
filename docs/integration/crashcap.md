# crashcap 本地与 CI 发布指南

`crashcap` 把已经生成的 Windows x64 MSVC EXE/DLL 和完整 PDB 7.0 发布到
Crash-Cap，用于崩溃分析。它不会执行 MSBuild/CMake、克隆仓库、分发安装包，默认也
不会上传源码。GitHub/GitLab 只是可选的 Git 来源，发布不依赖仓库 API 或 CI Runner。

典型本地流程：

```text
本机完成 MSVC 编译
  -> crashcap init（首次）
  -> crashcap validate
  -> crashcap doctor
  -> crashcap publish --profile release
  -> crashcap-publication.json + 网页 Ready/Sealed
```

## 1. 安全和网络边界

当前平台匿名使用 HTTP，只允许受信任内网或 VPN。开发机必须同时访问：

- Crash-Cap API，例如 `http://crashcap.intranet.example/api/v1`；
- API 返回的对象存储预签名地址（通常是 S3 Gateway）。

API 地址不是凭据，但不应写入仓库内的 `crashcap.toml`。优先级依次为：

1. `--api-url`；
2. `CRASHCAP_API_URL`；
3. 用户配置 `%APPDATA%\Crash-Cap\config.toml`（Linux 为
   `$XDG_CONFIG_HOME/crash-cap/config.toml`）。

用户配置只有以下内容：

```toml
api_url = "http://crashcap.intranet.example/api/v1"
```

## 2. 获取并校验工具

从 Workspace 的“开发者接入”页下载：

```text
tools/crashcap/
├── SHA256SUMS
├── release.json
├── windows-x86_64/crashcap.exe
└── linux-x86_64/crashcap
```

Windows PowerShell：

```powershell
$binary = "tools/crashcap/windows-x86_64/crashcap.exe"
$entry = Get-Content "tools/crashcap/SHA256SUMS" |
  Where-Object { $_ -match "  windows-x86_64/crashcap\.exe$" }
if (@($entry).Count -ne 1) { throw "missing unique Windows checksum entry" }
$expected = ($entry -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $binary).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "crashcap.exe SHA-256 mismatch" }
& $binary --version
```

内部试点允许 `release.json.signing.status=unsigned-pilot`。正式推广前必须同时满足：

- Windows 文件 Authenticode 状态有效；
- `signing.status=authenticode-signed`；
- `windows_signed_sha256` 与 `SHA256SUMS` 一致；
- `certificate_thumbprint` 属于组织批准的证书。

工具不需要 Python、Rust 或 OpenSSL 运行时。

## 3. 首次初始化

先完成本地 Release 编译，再在仓库根目录执行：

```powershell
$env:CRASHCAP_API_URL = "http://crashcap.intranet.example/api/v1"
tools/crashcap/windows-x86_64/crashcap.exe init `
  --workspace "lightstreamer" `
  --artifact-root "deploy/bin" `
  --profile release
```

`init` 会解析已有 Workspace、扫描 EXE/DLL/PDB 配对并生成 `crashcap.toml`。如果扫描
到多个 EXE，必须用 `--entrypoint app.exe` 明确入口；存在其他模块时，先检查候选角色，
再用 `--accept-discovered-roles` 确认初始 `owned` 归类，并在配置中把第三方模块改为
`dependency`。Workspace 不存在时命令默认
失败；只有明确接受创建副作用时才传 `--create-workspace`。

生成的配置可以提交到 Git：

```toml
schema_version = 1
workspace = "lightstreamer"
product = "lightstreamer"

[profiles.release]
artifact_roots = ["deploy/bin"]
version = { source = "git-describe" }
channel = "local"
require_clean = false

[[profiles.release.modules]]
code = "lightstreamer.exe"
debug = "lightstreamer.pdb"
role = "entrypoint"

[[profiles.release.modules]]
code = "plugins/render.dll"
debug = "plugins/render.pdb"
role = "owned"
```

模块必须使用 artifact root 下的精确相对路径，不支持发布时通配符猜测。所有 Artifact
basename 大小写不敏感地唯一。路径不能绝对化、包含 `..`、越出仓库或经过符号链接。

版本只支持以下声明式来源，不执行 shell：

```toml
version = { source = "literal", value = "1.2.3" }
version = { source = "env", name = "PRODUCT_VERSION" }
version = { source = "file", path = "VERSION" }
version = { source = "git-describe" }
```

`role` 只能是 `entrypoint`、`owned` 或 `dependency`，且至少一个模块是
`entrypoint`。设置 `require_clean = true` 可禁止 dirty/unknown 工作区发布。

## 4. 离线预检

```powershell
crashcap validate --profile release
```

`validate` 不访问网络，会检查配置、路径、大小、重复 basename、模块角色，并以同一套
共享解析库检查：

- PE 是 Windows x64 EXE/DLL；
- PDB 是完整 Microsoft PDB 7.0，不是 FASTLINK；
- PE RSDS debug identity 与 PDB identity 完全匹配；
- PE 内嵌 PDB basename 与配置一致；
- PE 不超过 512 MiB，PDB 不超过 2 GiB。

哈希使用流式读取；大 PDB 不会整体载入内存。扫描后文件如被替换，上传端和 Worker
仍会按登记的大小/SHA-256 拒绝，Build 不会被封存。

## 5. 联机诊断与发布

```powershell
crashcap doctor
crashcap publish --profile release
```

`doctor` 只读检查 API、Workspace、Build Publication 开关、客户端最低版本和 MSVC
Artifact Producer 能力。

`publish` 依次执行离线预检、登记 Publication、流式 PUT/multipart 上传、Worker
校验和 Ready 等待。默认来源为本地；检测到常见 CI 环境时为 CI，也可显式指定：

```powershell
crashcap publish --profile release --origin local --wait-seconds 1800
crashcap --json publish --profile release --origin ci
```

完全相同的配置、Git 状态和 Artifact 内容重跑会复用 Publication 与 Build，并跳过
已经 verified 的文件。同一内容从 local 和 CI 发布会创建两个 Publication，但指向
同一个 Build。Manifest、模块角色或任一文件字节变化都会得到新的内容指纹和 Build。

只有全部期望 PE/PDB 验证成功，Build 才进入 `ready` 并写入 `sealed_at`。封存后不能
修改 Manifest、替换文件或增加未声明文件。

默认回执为 `crashcap-publication.json`，仅包含 Publication/Build/指纹、状态、Git
revision/state 和期望清单结果；不包含源码、用户名、机器名、remote URL、凭据、
本地绝对路径或预签名 URL。可用 `--receipt <path>` 修改位置。

dirty 工作区允许发布，但 CLI 回执和 Build 页面会显示醒目警告。`unknown` 不会被
伪装成 clean。

## 6. 浏览器恢复路径

Build 页面仍允许逐文件恢复。对 content Build：

- Manifest 只读；
- 只能选择期望清单中 `missing` 的 PE/PDB；`rejected` 继续显示诊断原因，但不能借网页替换内容；
- 文件名和大小必须先匹配，Worker 最终验证 SHA-256 与 PE/PDB identity；
- sealed 后不再接受上传；
- 大文件或网络中断恢复优先重新运行同一个 `crashcap publish`。

Legacy Build 保留原有 Manifest v1/v2、浏览器 Artifact 和显式 source bundle 路径。

## 7. GitLab/GitHub CI

同一 CLI 也可用于 CI，不再维护 `crashcap-ci` 二进制。CI 只需要提交
`crashcap.toml`，并确保 Build Job 生成的精确路径在 Publish Job 中仍存在。

GitLab：

```yaml
include:
  - local: /.gitlab/ci/crashcap.yml

publish:crashcap-build:
  stage: publish
  extends: .crashcap:windows
  needs: [build:windows]
  variables:
    CRASHCAP_CONFIG: "crashcap.toml"
    CRASHCAP_PROFILE: "release"
```

在项目或 Group Variables 设置 `CRASHCAP_API_URL`。模板校验工具哈希，使用
`--origin ci` 发布并保留无凭据回执。GitHub self-hosted Windows 示例位于
`.github/workflows/phase2-build-publish.yml`。Runner 也必须同时位于可访问 API 和 S3
Gateway 的可信网络中。

## 8. 常见故障

| 错误或状态 | 处理 |
| --- | --- |
| `BUILD_PUBLICATIONS_DISABLED` | 管理员尚未在该环境启用试点开关。 |
| Workspace 解析为 0 个或多个 | 使用准确名称/`wsp_...` ID，或由管理员创建。 |
| `FASTLINK PDB is unsupported` | 使用 `/DEBUG:FULL` 重新链接。 |
| `PE/PDB identity mismatch` | PE 和 PDB 不是同一次链接输出，重新成套构建。 |
| `duplicate artifact basename` | 清理旧输出，改为唯一 basename 和精确相对路径。 |
| `ARTIFACT_CONTENT_MISMATCH` | 文件在预检后变化，重新执行完整 publish。 |
| `UNEXPECTED_ARTIFACT` | content Build 只能补交登记清单中的 PE/PDB。 |
| `BUILD_SEALED` | 内容已 Ready；任何内容变化都应产生新 Build。 |
| multipart/网络中断 | 保持文件和配置不变，重跑 publish 复用 Publication/Build 与已验证文件；未完成的文件会重新初始化上传。 |
| content Artifact identity 被拒绝 | 该精确内容无法 Ready；修复 PE/PDB 并重新构建，新的字节会产生新 Build。 |
| 对象上传 403 | 检查开发机到 S3 Gateway 的网络、时钟和预签名 URL 有效期。 |

## 9. 管理员启用与回滚

新路由默认关闭。试点环境显式设置：

```text
CRASHCAP_BUILD_PUBLICATIONS_ENABLED=true
```

升级只执行 additive migration。回滚时关闭该开关和 UI 入口，保留 schema、Build 与
Publication；Worker 仍可完成已经提交的校验。创建过 content Build 后不得数据库
downgrade。旧 CI API、Manifest、人工 Build 和浏览器路径保持兼容。

正式可用必须在目标内网开发机上补齐：真实 MSVC Release 发布、reported/auto-unique
DMP 符号解析、同内容重发/不同内容重编、网络中断、错误/超大 PDB、备份与浏览器证据，
并完成组织 Authenticode 签名。Docker Desktop 本机结果不能替代这些验收。
