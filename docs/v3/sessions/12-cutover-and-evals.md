# Session 12: Cutover And Evals

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

完成 V3 上线前的验证、迁移预演、cutover checklist、回滚策略和评估。

## 参考

- `docs/v3/05-migration-roadmap.md`
- `/home/grtresy/VSCodeRepo/26/open_deep_research/tests/`

## 本轮允许改动

- evals
- observability
- migration scripts
- cutover 文档
- 必要的短期迁移 shim

## 本轮禁止事项

- 不新增新的顶层架构概念
- 不再扩大产品边界

## 完成产物

- cutover checklist
- rollback strategy
- V2 retirement plan
- end-to-end evals
- observability / tracing requirements

## 验收标准

- 至少一条 V3 端到端路径可稳定运行
- 出现故障时有可执行回滚路径
- 评估脚本可以度量 research / execution / report drafting / final delivery 质量与成本
- 已明确 V2 停止功能演进、迁移窗口、下线路径与残余 shim 清理计划

## 建议验证

- `uv run pytest`
- `./scripts/check-mainline.sh`

## 交接给收尾阶段

- 若用户认可 V3 目标与实现状态，再讨论是否把主线架构文档同步回 `docs/OpenZyme架构设计.md`
