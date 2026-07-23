## 1. Failure domain and persistence

- [x] 1.1 Add typed failure taxonomy, immutable observation model, stable likely-cause mapping, and bounded public projection
- [x] 1.2 Add migration, repository methods, idempotency constraints, and CoreRepositories wiring for failure observations

## 2. Harness and runtime recovery

- [x] 2.1 Extend ToolResult and ToolRouter so ordinary exceptions become sanitized LLM-readable failures while boundary-fatal exceptions still escape fail closed
- [x] 2.2 Persist tool/harness/runtime failure observations and keep ordinary failed tool results inside the existing bounded agent loop
- [x] 2.3 Add exact idempotent recovery signals and source-bound recovery briefs for post-turn execution/continuation failures
- [x] 2.4 Project system-attributed runtime diagnostics without fabricating agent messages or task terminal state
- [x] 2.5 Update agent instructions to make continue/help/blocked/failed choices explicit and preserve same-operation retry limits

## 3. Verification and documentation

- [x] 3.1 Add domain/repository/tool-router/harness/runtime regression tests for repair, refusal, provider outage, unknown effect, fencing, deduplication, and task-status independence
- [x] 3.2 Update Host API/workspace/UI contracts and tests for safe failure facts, likely causes, agent hypotheses, and runtime attention
- [x] 3.3 Sync `docs/OpenZyme架构设计.md` and relevant `docs/v3/` doctrine/runtime/interface documents
- [x] 3.4 Run focused non-live tests, ruff, diff check, and OpenSpec strict validation
