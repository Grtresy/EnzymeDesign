## MODIFIED Requirements

### Requirement: Web Chat Host resumes project and episode context in the browser
The system MUST 提供一个基于浏览器的 Host 入口点，该入口点加载已初始化的 Enzyme 项目工作区，解析当前 episode，并呈现活跃的项目上下文、agent working state 和待处理 workflow 中断点，而无需用户手动检查工作区文件。

Web Chat Host 必须至少显示：

- 当前项目标识
- 当前 episode 标识和目标
- 当前 agent state 摘要
- 当前 working plan 或 selected action
- 待审批 / 待澄清 / 待反馈项
- 活跃 episode 的最近 observations 和 runs

#### 场景：打开现有项目恢复待反馈的 agent workflow
- **WHEN** 用户打开一个已存在活跃 episode 且 agent workflow 停在待澄清状态的项目
- **THEN** 浏览器 UI 从规范工作区状态显示当前项目、episode、目标、待澄清问题和最近 observations
- **THEN** 用户可以直接从该中断点继续，而无需先通过 CLI 查状态

### Requirement: Web Chat Host can drive the host workflow through shared runtime services
The system MUST 让浏览器 Host 能够通过调用共享 host runtime 服务来创建或切换 episode、启动或恢复 agent workflow、提交人类反馈、批准或拒绝需要门控的动作、触发 agent 决定的执行动作，以及继续 workflow，而不是通过 shell 调用 CLI 或在前端重新实现编排逻辑。

浏览器操作界面必须至少包括：

- 从目标创建新 episode
- 启动或继续 agent workflow
- 查看并提交待处理的人类反馈
- 批准或拒绝需要门控的 proposed action
- 查看当前 selected action 和 working plan
- 触发继续执行或恢复操作

#### 场景：浏览器用户提交澄清反馈并继续 workflow
- **WHEN** agent workflow 在 Web Chat Host 中提出一个澄清问题
- **THEN** 用户可以在浏览器中提交反馈并继续同一个 workflow
- **THEN** Host 通过共享 runtime 持久化反馈并推进规范状态，而不是在前端私有地推进对话

### Requirement: Web Chat Host visualizes execution state and report artifacts
The system MUST 为活跃 episode 提供 agent state、recent observations、run lineage、待处理 feedback items 和生成的 episode 报告的浏览器面板，以便用户可以检查 agent 行为和输出，而无需手动浏览项目工作区。

浏览器检查界面必须包括：

- 当前 agent state 摘要
- 最近 selected actions / decision trace 摘要
- 最近 observations 和 run 列表
- 待处理的 feedback / approval 项
- 当前 episode 的报告视图或下载入口

#### 场景：浏览器用户审查 agent 为什么改变行动路径
- **WHEN** 一个 episode 在多轮 observation 后切换了 strategy 或 selected action
- **THEN** Web Chat Host 显示最近 observations、decision trace 摘要和新的 working plan
- **THEN** 显示的信息与共享 runtime 生成的规范 agent state 和 run lineage 匹配

## ADDED Requirements

### Requirement: Web Chat Host 显示并处理 approval / safety gates
The system MUST 在浏览器中显式展示由 runtime 生成的 approval / safety gates，并允许用户查看风险原因、审批要求和当前状态，而不是仅通过按钮文案隐含审批语义。

浏览器界面至少必须显示：

- gate 类型
- 风险等级
- policy reason
- 待处理状态
- 可提交的审批动作

#### 场景：浏览器用户审查并批准高风险动作
- **WHEN** agent workflow 为一个高风险动作生成待审批 gate
- **THEN** Web Chat Host 显示该 gate 的原因和所需反馈类型
- **THEN** 用户批准后，workflow 可以从同一 interrupt state 继续推进

### Requirement: Web Chat Host 恢复 session / interrupt context
The system MUST 让浏览器 Host 显式展示当前 workflow 的 pending interrupts 和 session 恢复上下文，而不是只显示静态状态摘要。

浏览器至少必须能够显示：

- 当前 pending interrupt 列表
- 当前 interrupt 类型
- 最近恢复锚点或恢复来源
- interrupt 相关的 observation / feedback 上下文
- 当前 workflow 的活动 state version 或等价新鲜度信息

#### 场景：浏览器用户在刷新后继续同一个 interrupt
- **WHEN** 用户刷新页面或稍后重新打开 Web Host
- **THEN** 浏览器仍能恢复并显示同一 episode 的 pending interrupt 和相关上下文
- **THEN** 用户可以从该恢复点继续提交反馈或继续 workflow

#### 场景：浏览器提交过期恢复请求时刷新规范状态
- **WHEN** 浏览器基于过期的 interrupt 快照提交 approval 或 continue，而 runtime 返回 stale-state 错误
- **THEN** Web Chat Host 刷新 canonical interrupt state、gate 状态和 state version
- **THEN** 浏览器不会假定动作已被再次执行，也不会在前端私有地吞掉该冲突
