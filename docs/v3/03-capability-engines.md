# V3 Capability Plugins、Drivers 与工具可用性

> 旧 `openzyme-engines` 的 Deep Research 实现与 Core 中按 `task.kind` 自动规划 Research 的第二 authority
> 已从 active workspace 删除。`openzyme-research`、`openzyme-research-tavily` 与
> `openzyme-science-research` 已建立 reference contracts、manifest、worker 和 non-live 验证；旧
> Host/Runtime 的 ambient bio/research wiring 已删除。通用 Host 只接受 Distribution 的 manifest-driven
> exact runtime mount；真实历史 deployment cutover 与 live Provider/HPC activation 仍是独立授权边界。

## Plugin、Adapter 与 Driver

Capability Plugin 增加语义能力，可以拥有自己的 namespaced state、tool、worker、projection、validator 和
qualification spec。Adapter 只实现已有 Port；Driver 隶属于 Plugin，把 typed request/result 映射到具体
route，不拥有新的顶层科学语义。

例如：

```text
openzyme.research Plugin -> Tavily Adapter
openzyme.hpc Plugin      -> SSH/SFTP/rsync Adapter + Slurm Adapter
enzymedesign.hmmer       -> Local HMMER Driver / HPC HMMER Driver
enzymedesign.vina        -> Container Vina Driver / HPC Vina Driver
enzymedesign.structure   -> Local fpocket Driver / HPC fpocket Driver
enzymedesign.alphafold   -> HPC AlphaFold 3 Driver
```

Plugin 不能 import Adapter client、其他 Plugin repository、Kernel repository implementation 或 Host 私有
service。跨 Plugin 协作必须声明 capability requirement，由 Kernel resolver 在 exact Distribution、Session
binding 和 route catalog 中求解。

当前 Extension SPI 已把通信面固定为：

- 十二类窄 Kernel application services：Task、Protocol、Approval、Authority、Publication、
  ControlledOperation、Continuation、Failure、CapabilityQuery、ExtensionInvocation、ExtensionState、
  TaskEvidence；
- 独立 Tool/Capability/Qualification/Route/Projection/Worker/Validator/Schema/Migration contributions；
- namespace-confined `ExtensionTransactionParticipant`，带 read/mutation/payload/time budget；
- 只有 `compile`/`validate_result`、没有 dispatch authority 的 `SubordinateDriver`。

具体字段、事务规则和 authoring 负例见 [Plugin 开发指南](plugin-authoring-guide.md)。

## Extension manifest 与激活

entry point 只定位纯 manifest，不能因 wheel 已安装就启用。Distribution 显式列出 required/optional Plugin、
Adapter slots 和 Drivers。Host 在任何 runtime surface 出现前原子验证：

- component/version/build/contract/manifest digest；
- required Kernel 与 Extension SPI contract；
- capability provider/version/operation/same-target dependency；
- tool、route、projection、worker、validator、Driver、migration namespace collision；
- migration/schema compatibility 和 Driver owning Plugin；
- dependency cycle、unknown/ambient component 和 Session pin。

required 缺失阻止启动；optional 未安装为 `inactive`；manifest 合法但当前 resource route 不足可
`degraded`。optional 的 schema/digest/migration/collision/cycle 错误仍阻止启动，不能当成“可选所以忽略”。

实现中的 route 分为 capability route 和 delivery HTTP route：前者绑定 capability/target/Driver，后者以
closed method enum 和 normalized template path 声明。`GET /x` 与 `GET /x/` 会归一为同一 key；query、fragment、
percent encoding、空 segment 和重复 template parameter 被拒绝。两类 route ID 也不得交叉重名。所有 catalog
先在内存构造并完成碰撞校验，再作为一个 composition 结果发布，不存在 partial registration。

当前 target Kernel 的 activation 顺序已经由代码固定：三类 `ReadOnlyDeploymentVerification` 先证明 exact
composition、core schema 与 installed wheel set，随后才产生 `DeploymentActivationEpoch`；gate 未 active 时
writer、HTTP route、worker、runtime、external effect 全部拒绝。Plugin runtime bundle 的 tool、capability/HTTP
route、projection、worker、finish validator 与 transaction participant 必须与 manifest exact set 相等，且
Driver 只能挂到 owning Plugin 的 exact route。验证在 immutable mount set 返回前完成，失败时没有 partial
registry。通用 Host 只挂载 Distribution 已验证的 exact surfaces，不存在旧 Host composition fallback。

