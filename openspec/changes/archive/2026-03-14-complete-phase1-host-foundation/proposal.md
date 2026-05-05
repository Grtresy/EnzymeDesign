## Why

当前仓库已经具备 Phase 1 的 MVP 骨架，但仍有几处会影响后续 Phase 正确性和返工成本的底座缺口：Host runtime 还没有统一走 MCP client 边界，capability discovery 仍停留在独立提案阶段，workflow 的 execute/observe 语义部分落在图外服务层，project memory 的审计与状态更新也还没有完全收敛为可持续扩展的规范路径。继续推进体验增强或更高阶段能力前，需要先把这些底座补齐。

与此同时，已有未实现的 `add-host-capability-discovery` change 已经提出了 summary/detail 两层能力暴露机制。本次变更将其并入更完整的 Phase 1 foundation 收尾工作，避免把协议收敛、状态真源和 capability discovery 拆成多个彼此耦合却分散的 change。

## What Changes

- 收敛 Host runtime 到 MCP server 的接入边界，让 memory、preprocess 和 HPC tool contracts 的运行路径可以通过统一的 capability / client 语义暴露，而不是继续依赖库级直连作为唯一正式集成方式。
- 明确 Phase 1 收尾追求的是 MCP 风格的稳定资源/工具契约，而不是把所有能力都强制改造成独立部署、跨进程访问的 MCP server；对 `project memory` 尤其如此。
- 引入 Host 侧 capability registry，采用 summary -> inspect -> detail contract 的发现路径，并吸收 `add-host-capability-discovery` 中已提出的能力发现设计。
- 调整 host agent planning，使 agent 默认基于 capability summaries 决策，需要时显式 inspect 单个 capability 的 detail contract，再选择具体 tool。
- 扩展 shared runtime，使 capability inspect、visible detail scope、action execution 和 observation 回灌都成为共享应用服务的一部分，并与 `active_state_version` / resume 语义对齐。
- 收敛 `mcp-project-memory` 的规范状态职责，明确 append-only decision log、workflow event audit、版本化状态更新与跨宿主共享恢复边界。
- 调整 Web Host 的可视化要求，让 capability inspect 与 workflow audit 事件先进入 trace / debug 视图，而不是新增一套独立主界面控制流。
- 用本次 consolidated change 取代未实现的 `add-host-capability-discovery` change。

## Capabilities

### New Capabilities
- `host-capability-discovery`: 定义 Host 侧 capability registry、summary/detail contract、按需 inspect、短生命周期 detail visibility 和 capability audit 事件。

### Modified Capabilities
- `host-agent-planning`: 将 agent 的工具发现路径改为先消费 capability summary，再按需 inspect detail 并选择具体 tool。
- `host-cli-runtime`: 收敛 shared runtime 的 MCP 接入边界、受控执行语义、capability inspect 服务和跨宿主共享状态读取路径。
- `mcp-project-memory`: 强化 canonical workflow state、append-only decision log、版本化恢复与 capability/workflow audit 记录。
- `web-chat-host`: 调整浏览器 Host 的 runtime 消费与可视化要求，暴露 capability inspect / workflow audit 结果并处理 stale state。

## Impact

- `packages/enzyme-host-runtime` 将新增 capability registry、normalized MCP client/service access、detail visibility scope 和更完整的 workflow event 持久化路径。
- `apps/mcp-project-memory` 需要补强 audit / decision log / workflow event 的规范存储与读取契约。
- `project memory` 的目标形态是 canonical state service with MCP-style contract；实现上允许继续使用进程内 adapter，并为将来切换到真实 MCP transport 预留空间。
- `apps/enzyme-web-host` 和 `apps/enzyme-host-cli` 会继续复用共享 runtime，但会消费新的 capability discovery、trace 和 state freshness 语义。
- `apps/mcp-preprocess`、`apps/mcp-hpc-tool-contracts` 及后续 MCP server 需要通过统一 capability metadata 或 Host override 方式接入 discovery。
- 现有 `openspec/changes/add-host-capability-discovery/` 将被本次变更吸收后移除，避免重复实现和冲突规范。
