# Session 01: V3 文档包落盘

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

一次性建立 `docs/v3` 文档包，作为后续全部 V3 实施的统一来源。

## 本轮允许改动

- `docs/v3/README.md`
- `docs/v3/*.md`
- `docs/v3/sessions/*.md`

## 本轮禁止事项

- 不改任何运行时代码
- 不改数据库 schema
- 不改 API、CLI、UI
- 不回写 `docs/OpenZyme架构设计.md`

## 完成产物

- doctrine 文档
- 目标架构文档
- control plane 文档
- capability engines 文档
- public interfaces 文档
- migration roadmap 文档
- 12 个 session 任务包文档

## 验收标准

- 每个 session 文档都包含：目标、允许改动、禁止事项、完成产物、验证命令、交接条件
- 每个 session 文档顶部都重复 guardrail
- 文档中明确引用 `learn-claude-code` 与 `open_deep_research` 的参考路径

## 建议验证

- `rg -n "Guardrail|禁止事项|交接条件" docs/v3`
- `rg -n "learn-claude-code|open_deep_research" docs/v3`

## 交接给下一轮

- 后续 AI 在开始 V3 任意工作前，先读 `docs/v3/README.md` 和对应 session 文档
