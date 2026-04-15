# OpenZyme 主线架构设计

## 1. 文档定位

本文档描述当前根仓库主线的 V2 架构边界，以及当前主线已经形成的实现模型。

它回答四类问题：

1. 当前主线仓库保留哪些系统能力
2. V2 当前主线的顶层架构如何分层
3. 一个 episode 在 Host、Graph、Runtime、Storage、UI 之间如何流动
4. 当前哪些机制已经落地，哪些还在继续收敛

它**不再**描述已经迁入 `legacy/v1/` 的 V1 Host 实现。  
V1 归档文档见：[legacy/v1/docs/OpenZyme V1实现架构设计.md](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1/docs/OpenZyme%20V1%E5%AE%9E%E7%8E%B0%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1.md)

V2 目标蓝图见：[docs/OpenZyme V2 LangChain重写蓝图.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme%20V2%20LangChain%E9%87%8D%E5%86%99%E8%93%9D%E5%9B%BE.md)

本文档描述的是**当前主线的已确认架构模型**。  
蓝图文档描述的是**更长期的目标态与收敛路线**。  
若两者出现细节差异，应以“当前主线代码 + 当前 OpenSpec”作为当前实现事实，以蓝图作为后续演进方向。

---

## 2. 当前主线边界

根仓库主线已经完成一次 V1 -> legacy 的硬切换。

当前主线保留：

- `apps/mcp-hpc-runner`
- `containers/`
- `database/`
- `docs/`
- `openspec/`
- 已进入 V2 主线实现的目录：
  - `apps/openzyme-host-api`
  - `apps/openzyme-web-ui`
  - `packages/openzyme-graph`
  - `packages/openzyme-domain`
  - `packages/openzyme-runtime`
  - `packages/openzyme-storage`
  - `packages/openzyme-tools`
  - `packages/openzyme-execution`
  - `packages/openzyme-research`

已经迁入 `legacy/v1/` 的旧主线包括：

- Host runtime
- Web Host
- Host CLI
- `mcp-project-memory`
- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `pi-ai-sidecar`
- V1 playgrounds
- V1 相关 OpenSpec 规格与变更工件

因此，根仓库当前**不是**“V1 Host 系统的持续实现目录”，而是：

- 一个保留 HPC 执行基础设施的主线仓库
- 一个承接 OpenZyme V2 重建的主线工作区

---

## 3. 当前 V2 的核心结论

### 3.1 V2 不是 5-phase 顶层工作流

当前主线采用的顶层工作流模型是：

- `intake`
- `design`
- `report_review`

`research` 与 `execution` 仍然是重要能力，但在当前主线中，它们默认被视为：

- `design` agent loop 内部可调用的 graph-backed capabilities
- 设计阶段内部的受控步骤
- Host/UI 可见但不作为独立顶层 phase 暴露的能力边界

因此，当前主线不再把 `research`、`execution` 当作顶层 supervisor phase 暴露给浏览器 phase rail、顶层 graph contract 或架构主图。

### 3.2 V2 采用 artifact-first，而不是 candidate-first

当前主线中，设计阶段的核心业务语义不是“生成候选并选择一个 selected candidate”，而是：

- 维护一个 artifact-first 的设计工作区
- 消费 research 产生的 canonical evidence
- 对 artifact 做聚焦、标注、执行准备和结果回收
- 基于 artifact workspace 与 execution result 继续做 design decision

这意味着：

- `ArtifactRecord` 是当前主线中的核心设计载体之一
- design workspace 的状态以 artifact、focused artifact、workspace summary、execution-ready 信息为中心
- 旧的 candidate-first 词汇不应再作为当前主线的主要语义

### 3.3 顶层工作流真状态不在前端，也不在 artifact 文件树

当前主线的状态真源拆分为三层：

- 关系型存储：canonical business records
- LangGraph checkpointer：execution-local workflow state
- artifact store：大文件与产物

浏览器、CLI、Host read model 都是这些真状态的**投影消费者**，而不是 workflow truth owner。

---

## 4. 顶层分层

当前主线的顶层分层如下：

```text
User
  |
  v
React Web UI / Thin CLI
  |
  v
FastAPI Host API
  |
  v
LangGraph Supervisor Graph
  |
  +--> intake
  +--> design
  +--> report_review
  |
  v
Design-owned capabilities
  |
  +--> research
  +--> execution
  |
  v
Typed tools / application services
  |
  +--> research service
  +--> execution compiler / dispatcher
  +--> reporting service
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> LangGraph checkpointer
  +--> artifact store
  +--> mcp-hpc-runner / SSH / Slurm
```

### 4.1 顶层边界

