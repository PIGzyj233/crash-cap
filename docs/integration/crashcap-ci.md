# crashcap-ci 第三方 CI 接入指南

本文面向需要把 Windows 原生程序的 PE/PDB 发布到 Crash-Cap 的项目维护者。
完成接入后，每个 CI Build 都会得到一个可复用的 Crash-Cap Build；只有 Manifest
存在且所有声明的 PE/PDB 都通过服务端验收时，CI 才会成功。

本文适用于 `crashcap-ci 1.0.0`。当前正式支持的生产者基线是
Windows x64、MSVC、完整 PDB 7.0；clang-cl 和 Crashpad 仍是实验性生产者。

## 1. 向 Crash-Cap 管理员获取信息

开始前需要取得：

- Crash-Cap API 地址，必须包含 `/api/v1`，例如
  `http://crashcap.intranet.example/api/v1`；
- 已创建的 Workspace ID 或唯一名称；`crashcap-ci` 不负责创建 Workspace；
- 与 Runner 操作系统匹配的 `crashcap-ci`、`SHA256SUMS` 和 `release.json`。

Runner 必须能同时访问 Crash-Cap API 和 API 返回的预签名对象存储地址。当前平台
没有登录或 API Token，只允许部署在批准的可信内网/VPN 中；不得从公网托管 Runner
访问，也不得把 API 或对象存储网关暴露到公网。

## 2. 准备并校验 CLI

推荐把管理员提供的整个 `tools/crashcap-ci` 目录放入项目，保留以下布局：

```text
tools/crashcap-ci/
├── SHA256SUMS
├── release.json
├── windows-x86_64/crashcap-ci.exe
└── linux-x86_64/crashcap-ci
```

Windows PowerShell：

```powershell
$binary = "tools/crashcap-ci/windows-x86_64/crashcap-ci.exe"
$entry = Get-Content "tools/crashcap-ci/SHA256SUMS" |
  Where-Object { $_ -match "  windows-x86_64/crashcap-ci\.exe$" }
if (@($entry).Count -ne 1) { throw "missing unique Windows checksum entry" }
$expected = ($entry -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $binary).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "crashcap-ci.exe SHA-256 mismatch" }
& $binary --version
```

Linux x86_64：

```bash
cd tools/crashcap-ci
grep '  linux-x86_64/crashcap-ci$' SHA256SUMS | sha256sum --check --strict -
chmod 755 linux-x86_64/crashcap-ci
./linux-x86_64/crashcap-ci --version
```

交付的二进制已嵌入 Manifest v1/v2 Schema。Runner 不需要安装 Rust、Python、
OpenSSL，也不需要单独复制 `contracts/` 目录。

## 3. 生成可验收的 MSVC 产物

每个模块必须同时保留匹配的 EXE/DLL 和完整 PDB。链接时使用完整调试信息，例如
`/DEBUG:FULL`；不要使用 `/DEBUG:FASTLINK`。FASTLINK、损坏或与 PE 不匹配的 PDB
都会被服务端拒绝。

建议的输出布局如下。目录名不固定，`crashcap-ci` 会递归查找文件：

```text
out/build-package/
├── build-manifest.json
├── bin/
│   ├── app.exe
│   └── engine.dll
└── symbols/
    ├── app.pdb
    └── engine.pdb
```

硬上限如下：

| 文件 | 上限 |
| --- | ---: |
| PE（EXE/DLL） | 512 MiB |
| PDB | 2 GiB |
| 可选源码 ZIP | 512 MiB |

大于 256 MiB、但不超过 2 GiB 的完整 PDB 是受支持的。大文件会使用流式 SHA-256
和 multipart 上传；不要在 CI 脚本中先把文件整体读入内存。

## 4. 编写 Build Manifest

不需要源码上下文时使用 Manifest `1.0`。可直接复制
[最小 Manifest 示例](examples/build-manifest-v1.json)：

```json
{
  "schema_version": "1.0",
  "product": "your-product",
  "version": "1.2.3",
  "channel": "release",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "build_number": "20260824.42",
  "architecture": "x86_64",
  "compiler": "msvc",
  "toolchain": "msvc-14.4",
  "modules": [
    {
      "code_file": "app.exe",
      "debug_file": "app.pdb",
      "role": "entrypoint"
    }
  ]
}
```

注意：

