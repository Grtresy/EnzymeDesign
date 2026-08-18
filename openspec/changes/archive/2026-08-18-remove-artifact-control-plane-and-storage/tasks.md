> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 0. 当前 release removal gate

- [x] 0.1 重读并绑定直接前置 `historical_artifact_migration_release_gate@3`、真实 inventory/global receipt、standalone verification 与 source-preservation proof，拒绝用空查询或 fixture 替代。
- [x] 0.2 按用户授权将保留审计文件名的 gate 升级为 `artifact_subsystem_removal_release_gate@3`，仅授权解析出的 local deployment 执行 final-schema rebuild 与 receipt-bound legacy storage deletion。
- [x] 0.3 在 OpenSpec operator 目录实现独立 offline executable、13-change exact receipt 校验、historical exact-set 校验、quiescence/backup 校验、deterministic dry-run 与 immutable receipt；不注册到 normal runtime/tool discovery。
- [x] 0.4 明确 mutation 前必须重验全部 receipt/inventory/dry-run，禁止不同或未指定 deployment、任何 current repository-service Git/LFS 删除、`--force`/manual override 与 provider/HPC/network/live effect。

## 1. 精确 13-change 与历史迁移 receipt 门禁

- [x] 1.1 实现 removal manifest，依次要求 `supersede-aox-hmm-artifact-cutover`、`establish-project-repository-bindings`、`establish-agent-capability-leases`、`provision-independent-agent-git-workspaces`、`publish-and-sync-workspace-revisions`、`support-git-lfs-work-products`、`migrate-research-report-and-task-handoffs-to-files`、`provision-isolated-executor-hpc-workspaces`、`execute-hpc-jobs-from-workspace-revisions`、`migrate-scientific-deliverables-to-files`、`replace-sandbox-artifact-boundaries-with-files`、`cut-over-workspace-public-interfaces` 与 `migrate-historical-artifacts-to-git-lfs` 的精确 completion/acceptance identity。
- [x] 1.2 验证每个 prerequisite receipt 的 exact version、source/schema/contract identity、activation epoch、acceptance result、transitive receipt link 与 non-superseded status；feature flag、deployed binary、empty query、backup 或 operator assertion 均不等价。
- [x] 1.3 对照 current database/storage inventory generation、snapshot identity、row/object/byte/reference identity-set equality、全部 unit receipt、zero unresolved/post-freeze write 与 AOX non-adoption，重新验证精确 `HistoricalArtifactMigrationReceipt`。
- [x] 1.4 从空 Git/LFS object cache fresh-fetch 并回读 receipt 指定的每个 historical target；授权任何 DDL 前，重新核对 commit/tree/path/blob 或 LFS OID/size、actual bytes、digest、lineage 与 mapping。
- [x] 1.5 若 receipt 缺失/不匹配、inventory drift、target 不可读、identity set 不完整、unknown absence 或 writer fence stale，则在 mutation 前 fail closed；不得提供 `--force`、empty-count、current-code-unused 或 manual-override 路径。

## 2. 专用 offline removal authority 与 quiescence

- [x] 2.1 新增专用 offline removal executable 与短期 migration authority；它们不得出现在 normal Host/runtime/tool discovery 中，并且是唯一允许执行 gated schema rebuild 与 legacy-storage deletion 的 caller。
- [x] 2.2 要求进入 maintenance mode，并停止 Host、CLI mutation consumer、session/runtime drain、continuation、sandbox/execution worker、runner callback 与 UI write；签发覆盖 owner、process、lease/fence、mutation 与 unsettled external effect 的 quiescence receipt。
- [x] 2.3 创建并独立验证绑定 exact removal manifest 的 database 与 legacy-storage backup；文档明确 recovery 只能恢复到隔离 legacy environment，绝不把 artifact state 重新引入 current runtime。
- [x] 2.4 实现 non-mutating dry run，输出 exact final schema manifest、surviving-table rebuild/copy plan、typed replacement coverage、drop set、storage deletion identity、expected byte 与 startup/removal ledger transition。
- [x] 2.5 获取 DDL authority 前立即重新验证 13 个 receipt、historical receipt、backup、quiescence、writer fence、inventory 与 dry-run digest；出现任何 drift 时释放 authority 且不执行 mutation。

## 3. SQLite rebuild-and-copy 与 artifact schema 删除

