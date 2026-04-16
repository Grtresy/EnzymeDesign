# Session 06: Background And Protocols

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

在已固定的 task-lane-agent 绑定规则上，实现后台执行、inbox、delegation request-response 协议与统一 approval FSM。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s08-background-tasks.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s09-agent-teams.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s10-team-protocols.md`

## 本轮允许改动

- inbox models / repositories
- background job runner
- delegation protocol / agent roster projection
- approval protocol implementation
- event streaming glue

## 本轮禁止事项

- 不把审批再做成 execution graph 专属语义
- 不引入 lane/workspace 隔离实现
- 不重新定义 task / lane / agent 的绑定规则

## 完成产物

- inbox message store
- correlation id request-response FSM
- spawn / delegate protocol envelope
- agent roster projection
- background completion notifications
- unified approval handling

若必须提前于 Session 07 落地，本轮只允许交付 lane-agnostic protocol base，不得抢先固化 lane-aware restore / binding 规则。

## 验收标准

- 所有审批统一进入同一 protocol layer
- 后台执行可完成并回填通知
- inbox / approval 状态可投影给 UI / CLI
- agent-to-agent 消息、delegation、approval 使用统一 correlation / envelope 语义

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core apps/openzyme-host-api`

## 交接给下一轮

- Session 07 将 task 和 execution context 显式绑定到 lane
