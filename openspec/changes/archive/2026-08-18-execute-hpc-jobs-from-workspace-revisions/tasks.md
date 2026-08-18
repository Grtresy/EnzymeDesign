> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 0. 连续源码迁移 gate

- [x] 0.1 读取 C8、Git LFS、controlled-operation、scientific-attempt 与 runner 当前 source identities，确认正式 predecessor receipts 尚未生成且不得宣称 job route 已验收。
- [x] 0.2 生成 `workspace_revision_execution_source_only_dependency_gate@1`，只授权 domain/repository/migration/runner/Host/credential provider、延后测试与文档源码；明确禁止 compute-tree、credential、SSH、Slurm/direct payload、poll/cancel/reconcile、live/external effect 与 production activation。
- [x] 0.3 将 source-only gate 写入 proposal/design/spec，正式 1.1--1.4 prerequisite receipt 继续延后到 combined final source 的统一验收。

## 1. 前置 change receipts

- [x] 1.1 用 pure verifier 核验 `provision-isolated-executor-hpc-workspaces` change receipt，确认exact owner/generation、remote clone、native login data plane、same-handle provisioning/reconciliation及旧staging hard gate已闭合。
- [x] 1.2 用 pure verifier 核验 `support-git-lfs-work-products` change receipt，确认standard Git LFS endpoint、revision closure manifest、actual bytes verification、published pins 与 compute Gitless prerequisite已闭合。
- [x] 1.3 直接pure-verify `agent_capability_lease_acceptance@1`及C8传递的repository binding、independent workspace/publication chain，确认C2只提供canonical executor lease identity/status/profile seam，C8只提供native login/file credential与remote workspace；普通job automatic execution、scientific admitted-attempt gate和scheduler submit credential均不得被这些receipts提前宣称完成。
- [x] 1.4 生成并验证本 change 的 prerequisite receipt，绑定上述 receipts、当前 commit、design/spec digests，以及每个target对Slurm protected submit wrapper、one-occurrence credential原子consume、ambient/unregistered pre-scheduler rejection、unique marker/accounting和bounded direct SSH queryable process/terminal receipt的dispatch-ledger qualification inputs；缺失时不得构造compute tree或submit payload。

## 2. WorkspaceRevisionExecution admission 与 canonical ownership

- [x] 2.1 在domain/Host schema中实现versioned workspace-revision execution request，绑定operation/admission、executor lease、可选scientific `attempt_id`/`state_version`/`admission_request_id`/admission-request digest/source envelope与workflow-contract/scope/effect/HPC-target identity或独立operation approval、workspace id/generation、binding、source class、commit/tree/LFS manifest、clean observation、cwd、command/env/resources/mode/target/policy/deadline。
- [x] 2.2 修改`ControlledOperationExecution` route identity与repository constraints，保证每个logical job唯一owner且retry/recovery对authorization、workspace、revision、command、resources、target或deadline drift fail closed。
- [x] 2.3 由本change实现ordinary non-scientific executor job在C2 seam验证active exact lease与frozen route policy后create-or-read唯一dispatch-ready execution，不创建pending human approval；证明C2 receipt、role或retry counter本身都不构成job execution或ambient scheduler submit authority。
- [x] 2.4 实现local/canonical/remote login clone三方clean revision validator，覆盖HEAD/index/tracked/untracked、binding、commit/tree、attributes/LFS closure和normalized cwd；不stash、clean、commit、snapshot或substitute revision。
- [x] 2.5 实现private与published source class验证及immutability，允许policy内clean private job但不创建team publication，recovery不得在两种source class间替换。
- [x] 2.6 实现scientific route的exact admitted-attempt gate：绑定`ScientificAttempt.attempt_id`/`state_version`、`admission_request_id`与immutable `ScientificAttemptAdmissionRequest.request_digest`、source `envelope_id`及workflow-contract/scope/effect/HPC-target identity和current dispatch eligibility；覆盖source envelope因成功admit最后attempt而`EXHAUSTED`仍有效、无matching admitted attempt/admission request、identity drift或terminal-ineligible attempt零backend effect，且不得要求新`ACTIVE` envelope或从Slurm事实推断科学authority。

## 3. Login-side exact revision 到 Gitless compute tree

