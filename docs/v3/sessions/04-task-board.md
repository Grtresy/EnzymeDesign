# Session 04: Task Board

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

实现持久化 task board，包括 DAG、状态转换与最小 task assignment 语义。

这里的 `task` 指 master agent 对内部团队下达的正式工作单元，而不是普通对话消息或 capability 参数。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s03-todo-write.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s07-task-system.md`

## 本轮允许改动

- task repositories
- harness loop 的 task-related tools
- task projections

## 本轮禁止事项

- 不把任务列表塞回 prompt 充当唯一真状态
- 不引入 lane/worktree
- 不做 background jobs

## 完成产物

- task create / update / list / get
- blocked_by 依赖关系
- assigned_ref / priority / status
- task board projection

补充约束：

- task 默认由 master agent 基于用户目标创建与编排
- task board 的主用途是支撑内部工作协调，而不是给用户做手工项目管理
- 具体 research / execution / reporting task 默认可被委托给 teammate agent 推进
- reporting task 默认由 report teammate 围绕 `report_draft` 直接推进，而不是默认先起 reporting engine
- capability invocation 默认应围绕 task 发生，而不是绕过 task 直接从 conversation 裸触发

## 验收标准

- 任务可跨压缩恢复
- 被阻塞任务与可执行任务可明确区分
- harness loop 可从 task board 推断下一步工作
- 能区分“只属于 conversation 的澄清消息”和“应正式落入 task board 的内部工作”

推荐的判断规则：

- 只留在 `conversation`：澄清问题、解释说明、礼貌往返、交付后的简短反馈
- 应沉淀为 `task`：需要独立推进、可委托、可绑定 lane / approval / capability、可判断完成的工作

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core packages/openzyme-domain`

## 交接给下一轮

- Session 07 先在 task board 基础上引入 lane / workspace isolation
