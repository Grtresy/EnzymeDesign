# V3 Public Interfaces

> Client、CLI 和 Web UI 的生产代码已经只接受 exact `file_workspace_public@2`；通用 Host 也已有独立
> `create_v2_app()` composition surface。Standard 已接入 Session、Task、Lane、Agent、Protocol、Approval、
> AgentAuthorityLease、message ingress、runtime turn、workspace CRUD/exec/checkpoint/publication/handoff 和
> event/restore/continuation 的 exact application/runtime closure。真实历史 deployment 仍未执行一次性离线 cutover；
> non-live 目标组合完成不得冒充已部署
> cutover，更不得原地扩展或在线翻译 `@1`。

## Media contract

当前源码唯一的公开 workspace contract：

```text
file_workspace_public@2
application/vnd.openzyme.file-workspace+json;version=2
```

Host、CLI、UI、SDK、event/restore schema 和 tool catalog 作为一个 digest-bound release bundle。
任何混合版本、旧 media、旧 catalog 或 stale continuation 都 fail closed，不做 dual serialization。

## Host API

通用 Host contract 与 Standard 当前已接入的主要接口：

- `POST /v3/sessions`：pre-Session bootstrap 只绑定 exact release/public-contract identity，由 Distribution
  gateway 经短时 operator authorization 原子创建 Session、master、root `AgentAuthorityLease`、revision-1
  capability binding、composition pin、exact repository pin、`WorkspaceGeneration` reservation、pending
  exact-generation lease 与 durable provisioning intent；HTTP 返回公开 readiness，不等待 Git/LFS、volume
  或 capsule 外部工作；
- `POST /v3/sessions/{id}/messages`：写消息和 wakeup signal，不同步 drain；
- `POST /v3/sessions/{id}/tasks`、`.../finish`、lane/agent/protocol/approval/authority routes：
  通过 Standard Kernel application gateway 执行 exact CAS command；
- `GET /v3/sessions/{id}/workspace`：读取 file-first public projection；
- `POST /v3/sessions/{id}/runtime/drain`、workspace CRUD/exec/checkpoint/publication/handoff：已定义
  closed Kernel route contract，但 Standard 只能在对应 application runtime 真实注入后开放，不能由
  Host 空壳模拟成功。

request authentication、session access、owner/member、capability lease、generation 和 media version
在路由层先验证，核心 mutation 下沉 service/repository。

共享部署中的 executor owner view 只接受身份为 `agent-member:<member_id>` 且角色精确为
`agent` 的 principal；该 principal 只可调用自己的 `GET .../workspace`，并由 Host 重新读取
session membership、lease 与 generation。调用方不能通过 query/body 声明 subject。普通 user、
operator、admin 和浏览器 UI 使用 general catalog，agent principal 使用独立 executor catalog；
二者都必须与同一 release bundle 精确匹配。

## Workspace projection

`@2` 的 closed root 已在 Contracts/Kernel 实现，形状为：

```json
{
  "schema_version": "file_workspace_public@2",
  "release": {
    "schema_version": "openzyme_layered_release_identity@1",
    "kernel_contract_digest": "sha256:...",
    "core_schema_digest": "sha256:...",
    "adapter_bundle_digest": "sha256:...",
    "extension_bundle_digest": "sha256:...",
    "declared_tool_catalog_digest": "sha256:...",
    "route_catalog_digest": "sha256:...",
    "projection_catalog_digest": "sha256:...",
    "migration_catalog_digest": "sha256:...",
    "workspace_backend_digest": "sha256:...",
    "host_build_digest": "sha256:...",
    "client_build_digest": "sha256:...",
    "release_digest": "sha256:...",
    "public_contract_digest": "sha256:..."
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
    "openzyme.science@1": {
      "section_contract_digest": "sha256:...",
      "payload": {},
      "next_cursor": null,
      "projection_digest": "sha256:..."
    }
  }
}
```

