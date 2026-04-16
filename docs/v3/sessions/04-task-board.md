# Session 04: Task Board

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

实现持久化 task board，包括 DAG、状态转换与最小 task assignment 语义。

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

## 验收标准

- 任务可跨压缩恢复
- 被阻塞任务与可执行任务可明确区分
- harness loop 可从 task board 推断下一步工作

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core packages/openzyme-domain`

## 交接给下一轮

- Session 07 先在 task board 基础上引入 lane / workspace isolation
