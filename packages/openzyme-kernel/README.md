# openzyme-kernel

这是 OpenZyme canonical Kernel 的实现包。它拥有协作真值、authority、受控外部效果、运行时协调、
不可变 revision handoff、显式组合、能力目录和工具可调用性解析；它不依赖具体 Adapter 或 Plugin。

本包当前提供：

- required/optional Plugin 的显式 activation 与 exact manifest 验证；
- Distribution parser/locator 之后的 all-or-nothing composition activation：同一 Adapter 的 target-scoped
  bindings 分别进入 bundle，ambient locators 被记录但不读取/挂载；Driver 必须同时匹配 owning Plugin
  capability contract、selected Adapter Port 和 exact route；
- `ExtensionBundleRegistry`/`CapabilityRegistry` 与 package-independent dependency graph，拒绝
  missing/incompatible/ambiguous/cyclic capability；
- collision-safe `DeclaredToolCatalog`、capability `RouteCatalog`、normalized `HttpRouteCatalog`，以及 projection、
  worker、finish-validator、schema、migration、transaction-participant、qualification 的独立 catalog/digest；
- operator/admin-only 的 immutable `SessionCapabilityBindingRevision` publish/adopt/revoke 状态机；
- 基于 Plugin、resource、authority、workspace、task/role policy、route 与 health 的
  `ToolAffordanceResolver`；
- model function list 过滤、secret-safe `capabilities.inspect`、explicit route admission 与 dispatch/
  continuation exact route proof 重验。
- `WorkspaceOperationCoordinator`：只读 observation 直接经 authority + exact Observation Port；filesystem
  mutation、process exec 与 transfer 在任何 Adapter dispatch 前先持久化通用 `ControlledOperation`
  admission，随后按 exact provider Port settle 或进入 reconcile。未知 Adapter 异常保留 cause chain，
  `dispatch_in_doubt` 不重试、不换 provider/target/route，也不推断 publication 或 Task terminal。显式
  reconciliation 复用原请求并只调用 Port 的 `reconcile`，记录 `redispatch_performed=false`；无 terminal
  proof 时保持原 operation 不确定。
- `mount_runtime_tool_set()` 先把 Kernel base runtimes 与已通过 manifest 校验的 Plugin runtimes 合并成
  exact、digest-bound 的运行时闭包；它逐项重验 owner component、runtime ID、tool contract 和 active release
  catalog，缺失、多余、collision 或跨 activation mount 均在 runtime 开放前整体失败。Kernel runtime 使用
  `owner_component_id`，不会为了复用 Plugin SPI 而把 Kernel 伪装成 Plugin。
- `MountedRuntimeCapabilityGateway`：从 exact command scope 读取同一 declared catalog、affordance snapshot 和
  current capability context；模型只看到 snapshot 中可调用的 `ToolSpec`。每次 tool request 在调用 mounted
  exact mounted Kernel/Plugin runtime 前重验 Session/member/snapshot/binding/lease/workspace/health/policy/route，
  并再次核对 owner/runtime ID/contract；stale 以
  `no_effect`、零 fallback 拒绝。runtime 未挂载时 fail closed；runtime 抛出异常或返回错 receipt identity 时
  保留 `dispatch_in_doubt`，不自动重试或替换 route。
- 五个 closed base runtimes：`workspace.status`、`workspace.fs.read/list/mutate` 与 `workspace.exec`。
  它们通过 Host 的 `LocalWorkspaceToolContextResolver` 从 current Session/member/authority/generation 解析唯一
  local binding；schema 与 runtime 都拒绝 caller-supplied `workspace_id`、credential、target 或 remote locator。
  effectful call 从 exact tool call 派生 operation/idempotency identity，再进入上述 Coordinator；raw receipt 明确
  标注没有 checkpoint/publication/cleanup/Task transition。
- `RuntimeTurnCoordinator`：从 claimed signal、current SessionRuntimeLease、layered release、exact
  SessionCapabilityBindingRevision、ToolAffordanceSnapshot、selected runtime Adapter 与 bounded budget 构造
  immutable command。Adapter outcome 必须逐项回显 Session/agent/member/turn/signal/lease/fence/process epoch；
  Kernel 通过原子 repository Port once-only consume，并把 continuation delivery 与 runtime settlement 写成
  两个 typed outbox intent。duplicate outcome 不重新运行 Adapter，cross-Session/wrong-member/late epoch 或
  budget drift 在消费前拒绝，settlement contract 不含 Task terminal mutation。
