## Context

现有 `SessionRuntimeLease` 只协调 bounded agent turn，`ControlledOperationExecution` lease/fence 只拥有 durable external effect，mutation writer 只保护 canonical writes。C1 已建立 project repository binding、session pin、Git/LFS credential record 和 private namespace primitive，但其 `ActiveCapabilityLeaseAssertion` 只是 acceptance-only caller assertion，不是 production capability owner。当前 `SandboxWorkspaceRecord` 也没有 canonical generation readiness，真实 independent Git workspace、capsule、network 与 toolchain 由 C3 建立。

本设计新增正交的 `AgentCapabilityLease` control-plane，并明确采用 staged cutover：C2 建立 lease、generation reservation/readiness、policy、credential 与 admission seams；从 C2 起 runtime/delegation 即 fail closed 地要求 exact active lease，所以在 C3 提供真实 workspace readiness 前，existing/new agents 会明确处于 `provisioning_required`、non-runnable 状态。C2 不用 legacy sandbox 或测试 fixture 伪装 production readiness。

## Goals / Non-Goals

**Goals:**

- 把 capability grant 精确绑定到 `session + agent_member + workspace_generation + closed profile + policy digest`，以 `pending_workspace | active | revoked` 表达 lifecycle。
- 建立 canonical workspace generation reservation/readiness seam，使后继 C3 可以提交 verified workspace-ready fact并原子激活 matching lease。
- 从 C2 落地开始，在 agent runtime、restore 与 delegation admission 强制 exact-generation active lease；缺失时直接呈现 provisioning blocker。
- 冻结 general/executor capability declarations、target scope、role/profile 与 delegation policy，禁止 profile fallback 或 ambient inference。
- 为 C1 repository credential broker及后继 Git/HPC/Host-supervised boundary提供同一 transaction 内可验证的 active-lease seam和短期 credential derivation seam。
- 定义 exact、bulk 与 explicit-subtree revoke topology，以及显式 `AgentRetirementRecord` owner。
- 保持 runtime、execution、mutation、scientific authorization、scientific ceilings 与 runtime mechanical budgets 的 owner 边界。
- 所有失败显式返回，不自动 retry、replay、fallback、改写 intent 或迁移 task 状态。

**Non-Goals:**

- 不实现 C3 的 independent clone、persistent volume、capsule activation、ordinary network、upload/download runtime、native toolchain 或真实 tool exposure。
- 不实现 C4 的 `WorkspacePublicationIntent`、`PublishedRevision`、publication ref/effect 或真实 publication authority cross-product。
- 不签发真实远程 SSH/HPC credential，不创建或修改远程 HPC login workspace，不执行 rsync/scp/Slurm operation。
- 不实现 ordinary job 的 approval-free admission、automatic `ControlledOperationExecution` creation、target-side submit enforcement或one-occurrence `sbatch` credential。
- 不创建万能 budget authority；不改变 `ScientificAttemptAuthorization` 的 scientific ceilings，也不把 prompt/step budget升级成 grant。
- 不从旧 sandbox process、runtime lease、现有 tool catalog、ambient config、C1 acceptance assertion 或 private namespace hold推断 capability lease/workspace readiness。
- 不为缺失 workspace/lease 的 agent 提供 legacy runtime、parent capsule、local execution 或其他 compatibility fallback。

## Decisions

### 1. Lease identity 与 generation reservation/readiness 分层

`AgentCapabilityLease` 包含 `lease_id`、session、internal agent member、public agent identity、workspace generation、closed capability profile/set、target-scope digest、policy version/digest、derived-from provenance、idempotency key、state version及 issued/activated/revoked facts。状态闭集为：

- `pending_workspace`：generation 已保留，policy 与 owner identity 已冻结，但没有 verified workspace-ready fact，不能授权任何 runtime/credential/capsule action；
- `active`：matching generation readiness 已由 canonical seam确认，可供 admission boundary重读；
- `revoked`：终态，不能恢复、降级或复用。

C2 同时建立最小 `AgentWorkspaceGenerationReservation`（或等价 canonical record），只拥有 `session + agent_member + generation` reservation、单调 generation、readiness status、readiness owner/ref/digest与replacement关系。它不保存 clone path、volume、`.git`、HEAD、network或capsule事实。只有注册的 workspace provisioner seam 可以为 exact reservation提交 ready fact；C3 将实现该 production provider。C2 tests可以使用显式 test provider，但 acceptance 不得把它写成 production workspace proof。

