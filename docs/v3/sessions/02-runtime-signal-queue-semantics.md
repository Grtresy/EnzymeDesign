# Session 02: Runtime Signal Queue Semantics

## 目标

补强 `AgentRuntimeSignal` 队列语义：`pending/claimed/completed/failed`、claim lease、stale claim recovery、重复 signal 去重和失败重试边界。

## 前置阅读

- `docs/v3/02-control-plane.md`
- `docs/v3/05-agent-runtime.md`
- `packages/openzyme-domain/src/openzyme_domain/control_plane.py`
- `packages/openzyme-core/src/openzyme_core/repositories.py`

## 修改范围

- `AgentRuntimeSignal` domain model
- `agent_runtime_signals` SQLite migrations
- `AgentRuntimeSignalRepository`
- repository tests

## 执行步骤

1. 为 signal 增加 `claimed_by`、`claim_expires_at`、`attempt_count`、`last_error`。
2. 增加 repository 层 `claim_next()`、`complete()`、`fail()`、`release()`。
3. 让 duplicate wakeup dedupe 覆盖未完成 signal，避免 pending/claimed 期间重复排队。
4. 覆盖 lease 过期恢复、重复完成幂等、retryable failure 和 exhausted failure。
5. 更新 control-plane 文档中的字段和状态转换。

## 验证命令

- `uv run pytest packages/openzyme-core/tests/test_migrations.py`
- `uv run pytest packages/openzyme-core/tests/test_repositories.py`

## 完成标准

- stale claimed signal 可在 lease 过期后被新 worker 重新 claim。
- 未过期 claimed signal 不会被第二个 worker claim。
- 失败重试记录 `last_error`，并在 attempt 上限后进入 `failed`。