- `ControlStoreRuntimeOutcomeRepository` 提供该 repository Port 的 Kernel-owned 实现：Host 必须先把 exact
  `RuntimeTurnCommand` 与 current claimed signal、Session lease generation/fence、AgentMember process epoch
  做 CAS 注册，才能调用 Adapter；outcome consumption 再次重验同一组 current facts，并在一个 Unit of Work
  中 once-only 写 consumption、signal settlement、可选 continuation intent、runtime settlement event/outbox。
  duplicate exact outcome 返回 duplicate，另一个 outcome 或 late epoch/fence 无 canonical effect；该事务不读取、
  不创建也不更新 Task。
- `RuntimeCoordinationKernelApplicationService` 是 `SessionRuntimeLease` 与 `AgentRuntimeSignal` 的目标唯一
  owner。lease acquisition/heartbeat/release 使用 exact owner/token/generation/fence；signal enqueue 绑定目标
  member process epoch、`AgentAuthorityLease` digest 与 workspace generation，claim 只接受 pending 或已过期
  claimed occurrence，且 runtime lease 与目标 authority 任一漂移都以零 mutation 失败。

HMMER 等领域 Plugin 只声明 capability/operation/version/same-target requirements；Kernel 把它们与
Session 已采用 inventory、HPC/Compute 提供的 route 和 Agent authority 求交。返回的
`ToolDispatchAdmission` 固定 route/driver/target/inventory/proof digest，不自动选唯一 route，不在
continuation 中迁移 route。

Activation 不存在 last-write-wins：single-valued capability provider、canonical dotted tool、capability/HTTP
route ID、`METHOD + normalized path`、projection、worker、validator、schema、migration、participant、
qualification、Driver ID 或 state namespace 的任一冲突都会在 surface mount 前拒绝整个 composition。
required 缺失失败；optional wheel 缺失是 `inactive`；合法 manifest 只有 resource route 尚未绑定时为
`degraded`。optional 的 version/digest/schema/migration/cycle 漂移仍然失败，不能被降级吞掉。

Kernel 现已提供 fail-closed deployment/session 边界：

- `DeploymentActivationCoordinator` 只接受 composition、core schema、installed wheel set 三份
  `ReadOnlyDeploymentVerification`。每份 proof 都强制 no-mutation/no-effect/no-fallback；全部通过后才创建
  immutable `DeploymentActivationEpoch`；
- `DeploymentActivationGate` 在 epoch 之前拒绝 repository writer、HTTP route、worker、runtime 与 external
  effect，并禁止进程内 hot activation；
- `SessionCompositionService` 用一个 repository call 原子创建 Session、`SessionCompositionPin` 与 revision 1
  capability binding；pin 固定 layered release、Driver/HTTP/contribution catalogs 与 Host/client epoch；
- `SessionCompositionGuard` 为 message、drain、approval、tool、workspace mutation、publication、controlled
  operation 和 restore 提供同一 fail-closed admission。drift 只返回 typed upgrade-required，operation callback
  不可达；新 inventory 可产生 monotonic binding revision，但不能改 Extension bundle；
- `mount_extension_surfaces` 在返回任何对象前 exact-match Plugin tool/route/HTTP route/projection/worker/
  validator/transaction participant runtime set，拒绝 ambient bundle、partial surface、Host internal runtime 与
  cross-owner Driver；
- `ExtensionStateKernelApplicationService` 是 namespaced Plugin mutation 的统一 admission：它把 manifest 中的
  participant owner 与 mounted runtime exact-match，随后重验 Session composition pin、Extension bundle、
  capability binding 和当前 authority generation/fence，最后才经 Store Adapter 的
  `ExtensionTransactionCoordinatorPort` 执行。Kernel 和 Plugin 都不接触 raw SQLite 或 `CoreRepositories`；
- `verify_offline_plugin_change` 只读检查 quiescence、non-terminal Session/continuation、owned state disposition、
  migration plan 与 unsettled operation；它不执行升级、删除或 cutover；
- `observe_composition_failure` 生成同一 diagnostic identity 下的公开安全 failure 与受保护 diagnostic。公开
  facts 不含 Host path/secret/traceback，且固定 `no_effect`、零 mutation、零 fallback。
- `assemble_file_workspace_public_v2` 只从 closed Kernel core payload 与 exact authorized
  `ProjectionContributor` 组装 namespaced public projection，对 runtime/contract/cursor 漂移、重复 section、
  section/global byte budget 和 credential/Host/HPC private fields fail closed。Core 每个 section 的
  object/array kind 及递归 forbidden vocabulary 也由 Contracts 校验；旧 lease alias 或 Plugin-owned field
  不能藏入任意 Core nested payload。
