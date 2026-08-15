## 1. 精确 public-cutover receipt 与 writer-freeze 门禁

- [ ] 1.1 新增 migration admission，要求 `cut-over-workspace-public-interfaces` 的精确 completion receipt、已激活的 `file_workspace_public@1` epoch、catalog/schema/build identity 与 zero-legacy-public-surface proof；不得用 flag、推断的 deployment state 或部分验收替代。
- [ ] 1.2 在 inventory 开始前重新验证 current report、research、task、protocol、controlled-operation、sandbox、scientific、HPC、Host、CLI、SDK 与 UI 路径均无法创建或修改 artifact record、reference、staging value 或 storage object。
- [ ] 1.3 停止 Host mutation/runtime consumer、continuation、sandbox/execution worker、runner callback 与剩余 migration writer，并签发精确 quiescence 和 writer-freeze receipt，绑定 owner、process、lease/fence、unsettled effect、database high-watermark 与 storage generation。
- [ ] 1.4 在迁移前创建并验证一致的 database 与 legacy-storage backup/snapshot identity；任何 backup mismatch、post-freeze write、新发现的 writer 或 unsettled effect 都使准入失效，且不授权 Git write 或 source deletion。

## 2. 不可变全系统 inventory

- [ ] 2.1 构建 schema inventory，覆盖每个 artifact table、row identity、column、foreign key、trigger、index、repository field 与含 reference 的 table，包括 report、research、task、protocol、controlled-operation、sandbox、scientific 和 HPC owner。
- [ ] 2.2 构建 storage inventory，覆盖每种已声明 legacy storage scheme、file、canonical tree member、blob、`engine-document://` alias target、object identity、byte range、digest、size、owner 与 lineage；不得把 metadata row 当作 byte proof。
- [ ] 2.3 将 schema FK、source/repository symbol 与 field reference、storage scan 交叉核对为精确 identity-set union；duplicate、alias、orphan、missing byte、unsafe locator、unsupported scheme 与 conflicting digest 必须成为显式 blocker，不得跳过。
- [ ] 2.4 持久化不可变且带版本的 inventory manifest，绑定 database/storage snapshot identity、high-watermark、writer-freeze receipt、expected row/object/byte/reference identity set、per-owner count 与 deterministic migration-unit assignment。

## 3. 确定性 unit 与真实 byte source resolution

- [ ] 3.1 将 frozen inventory 划分为 deterministic project/session migration unit，具有稳定 ordering、unit id、target repository binding/policy、namespace 与 retry identity；拒绝 ambiguous 或 cross-owner assignment。
- [ ] 3.2 为每种已清点 storage scheme 与 canonical tree 实现 allowlisted、path-safe reader，将 alias 解析到唯一 frozen source object，并拒绝 traversal、symlink escape、mutable remote target 与 ambient-path fallback。
- [ ] 3.3 读取每个 expected file/tree member 的每一个实际 byte，并重算 legacy digest、size、canonical tree membership 与 lineage；任一 missing、corrupt、short、conflicting 或 unreadable byte 都使整个 unit 失效。
- [ ] 3.4 在 Host-owned append-only historical namespace 中推导 deterministic normalized target path，并拒绝 path collision、大小写/Unicode normalization conflict、reserved path 或任何会覆盖已有 immutable ref 的 mapping。

## 4. 不可变 Git/LFS 写入与 fresh read-back

- [ ] 4.1 对每个 source object 应用 pinned repository 与 Git LFS policy，保留 canonical tree，并根据 content/policy 而非 legacy kind 或 filename 推断选择 Git blob 或 LFS object。
- [ ] 4.2 将每个完整 unit 写入其 deterministic immutable historical commit/tree/ref，并包含 mapping manifest；不得创建 `PublishedRevision`、current workspace handoff、scientific deliverable、report publication 或 external-job projection。
- [ ] 4.3 从空 Git/LFS object cache 的 fresh clone/fetch 验证每个 target：读取 actual bytes，并核对 remote ref、commit、tree、normalized path、blob 或 LFS pointer/OID/size、canonical digest 与 unit manifest。
- [ ] 4.4 处理 remote-write/database-receipt 中断时，将 immutable target 视为 non-current orphan candidate；exact idempotent retry 时重新读取并匹配，若 target 冲突则拒绝，且不得删除、覆盖或另选新 ref。

## 5. 历史 mapping 与完整 reference rewrite

- [ ] 5.1 新增不可变且带版本的 `HistoricalArtifactRef`/mapping model，绑定每个 original id、kind、digest、owner、lineage、source identity、unit、historical commit/tree/path、Git blob 或 LFS OID/size、verification result 与永久 non-adoption eligibility。
- [ ] 5.2 对 bytes 相同但 owner、attempt、role 或 reference graph 不同的 legacy identity 保留独立 mapping，同时允许底层复用 content-addressed Git/LFS object。
- [ ] 5.3 为每个仍存续的 report、research、task、protocol、controlled-operation、sandbox、scientific 与 HPC FK/reference 生成精确 rewrite plan；按用途选择正确的 typed revision/path/result/scientific/historical identity，不得使用单一通用 replacement type。
- [ ] 5.4 完成 target read-back 后，原子重新验证 source row version、writer fence、inventory generation 与 target identity，再在单个 transaction 中写入全部 mapping、全部存续 typed reference replacement 和一个 per-unit receipt。
- [ ] 5.5 若任何 expected FK/reference 缺失、重复、变化、未类型化或未解析，则以零 partial rewrite 拒绝该 unit；不得以 `NULL`、empty value、metadata-only pointer、placeholder、synthetic result 或 silent skip 替代。

