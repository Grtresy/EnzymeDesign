# mcp-project-memory

## ADDED Requirements

### Requirement: Memory server exposes canonical project resources
系统 MUST 通过稳定的 `enzyme://` URI 暴露项目工作区中的核心对象，并支持 `resources/list` 与 `resources/read` 读取这些资源。

MVP 资源集合至少包括：

- `enzyme://project/{project_id}/config`
- `enzyme://project/{project_id}/episodes`
- `enzyme://project/{project_id}/episode/{episode_id}/goal`
- `enzyme://project/{project_id}/episode/{episode_id}/state`
- `enzyme://project/{project_id}/episode/{episode_id}/plan`
- `enzyme://project/{project_id}/episode/{episode_id}/annotations`
- `enzyme://run/{run_id}/manifest`
- `enzyme://candidate/{candidate_id}/summary`
- `enzyme://experiment/{experiment_id}/result`

#### Scenario: Existing episode resources can be listed and read
- **WHEN** 某个 `project_id` 下已经存在 `episode_id` 对应的 `goal.md`、`state.json`、`plan.yaml` 和 `annotations.json`
- **THEN** `resources/list` 返回这些资源的稳定 `enzyme://` URI
- **THEN** `resources/read` 能读取对应内容，而不要求 Host 直接访问底层文件路径

### Requirement: Episode state updates are structured and durable
系统 MUST 提供 `update_episode_state` 与 `record_decision` 两个 tools，用于更新当前 episode 的结构化状态和追加决策日志。

`update_episode_state` MUST 将最新状态持久化到 episode 的 canonical state 文件。`record_decision` MUST 生成稳定 `decision_id`、记录时间戳、作者与可选 `evidence_refs`，并以追加方式写入决策日志。

#### Scenario: Updating episode state persists a new snapshot
- **WHEN** 调用方使用 `update_episode_state` 提交某个 `project_id` / `episode_id` 的新状态对象
- **THEN** 系统将该状态写入该 episode 的 canonical state 文件
- **THEN** 随后通过 `enzyme://project/{project_id}/episode/{episode_id}/state` 读取到的内容与最新提交一致

#### Scenario: Recording a decision appends an auditable entry
- **WHEN** 调用方使用 `record_decision` 提交决策类型、原因、作者和证据引用
- **THEN** 系统为该条记录生成稳定 `decision_id` 和时间戳
- **THEN** 该记录被追加到该 episode 的决策日志中，而不是覆盖已有记录

### Requirement: Plan confirmation and annotations share one source of truth
系统 MUST 提供 `confirm_plan` 与 `save_structure_annotations` tools，并使它们写入的结果可通过同一项目工作区中的 canonical resources 读取。

`confirm_plan` MUST 写入该 episode 的计划文件。`save_structure_annotations` MUST 持久化结构标注、用户备注或约束编辑结果，并将它们作为该 episode 的状态真源之一。

#### Scenario: Confirmed plan is readable through the plan resource
- **WHEN** 调用方对某个 episode 调用 `confirm_plan` 并提交结构化计划内容
- **THEN** 系统将该计划写入该 episode 的 canonical plan 文件
- **THEN** 通过 `enzyme://project/{project_id}/episode/{episode_id}/plan` 读取到的内容就是刚刚确认的计划

#### Scenario: Saved annotations are reused as canonical episode annotations
- **WHEN** 调用方使用 `save_structure_annotations` 保存某个 episode 的标注对象
- **THEN** 系统将标注持久化到该 episode 的 canonical annotations 文件
- **THEN** 通过 `enzyme://project/{project_id}/episode/{episode_id}/annotations` 读取到相同的标注内容

### Requirement: Experiment imports and episode archives preserve lineage
系统 MUST 提供 `import_experiment_results` 与 `archive_episode` tools，用于把实验反馈纳入项目状态，并在 episode 完成时生成可复现的归档索引。

`import_experiment_results` MUST 为导入结果生成稳定 `experiment_id` 或接受调用方提供的稳定 id，并建立其与 `project_id`、`episode_id`、候选或 run 的引用关系。`archive_episode` MUST 生成该 episode 的归档 manifest，并标记该 episode 已归档。

#### Scenario: Imported experiment result becomes a readable resource
- **WHEN** 调用方使用 `import_experiment_results` 提交某个 episode 的实验结果及其关联的 candidate/run 引用
- **THEN** 系统持久化该实验结果并建立稳定 `experiment_id`
- **THEN** 通过 `enzyme://experiment/{experiment_id}/result` 可以读取到该实验结果内容

#### Scenario: Archived episode produces a manifest with lineage references
- **WHEN** 调用方对某个 episode 调用 `archive_episode`
- **THEN** 系统为该 episode 生成或更新 `manifest.json`
- **THEN** manifest 中包含该 episode 的 goal、state、plan、decision log、run 引用和 experiment 引用的定位信息

### Requirement: Resource and tool access is bounded to configured project roots
系统 MUST 只允许读取和写入配置过的项目工作区中的受控文件，拒绝路径穿越或任意文件访问。

所有基于 `project_id`、`episode_id`、`run_id`、`candidate_id`、`experiment_id` 的资源解析都 MUST 经过规范化与边界校验。

#### Scenario: Path traversal input is rejected
- **WHEN** 调用方构造包含 `..`、绝对路径或越界标识的资源参数或工具参数
- **THEN** 系统拒绝该请求并返回验证错误
- **THEN** 不会读取或写入任何项目工作区之外的文件

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
