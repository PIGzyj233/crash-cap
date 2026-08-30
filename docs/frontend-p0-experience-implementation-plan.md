# Crash-Cap P0 使用体验改造实施计划

- 状态：`实现完成；本地自动 Gate 通过；GATE-P0X-C/FINAL 因真实 Tab/200% 与目标内网签署为 NOT_PROVEN`
- 日期：2026-08-30
- 代码基线：`main@3e3c8a3`
- 范围：平台主页、Crash Inbox（Occurrence 列表）、真实路由与可分享链接

## 1. 目标与结果

本计划把当前“先选中或恢复一个 Workspace，再在单页内切换组件”的前端，改造成一个具有稳定入口、
可检索事故队列和可刷新 URL 的崩溃分析平台。

完成后应得到以下用户结果：

1. 打开 `/` 永远进入平台主页，不因浏览器中保存过 Workspace 而被直接带进某个 Workspace。
2. 用户可从 `Crash Inbox` 浏览、筛选并打开历史 Occurrence，不再依赖“刚上传完成”或其他页面的临时入口。
3. Workspace、Build、Group、Occurrence、报告页签和历史 Run 都有可刷新、可复制、可前进后退的 URL。
4. 重分析仍只产生新的 Analysis Run，不把同一个 DMP 误计为新的 Occurrence。
5. 新旧后端数据完全兼容；改造只增加读 API 和索引，不回填、不改写历史业务数据。

## 2. 当前基线与问题边界

当前实现的关键事实如下：

- `platform/frontend/src/App.tsx` 使用本地 `Page` 状态切换 Overview、Build、Group 和
  Occurrence；地址栏不表达当前页面。
- 浏览器保存完整的 `crash-cap.workspace` JSON。只要本地存在记录，根路径就直接进入该
  Workspace，且进入前不向服务端验证记录是否仍有效。
- `platform/frontend/src/api/client.ts` 和后端目前只有 Occurrence 详情 API，没有 Workspace
  范围的 Occurrence 列表。
- `platform/frontend/nginx.conf` 已配置 `try_files ... /index.html`，具备浏览器深链 fallback，
  但还没有路由层使用它。
- 现有领域模型已能提供列表所需事实：Occurrence、Current Analysis、latest attempt、
  Analysis Summary、Build Resolution 和 Current Group Membership；无需新增业务实体。

本计划不顺带实施以下内容：

- 登录、RBAC、SSO 或 Workspace 权限模型；仍遵守可信内网、匿名访问边界。
- Family Group、merge/split、趋势/回归检测和新的分组算法。
- 删除、合并或重建历史 Occurrence/Analysis Run。
- 全站视觉重做、移动端原生适配或新的分析引擎能力。
- 将已有 Overview 的所有统计口径一次性重构；P0 只保证新主页不把“无样本”显示成优秀百分比。

## 3. 必须冻结的产品与领域决策

### 3.1 导航决策

- `/` 是稳定的平台主页，任何情况下都不自动重定向到上次 Workspace。
- 浏览器只保存 `lastWorkspaceId`，用于主页上的“继续上次 Workspace”快捷入口；它不是当前页面状态，
  也不是 Workspace 事实来源。
- URL 使用不可变的 `workspace_id/build_id/group_id/occurrence_id`。页面和面包屑展示人类可读名称，
  不把可能变化的展示名当路由身份。
- 当前 Workspace、页面、报告页签、Run 和 Inbox 筛选条件均由 URL 决定。
- URL 中的 Workspace 与资源不匹配时显示明确的 404/越界提示，不静默切换 Workspace。

### 3.2 Occurrence 与分析状态决策

- Occurrence 表示一个 Workspace 内一份不同的、已接受的 DMP；reprocess 不增加 Occurrence。
- `current_analysis` 只表示当前被选中的 COMPLETE/PARTIAL Run；它不等于最近一次尝试。
- `latest_attempt` 独立展示。若新 Run 失败而旧 Current Analysis 仍有效，列表必须同时显示
  “Current 可用”和“最近重试失败”，不能互相覆盖。
- 崩溃类型、异常、顶部函数、版本、质量与 Group 都只从 Current Analysis 投影。
- 没有 Current Analysis 的 Occurrence 仍出现在 Inbox；分析摘要字段为 `null`，状态由
  latest attempt 表达。
- Group 只有在 `group_membership.analysis_run_id == occurrence.current_run_id` 时才是当前分组。

