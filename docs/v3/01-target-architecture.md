# V3 Target Architecture

> 本文描述 `separate-openzyme-kernel-from-capability-extensions` 的目标 owner。包根、Client、CLI 与 UI 已切到
> 独立通用 `file_workspace_public@2`；旧 `@1` 只允许显式离线历史 reader 访问。目标 Distribution manifest
> 已可构建 active exact graph 和 isolated fresh proof，但尚未对真实部署执行一次性离线 cutover，因此不得把
> source-level 收口当作 production cutover。

## 两条正交轴

语义所有权轴：

```text
openzyme-contracts / openzyme-extension-spi
                    ↓
              openzyme-kernel
                    ↓
       domain-neutral Capability Plugins
                    ↓
          EnzymeDesign Product Plugins
```

部署组合轴：

```text
Kernel + selected Adapters + selected Plugins + selected Drivers
       + Host/Client/CLI/UI delivery surfaces
       = exact Distribution
```

`OpenZyme Standard` 和 `EnzymeDesign` 都是 Distribution，不是 L2/L4 语义层。Standard required
semantic Plugin set 为空；它选择 SQLite、Git/LFS、本地 process、Agent turn 与 delivery surfaces。
EnzymeDesign 选择自己的 required/optional Plugins 和 Drivers，但不能源码依赖 Standard。

## Component kind 与依赖方向

| Kind | 目标包 | 拥有什么 | 允许依赖 |
|---|---|---|---|
| Contracts | `openzyme-contracts` | 稳定 ID/DTO/failure/tool/capability/workspace Port | Python 标准库 |
| Extension SPI | `openzyme-extension-spi` | Adapter/Plugin/Driver/Distribution manifest 与贡献协议 | Contracts |
| Kernel | `openzyme-kernel` | canonical application state、composition/capability/affordance resolution | Contracts + SPI |
| Adapter | `openzyme-store-sqlite`、`openzyme-workspace-git-lfs`、`openzyme-runtime-llm`、`openzyme-process-podman` | 已有 Port 的机制实现 | 对应 contracts/ports |
| Capability Plugin | `openzyme-research`、`openzyme-reporting`、`openzyme-science`、`openzyme-compute`、`openzyme-hpc` | namespaced state/tools/routes/workers/validators | Contracts + SPI + public Kernel application contracts |
| Product Plugin | `enzymedesign-*` | HMMER、AOX、Vina、序列/结构/前处理等垂直语义 | SPI + 通用 capability contracts |
| Driver | HMMER/Vina local/HPC driver、HPC SSH/Slurm adapters | typed request 到 exact route 的实现 | owning Plugin contract + Adapter Port |
| Distribution | `openzyme-standard`、`enzymedesign` 配置 | exact selection/bundle identity | 所选组件；不拥有 canonical state |

必须禁止：

```text
Kernel -> SQLite/Git/LangChain/Research/Science/HPC/EnzymeDesign
Contracts -> FastAPI/LangChain/provider/scientific/process libraries
Product Plugin -> Host internals/Core repositories/provider implementation
HMMER/Vina -> SSH/Slurm implementation
Adapter -> top-level business entity/tool
```

AOX 的 current/historical workflow contract 与 17-role scientific file contract 已迁入
`enzymedesign-aox`；deterministic calculation modules 位于 subordinate
`enzymedesign-aox-executor` Driver，旧 `openzyme-pipeline` 组件已移除。AOX file-bundle finalizer 也由
Product Plugin 拥有，只消费通用 Science finalization/read ports 和 Distribution 选择的 Driver receipt
validator。Host 仍存在的显式组装 import 记录为 migration ledger，不构成新的允许依赖方向，必须在
EnzymeDesign Distribution mount 完成时删除。

Host 是组合根，不是长流程同步执行线程，也不是状态 owner。Python entry point 只定位纯 manifest；只有
`distributions/*/openzyme-composition.toml` 选择且通过 exact identity/digest/dependency/collision/migration
校验的组件才可激活。未列出的已安装包被忽略，不形成 ambient capability。

