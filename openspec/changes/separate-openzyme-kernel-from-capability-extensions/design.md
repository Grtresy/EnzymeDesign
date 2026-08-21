## Context

OpenZyme V3 已经把最困难的运行时语义固定为可执行事实：Session、Task、Lane、Agent、Protocol、Approval、authority lease、runtime signal/command/continuation、mutation authority、effect certainty，以及由 Git commit/tree/LFS closure 表达的不可变文件交接。当前问题既包括这些语义的代码 owner、持久化机制、默认部署和垂直产品仍混在同一组包中，也包括插件真正需要的 capability dependency、target inventory、route resolution 和逐 turn tool affordance 尚未形成 canonical 闭环。

当前 `dev` 的直接依赖和源码事实包括：

- `openzyme-core` 直接依赖 `openzyme-domain`、`openzyme-research` 和 `openzyme-runtime`，同时包含 SQLite repository、Git/LFS、Podman/capsule、Research planner、Reporting、Scientific lifecycle、revision execution、HPC workspace 和 AOX file contract；
- `openzyme-runtime` 直接依赖 LangChain、`openzyme-domain` 和 `openzyme-research`，把 runtime SPI、Provider、prompt/context、进程机制和 Research wrapper 混在一起；
- `openzyme-engines` 同时依赖 LangChain/LangGraph、Domain、Runtime、Research、Tools 和 Preprocess，并承载 `deep_research.start`；
- `DeepResearchTaskPlanner` 位于 Core，按 `task.kind == "research"` 自动生成 `deep_research.start`，因此 Kernel 正在替扩展选择能力路线；
- `openzyme-host-api` 是当前组合根，但直接装配 Deep Research、AOX scientific contract/finalizer、revision execution、HPC workspace 和 `mcp-hpc-runner`；
- `openzyme-domain` 同时暴露核心 control-plane、scientific、HPC、job 和 report 数据结构；`mcp-hpc-runner` 因而依赖整个 Domain；
- 当前 `file_workspace_public@1` 把 Core、Report、Science、Execution/HPC 投影和所有 catalog/build digest 绑定在一个平面 schema 中。
- `EngineRegistry.register()` 对重复 engine name 采用后写覆盖，`ToolRuntime.is_visible()` 只返回布尔值，`AgentStepContext` 没有 capability binding、route、inventory generation 或 affordance snapshot；`top_level_tool_descriptors()` 还会忽略传入的 engine registry；
- 当前 `AgentCapabilityLease` 强制等于 `general`/`executor` 两个 closed profile，把 authority grant 与 extension/resource/tool availability 混为一个词；本地 `workspace.exec` 需要完整 GENERAL capability set；
- 当前 HPC qualification 只保存整体 `toolchain_digest`，无法回答某个 target 是否具有指定版本 HMMER/Vina、允许哪些 operation、资格证明何时生成；
- 当前 executor 工具只提供 `hpc.workspace.request/inspect/verify/sync_source`。远端 Shell/结构化 CRUD 仍通过本地 `workspace.exec` 获取 SSH credential 后自行调用，不能形成统一的 remote effect/reconcile receipt。

这些耦合使“增加一种新能力不修改 Kernel”无法成立，也使 `pip install openzyme-core` 的安装闭包不再代表一个平台内核。本 change 在 monorepo 内纵向切开 owner 和依赖方向；它不重新设计已经验收的 V3 状态机。

约束如下：

- 以 `docs/OpenZyme架构设计.md`、`docs/v3/` 稳定文档、当前 source/config/composition 和可执行 qualification 为共同 oracle；发现偏离时必须显式修正，不能静默选择其中一个；
- agent 继续拥有研究、科学、工具选择、Git 操作和完成时机等策略；Kernel 只拥有真实约束、身份、授权、状态迁移和安全失败；
- SQLite 继续是 OpenZyme Standard 的 control-plane persistence，Git/LFS 继续是文件真值；短事务、single-writer、lease/fence 和 all-or-nothing Unit of Work 不因包拆分而变成跨服务事务；
- 已确认没有仓外消费者，因此最终 cutover 不需要跨 release 维持旧 Python import 或 `@1` mutation compatibility；仓内迁移仍必须 fail closed 并保留历史只读证据；
- 已确认当前 V3 可以暂时保留 Git-shaped revision contract。本 change 不抽象成任意对象存储或多 workspace backend；它只把 Git 命令和存储机制移出 Kernel；
- 本 change 不拆 Git repository，不改 scientific acceptance、Agent 策略或既有业务状态机，不重命名既有业务表，也不运行任何 live Provider/HPC/Chrome/MICU/campaign。

## Goals / Non-Goals

**Goals:**

- 用可构建 wheel、Python namespace、application port 和依赖门禁定义两条正交架构轴：语义所有权轴上的 Contracts/Extension SPI、Kernel、Capability Plugins、Product Plugins；部署组合轴上的 Adapter slots、Drivers、delivery surfaces 与 Distribution manifests。
- 让 Kernel 只拥有跨领域 canonical truth、authority、runtime coordination、Git-shaped revision/path handoff、generic controlled-operation、tool/capability invocation 和核心 mutation services。
- 让 Kernel 额外拥有 Extension Bundle Registry、Capability/Dependency Resolver、Tool Affordance Resolver、generic ResourceCapabilityFact 索引与 Session capability binding；它不拥有 target-specific probe 或领域策略。
- 让 SQLite、Git/LFS、Host、Client/CLI、Core UI、默认 LLM runtime 和进程隔离成为 Standard Distribution 显式选择的 adapters/delivery surfaces，而不是 Kernel 实现细节或语义层。
- 建立 manifest 驱动、版本和 digest 精确绑定、无 ambient capability 的扩展装配；把 route/tool/projection/worker/migration/qualification 注册纳入同一 release identity。
- 建立 `openzyme-extension-spi`，把 Adapter Port、Plugin contribution、Driver 和 Distribution contract 与 Kernel implementation 分开。
- 把 Extension Capability、Resource Capability、Authority Capability 与 Tool Affordance 分成不同的 canonical facts，并由 declared catalog、target inventory、Session binding、authority、workspace readiness、health 和 task policy共同解析模型可见工具。
- 建立 immutable target toolchain inventory generation 和 operator-controlled qualification/adoption；Plugin 声明 requirement，HPC/Compute provider 声明 route，Adapter 执行 probe/run，Agent 不自行探测或采用新 generation。
- 建立统一 Workspace Runtime contracts；本地与 HPC workspace 保留不同生命周期 owner，但通过 runtime binding 和 Observation/Filesystem/Process/Transfer ports 执行受控操作。
- 允许扩展拥有 namespaced state 和 migration，同时禁止其直接写 Core tables；需要原子更新时只经受限 transaction participant 与 Kernel command context 参与同一短 SQLite Unit of Work。
- 把 Research、Reporting、Science、Compute 与 HPC 迁为通用 Plugins，把 AOX/HMMER/序列/结构/docking/preprocess 完整迁入 EnzymeDesign。
- 用 `file_workspace_public@2` 表达稳定 Core projection 与 namespaced extension projection，并一次性离线切换 session/release identity。
- 建立 Kernel-only、Standard Distribution 和 EnzymeDesign Distribution 三种 non-live qualification profile，以及 source/import、pyproject、wheel、manifest/catalog/capability/inventory/affordance 和 forbidden-vocabulary 门禁。

**Non-Goals:**

- 不实现多 Host、分布式 writer、微服务或跨数据库事务；组合根可以依赖多个包，但 Kernel 不反向依赖它们。
- 不承诺任意 workspace backend；commit、tree、immutable ref、LFS closure 和 `RevisionPathRef` 仍是当前协议的一部分。
- 不改变 `task.finish` 的显式 owner、不从 runtime idle/tool result/publication/report/scientific receipt 推导 Task terminal。
- 不替 Agent 添加按 task kind 自动规划 Research、AOX、HPC 或其他领域路线的 Kernel policy。
- 不允许 Kernel、Plugin 或 Distribution 在只剩一个 route 时替 Agent 隐式选择 target；正式 target-bound tool call 必须绑定 Agent 显式选择的 route。
- 不同时重命名数据库表、重写 scientific lifecycle、改变 AOX acceptance threshold、改变 runner effect certainty 或扩大 external retry。
- 不把直接 Shell/CRUD 成功提升为 publication、formal compute、scientific adoption 或 Task terminal；这些边界继续要求各自显式命令。
- 不立即拆成多个 Git repository；先证明 wheel 可独立构建、依赖单向、扩展可移除，再另行决定物理仓库边界。
- 不新增 Python `extensions/`、`products/` 或 `distributions/` workspace root；继续使用 `packages/`/`apps/`，仅允许独立 `distributions/` 配置目录承载发行 manifest。
- 不把旧包 re-export、`@1` reader 或 archived migration 作为长期兼容产品；它们只允许存在于明确有删除任务的迁移窗口或离线历史验证路径。

