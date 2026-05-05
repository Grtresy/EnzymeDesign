## Context

仓库当前已经有三块关键底层能力：

- `mcp-hpc-tool-contracts`：领域工具入口和 `RunSpec` 编译层
- `mcp-hpc-runner`：SSH / Slurm 执行层
- `mcp-project-memory`：项目状态与工件真源

但这些能力仍然是分散的服务与库，没有一个统一的 Host 入口把项目初始化、episode 生命周期、计划确认、step 执行、状态回写和报告整理组织成终端可用的闭环。当前 change 的目标不是做完整产品 Host，而是先落一个最小 orchestration host：能闭环、能复用、不过度产品化。

## Goals / Non-Goals

**Goals:**
- 新增一个本地 Host CLI/runtime，提供 `enzyme` 命令入口
- 打通项目初始化、episode 创建、计划确认/导入、step 执行、状态查看和报告生成的最小闭环
- 使用 `mcp-project-memory` 兼容的数据契约作为状态真源
- 通过 `mcp-hpc-tool-contracts` 触发计划 step 执行，并把 run lineage 回写到项目工作区
- 为后续其它 Host 入口复用同一 runtime 留出稳定边界

**Non-Goals:**
- 不实现 Web Chat Host、浏览器 UI 或完整产品体验层
- 不在本次变更中实现 LLM 驱动的 chat 对话、自动计划生成或多 Agent 编排
- 不实现 `mcp-structure-workbench`、文献检索、实验反馈高级闭环或复杂权限系统
- 不引入新的远程服务编排层、消息队列或数据库

## Decisions

### 1. 新增独立 Python app `apps/enzyme-host-cli`

**决策**：Host CLI/runtime 作为新的 Python workspace app 落在 `apps/enzyme-host-cli`，提供 `enzyme` 可执行入口。

**理由**：
- 当前仓库所有可执行能力都以 Python app 形式存在，结构一致
- 便于复用现有 `uv` workspace、测试和发布方式
- Host runtime 是产品层入口，不应继续塞进已有底层服务中

**备选方案**：
- 直接把 CLI 混入 `mcp-project-memory`：会让状态服务和用户入口耦合
- 先做 Node/TUI：与现有 Python 能力脱节，增加一次技术栈切换

### 2. CLI 与 runtime 逻辑分层，命令层保持轻量

**决策**：CLI 只负责参数解析、工作目录定位和用户可读输出；项目初始化、episode 管理、计划确认、执行编排、报告生成都下沉到独立 runtime 服务模块。

建议内部拆分为：

- `workspace.py`：项目目录和 `cli_state.json` 管理
- `memory_client.py`：对 `mcp-project-memory` 数据契约的读写封装
- `plan_runtime.py`：计划加载、step 选择、`--resume` 决策
- `execution.py`：调用 `mcp-hpc-tool-contracts` 并处理 run 结果
- `reporting.py`：聚合 episode 摘要与报告文件

**理由**：
- CLI 命令面会继续扩张，先把可测试业务逻辑与终端 I/O 分开
- 后续其它 Host 入口可以直接复用 runtime 层，而不是重写编排逻辑

**备选方案**：
- 所有命令直接写在 `cli.py`：初期快，但会迅速失控且难测试

### 3. MVP 优先采用本地进程内适配器，而不是管理多个 MCP stdio 子进程

**决策**：MVP 的 Host runtime 优先通过进程内 Python 适配器调用现有 app 的业务模块与客户端封装，而不是在 CLI 内部管理 `mcp-project-memory` / `mcp-hpc-tool-contracts` 的 stdio MCP 子进程生命周期。

但 runtime 仍然必须遵守现有服务的数据契约和调用语义：

- 状态读写必须复用 `mcp-project-memory` 的 canonical workspace 约定
- step 执行必须通过 `mcp-hpc-tool-contracts` 的 adapter/run 编译与调用逻辑

**理由**：
- 当前目标是先打通 CLI 闭环，不是再实现一个 Host 级 MCP client manager
- 进程内适配器更容易做稳定单元测试，也更容易隔离 HPC 依赖
- 将来需要完整 MCP transport 时，可以在 client 层替换实现而不改命令语义

**备选方案**：
- 直接通过 stdio MCP 和各服务通信：边界更纯，但会显著增加进程管理、握手、错误恢复和测试复杂度

