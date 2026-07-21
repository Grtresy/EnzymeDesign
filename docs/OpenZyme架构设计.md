# OpenZyme 主线架构设计

## 1. 文档定位

本文档描述当前根仓库主线的 OpenZyme V3 架构边界与实现事实。

它回答四类问题：

1. 当前主线仓库保留哪些系统能力
2. V3 当前产品真状态与顶层架构如何分层
3. 一次 session 在 Host、Harness、Agent Runtime、Capability Engines、Storage、UI 之间如何流动
4. 当前哪些机制已经落地，哪些仍是切换期约束或未完成证明

当前主线采用 V3 的
`session + task board + lane/workspace + approval + resident teammates + explicit runtime commands`
语义。旧 `episode + phase graph` 产品面、接口、包和规格已经从主线删除；新产品行为不再以
`intake -> design -> report_review` 作为顶层真状态，也不再维护双栈兼容入口。

部署边界采用显式双 profile：`local-dev` 只允许 loopback 且使用固定本地 principal；`shared` 必须配置 Bearer principal、project allowlist 与 role，并以 SQLite `SessionAccessRecord` 保存 session owner/access 真状态。共享模式的 mutation 强制 `Idempotency-Key`，approval/lane actor 由 Host 认证结果确定；debug 默认关闭，启用后仍要求 operator/admin 且只返回脱敏记录。近期运行边界仍是单进程、file-backed SQLite，不把该 profile 设计误称为多进程扩展已经完成。

`local-dev` 只放宽本地认证，不放宽科学真实性：configured Host 缺真实 execution/research backend 时保留 unavailable 能力或返回结构化失败，绝不自动装配 deterministic success。deterministic adapters 只能由 `build_local_eval_foundation()` 或 `dev_web_ui --fixture-non-cutover` 显式选择，所有 outcome 必须标记 `fixture_non_cutover`、`synthetic_source=true`、`cutover_eligible=false`。`dev_web_ui` 默认走 configured foundation；未配置 execution backend 的默认值是 `disabled`。bio research service 为 `None` 时不注册对应工具，不能隐式创建 fixture service。

V3 稳定文档入口见：

- [docs/v3/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/README.md)
- [docs/v3/00-harness-doctrine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/00-harness-doctrine.md)
- [docs/v3/01-target-architecture.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/01-target-architecture.md)
- [docs/v3/02-control-plane.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/02-control-plane.md)
- [docs/v3/03-capability-engines.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/03-capability-engines.md)
- [docs/v3/04-public-interfaces.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/04-public-interfaces.md)
- [docs/v3/05-agent-runtime.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/05-agent-runtime.md)
- [docs/v3/06-top-level-llm-loop.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/06-top-level-llm-loop.md)
- [docs/v3/07-runtime-hpc-reliability.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/07-runtime-hpc-reliability.md)
- [docs/v3/runtime-hpc-reliability-operations.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/runtime-hpc-reliability-operations.md)

本文档是主线架构入口；`docs/v3/` 是 V3 主题细则。若两者与当前代码实现出现差异，必须同时核对代码、V3 稳定文档与最近验收事实后修正文档或实现，不能用旧 workflow 叙述压过当前 V3 代码事实。

---

## 2. 当前主线边界

本仓库是基于 `uv` 的 Python monorepo。应用入口位于 `apps/`，共享库位于 `packages/`，Python 子项目采用 `src/` 布局。

当前主线保留的主要应用：

- `apps/openzyme-host-api`：FastAPI Host API，包含 V3 `/v3` 产品接口；作为 HTTP/SSE composition root 装配 repositories、engine registry、runtime foundation、background worker 和 runner server，评测/fixture 模块仅保留迁移兼容，不再作为新增 V3 runtime/eval 逻辑落点
- `apps/openzyme-host-cli`：Thin CLI client
- `apps/openzyme-web-ui`：浏览器工作区 UI
- `apps/mcp-hpc-runner`：SSH/Slurm/HPC runner 边界

当前主线 V3 优先落点：

- `packages/openzyme-domain`：control-plane 领域对象，如 `Session`、`Task`、`Lane`、`ApprovalRequest`、`InboxMessage`、`AgentMember`、`AgentRuntimeSignal`、`ControlledOperationExecution`、`RuntimeCommandRecord`、`ContinuationState`、`MutationScope`、`MutationWriter`、`MutationQuiescenceReceipt`、`EngineInvocation`、`RunRecord`、`SessionArtifactRecord`、`SessionReportDraftRecord`、`SessionReportRecord`
- `packages/openzyme-core`：V3 harness、task board、lane manager、protocol、projection、agent runtime、scheduler、tool registry、report draft tools、docs tools；对 runtime SPI 保留旧 public import 的兼容重导出
- `packages/openzyme-engines`：capability engines，尤其是 execution pipeline engine 与 sandbox supervision；不得依赖 `openzyme-core` 的 concrete harness 类型
- `packages/openzyme-pipeline`：受控 execution pipeline sandbox 内 SDK
- `packages/openzyme-research`：research provider 与 research capability 相关实现
- `packages/preprocess-backend`：受控 preprocess 能力后端

共享能力包：

- `packages/openzyme-runtime`：settings、LLM、limits、research seams、engine/tool SPI、artifact projection / artifact boundary service、static route policy 等无顶层产品真状态的 runtime seam
- `packages/openzyme-tools`：HPC catalog 的唯一权威来源、tool execution contract、command rendering、RunSpec compiler helper 与 result parser
- `packages/openzyme-execution`：runner adapter normalization；不得直接依赖 `apps/mcp-hpc-runner`，真实 runner server 由 Host API composition root 注入

这些包不拥有顶层产品真状态。新增产品状态、协议、调度、workspace projection、report draft、execution pipeline 语义时，默认应优先放在 V3 harness/control-plane 相关包中。

---

## 3. V3 核心结论

### 3.1 顶层真状态是 Control Plane，不是 Graph

V3 的产品真状态由 Host control plane 持久化，并通过 workspace projection 对外暴露。核心对象包括：

- `session`
- `task`
- `lane`
- `approval`
- `inbox`
- `agent_member`
- `agent_runtime_signal`
- `controlled_operation_execution`
- `runtime_command`
- `continuation_state / continuation_delivery`
- `mutation_scope / mutation_writer / quiescence_receipt`
- `engine_invocation`
- `artifact`
- `run`
- `report_draft`
- `report`
- `research evidence / source refs / gaps`

LangGraph / LangChain 可以继续作为 `deep_research`、局部 research loop 或其他内部能力实现工具，但不能重新成为 V3 产品级 workflow truth owner。

### 3.2 用户只与 Master 对话，Teammate 是内部团队成员

V3 默认角色模型：

- 用户是甲方
- OpenZyme 是乙方
- `master agent` 是对外负责人，理解用户目标、创建 task、委托 teammate、汇报结果
- `teammate agent` 是内部执行者，围绕明确 task/lane/correlation 推进研究、执行或报告
- `harness` 是系统层，负责状态、协议、约束、恢复、工具分发和投影

当前固定 teammate roster 为：

- `researcher`：literature and data research
- `executor`：approved computational execution
- `reporter`：report drafting and publishing

不要把 provider tools 或 capability engines 说成 teammate；例如 fpocket、Vina、PubMed、UniProt、RCSB PDB 是工具/能力/数据源，不是 agent team 成员。

### 3.3 Resident Teammate 不等于常驻 LLM 进程

V3 的 teammate 是 resident agent member，常驻的是 identity、role、status、task focus、inbox、protocol thread、memory 和 workspace 读视野；LLM loop 只在明确 wakeup signal 被 scheduler claim 后执行 bounded turn。

当前实现已经具备：

- `AgentRuntimeSignal` 持久化 signal queue
- `AgentRuntimeScheduler` claim lease、bounded drain 和并发限制参数
- stale claim recovery、attempt 计数、失败记录和 duplicate wakeup dedupe 相关 repository 覆盖
- FastAPI lifespan 中的单进程 `V3BackgroundRuntimeService`，通过 durable signal + in-process notifier 自动唤醒 scheduler
- 单进程 `V3DurableWorkSupervisor`，分别运行 runtime-command、controlled-operation、continuation-delivery 等短 claim worker
- 显式 `POST /v3/sessions/{session_id}/runtime/drain`，作为 durable debug/operator/manual recovery command admission

当前默认产品路径是：REST handler 持久化状态并排队 `AgentRuntimeSignal`，后台 runtime service claim pending 或 expired-lease signal 后启动 bounded master / teammate turn。显式 `/runtime/drain` 只原子写入 durable command/outbox，始终返回 HTTP `202`；独立 `RuntimeCommandWorker` 再认领 command 并调用 bounded scheduler，调用方通过 session-scoped GET 查询结果。HTTP request、command、signal claim 和 session lease 都不拥有 approval、provider、sandbox 或 HPC wall time；旧同步 response fallback 已退休。

message admission 与 runtime 推进解耦时，结构化 focus 的 canonical truth 仍属于 source message，而不是 signal 或 worker 内存：显式 `skill_keys` 去重后写入同一 user conversation document，signal 只保存 `source_ref`。master 在进入 `working`、发出 `agent.woken` 或调用 provider 前，必须从 exact source 恢复；public user-message 的 participant/session/document identity 任一损坏都 fail closed。普通 agent protocol inbox 可以唤醒 master，但不携带 workflow authority；background worker 与手动 `/runtime/drain` 走相同恢复规则，均不能注入或合并 refs。

### 3.4 No Hidden Fallback

V3 默认失败策略是显式失败传播，而不是隐藏 fallback。

要求：

- provider/model/runtime 异常不得被静默吞掉并伪造成成功
- 工具参数错误返回 LLM 可读的 structured tool error observation
- 意图不清或前置条件不满足时，应让 task/approval/protocol 表达 blocked/failed/needs clarification
- 不得通过隐藏 fallback 重新打开 blocked action、替换用户目标、默认选择可运行工具或合成虚假 plan
- bounded loop 到达上限可以标记 runtime signal/agent failure，但不能据此推断业务 task 已完成或失败

所有 `structured`、`tool_calling`、`chat` 与 connectivity smoke 的 provider 调用都必须经过 `openzyme_runtime.LlmInvocationRuntime`。invoker 只负责构造 payload、结构化解析或 tool response 还原；runtime 统一负责 limiter、timeout、retry/backoff、`Retry-After`、错误 taxonomy 与 LLM debug 记录。502/503/504、transport timeout/connection failure 属于 retryable；429 只有 transient 或带 `Retry-After` 时 retryable，usage/quota/invalid/context 类 429 不重试；400/401/403、schema/tool argument/context window 错误不重试。runtime 不拥有 session compaction、restore context rebuild 或 harness/engine 状态机。

tool-calling provider schema 必须经过 `openzyme_runtime.ProviderToolAdapter`。OpenZyme 内部 truth 是 dotted canonical `ToolSpec.tool_name`，例如 `task.create`、`execution.pipeline.start`；adapter 将 canonical `ToolSpec` 投影为 provider-visible tools，并输出 `canonical_to_provider` / `provider_to_canonical` 映射。MICU 的 `task.create -> task_create` 这类 dotted alias 只存在于 adapter 生成的 provider request 与 LLM debug 记录中；provider response 返回后必须先恢复 canonical tool name，再进入 driver、`ToolRouter.dispatch()`、tool invocation、tool result、workspace `agent_traces` 与 `tool.invoked` / `tool.completed` events。非 MICU / 不需要 alias 的 OpenAI-compatible base URL 保持 canonical 名称。

### 3.5 Token-Budgeted Harness

V3 master / teammate LLM 调用必须先经过统一 token budget preflight。harness 按模型 profile 估算完整 prompt，包括 system prompt、conversation/messages、tools schema 和 tool observation；达到 80% 记录 warning，达到 85% 自动写 bounded session/lane compaction 并刷新 restore context，达到 90% 显式返回 `context_budget_exceeded`，不得把超限 prompt 交给 provider。prompt-budget compaction 改变的是后续 LLM restore prompt projection，不删除或改写持久 conversation history，也不改变 workspace conversation read model。

