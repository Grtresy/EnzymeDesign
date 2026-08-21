## Why

OpenZyme V3 已经形成清晰的协作真值、授权、可靠外部效果与不可变文件交接语义，但这些语义目前仍与 SQLite、Git/LFS、LangChain、Podman、Research、Reporting、Science、HPC 和 AOX/酶设计能力混装在 `openzyme-domain`、`openzyme-core`、`openzyme-runtime` 与 Host composition 中。现有工具目录又把“部署安装了什么”“target 上实际有什么”“Agent 被允许做什么”和“此刻能否调用”压缩成静态 catalog、粗粒度 capability profile 与布尔 `is_visible()`；HPC qualification 只有不可解释的整体 `toolchain_digest`，Host 仍直接装配具体 runner、Research 和生物能力。因此，仅移动 Python 文件不会形成真正的插件系统。

现在 file-workspace cutover 已完成并通过主线与架构资格验证，正适合在不改变科学结论、Agent 策略或既有 Task/Science terminal 语义的前提下，同时固定产品边界、依赖方向、显式组合、能力解析和 workspace runtime 基础契约，避免下一种能力继续反向修改 Kernel 或由 Host 硬编码可用性。

## What Changes

- 用两条正交轴替代单一五层链：语义所有权轴为 `Contracts / Extension SPI -> Kernel -> Capability Plugins -> Product Plugins`；部署组合轴把 Kernel、明确选择的 Adapters、Plugins、Drivers 与 API/CLI/UI 解析为一个 digest-bound Distribution。`OpenZyme Standard` 与 `EnzymeDesign` 都是 Distribution，不是新的语义层。
- 固定五个不同概念：Kernel 定义 canonical rules；Adapter 实现既有 Port；Plugin 增加语义能力；Driver 在 Plugin 内把 typed request 转换为具体执行方式；Distribution 只选择 exact Kernel、Adapter、Plugin、Driver 和 delivery surface，不拥有业务状态。
- **BREAKING**：建立 `openzyme-contracts` 与 `openzyme-kernel`，纵向拆分现有 `openzyme-domain` 和 `openzyme-core`；迁移期间仅允许 change 内部兼容 re-export，最终 cutover 不保留 `openzyme-domain`、`openzyme-core`、`openzyme-runtime` 或 `openzyme-engines` 作为第二 authority。已确认不存在仓外消费者，因此不提供跨 release 的旧包兼容窗口。
- 建立 `openzyme-extension-spi`。Adapter ports、Kernel application service contracts 与 Plugin contribution SPIs 分组且保持 implementation-free；Plugin 不获得 `CoreRepositories`、raw SQLite、Host internals 或无限权力的任意事件 hook。
- 把 runtime coordination 与 runtime mechanism 分开：Kernel 保留 signal、claim、session lease、bounded command/outcome、continuation、fence 与 settlement；runtime SPI、LLM/provider、prompt/compaction、LangChain、Podman/process、配置和 provider diagnostics 分别进入明确的 adapter 包。
- 把 SQLite repositories/migrations、Git/LFS repository service、workspace provision/publication mechanism、Host API、HTTP client/CLI、静态 Core UI 和默认 runtime/process adapters 组合为 Standard Distribution；其 required semantic Plugin set 固定为空。Kernel wheel 不安装 FastAPI、LangChain、模型 Provider、Tavily、生物科学库、容器、SSH 或 Slurm 依赖。
- 新增显式、digest-bound extension composition。Python entry point 只定位 manifest；`openzyme-composition.toml` 明确列出 exact extension set。Host 拒绝未列出的 ambient capability、版本或 digest 漂移，以及 tool、route、projection、worker、migration namespace 冲突。Host activation 和 Session 都绑定 exact extension bundle 与 workspace backend identity。
- 明确 optional Plugin 的 fail-closed 语义：未安装可保持 `inactive`，合法激活但资源资格不足可保持 `degraded`；manifest/schema/digest/migration 冲突、依赖环或供应链完整性错误无论 required/optional 都阻止 activation。安装或恢复 optional Plugin 不得热更新既有 Session。
- 扩展状态使用 namespaced tables 和独立 migration bundle，并可作为受限 transaction participant 加入 Standard SQLite 的短 `BEGIN IMMEDIATE` Unit of Work；扩展不能获取或写 Core repositories/tables，核心 mutation 只能通过 Kernel application service/command。
- **BREAKING**：把公开的 `AgentCapabilityLease` 概念更正为 `AgentAuthorityLease`。`general/executor` 只可作为签发模板，admission 必须检查 operation-specific authority grant；现有物理表名首轮不改，由 table-owner/migration ledger 接管，`@2` 不保留旧公共别名。
- 建立四类不可混淆的能力事实：Extension Capability 表示安装并激活的语义能力；Resource Capability 表示 exact target inventory 上的实际软件/硬件/数据事实；Authority Capability 表示 Agent 被授权的操作；Tool Affordance 是三者与 workspace/task/health/policy 在特定 Session/turn 上求交后的结果。
- 新增 `CapabilityRegistry`、dependency/route resolver、`DeclaredToolCatalog`、`ToolAffordanceResolver`、`ToolAffordanceSnapshot` 与 `capabilities.inspect`。模型函数列表只包含 `AVAILABLE`/`AVAILABLE_WITH_APPROVAL`；blocked 能力只通过安全 inspection 展示，`HIDDEN` 完全不可见；dispatch 前重验 snapshot、authority、workspace generation、inventory generation 与 exact route，stale 时以 `no_effect` 失败且不得替换 route。
- 把 HPC qualification 升级为 immutable `TargetToolchainInventory` generation、`TargetCapabilityFact` 与 `SoftwareQualificationReceipt`。Tool Plugin 只声明 declarative requirements/qualification spec；HPC Plugin 管理 target/inventory；SSH/Slurm Adapter 执行 operator-controlled probe/run；Kernel 只索引和验证安全 capability fact。Agent 不得在 turn 中自行 SSH 探测，只有 operator/admin 能发布并显式更新 Session capability binding；Agent 只在已绑定 routes 中选择。
- 建立通用 Workspace Runtime：Kernel 定义 `WorkspaceRuntimeBinding`、Observation/Filesystem/Process/Transfer ports、operation-specific authority、request/receipt/effect certainty 和基础 `workspace.*` 工具契约；本地 filesystem/Podman 与远端 SSH/SFTP/rsync 由 Adapters 实现，HPC Plugin 拥有远端 workspace 生命周期和 `hpc.workspace.*` contribution。
- **BREAKING**：`workspace.exec` 只绑定当前 Agent 的本地 generation，不再承载 HPC SSH 登录；HPC 使用显式 opaque `workspace_id` 的 `hpc.workspace.exec/fs.*`。所有 exec、文件 mutation 与 transfer 都通过 durable ControlledOperation，读/list/stat/hash 为 observation。Workspace root 生命周期 cleanup 与普通文件 remove 永久分离，HPC login/file credential 永不包含 scheduler authority。
- 把 Deep Research、通用 Research、Reporting、Scientific lifecycle、revision execution 与 HPC/Slurm 迁为显式通用扩展。删除 Core 中按 `task.kind == "research"` 自动选择 `deep_research.start` 的策略；Agent 自己选择 capability，或由显式启用的 extension policy 提供 planner。
- 把 revision-bound formal execution 归入 `openzyme-compute` Plugin，HPC target/workspace/inventory 归入 `openzyme-hpc` Plugin，SSH/Slurm 归入 adapters。Plugin 之间按 capability contract/route 组合，不按 Python 包名互相调用。
- 把 PubMed、Semantic Scholar 与 literature quorum 放入 science-research 能力；把 UniProt、RCSB、InterPro、HMMER、AOX、fpocket、Vina、AlphaFold catalog、RDKit/Meeko/Open Babel 前处理和酶设计验收规则迁入 EnzymeDesign。正式 HMMER/Vina 工具必须编译 typed `ExecutionWorkloadSpec` 并经 Compute lifecycle；直接本地或 HPC Shell 只表示探索性进程事实，不能成为 scientific adoption 或 formal finish evidence。`openzyme-pipeline` 的通用 control-socket/revision SDK 抽成 execution SDK，其 AOX calculations 迁入 EnzymeDesign。
- **BREAKING**：推出 `file_workspace_public@2`，基础投影只包含 Kernel facts；Research、Reporting、Science、Compute/HPC 和 EnzymeDesign 数据进入按 Plugin contract ID 命名的 `extensions` section。release identity 分别绑定 Kernel contract/schema、Adapter bundle、Extension bundle、declared tool、route、projection、migration、workspace backend 与 Host/client build digest；Session capability binding 和逐 turn affordance 使用独立 identity。`@1` 不双写、不在线翻译，也不能继续 mutation。
- 分离不同变化频率的 identity：kernel contract、adapter bundle、extension bundle、declared tool catalog、projection catalog、target inventory/session capability binding 与 turn affordance snapshot 分别 digest；瞬时 target health 不触发 release contract 改版，但会在 dispatch revalidation 中阻止调用。
- 保留当前 Git-shaped revision contract：commit、tree、immutable ref、Git LFS closure 与 `RevisionPathRef` 仍是 V3 精确文件交接协议；只把 Git 命令、ref/hook、credential、bare root、LFS store、pin/GC 和挂载机制迁入 Standard adapter。本 change 不引入多 workspace backend 抽象。
- 建立 Kernel-only fake-Adapter、OpenZyme Standard production Distribution 和 EnzymeDesign product Distribution 三种 non-live qualification profile，并加入 source import、pyproject、wheel metadata/content、manifest/catalog 和 forbidden-vocabulary 依赖门禁。
- 把实现与文档同步纳入 completion contract：每个 ownership/call-path/composition/public-contract 迁移必须在同一实施阶段更新 `docs/OpenZyme架构设计.md`、对应 `docs/v3/` 稳定文档、受影响 package/app README 与部署/迁移说明，并由 source-to-doc traceability 和最终 drift audit 证明代码、配置、schema、OpenSpec 与文档一致。
- 本 change 在当前 monorepo 的既有 `packages/` 与 `apps/` 根内完成 wheel 与 namespace 分层；Distribution manifest 可放入独立 `distributions/` 配置目录，但不新增 Python `extensions/`/`products/` workspace 根。不拆 Git repository，不改 scientific acceptance 语义，不重命名现有数据库表，不新增隐藏 fallback，不替 Agent 选择科学计划，不启动 provider/HPC/MICU/Chrome/live campaign。

