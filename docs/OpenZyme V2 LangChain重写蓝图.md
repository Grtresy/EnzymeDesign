# OpenZyme V2 LangChain重写蓝图

## 1. 文档定位

本文档用于落盘本次对话形成的 OpenZyme V2 重写方案，目标是回答：

- 如果用 LangChain 生态重写 OpenZyme，主内核应该怎么选
- Host、前端、执行基础设施和状态真源应该如何重新划分
- 哪些现有能力值得保留，哪些应该收回 Host 内部
- 后续如果立项实施，应该按什么顺序推进

本文件是一个 V2 设计蓝图，不直接等价于当前仓库实现，也不覆盖 `docs/OpenZyme架构设计.md` 对现状的描述。

---

## 2. 核心结论

### 2.1 技术路线

OpenZyme V2 采用如下组合：

- **LangGraph 作为主内核**
- **LangChain 作为模型、工具、structured output 与 agent primitives 层**
- **Deep Agents 不作为主框架，只作为局部可选增强**

原因：

- OpenZyme 的核心复杂度在于可恢复工作流、审批中断、长任务追踪、执行编排、跨入口一致性和审计，而不是一个通用聊天 agent。
- 这些能力更适合由显式状态图、持久化 checkpoint 和明确的阶段边界承载。
- `Deep Agents` 更适合开放式、多文件、多子代理的泛化任务，不适合直接承载 OpenZyme 这种 workflow-first 产品控制面。

### 2.2 产品与系统边界

V2 的目标不是把 OpenZyme 退化成“一个带工具的聊天机器人”，而是构建一个：

- workflow-first
- durable
- auditable
- Web-first
- execution-aware

的 agent host。

### 2.3 前端结论

Web UI 采用：

- **自建 React 产品前端**
- **LangGraph frontend 作为 workflow/streaming 交互层**
- **LangChain frontend 作为聊天、工具调用、interrupt 交互层**
- **Deep Agents frontend 仅作为局部模式参考，不作为主 UI 架构**

这意味着 OpenZyme 的主页面、项目导航、episode 视图、run/artifact 面板、报告页依然由自定义前端承担；LangChain 官方 frontend 能力只接管 agent interaction layer，而不是整个产品信息架构。

---

## 3. 架构目标

V2 需要满足以下目标：

1. 将自然语言目标转为可恢复的多阶段工作流，而不是一次性 prompt 执行。
2. 将长期状态真源从当前工作区文件树迁移为数据库与 checkpoint 体系。
3. 保持 Web 为主入口，CLI 为辅入口，但两者共享同一 Host 语义。
4. 将高价值但边界清晰的领域能力收敛为 Host 内部 typed tools / service adapters。
5. 保留 HPC/远程执行基础设施的独立边界，不在 V2 中重写这部分基础设施。
6. 让前端可以感知 graph phase、node progress、interrupt、approval、run 和 artifact，而不是只看聊天消息。

---

## 4. 总体架构

### 4.1 顶层分层

```text
User
  |
  v
React Web UI / CLI
  |
  v
FastAPI Host API
  |
  v
LangGraph Supervisor Graph
  |
  +--> Intake Subgraph
  +--> Research Subgraph
  +--> Design Subgraph
  +--> Execution Subgraph
  +--> Report/Review Subgraph
  |
  v
Typed Tools / Application Services
  |
  +--> Preprocess Service
  +--> Research Service
  +--> Design Service
  +--> Execution Compiler / Dispatcher
  +--> Reporting Service
  |
  v
Persistence + Infra
  |
  +--> Postgres / equivalent relational store
  +--> LangGraph Postgres checkpointer
  +--> Artifact store
  +--> HPC runner / Slurm / SSH
  +--> Model providers
```

### 4.2 角色划分

- **Web UI / CLI**：交互壳，不持有工作流真状态。
- **Host API**：统一入口，暴露项目、episode、resume、approval、runs、artifacts、report 等接口。
- **Supervisor Graph**：顶层控制面，负责阶段切换、interrupt、resume、终止与恢复。
- **Specialist Subgraphs**：负责领域内逻辑，不抢占全局控制权。
- **Typed Tools / Services**：承接能力执行，不直接承载 episode 生命周期。
- **Persistence**：持久化 graph state、业务记录、审计记录与工件索引。

---

## 5. 图架构设计

### 5.1 主图模式

主图采用：

- **Supervisor + specialist subgraphs**

而不是：

- 单一超级 agent
- 一个覆盖所有阶段的大 Prompt loop
- 大量持续协作的 agent society

### 5.2 固定子图

V2 默认只保留 5 个固定子图：

1. `intake`
2. `research`
3. `design`
4. `execution`
5. `report_review`

这样做的目的：

- 保持系统的领域可解释性
- 让前端能够稳定映射 graph phase
- 限制 agent 自由度，降低不可控复杂度