## Decisions

### 1. 用语义所有权轴与部署组合轴替代单一五层链（D1）

语义所有权轴回答“谁定义状态、工具语义和业务能力”：

```text
Contracts / Extension SPI
            ^
            |
      OpenZyme Kernel
            ^
            |
    Capability Plugins
            ^
            |
 Product Plugins / EnzymeDesign
```

部署组合轴回答“这次部署选择了哪些实现和能力”：

```text
Kernel
+ exact Adapter bindings
+ activated Plugins
+ selected Drivers / Routes
+ API / CLI / UI
= one versioned Distribution
```

`OpenZyme Standard` 是 required semantic Plugin set 为空的官方 Distribution；`EnzymeDesign` 是选择通用与垂直 Plugins 的产品 Distribution。两者都不拥有新的 canonical 语义，也不构成 Kernel 与 Plugin 之间的依赖层。

五个术语使用 closed 定义：

| 概念 | 所有权 | 禁止事项 |
| --- | --- | --- |
| Kernel | 定义跨领域 canonical rules、authority、identity、状态迁移与解析器 | 不实现 SQLite/Git/LLM/SSH/Slurm，不定义领域策略 |
| Adapter | 实现一个已存在的 Port | 不增加顶层 canonical entity，不直接增加 vendor-specific Agent tool |
| Plugin | 增加语义能力、tool/state/worker/projection/qualification | 不直接写 Core table，不 import 具体 Adapter |
| Driver | 在所属 Plugin 内把 typed request 编译到一种 route/backend | 不独立定义顶层科学语义，不成为 ambient Plugin |
| Distribution | 选择 exact Kernel、Adapters、Plugins、Drivers 与 delivery surfaces | 不拥有业务状态，不因环境中多装包而改变能力 |

`openzyme-contracts` 只包含稳定 ID、枚举、DTO、failure envelope、`ToolSpec`/`ToolResult`、adapter ports、Kernel application service contracts 和 schema identities。`openzyme-extension-spi` 只包含 manifest/contribution/driver/provider SPIs，并依赖 Contracts。两者都不得创建 repository、打开 SQLite、执行 Git/进程/网络，也不得依赖 FastAPI、LangChain、Provider、生物或 HPC 库。

`openzyme-kernel` 依赖 Contracts 与 Extension SPI，拥有 application services、跨领域状态机、composition validation、capability graph 与 affordance resolution。Adapter 依赖其 Port contracts；Plugin 依赖 Contracts、Extension SPI 与公开 Kernel application service contracts，不能 import Kernel repository implementation。Composition root 可以依赖所选所有具体实现，但不改变内层依赖方向。

Python wheels继续位于现有 `packages/`，应用位于 `apps/`；语义类别由 distribution/manifest kind、public contract 和依赖门禁表达。独立 `distributions/` 目录只保存 versioned composition manifests，不成为新的 Python workspace root。

替代方案是保留 `openzyme-domain`/`openzyme-core`，只新增插件目录。拒绝，因为当前两个包本身已经同时拥有 Core、Science、HPC、Report 和机制，无法通过目录搬迁修复安装闭包和反向 import。另一个替代方案是把 Standard 继续放入 L2；拒绝，因为 Distribution 对所选具体组件形成横向组合，而不是语义依赖层。现在拆 Git repository 或微服务同样拒绝，因为当前 mutation 依赖同一短 Unit of Work，物理分布会在 contract 尚未稳定时引入分布式一致性问题。

### 2. Kernel 的 closed ownership matrix 以“任何领域都需要且改变会改变上层语义”为准（D2）

Kernel 必须拥有以下逻辑对象和状态机：

| Family | Kernel owner | 明确排除 |
| --- | --- | --- |
| Collaboration | Project/Session、Task/Dependency/Finish、Lane、AgentMember/parent-child、Delegation、Inbox、Protocol、canonical conversation facts、retirement settlement、Memory | AOX task kind、Research planner、report section、scientific policy |
| Authority | ApprovalRequest、AgentAuthorityGrant/Lease、operation-specific authority、owner/generation/lease/fence、mutation writer/quiescence/settlement、idempotency identity | Extension/resource/tool availability、Provider credential issuance mechanism、SSH key、Git credential implementation |
| Runtime coordination | AgentRuntimeSignal/claim、SessionRuntimeLease、bounded RuntimeCommand/Outcome、continuation delivery、process epoch/fence、settlement/retirement | LangChain、model selection、prompt implementation、token estimator、Podman/tmux/subprocess |
| File collaboration | ProjectRepositoryBinding identity/session pin、WorkspaceGeneration、private checkpoint、publication intent、immutable PublishedRevision、RevisionPathRef、verified handoff/evidence | git subprocess、clone/fetch/push/ref/hook、bare root、credential、LFS store/pin/GC/mount |
| External effects | generic ControlledOperation admission/identity/approval/dispatch certainty/observe/reconcile/deadline/cancel/result/receipt | Tavily、browser、SSH、Slurm、mail、database-specific external write |
| Capabilities | Extension/Resource/Authority/Affordance 四类 fact 的通用 identity、Extension Bundle Registry、capability graph、declared catalog、route/affordance resolution、invocation identity/status/failure、Session binding | `deep_research.start`、`hmmer.search`、`vina.run`、AOX branch、target-specific probe |
| Workspace runtime | WorkspaceRuntimeBinding、Observation/Filesystem/Process/Transfer request/receipt、root-relative path与operation effect identity | Podman、native filesystem、SSH/SFTP/rsync实现、HPC workspace lifecycle、scheduler |
| Core mutation | application commands、authorization、event emission、generic EvidenceRef、finish-validator invocation | extension direct table/repository access、validator-driven automatic finish |

首次 Session 不得依赖一个尚不可能存在的 Session-bound Agent lease。Host/delivery security 先通过
implementation-free `SessionBootstrapAuthorityVerifierPort` 验证短时 operator authorization；该 authorization
绑定 exact project/Session、root `AgentAuthorityLease`、revision-1 `SessionCapabilityBindingRevision`、immutable
`SessionCompositionPin` 以及 Extension/binding digests。Kernel 随后在单一短 UoW 中 create-only 写入 Session、
master AgentMember、root lease、initial binding、composition pin 与一个 durable bootstrap event。普通
`CollaborationKernelApplicationService.CREATE_SESSION` 不得用预置假 lease 绕过这个入口；认证失败、过期、
identity/digest drift 或任一 owner-table conflict 都必须整笔回滚。bootstrap 不创建 workspace、运行 runtime、
创建 Task 或采用新 target inventory，后续 mutation 仍只接受 canonical AgentAuthorityLease。

当前 `EngineInvocation`/tool call 表可以在本 change 中保留物理表名和兼容的持久化字段，但其逻辑语义必须是领域无关的 capability invocation。`AgentCapabilityLease` 的公开 DTO/schema/projection 在 `@2` cutover 中更名为 `AgentAuthorityLease`；现有物理 table 名首轮保留并由 table-owner ledger 显式接管。其他 symbol 只有必要且可机械验证时才重命名；不得把概念纠正与无关表 DDL 混为一次状态迁移。

Task owner 调用 `task.finish` 时，Kernel 可调用当前 Task 声明所绑定的 finish validators；validator 只返回 typed acceptance/rejection evidence，Kernel 仍是唯一 Task terminal writer。扩展 receipt、publication、runtime outcome 和 agent idle 都不能触发 finish。

