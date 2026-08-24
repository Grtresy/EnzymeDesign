# openzyme-store-sqlite

Kernel control store 的 SQLite Adapter。

当前已提供 side-effect-free locator、exact Adapter manifest，以及目标
`openzyme.control-store-port@1` 实现。目标实现已经包含：

- closed migration catalog、25 个 legacy owner/phase source bundle、两个 closed target schema profile 与显式
  offline-only composite fresh bootstrap；
- normal startup 的只读、零 mutation schema proof；
- 绝对路径与 bounded busy timeout 的 closed 配置；
- 先验证 proof、再开放 writer 的 connection lifecycle；
- 短 `BEGIN IMMEDIATE` Unit of Work，以及同一事务内的 event/outbox；
- namespace-confined `ExtensionStateStore` 与 SQLite authorizer；
- bounded `ExtensionTransactionParticipant` prepare/apply/result；
- immutable Extension bundle、catalog identity、Session capability binding、resource capability fact，以及
  Workspace effect 的 reserve/settle ledger。ledger 使用 exact provider/operation/intent/session/workspace
  generation identity、CAS `ledger_version` 和 content-bound receipt；它是 Adapter persistence mechanism，
  不成为 Plugin state 或新的 canonical Task/Science 真值。
- external qualification 的 protected SQLite ledger 也由本 Adapter 拥有，只保存 contract 已验证的 safe dry plan
  和 safe receipt JSON；private diagnostic root 与 credential material 不写入公共 payload。Distribution 只编排
  plan 和 Port，不能直接 import `sqlite3` 或把 qualification evidence 变成 Session adoption/cutover。
- `verify_session_composition_state_read_only()` 对每个 Session pin、连续 binding revision、固定
  Extension/route catalog 与 adopted target inventory reference 做零写入闭包，orphan 或 drift
  直接拒绝。
- offline planning 使用十六类 closed inventory observation 生成 no-effect dry-run proof；quiescence
  对 Host、Plugin workers、runtime/process、runner、UI、SQLite/Git writers 的 exact owner set
  做零写入闭包，不会隐藏 unsettled/unknown effect。
- database/configuration/storage backup 必须各自提供 source/copy size+content digest 和 independent
  readback；receipt 固定“activation 前 exact rollback、activation 后 forward-only”，不声称已执行备份。
- Session classifier 只将全部 Core/extension/workspace/authority/inventory/continuation/effect 唯一映射且
  已有 exact target pin/binding 的非终态 Session 标为 `migrated_at2`；终态 `@1` 作 historical，
  任一歧义则 blocked 且不补造 pin。
- `apply_offline_cutover_transaction()` 在单一 `BEGIN IMMEDIATE` 中重验旧 capability-lease 行的
  `AgentAuthorityLease` 确定性映射，写入 exact activation/catalog、已分类 Session 的 revision-1
  binding/pin、三份 backup receipt、item/session ledger 与 `offline_removal_complete` deployment state。
  任一 source row、pin、FK、digest 或 ledger child closure 失败都回滚全部 target rows，不生成
  complete proof；commit 后只用 read-only verifier 重算。
- Store-owned `002_deployment_proof.sql`，以及 `openzyme_fresh_install_bootstrap_receipt@2`、
  `openzyme_offline_cutover_ledger@2`、三类独立 backup receipt、逐 Session disposition 和 tagged
  deployment state 的 closed DTO/表结构。

`SQLiteControlStore` 现已实现 Contracts `ControlStorePort` 的 transaction/CAS/event/outbox 机制，但明确不
创建通用 `kernel_records(payload_json)` 平行真值表。每个 canonical entity 必须注册一个
`SQLiteKernelEntityCodec`，声明 owner 与既有 table closure，并把 snapshot/mutation 映射到该 owner 的现有
业务表；未映射 entity 直接失败。Unit of Work 在 `BEGIN IMMEDIATE` 内重验 Session version 和每条 mutation
的 state version，任一 CAS、event occurrence 或 outbox identity 错误回滚全部业务写、event 和 outbox，且不
重试、不调用外部 I/O。Plugin-free Kernel 声明的 40 种 canonical entity 均已有 production codec；
`openzyme-standard` 只有在 exact deployment activation 通过且 40/40 codec closure 一致时才构造 writer。
这证明 Store Adapter 的目标映射闭合，不等于通用 Host 已完成 caller cutover，也不授权 live 或 offline
deployment cutover。

