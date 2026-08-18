> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 1. C4 前置 receipts 与 publication admission gate

- [x] 1.1 验证 immutable C0/C1 receipts；对尚待最终统一验收的 C2/C3 记录 current source/schema/policy/interface digests与未完成验收tasks，固定`acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`。source-only gate只允许继续源码，不得当作publication route、execution、shared truth或predecessor acceptance证明。
- [x] 1.2 生成C4 source-only dependency gate，记录pinned binding、ready independent clone、active generation-bound lease、private checkpoint与Host-only create-only publication namespace的当前实现接口；禁止据此执行实际publish、credential、remote Git I/O、live/effect或production claim。
- [x] 1.3 冻结current `ControlledOperationExecution` owner/fence/effect-certainty/reconciliation baseline，明确publication必须复用该canonical owner且不得创建第二套effect FSM。
- [x] 1.4 记录approval gate裁决：显式 `workspace.publish` intent加active capability lease足以由C4自动canonical化publication execution，不创建或请求逐publication human approval；scientific/upstream authority仍保持独立。
- [x] 1.5 冻结C4-owned intent × lease × execution组合矩阵与phase semantics，覆盖三轴缺失/漂移、valid execution fence、dispatch前revoke和possible-effect后revoke；C4只消费C2返回的exact lease状态，不重做exact/session-policy/subtree/parent-child revoke选择，也不引入通用budget authority。

## 2. Publication domain、migration 与 repositories

- [x] 2.1 在 `openzyme-domain` 增加immutable `WorkspacePublicationIntent`、`PublishedRevision`、publication lifecycle/result与safe reference types，覆盖spec要求的全部identity fields。
- [x] 2.2 添加单一forward SQL migration，创建publication intents、published revisions、exact remote receipts、supersedes links、event/outbox关系与idempotency/immutability unique constraints。
- [x] 2.3 实现intent repository的create-or-read-exact semantics：相同idempotency key和全部identity fields返回同一intent，任一binding/generation/commit/tree/base/manifest/policy/publisher/supersedes drift在I/O前拒绝。
- [x] 2.4 实现`PublishedRevision` append-only repository与create-once materialization，拒绝record update/delete、duplicate publication和dangling/mismatched intent/execution/receipt。
- [x] 2.5 实现canonical whole-tree path manifest，绑定每个path、mode、Git object identity及policy要求的size/LFS identity，并持久化manifest与digest而不是抽样。
- [x] 2.6 增加domain/migration/repository tests，覆盖idempotent reread、identity drift、supersedes、immutable update/delete、manifest canonicalization和foreign binding/generation。

## 3. `workspace.publish` whole-clean-commit admission

- [x] 3.1 增加model-visible `workspace.publish` tool与thin Host API/service seam，只接受explicit idempotency key、workspace generation、expected HEAD、binding version、base/parent、optional supersedes和whole-repository intent。
- [x] 3.2 在任何remote effect前通过C2 canonical seam验证exact active capability lease，并验证exact C3 private checkpoint proof、clean working tree、HEAD/commit/tree一致、commit属于pinned binding及current policy digest；不得把C2 receipt本身当作active lease或publication execution。
- [x] 3.3 拒绝staged/unstaged/untracked state、partial/path-only request、uncheckpointed completed step、foreign commit和policy mismatch，并返回exact facts而不stage、commit、clean、ignore、rewrite、push或package files。
- [x] 3.4 在admission事务中preallocateimmutable `publication_id`与binding-policy publication ref，并冻结commit/tree、publisher、generation、base/parent、manifest、policy、supersedes和idempotency identity。
- [x] 3.5 实现C4三轴composition service/repository constraints：active exact lease与frozen explicit intent验证后create-or-read exactly one publication execution；缺轴、identity drift或invalid fence均零Git I/O，且不生成pending human approval或逐publish approval projection。
- [x] 3.6 增加admission focused tests，覆盖clean whole commit成功、dirty/partial/uncheckpointed/policy drift拒绝、no auto-Git、无human approval、三轴完整cross-product与无通用budget-authority替代。

## 4. Canonical controlled execution、immutable ref 与 receipt

