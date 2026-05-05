## Context

现有仓库已经有三个面向执行层的 MCP 服务：

- `mcp-preprocess`：本地预处理
- `mcp-hpc-tool-contracts`：领域工具编译层
- `mcp-hpc-runner`：SSH / Slurm 执行层

但 Claude Code 风格体验依赖的并不只是“能调工具”，还依赖一个长期上下文层：项目配置、当前 episode、设计约束、决策记录、run 索引、候选摘要、实验反馈与归档产物都必须落到稳定的结构化状态上。仓库中的架构文档已经为 `mcp-project-memory` 定义了职责边界和建议资源 URI，但当前没有任何实现，也没有把这些对象收敛为一个可测试的 MCP 服务。

这次变更的目标是定义一个最小但可落地的 `mcp-project-memory` MVP：它不承担完整 Host 编排，不负责 UI，也不引入数据库，而是先把“状态真源 + 稳定 MCP 边界”定下来，为后续 CLI、Web Host 和 `mcp-structure-workbench` 提供同一个读写入口。

## Goals / Non-Goals

**Goals:**
- 新增一个本地 Python MCP(stdio) 服务 `apps/mcp-project-memory`
- 基于官方 MCP Python SDK 实现 `tools` 和 `resources` 暴露层，而不是继续手写协议分发
- 提供稳定的 `enzyme://` resources，用于读取项目、episode、run、candidate 和 experiment 相关对象
- 提供最小 mutation tools，用于记录决策、更新 episode 状态、确认计划、保存结构标注、导入实验结果和归档 episode
- 让资源 URI 与文件系统布局一一映射，保证状态可恢复、可审计、可脱离 Host 单独测试
- 为后续 Web Host / CLI / MCP App 复用打下统一契约

**Non-Goals:**
- 不实现完整的 Web Chat Host、CLI 交互层或多 Agent 编排器
- 不引入数据库、消息队列或远程存储；MVP 仅使用本地文件系统
- 不实现多用户协作、细粒度权限系统或分布式并发协调
- 不在本次变更中定义所有上层业务 schema，只先覆盖当前架构文档要求的最小对象集合

## Decisions

### 1. 采用文件系统驱动的项目工作区，而不是数据库

**决策**：`mcp-project-memory` 以本地项目工作区作为唯一持久化后端。每个 `project_id` 映射到一个工作区根目录，目录形态与现有架构文档保持一致，至少包含：

```text
<project_root>/
  enzyme.yaml
  episodes/
    <episode_id>/
      goal.md
      state.json
      plan.yaml
      annotations.json
      runs/
      artifacts/
      manifest.json
```

**理由**：
- 当前仓库所有 MCP 服务都以本地进程 + 本地文件为主，文件系统方案与现状一致
- 后续 CLI、Web Host、批处理脚本都可以直接复用同一批文件，而不需要额外数据库接入层
- 归档、diff、回滚、手工排障和测试夹具都更容易

**备选方案**：
- 使用 SQLite / PostgreSQL：能提供更强事务能力，但会显著增加配置、迁移和测试复杂度；当前阶段收益不足
- 由 Host 自己维护状态、不单独做 memory server：会导致状态边界不稳定，结构标注、实验反馈和工具执行索引无法跨入口复用

### 2. 资源 URI 与工作区文件做稳定映射

**决策**：MVP 至少支持以下 `enzyme://` resources，并要求 URI 到文件路径的映射可预测：

- `enzyme://project/{project_id}/config`
- `enzyme://project/{project_id}/episodes`
- `enzyme://project/{project_id}/episode/{episode_id}/goal`
- `enzyme://project/{project_id}/episode/{episode_id}/state`
- `enzyme://project/{project_id}/episode/{episode_id}/plan`
- `enzyme://project/{project_id}/episode/{episode_id}/annotations`
- `enzyme://run/{run_id}/manifest`
- `enzyme://candidate/{candidate_id}/summary`
- `enzyme://experiment/{experiment_id}/result`

**理由**：
- 这些 URI 已经在架构文档中出现，先把最小集合落地可避免后续接口漂移
- 资源读取是 Host、CLI 和结构标注 UI 的基础能力，必须优先稳定
- URI 与文件路径一一映射，便于实现 `resources/list` / `resources/read` 与测试夹具

**备选方案**：
- 仅支持 tools，不暴露 resources：会让 Host 仍然需要直接读文件，破坏 MCP 边界
- 暂时只做 project / episode state，忽略 run/candidate/experiment：会导致实验反馈链路和产物追踪缺失

### 3. 写操作通过显式 mutation tools 完成，禁止任意路径写入

**决策**：MVP 工具集合限定为显式状态变更操作，不提供“写任意文件”能力。初始工具包括：

- `record_decision`
- `update_episode_state`
- `confirm_plan`
- `save_structure_annotations`
- `import_experiment_results`
- `archive_episode`

每个工具都只接受结构化参数，并且只能写入对应项目工作区中的受控文件。

