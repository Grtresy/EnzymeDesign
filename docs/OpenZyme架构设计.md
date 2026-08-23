# OpenZyme V3 架构设计

> 当前状态：`separate-openzyme-kernel-from-capability-extensions` 正在分阶段实施。当前源码的普通
> Host/Client/CLI/UI 公共合同已经收敛到 exact `file_workspace_public@2`；旧 `@1` 只允许由显式离线历史
> reader 解释。源码切换不等于真实部署切换：只有 Distribution manifest、migration、deployment
> proof/epoch 和 qualification 对同一 identity 闭合后，目标 owner 才能视为生产 authority。

Git-shaped publication 的具体机制已由 `openzyme-workspace-git-lfs` 目标 Adapter 实现：显式 repository
locator、private ref/commit/tree/whole-tree manifest observation、LFS actual-byte verification、create-only
publication ref、restart-safe original-receipt observation，以及 process-scoped credential 的 exact-base
clone runner。durable root confinement、bare repository identity/base/ref、pre-receive hook 和 LFS object
actual-byte store 也已迁入该 Adapter；hook 随 wheel 打包，旧 Core 不再包含 Git subprocess/storage 实现文件。
private ref 派生、agent/publication/historical ref ACL 与 Host-owned ref update service 也已迁入 Adapter；它们只
落实已授权意图的 exact namespace、fast-forward/create-only 规则，不拥有 Kernel publication authority。
LFS policy/quota/upload session/closure/read/retention/GC receipt 的 SQLite-backed repository 也由 Adapter
实现，但事务 commit 由 Store/UoW 注入并继续执行 writer/fence 校验，Adapter 不建立第二事务权威。
`.gitattributes`/pointer/whole-tree closure validation、private reachability finalization 与 receipt-bound GC
mechanism 同样归 Adapter；它们仅产生或验证 Git/LFS receipts，不推导 Kernel publication、Science adoption
或 Task completion。
private namespace open/hold/close、receipt-before-delete 与 exact whole-generation ref retirement 也归 Adapter；
旧 Core factory 只注入 Store/UoW fence，不拥有 retention 状态机。
native Git/LFS 与 Gitless compute 的 qualification DTO/validator 也归 Adapter，旧 Core 不再导出该机制。
closed repository credential 与 read-only provision credential 的 claims/schema/error contract，以及
key/HMAC/envelope/token-digest material，同样由 Adapter 唯一实现；普通与 provision credential 的 token
issuance、ledger insert/read/revoke 已分别进入 Adapter issuance store，但不自行 commit。旧 brokers 暂时只保留
binding/pin/Kernel lease/private-namespace 或 pending-workspace admission 与 Store UoW 协调；claims/ledger/token 验证成功永远不能
替代 authority admission。
clone 通过注入的 Podman command port 执行，secret 不进入 argv/receipt，且重验独立 `.git`、remote、object
format、base commit/tree。Kernel 只拥有 intent、ControlledOperation、
immutable publication/path truth；Standard manifest 已可构建 exact Plugin-free composition 和 fresh proof，
并在 startup verification 后挂载带独立 digest 的 exact 空 Plugin runtime set，
Git smart HTTP/LFS Batch 的 CGI streaming、对象传输和错误映射已经由 Adapter 拥有，Host 只注入认证、preflight
与 Store scope；binding endpoint/base/pinned commit/default HEAD 验证也通过 Contracts 的窄 Port 由 Adapter 实现，
Kernel 仍唯一拥有 binding/Session pin canonical state。但 workspace lifecycle、pin/GC 和 writer adoption 完成前
仍不得开放生产 surface。

层间通信只走稳定 Contracts Port（Kernel 出站调用 Adapter）或 Kernel Application API（Plugin 提交 command、
query/evidence）；同层组件按 owner 协作：同一原子 occurrence 使用共享 typed reducer 加一个 UoW，不嵌套
service transaction；独立生命周期使用 durable event/outbox/continuation，不直接写对方表。Protocol 产生
wakeup signal 就属于前者，HMMER Plugin 通过 capability route 调用 HPC Workspace/Compute Port 属于后者。

## 1. 当前架构结论

OpenZyme 的稳定产品内核是：

`session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain`

文件内容由项目 Git 仓库、私有工作区修订、不可变发布修订和 Git LFS 对象承载。SQLite
保存身份、权限、租约、意图、回执、状态机和投影索引，不保存第二套通用文件目录真相。
历史 artifact 子系统不属于当前 runtime、domain、tool、SDK、API、UI 或 fresh-install
schema；它只在隔离的离线迁移和删除 operator 中以冻结旧输入的名字出现。

这次切换是 breaking cutover，不存在 dual-write、read-through、旧工具自动改名或旧请求
翻译。旧数据库只能在停机、备份、精确清单和回执门禁下由专用离线程序升级；普通 Host
启动不会执行兼容迁移。

## 2. 双轴模块边界

语义所有权轴回答“谁定义状态、工具语义和业务能力”：

```text
Contracts / Extension SPI
          ↓
OpenZyme Kernel
          ↓
Capability Plugins
          ↓
Product Plugins / EnzymeDesign
```

部署组合轴回答“这次安装选择哪些实现和能力”：

```text
Kernel + Adapters + Plugins + Drivers + delivery surfaces = Distribution
```

`OpenZyme Standard` 与 `EnzymeDesign` 都是 Distribution，不是语义层。Standard 的 required semantic
Plugin 集合为空；EnzymeDesign 可以把通用或垂直 Plugin 标为产品必需，但不能把 Standard 当作源码层
依赖或隐式继承能力。

manifest 选择、runtime mount、non-live readiness、target/provider qualification、真实部署 cutover 与一次
live 外部调用是六个不同事实：

| 状态 | 含义 |
| --- | --- |
| `selected` | exact manifest 选择组件，尚不保证实例已构造 |
| `runtime_mounted` | exact runtime identity 和 surface 已装配，尚不保证外部 target 可用 |
| `ready_non_live` | exact 外部资格目录、profile、Port、fixture、reconcile、credential 与 receipt verifier 已在禁止 live 的条件下闭合；尚未连接真实 subject |
| `qualified` | exact target/provider 的当前 receipt 满足要求，尚不表示 Session 已采用或流量已切换 |
| `cutover` | 真实部署已经采用该实现，尚不授权某次 live effect |
| `live` | 一次明确授权的外部调用实际发生；成功仍不自动形成 publication、Science adoption 或 Task terminal |

| 类别 | 职责 | 禁止事项 |
|---|---|---|
| Kernel | collaboration truth、authority、runtime coordination、revision/handoff、controlled effect、extension/capability/affordance resolution | import 具体 Adapter、Research、Science、HPC、AOX/HMMER/Vina |
| Adapter | 实现已定义的 Store、Workspace、Runtime、Credential、Process 或 Plugin-specific Port；依赖 Plugin 时仅可消费其独立公开的 Port contracts | 增加顶层 entity/tool、导入 Plugin service/repository，或从 mechanism receipt 推断 Task terminal |
| Plugin | 增加 namespaced state、tool、worker、projection、validator 与 capability | 访问 raw Core repository/SQLite/Host 私有 service，或按包名调用别的 Plugin 内部实现 |
| Driver | 把 owning Plugin 的 typed request 映射到 exact route | 脱离 Plugin 激活、拥有顶层语义、自动 fallback |
| Distribution | 选择 exact component/version/digest 并作为 composition root 启动 | ambient package activation、Session hot swap、拥有 canonical state |

目标 wheel owner 见 [ADR-0001](v3/adr/0001-what-is-openzyme.md) 和
[`source-bound-baseline.json`](v3/architecture/source-bound-baseline.json)。当前迁移状态是：

可执行 surface 的 owner 另由
[`catalog-owner-inventory.json`](v3/architecture/catalog-owner-inventory.json) 固定并由架构脚本重算；当前
catalog duplicate authority 集合已经为空。通用 Host 对 Reporting、Science、HPC 与本地 workspace 只挂载
canonical Plugin/Kernel surfaces；旧 function handler/repository/writer packages 已删除。拆分前部署状态由
[`pre-split-deployment-state-inventory.json`](v3/architecture/pre-split-deployment-state-inventory.json) 记录为
只读、去敏聚合快照；它只支持迁移分类，不是 `@2` activation、Provider/HPC readiness 或业务终态证明。

- `openzyme-contracts` 已拥有 Session/Task/Lane/Agent/Inbox/Approval、runtime coordination、
  ProjectRepositoryBinding/session pin、authority/capability/tool/evidence/workspace DTO，并已成为
  reliability、runtime command、effect certainty 和 failure contracts 的 canonical owner；旧 Domain
  paths/aliases 已删除。Session、Task/Lane、access、durable event/command receipt、
  Approval/Inbox/Memory/Agent、ControlledOperation、Continuation、runtime lease/signal 的 SQLite
  repository implementation，以及 reliability、runtime command/mutation/quiescence、failure/diagnostic、
  workspace checkpoint/publication、engine invocation/document 和历史 capability/retirement 物理 repositories
  已迁入 Store；历史 capability DTO 只由 offline migration codec 还原，Store 不依赖旧 Domain，也不在
  `@2` 导出旧 alias。project binding/Session pin、revision/path handoff/task finish evidence repositories 也由
  Store 实现，Research index 已从 handoff repository 拆离；Agent Git workspace repository 则由 Git/LFS
  Adapter 实现并接收 Store commit callback。旧 Core/Domain/Runtime/Execution authority packages 已删除；