Kernel 组装器要求 mounted projection runtime 与 authorized projection catalog 精确一致，为每个
section 传入 item/byte budget 和 cursor，再校验 result identity、digest、section byte budget 与全局 byte
budget。credential/token/private key/Host path/HPC remote root/login alias/scheduler handle 等字段在公开边界
直接拒绝。Core 的 object/array section kind 与递归字段词汇也是 closed contract 的一部分；artifact-era、
`AgentCapabilityLease` 和任何 Research/Reporting/Science/Compute/HPC/EnzymeDesign-owned nested field 都会在
组装前失败，不能用嵌套字典绕过 owner partition。候选 Host surface 只接受已通过 startup proof 的
`MountedExtensionSurfaces`，并由 `FileWorkspaceV2HostSurface.from_mounted_surfaces()` 一次绑定 exact activation、
runtime mount、release、Kernel core provider 与 projection contributor；不能扫描环境或手工补装 contributor。
之后通用 `create_v2_app()` 才为 exact workspace inspection、Distribution 选定的 Kernel mutation route 和
manifest-mounted Plugin GET route 调用该组装器；每个 Session-scoped mutation 在 command gateway 前重验 release/public contract/projection/binding/
affordance identity，inspection 同时重验 Core payload binding 等于 Kernel query context binding，且 declared
catalog 与 extension bundle 等于 release。未挂载 route 不存在，identity stale 在 command gateway 前拒绝。以上失败都明确
`mutation_applied=false`、`fallback_performed=false`，不会调用 `@1` builder。该 seam 是 non-live cutover
preparation，不是已执行 offline activation 的声明。Plugin HTTP runtime 还必须逐项匹配 manifest 的 owner、
method、normalized path 和 contract digest；当前 query SPI 只接受 GET，mutation 不能绕过 Kernel application service。

Standard 的候选生产路径不再使用测试 fake：`SQLiteControlStore.list_for_session()` 以 target CAS ledger 的
Session 索引做 `LIMIT + 1` 查询，每个 identity 仍通过 owner-table codec 重建并验证；
`KernelPublicWorkspaceProjectionService` 从这些 canonical records 解析唯一 subject/root Agent、active
`AgentAuthorityLease`、latest `SessionCapabilityBindingRevision` 和 local workspace readiness，再使用 Distribution
提供的 exact capability registry 计算 affordance。尚未 provision workspace 时，projection 使用 bootstrap
已经保留的 exact generation 并报告 `provisioning`；workspace-required tool 为 blocked，不得用 generation `0`
或临时空 workspace 代替 reservation。snapshot ID/timestamp 从当前事实稳定派生，
不会仅因重复 GET 改变 mutation header。Standard 最后以 `build_standard_file_workspace_v2_host_surface()` 将
provider、active release 和 empty Plugin mount 注入通用 Host。`build_standard_kernel_application_runtime()` 已把
真实 Session bootstrap、Task/Lane/Agent、Protocol、Approval、AgentAuthorityLease 与 message ingress application
接到同一 target SQLite Store；`build_standard_v2_host_app()` 再完成通用 security/Host 组装。消息 ingress 原子写
conversation、user-kind inbox 和 pending runtime signal，但不隐式执行 drain、不完成 Task。显式 runtime drain、
local workspace filesystem/process、checkpoint、publication 与 handoff route 已接到 exact Standard operational
selection；缺少任一选定 Port 时 Host 构造失败，不调用旧 writer。默认 deployment 仍未执行 offline activation，
且不会把 legacy Session 在线翻译。

workspace projection 同时保留两种不同的版本事实：`state_version` 是 Control Store record CAS，
`workspace_state_version` 是 `WorkspaceGeneration`/`WorkspaceRuntimeBinding` 同一 logical generation 内的生命周期
版本。二者不得覆盖或互相推导。

`openzyme-client` 的 `@2` guard 不只 pin release。一次 workspace inspection 必须从
`core.capability_binding.binding_digest` 与 `core.tool_reflection` 交叉得到同一个 binding digest 和 exact
`affordance_snapshot_digest`；mutation caller 必须回传这两个 identity。Client 在 inspection 时先把 Host 的
workspace-contract、release、public-contract、projection、binding、affordance 六个响应头与 closed 正文逐项
交叉验证；在 mutation transport 前再次重验 release/public contract/binding/affordance，并把 projection、
binding、snapshot digest 写入请求头。任一漂移
返回 typed stale error，`mutation_applied=false`、`fallback_performed=false`。Host 候选 surface 已实现相同的
server-side mutation identity admission；pre-Session bootstrap 只验证 release/public contract，不虚构尚不存在的
projection/binding/affordance。CLI 的生产模式已通过共享 Client/Contracts 完成 bootstrap 以及 inspection →
exact-bound message mutation；其他 command 只有在当前 Distribution route closure 内才能发送，否则在
transport 前失败。Web UI 生产
client/controller/view 同样只消费 @2；二者都不会把 `@1` response 转成 `@2`。event/restore/continuation 与真实
deployment epoch cutover 仍待收口。

