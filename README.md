# Crash-Cap

Windows x64 崩溃分析平台：选择空间、上传 EXE / DLL / PDB / DMP，附带可选版本。

```powershell
crashcap upload .\Release --workspace light-streamer --build-version 11.0.1.27 --api-url http://localhost:8082
crashcap upload .\sdk.dll .\sdk.pdb --public --build-version 3.2 --api-url http://localhost:8082
crashcap upload .\crash.dmp --workspace light-streamer --api-url http://localhost:8082 --receipt upload.json --json
```

目标必须是 Workspace 的 ID/精确名称，或 `--public`。Workspace 在浏览器创建。版本可以省略，不需要 Git、配置文件、Build 或 Manifest。目录递归发现支持文件。公共空间不接收 DMP。PE/PDB 可以分开上传，缺少另一半仍算上传成功。

浏览器平台入口选择 Workspace 或公共空间；Workspace 内直接上传到当前空间。“产物与符号”显示文件、版本、等待配对、符号可用或身份冲突。DMP 报告允许编辑版本，不需要重新分析。

- [当前设计](docs/design.md)
- [领域术语](CONTEXT.md)
- [上传 v3 与验收指南](docs/upload-v3-guide.md)
- [取代 Build 发布的决定](docs/adr/0022-upload-files-with-scoped-symbol-availability.md)
- [HTTP OpenAPI](platform/frontend/openapi.json)

新库基线只支持空库部署；旧数据和旧客户端不兼容。全部 API 为 `/api/v3`，报告为 Canonical 2.0。源码包上传已移除。

```powershell
cargo test --workspace
cd platform
uv run ruff check api worker cli
uv run mypy api worker cli
uv run pytest
cd frontend
pnpm lint
pnpm test
pnpm build
```

真实验收需要生成 PE/PDB/DMP fixtures，并运行 PostgreSQL、对象存储、队列和 Symbolicator。执行部署前阅读指南中的资源范围、备份和整套回退要求。未记录的目标环境验收不得视为已通过。
