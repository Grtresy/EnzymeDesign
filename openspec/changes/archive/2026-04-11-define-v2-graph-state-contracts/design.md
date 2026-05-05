## Context

蓝图把 `LangGraph Supervisor Graph` 作为 OpenZyme V2 的主内核，并固定五个子图：`intake`、`research`、`design`、`execution`、`report_review`。当前主线还没有任何 graph contract，因此如果不在 Phase A 先锁定状态模型，Phase B 一旦开始实现最小主链，就会把 phase 切换、interrupt envelope、resume 位置和节点进度语义分散到代码里。

本 change 依赖 `define-v2-domain-storage-contracts` 提供的 episode 业务锚点和存储分界，但不负责定义 API 或 UI 投影。

## Goals / Non-Goals

**Goals:**

- 定义 supervisor graph 的顶层 state 和固定子图边界。
- 固定 `thread_id = episode_id`、interrupt/resume 和 approval handoff 的语义。
- 让 Phase B 的最小主链可以直接按契约实现，而不再补基础状态定义。
- 为 Host API 与 UI 暴露一致的 phase、progress 和 pending-interrupt 信息。

**Non-Goals:**

- 不实现实际 graph 节点代码或 LangGraph wiring。
- 不细化 research/design/report 的内部算法。
- 不定义 HTTP API、stream wire format 或前端视图模型。
- 不修改业务库 schema，本 change 只定义 graph-execution-side state。

## Decisions

### 1. Supervisor graph 采用固定 phase 枚举，而不是开放式 agent society

顶层 graph 只允许在五个固定 phase 之间切换：

- `intake`
- `research`
- `design`
- `execution`
- `report_review`

这样做是为了与蓝图保持一致，并保证 Host/UI 能稳定映射当前阶段。开放式 phase 集合会削弱可解释性，也会让前端和审计视图失去稳定语义。

### 2. Episode ID 同时作为 graph thread anchor

graph contract 明确要求 `thread_id = episode_id`。这样业务库中的 episode 记录与 LangGraph checkpoint lineage 可以使用同一锚点，恢复入口不需要再维护额外映射表。

备选方案是 graph 使用独立 thread key，再从业务库查映射。未采用，因为会增加恢复和审计复杂度。

### 3. 子图只暴露结构化入口/出口，而不泄漏内部节点细节

每个固定子图必须定义：

- 进入该 phase 前所需的最小输入
- 该 phase 结束后对 supervisor 可见的结构化输出
- 该 phase 可能产生的 interrupt 类型或 handoff 结果

不要求 Phase A 细化子图内部节点。这样可以让 Phase B/C 在不破坏顶层 contract 的前提下演进内部实现。

### 4. Interrupt 与 approval 统一为可恢复挂起状态

graph state 需要统一表达以下可恢复挂起状态：

- clarification interrupt
- approval pending
- escalation
- recoverable failure handoff

每种挂起状态都必须携带恢复所需的最小 envelope，例如原因、恢复动作类型、关联 episode、关联 phase 和 freshness anchor。这样 Web 与 CLI 才能复用同一恢复语义。

### 5. Node progress 采用结构化状态，而不是只靠日志流

graph state 契约中必须包含可投影的进度信息，例如当前 phase、活跃节点、节点状态和最近转移时间。日志和 trace 仍然保留，但不能作为 UI 获取 workflow pane 状态的唯一来源。

### 6. Graph 只持有 execution-local state，不重复定义 business truth

graph state 只定义 workflow 执行、恢复和阶段切换所需的 durable execution state；业务真状态仍由关系库负责。本 change 明确禁止把 episode/approval/run 的 canonical record 完整镜像到 graph state 中。

## Risks / Trade-offs

- [Phase 契约过早僵化] -> 只固定 supervisor 可见边界，不锁死各子图内部节点。
- [Graph state 与业务状态重复] -> 在 specs 中明确 execution-local 与 canonical business state 的分层规则。
- [Progress 过于抽象导致 UI 无法消费] -> 要求 progress 至少能表达 phase、活跃节点、挂起原因和最近状态变化。

## Migration Plan

- 先以本 change 定义顶层 graph contract；
- Phase B 按该 contract 优先实现 `intake`、`execution` 和 resume/approval 主链；
- `define-v2-host-ui-contracts` 再基于本 change 的 phase/progress/interrupt 语义定义 API 和前端投影。

## Open Questions

- 无阻塞实现的开放问题；research/design/report 子图内部细节有意留给后续 change。
