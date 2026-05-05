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