## 6. AOX 历史隔离与只读重现

- [ ] 6.1 将每个 superseded AOX campaign、attempt、selection、occurrence、disposition、authority、root、deliverable、bundle、receipt 与 mapping 标记为 `historical_import_non_adoptable`，并在 unit manifest 中绑定 exact supersession decision。
- [ ] 6.2 将 AOX historical verifier 实现为 immutable historical Git/LFS ref 与 original lineage 的纯只读 consumer；它可以重现 frozen fact，但不得创建 current publication、deliverable、selection、closure、task evidence、receipt、campaign decision 或 GO/NO-GO。
- [ ] 6.3 增加 admission barrier，证明 digest 相同的 historical bytes 不能满足 fresh workflow/source/config pin、attempt authority、selection/adoption、report claim、final bundle、fault criterion、campaign reducer、cutover evidence 或 live authority。

## 7. 逐 unit receipt、retry 与 freeze monitoring

- [ ] 7.1 定义 deterministic per-unit receipt，包含 inventory/source version、expected/migrated identity set、actual-byte total、target commit/tree/ref 与 Git/LFS closure、mapping/reference rewrite、verifier identity、non-adoption result 和 zero-post-freeze-write proof。
- [ ] 7.2 使 exact completed-unit replay 保持只读且不改变 identity；incomplete-unit replay 只有在重新验证相同 source inventory 与 immutable target 后才可恢复，且不得产生 duplicate mapping、ref mutation 或改变 unit boundary。
- [ ] 7.3 在所有 unit 执行期间持续将 database/storage high-watermark 与 writer-fence event 同 frozen inventory 比较；任何 post-freeze write 或 inventory drift 都使受影响 unit 失效并阻止 global receipt。
- [ ] 7.4 对 missing/corrupt source，只允许从已验证 backup 恢复同一 authoritative identity 并重跑受影响 unit；禁止 placeholder byte、alternate locator、partial success 或 source deletion。

## 8. 全局 exact-set receipt 与强制 no-delete 停点

- [ ] 8.1 使用 pinned verifier code/config identity，对每个 unit、historical ref、Git blob、LFS object、actual byte、mapping、lineage、rewritten reference 与 AOX non-adoption proof 运行独立 empty-cache verifier。
- [ ] 8.2 仅当 row、object、byte、reference、unit、commit、blob、LFS object 与 lineage 的 expected/migrated identity set 精确相等，且全部 per-unit/read-back proof 通过时，签发唯一 immutable global `HistoricalArtifactMigrationReceipt`。
- [ ] 8.3 要求 global receipt 证明 missing、corrupt、conflicting、skipped、placeholder、orphan、unresolved-reference、post-freeze-write 与 AOX-adoption item 均为零；只有 count equality 而没有 identity-set equality 时不得完成 change。
- [ ] 8.4 签发 receipt 后立即停止本 change，所有 legacy artifact table、FK、trigger、index、source blob/object、storage root 与 migration-only reader 必须仍存在且保持冻结；增加 hard guard，仅允许 `remove-artifact-control-plane-and-storage` 在精确重新验证 receipt 后执行删除。
- [ ] 8.5 支持从空 Git/LFS cache 独立重新验证 immutable global receipt；不得查询 artifact byte 作为证明，也不得修改 receipt、mapping、source 或 current product state。

## 9. 聚焦验收、架构文档与完成 receipt

- [ ] 9.1 新增并运行聚焦 inventory/unit/repository 测试，包括专用 historical-migration suite 与 `packages/openzyme-core/tests/test_migrations.py`，覆盖每种 storage scheme、canonical tree、alias、byte-range/digest failure、path collision、deterministic unit、idempotent remote orphan 与 source-preservation case。
- [ ] 9.2 新增并运行聚焦 reference-graph 测试，覆盖每个 report、research、task、protocol、controlled-operation、sandbox、scientific 与 HPC FK/ref rewrite，以及 transaction rollback、unresolved-ref blocker、exact-set equality 与 post-freeze-write invalidation。
- [ ] 9.3 新增并运行 empty-cache Git/LFS read-back 与 AOX negative-adoption 测试，证明 actual-byte closure、immutable namespace behavior、historical-only verification、没有 current projection/evidence，且不授权 live 或 GO/NO-GO。
- [ ] 9.4 更新 `docs/OpenZyme架构设计.md` 及相关 `docs/v3/` control-plane、persistence、failure-recovery、compatibility-sunset、execution-pipeline 与 operator migration 文档，说明 inventory、freeze、real-byte Git/LFS migration、完整 reference rewrite、exact-set receipt、non-adoption 与强制 no-delete 边界。
- [ ] 9.5 对本 change 及所有已声明 predecessor 运行 strict OpenSpec validation，再运行 `./scripts/check-mainline.sh`；记录 exact source/config revision、command、result、排除的 live gate、backup/inventory identity 与任何 environment-owned blocker，不得放宽 receipt。
- [ ] 9.6 仅当 immutable change completion receipt 绑定精确 `HistoricalArtifactMigrationReceipt`、focused/mainline result、documentation digest、source-preservation scan、zero current writer 与 zero deletion action 后才可签发；该 receipt 本身不得授权 physical removal。