- `openzyme-store-sqlite` 已建立旧 `agent_capability_lease_records` 到公开
  `AgentAuthorityLease` 的只读 exact mapper：`workspace_generation` 是 generation，
  `state_version` 是 fence，旧 profile 只能收窄为 operation grants；它不编造 expiry、
  不更名物理表、不写库，也不代表 Store writer/cutover 已完成；
- `openzyme-extension-spi` 已拥有 closed Adapter/Plugin/Driver/Distribution manifest、十一类窄
  Kernel application services、typed contributions、受限 transaction participant 与 subordinate
  Driver contract；closed JSON codec 会拒绝 duplicate/unknown field 并重算 canonical digest，Distribution
  parser 保留 Adapter slot/target 与 Driver slot。entry point 只返回 locator，selected resource loader 不执行
  editable `.pth` 代码；
- `openzyme-execution-contracts` 只拥有 closed workload/route/failure 与 runner wire；formal
  revision-bound execution DTO 已归入 `openzyme-compute`。Compute 现在还提供显式 manifest、
  `workspace_revision_job.*` runtime、projection/UI-renderer/worker/transaction surfaces 和 provider-neutral application
  lifecycle；它通过唯一 Kernel ControlledOperation 保存 effect certainty，并只持有 request、opaque handle 与
  result。是否激活由 Distribution、deployment epoch 与 Session pin 决定；
  `mcp-hpc-runner` 只依赖窄 `openzyme-execution-contracts`；
- `openzyme-science` 已成为 attempt/selection/disposition/adoption/closure 与 scientific
  deliverable/validation receipt 纯 DTO 的唯一 owner；旧 Domain compatibility path 已删除，
  exact manifest、tools、projection、migration 与 restricted participant 已落地。历史物理 repository
  implementation 也已迁入 Science 的 offline-only namespace并通过受限 Store participant 写入。lifecycle/rollover/selection evaluation、attempt application、file-effect adoption、
  immutable-byte resolution、deliverable finalization 与 offline verifier 均由 Science 实现。offline verifier 已删除对 Reporting repository 与 Compute 实现枚举的直接
  依赖。Kernel command context/受限 participant 目标写路径已经实现并通过 SQLite 原子回滚、stale fence、
  extension-absent 和跨 Session 负例；当前在线 Host 只接受 `@2`，真实历史部署 adoption/cutover 仍未获授权；
- `openzyme-reporting` 已成为 report draft/report record、lifecycle、repository/service/tool/projection/renderer
  的唯一代码 owner；旧 Domain/Core compatibility path 已删除。Standard 不选本 Plugin，EnzymeDesign 只能按
  exact manifest 和 mounted surfaces 激活；
- `openzyme-research` 已拥有 provider-neutral request/source/evidence、invocation state、bounded
  orchestration、`deep_research.start`、worker、projection 与显式 revision/path 交接；
  `openzyme.research@1` 使用独立 projection digest、Session-scoped 稳定游标分页和 bounded public
  source facts，tool/projection/worker 通过显式 runtime surface builder 提交 Kernel mount gate；
  `openzyme-research-tavily` 是独立可选 Provider Adapter，secret 只通过 locator/resolver 取得，
  response loss 进入 `dispatch_in_doubt` 且不重发、不切换 Provider；
  `openzyme-science-research` 是 PubMed/Semantic Scholar/literature quorum 的 owner。旧
  `openzyme-engines` Deep Research authority、通用 Runtime 的 Research tool/provider seam、Core bio
  registrar 以及基础 Host 的 ambient Tavily/bio construction 均已移出 active runtime；
  UniProt/RCSB/InterPro 的产品 DTO/Port、capability/route 与 HTTP mechanism 已分别迁入
  `enzymedesign-core`、`enzymedesign-bio-providers` 与 `enzymedesign-bio-provider-adapters`；
  generic Host 不硬编码这些能力，具体 mounted surfaces 由 Distribution 注入；
- 通用 `EngineInvocation` 已进入 Contracts；旧 session run DTO 由 `openzyme-compute` 拥有，
  `sandbox_*` mechanism DTO 由 `openzyme-process-podman` 拥有。Podman 包已进一步实现 exact
  mount/image、bounded foreground process、process-group timeout cleanup、epoch/fence retirement 以及
  `ProcessIsolationPort`/`WorkspaceProcessPort` 桥；同包的 digest-pinned、network-none filesystem helper
  已实现本地 Observation/Filesystem Ports、CAS、原子写和 symlink/hardlink confinement；Transfer Adapter
  使用 manifest-bound opaque `transfer_ref` 与第二个 exact named volume，执行 create-only、内容校验的
  upload/download/immutable revision-tree materialization，且不泄漏 Host path/URL、不 checkout/merge/
  publish/cleanup；Store/control
  socket/Host/Distribution composition 尚未
  cutover，兼容字段也不进入最终 `@2` public contract；
- Agent Git workspace 的 Podman named-volume inspect/create、deterministic name 与
  Session/member/generation owner labels 已迁入 `openzyme-process-podman`；旧 Core volume implementation/
  export 已删除，provider-neutral volume Port 位于 Contracts。Git/LFS Adapter 的 provisioning/recovery
  mechanism 只消费注入的 volume/clone/observation Ports，返回 exact observation 或 typed blocker；Kernel
  application service 仍唯一执行 ready/block/replacement 与 lease/failure mutation。Host 只能显式注入所选
  Adapter backend。物理 volume receipt 不创建 canonical workspace、
  authority、publication 或 Task terminal；
- Agent capsule 的 versioned image manifest、Containerfile、qualification probe、digest-pinned build/
  qualification command、subprocess executor、exact-volume process runner 与 bounded control socket 已迁入
  `openzyme-process-podman`；旧 Core image module/assets、Podman runner 和顶层导出已删除。Kernel/Core 只消费
  runner Port 与 exact qualification receipt，Host 从显式选定的 Podman Adapter 取得 runner/executor；镜像构建、
  qualification 或 process exit 不能创建 workspace、authority、runtime command 或 Task 真值；
- `openzyme-contracts` 已定义 Store/UoW/event/outbox/clock/id/credential/effect Ports，
  `openzyme-runtime-spi` 已定义 bounded turn/capability gateway/process-isolation contracts；Kernel/Standard
  只经这些 Port 连接 selected Adapter，旧 Core/Runtime packages 已删除；
- SQLite、Git/LFS 和 LLM Adapter 已各自提供 side-effect-free locator 与 exact manifest；
  SQLite Adapter 的目标 control-store 实现现已具备 closed migration catalog、offline-only bootstrap、
  read-only startup proof、`BEGIN IMMEDIATE` UoW、event/outbox 原子写、namespace authorizer、受限 extension
  participant，以及 bundle/catalog/binding/resource fact/workspace receipt persistence。Kernel entity 通过
  explicit owner-table codec 映射，未映射即失败，不创建平行 JSON 真值表；当前通用机制、
  Session/Lane/Task/AgentMember/AgentAuthorityLease/SessionCapabilityBindingRevision/SessionCompositionPin/
  ConversationMessage/Memory/ProtocolRecord/InboxMessage production
  codec 与第一批 Kernel legacy-table repositories 已完成。现行 final-schema SQL、bootstrap 和 deployment
  proof 已机械迁入 Store；上述 Kernel repositories 已有唯一 Store implementation，并向 runtime signal、terminal
  controlled-operation projection 与 commit 注入 Kernel policy；offline historical source 按 owner/phase
  bundles 读取，target fresh loader 则按 Standard 或
  EnzymeDesign closed schema profile 只选择已安装 owner，再加 `openzyme_store_*` migration 建立 composite
  schema，并在开放 writer 前生成零写入、profile-bound composite proof。当前 `@2` Host 使用该 target writer；
  真实历史 deployment 的 adoption/cutover 仍未执行；
  `openzyme-standard` 已打包零 semantic Plugin 的 active exact composition，能只读选中四个 required
  Adapter，并为 Standard owner schema 生成 deterministic fresh seed/receipt。manifest active 仍必须配合 exact
  deployment proof、epoch 与 application-writer。当前本地
  workspace 的 Podman runner、volume backend 与 Git restore observer 已由
  `StandardLocalWorkspaceAdapterFactory` 显式构造，Host 只消费窄 factory Protocol；缺失 factory 或 binary/network
  identity 漂移时 fail closed，不再由 Host ambient 构造具体 Adapter；repository 侧的 durable roots、binding
  mechanism、revision backend、workspace recovery 与 credential issuance 也由
  `StandardRepositoryAdapterFactory` 按 exact settings/root-boundary 构造，Host 只注入 active bindings 和公开
  Ports，缺失 factory 时在 writer/route 前失败；LLM 机制也由 `StandardLlmAdapterFactory` 构造 exact
  runtime/provider，Host 启用 LLM 却未注入 factory 时在网络调用前失败；
- 五种离线 wheel profile 已闭合：Contracts+SPI、Kernel、Standard、runner 与 EnzymeDesign component set
  分别在独立 venv 核对 wheel `METADATA`、重算全部工作区发行闭包、拒绝非闭包
  `openzyme.extensions` entry point owner、禁止的旧/领域 distribution 和 import-time I/O。Standard-only
  profile 明确排除 Tavily、Research/Reporting/Science、Compute/HPC、runner、EnzymeDesign、Biopython、
  NumPy、RDKit、Meeko 与 Open Babel；该结果
  证明包装/依赖边界，不把不可激活的 Distribution 或 Plugin 提升为 production authority；