`openzyme_store_kernel_entity_versions` 只保存 entity identity、nullable Session scope、semantic owner、单调
state version 和 canonical record digest，不含 `payload_json`，因此它是 CAS/有界查询索引而不是第二套业务真值。
`SQLiteControlStore.list_for_session()` 只在 `(session_id, entity_type, entity_id)` 索引上做带 `LIMIT + 1` 的查询，
随后仍由显式 codec 从 owner table 重建并验证 payload/digest；超预算、scope 漂移或 ledger-owner row 漂移直接失败。
payload 必须由显式
codec 从 owner table 重建，owner row/ledger 任一缺失、owner 不符或 digest 漂移即 fail closed。production
codecs 已覆盖既有 `sessions`、`lanes`、`tasks`、`task_dependencies`、`agent_members`、
`agent_capability_lease_records`、`agent_runtime_signals`、`session_runtime_leases`、
`approval_requests`、`continuation_state_records`、`controlled_operation_records`、
`failure_observation_records`、`engine_documents`、`memory_entries`、`inbox_messages`、
`project_repository_binding_versions`、`project_repository_binding_heads`、
`session_repository_binding_pins`、`workspace_generation_records`、
`workspace_runtime_binding_records`、`verified_workspace_checkpoint_records`、
`workspace_publication_intents`、`published_revisions`、`revision_path_verification_records` 与
`task_evidence_records` 表，以及 `command_receipt_records` 中 target-only 的 immutable
`kernel_command_receipt` payload；Protocol 的三种操作统一持久化为稳定的
`protocol_record` entity type，operation 保持为 closed payload 事实，而不是产生动态 Store 类型。Lane 的目标
`workspace_binding_id`，以及 Task 的 owner、validator、evidence 与 explicit-finish 字段，是在保留原表名和
既有字段含义下新增的显式列，不写入 CAS ledger payload。checkpoint/publication 的 target triggers 只消费
Kernel `WorkspaceGeneration`、`WorkspaceRuntimeBinding`、`AgentMember`、`AgentAuthorityLease`、
`ProjectRepositoryBinding` 与 generic `ControlledOperation` truth，不再读取 Git Adapter workspace 或旧
publication execution tables。published-revision identity trigger 以 `ControlledOperation.actor_id` 对齐
`publisher_agent_member_id`，不会把稳定 AgentMember identity 与 provider-facing `agent_id` 混用。
ControlStore 还为
旧 schema mutation guard 注册 request-scoped callback，只在当前 UoW、exact Session 和 codec 声明的 channel
返回 allow，commit/rollback 后立即清空，不提供全局 bypass。

这些代码不表示当前 Host 已完成 cutover。现行 `001_file_workspace_final.sql`、bootstrap 与 deployment
proof 的代码 owner 已机械迁入本包。文件创建、connection flags、WAL、read/write/long-flow scope、短事务
commit/rollback 和 eager legacy schema bootstrap 也已迁入本包的
`LegacySQLiteRepositoryProvider`；它通过显式 `repository_factory`、connection configurer 和
pre-commit validator 装配旧聚合，不 import `openzyme-core`。旧 Core 已删除
`SQLiteRepositoryProvider`、`CoreUnitOfWork` 和 `CoreRepositoryConnectionScope` public exports；Host 只在
`legacy_repository_provider.py` 中保留 ledger-bound composition wrapper。Session、Task/Lane、access、durable
event/command receipt、Approval/Inbox/Memory/Agent、ControlledOperation、Continuation、runtime lease/signal
以及 reliability execution/receipt、runtime command/mutation/quiescence、failure/diagnostic、workspace
checkpoint/publication、engine invocation/document 的 SQLite repository implementation 已迁入本包；旧 Core
对这些名称只作兼容重导出，并为 runtime signal capability admission、terminal engine-invocation projection
和 commit fence 注入 Kernel policy。旧 capability/retirement 物理表的 SQL repository 也已迁入本包；Store
只认识 opaque record 和注入的 `LegacyAgentCapabilityRecordCodec`，旧 Domain DTO 构造仍留在临时 Core codec，
不会成为 Store 依赖或 `@2` public alias。project binding/Session pin 与 revision-path/protocol handoff/task
finish evidence repositories 也已迁入 Store；原 handoff repository 中的 Research index 已拆成独立 legacy
Plugin caller，不再污染 Kernel repository。保留物理表 `agent_capability_lease_records` 现在用 closed
`record_kind` 区分 historical `legacy_capability_lease` 与 target `agent_authority_lease`：前者继续受固定
`general/executor`、workspace reservation 和旧 lifecycle triggers 约束，后者只保存 operation-scoped
grants、generation/fence/state/digest，不生成旧 profile/capability alias；legacy mapping 也只读取前者。
Runtime/coordination retained tables 也使用 target-only columns：runtime signal 绑定 AgentMember、authority
digest、workspace/process generation 和 Session lease fence；Approval、Continuation 与 ControlledOperation
分别保存其 closed Kernel fields，不用假 operation/sandbox/engine envelope 填充历史必填列。目标 signal trigger
直接验证 target authority/runtime rows；旧 Core callback 名只由 ControlStore 注册 deny-only sentinel，避免
target writer import 旧 Core，并让任何 legacy mutation 尝试 fail closed。
旧 mixed Core 已移除；Kernel target production codec、通用 Host 及 Store writer 均只使用公开 Port/owner seam。
目标 fresh loader 必须显式选择 `openzyme_standard_local_file_sqlite_git@1`
或 `enzymedesign_local_single_process_file_sqlite@1`，只安装该 profile 的 owner bundles，再安装 namespaced
composition/deployment-proof migrations。`seed_fresh_install_composition_offline()` 已能在完全空的 target 上
以单一事务写 exact activation、Extension/catalog identities、deterministic bootstrap receipt 和 tagged
deployment state；`verify_fresh_install_deployment_read_only()` 会按同一 Distribution seed 零 mutation 复算。
该 loader 只用于明确的 offline cutover。normal startup 不创建、不修复、不升级表。Store 组件状态为
`target_implemented_not_cutover`；Distribution manifest 的 `active` 只允许结构闭包和 isolated fresh proof，
历史 schema adoption 未被授权时不得对真实部署执行迁移。