本地 Agent workspace 的当前迁移切片已经把 Podman capsule runner、named-volume backend 与 Git restore
observer 的构造放入 `openzyme-standard.StandardLocalWorkspaceAdapterFactory`，并把 volume fact/backend Port
下沉到 Contracts。Git/LFS Adapter 的 provisioning/recovery mechanism 只消费注入的 volume、clone 和 observation
Ports，返回 volume identity、完整 observation 或 typed blocker，不访问 Core repository。Host 只声明窄 factory Protocol
并重验 configured binary/network identity；配置存在但 factory 未注入、或 identity 漂移时在 surface 创建前失败。
repository 侧也由 `StandardRepositoryAdapterFactory` 冻结 exact settings/root-boundary，并构造 durable roots、
binding mechanism、revision backend、workspace recovery 与 credential issuance；Host 不再派生 Git/LFS locator
或实例化这些具体机制。LLM 侧由 `StandardLlmAdapterFactory` 构造 exact runtime/provider；generic Host 不实例化
LangChain/provider。Store factory、deployment epoch 与 application writer 已在 Standard target composition 闭合；
这不表示真实历史 deployment 已执行离线 adoption/cutover。

当前 loader 已实现 closed TOML/JSON、duplicate-key 和 canonical digest 验证，并能在不执行 editable `.pth`
代码的情况下读取 selected package resource。Adapter bundle 对 slot/target binding 做 canonical 排序；
Extension、declared tool、capability route、HTTP route、projection、worker、validator、schema、migration、
transaction participant 与 qualification catalog 各自重算 digest。HTTP runtime 额外逐项匹配 owner、method、
normalized path 与 contract digest；GET query runtime 不能获得 mutation authority。`openzyme-process-podman` 是首个带真实
locator/resource 的 Adapter。两个 Distribution manifest 已是 `active`，只表示 exact graph 可构建；Standard
Host 构造必须消费 startup proof/epoch，真实历史 deployment 未执行离线 adoption，因而仍不构成实际 cutover。

上述规则由
[`architecture/component-boundary-policy.json`](architecture/component-boundary-policy.json) 与
`scripts/check-openzyme-architecture.py` 从每个 wheel metadata、AST imports、source vocabulary、
Distribution selection 和 active test roots 联合验证。当前 active workspace 不含 `legacy_mixed_active`
组件；所有 target component 与 active Distribution 立即受门禁。Adapter 注册
`ToolContribution`、错误 component kind、Standard 被依赖成语义层、间接实现依赖或 historical root
重新进入 active import/test/entry-point 都会失败。

所有 `component_kind=product_plugin` 还会继承同一组反向依赖禁令，而不是只为当前 HMMER/Vina
逐包维护名单。当前或未来 EnzymeDesign 产品插件只要在 AST 中导入旧 Core/Domain、Kernel 实现、
SQLite Store、Host 内部模块、Git/LFS Adapter、HPC/SSH/Slurm 实现或私有 runtime/process 实现，
检查立即失败；wheel gate 也拒绝这些 implementation distributions 出现在 `Requires-Dist`。产品插件
只能消费 Contracts、Extension SPI、capability/product contracts 与公开 Port contracts。

`scripts/qualify-openzyme-contract-wheels.py` 另在 checkout 外构建工作区 wheelhouse，并从已经由 lock
固定且本机缓存命中的第三方 wheel 闭包离线安装 Standard Git/LFS transport 所需的
FastAPI/Pydantic，以及 AOX Driver 所需的 `biopython==1.87` 与 `numpy==2.4.4`；缓存缺失时资格检查
直接失败，不允许联网补齐。脚本分别创建五个无网络独立
venv：`contracts_spi_only`、`kernel_only`、`standard_only`、`runner_only` 和
`enzymedesign_component_set`。每个 wheel 的 `METADATA Requires-Dist` 必须与 member pyproject 的 runtime
依赖完全一致；每个 venv 的 OpenZyme/EnzymeDesign distribution set 必须等于重算依赖闭包，且任一
`openzyme.extensions` entry point 的 owning distribution 必须属于该闭包。profile 逐一拒绝禁止的第三方
或能力 distribution；import 期间
SQLite/network/process I/O 被拒绝。EnzymeDesign profile 显式拒绝旧 `openzyme-core`、`openzyme-domain`、
`openzyme-runtime` 和 `openzyme-tools`；Standard profile 则证明没有隐式 Research/Reporting/Science、
Compute/HPC、runner、Tavily、EnzymeDesign 或生物/对接依赖。