共享 projection 只输出：

- Core 中的 Session/Task/Lane/Agent/Protocol/Conversation/Approval/AgentAuthorityLease；
- Core 中的 capability binding、runtime、workspace generation/checkpoint/revision verification、publication、
  provisioning intent/readiness、workflow authority/link、Direct/Deferred/Hidden exposure、ordered runtime
  transcript/outcome、ControlledOperation/continuation/task evidence/command receipt 与 failure observation；
- exact Plugin section 中的 Research、Reporting、Science、Compute/HPC 状态。

每个来自 canonical record 的 Core object/array item 都显式包含其 `state_version`，供后续 CAS command 构造；
该字段是 Kernel record revision，不是 authority fence、workspace generation 或 Plugin entity version，任何 payload
自身占用同名字段都会使 projection fail closed。

禁止输出 credential/token、private ref、Host path、remote directory、raw runner/Slurm handle、backend log、
storage locator、materialization/staging state。owning executor locator 是独立 subject-scoped view。

## Tool catalog

`@2` 将工具合同与当前可调用性拆成两个身份：

- `DeclaredToolCatalog`：Kernel base tools 加 exact activated Plugin manifests 的稳定合同；
- `ToolAffordanceSnapshot`：每个 Session/member/turn 基于 capability binding、authority、workspace、route、
  approval 和 health 计算的 effective catalog。

Deployment composition 还分别固定 Adapter/Extension、capability route、normalized HTTP route、projection、
UI-renderer、worker、finish-validator、schema、migration、transaction-participant 与 qualification catalog digest。
这些低频 release identities 不混入 target health 或 per-turn authority。任何 canonical collision 都在 public
route/worker/renderer 挂载前拒绝整个 activation；不允许 Host 先暴露部分 surface 再报告其余 Plugin 失败。

`@2` 的 `SessionCompositionPin` 还固定 deployment composition bundle、Driver bundle、HTTP route 与全部
contribution catalogs、workspace backend、initial capability binding 和 Host/client compatibility epoch。
Host 当前 epoch 与 pin/binding 不一致时，只有安全 inspection 可以返回
`upgrade_required + drifted_fields + bounded digests`；message、drain、approval、tool、workspace mutation、
publication、operation 与 restore 都必须在业务 callback 前失败。公开错误固定 no-effect/零 mutation/零
fallback，不返回 manifest Host path、secret locator value 或 traceback；private diagnostic 通过同一
`diagnostic_id` 关联。

`ToolAffordanceSnapshot` 回答“当前是否可执行”，`ToolExposureSnapshot@1` 另行回答“本个 provider step
是否直接显示”。稳定协作动词和 role-essential capability 可以是 `DIRECT`；授权存在但不宜常驻 function list
的 long-tail capability 是 `DEFERRED`；策略要求不可披露的能力是 `HIDDEN`。`capabilities.inspect` 只能列出
非隐藏 blocker 与 Deferred 摘要；command-scoped expansion 必须显式选择 exact tool 并产生有界 claim，且不会
扩大 workflow、authority、approval、workspace 或 route。`HIDDEN` 在 inspection、错误提示和 provider schema
中都不可见。dispatch 携带 exposure/expansion、snapshot、lease、binding、workflow epoch、workspace generation
和 explicit route，任何漂移在 effect 前返回 typed stale error，不自动替换 route。

route-bound affordance 的安全投影可包含 opaque route ID、provider/driver ID、target ID、inventory
generation 及各层 digest，但不包含 SSH endpoint、login、remote root、binary locator、credential 或
probe output。`capabilities.inspect` 与模型 function list 必须消费同一个经验证 snapshot；前者
可显示非隐藏 blocker，后者只显示可调用 `ToolSpec`。
snapshot 同时包含 `subject_policy_digest`，以便 Task/role policy 在模型请求与 dispatch 之间变化时
fail closed；`HIDDEN` policy 不得借 inspection 泄漏 tool 或 route 存在。

