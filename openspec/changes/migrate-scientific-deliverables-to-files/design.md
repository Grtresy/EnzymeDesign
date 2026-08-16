## Context

连续源码迁移期间使用 `scientific_deliverable_source_only_dependency_gate@1`。它绑定 immutable AOX supersession receipt、当前 predecessor source gates 与 source identities，但不证明前序验收、不可启用 scientific file writer/contract epoch、不可读取 remote Git/LFS bytes、不可创建 publication，也不可触发 provider、HPC、attempt、selection、task、report、GO/NO-GO 或 live effect。正式 prerequisite/completion receipts 必须在 combined final source 的统一验收中重建。

当前科学链把 `SessionArtifactRecord` 同时当作交付物身份、sealed bytes locator、selection 输入、attempt lineage、finalizer 输出和离线验证入口。AOX 又把固定 17-role bundle、source snapshot、operation、selection、attempt closure 与 artifact set digest 原子绑定。前序 changes 已经建立 project repository binding、agent 独立 Git workspace、Git LFS、immutable `PublishedRevision`、revision/path handoff、workspace-revision HPC execution，并将旧 AOX artifact cutover supersede 为不可恢复的 legacy NO-GO。本 change 必须把 scientific truth 切换到 exact repository revision/path 与 Git/LFS bytes，同时完整保留科学 authority、selection、closure、effect certainty 和 verifier 语义。

本 change 只迁 current scientific writer/read path。旧 artifact bytes 的完整历史搬迁由 `migrate-historical-artifacts-to-git-lfs` 负责；artifact schema/storage 的物理删除由 `remove-artifact-control-plane-and-storage` 负责。三者不得合并为一次不可审计的 destructive migration。

## Goals / Non-Goals

**Goals:**

- 定义 immutable `ScientificDeliverableRef`，使科学交付物由 project repository binding、`PublishedRevision`、exact commit/tree、normalized repository path、Git blob 或 LFS object closure 与科学 lineage 共同定址。
- 让 AOX 固定 17-role bundle、candidate/finalizer、selection、attempt closure、evidence export 和 offline verifier 只消费 Git/LFS bytes，不再创建或读取 current artifact records。
- 保持 operation/attempt/selection/adoption/materialization/closure、approval、cross-attempt reuse guard、task terminal authority 和 GO/NO-GO 合同不变。
- 明确区分 fresh current scientific deliverable 与 legacy historical import；后者在 schema、namespace 和 validator 三层均不可 adoption。
- 一次性切换 current scientific writer，不提供 dual-write、artifact projection 或 extension-based kind inference。

**Non-Goals:**

- 不恢复或继续执行 superseded `aox-hmm-blank-world-cutover` 的 c001、8.3–8.8、authority、roots 或 effects。
- 不在本 change 中运行新的 AOX live campaign；后继 cutover 必须另建 OpenSpec 并取得 fresh pin 与 fresh live authorization。
- 不迁移或删除 legacy artifact rows/blob objects；只定义它们不能进入 current scientific path。
- 不改变 `task.finish`、runtime drain、approval resolution、controlled-operation effect certainty 或 scientific attempt authority 的业务所有权。
- 不把 arbitrary workspace path、dirty branch、private revision、URL、Host path 或 runner locator提升为科学交付物。

## Decisions

### 1. 以已发布 revision/path 为唯一 current scientific bytes identity

`ScientificDeliverableRef` 采用 closed versioned schema，并至少固定：

- project id、repository binding id/version 和 binding policy digest；
- publication id、immutable publication ref、published commit、tree id 和 normalized repository-relative path；
- ordinary Git blob id，或 Git LFS OID、declared size 与实际 bytes size；
- canonical content digest、media/format contract、scientific role 和 deliverable contract version；
- producer controlled operation/execution/result、scientific attempt、sealed selection、workspace generation 和 publisher；
- ref schema version、created time 与 optional supersedes ref。

同一 ref 的 identity fields 不可更新；修正必须产生新的 publication、ref 和 selection head。选择这一结构而不是通用 `FileRef`，是因为 scientific role、attempt 与 selection lineage 属于科学产品真状态，不能依赖 path 或文件扩展名推断。选择 `PublishedRevision` 而不是 private commit，是因为其他 agent、offline verifier 和 campaign reducer必须读取同一不可变 remote ref；local commit 或 private ref 仍可能被删除、force-update 或仅在单一 clone 可见。

### 2. Git/LFS 只承载 bytes，scientific control plane 继续承载 authority 与 closure

