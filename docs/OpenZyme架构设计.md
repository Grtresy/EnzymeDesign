# OpenZyme 主线架构设计

## 1. 文档定位

本文档描述当前根仓库主线的 OpenZyme V3 架构边界与实现事实。

它回答四类问题：

1. 当前主线仓库保留哪些系统能力
2. V3 当前产品真状态与顶层架构如何分层
3. 一次 session 在 Host、Harness、Agent Runtime、Capability Engines、Storage、UI 之间如何流动
4. 当前哪些机制已经落地，哪些仍是切换期约束或未完成证明

当前主线采用 V3 的
`session + task board + lane/workspace + approval + resident teammates + explicit runtime/drain`
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

- `packages/openzyme-domain`：control-plane 领域对象，如 `Session`、`Task`、`Lane`、`ApprovalRequest`、`InboxMessage`、`AgentMember`、`AgentRuntimeSignal`、`EngineInvocation`、`RunRecord`、`SessionArtifactRecord`、`SessionReportDraftRecord`、`SessionReportRecord`
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
- 显式 `POST /v3/sessions/{session_id}/runtime/drain`，作为 debug/operator/manual recovery 工具

当前默认产品路径是：REST handler 持久化状态并排队 `AgentRuntimeSignal`，后台 runtime service claim pending 或 expired-lease signal 后启动 bounded master / teammate turn。`/runtime/drain` 保留为显式诊断与恢复命令，不再是普通产品路径的必要步骤。

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

旧 schema、未知 schema、非空但未标记 `user_version` 的 SQLite 文件不做隐式迁移、修复、备份或删除；启动路径必须 fail fast，并提示 operator 手动删除旧库或指定新的 `--v3-sqlite-db` 路径。`020_v3_task_integrity` 把 task dependency 的同 session DAG trigger 纳入 current schema 校验；`021_v3_durable_event_outbox` 把 durable event、command receipt 及二者的 append-only/immutable trigger 纳入校验。因此升级后的旧本地库也必须按上述 fresh/current-version 规则处理，不能绕过 trigger 校验继续运行。需要长期保留的研究结果、execution 输出与报告应通过 artifact、report 或 export 留存，而不是依赖旧 SQLite runtime 文件跨 schema 版本继续可用。

Python import shim、CLI alias、`execution.pipeline.*`、Podman runner、runtime/tools/execution 包 seam 与旧 HTTP/runner call shape 的 sunset 证据统一由 `scripts/audit-v3-compat-callers.py` 和 `docs/v3/compatibility-sunset.md` 管理。仓库内零 caller 只证明当前 checkout，不证明外部零 caller；所有 `DEPRECATE` / `RETIRE-BLOCKED` surface 在 external inventory/telemetry/owner evidence 仍为 unknown 时必须保留。已经不存在的 `/v1`/`/v2`、raw runner lifecycle 参数和 legacy workspace activation 标为 `RETIRED` 防回归，不得把归档源码本身误删。

单进程不等于共享一个 SQLite connection。Host 以 file-backed `SQLiteRepositoryProvider` 为 composition root；每个 request、background worker、scheduler bounded turn 与 sandbox SDK control callback 都在实际执行线程内创建并关闭自己的 thread-affine connection。纯读使用 `query_only` read scope；不跨外部边界的 canonical command 使用短 `BEGIN IMMEDIATE` Unit of Work，使多个 repository mutation all-or-nothing；可能等待 LLM、provider、runner 或 sandbox 的长流程只能使用无长事务的 connection scope，由内部短写自行提交，严禁持有 SQLite write lock 跨外部调用。WAL 与 `busy_timeout` 只改善单进程并发，不替代 ownership、UoW 或后续 fencing。

scheduler 持有 session runtime lease 期间必须按 TTL 的有界分数持续 heartbeat；blocking provider call 在 worker thread 中执行时 coordinator event loop 仍负责续租。worker、它重建的 engine registry 以及 sandbox SDK control/adapter/HPC fetch callback 的每个 connection scope 都绑定同一 `session_id + lease_token + fencing_token`。write/approval/external tool 在 dispatch 前检查 lease；每次 repository commit 再次检查 lease 仍 active，session-scoped repository 写还必须等于 lease session。lease 丢失或被更高 fencing token reclaim 后，旧 worker 的 task、agent、protocol、engine、run、artifact、report、event 等迟到写入一律失败；已经开始但超时返回的 callback 也不能应用 late business effect。fencing 只拒绝 canonical 写回，外部系统重试仍必须依赖 operation digest、idempotency key 与 opaque run handle，不能把 fencing 冒充外部取消。

