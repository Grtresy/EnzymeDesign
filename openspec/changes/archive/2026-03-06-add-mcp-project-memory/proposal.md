## Why

当前仓库已经有 `mcp-hpc-runner`、`mcp-hpc-tool-contracts` 和 `mcp-preprocess`，但仍缺少一个统一的项目状态真源。Host、CLI、结构标注工作台和后续实验反馈流程都需要读取并更新同一份 `Project / Episode / Run / Artifact / Manifest` 上下文；如果继续依赖零散文件和自由文本约定，后续能力将无法稳定编排、恢复和审计。

## What Changes

- **新增** `apps/mcp-project-memory`：基于 MCP Python SDK 的本地 Python MCP(stdio) 服务，负责暴露项目状态与工件资源
- **新增** 稳定的 `enzyme://` resources：覆盖项目配置、episode 目标/状态/计划、结构标注、run manifest、candidate 摘要和实验结果
- **新增** 状态写入 tools：至少支持记录决策、更新 episode 状态、确认计划、保存结构标注、导入实验结果、归档 episode
- **新增** MCP Python SDK 依赖与服务封装：使用官方 SDK 的 `tools` / `resources` 能力替代手写 JSON-RPC 分发
- **新增** 文件系统驱动的存储约定：使 `mcp-project-memory` 与现有 `project/episodes/...` 目录布局一致，便于未来 CLI 和 Web Host 复用
- **新增** 面向测试的 schema 与持久化约束：保证资源读取、状态变更、审计记录和归档结果可验证

## Capabilities

### New Capabilities

- `mcp-project-memory`: 提供 Claude Code 风格工作流所需的项目状态与工件资源层，统一管理长期上下文、结构化资源读取和状态写入工具

### Modified Capabilities

## Impact

- `apps/`：新增 `mcp-project-memory` 服务及对应测试
- 依赖管理：新增 MCP Python SDK 依赖，并固定到稳定版本线
- 项目工作区布局：需要明确 `enzyme.yaml`、`episodes/`, `runs/`, `artifacts/`, `manifest.json` 等文件的最小约定
- 未来 Host / CLI / `mcp-structure-workbench`：可直接复用该服务暴露的 `enzyme://` resources 和 mutation tools，而不再自行维护状态副本