Git commit/tree/blob 和 LFS object证明内容与路径；数据库中的 `ScientificDeliverableRef`、selection、adoption/materialization、closure 和 validation receipt证明业务归属与科学裁决。Git history 不替代 task、approval、attempt、operation、mutation writer 或 GO/NO-GO state。

不采用“把所有科学状态写进 manifest 后只信 Git”的方案，因为 Git commit 不能证明 actor assignment、approval continuity、execution effect certainty、selection transaction 或 task terminal authority。也不采用新的通用 CAS/catalog，因为那会重新建立 artifact 的万能顶层概念。

### 3. Finalization 从 immutable publication 读取并在一个 control-plane transaction 中提交

科学执行先在 executor workspace 生成普通文件，完成 required validation，提交 clean commit，再通过 `workspace.publish` 得到 immutable `PublishedRevision`。AOX finalizer 的步骤为：

1. 在 mutation transaction 外解析 exact publication/ref，读取 Git/LFS closure，并重算每个文件的 blob/LFS/content digest、size、format 和 role contract。
2. 验证 publication、attempt、selection、producer operation/result、workspace generation 与 authority 全部属于同一 current scientific scope。
3. 构造 deterministic 17-role manifest 和 validation receipt preimage。
4. 在一个短 transaction 内重验 immutable publication identity、selection head、attempt state、actor/fence 和 mutation authority，并原子插入 17 个 `ScientificDeliverableRef`、bundle manifest 与 validation receipt。
5. exact idempotent replay 返回原 identities；任一 input、role、path、digest、selection 或 authority drift 均 fail closed，且零部分 ref/receipt 写入。

Git/LFS publication 已经是不可变外部事实，因此数据库 transaction 不跨 Git/LFS I/O。若 publication 在读取后不能按 exact immutable ref 重读，finalization 失败；不得改读 local clone、另一个 ref 或缓存 bytes。

### 4. AOX 17-role contract 是 closed manifest，不从扩展名猜语义

AOX finalizer继续要求 versioned fixed-role contract 的 exact 17 entries。每个 role 必须映射到唯一 normalized path 和明确 format contract；路径重复、role 缺失/额外、case/Unicode normalization 冲突、blob/LFS closure不完整或 bytes validation失败均阻止整组提交。文件扩展名只能是已声明 format 的被验证属性，不能决定 role、kind 或 fallback parser。

candidate/filter、conditional-empty 和 fixed bundle validation必须读取 exact published bytes。合法空结果仍由其专用科学合同与 receipt证明，不能用零字节、placeholder、sentinel 或缺文件表达。

### 5. Selection、adoption、closure 与 task exit 保持显式

Selection universe 继续由 Host 从 attempt-scoped controlled operations 与 covered execution/sandbox occurrences推导；每个 occurrence仍需显式 disposition，adoption仍需 exact role、operation、selection head、reason、idempotency和 same-attempt authority。`ScientificDeliverableRef` 只绑定已 sealed selection及其 adopted producer chain，不成为新的 occurrence、不会隐藏 failed/superseded history，也不能反向改变 selection。跨 attempt/campaign/probe/fault/historical-import operation、result或ref永远不 compatible。已发布文件存在、17 个 ref已创建或 verifier通过，都不机械 seal selection、close attempt、finish task、publish report或生成 GO。

`task.finish` 只接受 closed typed evidence，例如 `scientific_deliverable:<id>`、`scientific_closure:<id>`、report 或 controlled-operation result。裸 revision/path 不能代替 deliverable ref，因为它缺少科学 lineage 与 role validation。

同一 attempt内跨 run或跨 agent消费已采用的科学 bytes时，producer必须先形成 exact immutable publication/ref，consumer以原生 Git fetch取得该 ref，并在 controlled-operation admission中绑定 publication、commit/tree、path、blob/LFS identity、producer result、attempt和 workflow role。Host验证 same-attempt authority与bytes closure，但不再执行 artifact materialization、共享 checkpoint推断或路径复制。Git fetch成功本身不构成 adoption或科学完成。

### 6. Offline verifier 从 internal remote 重新取得 exact bytes

Offline verification 以 bundle/receipt 中的 repository binding version、immutable publication ref、commit/tree、path 和 blob/LFS identities为输入，通过只读 service identity从 internal remote fresh fetch。Verifier 必须：

