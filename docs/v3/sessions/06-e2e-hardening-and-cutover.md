# Session 06: E2E Hardening And Cutover

## 目标

端到端硬化：多 teammate 并发、approval resolve 唤醒、engine completion 唤醒、stale claim 恢复、provider limiter 压测、失败不误写 task 终态。同步更新 cutover checklist 和 harness complexity audit。

## 前置阅读

- `docs/v3/cutover-checklist.md`
- `docs/v3/harness-complexity-audit.md`
- `docs/v3/04-public-interfaces.md`
- `docs/v3/05-agent-runtime.md`
- `apps/openzyme-host-api/tests/test_api.py`

## 修改范围

- E2E/API regression tests
- scheduler/repository edge-case tests
- limiter stress tests
- cutover docs

## 执行步骤

1. 覆盖多 teammate pending signals 的 bounded drain。
2. 覆盖 approval resolved、engine completed、inbox unread 唤醒正确 teammate。
3. 覆盖 stale claim recovery 和 duplicate completion idempotency。
4. 压测 LLM/research provider limiter 不超过配置并发。
5. 确认 task 终态只由 `task.update` 或文档化机械迁移写入。
6. 更新 cutover checklist 和 audit 记录。

## 验证命令

- `uv run pytest -m "not integration"`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py`
- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py packages/openzyme-core/tests/test_repositories.py`
- `uv run pytest packages/openzyme-runtime/tests/test_limits.py`

## 完成标准

- V3 runtime 队列、scheduler、limiter 和 API 回归测试通过。
- 端到端路径不会因 teammate runtime failure 误写 task terminal state。
- cutover checklist 明确 runtime signal 和 limiter release gates。
