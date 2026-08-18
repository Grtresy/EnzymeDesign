## Context

独立 agent clone 让 local files、commits 和 private refs 有了清晰 owner，但这些状态默认对其他 agents 不可见，也不能单凭 branch name 形成共享真相。researcher 到 executor、reporter 或其他 collaborator 的交接需要一个 exact、immutable、可恢复的 revision identity；与此同时，Git remote ref update 是可能在 response loss 后 outcome unknown 的外部 effect，不能通过“再 push 一次”猜测解决。

本 change 新增显式 `workspace.publish`、append-only `PublishedRevision` 和基于标准 Git fetch 的显式同步。它复用 canonical controlled-operation ownership/effect-certainty/reconciliation，不创建第二套 publication/job state machine。

C2 只提供 generation-bound `AgentCapabilityLease` 的 canonical identity、状态/profile 查询与验收 receipt；它不实现 publication route。C4 拥有 publication-specific authority composition：必须把 exact frozen publication intent、admission 时 active 的 exact capability lease，以及唯一 canonical `ControlledOperationExecution` 分别持久化和联合校验，任何一轴都不能由另外两轴推断或替代。

在这次明确排序且统一后验验证的连续迁移中，C4 源码实现先消费 `workspace_publication_source_only_dependency_gate@1`。该 gate 直接绑定当前 C2/C3 实现和未完成验收任务，并声明 `acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`；它不允许执行真实 publish、remote Git I/O、live 或外部 effect，也不能替代最终 predecessor receipts。

## Goals / Non-Goals

**Goals:**

- 只有 agent 显式发布 whole-repository clean commit 时才建立 team shared file truth。
- 用 `PublishedRevision` 绑定 exact repository binding、commit/tree、parent/base、publisher、immutable ref、path manifest 和 policy digest。
- 让 publication ref 由 Host create-only 写入，禁止 force-update/delete，并用 frozen intent、idempotency key 和 exact receipt处理response loss。
- 实现并验收 publication intent × capability lease × controlled execution 的完整组合矩阵，包括 dispatch 前 revoke 与 possible-effect 后 revoke 的不同收敛语义。
- 让其他 agents显式fetch exact published ref并自主选择fast-forward、merge、rebase或cherry-pick；系统不自动修改clone或解决冲突。
- 允许protocol/task handoff引用`publication_id + revision + path`，同时保持publish、message delivery和task completion正交。

**Non-Goals:**

- 不自动stage、commit、push、publish、fetch、merge、rebase、cherry-pick、解决冲突或完成task。
- 不把agent local commit或private-ref push变成shared projection。
- 不实现upstream GitHub push/PR/release；它们是独立external effects。
- 不实现Git LFS object closure、threshold、quota或GC；后继LFS change扩展publish validator。
- 不允许partial/path-only publication，也不重新引入artifact catalog或CAS-facing product identity。
- 不重新实现 C2 的 lease 生命周期、exact/session-policy/subtree revoke 选择器或 delegation genealogy；C4只消费C2返回的exact lease identity与当前状态。
- 不引入通用 budget authority；publication 的有限重试/恢复策略只是 effect-recovery policy，不能替代 intent、lease 或 execution owner/fence。

## Decisions

### 0. Source-only dependency gate 不提升 predecessor 状态

C4 的源码准入与最终生产验收分离。源码准入重读 immutable C0/C1 receipts、C2 lease seam、C3 ready-workspace/checkpoint seam和 controlled-operation 基线，只允许修改 domain、migration、service、tool、projection、测试与文档。它不得作为 active lease、workspace readiness、checkpoint、execution fence、Git credential或publication receipt使用。全部连续 change 实现完成后，最终验收必须重新绑定正式 C2/C3 receipts、最终 source revision与 C4 完整验证；snapshot 中的旧 digest不能成为 fallback。

### 1. `workspace.publish` 冻结 whole-repository intent

调用者必须提供exact workspace generation、expected HEAD commit、repository binding version、可选declared base/parent publication、可选`supersedes`和幂等key。Host在创建任何remote effect前验证active capability lease、显式publication intent、clean working tree、HEAD相等、commit属于pinned repository、完整tree/path manifest与当前policy digest。manifest覆盖whole tree的path、mode、Git object identity以及政策要求的size/LFS identity；不接受路径子集。

