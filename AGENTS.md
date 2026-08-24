# Repository Guidelines

## 项目结构与模块组织

本仓库是基于 `uv` 的 Python monorepo。应用入口放在 `apps/`，共享库放在 `packages/`。Python 子项目统一采用 `src/` 布局，并在各自目录下维护 `tests/`。`apps/openzyme-web-ui` 是独立的 Node 前端工作区。

- `apps/openzyme-host-api`：FastAPI Host API，包含当前 V3 `/v3` 产品接口
- `apps/openzyme-host-cli`：Thin CLI Client
- `apps/openzyme-web-ui`：浏览器工作区 UI
- `apps/mcp-hpc-runner`：SSH/Slurm/HPC runner 执行边界
- `packages/openzyme-contracts`：实现无关的公开领域合同、身份、Port 数据结构与可靠性语义；不得导入 Kernel、Adapter、Plugin 或产品实现
- `packages/openzyme-extension-spi`、`packages/openzyme-runtime-spi`：Plugin/Driver/Distribution contribution seam 与框架无关的 runtime command/outcome seam
- `packages/openzyme-kernel`：V3 canonical control plane，拥有 Session、Task、lane、agent、protocol、approval、authority、runtime signal/lease、workspace identity、workflow authority、events 与 projection 组装语义
- `packages/openzyme-store-sqlite`、`packages/openzyme-workspace-git-lfs`、`packages/openzyme-runtime-llm`、`packages/openzyme-process-podman`：被 Distribution 显式选择的 Store、Workspace、Runtime、Process Adapter；不得把机制私有表提升为产品真状态
- `packages/openzyme-research`、`packages/openzyme-reporting`、`packages/openzyme-science`、`packages/openzyme-compute`、`packages/openzyme-hpc`：通用 Plugin application/contract 边界
- `packages/openzyme-research-tavily`、`packages/openzyme-hpc-ssh`、`packages/openzyme-hpc-slurm`：外部 provider/transport Driver；安装不等于激活、资格或 authority
- `packages/openzyme-standard`：不含垂直科学产品的官方基础 Distribution，负责 exact composition、Host launcher 与非 live 产品闭环
- `packages/enzymedesign-core`、`packages/enzymedesign-*`：EnzymeDesign 产品合同、Plugin/Driver、toolpack 与 AOX executor；通用 OpenZyme 层不得反向依赖它们
- `packages/enzymedesign-distribution`：EnzymeDesign 产品 Distribution，拥有 bundle、role/workflow policy、executable Host composition 与产品级非 live 验收
- `packages/openzyme-execution-contracts`、`packages/openzyme-execution-sdk`：受控 execution sandbox 的窄合同与 SDK；不得承载 Session、Task、authority、workflow 或 workspace 顶层真状态
- `docs/`：架构与开发文档；V3 稳定文档在 `docs/v3/`
- `openspec/`：规格文档与变更工件

## 构建、测试与开发命令

除非子项目 README 另有说明，默认在仓库根目录执行。

- `uv sync`：创建或更新工作区虚拟环境
- `./scripts/check-mainline.sh`：主线快速验证，包含 `ruff check apps packages`、非 live/非 integration Python tests、前端 `npm test` 与 `npm run build`
- `uv run pytest`：运行 `apps/` 和 `packages/` 下全部 pytest
- `uv run pytest -m "not integration"`：跳过依赖真实外部集成的测试
- `uv run pytest packages/openzyme-kernel/tests/test_runtime_coordination_application.py packages/openzyme-kernel/tests/test_protocol_application.py packages/openzyme-kernel/tests/test_runtime_turns.py`：V3 runtime signal / protocol / turn focused 回归
- `uv run pytest packages/openzyme-contracts/tests packages/openzyme-runtime-spi/tests packages/openzyme-store-sqlite/tests`：合同、runtime SPI 与 SQLite owner/codec 回归
- `uv run pytest apps/openzyme-host-api/tests/test_v2_app.py packages/openzyme-standard/tests/test_standard_v2_host.py packages/enzymedesign-distribution/tests/test_distribution.py`：公开 Host 与两个 Distribution focused 回归
- `uv run python -m openzyme_host_api.evals`：运行 V3 本地 workflow eval
- `uv --project apps/openzyme-host-cli run openzyme --help`：查看 CLI 入口与命令
- `cd apps/openzyme-web-ui && npm test && npm run build`：运行前端测试与构建
- `uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml`：启动 HPC Runner

