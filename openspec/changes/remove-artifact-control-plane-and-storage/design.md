## Context

前 13 个 changes 已按依赖顺序建立 repository binding、独立 agent Git workspace、Git LFS、immutable workspace publication、agent capability lease、file-native sandbox、executor HPC workspace、revision-bound external job、revision/path research/report/task handoff、旧 AOX cutover supersession、scientific deliverable file identity、file-only public surface和全量 historical Git/LFS migration。本 change执行用户选择 6B 的最后一步：物理删除 artifact domain、database structures、legacy storage objects和 current runtime code。

删除不是兼容性清理。`SessionArtifactRecord` 目前仍被多张历史表、FK、trigger、repository、sandbox/controlled-operation/scientific/HPC路径和 storage URI依赖；SQLite又不能安全地仅用若干 `DROP COLUMN`完成深 FK重构。必须在 offline maintenance window中先消费 exact historical migration receipt、重验 bytes/lineage覆盖，再执行 forward schema rebuild和storage deletion。最终 current product、runtime、fresh-install schema、API、SDK、UI和 tests均不得保留 artifact fallback。

## Goals / Non-Goals

**Goals:**

- 删除 `ArtifactKind`、`SessionArtifactRecord`、artifact repositories/services/tools/projections/mutation writers、`ArtifactBoundaryService`、`HpcStageRef`和 compatibility adapters。
- 通过 forward offline database migration物理删除 artifact tables、columns/FKs/triggers/indexes、materialization/publication/scientific artifact structures，并重建 surviving tables为 file/revision/job/result typed schema。
- 只在 exact historical migration receipt再次通过后，按冻结 inventory删除全部 legacy artifact blob/storage objects并验证零残留。
- 删除 controlled-operation、sandbox、research、report、scientific、HPC、Host/CLI/UI和 Pipeline SDK中的 artifact fields、schemas、events和 fallback。
- 让 fresh install直接建立最终 schema；旧 migration source仅作开发历史，不得被 current migration loader执行并短暂重建 artifact tables。
- 发现旧 schema、旧 tool/request或未完成 migration时 fail closed，要求显式离线升级，不自动恢复 legacy subsystem。

**Non-Goals:**

- 不删除 immutable historical Git/LFS refs、mapping manifests、migration receipts、repository history或 archived OpenSpec。
- 不把 historical import提升为 current publication/evidence，也不启动新的 AOX live campaign。
- 不改变 task、approval、execution lease/fence、effect certainty、scientific closure、Git publication或 external job的 canonical语义。
- 不提供 artifact compatibility mode、dual schema、lazy migration、read-through adapter、placeholder或 emergency fallback。
- 不允许 normal Host startup自动执行 destructive migration；该动作只能由显式 offline operator workflow完成。

## Decisions

### 1. 删除 gate绑定 exact 13-change prerequisite与 historical receipt

Offline remover必须验证以下 changes的完成/验收 identity，而不是只检查某个 feature flag：

1. `supersede-aox-hmm-artifact-cutover`
2. `establish-project-repository-bindings`
3. `establish-agent-capability-leases`
4. `provision-independent-agent-git-workspaces`
5. `publish-and-sync-workspace-revisions`
6. `support-git-lfs-work-products`
7. `migrate-research-report-and-task-handoffs-to-files`
8. `provision-isolated-executor-hpc-workspaces`
9. `execute-hpc-jobs-from-workspace-revisions`
10. `migrate-scientific-deliverables-to-files`
11. `replace-sandbox-artifact-boundaries-with-files`
12. `cut-over-workspace-public-interfaces`
13. `migrate-historical-artifacts-to-git-lfs`

除此之外还必须重验 `HistoricalArtifactMigrationReceipt` 的 inventory generation、database/storage snapshot、row/object/byte/reference set equality、每个 Git/LFS target fresh read-back、AOX non-adoption、zero unresolved refs和 zero post-freeze writes。Receipt缺失、版本不匹配、target object不可读或当前 inventory漂移都阻止任何 DDL/storage删除。

不接受 operator `--force`、empty table count、backup存在或“current code已不用”作为替代证明。

### 2. 使用专用 offline removal executable；normal runtime永不兼容旧 schema