### 3.3 兼容与安全决策

- 所有新增 HTTP 接口均为 additive；已有详情、上传、reprocess、SSE 和报告接口不改路径、不改语义。
- 列表不得返回 DMP SHA、对象键、预签名 URL、原始引擎输出或完整源码路径。
- 新 API 使用显式 Pydantic response model，并继续由 checked-in OpenAPI 生成前端 wire types。
- 这是 UI/read-model 改造，不改变核心领域语义，暂不需要单独 ADR；评审批准后必须同步
  `docs/design.md`。若评审要求修改 Occurrence/Current Analysis 定义，则先停工并新增 ADR。

## 4. 目标信息架构与路由

```text
/
├── /workspaces
└── /w/:workspaceId
    ├── /overview
    ├── /occurrences
    │   └── /:occurrenceId
    ├── /upload
    ├── /builds
    │   └── /:buildId
    ├── /symbols
    ├── /groups
    │   └── /:groupId
    └── /developer
```

路由行为：

| URL | 页面与行为 |
| --- | --- |
| `/` | 平台主页：Workspace 概览、待关注计数、最近 Occurrence、上传入口 |
| `/workspaces` | Workspace 管理/创建；可与主页复用列表组件，但 URL 独立 |
| `/w/:workspaceId` | 规范化重定向到 `/w/:workspaceId/overview` |
| `/w/:workspaceId/occurrences` | Crash Inbox；筛选、搜索和分页状态写入 query string |
| `/w/:workspaceId/occurrences/:occurrenceId` | Occurrence Report；校验资源属于 URL 中的 Workspace |
| `/w/:workspaceId/upload` | 复用现有 Dump 上传卡，成功后跳转到 Occurrence URL |
| `/w/:workspaceId/builds/:buildId` | 可直接刷新和分享的 Build 详情 |
| `/w/:workspaceId/groups/:groupId` | 可直接刷新和分享的 Exact Group 详情 |
| `*` | 404，提供“返回主页”和“返回 Workspace”动作 |

Query string 规范：

- Inbox：`from`、`to`、`crash_type`、`latest_status`、`resolution_method`、`version`、
  `build_id`、`grouping`、`q`、`cursor`。
- Report：`tab=overview|stack|threads|modules|raw|similar`；查看历史结果时增加 `run=<run_id>`。
- 缺失或非法参数回退到安全默认值，并从 URL 移除非法值；不能造成白屏。
- `Back` 使用浏览器历史；`location.state` 只能改善返回按钮文案，不能成为页面可访问的必要状态。

## 5. 页面方案

### 5.1 平台主页

主页第一屏回答三个问题：我在哪个平台、哪里需要处理、下一步能做什么。

- 主标题固定为 Crash-Cap，并清楚标注可信内网、匿名访问边界。
- “待关注”只展示可解释的计数：分析中、最近尝试失败、Unclassified Crash、受缺失/不匹配符号
  影响的 Occurrence。计数为 0 可以显示 0；没有样本的比率不得显示为 100%。
- Workspace 卡片展示显示名、最近 7 天 Occurrence 数、待关注数、最后一条 Occurrence 时间。
- 最近 Occurrence 最多展示 10 条，使用与 Inbox 相同的摘要组件。
- 主动作是“上传 Dump”。若尚未选 Workspace，先打开 Workspace 选择器，再导航到
  `/w/:workspaceId/upload`。
- “继续上次 Workspace”只有服务端确认 `lastWorkspaceId` 存在时才出现；失效记录从本地清除。
- 零 Workspace 时展示合法空状态和“创建 Workspace”，不出现错误重试页。

### 5.2 Crash Inbox

默认按 `occurred_at DESC, id DESC` 展示。建议列：

| 列 | 信息来源与展示规则 |
| --- | --- |
| 时间 | Occurrence `occurred_at`，同时提示 `time_source` |
| 当前结论 | Current Analysis 的 crash type、异常码/名称；无 Current 时显示“尚无可用分析” |
| 顶部位置 | `fault_module!top_function`；缺失时保留占位，不猜测 |
| Version / Build | Current Analysis 的 Build Resolution；ambiguous/unresolved 明确标记 |
| 分组 | Current Exact Group 或 Unclassified；无 Current 时为 N/A |
| 质量 | Current Analysis quality score；无样本显示 N/A |
| 最近动作 | latest attempt 状态；与 Current 状态并列而非覆盖 |

交互规则：