**理由**：
- 结构化工具比自由文件写入更容易验证 schema、记录审计信息和编写回归测试
- `mcp-project-memory` 的职责是状态真源，而不是通用文件编辑器
- 这组工具已经覆盖架构文档中最关键的写路径，足够支撑 MVP

**备选方案**：
- 暴露一个通用 `write_resource`：实现简单，但极易导致状态漂移和 schema 失控
- 把所有写操作都推迟到 Host：会让 `mcp-project-memory` 退化成只读层，无法承担状态真源角色

### 4. 决策日志和实验反馈采用追加式记录，episode 状态采用快照式覆盖

**决策**：
- `state.json`、`plan.yaml`、`annotations.json` 采用“最新快照”模型，由写入工具整体更新
- `decision_log`、`experiment_feedback` 采用追加式记录，每次写入都生成稳定 id、时间戳和引用关系
- `manifest.json` 作为 episode 归档后的综合可复现索引

**理由**：
- 快照对象适合被 Host 和 UI 直接读取当前值
- 决策与实验反馈天然需要审计和追溯，追加式结构更合理
- 归档时可以从快照和日志组合生成稳定 manifest

**备选方案**：
- 所有对象都做事件溯源：过度设计，当前实现和调试成本过高
- 所有对象都只做最新覆盖：会丢失关键审计信息，不适合回溯 decision / feedback 来源

### 5. 服务边界采用 MCP Python SDK，而不是手写 JSON-RPC

**决策**：`mcp-project-memory` 使用官方 MCP Python SDK 的 server API 实现，直接以 SDK 提供的 `tool` / `resource` 注册能力暴露服务；业务逻辑仍保留在独立的 `store.py`、`models.py` 等模块中，不把持久化逻辑写进 SDK 装饰器本身。

实现边界上，SDK 只负责：

- MCP 生命周期与 stdio 传输
- `resources/list` / `resources/read` 的注册与派发
- `tools/list` / `tools/call` 的注册与派发

而以下内容仍由仓库内代码负责：

- 项目工作区解析
- 文件系统存储与原子写入
- schema 校验与引用关系维护
- 审计日志与 manifest 组装

**理由**：
- `mcp-project-memory` 是第一个 resource-heavy 服务，SDK 对资源和工具的声明式注册更合适
- 减少手写协议样板代码，让实现聚焦在状态模型和存储边界
- 后续如果需要支持更多 MCP 能力，SDK 路径比自维护 JSON-RPC 更稳妥

**备选方案**：
- 延续现有手写 JSON-RPC 2.0 over stdio：短期可行，但会重复实现 SDK 已经提供的生命周期和注册逻辑，尤其在 resources 较多时维护成本更高

## Risks / Trade-offs

- **[状态 schema 过早僵化]** → 先只定义 MVP 所需对象；对 `state.json` 中的扩展字段保留前向兼容空间
- **[文件系统并发写入冲突]** → MVP 先按单 Host / 单写者模型设计；实现时至少使用原子写入和显式锁文件或替换策略
- **[URI 到路径映射带来路径穿越风险]** → 只允许访问配置过的项目根目录下受控文件，所有 path/URI 参数必须做规范化和边界检查
- **[run/candidate/experiment 引用关系不一致]** → `import_experiment_results` 和 `archive_episode` 必须同时更新索引文件，测试中覆盖交叉引用

## Migration Plan

1. 新建 `apps/mcp-project-memory/`，加入 workspace，并提供 `pyproject.toml`、CLI 和 server 骨架
2. 接入官方 MCP Python SDK，并固定到稳定版本线，而不是跟随预发布主线
3. 实现工作区配置、URI 解析、数据模型与文件存储层
4. 基于 SDK 注册 `resources`，覆盖项目、episode、run、candidate、experiment 资源
5. 基于 SDK 注册 6 个 mutation tools，并补充 schema 校验、原子写入和索引更新
6. 用夹具项目目录补齐单元测试 / 集成测试，验证资源读取、状态写入、归档与安全边界
7. 更新 README 或服务文档，说明 SDK 依赖、目录布局、工具入参与本地启动方式

**Rollback**：删除 `apps/mcp-project-memory` 及其 workspace 配置；由于状态落在独立项目工作区中，不影响现有 `mcp-hpc-*` 与 `mcp-preprocess` 服务。

## Open Questions

- MCP Python SDK 版本应固定到哪个稳定发布版本？建议使用 `v1.x` 对应发布版本，不跟随 `main` 分支的预发布变更。
- `run_id`、`candidate_id`、`experiment_id` 是否由 `mcp-project-memory` 生成，还是由上游 Host / runner 提供？MVP 可以先要求调用方传入稳定 id。
- `archive_episode` 是否需要冻结后拒绝进一步写入，还是仅打上 `archived` 标记？建议 MVP 先标记归档并保留只读校验。
- `candidate summary` 与 `experiment result` 的最小 schema 是否需要现在定死，还是先以“必填元数据 + payload”形式保持弹性？建议先保留弹性字段，但固定主键与引用字段。
