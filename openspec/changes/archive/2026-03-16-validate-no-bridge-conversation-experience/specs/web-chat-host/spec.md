## MODIFIED Requirements

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
