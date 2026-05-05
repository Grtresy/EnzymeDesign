# Session 07: Lane Isolation

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

实现 lane/workspace isolation，使任务与执行上下文显式绑定。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s12-worktree-task-isolation.md`

## 本轮允许改动

- lane manager
- 任务与 lane 绑定
- 可选 worktree / cwd 隔离实现
- lane lifecycle events

## 本轮禁止事项

- 不把 lane 当成临时 UI 概念
- 不在本轮重写 deep research / execution engine

## 完成产物

- lane create / claim / keep / remove
- task-lane binding
- lane-scoped memory / engine invocation binding rules
- delegated agent lane binding rules
- lane projection
- lifecycle event log

## 验收标准

- harness 执行时能明确知道在哪个隔离上下文运行
- lane 状态可跨重启恢复
- task 与 lane 的关系可查询、可投影
- 同一 session 下多 lane 并发时，memory、engine runs、delegated agents 可区分且可恢复

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core`

## 交接给下一轮

- Session 05 在 lane 规则已固定的前提下引入 memory、compaction、docs retrieval；随后 Session 06 再接 protocol / background