当工具结果本身或加入该结果后的下一轮 prompt 超预算时，完整 tool result 写入 `engine_documents(document_kind="tool_result_full")`，并登记为 `ArtifactKind.RESULT` artifact。LLM 只收到小型 observation，包含 `tool_result_context_over_budget`、`original_tool_ok`、`original_status`、`artifact_id` 和 `read_hint`。这不是业务失败判定，也不自动摘要原始 payload；agent 需要时通过 `artifact.get` 分页读取完整结果。

### 3.6 本地 V3 SQLite State 的兼容策略

开发与本地手动测试使用的 V3 SQLite 文件是 runtime/control-plane state，不是长期归档格式。当前主线只支持两类启动输入：

- fresh empty SQLite：启动时按当前 migration 列表初始化，并写入 `PRAGMA user_version`
- current-version SQLite：启动时校验关键表存在后复用

旧 schema、未知 schema、非空但未标记 `user_version` 的 SQLite 文件不做隐式迁移、修复、备份或删除；启动路径必须 fail fast，并提示 operator 手动删除旧库或指定新的 `--v3-sqlite-db` 路径。除既有 task-integrity 与 durable-event trigger 外，`026` 至 `031` migrations 已把 canonical controlled-operation execution、runtime command/continuation、dispatch request、immutable result artifact、mutation authority/snapshot 及其约束纳入 current schema 校验。因此升级后的旧本地库也必须按上述 fresh/current-version 规则处理，不能绕过 trigger 校验继续运行。需要长期保留的研究结果、execution 输出与报告应通过 artifact、report 或 export 留存，而不是依赖旧 SQLite runtime 文件跨 schema 版本继续可用。

Python import shim、CLI alias、`execution.pipeline.*`、Podman runner、runtime/tools/execution 包 seam 与旧 HTTP/runner call shape 的 sunset 证据统一由 `scripts/audit-v3-compat-callers.py` 和 `docs/v3/compatibility-sunset.md` 管理。仓库内零 caller 只证明当前 checkout，不证明外部零 caller；所有 `DEPRECATE` / `RETIRE-BLOCKED` surface 在 external inventory/telemetry/owner evidence 仍为 unknown 时必须保留。已经不存在的 `/v1`/`/v2`、raw runner lifecycle 参数和 legacy workspace activation 标为 `RETIRED` 防回归，不得把归档源码本身误删。

单进程不等于共享一个 SQLite connection。Host 以 file-backed `SQLiteRepositoryProvider` 为 composition root；每个 request、background worker、scheduler bounded turn 与 sandbox SDK control callback 都在实际执行线程内创建并关闭自己的 thread-affine connection。纯读使用 `query_only` read scope；不跨外部边界的 canonical command 使用短 `BEGIN IMMEDIATE` Unit of Work，使多个 repository mutation all-or-nothing；可能等待 LLM、provider、runner 或 sandbox 的长流程只能使用无长事务的 connection scope，由内部短写自行提交，严禁持有 SQLite write lock 跨外部调用。WAL 与 `busy_timeout` 只改善单进程并发，不替代 ownership、UoW 或后续 fencing。

scheduler 持有 session runtime lease 期间必须按 TTL 的有界分数持续 heartbeat；blocking provider call 在 worker thread 中执行时 coordinator event loop 仍负责续租。file-backed Host 的每次 heartbeat（包括 contention retry）都使用新建并及时关闭的独立 repository connection，不能复用 coordinator 或长时 worker scope；只把 SQLite `BUSY` / `LOCKED` 视为瞬态，并以 capped backoff 持续重试到成功或当前 lease expiry，其他异常显式传播。repository 必须先取得 SQLite writer lock，再计算 heartbeat/acquire 的 `now` 与新 expiry；锁等待跨过旧 expiry 时不得复活旧 lease。确认 lease 已丢失或 observed expiry 已到达即停止续租，但 cleanup 仍必须恢复 context 并 release 可释放的 row。worker、它重建的 engine registry 以及 sandbox SDK control/adapter/HPC fetch callback 的每个 connection scope 都绑定同一 `session_id + lease_token + fencing_token`。write/approval/external tool 在 dispatch 前检查 lease；每次 repository commit 再次检查 lease 仍 active，session-scoped repository 写还必须等于 lease session。lease 丢失或被更高 fencing token reclaim 后，旧 worker 的 task、agent、protocol、engine、run、artifact、report、event 等迟到写入一律以 non-retryable `runtime_write_fenced` 失败；已经开始但超时返回的 callback 也不能应用 late business effect。fencing 只拒绝 canonical 写回，外部系统重试仍必须依赖 operation digest、idempotency key 与 opaque run handle，不能把 fencing 冒充外部取消。

V3 public event log 不是 Host 进程内缓存。`durable_event_records.cursor` 是数据库分配的单调游标；事件、对应的短 canonical mutation 与可选 `command_receipt_records` 在同一 UoW 提交，rollback 不得泄漏 SSE event。event rows 只能 append，receipt rows 完成后不可更新或删除；`event_id` 全局唯一，`llm.response.created` 的 `trace_id` 在 session 内唯一。SSE 以 cursor 作为 `id:`，通过 `after_cursor` 或 `Last-Event-ID` 从 SQLite 重放，Host 重启不得改变既有 event id/cursor。所有 `/v3` mutation 接受 `Idempotency-Key`：同 scope、command type、key 与相同 request digest 返回首次完成响应且不重做副作用；同 key 不同 digest 返回冲突。local-dev 当前允许省略 key；shared profile 的强制认证阶段将同时把 key 设为必需。

### 3.7 Runtime/HPC 的 authority 与静默闭包

可靠性主线把四种 authority 明确分开：session runtime lease/agent signal claim 只拥有一次 bounded agent turn；execution lease/fence 只拥有一次 external-effect lifecycle；continuation delivery claim/process epoch 只拥有 exact result 向 exact attached process 的一次投递；mutation scope generation/writer fence 只拥有 canonical evidence 的写入与静默封存。任一 authority 的 idle、expiry 或 terminal 都不能推断其他 authority，更不能自动写入 task 业务终态。

`ControlledOperationExecution` 是 durable operation 唯一 external-effect owner。worker 只做短 claim/dispatch/poll/materialize slice，外部调用前重新检查 fence，且不持 session lease 或 SQLite transaction跨外部 wall time。恢复只允许在 proven `no_effect` 的同一 phase 内有界进行；direct SSH payload 已写出却丢失响应时进入 `dispatch_in_doubt`，只能 reconcile，不能 replay。

generic mutation closure 先 freeze admission 并推进 fence，再等待每个显式 writer/descendant 退休，获取两次一致的 bounded SQLite/event/artifact/report/live-ledger snapshot，签发 immutable receipt，最后 seal exact generation。runtime idle、空队列、HTTP 返回、timeout 或 missing handle 都不是 writer retirement 证明；seal 也不表示 task completed。完整合同见 `docs/v3/07-runtime-hpc-reliability.md`，迁移和回滚步骤见 `docs/v3/runtime-hpc-reliability-operations.md`。在 deterministic、non-live 与经单独批准的 real-SSH transport-only soak 全部通过前，`rxx` campaign 保持冻结。

---

## 4. 顶层架构

当前 V3 主线分层如下：

```text
User
  |
  v
React Web UI / Thin CLI / API Client
  |
  v
FastAPI Host API
  |
  v
V3 Host Control Plane
  |
  +--> session manager
  +--> task board
  +--> lane manager
  +--> approval protocol
  +--> inbox / team protocols
  +--> agent roster
  +--> shared workspace / artifact catalog
  +--> report draft / report records
  +--> event log / projection builder
  |
  v
Agent Runtime / Scheduler
  |
  +--> durable runtime signals
  +--> claim lease / stale recovery
  +--> bounded master turns
  +--> bounded teammate turns
  +--> background signal drain
  |
  v
Durable Work Supervisor
  |
  +--> runtime command worker
  +--> controlled-operation execution worker
  +--> continuation delivery worker / attached-process registry
  +--> mutation writer retirement and recovery
  |
  v
Agent Harness Kernel
  |
  +--> top-level master loop
  +--> role-scoped teammate restore context
  +--> tool registry and tool result envelope
  +--> token budget preflight / bounded compaction
  +--> over-budget tool result artifactization
  +--> docs.search / docs.read
  +--> protocol.send / protocol.thread
  +--> task.delegate / task.update
  |
  v
Capability Engines
  |
  +--> deep_research / provider tools
  +--> sandbox.workspace.* / sandbox.file.* / sandbox.exec / openzyme_pipeline SDK
  +--> execution pipeline internals and migration bridge
  +--> report_draft.* / report.publish
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> artifact store
  +--> event log
  +--> rootless Podman sandbox
  +--> mcp-hpc-runner / per-target ControlMaster / SSH / Slurm
```

顶层边界：

- Web UI / CLI 不持有 workflow truth；它们消费 Host API 和 workspace projection
- Host API 是共享入口，`/v3` 是当前产品语义面
- Control plane 持有跨对话、跨压缩、跨后台执行仍然成立的 canonical objects
- Agent runtime/scheduler 负责消费 wakeup signals，不决定业务任务内容
- Durable work supervisor 负责独立推进 command、external effect 与 result delivery；这些 worker 不借用 agent session lease 表示自身 ownership
- Harness kernel 负责 top-level loop、工具分发、restore context 和协议推进
- Capability engines 是被 harness 调用的专业能力，不拥有产品顶层真状态
- HPC runner 仍是外部执行边界，不被 Host 或 executor 直接替代

---

## 5. 一次 V3 Session 的主路径

典型 V3 主路径如下：

```text
POST /v3/sessions
  -> create session
  -> workspace projection

POST /v3/sessions/{session_id}/messages
  -> persist user message
  -> ensure resident agent:master
  -> queue agent:master AgentRuntimeSignal
  -> return without running master or teammate loop

POST /v3/sessions/{session_id}/runtime/drain
  -> validate access, strict request and Idempotency-Key
  -> atomically admit RuntimeCommandRecord + outbox
  -> return HTTP 202 + command_id + status_url

V3DurableWorkSupervisor / RuntimeCommandWorker
  -> claim one accepted command
  -> AgentRuntimeScheduler claims pending signals with session lease
  -> if signal is agent:master, run bounded top-level master loop
  -> if signal is teammate, wake focused resident teammate
  -> agent reads task / lane / inbox / protocol / workspace
  -> master creates / updates tasks and delegates with task.delegate
  -> teammate calls role-scoped tools or capability engines
  -> task / artifact / run / report draft / approval state updates
  -> terminal teammate outcome queues agent:master wakeup
  -> terminalize command when bounded batch finishes, fails, locks or parks work

GET /v3/sessions/{session_id}/runtime/commands/{command_id}
  -> return closed, redacted command status/outcome

GET /v3/sessions/{session_id}/workspace
  -> project current canonical state for UI / CLI

GET /v3/sessions/{session_id}/pending-approvals
  -> project only durable approval / operation / sandbox identity for control polling
```

关键约束：

