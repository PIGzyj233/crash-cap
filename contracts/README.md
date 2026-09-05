# 当前契约

客户端 HTTP 唯一版本 `/api/v3`，由 API 的 OpenAPI 描述。Canonical 唯一公开版本是 `analysis-result-v2.0.schema.json`，不包含 `build_resolution` 或业务版本标签。

内部分析输入使用 `analysis-run-v3`、`analysis-context-v3` 和 `resolution-manifest-v1`。最后一个是系统产生的符号选择快照，不是用户提交的 Build Manifest。内部任务入口为 `task-message-v3.schema.json`；各任务保留自己的消息版本 1.0/1.2。

证据比较、人工结果复核和分析需求契约继续复用。API、Worker、CLI 和浏览器共享同一业务验收规则。旧 Build、源码包、Publication、完整配对上传与 Canonical 1.x 契约不再提供运行兼容。