Client 与 Core UI 还必须重验完整 layered release、declared catalog、Session capability binding 和 condensed
ToolAffordance reflection。公开 reflection 不包含 `HIDDEN` 工具；inactive/degraded Plugin 使用结构化 blocked
state 与 blocker 解释原因，只有 `AVAILABLE`/`AVAILABLE_WITH_APPROVAL` 进入调用面。单个工具 blocked 不等于
整个 Core shell 不可读，但该工具 dispatch 必须本地 fail closed，且 `fallback_performed=false`。

`@2` 的五个 Kernel base workspace contract 是：`workspace.status`、
`workspace.fs.read`、`workspace.fs.list`、`workspace.fs.mutate` 与 `workspace.exec`。它们的 input schema 为
closed object，不包含 `workspace_id`、credential、target 或 remote locator；Host 从 current Session/member/
AgentAuthorityLease/workspace generation 与 pinned local route 解析唯一 binding。mutation/exec 由 exact tool
call 派生 idempotency/operation identity并进入 `WorkspaceOperationCoordinator`，result 明示没有 checkpoint、
publication、workspace cleanup 或 Task transition。Standard 已把五个 contract 接到 exact runtime mount；
每次调用仍按当前 workspace binding、authority、affordance 与 route 重验。任何未满足依赖或没有当前 exact
route 的工具必须保持 blocked，不能调用旧 registry，也不能改用相邻工具或本地 fallback。

其中 `workspace.fs.mutate`、`workspace.exec` 与 transfer 先形成 durable ControlledOperation admission，再调用
exact Adapter；响应丢失时，调用方只能以同一 request/operation/intent/authority/route 发起显式
reconciliation。Port 的 `reconcile(original_request)` 只观察既有 effect，不重新运行 helper、argv 或复制，
并固定报告 `redispatch_performed=false`、`fallback_performed=false`；没有 terminal proof 时继续保持
`dispatch_in_doubt`，不能从路径存在、进程消失或私有文件变化推断 checkpoint、publication 或 Task terminal。

旧 tool name 返回 removed-tool/stale-catalog error，并保留安全的 requested name 和 expected catalog
identity；不得调用替代 operation。

general 与 executor catalog 具有不同 digest。executor catalog 只增加 owner-scoped locator 读取，
不扩大 mutation tool、runner、SSH 或其他 agent workspace 的可见范围。

`@2` 不再用 actor kind 粗略选择全局 catalog；上述 subject-scoped snapshot 是唯一当前行为。

## `@2` projection owner partition

`@2` 使用 closed `core` section 保存 Session/Task/Lane/Agent/Protocol/Approval、
`AgentAuthorityLease`、Session capability binding、runtime/workspace/publication/operation/failure 等基础事实；
Plugin 数据只能进入 `extensions[plugin_contract_id]`，并绑定 exact projection schema/renderer digest。

当前 owner 映射为：Research → `openzyme.research@1`，Reporting → `openzyme.reporting@1`，
Science → `openzyme.science@1`，formal revision execution → `openzyme.compute@1`，远端 workspace、
target inventory 与 HPC route → `openzyme.hpc@1`。这些 contributor 都由各自 Plugin runtime bundle 显式提供；
Kernel/Host 只按 activated projection catalog 做 exact mount 和组装，不读取其 repository。现有 EnzymeDesign
垂直 tools 没有独立 canonical control-plane collection：正式计算状态归 Compute、科学采用/交付物归 Science，
文件结果归 workspace/publication。因此其 manifest 保持无 projection，不能为了制造产品 section 而从 tool
receipt 或事件推导空壳状态；未来某个产品 Plugin 真正拥有 canonical state 时，必须新增自己的 exact
projection contract 后才能公开。

