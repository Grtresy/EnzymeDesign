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

- `apps/openzyme-host-api`：FastAPI Host API，包含 V3 `/v3` 产品接口
- `apps/openzyme-host-cli`：Thin CLI client
- `apps/openzyme-web-ui`：浏览器工作区 UI
- `apps/mcp-hpc-runner`：SSH/Slurm/HPC runner 边界

当前主线 V3 优先落点：

- `packages/openzyme-domain`：control-plane 领域对象，如 `Session`、`Task`、`Lane`、`ApprovalRequest`、`InboxMessage`、`AgentMember`、`AgentRuntimeSignal`、`EngineInvocation`、`RunRecord`、`SessionArtifactRecord`、`SessionReportDraftRecord`、`SessionReportRecord`
- `packages/openzyme-core`：V3 harness、task board、lane manager、protocol、projection、agent runtime、scheduler、tool registry、report draft tools、docs tools
- `packages/openzyme-engines`：capability engines，尤其是 execution pipeline engine 与 sandbox supervision
- `packages/openzyme-pipeline`：受控 execution pipeline sandbox 内 SDK
- `packages/openzyme-research`：research provider 与 research capability 相关实现
- `packages/preprocess-backend`：受控 preprocess 能力后端

共享能力包：

- `packages/openzyme-runtime`
- `packages/openzyme-tools`
- `packages/openzyme-execution`

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
  +--> docs.search / docs.read
  +--> protocol.send / protocol.thread
  +--> task.delegate / task.update
  |
  v
Capability Engines
  |
  +--> deep_research / provider tools
  +--> execution.pipeline.* / sandbox / openzyme_pipeline SDK
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
- `POST /v3/approvals/{approval_id}/resolve`

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
- `artifacts` 是 session 共享工作面，不能暴露 Host repo path、sandbox host path、`storage_uri`、SSH/Slurm config 或 runner credentials
- `report_drafts` 是 reporter 的中间交付面，不是一次 invocation 的临时字符串
- `capabilities` 按 capability key 承载 research/execution 等投影，避免把 engine 内部状态固化成顶层 contract

---

## 7. Control Plane、Protocol 与 Runtime

### 7.1 Task 与 Delegation

`Task` 是 session 内可调度、可委托、可恢复、可完成的内部工作单元。默认由 master agent 基于用户对话创建和编排。

`task.delegate` 的职责：

- 校验 task 是否存在
- 校验 teammate role 是否有效
- 拒绝 blocked、already assigned、非 `todo` task
- 持久化 delegation payload
- 调用 `ProtocolService.delegate()`
- 返回 `wakeup_queued` 或明确失败 envelope

`ProtocolService.delegate()` 的职责：

- 创建或更新 `AgentMember`
- 写入 `delegation_request` inbox message
- 排队 runtime wakeup signal
- 发出 `agent.spawned` / `agent.delegated` 等事件

业务 task 终态必须由 agent 通过 `task.update` 或已文档化机械迁移显式写入；runtime idle、max steps、tool result 或 protocol message 本身不自动表示 task completed。

### 7.2 Inbox 与 Protocol

`protocol.send` / `protocol.thread` 是 agent team 内部协调工具。

默认语义：

- `protocol.send` 写入有 recipient、correlation、payload、status 的 `InboxMessage`
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

---

## 8. Capability Engines

### 8.1 Deep Research 与 Provider Tools

`researcher` teammate 可以直接调用轻量 provider tools，也可以在开放式、多步、跨来源综合任务中调用 `deep_research` engine。

默认 provider / research surface 包括：

- PubMed
- Semantic Scholar
- UniProt
- RCSB PDB
- InterPro
- Tavily / web search 类能力（按配置与 live gate 启用）

Research 输出应归一化为 evidence、source refs、gaps 和必要的 workspace artifacts。普通 search hit 是 source/evidence，不应伪装成 artifact；真实下载或生成的 sequence / structure 文件才进入 artifacts。

### 8.2 Execution Pipeline

V3 execution 的主路径是 executor-authored pipeline code，而不是 executor 直接调用 runner、SSH、Slurm 或 runner config。

关键接口：

- `execution.pipeline.start`
- `execution.pipeline.status`
- sandbox 内 `openzyme_pipeline` SDK
- docs 工具 `docs.search` / `docs.read`

执行边界：

- pipeline code 在受控 rootless Podman sandbox 中运行
- sandbox 默认无网络、非 root、资源受限
- Host repo、用户 home、`.ssh`、数据库、runner config、HPC credentials 不得挂载进 sandbox
- HPC 请求只能通过 `openzyme_pipeline.hpc` 进入 Host supervisor，再编译为 runner `RunSpec`
- dry-run / validation 先生成 `ExecutionPlan`；需要 approval 的 HPC operation 在用户 approve 前不得提交
- approval 绑定 plan digest、artifact reads、HPC operation list、expected outputs 和资源估计
- runner/HPC 不得直接使用 Host 本地 artifact path；输入必须通过 artifact catalog 授权并 staged 到远端工作目录
- 远端输出只有在 declared `expected_outputs` 中声明后才会下载并登记为 artifact

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

- `live_e2e` 是外部配置和 live 依赖的必要 gate，但不能单独证明单消息完整报告生产路径已经产品完成
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