- `MessageIngressKernelApplicationService` 在单一 UoW 中校验 Session CAS、root Agent authority、workspace
  generation/process epoch 与可选 Task/Lane scope，随后写 canonical conversation、user-kind inbox 和 pending
  `AgentRuntimeSignal`。source user 与 admitted-by Agent 是两个显式身份；该服务不调用 runtime、不改变 Task。
- `build_public_tool_reflection` 要求 affordance snapshot 对 declared catalog 每个工具精确分类，
  只公开 non-hidden affordance 并与 Session capability binding digest 绑定。
- `KernelPublicWorkspaceProjectionService` 通过 `KernelRecordQueryPort` 直接读取 target canonical records，选择
  exact Session subject/root Agent、active `AgentAuthorityLease`、latest binding 与 local workspace readiness，再由
  active Distribution 提供的 `CapabilityRegistryResolverPort` 生成稳定 affordance snapshot 和 closed Core section。
  它不 import SQLite、不调用 `@1` projection/repository、不在线翻译 Plugin 数据；未 provision workspace 使用
  generation `0` 且所有 workspace-required tool 保持 blocked，而不是补造 ready workspace。
- `FinishValidatorRegistry` 从 exact mounted Plugin surface 构造 closed validator set，只运行 Task 上固定的
  validator ID 并聚合只读结果；missing、collision 或 identity drift 都 fail closed。`TaskKernelApplicationService`
  只在 owner 提交显式 `task.finish`、exact AgentAuthorityLease generation/fence 仍有效且全部 validator 接受后，
  才用 Contracts `ControlStorePort` 在同一 Unit of Work 写 Task terminal、Session version、durable event 与 outbox。
  普通 `task.update` 不能携带 terminal status，validator/receipt 本身没有 Core 写句柄，也不会完成 Task。
- Port-backed application services 已为目标 `@2` 写路径实现 collaboration、Protocol、Approval、Authority、
  Continuation、Failure、TaskEvidence 与 generic ControlledOperation reducer。它们只消费 Contracts UoW/read/
  clock/id Ports：delegation/send/handoff 原子创建 inbox+wakeup 而不运行 recipient；Approval resolution 不 dispatch；
  Continuation 注册时由 Kernel 从 canonical active AgentMember 固定 process epoch，delivery/fail 重验该 epoch 与
  source version；Failure 保留 effect certainty；EvidenceRef 必须先 immutable register，
  read-only validation 和 receipt 都不完成 Task。ControlledOperation 保持一个 operation identity、dispatch generation、
  no-effect/in-doubt/effect-known/terminal-known、explicit reconcile 与零 fallback，并把 idempotency receipt 与
  event/outbox 同事务写入。effect-known 保持 active/可观察；approval admission 重验 exact intent 与 expiry，cancel
  intent 与原始 operation intent 分离。
- `AgentAuthorityLeaseKernelApplicationService` 是 authority issue/supersede/revoke 的唯一 reducer。新 root lease
  从 generation 1 开始；有 parent 的 successor 必须对 active parent 做 exact state-version CAS，并同时将 parent
  推进为 `superseded`；revoke 重建全部 operation-specific grants，使 grant 与 lease 一起递增 generation/fence。
  issuer authority、目标 member、Session、idempotency identity 任一不匹配时不创建 partial child 或事件。
- `SessionBootstrapKernelApplicationService` 处理唯一的 pre-Session authority 缺口：先调用 Contracts
  `SessionBootstrapAuthorityVerifierPort` 重验短时 operator authorization，再在同一 ControlStore UoW 中
  create-only 写 Session、master AgentMember、generation/fence 1 root AgentAuthorityLease、revision-1
  SessionCapabilityBindingRevision、immutable SessionCompositionPin 与一个 durable event。authorization 绑定
  root lease/pin/binding digests；过期、拒绝、identity drift 或任一 owner conflict 全部零 mutation。普通
  collaboration `CREATE_SESSION` 明确返回 `session_bootstrap_command_required`，bootstrap 不运行 runtime、创建
  workspace/Task 或采用 inventory。当前 Kernel + SQLite focused path 已通过；Standard 已将真实 provider 接到
  generic Host `FileWorkspaceV2HostSurface`，但完整 Host mutation caller cutover 仍待完成。
- `PublicationKernelApplicationService` 是 checkpoint/publication/path verification 的目标唯一应用 owner。
  `VERIFY_CHECKPOINT` 用 pinned repository binding、workspace generation、authority 与 Adapter private-ref
  observation 形成 immutable checkpoint；`PUBLISH` 明确分成 `admit` 和 `materialize` 两个 phase。admit 只冻结
  whole-tree intent；Git create-only ref dispatch 必须由同 intent digest 的 generic ControlledOperation 完成；
  materialize 只接受 `terminal_known + mutation_applied=true` 的 exact operation，再调用
  `WorkspaceRevisionBackendPort.observe_publication` 观察而不重发，并原子写入 `PublishedRevision`。路径验证从
  PublishedRevision 与 Session pin 重建 exact identity。三个 phase 的命令使用通用 `resource_id` 分别指向
  checkpoint、publication 或 path-ref，所有记录与 command receipt 都是 create-only。