涉及 HPC 流程时，先复制 `apps/mcp-hpc-runner/config/hpc_runner.example.toml` 为 `hpc_runner.toml`。

Pytest markers 中的 live gate 需要显式配置与 opt-in：`live_llm`、`live_tavily`、`live_hpc`、`live_e2e`、`seeded_live_smoke`、`quality_eval`。`live_e2e` 是外部配置/依赖证明，不要把它单独说成单消息完整报告生产路径已经产品完成；`seeded_live_smoke` 是辅助回归，不是 cutover proof。

## 代码风格与命名规范

统一使用 Python `>=3.12`。遵循现有代码风格：4 空格缩进、显式类型标注、结构化数据优先使用 `dataclass` 或 Pydantic、模块职责保持单一。文件、函数、变量使用 `snake_case`，类名使用 `PascalCase`，包名应与 `src/<package_name>` 目录保持一致。

优先使用包内绝对导入；FastAPI 路由层和 CLI 入口保持轻量，核心逻辑下沉到 Kernel application service、Adapter mechanism、Plugin application 或 Distribution composition。V3 control-plane 状态应使用 `openzyme-contracts` closed contract、Kernel owner、ControlStore 与 projection，不要只写入 prompt、浏览器状态、Adapter 私有表或临时文件树。

## 测试规范

统一使用 `pytest`。测试文件命名为 `test_*.py`，放在对应项目的 `tests/` 目录下。依赖真实外部系统的测试使用 `@pytest.mark.integration` 及相应 live marker，耗时较长的测试使用 `@pytest.mark.slow`。任何行为变更都应补充单元测试；涉及 closed schema、owner codec、workflow authority、runtime signal/turn、approval、controlled operation、workspace provisioning/projection 或 public client 的改动，应在对应 app/package 附近添加正向、stale/fence、idempotency、restart 和 forbidden-fallback 回归。

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

V3 默认产品语义是 `session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain`。fresh Session 先进入显式异步 workspace readiness，用户消息只创建 durable request-lineage 与 wakeup，随后由显式 drain 推进 resident teammate。LangGraph / LangChain 可以作为 Plugin/Adapter 内的局部实现工具存在，但不能成为顶层产品真状态。

## V3 实施守则

