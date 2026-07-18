# Deferred: bounded capability-facts repository query

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只收紧 `world.inspect(sections=["capabilities"])` 的公开投影：按 `task_id`
过滤，降低 invocation 与每类 related ref 上限，拒绝 URI、credential、Host path 等
locator-shaped ref，并在序列化后的 facts index 达到固定字节预算时 fail-closed 截断。

这仍没有解决 repository 读取成本。当前 `WorldInspectionService` 先通过现有 repository
方法构造完整 domain records，再仅取 count 和 ID：`engine_documents` 会读取并解析
`payload_json`，artifact 会读取 `metadata_json`，research evidence/source/gap 会把正文、
locator 与 provenance 一并实例化。把它改成只读窄列、SQL 端聚合和按 invocation 有界取 ref，
会新增跨多个 repository/table 的 projection ownership、查询 schema、索引、分页与兼容合同，
属于较大的架构调整。本提案只记录目标方案，不在当前 Goal 实现。

## Problem evidence

- `EngineDocumentRepository.list_by_invocation()` 使用 `SELECT *`，随后 `_row_to_document()`
  解析完整 `payload_json`；一个只需要 `document_id` 与 count 的 agent 查询仍会把大文档加载到
  Host 内存。
- `SessionArtifactRepository.list_by_invocation()` 构造完整 artifact record，包括不应进入
  capability facts 的 metadata；research evidence/source/gap repository 同样读取正文、query、
  snippet、locator、author/provenance 等列。
- session invocation 列表先读取全部匹配行，再由 service 做 task filter、requested limit、
  hard invocation cap 和 byte-budget truncation。公开输出有界，不代表数据库读取、JSON decode、
  Python object allocation 或查询时间有界。
- 当前局部修复以 deterministic newest-first 返回至多 20 个 invocation，但没有 cursor；长任务的
  旧 invocation无法按页读取。把 hard cap简单改回 oldest-first同样错误，因为会隐藏最新 outcome。
  需要稳定 cursor/snapshot语义，而不是继续扩大单页上限。
- `WorldInspectionService.inspect()` 目前在判断 `sections` 前就 eager 构造 task board、task、agent、
  signal、approval、operation、artifact 与 runtime audit。即使只请求 `capabilities`，无关 section
  的 session rows 和 rich artifact projection 也已经读取；单独优化 related query仍不足以形成
  端到端 bounded read。
- 一个历史 invocation 下的大 payload 或数十万 related rows 可以在返回第一个 facts page 前耗尽
  Host memory/CPU；公开 byte cap只能阻止 prompt 放大，不能阻止 read amplification。
- 直接给每个现有业务 repository 增加 ad-hoc `ids_only=True` 会复制排序、过滤与截断语义，且容易
  在新 related kind 加入时漏掉某一路径。

## Agent and harness impact

- agent 需要的是低摩擦、task-scoped 的 invocation 身份、状态、时间、输出 opaque ref、related
  count 和少量可发现 ID，不需要等待 Host 解析无法看到的 payload body。
- harness 应忠实呈现存在多少相关记录、哪些 refs 因 policy 被省略、是否因 page/byte budget 截断；
  不得因查询优化而猜测 workflow、隐藏 terminal outcome 或自动选择下一步。
- payload 很大不应改变 facts 查询的可用性。若数据库无法在受控预算内完成窄查询，应返回稳定的
  query-budget failure，而不是静默回退到 full projection 或无 task filter 的 session scan。
- 本能力保持 read-only；它不拥有 session、task、invocation、artifact 或 research 的顶层真状态。

## Target invariants

1. capability facts 查询只选择公开合同需要的窄列；SQL、row mapper 与 trace 中均不得读取或解析
   document `payload_json`、artifact `metadata_json`、evidence/source/gap 正文或 provider locator。
2. service 必须先解析 closed `sections`，再仅调用所需 read model；capabilities-only 请求不得
   eager 构造 task board、artifact list、runtime audit 或其他未请求 section。
3. `session_id` 必选，`task_id` 在 teammate 当前任务查询中必选；缺少/非法 filter 不能扩大为
   全 session scan。
4. invocation page 在 SQL 层应用稳定排序、hard limit 与 `limit + 1` 截断探测；service 不先加载
   全 session invocation records。
5. related count 在 SQL 层按 invocation/kind 聚合；每类 refs 在 SQL 层应用固定 per-invocation
   上限，不能先实例化全部 records 再切片。
6. 所有 ref 进入 public DTO 前仍执行严格 opaque-ID policy；query 层窄列不等于公开安全。
7. facts index 的最终 serialized-byte budget 继续由 public projection 层独立执行。SQL row limit、
   per-kind ref limit 与 byte budget 三层都必须存在，不能相互替代。