Plugin upgrade/removal 只能在 quiescent offline verifier 下评估。non-terminal Session pin/continuation、
unsettled operation、没有 disposition receipt 的 owned state，或升级时缺失 migration plan 都阻止新 epoch。
Verifier 不迁移、不删除、不重试外部效果；新安装 optional Plugin 只能属于新 epoch，旧 Session pin 不变。

## 四类能力事实

| 事实 | 回答的问题 | writer/变化频率 | 不能证明 |
|---|---|---|---|
| `ExtensionCapabilityFact` | 部署激活了什么语义能力 | composition activation / release | target 有软件、Agent 有权、当前可调用 |
| `ResourceCapabilityFact` | exact target inventory 上有什么 | operator qualification/adoption | Plugin 已启用、Agent 有权 |
| `AuthorityGrant` / `AgentAuthorityLease` | Agent 被允许做什么 | Kernel lease/generation/fence | 软件存在、route 健康 |
| `ToolAffordance` | exact Agent turn 此刻能调用什么 | Kernel resolver / per turn | 未来仍可用或 effect 已发生 |

旧 `AgentCapabilityLease` 公开名会在 `@2` 改为 `AgentAuthorityLease`，因为它表达权力而不是工具可用性。
首轮保留旧物理表名，但公共 Contracts 不导出旧别名。

## Declared catalog 与 effective affordance

`DeclaredToolCatalog` 是 Kernel base tools 加 exact activated Plugin manifests 的静态契约集合，包含：

- canonical dotted tool name、owner 与 runtime ID；
- closed input/output schema 和 tool contract digest；
- required authorities、approval policy、capability requirements；
- workspace/route requirements 与 extension bundle identity。

`openzyme-contracts.ToolSpec` 是这一规格的唯一 canonical DTO；输入/输出 schema 在内存中
冻结，在 public/provider 投影时还原为标准 JSON。公开 `ToolInvocation`/`ToolResult` 必须携带完整
identity 且不包含 private diagnostic。迁移期旧 handler 的 process-local
`ToolDispatchInvocation`/`ToolDispatchResult` 只是 Runtime 内部过渡类型，不是 Plugin 契约或
`@2` 公开词汇。

任何 canonical collision 都在 activation 阶段 all-or-nothing 失败；旧 `EngineRegistry` 也不再允许重复名称
后写覆盖。

每个 bounded turn 由 Kernel 对以下事实求交生成 `ToolAffordanceSnapshot`：

```text
Plugin active
∩ dependency resolved
∩ Session capability binding
∩ target inventory qualification
∩ compatible route
∩ Agent authority
∩ workspace readiness/generation
∩ task/role policy
∩ current target health
```

closed states 为：`AVAILABLE`、`AVAILABLE_WITH_APPROVAL`、`BLOCKED_DEPENDENCY`、
`BLOCKED_CONFIGURATION`、`BLOCKED_QUALIFICATION`、`BLOCKED_AUTHORITY`、`BLOCKED_PROVISIONING`、
`TEMPORARILY_UNAVAILABLE` 和 `HIDDEN`。模型 function list 只含前两者；只读 `capabilities.inspect`
可显示非隐藏 blocker、requirement 和安全 target identity；`HIDDEN` 不在任一表面泄露。

瞬时 health 不改变 release/declared catalog digest。dispatch 前重新验证 snapshot、lease、binding、workspace
generation、health 和 explicit route；变化统一以 `tool_affordance_stale`、`no_effect`、零 fallback 拒绝。
队列繁忙但 scheduler 仍接受 job 时 route 仍 available；continuation 永远绑定原 route。

当前 Kernel 实现已将这个闭环分成 `ExtensionBundleRegistry`、`CapabilityRegistry`、
`DeclaredToolCatalog` 和 `ToolAffordanceSnapshot`。Resource fact 必须同时匹配 Session 采用的 target、
inventory generation 与 inventory digest；route proof 进一步固定 provider、driver、target、inventory、
capability proof 和 route digest。`ToolDispatchAdmission` 保存这些安全 identity，续运时只重验
原 route，即使其他 route 出现也不会自动迁移。
每个 snapshot 还绑定 Session/member/Task/role 的 `subject_policy_digest`；typed policy decision 只能
allow、block 或 hide exact tool，policy 变化会使 dispatch stale，不会由 Runtime 自行解释 role。

