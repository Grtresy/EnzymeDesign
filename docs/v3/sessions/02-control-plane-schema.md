# Session 02: Control Plane Schema

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

定义并实现 V3 control plane 的 canonical types、repositories、storage schema 草案。

## 参考

- `docs/v3/02-control-plane.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s07-task-system.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s10-team-protocols.md`

## 本轮允许改动

- `packages/openzyme-domain`
- `packages/openzyme-core` 中与 repository / persistence 直接相关的边界
- 必要 migration 资产

若代码仍暂时位于旧的 `openzyme-storage` / `openzyme-runtime` 目录，可先在原地实现，但设计目标必须收敛到 `openzyme-core`。

## 本轮禁止事项

- 不实现 UI / CLI
- 不引入 deep research engine 改造
- 不写 harness loop
- 不将 `session/task/lane` 状态先临时挂在 graph checkpoint

## 完成产物

- `session/task/lane/approval/inbox/memory` 的 domain models
- `agent_member / engine_invocation` 的 domain models
- repositories / storage contracts
- migration SQL 或等价持久化方案
- 基础 CRUD 测试

## 验收标准

- 这些对象能脱离 graph checkpoint 独立存在
- repository API 能支持后续 task board、lane binding、approval FSM、memory persistence、delegation protocol、engine invocation restore
- memory schema 具备 `session / lane / task` scope 语义
- inbox schema 能区分 `user / agent / system` sender-recipient typing
- schema 不要求一步到位，但字段命名必须稳定

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-domain packages/openzyme-core`

## 交接给下一轮

- Session 03 可以在这些 canonical objects 之上实现 harness kernel
