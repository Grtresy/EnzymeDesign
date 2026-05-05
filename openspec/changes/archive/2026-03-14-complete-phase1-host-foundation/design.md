## Context

OpenZyme 当前的 Phase 1 基础能力已经可用：Host runtime、CLI、Web Host、agent workflow、project memory 和执行后端都已经落地。但几条关键演进路径仍然没有收口：

- runtime 到 `mcp-project-memory`、`mcp-preprocess`、`mcp-hpc-tool-contracts` 的访问仍以库级直连为主，尚未形成统一的 host-side capability / client 边界；
- capability discovery 已有单独 change 草案，但尚未进入当前主工作流；
- workflow 的 `decide` 逻辑在 orchestrator 中，而 `execute selected action -> write manifest -> record observation` 仍有部分散落在 service 层；
- canonical snapshot、decision trace 和 append-only 审计事件之间的关系尚不够清晰；
- 当前讨论里的关键澄清是：这里要收敛的是 MCP 风格 contract，而不是把 `mcp-project-memory` 强制变成一个永远运行在 Host 对面的独立 server 进程；
- 这些问题一旦带入 Phase 2/3，会导致 capability 扩张、状态恢复、并发入口和解释性功能出现高返工成本。

因此本次设计不是推翻现有 MVP，而是在保留当前工作闭环的前提下，把 Phase 1 的正式底座抽象补齐，并吸收 `add-host-capability-discovery` 已提出但未实现的能力发现设计。

## Goals / Non-Goals

**Goals:**

- 为 Host runtime 定义统一的 MCP-facing 边界，替代“不同后端各自被直接 import”的长期形态。
- 在 Host 中建立 capability registry，并支持 summary -> inspect -> detail contract 的按需展开流程。
- 让 agent planning、runtime 服务和宿主界面共享同一套 capability 与 workflow state 语义。
- 收敛 canonical state、append-only audit log 和 resume/version 校验的职责边界。
- 把 action execution / observation 回灌建模为显式 workflow transition，而不是单纯的 service 层副作用。
- 让新 change 完整覆盖 `add-host-capability-discovery` 的需求，并作为其替代方案。

**Non-Goals:**

- 不要求本次就把所有后端都迁移成真实远程 stdio MCP 进程通信；重点是统一 runtime-facing contract，而不是强制网络形态。
- 不在本次变更中重写 Web Host 的整体 UI，只补充 trace / debug / stale-state 相关的 requirement。
- 不在本次变更中实现多 agent 并发 orchestration，但数据模型必须为 `role/agent_id` scope 预留空间。
- 不在本次变更中推进 Phase 2/3 的高级体验，如 checkpoint、parallel branches、external collaboration hooks。

## Decisions

### 1. 引入 Host capability gateway，统一 runtime 到各 MCP 能力的访问边界

`HostRuntime` 不再把 memory、preprocess、tool contracts 视为“直接 import 的内部库”，而是通过统一的 host capability gateway 访问。

该 gateway 负责三类动作：

- 列出 agent-selectable capability summaries；
- inspect 单个 capability 的 detail contract；
- 执行 capability 下的受控 action，并返回规范化 execution result。

这样做的原因是：

- runtime 的上层不再感知底层是 in-process adapter、本地 MCP client，还是未来的 stdio/server connection；
- capability discovery 与实际执行路径共享同一套标识和元数据；
- 后续新增 `mcp-bio-research`、`mcp-structure-workbench` 时，不需要继续扩散新的直连代码路径。

备选方案：

- 要求所有现有后端立即切换为真实 MCP client 连接。
- 保留现在的 direct import 方式，只在 agent prompt 层增加 capability summary。

不采用的原因：

- 第一种迁移成本过大，会把本次 change 变成基础设施重写。
- 第二种没有解决长期边界漂移问题。

因此首版采用“统一 contract + 可替换 adapter”的策略：底层实现可以先继续复用本地 Python adapter，但 runtime-facing 语义必须统一。

### 1.1 `mcp-project-memory` 采用 MCP-style contract，而不是强制独立 server 形态

本次 change 对 `project memory` 的要求是：

- 对 Host/runtime 暴露稳定的资源/工具契约；
- 作为 canonical state source 与 append-only audit source 被统一访问；
- 允许当前实现继续以内嵌 adapter 或同进程 service 方式承载；
- 为后续切换到真实 MCP server transport 保留兼容路径。

