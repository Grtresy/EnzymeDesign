# Session 11: V3 API CLI UI

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

提供 `/v3` API、Thin CLI、conversation-first Web workspace，使用户真正通过 V3 control plane 与 master agent 交互，并让顶层 `/v3` conversation ingress 可以由真实 LLM master-agent loop 驱动。

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
- top-level `LlmConversationDriver`
- CLI workspace 视图
- Web conversation timeline
- approval cards
- 只读 workspace inspector，包括 task board、lane board、delegation、artifacts、report drafts、reports、capabilities
- v3 streaming events
- canonical `workspace.conversation`
- canonical `workspace.agent_traces`
- built-in V3 tool schema/catalog for top-level tool-calling

语义补充：

- `workspace.conversation` 展示用户与 master agent 的对话
- `workspace.agent_traces` 展示 master / teammate 每次 LLM response 的文本输出与工具调用请求，来源于 `engine_documents(document_kind="llm_trace_step")`
- `task board + delegation + lane board + capabilities` 展示 OpenZyme 内部执行组织
- `artifacts` / `report drafts` / `reports` / `capabilities` 共同展示 agent team 的共享工作面，而不是只展示最终交付物
- Web UI 默认表现为“一个对外负责人 + 一个内部执行团队”，而不是多个平级 agent 直接面向用户
- Web UI 主对话区组合渲染 `workspace.conversation` 的 user message 与 `workspace.agent_traces.harness` 的 master trace；无 trace 的旧 workspace 回退展示 assistant conversation message
- 带 `tool_calls` 的中间 LLM response content 只通过 `workspace.agent_traces` 展示，不写入 `workspace.conversation`
- Web UI 左侧 active session 的 `Team` 下嵌套 teammate 名字；点击 teammate 后中间区域显示该 teammate 的只读 trace，包含角色种子提示、LLM 文本与工具调用请求，不显示 tool result，也不允许直接向 teammate 发送消息

## 验收标准

- 用户能通过对话消息继续 harness loop
- 顶层 LLM 至少可以完成一次真实 tool call 再继续输出 assistant 消息
- 当 harness 需要人工确认时，UI 在对话流中展示 approval card，并能 approve / reject 后恢复 loop
- 用户能查看 session、task board、lane board、approvals、delegation、artifacts、report drafts、reports、capabilities，但默认不需要手工创建或编排 task / lane
- UI 刷新后可以只靠 workspace projection 恢复，包括 conversation timeline
- SSE replay 包含 `llm.response.created`，浏览器可增量更新 `workspace.agent_traces` 且重复事件不重复渲染
- SSE follow 在 `POST /v3/sessions/{session_id}/messages` 尚未返回时，也应能收到每次 LLM response 产生的 `llm.response.created`
- 至少有一条主路径符合 `user -> master agent -> task -> teammate loop -> report draft/capability -> delivery`

## 建议验证

- `uv run pytest -m "not integration" apps/openzyme-host-api apps/openzyme-host-cli`
- `cd apps/openzyme-web-ui && npm test && npm run build`
- `uv run pytest -m "integration and live_llm" apps/openzyme-host-api/tests -k v3`

## 交接给下一轮

- Session 12 做 cutover、evals、回滚和迁移收口
