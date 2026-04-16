# OpenZyme V3 公共接口

## 1. 总体原则

V3 允许引入破坏性新接口，并以替代 V2 为目标。

目标：

- 给前端、CLI、外部调用方一个新的 harness-first 语义面
- 不要求调用方理解 LangGraph、phase graph、internal engine state

说明：

- `/v3` namespace 仍然保留，便于在迁移窗口内识别新接口
- 但 V3 默认不承担长期兼容 V2 语义的义务
- 任何兼容层都只应视为短期迁移措施，而不是长期产品承诺

## 2. API 设计默认值

建议最小接口：

- `POST /v3/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/events`
- `POST /v3/tasks`
- `PATCH /v3/tasks/{task_id}`
- `POST /v3/lanes`
- `POST /v3/lanes/{lane_id}/claim`
- `POST /v3/lanes/{lane_id}/keep`
- `POST /v3/lanes/{lane_id}/remove`
- `POST /v3/approvals/{approval_id}/resolve`

说明：

- `POST /v3/sessions/{session_id}/messages` 是默认的 harness command ingress，可触发普通消息处理、task updates、delegation、engine 调用
- V3 初期不要求单独暴露 `agents` REST 资源，但 workspace projection 必须能显示 delegated agent / subtask 状态

## 3. Workspace Contract

`GET /v3/sessions/{id}/workspace` 返回统一 snapshot。

最低字段分区：

- `session`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `activity_feed`
- `artifacts`
- `reports`
- `capabilities`

说明：

- `capabilities` 是可扩展分区，按 `capability_key` 挂载各 engine 的投影
- 不应把当前 engine 名称直接固化为 workspace 顶层 contract，避免后续每新增一种能力都破坏接口

## 4. CLI 语义

V3 CLI 不再围绕 `episode phase` 渲染。

默认能力：

- 查看 session workspace
- 查看和更新 task board
- 处理 approvals
- 观察 lane 状态
- 发起消息 / 继续 agent loop

## 5. Web UI 语义

V3 Web UI 默认呈现：

- 主工作区叙事
- task board
- lane/workspace 状态
- approvals
- artifacts / runs / reports
- activity feed

不要求用户理解：

- 哪个 graph 节点正在运行
- 哪个 subgraph 持有当前局部状态

## 6. Streaming

V3 streaming 默认围绕 control-plane events，而不是围绕 graph implementation 细节。

推送单位：

- `task.updated`
- `approval.requested` / `approval.resolved`
- `lane.created` / `lane.bound` / `lane.removed`
- `agent.spawned` / `agent.message.delivered`
- `engine.invocation.started` / `engine.invocation.updated` / `engine.invocation.completed`
- `report.generated`

## 7. 弃用策略

- V2 进入 `deprecated / frozen` 状态，不再继续功能性演进
- V3 完成后应直接制定 V2 retirement plan，而不是默认长期双栈并行
- 若迁移窗口内仍需保留少量兼容入口，它们只能作为临时 shim，不能反向主导 V3 设计
- `current_phase`、phase rail、supervisor-route 等 V2 词汇不再是 V3 公共接口基线