- 整行包含可键盘聚焦的真实链接，新标签打开和复制链接都可用。
- 时间范围、类型、最近状态、Build Resolution、Version/Build、分组和文本搜索可组合。
- 筛选改变时清除旧 cursor，并以 `replace` 更新 URL；用户主动翻页用 `push`，使浏览器返回可恢复上页。
- 第一页合法为空时展示“当前筛选无结果”，并提供清除筛选；Workspace 从未有 Occurrence 时提供上传入口。
- API 错误、合法空集合、首次加载和后台刷新是四种不同状态；后台刷新不清空已有表格。

### 5.3 Occurrence Report 与现有页面

- Occurrence Report 从路径参数读取 Occurrence，从 `tab/run` 读取选中视图。
- 上传完成后以 `navigate(..., { replace: true })` 进入报告，刷新后仍能继续轮询/SSE。
- Overview、Symbol Health、Group、Build 页面中的 Occurrence/Group/Build 入口全部改为 `<Link>`。
- 面包屑每一级可导航；侧栏使用 `NavLink`，选中态由 route match 决定。
- 切换 Workspace 返回主页/Workspace 选择器，不再把 React 内存状态清空当作导航。

## 6. 新增 HTTP 读模型

### 6.1 `GET /api/v1/platform/overview`

建议响应模型：

```json
{
  "window_start": "ISO-8601",
  "window_end": "ISO-8601",
  "workspace_count": 2,
  "attention": {
    "in_progress": 3,
    "latest_attempt_failed": 1,
    "unclassified_crashes": 4,
    "symbol_affected_occurrences": 2
  },
  "workspaces": [
    {
      "workspace": { "...": "WorkspaceResponse" },
      "occurrence_count": 20,
      "attention_count": 4,
      "last_occurrence_at": "ISO-8601 or null"
    }
  ],
  "recent_occurrences": ["OccurrenceListItemResponse"]
}
```

约束：

- 默认窗口 7 天；允许 `from/to`，并限制最大跨度为 90 天。
- Workspace 聚合通过集合查询完成，不允许逐 Workspace 调 Overview API。
- 主页只返回计数和最多 10 条最近记录；不返回昂贵的全量 total 或大对象。
- `latest_attempt_failed` 使用最近一次 Run 的终态失败集合：
  `FAILED|REJECTED|CANCELLED|TIMEOUT|OOM`，即使旧 Current Analysis 仍可用也必须计入。
- `in_progress` 使用最近一次 Run 的非终态集合；Current Analysis 不参与判定。

### 6.2 `GET /api/v1/workspaces/{workspace_id}/occurrences`

参数：

| 参数 | 规则 |
| --- | --- |
| `from/to` | 过滤 Occurrence `occurred_at`；`from <= to`，最大跨度 366 天 |
| `crash_type` | `crash|hang|unknown|no_current`，依据 Current Analysis |
| `latest_status` | 精确过滤 latest attempt status |
| `resolution_method` | `reported|auto_unique|manual|ambiguous|unresolved|no_current` |
| `version` | Current Analysis Summary 的精确 Version |
| `build_id` | Current Analysis 的 resolved Build ID |
| `grouping` | `exact|unclassified|no_current` |
| `q` | 最长 128 字符；匹配 Occurrence ID、异常名/码、fault module、top function、Version |
| `cursor` | 不透明的版本化 keyset cursor |
| `limit` | 默认 50，最小 1，最大 200 |

建议响应：

```json
{
  "items": [
    {
      "id": "occ_...",
      "workspace_id": "ws_...",
      "occurred_at": "ISO-8601",
      "uploaded_at": "ISO-8601",
      "time_source": "dump|reported|uploaded|manual",
      "current_analysis": { "...": "AnalysisRunResponse or null" },
      "latest_attempt": { "...": "AnalysisRunResponse or null" },
      "summary": {
        "crash_type": "crash|hang|unknown",
        "exception_code": "string or null",
        "exception_name": "string or null",
        "access_type": "string or null",
        "fault_module": "string or null",
        "top_function": "string or null",
        "version": "string or null"
      },
      "group": { "...": "GroupSummaryResponse or null" }
    }
  ],
  "next_cursor": "opaque string or null"
}
```

分页规则：

- 固定排序 `(occurred_at DESC, id DESC)`，读取 `limit + 1` 判断下一页。
- cursor 内部包含版本、最后一行的 `occurred_at/id` 和筛选摘要；base64url 只是传输编码，不把它
  当安全边界。
