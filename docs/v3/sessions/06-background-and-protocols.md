# Session 06: Background And Protocols

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

在已固定的 task-lane-agent 绑定规则上，实现后台执行、inbox、delegation request-response 协议与统一 approval FSM。

本轮里的 delegated teammate 默认是 task-aware protocol actor，而不是脱离 task 的自由聊天伙伴。

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

协议语义补充：

- `correlation_id` 解决消息线程归属
- `task_id` 解决工作归属
- `lane_id` 解决执行上下文归属
- `delegation request` 默认应尽量绑定 `task_id`
- protocol 既服务于 master -> teammate delegation，也服务于 teammate <-> teammate 的 peer communication
- protocol thread 默认围绕共享 session workspace 发生，而不是围绕一次性 prompt helper 发生

若必须提前于 Session 07 落地，本轮只允许交付 lane-agnostic protocol base，不得抢先固化 lane-aware restore / binding 规则。

## 验收标准

- 所有审批统一进入同一 protocol layer
- 后台执行可完成并回填通知
- inbox / approval 状态可投影给 UI / CLI
- agent-to-agent 消息、delegation、approval 使用统一 correlation / envelope 语义
- delegated teammate 默认围绕 task 推进工作，并把结果回传给 master agent / control plane

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core apps/openzyme-host-api`

## 交接给下一轮

- Session 07 将 task 和 execution context 显式绑定到 lane