8. count 表示数据库中真实匹配行数；returned refs 表示经过排序、上限与 public-ref policy 后的
   子集。两者差异必须可解释，不能把 rejected locator 当作不存在。
9. 同一 snapshot 内排序 deterministic：invocation 使用 `(started_at, invocation_id)`，related
   ref 使用 `(created_at, opaque_id)`；并发写入不得导致同一 row 重复出现在相邻 page。
10. 查询不得引入 materialized mutable shadow table 作为第二套真状态。若使用 cache/index，必须
   可从 canonical tables 重建并以 transaction/change sequence 证明新鲜度。
11. query timeout、SQLite busy、schema drift、unknown related kind 或预算耗尽均显式 fail closed；
    禁止回退到旧 rich `SessionProjectionBuilder`。

## Proposed ownership and API

建议在 `openzyme-core` repository 层新增窄、只读的 `CapabilityFactsQueryRepository`，由
`CoreRepositories` 组合并被 `WorldInspectionService` 调用。它不复用 rich UI projection，也不
移动 canonical write ownership。

```text
CapabilityInvocationFactRow
  invocation_id / engine_name / task_id / lane_id
  status / approval_id / started_at / finished_at / output_ref

CapabilityRelatedCounts
  invocation_id
  document_count / artifact_count / evidence_count
  source_ref_count / gap_count

CapabilityRelatedRefRow
  invocation_id / related_kind / opaque_id / created_at

CapabilityFactsQueryPage
  invocation_rows[] / related_counts{}
  related_refs{} / has_more / snapshot_cursor
```

候选接口：

```python
query_page(
    *,
    session_id: str,
    task_id: str,
    after: CapabilityFactsCursor | None,
    invocation_limit: int,
    related_ref_limit: int,
) -> CapabilityFactsQueryPage
```

接口只接受已经由 tool boundary 验证的 opaque filter 和 server-owned hard limits。caller 不能
传任意 SELECT 列、排序、table 或 SQL fragment。

## Query shape

1. invocation query 从 `engine_invocations` 只选上述十个窄列，以
   `session_id = ? AND task_id = ?` 过滤，按 `(started_at, invocation_id)` 排序，并请求
   `hard_limit + 1` 行探测 `has_more`。
2. count query 对本页 invocation IDs 分别在五张 canonical table 做 `GROUP BY invocation_id`。
   可以使用固定 `UNION ALL` closed schema；不得把 table/column 名交给 caller。
3. ref query 只选择 ID、invocation ID、created_at、related kind。SQLite 可使用
   `ROW_NUMBER() OVER (PARTITION BY invocation_id, related_kind ORDER BY created_at, opaque_id)`
   并在 SQL 层过滤 `row_number <= related_ref_limit`。
4. service 按 invocation page 顺序组装 facts，再执行 opaque-ref sanitizer 与 canonical JSON byte
   budget。若某一 item 使 page 超限，停止追加并声明 `truncated=true`。
5. cursor 至少绑定 session、task、last started_at/ID、query schema version 与 stable snapshot
   identity。若单进程 SQLite 无法提供跨请求 snapshot token，第一阶段可以只支持单次 bounded
   page并明确 `cursor_consistency=best_effort`，不得伪称 snapshot isolation。
6. `WorldInspectionService` 根据已验证的 section set lazy 调用对应 query；只有显式请求
   `diagnostics` 才执行 runtime audit，只有显式请求 `tasks` 才构造 task board。section routing
   自身不缓存或拥有业务状态。

## Index and SQLite considerations

- 审计或新增 `engine_invocations(session_id, task_id, started_at, invocation_id)` 复合索引，避免
  task-scoped facts page退化为全 session scan。
- 五类 related table至少需要 `(session_id, invocation_id, created_at, id)` 可覆盖排序/计数的
  索引；是否增加 covering index由 `EXPLAIN QUERY PLAN` 和真实规模基准决定。
- invocation ID列表必须有 server-owned 小上限，使用固定 placeholder expansion；不得把数万 ID
  写入一个 `IN (...)`。
- 当前产品保持单进程 SQLite。本提案不引入外部 cache/database，也不以未来多进程需求扩大本次
  ownership。
- query budget应覆盖 statement timeout/interrupt、row count和组装时间；SQLite busy应沿现有
  typed runtime error taxonomy暴露，不在 read path执行隐式重试风暴。

## Migration plan

1. 为现有实现加入只读 instrumentation/benchmark，记录 SQL rows、JSON decode 次数、Host RSS、
   latency和最终 public bytes，建立 rich-load amplification 基线。
