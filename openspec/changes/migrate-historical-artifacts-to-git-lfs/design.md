## Context

用户选择 6B：本轮最终物理删除 artifact tables、FKs、triggers、storage和 runtime code。删除前必须证明每一个仍需保留的 legacy row、实际 bytes、lineage与 foreign reference已经迁入 immutable Git/LFS history。当前 legacy来源不只有普通 blob文件，还包括 sealed source tree、`engine-document://` alias、provider/research evidence、report linkage、sandbox materialization/run、controlled-operation input/result、scientific materialization/selection和 AOX fixed deliverables。只迁 metadata或只保留原 digest都会在删除 storage后失去可验证内容。

本 change 位于 current writer/public/scientific cutover之后、physical removal之前。它只做历史迁移和删除前证明，不删除旧 tables、FKs、triggers或 source objects。迁移期间所有 artifact writer必须已冻结；不存在 dual-write，也不允许把迁入历史的 bytes提升为 current publication或科学 evidence。

## Goals / Non-Goals

**Goals:**

- 完整枚举 legacy artifact rows、storage objects和所有 inbound/outbound lineage/FK consumer，形成冻结的 migration inventory。
- 按 project repository binding与 session建立 Host-managed immutable historical-import Git refs，并用 Git blob或 Git LFS保存真实 bytes。
- 对每个对象执行 source read/digest verification、Git/LFS write、fresh read-back和 digest/size/tree verification。
- 把仍需保留的 control-plane references改写为 typed revision/path/result/scientific/historical refs，并生成可重复验证的一次性 migration receipt。
- 为 superseded AOX和其他 scientific history建立机器可验证的 non-adoptable边界。
- 为下一 change提供不可绕过的 complete-coverage deletion gate。

**Non-Goals:**

- 不删除、truncate或 vacuum artifact tables、FKs、triggers、indexes、blob roots或任何 source object。
- 不创建 current `PublishedRevision`、`ScientificDeliverableRef`、report publication、task evidence、fresh attempt、selection、closure或 GO/NO-GO。
- 不重新启用 frozen artifact writer，不 dual-write Git/LFS与 legacy storage。
- 不用 placeholder、空文件、metadata-only row、silent skip、digest信任或 extension推断代替实际 bytes。
- 不运行 provider、HPC、MICU、Chrome或任何 live scientific action。

## Decisions

### 1. 使用离线、fenced、inventory-first migration，而不是在线 lazy read-through

迁移只在 Host current product和所有 legacy artifact writers停止后运行。Operator首先取得数据库与storage一致性快照，并建立 closed `HistoricalMigrationInventory`：

- database schema/migration version、project binding version和 inventory generation；
- artifact row count、每个 legacy artifact id/kind/owner/session/task/lane/run/operation/attempt、storage scheme、declared digest/size和metadata digest；
-所有 materialization、report、research、sandbox、controlled-operation、scientific、HPC和 task/protocol evidence引用；
- storage root identity、object locator摘要、source high-watermark和 writer/quiescence receipt；
- duplicate locator/content groups、orphan rows、orphan objects和 unresolved references。

Inventory完成后以 database trigger和 migration authority fence拒绝任何 artifact insert/update/delete和 storage publication。若快照后出现 row/object变化，整个受影响 migration unit失效。拒绝 lazy migration，是因为读取到一个 legacy id时才搬运无法证明 orphan objects、未访问 rows或跨表 lineage已经闭合，也不能安全授权后续 drop。

### 2. Migration unit按 repository binding与 session闭合

默认 migration unit是一个 pinned project repository binding version下的单一 session；project-scoped但无 session owner的对象进入显式 project migration unit。每个 unit有 deterministic id，绑定 inventory generation、完整 row/ref/object manifest digest和目标 historical ref namespace。