替代方案是把 ScientificAttempt 视为 Kernel，因为当前 formal closure 很关键。拒绝，因为非科学工作流不需要它；Kernel 保留通用 EvidenceRef 和 finish validator SPI 即足够。另一个替代方案是把 Git 全部移出 contract；本次拒绝，因为已验收的精确 revision/tree/LFS identity 是当前协作协议而非可随意替换的实现细节。

### 3. 最终包拓扑先固定逻辑 wheel，迁移可分阶段但最终只有一个 authority（D3）

目标包和主要来源如下：

| 目标 wheel/应用 | 主要职责 | 现有来源 |
| --- | --- | --- |
| `openzyme-contracts` | core DTO、adapter ports、Kernel application service contracts、failure/tool/capability/workspace contracts | `openzyme-domain` 的核心部分、`openzyme-runtime.contracts/seams` 的纯协议 |
| `openzyme-extension-spi` | ExtensionManifest、Plugin contribution、Driver/Route、qualification/projection/worker/validator SPIs | 新增；只依赖 Contracts |
| `openzyme-kernel` | application services、状态机、bundle/capability/affordance resolver、generic router/operation/runtime coordination | `openzyme-core` 的跨领域部分 |
| `openzyme-store-sqlite` | Core repository implementations、schema bootstrap、migrations、UoW | `openzyme-core.repositories` 及 repository modules |
| `openzyme-workspace-git-lfs` | Git/LFS repository/workspace/checkpoint/publication mechanism | Git/LFS/provision/recovery/credential/storage modules |
| `openzyme-runtime-spi` | `AgentRuntimeAdapter`、bounded turn input/output、runtime adapter errors | 当前 Runtime 的纯 seam；只依赖 Contracts |
| `openzyme-runtime-llm` | LLM/provider、prompt/context/compaction、LangChain adapter、diagnostics | 当前 `openzyme-runtime` 的模型部分 |
| `openzyme-process-podman` | subprocess/Podman/capsule/process lifecycle 与本地 WorkspaceProcess/Filesystem 实现 | Runtime/Core capsule 与 Podman modules |
| `openzyme-client` | `@2` HTTP DTO/client；供 CLI 和其他客户端复用 | Host CLI 中的 HTTP/client contract |
| `openzyme-standard` | required semantic Plugin set 为空的显式 Distribution manifest、默认 adapter factories、distribution metadata | 新增；不拥有业务状态 |
| `openzyme-host-api` | 通用 Host composition root、安全/API/core routes、extension mount | 当前 Host 去除 AOX/Science/HPC hardcode 后 |
| `openzyme-host-cli` | thin `openzyme-client` wrapper | 删除对 runtime implementation 的依赖 |
| `openzyme-web-ui` | Core UI shell + manifest-driven extension renderer | 当前 UI 分层 |
| `openzyme-research` | provider-neutral Research contracts/engine/tool/projection | 当前 Research + Deep Research 的通用部分 |
| `openzyme-research-tavily` | Tavily provider adapter | 当前 Tavily optional extra |
| `openzyme-reporting` | report lifecycle/render/validation/projection/finish validator | Core report modules |
| `openzyme-science` | Scientific lifecycle/contracts/repositories/validators | Domain/Core scientific modules |
| `openzyme-execution-contracts` | narrow revision execution/runner wire DTO | Domain job wire 的最小闭包 |
| `openzyme-compute` | revision-bound formal execution admission/worker/result lifecycle 与 typed workload | Core/Host execution modules |
| `openzyme-execution-sdk` | sandbox control-socket/revision request SDK | `openzyme-pipeline` 通用部分 |
| `openzyme-hpc` | target、executor workspace、toolchain inventory、resource route 与 credential semantics | execution/Core/Host HPC modules |
| `openzyme-hpc-ssh` / `openzyme-hpc-slurm` | SSH/SFTP/rsync workspace 与 Slurm scheduler adapters | runner/Host transport implementations |
| `mcp-hpc-runner` | 可独立部署的 runner service | 只依赖 execution wire contracts |
| `enzymedesign-*` | AOX、bio research、HMMER、sequence toolpack、structure、docking、preprocess、product Distribution | Pipeline、Tools、Preprocess、Host AOX 和相关 fixtures |

逻辑 package 可以在任务阶段按编译/测试风险拆成多个短迁移，但最终 `openzyme-domain`、旧 `openzyme-core`、旧 `openzyme-runtime`、`openzyme-engines`、通用名却只含酶工具的 `openzyme-tools` 均不得成为第二 authority。迁移 re-export 必须有 allowlist、调用点 ledger、删除任务和 forbidden-import gate；由于没有仓外消费者，最终 release 不发布兼容 wheel。

替代方案是一次性移动所有文件并同时重命名所有类、表和 route。拒绝，因为包 ownership、运行语义和数据迁移会失去可定位的失败边界。本 design 允许阶段性搬迁，但每阶段都要求唯一 canonical implementation，shim 只能单向 re-export，不能复制逻辑。

### 4. Plugin discovery 与 activation 分离，Distribution manifest 是唯一 enablement authority（D4）

Python entry point group `openzyme.extensions` 只返回一个纯 manifest locator；它不是启用授权。部署根目录的 `openzyme-composition.toml` 必须声明：

```toml
composition_id = "enzymedesign.standard@1"
core_contract = "openzyme.kernel@1"
core_contract_digest = "sha256:..."
workspace_backend_id = "openzyme.workspace.git@1"
workspace_backend_digest = "sha256:..."

[[extensions]]
extension_id = "openzyme.research@1"
distribution = "openzyme-research"
version = "..."
manifest_digest = "sha256:..."
required = true
```

每个 canonical `ExtensionManifest` 至少闭合：

- `extension_id`、semantic version、manifest/schema version、contract digest 和 required core contract range/digest；
- Plugin kind、distribution/build identity、提供的 capability IDs，以及按 capability contract 声明的 `requires.all/any`、版本/operation/same-target constraints；
- tool specs、required authority grants、approval policies、route-selection policy；
- projection schema/provider、routes、workers、finish validators；
- Driver/Route contributions、qualification spec 与 resource capability requirements；
- state namespace、migration bundle/digest 和 transaction participant declarations；
- qualification scenarios/resource manifests；
- non-secret configuration schema/digest。Secret 只保存 locator/credential owner，不能进入 manifest 或 Session projection。

Host 读取 manifest bytes、canonicalize 并重算 digest，再验证 exact installed distribution/version。未列入 composition 的已安装 entry point 不加载、不注册，也不能通过 import side effect获得 capability。required Plugin 缺失或依赖不满足时 activation 失败；optional Plugin distribution 未安装时保持 `inactive`，合法 Plugin 的 resource qualification 暂不满足时保持 `degraded`。但 optional Plugin 的 manifest/schema/digest/version/migration 完整性错误、重复 key、依赖环或 partial registration 与 required Plugin 一样阻止整个 activation，不能以“optional”为由吞掉供应链或契约错误。

装配阶段建立 closed catalogs 和 capability dependency graph，并对以下 canonical key 做全局唯一性检查：tool name、`METHOD + normalized route`、projection contract ID、worker ID、migration namespace、finish validator ID、Plugin-provided capability ID 与 Driver/route ID。冲突不是“后加载覆盖前加载”，而是 typed startup failure。依赖必须按 capability contract 解析，Plugin 不得以 Python distribution/import 名称调用另一个 Plugin 的内部 service。

optional Plugin 后续被安装、恢复资格或新增 route，只能进入新的 deployment activation epoch；既有 Session 不热获得其 tools/state。替代方案是扫描所有 installed entry points 自动启用；拒绝，因为 ambient capability 无法进入 release digest，也违反 fail-closed authority。另一个替代方案是让 Host 在 Python 代码里 hardcode 插件列表；拒绝，因为这会把 EnzymeDesign policy 重新放回通用 composition root。

### 5. Deployment activation 与 Session 同时 pin exact extension bundle（D5）

规范化 Distribution composition 分别产生 `adapter_bundle_digest`、`extension_bundle_digest`、`declared_tool_catalog_digest`、`route_catalog_digest`、`projection_catalog_digest`、`migration_catalog_digest` 和总 `composition_bundle_digest`。动态 target health、Agent authority 和 workspace readiness不得塞入这些低频 release identities。Standard startup 先以只读方式验证 schema/composition proof，再激活一个 deployment composition epoch；成功后才能创建 repository writers、workers 和 routes。

