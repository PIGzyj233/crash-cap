# Phase 1 目标内网 HTTP perimeter probe

本探针是只读证据收集器，不是网络边界的替代品。它可以证明“执行探针的这台机器”从批准 CIDR 通过 HTTP 到达目标 API、Frontend 与 S3 Gateway，并检查 API 路由；它不能从单机结果推断任意外部网段不可达。RustFS 本身不发布宿主机端口。Phase 1 按 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md) 明确拒绝 HTTPS/TLS，HTTP 流量只能留在受控可信内网。

## 运行方式

在目标可信内网的一台验收机上，由具名开发或运维执行者提供 HTTP 目标 URL 和允许的源网段：

```text
python scripts/phase1/target_perimeter_probe.py \
  --api-url http://crashcap.intranet.example \
  --frontend-url http://crashcap.intranet.example/web \
  --object-store-url http://crashcap-s3.intranet.example \
  --allowed-cidr 10.0.0.0/8 \
  --occurrence-id occ_<known-accepted-dump> \
  --outside-evidence C:\evidence\outside-probe.json \
  --json-out C:\evidence\perimeter-probe.json
```

`--outside-evidence` 必须来自明确位于目标允许网段之外的探针机或隔离网络命名空间，且包含 `tester`、`target`、API/Frontend/S3 Gateway 每个 endpoint 的 `reachable=false` 结果和实际执行者签字/证据引用。执行者可以是开发或运维人员，但必须记录真实网络视角；探针不会创建、补全或自签这个文件，没有它时机器可读结果只能是 `NOT_PROVEN`。

输出 JSON 的顶层 `status` 只有在所有本机检查和外部证据都通过时才为 `PASS`；任何 `FAIL` 或 `NOT_PROVEN` 都使顶层保持 `NOT_PROVEN`，详细原因保存在 `checks`、`hard_failures` 和 `not_proven`。退出码为 0 仅对应顶层 `PASS`。

探针只执行 GET（健康检查、Frontend 首页、OpenAPI 和指定 occurrence 的 raw-download denial），不创建 Workspace/Build、上传对象、reprocess 或修改 Group。检查内容包括：

- OS 选择的本机源地址是否落入 `--allowed-cidr`；这只代表本机来源，不代表整个网段；
- API/Frontend/S3 Gateway URL 严格使用 `http://`，并从 OS 选择的批准内网源地址可达；任何 `https://` 输入都直接失败；
- OpenAPI 无 DELETE、login/users/roles/RBAC/memberships 路由；
- 给出已验收 occurrence 时，raw 下载返回 `403 + RAW_DOWNLOAD_DISABLED`；不提供 occurrence 时明确 `NOT_PROVEN`；
- 独立 outside probe 的不可达证据是否与目标 URL、tester、target、environment 及签字引用一致。

## Outside probe 文件最小格式

以下只是结构示例，不是可直接签署的证据：

```json
{
  "tester": {"name": "developer-or-operator", "is_developer": true},
  "target": {
    "api_url": "http://crashcap.intranet.example",
    "frontend_url": "http://crashcap.intranet.example/web",
    "object_store_url": "http://crashcap-s3.intranet.example"
  },
  "environment": {
    "name": "target-intranet-prod-like",
    "observed_at": "2026-08-21T12:00:00Z"
  },
  "probes": [
    {"name": "api", "source_network": "outside", "reachable": false, "method": "tcp+http"},
    {"name": "frontend", "source_network": "outside", "reachable": false, "method": "tcp+http"},
    {"name": "object_store", "source_network": "outside", "reachable": false, "method": "tcp+http"}
  ],
  "attestation": {
    "signed_by": "developer-or-operator",
    "signature_ref": "ticket-or-signed-record-id"
  }
}
```

不要把同一 loopback probe 或浏览器截图填入 outside evidence；这些证据只能支撑本机 smoke，不能关闭 GATE-P1-15。若在同一宿主机使用隔离网络命名空间，必须记录网络名、源地址、实际连接失败和端口绑定，并明确它只证明该宿主机的网络边界，不外推为整个生产内网防火墙结论。