Science 包具备 exact manifest、runtime contribution bundle、Kernel-admitted restricted participant
写路径与通用 workflow contract registry；旧 lifecycle/repository/Host `@1` caller 已删除。组件的
`target_implemented_not_cutover` 表示真实历史部署尚未执行离线 cutover，不是 activation 许可。详情见
[Science Extension](science-extension.md)。
该验证只证明 wheel content/install/import closure；即使 Distribution manifest 为 `active`，也不授予运行
authority。

目标 Kernel 已实现 deployment activation/session pin 的纯机制层：`DeploymentActivationCoordinator` 要求
composition、core schema、installed wheels 三类 no-effect verification；`DeploymentActivationGate` 在成功前
封锁 writer/route/worker/runtime/effect；`SessionCompositionService` 原子提交 Session、composition pin 与
initial capability binding；`SessionCompositionGuard` 对 message、drain、approval、tool、workspace、publication、
operation、restore 使用同一 bundle/binding 检查。runtime contributions 由 `mount_extension_surfaces` 全量
exact-match 后一次性返回，不存在 partial registration。Plugin upgrade/removal verifier只做 quiescent offline
preflight，不执行 migration。两个 Distribution 已通过结构 activation 与 isolated fresh proof；通用
`create_v2_app()` 只消费注入的 exact surface、Kernel command gateway 和已挂载 Plugin GET runtimes，不 import
Science/HPC/SQLite/runtime implementation。Standard target composition 已采用这些入口；真实历史部署是否
cutover 仍只由 offline migration/activation receipt 证明。

## 跨层与同层通信

- Kernel 调用 implementation-free Port；Adapter 返回 typed receipt/outcome，不能直接写 Kernel tables。
- Plugin 通过 narrow Kernel application service 发 command/query，不获得 raw SQLite、repository provider 或
  Host 私有对象。
- Kernel 不 import Plugin runtime；Plugin 通过 manifest 贡献 tool、capability、route、qualification、
  projection、worker、finish validator、schema/migration participant。
- Plugin 之间按 capability requirement 和 typed contract 通信。Resolver 返回 exact route，consumer 不
  import provider 包。
- Adapter 之间不分享内部 client；由 owning service 编排多个 Port，或由明确声明的 aggregate Adapter
  实现复合 Port。
- Driver 必须隶属于一个 Plugin，不能脱离 owner 激活或做隐式 route fallback。

共享文件只跨 `PublishedRevision + RevisionPathRef` 边界；external effect 只跨 durable
`ControlledOperation`/formal Compute boundary。任何进程退出、文件存在、provider response、Plugin receipt
或 scientific closure 都不能替 Task owner 完成 `task.finish`。

## 四类能力事实与工具目录

四类事实不能互相证明：

1. `ExtensionCapabilityFact`：Distribution 实际激活了哪些语义能力；
2. `ResourceCapabilityFact`：某个 target inventory generation 上有哪些软件、硬件、数据、资产或 license；
3. `AuthorityGrant` / `AgentAuthorityLease`：某 Agent 当前被允许做什么；
4. `ToolAffordance`：在 exact Session/member/turn/binding/workspace/health 下工具是否真正可调用。

Plugin 顶层 resource requirement 可以表达产品支持闭包；当不同 Driver/target 采用不同但明确受支持的软件合同时，
每个 `RouteContribution` 还必须声明 owner-local exact resource requirement。Kernel 只为 Session 已绑定 target 且其
inventory fact 同时满足 route 的 contract、operation 与 version spec 时生成 `RouteRef`。route requirement 漂移只
产生该 route 的 `blocked_qualification`，不得运行时探测后改写 argv、选择相邻 Driver、切换 target 或 fallback。

`DeclaredToolCatalog` 由 Kernel base tools 和已激活 Plugin manifests 决定并固定 contract digest；每个 bounded
turn 再生成 `ToolAffordanceSnapshot`。模型 function list 只含 `AVAILABLE` 与
`AVAILABLE_WITH_APPROVAL`；blocked 工具仅通过安全 `capabilities.inspect` 查看原因；`HIDDEN` 对两者都不可见。

