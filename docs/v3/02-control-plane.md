# V3 Control Plane

> 以下 repository/table 列表描述 target `@2` owner 与为离线 adoption 保留的历史物理表。
> [`architecture/table-owner-manifest.json`](architecture/table-owner-manifest.json) 唯一固定语义 owner；首轮迁移不重命名
> 物理表。通用 Host/Standard 只使用 target writer，真实历史 deployment 的离线 adoption/cutover 未执行。

## Canonical state

control plane 保存结构化 identity、state、lease/fence、receipt 和关系，不保存通用文件正文。
主要聚合为：

- session、access、task/dependency/finish、lane、agent member、inbox、approval；
- runtime signal、session lease、runtime command、continuation delivery；
- project repository binding、session pin、credential、private namespace；
- agent Git workspace、checkpoint、publication intent/execution/published revision；
- Git LFS policy/object/link/closure/verification/pin/GC receipt；
- controlled operation、dispatch/observation/result handle；
- executor HPC workspace、revision execution request、job handle/observation/result；
- research file index、report draft/report、protocol file handoff/revision path ref；
- scientific attempt、selection、occurrence、disposition、effect adoption、deliverable/receipt；
- mutation scope/writer/quiescence snapshot/receipt、durable event 和 deployment schema state。

目标拆分后，Kernel 只拥有跨领域基础真值：Session/Task/Lane/Agent/Protocol/Approval、runtime coordination、
authority、publication/revision/path、generic evidence 和 ControlledOperation。Reporting、Research、Science、
Compute/HPC 分别拥有自己的 namespaced state；SQLite Adapter 实现所有 repository/UoW/migration persistence，
但不因此获得这些语义的决策权。Plugin 只能通过 narrow application service 和受限 transaction participant
参与写入，不能访问 Core 私有表或 raw connection。

当前通用 control-plane、repository-binding、reliability/failure 纯契约已经从 `openzyme-domain`
迁到 `openzyme-contracts`。`Session`、`Task`、`Lane`、`AgentMember`、Inbox/Approval、runtime signal/lease、
`ControlledOperation`、`ContinuationState`、`ProjectRepositoryBinding` 与
`SessionRepositoryBindingPin` 都只有一份 canonical class/enum implementation；同时包括：
`ControlledOperationExecution`、runtime command、continuation delivery、mutation scope/writer、
quiescence、`ExternalEffectCertainty`、`RetryEligibility` 和 `FailureObservation` 只有一份 canonical
class/enum implementation。旧 Domain modules/aliases 已删除，仓内 caller 直接依赖 Contracts。该代码 owner
迁移没有改变历史表名或 row shape；当前持久化 owner 是 SQLite Store。

workspace observation/private-ref proof、verified checkpoint、publication intent/manifest/remote receipt、
append-only `PublishedRevision` 与 fetch identity 也已迁为 `openzyme-contracts` 的唯一 class/enum
implementation；旧 `openzyme_domain.workspace_checkpoints` 与
`openzyme_domain.workspace_publications` 兼容模块及顶层别名已经删除。仓内生产 caller 已改用 Contracts；
publication mutation 由 Kernel application service 协调并由 Git/LFS Adapter 执行；旧 Core package 已删除。

`RevisionPathRef`、`ProtocolFileHandoff` 和 generic `ControlledOperationResultRef` 同样由 Contracts
唯一拥有；`ReportRef` 与 `ScientificClosureRef` 分别由 Reporting/Science contract package 拥有。
旧 mixed `revision_path_handoffs` aggregate 已删除，`TaskEvidenceRef@1` 只允许离线历史 reader 使用；
`@2` 使用 domain-neutral `EvidenceRef`，不会把 Report/Science union 重新塞回
基础 Contracts。

Git-specific `AgentGitWorkspace`、observation/restore comparison 与 Git-LFS
policy/pointer/closure/verification/upload/read/reachability/GC receipt 纯机制 DTO 现在由
`openzyme-workspace-git-lfs` 唯一实现。旧 `openzyme_domain.agent_git_workspaces` 与
`openzyme_domain.git_lfs_work_products` 兼容模块及顶层别名均已删除。仓内生产 caller 已直接使用
Adapter namespace。private/public ref、immutable byte observation、Gitless compute tree、exact-base clone
与 typed restore observation 已经由 Adapter 实现；durable root、bare repository/hook 和 LFS actual-byte object
store 以及 private ref 派生、agent/publication/historical ref ACL/owner update 的 Git/filesystem/subprocess
机制也已从旧 Core 迁入 Adapter，且 hook 位于 Adapter wheel。LFS policy/session/closure/read/retention/GC
receipt repository 同样由 Adapter 实现，但 commit callback 必须由 Store/UoW 注入并保留所有 fence。clone/restore
仍由上层显式注入 command/process port，
publication manifest/LFS closure validation、private reachability finalization 与 receipt-bound GC 也已通过
窄 repository bundle Port 迁入 Adapter；这些 receipts 不能自动写入 Kernel publication/Task/scientific truth。
native Git/LFS 与 Gitless compute qualification DTO/validator 同样是 Adapter mechanism，不属于 Kernel truth。
private namespace retention/hold/receipt-before-delete/ref retirement 也由 Adapter 实现；Store/UoW callback
由 Standard 显式注入，不存在 legacy Core factory。
clone 的进程作用域 credential 不能进入 argv/receipt，restore 只读且不得 repair/replacement，也不能读取
Host root 或持久化 secret。closed repository credential 与 read-only provision credential 的
claims/schema/error contract，以及 key/HMAC/envelope material，已由 Adapter 唯一实现；普通与 provision
credential 的 token/issuance-ledger mechanism 均位于 Adapter 且不自行 commit；Kernel
authority/pending-workspace admission 与 Store UoW 保持独立。claims/ledger/token 验证不替代 Kernel authority。workspace
volume allocation、exact-base clone observation 与 restore failure classification 已进入 Adapter mechanism；Kernel
仍唯一执行 lease activation、ready/block/replacement 与 failure canonical mutation。LFS pin/GC external effect
只有在 exact Adapter selection 和 authority admission 后可执行；安装 wheel 不产生 workspace capability。