- `enzymedesign` 已成为独立、版本化 Distribution wheel：它直接选择 Kernel、Standard-compatible
  Adapters、通用/产品 Plugins 与 Drivers，不依赖 `openzyme-standard` 作为语义层。repository 与 packaged
  composition exact 相等，30 个 manifest locator、8 Adapter、14 Plugin、8 Driver、32 个 Plugin tool 加 5 个
  Kernel workspace base tool（合计 37 个）的 catalog 全部
  闭合，并能生成 EnzymeDesign fresh seed；typed runtime surface set 还能在 read-only startup gate 后通过
  Kernel exact mount 闭合 32 Plugin tools、13 capability routes、2 HTTP routes、5 projections、5 workers、
  2 finish validators 和 3 transaction participants，缺失或多余 surface 会在 mount 前失败。产品
  `build_enzymedesign_application_runtime()` 还会精确核对 8 个 selected Adapter runtime binding 的
  slot/target/component/manifest/contract/build identity；LLM、Git、Podman 与 Slurm 的 effectful operational
  object 只能从这组 binding 派生，composition root 不再接受第二套独立 operational selection。闭合 5 个
  Kernel 与 32 个 Plugin tool runtime 后才构造 SQLite writer、Kernel command/runtime gateway 与公共投影；
  通用 Host 入口已从该 graph 完成真实 Session bootstrap，且不依赖 `openzyme-standard`。这证明
  `runtime_mounted`；Distribution 另以 `ToolDispatchBinding` 将 Kernel 重验后的 authority fence、workspace
  generation、route/driver/target/inventory proof 传给 HMMER/Vina 正式 application bridge，再由 subordinate Driver
  编译 typed workload 并进入 Compute ControlledOperation/声明式 runner Port。formal binding 在 writer 可达前
  一次性绑定，并只从 canonical PublishedRevision、publication-owned path verification、ready owner workspace、
  当前 authority 与 adopted capability binding 推导 admission。该 bridge 已有 non-live 直接证明，
  Compute execution record 现通过 Kernel-admitted extension state、Store-owned SQLite coordinator/query 与
  `openzyme_compute` namespace 做 CAS 持久化；产品组合根同时构造 Kernel continuation service。SQLite restart
  record 在首次外部调用前先持久化 `dispatch_state`、occurrence identity 与 receipt digest；无 provider handle 的
  uncertain response 或 typed exception 在重启后都只 reconcile 原 occurrence，dispatch count 保持 1。terminal
  result 还必须在落库和 continuation 注册前通过持久化的 exact Driver validator identity、compiled workload
  contract 与 HMMER/Vina result semantics；失败不会唤醒 owner。
  真实 non-live 产品场景还从通用 Host、Session pin、authority、immutable publication、adopted inventory 和
  affordance/route，经 mounted HMMER/Vina Drivers 与 Compute 到声明式 fake runner，再验证 terminal result、
  owner continuation、Science finish validator 以及 Task 保持 `todo`。该测试直接 seed 合法 canonical
  capability/workspace/path facts，并为其他 application 与外部 I/O 使用 no-op/fake Port，因此只证明
  `real mounted EnzymeDesign product graph with formal HMMER/Vina cross-layer slice`，不证明 14 个 Plugin 的
  全部正式命令自然创建所有前置事实，也不等于真实 HPC/Slurm target qualified、cutover 或 live；
- EnzymeDesign 现在另有 external qualification readiness 层：从 exact activated Distribution 推导 45 个
  `capability + operation + route + target/provider + source/build/config digest` 单元，分为 required `base`
  和显式启用的 `research-provider`、`hpc-primary`、`hmmer`、`docking`、`alphafold` profiles。recording backend
  只消费 deterministic fixture；unknown effect 只 reconcile 同一 attempt，rejecting credential resolver
  不返回 material。`ready_non_live` receipt 不能作为真实 qualification receipt adopt，运行时 admission 对
  missing/expired/drifted unit 只给出 `blocked_qualification`，不切换 route/subject；
- 真实 route qualification 的第一实施阶段仍是 plan-only：只从显式 allowlisted safe snapshot 形成
  source-bound subject observation；LLM/Tavily/Git/Podman/HPC/科学软件的 partial/missing identity 都产生
  `ExternalIdentityGap` 和待操作员选择的候选方案。Batch 1 固定闭合 `base + research-provider + hpc-primary +
  hmmer + docking`，AlphaFold 是独立 Batch 2。dry plan 固定零 retry、无 fallback、
  `live_effect_authorized=false`；预算是宽松熔断而非测试压缩目标，LLM/Tavily occurrence 现金硬上限分别为
  USD 100/USD 50，LLM request 硬上限 20，batch 现金硬上限 USD 250。operator candidate 选择与 subject 闭合之间新增独立
  `ExternalIdentityPreparationPlan`：本地 Git/LFS 建仓、Provider locator/account、digest-pinned image 与 HPC
  profile/inventory 只能由 exact preparation authorization 执行，且不能产生 `qualified`。当前 Git scope 只允许
  本地隔离 repository/LFS endpoint，禁止 hosted sync。Preparation 完成并重新发现 identity 后才重建
  qualification dry plan；准备 runtime 采用 `0700` operator state root、`0600` 私有文件与 exact locator，无
  ambient credential fallback。Batch 1 只有 LLM/Tavily locator、本地 Git/LFS、`base`/`hmmer`/`docking` 三镜像组
  和 `Diannan/3090` qualification-only HPC identity 七个 action；SSH subject 显式绑定 host/port（当前端口
  `22222`）且不读取用户 SSH config fallback；成功只形成 protected
  `ExternalIdentityPreparationResult`。effect-free rediscovery 还必须把 `nonlive.locator.*` 重绑为专用
  LLM/Tavily/HPC locator、移除本地 Git credential placeholder 并重建 unit digest。Preparation authorization
  绑定 exact plan/batch/operator、持久且一次性，terminal action 不得重复派发并支持 exact 私有撤销；qualification
  authorization 仍独立绑定 exact plan digest/batch/operator，持久一次性、无 wall-clock 过期、支持 exact 私有撤销，且 terminal unit 不得重复派发。两级 backend 都必须在各自 authority 缺失、撤销或失配时于
  credential resolution 前失败。真实 receipt 即使完成也只证明 `qualified`，不能更新
  Session binding 或替代另一个 cutover change。正式本地入口拆成 root/layout-only bootstrap、canonical authorization
  writer 与 source-bound Batch 1 executor；executor 必须先预检全部 exact locator，再按稳定 occurrence identity 写 protected
  ledger。已有 residual state 而无 terminal result 时停止人工 reconcile，不覆盖、不重发、不 fallback。当前 live bridge
  已覆盖 Provider、Git/LFS、Podman、SSH、Slurm 与 HMMER/Vina/fpocket/preprocess 正式 Compute route；Diannan 科学
  route 只消费 target 已安装且 digest-pinned 的 Apptainer SIF，不安装、升级或重建 HMMER/Vina/fpocket，本地科学
  route 只采用已固定 digest 的 qualification image。唯一另行治理的 target 安装是 exact
  target-qualified exact `openzyme-workspace-runtime`：Diannan 绑定
  `/home/grtresy/.local/libexec/openzyme-workspace-runtime`，其实现、principal-bound deployment plan、native qualification 和 exact rollback
  均属于当前 qualification change，但不构成 inventory adoption、runtime activation 或 cutover；
- `openzyme-workspace-git-lfs` 已成为 `AgentGitWorkspace` identity/observation/restore 与 Git-LFS
  policy/pointer/closure/verification/receipt 机制 DTO 的唯一代码 owner；旧 Domain shim 已删除，仓内生产
  caller 使用 Adapter namespace。private/public ref 与 immutable-byte backend、
  Gitless compute tree、exact-base clone、provisioning mechanism 与 typed recovery probe 已经迁入；restore probe 通过注入的
  workspace process port 只读分类 permission/corruption/base drift/infrastructure，不 repair 或 replacement；
  durable roots、bare repository/hook、ref policy/owner update、LFS actual-byte object store 与 repository HTTP
  transport 也由 Adapter 唯一实现；credential authority application service、LFS pin/GC writer 只有在
  Distribution exact selection 和 Kernel authority admission 后可用；
- 新 `openzyme-kernel` 已拥有第一阶段 composition、Extension/Capability registries、
  operator-only Session binding、declared catalog、affordance resolver、安全 inspection 和 exact route/
  continuation revalidation；HMMER/Vina 只依赖 capability contract，不依赖 HPC/Slurm 实现；
- 旧 `openzyme-tools` 静态酶工具 catalog 已从 workspace、Host dependency、锁文件和 active source 删除；
  fpocket、Vina 与 AlphaFold 3 的工具契约、qualification、resource requirement 和 Driver 分别由
  `enzymedesign-structure`、`enzymedesign-vina` 与 `enzymedesign-alphafold` 的 exact manifest 唯一拥有。
  Core skill catalog 默认为空，Distribution 未显式挂载 catalog 时不得从安装路径发现 ambient capability；
- `enzymedesign-sequence-toolpack` 已从空骨架升级为 exact Product Plugin：它拥有 bounded FASTA/plain
  parser 与 UniProt、RCSB、InterPro 的 provider-neutral ToolSpec。数据库能力通过 explicit capability route
  求解，Plugin 不包含 HTTP client，也不在 Agent turn 探测 Provider；三类 capability/route 由
  `enzymedesign-bio-providers` 提供，`enzymedesign-bio-provider-adapters` 仅实现
  `enzymedesign.bio-provider@1`。Adapter 单次 dispatch、不自动重试或切换 Provider，也不写 workspace、
  publish revision 或推断 Task 完成；只有 EnzymeDesign exact mount 可激活；