设备级破坏性 reset 由 `openzyme_store_sqlite.device_fresh_reset` 单独拥有。它使用
`device_fresh_install_reset_inventory@2` 冻结绝对路径、component/owner/Distribution、inode/device/content、
强制 exclusions 与 recoverability，并在每次 `unlink`/`rmdir` 前重验同一 identity、写 durable occurrence。
`device_fresh_install_reset_receipt@2` 必须绑定独立的 fresh-bootstrap receipt、wheel/doc/Distribution/composition
identity；该模块不在 normal startup、Kernel 或 Agent tool surface 中。未在删除前生成的 inventory/occurrence
不能事后补造。

现行单体 SQL 同时保留为 compatibility bootstrap，并由
`scripts/partition-openzyme-sqlite-schema.py` 确定性生成 25 个 owner/phase bundles。生成顺序固定为所有 owner
tables → indexes → triggers → Store finalize；`migration-catalog.json` 绑定每个资源、owner、object closure 与
digest。`--check` 会在内存中分别重放单体与分区 assets，要求 `sqlite_master`、`user_version`、159 tables、
134 indexes、706 triggers 和 462 foreign keys 完全相同。分区没有重命名 DDL，也不是 production cutover。

## Connection 与 migration 边界

`SQLiteConnectionProvider.preflight()` 只执行路径 `stat`，不打开数据库。正常启动顺序必须是：

1. `open_verifier()` 以只读连接打开现有文件；
2. `verify_composite_store_schema_read_only()` 先调用
   `verify_owner_partitioned_schema_read_only()` 验证 explicit owner schema profile，再调用
   `verify_store_schema_read_only()` 验证仅限 `openzyme_store_*` 的 UoW/composition closure。前者从 packaged
   `migration-catalog.json` 重验 source bundle resource digest、选中 owner 的 table/index/trigger closure、
   profile-specific foreign-key closure、source user version 和零 mutation/plugin import/writer facts；
3. caller 提供 `SQLiteStartupCompositionExpectation`；verifier 不 import Plugin，而是从 exact activation
   epoch 的 immutable rows 核对 Extension bundle payload，以及 closed adapter/extension/migration catalog
   set 和 canonical digests；
4. `open_writer(proof)` 在 exact writer handle 上再次验证同一 proof 后才返回连接。

fresh seed 要求七类 catalog 正好为 `adapter_bundle`、`extension_bundle`、`declared_tool`、`route`、
`projection`、`migration`、`workspace_backend`，并要求 release 的 `core_schema_digest` 等于实际 composite
schema manifest。receipt 同时绑定所选 owner profile、全部 migration source digest、installed wheel set 和
table-owner manifest，且固定 `legacy_schema_initialized=false`、`legacy_storage_initialized=false`。重复
seed、非空 target、epoch/schema 错绑或 state/receipt/epoch JSON 漂移均拒绝，不修复也不 fallback。
Distribution fresh factory 通过 Kernel 三 proof coordinator 生成 epoch；startup 只能在 Store
deployment proof 和 Session composition-state proof 同时通过后重新授权该持久化 epoch。