## Capabilities

### New Capabilities

- `openzyme-kernel-boundary`: 定义稳定 Contracts、Kernel canonical truth、application ports、允许与禁止的依赖，以及 Memory、generic capability invocation、runtime coordination、revision/path、evidence 和 controlled-operation 的 owner。
- `openzyme-extension-spi`: 定义 Adapter、Plugin、Driver、Distribution 的稳定术语，ExtensionManifest/Contribution SPIs、Kernel application service contracts 与禁止的宽泛 hook/repository authority。
- `openzyme-extension-composition`: 定义显式 composition manifest、extension manifest、exact activation/session pin、catalog collision、route/worker/projection 注册、namespaced state/migrations、transaction participant 与 fail-closed upgrade/removal。
- `openzyme-capability-resolution`: 定义四类 capability fact、capability dependency graph、declared tool catalog、route resolution、dynamic affordance、dispatch revalidation、inspection 与分层 digest。
- `openzyme-target-toolchain-inventory`: 定义 target inventory generation、软件/硬件/数据 capability fact、qualification spec/receipt、operator adoption、validity/health 与 Session binding。
- `openzyme-workspace-runtime`: 定义 local/remote workspace runtime binding、Observation/Filesystem/Process/Transfer ports、结构化 CRUD、Shell/transfer operation、authority、receipt、effect certainty 与 scheduler 分离。
- `openzyme-runtime-adapter`: 定义 Kernel runtime command/outcome 与可替换 Agent runtime、LLM/provider 和 process adapter 之间的 SPI、身份、错误、fence、bounded turn 与 settlement 边界。
- `openzyme-standard-composition`: 定义 Standard 作为 required semantic Plugin set 为空的官方 Distribution，选择 SQLite、Git/LFS、Host、Client/CLI、Core UI、默认 LLM runtime 和 process isolation adapters，并提供 core-only 可运行基线。
- `openzyme-research-extension`: 定义 provider-neutral research orchestration、source/evidence、web/document Provider adapter、published-file handoff 和可选 science-research provider 分层。
- `openzyme-reporting-extension`: 定义 report draft/publication、格式/渲染/验证、projection 和 task-finish validator，且保持 report、publication 与 task terminal 分离。
- `openzyme-science-extension`: 定义 ScientificAttempt、selection、occurrence、disposition、adoption、deliverable、formal closure 与 science finish validator 的扩展 ownership。
- `openzyme-compute-plugin`: 定义 revision-bound formal execution、typed workload、route-bound dispatch/observe/reconcile/cancel/result 与 generic controlled-operation 的组合边界。
- `openzyme-hpc-plugin`: 定义 HPC target、executor workspace、target inventory、narrow runner wire contracts及其与 SSH/SFTP/rsync/Slurm adapters 的组合边界。
- `enzymedesign-product-composition`: 定义 AOX/HMMER、序列与结构分析、docking/preprocess、垂直工具、workflow contracts、routes/UI 与 qualification 的 EnzymeDesign ownership。
- `openzyme-layered-qualification`: 定义三种 composition profile qualification、依赖/安装闭包、扩展可移除性、release bundle 和既有 V3 不变量的迁移前后等价证明。

