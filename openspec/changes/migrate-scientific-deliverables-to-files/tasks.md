## 1. 精确前序 receipt 与非 live 门禁

- [ ] 1.1 新增准入验证器，要求 `supersede-aox-hmm-artifact-cutover`、`migrate-research-report-and-task-handoffs-to-files`、`execute-hpc-jobs-from-workspace-revisions`、`publish-and-sync-workspace-revisions` 和 `support-git-lfs-work-products` 的精确完成 receipt 及其声明的 contract/schema identity；启用科学文件 writer 前，拒绝任何缺失、不匹配、已 superseded 或未经验证的 receipt。
- [ ] 1.2 根据 supersession receipt 验证所有 legacy AOX campaign、attempt、authority、selection、occurrence、root 和 deliverable 均已冻结且不可运行；若任何 legacy authority 或 continuation 仍可执行，则记录封闭 blocker。
- [ ] 1.3 新增 source-bound activation preflight，证明 immutable publication、Git LFS closure、revision-bound HPC result 和 revision/path research handoff 均可用，同时所有 current scientific artifact writer 仍保持禁用。
- [ ] 1.4 使本 change 的准入与完成路径明确拒绝 AOX live launch、fresh live authority、provider execution、HPC submission 或 campaign GO/NO-GO；本 change 只允许运行 fixture 与 offline verification。

## 2. 科学交付物领域模型、schema 与 repository

- [ ] 2.1 新增不可变且带版本的 `ScientificDeliverableRef`、bundle manifest 和 validation receipt domain model，绑定 repository policy/version、publication/ref、commit/tree、normalized path、Git blob 或 LFS OID/size、content digest、role/format、producer operation/result、attempt、sealed selection、workspace generation 与 publisher。
- [ ] 2.2 为 scientific deliverable ref、exact role bundle 和 validation receipt 新增 forward schema migration，落实唯一性、不可变性、attempt/selection/publication ownership、normalized-path 与 Git-versus-LFS identity constraint；不得新增可空的 artifact compatibility column。
- [ ] 2.3 实现以原子方式创建和读取新 identity 的 repository；幂等重放返回完全相同的 identity，并拒绝 identity mutation、cross-project publication、cross-attempt lineage、stale selection head 或冲突的 idempotency payload。
- [ ] 2.4 用 typed deliverable、bundle、selection、closure 和 verification reference 替换 scientific task evidence 与 projection payload；artifact id、artifact-set digest、storage URI 和 `HpcStageRef` 不得再作为有效的 current evidence。

## 3. 不可变 Git/LFS 解析与原子定稿

- [ ] 3.1 实现只读 scientific resolver，仅解析 pinned internal `PublishedRevision` 与 normalized repository-relative path，并验证 commit、tree membership、Git blob 或 LFS pointer/OID/size、actual bytes 和 canonical digest；不得回退到 ambient checkout 或 Host-local path。
- [ ] 3.2 根据 publication identity、exact path/role manifest、actual-byte validation、producer lineage、attempt、sealed selection、actor、fence 和 mutation authority 构造 deterministic validation preimage，并提供稳定 digest 供 transaction-time revalidation。
- [ ] 3.3 实现短事务 finalization：插入完整 deliverable set、bundle 和 validation receipt 前，重新验证 immutable publication identity、selection head、attempt state、actor、fence、mutation authority 与 preimage digest。
- [ ] 3.4 当 path、byte、LFS、format、role、selection、attempt、fence 或 authority 发生任何漂移时，保证零 partial record；exact replay 返回原始 ref 和 receipt，且不读取或写入 artifact storage。

## 4. AOX 精确 17-role 文件 bundle

- [ ] 4.1 将 active AOX deliverable contract 编码为封闭、带版本且恰含 17 个命名 role 的 manifest；每个 role 具有唯一 normalized path 与显式 format contract，并拒绝缺失、额外、重复、大小写/Unicode 冲突或从扩展名推断的 role。
- [ ] 4.2 重构 AOX candidate、filter 与 conditional-empty validation，使其读取精确的 published Git/LFS bytes，并要求声明的 typed empty-result contract 与 receipt；不得以缺失文件、零字节文件、placeholder 或 sentinel 表达空结果。
- [ ] 4.3 重构 AOX bundle finalizer，在一次原子提交 17 个 ref 和一个 deterministic receipt 前，验证全部 17 个 role、source revision、producer operation/result、attempt、sealed selection、byte contract 与 aggregate manifest。
- [ ] 4.4 重构 AOX evidence export、public product closure 与 architecture qualification input，使其消费 `ScientificDeliverableRef` identity 和实际 immutable bytes，不得重建 artifact set 或翻译 legacy bundle schema。

## 5. 选择、occurrence、authority 与 task 语义