- 新 Kernel 还已实现 all-or-nothing activation catalogs：Adapter/Extension bundle、declared tool、capability
  route、normalized HTTP route、projection、worker、validator、schema、migration、participant 与 qualification
  都独立重算 digest；single provider、dotted tool、`METHOD + path`、Driver ID 或 namespace 冲突和依赖环在
  mount 前失败。`openzyme-process-podman` 已提供首个真实 locator/resource；两个 Distribution
  均已可构建 exact active graph，但没有 read-only startup proof/epoch 仍不能开放 production surface；
- 新 Kernel 已实现 deployment activation epoch 与 Session composition pin 机制：composition/core-schema/
  installed-wheel 三类只读 proof 全部通过后 gate 才允许 writer/route/worker/runtime/effect；Session、pin 与
  initial capability binding 由一个 repository call 原子提交。message、drain、approval、tool、workspace、
  publication、operation、restore 共用 fail-closed guard；inventory adoption 只追加 binding revision，不热换
  Extension bundle；
- Plugin runtime mount 会在返回任何 surface 前 exact-match tool、capability/HTTP route、projection、worker、
  finish validator 和 transaction participant，拒绝 partial/ambient/Host-internal runtime 及 cross-owner Driver。
  offline upgrade/removal verifier 已检查 quiescence、Session/continuation pin、owned state disposition、migration
  plan 与 unsettled operation；公开 composition failure 和 private diagnostic 共用 identity并做 path/secret
  隔离。通用 `@2` Host/Standard 已消费这些 target surfaces；真实历史 deployment cutover 未执行；
- 新 Kernel 还已实现 implementation-free `WorkspaceOperationCoordinator`：query-only observation 不写
  operation，filesystem mutation/process exec/transfer 则在 exact Adapter dispatch 前先写唯一
  ControlledOperation admission，response loss 进入 reconcile 且不 retry、fallback 或切换 route；三个
  effectful Port 均用原请求执行只观察式 reconcile，Kernel 固定 `redispatch_performed=false`，无 Adapter
  terminal proof 时保持同一 operation 为 `dispatch_in_doubt`；
- Workspace effect 的 Adapter-private occurrence 已从进程内缓存迁入 Store-owned SQLite ledger：Contracts
  固定 `WorkspaceOperationIdentity`、reserve/read/settle Port 和 content-bound receipt codec；Podman filesystem、
  process、transfer 与 SSH Adapter 都必须先以 provider/operation/intent/session/workspace generation 原子
  reserve，随后才可 dispatch。Standard 与 EnzymeDesign composition root 注入同一 target ledger；Host 重启后
  exact duplicate 只返回持久 receipt，uncertain occurrence 只 reconcile 原 transport identity，零 redispatch、
  零 target/provider fallback。SSH/Slurm reconcile 必须先读取 durable occurrence；已有 uncertain occurrence 时，
  credential、locator 或 qualification 暂不可用只表示 reconciliation unavailable，必须保留
  `dispatch_in_doubt + mutation_applied=null`，不能降级成 `no_effect`。该 ledger 是机制事实，不会自动
  checkpoint、publish、adopt 或完成 Task；
- 新 Kernel 已实现 `RuntimeTurnCoordinator`：从 claimed signal、Session runtime lease、layered release、
  exact capability binding/affordance snapshot 与 selected runtime Adapter 构造 immutable bounded command，
  对 outcome 的 Session/member/signal/fence/epoch/budget 做 closed validation，并通过 repository Port 原子
  once-only consume。duplicate ingestion 不重新执行 Adapter，continuation delivery 与 runtime settlement
  使用独立 outbox intent，且 settlement 固定不产生 Task transition。目标 ControlStore repository 已进一步
  实现 command 预注册与 outcome 消费点的 current signal/lease/fence/process-epoch CAS；Standard runtime drain
  使用这一唯一 coordinator；
- 新 Kernel 已实现 `PublicationKernelApplicationService`：checkpoint 将 pinned repository binding、workspace
  generation、authority 与 Adapter private-ref observation 求交；publication 的 admit 只冻结 whole-tree intent，
  Git create-only ref dispatch 必须走同 intent digest 的 generic ControlledOperation；materialize 只在 exact
  `terminal_known` receipt 后调用 Adapter `observe_publication`，绝不重发 dispatch，再 create-only 写入
  `PublishedRevision`。`WorkspacePublicationCoordinator` 进一步在 Adapter effect boundary 前先持久化
  `dispatch_in_doubt`，response loss 或 receipt drift 后只 reconcile 原 execution/generation/fence；首次 dispatch 仍要求
  current authority；coordinator 还从 Session pin、workspace binding/generation、verified checkpoint、Adapter
  commit/manifest observation 与 Git/LFS manifest policy 构造确定性 frozen intent，policy/identity drift 在
  dispatch 前以 `no_effect` 拒绝，相同 idempotency replay 不重复观察 Adapter。已不确定的原 effect 则可在 lease revoke 后按同一 admitted identity 完成 observation/settlement，
  不授予新 dispatch 权。RevisionPath verification 同样绑定 Session pin、commit/tree/object identity；旧
  publish mutation 使用 Host-to-Kernel application，Standard 能构造 exact target publication runtime；历史
  `@1` 只读兼容面不在在线 Host，真实 deployment adoption/cutover 仍未执行；
- 新 Kernel 已实现 `RuntimeCoordinationKernelApplicationService`：Session runtime lease 与 signal occurrence
  分层持有；acquire/heartbeat/release 和 enqueue/claim 均绑定 owner、generation/fence、process epoch、目标
  authority/workspace generation，并在短 UoW 内形成 durable event/outbox，绝不隐式完成 Task；
- 新 Kernel 已实现 `AgentAuthorityLeaseKernelApplicationService`：root issuance、parent-bound successor 和
  revoke 均通过 issuer 的 operation-specific grant；successor 创建与 parent supersede、revoke 的
  grant/lease generation-fence 递增均为同一短 UoW，禁止 stale writer 和 partial authority state；
- 新 Kernel 已实现唯一的 pre-Session `SessionBootstrapKernelApplicationService`：delivery security 通过
  Contracts verifier Port 验证短时 operator authorization，authorization 绑定 exact project/Session、root
  lease、revision-1 capability binding 和 immutable composition pin；Kernel 随后在一个 UoW 中 create-only
  写 Session/master/root authority/binding/pin/event。普通 collaboration create 不再接受不可能合法预置的
  Session lease，失败不产生 partial Session，bootstrap 也不创建 workspace/Task 或运行 runtime；
- 新 Kernel 已实现 `WorkspaceIdentityKernelApplicationService`：Project repository binding 保留不可变历史并
  单调推进 head，Session repository pin 一次性冻结；WorkspaceGeneration 使用 closed lifecycle 和双重
  generation/state-version，只有经 exact settled ControlledOperation receipt 证明的 ready generation 才产生
  runtime binding，进入 retiring 即失去执行 affordance。Git/LFS/provision/cleanup 机制不进入 Kernel；
- Standard 已将目标 runtime/local-workspace operational graph 接到同一个 target `SQLiteControlStore` writer：
  exact Adapter selection 先构造 Kernel authority/ControlledOperation owners、Podman workspace Ports、declared
  tool runtime mount 与 capability gateway，再构造 canonical signal lease/claim、bounded turn 和 once-only outcome
  consumption。fresh non-live Host 测试已证明 ready workspace + authority successor + message → signal → drain →
  released lease；构造和测试均未调用真实 Provider、Podman、Git、网络或 HPC，真实 offline cutover 仍未执行；
- `openzyme-runtime-llm` 已成为 LLM mechanism 唯一 owner：除 exact-provider `AgentRuntimeAdapter` 的 closed
  配置、credential-slot、有界 context/step/time/usage、同 provider retry 和 no-switch failure 外，旧
  LangChain model factory/invoker、prompt tokenizer、token ledger、debug recorder 与 connectivity mechanism
  均位于该 Adapter；旧 Runtime compatibility package 已删除。Standard 通过
  `StandardLlmAdapterFactory` 显式构造，generic Host 在 LLM 启用但 factory 缺失时 fail closed；locator/
  preflight 不发网络请求，live connectivity 必须另行显式授权。`openzyme-process-podman` 已拥有
  process/filesystem/transfer、container lease 与 retirement 的唯一实现，并以 exact
  binary/image/mount identity 做离线 preflight。安装 Adapter wheel 不等于某个 Session 已获得 affordance；
- 新 Kernel 已实现 closed `workspace.status`、`workspace.fs.read/list/mutate`、`workspace.exec` runtimes；
  Host read-only resolver 将 current Session/member/workspace/authority 与显式 composition pin 求交后生成唯一
  local binding，schema 与 runtime 都拒绝 caller `workspace_id`、credential、target 和 remote locator。它们由
  Standard exact runtime mount 暴露，不存在旧 ToolRegistry；
- Standard 已把这五个 Kernel base tool 从 declared catalog 继续闭合到 exact runtime mount：Kernel runtime 与
  Plugin runtime bundle 分开输入，统一按 active release 核对 owner component、runtime ID 与 contract digest；
  missing/unexpected/collision 或 activation drift 在开放 bounded runtime 前整体失败。
  `StandardLocalWorkspaceRuntimeFactory` 只把 coordinator 接到选定的 Podman filesystem/process Ports，构造不执行
  进程或文件 mutation。Plugin-free 语义仍是零 Plugin，而不是零工具或一个伪造的 Kernel Plugin；
