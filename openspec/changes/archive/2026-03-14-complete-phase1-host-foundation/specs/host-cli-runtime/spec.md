## MODIFIED Requirements

### Requirement: Host runtime exposes reusable application services for multiple host surfaces
The system MUST 为项目加载、episode 生命周期管理、agent workflow 启动与恢复、设计契约修订、working plan 修订、受控工具执行、人类反馈提交、运行查找、报告实体化以及 capability discovery 暴露类型化的应用服务操作，以便 CLI 和 Web Host 界面复用相同的编排语义。

这些共享 runtime 服务必须操作规范工作区状态，并且必须可以在不解析 CLI stdout 或调用 shell 命令作为集成边界的情况下调用。

在 capability discovery 方面，这些服务至少必须支持：

- 读取当前对 agent 可见的 capability summaries
- 按 `capability_id` 或等价 handle inspect 单个 capability 的 detail contract
- 为当前决策窗口解析或限制可见的详细 contract 集合
- 读取 capability inspect 与具体 tool 选择之间的关联审计信息

#### 场景：Web Host inspect 了某个 capability 后 CLI 仍能看到同一轮的选择上下文
- **WHEN** Web Host 通过共享 runtime 为当前 episode inspect 了某个 capability 的 detail contract
- **THEN** 后续 CLI 调用可以读取同一 episode 的 capability inspect 记录和关联决策上下文
- **THEN** 两个宿主界面观察到的是同一个共享 runtime 生成的 discovery 状态，而不是各自私有维护的 tool 可见集

### Requirement: Host runtime uses project memory as the canonical state source
Host runtime MUST 通过 `mcp-project-memory` 数据契约持久化和读取 episode 目标、agent working state、decision trace、append-only workflow audit、feedback log、运行清单和报告元数据，而不是维护单独的 host 拥有状态模型。

CLI 和 Web Chat Host 都不得在规范项目工作区之外维护 agent state、feedback、runs、workflow audit 或报告状态的特定于界面的副本。

#### 场景：agent workflow 中断后可在宿主界面间恢复
- **WHEN** 一个 episode 的 agent workflow 在 Web Chat Host 中停在待审批状态
- **THEN** 该待审批状态、相关 decision trace 和 workflow audit 事件被持久化在规范 episode 资源中
- **THEN** CLI 随后读取同一 episode 时可以恢复相同的 workflow 中断点并继续推进

## ADDED Requirements

### Requirement: Host runtime routes agent-selectable MCP access through a normalized capability gateway
Host runtime MUST 通过统一的 capability gateway 访问 agent-selectable MCP capabilities，而不是要求上层 workflow 直接依赖具体的底层导入路径、server transport 或 provider-specific 调用方式。

The gateway MUST support at least:

- listing capability summaries for agent planning
- inspecting one capability detail contract
- resolving a selected action to the correct backend execution path
- returning normalized execution results that preserve run lineage and artifact references

The gateway MAY use in-process adapters, embedded services, or MCP clients internally, but its contract MUST remain stable to the runtime and host surfaces.

#### Scenario: Runtime can switch backend integration strategy without changing the planning contract
- **WHEN** a capability is backed by an in-process adapter in one environment and an MCP client in another
- **THEN** host planning and host surfaces still consume the same capability summary, inspect, and execution service contract
- **THEN** runtime does not require a different planning or UI code path for each backend transport

### Requirement: Canonical state services are defined by contract, not by mandatory deployment topology
Host runtime MUST treat canonical state services such as project memory as MCP-style service boundaries without requiring them to always run as separately deployed peer processes.

This requirement MUST ensure that:

- runtime code depends on a stable contract for reading and mutating canonical state
- an in-process adapter and a real MCP server transport are both valid implementations of that contract
- host surfaces do not gain permission to bypass the contract and manipulate workspace files directly

#### Scenario: Project memory stays contract-stable across in-process and MCP-server implementations
- **WHEN** project memory is provided by an embedded adapter in one environment and by an MCP server in another
- **THEN** Host runtime still uses the same canonical read/write contract
- **THEN** neither CLI nor Web Host needs a transport-specific integration path

### Requirement: Host runtime records execution and observation as explicit workflow transitions
Host runtime MUST persist the lifecycle of selected-action execution as explicit workflow transitions instead of relying only on state snapshot mutations and run manifests.

At minimum, runtime MUST record:

- action execution started
- action execution finished
- observation recorded
- the link among action id, run id, manifest path, and resulting observation id

These transitions MUST be written to the canonical workflow audit path together with the corresponding snapshot updates.

#### Scenario: A completed tool action is traceable through canonical runtime transitions
- **WHEN** runtime executes an approved or otherwise executable action
- **THEN** runtime writes both the canonical snapshot updates and explicit execution-transition audit events
- **THEN** later readers can trace the observation and manifest lineage directly from runtime transitions rather than inferring them from partial state changes