- Web UI / CLI 不持有工作流真状态
- Host API 是唯一共享入口
- Supervisor Graph 只承担 `intake`、`design`、`report_review` 三个顶层 phase 的 episode 生命周期控制
- `research` 与 `execution` 默认作为 `design` agent loop 内部可调用能力存在
- typed services 负责能力执行，不直接拥有 workflow 生命周期
- `mcp-hpc-runner` 继续作为外部执行边界，而不是被 V2 Host 替换

### 4.2 这样分层的原因

这样设计是为了同时满足：

- episode 可恢复
- approval / resume 可审计
- Web 与 CLI 共享同一 Host 语义
- design 可以在内部多轮调用 research 和 execution，而不把顶层 phase 语义搞复杂
- HPC 相关基础设施保持独立稳定边界

---

## 5. 一次 Episode 的主路径

### 5.1 逻辑主路径

一个典型 episode 的主路径如下：

```text
create_episode
  |
  v
intake
  |
  v
design
  |
  +--> research (0..N 次)
  |
  +--> execution (0..N 次)
  |
  +--> approval / clarification / recoverable failure
  |
  v
report_review
  |
  v
completed
```

其中：

- `intake -> design -> report_review` 是顶层 phase 切换
- design 内的 `research` / `execution` 是内部 loop step
- 某次 execution 触发 approval，不代表 episode 顶层 phase 离开了 `design`
- report_review 只在 design 达到 stop condition 后进入

### 5.2 API 到 Graph 的流动

```text
POST /commands/create_episode
  |
  v
HostApiService.create_episode()
  |
  v
GraphRuntimeFacade.compile_graph()
  |
  v
build_v2_supervisor_graph(...)
  |
  v
thread_id = episode_id
```

关键约束：

- `episode_id` 是业务锚点，也是 graph thread 锚点
- Host 不自行维护第二套 workflow thread id
- 后续 resume 一律在同一个 `episode_id` 线程上继续

### 5.3 Resume 与 Approval 的流动

```text
pending interrupt / approval
  |
  v
Host API resolve_approval / resume_episode
  |
  v
Command(resume=...)
  |
  v
same episode thread resumes
```

当前主线要求：

- interrupt payload 可投影
- approval 可通过 Host 命令解决
- resume 不重新创建 episode
- UI/CLI 只调用 Host，不直接碰 checkpointer

---

## 6. 顶层 Phase 说明

### 6.1 `intake`

`intake` 的职责是：

- 接收用户目标
- 提取约束、成功标准和设计导向
- 生成初始 `DesignBrief`
- 在信息不足时触发 clarification interrupt

`intake` 不负责任何领域执行，也不直接产生最终 artifact。  
它的主要作用是把用户意图转为后续 `design` 可消费的结构化输入。

### 6.2 `design`

`design` 是当前主线的核心 phase。

它的职责是：

- 维护 artifact-first 的设计工作区
- 消费 canonical research outputs
- 选择何时触发 research、何时触发 execution
- 形成当前设计判断、下一步动作和停止条件
- 在必要时请求人工确认

顶层 `design` 的关键特征：

- 它是对用户最主要的工作 phase
- 它可以内部多轮循环
- 它并不要求每次循环都进入 execution
- 它可以在 evidence 不足时先补 research
- 它的输出不是 selected candidate，而是可报告的设计状态与 artifact workspace

### 6.3 `report_review`

`report_review` 的职责是：

- 汇总 design 最终状态
- 汇总相关 evidence、run、artifact、decision trace
- 生成 report record 与 report artifact
- 将 episode 推入 completed

它不是简单地把 execution summary 拼成一段话，而是当前主线中“从可运行 episode 到可消费结果”的最后一层产品语义。

---

## 7. Design 内部能力

### 7.1 为什么 research 不是顶层 phase

在当前主线里，research 的定位是：

- 为 design 提供结构化 evidence
- 由 design 在需要时触发
- 对 UI 可见，但不必提升为顶层 workflow rail

这样做的原因：

- research 本身不是最终目标，而是支撑 design 决策的能力
- 很多 episode 不需要单独经历一个“纯 research phase”
- 如果把 research 提升为顶层 phase，会把 Host/UI 顶层 contract 弄得过于僵硬

### 7.2 design 内部 research 的职责

design 内部 research 负责：

- 检索外部信息
- 归一化 evidence
- 写入 canonical `EvidenceRecord`、`SourceRef`
- 形成 `ResearchSummaryRecord`
- 显式记录 unresolved gaps

它的输出应该服务于：

- 后续 design iteration
- Host projection 中的 evidence pane
- 最终 report_review

### 7.3 为什么 execution 不是顶层 phase

execution 在当前主线里更像：

- design 用来验证、评估、生成 run/artifact 的执行能力
- 一种可能多次发生的内部动作
- 带 approval、失败分类、结果回流的 evaluator / dispatcher

如果把 execution 作为顶层 phase，会导致：