- [ ] 5.1 保留由 controlled operation 与被覆盖的 execution/sandbox occurrence 推导出的完整 attempt-scoped selection universe，并为每个 success、failure、supersession、abandonment 与 unknown-effect occurrence 保留显式 disposition。
- [ ] 5.2 将 adoption 绑定到精确 attempt、operation、terminal immutable result、role、selection head、reason、idempotency identity、effect certainty、actor、fence 与 mutation authority；拒绝 cross-attempt、cross-campaign、probe、fault 和 historical-import candidate。
- [ ] 5.3 保证 `ScientificDeliverableRef` 位于已 sealed selection 与 adopted producer chain 的下游；文件存在、publication、17 个 ref、bundle validation 或 offline verification 均不得机械地 seal selection、close attempt、调用 `task.finish`、发布 report 或产生 GO/NO-GO。
- [ ] 5.4 仅允许通过已验证的 immutable publication 与 exact path 消费同一 attempt 的跨 workspace 输出；不得把 private producer path materialize 到 artifact storage，也不得根据 bytes 相同推断 adoption。

## 6. 生产方、Host 公开面与单向激活

- [ ] 6.1 改造 research/provider 与 revision-bound HPC 的科学输出 handoff，使其返回 scientific resolver 可验证的 immutable publication/path/result identity；保留 external operation/job/result lineage，并明确该合同不包含 `expected_outputs`。
- [ ] 6.2 改造 Host service、API schema、projection、evaluator fixture 与 report link，使其在现有 authorization 和 bounded projection 规则下，仅暴露 current scientific file ref、role bundle、selection/closure fact 与 validation receipt。
- [ ] 6.3 对 artifact id、artifact kind、artifact-set digest、storage URI、`HpcStageRef`、旧 AOX bundle version、private ref、dirty path 和 unknown publication 返回带版本的 stale-contract 或 non-adoptable error；不得 lookup、conversion、创建 placeholder、dual-write 或 parser fallback。
- [ ] 6.4 实现 quiescent activation：证明 active scientific artifact writer/process/continuation 为零且没有 unsettled external effect，原子推进 scientific contract epoch，并保留冻结的 legacy row/byte 等待后续 historical migration，不得删除。
- [ ] 6.5 使 activation 后的恢复仅能沿 file/revision contract 前向修复；即使 Git/LFS 不可用，也不得重新启用 artifact writer 或旧 verifier，并要求针对同一 immutable publication identity 重试。

## 7. 离线验证与永久历史不可采纳

- [ ] 7.1 实现 offline verifier：从空 Git/LFS object cache 开始，fresh-fetch pinned immutable ref，读取每个声明的 byte，并重算 path/tree/blob 或 LFS identity、digest/size/format、17-role manifest、producer lineage、selection、closure、report link 与 bundle digest。
- [ ] 7.2 将 `HistoricalArtifactRef` 定义为独立的 Host-owned immutable historical namespace，携带 legacy identity/lineage 与 `historical_import_non_adoptable`；禁止转换为 `PublishedRevision` 或 `ScientificDeliverableRef`，并从 current projection 与 selection universe 中排除。
- [ ] 7.3 为 digest 相同的 historical AOX bytes 增加负向验证：冻结的 selection、occurrence、attempt、authority、root 与 receipt 仍可检查，但不得满足 fresh workflow/source/config pin、scientific closure、report claim、fault criterion、cutover evidence 或 GO。
- [ ] 7.4 生成绑定 source/config/test digest 的 non-live qualification result，证明 exact 17-role atomicity、typed empty result、same-attempt lineage、cross-attempt/historical rejection、missing/tampered LFS rejection、显式 task terminality 与零 artifact write。

## 8. 聚焦验收、架构文档与完成 receipt

- [ ] 8.1 在 `packages/openzyme-core/tests/test_scientific_attempts.py`、`test_scientific_workflow_contracts.py`、`test_scientific_attempt_lifecycle_architecture.py` 和 `test_migrations.py` 中新增并运行聚焦 domain/repository/migration 测试，覆盖 immutable ref、transaction drift、idempotency、occurrence coverage、selection、closure、task non-terminality 与零 artifact write。
- [ ] 8.2 在 `apps/openzyme-host-api/tests/test_aox_bundle_finalizer.py`、`test_aox_cutover_evidence.py`、`test_aox_scientific_contract.py`、`test_aox_public_product_closure.py` 和 `packages/openzyme-pipeline/tests/test_aox_exact_finalization.py` 中新增并运行聚焦 AOX/Host/pipeline 测试，覆盖 exact 17 role、conditional-empty、actual-byte/LFS verification、lineage 与 historical non-adoption；不得运行 live marker。
- [ ] 8.3 更新 `docs/OpenZyme架构设计.md` 以及相关 `docs/v3/` control-plane、capability-engine、public-interface、failure-recovery 和 execution-pipeline 文档，将 file/revision scientific truth、显式 selection/closure、historical non-adoption、禁止 artifact fallback，以及未来独立 live-cutover authority 边界写为规范。
- [ ] 8.4 对本 change 及其 dependency change 运行 strict OpenSpec validation，再运行 `./scripts/check-mainline.sh`；记录 command、exact revision、result、跳过的 live gate 及任何 environment-owned blocker，不得降低验收标准。
- [ ] 8.5 仅当前序 identity、已激活的 scientific contract epoch、focused/mainline result、documentation digest、non-live qualification 与 zero-artifact-write proof 全部匹配时，签发 immutable change completion receipt；明确声明该 receipt 不授予 AOX live authority 或 GO/NO-GO。