dispatch 必须重新验证 snapshot、authority lease、workspace generation、capability binding、health 和
explicit route。任何漂移返回 `tool_affordance_stale`、`effect_certainty=no_effect`、
`fallback_performed=false`；continuation 保留原 route，不自动迁移。

静态目录不等于运行时已经可调用。Host 在 deployment activation 后必须建立
`MountedRuntimeToolSet`：Kernel base runtimes 与 Plugin runtime bundles 先各自保持 owner 边界，再合并并逐项
匹配 active catalog 的 owner、runtime ID 与 contract digest。Plugin-free Standard 因而表现为“零 Plugin
runtime + 五个 Kernel base runtime”，而不是空 runtime 或把 Kernel 包装成一个隐式 Plugin。

## Repository 与 Workspace Runtime

Kernel 保留 Git-shaped identity：project repository binding、Session pin、workspace generation、checkpoint/
publication intent、immutable `PublishedRevision` 与 `RevisionPathRef`。`openzyme-workspace-git-lfs` 实现实际
Git/ref/LFS/byte verification、Gitless compute tree、exact-base clone 与 typed restore observation
mechanism；clone 只消费注入的 command port 和进程作用域 credential，重验独立 Git identity，secret 不进入
argv/receipt；restore probe 只读分类 permission/corruption/base drift/infrastructure，不 repair/replacement。
Adapter 还拥有 durable root confinement、bare repository identity/base/ref、pre-receive hook、private ref
派生、agent/publication/historical ref ACL/owner update 与 LFS object actual-byte store；旧 Core 已删除这些
Git/filesystem/subprocess/ref-policy 实现和顶层 re-export。LFS policy/session/closure/read/retention/GC receipt
repository 也由 Adapter 实现，并由 Store/UoW 注入 fenced commit，因此不能自行形成事务权威。closed repository
credential 与 read-only provision credential 的 claims/schema/error contract，以及 key/HMAC/envelope
material，也由 Adapter 唯一实现；普通与 provision credential token/issuance-ledger mechanism 均已由 Adapter
实现且不自行 commit；旧 brokers 仅保留 authority/pending-workspace admission 与 Store UoW 协调。Git smart HTTP/LFS
Batch transport mechanism 也已迁入 Adapter，并只消费 Host 注入的认证、repository scope、root manager 与 preflight
receipt Ports；binding endpoint/base/pinned commit/default HEAD 验证实现 `RepositoryBindingMechanismPort`，Kernel
只编排 binding/Session pin canonical mutation；Host 不再拥有 CGI streaming 或 LFS object routes。checkpoint
compatibility service 与 publication 只读查询也只消费 `WorkspaceRevisionBackendPort`，不再读取 raw ref、执行 Git 命令或
构造 remote receipt；clean status parser、create-only dispatch、response-loss reconcile 与 namespace observation
均由 Adapter 拥有。LFS pin/GC composition writer adoption 仍未 cutover。当前 change 不引入其他
workspace backend，也不拆 Git repository。

`.gitattributes`/pointer/whole-tree closure validation、immutable object-read receipt、private reachability
finalization 与 receipt-bound GC 已由 Adapter 通过窄 repository bundle/UoW Port 实现。这里的成功回执只证明
对应 Git/LFS mechanism，不代表 publication、scientific adoption 或 Task completion；现阶段仍待完成的是
production composition application writer adoption。
native Git/LFS Batch API/credential non-persistence 与 Gitless compute qualification 也由 Adapter 唯一实现，
不再由旧 Core 提供 schema 或 validator re-export。
private namespace open/hold/close、receipt-before-delete、whole-generation reachability 与 exact ref retirement
同样由 Adapter 实现；旧 Core composition factory 只注入 fenced commit 与 transaction-depth observer。

Workspace Runtime 使用窄 Port：

- `WorkspaceObservationPort`：status/stat/list/read/hash，query-only；
- `WorkspaceFilesystemPort`：write/mkdir/move/copy/remove/apply-patch；
- `WorkspaceProcessPort`：exact argv、root-relative cwd、authority generation/fence、process epoch、bounded
  stdin/stdout/stderr/timeout 与 content-bound result；Podman Adapter 实现该 Port并由 Standard 显式选择；