- cursor 损坏、版本未知或与当前筛选不匹配时返回 `422 INVALID_CURSOR`。
- 不返回总条数。P0 以稳定浏览为目标，避免每次筛选执行昂贵 `COUNT(*)`。
- 搜索中的 `%`、`_` 按普通字符转义；空白 query 视为未筛选。

### 6.3 查询实现与索引

新增 `services/occurrence_queries.py`，由平台主页和 Inbox 复用同一投影，不把复杂 SQL继续堆进
`routes.py`。查询必须批量获得 latest attempt，不得对每个 Occurrence 调用 `latest_run()`。

建议新增 additive migration `0010_occurrence_browse_indexes.py`：

```text
ix_occurrences_workspace_occurred_id
  (workspace_id, occurred_at DESC, id DESC)

ix_analysis_runs_occurrence_id_desc
  (occurrence_id, id DESC)

ix_uploads_workspace_dmp_status_uploaded
  (workspace_id, file_kind, verification_status, uploaded_at DESC)
```

PostgreSQL 目标环境在数据量较大时使用 concurrent index build；SQLite 迁移测试使用等价普通索引。
不做数据回填。Version/文本搜索的额外索引只在目标 PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)`
证明需要后再加入，避免没有证据的索引膨胀。

## 7. 前端实现结构

### 7.1 路由与 Shell

- 增加 `react-router-dom` 并锁定与 React 19 兼容的当前版本。
- `main.tsx` 挂载 Browser Router；`App.tsx` 只保留主题、Error Boundary 和 route tree。
- 新增 `layouts/PlatformLayout.tsx`、`layouts/WorkspaceLayout.tsx`；Workspace Layout 通过
  `workspaceId` 调 `GET /workspaces/{id}`，服务端响应是唯一事实源。
- 新增 `routes/routePaths.ts` 集中生成 URL，禁止页面手拼路径。
- 原有页面先保留 props，但把 `onOpenOccurrence/onOpenBuild/onOpenGroup` 逐步替换为链接；集成后删除
  `Page/Section` 内存状态和完整 Workspace localStorage。

### 7.2 数据层

- response model → OpenAPI → `src/generated/openapi.ts` → `src/types.ts`，不新增重复手写 wire interface。
- 新增 `getPlatformOverview/listOccurrences` 和对应 hooks。
- Inbox query key 包含规范化后的全部筛选参数；cursor 作为分页参数，使用
  `keepPreviousData/placeholderData` 保留上一页视觉稳定性。
- 上传/reprocess 成功后精确失效 `platform-overview`、`occurrences`、`occurrence` 和相关 Overview key。
- Mock API 必须实现新接口，覆盖无 Workspace、无 Occurrence、处理中、Current 可用但 latest 失败四组数据。

### 7.3 页面状态与可访问性

- 每个集合页统一四态：首次 loading、合法 empty、retryable error、已有数据上的 background refresh。
- 页面切换后更新 `document.title`，主标题获得程序化 focus；保留键盘可见焦点。
- 行导航使用真实链接；筛选表单有 label；图标按钮有可访问名称；状态不能只靠颜色区分。
- 1280 px、1440 px、200% 浏览器缩放下不能遮挡主要动作；窄屏允许表格横向滚动。

## 8. 并行实施车道与依赖

```text
P0X-A 契约/查询/索引 ───────┐
                            ├── P0X-D 首页与 Inbox 集成 ── P0X-E Gate/UAT