- `POST /v3/sessions/{session_id}/messages` 是用户到 master 的入口，只持久化用户消息（含该消息显式选择并去重的 `skill_keys`）并排队 `agent:master` wakeup，不直接执行 master loop，也不隐式执行 bounded teammate runtime drain；每条 signal 只从自己的 exact source message 恢复，focus 不跨消息 sticky/union
- `POST /v3/sessions/{session_id}/runtime/drain` 是 debug/operator/manual recovery 的显式 durable command admission；它必须带 `Idempotency-Key`，只接受 closed limits，始终返回 `202`，不得绕过 command worker 直接运行 agent loop。可选 `Prefer: wait=0..2` 只短暂等待 command 状态，不改变 ownership 或取消语义
- `task.delegate` 是产品-facing delegation tool，但真实写路径是 `ProtocolService.delegate()`
- `protocol.send` 只投递消息并排队 wakeup signal，不同步运行 recipient
- `auto_enqueue_ready_tasks` 默认关闭，只用于显式 operator/debug/recovery 场景
- approval resolve 只改变 approval/resolution/continuation 状态并排队必要 wakeup，不直接恢复 execution、不直接运行 master loop，也不直接替用户或 agent 批准后续未知动作
- `world.inspect` 是 agent-facing 结构化世界读取工具，只暴露事实、约束、tool schema、route policy、approval requirement、outcome 与 runtime diagnostics；不得输出 `recommended_actions` 或替 agent 判断 workflow / 完成条件。teammate 的 `capabilities` 视图必须绑定当前 task，显式跨 task filter 返回 typed error；master 保留既有显式 session-wide 读取权限。该 facts page newest-first，最多 20 个 invocation、每类 8 个 closed opaque refs、serialized facts 最多 64 KiB，只内联 identity/status/timestamp/count/ref；不得把文档正文、output payload 或 evidence body 重新塞进 prompt context。当前实现仍会 hydrate rich repository rows，窄列 query、lazy sections 与 cursor 属于 `docs/v3/architecture-proposals/bounded-capability-facts-query.md` 的后续大调整
- 通用 harness 不按 AOX/HMM、research 或其他领域关键词注入 recipe、改写 delegation 或剥夺工具。领域 SOP 进入 `docs/v3/workflow-packs/*.workflow.json`：只有 caller 显式提交完整 `workflow:<id>@<semver>#sha256:<manifest-digest>` 才会选择；manifest 固定 knowledge document version/digest，并声明 capability/tool requirements。`task.delegate.workflow_refs` 只能显式选择 caller 当前授权 refs 的无重复子集；省略或 `[]` 表示不绑定，不能把 parent focus 的全部 workflow 隐式传播给 teammate。claim 前校验 target role/tool/engine 与 manifest snapshot，teammate restore 再校验 drift；失败保持 task、agent、inbox、signal 无副作用。blank-world collector 还必须从 durable delegation document 重建 role-scoped binding：AOX executor 精确绑定 campaign workflow ref 和完整 manifest snapshot，researcher/reporter 必须保持空绑定；bundle verifier 对 snapshot 的 core/content digest 离线复算。模型的 `skill.load` 不能自行激活 workflow pack，agent 在版本化真实约束内仍保留策略自由
- terminal task 上残留的 wakeup signal 是 stale runtime fact，应被安全消费为 completed signal，不应再次驱动 teammate loop 或制造 runtime failure
- controlled operation 进入 terminal 后，对应 `inv_sandbox_adapter_<operation_id>` engine invocation 必须稳定进入 terminal；该不变量只收口 runtime 状态，不代表业务 task completed

---

## 6. Public Interfaces 与 Workspace Projection

当前 V3 主要公开接口：

- `POST /v3/sessions`
- `GET /v3/projects/{project_id}/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `POST /v3/sessions/{session_id}/runtime/drain`
- `GET /v3/sessions/{session_id}/runtime/commands/{command_id}`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/pending-approvals`
- `GET /v3/sessions/{session_id}/events`
- `GET /v3/runtime/health`
- `POST /v3/approvals/{approval_id}/resolve`

Public HTTP contract 使用 strict request DTO 与显式 response DTO：未知字段、非法 enum、空 update 与长度越界统一返回 `422`，所有错误统一投影为 `error.code/message/hint/details`，不再混用 FastAPI `detail` 字符串。approval actor 与 lane claimant 只取认证 principal，调用方提交 identity 字段会被 DTO 拒绝。`GET /v3/runtime/health` 只返回 `v3.runtime_health.v1` 的脱敏 component 状态和 deployment/storage profile；worker id、原始错误、Host path、runner config 与 secret 只能留在受保护的 debug/内部边界。

SSE 保留默认的 typed-event 模式，并提供 `envelope=1` 的稳定 generic 模式：SSE name 固定为 `openzyme.event`，真实类型在 JSON `event_type` 中。Web UI 使用 generic envelope，因而新 event type 不依赖前端 allowlist；cursor、`Last-Event-ID`、visibility 与 restart replay 契约不变。CLI 与 Web UI 的 mutation 自动生成 `Idempotency-Key`，浏览器 approval body 不再携带 client-owned `actor_ref`。

`GET /v3/sessions/{session_id}/workspace` 是 UI/CLI 的 canonical snapshot，至少包含：

- `session`
- `conversation`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `agent_traces`
- `activity_feed`
- `artifacts`
- `report_drafts`
- `reports`
- `capabilities`

Projection 约束：

- conversation 只表达用户与 master 的产品级对话
- teammate 输出、工具调用、trace 和 protocol thread 通过 `agent_traces`、`delegation`、`activity_feed`、`inbox` 等 read model 表达
- `delegation.agents` 表达 resident team roster，而不是最近一次 `task.delegate` 的临时返回
- `artifacts` 是 session 共享工作面；session workspace 属于 collection read model，`artifacts`、`artifact_index.latest`、`activity_feed` artifact payload 与 capability-run artifacts 统一复用 `artifact.list` 的 deterministic bounded item projection。完整 canonical metadata 仍原样保存在 Artifact row 并通过 `artifact.get` 分页读取，workspace 只内联短 identity/scalar/small-container 与 versioned digest/count/size/omission/read hint；大 accession、sequence/page digest、identity mapping 或 file manifest 不得在多个 workspace branch 线性重复。`storage_uri` 只属于 Host-private catalog record，workspace/API/agent tool result 只能暴露安全 artifact 投影，不能暴露 Host repo path、Host artifact path、sandbox host path、runner private path、SSH/Slurm config 或 runner credentials
- mutation 内的 derived activity-event backfill 只能构造 sanitized activity projection，不能递归调用 composite workspace；approval resolve 可继续返回 bounded workspace command result，但 SQLite write transaction 不得随无关 Artifact metadata 的多分支全量回显线性放大
- 外部 provider 下载进入 control plane 时默认登记为 sealed artifact，metadata 记录实际 bytes 的 SHA-256 `content_digest` / `sealed_digest`、provider、external id/source locator、format、retrieved_at 与 provenance；executor sandbox 内的 `rcsb_pdb.download_structure` 走 `rcsb_pdb.download_structure.provider:v1` 受控 provider operation，由 Host 下载、校验和登记结构 artifact，sandbox 不直接联网；`hpc.stage_artifact` 只消费 catalog 授权和 sealed digest，fpocket/FASTA/PDB 等业务输入合法性由后续 capability tool 校验
- 执行相关源码必须可审计：executor 日常编辑发生在 persistent sandbox workspace 内；进入 dry-run、approval、正式执行或报告复用前，Host 必须把相关源码 snapshot 为 `ArtifactKind.CODE` artifact，记录 `metadata.semantic_type="pipeline_source"`、SHA-256 `content_digest`、`sandbox_workspace_id`、entrypoint、file digests 与 version/lineage metadata
- `report_drafts` 是 reporter 的中间交付面，不是一次 invocation 的临时字符串
- `capabilities` 按 capability key 承载 research/execution 等投影，避免把 engine 内部状态固化成顶层 contract
- `runtime_state` 是 diagnostic-only projection；agent 若需要低摩擦读取完整世界事实，应通过 `world.inspect` 查询 task、artifact、operation、approval、outcome、signal、tool surface 和 route policy，而不是从 prompt 片段或 artifact 名称中猜测

---

## 7. Control Plane、Protocol 与 Runtime

### 7.1 Task 与 Delegation

`Task` 是 session 内可调度、可委托、可恢复、可完成的内部工作单元。默认由 master agent 基于用户对话创建和编排。

`task.delegate` 的职责：

- 校验 task 是否存在
- 校验 teammate role 是否有效
- 拒绝 blocked、already assigned、非 `todo` task
- 使用 `agent_role` 表示能力选择，使用可选 `agent_ref` 解析已有 canonical teammate；不得接受 role 字符串作为 `agent_id`
- 在需要新 teammate 时创建 canonical `agent:<role>:<opaque-id>`，分配 role-specific nickname、display name 与 routeable handle
- 持久化 delegation payload
- 调用 `ProtocolService.delegate()`
- 返回 `wakeup_queued` 或明确失败 envelope

`ProtocolService.delegate()` 的职责：

- 创建或更新 canonical `AgentMember`
- 写入 `delegation_request` inbox message
- 排队 runtime wakeup signal
- 发出 `agent.spawned` / `agent.delegated` 等事件

`task.create`、`task.update`、Host `POST /v3/tasks` / `PATCH /v3/tasks/{task_id}` 与 repository 默认 edit intent 都不能写入或跨越 business-exit status；除 agent-level / legacy pending approval block 这类已文档化机械迁移外，`blocked`、`completed`、`failed`、`cancelled` 必须走唯一业务出口命令 `task.finish`，不得通过 raw `TaskRepository.save()` 绕过。durable SDK attached continuation 的 park 只暂停 agent/runtime，task 保持 `in_progress`，待 exact continuation delivery 的 `ENGINE_COMPLETED` owner wake 继续。blocked task 保持 blocked 时仍可做描述修正、lane unbind 等非状态编辑，但不能直接再次 finish；必须先通过显式 resume/reopen 迁移回 `in_progress`。completed / failed / cancelled task 连非状态 edit 也 fail closed。`task.finish` 只可改变 status、updated_at 与 failure fields，并在同一个 SQLite transaction 中写 `task_finish` document、task row 与 durable event；commit 后 SSE 才可见，任一写入失败必须整体回滚。测试需要构造历史终态时必须显式使用 fixture seed intent，不能让产品写路径获得同等豁免。

业务 task 终态必须由 agent 通过 `task.finish` 或已文档化机械迁移显式写入；runtime idle、max steps、tool result 或 protocol message 本身不自动表示 task completed。允许的机械迁移只包括 task claim、agent-level / legacy pending approval block 与 approval resume 等已命名 command；durable SDK approval/continuation 不改变 task status。机械迁移使用显式 mechanical intent，必须真实改变 status，且除 status / updated_at 以及 claim 所需 assigned_ref 外不得夹带 task 字段修改。`task.finish` 授权只比较 canonical `agent_id`，role 字符串不能代表 task owner。

`blocked_by` 必须始终形成 session 内 DAG。service 在写前返回包含 cycle path 的领域错误；SQLite `task_dependencies` 的 INSERT / UPDATE trigger 同时拒绝跨 session edge 和任意长度的依赖环。Task row upsert 与该 task 的 dependency replacement 必须原子提交，不能留下“task 已更新但 dependency 只写入一部分”的中间状态。

### 7.2 Inbox 与 Protocol

`protocol.send` / `protocol.thread` 是 agent team 内部协调工具。

默认语义：

- `protocol.send` 写入有 recipient、correlation、payload、status 的 `InboxMessage`
- agent recipient 只能解析现有 canonical `agent_id`、`@handle`、唯一 nickname/display name；`researcher` / `executor` / `reporter` 是 role，不是 recipient identity
- agent recipient 的 unread inbox message 会创建 `inbox_unread` wakeup signal
- delivery 成功只表示消息和 wakeup 已排队，不表示 recipient 已执行或任务已完成
- request-response、diagnostic、handoff、clarification、result completion 都应复用 correlation thread

### 7.3 Runtime Signal

`AgentRuntimeSignal` 用于表达需要唤醒 resident teammate 的事件。

当前 signal reason 至少包括：

- `delegation_assigned`
- `inbox_unread`
- `task_available`
- `approval_resolved`
- `engine_completed`
- `manual_resume`

Claim 语义：

- scheduler 只能 claim `pending` signal 或 lease 已过期的 `claimed` signal
- claim 写入 `claimed_by`、`claim_expires_at` 并递增 `attempt_count`
- turn 成功后写为 `completed`
- retryable failure 可在 attempt 上限内回到 `pending`
- non-retryable 或 exhausted failure 写为 `failed`