部署进入 maintenance mode后停止 Host、CLI mutation consumers、sandbox、execution workers、runner callbacks和 UI writes，并取得 session/execution/continuation/sandbox/mutation quiescence receipt。专用 offline executable以短期 migration authority打开数据库和legacy storage，完成 gate、DDL、storage deletion与验证。

新 runtime binary只认识 final schema generation和 file/revision/job contracts。Normal startup若发现 legacy table、column、trigger、storage marker、old public contract或 removal-incomplete状态，返回中性的 `legacy_schema_unsupported` / `legacy_removal_incomplete`并退出；它不把已移除概念重新暴露为 current error vocabulary，也不加载 legacy repository、运行迁移、创建表或读旧 bytes。

这样把必要的旧-schema知识限制在一次性离线 migrator中，而不是留在长期 runtime形成 fallback。

### 3. SQLite使用 rebuild-and-copy，不做局部 nullable遗留

Forward migration先创建 final surviving tables，schema中只保留 revision/path/publication/report/scientific deliverable/external job/result和现有 authority fields。对每张曾含 artifact FK/column的 table：

1. 验证对应 typed replacement已由前序 migration填充且与 historical receipt映射一致；
2. 创建 final table与 final triggers/indexes；
3. 在 transaction内复制非 artifact columns和 typed refs；
4. 校验 row count、primary/unique keys、foreign-key closure、immutable/authority constraints和 canonical digests；
5. 原子替换旧 table。

随后删除 artifact主表、materialization/GC、controlled-operation result artifact、scientific artifact materialization和所有只服务 artifact publication/staging的 tables、triggers/indexes。`artifact_publication` mutation writer category、artifact event/outbox schemas和 artifact storage locator columns一并删除。任何 replacement缺失不得转成 `NULL`、空 ref或 synthetic result。

### 4. Runtime/domain代码按 owner完整删除，不保留空壳类型

代码删除分区如下：

- domain/repository：`ArtifactKind`、`SessionArtifactRecord`、artifact/materialization/GC repositories和所有 artifact id/list/digest fields；
- runtime/core：`ArtifactBoundaryService`、artifact tools/catalog/projection/redaction、artifact mutation writer、source snapshot artifact和 sandbox stage/register/fetch callback；
- engines/pipeline：artifact helper、artifact alias、Podman per-run artifact stage/register、Pipeline SDK `artifacts`模块、`HpcStageRef`和 expected-output artifact publication；
- control-plane consumers：controlled-operation artifact-set/result fields、research/report/task artifact refs、scientific artifact structures、AOX current artifact finalizer和 fallback readers；
- Host/CLI/UI：artifact request/response models、events、restore/reflection/prompts、workspace `artifacts/artifact_index`和 UI artifact reducer/view；
- runner：`StagedInput.artifact_id`、ArtifactStore命名/contract、runner-artifact output publication和 per-run artifact staging/fetch；保留 executor workspace、runner-private state、opaque job handle、effect journal和 lifecycle。

不保留 deprecated alias、protocol translation或 stub class，因为它们会让旧 import/tool/schema继续通过并形成复活点。Archived migration/verifier source必须移到 current package/import/tool discovery之外。

### 5. Legacy storage删除使用 receipt inventory，且与 schema完成状态分离

DDL成功后，offline remover按 historical receipt中的 exact legacy object inventory删除 source objects和只服务 artifact的 directories。每个删除目标必须在 allowlisted legacy root内、非 symlink、identity/digest与 receipt一致；不通过 glob、ambient environment或 unresolved locator扩大范围。

删除过程幂等记录到 deployment migration ledger中的 `LegacySubsystemRemovalReceipt`；它只证明一次离线删除，不提供 legacy资源读取能力，也不属于 current product control-plane schema。Receipt包含 expected/deleted/already-absent object identity、bytes、root和 error set。`already_absent`只有在 historical migration时已证明 source object identity且当前 absence与同一 receipt匹配时才允许；未知缺失阻止完成。全部对象删除后重新扫描 legacy roots和数据库，要求 exact zero artifact runtime structures/objects。

