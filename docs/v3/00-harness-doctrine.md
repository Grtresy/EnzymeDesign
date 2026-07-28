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

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Free-text or model-inferred workflow activation is forbidden. A caller may explicitly bind a versioned workflow knowledge pack by id, version, manifest digest, and pinned document digests; requirement or digest drift fails before the provider call, while the agent retains strategy choice inside the declared constraints. LangGraph is allowed inside capability engines, not as product truth.`

除非用户明确要求，否则不得弱化这条 guardrail。

## 8. 可执行架构资格边界

架构资格系统位于 repository/operator validation plane，不进入 harness 产品状态。它从稳定合同
和 closed invariant registry 出发，用真实 `HostApiDependencies + create_app()` composition、
file-backed SQLite、当前 worker/gateway/projection 与 deterministic controlled adapter 观察系统，
但不替 agent 创建 task、选择 plan、推断业务终态或调用真实外部系统。report/receipt 只能回答
“当前提交是否满足已声明架构不变量”，不能成为 session、campaign 或 scientific truth。

该边界落实同一原则：harness 忠实呈现真实约束，agent 在约束内保留策略自由。资格测试验证
authority、fencing、effect、evidence 与 bounded progress，不把某条固定 AOX workflow 写回通用
harness。

## 9. Failure observation 与 attempt doctrine

Harness 的 fail closed 对象是不可违反的真实边界，不是“任何函数返回 false 就杀死 agent”。
effect 已知的 ordinary failure 必须成为 agent 可读 observation 并允许 bounded turn 继续；
unknown effect、fencing、authority、integrity、permission、budget 和未退休 process/writer
才停止对应 ownership。任何 runtime stop 都不等于 task business exit。

`FailureObservation` 是 Host/Harness 的 immutable fact，`failure.get` 只负责读取。模型的
hypothesis、解释与恢复策略不进入第二套 failure control plane；Harness 不建立 turn-local
recovery obligation，不要求 exact settlement，也不因安全失败后的 prose/read 触发 response
veto。agent 可以显式拒绝，但 Harness 不替它拒绝：需要外部修复或新 authority 时使用
`task.finish(blocked)`，objective 本身确知不可能时才使用 `failed`。bounded turn 的
`COMPLETED` / `MAX_STEPS_EXCEEDED` 都不自动改变 task。

失败不会自动创造新的工作。ordinary tool failure 在同一 bounded loop 中交给 agent；
continuation/engine 的后置结果复用其 canonical `ENGINE_COMPLETED` source-bound signal。
approval、user message、protocol、task delegation、engine/continuation completion 等真实
世界变化仍可产生 wakeup，单纯“agent 尚未采取 Harness 期待的恢复动作”不能产生 signal。

Lane 只在它确实提供 cwd、branch、workspace 与 task isolation 时进入事实身份。它不是所有
failure、provenance 或 recovery 的强制 join key；session-scoped evidence 可以明确保持
`lane_id=None`。

允许试错不等于忽略历史。formal scientific attempt 必须保留 full occurrence universe，由
agent 显式 disposition 并选择 adopted chain；closure 同时要求 selection、effect、
authorization 和 quiescence 完整。详见
[08-failure-recovery-and-scientific-attempts.md](08-failure-recovery-and-scientific-attempts.md)。

Harness 呈现 scientific 约束的正确单位是 attempt-bound、digest-closed contract，而不是
prompt 提示。role-to-operation signature、scope、cardinality 和 reuse policy 必须由同一个
registry contract 同时驱动 validation、inspection/readiness 和 verifier。Harness 可以告诉
agent 某 occurrence 与哪些 roles 兼容，但不能替它选择 occurrence、role、disposition、
replacement 或 seal；采用动作由 agent 通过原子 `scientific.operation.adopt` 明确表达。

bounded turn 用尽步骤时，exact signal 必须 terminal 且不得原地加 budget/replay；task 与
agent 仍可在新 turn replan。runtime command 也必须区分已经发生的 scheduler 进度和其后的
projection 成败：projection error 不能把真实 processed count 改写为零。known terminal
no-effect occurrence 可留在同一 authorized attempt 并被显式处置；unknown effect、active
owner、authority/resource breach 与 cross-attempt reuse 仍 fail closed。