### 5.3 各子图职责

#### `intake`

- 用户目标澄清
- 提取约束与成功标准
- 生成初始 `DesignBrief`
- 在信息不足时触发 clarification interrupt

#### `research`

- 检索外部研究证据
- 归一化 evidence
- 形成可追溯的 evidence refs
- 为 design/execution 阶段提供结构化输入

#### `design`

- 生成设计候选
- 比较候选优先级
- 形成下一步实验或计算建议
- 在必要时请求人类确认或加约束

#### `execution`

- 调用预处理能力
- 编译 execution request / RunSpec
- 提交执行
- 轮询状态
- 抓取 artifact
- 处理失败、重试和人工审批

#### `report_review`

- 汇总结果
- 生成面向用户的说明
- 写入 decision trace
- 产出阶段总结与最终 report

### 5.4 中断与恢复

中断语义统一使用 LangGraph 的 interrupt/resume 模式：

- clarification
- approval
- escalation
- recoverable failure handoff

所有恢复入口都围绕同一个 `thread_id = episode_id` 展开，Web 与 CLI 不各自维护私有工作流状态。

---

## 6. 状态真源与持久化

### 6.1 迁移方向

V2 不再以项目工作区文件树作为长期状态真源，而是采用：

- **数据库存业务状态**
- **LangGraph checkpointer 存执行状态**
- **artifact store 存产物**

### 6.2 分层存储策略

#### 业务状态

建议进入关系型数据库：

- projects
- episodes
- decisions
- evidence
- candidates
- runs
- approvals
- projections

#### 图执行状态

建议进入 LangGraph checkpointer：

- 当前 phase
- graph node state
- pending interrupt
- checkpoint lineage
I- resume position

#### 工件与大文件

建议进入 artifact store：

- 结构文件
- 日志
- 报告
- 结果文件
- 下载缓存

### 6.3 工作区角色变化

V2 中项目工作区仍然存在，但只承担：

- 用户输入文件
- 调试缓存
- 本地查看友好的导出工件

它不再是系统真状态来源。

---

## 7. 领域能力边界

### 7.1 基本原则

本次蓝图默认将多数现有 MCP 能力并入 Host 内部 typed tools / service adapters，而不是继续以 MCP 作为应用内主边界。

原因：

- 对 V2 而言，主要目标是更紧密地让 graph、typed state、tool execution 和 frontend stream 协同。
- 对仓库内自有能力，跨进程 MCP transport 的收益低于统一类型系统和调用路径的收益。

### 7.2 需要保留独立边界的能力

以下能力仍建议保留独立边界：

- `mcp-hpc-runner` 或等价 execution runtime

原因：

- 它本身已经是稳定的基础设施层
- 它处理 SSH / Slurm / staging / artifact fetch / job lifecycle
- 重写收益低，迁移风险高

### 7.3 适合收回 Host 的能力

以下能力默认改造成 Host 内部 service / tool adapter：

- preprocess
- tool contract compilation
- research aggregation
- report generation

是否保留它们的外部 MCP 版本，可以作为互操作层附加提供，但不再作为 V2 主调用路径。

---

## 8. 前端方案

### 8.1 总体策略

前端采用：

- **自建 React Web App 负责产品壳**
- **LangGraph frontend 模式负责 graph stream 与 node output 渲染**
- **LangChain frontend 模式负责消息、tool call、interrupt、history**

### 8.2 不采用的方案

不采用以下方案作为主路径：

- 将 OpenZyme 做成纯 chat 界面
- 将 Deep Agents frontend 直接当产品主壳
- 将 workflow 状态主要保存在浏览器前端

### 8.3 页面结构

建议固定为五个主要区域：

1. `Project shell`
2. `Workflow pane`
3. `Chat / Operator pane`
4. `Evidence / Run pane`
5. `Report pane`

#### `Project shell`

- 项目切换
- episode 列表
- 当前状态摘要
- 最近 run / artifact

#### `Workflow pane`

这是最贴近 LangGraph frontend 的区域，负责展示：

- 当前 phase
- graph node 状态
- node 输出摘要
- 当前等待点
- 当前恢复位置

#### `Chat / Operator pane`

这是最贴近 LangChain frontend 的区域，负责展示：

- 用户消息
- assistant 消息
- tool 调用摘要
- clarification
- approval interrupt
- resume 操作

#### `Evidence / Run pane`

- research evidence 列表
- run timeline
- log 摘要
- artifact 索引
- job 状态与重试入口

#### `Report pane`

- 阶段总结
- decision rationale
- report markdown / rich view

### 8.4 与 LangChain 官方 frontend 的关系

#### 适合直接借鉴的能力

- `useStream`
- messages/tool calls/interrupts/history 流式渲染
- 将 graph/node 输出映射成 cards
- agent 交互层状态同步

