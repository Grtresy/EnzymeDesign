## Why

OpenZyme V2 已明确采用 LangGraph-first，但当前还没有任何正式的 graph state schema、interrupt envelope 或 subgraph contract。若直接进入 Phase B，会导致 supervisor、subgraph 和恢复语义在实现时被临时决定，后续很难保持 Web/CLI/Host 一致。

## What Changes

- 定义 V2 supervisor graph 的顶层 state schema 和固定 phase 枚举。
- 定义 `intake`、`research`、`design`、`execution`、`report_review` 五个固定子图的输入输出契约。
- 定义 `thread_id = episode_id`、interrupt/resume、approval 和 recoverable failure handoff 的状态表达。
- 定义节点进度、phase 转移和可恢复执行状态的最小 contract，供后续 API 与前端消费。
- 将 graph state 与关系库 business state 的分工显式化，避免 graph 层持有自己的私有业务模型。

## Capabilities

### New Capabilities
- `v2-graph-state`: 定义 V2 supervisor graph、固定子图边界、interrupt/resume 语义和 durable graph state schema。

### Modified Capabilities

## Impact

- 影响 `packages/openzyme-graph`、`packages/openzyme-domain`、`packages/openzyme-storage` 和后续 `apps/openzyme-host-api` 的 contract 设计。
- 为 Phase B 的 `intake + execution + approval/resume` 最小主链提供可直接实现的 graph 契约。
- 要求后续 Host API 与 frontend read model 复用这里定义的 phase、interrupt 和 progress 语义。
