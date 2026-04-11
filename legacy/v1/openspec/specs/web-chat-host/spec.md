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
The system MUST 为活跃 episode 提供一个基于 canonical workflow state 的 conversation-style 主界面，使用户可以顺着一条连续叙事理解 agent 刚刚做了什么、当前为什么停下、系统在等待什么，以及下一步最合理的动作，而无需自己在多个分散 panel 之间拼接状态。

该主界面必须满足：

- 主操作区域使用由 canonical state 派生出的 timeline / message-card 视图，而不是依赖独立的浏览器 message store 或聊天历史真源
- timeline 至少能够表达：
  - 当前状态总结
  - 当前 stop reason / blocker
  - next step suggestion
  - selected action 摘要
  - pending interrupt / approval gate
  - recent run result 或 observation 摘要
- gate、interrupt、selected action 和 recent run 等关键节点必须可以以消息卡片形式嵌入主时间线，而不是只能在独立面板中查看
- report preview、trace/debug、raw agent state 和 provenance 信息仍然必须可查看，但不得继续占据主操作区域的最高优先级
- 浏览器不得为该时间线维护会独立漂移的 workflow message 真源；刷新后必须能够仅基于共享 runtime 返回的 canonical snapshot 重建相同语义

当 agent workflow 启用 capability discovery 与 LLM backend 时，浏览器检查界面还必须包括：

- capability inspect 与相关 workflow audit 事件的 trace 或 debug 视图入口
- 当前 agent backend 名称
- 当前是否处于 fallback / degraded 状态
- 最近一次 sidecar 或 provider 错误摘要（若存在）
- provider / model / sidecar 版本等详细 provenance 信息的详情视图或调试视图入口

浏览器主操作区域 MUST 优先显示 narrative timeline、当前卡点和可操作消息卡片，而不是把 capability inspect 细节、完整 raw state 或 provider/model 元数据放在最显著位置。

#### Scenario: Awaiting approval state is shown as a narrative timeline with an actionable gate card
- **WHEN** 一个 episode 停在 `awaiting_approval`，且 runtime 已生成 pending gate 和对应 interrupt
- **THEN** Web Chat Host 在主区域显示一条能解释“系统为什么停下”的叙事时间线
- **THEN** 待审批 gate 以可操作消息卡片形式出现在时间线中，用户可以就地看到原因并提交审批动作

#### Scenario: Refreshing the page reconstructs the same timeline from canonical state
- **WHEN** 用户刷新页面或稍后重新打开同一个活跃 episode
- **THEN** Web Chat Host 基于共享 runtime 返回的 canonical snapshot 重建相同语义的 timeline 和卡片
- **THEN** 浏览器不会依赖独立 message 历史才能知道系统当前停在什么地方

#### Scenario: Debug information remains available without displacing the main workflow narrative
- **WHEN** 当前 episode 同时存在 plain-language explanation、technical explanation、workflow audit 和 provider provenance
- **THEN** Web Chat Host 在主区域优先展示面向用户的 narrative timeline、blocker 和 next step
- **THEN** technical explanation、workflow audit 和 provenance 信息仍保留在 debug / trace 区域供进一步检查

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

### Requirement: Web Chat Host 突出显示当前进度、停下原因和下一步建议
The system MUST 在浏览器主操作区域优先展示 workflow 当前进度、停下原因和下一步建议，而不是要求用户先阅读原始状态 JSON、完整 trace 或底层日志。

浏览器主视图至少必须显示：

- 当前 workflow 处于什么状态
- 系统最近完成了什么
- 当前卡在哪里
- 用户现在最应该做什么
- 当前是否需要用户立即介入

当 workflow 进入 `needs_input`、`awaiting_approval`、`blocked`、`max_turns_exceeded` 或等价状态时，浏览器主视图 MUST 把该原因放在显著位置。

#### 场景：浏览器用户打开一个等待输入的 episode
- **WHEN** workflow 因缺少必要输入而暂停
- **THEN** Web Chat Host 在主区域清楚显示"系统在等什么输入"
- **THEN** 用户可以直接看到补齐输入后的建议下一步，而不必先进入调试面板

#### 场景：浏览器用户打开一个等待审批的 episode
- **WHEN** workflow 因审批 gate 暂停
- **THEN** Web Chat Host 在主区域显示审批原因、当前卡点和建议动作
- **THEN** 用户无需先阅读原始 gate 数据也能理解为什么系统没有继续执行

### Requirement: Web Chat Host 将解释信息分成简明说明和技术细节
The system MUST 在浏览器中把决策解释分成"易懂说明"和"技术细节"两层，而不是把所有信息都挤进同一块展示区域。

浏览器界面至少必须支持：

- 在主操作区域展示简明说明
- 在 trace、debug 或等价展开区域展示技术解释
- 让两层解释指向同一个 selected action、停下原因或审批决定

简明说明 MUST 优先回答：

- 系统为什么这样做
- 这对当前目标意味着什么
- 用户接下来该做什么

首版简明说明 MUST 固定使用中文。

#### 场景：用户查看当前 selected action 的原因
- **WHEN** workflow 选中了新的下一步动作
- **THEN** 主区域显示易懂说明，帮助用户快速理解该动作的目的
- **THEN** 调试区域可以展开查看更详细的技术解释和相关状态依据

#### 场景：用户查看 blocked 状态的原因
- **WHEN** workflow 进入 `blocked` 或等价状态
- **THEN** 主区域先显示简明说明和建议动作
- **THEN** 技术细节仍可在展开区域查看，而不是占据主要操作空间

### Requirement: Web Chat Host validates conversation feel without introducing a new chat control plane
The system MUST 在首轮“无桥梁版本验证”中，把“更像对话”的体验限制为 canonical workflow state 的展示方式变化，而不是同时引入新的自然语言控制层。

该验证阶段至少必须满足：

- 主界面可以看起来像连续对话或连续汇报，但其内容仍然来自共享 runtime 和 canonical workflow state
- 用户继续 workflow、审批 gate、提交 feedback、执行 selected action 的路径，仍然是已有的 runtime-backed 动作，而不是浏览器端自由解释的聊天命令
- 页面可以包含嵌在消息卡片里的按钮和表单，但不得要求新增自由文本 chat composer 才能完成关键 workflow 操作
- 页面不得新增一份独立持久化的 browser-side conversation state 来记录 workflow 真实进度

#### Scenario: User responds to the workflow through inline action cards rather than a new chat bridge
- **WHEN** 用户需要批准 gate、继续 workflow 或提交结构化 feedback
- **THEN** Web Chat Host 允许用户直接在相关消息卡片中完成这些动作
- **THEN** 这些动作仍然通过共享 runtime 更新 canonical workflow state，而不是通过新的 chat bridge 私自解释和提交

#### Scenario: The validation surface remains usable without a freeform chat composer
- **WHEN** 用户进入一个需要人工介入的 episode，例如 `awaiting_approval` 或 `needs_input`
- **THEN** 用户无需依赖新的自由文本聊天输入框，也能完成本轮最关键的操作
- **THEN** 该页面仍然可以被视为一次“无桥梁版本”的有效体验验证，而不是半完成的聊天系统
