## Why

OpenZyme 当前会把不少可观察、可修复的 tool/harness 异常直接提升为 agent turn 或 runtime 失败，导致 agent 尚未看到真实错误就失去修复、改道或明确拒绝的机会。生产级 harness 应 fail closed 地保护真实约束，同时把失败结构化交还给仍存活的 agent；只有 agent 本身无法运行时，Host 才应以系统身份报告诊断，而不能伪造 agent 决策。

## What Changes

- 增加 canonical、可公开投影的 failure observation，区分 validation、tool、provider、controlled-effect、harness、runtime 与 system failure，并携带确定事实、可重试边界、错误码和安全诊断。
- ordinary tool/engine failures 默认成为 LLM 可读的失败结果与 durable recovery wakeup，不再自动终止 agent turn；未知 external effect、fencing、权限或一致性失败仍 fail closed。
- 允许 agent 在看到完整失败事实后继续修复、选择替代策略、请求帮助，或通过现有 `task.finish(status="blocked"|"failed")` 明确说“不”；Harness 不替 agent 写业务终态。
- agent runtime 无法继续时，由 Host 以 system diagnostic / `runtime_attention` 暴露原因、规则化可能原因和证据引用，保持 task 非终态，禁止冒充 agent 回复或隐式 fallback。
- 保留 bounded provider retry，但仅允许预声明、同一 logical operation 且 effect 安全的内部 retry；禁止隐藏重放、静默改写参数或自动开启新 attempt。

## Capabilities

### New Capabilities

- `agent-failure-recovery-and-refusal`: 结构化失败观察、agent 恢复回路、显式拒绝和 Host 系统诊断语义。

### Modified Capabilities

- `runtime-continuation`: durable runtime signal 必须能携带 source-bound failure/recovery context，并保持 signal/turn failure 与 task 业务终态分离。
- `controlled-operation-execution`: controlled operation 的失败、effect certainty 和 retry eligibility 必须作为 agent 可消费事实交付，且不能由 runtime 自动推导 task 终态。

## Impact

- 影响 `packages/openzyme-runtime` 的 tool result/error envelope，`packages/openzyme-core` 的 harness、agent runtime、scheduler、protocol、repositories 与 workspace projection。
- 影响 `packages/openzyme-domain` 的 runtime signal / failure observation 领域对象，以及 Host API、CLI、Web UI 的安全诊断呈现。
- 需要数据库迁移、focused runtime regression、Host API/UI tests，以及 `docs/OpenZyme架构设计.md` 和相关 `docs/v3/` 稳定合同同步。
