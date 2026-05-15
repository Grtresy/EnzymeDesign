# Session 03: Async Scheduler Worker

## 目标

实现 `AgentRuntimeScheduler`，提供 `run_once()`、bounded `run_forever()`、graceful shutdown、session/global max concurrency，并让 `runtime/drain` 走 scheduler claim 语义。

## 前置阅读

- `docs/v3/01-target-architecture.md`
- `docs/v3/04-public-interfaces.md`
- `docs/v3/05-agent-runtime.md`
- `packages/openzyme-core/src/openzyme_core/agent_runtime.py`
- `apps/openzyme-host-api/src/openzyme_host_api/v3_service.py`

## 修改范围

- 新增 scheduler module
- Host API `runtime/drain`
- scheduler tests
- existing protocol/runtime tests

## 执行步骤

1. 新增 scheduler class，使用 repository claim lease 获取 work。
2. `run_once()` bounded claim `max_signals`，无 `model_factory` 时不 claim。
3. `run_forever()` 支持 poll interval、stop event、max ticks 和 shutdown request。
4. 用 session/global concurrency 限制单 tick 可 claim 数。
5. 保留 `runtime/drain` 为显式 debug/test/manual drain 入口，但内部调用 scheduler。

## 验证命令

- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py`
- `uv run pytest packages/openzyme-core/tests/test_protocols.py`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py`

## 完成标准

- `runtime/drain` 不绕过 claim lease。
- 没有 LLM `model_factory` 时 pending signal 保持未 claim。
- scheduler 可被有界运行和优雅停止。