两类子 proof 不能互换，也不能只凭 object count 通过。`CompositeSQLiteStartupProof` 绑定两者 proof digest、
完整 sqlite_master digest、统一 user_version 和 object count；`open_writer()` 在 exact writer handle 上重验同一
composite proof。schema-only proof 只允许 offline bootstrap/inspection，`open_writer()` 明确拒绝它；只有同时
绑定 exact composition proof 后，writer 才能在 exact handle 上重验并获得 authority。本 verifier 不 mount
Plugin；缺失、多余、跨 epoch 或 payload drift 均零 mutation fail closed。

`bootstrap_fresh_offline()`、`install_owner_partitioned_schema_for_offline_migration()` 与
`install_store_schema_for_offline_migration()` 是显式离线入口。它们不会被
preflight、locator、import 或 normal startup 调用；现有路径一律 fail closed，也不会删除失败 occurrence
留下的文件。无参数调用只服务 legacy-full fixture；目标 Distribution 必须传入 closed profile：Standard
创建 107 tables/104 indexes/476 triggers/340 foreign keys，且没有 Research/Reporting/Science/Compute/HPC
或 legacy-removal tables；EnzymeDesign 创建 156 tables/134 indexes/706 triggers/461 foreign keys，并包含
所选通用 Plugin owner。两者 proof 的
profile/schema digest 必须不同，拿错 profile 以 unexpected-object 失败。

## Extension state 与事务

扩展只获得绑定一个 `state_namespace` 的结构化 reader/writer，不获得 repository provider 或 raw Core
connection。authorizer 在 participant 的整个 `prepare`/`apply` 调用期间生效，只允许固定
`openzyme_store_extension_state_records` 表，拒绝其他表、`ATTACH`、PRAGMA mutation 与 DDL。每个 plan
同时受到 read、mutation、payload byte 和 wall-clock budget 约束。

事务顺序固定为：Kernel 先完成 authority/admission 和所有外部 I/O → `BEGIN IMMEDIATE` → Core mutation
→ typed participant → durable event/outbox → commit。participant、CAS、budget 或 identity 任一失败都回滚
整个 occurrence；Store 不重试、不跳过 participant，也不把 receipt 推断成 Task/scientific terminal。

`RevisionPathVerificationReceipt` 没有伪造的 `session_id`；它通过 canonical `publication_id` 外键属于一次
publication。因此通用 `list_for_session()` 不会返回这类记录。需要验证 formal Compute 输入时，composition root
注入只读 `SQLiteRevisionPathVerificationQuery.list_for_publication()`，按 publication foreign key 读取并重新校验
closed receipt digest。Product Plugin 只消费该窄 query Port，不接触 raw SQL 或 Store 私有 repository。

## Authority 兼容映射

`openzyme_store_sqlite.authority_mapping` 是旧物理表与新公共契约之间的只读、fail-closed
mapper。它接受当前 `agent_capability_lease_records` 的 exact row shape，验证旧 schema、profile
tuple、target 排序、lifecycle、immutable fingerprint 与 canonical digest，再映射为 Contracts
拥有的 `AgentAuthorityLease`：

- `workspace_generation` 同时保留为 workspace generation，并映射为 lease generation；
- `state_version` 映射为 fence；
- `pending_workspace / active / revoked` 分别映射为 `pending / active / revoked`；
- 旧 `general / executor` 只作为 issuance provenance，展开为 operation-scoped
  `AuthorityGrant`，不能扩大旧行已有 authority；
- repository、network 与 HPC operation 必须由旧行中的 exact target scope 支撑；
- 旧表没有 wall-clock expiry，因此公共 lease 的 `expires_at` 为 `null`，mapper 不编造过期事实；
- mapper 不生成 Extension/Resource capability，不写数据库、不重命名表，也不创建
  `AgentCapabilityLease` 的 `@2` 公共别名。

映射规则的机器可检验来源是
[`authority-store-mapping.json`](../../docs/v3/architecture/authority-store-mapping.json)。连接/UoW/provider、
Kernel repository implementation、production codecs 与 159-table owner schema 均由 Store 拥有；
Standard 的 `@2` composition 使用该唯一 writer。历史数据库 adoption 与真实 deployment cutover 仍只允许由
离线 operator 流程在明确授权后执行。
