# OpenZyme V3 Control Plane

## 1. 目标

V3 control plane 负责保存所有**跨对话、跨压缩、跨后台执行**仍然成立的顶层状态。

设计原则：

- 能投影给 UI / CLI 的状态，不得只存在于 prompt
- 能跨多轮对话恢复的状态，不得只存在于 graph checkpoint
- 能驱动行为的状态，要么是 canonical object，要么是它的派生 projection
- 能并发恢复的 capability execution，不得只靠 engine 内部状态识别

## 2. Canonical Objects

### 2.1 Session

用途：

- 代表一次用户与系统的长期工作上下文
- 作为 memory、tasks、lanes、approvals 的上层锚点

建议字段：

- `session_id`
- `project_id`
- `title`
- `objective`
- `status`
- `created_at`
- `updated_at`

### 2.2 Task

用途：

- 持久化任务图与执行状态
- 支持依赖、assignment、lane 绑定、结果回填

建议字段：

- `task_id`
- `session_id`
- `subject`
- `description`
- `status`
- `blocked_by`
- `priority`
- `kind`
- `assigned_ref`
- `created_at`
- `updated_at`

### 2.3 Lane

用途：

- 表达隔离执行上下文
- 记录工作目录、资源绑定、生命周期

建议字段：

- `lane_id`
- `session_id`
- `name`
- `status`
- `cwd`
- `branch_name`
- `claimed_ref`
- `created_at`
- `updated_at`

### 2.4 Approval

用途：

- 统一所有人工审批与 agent protocol gating

建议字段：

- `approval_id`
- `session_id`
- `task_id`
- `lane_id`
- `kind`
- `requested_action`
- `status`
- `request_ref`
- `resolution_ref`
- `created_at`
- `resolved_at`

### 2.5 InboxMessage

用途：

- 支持 request-response 协议、agent team 协同、后台通知

建议字段：

- `message_id`
- `session_id`
- `sender`
- `sender_kind`
- `recipient`
- `recipient_kind`
- `message_type`
- `correlation_id`
- `payload_ref`
- `status`
- `created_at`

### 2.6 MemoryEntry

用途：

- 存储压缩摘要、连续性摘要、长期记忆

建议字段：

- `memory_id`
- `session_id`
- `scope_kind` (`session` / `lane` / `task`)
- `scope_ref`
- `kind`
- `summary`
- `source_range`
- `importance`
- `created_at`

### 2.7 AgentMember

用途：

- 表达可被 harness 恢复、投影、协议化通信的 delegated agent / teammate

建议字段：

- `agent_id`
- `session_id`
- `lane_id`
- `task_id`
- `name`
- `role`
- `status`
- `parent_agent_id`
- `created_at`
- `updated_at`

### 2.8 EngineInvocation

用途：

- 统一追踪 capability engine 的启动、恢复、重试、并发与结果回填

建议字段：

- `invocation_id`
- `session_id`
- `task_id`
- `lane_id`
- `engine_name`
- `status`
- `input_ref`
- `output_ref`
- `approval_id`
- `idempotency_key`
- `started_at`
- `finished_at`

### 2.9 Artifact / Run / Report

用途：

- 保留 V2 的 artifact-first 优势
- 但将其纳入更大的 harness control plane

要求：

- `run` 与 `artifact` 必须可回链到 session / task / lane / engine invocation
- `report` 必须能被 workspace projection 直接消费
- 大体积、engine-specific、调试型数据优先存入 artifact store，由 control plane 通过 typed ref 引用，而不是塞入 canonical row

## 3. Workspace Projection

V3 的 UI / CLI 不直接读取 raw internal state，而是读取一个统一 projection。

最小 projection 分区：

- `session`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `artifacts`
- `reports`
- `capabilities`
- `activity_feed`

## 4. Event Model

control plane 需要最小事件流，便于 streaming 与审计。

建议事件类型：

- `session.created`
- `task.created`
- `task.updated`
- `task.claimed`
- `lane.created`
- `lane.bound`
- `lane.removed`
- `agent.spawned`
- `agent.status_updated`
- `agent.message.delivered`
- `approval.requested`
- `approval.resolved`
- `memory.compacted`
- `inbox.delivered`
- `engine.invocation.started`
- `engine.invocation.updated`
- `engine.invocation.completed`
- `report.generated`

## 5. 与 V2 的迁移关系

- V2 `episode` 不能直接继续担任 V3 的唯一顶层对象
- V2 `approvals / runs / artifacts` 可以迁移并保留语义
- V2 graph checkpoint 不再作为产品顶层真状态来源
- 若有 state 仍需存于 LangGraph，只允许是某 capability engine 的局部运行态
- V2 control model 默认冻结，不再继续扩展新的顶层对象或 phase 语义
