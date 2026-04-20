# Session 11: V3 API CLI UI

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, skill loading, context compaction, approval protocols, and canonical control-plane projections. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

提供 `/v3` API、Thin CLI、conversation-first Web workspace，使用户真正通过 V3 control plane 交互。

## 参考

- `docs/v3/04-public-interfaces.md`

## 本轮允许改动

- `apps/openzyme-host-api`
- `apps/openzyme-host-cli`
- `apps/openzyme-web-ui`
- 必要的 read model / stream contracts

## 本轮禁止事项

- 不回退为 phase-centric UI
- 不要求前端读取 raw engine state
- 不把 task / lane 管理后台做成 Web UI 的默认用户体验

## 完成产物

- `/v3` API
- CLI workspace 视图
- Web conversation timeline
- approval cards
- 只读 workspace inspector，包括 task board、lane board、delegation、artifacts、reports、capabilities
- v3 streaming events

## 验收标准

- 用户能通过对话消息继续 harness loop
- 当 harness 需要人工确认时，UI 在对话流中展示 approval card，并能 approve / reject 后恢复 loop
- 用户能查看 session、task board、lane board、approvals、delegation、artifacts、reports、capabilities，但默认不需要手工创建或编排 task / lane
- UI 刷新后可以只靠 workspace projection 恢复

## 建议验证

- `uv run pytest -m "not integration" apps/openzyme-host-api apps/openzyme-host-cli`
- `cd apps/openzyme-web-ui && npm test && npm run build`

## 交接给下一轮

- Session 12 做 cutover、evals、回滚和迁移收口
