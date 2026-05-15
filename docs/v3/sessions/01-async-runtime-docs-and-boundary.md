# Session 01: Async Runtime Docs And Boundary

## 目标

明确 V3 异步 runtime 边界：agent 不是常驻进程，worker/scheduler 负责 claim wakeup signal 并运行 bounded turn。第一版以单进程 async scheduler 为目标，多进程 worker、外部队列和分布式 limiter 作为后续演进。

## 前置阅读

- `docs/v3/README.md`
- `docs/v3/00-harness-doctrine.md`
- `docs/v3/01-target-architecture.md`
- `docs/v3/05-agent-runtime.md`
- `docs/v3/harness-complexity-audit.md`

## 修改范围

- `docs/v3/README.md`
- `docs/v3/01-target-architecture.md`
- `docs/v3/05-agent-runtime.md`
- 不修改 `docs/OpenZyme架构设计.md`，除非用户单独确认

## 执行步骤

1. 在目标架构中写明单进程 scheduler 是第一阶段目标。
2. 在 runtime 文档中区分 resident identity 与非驻留 LLM loop。
3. 写清 scheduler/worker 只处理 claim、bounded turn、idle/shutdown，不承担业务完成判断。
4. 标出未来多进程、Redis/external queue、shared limiter 的演进点。

## 验证命令

- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py`
- `uv run pytest packages/openzyme-core/tests/test_protocols.py`

## 完成标准

- 文档明确 agent identity/inbox/task/memory 持久化，LLM loop 不常驻。
- `runtime/drain` 被描述为 scheduler command，而不是直接同步调用 teammate。
- 文档未把多进程或外部队列列为第一版阻塞项。
