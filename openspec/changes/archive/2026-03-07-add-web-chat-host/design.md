## Context

仓库当前已经有一条最小可测的 Host CLI 闭环：

- `apps/enzyme-host-cli` 负责项目初始化、episode 管理、计划确认、执行与报告
- `apps/mcp-project-memory` 提供 canonical state 和 `enzyme://` 资源读写语义
- `apps/mcp-hpc-tool-contracts` 负责 HPC/domain adapter 编译与执行
- `apps/mcp-preprocess` 负责本地预处理与格式转换

但这些能力还没有被组织成日常使用的主入口。现有 CLI 更像 runtime MVP 的测试壳，主要问题不是命令面不够多，而是 runtime 还没有以“可复用的应用服务层”落地：

- Web 目前没有入口
- CLI 内部 runtime 仍然绑定在 `apps/enzyme-host-cli` 中
- 执行路径默认面向 `mcp-hpc-tool-contracts`，尚未把 preprocess step 纳入统一 mixed-plan 语义

本次 change 的目标是优先落一个最小 Web Chat Host，同时把 runtime 抽到共享层，避免后续 Web 和 CLI 各自演化出不同的编排逻辑。

## Goals / Non-Goals

**Goals:**
- 新增一个本地 Web Chat Host，作为 MVP 主入口
- 抽取共享 Host runtime，使 Web 和 CLI 共用同一套项目、episode、plan、run、report 语义
- 支持 mixed-plan 执行路由，把 preprocess step 和 HPC/domain step 纳入同一执行闭环
- 提供最小浏览器界面，用于进入项目、创建 episode、确认计划、触发执行、查看状态/运行明细/报告
- 为后续 `mcp-structure-workbench` iframe 和 richer chat/workflow UI 留出可扩展边界

**Non-Goals:**
- 不在本次 change 中实现完整多 Agent 编排、自动计划生成或复杂审批系统
- 不实现 `mcp-structure-workbench`、`mcp-bio-research` 或 MCP Apps iframe 嵌入能力本身
- 不把 CLI 打磨成完整终端产品；CLI 继续作为调试、自动化和回归入口
- 不引入独立数据库、消息队列或远程多用户部署模型

## Decisions

### 1. 把共享编排逻辑提取到 `packages/enzyme-host-runtime`

**决策**：从 `apps/enzyme-host-cli` 中抽出 workspace、memory client、plan runtime、execution、reporting 等核心逻辑，放入新的 workspace package：`packages/enzyme-host-runtime`。

CLI 和 Web 都依赖这个 package：

- `apps/enzyme-host-cli` 负责命令解析和终端输出
- `apps/enzyme-web-host` 负责 HTTP 路由、浏览器交互和页面渲染

**理由**：
- 共享 runtime 是这次 change 的真正基础设施，不能继续埋在 CLI app 里
- 这样可以避免 Web 调 CLI、解析 stdout、或复制一套 orchestration 逻辑
- 后续如果还要引入 WebSocket、审批节点或 `enzyme chat` 命令，仍然能围绕同一个 runtime 扩展

**备选方案**：
- 继续把 runtime 留在 `apps/enzyme-host-cli` 并让 Web import 它：依赖方向混乱，Web 会变成“引用 CLI internals”
- 让 Web 通过 subprocess 调 `enzyme`：短期快，但输出不稳定、测试脆弱、错误语义差

### 2. 新增 `apps/enzyme-web-host`，采用 Python-first 本地 Web app

**决策**：新增 `apps/enzyme-web-host`，使用 Python Web 框架提供本地 HTTP 服务和最小浏览器 UI；MVP 不引入额外的 Node 构建链。

建议实现形态：

- 后端：FastAPI 或等价轻量 ASGI 框架
- 前端：由该 app 提供的最小静态页面或服务端模板页面
- 运行方式：本地启动时显式指向项目根目录或工作区配置

**理由**：
- 现有仓库核心能力都在 Python 生态内，先保持一致更容易集成和测试
- MVP 重点是 Host runtime 复用和浏览器入口，不是前端工程体系建设
- 无 Node 构建链时，开发与测试成本更低，适合先做最小闭环

**备选方案**：
- 直接做独立前后端分离 SPA：产品潜力更大，但当前范围过大
- 在 CLI 内新增 `enzyme chat` 打开本地 TUI：不能满足浏览器面板和后续 iframe 扩展需求

### 3. Web Host 通过 in-process service boundary 调共享 runtime

**决策**：Web Host 的 HTTP handlers 直接调用 `enzyme-host-runtime` 提供的 typed service objects，而不是在 Web 进程里管理 `mcp-project-memory` / `mcp-hpc-tool-contracts` 的 stdio 子进程，也不是调用 CLI 命令。

建议 runtime 暴露的服务边界至少包括：

- project loading
- episode create / switch
- plan confirm / import / read
- run full plan / run step / resume
- status summary
- run detail lookup
- report materialization

**理由**：
- 共享逻辑更容易做单元测试与集成测试
- 保持与现有 CLI 的本地进程内适配策略一致，避免本次变更同时引入 transport 复杂度
- 将来即使要改成 MCP transport 或远程 API，也可以在 service/adapter 层替换

**备选方案**：
- Web handler 直接 import 底层各 app 模块并分别调用：边界松散，语义重复

### 4. Mixed-plan 执行使用统一 StepExecutor 接口和标准化 run envelope

**决策**：在共享 runtime 中引入统一的 `StepExecutor` / `ExecutionAdapter` 抽象，对 plan step 做 deterministic routing：