- local `workspace.exec` 从未拥有 HPC credential provider、Host 注册或 prompt 路线，并在 schema/admission
  阶段拒绝 `hpc-native`/SSH 类请求；HPC workspace owner projection 不提供 credential service、login alias
  或 remote root。repository credential seam 仅服务 Session-pinned Git/LFS，
  最终 `@2` local schema 仍完全不接受 caller credential；
- Workspace process request/receipt 现已内容绑定 authority generation/fence、process epoch、stdin digest 与
  bounded result payload；Podman Adapter 不接受 local tool 提供的 HPC SSH credential 或 remote locator；
- filesystem mutation/transfer request 同样绑定 exact authority lease/generation/fence；transfer 还绑定 opaque
  ref、transfer manifest、byte budget 与 deadline；只读 observation 不建 operation，结构化小文件 mutation
  只在 Kernel admission 后进入无网络 helper，大文件/目录进入独立 Transfer Port；
- `openzyme-core`、`openzyme-domain`、`openzyme-runtime`、`openzyme-execution` 与相应旧 caller/shim/entry point
  已从 active workspace 删除；公共 diagnostic redaction 由 `openzyme-contracts` 拥有，thin CLI 只依赖
  client/contracts；
- 两个 Distribution 已解除 scaffold gate，但运行 authority 仍只由 exact schema/wheel/composition proof、
  持久化 activation epoch、Session pin 和当前 capability binding 授予。
- Store 已实现 non-live offline cutover planner 和 isolated atomic adoption：十六类 inventory、八类
  quiescence surface、三份 independent backup、Session 三分类、旧 authority 行确定性映射与
  composition/pin/ledger/state 单事务提交。该路径只在 fixture 中执行，未触及真实 deployment。

目标通信规则是 Kernel 调 Adapter Port、Plugin 调 narrow Kernel application service、Plugin/Driver 通过
manifest 与 capability/route contract 被 Host 组合。同层组件不任意互调：Adapter 由 owning service 编排，
Plugin 按 capability requirement 解析 provider/route，Driver 绑定 owning Plugin 和 exact route。共享文件只用
`PublishedRevision + RevisionPathRef`，外部 effect 只用 durable operation/typed Compute lifecycle。
当前 HPC Plugin 已通过 manifest 声明 target inventory、remote workspace、8 个 `hpc.workspace.*` 工具与
formal compute route，并由 Plugin-owned runtime 精确实现；Host 窄 bridge 在每次调用重验 opaque owner、
local/remote generation、target qualification 与 operation authority。
`openzyme-hpc-ssh`、`openzyme-hpc-slurm` 分别实现远端 Workspace Runtime 与 scheduler Port；三者仍为
legacy callers pending/not-cutover，不能从代码存在推断产品已激活。
完整 Plugin authoring 与通信约束见 [V3 Plugin 开发指南](v3/plugin-authoring-guide.md)。
closed manifest 与部署操作分别见
[Extension composition manifest reference](v3/extension-composition-manifest-reference.md) 和
[Deployment composition operator guide](v3/deployment-composition-operator-guide.md)。

LangGraph、LangChain 或其他 Agent framework 只可作为 runtime Adapter 或 Plugin 局部实现，不能替代
control plane。

## 3. 身份与所有权

### 3.1 项目仓库绑定

每个 project 拥有版本化 `ProjectRepositoryBinding`。session 启动时固定 binding version、
base commit、repository identity、Git/LFS endpoint identity 和 policy digest。后续 active
binding 变化不会静默重绑已有 session。

repository credential 必须同时绑定 session、agent member、workspace generation、
capability lease 和允许的 ref class；过期、撤销、跨 owner 或跨 generation 的 credential
均拒绝。私有 ref、credential、Host path、runner handle 和远端目录不进入共享投影。

### 3.2 独立 agent 工作区

每个 resident teammate 拥有独立 `AgentGitWorkspace`、generation、私有命名空间和清理
生命周期。agent 可以自由决定 fetch、merge、rebase、cherry-pick、编辑和何时请求发布；
harness 只呈现 clean/dirty、base、commit/tree、冲突、配额、租约和权限等真实约束。

workspace checkpoint 是私有可变事实。`workspace.publish` 是唯一将 exact clean commit
变为共享不可变 `PublishedRevision` 的边界。发布时必须重新验证：

1. binding、workspace generation、capability lease 和 clean observation；
2. commit/tree、父修订、publication intent 和 idempotency identity；
3. Git LFS closure 的 path、OID、size、actual bytes、quota 和 fresh readback；
4. remote push receipt、publication ref 和 immutable pin。

任何缺失、损坏、策略漂移或歧义都会在共享修订出现前失败，不自动改写 commit 或补造对象。

这些 checkpoint/publication DTO 现在由 `openzyme-contracts` 唯一实现；Git-specific
`AgentGitWorkspace` 与 LFS policy/closure/receipt DTO 则由 `openzyme-workspace-git-lfs` 唯一实现，旧 Domain
modules/aliases 已删除。协议按已确认决策暂时保持 Git-shaped，因此 commit/tree/ref、object mode/OID 和 LFS
identity 仍属于精确共享身份；Git 命令、remote transport、credential、LFS actual-byte 验证和 repository
root 则不属于 Contracts/Kernel 实现，必须由 `WorkspaceRevisionBackendPort` 的 Workspace Adapter 提供。
Port 只返回 exact observation/receipt 和有界 immutable bytes，不拥有 publication 状态。当前 teammate
`workspace.publish` handler 已删除旧 publish writer 调用和旧写实现/公开导出，Host 通过注入的 target application 翻译 closed request；
Standard target runtime 使用同一 SQLite Control Store 执行 intent、ControlledOperation、command receipt 与
`PublishedRevision` 的原子链。fetch/audit 由独立只读查询服务承载；Standard Host 装配 target runtime，
真实历史 deployment cutover 仍未执行。

### 3.3 文件交接

跨 agent、task、report 和 scientific 边界只传递 typed revision/path reference：

- `RevisionPathRef` 绑定 publication、commit、tree、path、object identity、content digest
  和 size；
- research index 只索引已发布路径；
- protocol handoff、task finish evidence 和 report content ref 必须引用已验证的发布路径；
- 后续私有 workspace 变脏不影响已经发布的不可变引用。

通用 `RevisionPathRef`、`ProtocolFileHandoff` 与 controlled-operation result ref 现在由
`openzyme-contracts` 唯一实现；`ReportRef` 和 `ScientificClosureRef` 分别归 Reporting 与 Science。
旧 `TaskEvidenceRef@1` 仅作为迁移兼容 union 保留，`@2` 通过 generic `EvidenceRef` 指向 owning
component，避免 Kernel contract 反向依赖垂直类型。

### 3.4 产品真值的 owner 与生命周期

| 产品真值 | canonical owner | 生命周期与持久化 | 禁止的推断或替代 |
| --- | --- | --- | --- |
| agent workspace | Kernel 拥有 owner/generation/authority 语义；Git Adapter 拥有 `AgentGitWorkspace` 机制记录 | SQLite 保存身份、状态、租约关联和安全投影；文件与完整 Git 状态位于 owner volume | lane cwd、Host checkout、另一个 agent workspace 或临时目录不能替代 |
| published revision | `WorkspacePublicationIntent`、`ControlledOperationExecution` 与 append-only `PublishedRevision` | intent、dispatch fence、remote receipt、publication ref 和 manifest 持久化；只允许 create-once/supersedes | private ref、mutable branch、相同 bytes 或 remote scan 不能自动成为 shared truth |
| external job/result | revision-bound execution owner、runner ledger 与 opaque handle | request、dispatch intent、handle、observation、cancel receipt、terminal result 和 deadline 持久化 | timeout、lease expiry、SSH 断开、文件存在或新 submit 不能冒充 settlement |
| scientific deliverable | scientific attempt/selection authority 与 finalization transaction | adopted producer effect、published path、actual-byte validation、bundle 和 receipt 原子持久化 | 文件存在、digest 相同、历史 import、job success 或 report claim不能自动 adopt/close |
| task terminal | task owner 通过显式 `task.finish` | terminal decision 与 closed typed evidence 在同一事务写入 | runtime idle、protocol delivery、publication、job/scientific terminal 不能机械完成 task |

这些对象可以互相引用，但任何一个对象的成功、失败、过期或不可见都不能替另一个 owner
做生命周期决策。projection、prompt、UI state、runner response 和离线 receipt 都只是各自权限内的
事实载体，不是第二套 canonical state。

## 4. Runtime 与协作语义

`POST /v3/sessions/{session_id}/messages` 只写入用户消息并排队 durable signal，不隐式
执行 teammate runtime drain。`POST /v3/sessions/{session_id}/runtime/drain` 只创建有界
runtime command，并返回 `202`；独立 worker 认领后推进 bounded turn。

`task.delegate` 的真实写路径是 `ProtocolService.delegate()`。`protocol.send` 只投递 inbox
并排队 wakeup，不同步运行 recipient。`auto_enqueue_ready_tasks` 默认关闭。

task 业务终态只能由 agent 显式 `task.finish` 或已文档化的机械迁移写入。runtime idle、
max steps、tool result、protocol message、job terminal、report publication 或 scientific
closure 都不自动等于 task completed。