ScientificAttempt/Selection/Disposition/Adoption/Closure 与 immutable scientific deliverable/validation
receipt 的纯 DTO 位于 `openzyme-science`，旧 Domain path 已删除。Science
exact manifest、workflow registry、tools、projection/HTTP route、worker、finish validator、logical migration
和 restricted transaction participant 也位于目标包；旧 Core workflow path 已删除。application
services、formal finalization、历史物理表的 offline adoption 均由 Science/Store 的 restricted participant
边界处理。旧 Domain/Core compatibility modules 已删除，只读 lifecycle resolver、rollover projector 和
selection evaluator 由 Science 消费窄 query view。当前在线 Host 只接受 `@2`；真实历史 deployment cutover
仍需另行授权，不得双写或把 non-live proof 误称为真实迁移完成。完整边界见
[Science Extension](science-extension.md)。

`SessionReportDraftRecord`、`SessionReportRecord` 及其 lifecycle enum 的纯契约已经迁入
`openzyme-reporting`，旧 Domain path 已删除。目标包还实现 immutable
`ReportVersion`、render/validation receipt、`openzyme_reporting` restricted transaction participant、bounded
projection、tool/worker/finish-validator runtime surfaces 与 exact manifest。participant 只使用 Store 注入的
`ExtensionStateReader/Writer`，不能获得 raw connection 或写 Core tables。Core 已删除默认 report tool 注册、
restore/prompt 注入、report-specific evidence 解析和 aggregate 中两张 legacy repository writer；旧模块只保留
`@1` 历史 shape 的 report collection 固定为空。`session_report_*` 物理表由 Store 为 offline historical
adoption 保留；current writer 只通过 restricted participant。Host 仅从 verified mount 装配 Plugin，真实
adoption/cutover 未执行，且不允许 dual-write。完整边界见
[Reporting Extension](reporting-extension.md)。

`SourceRefKind`、Research summary/evidence/source/gap 的纯契约已经迁入 `openzyme-research`，该 wheel
不依赖 aggregate Domain；旧 Domain/Core/Engines paths 已删除。Research repository/state writer、bounded
orchestration/tool、projection、provider split 与 manifest 均由 Research/Tavily owners 提供；是否 mount 由
Distribution 决定，generic Host 不硬编码 Research。

SQLite 文件创建、connection flags/WAL、read/write/long-flow scope、短事务、commit/rollback、历史 schema
bootstrap、target schema 与 Kernel repository implementation 均由 `openzyme-store-sqlite` 拥有。Store 不反向
import Kernel/Plugin implementation；Kernel policy 通过 typed callback/Port 注入。旧 heterogeneous
`CoreRepositories`、Host legacy wrapper 和 compatibility exports 已删除。Standard target writer 使用 closed
production codecs；Plugin state 只经 namespaced restricted participant。`AgentGitWorkspaceRepository` 由 Git/LFS
Adapter 实现并接收 Store fenced commit callback。

executor HPC workspace、provision/cleanup intent+receipt、credential claim 与旧 target qualification 的
纯 DTO 已迁入 `openzyme-hpc`；旧 `openzyme_domain.executor_hpc_workspaces` 兼容模块与顶层别名已经删除，生产 caller
已改用 Plugin contract owner。完整 application service、SQLite workspace repository、tools/worker、target
inventory 与 SSH/Slurm Adapter 均已归目标 owner；Host 仅实现窄 Kernel facts 与 tool composition gateway。
manifest 是否 activation 和 `@2` projection 是否包含 HPC section 由 exact Distribution/Session mount 决定；
Kernel/Agent 不得从安装状态推导 route 可用。

通用 `EngineInvocation`/status 已迁入 Contracts；旧 `session_run_records` 的 Run DTO 已迁入
`openzyme-compute`；`sandbox_*` image/workspace/run mechanism DTO 位于 `openzyme-process-podman`。旧 Domain
aggregate 已删除。Compute/Podman service、repository、worker 只通过 manifest/application Port 组合；历史
物理表名在首轮保留，writer 事务仍由 Store UoW 管理。