`capabilities.inspect` 返回 required/optional Plugin 的 active/inactive/degraded 安全状态、四类能力
identity、非隐藏 blocker 和 route proof；不返回 credential、SSH host/login、remote path、binary
locator 或 raw probe output。模型 function list 只从同一 snapshot 中选取 `AVAILABLE` 与
`AVAILABLE_WITH_APPROVAL` 的 `ToolSpec`。

`MountedRuntimeCapabilityGateway` 是这一约束进入 bounded runtime 的唯一桥：`list_tools` 必须携带 exact command
和 snapshot digest；`invoke` 再从 command scope 取得 current context 并调用 `revalidate_tool_dispatch`。只有
manifest/runtime/tool-contract 与 admission identity 全部一致时才进入 Plugin runtime。stale 或未挂载在调用前
返回 `no_effect`；runtime 抛出或 receipt identity 漂移时不得假称未执行，而是返回
`dispatch_in_doubt + reconcile_required`，且 `fallback_performed=false`。

Gateway 之前还必须建立 `MountedRuntimeToolSet`。它把 Kernel base runtime 与
`MountedExtensionSurfaces.tools` 分开接收，再按 active release 的 `DeclaredToolCatalog` 做 exact closure：每个
声明必须恰有一个 runtime，且 owner component、runtime ID 和 contract digest 完全一致；missing、unexpected、
collision、catalog/activation drift 均拒绝整个 runtime surface。Kernel base runtime 使用
`owner_component_id=openzyme.kernel`，不占用 Plugin bundle，也不改变 Plugin-free Standard 的零 Plugin 事实。

## Target inventory 与 qualification

Tool Plugin 提供 declarative `QualificationSpec`：capability ID、版本范围、operations、version query、
deterministic smoke、expected result schema，以及 software/hardware/data/asset/license requirements。它不能在
import、catalog build 或 Agent turn 中自行 SSH/`which` 探测。

HPC/Compute operator workflow 选择 exact target/environment，通过 Adapter 执行 probe，并生成不可变
`TargetToolchainInventory` generation、`SoftwareQualificationReceipt` 和 resource facts。只有 operator/admin
可 publish/adopt/revoke；Session 通过 immutable `SessionCapabilityBindingRevision` 显式采用。qualification
validity 与 transient health 分开：expired/revoked 阻止新 dispatch，health 恢复不改变 inventory identity。

Target inventory 是可解释的 append-only closure，而不是 opaque toolchain 字符串。HPC Plugin 的
`openzyme_hpc_*` namespaced tables 保存 exact qualification receipts、capability facts、inventory JSON closure、
generation predecessor 和 operator publication identity；安装 schema 只发生在显式 offline migration。
target qualification、Compute source manifest 与 runner wire 同时绑定 positive `inventory_generation` 和 exact
`inventory_digest`。Runner 不接收任意 inventory payload，也不能仅凭无结构来源的 digest 声称软件存在。
Runner 的 TOML 也是闭合配置，只能选择 transport/workspace/scheduler 和有界资源策略；
`[adapters.*]` 形式的领域软件 catalog 会在解析时拒绝，不能绕过 Plugin/Driver manifest 和 inventory adoption。

HPC Plugin 现已提供显式 `openzyme_plugin_manifest@1`，声明 `openzyme.hpc.target-inventory@1`、
`openzyme.hpc.workspace@1`、`openzyme.hpc.compute-route@1`，以及
`hpc-primary.workspace-runtime`、`hpc-primary.revision-job` 两条 route。它处于
`target_implemented_not_cutover`。8 个 `hpc.workspace.*` ToolSpec、runtime 与两条 route runtime 已由
Plugin 精确实现；`openzyme.hpc@1` bounded projection、只读 renderer contract 与 bounded worker 也由同一
manifest 注册。Host 的窄 bridge 对每次调用重验 opaque workspace owner、local/remote generation、target、
qualification 和 operation authority。完整 lifecycle application 与 SQLite workspace repository 已由 Plugin
唯一实现，只消费窄 Kernel facts Port 和显式 UoW；Host 不再拥有第二套 service/writer。manifest/runtime
存在仍不等于某个 Distribution/Session 已激活；EnzymeDesign 的 non-live application root 已 exact mount 这些
surfaces，但每个 Session 仍须 pin bundle/binding，工具仍须通过逐 turn affordance。`@2` projection 只从 exact
mounted surfaces 读取。SSH 与 Slurm Adapter 只实现对应 Port，
不能成为上述语义 owner。