在目标 Kernel 实现中，mounted Plugin finish validators 先进入 collision-safe closed registry；Task 固定适用
validator ID，调用方不能临时删减或换用另一个 validator。只有 canonical Task owner 的显式 `task.finish`
会运行这些只读 validator，并在 exact Task/Session version 与 AgentAuthorityLease generation/fence 重验通过后，
于一个 ControlStore Unit of Work 内写 terminal decision、durable event 和 outbox。validator failure、receipt、
publication 或 scientific closure 都没有自动 Task mutation authority；通用 Host 只经 Kernel application service
写入，不存在旧 Host writer 或双写路径。

目标 `openzyme-kernel` 已进一步实现只依赖 Contracts Ports 的 collaboration、Protocol、Approval、Authority、
Continuation、Failure、TaskEvidence 与 ControlledOperation application services。跨 Agent 同层通信统一写 canonical
protocol fact、inbox、durable wake signal 和 event/outbox，不同步执行 recipient；批准、continuation delivery、
failure observation、evidence registration 或 external terminal receipt 都不推断 Task 完成。retirement 先核对 owned
Task settlement，再推进 process epoch 并 revoke/advance authority fence。所有 effectful extension 共用同一
ControlledOperation intent/route/generation/effect-certainty/reconcile truth，未知 dispatch 不重试或换 route。
这些是当前 `@2` 写路径；历史数据库 adoption 仍只能离线执行，在线路径禁止双写或转换。

session runtime lease、signal claim、agent process epoch、controlled-operation execution
lease、continuation delivery fence、workspace generation 和 mutation writer fence 是不同
authority。一个 authority 的 idle、过期或终态不能推断另一个 authority 已完成。

后台 supervisor 只把结构化 `semantic_progress=true` 计作进展；lease、timestamp、poll、
version 或诊断变化不能冒充业务进展。未知 effect、缺失 handle 和序列化错误都显式失败。

## 5. Approval 与外部 effect

危险操作先创建结构化 approval request。批准只授予 exact operation digest、scope、owner
和时限，不允许 agent 在批准后替换参数、扩大路径或重开 blocked action。

`ControlledOperationExecution` 是通用外部 effect 的唯一 lifecycle owner。每次 worker slice
只做短 claim、dispatch、observe、materialize-result 或 reconcile，外部调用期间不持 SQLite
写事务。只有已证明 `no_effect` 的同 phase 才允许有界恢复；请求可能已经送达但结果未知时
进入 `dispatch_in_doubt`，禁止重发。

provider dispatch/observation receipt、opaque backend handle、absolute deadline、result
digest 和 fencing token 必须持久化。timeout 只说明观察窗口结束，不能推断 effect settled。

Workspace Runtime 已通过新 Kernel coordinator 接入这一顺序：先重验 Session/owner/generation、
operation-specific authority 与 explicit route，再持久化 admission，最后只调用 binding 指定的 provider。
Adapter 的 typed `no_effect`、known receipt 或 `dispatch_in_doubt` 都写回同一 ControlledOperation；未知
异常先登记 reconcile，再以 `raise ... from ...` 保留 cause chain。当前 production Host 尚未切换到该
coordinator，因此这不表示 local/HPC Adapter 已 cut over。

所有失败必须同时形成同一 `diagnostic_id` 关联的两层证据：公开
`failure_observation@2` 只包含稳定 `error_code`、component、operation、phase、typed identities、
effect certainty、retry/reconcile policy、`mutation_applied`、`fallback_performed`、安全 cause chain
和 next action；Host 私有 immutable diagnostic 保留完整 traceback、异常 `__cause__`/`__context__`、
errno/return code、bounded stdout/stderr、私有路径/handle 和相关 source identity。跨边界包装必须
使用 `raise ... from exc`。公开层按 allowlist 脱敏，但不得把未知原因改写为 not-found、corruption
或 retryable，也不得吞掉 cleanup、reconcile 或 diagnostic persistence failure。

## 6. Revision-bound HPC

目标架构中，formal execution 由 `openzyme-compute` Plugin 拥有；HPC target、inventory 和远端 workspace
由 `openzyme-hpc` Plugin 拥有；SSH/SFTP/rsync 与 Slurm 分别由 subordinate Adapters 实现。HMMER/Vina
等 Product Plugin 只声明 capability requirement 和 typed `ExecutionWorkloadSpec`，不 import HPC/Slurm。
Compute 的目标 application lifecycle 已位于 Plugin namespace：admission verifier 重验 exact
owner/authority/workspace/revision/LFS/route/inventory proof，dispatch/observe/reconcile/cancel 只调用注入的
route port，未知响应不 replacement；terminal result 只注册 owner continuation。当前以下段落仍包含尚待迁移
的已运行 `@1` repository/Host writer 路径，不能据此声称 production cutover。

HPC target inventory 必须是可解释的 append-only generation：Plugin namespaced persistence 保存
qualification receipt、software/hardware/data capability facts、predecessor、operator publication identity 和
完整 closure。旧 `toolchain_digest` 不再作为独立权威字段；target qualification、Compute source manifest、
runner config/wire 都绑定同一 positive `inventory_generation` 与 exact `inventory_digest`。后者只能是结构化
`TargetToolchainInventory` 的 closure，不能由 Runner 或领域 Plugin 从无结构字符串推断软件可用性。
这些 `openzyme_hpc_*` 表只由显式 offline migration 安装，Host 正常启动不得 opportunistically 建表。
EnzymeDesign fresh profile 现已把 qualification receipt、target inventory 和 scheduler occurrence 三张
HPC-owned 表纳入 exact owner schema；Standard profile 不安装它们。
Runner 的 closed `runner_effective_config@2` 也不接受 `[adapters.*]` 领域 catalog；修改
TOML 不能替代 Distribution 选择、Plugin/Driver contract、target qualification 或 Session inventory adoption。

executor 的登录数据面是 owner-scoped `ExecutorHpcWorkspace`。它可在自己的 generation
root 内使用原生 SSH、Git/LFS、rsync/scp 和文件 CRUD，但登录 credential 不含 scheduler
submit 权限。

`ExecutorHpcWorkspace`、provision/cleanup intent+receipt、credential claim 和旧 target qualification DTO
现在由 `openzyme-hpc` 唯一实现，旧 Domain 路径只作临时重导出。完整 application service、SQLite workspace
repository、Plugin manifest/tool/route runtime 和 Host 重验证 gateway 已实现；Core 不再保留 HPC service、
repository 或静态 tool writer。EnzymeDesign non-live application root 已完成 exact Distribution mount、`@2`
projection 及 SSH/Slurm Adapter identity/runtime factory 绑定；Agent 是否看到 `hpc.workspace.*` 仍由 Session
binding、authority、workspace readiness、target inventory 与 helper qualification 求交决定。真实 target
qualification 与 helper prerequisite 部署纳入当前 qualification change；Session adoption、生产 credential 激活和
live cutover 仍不在本 change 执行。

`openzyme-hpc-ssh` 已实现 target-scoped Observation/Filesystem/Process/Transfer Ports，使用私有 locator
解析 exact owner root、credential claim、workspace generation 与 target qualification。公开请求只含 opaque
workspace binding 和 root-relative path；hostname、login alias、remote root、credential 不越过 Adapter 边界。
lost response 保持 `dispatch_in_doubt`，reconcile 只观察同一 occurrence，且该 Adapter 永不携带 scheduler
authority。它消费 Store-owned durable Workspace occurrence ledger；terminal receipt 可跨 Adapter epoch 恢复，
uncertain receipt 只能经远端 wrapper 查询原 operation/request digest。它已被 EnzymeDesign exact composition
identity-mounted。target-qualified exact `openzyme-workspace-runtime` 现以
`software.openzyme-workspace-runtime == 1.0.0` resource capability 建模，私有 locator 同时绑定 helper build、
qualification receipt、target inventory generation/digest；缺失该事实时 remote tools 为
`blocked_qualification`。当前 change 现在包含标准库单文件 helper 的 source-bound 实现，以及 exact
Diannan `/home/grtresy/.local/libexec/openzyme-workspace-runtime` 的独立 principal-bound deployment plan、positive/negative qualification
和 compare-and-rollback。login/home/path/owner/mode 或 direct-user-libexec mechanism 未闭合时保持
`blocked_deployment_authority`，不得自动切换 `/usr/local`、`PATH`、相邻 executable 或另一用户目录；安装成功也仍不是 ambient、adopted
或 live capability。

`openzyme-hpc-slurm` 实现独立 `openzyme.hpc.scheduler-port@1`：只有 Compute admission 创建的一次性 formal
occurrence credential 可进入 submit/cancel；login/file credential 在类型和 resolver 上都被拒绝。raw Slurm id
只留在 HPC-owned SQLite occurrence ledger，公开层只持有 opaque handle；submit/cancel 在首次 effect 前原子
reserve exact identity，lost response 只 reconcile 同一 occurrence，不重新 submit/cancel，也不替换 scheduler、
target 或 route。EnzymeDesign 已把显式注入 backend/credential resolver/durable ledger 的 factory 绑定到 selected
Slurm Adapter 并在 proof 后构造 runtime；这不等于真实 Slurm target cutover 或 live 证明。

计算提交使用 `workspace_revision_execution_request@1`，必须绑定：

