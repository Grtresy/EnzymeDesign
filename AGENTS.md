# Repository Guidelines

## 项目结构与模块组织

本仓库是基于 `uv` 的 Python monorepo。应用入口放在 `apps/`，共享库放在 `packages/`。Python 子项目统一采用 `src/` 布局，并在各自目录下维护 `tests/`。`apps/openzyme-web-ui` 是独立的 Node 前端工作区。

- `apps/openzyme-host-api`：FastAPI Host API，包含当前 V3 `/v3` 产品接口
- `apps/openzyme-host-cli`：Thin CLI Client
- `apps/openzyme-web-ui`：浏览器工作区 UI
- `apps/mcp-hpc-runner`：SSH/Slurm/HPC runner 执行边界
- `packages/openzyme-domain`：V3 control-plane 领域对象与状态枚举
- `packages/openzyme-core`：V3 harness、task board、lane、protocol、projection、agent runtime、scheduler、docs/report tools
- `packages/openzyme-engines`：capability engines，尤其是 execution pipeline、sandbox supervision 与 engine tool 注册
- `packages/openzyme-pipeline`：受控 execution pipeline sandbox 内 SDK
- `packages/openzyme-research`、`packages/preprocess-backend`：research provider 与 preprocess 能力
- `packages/openzyme-runtime`、`packages/openzyme-tools`、`packages/openzyme-execution`：共享 runtime seams、tool adapters 与 runner adapters；不得承载新的顶层产品真状态
- `docs/`：架构与开发文档；V3 稳定文档在 `docs/v3/`
- `openspec/`：规格文档与变更工件

## 构建、测试与开发命令

除非子项目 README 另有说明，默认在仓库根目录执行。

