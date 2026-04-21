# OpenZyme V3 目标架构

## 1. 目标结论

OpenZyme V3 的目标不是“更复杂的 graph workflow”，而是一个 **harness-first scientific agent platform**。

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
  +--> projection engine
  |
  v
Agent Harness Kernel
  |
  +--> tool registry
  +--> skill loader
  +--> subagent / delegation manager
  +--> capability dispatch
  +--> background jobs
  |
  +--> deep_research engine
  +--> execution engine
  +--> reporting engine
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> artifact store
  +--> event log
  +--> mcp-hpc-runner / SSH / Slurm
```

## 2. V3 与 V2 的根本区别

V2 的产品主语义是：

- `episode`
- `intake -> design -> report_review`
- design 内部再调用 research / execution

V3 的产品主语义改为：

- `session`
- `task DAG`
- `lane / workspace isolation`
- `approval + inbox + delegation protocols`
- `capability engines` 被 harness 按需调用
- `workspace projection` 统一对外暴露当前状态

V3 里不再要求所有产品动作都投射为顶层 phase。

## 3. 顶层组件边界

### 3.1 V3 Host Control Plane

职责：

- 管理 `session` 生命周期
- 持久化 `task / lane / approval / inbox / memory / agent roster / engine invocation`
- 提供统一 API / streaming / projection
- 触发 harness kernel 运行
- 为 UI / CLI 提供 canonical workspace snapshot

不负责：

- 深研究推理细节
- HPC 执行编排细节
- 报告具体生成细节

### 3.2 Agent Harness Kernel

职责：

- 维护统一 top-level harness loop
- 执行工具分发
- 协调 tasks / lanes / approvals / delegation / background jobs
- 注入 skills、memory、tool results
- 维护 subagent spawn / resume / shutdown seam
- 决定何时调用 capability engines
- 通过 tool-calling model 驱动顶层消息回合

不负责：

- 直接成为业务记录存储层
- 直接替代 external runner
- 在顶层重新引入 graph orchestration

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
- `reporting`

要求：

- 输入输出稳定
- 内部实现可替换
- 对外暴露统一 tool / command contract
- 被 `engine invocation` 统一调度和恢复
- 不拥有产品顶层真状态

## 4. 数据流

### 4.1 主路径

```text
create session
  -> create / prioritize tasks
  -> assign / claim lane
  -> run harness loop
  -> delegate subtasks when needed
  -> call deep_research when needed
  -> call execution when needed
  -> resolve approvals through unified protocol
  -> materialize artifacts / runs / reports
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

## 5. 关键设计默认值

- `project` 继续保留为上层业务锚点
- `session` 替代 `episode` 成为交互锚点
- `task` 是默认工作组织单元
- `lane` 是默认执行隔离单元
- `delegation` 默认作为 harness tool / protocol 存在，而不是 prompt 惯例
- `workspace projection` 是 UI / CLI 唯一合法读模型
- `workspace.conversation` 是 V3 对话真读模型
- `deep_research` 默认优先内嵌 LangGraph / LangChain 实现
- `execution` 默认继续复用 `apps/mcp-hpc-runner`
- 顶层 LLM 默认最大单回合 tool call 并发上限为 `3`

## 6. 推荐 Monorepo 包布局

V3 默认不沿用 V2 那种偏细的 package 切法。

推荐收敛为：

- `packages/openzyme-domain`
  负责共享 domain models、canonical types、稳定词汇表
- `packages/openzyme-core`
  负责 control plane、repositories、runtime、tool registry、memory、approval、lane、projection、host-facing core services
- `packages/openzyme-engines`
  负责 `deep_research`、`execution`、`reporting` 等 capability engines
- `apps/openzyme-host-api`
- `apps/openzyme-host-cli`
- `apps/openzyme-web-ui`
- `apps/mcp-hpc-runner`

这样划分的原因：

- `domain` 的边界稳定，适合单独保留
- control plane、runtime、storage、tool dispatch 在 V3 里耦合很强，早期继续拆成多个包只会增加摩擦
- engines 的替换性和演进节奏与 core 不同，适合单独收口
- apps 仍然维持产品入口和外部执行边界

迁移桥接默认值：

- `packages/openzyme-runtime` + `packages/openzyme-storage` + `packages/openzyme-tools`
  逐步并入 `packages/openzyme-core`
- `packages/openzyme-research` + `packages/openzyme-execution`
  逐步并入 `packages/openzyme-engines`
- `packages/openzyme-graph`
  仅保留 capability engine 内部图，最终不再承载产品顶层真状态

迁移时允许先在旧目录中完成改造，但必须同时满足两条约束：

- 新增 V3 顶层语义只能先落到 `domain / core / engines` 的目标边界，不得继续扩展旧的产品级包职责
- 每轮过渡实现都要附带明确的目标归宿，避免长期停留在 mixed-package 状态

## 7. 参考实现路径

Harness 思想参考：

- `/home/grtresy/VSCodeRepo/learn-claude-code/README-zh.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/agents/s_full.py`

Deep research 参考：

- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/deep_researcher.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/docs/deep_researcher_graph_详解.md`

现有 OpenZyme V2 现状参考：

- `/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md`
- `/home/grtresy/VSCodeRepo/EnzymeDesign/packages/openzyme-graph/src/openzyme_graph/`
