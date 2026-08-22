# Deployment composition operator guide

本文说明目标 `@2` composition 的启动、Session 固定和 Plugin 变更操作。当前
`distributions/openzyme-standard` 与 `distributions/enzymedesign` 均为结构上可激活的 `active` manifest；
application composition root 和 isolated fresh SQLite proof 已通过，EnzymeDesign 还有真实内部、明确 fake 外部
Ports 的 non-live 产品级场景。manifest active 不会自行打开 writer、route、worker、runtime 或外部效果。

状态词必须按下表使用：

| 状态 | 操作含义 |
| --- | --- |
| `selected` | 当前 Distribution manifest 精确选择该组件 |
| `runtime_mounted` | startup proof 后已构造并核对 exact runtime surface |
| `qualified` | exact target/provider 有当前有效 qualification receipt |
| `cutover` | 真实部署已采用该 composition/Adapter/configuration |
| `live` | 某次明确授权的真实 Provider/SSH/Slurm/HPC/容器调用实际发生 |

这些状态不蕴含后继状态。2026-08-21 的设备 fresh reset 是绑定提交
`5548ca85b0b581584379b4810e0777a6d97683b6` 的独立已完成 occurrence；其后 source/schema 继续变化，因此该
receipt 不能证明当前最终 source 已 cut over，也不能由文档或测试静默重做。当前 change 的外部
Provider/SSH/Slurm/HPC/容器仍未 live 执行。

SQLite Store 的目标 Adapter 已实现 owner-profile schema、composition state 与 Store-owned
`002_deployment_proof.sql`。fresh seed 可原子生成 deterministic `@2` bootstrap receipt 和 tagged deployment
state，重启 verifier 可零 mutation 复算；offline cutover planner、单事务 adoption 和 post-commit read-only
verifier 已在 isolated SQLite 中闭合 exact inventory、backup、Session disposition、authority mapping、
item/error/byte closure。旧 Core repository callers 与旧 Host factory 已删除；新 Standard/EnzymeDesign
composition root 只在 read-only proof、exact Adapter/Plugin mount 全部通过后构造 writer。当前 source 的再次真实
部署 adoption 仍须独立 quiescent cutover 授权，不能由 non-live runtime mount 推断。

## 启动前置条件

操作员必须准备 exact：

- Distribution TOML 及其 digest；
- Kernel contract/manifest 与 core schema digest；
- selected Adapter/Plugin/Driver wheel name、version、manifest resource/digest；
- declared tool、capability/HTTP route、projection、migration 及其余 contribution catalogs；
- workspace backend manifest identity；
- Host/client build digests；
- installed wheel-set proof。

secret 不写入 manifest、catalog、Session pin 或命令输出。配置只声明 non-secret schema和 secret locator；
真实 credential 由 CredentialMaterialPort 在 authority admission 后短时提供。

## 离线 dry run、quiescence 与 backup

operator 必须先构造十六类 exact inventory observation：source、wheel、Distribution、Adapter、
Plugin、Driver、schema、table、import、catalog、target inventory、authority、workspace、Session、
continuation 和 unsettled effect。`build_offline_cutover_dry_run()` 只生成 no-effect proof；缺类别、
unresolved item 或非空 effect set 会保留 typed blocker，不会修复输入。

quiescence requirement 由 exact owner/surface pair 构成，至少覆盖 Host、全部已选 Plugin worker、
Agent runtime、process Adapter、runner、UI、SQLite writer 和 Git writer。只有每个 owner 均已
stopped/isolated、writer generation/fence 已固定、unsettled effect 为空且 unknown-effect count 为零
时才签发 quiescence receipt。

database、configuration 和 storage 三份 backup 各自闭合 source identity/content/size、copy identity/
content/size 与 independent readback digest。这些 API 验证 operator 已制作的备份，不自行读取
或复制真实路径。恢复边界固定为 activation 前精确回滚；任一 `@2` canonical mutation 后只能
quiesce 并 forward repair。