- `modules` 至少有一个 `role: "entrypoint"`；其他模块可标为 `owned` 或
  `dependency`；
- `code_file` 和 `debug_file` 填文件 basename，不填相对路径；
- 每个 basename 在 `--artifact-root` 下必须恰好出现一次，大小写不敏感；
- 不需要填写 `code_id` 或 `debug_id`。即使填写，它们也只是非可信提示，平台会从
  PE/PDB 重新提取并校验；
- `version` 是展示和聚合标签，不是符号匹配键；
- 字段完整定义见 [Manifest v1 Schema](../../contracts/build-manifest-v1.schema.json)。

需要源码上下文时才使用 Manifest `2.0` 和 ZIP。接入前同时阅读
[源码包安全契约](../operations/phase2-source-bundles.md)及
[Manifest v2 Schema](../../contracts/build-manifest-v2.schema.json)。

## 5. 在 Runner 上先执行一次

Windows PowerShell：

```powershell
$env:CRASHCAP_API_URL = "http://crashcap.intranet.example/api/v1"

& "tools/crashcap-ci/windows-x86_64/crashcap-ci.exe" `
  --workspace "your-workspace" `
  --manifest "out/build-package/build-manifest.json" `
  --artifact-root "out/build-package" `
  --producer "msvc" `
  --producer-build-id "gitlab-$env:CI_PIPELINE_ID" `
  --wait-seconds 1800

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Linux Runner 上传交叉编译得到的 Windows PE/PDB 时使用相同参数：

```bash
export CRASHCAP_API_URL="http://crashcap.intranet.example/api/v1"

tools/crashcap-ci/linux-x86_64/crashcap-ci \
  --workspace "your-workspace" \
  --manifest "out/build-package/build-manifest.json" \
  --artifact-root "out/build-package" \
  --producer "msvc" \
  --producer-build-id "gitlab-${CI_PIPELINE_ID}" \
  --wait-seconds 1800
```

`--api-url` 可代替 `CRASHCAP_API_URL`。如果没有显式传入
`--producer-build-id`，CLI 会依次尝试 `GITHUB_RUN_ID`、`BUILD_BUILDID` 和
`CI_PIPELINE_ID`。建议显式加上 CI 系统或项目名前缀，避免不同系统共用 Workspace
时发生碰撞。

`producer_build_id` 必须代表一次稳定的流水线 Build，而不是一次 Job 尝试。重试同一
流水线必须复用相同值；重新编译出不同版本或产物时必须使用新的值。

## 6. 判断接入成功

成功时进程退出码为 `0`，标准输出是 JSON。关键字段如下：

```json
{
  "artifacts": [
    { "kind": "pe", "path": ".../app.exe", "status": "uploaded" },
    { "kind": "pdb", "path": ".../app.pdb", "status": "uploaded" }
  ],
  "build_id": "bld_...",
  "ci_status": {
    "missing_artifacts": [],
    "ready": true,
    "rejected_artifacts": []
  },
  "workspace_id": "wsp_..."
}
```

验收标准：

- CLI 退出 `0`；
- `ci_status.ready` 为 `true`；
- `missing_artifacts` 和 `rejected_artifacts` 为空；
- 首次执行时 PE/PDB 状态为 `uploaded`；
- 使用相同 Manifest 和 `producer_build_id` 重跑，返回同一个 `build_id`，已验收文件
  状态为 `already_verified`。

`uploaded` 表示 CLI 已等待对应 Upload 达到 `ACCEPTED`，最终 Build Ready 还要求
Manifest 中每个模块的 PE/PDB Artifact 都为 `verified`。CLI 不上传 DMP；DMP 采集和
上报属于运行时崩溃接入的另一条链路。

## 7. 接入 GitLab CI

仓库已经提供可复用的 [GitLab 模板](../../.gitlab/ci/crashcap-ci.yml)。把该模板和
`tools/crashcap-ci` 制品目录复制到第三方项目后，可在 `.gitlab-ci.yml` 中写：

```yaml
include:
  - local: /.gitlab/ci/crashcap-ci.yml

publish:crashcap-build:
  stage: publish
  extends: .crashcap-ci:windows
  needs: [build:windows]
  variables:
    CRASHCAP_WORKSPACE: "your-workspace"
    CRASHCAP_MANIFEST: "out/build-package/build-manifest.json"
    CRASHCAP_ARTIFACT_ROOT: "out/build-package"