同一 `(session, agent_member, generation)` 最多一个 lease identity。对相同 immutable fingerprint的 issuance重放返回相同 pending或active record；generation、profile、capability set、target scope、policy或parent provenance任一漂移都冲突，不另发替代 lease。workspace replacement必须先关闭旧 generation并撤销旧 lease，再保留严格递增的新 generation。

### 2. C2 立即实施 non-runnable admission gate

C2 不等待 C3 才启用校验。从 C2 代码落地起：

- 每个 agent runtime claim/turn/capsule-facing admission都按 `session + member + exact generation` 重读 canonical active lease；
- restore不得复制旧 turn/process中的 lease object或bearer authority；
- existing master/teammate若没有 ready generation和active lease，workspace projection显示 `provisioning_required`，runtime不 claim/运行该 agent；
- `SessionRuntimeLease` 仍只允许 worker推进 scheduler，不得越过 capability provisioning gate。

delegation 分两层：caller/parent必须持有自己的 exact active lease才可进入 canonical delegation；Host可以原子创建 child identity、generation reservation与derived `pending_workspace` lease intent，但在 child workspace ready前不得把 child变成 runnable、不得让其 claim wakeup、不得借 parent capsule执行。C3提交 child readiness并激活 matching lease后，后续显式 runtime tick才可推进 child。provisioning failure保留 durable blocker，不自动删除 child或重试 provisioning。

该选择有意造成一个短暂但诚实的 staged状态：C2完成而C3未完成时，production agents non-runnable。它优于继续使用无法证明 generation/authority 的 legacy sandbox。

### 3. General/executor profiles 是 policy declarations，不是 C2 execution proof

general profile闭合声明 filesystem read/write、shell process、Git、Git LFS、ordinary network、upload和download。executor profile在此基础上声明 scoped SSH、rsync/scp、owned HPC login workspace CRUD和Slurm operations。role/profile、allowed child profiles、safe target ids或target-scope digest以及policy digest在 issuance时冻结；未知role、target drift或能力升级直接失败。

这些 capability names在 C2 中只供 policy、projection、credential/admission validator消费。C2 不据此修改 Podman network、安装工具、开放 destination、上传下载 bytes、连接远程 HPC或提交 job。真实 general capability运行由C3及后继change实现；真实 executor remote workspace和HPC/job边界由相应后继change实现。

parent profile不是child capability set的简单上限：general master必须能够按 frozen delegation policy创建 executor child。parent lease证明delegator identity并提供 provenance/policy input；child最终能力不得超过其 exact role允许的 child profile。不存在“parent缺能力时自动换profile”或“child失败时回parent执行”。

### 4. Credential 与 admission seam 只派生短期 authority

capability lease本身不含 bearer secret，也没有 TTL。C2 定义 `ActiveAgentCapabilityLeaseValidator` 和 process-scoped credential derivation seam：调用方只提交 lease id与expected session/member/generation/service/target/protocol，validator在同一 repository transaction中读取 canonical active lease并验证全部 identity、profile、policy和target facts。

C1 `RepositoryCredentialBroker` 的 production路径改为消费该 canonical validator：credential issuance、session pin、private namespace/hold与issuance record在同一 `BEGIN IMMEDIATE` transaction中闭合；caller不得再构造 production `ActiveCapabilityLeaseAssertion`。Git/LFS read与write authentication都重读 canonical active lease。credential TTL只终止credential；后续显式动作可在同一active lease下申请新credential，但不得自动重放先前失败的命令。

C2 只提供其他 service/target 可接入的 typed port、claims model与拒绝语义，不实现真实远程 SSH/HPC credential issuer、远程 CRUD、scheduler credential或one-occurrence submit bearer。private secret不得进入public projection、persistent workspace、repo config或Host-home mount。

### 5. Revocation 默认 exact，bulk/subtree 必须显式有界

revocation topology固定为：

- 普通 explicit revoke默认只撤销 exact lease；
- session end bulk撤销该 session全部 active/pending leases；
- policy invalidation只bulk撤销matching policy version/digest适用范围内的leases；
- canonical agent retirement撤销该exact agent member跨generation的全部pending/active leases；
- workspace replacement只撤销被替换generation的matching lease；
- operator只有明确给出 subtree root与scope时才递归撤销该derived subtree；不因parent exact revoke自动级联；
- child revoke永不反向撤销parent或siblings。

