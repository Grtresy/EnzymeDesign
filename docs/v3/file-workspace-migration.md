# File workspace 迁移与 artifact 退役合同

## 当前状态

本页记录 C1--C14 的迁移目标和源码候选边界，不宣布 production cutover。
截至 2026-08-17，C10--C14 的 operator gate 均为 source-only：正式
completion/acceptance receipt、public activation epoch、全量 historical migration
receipt、fresh Git/LFS read-back、quiescence、backup 和 removal receipt 尚未形成。
因此 current Host、数据库 migration loader 和兼容路径仍以当前代码为事实；任何
候选 schema、projection、SDK 或离线合同都不能被解释为 live authority。

GO 只在 13 个前置 change 的 exact receipt、历史 identity/row/object/byte/reference
集合相等、零 post-freeze write、AOX non-adoption、final public epoch、完整测试与
架构 qualification 全部闭合后成立。任一事实缺失即 NO-GO；source-only gate、空表、
feature flag、backup、零 caller 扫描或 operator assertion 均不能替代 receipt。

## 目标资源合同

| 资源 | 精确身份 | owner 与写权限 | 生命周期与持久化 |
| --- | --- | --- | --- |
| project repository binding | clone identity、object format、default/base ref、credential scope、binding version/digest | project owner 配置；session 只 pin exact version | durable、版本化；drift fail closed |
| agent Git workspace | project/session/agent/generation、private ref、base commit/tree、binding version | resident teammate；capability lease 与 ref ACL 同时成立才可写 | provisioned → active → retiring → retired；private refs 与 volume 分离管理 |
| workspace checkpoint | workspace generation、commit/tree、manifest/LFS closure | workspace owner 创建；不是 public publication | append-only canonical row；不自动 handoff/task finish |
| immutable publication | publication id、ref、commit/tree、manifest、LFS closure、source checkpoint | Host publication authority | append-only；supersession 不删除旧 revision |
| revision/path handoff | repository binding version、publication/revision、normalized path、object identity/digest | sender 显式选择，recipient 只获得引用所授予的读取能力 | durable protocol/task/report/scientific typed ref；不复制 bytes |
| executor HPC workspace | target、login alias、remote root identity、owner generation、lease/fence | exact executor owner；只有 active lease 可见 locator | provision/qualify/use/cleanup receipt；runner-private handle 不公开 |
| external job/result | source revision、compute manifest、opaque backend handle、occurrence/effect certainty、result revision | Host supervisor 调度；executor 不接触 SSH/Slurm config | revision-bound durable lifecycle；timeout/release 不等于 settlement |
| scientific deliverable | attempt/selection、publication、role、path、Git blob 或 LFS OID/size、actual-byte digest、format contract | sealed scientific selection + fenced finalizer | ref/bundle/validation receipt 原子持久化；historical import 不可采纳 |
| historical import | original identity/lineage、migration unit、immutable historical ref/commit/tree/path、Git/LFS bytes | 一次性 offline migration authority | 永久只读、`historical_import_non_adoptable`；不进入 current publication/evidence |

session 与 agent workspace 必须分离：session 是 task/protocol/approval/runtime 真状态；
agent workspace 是某个 resident teammate generation 的私有 Git 工作面。publication、
handoff、scientific finalization 和 job result 均需显式边界操作，不能从 dirty worktree、
文件存在、runner output 或 task idle 自动推断。

## 公共投影与隐私

候选 `file_workspace_public@1` 只投影 typed workspace status、immutable publication、
report、scientific deliverable、external job/result 与 lease 摘要。login alias、remote path
或 runner locator 只可出现在 exact executor owner 且匹配 active capability lease 的
owner-only section；普通 agent、master、浏览器和报告不得获得这些值。raw storage URI、
credential、runner config、opaque backend handle 和 private Git credential 永不进入通用
workspace projection。

公共 catalog/schema bundle 与 projection 必须绑定同一 activation epoch。旧 schema、
未知 field/tool 或 digest drift 返回版本化 stale/unsupported error，不做字段翻译、路径
猜测、publication 选择、commit 创建、blocked action 重开或 external effect 重发。

## Sandbox、Pipeline 与 HPC 边界

目标 sandbox SDK 只处理 native workspace file 与 revision/path identity。sandbox 内代码
不能读 Host artifact catalog、Host path、SSH/Slurm config 或 runner credential，也不能把
catalog ref 直接传给 provider。HPC source 由 immutable revision + compute manifest 闭合；
结果通过 result revision/link 返回，不使用 expected-output artifact publication。

在正式 cutover 前，candidate file-workspace tool catalog、Host projection 和 Pipeline SDK
不得替换 current surface。current 代码若仍需要 artifact staging，必须继续遵循现行受控
边界；不得把候选 API 当作隐藏 fallback 并绕开 approval、lease/fence、effect certainty、
provenance 或 explicit `task.finish`。

## 历史迁移与物理删除

历史迁移按 project/session unit 冻结 inventory，读取 exact legacy locator，验证真实 bytes，
写入 append-only `refs/openzyme/history/*`，fresh-readback Git blob/LFS object，并证明 row、
object、byte、reference rewrite 和 unit receipt 的 exact set equality。source object 在全局
receipt 前必须保留；historical ref 永远不能满足 current scientific/publication/task/report
admission。

物理删除是另一个不可逆 offline maintenance 阶段。normal Host 不得获得 migration
authority。专用 remover 必须重新验证 13-change receipts、historical receipt、当前 inventory、
fresh targets、writer high-watermark、quiescence 和隔离恢复 backup，先产生无副作用 dry-run，
再在单一 database transaction 中 rebuild/copy/compare surviving typed tables并 drop legacy
schema；提交后才可按 frozen explicit allowlisted inventory 删除 storage。部分删除失败时
deployment 保持 removal-incomplete，runtime 拒绝启动，只能继续同一 receipt 的剩余目标，
不得重建 legacy schema 或扩大删除 root。

当前 `remove-artifact-control-plane-and-storage/operator/offline_removal_contract.py` 仅是纯
manifest/admission/dry-run 合同，位于 runtime、package export、entry point 和 migration
discovery 之外；它没有数据库、文件系统、Git/LFS、provider、runner 或网络 I/O，也不签发
authority。

## 激活、兼容与禁止 fallback

激活必须作为一个原子 epoch完成：final schema generation、current migration manifest、Host
tool/catalog/schema、CLI/SDK、UI reducer/view、runner contracts、docs 与 qualification receipt
必须一致。fresh install 只能建立最终 file/revision/job schema；artifact-era migration source
只可留在 inert archive。old/incomplete deployment 以 `legacy_schema_unsupported` 或
`legacy_removal_incomplete` 在 mutation 前拒绝启动。

禁止：dual-write、read-through compatibility、nullable legacy placeholder、synthetic ref、
ambient path、glob deletion、manual override、`--force`、隐式 task completion、timeout 推断
effect settled、把 historical import 提升为 current evidence，以及在 receipt 缺失时用“能跑”
的替代 plan。
