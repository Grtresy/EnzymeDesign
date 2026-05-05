# Host Runtime Capability Gateway

本文档说明 Phase 1 foundation 收尾后，Host runtime 如何接入 capability discovery、canonical project memory 和 workflow audit。

## 目标

- Host runtime 通过统一的 capability gateway 暴露 agent 可选能力，而不是让 planning 或 host surface 直接依赖具体导入路径。
- `project memory` 作为 canonical state service 存在，遵循 MCP 风格的资源/工具契约，但不要求必须是独立部署的 MCP server。
- CLI 与 Web Host 继续只消费 shared runtime 暴露的服务接口，不维护 capability visibility 或 workflow audit 的私有副本。

## Capability Discovery 路径

当前 runtime 采用 `summary -> inspect -> detail contract` 的发现路径：

1. `HostCapabilityGateway.list_summaries()` 返回当前 agent 可见的 capability summaries。
2. planning 先基于 summaries 判断是否需要某个 capability。
3. 若需要具体 schema，runtime inspect 单个 capability，并把 detail contract 绑定到当前 episode/state version 的 visibility scope。
4. inspect 事件被写入 canonical workflow audit，随后 workflow 再选择具体 tool action。

这样做的目的不是把 inspect 变成用户显式操作，而是把它作为 runtime 内部可审计 transition。CLI 和 Web Host 的主操作流仍然聚焦 workflow 控制、interrupt 和 gate。

## Capability Gateway Contract

`packages/enzyme-host-runtime/src/enzyme_host_runtime/capability.py` 提供统一 contract：

- `CapabilitySummary`: planning 默认消费的轻量摘要
- `CapabilityDetailContract`: inspect 后可见的详细工具契约
- `CapabilityVisibilityScope`: detail contract 的可见范围
- `NormalizedExecutionResult`: 不同 backend 返回结果的统一归一化视图
- `HostCapabilityGateway`: list / inspect / resolve / execute 的统一入口

当前默认 adapters：

- `mcp-preprocess`
- `mcp-hpc-tool-contracts`
- `mcp-project-memory`（默认隐藏，仅作为 canonical state service）

底层实现既可以是 in-process adapter，也可以以后换成真实 MCP client。对 runtime 而言，稳定的是 contract，不是 transport 拓扑。

在 `mcp-hpc-tool-contracts -> mcp-hpc-runner` 这条链路上，runner config 的推荐优先级是：

1. 上层显式传入 `runner_config`
2. `HPC_TOOL_CONTRACTS_RUNNER_CONFIG`
3. `HPC_RUNNER_CONFIG`

这里的环境变量回退应理解为 integration-friendly fallback：

- 它适合 Host runtime、playground 和临时自动化脚本
- 它让 Host 不需要把 `hpc_runner.toml` 一层层手工传透也能跑通
- 但它不应取代显式配置成为唯一正式配置通道

## Project Memory Contract

`ProjectMemoryService` 是 runtime 侧的 canonical state contract wrapper。它屏蔽底层 `ProjectMemoryStore` 的直接细节，让 runtime 依赖统一读写接口：

- episode state
- agent state
- feedback / approval / interrupts / session
- runs / manifests
- append-only workflow audit

这意味着：

- `project memory` 可以先以内嵌 adapter 形态运行
- 将来切到独立 `mcp-project-memory` server 时，runtime 和 host surface 不需要改调用语义
- host surface 不应该直接修改工作区状态文件

## Workflow Audit

runtime 现在把下面这些动作写入 canonical workflow audit：

- action selected
- capability inspected
- action execution started
- action execution finished
- observation recorded
- feedback recorded
- gate transitioned

这些事件与 `action_id`、`run_id`、`observation_id`、`state_version` 等稳定标识关联，方便跨 CLI / Web Host 追踪同一轮 workflow。

## Decision Trace And Decision Records

当前仓库里存在两类“决策相关记录”，它们职责不同，不应混为同一份真源：

- `decision_trace`
  - 来自 `agent_state`
  - 记录 agent workflow 内部的决策轨迹，例如 selected action、interrupt、observation summary
  - `enzyme://project/{project_id}/episode/{episode_id}/decision-log` 当前读取的是这条轨迹的 canonical episode resource 视图
- `record_decision`
  - 来自 `project memory` 的独立 append-only 写入契约
  - 适合记录宿主或外部调用方显式提交的审计决策
  - 当前写入 `decision_log.jsonl`，不等同于 agent 内部 `decision_trace`

因此在 Phase 1 foundation 范围内：

- 如果要解释 agent 为什么做出某个动作，优先看 `decision_trace` 和 `workflow audit`
- 如果要追加宿主侧的显式审计决策，使用 `record_decision`
- 后续若要合并这两条路径，应先明确统一后的 canonical resource 语义

## Host Surface 接入约束

CLI 与 Web Host 都应通过 `HostRuntime` 读取：

- capability summaries
- inspected capability detail contract
- workflow audit 摘要
- canonical agent state / pending interrupts / approval gates

不建议：

- 直接读取或拼装独立的 capability registry 副本
- 在界面层维护 workflow audit 缓存作为真源
- 绕开 runtime/project-memory contract 直接操作 episode 文件

## 后续接入新 MCP 的方式

新增 capability 时，优先补齐以下内容：

1. 在 capability gateway 中注册 summary 与 detail contract。
2. 为该 capability 提供稳定的 tool-to-capability 映射和 normalized execution result。
3. 确认该 capability 是否默认对 agent 可见，还是只通过 host/runtime 间接使用。
4. 补 capability registry 与 workflow audit 相关测试。

这样可以保证后续 `mcp-bio-research`、`mcp-structure-workbench` 等能力接入时，不再回到库级直连和界面私有状态的旧路径。