- `POST /v3/sessions/{session_id}/messages` 是用户到 master 的入口，不应隐式执行 bounded teammate runtime drain
- `POST /v3/sessions/{session_id}/runtime/drain` 只接纳显式 durable scheduler/runtime command 并返回 HTTP `202`；请求线程不得 claim command/signal、取得 Session lease 或调用 Provider/Adapter，独立 bounded worker 后续推进，客户端只用 exact command-status GET 轮询
- Session bootstrap 必须原子创建 exact repository pin、`WorkspaceGeneration` reservation、pending exact-generation authority lease 与 durable provisioning intent；HTTP 不等待 clone/volume/provider，公开 readiness 只使用 `provisioning | ready | blocked`
- 两个官方 Distribution 的可执行 launcher 在开放 Host surface 前都必须做只读 product preflight：核对实际 file-backed SQLite provider 与 exact 主库绝对路径，以及 active release、bundle/catalog、完整 Adapter runtime set、workflow registry、全角色 exposure policy 和 workspace binding；不得硬编码 `file_backed=true`、只相信配置/Factory 自报路径或在漂移时改用 in-memory/Standard fallback
- provisioning worker 只调用 Distribution 选定的 workspace Adapter；success 原子激活 runtime binding/lease，`no_effect`、`dispatch_in_doubt` 与 terminal failure 均显式 blocked，不自动 retry、切换 Adapter 或补造 workspace
- `dispatch_in_doubt` recovery 必须创建独立、可认领、可结算的 `WorkspaceProvisioningReconciliation` occurrence，并永久保留原 blocked intent、dispatch receipt 与 failure；只观察同一原请求，禁止原地改写或重新 dispatch。reconciliation 已证明 terminal failure 后，只有显式 successor command 才能创建下一 monotonic generation 与新 intent
- provisioning recovery 只通过 `POST /v3/sessions/{session_id}/workspace/provisioning/reconcile` 或 `/successor` 的 exact Session/intent digest/state-version 前置条件进入；两个入口都返回 `202` 和 exact closed admission-only result，必须陈述 adapter/external effect/runtime/Task/fallback 均未发生，不得公开 worker claim/terminal/private 字段，也不得隐式 provision、drain、创建 Task、换 Adapter 或从 CLI/UI 推断成功
- 每条 root message（包括显式空 workflow 选择）都要创建 request-lineage `WorkflowAuthorityBinding` 与 `RuntimeSignalAuthorityLink`；delegation 只能派生 selection/scope 子集，approval、continuation、protocol wakeup 沿 exact causal link 传播
- public message wire 以显式 `workflow_refs`（包括空数组）为 canonical 选择请求；`skill_keys` 只能作为互斥 compatibility alias，在 admission 时归一化且不进入 canonical authority row
- workflow authority 在 provider 前、每个 tool/delegation dispatch 前按 status/epoch/digest 重验；禁止从 raw `skill_keys`、memory、task/protocol prose、latest/all 扫描或隐式 union 恢复 authority
- runtime command 必须携带结构化、bounded、digest-bound world context，覆盖 objective、task/lane、workspace、inbox/protocol、approval/continuation、failure、workflow、capability/exposure 与 canonical transcript；prompt 只投影事实，不替 agent 选策略
- workflow resolution、workspace provisioning、runtime command 与 outcome settlement 的非空失败必须形成 exact 一一对应的公开 `FailureObservation` / 私有 `PrivateDiagnosticRecord`；业务 owner 与 pair 应在同一 fenced 事务结算，admission 前 resolver failure 只能另写诊断事务且不得产生 message/binding/inbox/signal/link，公开 API 不得序列化私有记录
- continuation settlement 只创建 durable pending intent；独立 delivery worker 原子创建下一条 pending signal 与 exact workflow authority link，该 signal 最早由下一次显式 runtime drain 执行，不得在当前 turn、`protocol.send` 或 approval resolution 中同步运行 recipient
- model tool exposure 使用 `Direct | Deferred | Hidden`：稳定协作动词和角色必需工具 Direct，long-tail Plugin tools 经 `capabilities.inspect` 显式 command-scoped 扩展；Hidden 的名称、描述和参数不得进入 provider context、inspection、transcript、CLI/UI 或公开 projection，model 只能看到可见项以及不泄露名称的 hidden count/identity digest；扩展不扩大 authority、不解除 blocker、不换 route
- `RuntimeTurnOutcome` 的 assistant/tool transcript、full outcome receipt 与 `FailureObservation` 必须在 Kernel fenced settlement 中持久化；下一 turn、CLI、UI 都读取同一 canonical transcript
- internal runtime contracts 与 public projection 必须分开：公开面只使用 `runtime_command_public@1`、`runtime_turn_command_public@1`、`runtime_turn_outcome_public@1`、`runtime_turn_outcome_receipt_public@1`、`runtime_command_outcome_summary_public@1` 和 `runtime_outcome_consumption_public@1`；不得公开 command/signal/session lease token、raw turn context/messages、raw tool request 名称/参数、嵌套 internal receipt 或私有 failure payload，只能公开 safe identity、count、digest、summary、effect facts、continuation/settlement reference 和 source digest
- `task.delegate` 是产品-facing delegation tool；真实 delegation 写路径是 `ProtocolService.delegate()`
- `protocol.send` 只投递 inbox message 并排队 wakeup signal，不同步运行 recipient
- `auto_enqueue_ready_tasks` 默认关闭，仅用于显式 operator/debug/recovery
- task 业务终态必须由 agent 显式 `task.finish` 或已文档化机械迁移写入；`task.update` 只编辑普通字段和非终态，runtime idle、max steps、tool result 或 protocol message 不自动代表 task completed
- 不新增隐藏 fallback：provider/runtime 异常显式失败，tool 参数错误返回 LLM 可读 tool error，不能静默改写用户意图、重开 blocked action 或默认选择“能跑”的替代 plan
- 跨进程、Git、runner、provider、SQLite 与外部 effect 的异常必须形成可诊断且脱敏的结构化记录：非空公开 failure 只接受 exact current `failure_observation@2`，旧 schema、未知字段或 private diagnostic 一律 fail closed；公开 facts/identities 按 allowlist 限定，至少包含稳定 error code、component、phase、关联 identity、effect certainty、mutation/fallback 事实、retry/reconcile policy、safe cause chain 与 `diagnostic_id`，不得包含 traceback、stdout/stderr、private context 或 tool request；私有记录保留完整 traceback、return code、bounded stdout/stderr 和上下文，包装异常使用 `raise ... from exc`
- execution teammate 不直接调用 runner、SSH、Slurm 或 runner config；它只通过当前 capability affordance 调用 Compute/HPC Plugin，并由受控 sandbox 内 `openzyme-execution-sdk` 间接请求 Host authority
- runner/HPC 不得使用 Host 本地路径、通用 catalog 或隐式 staging；输入必须绑定 exact workspace revision、commit/tree、Git LFS closure、clean observation 与受控 Gitless compute tree，输出由同一 opaque handle 的 observation、terminal receipt 和 owner workspace result 表达，不要求或补造 `expected_outputs`
- reporter/report 验收要检查 task board、delegation、inbox、显式 runtime drain、canonical assistant/tool transcript、workspace file/revision/publication、extension reporting projection 和 events，不能只看 tool 注册