P0X-B 路由/Shell ───────────┤
P0X-C UI（先用 mock） ──────┘
```

- `A` 与 `B` 可在契约冻结后并行。
- `C` 可在 OpenAPI 示例和 mock 冻结后与后端并行。
- `D` 必须等待 `A` 的实际 wire contract 和 `B` 的 route shell。
- `E` 必须在真实 PostgreSQL/API/Frontend 组合上执行，mock 或 SQLite 不能替代。

## 9. 可勾选实施任务

### 9.1 P0X-0：评审与契约冻结

- [x] **P0X-001｜冻结路由与首页行为** `[UX/UI]`。确认 `/` 永不自动跳转、URL 使用稳定 ID、
  `/upload` 采用独立路由。完成标准：第 3–5 节评审通过。
- [x] **P0X-002｜冻结 Occurrence 列表口径** `[MODEL/PLAT/UI]`。逐字段确认 Current Analysis、
  latest attempt、Group 和 no-current 状态。完成标准：至少覆盖“旧 Current 成功 + 新尝试失败”的例子。
- [x] **P0X-003｜同步权威设计** `[DOC/MODEL]`。把批准后的路由、两个新 API、cursor 和状态口径写入
  `docs/design.md`；确认 `CONTEXT.md` 无需改词义。
- [x] **GATE-P0X-0｜产品、领域和 HTTP 契约冻结**。未通过不得编写生产查询或切换根路径。

### 9.2 P0X-A：后端读模型与契约

- [x] **P0X-A01｜建立 response model 与 OpenAPI fixture** `[PLAT/REP]`，依赖 GATE-P0X-0。
  新增 Platform Overview、Occurrence List Item/Page 模型；字段均显式且无内部 key/hash。
- [x] **P0X-A02｜实现 cursor codec** `[PLAT/QA]`。版本化、严格解析、筛选摘要校验、bounded 长度；
  覆盖篡改、未知版本、筛选变化和时间边界。
- [x] **P0X-A03｜实现集合式 Occurrence 查询服务** `[PLAT]`。一次投影 current/latest/summary/group，
  支持组合筛选、keyset pagination 和 Workspace 隔离；固定 SQL 查询数，不允许 N+1。
- [x] **P0X-A04｜实现 `/workspaces/{id}/occurrences`** `[PLAT/REP]`。返回显式 Page 模型、标准错误
  envelope 和 `X-Request-ID`。
- [x] **P0X-A05｜实现 `/platform/overview`** `[PLAT/REP]`。集合式 Workspace 聚合和最近 10 条；
  不逐 Workspace fan-out。
- [x] **P0X-A06｜增加 migration 0010** `[MIG/PLAT]`。只建索引；PostgreSQL/SQLite upgrade 测试、
  offline SQL 和现有 rollback floor 通过。
  隔离 PostgreSQL/Redis Gate 已补跑：原 8 个 skipped 项为 `8 passed`，完整后端套件为
  `269 passed, 0 skipped`；同时修复了 `0010` concurrent DROP 在后续 data guard 拒绝回滚时
  索引先行消失的问题，downgrade 改为事务内 DROP 并通过真实 PostgreSQL roundtrip。
- [x] **P0X-A07｜后端契约与语义测试** `[QA]`。覆盖空库、处理中、Current/Latest 分叉、
  Unclassified、跨 Workspace、组合筛选、cursor 无重无漏、敏感字段不外泄。
- [x] **GATE-P0X-A｜新 API additive 且可独立上线**。旧前端在新 API/新索引下完全回归通过。

### 9.3 P0X-B：真实路由与导航骨架

- [x] **P0X-B01｜引入 Router 与 route path helper** `[UI]`，依赖 GATE-P0X-0。建立 route tree、
  404 和规范化 redirect。
- [x] **P0X-B02｜拆分 Platform/Workspace Layout** `[UI]`。Workspace 由 URL 加载，加载失败、404、
  网络错误分别处理。
- [x] **P0X-B03｜改造侧栏、面包屑和 Workspace 切换** `[UI]`。全部使用 Link/NavLink；
  选中态由 URL 决定。
- [x] **P0X-B04｜迁移现有 Build/Group/Occurrence 入口** `[UI]`。删除依赖 callback 的页面跳转；
  直接访问和浏览器刷新保持同一页面。
- [x] **P0X-B05｜收缩 localStorage** `[UI/QA]`。仅保存 lastWorkspaceId；旧完整 JSON 只读取一次 ID
  后删除，服务端不存在则清除。
- [x] **P0X-B06｜深链服务器测试** `[UI/OPS]`。验证已知 SPA route 返回 `index.html`，缺失
  `/downloads/crashcap/*` 仍返回真实 404，API 路径不被 SPA fallback 吞掉。
- [x] **GATE-P0X-B｜根路径、刷新、前进后退和新标签打开通过组件/集成测试**。

### 9.4 P0X-C：主页与 Inbox UI（可用 mock 并行）

- [x] **P0X-C01｜实现平台主页** `[UI]`。Workspace 卡、待关注、最近 Occurrence、创建/上传动作和
  last Workspace 快捷入口；零数据状态合法。
- [x] **P0X-C02｜实现 Occurrence 摘要组件** `[UI]`。Current 与 latest attempt 并列；复用于主页和
  Inbox，避免两套状态解释。
- [x] **P0X-C03｜实现 Crash Inbox 表格** `[UI]`。列、状态、语义链接、加载/空/错误/刷新四态完整。
- [x] **P0X-C04｜实现 URL 筛选与分页** `[UI/QA]`。集中 parse/serialize；筛选重置 cursor；复制 URL
  可恢复同一筛选。
- [x] **P0X-C05｜实现上传独立路由** `[UI]`。复用现有上传逻辑；完成后进入 Occurrence route，
  重复 DMP 返回既有 Occurrence 时同样正确跳转。
- [x] **P0X-C06｜报告 tab/run URL 化** `[UI]`。历史 Run、tab、返回 Inbox 都不依赖内存 callback。
- [ ] **GATE-P0X-C｜四组 mock 场景的视觉、键盘和状态语义评审通过**。
  四组 mock 已在 1440×900 完成人工视觉、状态语义与异步 `H1` 焦点检查；物理 Tab 遍历受当前浏览器控制边界限制，仍为 `NOT_PROVEN`。

### 9.5 P0X-D：真实契约集成

- [x] **P0X-D01｜生成并接入 OpenAPI types** `[REP/UI]`，依赖 GATE-P0X-A。`openapi:check` 无 drift，
  不用 `as unknown as` 绕过 wire 类型。
- [x] **P0X-D02｜接入主页与 Inbox hooks** `[UI]`。query key、失效和后台刷新符合第 7.2 节。
- [x] **P0X-D03｜端到端上传导航** `[UI/QA]`。上传、验证、Occurrence 创建/去重、SSE/轮询、报告
  URL 串联通过。
- [x] **P0X-D04｜真实错误与空集合验收** `[UI/QA]`。404、422 cursor、500/网关错误、合法空集合
  互不混淆，并显示 request ID。
- [x] **GATE-P0X-D｜真实 API 与新前端完成集成，旧详情/上传/reprocess 行为无回归**。

### 9.6 P0X-E：性能、UAT、发布与证据

- [x] **P0X-E01｜PostgreSQL 代表性规模测试** `[PLAT/QA]`。单 Workspace 100,000 Occurrence、
  多 Run/有无 Current/Group 混合；确认查询计划和固定查询数。
  本地 Compose PostgreSQL 16.10 target-like Gate 为 `PASS`；目标内网为 `NOT_PROVEN`。
- [x] **P0X-E02｜前端自动门禁** `[UI/QA]`。route、筛选、深链、可访问性、client/mock、lint、test、
  build 全部通过。
- [x] **P0X-E03｜Compose 浏览器 UAT** `[QA/OPS]`。按第 11 节逐项记录 URL、ID、截图、操作者和时间。
  当前结果：11 项 `PASS`、1 项 `NOT_PROVEN`（真实 200% 与物理 Tab），详见 `docs/evidence/frontend-p0-browser-uat-2026-08-30.md`。
- [x] **P0X-E04｜兼容发布与回滚演练** `[OPS]`。先 API 后前端；演练新前端回滚到旧镜像，数据和
  Current Analysis 不变。
- [x] **P0X-E05｜文档和证据收口** `[DOC/QA]`。更新 design、操作手册和证据索引；明确本地、
  Compose、目标内网证据边界。
- [ ] **GATE-P0X-FINAL｜第 13 节完成定义全部通过**。

## 10. 自动验证矩阵

### 10.1 后端/API

| 编号 | 场景 | 必须断言 |
| --- | --- | --- |
| API-01 | Workspace 无 Occurrence | `items=[]`、`next_cursor=null`，不是错误 |
| API-02 | 只有非终态 latest、无 Current | 条目可见，summary/group 为 null |
| API-03 | Current COMPLETE、latest FAILED | 两个状态同时保留，Current 摘要不被失败覆盖 |
| API-04 | reprocess 成功 | Occurrence 数不变，Current 投影更新 |
| API-05 | current crash 无 membership | `group=null`，UI 判为 Unclassified |
| API-06 | 历史 membership 与 Current 不同 | 不返回历史 Group |
| API-07 | Workspace A/B | A 的 list/home 投影不泄漏 B 的详情 |
| API-08 | 组合筛选 | crash type/latest status/resolution/version/build/grouping 取值来自规定事实 |
| API-09 | 两页间插入新 Occurrence | keyset 页内无重复；重新从第一页可见新条目 |
| API-10 | cursor 损坏/跨筛选复用 | 422 `INVALID_CURSOR`，有 request ID |
| API-11 | 搜索 `%`/`_`/超长字符串 | 正确转义或 422，不能扩大为意外通配查询 |
| API-12 | response 安全 | 无 object key、SHA、预签名 URL、内部路径 |

### 10.2 前端路由与交互

| 编号 | 场景 | 必须断言 |
| --- | --- | --- |
| UI-01 | 本地有旧 Workspace JSON，访问 `/` | 仍显示平台主页；只迁移 lastWorkspaceId |
| UI-02 | 直接打开 Occurrence URL | Workspace 与报告都从服务端恢复 |
| UI-03 | 报告页刷新/复制到新标签 | 保持同一 Occurrence、tab 和 run |
| UI-04 | 浏览 Inbox → Report → Back | 返回原筛选和页位置 |
| UI-05 | 失效 Workspace ID | 明确 404，清除 lastWorkspaceId，不无限重试 |
| UI-06 | Occurrence 不属于 URL Workspace | 显示资源不匹配，不切换到真实 Workspace |
| UI-07 | 合法空列表 | 显示空状态；不显示“加载失败” |
| UI-08 | 后台刷新失败 | 保留已有数据并给非阻塞提示 |
| UI-09 | 键盘/焦点 | 可遍历侧栏、筛选、行链接；路由切换焦点到主标题 |
| UI-10 | 深链服务端 fallback | SPA route 200；API/download 404 语义不变 |

### 10.3 性能门槛

目标 PostgreSQL 代表性数据、warm cache 下：

- 默认 Inbox 50 行 p95 ≤ 300 ms、p99 ≤ 500 ms。
- 带一个枚举筛选的 Inbox p95 ≤ 400 ms；文本搜索 p95 ≤ 1 s。
- 100 Workspace、总计 100,000 Occurrence 的平台主页 p95 ≤ 500 ms。
- API 返回大小：Inbox 50 行 ≤ 256 KiB，主页 ≤ 256 KiB。
- SQL 查询数不随返回行数增长；不得出现每行查询 latest Run/Group/Build 的 N+1。

这些数值只有在目标或明确记录的 target-like PostgreSQL 上测得才算 Gate 证据；SQLite、mock 和本机
开发服务器只作为功能预检。

### 10.4 仓库命令

实施时按当前脚本复核，最终至少执行：

```text
cd platform
uv run ruff check api worker cli tests migrations
uv run mypy api worker cli
uv run pytest -q tests migrations/tests

cd frontend
pnpm openapi:check
pnpm test
pnpm lint
pnpm build

python scripts/phase1/deploy_check.py --json --runtime-env-file <external-env>
python scripts/phase2/gate.py
```

缺少 PostgreSQL、Redis、RustFS 或浏览器目标环境而 skipped 的项目必须标记 `NOT_PROVEN`，不得写成
PASS。

2026-08-30 本地验收使用专属临时 PostgreSQL 16.10 与 Redis 7.4.5 执行上述后端命令，结果为
ruff/mypy 通过、`269 passed, 0 skipped`；容器及临时数据在测试后删除，未复用或修改现有 Compose
数据库与 Redis。

## 11. 真实浏览器 UAT

UAT 至少覆盖 1280×720、1440×900 和 200% 缩放；使用目标内网实际 API，不用 mock 数据。每一步记录
`PASS|FAIL|NOT_PROVEN`、tester、时间、Workspace/Occurrence/Run ID、完整 URL 和截图引用。

| Gate | 操作 | 证据 |
| --- | --- | --- |
| UAT-P0X-01 | 清空浏览器存储访问 `/` | 稳定主页、零/多 Workspace 状态 |
| UAT-P0X-02 | 保存 last Workspace 后重新访问 `/` | 不自动跳转；继续入口可用 |
| UAT-P0X-03 | 从主页选择 Workspace 并上传新 DMP | `/upload` → 唯一 Occurrence URL |
| UAT-P0X-04 | 重传相同 DMP | 进入同一 Occurrence，计数不增加 |
| UAT-P0X-05 | Inbox 组合筛选并复制 URL | 新标签恢复同一筛选结果 |
| UAT-P0X-06 | 打开报告、切 tab/run、刷新 | URL 与内容一致 |
| UAT-P0X-07 | 从 Group/Symbol/Build 打开 Occurrence | 使用同一规范 URL，浏览器 Back 正确 |
| UAT-P0X-08 | 触发新 Run 失败且保留旧 Current | Inbox 同时显示可用 Current 与 latest failure |
| UAT-P0X-09 | 无 Current/处理中 | 条目可见，状态轮询/SSE 后收敛 |
| UAT-P0X-10 | 非法/失效/跨 Workspace URL | 404 或资源不匹配，无数据泄漏 |
| UAT-P0X-11 | API 暂停后恢复 | retry 可恢复；已有列表不被错误空态替换 |
| UAT-P0X-12 | 键盘和缩放检查 | 所有主流程可操作，无关键控件遮挡 |

## 12. 发布、观测与回滚

### 12.1 发布顺序

1. 记录当前前端/API 镜像 digest、数据库 revision、旧根路径与关键流程 smoke 基线。
2. 运行 additive migration 0010；确认索引和迁移状态，不做 downgrade。
3. 只部署新 API，保持旧前端；观察新接口错误率、p95、SQL duration 和数据库负载。
4. 新 API Gate 通过后部署新前端；保留原外部 runtime env/secrets，不重新生成或输出凭据。
5. 先在一个 UAT Workspace 执行第 11 节，再扩大到全部可信内网用户。
6. 至少观察一个工作日；流量不足时执行等价浏览/上传负载后再签署 FINAL Gate。

兼容矩阵：

| API | Frontend | 状态 |
| --- | --- | --- |
| old | old | 既有回滚基线 |
| new | old | 必须支持，API 为 additive |
| new | new | 目标组合 |
| old | new | 不支持；回滚必须先回前端 |

### 12.2 观测项

- `GET /platform/overview` 与 list endpoint 的请求数、status、p50/p95/p99、结果行数和 cursor 错误。
- PostgreSQL query duration、rows examined/returned、临时文件和连接池等待。
- 前端 404、Error Boundary、API error code 和 request ID；不得把 URL 搜索词放入 metric label。
- 上传后进入报告成功率、Inbox → Report 导航成功率可以记录 bounded outcome，不记录 DMP 名称或路径。

### 12.3 回滚规则

- 路由、主页或 Inbox 出现阻断：先把 frontend 回滚到旧 digest；新 API 和索引可保留。
- 新 API 引发数据库负载：回滚 frontend 后停止新接口流量，再回滚 API；保留 additive 索引，不做紧急
  schema downgrade。
- 回滚不删除 localStorage、不修改 Occurrence/Current Analysis、不清理任何对象存储数据。
- 只有新前端与新 API 全部稳定后，才删除旧 `Page/Section` 内存导航代码；删除应是独立可审查提交。

## 13. 完成定义

- [x] `/` 在全新、旧缓存和失效缓存三种浏览器状态下都稳定进入平台主页。
- [x] 任意有效 Workspace/Occurrence/Build/Group URL 可直接打开、刷新、复制和前进后退。
- [x] Crash Inbox 可发现全部 Occurrence，包括无 Current、处理中和最近重试失败的条目。
- [x] Current Analysis 与 latest attempt 在 API、UI、筛选和测试中没有混用。
- [x] 同 Workspace 同 DMP 重传/reprocess 后 Occurrence 总数不增加。
- [x] OpenAPI、前端生成类型、设计文档和实际 wire JSON 一致。
- [x] 代表性 PostgreSQL 性能门槛和无 N+1 Gate 通过。
- [ ] 自动测试、Compose 深链测试和 UAT-P0X-01–12 全部 PASS。
- [x] 新 API + 旧前端兼容、前端优先回滚演练通过。
- [x] 证据明确区分源码/本机、Compose、目标内网和实际用户签署边界。

建议证据产物：

```text
docs/evidence/frontend-p0-api-contract-<date>.json|md
docs/evidence/frontend-p0-postgres-performance-<date>.json|md
docs/evidence/frontend-p0-browser-uat-<date>.md
docs/evidence/frontend-p0-go-no-go-<date>.md
```

只有上述完成定义全部勾选后，才把本计划状态改为 `Implemented`。

## 14. 建议提交拆分

1. `docs: freeze frontend p0 experience contract`
2. `feat(api): add occurrence browse read model`
3. `perf(db): add occurrence browse indexes`
4. `feat(ui): add stable platform and workspace routes`
5. `feat(ui): add platform home and crash inbox`
6. `test: gate frontend p0 deep links and occurrence semantics`
7. `docs: record frontend p0 rollout evidence`

每个提交记录执行的测试、未执行项和证据边界；不把本地 runtime、截图原图中的敏感信息、对象键、
预签名 URL 或凭据提交到仓库。