- `WorkspaceTransferPort`：manifest-bound opaque `transfer_ref` 的 revision sync/upload/download 等批量移动；
  不能接受 Host path/URL，也不能替代 publication 或 workspace cleanup。

这四个 Port 与 `ProcessIsolationPort` 都有 implementation-free contract ID/digest；Adapter manifest 声明它
实现的 exact Port contracts，Driver activation 只能引用 Distribution 已选 Adapter 实际提供的 Port。
具体 Adapter 可以依赖 owning Plugin 对外发布的窄 Port contract，例如 Slurm Adapter 实现 HPC
Plugin 的 scheduler port；该依赖不得穿透到 Plugin application service、repository、worker 或 Host
composition。source-bound checker 只为逐组件审查过的 contract-only 边界开放显式例外，不能把
`Adapter -> Plugin` 普遍放开。

当前 `openzyme-process-podman` 已实现本地 Observation/Filesystem/Process/Transfer Ports 的独立 Adapter
资格切片：helper source digest 固定、容器网络关闭、路径与 CAS 在 Adapter 内再次验证。Transfer 使用第二个
exact named volume 作为 Adapter-private staging boundary：download/revision source 只读，upload destination
可写；每次操作绑定 transfer manifest、content/size（已知时）、byte budget 与 deadline，采用 create-only
atomic copy，并可用 exact content 在 response loss 后重放同一请求。`sync_revision` 只物化由 Git/LFS Adapter
预先验证的 immutable tree 到显式子路径，不 checkout、merge、publish 或清理 workspace root。上述实现尚未
挂到 Standard 的 exact runtime/tool mount；transfer volume reservation、Git/LFS source preparation 与 durable
resolver 由 selected Store/Git Adapter 提供，缺失即 fail closed，Git publication 始终是独立边界。

mutation、exec 和 transfer 都进入 durable ControlledOperation；observation 不写状态。Local 与 HPC workspace
保留不同生命周期对象，只统一为 `WorkspaceRuntimeBinding`。local Agent tool 的 binding 由 Host 从 current
Session/member/generation 推导；remote tool 接受 opaque workspace ID，永不接受 hostname/login/root。

## Compute、HPC 与领域工具

`openzyme-compute` 拥有 revision-bound formal workload、dispatch/observe/reconcile/cancel/result；
`openzyme-hpc` 拥有 target、immutable toolchain inventory、executor workspace、credential 与 routes；
`openzyme-hpc-ssh` 和 `openzyme-hpc-slurm` 实现 remote workspace 与 scheduler Ports。login/file credential
永不包含 scheduler authority。

HMMER/Vina Plugin 声明 software capability/version/operations/same-target requirement，并把正式请求编译成
closed `ExecutionWorkloadSpec`。操作员在 exact target/environment 上执行 qualification、发布 inventory，
再显式为 Session 创建 binding revision。Agent turn 不 SSH 探测软件、不采用新 generation。直接 Shell
运行只产生 exploratory process receipt，不能成为 formal Compute/Science/publication/Task evidence。

UniProt、RCSB 与 InterPro 使用另一条同样显式的产品依赖链：`enzymedesign-core` 定义
`enzymedesign.bio-provider@1`，`enzymedesign-bio-providers` 提供三项 capability 与 exact HTTP routes，
`enzymedesign-bio-provider-adapters` 实现网络机制。Sequence Tool Pack 只依赖 capability ID，不 import
Adapter；Adapter 不注册 Agent 工具、不拥有产品状态。Provider 响应或下载 bytes 仍只是私有输入，必须由
Workspace application service 显式写入、提交和发布后才形成共享 revision/path。

`enzymedesign` Distribution wheel 打包与 `distributions/enzymedesign/openzyme-composition.toml`
逐字段相等的版本化组合，直接选择 Kernel、Adapters、Plugins 和 Drivers；它不 import 或依赖
`openzyme-standard`。当前 30 个 exact component locator 均可离线解析，manifest 已为 `active`，
但闭包验证成功不代表 Host 已 cutover 或任何 live Provider/HPC 可用；这些仍需 exact
startup proof、deployment epoch 与另行的 live qualification。