一个 unit必须 all-or-nothing：任一 source missing、digest mismatch、unsafe path、unsupported storage scheme、Git/LFS conflict、reference ambiguity或 read-back failure都会使整个 unit为 failed，且不写 complete receipt。已写入 internal remote的不可变对象可作为 incomplete orphan保留供相同 unit重试，但不能被 current product读取或被 deletion gate计为完成。

### 3. Historical Git layout显式保留 legacy身份但不成为 current publication

每个 unit发布到 Host-owned、append-only、禁止 force-update/delete的 internal namespace。Commit tree包含：

- versioned unit manifest，记录 inventory/root/parent、source database和 binding identity；
- 每个 legacy对象的 normalized payload path或 canonical source-tree subtree；
- mapping manifest，绑定 original artifact id/kind/digest/owner/lineage到 exact commit/tree/path、Git blob或 LFS OID/size；
- reference manifest，记录每个原 FK/evidence ref迁移到的 typed target；
- verification summary与 non-adoption classification。

大文件是否进入 LFS严格服从 pinned repository LFS policy；迁移器不得自动修改 policy或用外部 CAS。目录/source-tree对象以 Git tree和逐文件 manifest保存，不能压成未声明 archive后只比较外层 digest。`engine-document://` 等 alias必须解析并读取其真实 canonical content；仅复制 URI或 document id不算迁移 bytes。

这些 refs使用 `HistoricalImportRef`/`HistoricalMigrationReceipt`，而不是 `PublishedRevision`。它们不进入 team publication namespace、不出现在 current workspace projection，也不能被 `workspace.publish`、handoff或 scientific validator消费。

### 4. 每个 bytes对象执行双向实读验证

迁移器必须对每个 inventory entry执行：

1. 按 allowlisted legacy storage scheme打开真实 source object，拒绝 symlink/path escape/Host root drift，并读取全部 bytes或 canonical tree。
2. 重算 legacy contract要求的 file/tree/content digest和 size，与 row、metadata和所有引用中的 digest比较。
3. 写入目标 Git tree或 LFS object，提交到 deterministic historical ref；若目标 ref已存在，只接受 exact manifest/commit/object identity相同的 idempotent replay。
4. 通过 fresh clone/fetch和 LFS download从 internal remote重新读取目标，不使用 migration process的 source buffer或 local object cache作为唯一证明。
5. 重算 Git blob/tree、LFS OID/size、content digest和 mapping manifest；任一不一致使 unit失败。

缺失 source bytes时只能从已授权的原始备份恢复后重新开始同一 unit。不得创建 placeholder、空文件、metadata-only pointer或标记“已知缺失但视为成功”。

### 5. Reference rewrite使用 typed owner，且不留下 artifact FK

目标 Git/LFS bytes验证完成后，迁移器在一个 database transaction中：

- 重验 inventory generation、writer freeze和所有 source row/ref versions；
- 为 surviving report/research/task/protocol/controlled-operation/scientific history写 exact `HistoricalImportRef`、revision/path/result或 domain-specific historical ref；
- 更新所有需要保留的 consumer，使其不再依赖 artifact FK、storage URI或 catalog lookup；
- 写 immutable per-unit receipt，绑定 source inventory、target ref/commit/tree/LFS closure、mapping/reference manifest和 verifier digest。

若 transaction失败，legacy source保持不变，目标 historical ref保持 incomplete/non-current；重试必须复用相同 deterministic unit identity。不得先清空 FK再补 mapping，也不得把 unresolved引用改为 `NULL`以通过 gate。

### 6. Superseded AOX history是永久 non-adoptable

所有 superseded AOX/c001/旧 campaign bytes、receipts、authority、roots、attempt/selection/bundle和科学结果进入专用 historical classification：`historical_import_non_adoptable`。Mapping必须保留 original campaign/attempt/role/digest和 supersession decision，但明确：

- 不是 fresh workflow/source/config pin；
- 不拥有 current attempt authority、selection、closure或 effect adoption；
- 不能构造 `ScientificDeliverableRef`、current report evidence或 cutover bundle；
- 相同 bytes/digest也不能跨 namespace或 attempt adoption。