- preprocess 工具：`convert_format`、`smiles_to_3d`、`prepare_receptor`、`prepare_ligand`
- HPC/domain 工具：`fpocket`、`hhblits`、`chai_fold`、`colabfold`、`alphafold3`、`tunnels`、`vina`

两类执行器都输出同一类 run envelope / manifest payload，至少统一：

- `step_id`
- `tool`
- `status`
- `created_at`
- backend-specific payload
- output references

对于不产生远程 `run_id` 的 preprocess step，runtime 需要生成稳定的本地 run 标识并写入 canonical run manifest，以保证 episode state、logs、reporting 不区分来源。

**理由**：
- 如果 preprocess step 不进入统一 run 记录链，Web 和 CLI 就会看到两套执行语义
- 报告、恢复和状态面板都依赖统一的 step/run lineage

**备选方案**：
- 只让 Web 跑 HPC steps，preprocess 交给用户手工准备：会让 MVP 断成两半
- preprocess steps 不写 run manifest：`resume`、status 和 report 语义会变脆

### 5. Web Host 的项目上下文由服务端绑定，浏览器只保存轻量会话状态

**决策**：MVP 的 Web Host 服务端在启动时绑定一个项目工作区根目录；浏览器端只保存当前页面状态和轻量 UI 会话信息，不维护独立项目状态副本。

服务端负责：

- 解析项目根目录
- 读取 `.enzyme/cli_state.json`
- 读取 canonical episode state / plan / report
- 执行 runtime 操作并刷新视图模型

浏览器端负责：

- 展示 timeline / panels
- 触发表单提交和执行动作
- 轮询或刷新状态

**理由**：
- 当前仓库还是单用户、本地工作区模型，先保持简单
- 服务端绑定项目根目录后，页面逻辑和测试夹具都更直接

**备选方案**：
- 在浏览器端自行管理多项目列表和缓存：范围过大，也会引入状态漂移风险

### 6. Web UI 先实现“聊天壳 + 工作流面板”，不实现完整对话智能

**决策**：MVP 的 Web Chat Host 先实现一个 conversation-style shell 和结构化面板：

- 左侧或上方：当前 project / episode / goal / plan 概览
- 主区：活动时间线，显示用户动作、runtime 事件、run 更新
- 辅助面板：status、runs、run detail、report

“chat” 的含义在 MVP 中是连续工作上下文和事件流，而不是自动 LLM 规划。用户可通过表单、按钮或轻量命令输入触发 `new episode`、`confirm plan`、`run`、`resume` 等动作。

**理由**：
- 这样能满足“主入口 + 连续上下文 + 浏览器操作”的目标，同时避免把本次 change 扩大到对话代理系统
- 结构化动作更容易与共享 runtime 对齐和测试

**备选方案**：
- 一开始就加入模型对话和自动计划生成：价值高，但需要额外系统设计，不适合本次 change

### 7. 测试优先覆盖共享 runtime 和 Web-host happy path

**决策**：新增三层测试：

- `enzyme-host-runtime` 的单元测试：project/episode/plan/run/report 服务语义
- mixed-plan 执行测试：fake preprocess executor + fake tool-contract executor
- Web Host 集成测试：使用 HTTP test client 验证页面动作和 API 行为

不要求在默认测试中连接真实 HPC 或真实浏览器。

**理由**：
- 这次变更最容易失控的是共享 runtime 语义漂移，不是前端像素细节
- Web 层只要证明它没有复制业务逻辑，而是在正确调用 runtime，即可满足 MVP

**备选方案**：
- 只做 Web 端到端 UI 测试：覆盖重但定位差

## Risks / Trade-offs

- **[共享 runtime 提取会牵动 CLI 现有模块路径]** → 先复制并收敛接口，再把 CLI 改成薄壳，避免一次性大搬家
- **[preprocess step 没有天然远程 `run_id`]** → 为本地执行生成稳定 host-side `run_id`，并统一写入 run manifest
- **[Web UI 很快滑向完整前端产品]** → 明确只做最小浏览器壳，不引入复杂前端构建链和高级交互
- **[Web 与 CLI 语义再次分叉]** → 把所有状态变更和执行入口都下沉到 `enzyme-host-runtime`，前台只做适配
- **[mixed-plan 路由规则不清导致不可恢复]** → 显式维护 tool-to-executor 映射，并对未知工具在执行前报验证错误

## Migration Plan

1. 新建 `packages/enzyme-host-runtime/`，迁移当前 CLI 中可复用的 runtime 逻辑与测试
2. 调整 `apps/enzyme-host-cli` 依赖共享 runtime，保持现有 CLI 命令面可用
3. 在共享 runtime 中增加 mixed-plan execution routing 和标准化 local run manifest 写入
4. 新建 `apps/enzyme-web-host/`，实现项目加载、episode 操作、plan 确认、run/status/report 的最小 Web surface
5. 补齐 runtime 与 Web integration tests，并更新 README / 启动说明

**Rollback**：
- 删除 `apps/enzyme-web-host` 与 `packages/enzyme-host-runtime`
- CLI 可临时切回原有内部 runtime 模块
- canonical workspace 数据仍保留，不影响 `mcp-project-memory`、`mcp-preprocess`、`mcp-hpc-tool-contracts` 与 `mcp-hpc-runner`

## Open Questions

- Web Host 的 MVP 是否需要轮询式 run 状态刷新，还是手动刷新就足够？
- `report` 在 Web 中优先做只读预览，还是直接打开/下载生成文件即可？
- 是否在本次 change 中顺手加入 `enzyme chat` 命令来启动本地 Web Host，还是保持 Web app 独立启动入口？