- 顶层 phase rail 与用户心智不一致
- design loop 中的多次 execution 难以表达
- approval 语义在 UI/Host 上变得不清晰

### 7.4 design 内部 execution 的职责

design 内部 execution 负责：

- 把当前 artifact workspace 翻译成 execution handoff
- 编译 execution request / RunSpec
- 通过 `mcp-hpc-runner` 提交执行
- 轮询或接收结果
- 写入 canonical `Run` 与 `ArtifactRecord`
- 把结果返回 design loop 继续决策

因此，execution 对顶层 phase 的影响是间接的：

- 它改变 canonical run / artifact 状态
- 它可能触发 approval / reject / recoverable failure
- 它最终影响 design 是否继续、停止或进入 report_review

---

## 8. Artifact-First 设计工作区

### 8.1 核心语义

当前主线中，design 的主要业务对象不是 candidate，而是 artifact-first workspace。

它至少包含：

- 当前 episode 可见的 artifact 集合
- focused artifact ids
- artifact workspace summary
- execution-ready 标注
- design / research / execution turn 形成的 decision trace

### 8.2 Host / UI 中如何体现

在当前主线中，workspace projection 已经开始体现这种语义：

- `workflow`：顶层 phase 与 summary
- `research`：evidence、summary、gaps、recent turns
- `design`：artifacts、focused artifacts、workspace summary、recent turns
- `execution`：latest result、recent turns
- `report`：最终 report

浏览器并不是“重建 graph state”，而是消费这个 artifact-first 的 workspace projection。

### 8.3 为什么采用 artifact-first

artifact-first 的好处是：

- 不把 OpenZyme 限制在 candidate-selection 场景
- 更适合承接结构文件、日志、结果文件、报告等真实工作流产物
- 更容易让 research、execution、report 共用同一批 canonical artifact
- 更容易在 UI 上做 evidence/run/report/workspace 一体化展示

---

## 9. 状态真源与数据流

### 9.1 三层真源

当前主线的状态真源分为三层：

```text
Relational Store        -> canonical business records
LangGraph Checkpointer  -> execution-local workflow state
Artifact Store          -> large objects and generated files
```

### 9.2 关系型存储负责什么

关系型存储中当前主线关心的核心对象包括：

- `Project`
- `Episode`
- `Decision`
- `Approval`
- `Run`
- `ArtifactRecord`
- `ReportRecord`
- `EvidenceRecord`
- `SourceRef`
- `ResearchSummaryRecord`
- `UnresolvedGapRecord`

这些记录的作用是：

- 在 graph 之外可查询
- 可用于 Host projection
- 可用于 UI 初始加载
- 可用于审计与追踪

### 9.3 Checkpointer 负责什么

LangGraph checkpointer 负责的是 execution-local state，例如：

- 当前顶层 phase
- active node
- pending interrupt
- resume anchor
- loop-local execution state

这些状态不应被浏览器或 CLI 直接消费。  
它们必须先经过 Host/runtime/projection 层转译。

### 9.4 Artifact store 负责什么

artifact store 负责承载：

- 结构文件
- 日志
- result 文件
- report 文件
- 其他本地或远端生成工件

关系型存储只保存 artifact metadata，不保存大对象本体。

### 9.5 Host Projection 的角色

Host projection 负责把：

- relational records
- graph progress
- pending interrupts
- recent runs / artifacts / reports

聚合成 UI/CLI 易用的 workspace snapshot 和 stream events。

也就是说：

- canonical state 先更新
- projection 再刷新
- 前端永远是 projection consumer

---

## 10. 包职责与依赖方向

### 10.1 `apps/openzyme-host-api`

职责：

- 暴露 Host API
- 承载 command / query / stream 入口
- 组装 foundation、graph builder、projection loader

不负责：

- 自己拥有 workflow 真状态
- 绕过 runtime 直接做 package-local persistence

### 10.2 `apps/openzyme-web-ui`

职责：

- 呈现 browser workspace shell
- 消费 Host workspace projection 和 workflow events
- 呈现 top-level phase、evidence、runs、artifacts、report

不负责：

- 重建 raw LangGraph state
- 定义 workflow truth

### 10.3 `packages/openzyme-graph`

职责：

- 定义顶层 phase enum 与 graph-side contract
- 构建 supervisor graph
- 定义 intake / design / report_review 的 graph 逻辑
- 实现 design-owned research / execution graph-backed capabilities

不负责：

- 作为 business record 真源
- 替代 Host projection 层

### 10.4 `packages/openzyme-runtime`

职责：

- runtime foundation
- graph assembly
- repositories
- migration assets
- checkpointer wiring
- Host toolbox

它是 graph、Host、projection 之间的共享装配层。

### 10.5 `packages/openzyme-domain`

职责：

- 提供共享 business entities
- 提供 lifecycle enum
- 作为 storage / graph / host / UI 共享词汇表

