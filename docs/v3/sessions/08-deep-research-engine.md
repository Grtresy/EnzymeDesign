# Session 08: Deep Research Engine

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

将 deep research 重构为 V3 capability engine，对 harness 暴露稳定 tool / command contract。

## 参考

- `docs/v3/03-capability-engines.md`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/deep_researcher.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/docs/deep_researcher_graph_详解.md`

## 本轮允许改动

- `packages/openzyme-engines` 中的 deep research engine
- `packages/openzyme-core` 中 research engine seams / contracts
- research projections / canonical evidence persistence

若迁移初期仍需修改现有 `openzyme-graph` / `openzyme-runtime` 代码，允许以过渡方式实现，但目标归宿必须是 `openzyme-engines + openzyme-core`。

## 本轮禁止事项

- 不让 deep research engine 重新成为全局 orchestrator
- 不把 engine 内部 state 直接暴露给 UI / CLI
- 不修改 UI / CLI 产品层

## 完成产物

- V3 deep research engine API
- research invocation persistence
- normalized dossier output
- research task integration
- evidence / source / gap 回填 control plane

## 验收标准

- harness 可以把 deep research 当作一个稳定能力调用
- clarification / brief / supervisor / synthesis 语义对外收敛
- 输出可直接进入 workspace projection
- 同一 task 可多次发起 research invocation，恢复与重试不依赖 raw graph checkpoint

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-engines packages/openzyme-core apps/openzyme-host-api`

## 交接给下一轮

- Session 09 将 execution 纳入相同能力引擎模型