### 4. MVP 命令面只覆盖闭环必需能力

**决策**：本次 change 只承诺最小命令面：

- `enzyme init`
- `enzyme new-episode`
- `enzyme plan confirm` / `enzyme plan import`
- `enzyme run`
- `enzyme status`
- `enzyme logs`
- `enzyme report`

不扩展交互式 chat、复杂配置编辑、导出打包、富展示或项目级诊断命令。

**理由**：
- 这组命令已经足够覆盖“创建项目 -> 创建 episode -> 确认计划 -> 执行 -> 查看结果 -> 生成摘要”的闭环
- 再加更多命令会让当前 change 变成产品设计，而不是编排 runtime 落地

**备选方案**：
- 同时实现完整 CLI 面：范围过大，且会把大量精力花在 UX/命令设计而不是工作流闭环

### 5. 当前 episode 与执行恢复状态写入 `.enzyme/cli_state.json` 和 canonical episode state

**决策**：
- `.enzyme/cli_state.json` 记录当前项目上下文、当前 episode id 和最近访问的 run
- episode 的结构化进度、已确认计划、step 状态、run 引用写入 canonical episode state 和 run manifest
- `--resume` 基于 canonical episode state 与 run manifests 判断下一步，而不是只依赖 CLI 临时状态

**理由**：
- CLI 本地状态适合存放“当前光标”一类会话信息
- 真正需要可恢复和可审计的执行进度，必须进入 canonical episode 资源

**备选方案**：
- 把所有恢复信息只放在 `cli_state.json`：一旦切换入口或丢失本地状态就无法恢复

### 6. 报告和日志能力先做轻量可审计输出，而不是富产品体验

**决策**：
- `enzyme report` 的 MVP 先生成一个结构化 Markdown 报告，汇总 episode goal、confirmed plan、recorded runs、关键 artifact 路径和当前状态
- `enzyme logs <run_id>` 的 MVP 先输出本地 manifest 中记录的日志路径、run 状态和必要元数据；若日志已被抓取，可直接展示定位信息

不要求富叙事总结、彩色 TUI、流式日志 UI 或报告模板系统。

**理由**：
- 报告需要先建立稳定的数据链路，生成质量可以后续再增强
- 无额外 UI/LLM 依赖时更容易测试，也更适合作为 CLI MVP 的交付物

**备选方案**：
- 一开始就做自然语言报告或复杂日志体验：范围过大，且与当前 change 的闭环目标无关

## Risks / Trade-offs

- **[进程内适配器偏离 MCP 部署形态]** → 通过独立 client 层隔离调用方式，并增加契约测试保证行为与服务语义一致
- **[计划 schema 在 CLI 与 memory 之间漂移]** → 统一通过 canonical plan/state 文件和夹具测试约束输入输出
- **[HPC 运行依赖难以在本地 CI 稳定验证]** → CLI 测试默认使用 fake runner / mocked tool-contract client，远端集成测试保持 opt-in
- **[`--resume` 判断错误导致重复提交]** → 只以 persisted step status 和 run manifests 为依据，并在提交前做显式 completed 检查
- **[命令面过快膨胀]** → 只承诺闭环所需命令，新增命令必须能直接支撑当前工作流

## Migration Plan

1. 新建 `apps/enzyme-host-cli/`，加入 workspace，并提供 `pyproject.toml` 与 `enzyme` 入口
2. 实现 workspace 和 `cli_state.json` 管理，落地 `enzyme init` / `enzyme new-episode`
3. 封装 memory/tool-contracts 调用适配器，先打通 canonical goal/plan/state 读写
4. 实现 `enzyme run` 的 plan step 执行、`--step` / `--resume` 选择和 run manifest 回写
5. 实现 `status` / `logs` / `report`，补齐夹具测试和 README

**Rollback**：删除 `apps/enzyme-host-cli` 和 workspace 依赖；项目工作区数据仍保留在 canonical layout 中，不影响现有底层服务。

## Open Questions

- `enzyme plan` 的 MVP 是否只支持 `confirm/import` 已有计划文件，还是要同时提供规则驱动的 plan draft 生成？
- `enzyme logs <run_id>` 是否只展示本地 manifest 与已抓取日志路径，还是要补一个统一的日志抓取适配层？