### 10.6 `packages/openzyme-storage`

职责：

- 声明 schema / storage contract expectation
- 为 runtime 和 Host contract 提供稳定约束

### 10.7 `packages/openzyme-research`

职责：

- provider adapter
- research normalization
- research result object

它提供“如何做 research”的能力，而不是顶层 workflow 控制。

### 10.8 `packages/openzyme-execution`

职责：

- HPC runner adapter
- runner result normalization
- run/artifact 映射

### 10.9 `packages/openzyme-tools`

职责：

- catalog-backed execution planning
- execution request 编译
- execution result parsing

### 10.10 `apps/mcp-hpc-runner`

职责：

- 远程执行基础设施
- Slurm / SSH / staging / artifact fetch
- 稳定的 HPC 边界

它是当前主线中最明确保留的外部执行边界。

---

## 11. Host、CLI、UI 的协作关系

### 11.1 Host API 是唯一共享入口

所有共享的产品语义都应通过 Host API 暴露，包括：

- create episode
- resume episode
- resolve approval
- load workspace
- load reports / runs / artifacts
- stream workflow-aware events

### 11.2 CLI 是 thin client

当前主线中的 CLI 不应拥有独立 runtime 语义。  
它的职责是：

- 调用 Host API
- 渲染文本输出
- 复用与浏览器一致的业务语义

### 11.3 Web UI 是 workspace projection consumer

浏览器的基本模式是：

```text
workspace snapshot load
  +
workflow-aware stream events
  =>
local view state
```

这意味着：

- 顶层 phase rail 只显示 `intake`、`design`、`report_review`
- evidence / run / artifact / report 放在 workspace pane 中展示
- design 内部 research/execution 对用户可见，但不伪装成顶层 phase

---

## 12. 当前主线已落地与待收敛项

### 12.1 已经落地的部分

- `mcp-hpc-runner` 可独立测试与运行
- V2 主线目录与 uv workspace 已建立
- `openzyme-domain`、`openzyme-runtime`、`openzyme-storage` 已形成最小共享 contract
- `openzyme-graph` 已具备最小 supervisor / phase graph 骨架
- `thread_id = episode_id` 已跑通
- Host API 已提供最小 query / command / projection / stream 接口
- Web UI 已提供最小 browser workspace shell
- thin CLI 已可通过 Host API 工作

### 12.2 当前仍待继续收敛的部分

- 将当前统一大图完全收敛为 `Supervisor + 3 个固定顶层子图`
- 将 design 内 `research` / `execution` 的 loop-local contract 写稳并减少语义漂移
- 将 demo 占位逻辑替换成更完整的业务语义
- 将 Host stream 从 snapshot replay 收敛为更接近持续流的接口
- 将 artifact-first workspace 的 Host/UI 展示进一步产品化
- 将 runtime / graph / projection 的依赖方向继续理顺
- 将 eval / observability 覆盖到更多失败、补研、审批与恢复场景

### 12.3 当前文档中的“已落地”与“待补齐”如何理解

本文档里：

- “已落地”表示主线已有代码路径或 contract 骨架支撑
- “待补齐”表示方向已明确，但产品语义、稳定性或实现深度仍不足

它不等价于：

- “已经完全生产可用”
- “已经没有 contract drift”

---

## 13. 与蓝图文档的关系

本文档是**当前主线架构说明**。  
[docs/OpenZyme V2 LangChain重写蓝图.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme%20V2%20LangChain%E9%87%8D%E5%86%99%E8%93%9D%E5%9B%BE.md) 是**目标态蓝图**。

两者的分工是：

- 本文档回答“现在主线按什么模型理解”
- 蓝图回答“后续要往哪里继续收敛”

如果需要回答：

- V2 为什么选择 LangGraph
- 为什么采用 3-phase + design-owned capabilities
- 为什么状态真源转向 DB + checkpointer
- 为什么 design 采用 artifact-first

应优先看本文档和当前 OpenSpec。  
如果需要讨论更长期的目标态和路线图，再看蓝图文档。

---

## 14. 总结

当前根仓库的架构结论是：

- 主线已经不再继续承载 V1 Host 实现
- 主线保留 HPC 执行基础设施与共享资产
- OpenZyme 已经开始以 V2-first 的方式重建上层 Host、状态层和前端，并具备最小闭环骨架
- 当前顶层工作流模型是 `intake -> design -> report_review`
- `research` 与 `execution` 是 design-owned internal capabilities
- design 的核心语义是 artifact-first workspace，而不是 candidate-first
- V1 相关系统以 `legacy/v1/` 形式冻结保留

因此，任何后续主线实现、OpenSpec change 或架构讨论，都应默认以“当前代码为迁移基线、当前 OpenSpec 为实现约束、本文档为当前架构说明、蓝图为目标态”这一前提推进。