```

在 GitLab 项目或 Group CI/CD Variables 中设置 `CRASHCAP_API_URL`。它不是凭据，但
仍应限制到可信内网 Runner。模板使用 `CI_PIPELINE_ID` 作为幂等身份；如果多个项目
共享同一 Workspace，应复制模板并把项目标识加入 `producer_build_id`，例如
`${CI_PROJECT_ID}-${CI_PIPELINE_ID}`。

发布 Job 必须依赖实际生成 PE/PDB/Manifest 的 Build Job，并确保这些文件通过 CI
artifacts 传递到发布 Job。不要让发布 Job重新构建二进制。

GitHub Actions 的 self-hosted Windows 示例见
[Phase 2 Build publish workflow](../../.github/workflows/phase2-build-publish.yml)。该
Runner 同样必须位于批准的内网边界。

## 8. 幂等、重试和失败处理

Build 的幂等键是：

```text
(workspace_id, producer, producer_build_id)
```

相同身份和相同不可变元数据重跑会复用已有 Build，并跳过已经验证且 SHA-256 相同的
文件。CLI 对 API、对象上传的传输错误及服务端 5xx 最多自动尝试五次；4xx 不会自动
重试。

同一个幂等身份不能改写 `version`、commit、build number、channel、architecture 或
toolchain。否则 API 返回 `409 CONFLICT`。遇到网络中断或等待超时，应先用相同身份
重跑；不要为了绕过错误随机生成新的身份。

除 `--help`、`--version` 等正常查询外，发布成功退出 `0`；参数、Manifest、本地文件、
网络、上传或服务端验收失败统一退出 `2`。失败信息写入标准错误。

## 9. 常见问题

| 错误或症状 | 处理方式 |
| --- | --- |
| `Workspace ... must resolve uniquely; found 0` | 向管理员确认 Workspace ID 或准确名称，以及 API 环境是否正确。 |
| `found 2` 或更多 | Workspace 名称不唯一，改用 `wsp_...` ID。 |
| `Build Manifest validation failed` | 按错误中的 JSON 路径检查字段；优先从本文最小示例重新生成。 |
| `must resolve to exactly one file; found 0` | Manifest 文件名与实际 EXE/DLL/PDB 不一致，或 Build Job 未传递文件。 |
| `found 2` 或更多 Artifact | `artifact-root` 下存在同名副本；清理旧输出或缩小目录范围。 |
| `producer ... is experimental` | 正式接入改用 MSVC；`--allow-experimental` 只用于已有资格评估计划。 |
| `409 CONFLICT` | 同一 `producer_build_id` 对应的不可变构建信息发生变化；确认是否错误复用了流水线 ID。 |
| `artifact upload ended in REJECTED` | 检查文件格式、大小、PDB 是否 FASTLINK，以及 PE/PDB 是否来自同一次链接。 |
| `Build verification rejected artifacts` | 在 Crash-Cap Build 页面或 API 中查看具体 Artifact 状态；不要发布不匹配的半套符号。 |
| `timed out waiting ...` | 确认 Worker 和对象存储健康；大 PDB 可增加 `--wait-seconds`，然后用相同身份重跑。 |
| 对象上传返回 403 | 检查 Runner 到对象存储网关的网络和时钟；预签名地址过期后用相同身份重跑 CLI。 |

## 10. 第三方交付验收清单

- [ ] Runner 位于批准的可信内网/VPN，API 和对象存储地址均可达。
- [ ] `crashcap-ci` 与 `SHA256SUMS` 校验通过，版本已记录在流水线日志中。
- [ ] MSVC 生成完整 PDB，没有使用 FASTLINK。
- [ ] 每个 Manifest 模块都有唯一匹配的 PE 和 PDB，至少一个模块是 `entrypoint`。
- [ ] `producer_build_id` 在 Job 重试时保持不变，在新 Build 时变化。
- [ ] 首次发布退出 `0` 且 `ci_status.ready=true`。
- [ ] 相同身份重跑返回同一个 `build_id` 和 `already_verified`。

支持范围和晋级条件以
[CI producer compatibility matrix](../operations/phase2-ci-producer-matrix.md)为准；
Manifest 及文件大小的稳定契约以 [Crash-Cap 设计](../design.md)为准。
