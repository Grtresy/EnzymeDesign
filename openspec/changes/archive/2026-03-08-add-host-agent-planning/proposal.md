## 为什么

代码库已经拥有可复用的 host runtime、Web Host 和 CLI，但当前工作流仍然把 LLM 收缩成“起草一个计划”的角色，后续工具调用、状态推进和交互流程基本被固定死在预定义的执行边界里。这和目标中的 Host Agent 不一致。

我们需要的不是一个 planning console，而是一个持续做决策的 host agent：它应当能够根据 episode 目标、工具观察结果和人类反馈，决定下一步行动、请求澄清、调用工具、修订 working plan，并在必要时暂停等待审批。

## 变更内容

- 将 `host-agent-planning` 重新定义为 LangGraph 驱动的持续决策型 Host Agent workflow，而不是一次性规划器。
- 将“计划”从执行前冻结的唯一真源改为 agent state 中可修订的动态工件。
- 扩展共享 runtime，使其暴露 agent workflow 恢复、受控工具调用、观察记录和人类反馈提交接口。
- 扩展 `mcp-project-memory` 数据契约，使 agent state、feedback log、approval gate、interrupt 和 resume anchor 都有规范资源与写入边界。
- 明确 host 层的 approval / safety gate，约束高成本、高风险或外部副作用动作必须经过显式门控。
- 保留 confirmed plan 作为人类批准快照，但允许 runtime 在没有 frozen plan 时基于已批准 action snapshot 执行受控动作。
- 明确 session / interrupt 状态模型，使 agent workflow 可以跨 Web Host、CLI 和长任务中断恢复。
- 明确 gate 必须绑定不可变 action revision，resume 必须使用版本校验与幂等 continue 语义，避免跨入口重复执行。
- 更新 Web Chat Host，使其围绕 agent state、待反馈项、观察结果和当前行动展开，而不是围绕手工确认计划展开。
- 更新 CLI，使其能够检查 agent state、恢复中断、提交反馈和驱动单步继续。

## 能力

### 新增能力
- `host-agent-planning`：LangGraph 驱动的 host agent 工作流，持续决定下一步行动、消费 observations、请求人类反馈并修订 working plan。

### 修改的能力
- `host-cli-runtime`：扩展共享 runtime 需求，暴露 agent workflow 服务、受控工具动作和可恢复的 agent state，而不是只暴露 planning/confirmation API。
- `mcp-project-memory`：扩展项目内存数据契约，持久化 agent state、decision trace、feedback log、approval gates、interrupts 和带版本校验的恢复锚点。
- `web-chat-host`：扩展浏览器宿主需求，展示 agent workflow 状态、待审批/待澄清项、最近 observations 和当前行动控制，而不仅仅是计划草案状态。

## 影响

- `packages/enzyme-host-runtime`：将现有 `planning/` 重构为 agent workflow 模块，承载图状态、决策节点、反馈节点、观察节点和模型适配器。
- `apps/mcp-project-memory`：扩展 canonical resources 和 mutation tools，承载 agent workflow 的状态谱系、审批门控和 interrupt 恢复锚点。
- `apps/enzyme-web-host`：更新为 agent-aware host UI，支持恢复 workflow、中断处理、人类反馈提交和 observation 展示。
- `apps/enzyme-host-cli`：增加面向 agent workflow 的调试和恢复入口。
- 工作区状态使用：持久化对象从单纯 planning revision 扩展为 agent working state、session context、interrupt queue、decision trace、feedback log、approval gate、action snapshots 和 observation refs。
- 依赖项：继续使用 LangGraph 和类型化状态 / adapter 依赖，但接口将围绕持续决策而不是单次起草。