换句话说，我们要统一的是 interface boundary，而不是 deployment topology。

这样做的原因是：

- 当前单机本地工作流中，强制引入独立 transport 只会增加复杂度，而不会提升架构正确性；
- 但如果继续把它视为 Host 私有内部模块，又会失去跨宿主共享状态真源的清晰边界；
- 用 MCP-style contract 承载语义，可以同时保留演进空间与本地实现效率。

备选方案：

- 直接把 `project memory` 彻底并回 Host Core 内部模块。
- 立刻强制所有路径通过独立 `mcp-project-memory` server 访问。

不采用的原因：

- 第一种会弱化 canonical resource boundary，让 CLI/Web/未来 app 更容易绕过统一状态契约。
- 第二种会把当前 Phase 1 收尾目标错误地膨胀成 transport / deployment 重构。

### 2. capability registry 成为 agent 可见能力的唯一正式目录

Host 维护逻辑上的 capability registry，registry 条目而不是 MCP server 原始 schema，才是 agent 默认看到的能力集合。

每个条目至少包含：

- `capability_id`
- server / provider identity
- summary
- `use_when`
- result shape
- latency/cost hints
- inspect handle
- 可见性策略与 role scope

registry 只收录 agent 需要主动发现和选择的能力；基础设施型能力继续隐藏在 runtime 后面。

备选方案：

- 继续把 server 的 tools/list 直接视为可见能力目录。

不采用的原因：

- 这样会让 capability discovery 退化为“换个名字暴露原始 schema”，无法控制上下文大小，也无法表达 Host 级暴露策略。

### 3. summary/detail contract 分离，并把 detail visibility 绑定到 decision scope

默认情况下 agent 只消费 capability summaries。只有当 agent 或 runtime 明确 inspect 某个 capability 时，Host 才生成 detail contract。

detail visibility scope 至少绑定：

- `episode_id`
- `active_state_version`
- `role` 或等价 `agent_id`

scope 生命周期结束后：

- Host 恢复为 summary-only；
- detail contract 可以保留缓存，但不继续默认暴露给 LLM；
- 后续需要时必须再次 inspect。

备选方案：

- 一次 inspect 后永久加入上下文。
- 只按全局 episode 缓存，不区分 role。

不采用的原因：

- 前者无法解决 prompt 膨胀。
- 后者会阻断未来多 agent / role 的隔离需求。

### 4. workflow 将 execute/observe 收敛为显式 transition，而不是仅靠 service 层副作用

本次不要求把真实工具执行塞进 LangGraph 节点内部，但要求 action execution lifecycle 具备明确的 workflow transition 语义。

最小 transition 集合包括：

- `action_selected`
- `action_execution_started`
- `action_execution_finished`
- `observation_recorded`
- `capability_inspected`
- `gate_created`
- `interrupt_resolved`

这些 transition 既更新 canonical snapshot，也写入 append-only workflow audit log。

这样做的原因是：

- 既能保留当前 service 驱动执行的工程简洁性；
- 又能避免后续 checkpoint、回放、解释和 stale-state 调试时只看到“快照变化”而看不到事件链。

备选方案：

- 彻底重写成“执行也完全由 LangGraph node 驱动”。

不采用的原因：

- 这会把一次基础收尾变成整套 workflow runtime 重写。
- 当前更需要统一状态和事件语义，而不是强行重构执行引擎。

### 5. canonical snapshot 与 append-only audit log 分层并存

`mcp-project-memory` 同时维护两类持久化对象：

- canonical snapshot：当前 `state`、`agent-state`、`session`、`approval-gates`、`interrupts`、`runs` 等；
- append-only audit log：decision / capability inspect / execution / feedback / gate transition 等事件流。

snapshot 负责恢复与当前读取；audit log 负责解释与追溯。二者共享 stable identifiers，但职责不同。

备选方案：

- 只保留 snapshot，把 trace 继续当作 agent_state 内嵌字段。
- 完全事件溯源，只从 event log 重建所有状态。

不采用的原因：

- 只保留 snapshot 不足以支撑后续审计和调试。
- 全事件溯源对当前仓库过重，也不符合 MVP 演进节奏。