2. 定义 `capability_facts_query@1` closed DTO、排序、count/ref语义、cursor和稳定错误码；补 SQL
   statement snapshot tests，明确禁止列清单。
3. 实现窄 invocation query 与复合索引，在 shadow mode 同时运行旧逻辑，逐字段比较小型 fixture；
   shadow结果不进入 agent context。
4. 实现 SQL aggregate counts 与 per-kind windowed refs；对 zero/one/many、unsafe ID、并发插入、
   deleted rows和相同 timestamp做 differential/property tests。
5. 把 `world.inspect.capabilities` 切到 query repository，保留现有 public sanitizer、hard limits、
   page metadata和byte budget；任何 shadow drift先阻断切换。
6. 把 `WorldInspectionService` 改为 section-directed lazy reads，证明 capabilities-only path不读取
   task board、agents、signals、approvals、operations、session artifact list或runtime audit。
7. 移除 capability path 对五类 `list_by_invocation()` rich methods 的调用，并用 spy/trace测试证明
   payload row mapper零调用。
8. 真实大表压力验证后再考虑 cursor pagination；确认没有外部调用方依赖旧无 cursor map shape后，
   允许纠正性 breaking schema revision。

## Compatibility and rollout

- 第一阶段 public `world.capability_facts.page.v1` shape不变，只替换 read implementation；旧 rich
  workspace/API projection继续服务 UI，不与 agent facts query合并。
- 若引入 cursor或新的 truncation reason，发布显式 page schema revision；不得让旧 client把
  `has_more` 缺失解释为完整结果。
- rollback只能回到上一个明确版本的 bounded query；不能回到 full payload hydration并仍宣称相同
  resource contract。
- schema/index migration必须兼容现有单进程 SQLite备份与恢复；失败时 Host启动/health显式报告，
  不在查询时临时创建索引。

## Risks and mitigations

- **N+1 变成复杂 UNION**：固定 related-kind registry与 statement tests，禁止动态 SQL；以 query
  plan/benchmark选择一条 page query加有限 aggregate/ref queries。
- **count 与 refs跨 statement漂移**：在同一 read transaction/snapshot内完成一页；无法证明时在
  metadata声明 consistency，GO verifier不把该 page当 sealed evidence。
- **covering index增加写放大**：先测真实规模，新增最小复合索引；facts read性能不能以破坏
  canonical write latency为代价。
- **opaque sanitizer丢弃合法 legacy ID**：先审计实际 ID corpus，按显式 breaking policy迁移；
  禁止为了兼容重新允许 URI、credential或Host path。
- **projection repository变成新业务层**：只返回 immutable read DTO，不保存状态、不决定 workflow、
  completion或approval。
- **byte cap与SQL page cap不一致**：page metadata同时报告 matching、considered、returned、max bytes
  和 truncation；property tests覆盖所有组合。

## Acceptance criteria

- SQL trace证明 capability facts path从不选择 `payload_json`、`metadata_json`、summary、query、
  locator、snippet、authors/provenance等body列，也不调用相应 rich row mapper。
- repository spy证明 capabilities-only path零调用 task board、agent/signal/approval/operation/artifact
  session list与runtime audit；添加其他未请求 section不会发生隐式读取。
- 单个document payload为1 GiB、artifact metadata为100 MiB时，facts page的Host RSS和latency与
  payload大小近似无关，公开结果仅含count与bounded opaque IDs。
- 每个invocation拥有至少一百万related rows的压力fixture中，数据库返回到Python的ref rows仍不
  超过 `invocation_limit * related_kind_count * related_ref_limit`，count准确且查询按预算完成。
- `EXPLAIN QUERY PLAN`在真实schema下命中task/invocation复合索引，不出现全表payload scan或临时
  body materialization。
- unsafe URI、credential、Host path、超长/非法字符ID永不进入public JSON；counts仍反映其存在。
- task filter、稳定排序、limit、byte budget、truncation和并发写入测试均deterministic，未知schema
  或query timeout返回stable fail-closed error。
- rich UI projection与新的agent facts query做边界测试：前者可按授权读取正文，后者无任何body
  hydration authority；二者不共享会意外扩大agent surface的fallback。

## Explicit non-goals

- 不改变task、invocation、artifact或research canonical write repository与顶层真状态。
- 不让`world.inspect`成为planner、workflow template选择器或business completion decider。
- 不把UI rich projection删除或暴露给agent。
- 不引入PostgreSQL、Redis、外部搜索索引或多进程runtime。
- 不把facts page、count或cursor当作sealed scientific evidence或GO attestation。