每次撤销都在一个 transaction中先停止新credential issuance、撤销可撤销derived credentials并释放matching capability holds，再写lease revoked state与append-only lifecycle event。任何部分失败导致整笔rollback；不得留下“lease已撤销但credential/hold仍active”或相反状态。

### 6. Agent retirement 由 request freeze、cleanup proof 与显式 record 闭合

C2 先持久化 immutable `AgentRetirementRequest`，精确绑定 session、agent member、current generation/lease、shutdown ref、registered cleanup provider、actor/time 与 digest。request commit 是 admission freeze：该 exact member 的新 runtime signal enqueue/claim/turn、lease activation/issuance、repository credential issuance 与 capability hold 都立即拒绝。它不取消或伪造已经 claim 的 occurrence；旧 occurrence 必须在原 `SessionRuntimeLease` fence 下显式 terminal settlement。任一 `claimed` signal 的 claim、reclaim、complete、fail 或 release 都同时受 transaction-local runtime fence trigger 约束，generic mutation writer 或 raw SQL 不能替代该 owner。

cleanup provider 在 request 已冻结且该 agent 没有 `claimed` signal 后才能提交 immutable proof record；proof 绑定 request id/digest、generation、lease、provider、reason、observed time 与 cleanup digest。request、proof 与 final record 三相 insert 还必须分别持有 service-only、transaction-local、exact-record retirement lifecycle authority；普通 mutation writer 不能伪造 registered provider proof。最终 transaction 再次重读 request/proof、current owner/generation/lease与零 claimed signal，撤销该 exact agent member 跨 generation 的全部 pending/active leases，写 immutable `AgentRetirementRecord`，并把 member 置为 `SHUTDOWN/retired`。任一检查或写入失败整体 rollback；过早 proof 不能在旧 occurrence 结算后被复用。

`AgentMemberStatus.FAILED` 是可诊断/可恢复 runtime状态，`COMPLETED` 可以只是业务或显示状态，`STOPPED` 也不证明 cleanup完成；三者都不得推断 retirement。shutdown request本身同样不够，必须完成显式 cleanup/shutdown handshake并写入 retirement record。数据库和service必须拒绝绕过 retirement transaction直接把active lease与agent retirement状态组合成不一致事实。

### 7. Authority matrix 不创造未来 owner或万能 budget

C2只对当前存在的owner做真实 cross-product tests：

- capability lease不替代 `SessionRuntimeLease` claim；反向也不成立；
- capability lease不替代 mutation writer/scope/fence；反向也不成立；
- capability lease不替代 `ControlledOperationExecution` owner/fence；C2不自动创建job execution；
- capability lease不替代 `ScientificAttemptAuthorization`；其中的 attempt/MICU/cost/wall-time ceilings继续由scientific authority拥有；
- prompt/context/step budget只是机械runtime constraint，active lease不能扩大、绕过或重新分配这些bounds，也不存在由它们反推lease的路径。

C2没有 `WorkspacePublicationIntent` / `PublishedRevision` owner，因此只做结构性negative proof：lease domain/service不得创建publication record/ref、不得声明publication success，且projection明确不把private capability/credential state当作shared truth。真实 `capability lease × publication intent × execution owner`矩阵由C4实现和验收，C2不提前创建placeholder publication truth。

### 8. 失败直接返回，不修改 intent 或重放命令

missing reservation、pending workspace、missing/revoked lease、identity/generation/profile/target/policy mismatch、retirement、credential issuance/authentication failure均返回稳定typed error。核心 provisioning错误为 `provisioning_required`，并明确 agent non-runnable及缺失的generation/lease facts。

Host不切换workspace/endpoint、不借parent或other-agent authority、不隐式降权、不自动重开approval、不把远程动作改成本地动作、不增加budget、不自动迁移task状态，也不自动retry/replay失败命令。已知typed错误可在Host API边界显式映射；不得新增catch-all后继续执行或静默吞错。

### 9. 连续迁移的实现依赖 snapshot 与最终 acceptance 分离