## Authority 与 capability facts

目标公共名称是 `AgentAuthorityLease`，它由 operation-scoped `AuthorityGrant`、generation 和 fence 组成。
当前 `agent_capability_lease_*` 物理表名在本 change 保留，并由 store mapping/ledger 证明等价；`@2` 不导出
旧 `AgentCapabilityLease` alias。

当前只读 Store mapper 对 `agent_capability_lease_records` 做 exact row/schema/digest/lifecycle 校验：
`workspace_generation` 映射为 lease generation，`state_version` 映射为 fence，旧
`pending_workspace / active / revoked` 映射为公共 `pending / active / revoked`。旧表没有 wall-clock
expiry，因此 `expires_at=null`；不得从 state version、updated time 或 profile 推导一个虚构 expiry。
`general / executor` 只是签发模板的 provenance，mapper 把其 closed capability tuple 收窄为具体
workspace/repository/network/HPC operation grants，并要求旧行中存在对应 exact target。该过程不写数据库、
不重命名物理表、不生成 Extension/Resource capability，也不表示 Store writer 已 cut over。完整映射由
`docs/v3/architecture/authority-store-mapping.json` 固定并接受架构门禁。

Extension、resource、authority 和 tool affordance 是四种不同事实，分别由 composition、operator target
qualification、Kernel lease service 和 per-turn resolver 写入。它们不能互相作为证明。Session 固定
extension bundle、workspace backend 与 immutable `SessionCapabilityBindingRevision`；只有 operator/admin 可
publish/adopt/revoke inventory binding，Agent 只能选择当前 binding 已列出的 route。

`SessionCapabilityBindingService` 现已把该规则实现为单调 immutable revision：initial
`publish`、增量 `adopt` 和 `revoke` 只接受 operator/admin actor，并以 expected previous
revision 做 CAS。已有 Session 的 extension bundle/route catalog 不能借 binding update hot swap；
Agent actor 的尝试在 repository mutation 前以 `no_effect` 拒绝。Store 已提供 binding persistence
repository；Standard codec closure 已完成，通用 Host 使用 target Control Store。该闭包不表示历史部署
已经执行 offline adoption/cutover。

## Transaction boundary

repository mutation 使用短 `BEGIN IMMEDIATE` Unit of Work。一个 canonical command 涉及多个
repository 时必须 all-or-nothing。LLM、provider、Git remote、process、SSH 或 HPC 调用期间不持
SQLite 写事务。

同一语义层的 application services 不经私有 repository、嵌套事务或非类型化 callback 互调。需要同一
command 原子写多个 Kernel facts 时，共享 pure typed reducer，并由 command owner 在一个 UoW 中提交。例如
Protocol delivery 使用 Runtime Coordination 拥有的 closed signal payload reducer；Authority issue/supersede/
revoke 同时 CAS `AgentMember.active_authority_lease_id/workspace_generation`，使后续 signal 能绑定 exact
authority、workspace generation 与 process epoch。跨层调用则只能经 Contracts Port 或 Kernel Application API。

首次 Session 是显式例外边界，不是 authority bypass：Session-bound Agent lease 在 Session/master 尚未存在时
不可能合法预置。`SessionBootstrapKernelApplicationService` 先经
`SessionBootstrapAuthorityVerifierPort` 验证 delivery security 签发的短时 operator authorization；该事实绑定
exact project/Session、root lease、revision-1 binding、composition pin 及其 Extension/binding digests。随后一个
ControlStore UoW 按 create-only 语义原子写 Session、master AgentMember、generation/fence 1 root
AgentAuthorityLease、SessionCapabilityBindingRevision、SessionCompositionPin、durable event 和 outbox。普通
collaboration create 明确拒绝 fabricated preseeded lease；denial/expiry/drift/conflict 整笔回滚，且 bootstrap 不
创建 workspace/Task、不运行 runtime、不采用 inventory。

`openzyme-contracts` 已定义 implementation-free `ControlStorePort`、`KernelUnitOfWork`、immutable record
snapshot、expected-version mutation、durable event/outbox 与 commit receipt。Port 不泄露 connection/SQL；
`openzyme-store-sqlite` 现已实现目标 connection lifecycle、只读 startup proof、短
`BEGIN IMMEDIATE` UoW、event/outbox 原子提交、closed migration catalog，以及 bundle/catalog/binding/
resource fact/workspace receipt repositories。`SQLiteControlStore` 通过显式 `SQLiteKernelEntityCodec`
把每个 Kernel entity 映射到其既有 owner table，并在同一事务重验 Session/CAS 后提交业务 mutation、event
和 outbox；没有 generic JSON state table，未映射 entity 直接失败。Plugin-free Kernel 声明的 31 种 entity
已经全部拥有显式 production codec；跨 owner repository 和旧 `CoreRepositories`/Host caller 仍未收口，因此
这里只表示目标 Store transaction authority 与 Standard writer admission 已闭合，不表示系统 persistence
cutover 已完成。

