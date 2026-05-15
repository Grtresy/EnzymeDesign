# Session 04: Provider Tool Limits

## 目标

引入统一 limiter：agent/session/global 并发、LLM provider 并发、research provider 并发、execution/HPC 提交并发。异步优先；同步 SDK 只能通过受控 adapter 包在 limiter 内运行。

## 前置阅读

- `docs/v3/03-capability-engines.md`
- `docs/v3/05-agent-runtime.md`
- `packages/openzyme-runtime/src/openzyme_runtime/ai.py`
- `packages/openzyme-research/src/openzyme_research/adapters.py`
- `packages/openzyme-engines/src/openzyme_engines/deep_research.py`

## 修改范围

- runtime limiter abstraction
- provider/tool adapter integration points
- limiter tests
- capability docs

## 执行步骤

1. 定义 async limiter 和 sync adapter limiter。
2. 提供 named registry，默认覆盖 `global`、`session`、`agent`、`llm_provider`、`research_provider`、`execution_provider`。
3. 为同步阻塞 SDK 提供受控 `to_thread` 包装路径。
4. 用 mock 并发测试证明 10 个 provider 调用不会超过配置上限。
5. 在 capability docs 中写明线程池不是 quota 或 agent concurrency 模型。

## 验证命令

- `uv run pytest packages/openzyme-runtime/tests/test_limits.py`
- `uv run pytest packages/openzyme-research/tests/test_adapters.py`
- `uv run pytest packages/openzyme-engines/tests/test_deep_research.py`

## 完成标准

- limiter 可按名称复用。
- async 和同步阻塞调用均能受同一类并发策略约束。
- docs 明确 provider/tool 调用必须经过 limiter。