## 协作与表述规范

面向用户的计划、诊断、实施说明、验证结果、提交说明，以及项目文档，默认使用准确、通顺、自然的中文。仅代码标识、schema id、命令、接口路径、固定状态名、需逐字引用的原始错误文本，以及无法安全翻译的专有名词保留英文；普通概念不作无必要的中英文拼接。首次出现且确有必要时，可用“中文释义（英文关键词）”建立对应关系，后文沿用中文。

## 提交与 Pull Request 规范

近期提交历史以简短的 Conventional Commit 风格为主，如 `feat:`、`feat(scope):`。提交信息使用祈使句，必要时加作用域，例如：`fix(mcp-project-memory): reject stale workflow tokens`。

PR 应说明影响的 app/package、列出已执行的验证命令，并注明配置变更或运行风险。修改 `apps/openzyme-web-ui` 时附上界面截图；修改 MCP/HPC 行为时附上示例命令、请求参数或关键输出。修改 V3 架构、runtime、protocol、execution 或 report 行为时，应说明已对照的 `docs/v3/` 文档与新增/更新的回归测试。

## 架构与变更说明

架构设计的当前入口参考 `docs/OpenZyme架构设计.md`，具体 V3 细则参考 `docs/v3/README.md` 指向的稳定文档，并以当前代码实现作为事实校验。若发现实现、主架构文档和 V3 稳定文档存在偏离，不要静默选择其中一个覆盖其他来源；应先核对真实代码路径与验收证据，再同步修正文档或实现。若用户明确要求进行架构层面的变更，则在修改具体实现时同步更新 `docs/OpenZyme架构设计.md` 及相关 `docs/v3/` 文档，确保架构文档与项目实际设计保持一致。

*在openzyme开发的时候谨记一点：agent 应保留策略自由；harness 要把世界的真实约束忠实、结构化、低摩擦地呈现出来。*