checkpoint/publication 的公共 DTO 已由 `openzyme-contracts` 唯一拥有。公开面可以返回经过验证的
workspace generation、commit/tree、publication/ref 和 manifest digest，却不得返回 repository root、
private ref、credential、LFS object locator、remote transport locator 或 Git/LFS 命令细节。上述 locator
字段由 `@2.core` 递归 closed-schema validator 直接拒绝，而非只依赖调用者 redaction。Git-shaped identity 暂时保留；未来 backend
变化必须通过新 contract 版本和 offline migration，而不是让 Host/CLI 猜测别名。
这些 Git-shaped facts 的公共 owner 仍是 Kernel/Contracts；实际 root/ref/hook/LFS bytes、credential claims/
token/ledger、closure/GC 和 native-client qualification 由 `openzyme-workspace-git-lfs` Adapter 拥有。Adapter
receipt 进入公开面前必须由 Kernel application boundary 验证，不能公开 Host locator，也不能把 mechanism
success 提升为 publication、Science adoption 或 Task terminal。

`@2.core` 的通用文件引用使用 Contracts-owned `RevisionPathRef`/`ProtocolFileHandoff` 或
`EvidenceRef`。Reporting/Science 的 typed refs 只进入相应 namespaced extension section；旧
`TaskEvidenceRef@1` mixed union 不进入 `@2` public exports。

Reporting 的 section ID 是 `extensions["openzyme.reporting@1"]`。它只含分页后的 draft/report/render/
validation metadata 和授权的完整 `RevisionPathRef`，不含正文、Host/private path、storage URI、credential 或
renderer private log。只读 route `GET /v3/extensions/openzyme.reporting/sessions/{session_id}` 与该 section
共享 exact contract digest 和授权规则；UI 必须加载 `openzyme.reporting.renderer@1` 的精确 digest，否则只显示
incompatible extension 并禁用相关 mutation control。旧顶层 report 字段只能由 offline historical reader
解释，不能与当前 section 双写或在线翻译。

Science 的 section ID 是 `extensions["openzyme.science@1"]`。它只含授权、分页、byte-bounded 的 attempt、
selection、disposition、adoption、deliverable 和 closure metadata；credential、Host/remote path、raw log、storage URI
与 artifact-era identity 被拒绝。只读 route
`GET /v3/extensions/openzyme.science/sessions/{session_id}` 与该 section 绑定 exact contract digest；UI 只在
`openzyme.science.renderer@1` digest 匹配时渲染。旧顶层 scientific 字段只能由 offline historical reader
解释，不双写、不在线翻译。

`WorkspaceRevisionBackendPort` 是 Host 内部出站接口，不直接成为 HTTP/Agent tool schema。公共接口只消费
Kernel 验证后的 revision/path fact 或安全 byte projection；Adapter 的 Git command、remote response、
credential 和 storage locator 永不透传。
其 publication dispatch identity 也只来自已 admission 的 ControlledOperation；`@2` 客户端不能提交
execution generation/fence 或 remote receipt。Kernel materialize 必须校验 public command 中的 closed
receipt 与 Store 中 terminal receipt digest 一致，再调用 Adapter 的 observation-only 恢复路径。

移除 Plugin 只能使对应 extension section unavailable，不得改变 core 语义。`AgentCapabilityLease` 不作为
兼容 alias；旧 `@1` 仅保留 offline historical reader。任何 bundle/catalog/backend/build/binding/snapshot
drift 都在 mutation 前 fail closed。

旧 SQLite 物理表名 `agent_capability_lease_records` 可以在首轮 adoption 中保留，但不是公共 schema
名称。`@2` reader 只接受经过 Store mapper 验证并带 canonical digest 的 `AgentAuthorityLease`；其中
generation 来自旧 `workspace_generation`、fence 来自旧 `state_version`，旧行无 expiry 时必须保留
`expires_at=null`。CLI、SDK、UI 和 Plugin 不得观察物理表名、旧 profile tuple 或旧 DTO alias。

## Resident teammate projection 与 commands

`file_workspace_public@2` 保持既有 root 和 Core section 集合；本 change 只在这些 owner 已闭合的 section
内部加入版本化事实，不增加第二个 dashboard envelope：

- `core.session` / `core.workspace` 显示 exact reservation、generation、状态 `provisioning | ready | blocked`，
  并以 `workspace_provisioning_public@2` 公开 intent identity/digest/state-version、安全 blocker及nullable
  `workspace_provisioning_reconciliation_public@1`；reconciliation READY 只改变effective readiness，原blocked
  intent/failure仍原样可见；
- `core.conversation` / `core.runtime` 显示 root workflow binding、signal authority link、epoch/revocation、
  runtime command、ordered assistant/tool/failure transcript 与 settlement；