## Public projection 与 persistence

当前源码唯一的在线公共合同是 `file_workspace_public@2`；旧 mixed composition 已删除，`@1` shape 只允许由
显式 offline historical reader 在后续获权 cutover 中解释，不存在尚待迁移的普通仓内 caller，也不允许
Host/Client/CLI/UI 回退。现行 `001_file_workspace_final.sql` 的代码 owner
已迁为 SQLite Store，但真实部署尚未 cut over。`file_workspace_public@2` 使用 closed `core` section 与
`extensions[plugin_contract_id]`；公开 authority 只叫
`AgentAuthorityLease`。首轮保留 `agent_capability_lease_*` 物理表名，并由 store mapping/ledger 证明语义映射。
通用 Host 已加入由 Distribution 显式注入的候选 `@2` workspace inspection surface；它只消费 layered release、
Kernel core query provider 与 exact projection contributors，不构造 Plugin 或 Adapter。该 surface 缺失或 identity
漂移时 fail closed，且不翻译到 `@1`。Standard 已实现真实 provider：SQLite Adapter 用
`openzyme_store_kernel_entity_versions.session_id` 的 bounded index 找 identity，再由 exact target codec 从 owner
table 重建并校验 record；Kernel 选择 Session subject、authority、latest capability binding、workspace readiness，
生成 closed Core 与 affordance。Distribution 把该 provider 和 verified empty Plugin mount 注入 Host，Host 不反向
依赖 Standard。Standard 已把 Session bootstrap、Task/Lane/Agent、Protocol、Approval、AgentAuthorityLease 与
message ingress 通过真实 gateway 接到 target SQLite，并组装为通用 `@2` Host；message 只形成 conversation、
user-kind inbox 与 pending signal。runtime/workspace/publication 的其余 route、event/restore/continuation 收口和
真实 offline activation 仍属于 cutover 前的未完成工作。

SQLite 是 control-plane persistence Adapter；项目 Git 是文件内容真值。所有现有表、索引、触发器和外键的
目标 semantic owner 由 [`architecture/table-owner-manifest.json`](architecture/table-owner-manifest.json)
唯一解析，不在本 change 顺便重命名业务表。

## 当前 source-bound 门禁

[`architecture/source-bound-baseline.json`](architecture/source-bound-baseline.json) 固定实际 component/import
graph；[`architecture/catalog-owner-inventory.json`](architecture/catalog-owner-inventory.json) 从 active source、
manifest、Distribution 与资格 registry 重算 tool、route、event、projection、worker、schema、migration、
Driver、pytest marker 和 qualification scenario 的 owner/count/digest；
[`architecture/source-document-traceability.json`](architecture/source-document-traceability.json) 绑定 owner、源码、
文档和测试。当前 catalog 基线的 duplicate authority 集合为空：旧 harness 对 Reporting、Science、HPC 与
本地 workspace 的工具表面只投影 canonical Plugin/Kernel ToolSpec，不再复制声明。旧 function handler、
repository writer 或 Host composition 仍可能处于迁移期；catalog 唯一所有权不等价于 runtime cutover。
工具 observer 同时读取源码中的直接声明与纯 JSON Plugin manifest；动态 helper 生成的 ToolSpec 不能因 AST
中没有字符串 literal 而逃离 catalog closure。二者同 owner 时合并 source refs，跨 owner 时 fail closed。

[`architecture/pre-split-deployment-state-inventory.json`](architecture/pre-split-deployment-state-inventory.json)
是 2026-08-20 对操作员指定 SQLite locator 的 `mode=ro + query_only` 快照。该快照只记录 schema proof、
聚合 row count、WAL、未终结 Session/continuation/effect 和 owner 分布，不读取业务 row body 或 secret；当时分类
为 `fresh_empty_candidate`，但该结论既不证明 `file_workspace_public@2` 已 cutover，也不证明 Plugin、Provider
或 HPC 可用。运行：

```bash
uv run python scripts/check-openzyme-architecture.py
```

该 gate 只证明当前迁移基线和已实现 seam 一致，不替代三种最终 Distribution profile qualification、
`./scripts/check-mainline.sh` 或另行授权的离线 `@2` cutover。