provider/model 失败是否 retryable 由 `LlmInvocationRuntime` 的 taxonomy 决定。若 runtime 内部 retry 成功，当前 turn 继续执行；若 runtime retry 耗尽但 signal 仍有剩余 attempt，scheduler/runtime service 将 signal 释放回 `pending` 并记录 `signal.retry_scheduled`；非 retryable 或 signal attempt 耗尽才写为 `failed`。runtime idle、tool result、protocol message 或一次 provider transient failure 均不自动改变业务 task 终态。

---

## 8. Capability Engines

### 8.1 Deep Research 与 Provider Tools

`researcher` teammate 可以直接调用轻量 provider tools，也可以在开放式、多步、跨来源综合任务中调用 `deep_research` engine。

`deep_research` 内部 researcher/synthesis 的 LLM 调用必须复用同一 `LlmInvocationRuntime`，不能维护 engine 私有 retry 或隐藏 fallback。一次 retryable 502/`Retry-After` 若在 runtime 内恢复，engine invocation 继续推进；若 provider/runner 异常无法恢复，engine 必须写入 failed dossier / failed `EngineInvocation`，不能把 invocation 留在 `RUNNING`。

默认 provider / research surface 包括：

- PubMed
- Semantic Scholar
- UniProt
- RCSB PDB
- InterPro
- Tavily / web search 类能力（按配置与 live gate 启用）

Research 输出应归一化为 evidence、source refs、gaps 和必要的 workspace artifacts。普通 search hit 是 source/evidence，不应伪装成 artifact；真实下载或生成的 sequence / structure 文件才进入 artifacts。

文献 provider 使用结构化 `completed | empty | degraded | failed` outcome 和 bounded invocation policy。PubMed 是 AOX/HMM cutover 的 required quorum：至少一个来自真实 PubMed provider、schema-valid PMID、完整 provenance、绑定 NCBI identity digest 且非 fixture 的 citation 才完整，empty/schema drift/provider failure 均 fail closed；Semantic Scholar 与 Tavily 只是 enrichment，429、retry exhaustion、absence 或 empty 必须保留为 `degraded`，不得生成 synthetic hit 或抹除有效 PubMed evidence。configured Host 即使没有 Tavily key 也必须装配 PubMed/Semantic Scholar direct tools，并从 `OPENZYME_NCBI_EMAIL` / `NCBI_EMAIL`、NCBI tool/API key 与 `SEMANTIC_SCHOLAR_API_KEY` 注入各自配置，不能把 bio literature availability 错绑到 Tavily。

AOX researcher 可以在 bounded policy 内迭代多次 PubMed query，harness 不规定固定 query、one-call 或 first-success stop。cutover collector 只接受 researcher 在唯一 `task.finish.evidence_refs` 中显式采用的 exactly one PubMed `artifact:<id>` 作为 primary aggregate receipt；零个或多个 adoption、按 latest/result-count/prose 推断，以及 task/invocation/artifact/source task-lane 不闭合都会 fail closed。`lane_id` 是可选 scope，允许整条链一致为 `None`，但不允许空字符串或部分漂移。report claim 必须引用该 primary artifact 内的 PMID/source。未采用的探索、empty、failed 或 superseded invocation 仍保存在 canonical SQLite；把全量 invocation universe 与 disposition/completeness root 封入离线 bundle 属于单独的 `@2` 架构提案，当前 `@1` 不声称具备该完整性 authority。

direct provider tool 在任何网络 I/O 前先写 `EngineInvocation(RUNNING)`，然后在 success、empty、degraded、typed failure、untyped failure 或 evidence-seal failure 上终结同一个 invocation；required PubMed `empty` 或 typed `failed` 必须终结为失败，不能因 callable 正常返回而被记为 success。可用于科学/报告的 citation metadata、call-local quorum 与 safe provider transcript 通过 artifact boundary 的 external ingress 复制到 Host 注入的 attempt-scoped content-addressed 只读 Blob root，按实际 bytes 重算 `content_digest/sealed_digest`；单个 search hit 仍是 source ref，不因同时存在 provider evidence artifact 而变成文件资产。source ref 持久化 PMID、provider supplied DOI、title、authors、venue/date、不可逆 NCBI identity digest、retrieval/request/response provenance 与 evidence artifact link。API/workspace 只投影安全 locator、status、identity digest 和 evidence digest，credential、private URL/query、private header、Host path 与受限全文不得进入 error/evidence/public projection。

research unit 的 `topic` 表示科学语义主题，不等于 provider 的检索类别。Tavily `web.search.topic` 只允许 `general`、`news`、`finance`，默认由 adapter 配置决定；科学主题必须放在 query/brief 中。tool schema 必须把该枚举呈现给 agent，绕过 schema 的非法值也应在 provider 调用前返回可恢复的 `invalid_tool_arguments`，不能把语义主题直接传给 provider，也不能静默改写为可运行类别。

### 8.2 Persistent Executor Sandbox 与 Execution Pipeline

V3 execution 的目标主路径是 executor-owned persistent sandbox workspace，而不是 executor 直接调用 runner、SSH、Slurm 或 runner config。executor 在自己的 sandbox 中迭代脚本、运行 Python/bash、检查中间文件；当某段源码进入 dry-run、approval、正式执行或结果审计时，Host 将相关 sandbox working-copy source snapshot 为 `ArtifactKind.CODE`，并把 snapshot digest 绑定到 execution plan、approval、run、artifact provenance 和 workspace projection。

关键接口：

- executor-facing `sandbox.workspace.status`
- executor-facing `sandbox.file.*` / `sandbox.exec`（Session 09 runtime 面）
- sandbox 内 `openzyme_pipeline` SDK
- Host/internal execution plan、run、approval、provenance 记录
- 迁移兼容 `execution.pipeline.start` / `execution.pipeline.status` bridge；它们不再是 executor 必须调用的 authoring 主路径
- docs 工具 `docs.search` / `docs.read`

执行边界：