target CAS metadata 使用 `openzyme_store_kernel_entity_versions`，字段仅限 entity type/id、semantic owner、
state version 与 record digest，不保存 payload，因而不能成为 generic JSON truth。显式 codec 必须从既有 owner
table 重建 payload，并让 digest 与 ledger exact 相等；missing/unadopted/owner drift 一律拒绝。当前
`SessionSQLiteKernelEntityCodec`、`LaneSQLiteKernelEntityCodec`、`TaskSQLiteKernelEntityCodec`、
`AgentMemberSQLiteKernelEntityCodec`、`AgentAuthorityLeaseSQLiteKernelEntityCodec`、
`AgentRuntimeSignalSQLiteKernelEntityCodec`、`SessionRuntimeLeaseSQLiteKernelEntityCodec`、
`ApprovalRequestSQLiteKernelEntityCodec`、`ContinuationSQLiteKernelEntityCodec`、
`ControlledOperationSQLiteKernelEntityCodec`、`FailureObservationSQLiteKernelEntityCodec`、
`SessionCapabilityBindingSQLiteKernelEntityCodec`、`SessionCompositionPinSQLiteKernelEntityCodec`、
`ConversationMessageSQLiteKernelEntityCodec`、`MemorySQLiteKernelEntityCodec`、
`ProtocolRecordSQLiteKernelEntityCodec`、`InboxMessageSQLiteKernelEntityCodec`、repository binding/head/pin、
workspace generation/runtime binding、checkpoint/publication/revision verification 与 task evidence codecs
已验证既有 `sessions`/`lanes`/`tasks`/`task_dependencies`/
`agent_members`/`agent_capability_lease_records`/`agent_runtime_signals`/`session_runtime_leases`/
`approval_requests`/`continuation_state_records`/`controlled_operation_records`/
`failure_observation_records`/`openzyme_store_session_capability_binding_revisions`/
`openzyme_store_session_composition_pins`/`engine_documents`/`memory_entries`/`inbox_messages` 以及对应
repository/workspace/publication/evidence owner tables 的
create/replace、CAS tamper rejection 与同事务
event/outbox；`lanes.workspace_binding_id` 以及 Task 的 owner、validator、evidence、explicit-finish 字段，
是保留物理表名和既有字段语义后新增的目标字段。checkpoint/publication 触发器只依赖 Kernel 的 workspace
identity、authority、repository binding 与 generic controlled-operation facts，不读取 Git Adapter workspace
或旧 publication execution owner。旧 mutation-guard callback 由 ControlStore 限定到当前 UoW 的 exact
Session 和 codec-declared channel，事务结束立即撤销。

Authority 保留旧物理表名，但不复用旧公共语义。表内 `record_kind` 明确区分 historical
`legacy_capability_lease` 与 target `agent_authority_lease`；旧行继续要求固定 `general/executor` profile、
workspace reservation 与旧 lifecycle trigger，目标行只接受 closed `AgentAuthorityLease` grants、
generation/fence/state/digest。目标 codec 不填充旧 profile/status/schema 字段，legacy cutover mapper 也只选择
legacy rows；两类记录不能互相伪装或由启动路径自动转换。

Runtime/coordination 同样不以兼容字段伪造目标语义。`agent_runtime_signals`、
`continuation_state_records`、`controlled_operation_records`、`approval_requests` 与
`session_runtime_leases` 通过 closed `record_kind` 或 target entity identity 区分历史行和 Kernel 行；codec
只从 target 列重建 canonical payload。目标 runtime signal 绑定 exact AgentMember、authority lease digest、
workspace generation、process epoch、Session runtime generation/fence 与 claim token，SQLite trigger 直接检查
这些结构化事实。ControlStore 对仍被历史 trigger 引用的旧 Core callback 只注册 deny-only sentinel，使目标
写入不需要 import 旧 Core，同时任何误入 legacy mutation path 都 fail closed。Approval resolution、Protocol
delivery 与显式 enqueue 统一使用同一个完整 signal occurrence builder，不再写简化的隐藏 wakeup payload。
Continuation 与 ControlledOperation 的 target state 分别保存在显式列中；旧 operation/sandbox/approval link
和旧 engine envelope 不会被补造为目标事实，`dispatch_in_doubt` 仍保存 `mutation_applied=null` 且不自动重发。

Protocol 的 `delegate`、`send`、`handoff` 是同一 canonical family 的 operation，不再作为动态 entity type；
Kernel 统一写 `protocol_record`，把 operation 保存在 closed payload 中，再原子写独立 `inbox_message` 和
runtime signal。这样 Store codec closure、event source identity 与恢复读取使用同一个稳定类型。

`openzyme-standard` 进一步把 Plugin-free Kernel 所需的 entity type 集合固化为
`STANDARD_KERNEL_ENTITY_TYPES`，并由 `build_standard_kernel_control_store()` 在实际 writer 构造前检查
codec closure。当前 31/31 codecs 全部闭合；exact schema/composition/wheel/Session proof 通过后，
`build_standard_kernel_control_store()` 才返回 writer。缺失、重复或未声明 codec 仍在任何 mutation 前以
`standard_kernel_store_codec_incomplete`、零 mutation、零 fallback 拒绝。这个结果证明 Standard Store
admission，不代表 Host 的 Session/Task/Agent/authority/runtime/workspace route 已完成 caller cutover；后者仍需
独立 qualification。