## HMMER 调用 HPC

`enzymedesign.hmmer` 声明：

```text
requires openzyme.execution.revision-job@1
requires software.hmmer >=3.3,<4 operations=[hmmbuild,hmmsearch]
requires same target for execution and software capability
```

`openzyme.hpc` 可以提供 `hpc:primary/hmmer:3.4` route，local/container provider 也可以提供兼容 route；
HMMER Plugin 不知道供应者包名。Agent 看到 route-bound affordance 后显式选择 route，HMMER Driver 将请求编译
成 closed `ExecutionWorkloadSpec`，`openzyme.compute` 监督正式 dispatch/observe/reconcile/cancel/result，
SSH/Slurm Adapter 只执行其 Port。

`openzyme-execution-contracts` 只拥有 closed workload、revision input、result contract、exact
route/inventory identity、safe failure 与 runner wire；formal admission/source manifest/
qualification/dispatch/result DTO 由 `openzyme-compute` 拥有。sandbox client protocol 位于
`openzyme-execution-sdk`；旧 `openzyme-pipeline` wheel 已删除。AOX semantic contract 由
`enzymedesign.aox` 唯一拥有；calculations、fixed references、motif/threshold、similarity graph 与
deterministic calculation manifest 由它的 subordinate `enzymedesign.aox.executor` Driver 实现。

直接 `hpc.workspace.exec(["hmmsearch", ...])` 是允许的探索性 Shell，只产生 process operation receipt。
它不能成为 formal Compute result、Scientific adoption、publication 或 Task finish evidence。正式工具也不能
因 HPC 不可用而偷偷切到 local/container route。

`enzymedesign.docking.preprocess` 则唯一拥有 molecule/docking 前处理。其 exact manifest 声明
`software.rdkit`、`software.meeko` 与 `software.openbabel` 的版本、operation 和 qualification；工具只接收
closed operation、workspace-root-relative 输入/输出路径和 idempotency identity，不接收 Host path、任意
command、credential 或 target。旧 `preprocess-backend` wheel 已退出 workspace。资源缺失只会使这一 optional
Plugin degraded，不会触发隐式转换器 fallback，也不会把私有输出提升为 publication、Science 或 Task terminal。

`enzymedesign.sequence.toolpack` 现已拥有 bounded FASTA/plain parser，以及 UniProt、RCSB、InterPro 的
provider-neutral ToolSpec。纯解析不产生外部效果；数据库工具要求 explicit route 与对应 provider capability，
不得在 import/catalog/Agent turn 中自行 HTTP 探测，也不得缺 Provider 时切到浏览器、其他数据库或本地缓存。
下载或查询 receipt 仍不是 publication、Science adoption 或 Task finish evidence。Provider Plugin
manifest/route 由 `enzymedesign.bio-providers` 声明，HTTP mechanism 由
`enzymedesign.bio-provider-http` Adapter 实现；二者由 EnzymeDesign Distribution 精确选择。
Host/runtime caller 的正式 activation 需要 exact Distribution、deployment epoch、Session pin、binding 与
affordance proof；不得以包已安装代替激活证明。真实历史数据库 cutover 是独立离线操作。

`enzymedesign.aox` 现已拥有冻结的 historical workflow reader、当前 workflow contract、17-role
scientific file-bundle contract、file-bundle finalizer、architecture qualification receipt contract 与 exact
manifest；`enzymedesign.aox.executor` 拥有全部 AOX pure
calculations/fixtures，并以 exact Driver manifest 绑定 owning Plugin、execution SDK 与 result contract。Plugin manifest 只声明
已经存在的 capability 和 dependency，不虚构历史上不存在的 route、worker、projection、qualification 或 UI
renderer。AOX file-bundle finalizer 已迁入 Product Plugin；通用 Host 只接收
`ScientificDeliverableRequestHandler` 和 `ScientificWorkflowContractRegistry` 公开 Science 端口，
不 import AOX 或 executor。EnzymeDesign Distribution 构造 exact AOX registry、finalization handler 和
calculation-receipt validator；handler 运行时再使用 Host 提供的
`ScientificPublishedFileReadPort` 与 `ScientificDeliverableFinalizationPort`。