若部分 filesystem删除失败，database不回滚或重建 artifact表；deployment保持 removal-incomplete、runtime拒绝启动，operator只可继续删除同一 receipt中的剩余对象。

### 6. Fresh install采用final baseline，旧 migrations不进入 runtime loader

新部署直接从 versioned final baseline schema创建数据库，baseline从未包含 artifact tables/FKs/triggers。历史 SQL migration files可留在 repository archive用于审计，但 current migrator manifest不加载它们；测试必须证明 empty database初始化期间也不会短暂创建 artifact schema或 storage root。

既有部署只能先运行 historical migration，再运行 offline removal。跳过 generation、从任意旧版本直接启动或复制旧 DB到新 binary均返回 unsupported migration state，不自动“补齐”旧 artifact tables。

### 7. 删除后的兼容性策略是明确拒绝

旧 `artifact.*`/`artifacts.*`/`scientific.artifact.*`/`hpc.stage_artifact` tool call、artifact request字段、artifact evidence ref、artifact-era restore context、old SDK import和 old workspace schema均返回明确 stale/removed-contract错误。错误只指向 file/revision/publication/job/result合同，不自动改写路径、选择 publication、创建 commit或重发 external effect。

Historical Git/LFS verifier是独立只读 operator能力；它按 historical manifests读取 Git/LFS，不链接或导入 artifact runtime package。

## Risks / Trade-offs

- [物理删除不可逆] → destructive step前要求独立备份、exact global migration receipt和 fresh Git/LFS read-back；删除后只允许将备份恢复到隔离 legacy环境，不回注 current runtime。
- [SQLite table rebuild遗漏 constraint或row] → 对每张 surviving table执行 schema manifest、row/key/FK/digest对照，并在单 transaction内替换；任一差异整体回滚 DDL。
- [DDL成功但storage删除部分失败] → runtime保持 removal-incomplete并拒绝启动；幂等继续 exact inventory删除，不重建 schema或 fallback读取。
- [archived code被 current import/discovery重新加载] → current package exports、entry points、tool registry、migration manifest和 static caller audit必须为零；archive与runtime路径物理隔离。
- [历史 verifier需要旧语义而诱发 runtime adapter] → verifier只消费 Git/LFS mapping manifest和版本化纯函数，不访问旧 DB/storage或 current product surface。
- [外部旧 client不断请求 artifact schema] → closed stale-contract错误与版本预检；不延长兼容期或保留 alias。

## Migration Plan

1. 收集并验证前 13 changes的完成 receipts、current file-only contract和 historical global receipt；对 internal Git/LFS refs执行独立 fresh read-back。
2. 创建并校验可恢复的数据库、legacy storage和 deployment config备份；备份只供隔离 recovery，不构成 deletion proof。
3. 停止 current services/workers，取得 quiescence和 writer-freeze proof；运行 offline remover dry-run，输出 exact DDL rebuild plan、surviving replacement refs和 storage deletion inventory。
4. 在单 database transaction中重建 surviving tables、复制 typed refs、验证 constraints/counts/digests并删除 artifact tables/FKs/triggers/indexes。失败时 transaction回滚，未删除storage。
5. DDL提交后，按 exact receipt删除 legacy storage objects并持续写 removal receipt；任何错误保持 deployment blocked并只重试同一删除计划。
6. 重新打开数据库执行 `foreign_key_check`、integrity/schema manifest、zero artifact symbol/table/column/trigger/index检查；扫描 allowlisted legacy roots要求零未处理对象。
7. 从 empty database验证 final baseline bootstrap；从 artifact-era DB验证 normal runtime明确拒绝且不会自动 migration/recreate。
8. 部署不含 artifact runtime code的新 binary，运行 focused/mainline/architecture qualification。只有 exact final schema与 complete removal receipt允许 Host启动。
9. 删除后的 defect采用 forward fix；不得恢复旧 tables、objects、tools、SDK或 projection。需要查看历史时只使用 immutable Git/LFS historical verifier。

## Open Questions

无。6B 已明确授权在历史迁移全量通过后物理删除；任何 coverage、integrity、quiescence或Git/LFS验证缺口都阻止删除，而不是触发 fallback或重新选择兼容模式。