- [x] 3.1 实现login-side exact commit/tree/Git attributes遍历与LFS actual bytes验证，生成canonical sorted source manifest并绑定binding/policy/toolchain identity。
- [x] 3.2 实现server-issued job root、temporary tree materialization、fsync/atomic ready install和same-manifest idempotency，任何partial/mismatch tree不得进入dispatch-ready。
- [x] 3.3 实现normalized cwd映射、symlink/submodule containment与writable work/result directories，拒绝revision外path escape和mutable login-clone bytes。
- [x] 3.4 构建compute launch contract与fixtures，证明compute-visible tree无`.git`、Git/Git LFS binary、repository/SSH credential、runner sidecar、Host path或internal-remote access。
- [x] 3.5 实现verified compute-tree cache的exact binding/commit/LFS/toolchain/owner key与fresh validation，cache drift只失败且不改用login clone或artifact snapshot。

## 4. Unique dispatch ledger、ExternalJobHandle 与 reconciliation

- [x] 4.1 扩展target qualification，要求Slurm具备protected submit wrapper、runner-owned remote dispatch ledger、one-occurrence credential原子consume、ordinary login/ambient/unregistered submit在scheduler前拒绝、unique scheduler marker、atomic same-dispatch create和authoritative `squeue`/`sacct` terminal lookup，并要求bounded direct SSH具备同一ledger绑定的queryable remote process identity与authoritative terminal receipt；任一mode缺少合同即在dispatch前禁用且不降级。
- [x] 4.2 为Slurm和bounded direct SSH统一在任何payload前持久化immutable dispatch intent/id，并由remote wrapper compare-and-create单一ledger occurrence；accepted occurrence必须materialize绑定mode/process-or-scheduler identity的Host-private `ExternalJobHandle`。
- [x] 4.3 实现accepted-response/local-receipt gap的`dispatch_in_doubt` transition，只按same dispatch id/ledger/marker-or-process/handle reconcile；matching adopt、conflict fail、unprovable unknown且零replacement submit。
- [x] 4.4 实现Slurm scheduler handle与direct remote process handle的exact poll、bounded logs和append-only observation/terminal receipts，冻结absolute deadline并保证Host/runner restart不重置或创建第二run/job/process。
- [x] 4.5 实现explicit same-handle cancel effect与receipt，cancel request、SSH disconnect、controlled-operation execution lease expiry、capability lease 撤销或失活、以及 timeout 均不得冒充scheduler/process terminal settlement。（整改登记：[GAP-HPC-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 4.6 实现bounded direct SSH remote wrapper、process launch receipt、query/status/log/terminal receipt与restart reconciliation；无法产生queryable process/terminal receipt的target/mode必须qualification fail，不能接受后再以“无handle unknown”收尾或改用`sbatch`。
- [x] 4.7 实现runner-only one-occurrence scheduler credential：仅current execution owner/fence可在ledger原子reserve exact dispatch occurrence后签发，claims绑定execution/dispatch/target/reservation nonce/marker/payload digest/protected wrapper audience/expiry；target在native `sbatch`前原子validate+consume，并拒绝replay、expiry与任何identity drift。
- [x] 4.8 在target OS/submit-wrapper层拒绝C8 ordinary login/file credential、agent login shell、ambient runner credential和未登记dispatch id的Slurm submission；Host/runner不得扫描、adopt、cancel或attach绕过路径job，credential consume后的response loss只reconcile原ledger/marker/handle且不签发replacement occurrence。

## 5. Runner API、phase journal 与旧合同删除

- [x] 5.1 将RunSpec切换为workspace/revision/cwd/command/resources/target/deadline identity，并从current schema和tool surfaces删除artifact ids、Host paths、`stage_to`、`HpcStageRef`与`expected_outputs`。
- [x] 5.2 将runner `ssh`/`sbatch`/`auto` selection在dispatch前冻结，`auto`只选择已通过reliable-handle qualification的mode一次且recovery不得改变mode/backend。
- [x] 5.3 将runner preflight切换为workspace owner/generation、clean revision、LFS closure、compute source manifest、cwd/entrypoint/toolchain检查，deterministic failure保持`no_effect`且不repair workspace。
- [x] 5.4 将runner phase/effect journal切换为workspace validation、source preparation、preflight、dispatch intent、accepted/in-doubt、observation、terminal settlement，删除staging/fetch/output-validation/artifact-publication phases。
- [x] 5.5 删除public expected-output validation、declared-output fetch和artifact result RPC/SDK，stale clients明确schema rejection且不翻译成file scan或alternate request。

## 6. Workspace job result 与业务状态分离

- [x] 6.1 实现immutable workspace job result identity，绑定operation/execution、opaque run、terminal receipt/status/exit、source revision/manifest、workspace generation、job root/cwd、command/resource/target digests和timestamps。
- [x] 6.2 删除controlled-operation current artifact-set/result-artifact fields/writers，并让ordinary result files留在executor remote workspace，不自动enumerate、fetch、commit或publish。
- [x] 6.3 实现owner通过native SSH/rsync/scp检查/下载结果文件的路径，证明transfer不会重新dispatch payload、创建output-fetch phase或改变canonical result。
- [x] 6.4 实现agent显式提交result files后可选exact result-revision link，link不得修改原job outcome、自动`workspace.publish`或adoptmutable path。
- [x] 6.5 更新continuation、wakeup、task/report/scientific consumers与safe projection，证明job terminal/result delivery不机械complete/fail/block/cancel/resume task或scientific attempt。
- [x] 6.6 实现restart matrix：proven pre-dispatch继续、in-doubt reconcile、accepted handle poll、terminal result redelivery、legacy无handle/revision row明确non-resumable，零synthetic receipt或fallback。（整改登记：[GAP-HPC-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）

## 7. Migration 与 current cutover

- [x] 7.1 增加workspace job/scientific admitted-attempt basis/dispatch intent/credential occurrence/handle/observation/result migrations、immutability/owner-match/fence triggers与rollback guards，旧artifact/expected-output rows保持historical且不可current replay。
- [x] 7.2 将Host API、engine adapters、pipeline SDK、worker、events和workspace projection一次性切到new job schema，禁止dual writer、missing-new-field fallback和legacy synchronous dispatch。
- [x] 7.3 审计并删除current production path中`expected_outputs`、artifact staging/fetch/materialization与replacement submit branches，保留的历史reader必须隔离于current admission。
- [x] 7.4 建立target-by-target、mode-by-mode activation gate：Slurm需protected wrapper、reservation-bound one-occurrence credential原子consume/replay rejection、ordinary/ambient/unregistered pre-scheduler denial、unique marker/ledger和authoritative accounting，direct需queryable process/terminal receipt；任一资格失败保持该mode explicit unavailable且不切换替代mode。

## 8. 验证、架构文档与 change receipt

- [x] 8.1 运行ordinary no-human-approval canonical execution、scientific admitted attempt/source-envelope `EXHAUSTED`/missing-or-drifted attempt、clean/private/published revision、dirty/drift、LFS closure/Gitless tree、duplicate worker、Slurm/direct dispatch response loss、marker/process conflict、poll/cancel/restart/deadline、direct handle qualification failure、ordinary login/ambient/未登记Slurm submit拒绝、one-occurrence credential consume/replay/mismatch、no-scheduler-scan-adoption、no-expected-output和task-separation focused tests及 touched Ruff/integration fixtures，并保存exact results。（整改登记：[GAP-HPC-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 8.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` execution/reliability/control-plane/runtime 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确clean revision、Gitless compute、Slurm/direct可靠ExternalJobHandle、runner-only one-occurrence scheduler authority、no-blind-resubmit、无expected_outputs/stage/fetch及普通job无逐job审批。
- [x] 8.3 运行 `DO_NOT_TRACK=1 openspec validate execute-hpc-jobs-from-workspace-revisions --strict`、`git diff --check`、forbidden artifact/HpcStageRef/expected_outputs/fetch/fallback/replacement-submit/unhandled-direct/ambient-scheduler-authority audit 与 `./scripts/check-mainline.sh`，不触发真实HPC/live effect。
- [x] 8.4 生成并 pure-verify `execute-hpc-jobs-from-workspace-revisions` change receipt，绑定C2/C8 seams、ordinary automatic execution proof、scientific admitted-attempt proof、scheduler credential occurrence/target rejection qualification、source/schema/migration/target-profile digests、focused/mainline/docs results、dispatch/recovery invariants和`implementation_complete=true`；receipt不得把C2/C8当作job implementation，也不得证明任何真实job已运行或task/scientific outcome成立。（整改登记：[GAP-HPC-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
