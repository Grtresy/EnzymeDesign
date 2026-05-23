# Session C: Product E2E And Failure Semantics

## Goal

用真实产品路径验证异步 agent team，并清理会掩盖失败的 fallback / test-only 行为。full live E2E 必须证明 master 与 teammate 都由 scheduler 异步启动，而不是依赖 REST handler 或 `/runtime/drain` 偷偷推进。

## Product E2E Path

Full live E2E 必须使用真实用户路径：

1. 创建 V3 session。
2. 发送用户消息。
3. 必要时通过 approval endpoint approve / reject。
4. 轮询 `workspace` / `events` / debug evidence。
5. 不调用 `/runtime/drain` 推进流程。

E2E 证据至少包含：

- master wakeup queued / claimed / completed / failed。
- teammate wakeup queued / claimed / completed / failed。
- master 与 teammate queued / working / idle / failed 状态投影。
- task count、roles、capability keys。
- approval waiting / resolved 状态。
- execution invocation、run、artifact、report draft/report 证据。
- final report 已出现在 workspace projection。

Seeded smoke 可以保留为回归测试，但不能冒充 full live E2E。当前 full live E2E 已改为
FastAPI lifespan 启动的 background runtime 产品路径；测试只轮询 workspace / events /
debug runtime，并通过 approval endpoint 解决 pending approval。

## Failure Semantics

- runtime signal failure 统一走 repository `fail()` 语义，记录 `last_error` 和 `attempt_count`。
- teammate runtime `failed`、`idle`、`max_steps_exceeded` 不能自动把业务 task 标成 completed / failed。
- 业务 task 终态只能由 agent 显式 `task.update` 写入，或由文档化的窄机械迁移写入。
- `invalid_tool_arguments`：`KeyError` / `TypeError` / `ValueError` 这类参数、枚举、引用错误可以作为 LLM 可读 tool observation 返回，指导 agent 修正参数。
- `controlled_domain_failure`：真实业务执行已经发生且返回结构化失败，例如 pipeline code 非零退出、SDK/HPC operation 返回 failed、artifact contract violation。可以持久化 failed invocation，ToolResult 必须 `ok=false`，业务 task 只能由 agent 显式 `task.update failed/blocked`。
- `runtime_exception`：provider/model/repository/Host 程序、sandbox preflight、sandbox runner crash、Host finalization、runner infrastructure exception 必须传播到 harness/scheduler，使 signal `failed` 并记录 `last_error`；不得转成 failed dossier、假 report、completed task 或 completed signal。
- `POST /v3/sessions/{session_id}/messages` 不提供 `max_steps` 字段，不控制后台 turn budget；background worker 使用 `OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT`，manual `/runtime/drain` 使用 `max_steps_per_agent`。
- 不允许为了通过测试合成 planner/execution 进展、默认替用户选择 runnable tool、重开 blocked action 或伪造 report。

## Workspace And Events

Workspace / events 必须能清楚投影：

- `agent:master` queued / working / idle / failed。
- teammate queued / working / idle / failed。
- approval waiting / resolved。
- signal queued / claimed / completed / failed。
- task status 与 delegation thread。
- engine invocation、execution artifacts、report draft/report。

低层 signal lifecycle 可以留在 debug/event 面，但 full E2E evidence 必须能读取到这些诊断事件。

## Implementation Tasks

- [x] 1. 改造 live E2E
   - 移除测试中用于推进产品流程的 `/runtime/drain` 调用。
   - 使用 polling 等待 workspace/events 达到目标状态。
   - 缺少 live LLM / Tavily / HPC 配置时报告 gate prerequisite missing，不算通过。

- [x] 2. 补强 projection
   - workspace 中展示 master 与 teammate runtime 状态。
   - events 中保留 signal lifecycle。
   - report、artifact、execution evidence 与 task/delegation correlation 可回链。

- [x] 3. 收敛 failure
   - scheduler worker 捕获异常后写 `fail()`，不伪造完成。
   - provider/tool runtime 异常默认传播为 signal failure。
   - 清理剩余 planner/execution/report fallback。

- [x] 4. 防 test-only path
   - Host service、tests、evals 不得通过 hidden synchronous master / teammate loop 让路径看起来成功。
   - `/runtime/drain` 测试只能验证 debug/manual drain 本身，不可作为产品 E2E 成功证据。

## Acceptance Criteria

- full live E2E 在真实 LLM + Tavily + HPC 配置下跑通。
- full live E2E 不调用 `/runtime/drain` 推进流程。
- E2E 证据包含 wakeup lifecycle、task、roles、capability keys、execution artifacts、report。
- seeded smoke 明确标注为辅助回归，不作为 full live gate。
- eval 和 full live E2E 使用 background runtime 产品路径；不调用 `/runtime/drain` 推进流程。
- `/runtime/drain` 保留为 debug / operator / manual 工具，且内部只走 scheduler claim path。
- 无 Host service hidden synchronous master / teammate loop。
- 无会掩盖失败的语义 fallback。

## Verification

- `uv run pytest -m "not integration"`
- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py`
- `uv run pytest -m "integration and live_llm" apps/openzyme-host-api/tests -k v3`
- `uv run pytest -m "integration and live_tavily" apps/openzyme-host-api/tests packages/openzyme-research/tests`
- `uv run pytest -m "integration and live_hpc" apps/mcp-hpc-runner/tests apps/openzyme-host-api/tests`
- `uv run pytest -m "integration and live_e2e" apps/openzyme-host-api/tests`
- 如果 workspace/UI 投影改变：`cd apps/openzyme-web-ui && npm test && npm run build`
