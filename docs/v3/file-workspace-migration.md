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

当前 public contract 是 `file_workspace_public@1`。Host、CLI、SDK 和 UI 只表达：

- agent workspace generation、clean/dirty status 和 private checkpoint；
- immutable `PublishedRevision`、Git/LFS closure 和 `RevisionPathRef`；
- report、scientific deliverable、external job/result 和 capability lease；
- task、lane、protocol、approval、runtime 和 failure 的 control-plane 状态。

旧工具、字段、media type、restore schema 和 saved catalog context 以不可重试 closed error
拒绝。禁止 dual serialization、自动 rename、read-through 和 silent fallback。

## Fresh install 与普通启动

fresh empty SQLite 只执行 `001_file_workspace_final.sql`，写入
`openzyme_file_workspace_final@2`、exact schema manifest digest 和 deterministic typed
`FreshInstallBootstrapReceipt`。重启时必须重算并匹配同一 manifest 与 bootstrap receipt digest。
fresh proof 不伪造 offline removal ledger；offline proof 继续要求完整且逐项闭合的独立 ledger。

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
`DeviceFreshInstallResetReceipt`。

隔离 fixture 回执只是测试证据，不能冒充真实部署 receipt。
