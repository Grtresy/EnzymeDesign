# OpenZyme V3 目标架构

## 1. 目标结论

OpenZyme V3 的目标不是“更复杂的 graph workflow”，而是一个 **harness-first scientific agent platform**。

角色模型默认采用：

- 用户是甲方
- OpenZyme 是乙方
- `master agent` 作为对外负责人，与用户对话、理解目标、创建和编排 task
- `teammate agent` 作为内部执行者，与 master 同属一个 agent team，默认推进具体 task
- `harness` 作为系统层，负责状态、协议、约束、恢复和投影

顶层结构：

```text
User
  |
  v
Web UI / CLI / API Client
  |
  v
V3 Host Control Plane
  |
  +--> session manager
  +--> task board
  +--> lane manager
  +--> approval protocol
  +--> memory / compaction
  +--> inbox / team protocols
  +--> delegation / agent roster
  +--> shared workspace / artifact catalog
  +--> projection engine
  |
  v
Agent Runtime / Scheduler
  |
  +--> resident agent roster (master + teammates)
  +--> user / inbox wakeups
  +--> explicit scheduler auto-claim for recovery/debug
  +--> approval / engine completion wakeups
  +--> idle / shutdown policy
  |
  v
Agent Harness Kernel
  |
  +--> tool registry
  +--> docs retrieval
  +--> master / teammate loop runtime
  +--> capability dispatch
  +--> background jobs
  |
  +--> deep_research engine
  +--> execution engine
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> artifact store
  +--> event log
  +--> mcp-hpc-runner / SSH / Slurm
```

## 2. V3 产品语义

V3 的产品主语义是：

- `session`
- `task DAG`
- `master agent -> teammate` delegation
- `lane / workspace isolation`
- `approval + inbox + team protocols`
- `capability engines` 被 harness 按需调用
- `report draft` 作为可恢复、可修订、可发布的中间交付物
- `workspace projection` 统一对外暴露当前状态

V3 里不再要求所有产品动作都投射为顶层 phase。

同时，V3 的 agent 不应继续建模为 REST 调用栈里的临时 loop 或一次性 subagent。默认语义是 resident agent team：

- master agent 是默认 resident member，例如 `agent:master`；它负责 user-facing conversation、task 编排与 teammate 协调
- teammate 的身份、role、inbox、task focus、status 与 protocol threads 跨多轮对话持久存在
- 常驻不表示持续占用 LLM 推理；idle agent 不运行模型，只等待 scheduler 的 wakeup signal
- 用户消息只持久化消息并排队 `agent:master` wakeup；Host API 不直接运行 master loop
- teammate 默认由 master delegation 唤醒，也可以被 inbox message、approval resolution、engine completion 或 manual resume 唤醒；task auto-claim 仅用于显式 recovery/debug/operator 场景
- `protocol.send` 不只是写入消息记录，还应产生 recipient 可消费的 wakeup signal

## 3. 顶层组件边界

### 3.1 V3 Host Control Plane

职责：

- 管理 `session` 生命周期
- 持久化 `task / lane / approval / inbox / memory / agent roster / engine invocation`
- 持久化 `artifact catalog / report draft / report / run` 并将其暴露为 session 共享工作面
- 提供统一 API / streaming / projection
- 将用户动作与 control-plane 变化转换为 agent wakeup signal
- 为 UI / CLI 提供 canonical workspace snapshot

不负责：

- 理解用户意图
- 决定 task 内容或项目级拆解
- 深研究推理细节
- HPC 执行编排细节
- 报告具体写作、修订与发布细节

### 3.2 Agent Harness Kernel

职责：

- 维护统一 top-level harness loop
- 执行工具分发
- 协调 tasks / lanes / approvals / delegation / background jobs 的持久化与协议推进
- 注入 docs snippets、memory、tool results
- 维护 teammate spawn / resume / shutdown seam
- 为每个 agent 构建 focused restore context，并暴露 role-scoped tool surface
- 决定何时调用 capability engines 或等待 agent team protocol 继续推进
- 通过 tool-calling model 驱动顶层消息回合

