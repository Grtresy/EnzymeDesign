> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 1. C2 前置 receipts、scope 与 authority gate

- [x] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1` receipt、source revision和legacy NO-GO；缺失或漂移时停止C2，且不得借C2启动任何AOX live工作。
- [x] 1.2 验证已落地的 `project_repository_binding_acceptance@1` receipt、C1 source/code/schema/policy digests及`production_capability_lease_issuance_proven=false`边界；拒绝把C1 acceptance-only assertion/hold升级成production lease事实。
- [x] 1.3 生成authority matrix receipt，记录 `SessionRuntimeLease`、`ControlledOperationExecution` lease/fence、mutation writer、approval与`ScientificAttemptAuthorization`的owner/lifecycle；明确scientific ceilings属于`ScientificAttemptAuthorization`，prompt/context/step budget只是机械约束，当前不存在万能budget owner。
- [x] 1.4 冻结closed general/executor capability profiles、role/allowed-child-profile map、safe target scope与policy digest；general声明filesystem、shell、Git/LFS、ordinary network、upload/download，executor额外声明scoped SSH、rsync/scp、HPC login CRUD和Slurm operations。
- [x] 1.5 生成C2 scope-boundary receipt：C2只实现lease/control-plane/policy/credential/admission seams与immediate runtime gate；不实现C3 clone/capsule/network/toolchain、C4 publication、真实远程HPC credential/CRUD、approval-free job admission或one-occurrence `sbatch`。
- [x] 1.6 固定staged cutover：从C2起所有agent runtime/delegation要求active exact-generation lease；C3未ready前existing/new agent都显式`provisioning_required`、non-runnable，不保留legacy sandbox/parent capsule/local execution fallback。
- [x] 1.7 定义非验收 `agent_capability_lease_implementation_snapshot@1`：它只允许固定顺序的 C3 继续源码实现，必须声明 acceptance/final-source/effect/live 均未证明，不能替代最终 receipt、runtime authority 或 production gate。

## 2. Lease、generation readiness 与 retirement domain/migration

- [x] 2.1 在 `openzyme-domain` 增加closed capability/profile/lease-status/revocation-scope/revocation-reason/event enums与`AgentCapabilityLease`；status固定为`pending_workspace | active | revoked`，identity绑定lease/session/internal member/public agent/generation/profile/set/target/policy/parent/idempotency及lifecycle facts。
- [x] 2.2 增加最小 `AgentWorkspaceGenerationReservation` / readiness domain与repository seam，只记录generation reservation、单调replacement和typed readiness owner/ref/digest；禁止存储或声称clone path、volume、`.git`、HEAD、capsule、network或toolchain事实。
- [x] 2.3 增加immutable `AgentRetirementRequest`、cleanup proof record与最终 `AgentRetirementRecord` / shutdown-completed fact，精确绑定current generation/lease、request/provider/proof、actor/reason/time/digest；明确`FAILED`、`COMPLETED`、`STOPPED`、task terminal、runtime failure或单独shutdown request都不构成retirement。
- [x] 2.4 添加单一forward SQL migration，建立generation reservations、lease records、append-only lifecycle events与retirement request/proof/final records；增加owner identity、严格递增generation、每个`session + member + generation`唯一lease、每agent单一active lease、immutable fingerprint、state transition和parent/child provenance constraints；为`agent_runtime_signals`增加不可变、成对的lease/generation occurrence binding，历史未绑定signal保留但不可claim。
- [x] 2.5 为migration后的新repository credential rows和`active_capability_lease` holds增加canonical lease owner triggers，同时保留C1历史acceptance-only rows为不可升级的审计事实；不得添加会使038历史数据迁移失败的追溯FK。
- [x] 2.6 增加domain/migration/repository focused tests，覆盖closed enum、pending/active/revoked invariants、duplicate generation、identity/profile/target/policy drift、cross-agent owner、append-only events、invalid retirement和038→新migration兼容性。

## 3. Issuance、activation 与 revoke lifecycle services

- [x] 3.1 实现generation reservation与一次性issuance service：相同immutable fingerprint重放返回同一pending或active lease；generation/profile/set/target/policy/parent任一漂移显式冲突且不创建替代lease。
- [x] 3.2 实现registered readiness provider seam与`pending_workspace -> active`原子transition；只有exact reservation的verified owner/ref/digest可激活，C2 production composition在C3 provider缺失时只能保持pending/provisioning-required。
- [x] 3.3 实现active-lease validator，精确校验lease/session/member/public agent/generation/profile/capability/target/policy/retirement状态；不得从runtime lease、PID、tool exposure、namespace hold、legacy sandbox或ambient config推断。
- [x] 3.4 实现revoke topology：ordinary explicit revoke默认exact；session end按session bulk；policy invalidation按matching policy scope bulk；canonical agent retirement撤销该exact member跨generation的全部pending/active leases；workspace replacement只撤销旧generation；operator只有显式scope时可subtree revoke；parent exact revoke不自动级联，child不反向影响parent/siblings。
- [x] 3.5 在一个write transaction中完成停止credential issuance、撤销可撤销derived credentials、释放matching holds、写revoked state和append-only event；任一步失败整笔rollback，禁止silent partial closure。
- [x] 3.6 实现explicit retirement lifecycle：request/proof/final三相分别要求service-only transaction-local exact authority；先提交exact request admission freeze，所有claimed迁移要求原`SessionRuntimeLease` fence，拒绝claimed signal存在时持久化cleanup proof或finalize，再在最终transaction重验request/proof/零claim、写`AgentRetirementRecord`并撤销该exact agent member的全部pending/active leases；增加issuance/activation/revoke/session bulk/policy bulk/subtree/replacement/retirement/file-backed concurrency focused tests。

## 4. Immediate runtime/delegation gate 与 credential/admission seams

- [x] 4.1 在每个agent runtime claim/turn/capsule-facing admission前按current `session + member + generation`重读canonical active lease与retirement-request freeze；`SessionRuntimeLease`只拥有scheduler推进权，不能绕过provisioning或retirement gate。
- [x] 4.2 在session/runtime restore中不复制旧turn/process authority；existing master/teammate缺ready generation或active lease时投影`provisioning_required`并保持non-runnable，runtime signal不得被claim/run，也不得采用legacy workspace fallback。
- [x] 4.3 在delegation入口先校验parent exact active lease；允许原子创建child identity、generation reservation与derived pending lease intent，但child ready/active前不得排入runnable wakeup或借parent capsule/token/workspace/credential执行。
- [x] 4.4 将C1 `RepositoryCredentialBroker` production路径从caller构造的`ActiveCapabilityLeaseAssertion`升级为同一`BEGIN IMMEDIATE` transaction中canonical lease validation + session pin + namespace/hold + issuance record；transaction commit后才返回bearer。
- [x] 4.5 令Git/LFS read和write authentication都重读canonical active lease；credential TTL仅结束credential，lease revoke transaction撤销credential/hold，后续显式重签不得自动replay先前失败命令。
- [x] 4.6 定义后继service可消费的typed credential/admission port与claims/error model，但不接入真实SSH/HPC issuer、远程CRUD、scheduler submit、automatic job execution或one-occurrence `sbatch`；增加runtime/delegation/repository-credential focused tests验证无side effect/fallback/implicit approval变化。

## 5. Projection、authority 正交与 failure semantics

- [x] 5.1 增加safe Host API/workspace projection，只公开lease id、public owner、generation reservation/readiness status、closed capability names、safe target identity/digest、policy digest、parent provenance、lifecycle/revocation/retirement facts；隐藏bearer、signing material、private namespace/service locator和Host path。
- [x] 5.2 为missing reservation/readiness、pending、missing/revoked/mismatched lease、retired agent、credential rejection和policy drift定义stable typed errors；核心缺口统一呈现`provisioning_required`与non-runnable事实。
- [x] 5.3 增加当前owner authority cross-product tests，逐项证明capability lease与runtime claim、mutation writer、execution owner/fence及scientific authorization互不替代；capability lease不得自动创建`ControlledOperationExecution`或修改任何execution状态。
- [x] 5.4 增加budget ownership tests：active lease不扩大/绕过prompt、context或step机械bounds，也不创建、消费或调整`ScientificAttemptAuthorization`中的attempt/MICU/cost/wall-time ceilings；反向也不产生lease。
- [x] 5.5 增加publication structural negative tests：C2不得定义/写入`WorkspacePublicationIntent`、`PublishedRevision`、publication ref/effect或shared-truth projection；真实`capability × publication intent × execution`矩阵明确留给C4。
- [x] 5.6 增加failure-path tests，证明所有typed failure不触发silent retry、route/workspace/endpoint fallback、local/parent substitution、profile downgrade/upgrade、approval reopen、budget increase、command replay或automatic task transition。

## 6. 最终统一验证、文档与 C2 acceptance receipt

- [x] 6.1 在全部连续 change 组合实现完成后运行domain/core/Host focused tests，覆盖generation reservation、pending/active/revoked lifecycle、immediate non-runnable runtime/delegation gate、explicit retirement、exact/bulk/subtree revoke、C1 credential原子升级、安全projection与authority/budget/publication negative matrices。
- [x] 6.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/02-control-plane.md`、`docs/v3/03-capability-engines.md`、`docs/v3/05-agent-runtime.md` 与repository operations文档，记录C2 staged cutover、C3 readiness owner、non-runnable窗口、revocation topology、retirement及deferred capabilities。
- [x] 6.3 在最终统一验收阶段运行 `DO_NOT_TRACK=1 openspec validate establish-agent-capability-leases --type change --strict --no-interactive` 并保存通过结果。
- [x] 6.4 在最终统一验收阶段运行 `./scripts/check-mainline.sh`，确认无live/provider/HPC opt-in；不得以test readiness、legacy sandbox、manual approval、temporary provider或fallback route掩盖production provisioning缺口。
- [x] 6.5 在最终组合源码上审计Git diff、migration、runtime/delegation admission、credential/redaction、projection和forbidden symbols/call sites，确认后继实现没有弱化existing execution/scientific fences，且任何超出 C2 owner 的能力只由其指定后继 change 拥有。
- [x] 6.6 最终统一验收全部通过后生成immutable `agent_capability_lease_acceptance@1` receipt，绑定C0与C1 receipts、最终 source revision、authority/scope matrices、code/schema/policy digests、focused tests、docs、strict OpenSpec和mainline；显式记录C2自身未单独证明的production能力，并与实现期 snapshot 保持不可升级、不可替代关系。（整改登记：[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