- executor sandbox 运行在受控 rootless Podman 环境中，默认无网络、非 root、资源受限
- 默认多个 executor 使用同一个 Host-configured sandbox base image digest，分别启动各自的 rootless container process 并挂载各自独立的 persistent sandbox workspace；image layer 可以共享，sandbox workspace 不共享
- executor sandbox base image 由 Host-level image registry / bootstrap contract 管理，记录 `image_ref`、resolved `image_digest`、最低能力声明和 `sandbox_protocol_version`；缺失或不兼容返回结构化 image error，不自动换 image 或回退到旧 pipeline runner
- `image_ref` 只是配置/发现入口，不能作为执行身份。Host 在 local startup、live/eval bootstrap 与 plan preflight 都必须把它解析为完整 `sha256:<64hex>` immutable image id；Podman `.Id` 的裸 64 位 hex 与带 `sha256:` 前缀形式只在此处做严格等价规范化，其他格式拒绝且不得写入 image registry。同时对实际注入 sandbox 的 `openzyme_pipeline` SDK source tree（排除 bytecode/cache/symlink）计算 digest；`runtime_identity_digest` 绑定 image id、SDK digest 与 sandbox protocol。正式执行前再次解析并逐字段比对，复制 SDK 后再次验 digest，Podman `run` 必须使用 immutable image id；任何 tag 漂移、SDK 漂移或 identity 缺失都在 sandbox/runner 前 fail-closed
- 每个 executor 拥有独立 persistent sandbox workspace；`sandbox_workspace_id` 按 `session_id + canonical agent_id/member_id` 复用，`task_id` / `lane_id` 只是当前 focus metadata；持久化对象是 sandbox workspace volume、manifest、projection summary 和 canonical records，不是容器进程或 container id；容器可重启，sandbox workspace volume 保留，`sandbox_workspace_id` 进入 execution provenance
- sandbox workspace root 是 Host composition 注入的 attempt/deployment-scoped 依赖，不是 workspace status、file service 或 exec service 可各自选择的默认值；同一 runtime context 中的 `sandbox.workspace.status`、显式/隐式 workspace lookup、file CRUD、source snapshot、Podman bind 与 recovery 必须解析到同一 root。显式 `sandbox_workspace_id` 仍须按当前 `session_id + agent_member_id` 校验 ownership，不能因 id 已知而绕过 actor 绑定
- `sandbox.exec.argv` 是 direct exec-form 数组，不存在隐式 shell parsing；需要 shell 时必须由 agent 显式选择 `bash -lc`。明显把 heredoc 当作 Python argv 的请求应在 source snapshot、SandboxRun 和容器进程产生前以 typed tool error 拒绝并给出真实可行路径，Host 不静默改写为 shell，也不因此放宽真实 nonzero run 的 fail-closed 语义
- 通过前序 request、workspace、layout 与 runtime 校验并进入 source preflight 的每次 `sandbox.exec`（包括 `python -c`、package/signature inspection 与 diagnostics）都在 `SandboxRun` 和 process 产生前封存整个非空 `/workspace/src`；前序校验可以更早返回其自身错误。`sandbox.exec` 不是 read-only environment inspection shortcut；API/签名事实优先来自 `docs.search` / `docs.read`，确需 runtime introspection 时由 executor 先写入显式 inspection source。空树以 `source_snapshot_empty` fail closed，并明确未创建 run/process；Host 不自动生成占位源码或提供未审计 fallback。harness 只忠实呈现该 provenance 约束，不替 agent 固定科学策略
- `/workspace/input` 是 Host 管理并以 read-only 挂载给 sandbox process 的授权输入树；executor source 不得对 root、materialization target 或其父目录执行 `mkdir`、write、copy 或预创建。`artifacts.materialize` 由 control boundary 在 Host 侧创建并授权 target/parents，成功后只返回可读 sandbox path；可变 scratch 使用 `/workspace/work`，待登记结果使用 `/workspace/output`。该真实约束必须同时出现在 tool descriptor、受控 artifacts 文档和 workflow prompt，`EROFS` 不得触发 remount、alternate-path fallback 或重复 operation
- 无 canonical workspace row 时，派生 workspace leaf 必须不存在并由 Host 以 no-replace/exclusive-create 语义一次性建立 `/workspace/src|input|work|output|logs|manifest` 六目录；预存目录、文件或 symlink 一律进入 `sandbox_volume_corrupt`，不得接管或修改现场。已有 workspace 的根或任一必需目录若缺失、不是目录或为 symlink，同样 fail closed，status/file/exec 不得静默补成空目录。`sandbox.exec` 在 source snapshot、run record 或 container process 产生前再次校验完整布局，防止 stale READY 退化成底层 runtime path error
- Host repo、用户 home、`.ssh`、数据库、runner config、HPC credentials 不得挂载进 sandbox
- sandbox 内可做文件 CRUD、bash、python 和中间结果检查；sandbox workspace 是 working copy/cache，不是 canonical truth
- NCBI、UniProt、EBI HMMER 等网络数据库请求只能通过 `openzyme_pipeline.bio` 由 Host supervisor 托管执行；sandbox 不直接联网，也不保存 provider credential 或 Host cache path；provider outputs 必须写入 caller 指定的 `/workspace/output/...` 并经 Host artifact boundary 登记，RPC 只返回 bounded summary、manifest 和 artifact refs
- sandbox 到 Host 的 control socket 每个 connection 只传一个 JSON-RPC 2.0 NDJSON frame；request/response payload 的对称硬上限均为 `4 MiB`，不含终止 newline。`recv` 的 `64 KiB` 只是一块读取大小，Host 与 SDK 必须跨 chunk 聚合到 newline；非 null JSON-RPC `id` 只允许 UTF-8 bytes 不超过 `256` 的 string 或 signed int64（排除 bool）。其余 request semantics 非法时保留已安全提取的 id；id 本身超限/非法或无法安全提取时 error 使用 `id=null`。畸形 UTF-8/JSON、duplicate object key、`NaN`/`Infinity`、EOF 残帧、response identity 漂移、超限均以 bounded structured transport error fail closed；SDK request serializer 和 Host response serializer 同样禁止 non-finite number。首 newline 后已观察到的非空 trailing bytes 在 dispatch 前拒绝。硬保证是每 connection 最多执行一个 request：首 request 接受后才晚到的第二帧可能只观察到 connection 关闭而没有第二个 error，但不得执行第二个 method/operation。单连接错误不得终止 accept worker，SDK 必须在发送前检查 request size 并在接收时实施同一上限；Host 超大 response 只能替换为小型结构化错误。connection/read/send 与首字节后的 partial-frame 使用固定 5 秒 I/O timeout。对于 `durable_async_v1`，Host 在 admission 后把 exact socket/process epoch 交给 attached-process supervisor；approval/provider/HPC wall time 由 execution 与 continuation workers 推进，原 agent signal、session lease 和 HTTP request 已释放。只有 frozen `legacy_sync` owner 保留兼容同步等待，不能成为新 operation fallback。该 transport 不创建第二套 canonical execution state，也不升级 sandbox protocol/image version
- `artifacts.register` 的 logical metadata 与 4 MiB control frame 分离：SDK 对 ASCII-safe canonical JSON `<=256 KiB` 的 object 内联，对 `(256 KiB, 32 MiB]` 自动写入 attempt-local `/workspace/work/.openzyme/artifact-metadata/<sha256>.json`，wire 只传 exact-four-field `artifact_registration_metadata_sidecar@1`；更大 object 在连接前 non-retryable fail closed。Host 通过当前 workspace 的 fd-anchored/no-follow 路径在任何 validation、seal 或 catalog mutation 前核 exact wire path、regular file、size、SHA-256、strict UTF-8、duplicate key、non-finite、object root 与 canonical bytes；inline raw caller 也必须通过相同 canonical JSON 规则及 `256 KiB` 上限。top-level `content_digest`、`sealed_digest`、`tree_digest` 是Host-owned registration identity，caller在SDK和Host effect前均不得自报。sidecar 只是 transport spool，不是 Artifact、科学 evidence 或 canonical storage，catalog 仍保存完整 logical metadata。成功响应固定为 bounded `artifact_registration_response@2`，其中artifact是exact `{artifact_id,metadata}`闭集而非general public projection，metadata与validation分别使用versioned summary；`fasta_zero_records@1` 的回显 `derivation_contract_id` 在 effect 前限制为最多 `256` UTF-8 bytes，4 MiB 上限不提高。compat provisional response不重复回显path，并在128-item上限内有固定预算。`register_many` 另有 128-item/32 MiB unique-metadata aggregate cap，并在写入前解析全部 metadata transport；它仍是逐项 commit 的兼容 helper，晚项非 metadata 失败的跨项原子化属于 outcome-unknown 架构提案，不在本 Goal 伪称已经完成
- Host-supervised bio provider 不得把按记录线性增长的 identity map 塞进单个 FASTA Artifact 的 inline metadata。NCBI/UniProt 的完整逐序列 identity 记录保存在同一 provider result 的独立 canonical `metadata.json` Artifact；FASTA Artifact 只以 `sequence_digest_count`、exact canonical `sequence_digest_index_digest` 与 `canonical_sequence_digest_index@1` 替代线性 map，并继续保留固定 database/retrieval/release/identity/validation provenance。该 index 对 NCBI 使用产出 FASTA 的 requested accession，对 UniProt 只使用产出 FASTA 的 active primary accession；typed inactive identity 不计入。digest preimage 是按 key 排序、`indent=2`、ASCII-safe escape、末尾一个 LF 的 UTF-8 JSON object，count 同时等于 object member 与 FASTA record 数。它只是 bounded catalog summary，不是 cutover eligibility 输入；formal UniProt 的既有 raw→parsed metadata→FASTA 科学闭包仍须独立验证，其他 provider 路径继续依赖各自 byte-Artifact/operation contract 而不能把该摘要当作 raw normalization 证明。Host 在写入任何 provider draft 前必须对整组 draft 完成 path 合法性、组内重复、既有 catalog digest 冲突和 registration metadata transport 预检；这关闭已知的 conflict/oversized-metadata partial write，但 ArtifactBoundary 的逐件 validation/seal/catalog commit 仍非跨件事务，不能据此宣称 set-level atomicity
- `bio.uniprot_fetch` 的 route policy id 保持 `bio.uniprot_fetch.provider:v1`，provider config 更新为 `provider_config:uniprot:v3`，identity contract 更新为 `uniprot_primary_sequence_identity@2`。一次 SDK 调用、一个 controlled operation 和一次 approval 最多承载 `100000` 个 accession；Host 固定拆成每 query 最多 `100` 个 accession，`batch_size` 仍只控制 UniProt response page 的 `size`（上限 `100`），`Link: rel=next` page cap 按 query 独立计算。每个 response page 与生成它的 exact query accession slice/digest 绑定；返回另一个 query 中的 requested identity 也属于 cross-query swap，必须 `provider_identity_mismatch`。next link 只允许 exact `https://rest.uniprot.org[:443]/uniprotkb/search` 且无 userinfo/fragment；malformed/off-origin 以 `provider_schema_drift` 停止，public diagnostic 只保留 link digest 和固定 expected endpoint。active sequence records 与 typed inactive records 必须对 complete requested set 形成 exact 互斥分区；inactive 仅在 primary accession 精确等于 producing query 中的 requested accession 时接受，并形成 `inactiveReasonType=DELETED|MERGED` 的判别联合。`DELETED` 保留非空 canonical deleted reason，`MERGED` 保留非空、去重的 `mergeDemergeTo` replacement-target annotations；两者都保留 UniParc id、release/retrieval 与 response/record digests，固定 `identity_replaced=false`，无 sequence/audit，且不得跟随、抓取或使用 replacement、UniParc、HMMER sequence。unknown、`DEMERGED`、malformed inactive、active 缺 sequence、完全无返回或 partition 不闭合均 fail closed。approval 前 SDK 投影 accession/query batch 数（默认 `100` query cap 下当前完整 `37772` 对应 `378`）只是透明预测，不是实际 limit 或 approval authority；Host 注入的 provider config 可收紧 cap，并在 HTTP 前作最终校验。把 canonical estimate/actual limits 从 route policy+Host config 重建并绑定 approval/config identity 的大改仅记录在 [Host-authoritative controlled-operation resource estimate and limit snapshot](v3/architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md)，本 Goal 不实施。transcript 继续绑定 query/page 坐标、accession range/count/digest 与 response digest；HTTP failure 只增补 query-batch index/count/start/count/digest 和 completed/requested page 坐标，不回显 raw URL、accession list 或 cursor。duplicate detection 用 frequency-map 线性扫描并只对 duplicate keys 稳定排序。所有 query/page 仍属于同一 operation，不得拆成重复 approval。当前输入已是 primary UniProt accession；切换 async ID Mapping 所需的 durable job handle、submit/poll/result resume、幂等与 evidence/verifier schema 迁移不在本 Goal 内
- `bio.hmmer_search` 的 route policy id 保持 `bio.hmmer_search.provider:v1`，provider config 更新为 `provider_config:ebi_hmmer:v2`。result `page_size` 默认与上限均为 `1000`；poll URL 显式携带 `page=1&page_size=<configured>`，terminal poll payload 只提供 status 与 `result.stats.nreported` closure，即使 body 含 hits 也不作 result page。result materialization 永远从同一 page size 的显式 `page=1` 开始，再逐页读到稳定 `page_count`；跨页 `page_count` 漂移、非截断 raw hit count 不等于 terminal `nreported`、或 SUCCESS empty 不是 `nreported=0/page_count=0/hits=[]` 均 fail closed。这一修复不改 `max_hits`、provider order 或 parsed-hit schema
- sandbox provider operation 已建立 request draft 后遇到 `PipelineSdkFailure` 时，Host 通过同一 sandbox artifact boundary 登记 `provider_request.json` / `provider_observation.json` / `provider_error.json` 三件 diagnostic artifact，然后以原 canonical code/stage/retryable 语义重抛，仅增补 safe artifact refs。这不是 provider success，不进入 AOX 17 件 normalized deliverable，也不授权 retry、operation replay 或 alternate provider
- provider、artifact registration 与 HPC fetch 的 bounded response 允许在嵌套 provenance 中重复描述同一 artifact，但 executor 不应递归猜测 envelope。`openzyme_pipeline.artifacts.provider_file_ref`、`registered_artifact_ref` 与 `fetched_output_ref` 是按 response origin 互斥的 selector，不是可串联 pipeline：前者只读 provider manifest，中者只接受 exact `artifact_registration_response@2` 及其 bounded metadata/validation summary，后者只读 `fetch_refs`；summary 缺少原 logical metadata 字段不表示 catalog metadata 被截断或为空。durable provider 的 immutable result handle 保存完整 Host-verified S12 adapter envelope；唯一 transition service 的兼容投影把完整值写入 `adapter_result_envelope`，只把其中 exact object `bounded_summary` 写入 `result_summary`，保证 sandbox 看见与同步 executor 相同的 direct provider response。不存在该字段的 HPC run handle/failure envelope direct 投影，字段存在但畸形则 fail closed，不允许 SDK 递归猜测。attached process 恢复后的 `hpc.fetch_outputs` 必须使用 control-server 当前 repository 与 nested artifact-publisher mutation writer，不能重新进入已释放的 agent-turn runtime scope；durable HPC result 已冻结时只验证返回的 run/artifact/fetch refs 与 immutable adapter envelope 完全一致，不 raw save operation。兼容 `PodmanPipelineSandboxRunner` 的 run-local register 只能返回 `pipeline_provisional_registration_response@1(canonical=false)`，不得伪装成 durable catalog ref，registration selector 必须拒绝。provider/fetch selector 已返回 terminal canonical artifact ref，继续传给 registration selector 或构造 synthetic envelope 必须结构化 fail closed。三个 helper 均要求 exact-one artifact id/digest 并对 nested-only、重复或畸形投影 fail closed，不执行 I/O、fallback 或 operation replay。artifact boundary 的 source authority 是 control socket/controlled operation 所属当前 run 的 Host-owned snapshot，不能从 sandbox 参数自报，也不能因 workspace `last_command_summary` 尚指向上一命令而错绑旧 snapshot。AOX cutover 在 approval 前按 session/method 与 sandbox 历史检查 eligibility：同一 reached SDK method 的第二个 operation、已有 `failed|recovery_failed` operation 或 terminal failed sandbox run 均在 provider/runner dispatch 前停止该 attempt；checkpoint 只保留失败事实，不授权跨 run adoption。完整 cross-run effect adoption 仍只存在于对应架构提案
- MAFFT、CD-HIT、HMMER CLI 等 AOX/HMM 生信工具只能通过 `openzyme_pipeline.bio_tools` 由 Host supervisor 托管执行；pipeline 不直接 shell/subprocess 调本地 binary
- MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner 和领域 toolchain packaging 不进入 executor base image；它们属于 Host supervisor 的 backend/toolchain registry 和 bio_tools route policy
- CD-HIT cluster 真值来自完整 `.clstr`，由 Host/runner normalize 为 one-member-per-row 的 `cdhit_cluster_membership@1`；Host 必须在登记任何 CD-HIT output 前将 membership 与 staged FASTA 身份及长度闭合校验。aggregate representative/count、缺失/重复 member 或 deterministic fixture 均不能作为 cutover 证据
- 外部执行只能通过 Host-supervised SDK 进入 provider、明确配置的本地 adapter 或 HPC runner；AOX/HMM `bio_tools` 的 Session 14 产品 route 是 HPC-only，不以 Host-local Apptainer 作为 fallback。`openzyme_pipeline.hpc` 保留为 executor-facing placement / remote workspace / declarative stage-fetch namespace，领域能力优先由 `bio` / `bio_tools` / `structure_tools` / `docking` 表达，稳定边界是不暴露 SSH、Slurm、runner path、SIF path 或 database mount
- HPC catalog、fpocket / Vina / `bio_tools` tool execution contract、command rendering、RunSpec compiler helper 与 parser 的权威在 `packages/openzyme-tools`；`openzyme-engines` 只能调用这些 helper，不维护第二套 command template 或 parser；`openzyme-runtime.hpc_catalog` 仅保留迁移兼容 shim
- 科学结论只能来自可读、已登记并通过对应 parser 的 output artifact。pipeline step 的 parser 必须接收该次 runner 实际返回的 artifact refs，不能用空 artifact list 解析；fpocket 缺 `target_info.txt`、读取失败或无法解析时，即使 runner `raw_result` 自报 `pockets_found` 也不得生成 pocket count 或 `design_signal=proceed`；未知 tool parser 同样不得默认 `proceed`
- dry-run / validation 先生成 `ExecutionPlan`；需要 approval 的外部/backend operation 或显式 `inputs.approval_policy="single_plan"` plan 在用户 approve 前不得提交
- dry-run 必须列出 bio SDK operations、每种 operation 的静态 `max_calls`、route policy、approval requirement、预计 provider requests、分页/配额估计和 expected database artifacts；重复调用和 literal bounded loop 必须计入总量，函数体、动态 iterable、while/comprehension 等无法证明有限上界的外部 SDK 调用在启动 sandbox/runner 前 fail-closed；大型 FASTA、metadata、raw hits、parsed hits 与 sanitized provider transcript 均登记为 artifact，RPC 只返回 bounded summary
- dry-run 必须列出 bio_tools operations、资源估计、expected outputs 和 approval/route 需求；declared output 缺失、格式非法、资源超限、tool_missing 或 oversized log 均返回结构化状态
- runner-owned fixed bio-tool template 的 output path 是真实执行约束，不是 agent 可自由命名的逻辑标签；Host 必须在 runner/HPC dispatch 前把 agent 声明与 canonical path set 精确比较，不匹配时返回包含 expected/declared paths 的 LLM-readable `bio_tool_output_contract_mismatch`，不得静默改写后继续运行昂贵 HPC job
- plan、approval、execution invocation、RunSpec、output artifact provenance 与 workspace projection 记录 `sandbox_workspace_id`、`source_code_artifact_id`、`source_code_digest`、`source_code_version`、immutable image digest、Pipeline SDK digest、`runtime_identity_digest`、input artifact digests、operation set、backend route 和 expected outputs；正式执行前 Host 重新校验 approved source snapshot 与完整 sandbox runtime identity。persistent `sandbox.exec` 把同一 identity 写入 `SandboxRun.compatibility`，其 adapter operation 只能继承对应 run 的 identity，不得从 tag、workspace 默认值或临时兼容值重建
- approval 绑定完整 operation digest、artifact reads、SDK/toolchain/backend operation list、每种 operation 的 `max_calls`、expected outputs 和资源/配额估计；正式执行在每次 provider/tool/HPC 外部调用前原子消费 approved plan call budget，超过上界返回 `execution_plan_quota_exceeded` 且不得触达 adapter/runner；同 session 内 digest 完全一致可复用 approved approval，digest 漂移必须重新审批或结构化失败
- artifact `kind` 是 control-plane 闭集：`code|log|sequence|structure|report|research_dossier|result|cache|other`；HMM、CSV、JSON 等编码以及 model/alignment/table/graph 等科学语义只能进入 `format` 或 metadata，不能发明新的 kind。`directory` 仅是 `expected_outputs` 的既有 shape sentinel，不会写入 artifact kind。sandbox SDK 在 control call 前校验，Host artifact boundary 与 Core/Podman raw control socket 对旧 SDK/绕过调用重复校验；非法值统一以 non-retryable `artifact_kind_invalid` 在封存和外部工作前 fail closed。bio-tool runner declaration 若显式提供 kind/format，也必须与固定模板一致；显式非法 kind 不得按文件扩展名静默回退，valid-but-wrong pair 同样在 runner dispatch 前结构化拒绝。AOX 的 HMM 固定为 `result/hmm`，FASTA 固定为 `sequence/fasta`，CSV/JSON 固定为 `result/csv|json`；17 个 normalized deliverable 的 online copy/cache-hit、fault target 与 offline verifier 还以 `aox_fixed_deliverable_artifact_contract@1` 同时绑定 exact path/kind/format，任一缺失或漂移 fail closed
- sandbox `artifacts.materialize` 只能把授权 catalog artifact 安全搬入 workspace；每次读取、复用和复制前后都必须重算 sealed Blob 的 file/tree digest，并与 Artifact row 声明的 digest 一致；同一 artifact digest、target path 和 mode 幂等复用，路径或 Blob digest 冲突必须保留现场、进入 quarantine/GC 台账并结构化失败，不能覆盖同 digest Blob 或继续 materialize；`artifacts.register` 必须在登记前执行非空、FASTA/HMM/CSV 必需列等轻量校验。科学 empty result 不是通用空文件豁免：AOX 零记录 FASTA 只有在 exact-zero bytes、稳定 `empty_result_reason`、版本化 derivation contract 和 `validation_profile=fasta_zero_records@1` 同时成立时才可登记，未知 profile 或 sentinel payload 一律 fail closed；cutover bundle 还必须封存可离线重算的 catalog validation receipt。`artifacts.snapshot_code` 使用同 Blob root 下的临时树原子固化执行源码，复用已有 snapshot 时同样重新验哈希；cutover evidence 不把 source directory 当单文件读取，而是仅接受 `kind=code` 的 typed snapshot，规范化为 `openzyme_sealed_source_tree@1` envelope，逐文件绑定安全相对路径、size、content digest/base64 和整树 digest，并在构建与离线验证时双重重算；可解码 UTF-8 源码还必须在 base64 前后分别通过 public-safety 检查
- 同一 `sandbox_workspace_id` 同时只允许一个 active `sandbox.exec`；container process id 不是 canonical state，`SandboxRun`、file audit、command log artifact 和 changed-file summary 才是审计状态
- `sandbox.exec` 默认 `120s`，`s09.exec_policy.v2` 的有限全局上限为 `3600s`，其 CPU/memory/pids、无网络、单 active exec 与 container retirement 约束不变。AOX 中任何可能到达真实 `bio.hmmer_search` 的 command 必须使用 exact `3600s`，纯 inspection/source-repair 可更短；approval 前由 canonical `SandboxRun.resource_policy` 校验，不能只依赖 prompt。该资源事实不固定 agent 的脚本结构或合法修复策略
- AOX similarity 的当前有界纠正不提高通用 sandbox 资源：formal private-cgroup Podman 已实证可从根 `/sys/fs/cgroup/cpu.max` 得到 2-CPU quota，worker cap 取 pair count、硬上限 `16`、affinity/`cpu_count` 与所有可用 cgroup v2/v1 quota/period 向上取整值的最小值，present 但 unreadable/incomplete/malformed 的 limit fail closed。真实 516-sequence/132,870-pair 校准中 2 workers 为 `84.087s`，比 affinity-only 16 workers 的 `168.766s` 更快，故固定 2-CPU/3600s 不是当前 blocker。通用 Host、嵌套 ancestor cgroup、placement plan 与 authoritative resource receipt 的未覆盖面只记录在 [Host-authoritative scientific-calculation placement and sandbox resource class](v3/architecture-proposals/host-authoritative-scientific-calculation-placement-and-sandbox-resource-class.md)，本 Goal 不扩张 helper 为通用资源架构
- sandbox workspace 的 disk quota 是 Host 强制执行的硬边界：`sandbox.file.write` / `sandbox.file.patch` 在原子替换前按 prospective bytes 拒绝超额，`sandbox.exec` 结束后按完整 workspace 重算；子进程、control socket 或 SDK 产出导致超额时，run 必须终止为 `resource_exceeded`、workspace 必须进入 `quota_exceeded`，清理到限额内前不得再次执行
- sandbox/adapter/provider 的公开诊断只能保留稳定 error code、bounded summary、digest、size 和无读取 authority 的 opaque log ref。已知 Host workspace/control-socket root 在 schema 声明的 diagnostic/locator field 中映射为 `/workspace` 与 `/openzyme/control.sock`；随后对已测试的 high-risk corpus（常见 Unix/HPC roots、Windows drive、UNC、`file://`、private/special-use URL、storage/runner locator 与 credential forms）递归脱敏。该 producer sanitizer 不声称能从任意自由文本识别所有 private path，也不无类型改写用户输入、conversation 或 scientific/report 正文；AOX offline verifier 仍独立拒绝任何 surviving absolute Host path/private locator。进程 stdout/stderr 以 binary capture，public summary 才使用 replacement decode；完整 raw bytes 仅写 attempt-local Host-private command-log root，run directory/file 分别以 exclusive `0700`/no-follow `0600` 创建，公开 digest/size 按这些 raw bytes 计算。projection 只对历史 diagnostic 与 schema-declared locator field 再投影，不能通过旧 SQLite 绕过当前写边界
- AOX public evidence scanner 只把四个 exact logical manifest suffix `/provider_parsed/metadata.json`、`/provider_parsed/parsed_hits.csv`、`/provider_parsed/proteins.fasta`、`/provider_parsed/sequences.fasta` 视为非 Host locator，并在 sealed Python source 中窄识别 `Path("aox_hmm")/p.name` 这类真实 `/` path-join syntax；它不开放整个 provider directory，也不把任意右括号后的 slash 当例外。未知 suffix、traversal、任意 `prefix)/p.name`、`/home/...`、`/tmp/...` 和其他未识别 absolute path 继续 fail closed；既有 `/workspace`、`/openzyme/control.sock` 与 public `/v3/...` route 规则不变
- runner/HPC 不得直接使用 Host 本地 artifact path；输入必须通过 artifact catalog 授权并 staged 到远端工作目录
- runner 在 payload 执行前的 `remote_layout`、`input_parent`、`input_transfer` 或 Slurm `runner_control_transfer` 终态失败必须立即通过本地 `ArtifactStore` 写入 Host-trusted `runner_failure@1`；该 exact schema 闭集只含 `schema_id`、opaque `run_id`、phase、一基 input ordinal/内容 digest（layout 均为空，control transfer ordinal 为空且 digest 绑定 `job.sbatch` bytes）及 `returncode/timed_out/elapsed_seconds`。engine 继续向 agent 返回 `hpc_staging_failed`，只投影上述已校验字段；adapter → sandbox control socket → `PipelineSdkError` 必须同时保留顶层安全 `stage="hpc_staging"`、typed boolean `retryable`、sanitized hint 与 `details.runner_failure`，不得把 stage/retryability 只藏在 details 或 traceback 中。projector 存在但畸形/抛错时使用固定泛化 reason，绝不读取异常文本。SSH target、命令、stderr、credential、Host/远端 path 或 locator 均不得越界。`retryable=true` 只忠实呈现恢复可能性，不授权同 attempt 自动 replay、重开 approval、切换 backend 或采用既有 effect。该 manifest 不是成功 run/output 或 artifact authority，也不引入额外隐式重试、重连、连接复用或 timeout 数值放宽；既有 rsync→最多一次 scp fallback 保持有界，Slurm layout/control transfer 纠正性应用既有 `staging_timeout_seconds`
- payload 已进入 `remote_execution` 后，runner 必须保留 raw nonzero 的首要 transport/tool failure，不能因成功态 toolchain identity marker 缺失而覆盖；只有远端命令返回零且 marker 缺失或非法时才归类 `TOOLCHAIN_IDENTITY_MISSING`。`SSH_CONNECTION_TIMEOUT` 向 engine 投影为可重试的 `hpc_runner_timeout`，`SSH_CONNECTION_FAILED` 投影为可重试的 `hpc_runner_unavailable`；该 retryability 只是呈现给 agent/operator 的结构化事实，不触发隐藏 replay、自动重批 approval、backend fallback 或连接策略变更。任何 remote nonzero 或无效 success marker 都跳过 output fetch，不能产生科学 artifact；runner raw stdout/stderr 只保留在 Host-private artifact store，server、execution adapter、engine 和 V3 Host 公共投影仅允许 opaque run id、稳定 status/error/stage/exit 等闭集字段
- `packages/openzyme-execution` 只规范化 Host-supervised runner 调用结果，不直接构造 `MCPHpcServer`；`apps/openzyme-host-api` 作为 HTTP/SSE composition root 负责实例化 runner server 并注入 adapter
- 远端输出只有在 declared `expected_outputs` 中声明且 runner 实际返回可读内容后才会下载并登记为 artifact；missing output、失败 run、不可读 fetch source 均结构化失败，不生成占位文件或伪造科学 artifact。只有同时标记 `fixture_non_cutover` / `simulation_non_cutover` 且携带相应 fixture/simulation 证据的显式测试 outcome 才可生成 placeholder，并必须写入 `synthetic_source=true`、`cutover_eligible=false` 与非产品 scientific status
- 对 HPC-heavy 流程，Host 维护独立的 HPC placement workspace；`hpc_workspace_id` 按 `sandbox_workspace_id + normalized_label` 复用，executor 通过 `hpc.workspace`、`stage_artifact` 和 `fetch_outputs` 声明文件流，Host supervisor 负责真实 staging/fetch 和 artifact registration，不能把该远端工作区描述成 sandbox workspace 的 mirror，也不能把 remote path 暴露给 executor
- blank-world live attempt 由 Host composition 注入彼此独立的 SQLite、sandbox workspace、sealed blob/artifact 和 HPC workspace roots；execution pipeline、provider artifactization、HPC fetch 与 source snapshot 必须贯穿同一 attempt-scoped root identity，任何局部共享 `/tmp` fallback 都使该 attempt 不具备 cutover 资格。public proof 仅包含 root digest/空目录证明，不暴露 Host 或远端路径
- 现行 AOX attempt collector 的单文件 no-replace/seal 不等于 evidence archive 的 transaction，也没有统一证明 final `artifacts/` 实际文件集与 declared inventory exact equality。两阶段 private staging→验证→commit、artifact-root 全闭包、failure atomicity、crash recovery 和 schema migration 的完整方案单独记录在 [transactional attempt evidence collection and root closure](v3/architecture-proposals/transactional-attempt-evidence-collection-and-root-closure.md)，当前 Goal 不实施；在该迁移落地前不得用提案语义补强已封存 bundle 或 GO 结论
- blank-world campaign 的 fresh SQLite 不继承 sandbox image registry 状态；在首个 session/model/provider 调用前，campaign 必须把 public runtime health 返回的 canonical immutable image / Pipeline SDK digests 与 pinned campaign identity 逐字段比对，完全一致后才在该 attempt 内登记 digest-pinned、cutover-grade image row。预存 row、缺失、格式非法或 digest 漂移必须在产生外部副作用前 fail closed；public preflight identity 同时进入 sealed launch receipt并由 offline verifier 对照 campaign image/SDK identity
- AOX/HMM `pin` 是 `run-live` 的 canonical supported operator bootstrap：它在 clean checkout 上使用 production compiler 和受信 Host 的 forced-SSH runner 执行四个 deterministic non-scientific MAFFT/hmmbuild/hmmalign/CD-HIT payload，只从 runner 签发的 same-shell runtime identity 得到 toolchain image digests。writer 将 exact-seven identity 与 exact-nine prerequisites 以 `0600` canonical JSON 发布在 checkout 外同一 existing real transaction directory，三个 reserved targets 初始必须不存在；Host 在两个 payload 落盘后最后发布闭集 `.aox-cutover-pin-commit.json`，用 basename 和 canonical payload digest 形成单一 consumer-visible commit point。marker 前 crash 留下的 orphan payload 不可消费；`run-live` 必须在读取 settings、构造 launch/campaign 或创建 root 前拒绝 marker 缺失、symlink、跨目录、开放/畸形字段或 digest drift。该无签名 marker 只证明 committed pair 完整性/一致性，不证明 producer provenance、目录整体 freshness 或消费时 file mode；真实运行仍依赖 trusted operator、actual launch recomputation 与每个 operation 的 runner-issued identity fail-closed
- AOX/HMM `run-live` 在构造 runner/campaign 或 attempt root 前必须从 clean checkout、digest-pinned workflow registry、`aox_motif_rule_score@1`、实际 Podman runtime preflight 与 Pipeline SDK tree 重算 canonical 七字段 identity；已提交的 pin declaration 只用于精确比较，不是真值来源。`config_digest` 必须来自 safe `aox_blank_world_runtime_config@1` preimage，绑定 trusted local Host/single-process SQLite、HPC runner config digest、runner-owned manifest bytes digest 及 exact AOX `tool_id` 到 adapter/template/runner-contract digest 的闭集 expectation map、effective MICU/research/tracing/test opt-in、driver/Chrome bounds 与既有累计 500M ledger identity，但不投影 credential、NCBI email 或私有路径；100M→500M 只能由 operator 显式执行 exact fixed-policy migration，保留全部历史 usage，caller-selected lower limit 不被抬高，普通 summary/reserve/run-live 不自动迁移。MICU/OpenAI-compatible blank-world live 必须显式声明 `context_window_tokens` 且不大于 `200000`，不得按模型名继承第三方 endpoint 未证实的百万级 context。每个 attempt root 前重新校验 checkout/config drift，exact-nine prerequisite 顶层 schema 不因此扩张
- blank-world prerequisites 是 exact-nine 闭集：`git_commit`、`config_digest`、`workflow_ref`、`image_digest`、`sdk_digest`、`toolchain_image_digests`、`credential_slots`、`ncbi_identity`、`prompt_accessions`。前五项必须与 launch identity 相等；toolchain map 只含 versioned MAFFT 7.525、hmmbuild/hmmalign 3.4 与 CD-HIT 4.8.1 SIF digest，两个 HMMER operation 必须绑定相同 bytes；credential 只投影 availability boolean，prompt accessions 只允许 formal exact-14 与 fixed probe
- cutover-grade HPC tool receipt 必须由 runner 签发 `mcp_hpc_toolchain_runtime_identity@1`：runner-owned manifest 决定 private SIF locator，同一 SSH login shell 先 scrub 所有继承的 `APPTAINER_*` / `SINGULARITY_*` runtime-control 变量并二次确认不存在，任一变量无法移除则在 payload 前 fail closed；随后直接执行该 resolved pathname，并在 payload 前后哈希同一 pathname。只有两次 digest 相等且 payload 成功才以现有 `attestation_scope=same_ssh_login_shell_pre_exec` 闭集 schema 投影单一 `image_digest`。Host 不接收 private pathname 或两个中间 digest，collector/verifier 将该 equal digest 与 exact prerequisite 比对。这只证明“受控运行时环境中同一路径在 payload 前后 bytes 未变且被直接执行”，不证明 immutable inode/content-addressed snapshot；更强保证单独记录在 [immutable HPC SIF execution snapshot](v3/architecture-proposals/immutable-hpc-sif-execution-snapshot.md)，本 Goal 不实施。当前 Slurm 没有 job-internal same-execution attestation，不能用于 AOX cutover identity；submit/preflight metadata 不得冒充执行证明。跨 runner/route/template/DTO/verifier 的单一合同 registry 属于 [deferred architecture proposal](v3/architecture-proposals/single-source-hpc-toolchain-contract-registry.md)，当前 Goal 不实施
- blank-world live 的 probe、两次 positive 与 fault attempt 全部通过 same-process loopback HTTP Host 驱动。cutover effective config 固定 `max_signals_per_drain=1`：driver 为每轮 POST 一个带独立 idempotency key 的 durable command，校验 `202 + command_id + status_url`，随后轮询 exact session-scoped GET。command worker 每次最多 claim 一个 signal；command 在 bounded batch完成、失败、locked 或 park work 后即 terminal，approval/provider/HPC wall time 不延长 command lifetime。driver 并发读取 `GET /v3/sessions/{session_id}/pending-approvals` 并通过唯一 approval resolve API 处理同一 attached operation；command terminal 后若 generic mutation scope 仍有 attempt driver 之外的 writer，driver 继续紧凑 approval 轮询并等待这些 writer 退役，不能把 command terminal 当作 continuation/quiescence。result 由 execution/continuation workers推进，后续 agent wakeup由下一条 command消费；generic writer 状态只控制“尚不可推进/冻结”，不能充当科学成功或 task 完成判据。compact endpoint 与 `workspace.pending_approvals` 读取同一 Approval/ControlledOperation/SandboxRun rows，只返回 `session_id + pending_approvals`，不得构造 artifact/activity/report/capability；普通 auto gate 热循环和失败 cleanup 禁止轮询 composite workspace，只有 Chrome handoff 与 command/continuation 收口后的最终证据读取 workspace。probe/非 Chrome gate 自动批准，positive 1 首个 formal approval 只由浏览器批准；public coordination 失败后只 reject 已出现及后来出现的 unresolved operation以 fail closed，绝不用 approve 做清理或继续科学执行。same-process Host 的 HTTP-handler tracker只辅助 thread retirement，不是 mutation authority或静默证明；eligible closure 必须使用 generic mutation scope：freeze admission、等待 exact writer/descendant retirement、两次一致 SQLite/event/artifact/report/MICU-ledger snapshot、immutable receipt验证与 seal。process epoch只证明本地 writer退出，不证明远端 effect取消。core 与 Podman sandbox worker 仍为 non-daemon并使用 exact-container lease；永久阻塞时当前同进程实现宁可不封存，OS 级 bounded fatal retirement仍属于 [process-isolated live-attempt supervision](v3/architecture-proposals/process-isolated-live-attempt-supervision.md)。API receipt sequence 在 request start预留并在 response完成时 finalize；gap 或 transport normalization失败只能形成 non-cutover evidence。产品 command/continuation合同见 [Runtime / HPC可靠性边界](v3/07-runtime-hpc-reliability.md)
- drain coordinator 必须区分“请求已结束”和“最后一次 compact approval read 已发生在该 response 之后”：成功 worker terminal 后至少再执行一次 public pending-approval GET，才可断言没有新 durable `waiting_approval`，随后读取一次 bounded workspace 作为最终 semantic snapshot；若 worker 自身失败则保留 `runtime_drain_command_failed`，只有 public coordination/cleanup 失败才使用 coordination failure taxonomy
- `workspace.pending_approvals` 是 UI composite snapshot，`GET /v3/sessions/{session_id}/pending-approvals` 是同源紧凑 control snapshot。SSE 仍负责低延迟刷新，但 durable execution/continuation 可以在一个 runtime command 已 terminal 后产生后续 approval/result event，所以 event replay 不能单独证明当前无 pending approval；Web UI 还要对当前 selected session 做低频只读 workspace reconciliation。每个 active generation 请求必须 single-flight，session 切换、workspace mutation 或 SSE reducer 更新都会 abort/失效旧 generation，旧请求的 `finally` 也不能清除新 generation。挂起的旧 session GET 不得饿死新 session reconciliation，任何轮询不得写产品状态、维护第二真值或覆盖较新的 mutation/event snapshot
- AOX HMM-capable path 仍对 provider poll、sandbox process 与 formal attempt 使用分层有限 deadline；`pin`/`run-live` 在 attempt root、approval 与 provider dispatch 前校验实际 engine/core policy。durable execution/continuation 使 HTTP command 与 session lease 不再拥有这些 external deadlines，但没有取消 provider/HPC 或 process 自身的 bound。任一低于 route policy 的 timeout 仍 fail closed；完整 authority、recovery 与 quiescence合同见 `docs/v3/07-runtime-hpc-reliability.md`
- `chrome-once` 只把 positive 1 首个 formal approval 暴露给 same-process loopback Web UI；driver 不代替浏览器调用 approval resolve。driver 必须在触发可能产生 handoff 的 drain 前记录 durable event cursor，从该 cursor 重建即时 resolution/continuation，并立即验证 `pre_cursor < resolution_cursor < continuation_cursor`；浏览器 resolution consumer 只将带闭合 `decision=approved|rejected` 的 canonical `approval.resolved` command event 解释为 operator decision，同名但只有 ApprovalRequest `status`、没有 `decision` 的 activity projection echo 必须忽略，不能冒充批准或拒绝。真正的 canonical `decision=rejected` 仍立即 fail closed；有界 deadline 内没有 canonical closed decision 也必须 fail closed。浏览器 approval deadline 从 handoff 独立计时，同时不得超过 attempt 总 deadline。`aox_browser_approval_receipt@2` 必须绑定产生当前 pending projection 的 exact pre-workspace receipt、post workspace semantic preimage、public response receipt 与完整 resolution/continuation durable-event record；public API receipt 是含 `response_semantic_digest` 的 exact 七字段闭集。handoff 必须动态身份完整：发出 sealed logical page URL、Host process、UI dist digest、versioned receipt schema id、not-before、exact target 与 expected page state。terminal 后 Host 强制保持 completion observation window；trusted operator 必须使 final target 在 hold 内不存在，并把其 Chrome console、page target、三类 MCP request/response 与 PNG 投影封装为 `aox_browser_observation_capture@1`。稳定的 `openzyme-aox-cutover browser-receipt` helper 校验闭集，只在 not-before 后创建 mode-`0600` sibling temp，计算 exact 23-field receipt 的 aggregate digest/PNG dimensions，经 file fsync、atomic no-replace install 与 parent-directory fsync 发布；它不得伪造 Host acceptance timing，也不证明投影与 MCP 原始 response 的对应关系。当前 Host 只能证明每次 bounded poll 时 target 缺失，以及最终文件是 post-hold、non-symlink、mtime 合格且经两次 stat/read 稳定的 regular file；它不证明轮询间连续缺失、operator atomic/fsync provenance 或 browser-origin-complete transcript。窗口结束后的独立正有限 submission timeout 写入 effective config，不能用延长提交时间缩短 Host hold。`aox_browser_observation_receipt@2` 绑定 challenge、Host/UI/page、clean console、terminal page state、DevTools transcript、完整可解码 PNG 与 Host acceptance timing。最后一次只读 workspace 和 `after_cursor=0,replay=true` 全事件 preimage 作为 bundle-level artifact 封存而不回写产品真状态；fault closure 的 task/report/draft/conversation/event/consumer 集合必须与其 exact equality。全局 canonical command 与 derived activity projection 的 event taxonomy 分型属于 [deferred architecture proposal](v3/architecture-proposals/canonical-approval-command-vs-activity-projection-events.md)，本 Goal 不实施；`auto` campaign 不能满足 Chrome GO criterion
- AOX/HMM 正式科学链从一份 exact-14 NCBI protein aggregate 分离两类身份：13 条 fixed HMM reference 经 `openzyme_pipeline.aox_reference.select_hmm_reference_set` / `aox_hmm_reference_set_selection@1` 产生 `AOX_ref21.fasta` 并且只有该文件进入 MAFFT/hmmbuild；`AAB57849.1` 经 `select_scoring_reference` / `aox_reference_selection@1` 单独产生坐标 reference。EBI HMMER `refprot` raw/parsed hits 必须先经 `openzyme_pipeline.aox_hmmer.parse_and_filter_csv` / `hmmer_score_filtered_accessions@1` 得到 score `>200` 的 exact accession artifact，才能触发 UniProt；`uniprot_primary_sequence_identity@2` 必须将 requested set 精确分为 active sequence 与 typed inactive `DELETED|MERGED`，sequence/length 真值只由 active UniProt record 提供。`openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions` / `aox_sequence_length_join@2` 先确定性排除两类 inactive，绝不跟随 MERGED target，再对 active sequence 应用 inclusive `650..700`，并以 active/inactive-reason/output/length-rejected counts 及 sorted identity mappings 使 partition 可离线重算。`openzyme_pipeline.aox_reference.assemble_scoring_input` / `aox_scoring_input_assembly@1` 再把 AAB 放在首位、追加 post-UniProt targets，HMMalign 消费该 scoring input 与真实 HMM；motif 与 graph 必须分别调用 `openzyme_pipeline.aox_motif.score_aligned_fasta` 和 `openzyme_pipeline.aox_similarity.build_similarity_graph`。agent 必须通过 provider transcript 的声明后缀和 HPC `fetch_refs[].declared_output_path` 绑定真实 bytes，且 MAFFT/hmmbuild/CD-HIT/HMMalign 只声明 runner-owned canonical output path；不得近似重写这些计算、生成 sentinel empty、把 AAB 混入 model training，或用 HMMER/probe/reference/MERGED replacement sequence 代替 UniProt active target。当前 pinned SDK 的 primary FASTA/CSV/JSON accessors 与 `metadata_json()` 返回 Python `str`，`metadata()` 返回结构化 `dict[str, object]`；受控 workflow facts 必须披露这些类型，bytes-only writer 前只做一次 UTF-8 encode，type/annotation drift 不得触发隐式 coercion。科学计算 callable、canonical serializer、agent-facing facts 与 receipt 目前仍分散；统一 versioned capability projection 的大改动仅记录在 [versioned scientific calculation capability projection](v3/architecture-proposals/versioned-scientific-calculation-capability-projection.md)，本 Goal 不实施
- AOX graph 的当前 `aox_global_sequence_identity@1` implementation/calculation 分别固定为 `sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5` / `sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`。`biopython_trace_guarded_numpy_gotoh@1` exact pin Biopython `1.87` 与 cutover NumPy `2.4.4`，只允许 proven `<2^53` integral binary64 packed score；首个 optimal trace 出现相邻 opposite gap-state switch 时调用 exact `numpy_three_state_gap_switch_correction@1`，所有 import/version/algorithm/numeric/trace/correction drift 均无 fallback fail closed。reference recurrence 的 state order 只记录 tie provenance；当前 graph 不承诺或发布 alignment coordinates/path，未来若发布必须启用新 calculation id 与显式 trace contract。reference validation NumPy `2.4.6` 与 cutover `2.4.4` 是明确不同的 exact 环境；最终 comparison receipt `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e` 由两次独立 cutover-`2.4.4`、2-CPU/2-worker full-set run 证明 raw repeatability，并在只规范化 pin-induced fields/manifest closure 后逐字节等于 old pure-v3 输出。它不声称 direct full-set patch A/B，且与历史 pure-v3、临时 2-CPU receipt 一样始终 non-cutover；只完成 diagnostic/reviewer 与 workflow knowledge pin gate，不是 live GO evidence
- 到达 UniProt 的 cutover-eligible positive 必须通过 `scientific_checks.sequence_join.uniprot_raw_response_artifact_id` 把 raw response artifact 与同一个 formal `uniprot_fetch` operation 的 provenance/output 及 UniProt provider receipt 闭合。无网络 verifier 从 closed raw envelope/response rows 重放 page/body/header release 与 ordered digest chain，用 engine sanitizer 建立 raw-result↔metadata requested/primary 双射；active sequence 的规范化 bytes、raw/metadata length/digest 必须继续闭合到 FASTA，inactive 禁止 sequence/entryAudit 并重建 exact DELETED reason 或 MERGED non-follow annotation。无关 future raw result fields 可以存在，但完整 sanitized non-sequence object 必须等于 `provider_metadata`，`record_digest` 则绑定完整 sanitized result；本轮 diagnostic 的 exact-five inactive shape 不是未来字段 allowlist
- AOX/HMM healthy empty 不要求无意义的全工具调用；offline verifier 从封存 artifact 推导 `hmmer_upstream_empty | length_filter_empty | motif_filter_empty | nonempty` 分支，分别省略 `UniProt+HMMalign+CD-HIT`、`HMMalign+CD-HIT`、`CD-HIT` 或无省略。upstream empty 的 `provider_upstream_empty_receipt@1` 只证明 trigger/reason 和 `provider_io_performed=false`，不得伪造 operation/request/response digest；独立 known-positive probe 覆盖正式分支未到达的 capability，但其 bytes、operation 和结论永不进入正式图与 report claim
- Provider cache 只能作为 Host-private optimization；cache key/digest 可进 provenance，但 cache hit 不能替代当前真实 provider/live prerequisite 证据
- AOX/HMM local Live cutover 只能由同一 commit/config/workflow/scoring/image/SDK identity 下两次独立 blank-world 正向 attempt 和一次受控 fail-closed attempt 的 sealed bundle 聚合得出；每个正向 attempt 必须有 published report 并通过无网络 offline verifier。故障不是任意 provider failure：必须以 `derived_required_artifact_blob_byte_flip@2` 到达 real NCBI exact-14 `proteins.fasta` → `aox_hmm_reference_set_selection@1` → derived `AOX_ref21.fasta` → pending MAFFT seam，产生 exact `artifact_blob_digest_mismatch`；`aox_fault_negative_state_closure@1` 必须证明执行 task fail/block/cancel、reporter 未完成、无 ready/published report/draft、无 successful alternate consumer 或 downstream fixed deliverable、conversation/durable event/final failure 一致，且 fault MICU 增量完全归因于本 campaign。当前在三份真实 attempt digest 封存前一律是 **NO-GO**；S15 历史 pass、seeded smoke 和 fixture 只是 non-cutover 证据，这些 attempt bundle 不是新的顶层 control-plane 真状态