legacy catalog 仍保留 25 个 owner/phase source bundles；目标 fresh loader 必须显式选择 closed owner schema
profile，只安装该 Distribution 选中的 owner bundles，再安装 namespaced `openzyme_store_*` composition/UoW
表。`openzyme_standard_local_file_sqlite_git@1` 只选 Kernel、Git/LFS workspace 与 Podman process owner；
`enzymedesign_local_single_process_file_sqlite@1` 另选 Research、Reporting、Science、Compute 与 HPC owner。
Store target tables 由 Store migration 安装，不复用 legacy `deployment_schema_state/legacy_removal_*` tables。
normal startup 统一调用 `verify_composite_store_schema_read_only()`：owner schema 由
`verify_owner_partitioned_schema_read_only()` 依据 exact profile 核对 table/index/trigger/FK closure 与 resource
digests，Store 自身 closure 由 `verify_store_schema_read_only()` 核对。拿 EnzymeDesign schema 冒充 Standard
会在 read-only object closure 阶段失败。composite proof 绑定两种
proof digest、完整 sqlite_master digest、统一 user version 与 object count，全程零 mutation。正常 writer
activation 还必须提供 `SQLiteStartupCompositionExpectation`：verifier 在不 import Plugin 的前提下，从 exact
activation epoch 的 immutable rows 验证 Extension bundle payload 和 closed adapter/extension/migration
catalog set/digest；schema-only proof 仅可用于离线 bootstrap/inspection，不能开启 writer。writer exact handle
再次验证同一 composition proof，missing/extra/cross-epoch/payload drift 均无修复地拒绝。

扩展 participant 的整个 `prepare`/`apply` 期间由 SQLite authorizer 限制在声明的 `state_namespace` 与固定
extension-state 表；其他表、`ATTACH`、PRAGMA mutation、DDL 和跨 namespace 访问均 fail closed。
read/mutation/payload/time 任一 budget 超限或 participant result identity 不匹配时，Kernel occurrence 与
extension writes 一并 rollback，不重试或跳过 participant。

每个实际执行线程创建并关闭自己的 connection。read scope 使用 `query_only`。WAL、busy timeout
和 retry 只解决局部 contention，不替代 owner、fence 或 idempotency。

## Identity 与 idempotency

idempotent replay 必须同时匹配 request digest 和 owner scope。相同 key 不同 payload 是冲突，
不能返回旧结果。外部 dispatch identity 至少绑定 operation digest、dispatch generation、backend
request identity 和 fence。publication identity 至少绑定 intent、commit/tree、closure 和 remote ref。

## Lease 与 fencing

- session runtime lease：一次 bounded agent turn；
- signal claim：一次 wakeup delivery；
- process epoch：attached process 的 Host callback；
- execution lease/fence：一次外部 effect lifecycle；
- continuation delivery fence：一次 result resume；
- workspace generation：一个 agent/remote workspace incarnation；
- mutation writer fence：一个 scope generation 的 canonical write authority。

stale writer 的迟到结果在 commit 边界拒绝。lease expiry 不等于外部取消或 task completion。

## Events 与 projection

durable event 是 canonical mutation 的审计输出，不是另一套 owner。public projection 从当前 typed
repository rebuild；当前 event replay 或 restore 必须匹配 `file_workspace_public@2`、layered release、
Extension bundle、declared tool catalog、capability binding 与 affordance snapshot。旧 `@1` event/catalog
context 只允许离线读取，并终止为 stale，不在线合成 alias。

`@2` 分离 Kernel/Adapter/Extension bundle、declared tool catalog、route/projection/migration
catalog、Session capability binding 和 turn affordance snapshot digest。瞬时 target health 只进入 affordance，
不改 release identity。

## Deployment epoch 与 Session composition pin

`DeploymentActivationEpoch` 是 read-only composition/schema/wheel verification 全部成功后的 immutable
deployment identity。它绑定 Distribution document、Kernel manifest、layered release、Driver/HTTP route/
contribution catalogs及两类 verification receipt。epoch 出现前，`DeploymentActivationGate` 不签发
repository-writer、route、worker、runtime 或 external-effect surface authorization。

新 Session 必须由 `SessionCompositionRepository.create_session_with_composition()` 一次写入 Session、
`SessionCompositionPin` 和 revision 1 `SessionCapabilityBindingRevision`。pin 固定 core schema、Adapter/
Extension bundles、declared tool/capability route/projection/migration、workspace backend、Host/client build 与
origin composition；initial binding 固定 Extension/route bundle 和 operator 已采用 inventory。不存在先建
Session、稍后补 pin 的合法状态。