新 Session 必须原子绑定：

- core contract/schema digest；
- exact Distribution/composition、adapter bundle 与 extension bundle digest；
- declared tool/route/projection catalog digest；
- workspace backend ID/digest；
- 当前 `SessionCapabilityBindingRevision`，其中只引用 operator 已采用的 immutable target inventory generations；
- Host/client compatibility epoch。

同一 Session 生命周期内不支持热替换 Plugin 或 Adapter bundle。Host 当前 bundle 与 Session pin 不一致时，只允许安全 inspection/typed upgrade-required response；messages、runtime drain、approval resolution、tool/capability invocation、workspace mutation、publication和外部 operation全部拒绝。Plugin/Adapter升级、移除或替换必须先 quiesce deployment，运行 offline compatibility/migration verifier，创建新 activation epoch，并按 Session migration规则显式处理。

Target inventory 采用是单独的高频显式过程：只有 operator/admin 能在已通过资格验证的 generation 上创建新的 monotonic `SessionCapabilityBindingRevision`。Agent 只能从当前 revision 已绑定且其 authority允许的 routes 中显式选择；新 inventory、唯一剩余 route 或恢复健康都不能自动改变既有 binding。每个 RuntimeTurnCommand 绑定该 revision 和 `turn_affordance_snapshot_digest`，每个 tool dispatch 再重验 exact route、inventory generation、workspace generation、authority lease/fence 与 health observation。

已安装但未启用的 extension 对 Session 不可见。移除一个未被 Session pin 的 extension 不改变 Core projection。移除被非终态 Session pin 的 extension，或移除仍有 unsettled operation/owned state 的 extension，必须在 activation 前失败；不能返回空 projection 或把 extension state折叠进 Core。

替代方案是只在 Host 启动时 pin bundle，不写 Session identity。拒绝，因为 restore/continuation 无法判断旧 tool schema 和 extension state 是否仍有效。另一个替代方案是为每个请求动态选择插件版本；拒绝，因为会破坏 deterministic restore、catalog identity 和 effect reconciliation。

### 6. 扩展状态可加入同一 SQLite 短事务，但不能获得 Core repository authority（D6）

扩展拥有稳定 `state_namespace`、独立 migration bundle 和 table ownership manifest。首轮拆分不重命名现有业务表；离线迁移把每张既有表精确归属到 Core 或一个 extension migration owner，并验证无重叠、无孤儿、无双 owner。新增 extension table 必须使用其声明 namespace，且外键/索引/trigger 依赖必须在 owner manifest 中闭合。

Kernel retained tables 不得靠 legacy sentinel payload 冒充目标语义。对 Authority、Approval、RuntimeSignal、
SessionRuntimeLease、Continuation 与 ControlledOperation 等已发生 contract 重构的实体，SQLite Adapter 在保留
物理表名时用 closed `record_kind`/target identity 与显式 target columns 分流；codec 只从目标列重建 canonical
payload，CAS ledger 不保存 JSON state。旧 callback 名在目标 ControlStore 中只能绑定 deny-only sentinel，
目标 claim/fence/effect trigger 直接验证 target authority、workspace、process 和 runtime generation；因此目标
writer 不 import 旧 Core，误入 legacy writer 也不会被兼容 fallback 放行。

同样的规则适用于 Git-shaped publication truth：SQLite checkpoint、publication intent、PublishedRevision 与
revision-path verification codecs 只读取 Kernel 的 `WorkspaceGeneration`、`WorkspaceRuntimeBinding`、
`AgentMember`、`AgentAuthorityLease`、repository binding/pin 和 generic `ControlledOperation` owner rows。
target FK/trigger 不得依赖 `agent_git_workspace_records`、Git remote receipt repository 或旧
workspace-publication execution tables；Git Adapter receipt 由 Kernel application service 验证后，仅以协议中
已有的 opaque receipt identity 和 terminal digest 进入 canonical publication fact。

扩展不能接收 raw `CoreRepositories`、Core SQLite connection、Host internal service 或 storage locator。它通过以下窄接口工作：

- Kernel application command/query：读取已授权 Core facts、请求 Core mutation；
- immutable `ExtensionCommandContext`：携带 Session/Task/Agent/lease/fence/revision/operation identity；
- Standard 提供的 `ExtensionStateStore`：只能访问声明 namespace；
- `ExtensionTransactionParticipant`：在 Kernel 已验证 authority 后，按 prepare/apply/result 协议加入同一短 `BEGIN IMMEDIATE` UoW；
- append-only extension event/projection provider：输出其 contract ID 下的 bounded、安全 payload。

Standard SQLite 实现必须用 wrapper/authorizer 和 table-owner manifest 双重限制 extension SQL；扩展 migration 和 runtime statement触及 Core、其他 namespace、ATTACH、PRAGMA mutation或未声明 DDL时立即失败。Kernel 将完整 Core facts作为 context传入，扩展不能用 raw SQL反向读取 Core tables。

事务顺序固定为：外部 effect 之外完成所有输入/decision → Kernel admission/authority check → 打开短 UoW → Core mutation与声明的 extension participant顺序执行 → 同一 commit/rollback → durable event/outbox。LLM、Git、process、provider、SSH或Slurm期间绝不持有该事务。Participant异常回滚整次 mutation并形成结构化 failure；Kernel不重试或绕过 participant。

替代方案是每个 extension 使用独立数据库。首轮拒绝，因为 Scientific/Task 等现有原子不变量会变成分布式事务。另一个替代方案是给扩展 raw shared connection；拒绝，因为包边界无法成为实际 authority boundary。

### 7. Runtime coordination 与 runtime mechanism 通过稳定 SPI 分开（D7）

Kernel 产生并拥有 `RuntimeTurnCommand`，至少绑定 session/member/signal occurrence、task/lane focus、runtime lease generation/fence、process epoch、bounded step/time/budget、tool catalog digest、composition bundle digest 和 continuation identity。`AgentRuntimeAdapter` 只消费命令和一个受限 tool gateway，返回 closed `RuntimeTurnOutcome`：model messages/tool requests、usage、安全 summary、continuation/settlement意图或结构化 failure。

Adapter 不能直接完成 Task、修改 Protocol、写 repository、延长 lease、提交 controlled operation或解释 publication/scientific receipt为业务终态。Kernel 在验证 command identity/fence 后应用 outcome；stale、duplicate、wrong-session或bundle drift outcome不产生 canonical mutation。

`openzyme-runtime-llm` 拥有 LangChain、模型 Provider、prompt/context/compaction、token/model limits和provider diagnostics。`openzyme-process-podman` 拥有 Podman/capsule image、mount/environment、process supervision和retirement，并实现 ProcessIsolationPort。两者都通过 implementation-free SPI/Ports 接入；Kernel tests使用 deterministic fake Adapter，且不导入具体实现。

Provider/process error必须转换为包含 stable code、component、phase、correlation identity、effect certainty、mutation/fallback事实、retry/reconcile policy、cause chain和`diagnostic_id`的 failure observation。完整 traceback、bounded stdout/stderr、return code和私有配置只进受保护 diagnostics。Adapter不得把异常伪装成 success或静默换模型/进程方案。

替代方案是让 Kernel继续接受一个 LangChain runnable。拒绝，因为 Provider和prompt类型会泄漏到 canonical runtime contract。另一个替代方案是把signal/lease也放进 runtime adapter；拒绝，因为重启后的claim/fence/settlement必须由 durable truth owner掌握。

### 8. Research、Reporting、Science、Compute 与 HPC 是显式通用 Plugins（D8）

通用扩展边界如下：

