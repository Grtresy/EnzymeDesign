# Session 08: Deep Research Engine

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

将 deep research 重构为 V3 capability engine，对 harness 暴露稳定 tool / command contract，并明确它与 `research teammate` 的边界。

## 参考

- `docs/v3/03-capability-engines.md`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/src/open_deep_research/deep_researcher.py`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/docs/deep_researcher_graph_详解.md`

## 本轮允许改动

- `packages/openzyme-engines` 中的 deep research engine
- `packages/openzyme-core` 中 research engine seams / contracts
- research projections / canonical evidence persistence
- 供 `deep_research` 与 `research teammate` 复用的 bio provider adapters / prompt packs / artifact mapping

若迁移初期仍需修改现有 `openzyme-graph` / `openzyme-runtime` 代码，允许以过渡方式实现，但目标归宿必须是 `openzyme-engines + openzyme-core`。

## 本轮禁止事项

- 不让 deep research engine 重新成为全局 orchestrator
- 不把 engine 内部 state 直接暴露给 UI / CLI
- 不修改 UI / CLI 产品层
- 不把 `research teammate` 合并进 deep research graph
- 不要求所有 research 行为都必须先进入 `deep_research`

## 完成产物

- V3 deep research engine API
- research invocation persistence
- normalized dossier output
- research task integration
- evidence / source / gap 回填 control plane
- `deep_research` 与 `research teammate` direct provider tools 复用的 `ResearchObservation` contract
- 基于 `open_deep_research` 的 LangGraph / LangChain engine 实现方向
- enzyme-design-aware bio research provider baseline：`PubMed`、`Semantic Scholar`、`UniProt`、`RCSB PDB`、`InterPro`
- research 下载的 sequence / structure 到 workspace artifact 的映射规则

## 验收标准

- harness 可以把 deep research 当作一个稳定能力调用
- clarification / brief / supervisor / synthesis 语义对外收敛
- 输出可直接进入 workspace projection
- 同一 task 可多次发起 research invocation，恢复与重试不依赖 raw graph checkpoint
- `research teammate` 可以根据 task 选择：
  - 调用 `deep_research`
  - 或直接使用 provider-specific research tools 完成简单查询 / 下载
- direct provider search 与 deep research 内部 search 产出的 normalized `findings / sources / artifacts / gaps` 形状一致
- direct provider search 的重要 findings 不应只停留在 transient tool result；后续实现应能写入 canonical research evidence / source refs
- sequence / structure 下载结果不会只留在 engine 内部临时目录，而是可回填为共享 artifact

## 迁移目标

默认目标不是长期保留 bridge runner，而是逐步形成原生 V3 deep research engine：

- `open_deep_research` 作为 deep research graph 的主要参考实现
- `LangGraph` 负责 engine 内部图、子过程、并行研究单元与 resumable control flow
- `LangChain` 负责 tool binding、structured output、prompt orchestration 与 provider adapters
- bio provider adapters 尽量同时支撑：
  - engine 内部 research tool loop
  - `research teammate` 的 direct provider actions
- 两个调用面共享 `ResearchObservation` payload，外层分别包装为 engine-internal `ResearchToolResult` 或 harness `ToolResult.content`
- `ResearchObservation` 的核心字段保持轻量：`status`、`summary`、`findings`、`unresolved_gaps`、`artifacts`、`provider`、可选 `raw_ref`
- `findings.sources` 进入 canonical source refs；`artifacts` 只用于真实下载 / 生成的 workspace assets
- evidence / artifact / invocation persistence 仍以 V3 control plane 为准，不把 raw graph state 暴露为产品真源

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-engines packages/openzyme-core apps/openzyme-host-api`

## 交接给下一轮

- Session 09 将 execution 纳入相同能力引擎模型
