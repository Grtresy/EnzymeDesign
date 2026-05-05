## Why

当前 Host 已经能跑通“启动 workflow、执行动作、记录状态、等待反馈、恢复继续”这条主链路，但用户视角下的决策体验还不够完整。用户经常只能看到“系统现在停住了”或“系统选了一个动作”，却不容易看明白为什么停、为什么选、还差什么、下一步会怎样。

Phase 2 里最先该补的，不是再堆新工具，而是把 Host 的决策过程讲清楚、管清楚、展示清楚。这样后续接入 `mcp-bio-research`、`mcp-structure-workbench` 或多轨设计时，系统才不会变成“能力更多了，但用户更难理解和介入”。

## What Changes

- 为 host agent 增加更明确的终止语义，能清楚区分完成、失败、等待输入、预算耗尽、需要升级处理等状态。
- 为 host agent 增加更清晰的自动推进边界，避免用户不知道系统会继续做什么，或为什么没有继续做。
- 为 runtime 增加更易理解的信任与审批策略表示，让“为什么这个动作需要审批、为什么另一个不需要”变得可解释。
- 为 Web Host 和 CLI 增加统一的进度、停止原因、下一步建议和决策解释展示，而不是只显示原始状态快照。
- 让决策解释同时覆盖“技术原因”和“面向用户的简单说明”，帮助用户快速判断是否继续、修改约束或人工接管。

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `host-agent-planning`: 补充终止条件、自动推进预算、信任/审批语义和决策解释的规范要求。
- `web-chat-host`: 补充浏览器端的进度展示、停止原因、下一步建议和易懂解释要求。
- `host-cli-runtime`: 补充 CLI 侧的进度摘要、终止原因、恢复建议和解释输出要求。

## Impact

- `packages/enzyme-host-runtime`
- `apps/enzyme-web-host`
- `apps/enzyme-host-cli`
- `apps/mcp-project-memory`
- Host runtime 的 workflow 状态模型、审计记录和 Host 展示层会增加新的结构化字段或展示约定
