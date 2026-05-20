# Session B: Background Runtime Service

## Goal

Host API 启动后，单进程后台 runtime service 自动推进所有 pending agent signal。用户、Web UI、CLI 不需要调用 `/runtime/drain` 才能让 master 或 teammate 开始工作。

第一版仍是单进程 Host 内 scheduler，不引入 Redis、多进程 worker 或分布式队列。

## Product Semantics

- 用户发消息后，后台 scheduler 自动 claim `agent:master` wakeup。
- master delegate teammate 后，后台 scheduler 自动 claim teammate wakeup。
- teammate 完成 task、回复 protocol 或发布 report 后，只排队 master wakeup，后台 scheduler 自动恢复 master。
- approval resolve 后，只排队相关 agent wakeup，后台 scheduler 自动恢复对应 agent。
- `/runtime/drain` 是 debug / operator / manual drain；它不得成为产品路径或测试伪装路径。

## Implementation Tasks

- [ ] 1. FastAPI lifespan
   - 在 V3 Host API lifespan 中启动 background runtime worker。
   - shutdown 时发出 stop signal，等待当前 bounded turn 完成或按超时优雅退出。
   - 测试环境可配置禁用后台 worker，避免 deterministic unit tests 被后台并发扰动。

- [ ] 2. Scheduler worker loop
   - 持续扫描 / claim pending 或 expired-lease signal。
   - 支持 `agent:master` 与 teammate signal。
   - 每个 claimed signal 只运行一个 bounded turn。
   - 空队列时使用短 sleep/backoff，不 busy spin。

- [ ] 3. Lease and retry
   - claim 必须写入 `claimed_by`、`claim_expires_at` 并递增 `attempt_count`。
   - 成功走 `complete()`。
   - 程序/provider 异常默认走 `fail()`，记录 `last_error`。
   - retryable failure 只能按明确 policy 释放回 pending；不得吞异常伪造完成。
   - lease 过期后允许其他 worker reclaim。

- [ ] 4. Concurrency and provider limits
   - 保留 global / session / agent / provider limiter。
   - master 与 teammate turn 都进入统一 limiter。
   - 没有 LLM 配置或 model factory 不可用时，background worker 不 claim LLM-bound signal；应将缺失配置暴露为诊断状态，而不是把 signal 标成业务完成。

- [ ] 5. Debug drain
   - `/runtime/drain` 内部仍必须通过 scheduler claim lease。
   - drain 可限制 `max_signals` / `max_steps_per_agent`，用于 tests、operators、local diagnosis。
   - drain 不允许绕过后台 scheduler 的语义，不允许直接调用 master 或 teammate loop。

## Acceptance Criteria

- 用户发消息后，不调用 `/runtime/drain`，master 也会自动处理。
- master delegate teammate 后，teammate 自动开始工作。
- teammate 完成后，master 自动被唤醒。
- approval resolve 后，对应 agent 自动恢复。
- 没有重复 claim、绕过 lease、REST handler 同步执行 agent loop 的路径。
- 没有 LLM 配置时不会 claim 并启动失败的 LLM turn。

## Verification

- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py`
- `uv run pytest -m "not integration"`
- live LLM / Tavily / HPC 配置齐全时，使用真实产品路径验证无需 `/runtime/drain` 的后台推进。

