# 文件工作区切换与旧存储离线退役

## 当前状态

当前源码已经实现文件/修订架构、final-only schema、离线历史 Git/LFS 迁移器、独立 verifier、
receipt-gated schema rebuild 和旧字节删除器。2026-08-17 曾对本机一个明确解析的 local deployment
执行零历史对象的离线迁移/删除，并生成 `LegacySubsystemRemovalReceipt`。该证据树绑定旧源码
`64df75fddf2746d0442697f6f5903defbfdcf87c` 与
`sha256:3f1755fc8649b48b0e819b13c6fa778e36725c82e35584231cd05e8f090a3e64`，不能证明当前
`b841ba01eaa0cd2dc32f8a54dc0adbaae25cdfdf` 或整改后的最终源码。

本次 closure 已把旧 release/per-change/removal receipts 登记为待 supersede，并重开十四个 change 的
最终收据任务。本设备随后只允许按已授权的 fresh-install reset 清单删除精确归属 OpenZyme 的旧数据库、
runtime records、旧 storage、收据、缓存和备份；源码、Git/OpenSpec 历史、当前仓库 Git LFS 与任何
未解析或非 OpenZyme 路径不在删除范围。旧证据在删除前只用于审计，不再充当最终 acceptance。

## 公开切换

当前源码唯一的 public contract 是 `file_workspace_public@2`。Host、CLI、UI 与共享 Client 使用 closed
`core + extensions`：

- Core 表达 Session/Task/Lane/Agent/Protocol/Approval、`AgentAuthorityLease`、capability binding、
  runtime/workspace/publication/operation/failure；
- Plugin section 分别表达 Research、Reporting、Science、Compute/HPC 等 owner state；
- release identity 分别固定 Kernel/schema、Adapter/Extension bundle、tool/route/projection/migration catalog、
  workspace backend 与 Host/client build；
- Session mutation 额外固定当前 projection、capability-binding 与 affordance-snapshot digest。

这描述源码和待激活 Distribution，不表示本设备已执行真实 cutover。旧工具、字段、media type、restore schema
和 saved catalog context 只能由 offline historical operator 读取；普通 Host 以不可重试 closed error 拒绝。
禁止 dual serialization、自动 rename、read-through 和 silent fallback。

## Fresh install 与普通启动

目标 fresh empty SQLite 先按显式 Distribution profile 安装 owner-partitioned schema，再顺序执行
Store-owned `001_composition_state.sql` 与 `002_deployment_proof.sql`。离线 seed 只在所有表为空时，以一个事务
写入 exact activation epoch、Extension bundle、七类 catalog identity、
`openzyme_fresh_install_bootstrap_receipt@2` 和 `fresh_install_complete` deployment state。receipt 绑定
Distribution、完整 schema manifest、owner profile、migration sources、installed wheels、table-owner manifest
与 layered release identity，并明确两个 legacy initialization fact 均为 false；它不创建 removal ledger。

重启 verifier 接收同一显式 composition seed，只读重算 schema、catalog、receipt、activation 和 deployment
state digest。`offline_removal_complete` 是另一 proof variant，必须解析到唯一完整的
`openzyme_offline_cutover_ledger@2`；fresh receipt 不能替代它。当前 fresh verifier/receipt 已实现并通过
isolated SQLite 测试；完整 offline plan/apply/rollback/restart、Host startup proof 和 Session 分类也已在隔离
fixture 中实现。真实部署 cutover 仍未授权、未执行，测试 receipt 不能替代设备 proof。

以下输入在任何 mutation 前拒绝：

- 非空但不属于 exact final generation 的数据库；
- legacy table/column/trigger/index 或未知 `user_version`；
- final schema manifest drift；
- `offline_removal_incomplete`；
- fresh bootstrap receipt 或 offline removal receipt 与 deployment state 不一致；
- offline state 缺少 ledger、ledger 不完整，或 expected/deleted/already-absent/error set 不闭合。

