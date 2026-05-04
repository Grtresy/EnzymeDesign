# Session 03: Harness Kernel

## Guardrail

`Agent != workflow graph. Prefer tool dispatch, task persistence, lane isolation, docs retrieval, context compaction, approval protocols, and canonical control-plane projections. Skill loading is frozen in V3 until explicitly reapproved. LangGraph is allowed inside capability engines, not as product truth.`

## 目标

实现最小 V3 `agent_harness_loop`、tool registry、event bus 与 session runtime，为 master agent / teammate-agent 模型提供系统层支撑。

## 参考

- `/home/grtresy/VSCodeRepo/learn-claude-code/docs/zh/s01-the-agent-loop.md`
- `/home/grtresy/VSCodeRepo/learn-claude-code/agents/s_full.py`

## 本轮允许改动

- `packages/openzyme-core`
- 少量新的 runtime contracts

如果旧代码还在 `openzyme-runtime` / `openzyme-tools`，允许过渡期原地改造，但本轮产物的目标归宿是 `openzyme-core`。

## 本轮禁止事项

- 不接 deep research / HPC
- 不做 UI / CLI
- 不实现复杂 phase graph 替代物

## 完成产物

- 统一 harness loop
- tool registry / dispatch layer
- session-scoped runtime context
- delegation interface / teammate seam
- 事件发射与基本状态装载

职责边界补充：

- harness kernel 负责回合驱动、状态装载、工具分发、协议等待态与恢复
- harness kernel 不负责理解用户意图，不负责代替 master agent 生成 task 内容
- delegation seam 的目的不是提供自由消息通道，而是让 master agent 能把 task 委托给 teammate agent，并为后续 teammate loop 预留稳定运行面

## 验收标准

- 不靠 phase route 也能驱动一次完整 loop
- tool use / tool result 可以回灌
- session runtime 可以恢复已有 tasks / approvals / memory
- harness loop 仍保持单一 agent loop，而不是演化成产品级 orchestration graph
- kernel 至少预留稳定的 spawn / delegate / resume seam，供后续 agent roster、team protocol 与 teammate loop 层接入
- delegation seam 应支持 `task_id` 作为默认工作归属锚点

## 建议验证

- `uv run pytest -m "not integration" packages/openzyme-core`

## 交接给下一轮

- Session 04 起在 harness kernel 上增加 task board 机制
