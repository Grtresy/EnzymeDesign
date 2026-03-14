## MODIFIED Requirements

### Requirement: Episode state updates are structured and durable
系统 MUST 提供 `update_episode_state` 与 `record_decision` 两个 tools，用于更新当前 episode 的结构化状态和追加决策日志。

`update_episode_state` MUST 将最新状态持久化到 episode 的 canonical state 文件。`record_decision` MUST 生成稳定 `decision_id`、记录时间戳、作者与可选 `evidence_refs`，并以追加方式写入决策日志。

当 workflow 事件需要附带状态推进时，系统 MUST 允许 canonical snapshot 与 append-only 审计记录使用共享 stable identifiers 协同持久化，而不是要求调用方在不同私有文件中手工维持关联。

#### Scenario: Updating episode state persists a new snapshot
- **WHEN** 调用方使用 `update_episode_state` 提交某个 `project_id` / `episode_id` 的新状态对象
- **THEN** 系统将该状态写入该 episode 的 canonical state 文件
- **THEN** 随后通过 `enzyme://project/{project_id}/episode/{episode_id}/state` 读取到的内容与最新提交一致

#### Scenario: Recording a decision appends an auditable entry
- **WHEN** 调用方使用 `record_decision` 提交决策类型、原因、作者和证据引用
- **THEN** 系统为该条记录生成稳定 `decision_id` 和时间戳
- **THEN** 该记录被追加到该 episode 的决策日志中，而不是覆盖已有记录

### Requirement: Agent workflow resources are canonical and cross-surface readable
系统 MUST 为 episode 级别的 agent workflow 对象提供稳定的 canonical resources，以便 CLI、Web Host 和 runtime 在不共享私有内存的情况下读取同一份状态。

新增资源集合至少包括：

- `enzyme://project/{project_id}/episode/{episode_id}/agent-state`
- `enzyme://project/{project_id}/episode/{episode_id}/decision-log`
- `enzyme://project/{project_id}/episode/{episode_id}/feedback-log`
- `enzyme://project/{project_id}/episode/{episode_id}/approval-gates`
- `enzyme://project/{project_id}/episode/{episode_id}/interrupts`
- `enzyme://project/{project_id}/episode/{episode_id}/session`
- `enzyme://project/{project_id}/episode/{episode_id}/workflow-audit`

这些资源必须能表达：

- 当前 `active_state_version`
- 当前 `selected_action` 或其引用
- pending gates 和 pending interrupts
- feedback / approval 的结构化记录
- resume anchor 或等价恢复锚点
- capability inspect、action execution、observation ingestion 等 append-only workflow 事件

#### Scenario: Web Host 和 CLI 读取同一个 pending interrupt 与 gate
- **WHEN** runtime 为某个 episode 写入待审批 gate 和待恢复 interrupt
- **THEN** `resources/read` 可以通过该 episode 的 canonical resources 读取相同的 gate、interrupt、active state version 和 resume anchor
- **THEN** CLI 与 Web Host 观察到的是同一份持久化 workflow 状态，而不是各自推断出的副本

#### Scenario: Capability inspect and execution events are readable as canonical audit resources
- **WHEN** runtime 为某个 episode 记录 capability inspect、execution start、execution finish 和 observation record 事件
- **THEN** 这些事件会通过该 episode 的 canonical workflow audit resource 对外可读
- **THEN** 宿主界面和调试工具无需依赖私有日志文件即可追溯同一条事件链

## ADDED Requirements

### Requirement: Project memory is a canonical service boundary independent of transport shape
系统 MUST 将 project memory 定义为 canonical state service 的稳定契约边界，而不是要求它必须以独立部署、跨进程访问的 MCP server 形态存在。

该边界至少必须保证：

- Host runtime 通过统一资源/工具契约访问 canonical project memory
- 进程内 adapter、嵌入式 service 或真实 MCP server 都可以作为该契约的合法承载实现
- CLI、Web Host 和其它调用方不得因为使用进程内实现就绕过该契约直接读写工作区文件

#### Scenario: In-process project memory still behaves as the canonical service boundary
- **WHEN** project memory 由 Host 进程内 adapter 承载，而不是独立 server 进程承载
- **THEN** runtime 仍然通过统一的 canonical project memory contract 读取和写入状态
- **THEN** 该实现不会把 canonical state 退化成任意宿主代码都可直接篡改的内部私有模块

### Requirement: Workflow audit events are append-only and linked to canonical state
系统 MUST 提供 append-only 的 workflow audit 存储契约，用于记录 capability inspect、action execution、observation record、gate transition 和 feedback resolution 等事件。

每条 workflow audit 记录至少必须包含：

- 稳定 `event_id`
- `event_type`
- `episode_id`
- 关联的 `state_version` 或等价新鲜度锚点
- 相关对象标识，如 `capability_id`、`action_id`、`run_id`、`observation_id` 或 `gate_id`
- 时间戳

该 audit 契约必须满足：

- 以追加方式写入，而不是覆盖历史
- 与 canonical snapshot 共享 stable identifiers
- 可被 CLI、Web Host 和 runtime 共同读取

#### Scenario: Workflow audit preserves the execution lineage across state changes
- **WHEN** 同一个 episode 经历 capability inspect、工具执行和 observation 回灌
- **THEN** 系统会按时间顺序追加这些 workflow 事件
- **THEN** 即使后续 canonical snapshot 继续变化，先前事件链也不会被覆盖或丢失