- `WorkspacePublicationCoordinator` 把 publication 的 create-only Git effect 接入上述两个 Kernel owner：它先
  从 exact Session pin、workspace binding/generation、verified checkpoint、current authority 与 Adapter
  `observe_commit`/`observe_manifest` 结果构造确定性 publication/intent/operation identity；Git/LFS manifest
  policy 失败必须明确成为 `no_effect`，不能冻结 partial intent。随后它 admit frozen intent 和 generic
  `ControlledOperation`，在调用 `WorkspaceRevisionBackendPort.dispatch_publication`
  前把同一 operation 持久化为 `dispatch_in_doubt`，因此进程在 effect boundary 任一点退出后都不会把重启误判为
  可重新 dispatch。Adapter 返回丢失、receipt 不匹配或暂时不可观察时只能调用
  `reconcile_publication` 观察同一 execution/dispatch-generation/fence/receipt identity；不得 retry 或替换 route。
  首次 admission 与 dispatch 必须持有 current AgentAuthorityLease。operation 已进入 `reconcile_required` 后，lease
  即使被 revoke，仍允许原 Session/actor/Plugin/lease generation/fence/route identity 完成 observation、terminal
  settlement 和 `PublishedRevision` materialization；这不是新 authority，任何 identity drift 仍在 mutation 前拒绝。
  相同 idempotency identity 的 preparation replay 只读取已冻结 intent，不重新观察 Adapter；Git object ID 必须是
  exact lowercase SHA-1/SHA-256 形式。
- `WorkspaceIdentityKernelApplicationService` 持有 immutable `ProjectRepositoryBinding`、一次性 Session pin 和
  单调 `WorkspaceGeneration`。首代只能从 `RESERVED` 开始，同代状态版本逐一递增，新 generation 只能接在
  `RETIRED`/`FAILED` 后；`READY`/`RETIRED` 必须绑定 exact settled ControlledOperation receipt。只有 `READY`
  generation 产生 `WorkspaceRuntimeBinding`，进入 `RETIRING` 即撤销该运行时 affordance。Git/provisioning
  机制仍在 Adapter，远端 workspace 生命周期仍由 HPC Plugin 拥有。

`openzyme_kernel.testing` 提供无外部 I/O 的 deterministic clock/ID、atomic in-memory ControlStore，及
scripted runtime、Workspace Runtime、ControlledEffect、Git-shaped revision Adapters。所有 scripted Adapter
都绑定 exact command/intent/receipt；缺少脚本即 fail closed，observe/reconcile 使用独立脚本表而不会重发
dispatch。它们供 `kernel_fake_adapters@1` 和跨 Plugin application-contract 测试使用，不是 production
Adapter，也不会被 Distribution 自动选择。

Kernel 只依赖 `openzyme-contracts`、`openzyme-extension-spi` 与 implementation-free
`openzyme-runtime-spi`。Workspace coordinator/base runtimes 通过 narrow
`AuthorityApplicationService`、`ControlledOperationApplicationService` 和 Workspace Ports 工作，不持有
Adapter client。它不导入 SQLite、FastAPI、LangChain、
Git/Podman/SSH/Slurm、Research、Science 或 EnzymeDesign 实现。

通用 Host 通过 `KernelPublicWorkspaceProjectionService` 和显式 Kernel command gateway 读取或修改目标
Control Store；Standard factory 以同一 deployment epoch、Session composition pin 和 capability binding 组装
projection、runtime 与 workspace Port。仓内旧 `openzyme-core`、`openzyme-domain`、`openzyme-runtime` 和
`openzyme-execution` authority packages 已删除，不存在在线 `@1` writer、旧 ToolRegistry 或双写路径。

完整 manifest 与 operator 流程见
[`extension-composition-manifest-reference.md`](../../docs/v3/extension-composition-manifest-reference.md) 和
[`deployment-composition-operator-guide.md`](../../docs/v3/deployment-composition-operator-guide.md)。当前
Standard 与 EnzymeDesign Distribution 已可构建 exact active graph；通用 Host 已消费 deployment
proof/epoch 并只开放 `file_workspace_public@2`。这只证明 non-live 目标组合可运行；真实部署的离线
migration/cutover 仍需另行明确授权。

```bash
uv run pytest packages/openzyme-kernel/tests
```
