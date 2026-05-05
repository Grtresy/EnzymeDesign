## Why

仓库已经具备 `mcp-hpc-tool-contracts`、`mcp-hpc-runner` 和 `mcp-project-memory` 这些底层能力，但还没有一个最小 Host 把它们组织成可执行的闭环。现在需要的不是完整产品入口，而是一个足够小、能跑通工作流、且未来可被其它 Host 入口复用的 CLI/runtime 基座。

## What Changes

- 新增一个最小 Host CLI/runtime，提供 `enzyme` 命令作为本地工作流入口
- 新增项目初始化与当前 episode 管理能力，统一创建和维护 `enzyme.yaml`、`.enzyme/cli_state.json` 及 episode 目录骨架
- 新增基于 `mcp-project-memory` 契约的状态读写编排层，使 goal、state、plan、manifest 等数据保持单一真源
- 新增计划执行 runtime，把已确认的计划 step 依次调用到 `mcp-hpc-tool-contracts`，并把 run 结果和执行状态回写到项目工作区
- 新增最小 inspection 表面，支持 `status`、`logs` 和 `report` 这类闭环必需能力，而不是完整产品化命令集
- 新增端到端测试夹具，覆盖从 `enzyme init` 到 `enzyme run` / `enzyme report` 的最小闭环

## Capabilities

### New Capabilities
- `host-cli-runtime`: 提供最小可闭环、可复用的本地 Host CLI/runtime，用统一入口管理项目、episode、计划执行与状态回写

### Modified Capabilities

## Impact

- `apps/`：新增 Host CLI/runtime 项目及对应测试
- 依赖关系：Host CLI/runtime 需要编排 `mcp-project-memory`、`mcp-hpc-tool-contracts` 和 `mcp-hpc-runner`
- 项目工作区：正式落地 `enzyme.yaml`、`.enzyme/cli_state.json`、`episodes/<id>/...` 的 CLI 写入约定
- 上层入口：先提供最小 CLI 闭环，为后续其它 Host 入口复用同一 runtime 打基础
