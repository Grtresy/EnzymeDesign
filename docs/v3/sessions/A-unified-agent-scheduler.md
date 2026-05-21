# Session A: Unified Agent Scheduler

## Goal

将 V3 agent team 统一到同一套 scheduler 模型中：master agent 与 teammate agent 都是 resident agent member，所有 agent loop 都只能由 scheduler claim wakeup signal 后启动。

这不是只把 teammate 异步化。目标是移除两套 runtime 语义：

- 用户消息只持久化消息并排队 `agent:master` wakeup。
- teammate task completed / failed / protocol reply 只排队 `agent:master` wakeup。
- approval resolve 只排队相关 agent wakeup。
- REST handler 不直接运行 master loop 或 teammate loop。
- 当前没有 FastAPI background worker 时，`/runtime/drain` 是显式 manual scheduler command；它仍必须走 scheduler claim path，不能绕过 scheduler 直接调用 master / teammate loop。Session B 完成后它再退回 debug / operator / manual 工具。

## Design Constraints

- `agent:master` 是 session 内默认 resident agent member，与 `agent:researcher`、`agent:executor`、`agent:reporter` 同属一个 agent team。
- master 与 teammate 的差异是职责和 tool surface，不是 runtime 种类。
- scheduler 是唯一正常 runtime 入口；Host API 只负责 control-plane mutation 和 signal enqueue。
- master loop、teammate loop 都必须有 bounded turn、trace、status projection 与 failure record。
- teammate 结果不得直接写用户 chat；必须唤醒 master，由 master 基于 restore context 决定是否回复用户。

## Implementation Tasks

- [x] 1. 建模默认 master member
   - session 创建时确保存在 `agent:master`。
   - master member 记录 role、status、last_active、current wakeup reason。
   - workspace `delegation.agents` / event projection 能展示 master 与 teammate 的 queued / working / idle / failed 状态。

- [x] 2. 改造用户消息入口
   - `post_message()` 只持久化 user message、必要 inbox envelope 与 control-plane event。
   - `post_message()` 创建 `agent:master` 的 wakeup signal。
   - `post_message()` 不直接调用 `run_agent_harness_loop()`，也不通过 service helper 同步执行 master response turn。

- [x] 3. 改造 teammate-to-master 唤醒
   - teammate `task.update(completed|failed|blocked)`、`protocol.send` 给 master、report publish、engine/artifact 变化，只创建 master wakeup signal。
   - terminal teammate outcome 不再触发 Host service 内部 master response turn。
   - master 从 task board、protocol thread、artifacts、report draft/report 与 agent trace 中恢复上下文。

- [x] 4. 统一 scheduler claim path
   - scheduler claim 到 `agent:master` signal 时运行 top-level master loop。
   - scheduler claim 到 teammate signal 时运行对应 teammate loop。
   - signal completion / failure 走 repository `complete()` / `fail()` 语义，记录 `attempt_count` 与 `last_error`。

- [x] 5. 恢复上下文
   - master restore context 至少包含最新用户消息、user/master conversation、pending approvals、task board、teammate protocol threads、workspace artifacts、engine invocations、report drafts/reports、agent statuses。
   - teammate restore context 保持 role-scoped focus：task/lane/correlation、unread inbox、protocol thread、relevant workspace evidence。

## Acceptance Criteria

- `post_message()` 不直接运行 master loop。
- master loop 只能由 scheduler claim `agent:master` wakeup signal 后启动。
- teammate 结果不会直接写入 user chat；它们只更新 canonical state / protocol，并唤醒 master。
- approval resolve 不直接 drain runtime，只排队相关 agent wakeup。
- `/runtime/drain` 只通过 scheduler claim path 推进 pending signals；当前无 background worker 时，产品/测试需显式调用它。
- 文档和代码都不再把 master 与 teammate 描述为两套 runtime。

## Verification

- 文档检查：不应出现把 teammate terminal outcome 描述为 service 直接启动 master response turn 的旧表述；若提到产品自动推进，必须明确那属于 Session B background worker，当前实现仍依赖显式 `/runtime/drain`。
- 调度器重点测试：`uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py`。
- Host API 重点测试：`uv run pytest apps/openzyme-host-api/tests/test_api.py`。
- 主线非 live：`uv run pytest -m "not integration"`。