逐 Session 分类只有三种：终态 `@1` 为 `closed_historical_at1`；非终态且 Core/extension/
workspace/authority/inventory/continuation/effect 全部唯一闭合并已有 target pin/binding 时为
`migrated_at2`；其余一律 `blocked`。blocked disposition 不得携带伪造 pin/binding digest。

dry run、quiescence、backup 和 Session dispositions 全部闭合后，
`apply_offline_cutover_transaction()` 才允许打开一个 `BEGIN IMMEDIATE`。该事务重验全部旧
`agent_capability_lease_records` 并与预算的公开 `AgentAuthorityLease` mapping digest set 精确相等；
它不改名、不重写原业务行。同一事务再写 activation/catalog identities、migrated Session 的
revision-1 binding/pin、backup receipts、complete item/session ledger 和 tagged deployment state。任一一致性、
constraint 或 FK 失败都 rollback；commit 后的 authority 来自 read-only readback proof，不来自事务返回值。

## Fail-closed startup sequence

顺序不可调整：

```text
parse Distribution (read-only)
  -> discover locator identities (read-only)
  -> select allowlisted locators (read-only)
  -> read/canonicalize exact manifests (read-only)
  -> build dependency graph and all catalogs in memory
  -> SQLite path preflight without opening the database
  -> open verifier connection read-only
  -> verify exact user version/migration/object-owner/FK closure (zero mutation)
  -> close verifier connection
  -> verify installed wheel set (read-only)
  -> create DeploymentActivationEpoch
  -> authorize repository-writer factory
  -> reopen writer and revalidate the same schema proof on that handle
  -> mount all Plugin runtime bundles atomically
  -> expose routes/start workers/runtime/effect dispatch
```

`ReadOnlyDeploymentVerification` 的三种 kind 必须正好是 `composition`、`core_schema`、
`installed_wheels`，expected/observed digest 相同，并固定 `mutation_applied=false`、
`effect_certainty=no_effect`、`fallback_performed=false`。缺一个 proof、proof digest invalid、release/catalog drift
或 surface mount 不完整都使 gate 保持关闭。

fresh target 的初始 epoch 也必须由这三份 proof 经
`DeploymentActivationCoordinator.activate()` 产生，不允许 Distribution factory 直接填造 epoch。
进程重启时不生成 replacement epoch；Standard/EnzymeDesign 的
`verify_*_deployment_startup_read_only()` 重算 fresh deployment proof，检查当前 installed-wheel
digest，并逐 Session 校验 composition pin、连续 capability-binding revisions 与所引用的
target inventory facts，最后只用 `reactivate_persisted()` 为数据库中原 exact epoch 开启进程内
gate。任一 orphan binding、pin/payload/digest/catalog/inventory 漂移都零写入失败。

一个进程中的 active gate 不能在线替换 epoch。新的 composition 必须停止旧 surface、证明 quiescence，走
offline verifier/migration，再以新启动激活。

normal startup 永远不调用 `bootstrap_fresh_offline()` 或
`install_store_schema_for_offline_migration()`。fresh bootstrap 只接受不存在的明确绝对路径；existing-table
adoption 必须使用后续 offline cutover plan 和 exact table-owner ledger，不能让 Adapter opportunistically
`CREATE TABLE`、改 `user_version`、修 proof 或回退到旧 reader。

离线 fresh 路径在 schema-only proof 后还必须提供 exact `FreshInstallCompositionSeed`：activation epoch、
七类 catalog canonical payload、所选 owner profile、ordered migration source identities、installed wheel set 和
table-owner manifest。seed 完成后只能用 `verify_fresh_install_deployment_read_only()` 复核；重复 seed 或任何
receipt/state/catalog/epoch 漂移都要求重新创建空 target，不允许 normal startup 补写。