### 6. append-only audit 由 project memory 提供规范契约，Host runtime 负责写入

`mcp-project-memory` 作为 canonical state source，负责暴露 append-only audit 与 workflow event 的资源/写入契约；`HostRuntime`、CLI、Web Host 不得自建旁路审计文件。这里的“`mcp-project-memory`”指的是规范 contract 与 service boundary，不要求调用端必须总是跨进程命中一个独立 server。

最小事件类型包括：

- `decision_recorded`
- `capability_summary_considered`
- `capability_inspected`
- `action_execution_started`
- `action_execution_finished`
- `observation_recorded`
- `feedback_recorded`
- `gate_transitioned`

这样做的原因是：

- 所有宿主入口读取同一份规范事实；
- Web Host 和 CLI 不会因为各自的日志格式不同而造成追溯分裂。

### 7. Web Host 首版只消费 trace/debug 级 capability 事件

浏览器 Host 继续以 workflow 控制、state 摘要、interrupt 和 gates 为主。capability inspect 与 audit 事件先进入 decision trace / debug 视图，不上升为新的一级主操作模块。

这样做的原因是：

- 当前更需要验证底层语义稳定，而不是过早增加 UI 复杂度；
- capability discovery 首版主要服务于 agent correctness 和调试可解释性。

## Risks / Trade-offs

- [统一 capability gateway 但底层暂时仍有 in-process adapter] → 先统一 contract，后续再逐步替换 transport，避免一次性重写。
- [把 MCP 理解成必须独立部署的 server 形态] → 在规范中明确“contract first, transport optional”，避免把架构边界和部署拓扑绑定。
- [引入 summary -> inspect 增加一跳决策成本] → 仅对 agent-selectable capability 生效；上下文压缩收益通常大于多一跳的代价。
- [同时维护 snapshot 与 append-only log 可能产生双写复杂性] → 明确 snapshot 用于当前状态，audit 用于事件追溯，并要求共享 stable IDs 与单次 transition 写入。
- [execute/observe 不完全进入 LangGraph 节点可能被认为“还不够纯”] → 本次目标是消除图内外语义断裂，而不是追求框架纯度。
- [过早为 role scope 建模会增加实现复杂度] → 首版允许单 agent 默认值，但模型与存储字段必须预留 `role/agent_id`。
- [替换旧 change 可能造成需求遗漏] → 设计和 specs 中显式吸收 `add-host-capability-discovery` 的 summary/detail/inspect/scope/audit 需求后再删除旧 change。

## Migration Plan

1. 创建 consolidated specs，覆盖 capability discovery、runtime contract、project memory audit 和 Web Host 观察语义。
2. 在 runtime 中引入 capability gateway / registry 抽象，并让现有 preprocess、tool-contracts、memory 路径接入统一 contract。
3. 收敛 capability summary / inspect / detail visibility scope，并把相关事件写入 audit log。
4. 把 action execution / observation 路径改为显式 workflow transition 写入模型，同时保持现有 CLI/Web Host 的共享 runtime 入口不变。
5. 扩展 `mcp-project-memory` 的 canonical snapshot + append-only audit 契约，并让 Web Host / CLI 继续从同一来源恢复状态。
6. 在新 change 处于 apply-ready 后，移除被其吸收的 `add-host-capability-discovery` change。

回滚策略：

- 如果 capability discovery 路径不稳定，可退回 summary-only disabled 模式，但保留统一 gateway；
- 如果 append-only audit 引入问题，可暂时降级为写 snapshot + 最小 decision log，同时保留事件模型；
- 旧 change 不单独恢复，避免重新引入并行规范源。

## Open Questions

- capability registry 的 Host override 配置最终落在 runtime 包内静态清单、项目级配置，还是两者叠加，需在实现前确定具体优先级格式。
- append-only workflow event log 是否复用现有 `decision_log.jsonl`，还是新增更通用的 `workflow_events.jsonl`，需在 implementation 期结合现有 `mcp-project-memory` 文件布局确认。
- 首批 capability onboarding 是否只覆盖 `mcp-preprocess` 与 `mcp-hpc-tool-contracts`，还是同时为后续 `mcp-bio-research` 预留空 capability entry，需在 apply 阶段按实际实现范围确定。