- [x] 3.1 定义 final SQLite schema manifest，并清点当前含有 artifact column、FK、trigger dependency、index dependency 或 artifact-derived constraint 的每个 surviving table，以及对应的 exact typed file/revision/job/result replacement。
- [x] 3.2 对每个 surviving table 实现到 final typed schema 的 rebuild-and-copy，不得保留 nullable legacy column 或仅执行局部 `DROP COLUMN`；只复制 replacement identity 与 historical migration receipt 匹配的 row。
- [x] 3.3 在交换 table name 前，为每个 rebuilt table 验证 old-versus-new row 与 primary-key identity set、typed replacement ref、required value、foreign key、unique/check constraint、index 与 canonical row digest。
- [x] 3.4 在一个 transaction 中交换全部已验证 surviving table，并物理 drop artifact table、artifact column/FK、artifact-only trigger/index、materialization/publication/scientific-artifact structure 与 artifact writer bookkeeping。
- [x] 3.5 任何 copy、identity-set、constraint、FK、digest、schema-manifest 或 receipt mismatch 都应回滚整个 DDL transaction，使 deployment 保持 blocked 且 pre-removal database 完整。
- [x] 3.6 提交后运行 `foreign_key_check`、final schema-manifest comparison、row/key/digest reconciliation 与精确扫描，证明 artifact table、column、FK、trigger、index 和 writer category 均为零。

## 4. 受 receipt 约束的 legacy storage 删除

- [x] 4.1 仅当 final-schema transaction 与 post-DDL verification 成功，且 exact historical receipt 和 removal manifest 仍有效时，才允许 storage deletion；gate、dry run 或 schema rollback 期间绝不删除 source object。
- [x] 4.2 直接从 frozen receipt inventory 解析 explicit allowlisted legacy root 下的每个 deletion target，并验证 object identity/digest/size、real path containment 与 non-symlink status；不得使用 glob、ambient environment 或 unresolved locator。
- [x] 4.3 在幂等 deployment `LegacySubsystemRemovalReceipt` 中记录 `expected`、`deleted`、`already_absent`、byte、root 与 error identity set；只有同一 historical receipt 已证明 exact source identity 及其当前 absence 时，才接受 `already_absent`。
- [x] 4.4 文件系统部分删除时，保留 final schema，将 removal 标记为 incomplete，阻止 normal startup，并只允许对 receipt 中精确剩余 identity 重试；不得重建 artifact table、扩大 root 或把 unknown absence 重新解释为成功。
- [x] 4.5 删除后重新扫描所有 allowlisted legacy root、database structure、storage marker 与 removal ledger，要求 residual artifact object/structure 精确为零，且 expected-versus-deleted/already-absent identity set 精确相等。

## 5. Runtime、domain、tool、SDK、API 与 UI 物理删除

- [x] 5.1 删除 `ArtifactKind`、`SessionArtifactRecord`、artifact repository/service、`ArtifactBoundaryService`、artifact mutation writer、artifact evidence ref、artifact projection/event、materialization/publication helper，以及暴露它们的全部 current package export 或 import。
- [x] 5.2 从 report、research、task、protocol、controlled-operation、sandbox 与 scientific runtime path 删除 artifact field、FK、callback、alias 与 fallback branch，同时保留其 typed file/revision/result/occurrence/authority 语义。
- [x] 5.3 删除 engine 与 pipeline artifact staging/fetch/register/publication helper、`openzyme_pipeline.artifacts` surface、`HpcStageRef`、per-run artifact alias 与 artifact-shaped expected-output handling，同时保留 revision-bound executor workspace 和 external-job/result lifecycle。
- [x] 5.4 删除 runner-facing artifact catalog/staging payload 与 compatibility adapter，且不得改变前序已经验收的 no-expected-output revision-bound job contract、opaque handle 与 effect-certainty contract。
- [x] 5.5 从 Host/core/CLI 删除 artifact endpoint、request/response field、media schema、restore/event decoder、CLI rendering、evaluator fixture、prompt、reflection metadata 与 tool name；unknown legacy name 必须以 unsupported 失败且不得翻译。
- [x] 5.6 从 web UI 删除 artifact reducer、state、view、client parsing、label、route 与 fallback rendering，仅保留已验收的 file/revision/publication/scientific/job/lease contract。
- [x] 5.7 从 entry point、plugin/tool discovery、generated schema、build output、package `__init__` export、type stub 与 current test fixture 中删除 legacy code；archived migration/verifier material 必须位于 current import 与 callable product surface 之外。
- [x] 5.8 仅依据新增 `artifact-subsystem-removal` capability 和 predecessor receipt 审计实现；本 change 不得重新打开或重新定义 controlled-operation、runner 或 sandbox product requirement。

## 6. 最终 fresh-install baseline 与 inert legacy migration

