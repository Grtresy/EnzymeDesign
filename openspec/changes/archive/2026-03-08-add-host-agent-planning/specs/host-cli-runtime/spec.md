## ADDED Requirements

### Requirement: Host runtime 暴露可恢复的 agent workflow 服务
Host runtime MUST 为 CLI 和 Web Host 暴露类型化的 agent workflow 服务，使宿主界面可以恢复、推进和检查持续决策型 workflow，而不是只调用一次性的 plan draft / approval API。

这些服务至少必须支持：

- 启动或恢复当前 episode 的 agent workflow
- 读取当前 agent working state
- 提交人类反馈或审批结果
- 触发 agent 决定的受控工具动作
- 读取 observations、run lineage 和 termination 状态

#### 场景：CLI 恢复一个等待反馈的 workflow
- **WHEN** 某个 episode 的 agent workflow 处于待澄清或待审批状态
- **THEN** CLI 可以读取该 episode 的当前 agent state 并显示待处理项
- **THEN** CLI 可以提交反馈并继续同一个 workflow，而不依赖特定于界面的状态迁移

### Requirement: Host runtime 通过受控执行边界承载 agent 决定的动作
Host runtime MUST 允许 agent workflow 选择动作，但实际工具执行仍通过共享 runtime 的受控适配器完成，以保留工作区语义、manifest 记录和策略门控。

runtime 至少必须负责：

- 验证动作是否合法
- 执行工具调用
- 写入 run manifest 和报告元数据
- 将结果整理为 observations 返回给 agent workflow

#### 场景：agent 选择工具动作后 runtime 记录完整执行谱系
- **WHEN** agent 选择一个工具动作并提交给 runtime 执行
- **THEN** runtime 产生规范的 run manifest、artifact refs 和 observation 摘要
- **THEN** 这些结果可被后续 agent 决策和所有宿主界面共同读取

## MODIFIED Requirements

### Requirement: Host runtime executes confirmed plan steps through tool contracts
系统 MUST 同时支持两类受控执行入口：

- 基于已批准 `action snapshot` 的 agent-driven 动作执行
- 基于已确认 `confirmed plan` 快照的兼容性计划执行

对工具后端的路由、manifest 记录和 canonical lineage 语义必须在两类入口之间保持一致。

只有在既不存在可执行的已批准 action snapshot、也不存在可执行的 confirmed plan snapshot 时，runtime 才能在提交任何工作前返回验证错误。

#### Scenario: Approved action snapshot can execute without a frozen plan
- **WHEN** agent workflow 已生成并获批一个 `prepare_ligand` action snapshot，但当前 episode 还没有新的 confirmed plan 文件
- **THEN** runtime 仍可以通过受控执行边界执行该动作并记录规范 run lineage
- **THEN** 该动作不会因为缺少 frozen confirmed plan 而被一刀切拒绝

### Requirement: Host runtime exposes reusable application services for multiple host surfaces
The system MUST 为项目加载、episode 生命周期管理、agent workflow 启动与恢复、设计契约修订、working plan 修订、受控工具执行、人类反馈提交、运行查找和报告实体化暴露类型化的应用服务操作，以便 CLI 和 Web Host 界面复用相同的编排语义。

这些共享 runtime 服务必须操作规范工作区状态，并且必须可以在不解析 CLI stdout 或调用 shell 命令作为集成边界的情况下调用。

#### 场景：Web Host 提交反馈后 CLI 能继续同一个 workflow
- **WHEN** Web Chat Host 为活跃 episode 提交一条澄清反馈并使 agent workflow 进入新的待执行状态
- **THEN** 后续 CLI 调用可以读取同一 episode 的新 agent state 并继续推进 workflow
- **THEN** 两个宿主界面观察到的是同一个规范状态，而不是各自维护的编排副本

### Requirement: Host runtime uses project memory as the canonical state source
Host runtime MUST 通过 `mcp-project-memory` 数据契约持久化和读取 episode 目标、agent working state、decision trace、feedback log、运行清单和报告元数据，而不是维护单独的 host 拥有状态模型。

CLI 和 Web Chat Host 都不得在规范项目工作区之外维护 agent state、feedback、runs 或报告状态的特定于界面的副本。

#### 场景：agent workflow 中断后可在宿主界面间恢复
- **WHEN** 一个 episode 的 agent workflow 在 Web Chat Host 中停在待审批状态
- **THEN** 该待审批状态和相关 decision trace 被持久化在规范 episode 资源中
- **THEN** CLI 随后读取同一 episode 时可以恢复相同的 workflow 中断点并继续推进

## ADDED Requirements

### Requirement: Host runtime 对受控动作执行统一的 approval / safety policy
Host runtime MUST 在 agent workflow 和实际工具执行之间应用统一的 approval / safety policy，而不是由 CLI 或 Web Host 各自决定哪些动作需要审批。

该策略至少必须能够：

- 根据动作类型和风险等级判断是否需要 gate
- 为 gate 生成结构化原因和待处理状态
- 在审批通过后解锁动作
- 在审批拒绝后将结果回写为 agent feedback / decision trace
- 将 gate 绑定到不可变的 `action_id` / `action_revision` 或等价 action snapshot
- 在 action revision 变化后拒绝使用旧 gate 解锁新动作

#### 场景：CLI 看到与 Web Host 相同的待审批 gate
- **WHEN** runtime 为某个动作创建待审批 gate
- **THEN** CLI 和 Web Host 读取到的是同一个 gate 记录和状态
- **THEN** 任一入口提交审批结果后，另一个入口都能观察到同一状态转换

### Requirement: Host runtime 暴露 session / interrupt 恢复边界
Host runtime MUST 暴露用于读取和恢复 session / interrupt state 的服务接口，而不是要求宿主界面自己推断 workflow 当前停在何处。

这些服务至少必须支持：

- 读取当前 pending interrupts
- 返回 resume anchor
- 提交 interrupt resolution
- 从指定恢复点继续 workflow
- 在 continue / resolve 时校验 `active_state_version` 或等价版本字段
- 对重复 continue 提供幂等结果，或明确返回 stale-state 错误而不重复触发动作

#### 场景：外部长任务完成后 runtime 从恢复锚点继续
- **WHEN** 某次 agent 决定的外部运行已完成且对应 interrupt 仍处于 pending
- **THEN** runtime 可以基于持久化的 resume anchor 恢复 workflow
- **THEN** 新的 observation 和后续决策被写回同一 episode 的规范状态

#### 场景：过期恢复请求不会导致重复执行
- **WHEN** Web Host 与 CLI 基于同一个旧 `resume_token` 同时请求继续 workflow
- **THEN** runtime 只接受第一个匹配当前 state version 的请求
- **THEN** 其他请求得到 stale-state 或等价结构化错误，并且不会再次执行同一个工具动作