不负责：

- 直接理解用户意图
- 直接决定 task 的业务内容
- 取代 master agent 做项目经理式编排

- 直接成为业务记录存储层
- 直接替代 external runner
- 在顶层重新引入 graph orchestration

### 3.2.1 Agent Runtime / Scheduler

Agent runtime / scheduler 负责让 master 与 teammate 都以“持久 agent 成员”存在，而不是让 master 在 REST handler 调用栈中运行、teammate 在 `task.delegate` 调用栈中短暂运行。

第一阶段目标是单进程 async scheduler：Host 进程内 worker 从持久化 signal queue claim lease，并运行 master 或 teammate 的 bounded turn。多进程 worker、Redis/外部队列、跨进程共享 limiter 是后续扩展，不作为第一版阻塞项；但 claim API、worker id、lease expiry 与 limiter 抽象必须从第一版开始保留。

职责：

- 维护 master 与 teammate lifecycle：`spawned -> working -> idle -> working ... -> shutdown`
- 根据 user message、inbox unread、pending task、approval resolved、engine completed、manual resume 等信号唤醒对应 agent
- 在 agent idle 时停止 LLM turn loop，只保留可恢复身份与 control-plane 状态
- 将 user message、`protocol.send`、explicit delegation、显式 task auto-claim、background completion 转化为可审计的 wakeup event
- 为被唤醒 agent 构建 focused restore context；master context 包含 conversation、task board、protocol threads 与 workspace evidence，teammate context 包含 identity、role、task/lane focus、unread inbox、protocol thread、workspace artifacts 与相关 memory
- 执行 idle timeout、shutdown handshake、failure recovery 与重试策略

不负责：

- 直接决定业务任务内容
- 替代 master 做项目管理
- 把所有 agent 变成永远运行的后台 LLM process
- 把 runtime 内部队列暴露成普通用户需要操作的产品界面

顶层 loop 的默认形态是一个 bounded turn loop：

```text
restore context
  -> call top-level model with tool schemas
  -> inspect tool calls / assistant output
  -> dispatch tools through harness registry
  -> feed tool results back into next model turn
  -> stop when the model emits a final assistant message
  -> or return a waiting state for approval / delegation
```

实现约束：

- 顶层 loop 继续由 OpenZyme 自己维护，不使用顶层 LangGraph / agent graph 编排
- 顶层只复用 LangChain / LangGraph 的模型接入层，例如 chat model 初始化、tool binding、tool-calling response 解析
- capability engine 内部可以继续使用 LangGraph，但 engine state 不能反向成为产品顶层真状态

### 3.3 Capability Engines

能力引擎是被 harness 调用的可替换模块。

初始包括：

- `deep_research`
- `execution`

要求：

- 输入输出稳定
- 内部实现可替换
- 对外暴露统一 tool / command contract
- 被 `engine invocation` 统一调度和恢复
- 不拥有产品顶层真状态
- `execution` 默认通过受控 pipeline sandbox 承载 executor 生成的 Python pipeline，而不是让 executor 直接调用 runner tool
- pipeline 内的 HPC 调用必须通过 `openzyme_pipeline` SDK 进入 Host supervisor，再由 tool contract compiler 生成 runner `RunSpec`
- preprocess 是 pipeline 可调用能力，由 executor 在受控代码中判断和编排；preprocess 产物必须先登记为可信 workspace artifact，再被 HPC step 消费

## 4. 数据流

### 4.1 主路径

