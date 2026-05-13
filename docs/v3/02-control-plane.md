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

- 持久化 master agent 对内部工作的正式安排
- 作为 session 内可调度、可委托、可恢复、可完成的工作单元
- 支持依赖、assignment、lane 绑定、delegation、结果回填

补充定义：

- `task` 不是普通聊天消息，也不是 capability tool call 的临时参数
- `task` 默认由 master agent 基于用户对话创建和编排
- `task` 是 delegated teammate、lane、approval、engine invocation、artifact、report draft、report、protocol thread 的默认关联锚点
- `task` 的存在意义是让内部执行和外部对话解耦：用户与 master agent 对话，内部团队围绕 task 推进工作
- `blocked_by` 是执行闸门：下游 task 可提前创建，但在 blocker terminal 前不能被 `task.delegate`、auto-claim 或普通 wakeup 推进执行

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

- 表达 task 的隔离执行上下文
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
- 作为 resident teammate 的 wakeup source，而不只是调试消息记录

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

状态语义：

- `unread` 表示消息尚未被 recipient teammate 的 restore context 消费
- `delivered` 表示消息已进入 recipient 的一次 work turn
- `acknowledged` 表示 recipient 已处理并完成必要回复或状态更新
- request-response message 必须通过 `correlation_id` 回链到同一 protocol thread

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

- 表达可被 harness 恢复、投影、协议化通信的 teammate agent
- 表达哪个 teammate 正在代表 agent team 推进哪个 task，以及它当前的 role / focus / 生命周期
- 表达 resident teammate 在 working / idle / blocked / failed / shutdown 之间的可恢复运行状态

建议字段：

- `agent_id`
- `session_id`
- `lane_id`
- `task_id`
- `name`
- `role`
- `status`
- `runtime_state`
- `parent_agent_id`
- `current_correlation_id`
- `wakeup_reason`
- `last_active_at`
- `idle_since`
- `shutdown_requested_at`
- `created_at`
- `updated_at`

补充约束：

- teammate 在“是否是 agent”这件事上与 master 平级；差异在于职责，而不是本体类型
- master 是 team leader 与 user-facing agent；teammate 是 internal worker / specialist
- teammate 应拥有自己的 restore context、tool surface、protocol thread 与状态投影
- teammate 的身份与 inbox 默认常驻；idle 状态不持续调用 LLM，但必须可被 scheduler 恢复
- master 显式 delegation 是默认产品路径；teammate auto-claim 仅用于显式 recovery/debug/operator 场景中的 role 匹配认领

### 2.7.1 AgentRuntimeSignal

用途：

- 表达哪些事件需要唤醒 resident teammate
- 将 inbox、task、approval、engine completion、manual resume 等变化统一接入 scheduler
- 避免 `protocol.send` 只写入数据库但无人消费

建议字段：

- `signal_id`
- `session_id`
- `agent_id`
- `task_id`
- `lane_id`
- `correlation_id`
- `reason`
- `source_ref`
- `status`
- `created_at`
- `claimed_at`
- `completed_at`

补充约束：

- `reason` 至少覆盖 `delegation_assigned`、`inbox_unread`、`task_available`、`approval_resolved`、`engine_completed`、`manual_resume`
- `inbox_unread` 不只来自 teammate-to-teammate 消息，也包括 master-to-teammate 的 follow-up message
- signal 的 `task_id`、`lane_id`、`correlation_id` 与 `source_ref` 应足够让 runtime 恢复 focused teammate turn，并从 source inbox payload 渲染 wakeup context
- scheduler 只能 claim 未完成 signal；claim 后必须要么完成，要么释放/标记失败
- signal 是调度语义，不替代 canonical task、inbox、approval 或 engine invocation

### 2.8 EngineInvocation

用途：

- 统一追踪 capability engine 围绕某个 task 的启动、恢复、重试、并发与结果回填

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

### 2.9 Artifact / Run / ReportDraft / Report

用途：

- 保留 V2 的 artifact-first 优势
- 但将其纳入更大的 harness control plane
- `report_draft` 作为 report teammate 的共享中间工作对象，用于承载可修订、可恢复、可发布的总结过程

要求：

- `run` 与 `artifact` 必须可回链到 session / task / lane / engine invocation
- `report_draft` 必须可回链到 session / task / teammate / protocol thread，并可被 workspace projection 直接消费
- `report` 必须能被 workspace projection 直接消费
- final `report` 默认来自 `report_draft` 的发布结果，而不是强依赖一次 capability invocation
- 大体积、engine-specific、调试型数据优先存入 artifact store，由 control plane 通过 typed ref 引用，而不是塞入 canonical row
- session 级 artifact catalog 必须可被 master 与 teammate 共同读取；artifact 不是只给 UI 看的投影附件
- artifact 默认是 team 共享工作面的一部分，task / lane 决定焦点与归属，而不是决定可见性的唯一边界
- execution input artifact 必须先由 control plane 校验属于当前 session，才能被编译成 runner input；LLM 或用户提供的任意本地路径不得绕过 artifact catalog
- execution output artifact 只来自 runner declared output fetch，必须记录来源 run、engine invocation、tool contract、relative path 与 provenance
- preprocess 生成的中间文件也是 session artifact；它们可以作为后续 execution input，但必须保留来源 artifact 与转换工具 metadata

`report_draft` 建议最小字段：

- `draft_id`
- `session_id`
- `task_id`
- `owner_agent_id`
- `status`
- `title`
- `summary`
- `content_ref`
- `published_report_id`
- `created_at`
- `updated_at`

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
- `report_drafts`
- `reports`
- `capabilities`
- `activity_feed`

其中推荐的阅读关系是：

- `conversation` 看用户与 master agent 的往来
- `task_board` 看内部工作如何被拆解和推进
- `delegation` 看 resident team roster、teammate 生命周期、哪些 teammate 正在推进哪些 task、持有哪些 correlation thread、是否有 unread wakeup
- `lane_board` / `capabilities` 看 task 在什么执行上下文里运行
- `report_drafts` 看 report teammate 正在如何组织、修订、准备发布交付物
- `artifacts` 看 agent team 当前共享工作面中已产出的证据、结果与中间产物

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
- `agent.woken`
- `agent.idle`
- `agent.status_updated`
- `agent.message.delivered`
- `agent.inbox_unread`
- `agent.delegated`
- `agent.task_claimed`
- `agent.shutdown_requested`
- `agent.shutdown_completed`
- `approval.requested`
- `approval.resolved`
- `memory.compacted`
- `inbox.delivered`
- `engine.invocation.started`
- `engine.invocation.updated`
- `engine.invocation.completed`
- `report_draft.updated`
- `report.generated`

## 5. 与 V2 的迁移关系

- V2 `episode` 不能直接继续担任 V3 的唯一顶层对象
- V2 `approvals / runs / artifacts` 可以迁移并保留语义
- V2 graph checkpoint 不再作为产品顶层真状态来源
- 若有 state 仍需存于 LangGraph，只允许是某 capability engine 的局部运行态
- V2 control model 默认冻结，不再继续扩展新的顶层对象或 phase 语义