普通 Host 不加载旧 repository/storage adapter，也不运行离线 operator。
startup failure 必须报告 proof kind、expected/observed generation/manifest/receipt digest、ledger closure、
`mutation_applied=false` 与 `diagnostic_id`，不得静默初始化、补空 ledger 或选择另一条迁移路径。

## 阶段一：冻结历史迁移

迁移前必须：maintenance mode、停止 Host/runtime/continuation/execution/runner callback/UI
writer、验证数据库和 storage 备份，并签发 exact quiescence/writer-freeze receipts。

当前 target Store 已实现这一阶段的计划/验证合同：十六类 inventory dry run、exact
owner/surface quiescence、三类 independent backup readback 和逐 Session 三分类。它们不读取真实
外部路径、不停止进程、不制作备份、不写数据库；真实 operator 必须以另行授权的观察填充
这些 closed DTO。随后的 target Store adoption 已在 isolated SQLite fixture 中实现：它在一个短事务
内重验 authority mapping，写入 exact composition/Session pin/ledger/state，失败则全量回滚。这不表示
真实 deployment 已执行 cutover；本 change 仍禁止未经另行授权调用该 mutation 路径。

`offline_historical_inventory.py` 从只读旧库与 explicit source map 生成 exact manifest：
database/storage snapshot、schema inventory、每个 object 的 owner/lineage/source row version、
byte digest/size/range、repository binding/base commit，以及每个旧引用的 typed replacement。
inventory 会对数据库文件与专用 legacy roots 做前后快照，并要求 root 中的物理文件与 source
map 精确相等。任何未映射 storage locator、额外或缺失文件、未覆盖引用、symlink、越界路径、
short byte range 或 digest drift 都阻断。非历史型 revision/path/result/scientific replacement 必须
在冻结前已经具有精确 typed identity；迁移器不得用 `commit:path` 或 synthetic result 代替。

`offline_historical_migrator.py` 只在 admission 与 inventory 完全匹配时工作。它按
project/session owner 单元，从 pinned base commit 创建 `refs/openzyme/history/*`，按 policy
写 Git blob 或 Git LFS，且把 policy digest 和 unit manifest blob 固定到 target/receipt。若 immutable
ref 已存在，只接受与本次 deterministic commit 完全相同的 target。push 后从空 cache fresh-fetch
并逐字节回读。随后在一个 SQLite
transaction 中写 immutable mapping/rewrite/unit/global receipt。源行和源字节保留不删。

迁移器、standalone verifier 和删除器均要求 operator 显式提供绝对、非 symlink、受界的 working
root；所有临时 worktree、clone 和 final-copy 都只能建立在该 root 下。它们不读取系统临时目录、
当前目录或环境变量来推断数据位置。

`offline_historical_verifier.py` 不依赖 current runtime model 或旧 storage。它只读取迁移
receipt 和 immutable Git/LFS target，重新 fresh-fetch，并证明：

- expected 与 migrated identity/reference/byte set 精确相等；
- unresolved、negative 和 post-freeze write 均为零；
- source preserved；
- 每个 ref 都是 `historical_import_non_adoptable`，不能进入 current publication、handoff、
  scientific admission、task evidence、report claim 或 GO/NO-GO。

## 阶段二：最终 schema 与物理删除

`offline_remover.py` 是唯一可执行 removal 的 caller，且不注册到 Host、tool catalog、SDK
或 entrypoint。执行前它再次验证：

1. 固定顺序的 13 个前序 completion/acceptance receipt；
2. exact historical migration receipt 与 target readback；
3. maintenance/quiescence、writer fence、unsettled effect 为零；
4. database/storage backup digest；
5. current inventory、final schema manifest 和 deterministic dry-run digest；
6. surviving table 的 rebuild/copy identity 和 explicit storage deletion set。