V3 public event log 不是 Host 进程内缓存。`durable_event_records.cursor` 是数据库分配的单调游标；事件、对应的短 canonical mutation 与可选 `command_receipt_records` 在同一 UoW 提交，rollback 不得泄漏 SSE event。event rows 只能 append，receipt rows 完成后不可更新或删除；`event_id` 全局唯一，`llm.response.created` 的 `trace_id` 在 session 内唯一。SSE 以 cursor 作为 `id:`，通过 `after_cursor` 或 `Last-Event-ID` 从 SQLite 重放，Host 重启不得改变既有 event id/cursor。所有 `/v3` mutation 接受 `Idempotency-Key`：同 scope、command type、key 与相同 request digest 返回首次完成响应且不重做副作用；同 key 不同 digest 返回冲突。local-dev 当前允许省略 key；shared profile 的强制认证阶段将同时把 key 设为必需。

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
  +--> explicit runtime drain
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
  +--> mcp-hpc-runner / SSH / Slurm
```

顶层边界：

- Web UI / CLI 不持有 workflow truth；它们消费 Host API 和 workspace projection
- Host API 是共享入口，`/v3` 是当前产品语义面
- Control plane 持有跨对话、跨压缩、跨后台执行仍然成立的 canonical objects
- Agent runtime/scheduler 负责消费 wakeup signals，不决定业务任务内容
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
  -> AgentRuntimeScheduler claims pending signals with lease
  -> if signal is agent:master, run bounded top-level master loop
  -> if signal is teammate, wake focused resident teammate
  -> agent reads task / lane / inbox / protocol / workspace
  -> master creates / updates tasks and delegates with task.delegate
  -> teammate calls role-scoped tools or capability engines
  -> task / artifact / run / report draft / approval state updates
  -> terminal teammate outcome queues agent:master wakeup

GET /v3/sessions/{session_id}/workspace
  -> project current canonical state for UI / CLI
```

关键约束：

- `POST /v3/sessions/{session_id}/messages` 是用户到 master 的入口，只持久化用户消息并排队 `agent:master` wakeup，不直接执行 master loop，也不隐式执行 bounded teammate runtime drain
- `POST /v3/sessions/{session_id}/runtime/drain` 是 debug/operator/manual recovery 的显式 scheduler command；它必须通过 scheduler claim lease，不得绕过 scheduler 直接调用 agent loop
- `task.delegate` 是产品-facing delegation tool，但真实写路径是 `ProtocolService.delegate()`
- `protocol.send` 只投递消息并排队 wakeup signal，不同步运行 recipient
- `auto_enqueue_ready_tasks` 默认关闭，只用于显式 operator/debug/recovery 场景
- approval resolve 只改变 approval/resolution/continuation 状态并排队必要 wakeup，不直接恢复 execution、不直接运行 master loop，也不直接替用户或 agent 批准后续未知动作
- `world.inspect` 是 agent-facing 结构化世界读取工具，只暴露事实、约束、tool schema、route policy、approval requirement、outcome 与 runtime diagnostics；不得输出 `recommended_actions` 或替 agent 判断 workflow / 完成条件
- 通用 harness 不按 AOX/HMM、research 或其他领域关键词注入 recipe、改写 delegation 或剥夺工具。领域 SOP 进入 `docs/v3/workflow-packs/*.workflow.json`：只有 caller 显式提交完整 `workflow:<id>@<semver>#sha256:<manifest-digest>` 才会选择；manifest 固定 knowledge document version/digest，并声明 capability/tool requirements。`task.delegate.workflow_refs` 只能显式选择 caller 当前授权 refs 的无重复子集；省略或 `[]` 表示不绑定，不能把 parent focus 的全部 workflow 隐式传播给 teammate。claim 前校验 target role/tool/engine 与 manifest snapshot，teammate restore 再校验 drift；失败保持 task、agent、inbox、signal 无副作用。模型的 `skill.load` 不能自行激活 workflow pack，agent 在版本化真实约束内仍保留策略自由
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
- `GET /v3/sessions/{session_id}/workspace`
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
- `artifacts` 是 session 共享工作面；`storage_uri` 只属于 Host-private catalog record，workspace/API/agent tool result 只能暴露安全 artifact 投影，不能暴露 Host repo path、Host artifact path、sandbox host path、runner private path、SSH/Slurm config 或 runner credentials
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