### Modified Capabilities

- `file-workspace-public-interfaces`: 从单一全量 `@1` base schema 改为 `@2` Kernel core + namespaced extension sections，并绑定 extension/projection/workspace-backend release identity 与 offline cutover。
- `file-workspace-cutover-assurance`: 将单一 production composition 验证扩展为 Kernel-only、Standard 和 EnzymeDesign 三种 profile oracle，同时保持 authority、effect certainty、revision、task/scientific terminal 分离等既有不变量。
- `file-workspace-deployment-proof`: fresh/offline proof 改为验证分层 wheel 安装闭包、显式 composition manifest、extension migrations/catalogs、core-only 启动和 EnzymeDesign product bundle，而不是隐式安装全仓能力。

## Impact

影响根 uv workspace、所有 `packages/openzyme-*`、`packages/preprocess-backend`、`apps/openzyme-host-api`、`apps/openzyme-host-cli`、`apps/openzyme-web-ui`、`apps/mcp-hpc-runner`、新增 Distribution manifests、SQLite migration/repository composition、authority schema/public projection、target inventory/session capability binding、workspace operation、public schemas/events/restore、tool/projection/route catalogs、deployment manifests、architecture qualification、`./scripts/check-mainline.sh`、`docs/OpenZyme架构设计.md` 和相关 `docs/v3/` 稳定文档。现有物理业务表名与 scientific/task/runtime terminal 语义先保持；代码 ownership、wheel dependency、composition identity 与 `@2` public contract 在离线 quiescent cutover 中一次性切换。
