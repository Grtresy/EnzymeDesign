# mcp-project-memory

## ADDED Requirements

### Requirement: Agent workflow resources are canonical and cross-surface readable
系统 MUST 为 episode 级别的 agent workflow 对象提供稳定的 canonical resources，以便 CLI、Web Host 和 runtime 在不共享私有内存的情况下读取同一份状态。

新增资源集合至少包括：

- `enzyme://project/{project_id}/episode/{episode_id}/agent-state`
- `enzyme://project/{project_id}/episode/{episode_id}/decision-log`
- `enzyme://project/{project_id}/episode/{episode_id}/feedback-log`
- `enzyme://project/{project_id}/episode/{episode_id}/approval-gates`
- `enzyme://project/{project_id}/episode/{episode_id}/interrupts`
- `enzyme://project/{project_id}/episode/{episode_id}/session`

这些资源必须能表达：

- 当前 `active_state_version`
- 当前 `selected_action` 或其引用
- pending gates 和 pending interrupts
- feedback / approval 的结构化记录
- resume anchor 或等价恢复锚点

#### Scenario: Web Host 和 CLI 读取同一个 pending interrupt 与 gate
- **WHEN** runtime 为某个 episode 写入待审批 gate 和待恢复 interrupt
- **THEN** `resources/read` 可以通过该 episode 的 canonical resources 读取相同的 gate、interrupt、active state version 和 resume anchor
- **THEN** CLI 与 Web Host 观察到的是同一份持久化 workflow 状态，而不是各自推断出的副本

### Requirement: Agent workflow mutations are versioned and resumable
系统 MUST 提供用于写入 agent workflow 状态的结构化 tools，并要求关键恢复路径使用版本校验，以防止跨入口重复执行或覆盖新状态。

最小 mutation surface 至少包括：

- 写入 agent state 快照或 working state patch
- 追加 feedback / approval 记录
- upsert approval gate
- 写入或解决 interrupt
- 提交 resume / continue 请求

这些写入必须至少支持：

- `state_version` 或等价的乐观并发版本
- `resume_token` 或等价的单次恢复锚点
- 对过期 token / stale version 的结构化拒绝
- 对重复 continue 的幂等语义

#### Scenario: 旧的 resume token 不会重复推进 workflow
- **WHEN** Web Host 和 CLI 基于同一个旧 interrupt 快照同时尝试提交 continue
- **THEN** 只有第一个匹配当前 `state_version` 与 `resume_token` 的请求会成功推进 workflow
- **THEN** 后续请求收到结构化 stale-state 错误，并且不会再次触发工具执行或覆盖新的 interrupt 状态