- `core.tasks` / `core.agents` / `core.protocol` 显示 assignment、delegation、inbox、causation 和 wakeup，
  但 protocol delivery 或 runtime settlement都不推导 Task 终态；
- `core.tool_reflection` 显示 Direct tools、非隐藏 Deferred 摘要、expansion claim 与 blocker；Hidden 不出现。

内部可恢复合同与公开 DTO 不共用字节：Store 继续保存完整 `runtime_turn_command@2`、
`runtime_turn_outcome@1` 与 receipt，公开投影则只接受 `runtime_command_public@1`、
`runtime_turn_command_public@1`、`runtime_turn_outcome_public@1`、
`runtime_turn_outcome_receipt_public@1`、`runtime_command_outcome_summary_public@1` 和
`runtime_outcome_consumption_public@1`。公开 command 不含 command/signal/session lease token；turn command 只含
`context_digest`、`message_count` 与 safe fences；outcome 只含消息/工具请求 count、工具请求 aggregate digest、safe
failure 与 source digest；command outcome summary 只保留 turn aggregate digest/count 与 runtime/Task/fallback facts；
outcome consumption 只保留 consumption/command/outcome/receipt 的 safe identity/digest 以及 continuation/settlement
reference。任何公开 DTO 都不得包含 raw context/messages、tool name/arguments、嵌套 internal outcome receipt 或完整
私有 failure。tool transcript 只保留 allowlisted settlement facts；无法解析为当前 closed ToolResult 的历史 tool
content 退化为固定安全摘要，而不是原文回退。

公开 command 的产品顺序是：创建 Session 后轮询同一 projection 的 readiness；`POST .../messages` 原子写
root workflow binding、conversation/inbox/signal 与 signal authority link，但只报告 queued；用户或 operator
再显式调用 `POST .../runtime/drain` 推进有界 turn。approval resolution 只写决定并排队 causally-linked wakeup，
不在同一 HTTP 请求同步执行 recipient。所有 command 都复用 inspection 返回的 exact release、projection、
binding 与 affordance identity；drain 请求没有 workflow、tool expansion 或 route 选择字段。

旧 Session 若缺少 reservation、provisioning intent、workflow authority 或新 transcript owner record，不在线
补造语义，返回 typed incompatibility 并要求 offline migration 或新建 Session。inner fact 的新增不能把
`@1` response、旧 conversation prose 或临时 UI state 翻译成 canonical `@2` truth。

provisioning recovery 另有两个 operator-only direct routes：

- `POST /v3/sessions/{session_id}/workspace/provisioning/reconcile`：以 exact intent digest/state-version 和bounded
  claim接纳同一原请求的durable observation-only reconciliation；
- `POST /v3/sessions/{session_id}/workspace/provisioning/successor`：只在known/diagnosed failure之后，以exact
  failed intent和resolved reconciliation identity创建下一monotonic generation与新intent。

两者均返回HTTP `202`，都在Host执行release/project/projection/precondition检查，并直接进入Distribution的专用
gateway；不得借generic mutation route、runtime drain、Task或另一个Adapter间接实现。CLI从current projection
取得并交叉验证intent version/digest，提交后重新inspect canonical projection，不把本地HTTP body当ready真值。
两个 `202` result 都是 exact closed admission-only facts：显式证明adapter、external effect、runtime、Task和fallback
均未发生；reconciliation result只公开occurrence/source lineage与enqueue事实，不公开`claim_*`、terminal receipt、
failure/diagnostic或任意private/tool payload。Host在返回前、CLI在二次inspect前均fail closed校验这些事实。

## CLI 与 UI

CLI 是薄 HTTP client，不读取 SQLite 或 repository root。它通过 HTTP 完成 Session bootstrap/readiness、
conversation message、task board、agents/delegations/inbox、approvals、failures、显式 drain 和 command polling，
并明确区分 `queued`、`provisioning`、`ready`、`blocked`、`running` 与 settled outcome。CLI 不在 message 后
隐式 drain，也不从自然语言 assistant response、tool success 或 runtime idle 推断 task completed。

