## Why

即使 V2 的 domain 和 graph state 先定义完成，若没有统一的 Host API contracts 与 frontend read model，后续 `openzyme-host-api` 和 `openzyme-web-ui` 仍会各自发明资源形状、流式事件和 workflow pane 数据结构。Phase A 需要先把这些消费边界锁定，才能让 Web-first 产品壳稳定落地。

## What Changes

- 定义 V2 Host API 的资源面和命令面契约，覆盖 project、episode、resume、approval、runs、artifacts 和 report。
- 定义 Host 的 workflow stream / event contract，使 graph phase、progress、interrupt 和 execution 事件能够稳定外露。
- 定义 frontend read model 和 projection 边界，支撑 workflow pane、approval pane、run/artifact pane 和 report 视图。
- 明确 API/read model 如何消费 domain model 与 graph state，而不是重复拥有业务真状态。
- 固定首版 UI 依赖的最小投影集合，为 Phase B 的最小 Web UI 和后续完整页面打底。

## Capabilities

### New Capabilities
- `v2-host-api`: 定义 V2 Host API 的核心资源、命令和流式事件契约。
- `v2-frontend-read-model`: 定义 V2 Web UI 所依赖的 workflow、approval、run、artifact 和 report 投影模型。

### Modified Capabilities

## Impact

- 影响 `apps/openzyme-host-api`、`apps/openzyme-web-ui`、`packages/openzyme-storage` 和后续 projection 实现。
- 要求后续 API 和 UI 复用 `define-v2-domain-storage-contracts` 与 `define-v2-graph-state-contracts` 的实体、phase 和 interrupt 语义。
- 为 Phase B 的最小 Web UI 提供可直接实现的接口和 read model 依赖。