#### 只能局部借鉴的能力

- Deep Agents 的 todo/subagent/sandbox

这些模式更适合：

- 局部研究子任务可视化
- 未来的专家子图辅助面板

不适合承担 OpenZyme 的主信息架构。

---

## 9. 核心类型与接口

### 9.1 核心领域对象

V2 统一使用 typed domain model，建议核心对象固定为：

- `ProjectRecord`
- `EpisodeRecord`
- `EpisodeCheckpointRef`
- `DesignBrief`
- `ConstraintSet`
- `EvidenceRecord`
- `CandidateRecord`
- `ExecutionRequest`
- `ExecutionRunRecord`
- `ApprovalRequest`
- `DecisionLogEntry`
- `ArtifactRecord`

### 9.2 Graph state

建议拆为两层：

#### `SupervisorState`

包含：

- project_id
- episode_id
- current_goal
- phase
- selected_candidate_id
- latest_run_id
- pending_interrupt
- active_approval
- stop_reason

#### Phase-local state

按子图拆分：

- intake state
- research state
- design state
- execution state
- report state

避免一个巨型共享 state 承担所有语义。

### 9.3 前端读模型

建议面向前端增加聚合投影：

- `EpisodeProjection`
- `GraphExecutionView`
- `FrontendStreamEvent`

其中：

- `EpisodeProjection` 提供页面初始化时的聚合快照
- `GraphExecutionView` 提供 workflow pane 的结构化数据
- `FrontendStreamEvent` 提供流式 token、node output、tool call、interrupt、resume 信息

### 9.4 Host API

默认公开以下能力：

- `POST /projects`
- `POST /episodes`
- `POST /episodes/{id}/start`
- `POST /episodes/{id}/resume`
- `POST /episodes/{id}/approve`
- `POST /episodes/{id}/reject`
- `GET /episodes/{id}`
- `GET /runs/{id}`
- `GET /artifacts/{id}`
- `GET /reports/{episode_id}`

CLI 应改为这些接口的 thin client，而不是维持一套独立 runtime 语义。

---

## 10. 测试与可观测性

### 10.1 单元测试

覆盖：

- domain models
- tool adapters
- execution adapters
- graph routing 条件
- structured output 解析

### 10.2 图级测试

覆盖：

- episode 启动
- supervisor 到子图切换
- interrupt 后 resume
- checkpoint 恢复
- stop reason 一致性
- 失败重试和人工接管

### 10.3 前端集成测试

覆盖：

- `useStream` 消费 graph 输出
- workflow pane 的实时节点状态更新
- approval / reject / resume 操作
- run / artifact 面板和后端投影一致

### 10.4 端到端验收

至少跑通一条真实样例闭环：

- 创建 episode
- intake 澄清
- 进入 research 或 design
- 提交 execution
- 处理中断或审批
- 查看 artifact
- 生成 report

### 10.5 可观测性

建议接入 LangSmith：

- trace graph execution
- trace tools
- trace subgraphs
- 将 trace/span id 绑定到 decision log

---

## 11. 迁移与实施顺序

### 11.1 推荐策略

建议按 V2 新系统并行建设，而不是原地替换现有 runtime。

### 11.2 四阶段实施

#### Phase A：定义基础契约

- V2 domain model
- DB schema
- graph state schema
- Host API contracts
- frontend read model

#### Phase B：打通最小主链

- intake 子图
- execution 子图
- approval / resume
- Postgres + checkpointer
- 最小 Web UI

目标是先跑通一个从目标到执行再到结果读取的最小闭环。

#### Phase C：补齐研究与设计

- research 子图
- design 子图
- evidence model
- candidate comparison
- richer workflow pane

#### Phase D：补齐报告与产品化

- report_review 子图
- Web UI 完整页面
- CLI 薄客户端
- observability / evals
- 旧系统迁移脚本

---

## 12. 决策摘要

本次蓝图的最终默认决策如下：

- 主内核：LangGraph
- 下层基础：LangChain
- Deep Agents：仅局部可选
- 主图组织：Supervisor + 少量专家子图
- 产品入口：Web 为主，CLI 为辅
- 状态真源：数据库 + LangGraph checkpointer
- 能力边界：多数收回 Host 内部 typed tools
- 执行基础设施：保留独立 HPC/remote execution boundary
- 前端策略：自建 React UI + LangGraph/LangChain frontend 能力

---

## 13. 后续可直接衔接的工作

如果要从蓝图进入实施，下一步最值得产出的不是代码，而是三类正式工件：

1. V2 domain model 与 DB schema 草案
2. Supervisor graph 与 5 个子图的状态与节点设计
3. Web UI 信息架构与 API/stream contract 草图

在此基础上，再决定是否需要为 V2 新开 OpenSpec change。