目标写路径现在由更窄的 `SessionBootstrapKernelApplicationService` 将上述 composition graph 与 master/root
authority graph 合并到同一 ControlStore UoW；旧 `SessionCompositionService`/repository 仍是迁移期只覆盖
Session+pin+binding 的机制，Host 不得把它与新的 bootstrap 先后调用形成两个事务。SQLite 已提供 binding/pin
在内的完整 31/31 owner codecs 和真实 fresh-epoch focused test；production Host verifier/caller 尚未完成，
因此 Host route 当前仍 fail closed，但原因不再是 Store codec 缺失。

inventory adoption 只创建 monotonic binding revision，不改 pin。message、drain、approval、tool、workspace
mutation、publication、controlled operation 和 restore 都在 callback 前比较 active epoch、pin 与 latest binding；
drift 返回 `session_composition_upgrade_required` 且不 mutation/fallback。进程重启可重新验证同一 exact
composition；不同 bundle 或后来安装的 optional Plugin 不热进入旧 Session。

## Plugin application transaction

Plugin 不获得 `CoreRepositories` 或 connection。它用 immutable `KernelCommandContext` 调用 Task、
Protocol、Approval、Authority、Publication、ControlledOperation、Continuation、Failure、
CapabilityQuery、ExtensionInvocation、ExtensionState 或 TaskEvidence application service。context 绑定 Session/actor、
owning Plugin、authority generation/fence、expected Session version、bundle/binding digest、
idempotency、workspace generation 与 route。

需要与 Kernel mutation 原子提交的 extension state 通过 `ExtensionTransactionParticipant`：
`prepare` 只读声明 namespace 并返回带 expected-version 和预算的 plan，`apply` 只使用
namespace-confined writer。transaction 内禁止 Provider、Git、process、SSH、scheduler I/O；任一
participant 失败使整个 Unit of Work rollback。不存在可观察并修改任意 Core state 的
`on_any_event` hook。

`ExtensionStateKernelApplicationService` 在 Store transaction 之前 exact-match activated participant owner 与
namespace，并重验 Session pin、Extension bundle、capability binding 和 authority generation/fence；随后才把
closed `ExtensionStateCommand` 交给 Adapter 实现的 `ExtensionTransactionCoordinatorPort`。Science 等 Plugin
只持有这一 application service，不持有 coordinator、connection 或 repository aggregate。

目标 `@2` Kernel 已实现 closed `FinishValidatorRegistry` 与 Port-backed
`TaskKernelApplicationService`。Session pin/mount 决定 exact validator set，Task state 决定其中哪些 validator
适用；只有 owner 的显式 `task.finish` 才触发只读验证。missing validator、collision、validator identity drift、
evidence rejection、Task/Session version drift 或 AgentAuthorityLease generation/fence drift 均为 `no_effect`，
不选择替代 validator。全部接受后，Task terminal、Session version、durable event 与 outbox 在一个 UoW 中提交。
普通 `task.update` 的 closed field set 明确拒绝 terminal status。Host 的 Task/Protocol mutation 只经这些
Kernel services；validator receipt 不等于 Task terminal，也不等于历史 deployment cutover proof。

同一目标切片还实现了只依赖 Contracts Ports 的 collaboration/Protocol/Approval/Authority/Continuation/Failure/
TaskEvidence/ControlledOperation services。Session、Task/dependency、Lane、parent-child AgentMember、conversation、
Memory 与 retirement settlement 由 collaboration reducer 写；delegate/send/handoff 在一个 UoW 写 protocol fact、
inbox、pending runtime signal、event/outbox，但 `recipient_runtime_executed=false`。retirement 在 owned Task 全部结算后
才推进 member process epoch，并 revoke/advance authority fence。Approval 只改变 request truth；approved 不等价于
operation dispatched。Continuation 注册方只提交 source/recipient/resume facts，Kernel 从 canonical active
AgentMember 读取并固定 process epoch；delivery/fail 再显式携带 expected epoch，stale retirement epoch 在 mutation
前拒绝。FailureObservation 继续保留原 effect certainty。
EvidenceRef 先 immutable register，验证为只读。

generic ControlledOperation reducer 统一保存 intent、route、AgentAuthorityLease generation/fence、dispatch generation、
deadline/cancel/result/receipt、`no_effect / dispatch_in_doubt / effect_known / terminal_known` 和 explicit reconcile；
idempotency receipt、state mutation、durable event 与 outbox 同事务提交，未知效果不重发、不换 route、不 fallback。
`effect_known` 只把 operation 推进为可继续观察的 active，不冒充 terminal；只有 `terminal_known` 或明确的
terminal `no_effect` 才结算。需要 approval 时 admission 还要重验 exact intent、approved 状态和未过期事实。
首次 admission、dispatch、普通 observe 与 cancel 都要求 current AgentAuthorityLease；一旦 exact operation 已持久化为
`reconcile_required`，后续 reconcile 只允许原 Session/actor/Plugin/lease generation/fence/route identity 观察并结算。
因此 lease revoke 会阻止新 effect，却不会让一个可能已经发生的外部 effect 永久失去 reconciliation；不同 actor、
新 lease、stale fence 或替代 route 仍以 `controlled_operation_identity_stale` 在 Adapter 调用前拒绝。

