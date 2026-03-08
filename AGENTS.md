# Repository Guidelines

## 项目结构与模块组织

本仓库是基于 `uv` 的 Python monorepo。应用入口放在 `apps/`，共享库放在 `packages/`。各子项目统一采用 `src/` 布局，并在各自目录下维护 `tests/`。

- `apps/enzyme-web-host`：基于 FastAPI 的 Web Host
- `apps/enzyme-host-cli`：本地命令行 Host
- `apps/mcp-*`：MCP 服务，包括 HPC runner、preprocess、project memory 等
- `packages/enzyme-host-runtime`：Web 与 CLI 共用的运行时
- `packages/preprocess-backend`：可复用的分子预处理能力
- `docs/`：架构与开发文档
- `openspec/`：规格文档与变更工件

## 构建、测试与开发命令

除非子项目 README 另有说明，默认在仓库根目录执行。

- `uv sync`：创建或更新工作区虚拟环境
- `uv --project apps/enzyme-web-host sync --extra dev`：安装 Web Host 开发依赖
- `uv --project apps/enzyme-web-host run enzyme-web-host --project-root /path/to/project`：启动 Web Host
- `uv --project apps/enzyme-host-cli run enzyme --help`：查看 CLI 入口与命令
- `uv run pytest`：运行 `apps/` 和 `packages/` 下全部测试
- `uv run pytest -m "not integration"`：跳过依赖 HPC 环境的集成测试
- `uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml`：启动 HPC Runner

涉及 HPC 流程时，先复制 `apps/mcp-hpc-runner/config/hpc_runner.example.toml` 为 `hpc_runner.toml`。

## 代码风格与命名规范

统一使用 Python `>=3.12`。遵循现有代码风格：4 空格缩进、显式类型标注、结构化数据优先使用 `dataclass` 或 Pydantic、模块职责保持单一。文件、函数、变量使用 `snake_case`，类名使用 `PascalCase`，包名应与 `src/<package_name>` 目录保持一致。

优先使用包内绝对导入；FastAPI 路由层和 CLI 入口保持轻量，核心逻辑下沉到 runtime 或 service 模块。

## 测试规范

统一使用 `pytest`。测试文件命名为 `test_*.py`，放在对应项目的 `tests/` 目录下。依赖 HPC 环境的测试使用 `@pytest.mark.integration`，耗时较长的测试使用 `@pytest.mark.slow`。任何行为变更都应补充单元测试；涉及工作流、接口或状态持久化的改动，应在对应 app/package 附近添加回归测试。

## 提交与 Pull Request 规范

近期提交历史以简短的 Conventional Commit 风格为主，如 `feat:`、`feat(scope):`。提交信息使用祈使句，必要时加作用域，例如：`fix(mcp-project-memory): reject stale workflow tokens`。

PR 应说明影响的 app/package、列出已执行的验证命令，并注明配置变更或运行风险。修改 `apps/enzyme-web-host` 时附上界面截图；修改 MCP/HPC 行为时附上示例命令、请求参数或关键输出。

## 架构与变更说明

提出新的 OpenSpec change 前，先参考 `docs/OpenZyme架构设计.md`，确保变更目标、模块边界和职责划分与当前架构描述一致。若你对项目架构本身有调整建议，不要直接默认更新架构文档；应先询问用户是否需要同步写入 `docs/OpenZyme架构设计.md`，再进行文档修改。