UI reducer 只接受 versioned file workspace sections；未知 key 不恢复旧 state。controller 以 projection
identity 和 command receipt reconcile readiness、ordered transcript、collaboration、approval、runtime command、
workspace、经验证的投影变化观测与 failure facts，而不是在浏览器维护第二份 session/task/runtime 真状态。
当前 transport 是对 exact Host workspace projection 的有界轮询：客户端只在 canonical projection digest
变化时派生 UI-local change observation；它不是 Host outbox/canonical event stream，也不能补造 Kernel event。
UI 不显示 private
locator、raw external handle 或 Hidden capability。CLI/UI error rendering 使用 Host safe error，不展开 secret
或内部路径，也不根据文案自行推断 retry、reconcile 或 fallback。

Web UI 的 `file_workspace_v2_state`、`core_shell` 与
`extension_renderer_loader` seam。`file_workspace_v2_state` 对 root/release/core/extension section 使用
closed validation，并递归拒绝 Core 中的 Reporting、Science、Compute/HPC、EnzymeDesign、artifact-era 和
private locator 字段；`core_shell` 只克隆 `projection.core`，extension payload 只交给 exact
manifest-declared renderer。renderer catalog、section contract 或 renderer identity 缺失/漂移时 UI 阻止
mutation，不合并 payload、不加载 fallback renderer。Plugin-free `extensions = {}` 仍产生可工作的 Core shell。

上述 seam 已进入 `main/controller/view/client`、`npm test` 与 build output；生产调用者只消费 exact
`@2` release/binding/affordance/renderer identity，不再有在线 `@1` reducer。这仍不等于真实 deployment
cutover 已执行：Host Distribution mount、release injection 和设备上的 activation proof 仍必须另行完成。

## Restore

continuation intent 绑定 session、agent/member、source command/outcome、process epoch、完整 layered release
digest、Extension bundle、DeclaredToolCatalog、Session capability binding revision/digest 和
ToolAffordanceSnapshot identity。恢复时 release/bundle/catalog/owner/epoch 任一漂移以
`runtime_continuation_contract_stale` 在 claim/dispatch 前硬失败；binding 或 affordance 已更新时允许把对话作为
新 bounded turn 的输入，但原 dispatch 固定 blocked，必须取得 fresh binding/snapshot。validator 是只读的，
`mutation_applied=false`、`fallback_performed=false`；旧 schema/catalog context 不 replay、rename 或重新解释。

## Error semantics

当前非空公开错误对象只接受 exact closed `failure_observation@2`，至少包含：稳定 `error_code`、component、
operation、phase、allowlisted typed identities/facts、effect certainty、retry/reconcile policy、
`mutation_applied`、`fallback_performed`、安全 cause chain、`diagnostic_id` 和 next action。旧 schema、未知字段、
私有 diagnostic 或无法安全解析的值一律 fail closed；公开值不得包含 traceback、stdout/stderr、private context、
tool request 或 secret locator。API、tool result、event、workspace 与 world projection 使用同一字段语义；UI/CLI
不自行推断 retryability，也不把私有值降级为字符串后继续展示。

其 canonical DTO、`ExternalEffectCertainty` 和 `RetryEligibility` 位于
`openzyme-contracts`。旧 `openzyme_domain` package、alias 与单向重导出已经删除；历史部署只能由
`openzyme-store-sqlite` 的显式 offline migration reader 按 ledger 读取，不能通过在线 import compatibility
进入当前 Host。Workspace、tool、Plugin 或 Host 不得再定义第二套 effect/failure enum。

- validation/authorization：请求未被接受，`mutation_applied=false`，外部 effect 为 `no_effect`；
- `no_effect`：有证据证明外部请求未发生，可否重试仍由显式 policy 决定；
- `dispatch_in_doubt`：请求可能发生，只能按同一 intent/handle reconcile；
- stale lease/fence/generation：迟到 writer 无 canonical write authority，不自动换 owner 或重放；
- cleanup failure：保留 primary failure，同时显式记录 cleanup outcome 和 residual identity；
- old/incomplete database：mutation 前返回带 expected/observed proof 的
  `legacy_schema_unsupported` 或 `legacy_removal_incomplete`。

完整 traceback、异常链、私有路径/handle、return code 和 bounded stdout/stderr 只存在 Host-private
immutable diagnostic record 中。公开 sanitizer 仅允许 safe type/code/digest/count/phase，确定性标记
secret/path/handle redaction；error envelope 不将 unknown 伪装成 not-found、corruption 或 retryable。
