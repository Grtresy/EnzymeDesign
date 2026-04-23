# Session 09: Execution Engine

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

将 HPC execution 改造成 V3 capability engine，并统一接入 harness approval protocol。

## 参考

- `docs/v3/03-capability-engines.md`
- `/home/grtresy/VSCodeRepo/EnzymeDesign/apps/mcp-hpc-runner/`

## 本轮允许改动

- execution runtime seams
- execution engine contract
- run / artifact persistence
- approval integration

## 本轮禁止事项

- 不新建 execution phase 作为产品主语义
- 不回到 graph-native approval-only 语义
- 不改 Web UI / CLI

## 完成产物

- execution engine API
- execution invocation persistence
- harness-managed approval path
- request compile / submit / parse result
- canonical run / artifact updates

## 验收标准

- 审批从 control plane 发起和恢复
- run / artifact 可关联到 session / task / lane
- 同一 task 的多次 execution invocation 可区分、可恢复
- execution 结果可回到 report draft / workspace projection

## 建议验证

- `uv run pytest -m "not integration" apps/mcp-hpc-runner packages/openzyme-engines packages/openzyme-core apps/openzyme-host-api`

## 交接给下一轮

- Session 10 汇总 research / execution / artifacts 成 report draft 与统一工作区叙事