- `openzyme-research`：provider-neutral research request/source/evidence、bounded orchestration、tools/workers/projection；`openzyme-research-tavily`等 provider单独实现具体请求。Core `DeepResearchTaskPlanner`删除；Agent显式选择tool，或 composition显式启用的policy extension提供planner。
- `openzyme-reporting`：draft/report lifecycle、section/format、render/validation、published revision/path、projection和finish validator。Report draft存在、文件发布或render成功不自动完成Task。
- `openzyme-science`：ScientificAttempt、selection、occurrence、disposition、adoption、deliverable、formal closure、rollover和science finish validator。它可以要求Task finish evidence，但不能自行写Task terminal。
- `openzyme-compute`：published revision到formal external execution的typed workload、admission/identity/observe/reconcile/cancel/result；复用Kernel ControlledOperation而不复制effect certainty状态机，也不要求HPC存在。
- `openzyme-hpc`：target、executor remote workspace、credential、toolchain inventory、resource capability facts与route provider语义；它不定义HMMER/Vina等领域工具。
- `openzyme-hpc-ssh`/`openzyme-hpc-slurm`：分别实现remote workspace filesystem/process/transfer ports与scheduler port；`mcp-hpc-runner`只依赖closed execution wire DTO，不依赖整个平台Domain。

所有 Plugins 共享三条硬边界：外部效果经 generic controlled-operation；共享文件经 PublishedRevision + RevisionPathRef；核心 mutation经 application command。Plugin transcript、engine document、provider success、runner result、report和scientific receipt各自只代表其声明事实。

PubMed、Semantic Scholar和literature quorum属于可选的 science-research能力，因为其契约带科学来源/证据政策；普通网页/文档Research不依赖Science。UniProt、RCSB、InterPro和HMMER属于EnzymeDesign bio extension，而不是通用Research。

替代方案是保留一个宽泛的 `openzyme-engines` 聚合包。拒绝，因为它无法表达各能力独立安装、迁移、资格验证和Session pin。通用 distribution可以提供 extras，但每个extension仍必须有独立manifest/contract/digest。

### 9. EnzymeDesign 是消费公开扩展协议的垂直产品，不是 Host 特例集合（D9）

EnzymeDesign Distribution显式选择 Kernel、Standard adapters/delivery surfaces、Research、Reporting、Science、Compute/HPC及其垂直Plugins。以下词汇和实现只能出现在EnzymeDesign/相应Plugin或其qualification/archive路径：AOX、HMMER/hmmbuild/hmmsearch、UniProt、RCSB、InterPro、motif、sequence similarity graph、fpocket、Vina、AlphaFold、RDKit、Meeko、Open Babel、enzyme-specific deliverable/report/acceptance。

`openzyme-pipeline` 被拆为不含生物依赖的 `openzyme-execution-sdk` 和 EnzymeDesign calculation package。前者只提供 `/openzyme/control.sock`、closed revision-bound request/result和failure types；后者拥有AOX reference、threshold、sequence algorithms以及Biopython等依赖。`preprocess-backend`成为 `enzymedesign-docking-preprocess`。当前 `openzyme-tools` 中的AlphaFold/fpocket/Vina catalog进入EnzymeDesign，并删除该误导性通用聚合包。

HMMER/Vina等正式工具拥有自己的输入输出语义、qualification spec、result validator和Driver，但不直接 import HPC/Slurm实现。Agent tool call必须显式提供当前affordance中一个exact `route_id`；领域Driver将请求编译成typed `ExecutionWorkloadSpec`，经Compute Plugin和该route执行。直接`workspace.exec`或`hpc.workspace.exec`产生的进程回执仅支持探索、诊断和显式文件检查，不能成为Scientific adoption、formal deliverable或Task finish evidence。Plugin可通过WorkspaceProcessPort进行版本检查或轻量验证，但不能绕过formal Compute lifecycle提升结果权威性。

通用 Host 只提供 Plugin mount seam；AOX routes、workers、projection/UI renderer、workflow contracts、fixtures和qualification由 `enzymedesign` Distribution注册。EnzymeDesign不能 import `openzyme_kernel.repositories`、SQLite implementation、Host internal service、Git storage locator、HPC internal service或Slurm adapter。

替代方案是在通用Host保留AOX route但通过feature flag隐藏。拒绝，因为代码和依赖仍属于默认产品安装闭包，也会让Host成为垂直schema owner。

### 10. `file_workspace_public@2` 以稳定 Core 和 namespaced extensions 表达投影（D10）

`@2` 顶层 closed shape 为：

```json
{
  "schema_version": "file_workspace_public@2",
  "release": {
    "kernel_contract_digest": "...",
    "core_schema_digest": "...",
    "adapter_bundle_digest": "...",
    "extension_bundle_digest": "...",
    "declared_tool_catalog_digest": "...",
    "route_catalog_digest": "...",
    "projection_catalog_digest": "...",
    "migration_catalog_digest": "...",
    "workspace_backend_digest": "...",
    "host_build_digest": "...",
    "client_build_digest": "...",
    "release_digest": "...",
    "public_contract_digest": "..."
  },
  "core": {
    "session": {},
    "tasks": [],
    "lanes": [],
    "agents": [],
    "protocol": {},
    "conversation": {},
    "approvals": [],
    "authority_leases": [],
    "capability_binding": {},
    "runtime": {},
    "workspace": {},
    "publications": [],
    "operations": {},
    "failures": {},
    "tool_reflection": {}
  },
  "extensions": {
    "openzyme.research@1": {},
    "openzyme.reporting@1": {},
    "openzyme.science@1": {},
    "openzyme.execution@1": {},
    "enzymedesign.aox@1": {}
  }
}
```

具体Plugin section只有在exact Session bundle中启用且caller有权读取时存在；缺失表示未启用，不表示空的领域状态。每个section由其projection schema/digest验证并遵守全局预算、pagination、redaction和continuation contract。Core还提供bounded `capabilities` inspection view，区分activated/inactive/degraded Plugin、safe resource requirement、authority与affordance blocker，但不公开`HIDDEN`工具、credential、binary path或私有probe output。Core reducer/UI不得读取Plugin payload推导Task/runtime/publication truth；Plugin renderer不得写Core state。

Git-shaped workspace/publication facts继续出现在Kernel，因为它们是当前V3协作协议；Host path、bare root、credential、private ref、LFS store locator和backend logs仍不公开。Compute/HPC section只返回owner-scoped opaque workspace/route/receipt identities，不返回SSH hostname、login alias、remote root或runner locator。

`@1` schema、tool catalog、events和saved continuation在cutover后不可 mutation、双写或在线翻译。历史reader只允许离线、只读、显式选择。`@2` client/UI在任一release/catalog/bundle/backend digest不匹配时进入typed stale-contract状态且不发送mutation。

替代方案是在`@1`顶层继续追加可选字段。拒绝，因为Core schema仍会被每个extension能力扩张，且移除插件会改变基础投影。另一个替代方案是自由form extension dict；拒绝，因为无法绑定closed schema和projection catalog。

### 11. Offline cutover一次性迁移package authority、schema ownership和session pin（D11）

迁移分为可验证阶段，但production activation只有一个原子边界：

1. 冻结current source/component/state/table/import/tool/route/projection inventory，生成owner matrix和forbidden dependency baseline；
2. 在不改表名和状态机的情况下抽取Contracts/Kernel并建立temporary re-export ledger；
3. 迁出SQLite、Git/LFS、runtime/process和client机制，保持现有focused tests通过；
4. 以Research作为首个reference extension，建立manifest/registry/state/projection/worker seam并删除Core planner；
5. 迁出Reporting、Science、Compute/HPC，再迁EnzymeDesign；
6. 构建所有 wheel，运行三种 profile qualification 和 dependency/content gates；
7. 进入maintenance/quiescence，冻结database/repository/workspace inventory和unsettled operation set，创建并验证exact backup；
8. offline migrator验证table-owner manifest，执行新增composition/session pin schema与extension migration adoption，生成`@2` schema/composition cutover receipt；
9. 对每个Session分类：terminal/historical Session可保持`@1`离线只读；非终态Session只有在Core/extension rows、workspace backend、catalog和unsettled effect均能精确映射时才迁为`@2`。任何unknown/ambiguous/unowned状态阻止activation；
10. 启动`@2` EnzymeDesign composition，以只读startup verifier重算proof和bundle；成功后才开放writer/worker/route；
11. 删除temporary re-export和旧package authority，运行forbidden import/vocabulary/archive-path gate及全量qualification。

