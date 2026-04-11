## Why

OpenZyme V2 目前只有目录骨架，没有稳定的 domain model 和存储分层契约。若在此之前直接进入 graph、API 或 UI 实现，会把实体命名、状态归属和持久化边界反复返工到多个模块里。

## What Changes

- 定义 V2 的核心业务实体、稳定标识和生命周期状态，作为 `openzyme-domain` 的正式契约。
- 定义关系库、LangGraph checkpointer 和 artifact store 的职责边界，作为 `openzyme-storage` 与 `database/` 的正式契约。
- 明确哪些数据属于 canonical business state，哪些属于 durable execution state，哪些属于大文件产物。
- 为 Phase B 的最小主链提供统一的 ID、关联关系和持久化 ownership，避免 graph/API/UI 各自发明一套状态模型。
- 为 Phase C 的 `evidence`、`candidate` 等能力预留扩展位，但不在本 change 内展开细化。

## Capabilities

### New Capabilities
- `v2-domain-model`: 定义 OpenZyme V2 的核心实体、稳定标识、生命周期状态和跨模块共享的 typed contracts。
- `v2-storage-schema`: 定义业务库、graph checkpointer 和 artifact store 的分层持久化契约及关联规则。

### Modified Capabilities

## Impact

- 影响 `packages/openzyme-domain`、`packages/openzyme-storage`、`database/` 和后续 `packages/openzyme-graph` 的状态建模方式。
- 为 `apps/openzyme-host-api`、`apps/openzyme-web-ui` 和 `packages/openzyme-execution` 提供统一的实体和持久化边界。
- 与现有 `mcp-hpc-runner` spec 保持集成关系，但不修改 runner 自身 requirement。
