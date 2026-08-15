## 1. C4 前置 receipts 与 publication admission gate

- [ ] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1`、`project_repository_binding_acceptance@1`、`agent_capability_lease_acceptance@1` 与 `agent_git_workspace_acceptance@1` receipts及其source/code/schema/policy digests；任一缺失或漂移时停止C4。
- [ ] 1.2 生成C4 dependency gate receipt，证明caller拥有pinned binding、ready independent clone、active generation-bound lease、可验证private checkpoint，以及Host-only create-only publication namespace。
- [ ] 1.3 冻结current `ControlledOperationExecution` owner/fence/effect-certainty/reconciliation baseline，明确publication必须复用该canonical owner且不得创建第二套effect FSM。
- [ ] 1.4 记录approval gate裁决：显式 `workspace.publish` intent加active capability lease足以自动canonical化publication execution，不创建或请求逐publication human approval；scientific/upstream authority仍保持独立。

## 2. Publication domain、migration 与 repositories

- [ ] 2.1 在 `openzyme-domain` 增加immutable `WorkspacePublicationIntent`、`PublishedRevision`、publication lifecycle/result与safe reference types，覆盖spec要求的全部identity fields。
- [ ] 2.2 添加单一forward SQL migration，创建publication intents、published revisions、exact remote receipts、supersedes links、event/outbox关系与idempotency/immutability unique constraints。
- [ ] 2.3 实现intent repository的create-or-read-exact semantics：相同idempotency key和全部identity fields返回同一intent，任一binding/generation/commit/tree/base/manifest/policy/publisher/supersedes drift在I/O前拒绝。
- [ ] 2.4 实现`PublishedRevision` append-only repository与create-once materialization，拒绝record update/delete、duplicate publication和dangling/mismatched intent/execution/receipt。
- [ ] 2.5 实现canonical whole-tree path manifest，绑定每个path、mode、Git object identity及policy要求的size/LFS identity，并持久化manifest与digest而不是抽样。
- [ ] 2.6 增加domain/migration/repository tests，覆盖idempotent reread、identity drift、supersedes、immutable update/delete、manifest canonicalization和foreign binding/generation。

## 3. `workspace.publish` whole-clean-commit admission

- [ ] 3.1 增加model-visible `workspace.publish` tool与thin Host API/service seam，只接受explicit idempotency key、workspace generation、expected HEAD、binding version、base/parent、optional supersedes和whole-repository intent。
- [ ] 3.2 在任何remote effect前验证active capability lease、exact C3 private checkpoint proof、clean working tree、HEAD/commit/tree一致、commit属于pinned binding及current policy digest。
- [ ] 3.3 拒绝staged/unstaged/untracked state、partial/path-only request、uncheckpointed completed step、foreign commit和policy mismatch，并返回exact facts而不stage、commit、clean、ignore、rewrite、push或package files。
- [ ] 3.4 在admission事务中preallocateimmutable `publication_id`与binding-policy publication ref，并冻结commit/tree、publisher、generation、base/parent、manifest、policy、supersedes和idempotency identity。
- [ ] 3.5 实现no-per-publication-approval path：active lease与frozen explicit intent验证后直接进入automatic canonical execution creation，不生成pending human approval或逐publish approval projection。
- [ ] 3.6 增加admission focused tests，覆盖clean whole commit成功、dirty/partial/uncheckpointed/policy drift拒绝、no auto-Git和无human approval。

## 4. Canonical controlled execution、immutable ref 与 receipt

- [ ] 4.1 为每个frozen publication intent自动创建并绑定exactly one `ControlledOperationExecution`，持久化dispatch intent后再执行Git I/O，并使用独立execution lease/fence拥有remote effect。
- [ ] 4.2 实现Host-only create-if-absent compare-and-set publication ref route，绑定exact internal remote/ref/expected absence/new commit，禁止force-update、delete、alternate ref或upstream fallback。
- [ ] 4.3 持久化immutable remote receipt，绑定remote identity、binding version、publication id/ref、expected previous absence、new commit/tree、server observation、execution generation和receipt digest。
- [ ] 4.4 只有在exact remote ref/commit/tree与frozen intent已确认后才materialize `PublishedRevision`和team event；private ref或unrecorded remote branch不得被扫描成publication。
- [ ] 4.5 实现response-loss reconciliation，仅查询同一preallocated ref：exact commit收敛原execution/publication，different commit形成integrity conflict，无法证明则保持`dispatch_in_doubt`。
- [ ] 4.6 禁止automatic push retry、replacement dispatch、new publication id/ref、fallback remote、approval reopen或intent rewrite；proven failure由agent在新explicit intent中决定后续动作。
- [ ] 4.7 闭合remote-ref-created/DB-commit-lost crash window，使restart只reconcile原intent/ref并create-once materialize相同publication，不产生duplicate record/event。
- [ ] 4.8 增加execution/recovery focused tests，覆盖success receipt、response loss exact-match、different-ref conflict、unreconcilable unknown、stale fence、restart materialization和零replacement dispatch。

## 5. Team projection、explicit fetch 与 handoff

- [ ] 5.1 扩展workspace/team projection，仅公开canonical `PublishedRevision`的publication id、binding、commit/tree、base/parent、publisher、immutable ref、manifest/supersedes和safe effect facts，隐藏private refs、credentials、Host paths和raw Git diagnostics。
- [ ] 5.2 提供exact publication fetch identity/verification seam，使recipient在own clone中显式运行standard `git fetch`并校验ref/commit/tree；Host不得自动fetch、checkout或更新branch。
- [ ] 5.3 保持fast-forward、merge、rebase、cherry-pick或只读inspection为agent显式Git动作；冲突或identity mismatch直接返回，不自动选策略、解决冲突、fallback revision或retry。
- [ ] 5.4 扩展protocol/task evidence schema以接受 `publication_id + exact revision + repository-relative path`，验证path位于canonical manifest且不复制bytes或接受mutable branch name。
- [ ] 5.5 保持publish、protocol delivery、wakeup、dependency与task terminal states正交；publication成功不得自动send message、fetch、satisfy dependency或调用`task.finish`。
- [ ] 5.6 实现supersedes projection与读取规则：新publication可推荐替代旧publication，但两条record/ref均保持immutable、可寻址和可审计。
- [ ] 5.7 增加two-agent integration tests，覆盖publisher private state不共享、publication后recipient显式fetch且branch/working tree不变、manual merge conflict无auto-resolution和exact handoff path validation。

## 6. Migration、retention 与 boundary audit

- [ ] 6.1 不回填existing local commits、private refs、legacy artifacts或remote branches为`PublishedRevision`；需要保留的历史数据只进入独立historical migration namespace。
- [ ] 6.2 增加publication namespace/ref retention与read-only audit command，确保confirmed或superseded refs/records不可force-delete，且private/historical refs不会进入team projection。
- [ ] 6.3 审计upstream effect边界，证明internal publication不会push GitHub/upstream、创建PR/release或把upstream failure当internal fallback。
- [ ] 6.4 为后继Git LFS change保留hard validator seam；C4只验证当前policy manifest identity，不自行实现threshold、object closure、quota或GC fallback。

## 7. Focused tests、文档与 C4 验收 receipt

- [ ] 7.1 运行domain/core/Host/native-Git focused suites，覆盖whole-clean-commit admission、automatic `ControlledOperationExecution`、无逐publication approval、immutable ref/receipt、effect certainty、explicit fetch和no-auto-merge/retry。
- [ ] 7.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/02-control-plane.md`、`docs/v3/04-public-interfaces.md`、`docs/v3/05-agent-runtime.md` 与execution/reliability文档，记录publication shared-truth和explicit sync边界。
- [ ] 7.3 运行 `DO_NOT_TRACK=1 openspec validate publish-and-sync-workspace-revisions --type change --strict --no-interactive` 并保存通过结果。
- [ ] 7.4 运行 `./scripts/check-mainline.sh`，确认不得以auto-merge、push retry、manual approval、mutable team branch、private-ref scan或live external service绕过失败。
- [ ] 7.5 审计Git diff、migration、tool/API schemas、approval paths、ref ACL、projection与task/protocol transitions，确认没有silent publication、upstream effect、artifact fallback或automatic workflow completion。
- [ ] 7.6 生成 immutable `workspace_publication_acceptance@1` change receipt，绑定C0--C3 receipts、code/schema/policy digests、focused/two-agent/recovery tests、docs、strict OpenSpec、mainline、immutable ref/receipt proof与final scope audit。