回滚只在`@2` activation前成立：停止进程、验证无post-freeze write，恢复exact database/config backup并运行旧release只读proof。`@2`开放mutation后不得自动回到`@1`、恢复旧writer或双写；失败必须quiesce并通过forward migration修复。Git publication保持immutable，rollback不能改写已发布revision。

替代方案是逐Session在线lazy migration。拒绝，因为同一Host会同时拥有两套tool/schema/extension bundle，continuation和external effect reconciliation无法安全解释。由于没有仓外消费者，一次性offline cutover是更小且更可信的兼容面。

### 12. 三种qualification profile分别证明Kernel语义、Standard机制和EnzymeDesign组合（D12）

建立三个closed profile：

| Profile | Production path | 允许替换 | 必须证明 |
| --- | --- | --- | --- |
| `kernel_fake_adapters@1` | Contracts + Kernel application services | in-memory repositories、fake runtime/workspace/effect ports | collaboration、authority、lease/fence、runtime command、publication/handoff语义、controlled-operation、显式Task finish；无网络/SQLite/Git/container |
| `openzyme_standard_local_file_sqlite_git@1` | Standard真实Host/SQLite/local Git/LFS/client/Core UI | LLM/provider/process外部端口 | 无extension仍可创建/推进Core事实；schema/composition proof；Git-shaped revision；restart/fencing；默认wheel闭包 |
| `enzymedesign_local_single_process_file_sqlite@1` | EnzymeDesign真实product composition与所有声明extension | LLM/provider/runner/Chrome等登记外部端口 | extension注册/迁移/projection、Science/Execution/AOX现有不变量和跨层组合 |

现有executable architecture invariant registry升级为声明profile、composition bundle和allowed external ports。每个scenario继续同时断言允许结果与禁止的fallback/duplicate effect/task inference/secret disclosure。Kernel profile不能import Standard/extension；Standard profile移除全部extension后必须仍通过其closed场景；EnzymeDesign profile不能用fixture composition替代真实manifest装配。

额外静态/构建门禁包括：

- AST/import-linter验证禁止依赖方向和archive不在active import/test path；
- root/member `pyproject.toml` 与lock metadata验证wheel依赖闭包；
- 从fresh temp environment安装built wheel并检查`METADATA`和wheel contents；
- Kernel/Contracts禁止FastAPI、LangChain/OpenAI、Tavily、Biopython/NumPy/RDKit/Meeko、Podman/SSH/Slurm等依赖或领域import；
- 通用Host/Standard禁止AOX/HMMER/Vina/fpocket/AlphaFold/RDKit/Meeko等垂直symbol；
- manifest/tool/route/projection/worker/migration/qualification catalogs重算digest并验证无冲突、无ambient registration；
- exact extension removal、version drift、digest tamper、session pin mismatch和stale continuation负例；
- current V3 authority、effect certainty、revision identity、runtime/task/scientific/report terminal分离在拆分前后保持。

Qualification报告仍是repository/operator evidence，不进入产品控制面，也不授权live。任何缺失profile、skip/xfail、unproven invariant或source/bundle drift都阻止change completion和cutover receipt。

### 13. 文档是每个实现切片的同步交付物，而不是最终补写项（D13）

每个改变 owner、依赖、public contract、composition、migration、runtime、projection 或部署方式的实现切片必须在同一切片中更新其权威文档：

- `docs/OpenZyme架构设计.md` 维护产品定义、层次、目标依赖图和总 composition；
- `docs/v3/00` 至 `06` 及 execution pipeline、persistence、failure/recovery、compatibility/cutover、complexity audit 等相关稳定文档维护具体 owner、identity、lifecycle、persistence、错误语义、禁止 fallback 和 session split；
- 每个受影响 package/app README 维护安装闭包、公开 imports、entry point、配置、启动和测试命令；
- deployment/operator 文档维护 manifest、离线 migration、rollback/forward-repair、qualification 和不运行 live 的边界；
- OpenSpec delta、source owner matrix、table/import/catalog inventory 和 qualification registry 保存可机器检查的 source-to-doc refs。

阶段验收不得以“代码先合入，文档在最后统一修”完成。测试或审计发现文档仍声称 Core 拥有 Research/Science/HPC/AOX、旧包仍是 authority、`@1` 可 mutation、Host 自动加载插件，或命令/路径已不存在时，对应实现任务保持未完成。最终 drift audit 必须从当前 source/config/manifest/schema 反向核对文档，而不是只检查关键词存在。

替代方案是只在最终阶段更新主架构文档。拒绝，因为这个 change 跨多个阶段，过渡期错误文档会直接指导后续实现重新引入反向依赖，也无法为每个 focused qualification 提供当前 contract。

### 14. 四类 capability fact 分开持久化和求交（D14）

同一个“capability”词不能继续同时代表安装、资源、授权和模型可调用性。Kernel使用四种closed contract：

| Fact | Canonical question | Owner / writer |
| --- | --- | --- |
| `ExtensionCapabilityFact` | 当前deployment/Session激活了什么语义能力 | deployment activation + Kernel registry |
| `ResourceCapabilityFact` | exact target inventory generation实际具有什么软件/硬件/数据/服务 | qualified provider发布，Kernel索引安全事实 |
| `AuthorityGrant` / `AgentAuthorityLease` | 当前Agent在什么scope/generation/fence下被允许做什么 | Kernel authority service |
| `ToolAffordance` | 对当前Session/Agent/turn/workspace/task，此工具和哪些route真正可调用 | Kernel resolver派生，不由Plugin直接写 |

`AgentAuthorityLease` 使用operation-scoped grants，例如 `workspace.fs.read`、`workspace.fs.write`、`workspace.process.exec`、`hpc.workspace.provision`、`hpc.workspace.fs.read/write`、`hpc.workspace.process.exec`、`hpc.scheduler.submit/observe/cancel`。`general`/`executor`可作为签发模板，但lease不再要求capability tuple严格等于一个closed profile；模板变化也不能自动扩张既有lease。

Plugin manifest通过capability ID、contract/version range、required operations和same-target constraints声明`requires`，不得依赖提供方包名。Resolver建立acyclic graph并输出所有满足条件的exact routes；缺失requirement、版本不兼容、same-target冲突、cycle或ambiguous provider都形成typed blocker或activation failure，不会触发local/remote替代。

替代方案是继续把所有信息塞进`AgentStepContext.tool_catalog_digest`或`AgentCapabilityLease`。拒绝，因为authority撤销、target软件升级和Plugin安装具有不同owner、变化频率与恢复规则，混合后无法解释restore或dispatch时的真实世界状态。

### 15. Declared Tool Catalog 与逐turn Tool Affordance分离（D15）

`DeclaredToolCatalog`只由当前Session已激活且contract完整的Plugin manifests与Kernel base tools确定，包含canonical tool name、description、closed JSON Schema、governance、required authorities、capability requirements、Plugin/contract identity。它是低频、Session-pinned contract；optional Plugin未安装时不伪造tool schema，inspection只显示distribution声明的缺失capability。

每个bounded turn前，Kernel用exact Session bundle、`SessionCapabilityBindingRevision`、AgentAuthorityLease、workspace generation/readiness、task/role policy、route inventory/health和approval policy产生`ToolAffordanceSnapshot`。状态至少闭合为：

```text
AVAILABLE
AVAILABLE_WITH_APPROVAL
BLOCKED_DEPENDENCY
BLOCKED_CONFIGURATION
BLOCKED_QUALIFICATION
BLOCKED_AUTHORITY
BLOCKED_PROVISIONING
TEMPORARILY_UNAVAILABLE
HIDDEN
```

只有`AVAILABLE`和`AVAILABLE_WITH_APPROVAL`进入模型function list。`capabilities.inspect`可返回该subject有权知道的declared-but-blocked capability、blocker、required fact和safe route proof；`HIDDEN`从tool list与inspection同时消失。排队或资源繁忙只要scheduler仍接受job，通常仍是AVAILABLE；target明确down、qualification过期或credential provider不可用才阻止dispatch。

Agent对target-bound正式工具必须显式提交`route_id`。即使当前只有一个route，Kernel也不能填充默认值。真正dispatch前重新计算并比较affordance snapshot、authority lease/fence、workspace generation、Session binding、inventory generation、route/driver identity和health；任一漂移返回`tool_affordance_stale`、`effect_certainty=no_effect`、`fallback_performed=false`。已开始的continuation永远绑定原route，不因新route出现自动切换。