Extension transaction 只能在 Kernel 已完成 authority/admission 与所有外部 I/O 后进入短
`BEGIN IMMEDIATE`。participant 的 `prepare`/`apply` 全程由 namespace authorizer 和
read/mutation/payload/time budgets 约束；跨表/namespace、`ATTACH`、PRAGMA mutation、DDL、CAS drift 或 result
identity drift 会回滚 Core mutation、extension state、event 和 outbox。LLM、Git、process、SSH、scheduler
不能在该事务内执行。

## 新建 Session

只有 active epoch 才能创建 Session。创建事务必须一次提交：

1. Kernel Session；
2. `SessionCompositionPin`；
3. revision 1 的 `SessionCapabilityBindingRevision`；
4. 对应 durable event/outbox facts。

pin 固定 Kernel/schema、Adapter/Extension/Driver bundle、declared tool、capability/HTTP route、projection、
migration/contribution catalogs、workspace backend、Host/client epoch 与 origin deployment identity。初始 binding
固定 Extension bundle、capability route catalog 和 operator 已采用的 inventory generations；可以为空，但不能
从环境自动补 target。

如果三者不能同一 transaction 提交，Session 创建必须整体失败，不允许产生没有 pin 的 Session 或孤立 binding。

## 请求与 restore 守卫

以下入口在 mutation/dispatch callback 前读取 current active epoch、Session pin 和 latest capability-binding
revision：

- user message；
- explicit runtime drain；
- approval resolution；
- tool/capability invocation；
- workspace mutation/exec/transfer；
- checkpoint/publication；
- controlled operation admission/observe/reconcile/cancel；
- restore/continuation resume。

任何缺失、digest invalid、wrong Session、Extension/route bundle drift、workspace/Host-client epoch drift都返回
`session_composition_upgrade_required`，并保持 `no_effect`、零 mutation、零 fallback。安全 inspection 可以读取
typed blocker 和 expected/observed bundle digest；不能借 inspection 执行操作。

同一 exact composition 在进程重启后可以重新形成验证 epoch；compatibility 由 composition/release digest
判断，不因进程局部 epoch ID 改变而误判。不同 composition，即使只是后来安装了 optional Plugin，也不会让
既有 Session 热获得 tool、projection 或 state。

## Target inventory adoption

Tool Plugin 只声明 versioned `QualificationSpec`，不得在 import、catalog build 或 Agent turn 中执行
`which`、SSH 或 smoke。操作员选择 exact target/environment 后，HPC qualification workflow 为 version query
和 deterministic smoke 分别创建 exact operation identity，并通过一个由 Kernel `ControlledOperation`
支撑的 Adapter Port 执行。Adapter response 必须回绑 request digest；响应未知只 reconcile 同一 occurrence，
不得重发、换 target 或回退到本地。

只有所有 probe `terminal_known`、observed version 存在且 smoke result 匹配 expected schema 时，workflow 才原子
发布 `SoftwareQualificationReceipt`、`TargetCapabilityFact`、`TargetToolchainInventory` 与
`InventoryGeneration`。terminal smoke 还必须回报实际证明的 non-empty supported operations，且只能是
QualificationSpec expected-result schema 允许的值；receipt 和 capability fact 保存同一集合。空 operations、
schema 外 operation、`dispatch_in_doubt`、identity drift、失败或 Agent actor 都保持 inventory repository
不变。transient health 是独立 observation，不参与 inventory、release 或 Plugin digest。

不要把领域工具写入 runner TOML。`runner_effective_config@2` 只接受 runner、cluster、
SSH transport、executor workspace、Slurm、execution bounds、limits 和 logging section；
`[adapters.hmmer]`、`[adapters.vina]` 等 section 会 fail closed。要改变工具可用性，操作员必须更新
Plugin/Driver 组合或发布、采用新 inventory generation，不能直接改 runner 配置制造能力。

Inventory 持久化使用 HPC Plugin 自己的 `openzyme_hpc_*` append-only namespace；正式安装必须由 offline
migration catalog 执行，普通 Host startup 不会 opportunistically 建表。采用结果写入 target qualification、
Compute/runner boundary 时必须携带同一 positive generation 与 closure digest，禁止继续配置只有
`toolchain_digest` 的 target，也禁止 Runner 从无结构 digest 推断 HMMER、Vina 或其他软件能力。

