## Why

AOX blank-world cutover 现行 `aox_blank_world_attempt_bundle@2` 仍按 exact occurrence set 验收，并把同 attempt 中任一 failed run/operation 视为永久 NO-GO，无法表达已经确定的“过程允许试错、最终 adopted chain 仍严格验收”语义。必须让 AOX 成为 generic scientific selection/closure 的首个消费者，同时冻结 r48–r51 历史证据并在下一次编号 live attempt 前完成非 live 资格验证。

## What Changes

- **BREAKING**：新增 `aox_blank_world_attempt_bundle@3` 与 verifier `@3`，以 sealed operation universe、disposition、selected chain、materialization、closure 和 authorization envelope 验证最终证据；保留 `@2` 历史 verifier，禁止自动升级旧 bundle。
- 将 AOX live driver 从“任一失败/第二 occurrence 即拒绝”迁移为 authority/effect/quiescence 驱动的 admission：closed known failures 可处置后继续，unknown effect、未退役进程、越权或未处置事实仍拒绝。
- formal attempt 可跨多个 sandbox run 修复和继续，但 adoption/materialization 仅限同一 fresh attempt/root/scope；两个 independent positive 与 fault attempt 之间零复用。
- 增加 AOX 非 live recovery qualification，覆盖失败后修复、显式 supersession、unknown-effect fail closed、envelope exhaustion、bundle tamper 和历史 `@2` 冻结。
- 更新 Host API、workspace/UI evidence projection、操作手册与 GO checklist；r48–r51 永久保持 NO-GO，本变更不启动下一次编号 live attempt。

## Capabilities

### New Capabilities

- `aox-selected-chain-cutover`: AOX selected-chain bundle/verifier、driver admission、恢复资格测试和 cutover 证据语义。

### Modified Capabilities

- `live-attempt-supervision`: supervisor 必须校验 durable attempt authorization、effect safety 与 closure eligibility，并在父/子进程 outcome 未知时继续禁止后续 attempt。

## Impact

- 影响 `apps/openzyme-host-api` 的 AOX driver、runtime observation、evidence collector/verifier、eval/live gates 与 API projection。
- 影响 `packages/openzyme-core`/`packages/openzyme-engines` 的 AOX tool wiring 和 workspace evidence，及 `apps/openzyme-web-ui` 的 selection/closure/diagnostic 展示。
- 影响 AOX OpenSpec change、`docs/OpenZyme架构设计.md`、`docs/v3/aox-hmm-blank-world-cutover.md`、execution-pipeline 文档和 campaign runbook。
- live 外部系统、MICU ledger 与下一次编号 attempt 在本变更内保持未触发状态。