AOX historical verifier可按原 schema从 historical Git/LFS bytes重放只读验证，但输出只解释冻结事实，不生成 current validation receipt或 GO。

### 7. 全局 migration receipt是 removal change的硬前置

所有 units完成后生成唯一 immutable `HistoricalArtifactMigrationReceipt`，至少绑定：

- inventory generation与数据库/storage snapshot identity；
- expected/migrated row、object、byte、reference和 unit counts；
-每个 unit receipt、target commit/tree/ref和 Git/LFS closure aggregate；
- zero missing/corrupt/conflicting/skipped/placeholder/unresolved-reference facts；
- zero post-freeze writes和 writer-quiescence proof；
- AOX non-adoption aggregate；
- independent read-back verifier code/config digest和通过结果。

Global receipt只有在 exact set equality成立时产生。Count相等但 identity set不同、存在 orphan object、未映射 FK或未验证 LFS object都阻止完成。下一 change只能消费该 exact receipt；不能以 operator flag、部分成功或重新扫描后的“看起来为空”替代。

## Risks / Trade-offs

- [legacy storage中已有缺失或损坏 bytes] → unit失败并保留 source；只能从权威备份恢复后重跑，绝不 placeholder/silent skip。
- [迁移时间长且 Git/LFS空间放大] → 按 session unit分批、复用内容相同的 Git/LFS objects，但每个 legacy identity仍保留独立 mapping；删除 gate等待全部 units。
- [remote write成功而 DB receipt失败] → target namespace不可变且 non-current；相同 unit幂等重读验证后再提交 transaction，不删除或换 ref。
- [FK graph遗漏导致 drop后历史断链] → inventory从 schema FKs、repository symbol/field audit和 storage scan三路求并集，global receipt要求 reference set equality。
- [历史 AOX bytes被误认为 fresh evidence] → distinct type/namespace/eligibility、supersession binding和 current validator negative tests共同阻断。
- [冻结时间过长] → current product已在前序 changes完全脱离 artifact writer；迁移不以重新开放旧 writer缩短窗口。

## Migration Plan

1. 验证前序 current writer、scientific和 public-surface cutover全部完成；停止 Host runtime，等待 session/execution/continuation/sandbox/mutation writers和外部 effect达到可证明 quiescence。
2. 建立数据库与 legacy storage一致性备份，生成 schema/storage/FK inventory和 high-watermark；安装 writer freeze并证明后续写入被拒绝。
3. 在 dry-run模式解析每个 storage scheme和 reference graph，输出 exact unit manifests；任何 unsupported locator、orphan或 digest conflict在写 Git前阻断。
4. 按 deterministic unit迁移真实 bytes到 immutable Git/LFS historical refs，逐对象 fresh read-back验证；失败 unit保持 incomplete并修复 source后重跑。
5. 对通过的 unit原子改写 surviving references并写 per-unit receipt；持续重验无 post-freeze write和 inventory drift。
6. 所有 unit完成后，从空 Git object cache的独立 verifier重放全部 refs/LFS bytes/lineage/AOX non-adoption，生成 global receipt。
7. 本 change到此停止：旧 tables、FKs、triggers、indexes、source blobs和 runtime migration reader全部保留且 frozen；不得提前删除。
8. 若 global receipt前发生失败，恢复或修复 source并重跑相同 unit；若 receipt已生成，后续只允许创建绑定新 inventory generation的显式补充 migration，不得修改既有 immutable receipt。
9. 仅当 `remove-artifact-control-plane-and-storage` 验证 exact global receipt与当前 schema/storage inventory仍一致时，才进入物理删除。

## Open Questions

无。6B 已固定“先完整迁移并验证，再由下一 change物理删除”；缺失 bytes、冲突或未映射 lineage均是 migration blocker，不是允许降级的产品选择。