target inventory 是独立、高频而显式的 operator/admin 过程。采用新 generation 时：

- Extension bundle 和 capability route catalog 必须仍与 Session pin 一致；
- generation 对同一 target 必须单调增加；
- 创建新的 immutable binding revision；
- 不改 SessionCompositionPin；
- Agent 仍须在新 revision 提供的 routes 中显式选择，Kernel 不自动选唯一 route。

## Plugin upgrade/removal preflight

升级或移除前先生成 closed inventory：

- 所有 pin 该 Plugin 的 Session 及 terminal/migrated disposition；
- 所有 continuation 及 source version/terminal state；
- Plugin namespace row count/state digest/disposition receipt；
- Plugin-owned controlled operations 的 terminal/effect settlement；
- quiescence receipt；升级时还需要 migration plan digest。

`verify_offline_plugin_change()` 只做只读判断。下列任一情况阻止新 composition：non-terminal 且未显式迁移的
Session、non-terminal continuation、unsettled effect、非空 state 无合法 disposition、升级非空 state 无 migration
plan、deployment 未 quiesce。unused Plugin 只有在无 pin/continuation/effect/state blocker 时才可从新 epoch 省略。

Verifier 通过不等于已执行 migration、删除或 activation，也不授权真实数据库、Git、Provider、SSH/Slurm 操作。

## 拆分前部署状态只读盘点

在制定 `@2` 离线迁移计划前，操作员必须对明确指定的 control-store locator 运行只读盘点：

```bash
python3 scripts/inventory-openzyme-deployment-state.py \
  --database /operator/selected/control-plane.sqlite3 \
  --locator-id operator-selected-primary
```

脚本使用 SQLite `mode=ro` 和 `query_only`，不 import 产品包、不启动 Host、不执行 migration，也不写数据库；输出
只含文件 digest/size、schema proof identity、WAL、owner 聚合 row count，以及 Session、continuation、effect、
workspace pin、authority lease 和 HPC qualification 的计数。`locator-id` 是操作员给出的非秘密逻辑名，不能填
credential、URL 或 Host path。

仓库基线保存于
[`architecture/pre-split-deployment-state-inventory.json`](architecture/pre-split-deployment-state-inventory.json)。
它是某一时刻的工程证据，不会自动刷新，也不得用于推断 `@2` cutover、Plugin activation、live Provider/HPC
readiness 或 Task/scientific terminal。若当前数据库 digest、WAL 或聚合计数不同，必须生成新的候选盘点并重新
进行 offline classification；不得静默沿用仓库快照。

## 诊断与恢复

公开 activation failure 只显示稳定 code、component/phase、Distribution/component identity、allowlisted
expected/observed digest、collision/dependency key、`no_effect` 和 `repair_composition_and_restart`。不要把 traceback、
Host path、secret value、credential locator、stdout/stderr贴到公开 API。

同一 `diagnostic_id` 对应受保护 private record；其中 traceback/cause chain/output都有上限，secret-like fields
仍会 redaction。修复后重新运行整个 read-only sequence，不从失败中间点继续 mount，也不复用 partial registry。

## 设备 fresh reset

设备 reset 是显式、破坏性的部署管理流程，不是 Kernel command、Agent tool、普通 startup 或 offline
composition adoption 的隐式分支。当前 `device_fresh_install_reset_inventory@2` 要求每个 target 同时绑定：

- 精确绝对路径、`target_kind`、closed `component_kind`、`component_owner`；
- 旧 `distribution_id` 与 `distribution_manifest_digest`；
- owner evidence、`exact_tree` 或 closed `explicit_relative_paths` ownership scope；
- inode/device/type/mode/uid/gid/size/content digest、删除方法和真实 recoverability。