Digest分层为：`kernel_contract_digest`、`adapter_bundle_digest`、`extension_bundle_digest`、`declared_tool_catalog_digest`、`route_catalog_digest`、`projection_catalog_digest`、`session_capability_binding_digest`与`turn_affordance_snapshot_digest`。瞬时health observation拥有自己的identity，不改变release contract。

替代方案是把blocked工具仍放入模型列表并让handler返回错误。拒绝，因为这浪费turn且诱导重复调用；同时完全删除blocked事实也拒绝，因为Agent需要低摩擦地知道真实阻塞和可采取的显式动作。

### 16. Target toolchain inventory是结构化、不可变、operator-controlled的资源事实（D16）

HPC/Compute target provider拥有`TargetToolchainInventory`生命周期。每个immutable generation绑定target/profile/provider、qualification policy、生成时间/有效期、environment closure和一组`TargetCapabilityFact`。软件fact至少包含capability ID、semantic version、supported operations、environment/binary digest与`SoftwareQualificationReceipt`；模型权重、数据库、accelerator和license使用各自capability ID而不是塞入软件字符串。

Tool Plugin提供declarative`QualificationSpec`：capability ID、允许版本范围、版本查询、deterministic smoke input、expected result schema、资源/asset/license requirement。HPC Plugin在operator-controlled qualification流程中选择exact target和credential；SSH/Slurm/process Adapter执行probe；Plugin不能在Agent turn中自行SSH或缓存私有探测结论。完整probe stdout/stderr/path只进private diagnostic，Kernel只接收并索引安全fact、version、target、generation、provider、qualification/closure digest与validity。

只有operator/admin能发布inventory generation、撤销qualification或创建新的`SessionCapabilityBindingRevision`。Agent可请求workspace provisioning并从当前binding中选择route，但不能采用新generation。新inventory发布、qualification恢复、软件升级或新route出现都不会自动改变既有Session。qualification过期、health明确down或route contract drift会阻止新dispatch；已发生operation仍按原identity观察/reconcile，不重发到新generation。

现有整体`toolchain_digest`在迁移后保留为结构化inventory closure digest，不再是无法解释的单值。runner wire只携带exact inventory/profile/route identities和执行所需closed事实，不接收Plugin内部对象、Host path或任意inventory payload。

替代方案是每个HMMER/Vina Plugin自己执行`which`/`--version`。拒绝，因为它会复制SSH/credential、产生互相冲突的事实、在每个turn引入外部effect且无法绑定qualification与真实job环境。

### 17. Workspace Runtime统一操作契约，但不合并生命周期owner（D17）

`AgentGitWorkspace`与`ExecutorHpcWorkspace`继续是不同领域对象。Kernel定义最小`WorkspaceRuntimeBinding`投影：workspace ID/kind、Session/owner、local/remote generation、state version、root identity digest、provider/target identity与必要qualification binding；它不暴露Host path、remote absolute root、hostname或credential。四个隔离Port为：

```text
WorkspaceObservationPort  -> status/stat/list/read/hash/HEAD/tree/dirty
WorkspaceFilesystemPort   -> write/mkdir/move/copy/remove/apply-patch
WorkspaceProcessPort      -> bounded argv execution
WorkspaceTransferPort     -> revision sync/rsync/scp/upload/download
```

模型基础工具保持小而closed：`workspace.status`、`workspace.fs.read`、`workspace.fs.list`、`workspace.fs.mutate`、`workspace.exec`；HPC Plugin贡献`hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec`。本地工具不接受`workspace_id`，Host从Session/member/active authority lease/generation解析唯一binding；HPC工具必须接受Host签发的opaque `workspace_id`并重新核对owner、target、local/remote generation、qualification与lease。

Process请求只接受argv array；使用Shell必须显式提交`["/bin/sh", "-lc", ...]`。cwd与filesystem path必须root-relative，拒绝absolute path、`..`、glob隐式扩张、symlink/hardlink escape和Host/runner locator。Filesystem mutation使用closed one-of、idempotency key和create/replace/remove precondition；workspace root或整个remote workspace的删除永远不属于普通`remove`。

所有`workspace.exec`、filesystem mutation和transfer在dispatch前创建durable ControlledOperation。Local Adapter通常在同一request窗口内settle，但response/process loss仍可进入`dispatch_in_doubt`；三个effectful Port都以`reconcile(original_request)`查询同一operation/intent的既有receipt/ledger，Kernel记录`redispatch_performed=false`，没有proof时保持in-doubt，绝不再次调用execute/mutate/transfer。remote Adapter同样必须支持exact observe/reconcile且不得重发。Observation/read不创建effect operation。默认禁止interactive TTY、后台进程和unbounded output；长任务进入formal Compute Plugin。

`workspace.exec`从本change起只执行当前Agent本地workspace，不再签发HPC SSH/login credential。远端探索由`hpc.workspace.exec`完成，login/file credential永不包含scheduler API；`hpc.scheduler.*`只由Compute/HPC formal job boundary消费。Shell/CRUD receipt只说明进程或private workspace mutation，不能自动checkpoint、publish、handoff、adopt或finish。

Transfer request只携带opaque `transfer_ref`、其exact manifest digest、root-relative workspace path、byte budget、deadline与authority/generation/fence；它不能携带URL、Host path、remote locator或任意credential。首个local Adapter以第二个exact Podman named volume作为Adapter-private staging boundary：download/revision source只读，upload destination只在预留object path可写，helper重新计算file/tree content identity后执行create-only atomic copy。`sync_revision`只把Git/LFS Adapter已验证并绑定commit/tree/LFS closure的immutable revision tree物化到Agent显式选择的private子路径，不执行checkout、merge、publication或workspace cleanup。transfer volume reservation、source preparation与durable ref resolver仍分别属于Store/Git-LFS机制，不能由模型构造。

替代方案是让一个万能`workspace.exec(workspace_ref=...)`同时隐藏本地、远端和scheduler治理差异。首轮拒绝；内部SPI统一，但模型工具保留local/HPC namespace直到effect/reconcile与authority差异经过独立资格验证。

### 18. 领域Plugin、Driver、Compute与HPC通过capability route通信（D18）

HMMER/Vina等领域Plugin拥有typed scientific/tool semantics、requirements、qualification spec、command/workload compilation与result parsing/validation。Compute Plugin拥有formal revision-bound execution；HPC Plugin拥有target/workspace/inventory与route；Slurm/SSH Adapter只实现机制。调用方向是：

```text
Agent -> ToolRouter/admission -> Domain Plugin
      -> ExecutionWorkloadSpec -> Compute Plugin
      -> exact resolved route -> HPC/local provider -> Adapter

Adapter observation -> provider receipt -> Compute outcome
      -> Domain result validator -> durable Agent continuation
```

Plugin之间不互相import实现或直接调用service。HMMER manifest可要求`openzyme.compute.revision-job@1`、`software.hmmer`的版本/operation和same-target constraints；HPC、local container或未来cloud provider都可贡献满足条件的route。Driver是Domain Plugin拥有的route-specific compiler/validator，可以单独打wheel，但必须由所属Plugin manifest和Distribution精确激活，不能独立增加顶层state/tool。

正式`enzymedesign.hmmer.build/search`和`enzymedesign.vina.submit`必须生成typed workload并走Compute ControlledOperation。Agent仍可通过local/HPC raw Shell探索、调试或检查文件，但进程回执不能满足Science validator或formal finish evidence。结果留在owner workspace，由Agent检查、显式Git提交/checkpoint/publish；runner不扫描`expected_outputs`，Host不补造结果。

替代方案是让HMMER Plugin直接调用HPC Plugin或Slurm Adapter。拒绝，因为它把领域语义绑到单一部署机制，也绕过route resolution、inventory qualification和统一effect lifecycle。

## Risks / Trade-offs