### 8.3 Report Draft 与 Report

Reporter teammate 默认使用：

- `report_draft.get`
- `report_draft.update`
- `report.publish`

`report_draft` 是可恢复、可修订、可投影的中间交付物；`report.publish` 才生成 final report record。当前 live/cutover 证明不能只看 tool 注册或 seeded smoke，必须确认 workspace 中出现 published draft / ready report，且 reporter task 的创建、委托和 drain 路径实际发生。

---

## 9. 验证与 Gate

常用非 live 验证：

- `./scripts/check-mainline.sh`
- `uv run pytest`
- `uv run pytest -m "not integration"`
- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py packages/openzyme-core/tests/test_protocols.py`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py -k v3`
- `uv run python -m openzyme_host_api.evals --v3`

主要 opt-in markers：

- `integration`
- `live_llm`
- `live_tavily`
- `live_hpc`
- `live_e2e`
- `seeded_live_smoke`
- `podman`
- `quality_eval`
- `slow`

Live gate 解释：

- 裸 `uv run pytest` 通过 `pytest.ini` 默认排除 `integration`、全部 `live_*`、`seeded_live_smoke` 与 `quality_eval`；真实外部测试必须同时满足环境 gate 与命令行显式 `-m` 选择，已配置凭据本身不能触发默认外部调用
- `live_e2e` 是外部配置和 live 依赖的必要 gate，但不能单独证明单消息完整报告生产路径已经产品完成
- live E2E 轮询在 task 已失败、所有 agent 均非 working/active 且没有 pending signal 或 unread inbox 时必须立即以持久 failure evidence 收敛；不得把外部 provider rate limit、缺 artifact 或 fail-closed 终止包装成通过，也不得在业务已静止后空等全局超时
- `seeded_live_smoke` 是辅助回归支持，不是 blank-world cutover proof
- reporter/report publication 的验收必须检查 task board、delegation、inbox、runtime drain、workspace `report_drafts` / `reports` 和相关 events
- 缺少 live provider/HPC 配置时，应报告为 gate prerequisite missing，不得计为通过

---

## 10. Legacy Boundary

V1 已迁入 legacy。旧 `episode + phase graph` 产品面已从主线删除，主线不再维护回滚用的 graph/storage/API/UI 双栈。

当前 V3 的产品语义：

- `session`
- `task DAG`
- `lane / workspace`
- `approval`
- `inbox / protocol thread`
- `resident teammate`
- `runtime signal`
- `workspace projection`
- `report draft / report`

因此，新变更的默认判断规则是：

- 新产品状态写入 V3 control plane，而不是只写 prompt、browser state 或 graph checkpoint
- 新 agent/team 行为通过 task、inbox、protocol、signal 和 explicit drain 表达
- 新 execution 行为走 pipeline sandbox、artifact catalog、SDK、approval 和 runner staging
- 不新增 `episode`、phase graph、supervisor-route 或旧 workspace projection 入口