- [x] 4.1 为每个通过C4三轴admission的frozen publication intent自动创建并绑定exactly one `ControlledOperationExecution`，固化intent/lease admission basis，持久化dispatch intent后再执行Git I/O，并使用独立execution lease/fence拥有remote effect。
- [x] 4.2 实现Host-only create-if-absent compare-and-set publication ref route，绑定exact internal remote/ref/expected absence/new commit，禁止force-update、delete、alternate ref或upstream fallback。
- [x] 4.3 持久化immutable remote receipt，绑定remote identity、binding version、publication id/ref、expected previous absence、new commit/tree、server observation、execution generation和receipt digest。
- [x] 4.4 只有在exact remote ref/commit/tree与frozen intent已确认后才materialize `PublishedRevision`和team event；private ref或unrecorded remote branch不得被扫描成publication。
- [x] 4.5 实现response-loss reconciliation，仅查询同一preallocated ref：exact commit收敛原execution/publication，different commit形成integrity conflict，无法证明则保持`dispatch_in_doubt`。（整改登记：[GAP-PUB-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 4.6 禁止automatic push retry、replacement dispatch、new publication id/ref、fallback remote、approval reopen或intent rewrite；proven failure由agent在新explicit intent中决定后续动作。
- [x] 4.7 闭合remote-ref-created/DB-commit-lost crash window，使restart只reconcile原intent/ref并create-once materialize相同publication，不产生duplicate record/event。
- [x] 4.8 增加execution/recovery focused tests，覆盖success receipt、response loss exact-match、different-ref conflict、unreconcilable unknown、stale fence、dispatch前lease revoke为`no_effect`、possible-effect后revoke仍same-ref reconcile、restart materialization和零replacement dispatch。（整改登记：[GAP-PUB-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）

## 5. Team projection、explicit fetch 与 handoff

- [x] 5.1 扩展workspace/team projection，仅公开canonical `PublishedRevision`的publication id、binding、commit/tree、base/parent、publisher、immutable ref、manifest/supersedes和safe effect facts，隐藏private refs、credentials、Host paths和raw Git diagnostics。
- [x] 5.2 提供exact publication fetch identity/verification seam，使recipient在own clone中显式运行standard `git fetch`并校验ref/commit/tree；Host不得自动fetch、checkout或更新branch。
- [x] 5.3 保持fast-forward、merge、rebase、cherry-pick或只读inspection为agent显式Git动作；冲突或identity mismatch直接返回，不自动选策略、解决冲突、fallback revision或retry。
- [x] 5.4 扩展protocol/task evidence schema以接受 `publication_id + exact revision + repository-relative path`，验证path位于canonical manifest且不复制bytes或接受mutable branch name。
- [x] 5.5 保持publish、protocol delivery、wakeup、dependency与task terminal states正交；publication成功不得自动send message、fetch、satisfy dependency或调用`task.finish`。
- [x] 5.6 实现supersedes projection与读取规则：新publication可推荐替代旧publication，但两条record/ref均保持immutable、可寻址和可审计。
- [x] 5.7 增加two-agent integration tests，覆盖publisher private state不共享、publication后recipient显式fetch且branch/working tree不变、manual merge conflict无auto-resolution和exact handoff path validation。

## 6. Migration、retention 与 boundary audit

- [x] 6.1 不回填existing local commits、private refs、legacy artifacts或remote branches为`PublishedRevision`；需要保留的历史数据只进入独立historical migration namespace。
- [x] 6.2 增加publication namespace/ref retention与read-only audit command，确保confirmed或superseded refs/records不可force-delete，且private/historical refs不会进入team projection。
- [x] 6.3 审计upstream effect边界，证明internal publication不会push GitHub/upstream、创建PR/release或把upstream failure当internal fallback。
- [x] 6.4 为后继Git LFS change保留hard validator seam；C4只验证当前policy manifest identity，不自行实现threshold、object closure、quota或GC fallback。

## 7. Focused tests、文档与 C4 验收 receipt

- [x] 7.1 在全部连续 change 组合实现完成后运行domain/core/Host/native-Git focused suites，覆盖whole-clean-commit admission、C4-owned intent × lease × execution完整组合、automatic `ControlledOperationExecution`、pre/post-dispatch revoke、无逐publication approval、immutable ref/receipt、effect certainty、explicit fetch和no-auto-merge/retry。
- [x] 7.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/02-control-plane.md`、`docs/v3/04-public-interfaces.md`、`docs/v3/05-agent-runtime.md` 与execution/reliability文档，记录publication shared-truth和explicit sync边界。
- [x] 7.3 在最终统一验收阶段运行 `DO_NOT_TRACK=1 openspec validate publish-and-sync-workspace-revisions --type change --strict --no-interactive` 并保存通过结果。
- [x] 7.4 在最终统一验收阶段运行 `./scripts/check-mainline.sh`，确认不得以auto-merge、push retry、manual approval、mutable team branch、private-ref scan或live external service绕过失败。
- [x] 7.5 在最终组合源码上审计Git diff、migration、tool/API schemas、approval paths、ref ACL、projection与task/protocol transitions，确认没有silent publication、upstream effect、artifact fallback或automatic workflow completion。
- [x] 7.6 最终统一验收全部通过后生成 immutable `workspace_publication_acceptance@1` change receipt，绑定正式C0--C3 receipts、最终source revision、C4-owned authority-matrix proof、code/schema/policy digests、focused/two-agent/recovery tests、docs、strict OpenSpec、mainline、immutable ref/receipt proof与final scope audit；source-only gate不得升级为该receipt。（整改登记：[GAP-PUB-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