选择whole-repository commit，是为了让handoff具备闭合context且可用标准Git验证。partial publication或从working tree直接打包被否决，因为它们会创建Git之外的第二种文件真相。validator不得自动stage/commit、修改`.gitattributes`、删除untracked file或修复policy。

### 2. publication id/ref 在dispatch前确定且不可变

Host在admission事务中创建frozen `WorkspacePublicationIntent`，预先分配`publication_id`和唯一ref，例如binding policy下的`refs/openzyme/publications/<publication_id>`，并绑定exact commit/tree、publisher、workspace generation、base/parent、manifest digest、policy digest和idempotency key。相同key只可重读完全相同的intent；任何字段漂移直接冲突，不创建替代publication id/ref。

选择preallocated immutable ref，是为了让response-loss reconciliation始终查询同一地址。按branch name更新mutable ref或失败后换ref重试被否决，因为无法证明产生了几个共享版本。

### 3. remote ref update 由 canonical controlled operation 独占

publication ref create是durable external effect，必须由唯一`ControlledOperationExecution`拥有、claim和fence。该 execution 在 active capability lease 和 frozen publication intent admission 时自动创建，`workspace.publish` 不再请求逐 publication 人工 approval。Git service只接受Host credential的create-if-absent compare-and-set，并返回绑定remote identity、exact ref、expected previous absence、new commit和server observation的receipt。Host确认remote ref精确指向intent commit后，才物化immutable `PublishedRevision`和team event。

若response丢失，reconciliation只查询同一remote/ref：ref精确匹配commit时收敛为成功并复用同一publication；ref存在但commit不同是integrity conflict；无法证明结果时保持`dispatch_in_doubt`。系统不自动push、replacement dispatch、fallback remote或新建publication。选择复用`ControlledOperationExecution`而非独立publication FSM，是为了保留唯一effect owner、fence和unknown-outcome语义。

### 4. C4 拥有三轴 publication authority composition

Publication admission service必须联合读取并冻结三类独立事实，且按阶段执行以下矩阵：

| Exact publication intent | Exact capability lease | Canonical execution | 阶段与结果 |
| --- | --- | --- | --- |
| 缺失或不匹配 | 任意 | 任意 | 在创建execution/ref前拒绝；既有execution token不能合成intent |
| 已冻结 | 缺失、inactive或identity/profile不匹配 | 不存在 | 在admission事务前拒绝，不创建execution或remote effect |
| 已冻结 | admission时active且identity匹配 | 不存在 | C4原子create-or-read exactly one execution；execution durable前禁止Git I/O |
| 已冻结 | active | 存在但intent/binding/generation不匹配，或owner/fence无效 | consistency/fence conflict，零remote effect与零shared truth |
| 已冻结 | active | exact且current owner/fence有效 | 只允许该execution dispatch或reconcile预分配ref |
| 已冻结 | dispatch前被C2判定inactive | exact且尚无possible effect | 关闭新dispatch并以`no_effect`终止；不得重开approval或换lease |
| 已冻结 | possible/accepted effect后被C2判定inactive | exact且已有dispatch intent/effect evidence | 禁止新dispatch；仍由原execution/fence只reconcile同一ref并物化已证明的原publication |

C2 的 exact revoke、session/policy bulk revoke与operator显式subtree revoke最终都表现为该exact lease的canonical状态；C4不自行遍历parent/child，也不把child revoke反向施加给parent。选择由C4实现矩阵，是因为publication intent、Git effect owner与shared-truth materialization都是C4 route facts，C2 receipt只能证明lease seam存在，不能证明publication route已经产品闭合。

### 5. `PublishedRevision` 与ref都是append-only shared truth

`PublishedRevision` 至少绑定 `publication_id`、project/session、repository binding version、exact commit/tree、Git parent commits、declared base/parent publication、publisher agent/workspace generation、immutable publication ref、canonical path manifest/digest、policy digest、intent/execution/receipt identities、created time和可选`supersedes`。记录和ref均不可更新或删除；修订错误只能创建新publication并引用被supersede的旧id，旧记录继续可见。

选择append-only publication，而不是移动team branch，是为了消除force push和读者竞态。`supersedes`只表达推荐链，不篡改旧revision或让旧handoff失去审计意义。