- 验证 ref ACL/immutability、commit/tree/path membership 和 LFS pointer closure；
- 读取实际 bytes，重算 digest、size、format、scientific contract和 17-role aggregate；
- 重算 producer operation/result、attempt、selection、closure、report/source links和 bundle digest；
- 拒绝 local path、ambient checkout、object cache-only proof、missing LFS bytes、alternate ref、history rewrite和 current database metadata-only proof。

网络/remote 不可用时结果是明确的 verification blocker，不得回退到 artifact storage 或 Host-local clone。Verifier 只读且不创建 publication、deliverable、closure 或 campaign decision。

### 7. Legacy AOX import使用不可采纳的独立类型与 namespace

后续历史迁移产生的 `HistoricalArtifactRef` 位于 Host-managed immutable historical namespace，并固定 `eligibility = historical_import_non_adoptable`、原 legacy id/kind/digest/lineage 和 migration receipt。它不是 `PublishedRevision`，不能转换为 `ScientificDeliverableRef`，不能进入 current selection universe，也不能满足 fresh workflow/config pin、attempt authority、scientific closure、report claim 或 cutover verifier。

拒绝规则按 typed record/namespace/validator 三层实施，而不是依赖命名约定。相同 bytes digest不改变这一结论；内容相同不等于 effect、attempt 或 provenance identity相同。

### 8. Current code不保留 artifact fallback

切换后，scientific domain/repository、AOX finalizer/evidence export、provider/HPC integration、Host projection和 evaluator只接受新的 closed refs。发现 artifact id、artifact-set digest、`HpcStageRef`、artifact storage URI或旧 bundle schema时返回 versioned stale-contract/non-adoptable error。不得自动查旧表、转换旧 id、创建 placeholder、dual-write或按 path extension猜测合同。

## Risks / Trade-offs

- [Git/LFS remote 暂时不可用会阻断 finalization 或 offline verification] → 以 immutable publication identity重试同一只读动作；不切换 locator或降低验证范围。
- [17 个文件验证在 transaction 外发生，期间 selection/authority可能变化] → transaction 内重验 immutable publication、selection head、attempt state、actor、fence和 preimage digest，漂移时零写入。
- [Git commit可包含无关文件] → `ScientificDeliverableRef` 和 bundle只授权 exact normalized paths；publication path manifest、role manifest和 policy digest共同限制消费面。
- [LFS pointer存在但对象缺失或 size 错误] → publish和 finalizer均要求 pointer/OID/size/actual bytes闭合，缺失直接阻断。
- [历史 AOX bytes与 current bytes digest相同而被误采纳] → historical ref类型、namespace、eligibility和 attempt lineage四重隔离；validator不以 digest相等推导 adoption。
- [一次性切换降低回滚便利] → 在 isolated database/remote replica完成全量 non-live qualification；activation后只做 forward repair，不重新启用 artifact writer。

## Migration Plan

1. 验证前序 changes 已提供 immutable `PublishedRevision`、Git/LFS closure、agent/executor workspace、workspace-revision job result和 revision/path handoff；确认 superseded AOX旧 campaign不可运行。
2. 新增 scientific deliverable domain/repositories、typed task evidence和 Git/LFS resolver，但保持 current scientific入口关闭；在隔离 fixture上重放 AOX 17-role positive/empty/tamper验证。
3. 改造 provider/HPC output handoff、AOX candidate/finalizer、selection/closure、evidence export、Host eval和 offline verifier，使其只生成/读取 `ScientificDeliverableRef`。
4. 运行 source-bound non-live qualification，证明 exact 17-role atomicity、same-attempt lineage、cross-attempt/historical rejection、LFS missing/tamper、task non-terminal和 no-artifact-write。
5. 在 quiescent migration window冻结所有 scientific artifact writer，确认零 active writer/process/continuation和零未结 external effect；原子提升 scientific contract epoch。不存在 dual-write窗口。
6. activation后拒绝所有旧 scientific/artifact请求。旧 rows/bytes保持冻结，只等待 `migrate-historical-artifacts-to-git-lfs`，不参与 current projection或 verifier。
7. 若 activation前资格检查失败，丢弃未启用的新 schema数据并修正后重跑；activation后禁止回退到 artifact合同，只允许修复新路径并从 immutable publication重算。
8. 本 change 完成后，新 AOX live cutover仍必须另建 change、fresh workflow/source/config pin、fresh authority和fresh roots；本 change本身不授权 live。

## Open Questions

无。产品选择已由 1A、2A、3A、4A、5A、6B 固定；剩余工作均为实现与验收，不构成可改变上述边界的开放产品问题。
