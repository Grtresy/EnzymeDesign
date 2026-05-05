## Why

当前 Web Host 已经能把 workflow 跑起来，也能展示状态、审批、执行结果和报告，但整体交互 still 更像“操作台”，不像“在和系统协作”。用户能看到系统停在什么地方，却不一定能自然地感受到：系统刚刚做了什么、为什么停下、现在在等我做什么、我做完之后它会怎么继续。

现在还不适合立刻引入新的对话桥梁层。底层的 canonical workflow state、approval gate、interrupt、run lineage 和 decision explanation 刚刚稳定下来，如果马上再加一个自然语言中间层，很容易把问题搞混。更合理的顺序是：先做一轮“无桥梁版本验证”，看看仅靠现有结构化状态和现有 runtime 能不能把 Web Host 重新组织成更有连续感、更像对话协作的体验。如果这一步已经足够好，后续就不必过早增加新的复杂层。

## What Changes

- 调整 Web Host 的主交互区域，让页面首先呈现“连续叙事”而不是分散的状态块。
- 基于 canonical workflow state、workflow audit、approval gate、interrupt、progress summary 和 explanation 生成一个 conversation-style timeline，让用户顺着时间线理解系统刚刚做了什么、当前为什么停下、下一步建议是什么。
- 把 pending interrupt、approval gate、selected action、run result 等关键节点改造成嵌在时间线里的消息卡片，而不是只放在独立面板里。
- 明确这次验证不引入新的 chat 输入框、不引入新的 message 真源、不让前端私自推进 workflow；所有真实动作仍通过共享 runtime 和 canonical state 完成。
- 为这次验证补充回归测试和手动体验路径，确保“更像对话”只是展示层变化，不会破坏现有 workflow-first 边界。

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `web-chat-host`: 浏览器主界面需要支持基于 canonical workflow state 的 conversation-style timeline、消息卡片化的 gate / interrupt / run 状态，以及更连续的叙事式主操作区。

## Impact

- `apps/enzyme-web-host`
- 可能需要少量触及 `packages/enzyme-host-runtime` 的 snapshot 组织或展示辅助字段，但不新增新的状态真源
- Web Host 相关测试
- playground / 手动演示文档，用于验证“无桥梁版本”是否已经足够改善协作感
