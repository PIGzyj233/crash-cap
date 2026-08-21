# Phase 1 目标内网 UAT 清单

这是 GATE-P1-16 的内部验收记录模板。由目标环境中实际执行的开发或运维人员完成，填写真实 tester、target、environment、观察时间和证据引用。自动化单元测试、mock、合成 JSON 或自动生成的签名不能替代真实目标环境证据。

## 前置条件

1. 目标部署已固定 Compose/镜像 digest，并按 [ADR-0005](../adr/0005-use-plain-http-inside-the-phase-1-trusted-intranet.md) 通过可信内网 HTTP 发布；不得配置 HTTPS，也不得让端口离开批准的私网边界。
2. Tester 是实际执行本次验收的开发或运维人员，能够操作浏览器和目标 API；`tester.is_developer` 必须明确为布尔值（开发人员填 `true`，其他执行者填 `false`）。签署人可以就是实际执行者。
3. 记录目标名称、入口 URL、网络/集群、发布身份、执行主机和观测时间。
4. 先运行 [target perimeter probe](phase1-target-perimeter-probe.md)，把 JSON 结果和独立 outside probe 证据作为 GATE-P1-15 的边界证据引用。
5. 每一步都必须填写 `PASS`、`FAIL` 或 `NOT_PROVEN`、观测时间和证据引用；缺证据不能视为通过。

## 端到端步骤

| Gate | 执行操作 | 必须保留的证据 |
| --- | --- | --- |
| GATE-P1-01 | 创建 Workspace、Build、Manifest、匹配 PE/PDB，上传正确 DMP，打开报告 | Workspace/Build/Occurrence/Run ID；函数、文件、行号截图或导出 |
| GATE-P1-02 | 上传错误 PDB 并分析 | PDB verification=`pdb_mismatch`；报告中无静默错误符号 |
| GATE-P1-03 | 只保留 PDB、不提供 PE，上传 DMP | `PARTIAL`、unwind/quality 下降和模块状态 |
| GATE-P1-04 | 补上传 PE，触发 reprocess | 新 Run、旧 Run 仍可查、Occurrence 总数不变 |
| GATE-P1-05 | 在同 Workspace 重传同 SHA，再在另一 Workspace 上传 | 同 Workspace 复用 Blob/Occurrence；跨 Workspace 不复用 |
| GATE-P1-06 | 在有排队任务时重启 API | Redis 中任务仍能被恢复 Worker 消费，Run ID/结果记录 |
| GATE-P1-07 | 重启 Symbolicator 后重提分析 | 新 attempt 不依赖旧 request，最终结果可完成 |
| GATE-P1-08 | 执行已批准的 Core 故障隔离演练 | Core crash/timeout/OOM 记录；API 和独立任务仍健康 |
| GATE-P1-09 | 直传大文件并测试 >256 MiB 边界 | DMP 不经过 API body；超限拒绝且不入队 |
| GATE-P1-10 | 在两个 Workspace 使用同名符号文件 | debug ID、Workspace scope 和报告结果不串扰 |
| GATE-P1-11 | 登记同 Version 的多个 Build 后上传未指定 Build 的 DMP | `ambiguous/unresolved` 和未知 Version，不猜测 |
| GATE-P1-12 | 使用无精确业务帧的 DMP | Unclassified，不创建伪 Exact Group |
| GATE-P1-13 | 让 reprocess 改变 Build/Group 再看 Overview | current/group 实时变化，Occurrence 总数保持不变 |
| GATE-P1-14 | 分别提交 Crash、Hang、Unknown 和 Rejected | Dashboard 分栏，非 Crash 不进入 Crash Occurrence |
| GATE-P1-15 | 从允许内网和 outside probe 检查 HTTP 边界 | perimeter probe JSON、HTTP-only scheme/批准源 CIDR、外部不可达证据、无 DELETE/login/RBAC、raw 默认拒绝 |
| GATE-P1-16 | 完整流程从 Workspace 到后补符号 reprocess | 本表所有步骤 PASS；导出 UAT JSON/Markdown 并由实际执行者签字 |

## 记录格式

用 `scripts/phase1/uat_runner.py` 校验填写的 JSON 并生成机器可读 JSON 与 Markdown：

```text
python scripts/phase1/uat_runner.py \
  --answers C:\evidence\phase1-uat-answers.json \
  --output-json C:\evidence\phase1-uat-result.json \
  --output-markdown C:\evidence\phase1-uat-signoff.md
```

可先生成空白模板，但空白模板只会得到 `NOT_PROVEN`：

```text
python scripts/phase1/uat_runner.py \
  --answers unused.json \
  --output-json unused-result.json \
  --output-markdown unused.md \
  --write-template C:\evidence\phase1-uat-answers.json
```

Runner 不会替 tester 勾选、不产生 evidence、不改变开发者标记，也不会生成签名；`target.base_url` 还必须是无 userinfo/query/fragment 的 `http://` URL，HTTPS 记录不能通过。只有填写的 16 个 Gate 全部显式 `PASS`、证据引用完整且 `signoff.signature_ref` 指向实际签署记录（不能为 `auto` 或 `generated`）时，结果才可能为 `PASS`。`signoff.signed_by` 可以与 `tester.name` 相同。