先在独立 final copy 中创建最终 schema并复制 surviving typed rows，核对 row/key/digest、
constraint 和 foreign key。随后以单一 DDL transaction 交换 schema。失败时完整回滚，且不
删除任何 source object。

只有 post-DDL manifest 和 FK 验证成功后，才按 receipt 中的 explicit root identity、relative
path、digest 和 size 删除旧字节。不得使用 glob、ambient env、symlink、`--force` 或 manual
override。partial deletion 会保留 final schema，写 `offline_removal_incomplete`，阻止普通
startup；重试先从 final-schema ledger 重新绑定原 manifest、backup、historical receipt 和 target
set，只能处理同一 receipt 的剩余 identity，不重新比较旧库或重建旧 schema。最终 receipt 中
本次 `deleted` 与先前已 receipt 证明的 `already_absent` 必须是不相交且并集等于 expected set。

## 恢复

在本次 fresh-install reset 执行前，旧备份只能恢复到隔离 legacy environment，用于审计或核对
删除清单；不得将旧 schema、storage、tool 或 API 重新接入 current runtime。用户已明确要求本机
旧记录与备份一并删除，因此 reset 完成后这些本机副本不可恢复；可保留的历史只限源码仓库中的
Git/OpenSpec 历史和不属于删除目标的当前 repository-service Git/LFS。任何目标归属不确定时停止该项。

## 验收

仓库验收必须同时包含：

- isolated tmp fixture 的完整 migration、fresh readback、non-adoption 和 source preservation；
- isolated tmp fixture 的 schema rebuild、storage removal、ledger 与 final restart；
- fresh install/restart 与 old/incomplete startup rejection；
- current source/schema/catalog/UI 的负向静态扫描；
- core/Host/CLI/SDK/runner/UI focused tests；
- 14 个 change 的 strict OpenSpec validation；
- architecture qualification 与 `./scripts/check-mainline.sh`。

Web UI 验收必须同时运行 file-workspace contract、client、state、controller 和 view 五层测试，并
执行 production build。changed-path 分页必须绑定 exact workspace/generation/continuation；stale async
response 详细失败，不能覆盖当前 state 或静默改用全量列表。

所有上述验收均为 non-live。它们不访问 provider、真实 SSH/Slurm/HPC 或浏览器外部服务，也不授权
设备删除；设备 reset 必须另行完成精确 inventory、quiescence、逐项删除、零残留扫描和
`device_fresh_install_reset_receipt@2`。

`@2` reset inventory 不再用一个笼统的“旧 OpenZyme state”标签覆盖整棵目录。每个 target 必须绑定 closed
component kind、component owner、旧 Distribution identity/manifest、owner evidence 和 ownership scope；closed
path 模式遇到未归属 sibling 时记录 unresolved 并在删除前停止。计划必须同时列出并保护 source tree、Git 历史、
OpenSpec 历史与当前仍被引用的 repository-service Git/LFS truth，任何 target/exclusion ancestry overlap 都失败。
仅当旧 service 已由零 pin、零未结算 effect、owner evidence 和单独授权证明为退役 storage 时，才可作为精确
`repository_service` target 删除；新建空根随即恢复为 current exclusion。

最终 reset receipt 逐项闭合 deletion occurrence 和 post-delete absence，并绑定 exact quiescence、zero scan、
built-wheel/document set、目标 Standard/EnzymeDesign Distribution、composition bundle、fresh database identity 与
独立 fresh-bootstrap receipt。它明确 `recoverable=false`，不能被描述为自动 rollback，也不能替代 bootstrap、
offline cutover、Session composition pin 或 production startup proof。真实操作另记 operator evidence。若一次删除
未先经过 frozen `@2` inventory 和逐路径 occurrence log，后续不得追认或补造正式 reset receipt；独立
fresh-bootstrap proof 仍可按其自身合同验证。

隔离 fixture 回执只是测试证据，不能冒充真实部署 receipt。