- exact private checkpoint 或 immutable publication；
- source ref、commit、tree、LFS closure 和 fresh clean observation；
- executor member、capability lease、remote workspace generation；
- cwd、command digest、environment policy、resource digest、target qualification；
- operation/execution identity、absolute deadline，必要时还包括 scientific admission。

runner 从修订准备计算源，计算 payload 不携带 `.git`、Git/LFS credential、LFS endpoint、
Host path 或 storage locator。公开生命周期只使用 opaque run handle。无 expected output 的
成功仍由 terminal observation 和 result receipt 表达；不能补造空文件。cancel 必须绑定同一
RunSpec、dispatch intent 和 opaque handle，并返回包含 `receipt_id` 的 canonical cancellation
receipt；cancel request 与 receipt 都不能冒充 backend terminal settlement。dispatch、observe、cancel
和 reconcile replay 在返回任何已存 handle/receipt 前都重新执行相同 identity/digest 校验。

## 7. Reporting extension

Reporting 是 optional semantic Plugin，不属于 Kernel 或 Standard semantic layer。目标
`openzyme-reporting` 已拥有 exact manifest、`openzyme_reporting` namespace transaction participant、
`report_draft.get/update`、`report.publish`、`report.render.request`、bounded projection/HTTP route、render worker、
UI renderer contract 与只读 finish validator。它只依赖 Contracts/Extension SPI，不 import Core repository、
SQLite Store、Host、Git/LFS 或 process implementation。

报告正文始终是 Agent workspace 中的文件；Reporting 只登记 clean published `RevisionPathRef` 和 bounded
metadata/receipt。draft、workspace publication、render、validation、business report publication 和 Task terminal
相互独立。finish validator 只在 Task owner 显式 `task.finish` 时核对 exact report contract/version/digest 和
已有 validation，不执行 render/publication 或任何写入。renderer/schema/authority/ref drift 均 fail closed，禁止
自动提交、发布、格式/renderer fallback 或从报告存在推导 Task 完成。

当前状态是 `target_implemented_not_cutover`：Core 已删除同名 tool 注册、restore/prompt 注入、
report-specific evidence 解析和 legacy repository writer；`session_report_*` rows 只为 offline historical adoption
保留，`@1` 历史 report collection 固定为空。EnzymeDesign non-live application root 已在 startup proof 后 exact
mount Reporting surfaces；当前最终 source 的真实离线采用仍未执行，因此不能提升为 deployment authority。详见
[Reporting Extension](v3/reporting-extension.md)。

SQLite 机制由 `openzyme-store-sqlite` 独占：文件/connection/WAL、短事务 UoW、Kernel codecs、owner-partitioned
schema、Plugin transaction participants、deployment proof 和 legacy-only migration readers 都在 Store。旧 Core
repository provider/UoW/compat exports 与 `CoreRepositories` 聚合已经删除。Kernel canonical mutation 只经
`SQLiteControlStore` 和 application services；Plugin state 只经 namespaced participant；Git workspace mechanism
由 Git/LFS Adapter 拥有。Standard/EnzymeDesign composition root 只在 read-only proof 与 exact mount 后构造同一
writer。上述 source/runtime closure 不等于当前最终 source 已真实 offline cutover。

## 8. Science extension 与 scientific file contract

Science 是 optional semantic Plugin，拥有 attempt、selection、disposition、adoption、deliverable、validation、
closure 和通用 workflow contract registry。目标 `openzyme-science` 已有 exact manifest、namespaced transaction
participant、tool/route/projection/worker/UI renderer contracts 和只读 finish validator；旧 Core/Host lifecycle、
repository、public `@1` 和物理表仍待 offline cutover，所以当前不得激活新 runtime 或双写。AOX roles、thresholds、
finalizer 和 workflow contract instance 不属于通用 Science，必须由 EnzymeDesign Plugin 注册。

Science 的目标 projection application 只通过 `ScienceProjectionStateQuery` 读取 extension state；SQLite 的
`SQLiteExtensionStateProjectionQuery` 按 composition allowlist、Session 和稳定复合游标返回 records，不向 Plugin 暴露
raw connection。Science 对每个 record 重验 namespace/Session/entity identity，attempt-scoped mutation 还重验 exact
attempt generation。`ScienceUiRenderer` 只读 namespaced payload，固定不写 Core state、不推导 Task terminal；
renderer/section digest 不匹配时阻止相应 mutation surface，不回退到旧顶层 scientific 字段。

当前 `enzymedesign-aox` 已成为 AOX workflow、历史/current contract 和 17-role scientific file bundle 的唯一
语义 owner，并拥有 AOX architecture qualification receipt 的 closed/current-historical contract；
`enzymedesign-aox-executor` subordinate Driver 拥有 fixed references、motif/threshold、similarity
graph、deterministic calculations 和 fixtures。旧 `openzyme-pipeline` wheel 与 Core/Host 中的 contract
authority 已删除。Host 中的 finalization application service 只实现通用 Science application
port；AOX finalizer 已归入 Product Plugin，并通过 `ScientificPublishedFileReadPort` 和
`ScientificDeliverableFinalizationPort` 与 Host 通信。通用 Host 只接收 Science 公开
handler/registry 端口；EnzymeDesign Distribution 构造 AOX registry、finalizer handler 和 exact
executor receipt validator。AOX qualification/fixture 同样由 Product Plugin/Driver 拥有；历史上不存在的
vertical route、worker、projection 或 UI renderer 不会为了补齐 manifest 而被虚构。
这也适用于 `@2`：当前 EnzymeDesign 垂直工具没有独立 canonical collection，formal execution 与科学结果分别
由 `openzyme.compute@1` 和 `openzyme.science@1` 投影，文件结果由 Kernel publication 投影；不得从 tool receipt
或 AOX 事件补造一个产品顶层 section。Research、Reporting、Science、Compute 与 HPC 则各自提供 exact
namespaced contributor，`@2.core` 不含这些旧 `@1` 顶层字段。

scientific attempt、selection、occurrence、disposition、effect adoption、deliverable 和 task
终态相互独立。一个 deliverable 必须引用已发布 revision 中的 exact file，并绑定一个当前
selection 内显式采用的成功 producer effect。

finalization 会从不可变 publication fresh-read Git blob 或 LFS bytes，逐项验证 path、role、
format contract、digest、size、producer adoption 和 bundle completeness，原子写入
`ScientificDeliverableRef`、bundle 与 validation receipt。未知、缺失或不匹配永不解释为
negative scientific result。

AOX/HMM 仍可作为显式 scientific workflow contract 使用，但历史 cutover campaign、旧
catalog identity 和历史导入修订不能被当前 attempt、publication、report 或 GO/NO-GO
自动采用。

closure receipt、validation、runtime wake 和 worker terminal 都不完成 Task；只有 owner 的显式 `task.finish` 才能
触发 Science validator。完整边界见 [Science Extension](v3/science-extension.md)。

## 9. 公开接口

当前源码唯一的在线公开媒体类型为：

`application/vnd.openzyme.file-workspace+json;version=2`

历史 `file_workspace_public@1` 投影曾只包含授权后的：workspace status、private revision fact、
published revision、report、scientific deliverable、external job/result、capability lease、
conversation、task/lane board、agents、approval、activity 和 failure observation。只有 owning
executor 的专用 view 可以返回经裁剪的 workspace locator。该形状现在只允许离线历史 reader 解释。

当前源码已推出 closed `file_workspace_public@2` contract；后续一次性离线 cutover 只负责让真实部署采用
这一已固定合同。基础 `core` section 公开
`AgentAuthorityLease`、Session capability binding 和 per-turn affordance identity，Plugin 数据进入
`extensions[plugin_contract_id]`。`@1` 不在原地扩字段，也不为 `AgentCapabilityLease` 提供 `@2` alias；
Client、CLI 和 Web UI 的生产代码已经只接受 `@2`，通用 Host 包根也已改为由 Distribution 显式注入的
`@2` workspace inspection/message/runtime-drain surface：它只能从 startup proof 后的 exact
`MountedExtensionSurfaces` 构造，并验证 activation/runtime-mount、layered release、Kernel query context、
Extension bundle、projection catalog 和 binding/affordance identity；共享 Client 必须把 Host 返回的
workspace-contract、release、public-contract、projection、binding、affordance 响应头与 closed 正文逐项
交叉验证后才形成 mutation scope。Core payload binding 还必须与 query context
一致，mutation 在业务 handler 前重验
projection scope。Plugin GET route 还逐项匹配 manifest owner/method/path/contract digest；Plugin mutation必须
通过 Kernel application service。未注入、身份漂移或 route 未挂载时 fail closed，不调用 `@1` builder 进行在线
翻译；Standard target startup 会验证并采用 deployment epoch，但真实历史 deployment 的离线 adoption 仍未执行。
Standard 已补齐该 surface 的真实 Core provider：SQLite target CAS ledger 用 nullable `session_id` 和 bounded
index 只找 canonical identity，payload 仍由 32/32 owner-table codec 重建和验 digest；Kernel 据此解析唯一
subject/root Agent、authority、latest binding、workspace readiness 和完整 affordance 分类。Distribution 再把
provider 与 verified empty Plugin mount 注入 Host，依赖方向是 Standard → Host，不允许 Host 反向选择 Standard。
未 provision workspace 只在 affordance snapshot 中表示为 generation `0`/blocked，不补造 workspace 真值。
Standard 现已用 `build_standard_kernel_application_runtime()` 将 Session bootstrap、Task/Lane/Agent、Protocol、
Approval、AgentAuthorityLease 与 message ingress 接到同一 target SQLite Store，并由
`build_standard_v2_host_app()` 形成真实 HTTP 组合。用户 principal 是消息 source，root Agent 仅以自己的 lease
执行 admission；一个事务写入 conversation、user-kind inbox 和 pending signal，明确不 drain、不推断 Task 终态。
尚未接入的 runtime/workspace/publication route 会 fail closed，不能回退旧 mixed Host。