连续迁移需要在 C2、C3 及后继 change 的最终组合形态形成前持续修改同一批 domain、migration、runtime 和文档文件，因此后继源码实现的准入不能要求一个尚未运行最终组合验收、也尚未绑定最终 source revision 的 C2 acceptance receipt。C3 开始源码实现前改为生成 `agent_capability_lease_implementation_snapshot@1`：它绑定当时的 C0/C1 receipts、C2 change identity、source/schema/policy/interface digests、明确的未完成最终验收任务和禁止能力声明。

该 snapshot 是非验收、非 authority、非 runtime record。它必须固定声明 `acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`，只能证明“C3 已读取并以这些 C2 实现接口为起点继续修改源码”。它不得激活 lease、清除 `provisioning_required`、签发 credential、provision workspace、创建 publication/execution、启动 live 或满足任何 production/cutover gate。snapshot 漂移只要求后继实现重新读取当前事实并更新其 implementation dependency record；不得自动回退到旧接口或把 drift 当成 acceptance。

`agent_capability_lease_acceptance@1` 的标准不降低。它仍须在全部连续 change 的组合实现完成后，绑定最终 source revision、focused tests、strict OpenSpec、mainline、scope/forbidden audit 与 deferred production claims。只有该最终 receipt 才能声明 C2 acceptance；implementation snapshot 永远不能被升级、重命名或推断成 acceptance receipt。

## Risks / Trade-offs

- [C2到C3之间production agent不可运行] → projection和API明确显示 `provisioning_required`；实现阶段 snapshot 明确不是 production proof，最终 C2 receipt 诚实记录未证明production workspace/capsule，C3是恢复runnable状态的唯一successor。
- [长生命周期grant扩大credential泄露窗口] → lease不含secret；credential短期且audience-bound，revoke transaction同步停止续发并撤销可撤销credential。
- [executor profile被误读为HPC已可用] → C2 receipt和projection区分declared capability与provider readiness，明确remote HPC credential/CRUD/job未实现、未证明。
- [显式retirement增加一个lifecycle record] → 避免把普通 FAILED/COMPLETED/STOPPED误判为永久撤权；shutdown closure保持可审计。
- [exact revoke不自动级联可能留下active child] → 这是选定的隔离语义；需要级联时operator显式subtree，session/policy bulk继续覆盖其适用范围。
- [credential rotation导致动作失败] → 直接呈现认证错误；只允许后续显式动作重新签发，不自动重放effectful动作。

## Migration Plan

1. 验证C0与已落地C1 receipts，冻结authority matrix、closed capability profiles、delegation/target policy和C2 scope boundary。
2. 新增 lease、generation reservation/readiness、retirement request/proof/final record domain/repositories、单一forward migration、append-only events与唯一/transition/owner constraints；不修改现有runtime/execution/mutation/scientific owner。
3. 为agent creation/delegation登记generation reservation和`pending_workspace` lease；不从legacy sandbox回填ready/active facts。
4. 在runtime/restore/delegation入口立即启用active exact-generation validation。existing master/teammate在C3前显式non-runnable，projection给出provisioning blocker。
5. 将C1 repository credential production路径切到canonical lease validator及原子issuance/revoke；保留历史acceptance-only rows为审计记录，不将其升级为production lease。
6. 增加exact/bulk/explicit-subtree revoke与request-freeze/proof/finalize retirement lifecycle，并验证child不反向、parent exact revoke不隐式级联、旧 claimed occurrence 未结算时不能记录 proof 或完成 retirement。
7. 增加safe projection、failure tests与当前owner cross-product tests；publication只做negative structural proof，真实矩阵留C4。
8. 在连续迁移实现阶段生成非验收 `agent_capability_lease_implementation_snapshot@1`，只允许 C3 继续源码实现；它不授权实际 provisioning、lease activation、live 或外部 effect。
9. 全部连续 change 的组合实现完成后统一运行 C2 focused/strict/mainline/scope 验收；C2 acceptance 明确记录production Git workspace/capsule/network/toolchain、publication、remote HPC credential/CRUD、approval-free job及one-occurrence `sbatch`均未由 C2 单独证明。
10. 回滚时停止新issuance/activation并按明确scope撤销leases；已持久化reservation/lease/retirement/events保留审计，不恢复legacy fallback或重放失败动作。

## Open Questions

无。C2/C3 staged cutover、implementation snapshot 与 final acceptance 分离、immediate non-runnable gate、generation readiness seam、revocation topology、explicit retirement、budget ownership、publication deferment与验收声明均已裁决。
