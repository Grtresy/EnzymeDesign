## ADDED Requirements

### Requirement: CLI 输出简洁的决策状态摘要和下一步建议
The system MUST 让 CLI 在读取活跃 workflow 状态时，优先输出简洁、可执行的状态摘要，而不是只打印底层状态字段。

CLI 的默认摘要至少必须包括：

- 当前 workflow 状态
- 最近完成的关键动作
- 当前停下或卡住的原因
- 建议的下一步动作
- 当前是否需要用户介入

当 workflow 处于 `needs_input`、`awaiting_approval`、`blocked`、`max_turns_exceeded` 或等价状态时，CLI MUST 明确输出该原因，而不是只显示通用的失败或等待文案。

#### 场景：CLI 用户查看等待审批的 workflow
- **WHEN** 用户运行状态或 workflow 相关命令，且当前 episode 因审批 gate 暂停
- **THEN** CLI 输出说明系统为什么停下
- **THEN** CLI 输出建议用户下一步执行审批、拒绝或修改约束，而不是只显示存在 pending gate

#### 场景：CLI 用户查看预算耗尽的 workflow
- **WHEN** workflow 因达到自动推进预算而停止
- **THEN** CLI 输出清楚的停止原因
- **THEN** CLI 输出建议动作，例如补充信息、人工继续或调整目标

### Requirement: CLI 在详细模式下显示技术解释和策略原因
The system MUST 支持 CLI 在详细模式下输出技术解释和策略原因，帮助用户调试为什么系统选了某个动作、为什么暂停，或为什么要求审批。

详细模式至少必须能够展开：

- selected action 的技术解释
- 停止或暂停的技术原因
- gate 的策略原因和信任判断结果
- 与当前判断相关的关键 observation 或等价上下文摘要

默认模式 MUST 保持简洁；详细模式才展开更多调试信息。

面向用户的简明解释在首版 MUST 固定使用中文。

#### 场景：CLI 用户用详细模式查看当前动作原因
- **WHEN** 用户以详细模式查看 workflow 状态
- **THEN** CLI 展示当前 selected action 的技术解释和相关上下文
- **THEN** 用户可以区分“面向人看的建议”与“面向调试的依据”

#### 场景：CLI 用户用详细模式查看审批原因
- **WHEN** 某个动作需要审批且用户以详细模式查看状态
- **THEN** CLI 展示更完整的策略原因和信任判断结果
- **THEN** 用户不需要手动打开工作区文件才能理解为什么系统没有继续执行