```text
create session
  -> ensure resident agent:master
  -> user message is persisted and queues agent:master wakeup
  -> scheduler claims master signal
  -> master agent understands user goal
  -> master agent create / prioritize tasks
  -> master agent spawn / assign / resume teammate agents when needed
  -> agent runtime records roster state and wakeup signals
  -> scheduler claims teammate signal
  -> teammate agent wakes on delegation, inbox, task claim, approval, or engine completion
  -> teammate agent restores on shared session workspace with task/lane focus
  -> teammate inspects artifacts / protocols / task state
  -> teammate chooses tools / capability calls when needed
  -> teammate returns to idle when no immediate work remains
  -> teammate protocol / task / report change queues agent:master wakeup
  -> scheduler claims master signal
  -> report teammate may update report draft directly on shared workspace
  -> assign / claim lane for delegated task when execution context is required
  -> resolve approvals through unified protocol
  -> teammates may communicate peer-to-peer through team protocols
  -> materialize artifacts / runs / report drafts / reports
  -> master agent synthesize progress / deliverables back to user
  -> project workspace snapshot
```

### 4.1.1 消息回合路径

```text
POST /v3/sessions/{session_id}/messages
  -> persist user message
  -> build restore context
  -> call top-level tool-calling model
  -> if tool calls exist:
       dispatch tools
       persist tool side effects
       feed tool results into the next model turn
  -> else if assistant output exists:
       persist assistant message
       auto compact
       return completed
  -> else if approval / delegation wait state exists:
       persist wait state
       auto compact
       return waiting
```

### 4.2 恢复路径

```text
reload session
  -> restore conversation
  -> restore task board
  -> restore lane bindings
  -> restore pending approvals
  -> restore inbox / agent roster / background completions
  -> derive pending wakeup signals for resident teammates
  -> restore memory summary / compressed context
  -> restore engine invocations
  -> continue harness loop
```

### 4.3 UI / CLI 路径

```text
UI/CLI
  -> query / stream v3 workspace projection
  -> display tasks / approvals / runs / artifacts / reports / lane state
  -> send structured commands back to control plane
```

Web UI 的默认交互是 conversation-first：用户通过消息表达目标，通过 approval cards 确认高风险动作；task / lane / engine invocation 等 control-plane 对象由 harness tools 维护，并以只读 workspace inspector 形式展示。CLI 可以保留 task / lane mutation 作为 operator、调试、自动化能力，但这不是普通 Web 用户推进工作的默认方式。

默认主路径不是“用户消息直接触发 capability”，而是：

- 用户与 master agent 对话
- master agent 创建和编排 task
- master agent 将具体 task 分配给 teammate agents
- teammate agents 在共享 session workspace 上围绕 task 推进工作，并按需绑定 lane、调用 capability、读写 artifacts / report drafts / reports
- 显式 recovery/debug/operator auto-claim 可以根据 role、`blocked_by` 与 assignment policy 认领 ready unassigned task，但默认产品路径仍是 master 显式委派
- teammate 之间通过 team protocol 协作，master 负责对外汇报和最终交付

## 5. 关键设计默认值

