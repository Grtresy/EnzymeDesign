## Why

仓库已经具备 `mcp-preprocess`、`mcp-hpc-tool-contracts`、`mcp-hpc-runner` 和 `mcp-project-memory`，也有一个可用于测试闭环的最小 CLI，但还没有面向日常使用的主入口。根据当前架构路线，MVP 需要一个 Web Chat Host 把项目上下文、计划确认、工具执行、长任务状态和报告查看组织成一个连续工作流，同时把现有 runtime 从“只够 CLI 跑测试”提升成可被 Web 与 CLI 共享的应用服务层。

## What Changes

- 新增一个最小 `Web Chat Host`，提供基于浏览器的会话入口，承载项目/episode 上下文、计划确认、执行触发、状态查看和报告入口
- 提炼并加固现有 Host runtime，使 Web 和 CLI 共用同一套项目定位、episode 生命周期、计划执行和状态回写语义
- 为 Host runtime 增加 mixed-plan 执行路由，支持本地预处理 step 直接调用 `mcp-preprocess` 能力，HPC step 继续通过 `mcp-hpc-tool-contracts`
- 新增最小 Web API / service boundary，避免 Web 直接复用 CLI 命令解析或自行拼装底层调用
- 新增覆盖 Web Host 到 runtime 的集成测试夹具，验证“进入项目 -> 创建/切换 episode -> 确认计划 -> 运行 step -> 查看状态/报告”的最小闭环

## Capabilities

### New Capabilities

- `web-chat-host`: 提供最小浏览器 Host 入口，组织对话工作流、项目上下文、计划确认、执行与结果查看

### Modified Capabilities

- `host-cli-runtime`: 把现有 runtime 从 CLI 专用 MVP 提升为可被 Web 和 CLI 复用的共享应用服务层，并支持 mixed-plan 执行路由

## Impact

- `apps/`：新增 Web Host app，并调整 `enzyme-host-cli` 内部 runtime 分层
- Host runtime：需要抽出稳定的 service/API 边界，避免 CLI 命令层和 Web 界面层重复实现编排逻辑
- 执行编排：需要统一 `mcp-preprocess` 与 `mcp-hpc-tool-contracts` 两条执行路径的状态回写与 run 记录方式
- 测试：新增 Web 层和跨入口共享 runtime 的集成测试
- 交互入口：CLI 继续保留为调试/回归入口，Web 成为 MVP 主入口
