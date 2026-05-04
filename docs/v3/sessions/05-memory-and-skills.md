# Session 05: Memory And Docs

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

在已固定的 lane binding 规则上，实现 context compaction、memory persistence，以及受控文档检索能力。skill loading 在 V3 中冻结，暂不作为默认工具、默认上下文注入机制或 execution 用法来源；是否完全弃用后续再决定。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s06-context-compact.md`

## 本轮允许改动

- runtime memory store
- compaction strategies
- docs discovery / lazy read machinery

## 本轮禁止事项

- 不把 memory 仅做成临时日志
- 不在本轮引入 background workers
- 不实现 capability engine 大改造
- 不重新定义 lane / agent ownership 语义
- 不启用 `skill.list` / `skill.load` 作为 V3 默认模型工具
- 不把 execution pipeline / HPC SDK 用法放回 skill catalog

## 完成产物

- memory entry persistence
- continuity summary / compact hooks
- docs registry / read-only document injection
- lane-aware compaction / restore semantics
- compaction 后的 session restore

若必须提前于 Session 07 落地，本轮只允许交付 lane-agnostic 的 memory / compaction base，不得抢先固化 lane-aware restore 规则。

## 验收标准

- 压缩后 task / approval / lane 等状态不丢
- docs 按需检索和读取，不预塞所有上下文
- execution pipeline / HPC SDK 用法必须来自 `docs/v3/execution-pipeline-docs/`，不再以 skill catalog 为 V3 主路径
- `skill.list` / `skill.load` 不出现在 V3 默认 tool surface；若旧代码仍保留，只能作为冻结兼容面，不能被新 V3 流程依赖
- session 可用压缩摘要继续工作
- `session` 与 `lane` 范围的 continuity summary 明确区分，恢复时不串味

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core`

## 交接给下一轮

- Session 06 在可恢复上下文上增加 background jobs 与协议层
