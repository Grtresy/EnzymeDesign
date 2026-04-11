## Context

蓝图明确 V2 是 Web-first，并要求前端能感知 graph phase、node progress、interrupt、approval、run、artifact 和 report。当前主线还没有 Host API 或 Web UI 的任何实现，因此如果不在 Phase A 先定义消费边界，后续 `openzyme-host-api` 和 `openzyme-web-ui` 很容易围绕临时需求演化出不兼容的接口。

本 change 依赖前两个 change 提供的 domain vocabulary 和 graph-state contract，但它本身只定义 API/read model，不实现具体端点或 UI 组件。

## Goals / Non-Goals

**Goals:**

- 定义 V2 Host API 的核心资源、命令和流式事件面。
- 定义前端工作流相关视图所依赖的 read model/projection 契约。
- 明确 API/read model 与 business truth、graph state 的关系，避免 Host/UI 自建私有状态源。
- 为 Phase B 的最小 Web UI 提供足够稳定的依赖面。

**Non-Goals:**

- 不实现 FastAPI 路由或 React 组件。
- 不细化视觉设计、页面布局或交互文案。
- 不重新定义 domain entity 或 graph internal state。
- 不要求 Phase A 内完成完整 CLI 契约；CLI 只需后续复用相同 Host 语义。

## Decisions

### 1. Host API 同时暴露资源查询和状态变更命令

Host API 需要同时覆盖：

- 可查询资源：projects、episodes、runs、artifacts、reports、pending approvals；
- 可触发命令：create episode、resume、approve/reject、run-related actions。

这种区分可以让前端 read model 明确依赖查询面，同时把工作流推进动作保留为显式命令，而不是混入资源更新语义。

### 2. Workflow stream 采用 graph-derived event contract，而不是聊天消息拼装

流式接口必须能够表达：

- phase 变更
- progress 更新
- interrupt/approval 挂起
- run 状态变化
- artifact 可用
- report 可用

不采用“只流式返回聊天消息”的设计，因为蓝图明确前端需要 workflow-aware，而不是仅 message-aware。

### 3. Frontend read model 是 projection，不是新的真状态

前端所见的 workflow pane、approval pane、run/artifact pane 和 report 视图都来自 projection/read model。该模型可以聚合业务库与 graph state，但不得成为新的 canonical state owner。

这意味着：

- API 返回的 read model 可以为 UI 便利性做整形；
- 但写操作仍需回到 Host 命令面；
- UI 不维护私有 workflow truth。

### 4. 首版 read model 只覆盖最小主链和关键产品面板

Phase A 只要求定义首版必须稳定的投影集合：

- workflow summary/progress
- pending interrupt or approval summary
- run list and run detail summary
- artifact list
- report summary

更丰富的研究/设计视图可在 Phase C/D 增补，不在这里过度设计。

### 5. API 和 read model 必须复用已有 phase 与 interrupt 语义

本 change 明确要求 API 和 read model 不得重新发明 phase 名称、approval 状态或 interrupt 类型。它们必须直接复用 graph-state change 中定义的枚举和 envelope 类型。

## Risks / Trade-offs

- [API 面一次定义过宽] -> 先聚焦蓝图明确列出的核心资源和命令，避免提前覆盖所有未来产品面。
- [read model 与 canonical state 混淆] -> 在 specs 中显式要求 projection 只读且来源可追溯。
- [流式契约退化为消息流] -> 强制要求 workflow-aware event types，而不是仅聊天文本。

## Migration Plan

- 在本 change 中先定义 API 与 projection 契约；
- Phase B 先实现最小闭环需要的 endpoints、resume/approval 命令和 workflow stream；
- Phase C/D 再在不破坏现有 contract 的前提下增加更丰富的 read model 视图。

## Open Questions

- 无阻塞实现的开放问题；CLI 的完整薄客户端 contract 留待产品化阶段扩展。