旧 `openzyme-tools` 已从 workspace、Host dependency、锁文件和 active source tree 删除。原静态 HPC catalog
不再是工具或资源真值：`enzymedesign.structure` 唯一拥有 fpocket tool/qualification/local-HPC Drivers，
`enzymedesign.vina` 唯一拥有 Vina tool/qualification/local-HPC Drivers，`enzymedesign.alphafold` 唯一拥有
AlphaFold 3 tool/qualification/HPC Driver。软件、模型参数、数据库、CUDA 与硬件可用性由 exact target
inventory 证明；垂直 manifest 只声明 capability requirement，不能用 Markdown skill catalog 或包内二进制
路径替代 qualification receipt。Core 的 `SkillRegistry` 默认目录为空，只有 Distribution 显式挂载的
manifest-bound catalog 才可被读取，因此安装残留不能形成 ambient capability。

## Research、Reporting、Science 与 Compute

- Research Plugin 拥有 provider-neutral request/source/evidence、invocation state、bounded orchestration、
  `deep_research.start`、worker 与 projection；Tavily 是独立可选 Provider Adapter。Agent 显式 admission，
  worker 通过 ControlledOperation dispatch/observe/reconcile；response loss 不重发、不换 Provider。
  provider transcript/source receipt 不是 publication 或 Task evidence，durable prose/index 必须由 Agent 写入
  workspace 并显式链接 `PublishedRevision + RevisionPathRef`。`openzyme.research@1` projection 现在使用
  独立于 tool contract 的 exact digest，以 invocation ID 做稳定排页，
  只输出 Session-scoped invocation、bounded source 与 publication ref；Provider transcript、raw response 和
  私有 locator 不进入该 section。其 tool/projection/worker 由显式 runtime surface builder 产生，再由
  Distribution 交给 Kernel mount gate，manifest discovery 本身不会激活它们。
  PubMed、Semantic Scholar 与 literature quorum
  的 owner 是 `openzyme-science-research`；基础 Host/Runtime 已不再构造这些能力。UniProt/RCSB/InterPro
  的 DTO/Port、capability/route 和 HTTP mechanism 已依次归属 `enzymedesign-core`、
  `enzymedesign-bio-providers` 和 `enzymedesign-bio-provider-adapters`；EnzymeDesign non-live application root
  已按 exact Distribution 选择并 mount，它们仍须经过 Session binding/authority/route admission 才能调用。详见
  [Research Extension](research-extension.md)。
- Reporting Plugin 拥有 draft/render/format/validation/projection/finish validator；report 文件仍通过发布修订
  共享，任何 draft/render/publication 都不自动完成 Task。`openzyme-reporting` 现已实现 exact manifest、四个
  tool runtimes、namespace transaction participant、bounded projection/HTTP route、render worker、UI renderer
  contract 和只读 finish validator；它不 import Core repository、Store implementation、Host、Git 或 process
  Adapter。Core 已移除旧 descriptor/function handler、restore/prompt 注入、report evidence 解析和 repository
  writer；`@1` 历史 collection 固定为空。当前状态是 `target_implemented_not_cutover`：Standard
  不选择它；EnzymeDesign non-live application root 已从 verified Plugin mount 装配这些 surfaces，但这不等于
  当前最终 source 已真实 deployment cutover。详见
  [Reporting Extension](reporting-extension.md)。
- Science Plugin 拥有 attempt/selection/occurrence/disposition/adoption/deliverable/closure；validator 只返回
  read-only result，只有 Task owner 的显式 `task.finish` 写终态。`openzyme-science` 已实现 exact manifest、
  六个 lifecycle tool runtimes、workflow registry、namespace participant、bounded projection/HTTP route、worker、
  UI renderer contract 和 finish validator；它不 import Core repository、Store、Host 或 HPC Adapter。旧
  Core/Domain lifecycle、repository 与 Host `@1` writer 已删除，catalog 不存在同名第二 authority；Plugin
  activation 仍必须来自 exact Distribution/session mount。详见
  [Science Extension](science-extension.md)。