目录只能在 owner evidence 证明整棵树时使用 `exact_tree`。若使用 `explicit_relative_paths`，任何未列 sibling
或已声明但缺失的 path 都进入 `unresolved_targets`；只要该集合非空，destructive execution 在第一次 mutation
前失败，不能把 sibling 自动归给父目录 owner。特殊文件、mount boundary、symlink/identity drift 和 broad target
同样 fail closed。

plan 必须至少显式保护 `source_tree`、`git_history`、`openspec_history` 与
`current_repository_git_lfs_truth` 四类 exclusion。target 与任一 exclusion 存在相同路径或祖先/后代关系时
整项拒绝；实现不会替操作员缩窄路径、展开 glob、读取 ambient environment 或把当前 repository/workspace root
变成删除目标。已经由零 Session pin、零未结算 effect、精确 owner evidence 和单独操作员授权证明为退役部署
storage 的旧 repository-service 例外：它必须以 `repository_service` component target 明确列出，而不是继续冒充
`current_repository_git_lfs_truth` exclusion；fresh bootstrap 后新建的空 Git/LFS 根重新成为该 exclusion。

inventory freeze 只接受 `openzyme_offline_quiescence_receipt@1` 的 digest。该 quiescence receipt 必须已经覆盖
exact Distribution 的 Host、所有 Plugin worker、Agent runtime、process Adapter、runner、UI、SQLite writer 和
Git writer，并证明 unknown/unsettled effect 为零。删除授权再绑定 frozen inventory digest；执行过程中每个
`unlink`/`rmdir` occurrence 都先按 inode/device/content identity 重验，随后 durable 记录 component、owner、旧
Distribution、删除方法、`post_delete_absent=true` 与 `recoverable=false`。响应或日志不确定时只能检查并恢复同一
inventory，不能生成新 inventory、自动重删或宣称 rollback。

fresh bootstrap 可以在同一路径重建数据库，且文件系统允许复用刚删除对象的 inode；因此 replacement 证明不能把
“inode 必须变化”当作安全条件。校验必须同时绑定原 deletion occurrence、独立 fresh-bootstrap receipt、当前
device/inode/content identity，并证明新 content identity 不等于被冻结的旧对象。缺少任一项仍按路径复活拒绝。

删除完成后，操作员必须另行对空 locator 执行所选 Standard 或 EnzymeDesign 的 fresh bootstrap。最终
`device_fresh_install_reset_receipt@2` 同时绑定：source、frozen inventory、component-owner set、完整 exclusion、
quiescence、逐 path deletion results、permission adjustments、zero-residual scan、built wheel set、文档集合、
目标 Distribution/version/manifest、composition bundle、fresh database identity 和独立 fresh bootstrap receipt。
reset receipt 与 bootstrap receipt 永久分离；二者都不拥有 Session、Task、approval、runtime、Plugin 或科学真值。
EnzymeDesign receipt 绑定 exact Plugin/migration/inventory catalogs 也不表示 Provider、SSH/Slurm 或 HPC live ready。

设备重置合同与执行器现在由 `openzyme_store_sqlite.device_fresh_reset` 的 offline operator surface 拥有；旧
`openzyme_core.device_fresh_reset` 和旧 Core export 已删除。仓库中的 tmp fixture receipt 只证明合同和失败语义，
不能替代真实 quiescence、真实删除、真实 fresh bootstrap 或另行授权的设备操作。

## 当前 non-live 验证

```bash
uv run pytest packages/openzyme-contracts/tests \
  packages/openzyme-extension-spi/tests \
  packages/openzyme-kernel/tests \
  packages/openzyme-store-sqlite/tests \
  packages/openzyme-process-podman/tests
uv run ruff check packages/openzyme-contracts packages/openzyme-extension-spi \
  packages/openzyme-kernel packages/openzyme-store-sqlite packages/openzyme-process-podman
uv run python scripts/check-openzyme-architecture.py
openspec validate separate-openzyme-kernel-from-capability-extensions --strict
```

这些命令不运行 live Provider、SSH、Slurm、HPC、浏览器或真实 cutover；绿色结果也不能替代后续 offline
migration proof 与三 composition profile qualification。
