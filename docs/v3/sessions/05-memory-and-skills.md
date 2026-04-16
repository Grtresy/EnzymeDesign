# Session 05: Memory And Skills

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

在已固定的 lane binding 规则上，实现 context compaction、memory persistence、skill loading。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s05-skill-loading.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s06-context-compact.md`

## 本轮允许改动

- runtime memory store
- compaction strategies
- skill discovery / lazy load machinery

## 本轮禁止事项

- 不把 memory 仅做成临时日志
- 不在本轮引入 background workers
- 不实现 capability engine 大改造
- 不重新定义 lane / agent ownership 语义

## 完成产物

- memory entry persistence
- continuity summary / compact hooks
- skill registry / skill injection
- lane-aware compaction / restore semantics
- compaction 后的 session restore

若必须提前于 Session 07 落地，本轮只允许交付 lane-agnostic 的 memory / compaction base，不得抢先固化 lane-aware restore 规则。

## 验收标准

- 压缩后 task / approval / lane 等状态不丢
- skills 按需加载，不预塞所有上下文
- session 可用压缩摘要继续工作
- `session` 与 `lane` 范围的 continuity summary 明确区分，恢复时不串味

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core`

## 交接给下一轮

- Session 06 在可恢复上下文上增加 background jobs 与协议层