- [x] 6.1 用 fresh final-schema baseline 替换 current database initialization；它只创建 file/revision/publication/report/scientific/job/result/lease structure，绝不创建 artifact table、field、trigger、index、storage root 或 writer。
- [x] 6.2 将旧 artifact-era migration asset 移出 current migration loader 与 runtime package surface，只作为 inert development/archive history 保留，确保 fresh install 或 startup 期间无法执行。
- [x] 6.3 新增显式 supported-generation transition：offline executable 只识别 exact pre-removal generation 与 complete receipt，normal runtime 只识别 exact final generation。
- [x] 6.4 证明 fresh empty database/storage 的 initialization 与 restart 产生相同 final schema/storage manifest 和 import/tool catalog，且不会短暂创建 artifact structure 或 legacy directory。

## 7. 封闭 startup 与独立 historical verification

- [x] 7.1 要求 normal startup 匹配 exact final schema generation 与 complete `LegacySubsystemRemovalReceipt`；启动时不得加载 legacy repository、migration reader、artifact storage adapter 或 compatibility schema。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 7.2 对 old database、legacy table/column/trigger/index、storage marker、old public contract、missing receipt 或 removal-incomplete ledger 返回中性的 `legacy_schema_unsupported` 或 `legacy_removal_incomplete`，不得把已移除概念重新暴露为 current error vocabulary，且 database/storage mutation 为零。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 7.3 保留 immutable historical Git/LFS ref、mapping manifest、migration receipt 与纯 offline verifier，使其无需 artifact table、storage root、repository、runtime model、projection 或 current tool registration 即可使用。
- [x] 7.4 物理删除后仍保留 `historical_import_non_adoptable`，确保 historical ref 无法满足 current publication、handoff、scientific admission、task evidence、report claim、live authority 或 GO/NO-GO。

## 8. 聚焦删除与负向兼容性验证

- [x] 8.1 新增 migration fixture，覆盖 exact receipt success、每种 receipt/inventory drift failure、SQLite rebuild rollback、final-schema reconciliation、unknown absence、partial storage deletion、idempotent retry 与 complete removal ledger behavior。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 8.2 新增 static source/schema/catalog/build scan；若 explicit offline archive/verifier allowlist 之外出现任何 current artifact runtime symbol、field、table、FK、trigger、index、tool/event/schema name、alias、SDK module、UI key、fallback branch 或 legacy import，则测试失败。
- [x] 8.3 新增 fresh-install 与 restart 测试，证明 baseline 从不创建 artifact structure/storage，并且 old 或 incomplete deployment 在 mutation 前以精确 closed error 被拒绝。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 8.4 删除全部 artifact runtime/storage fixture 后，从空 Git/LFS cache 新增 standalone historical-verifier 测试，包括 tamper/missing-object failure 与 AOX non-adoption。
- [x] 8.5 新增回归测试，证明 controlled-operation occurrence/effect certainty、no-expected-output revision-bound job lifecycle、executor workspace、sandbox native file、report、scientific deliverable、lease 与显式 `task.finish` 在没有 artifact code 时仍正常工作。

## 9. 聚焦验收、架构文档与完成 receipt

- [x] 9.1 针对 fresh-final 与 exact offline-upgrade fixture 运行聚焦 core/Host migration 和 runtime suite，包括实际存在的 `packages/openzyme-core/tests/test_migrations.py`、`test_protocols.py`、`test_agent_capability_projection.py`、`test_report_publication.py`、`test_scientific_file_deliverables.py`、controlled-operation/sandbox suite 与 `apps/openzyme-host-api/tests/test_api.py`。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-SCI-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-UI-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 9.2 运行聚焦 engine/pipeline/runner 与 web UI suite，包括 Podman workspace、pipeline、no-expected-output job lifecycle、实际存在的 `apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py`、`test_executor_workspace_contract.py`，全部五个 `apps/openzyme-web-ui/tests/*.test.js` suite 以及 UI build。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-UI-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 9.3 更新 `docs/OpenZyme架构设计.md` 及相关 `docs/v3/` doctrine、target architecture、control-plane、capability-engine、public-interface、runtime、top-level-loop、persistence、failure-recovery、compatibility-sunset、execution-pipeline 与 offline operator 文档，描述最终 artifact-free product/schema 与不可逆 receipt-bound removal path。
- [x] 9.4 对本 change 与全部 13 个 prerequisite change 运行 strict OpenSpec validation，再运行 `./scripts/check-mainline.sh`；记录 exact revision、schema/storage manifest、command、result、UI build、排除的 live gate 与任何 environment-owned blocker，不得新增 fallback。
- [x] 9.5 仅当 exact final schema、storage-zero scan、code/static scan、fresh baseline、old-startup rejection、standalone historical verification、focused/mainline result 与 documentation digest 全部匹配后，完成 immutable `LegacySubsystemRemovalReceipt` 并签发 change completion receipt。（整改登记：[GAP-STARTUP-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