- Compute Plugin 已提供 manifest、closed tool runtime、projection/UI-renderer、worker、transaction participant 和
  provider-neutral formal application lifecycle。它使用 admission verifier 核对 exact
  owner/authority/workspace/revision/LFS/capability binding/route/inventory，并复用唯一 Kernel
  ControlledOperation；Plugin 自身不保存第二套 effect certainty、retry 或 cancel 状态。HPC 只是可选 route
  provider，Compute 不要求 Slurm 存在。每个 admission/observe/reconcile/cancel/continuation phase 使用派生自
  formal request 与 provider receipt 的独立幂等身份；`effect_known` 后仍可沿 original operation/route 观察到
  terminal，cancel intent 不覆盖原始 dispatch intent。generic Host 不硬编码 Compute；manifest 只有在选择它的
  Distribution/deployment epoch/Session pin 中才激活。

## Workspace Runtime 边界

Kernel Contracts 定义 Observation、Filesystem、Process、Transfer Ports。结构化 CRUD 优先于 Shell；path 必须
root-relative，拒绝 absolute、`..`、glob 与 link escape。exec 默认 exact argv、foreground、non-interactive、
bounded timeout/stdin/stdout/stderr；需要 shell 语义时必须显式使用 `/bin/sh -lc` argv。

status/stat/list/read/hash 是 query-only。mutation/exec/transfer 在 dispatch 前建立 durable ControlledOperation，
远端响应丢失可能是 `dispatch_in_doubt`，不自动 retry/换 target。Local `workspace.*` 与 remote
`hpc.workspace.*` 暂保留不同模型工具名，以公开其不同 credential/effect/reconcile 语义。

`openzyme-hpc-ssh` 现在实现上述四个 remote Workspace Runtime Ports。Adapter 通过私有 locator resolver 将
opaque workspace binding 解析为 exact owner root 和 credential claim；公开 DTO 永不携带 hostname、login alias、
remote root 或 credential。SFTP CRUD、SSH argv 和 rsync transfer 都回绑 operation/request digest；
`reconcile()` 只查询同一 occurrence，不调用 dispatch，也不获得 Slurm/scheduler authority。远端 helper 以
`software.openzyme-workspace-runtime == 1.0.0` resource capability 建模，exact build、qualification receipt 与
target inventory generation/digest 同时进入私有 locator；缺失事实时工具为 `blocked_qualification`。EnzymeDesign
已 selected 并 identity-mounted 该 Adapter，但真实 target 上的 helper 安装/qualification 和 live cutover 未执行。

`openzyme-hpc-slurm` 单独实现 `openzyme.hpc.scheduler-port@1`。它只接受 Compute admission 创建的 exact
scheduler occurrence credential；login/file credential 在类型与 resolver 上均不满足 submit。raw Slurm job id
只保存在 HPC-owned 持久 SQLite occurrence ledger，公开层只有 opaque handle。submit/cancel 在 effect 前原子
reserve provider/kind/operation/request；丢响应时，新 Adapter epoch 分别调用
`reconcile_submit`/`reconcile_cancel` 观察同一 occurrence，禁止重新提交、重新取消、换 scheduler 或换 route。
EnzymeDesign application root 只在 startup proof、exact Adapter set 与 Plugin mount 通过后，才用显式 backend、
credential resolver 和该 ledger 构造 selected Slurm runtime；这不代表真实 Slurm 已 cut over。

HMMER/Vina 的正式产品 binding 同样在 writer 暴露前一次性完成。它不接受工具参数自报的 authority、workspace、
revision 或 target truth，而是读取 canonical `PublishedRevision`、publication-owned path verification、ready owner
workspace、当前 authority lease 和 adopted Session capability binding；submit 前重新核对 route、inventory
generation/digest 与 capability proof。当前 non-live 产品资格场景通过通用 Host 和真实内部 composition 运行这条
链，只把 Agent-turn、Git-shaped revision backend 与 external Compute runner 明确替换为测试 Port，并证明
terminal result 只生成 owner continuation，Task 不自动完成。该证明不提升为真实 HPC/Slurm cutover 或 live。

## 错误与策略自由

Plugin/Adapter error 必须保留 stable code、component/phase、typed identities、effect certainty、
mutation/fallback facts、retry/reconcile policy 和 `diagnostic_id`，私有 cause chain 使用 `raise ... from exc`。
任何 broad catch 都不能伪装 success、改参数、自动换 provider/route、自动完成 Task 或合成文件。

Kernel 呈现真实约束与可用 routes，不替 Agent 选择科学策略。Plugin 可以提供 typed formal semantics 和证据，
但不能把隐藏 plan、固定 workflow phase 或领域判断塞进通用 Kernel。