publication 由 `WorkspacePublicationCoordinator` 组合 `PublicationKernelApplicationService` 与 generic
ControlledOperation：在 create-only Git dispatch 前先写 pessimistic `dispatch_in_doubt`，收到 exact remote receipt 后
才 terminal settle 并 materialize `PublishedRevision`。response loss、receipt drift 或观察暂缺都只调用
`WorkspaceRevisionBackendPort.reconcile_publication`，绝不重新 dispatch。撤权后的 materialization 必须绑定原 admitted
operation 的 authority generation/fence 与 terminal receipt，不重新要求 current lease，也不能借此创建新 publication。
这些 target services 已用 deterministic fake ControlStore 验证，但 legacy Host/SQLite writer 尚未 cut over，所以目前不
存在双写授权，也不能把 target test state 当成部署状态。

## File references

SQLite 中的 file relation 只保存 typed revision/path identity。验证至少覆盖 repository binding、
publication、commit/tree、path normalization、object type/OID、content digest、size 和 LFS closure。
任何 locator 或 mutable checkout path 都不能替代。

当前按已确认决策保留 Git-shaped revision contract。Contracts 可以携带 commit/tree/ref、Git object
mode/OID 和 LFS OID/size，但不能执行 Git、读取 bare root、访问 credential 或判断 remote 是否成功；
Adapter 返回 exact observation/receipt，Kernel 才据此推进 checkpoint/publication 状态机。

该边界由 implementation-free `WorkspaceRevisionBackendPort` 表达：read/observe 是 query-only；remote
publication dispatch 必须先进入 ControlledOperation admission，再由 Adapter 返回
`WorkspacePublicationRemoteReceipt`。Port 不携带 raw Git/LFS client、Host path、credential 或 mutable
checkout locator，也不能直接写 publication repository。

dispatch 侧必须收到 closed `WorkspacePublicationDispatchIdentity`：`receipt_id`、ControlledOperation
`execution_id`、`dispatch_generation` 与 `fencing_token`。Adapter 不能自己发明这些身份。materialize
侧则把 ControlledOperation 已持久化的 original remote receipt 重新交给
`observe_publication(binding, intent, receipt)`；Adapter 只核验 immutable ref/commit/tree 后返回同一回执，
不能按当前时间把观察伪装成原回执，更不能为了恢复而再次 push。若 dispatch response 根本没有持久化，
ControlledOperation 只能携带原 `WorkspacePublicationDispatchIdentity` 调用 `reconcile_publication`：ref 缺失
继续保持 `dispatch_in_doubt`，exact ref 返回一份明确的新 observation receipt，冲突 ref 终态失败。
publication namespace audit 同样只消费 Adapter 的 digest observation，不接触 raw `list_refs`。

目标 `@2` 应用路径现由 `PublicationKernelApplicationService` 固定为两段 publication：首次 `PUBLISH` 的
`phase=admit` 只在 current Session repository pin、workspace generation 和 `workspace.publish` authority 下
冻结 whole-tree intent；任何 create-only ref push 都属于另一个、与 intent digest 绑定的 generic
`ControlledOperation`。后续 `phase=materialize` 必须看到该 operation 已以 `terminal_known`、
`mutation_applied=true` 和 exact terminal receipt 结算，才调用 Git-shaped Adapter 的
`observe_publication`（不是 `dispatch_publication`）并 create-only 写入 `PublishedRevision`。响应丢失时原
operation 保持 reconcile-required，materialize 不重发、不换 route。`VERIFY_CHECKPOINT` 与
`VERIFY_REVISION_PATH` 同样把 Adapter observation 和 pinned binding/generation 求交后才记录不可变事实。

调用方不再提供已冻结 manifest/parent closure。`WorkspacePublicationCoordinator.prepare_intent()` 从 exact
Session、repository pin、workspace runtime binding、publication-boundary checkpoint 与 current
`AgentAuthorityLease` 开始，再消费 Adapter 的 commit/manifest observation 和 Git/LFS manifest policy；任一
identity 或 policy 失败均为 `no_effect`，不会留下 partial intent。确定性 idempotency replay 读取原 frozen
intent，不重复观察 Adapter。Standard 的 `build_standard_kernel_publication_runtime()` 已把目标 SQLite Store、
上述 Kernel services 和选定 Adapter Ports 组成可执行闭包；target Store 的 immutable
`kernel_command_receipt` codec 与 published-revision trigger 也已通过完整 fake-Adapter command 验证。

teammate `workspace.publish` handler 已删除对旧 `WorkspacePublicationService.publish()` 的调用，旧写实现和
公开导出也已移除；fetch/audit 只经独立的 `WorkspacePublicationReadService` 查询。写路径只接受注入的
Host-to-Kernel application；未注入即 fail closed。
默认 legacy Host bootstrap 也尚未把 Standard target runtime 自动接到全部 production route。因此当前可以证明
目标 publication application 与 Store 闭包可执行，但不能声称 production composition 或真实 deployment 已
cutover；禁止双写与在线 fallback。

Repository/workspace identity 的目标 writer 是 `WorkspaceIdentityKernelApplicationService`：

