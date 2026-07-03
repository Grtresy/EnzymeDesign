# OpenZyme V3 Harness Doctrine

## 1. 文档目的

本文档定义 OpenZyme V3 的最高级约束。

它不是实现细节文档，而是后续所有设计、任务拆分、代码评审时的裁判规则。

## 2. 第一原则

OpenZyme V3 的第一原则是：

**Master Agent 负责判断与对外协作，Harness 负责世界。**

这里的 world 指：

- tools
- knowledge
- observation
- action interfaces
- permissions
- task persistence
- context compaction
- background execution
- lane/workspace isolation
- approval protocols
- canonical projections

Harness 可以持久化和校验任务状态，但不能替 agent 判断某个 capability/tool outcome 是否代表业务阶段完成。业务任务的完成、阻塞、失败或取消必须由 master/teammate 通过显式 task lifecycle 工具写入。

这里的 `Master Agent` 指对外代表 OpenZyme 与用户沟通、理解需求、创建和编排 task 的顶层 agent，也是 agent team 的 team leader。

这里的 `Harness` 指为 master agent 与 teammate agents 提供持久化状态、协议、执行约束、恢复与投影的系统层。

参考基线：

- `/home/grtresy/VSCodeRepo/learn-claude-code/README-zh.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s03-todo-write.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s04-subagent.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s09-agent-teams.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s06-context-compact.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s07-task-system.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s08-background-tasks.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s10-team-protocols.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s11-autonomous-agents.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s12-worktree-task-isolation.md`

## 3. V3 明确反对的方向

V3 明确反对以下退化模式：

- 继续把顶层产品真状态建立在 `supervisor graph` 上
- 用越来越多的 graph node / conditional edge 充当产品 workflow 编排语言
- 把 AI 的判断硬编码成 phase router、decision tree、巨大的 if-else 流水线
- 让前端、CLI、Host 直接消费 raw graph state
- 让 task、approval、memory、lane 只存在于 prompt 或临时对话上下文里
- 让 harness 直接承担用户意图理解、task 拆解与项目级任务编排
- 让顶层 conversation 直接裸触发 capability engine，而不经过 task / team protocol 组织
- 把 teammate 退化成 deterministic helper，只保留身份外壳而没有自己的 restore context、tool surface 和 agent loop

如果某项设计满足下面任一描述，应默认视为偏离：

- “需要再加一个 phase 来表达这个产品动作”
- “把这个状态先挂在 graph checkpoint 里，以后再投影”
- “这个逻辑先写成 phase-local state，等稳定再抽象 control plane”

## 4. V3 允许的 LangGraph / LangChain 用法

LangGraph / LangChain 在 V3 中是**内部能力实现工具**，不是产品顶层真状态引擎。

允许的用法：

- `deep_research` 内部的 brief / supervisor / researcher / synthesis 子流程
- report generation / compression / summarization 等局部能力图
- tool-calling、structured output、provider 适配

不允许的用法：

- 让产品工作区的主语义重新依附于 phase routing
- 让 approval、task、lane、memory、session 生命周期只存在于 graph state
- 让浏览器为 graph implementation 细节负责

## 5. V3 顶层真状态

V3 顶层真状态必须属于 harness control plane，而不是属于某个 capability engine。

至少包括：

- `session`
- `task`
- `lane`
- `approval`
- `artifact`
- `run`
- `report`
- `inbox_message`
- `memory_entry`
- `workspace_projection`

这些对象的职责分工默认是：

- `conversation` 负责承载用户和 master agent 的对话时间线
- `task` 负责承载 master agent 对内部工作的正式安排，也是 team 内部协作的第一锚点
- `lane` 负责承载 task 的执行隔离上下文
- `agent_member` 负责承载 team 内可恢复、可通信、可被投影的 teammate agent
- `artifact` / `report` / `run` 负责承载 team 的共享工作面，而不只是 capability 的附属结果

这些对象必须可以在：

- API 中查询
- UI / CLI 中投影
- 压缩后恢复
- 多轮对话后延续
- 后台执行后回填

## 6. V3 设计判断法

做设计判断时，优先问以下问题：

1. 这是不是 harness 责任，而不是模型责任？
   对 V3 而言，harness 的责任是持久化与协议，不是理解用户意图或替 master agent 做任务拆解。
2. 这项状态是否应该跨压缩、跨会话、跨 lane 持久化？
3. 这项能力应不应该作为一个 tool / protocol / control-plane object 存在？
4. UI 是否可以只消费 projection，而不用理解内部能力引擎？
5. 如果把 LangGraph 替换掉，产品主语义还成立吗？

额外判断：

6. 这项协作是围绕 `task`、`lane`、`artifact` 的 team 协同，还是只是 prompt 里的一段自由聊天？
7. 这项能力应该由 master agent 对外承诺，还是由 teammate agent 在共享 workspace 上内部推进？

如果第 5 条回答是“不会”，说明设计仍然 graph-first。

## 7. 对后续 AI 的硬性提醒

后续 AI 在每次 V3 实施时必须默认遵守以下 guardrail：

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

除非用户明确要求，否则不得弱化这条 guardrail。
