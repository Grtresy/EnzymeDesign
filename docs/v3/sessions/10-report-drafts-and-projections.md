# Session 10: Report Drafts And Projections

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

构建 `report_draft` 工作面与统一 workspace projection，使 research、execution、artifact、report draft、report 可以对外形成稳定工作区视图。

## 参考

- `docs/v3/02-control-plane.md`
- `docs/v3/04-public-interfaces.md`

## 本轮允许改动

- report draft contracts
- projection loaders
- host-facing workspace assembly

## 本轮禁止事项

- 不改产品 UI
- 不把 projection 绑定到内部 graph state 细节

## 完成产物

- report draft model
- report draft tool surface
- unified workspace projection
- activity feed / summary projection
- named workspace sections aligned with public interface contract

补充约束：

- 本轮默认不引入 reporting engine
- report teammate 直接围绕 `report_draft` 组织总结、修订与发布前准备
- final `report` 作为 `report_draft` 的发布结果进入 workspace，而不是 engine invocation 的默认副产物

## 验收标准

- UI / CLI 不必理解 internal engines
- workspace snapshot 可以完整表达当前 session 状态
- projection section names 与 `/v3` 公共接口保持一致
- report draft / report / artifact / run / task / approval 能统一渲染

## 建议验证

- `uv run pytest -m "not integration" apps/openzyme-host-api packages/openzyme-core packages/openzyme-engines`

## 交接给下一轮

- Session 11 在稳定 projection 上实现 `/v3` API、CLI、UI