`task.create`、`task.update`、Host `POST /v3/tasks` / `PATCH /v3/tasks/{task_id}` 与 repository 默认 edit intent 都不能写入或跨越 business-exit status；除 pending approval block 这类已文档化机械迁移外，`blocked`、`completed`、`failed`、`cancelled` 必须走唯一业务出口命令 `task.finish`，不得通过 raw `TaskRepository.save()` 绕过。blocked task 保持 blocked 时仍可做描述修正、lane unbind 等非状态编辑，但不能直接再次 finish；必须先通过显式 resume/reopen 迁移回 `in_progress`。completed / failed / cancelled task 连非状态 edit 也 fail closed。`task.finish` 只可改变 status、updated_at 与 failure fields，并在同一个 SQLite transaction 中写 `task_finish` document、task row 与 durable event；commit 后 SSE 才可见，任一写入失败必须整体回滚。测试需要构造历史终态时必须显式使用 fixture seed intent，不能让产品写路径获得同等豁免。

业务 task 终态必须由 agent 通过 `task.finish` 或已文档化机械迁移显式写入；runtime idle、max steps、tool result 或 protocol message 本身不自动表示 task completed。允许的机械迁移只包括 task claim、pending approval block 与 approval resume 等已命名 command；它们使用显式 mechanical intent，必须真实改变 status，且除 status / updated_at 以及 claim 所需 assigned_ref 外不得夹带 task 字段修改。`task.finish` 授权只比较 canonical `agent_id`，role 字符串不能代表 task owner。

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
- Host repo、用户 home、`.ssh`、数据库、runner config、HPC credentials 不得挂载进 sandbox
- sandbox 内可做文件 CRUD、bash、python 和中间结果检查；sandbox workspace 是 working copy/cache，不是 canonical truth
- NCBI、UniProt、EBI HMMER 等网络数据库请求只能通过 `openzyme_pipeline.bio` 由 Host supervisor 托管执行；sandbox 不直接联网，也不保存 provider credential 或 Host cache path；provider outputs 必须写入 caller 指定的 `/workspace/output/...` 并经 Host artifact boundary 登记，RPC 只返回 bounded summary、manifest 和 artifact refs
- MAFFT、CD-HIT、HMMER CLI 等 AOX/HMM 生信工具只能通过 `openzyme_pipeline.bio_tools` 由 Host supervisor 托管执行；pipeline 不直接 shell/subprocess 调本地 binary
- MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner 和领域 toolchain packaging 不进入 executor base image；它们属于 Host supervisor 的 backend/toolchain registry 和 bio_tools route policy
- 外部执行只能通过 Host-supervised SDK 进入 provider、明确配置的本地 adapter 或 HPC runner；AOX/HMM `bio_tools` 的 Session 14 产品 route 是 HPC-only，不以 Host-local Apptainer 作为 fallback。`openzyme_pipeline.hpc` 保留为 executor-facing placement / remote workspace / declarative stage-fetch namespace，领域能力优先由 `bio` / `bio_tools` / `structure_tools` / `docking` 表达，稳定边界是不暴露 SSH、Slurm、runner path、SIF path 或 database mount
- HPC catalog、fpocket / Vina / `bio_tools` tool execution contract、command rendering、RunSpec compiler helper 与 parser 的权威在 `packages/openzyme-tools`；`openzyme-engines` 只能调用这些 helper，不维护第二套 command template 或 parser；`openzyme-runtime.hpc_catalog` 仅保留迁移兼容 shim
- 科学结论只能来自可读、已登记并通过对应 parser 的 output artifact。pipeline step 的 parser 必须接收该次 runner 实际返回的 artifact refs，不能用空 artifact list 解析；fpocket 缺 `target_info.txt`、读取失败或无法解析时，即使 runner `raw_result` 自报 `pockets_found` 也不得生成 pocket count 或 `design_signal=proceed`；未知 tool parser 同样不得默认 `proceed`
- dry-run / validation 先生成 `ExecutionPlan`；需要 approval 的外部/backend operation 或显式 `inputs.approval_policy="single_plan"` plan 在用户 approve 前不得提交
- dry-run 必须列出 bio SDK operations、每种 operation 的静态 `max_calls`、route policy、approval requirement、预计 provider requests、分页/配额估计和 expected database artifacts；重复调用和 literal bounded loop 必须计入总量，函数体、动态 iterable、while/comprehension 等无法证明有限上界的外部 SDK 调用在启动 sandbox/runner 前 fail-closed；大型 FASTA、metadata、raw hits、parsed hits 与 sanitized provider transcript 均登记为 artifact，RPC 只返回 bounded summary
- dry-run 必须列出 bio_tools operations、资源估计、expected outputs 和 approval/route 需求；declared output 缺失、格式非法、资源超限、tool_missing 或 oversized log 均返回结构化状态
- plan、approval、execution invocation、RunSpec、output artifact provenance 与 workspace projection 记录 `sandbox_workspace_id`、`source_code_artifact_id`、`source_code_digest`、`source_code_version`、immutable image digest、Pipeline SDK digest、`runtime_identity_digest`、input artifact digests、operation set、backend route 和 expected outputs；正式执行前 Host 重新校验 approved source snapshot 与完整 sandbox runtime identity。persistent `sandbox.exec` 把同一 identity 写入 `SandboxRun.compatibility`，其 adapter operation 只能继承对应 run 的 identity，不得从 tag、workspace 默认值或临时兼容值重建
- approval 绑定完整 operation digest、artifact reads、SDK/toolchain/backend operation list、每种 operation 的 `max_calls`、expected outputs 和资源/配额估计；正式执行在每次 provider/tool/HPC 外部调用前原子消费 approved plan call budget，超过上界返回 `execution_plan_quota_exceeded` 且不得触达 adapter/runner；同 session 内 digest 完全一致可复用 approved approval，digest 漂移必须重新审批或结构化失败
- sandbox `artifacts.materialize` 只能把授权 catalog artifact 安全搬入 workspace；每次读取、复用和复制前后都必须重算 sealed Blob 的 file/tree digest，并与 Artifact row 声明的 digest 一致；同一 artifact digest、target path 和 mode 幂等复用，路径或 Blob digest 冲突必须保留现场、进入 quarantine/GC 台账并结构化失败，不能覆盖同 digest Blob 或继续 materialize；`artifacts.register` 必须在登记前执行非空、FASTA/HMM/CSV 必需列等轻量校验；`artifacts.snapshot_code` 使用同 Blob root 下的临时树原子固化执行源码，复用已有 snapshot 时同样重新验哈希
- 同一 `sandbox_workspace_id` 同时只允许一个 active `sandbox.exec`；container process id 不是 canonical state，`SandboxRun`、file audit、command log artifact 和 changed-file summary 才是审计状态
- sandbox workspace 的 disk quota 是 Host 强制执行的硬边界：`sandbox.file.write` / `sandbox.file.patch` 在原子替换前按 prospective bytes 拒绝超额，`sandbox.exec` 结束后按完整 workspace 重算；子进程、control socket 或 SDK 产出导致超额时，run 必须终止为 `resource_exceeded`、workspace 必须进入 `quota_exceeded`，清理到限额内前不得再次执行
- runner/HPC 不得直接使用 Host 本地 artifact path；输入必须通过 artifact catalog 授权并 staged 到远端工作目录
- `packages/openzyme-execution` 只规范化 Host-supervised runner 调用结果，不直接构造 `MCPHpcServer`；`apps/openzyme-host-api` 作为 HTTP/SSE composition root 负责实例化 runner server 并注入 adapter
- 远端输出只有在 declared `expected_outputs` 中声明且 runner 实际返回可读内容后才会下载并登记为 artifact；missing output、失败 run、不可读 fetch source 均结构化失败，不生成占位文件或伪造科学 artifact。只有同时标记 `fixture_non_cutover` / `simulation_non_cutover` 且携带相应 fixture/simulation 证据的显式测试 outcome 才可生成 placeholder，并必须写入 `synthetic_source=true`、`cutover_eligible=false` 与非产品 scientific status
- 对 HPC-heavy 流程，Host 维护独立的 HPC placement workspace；`hpc_workspace_id` 按 `sandbox_workspace_id + normalized_label` 复用，executor 通过 `hpc.workspace`、`stage_artifact` 和 `fetch_outputs` 声明文件流，Host supervisor 负责真实 staging/fetch 和 artifact registration，不能把该远端工作区描述成 sandbox workspace 的 mirror，也不能把 remote path 暴露给 executor
- Provider cache 只能作为 Host-private optimization；cache key/digest 可进 provenance，但 cache hit 不能替代当前真实 provider/live prerequisite 证据
- AOX/HMM live cutover passed 必须在 S15 eval result 中生成 sealed inline evidence payload 与 `evidence_bundle_digest`，回链 prompt、配置 snapshot、image/toolchain/route/provider digest、approval、operation trace、artifact ids 和 final answer；该证据不是新的顶层 control-plane 真状态

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
