# Session 05: Host API Events Projection

## 目标

调整 Host API 与事件投影：`post_message`、`task.delegate`、`protocol.send` 只排队 wakeup；scheduler 产生 `signal.queued/claimed/completed/failed`、`agent.woken/idle/blocked/failed`。用户 projection 不暴露 raw queue internals，debug/event 面保留诊断信息。

## 前置阅读

- `docs/v3/04-public-interfaces.md`
- `docs/v3/05-agent-runtime.md`
- `docs/v3/harness-complexity-audit.md`
- `apps/openzyme-host-api/src/openzyme_host_api/v3_service.py`
- `packages/openzyme-core/src/openzyme_core/projections.py`

## 修改范围

- Host API service behavior
- runtime event emission
- workspace projection/debug projection boundaries
- API tests

## 执行步骤

1. 确认 user message、delegation、protocol send 不隐式运行 teammate。
2. 让 explicit `runtime/drain` 负责 bounded teammate turn。
3. 为 signal lifecycle 记录 diagnostic events。
4. 保持默认 workspace projection 展示 teammate 可理解状态，而非 raw queue counters。
5. 在 public interface docs 中明确 debug/event 面可保留 queue internals。

## 验证命令

- `uv run pytest apps/openzyme-host-api/tests/test_api.py`
- `uv run pytest packages/openzyme-core/tests/test_projections.py`
- `cd apps/openzyme-web-ui && npm test`

## 完成标准

- `post_message` 不隐式 drain teammate。
- `protocol.send` 返回 wakeup queued/sync unsupported 语义。
- raw signal details 只作为 diagnostic/debug 信息使用。
