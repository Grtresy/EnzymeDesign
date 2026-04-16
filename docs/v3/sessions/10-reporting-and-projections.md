# Session 10: Reporting And Projections

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

构建 reporting engine 与统一 workspace projection，使 research、execution、artifact、report 可以对外形成稳定工作区视图。

## 参考

- `docs/v3/02-control-plane.md`
- `docs/v3/04-public-interfaces.md`

## 本轮允许改动

- report generation contracts
- projection loaders
- host-facing workspace assembly

## 本轮禁止事项

- 不改产品 UI
- 不把 projection 绑定到内部 graph state 细节

## 完成产物

- reporting engine
- unified workspace projection
- activity feed / summary projection
- named workspace sections aligned with public interface contract

## 验收标准

- UI / CLI 不必理解 internal engines
- workspace snapshot 可以完整表达当前 session 状态
- projection section names 与 `/v3` 公共接口保持一致
- report / artifact / run / task / approval 能统一渲染

## 建议验证

- `uv run pytest -m "not integration" apps/openzyme-host-api packages/openzyme-core packages/openzyme-engines`

## 交接给下一轮

- Session 11 在稳定 projection 上实现 `/v3` API、CLI、UI