- `project` 继续保留为上层业务锚点
- `session` 替代 `episode` 成为交互锚点
- `task` 是默认工作组织单元
- `lane` 是默认执行隔离单元
- `delegation` / `team protocol` 默认作为 task-aware harness tool / protocol 存在，而不是 prompt 惯例
- `workspace projection` 是 UI / CLI 唯一合法读模型
- `workspace.conversation` 是 V3 对话真读模型
- teammate 默认拥有 session-wide artifact catalog 的读视野，并以 task / lane focused restore context 工作
- teammate 默认采用 role-scoped tool surface；共享读工具可见，危险写操作保持结构化约束
- teammate 默认是 resident agent member：身份与 inbox 常驻，LLM 推理只在 scheduler 唤醒后运行
- teammate lifecycle 默认包含 `working`、`idle`、`blocked`、`failed`、`shutdown` 等可投影状态
- `protocol.send` 默认产生可被 recipient teammate 消费的 wakeup signal；recipient 下一次恢复时必须看到相关 thread 与 unread payload
- `report draft` 默认不是 capability invocation 的副产物，而是 report teammate 可持续修订的共享工作对象
- `deep_research` 默认优先内嵌 LangGraph / LangChain 实现
- `execution` 默认继续复用 `apps/mcp-hpc-runner`
- `execution` 默认入口是 `execution.pipeline.*`，executor 只能提交或恢复受控 pipeline，不能直接 tool call `exec.run` / runner
- `execution` pipeline 默认运行在 rootless Podman sandbox 中，通过注入的 `openzyme_pipeline` SDK 访问 `artifacts`、`bio`、`bio_tools`、`preprocess` 与 `hpc`
- execution teammate 默认通过 `docs.search` / `docs.read` 按需读取 `docs/v3/execution-pipeline-docs/`，而不是依赖 prompt 内嵌完整 SDK reference
- `hpc.*` SDK 调用默认由 Host supervisor 执行 approval、quota、artifact 权限校验、tool contract 编译和 runner 调用
- `bio.*` SDK 调用默认由 Host supervisor 执行 provider 配置、网络访问、分页、quota、artifact 登记和 provenance；sandbox 不直接联网
- `bio_tools.*` SDK 调用默认由 Host supervisor 执行 tool preflight、local/HPC route、declared output 校验、artifact 登记和 provenance；sandbox 不直接 shell/subprocess 调 CLI
- `execution` 默认仍以 tool contract 编译 `command / inputs / expected_outputs / checks`，并通过 runner staging 传输 artifact
- preprocess 默认作为 pipeline SDK 能力存在，至少覆盖格式转换、Vina receptor/ligand PDBQT 准备与 SMILES 到 3D ligand
- 顶层 LLM 默认最大单回合 tool call 并发上限为 `3`
- research / execution / reporting 这类具体工作默认由 teammate agent 推进，而不是长期由 master 直接亲自完成
- reporting 默认由 report teammate 直接在共享 workspace 上完成，不要求单独 reporting engine

## 6. 推荐 Monorepo 包布局

V3 默认不沿用拆散的产品级 graph/storage 包切法。

推荐收敛为：

- `packages/openzyme-domain`
  负责共享 domain models、canonical types、稳定词汇表
- `packages/openzyme-core`
  负责 control plane、repositories、runtime、tool registry、memory、approval、lane、projection、host-facing core services
- `packages/openzyme-engines`
  负责 `deep_research`、`execution` 等 capability engines
- `apps/openzyme-host-api`
- `apps/openzyme-host-cli`
- `apps/openzyme-web-ui`
- `apps/mcp-hpc-runner`

这样划分的原因：

- `domain` 的边界稳定，适合单独保留
- control plane、runtime、storage、tool dispatch 在 V3 里耦合很强，早期继续拆成多个包只会增加摩擦
- engines 的替换性和演进节奏与 core 不同，适合单独收口
- apps 仍然维持产品入口和外部执行边界

当前边界：

- `packages/openzyme-runtime` 保留 settings、LLM、limits、research tool seams 与 capability-local helper
- `packages/openzyme-tools` 保留工具/adapter helpers
- `packages/openzyme-research` 和 `packages/openzyme-execution` 保留 provider/runner integration

所有边界必须满足两条约束：

- 新增 V3 顶层语义只能先落到 `domain / core / engines` 的目标边界，不得继续扩展旧的产品级包职责
- capability-local state 必须回写 control plane 后才能成为产品可见状态

## 7. 参考实现路径

Harness 思想参考：

- `/home/grtresy/VSCodeRepo/learn-claude-code/README-zh.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s09-agent-teams.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s10-team-protocols.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s11-autonomous-agents.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/agents/s_full.py`

Deep research 参考：

- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/deep_researcher.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/docs/deep_researcher_graph_详解.md`

OpenZyme 主线参考：

- `/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md`
- `/home/grtresy/VSCodeRepo/EnzymeDesign/packages/openzyme-core/src/openzyme_core/`