- `ProjectRepositoryBinding` 按 project 维护单调 head，但历史 binding record 永不覆盖；
- `SessionRepositoryBindingPin` 是一次性 immutable pin，必须逐字段匹配已注册 binding 和 Session project；
- `WorkspaceGeneration` 分离 logical generation 与同代 state version；首代必须是 generation/state version
  `1/1 + reserved`，同代只允许 closed lifecycle 转移，新 generation 只能接在 terminal predecessor 后；
- `ready`、`retired` canonical fact 必须引用同 Session 的 settled ControlledOperation，且其
  `effect_certainty=terminal_known`、`mutation_applied=true`、terminal receipt digest exact match；
- 只有 ready generation 物化 `WorkspaceRuntimeBinding`；进入 retiring/failed/retired 后不保留旧 runtime
  binding。该 binding 只包含 opaque root identity/provider/target，不公开 Host path 或 credential。
- `AgentAuthorityLease.workspace_generation` 的 target SQLite 外键直接指向
  `workspace_generation_records(session_id, owner_member_id, generation)`，不再要求在线补写旧
  `agent_workspace_generation_reservations`。公开 projection 将实体内 lifecycle 版本命名为
  `workspace_state_version`，将 record CAS 保留为 `state_version`。

Git ref、LFS、provision/cleanup 的实际调用仍由 Adapter/HPC Plugin 完成；Kernel 只消费受控操作回执并拥有
可恢复、可审计的 generation 真值。

公开 authority 写路径由 `AgentAuthorityLeaseKernelApplicationService` 持有。issue 必须使用 active issuer 的
`authority.lease.issue` grant；root generation 从 1 开始，successor 同时 CAS active parent 并逐一递增
generation/fence，parent 在同一事务变为 `superseded`。revoke 需要 `authority.lease.revoke`，并重建全部
operation-specific `AuthorityGrant` 使其 generation/fence 与 terminal lease 一致。reason 只进入 durable
audit event，不进入签名 authority payload；失败不会留下 child、parent 半更新或 outbox。

## Final schema

normal migration loader 的物理 owner 已迁为 `openzyme-store-sqlite`。目标 schema 由所选 Distribution 的
closed owner-partitioned migration profile，加上 Store-owned `001_composition_state.sql` 与
`002_deployment_proof.sql` 组成；旧 `001_file_workspace_final.sql` 只作为分区等价性的 source-bound 基线，
不是 normal startup 可单独运行的 migration chain。fresh empty database 写 `fresh_install_complete`；offline
adoption 成功写 `offline_removal_complete`。old、unknown 或 `offline_removal_incomplete` 在 mutation 前拒绝。

final schema 中保留 `legacy_removal_ledger/items` 只用于证明 deployment removal 完成与幂等重试，
它们不提供旧领域读取、写入、投影或 tool surface。

当前 schema 可在内存 SQLite 中重算出 147 张业务表、134 个索引、674 个触发器和 422 个外键；每个 index/
trigger/FK 通过 origin table 继承唯一 semantic owner。运行
`scripts/partition-openzyme-sqlite-schema.py` 会按 owner 与 tables/indexes/triggers/finalize phase 生成 25 个
closed migration bundles；`--check` 必须证明分区重放后的 `sqlite_master`、`user_version` 与全部 FK 数量同
现行单体 migration 完全一致。bundle 资源、object identity、semantic owner 和 digest 固定在 Store-owned
`manifests/migration-catalog.json`，重复、孤儿、跨 owner index/trigger 或字节漂移均使架构门禁失败。
`uv run python scripts/check-openzyme-architecture.py` 会拒绝重复 owner、孤儿对象、未知 owner、数量或 digest
漂移。该 inventory 是迁移基线，不授权修改真实数据库。

offline `@2` adoption 先以十六类 dry-run inventory、八类 owner/surface quiescence、database/configuration/
storage 独立 backup readback 和逐 Session disposition 建立 no-effect proofs。非终态 Session 只有在 Core、
extension、workspace、公开 AgentAuthorityLease mapping、target inventory binding、continuation 和 controlled
operation 全部唯一闭合时才能迁移；否则保持 blocked，不能补造 composition pin。

通过后，Store 在单一 `BEGIN IMMEDIATE` 内重验所有旧 capability-lease row 到公开 Authority DTO 的 exact
mapping set，写 activation/catalog、revision-1 Session binding/pin、backup receipts、complete cutover ledger 和
tagged deployment state。首轮保留旧物理表名且不重写业务行。任何 row/key/FK/constraint/digest drift 都整体
rollback，不生成 complete proof。commit 后必须关闭 writer并执行 read-only deployment/session/authority/ledger
readback；startup 只相信该 readback 与 exact persisted epoch。

恢复边界以 canonical mutation 为准：activation 前且 post-freeze mutation 为零时可恢复三份 exact backup；
一旦 activation epoch 或任何 `@2` canonical mutation 持久化，只允许再次 quiesce 后 forward repair，不允许
downgrade、旧 reader、dual write 或把备份作为 current runtime authority。设备 reset 是独立 destructive operator，
其 receipt 不能替代 cutover ledger、Session pin 或 deployment startup proof。