### 6. team projection只读取 `PublishedRevision`

local commits、local branches、private refs和private push receipts不进入team shared projection。publication只有在remote effect已精确确认且`PublishedRevision`已持久化后可见；remote中未被canonical record引用的private/ref state不能被扫描成publication。读取者通过publication id得到safe exact ref、commit/tree、publisher、manifest和supersession facts，不获得其他agent private refs、credentials、Host paths或Git service internals。

选择canonical record projection，而不是扫描remote branches，是为了让共享真相具有事务、authority和receipt边界。把private push视为隐式publish被否决。

### 7. sync 是显式 fetch 加 agent-owned integration

其他agent在自己的capability lease和clone中，对明确`publication_id`执行标准`git fetch`并验证fetched ref/commit/tree与projection一致。fetch只增加本地objects/remote-tracking ref；是否fast-forward、merge、rebase、cherry-pick或只读取文件由agent明确决定。Host不自动checkout、更新branch、整合revision、解决冲突或在失败时重试另一策略。

选择标准Git primitives而不是`artifact.materialize`式复制，是为了保留Git provenance与agent策略自由。系统级auto-merge/sync loop被否决，因为冲突解决是语义决策。

### 8. Handoff、publish、message与task终态分离

protocol/task evidence可携带`publication_id + exact revision + repository-relative path`；consumer必须验证path存在于该publication manifest。创建publication不会自动发送handoff message、唤醒recipient、更新dependency或调用`task.finish`；发送message也不会自动fetch或merge。业务终态仍由agent显式决定。

选择closed reference handoff而不是复制bytes或传branch name，是为了让recipient复核exact source。把publish success等同于task completion被否决。

## Risks / Trade-offs

- [每次publication创建immutable ref会增长ref数量] → 使用独立namespace、索引和retention policy；被引用或superseded记录仍不可force-delete。
- [whole-repository manifest可能较大] → 持久化canonical manifest与digest并在projection分页/摘要；不能以抽样替代完整验证。
- [response loss导致`dispatch_in_doubt`阻塞后续publication] → exact ref提供可reconcile handle；未知时诚实等待，不用replacement push换取表面可用性。
- [agents需要自行处理Git冲突] → projection提供exact commit/tree/base/parent信息和原始Git错误，但Host不自动选择integration策略。
- [private工作被误以为已共享] → workspace projection明确区分dirty/local/private/published状态，team projection只列canonical publications。
- [lease在publication外部effect边界附近被revoke] → dispatch前以`no_effect`停止；possible effect后保留原execution并只reconcile预分配ref，不把revoke误作remote no-effect或删除已确认shared truth。

## Migration Plan

1. 记录非验收 C2/C3 source-only dependency gate；它不开放真实 publication、remote effect、live 或生产资格。
2. 新增publication intent、`PublishedRevision`、receipt/event repositories和唯一约束，并在internal remote配置Host-only create-only publication namespace。
3. 实现whole-tree clean-commit/policy validator；先覆盖普通Git objects，LFS closure由后继change增加为额外hard gate。
4. 在C4实现三轴authority composition service/repository constraints，覆盖全部intent/lease/execution组合、dispatch前revoke和possible-effect后revoke；C2 receipt只作为lease seam prerequisite。
5. 将publication dispatch接入canonical `ControlledOperationExecution`，实现exact ref create receipt和只查询同一ref的reconciliation。
6. 暴露`workspace.publish`与safe publication projection；只有具备pinned binding、ready independent workspace和active capability lease的agent可调用。
7. 向agent workspace提供显式fetch所需的safe ref identity；不添加自动sync/merge worker。
8. 更新protocol/task evidence schema以接受closed publication refs，但保持message、wakeup与task terminal transitions不变。
9. 不回填现有local commits、private refs或legacy artifacts为`PublishedRevision`；历史迁移使用独立historical namespace和receipt。
10. 全部连续 change 合并实现后统一生成正式 predecessor/current receipts；回滚时停止新publish admission并回退readers，保留所有已确认 refs、intents、executions、receipts和records。

## Open Questions

无。显式whole-repository publish、immutable ref、effect certainty、shared-truth projection、agent-owned sync和handoff边界均已裁决。