- `uv sync`：创建或更新工作区虚拟环境
- `./scripts/check-mainline.sh`：主线快速验证，包含 `ruff check apps packages`、非 live/非 integration Python tests、前端 `npm test` 与 `npm run build`
- `uv run pytest`：运行 `apps/` 和 `packages/` 下全部 pytest
- `uv run pytest -m "not integration"`：跳过依赖真实外部集成的测试
- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py packages/openzyme-core/tests/test_protocols.py`：V3 runtime signal / scheduler / protocol focused 回归
- `uv run pytest apps/openzyme-host-api/tests/test_api.py -k v3`：V3 Host API focused 回归
- `uv run python -m openzyme_host_api.evals`：运行 V3 本地 workflow eval
- `uv --project apps/openzyme-host-cli run openzyme --help`：查看 CLI 入口与命令
- `cd apps/openzyme-web-ui && npm test && npm run build`：运行前端测试与构建
- `uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml`：启动 HPC Runner

涉及 HPC 流程时，先复制 `apps/mcp-hpc-runner/config/hpc_runner.example.toml` 为 `hpc_runner.toml`。

Pytest markers 中的 live gate 需要显式配置与 opt-in：`live_llm`、`live_tavily`、`live_hpc`、`live_e2e`、`seeded_live_smoke`、`quality_eval`。`live_e2e` 是外部配置/依赖证明，不要把它单独说成单消息完整报告生产路径已经产品完成；`seeded_live_smoke` 是辅助回归，不是 cutover proof。

## 代码风格与命名规范

统一使用 Python `>=3.12`。遵循现有代码风格：4 空格缩进、显式类型标注、结构化数据优先使用 `dataclass` 或 Pydantic、模块职责保持单一。文件、函数、变量使用 `snake_case`，类名使用 `PascalCase`，包名应与 `src/<package_name>` 目录保持一致。

优先使用包内绝对导入；FastAPI 路由层和 CLI 入口保持轻量，核心逻辑下沉到 runtime、service、harness 或 engine 模块。V3 control-plane 状态应使用结构化领域对象、repository 与 projection，不要只写入 prompt、浏览器状态或临时 artifact 文件树。

## 测试规范

统一使用 `pytest`。测试文件命名为 `test_*.py`，放在对应项目的 `tests/` 目录下。依赖真实外部系统的测试使用 `@pytest.mark.integration` 及相应 live marker，耗时较长的测试使用 `@pytest.mark.slow`。任何行为变更都应补充单元测试；涉及工作流、接口、状态持久化、runtime signal、approval、execution pipeline 或 workspace projection 的改动，应在对应 app/package 附近添加回归测试。

## V3 架构工作规则

当前主线架构入口是 `docs/OpenZyme架构设计.md`。涉及 V3 harness、runtime、protocol、scheduler、Host API、execution 或 workspace projection 时，必须同时参考 `docs/v3/README.md` 指向的稳定文档和当前代码实现。推荐先读：

- `docs/v3/00-harness-doctrine.md`
- `docs/v3/01-target-architecture.md`
- `docs/v3/02-control-plane.md`
- `docs/v3/03-capability-engines.md`
- `docs/v3/04-public-interfaces.md`
- `docs/v3/05-agent-runtime.md`
- `docs/v3/06-top-level-llm-loop.md`
- `docs/v3/execution-pipeline-docs/README.md`，当改动涉及 execution pipeline / HPC SDK / sandbox 时
- `docs/v3/harness-complexity-audit.md`，当改动涉及 harness/runtime/protocol 边界时

V3 默认产品语义是 `session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain`。LangGraph / LangChain 可以作为 capability engine 或局部实现工具存在，但不能成为顶层产品真状态。

## V3 实施守则

- `POST /v3/sessions/{session_id}/messages` 是用户到 master 的入口，不应隐式执行 bounded teammate runtime drain
- `POST /v3/sessions/{session_id}/runtime/drain` 是显式 scheduler/runtime command；teammate work 通过 durable `AgentRuntimeSignal`、claim lease 和 bounded turn 推进
- `task.delegate` 是产品-facing delegation tool；真实 delegation 写路径是 `ProtocolService.delegate()`
- `protocol.send` 只投递 inbox message 并排队 wakeup signal，不同步运行 recipient
- `auto_enqueue_ready_tasks` 默认关闭，仅用于显式 operator/debug/recovery
- task 业务终态必须由 agent 显式 `task.finish` 或已文档化机械迁移写入；`task.update` 只编辑普通字段和非终态，runtime idle、max steps、tool result 或 protocol message 不自动代表 task completed
- 不新增隐藏 fallback：provider/runtime 异常显式失败，tool 参数错误返回 LLM 可读 tool error，不能静默改写用户意图、重开 blocked action 或默认选择“能跑”的替代 plan
- execution teammate 不直接调用 runner、SSH、Slurm 或 runner config；它提交 `execution.pipeline.*`，通过受控 sandbox 内 `openzyme_pipeline` SDK 间接请求 Host supervisor
- runner/HPC 不得使用 Host 本地 artifact path；输入必须经 artifact catalog 授权并 staging，输出必须来自 declared `expected_outputs`
- reporter/report 验收要检查 task board、delegation、inbox、runtime drain、workspace `report_drafts` / `reports` 和 events，不能只看 tool 注册

## 协作与表述规范

面向用户的计划、诊断、实施说明、验证结果、提交说明，以及项目文档，默认使用准确、通顺、自然的中文。仅代码标识、schema id、命令、接口路径、固定状态名、需逐字引用的原始错误文本，以及无法安全翻译的专有名词保留英文；普通概念不作无必要的中英文拼接。首次出现且确有必要时，可用“中文释义（英文关键词）”建立对应关系，后文沿用中文。

## 提交与 Pull Request 规范

近期提交历史以简短的 Conventional Commit 风格为主，如 `feat:`、`feat(scope):`。提交信息使用祈使句，必要时加作用域，例如：`fix(mcp-project-memory): reject stale workflow tokens`。

PR 应说明影响的 app/package、列出已执行的验证命令，并注明配置变更或运行风险。修改 `apps/openzyme-web-ui` 时附上界面截图；修改 MCP/HPC 行为时附上示例命令、请求参数或关键输出。修改 V3 架构、runtime、protocol、execution 或 report 行为时，应说明已对照的 `docs/v3/` 文档与新增/更新的回归测试。

## 架构与变更说明

架构设计的当前入口参考 `docs/OpenZyme架构设计.md`，具体 V3 细则参考 `docs/v3/README.md` 指向的稳定文档，并以当前代码实现作为事实校验。若发现实现、主架构文档和 V3 稳定文档存在偏离，不要静默选择其中一个覆盖其他来源；应先核对真实代码路径与验收证据，再同步修正文档或实现。若用户明确要求进行架构层面的变更，则在修改具体实现时同步更新 `docs/OpenZyme架构设计.md` 及相关 `docs/v3/` 文档，确保架构文档与项目实际设计保持一致。

*在openzyme开发的时候谨记一点：agent 应保留策略自由；harness 要把世界的真实约束忠实、结构化、低摩擦地呈现出来。*