Web UI 侧已实现独立的 `file_workspace_v2_state`、Core shell 与 manifest-declared extension renderer loader：
Core state 只消费 closed `@2.core`，extension payload 只进入 exact section renderer；renderer catalog、section
contract 或 renderer identity 缺失/漂移会禁用 mutation，且 Plugin-free Standard 不需要任何空的领域面板。
Core shell 同时重验完整 layered release 和 condensed ToolAffordance reflection；inactive/degraded Plugin 通过
blocked state 暴露原因，但对应工具不进入 dispatch 面，也不得自动改用其他 Plugin、route 或本地执行。
这些模块和负例测试已进入前端 build，当前 `main/controller/view/client` 已只接受 exact `@2`；但真实部署尚未
执行 offline activation，前端构建通过也不等于 production cutover。

旧 media type、旧 schema、旧 tool name 和旧 saved catalog context 返回不可重试的 closed
错误；Host 不做 alias 或 silent translation。CLI、UI、prompt、restore schema 和 tool catalog
作为同一 release bundle 由 digest 绑定。

## 10. 持久化与 final schema

目标 fresh install 按所选 Distribution 的 owner schema profile 安装分区 migration bundle，再顺序加载
Store-owned `001_composition_state.sql` 和 `002_deployment_proof.sql`。它以一个离线事务写 exact activation、
Extension/catalog identities、`openzyme_fresh_install_bootstrap_receipt@2` 和 tagged deployment state；receipt
绑定完整 schema/profile/migration source/wheel/table-owner/layered release identities，并明确未初始化 legacy
schema/storage。offline removal 使用独立 `openzyme_offline_cutover_ledger@2`，其三类 backup、Session
disposition、逐 item/error/byte closure 不能由 fresh receipt 代替。普通启动按 proof kind 重验 generation、
manifest、receipt digest 与 fresh/offline
closure。非空未知库、旧 generation、legacy structure、missing/tampered receipt、空缺或不完整 offline
ledger、以及 manifest drift 都在 mutation 前拒绝，并报告 expected/observed digest 且
`mutation_applied=false`。

SQLite connection 是 thread-affine 的。request、worker 和 bounded turn 在实际线程内创建
并关闭自己的 connection；短 canonical mutation 使用 `BEGIN IMMEDIATE`，任何 LLM、provider、
Git、runner 或进程等待都不能跨 SQLite 写事务。

历史升级分两阶段，且都只允许由 `openspec/changes/.../operator/` 下的离线程序执行：

1. 冻结旧数据库和 storage，建立 exact object/reference inventory，将 bytes 写入
   `refs/openzyme/history/*`，fresh-fetch 回读，写 typed rewrite 和不可采用回执，同时保留源；
2. 再次验证 13 个前序 receipt、历史迁移、静默、备份和 dry-run manifest，事务性重建 final
   schema，之后才按 explicit allowlist 删除 receipt 指定的旧字节。

部分删除会留下 `offline_removal_incomplete` 并阻止普通启动；重试只能处理同一 receipt 的
精确剩余 identity。恢复只能进入隔离旧环境，不能把已移除子系统重新接回 current runtime。
所有离线 operator 的临时 worktree、fresh clone 与 final-copy 都必须位于操作员显式给出的受界
绝对 working root；不允许从系统临时目录、当前目录或环境变量推断。非 historical replacement
必须复用冻结时已经存在的 typed revision/path/result/scientific identity，不生成通用字符串或
synthetic current record。

设备 fresh reset 是另一条显式破坏性管理边界，不属于 Kernel、Host startup 或 Agent tool。
`device_fresh_install_reset_inventory@2` 对每个绝对 target 固定 closed component kind、owner、旧
Distribution manifest、owner evidence、inode/device/content identity、删除方法和 recoverability；目录 owner
若不能证明整棵树，就必须提供 closed relative-path set，任何未知 sibling 都成为 blocker。source tree、Git 历史、
OpenSpec 历史和当前仍被 Session pin/发布引用的 repository-service Git/LFS truth 是强制 exclusions，target 与
exclusion 的任何祖先关系都在 mutation 前拒绝。只有已经由零 pin、零未结算 effect、精确 owner evidence 和单独
操作员授权共同证明为退役部署 storage 的旧 repository-service，才可改列为 reset target；fresh bootstrap 后创建的
新空服务根立即重新成为受保护的 current truth。执行前必须绑定覆盖 exact
Host/Plugin worker/runtime/process/runner/UI/SQLite/Git writer 且
unknown effect 为零的 offline quiescence receipt。

每次删除只产生同一 frozen inventory 下的 durable occurrence；没有自动 replay、target rewrite 或可恢复承诺。
同路径 fresh database 允许底层文件系统复用 inode，但 replacement admission 必须绑定原 deletion occurrence、
独立 fresh-bootstrap receipt 与 exact 新 content identity，且新旧 content digest 必须不同；不能把 inode 变化当作
创建证明，也不能仅凭路径存在追认 fresh 状态。
删除后的 `device_fresh_install_reset_receipt@2` 逐项绑定 post-delete absence，并闭合 source、wheel、文档、
zero-residual scan、目标 Distribution/composition、fresh database identity 与独立 fresh-bootstrap receipt。
reset receipt 与 bootstrap/deployment proof 互不替代，也不拥有 Session、Task、runtime、Plugin 或科学真值。
实现位于 `openzyme_store_sqlite.device_fresh_reset` 的 offline operator surface；旧
`openzyme_core.device_fresh_reset` 已删除。模块只负责 inventory、逐路径 occurrence 与 reset receipt，不能被
Kernel、Host startup 或 Agent runtime 导入为业务能力。真实设备操作必须另有 operator evidence；若删除发生时没有
先生成 frozen `@2` inventory/occurrence log，不得事后补造正式 reset receipt，即使后续 fresh bootstrap 已独立通过。

## 11. 验收边界

架构验收至少包括：focused unit/integration tests、12-family architecture qualification、external
qualification readiness、
fresh-install/restart、old-startup rejection、isolated offline migration/removal fixture、静态
source/schema/catalog scan、OpenSpec strict validation、前端 test/build 和
`./scripts/check-mainline.sh`。

architecture qualification 不是单一产品剖面：registry `@3` 固定
`kernel_fake_adapters@1`、`openzyme_standard_local_file_sqlite_git@1` 和
`enzymedesign_local_single_process_file_sqlite@1`。场景只为自己实际覆盖的剖面记账；Kernel fake
不加载 Store/Git/Host/runtime implementation/Plugin，Standard 验证 Plugin-free 本地组合，EnzymeDesign
验证 exact Plugin/Driver 组合。报告 `@4` 绑定 OpenSpec、source、wheels、Distribution/component
manifests、catalogs、inventory、schemas、文档实际字节、selection 与预算；`@1`–`@3` 只作历史读取。
资格子进程禁止 live credential、IP socket、skip 与 xfail；mainline 的 `premerge_subset` 包含三个剖面
的有界闭包，但不能冒充完整 qualification、部署 cutover 或 live 证明。

其中 Standard 的 schema/composition/restart suite 已证明只读 activation、SQLite schema、Git/LFS、Client、
空 Plugin mount，以及 `STANDARD_KERNEL_ENTITY_TYPES` 的 31/31 显式 SQLite codec closure；通过 exact
deployment gate 后可以构造 Kernel application writer。它仍未经过完整通用 Host caller + Plugin-free
collaboration qualification，因此不得把 Store writer admission 误记为完整产品路径。codec 缺失、重复或目录
漂移仍以 `standard_kernel_store_codec_incomplete` 在 mutation 前 fail closed。

拆分期间还必须运行 `uv run python scripts/check-openzyme-architecture.py`。该 gate 从实际
`pyproject.toml`、Python AST、Distribution 配置和 in-memory SQLite schema 重算 component/import/table
owner closure，并校验 source-to-document traceability；它是迁移门禁，不等于最终 cutover proof。

focused gate 通过不等于主线验收；mainline 失败时不得生成 acceptance receipt。live LLM、
provider、HPC 和 seeded smoke 同时需要 marker/profile opt-in 与独立 `OPENZYME_ALLOW_LIVE=1` operator gate，
也不能由 non-live 结果推断完成。普通 PR/dev CI 只运行 `OPENZYME_ALLOW_LIVE=0` 的 required readiness；
manual workflow 在本阶段仍为 plan-only，不读取 secrets、不调用真实 backend。真实部署的
迁移或删除必须另有明确目标、维护窗口、备份和 operator 授权；源码实现本身不构成执行授权。

## 12. 不变量

- harness 忠实、结构化、低摩擦地呈现世界约束，同时保留 agent 策略自由。
- authority、effect certainty、scientific truth、publication 和 task terminal 不互相推断。
- shared truth 只来自 typed repository 与 immutable revision，不来自 prompt、浏览器状态或临时目录。
- 没有隐藏 fallback、自动重试、silent schema translation、ambient path 或 manual override。
- external shell、plugin、framework 和 runner 是集成层，不替代 canonical control plane。
- 历史证据可以验证和读取，但不能升级为当前权限、发布、科学证据或产品真状态。