- **[大 change 容易同时移动过多 owner]** → 任务按Contracts/Kernel、机制、reference extension、通用extension、EnzymeDesign、cutover分阶段；每阶段保持唯一implementation并运行focused gate，最终才激活`@2`。
- **[temporary re-export变成永久第二authority]** → 建立逐symbol ledger、禁止新增caller、设定删除任务和final forbidden-import gate；无仓外消费者，不发布兼容release。
- **[接口抽取把实现细节伪装成稳定contract]** → Contracts只接纳跨领域identity/DTO/port；SQLite/Git/LangChain/FastAPI/provider类型不得穿透；每个候选type用owner/replaceability检查审计。
- **[Git-shaped Kernel contract限制未来backend]** → 明确这是当前V3协议性取舍并在workspace backend identity中版本化；未来多backend需要独立breaking change，不能在本change加入半成品抽象。
- **[扩展raw SQL越权或事务拖长]** → table-owner manifest、namespaced store、SQLite authorizer/wrapper、statement/time budget、无外部I/O的participant协议和rollback tests共同门禁。
- **[extension validator反向控制Task terminal]** → validator只返回typed evidence，只有Task owner的显式`task.finish`命令可触发Kernel terminal mutation，并测试receipt/idle/publication均不能自动完成。
- **[manifest存在但代码或catalog与digest不一致]** → 绑定distribution/version/build、canonical manifest、tool/projection/migration catalogs与wheel contents；startup在writer/effect前重算。
- **[optional Plugin吞掉完整性错误]** → 只允许distribution absent为inactive、合法Plugin资源不足为degraded；manifest/schema/digest/migration/collision/cycle错误一律阻止activation。
- **[capability一词重新混合authority与availability]** → 四类fact使用不同schema/owner/repository/digest；public contract使用`AgentAuthorityLease`且禁止把target inventory塞入lease。
- **[动态affordance在模型选择后漂移]** → turn snapshot只用于展示，dispatch必须重新解析并比较exact route/inventory/workspace/authority；stale为no-effect且不选择replacement。
- **[inventory qualification和真实job环境漂移]** → route绑定exact inventory/environment generation，qualification spec与receipt进入closure；已提交operation永远观察原route。
- **[通用workspace.exec继续成为远端旁路]** → 移除HPC login credential路径，remote exec/fs只由HPC Plugin贡献；scheduler从login/file credential永久排除。
- **[每个Shell/CRUD operation持久化增加负担]** → 只读observation不建ControlledOperation；mutating/exec/transfer使用统一短intent与异步settlement，不在外部调用期间持SQLite事务。
- **[正式领域工具退化为Shell wrapper]** → HMMER/Vina正式工具必须产生typed workload、result validator与formal Compute receipt；raw shell receipt在Science/finish validator中被拒绝。
- **[插件移除导致旧Session silently丢状态]** → Session exact pin、offline classification、unsettled operation/owned rows检查；未知或缺失extension阻止mutation和activation。
- **[`@2`扩展section重新成为无界payload]** → 每个schema closed且带独立budget/pagination/redaction；Core/extension projection catalog统一验证，UI只加载已pin renderer。
- **[UI或CLI继续依赖runtime/全量workspace类型]** → 建立`openzyme-client`，Core UI shell只依赖`@2` Core schema；extension renderer单独注册和测试stale bundle行为。
- **[runner仍通过Domain获得平台内部对象]** → 先抽`openzyme-execution-contracts` closed wire package，再迁runner；wheel test验证没有Kernel/Domain/Host依赖。
- **[旧表不重命名使owner不直观]** → 本change以table-owner manifest和migration bundle明确owner，避免同时做高风险DDL；物理命名规范化留给后续独立change。
- **[offline cutover中途失败]** → activation前exact backup、quiescence、dry run、single transaction和receipt；activation后禁止hidden downgrade，采用forward repair。
- **[架构文档、OpenSpec和source再次漂移]** → implementation tasks要求同步主架构与全部相关V3稳定文档，qualification registry以source-bound关系验证，不把旧报告当current truth。
- **[三种profile qualification成本上升]** → 每个 profile 使用 closed selection 且复用 invariant families；mainline运行bounded subset，final cutover运行全量non-live admission，不能用测试计数或单一E2E替代。

## Migration Plan

1. 完成当前executable architecture qualification基线，冻结component/import/table/catalog/composition/tool/authority/HPC/workspace inventory，并加入双轴依赖门禁但暂不改变runtime行为。
2. 创建`openzyme-contracts`、`openzyme-extension-spi`和`openzyme-kernel`，先建立pure contracts、manifest/contribution SPI、四类capability fact、route/affordance DTO与workspace runtime ports；用临时单向re-export保持仓内分阶段测试，记录全部caller。
3. 建立duplicate/cycle rejection、DeclaredToolCatalog、CapabilityRegistry/Resolver、ToolAffordanceResolver与只读`capabilities.inspect`；先用当前静态工具生成兼容manifest，不自动启用新能力。
4. 把公开`AgentCapabilityLease`迁为`AgentAuthorityLease`并拆operation-specific grants；保留现有物理表名，建立`SessionCapabilityBindingRevision`与dispatch revalidation。
5. 把SQLite、Git/LFS、runtime SPI/LLM、Podman/local workspace runtime和HTTP client迁入各自Adapters/Standard Distribution，保持现有业务表名与terminal语义。
6. 用Research + Tavily Adapter作为Plugin/Adapter reference composition，验证optional inactive/degraded、catalog collision与no-fallback；删除`DeepResearchTaskPlanner`及Core对Research/Engine/Runtime implementation依赖。
7. 建立TargetToolchainInventory/QualificationSpec/Receipt和HPC route provider；迁移远端workspace lifecycle，新增`hpc.workspace.exec/fs.*`，删除local`workspace.exec`的HPC credential旁路。
8. 迁出Reporting、Science、Compute/HPC；让runner仅依赖execution wire contracts，并验证每个Plugin可从Standard Distribution移除。
9. 迁出AOX、bio/HMMER、structure/docking/preprocess、垂直tools/routes/UI/qualification，建立EnzymeDesign Distribution与formal workload Drivers。
10. 实现`file_workspace_public@2` Host/client/UI/event/restore schema和offline cutover工具；不双写或在线翻译`@1`。
11. 构建 fresh wheels 并运行 Kernel、Standard、EnzymeDesign 三种 profile qualification、strict OpenSpec、focused suites、UI tests/build、eval和mainline。
12. 仅在另一次明确cutover授权下执行maintenance/quiescence、backup、dry run、table-owner/Session migration和`@2`activation；普通apply不得执行真实cutover或live qualification。
13. 删除全部temporary shim/old authority和archive import exposure，重新运行source/wheel/manifest/capability/inventory/affordance/qualification gate并生成source-bound completion receipt。

Rollback规则：第9步activation前可恢复exact backup和旧release；一旦`@2`接受canonical mutation，只能停止服务并forward-fix，不能自动降级、重新启用旧writer或将extension state塞回`@1`。任何外部effect处于unknown时，迁移/回滚都不得重发或替代其operation identity。

## Open Questions

以下产品级决策已于2026-08-19由用户一次性确认，不再作为实现阶段的开放问题：

- `0A`：保留当前change ID作为一个总括change，以内部阶段门禁推进；
- `1A`：Standard Distribution的required semantic Plugin set为空；
- `2A`：本change公开更名为`AgentAuthorityLease`，保留首轮物理表名；
- `3A`：optional absent/inactive和resource-degraded可启动，完整性/collision/cycle错误必须阻止activation；
- `4A`：只有operator/admin发布和采用target inventory generation，Agent只选择已绑定route；
- `5A`：local/remote exec、filesystem mutation和transfer进入durable ControlledOperation，`workspace.exec`不再承载HPC SSH；
- `6A`：HMMER/Vina正式运行必须走typed Compute lifecycle，raw Shell只作探索；
- `7A`：继续使用`packages/`与`apps/`作为Python workspace roots。

已确认“无仓外消费者”和“暂时保留Git-shaped revision contract”。其余实现选择必须由现有V3 doctrine的fail-closed、single-writer、explicit finish、no hidden fallback和agent strategy freedom约束得出。

实现阶段仍需通过清点而非产品决策确定三类机械细节：最终逐symbol迁移ledger、现有每张表的唯一owner manifest、以及每个现存Session的`@2`可迁移分类。任何无法唯一归属的项都作为implementation blocker返回，不得由实现者猜测或静默兼容。
