## 1. 前置 change receipts

- [ ] 1.1 用 pure verifier 核验 `provision-isolated-executor-hpc-workspaces` change receipt，确认exact owner/generation、remote clone、native login data plane、same-handle provisioning/reconciliation及旧staging hard gate已闭合。
- [ ] 1.2 用 pure verifier 核验 `support-git-lfs-work-products` change receipt，确认standard Git LFS endpoint、revision closure manifest、actual bytes verification、published pins 与 compute Gitless prerequisite已闭合。
- [ ] 1.3 重验C8 receipt传递的repository binding、capability lease、independent local workspace和publication receipt chain，确认普通job无逐job人工approval且科学workflow的独立authorization仍为closed gate。
- [ ] 1.4 生成并验证本 change 的 prerequisite receipt，绑定上述 receipts、当前 commit、design/spec digests，以及每个target对Slurm unique marker/accounting和bounded direct SSH queryable process/terminal receipt的dispatch-ledger qualification inputs；缺失时不得构造compute tree或submit payload。

## 2. WorkspaceRevisionExecution admission 与 canonical ownership

- [ ] 2.1 在domain/Host schema中实现versioned workspace-revision execution request，绑定operation/admission、executor lease、可选required authorization、workspace id/generation、binding、source class、commit/tree/LFS manifest、clean observation、cwd、command/env/resources/mode/target/policy/deadline。
- [ ] 2.2 修改`ControlledOperationExecution` route identity与repository constraints，保证每个logical job唯一owner且retry/recovery对authorization、workspace、revision、command、resources、target或deadline drift fail closed。
- [ ] 2.3 实现ordinary non-scientific executor job在active lease/route policy内自动创建dispatch-ready execution，不创建pending human approval；明确required scientific/operation authorization未批准时零backend effect，同时证明该lease不直接授予ambient scheduler submit authority。
- [ ] 2.4 实现local/canonical/remote login clone三方clean revision validator，覆盖HEAD/index/tracked/untracked、binding、commit/tree、attributes/LFS closure和normalized cwd；不stash、clean、commit、snapshot或substitute revision。
- [ ] 2.5 实现private与published source class验证及immutability，允许policy内clean private job但不创建team publication，recovery不得在两种source class间替换。

## 3. Login-side exact revision 到 Gitless compute tree

- [ ] 3.1 实现login-side exact commit/tree/Git attributes遍历与LFS actual bytes验证，生成canonical sorted source manifest并绑定binding/policy/toolchain identity。
- [ ] 3.2 实现server-issued job root、temporary tree materialization、fsync/atomic ready install和same-manifest idempotency，任何partial/mismatch tree不得进入dispatch-ready。
- [ ] 3.3 实现normalized cwd映射、symlink/submodule containment与writable work/result directories，拒绝revision外path escape和mutable login-clone bytes。
- [ ] 3.4 构建compute launch contract与fixtures，证明compute-visible tree无`.git`、Git/Git LFS binary、repository/SSH credential、runner sidecar、Host path或internal-remote access。
- [ ] 3.5 实现verified compute-tree cache的exact binding/commit/LFS/toolchain/owner key与fresh validation，cache drift只失败且不改用login clone或artifact snapshot。

## 4. Unique dispatch ledger、ExternalJobHandle 与 reconciliation

- [ ] 4.1 扩展target qualification，要求Slurm具备runner-owned remote dispatch ledger、unique scheduler marker、atomic same-dispatch create和authoritative `squeue`/`sacct` terminal lookup，并要求bounded direct SSH具备同一ledger绑定的queryable remote process identity与authoritative terminal receipt；任一mode缺少可靠handle/reconcile能力即在dispatch前禁用该mode且不降级。
- [ ] 4.2 为Slurm和bounded direct SSH统一在任何payload前持久化immutable dispatch intent/id，并由remote wrapper compare-and-create单一ledger occurrence；accepted occurrence必须materialize绑定mode/process-or-scheduler identity的Host-private `ExternalJobHandle`。
- [ ] 4.3 实现accepted-response/local-receipt gap的`dispatch_in_doubt` transition，只按same dispatch id/ledger/marker-or-process/handle reconcile；matching adopt、conflict fail、unprovable unknown且零replacement submit。
- [ ] 4.4 实现Slurm scheduler handle与direct remote process handle的exact poll、bounded logs和append-only observation/terminal receipts，冻结absolute deadline并保证Host/runner restart不重置或创建第二run/job/process。
- [ ] 4.5 实现explicit same-handle cancel effect与receipt，cancel request、SSH disconnect、lease expiry或timeout均不得冒充scheduler/process terminal settlement。
- [ ] 4.6 实现bounded direct SSH remote wrapper、process launch receipt、query/status/log/terminal receipt与restart reconciliation；无法产生queryable process/terminal receipt的target/mode必须qualification fail，不能接受后再以“无handle unknown”收尾或改用`sbatch`。
- [ ] 4.7 将普通executor login/file credential与scheduler submit authority分离：只有runner对frozen dispatch occurrence签发的one-occurrence credential可调用native `sbatch`，target必须拒绝agent login shell、ambient credential或未登记dispatch id发起的直接Slurm submission。

## 5. Runner API、phase journal 与旧合同删除

- [ ] 5.1 将RunSpec切换为workspace/revision/cwd/command/resources/target/deadline identity，并从current schema和tool surfaces删除artifact ids、Host paths、`stage_to`、`HpcStageRef`与`expected_outputs`。
- [ ] 5.2 将runner `ssh`/`sbatch`/`auto` selection在dispatch前冻结，`auto`只选择已通过reliable-handle qualification的mode一次且recovery不得改变mode/backend。
- [ ] 5.3 将runner preflight切换为workspace owner/generation、clean revision、LFS closure、compute source manifest、cwd/entrypoint/toolchain检查，deterministic failure保持`no_effect`且不repair workspace。
- [ ] 5.4 将runner phase/effect journal切换为workspace validation、source preparation、preflight、dispatch intent、accepted/in-doubt、observation、terminal settlement，删除staging/fetch/output-validation/artifact-publication phases。
- [ ] 5.5 删除public expected-output validation、declared-output fetch和artifact result RPC/SDK，stale clients明确schema rejection且不翻译成file scan或alternate request。

## 6. Workspace job result 与业务状态分离

- [ ] 6.1 实现immutable workspace job result identity，绑定operation/execution、opaque run、terminal receipt/status/exit、source revision/manifest、workspace generation、job root/cwd、command/resource/target digests和timestamps。
- [ ] 6.2 删除controlled-operation current artifact-set/result-artifact fields/writers，并让ordinary result files留在executor remote workspace，不自动enumerate、fetch、commit或publish。
- [ ] 6.3 实现owner通过native SSH/rsync/scp检查/下载结果文件的路径，证明transfer不会重新dispatch payload、创建output-fetch phase或改变canonical result。
- [ ] 6.4 实现agent显式提交result files后可选exact result-revision link，link不得修改原job outcome、自动`workspace.publish`或adoptmutable path。
- [ ] 6.5 更新continuation、wakeup、task/report/scientific consumers与safe projection，证明job terminal/result delivery不机械complete/fail/block/cancel/resume task或scientific attempt。
- [ ] 6.6 实现restart matrix：proven pre-dispatch继续、in-doubt reconcile、accepted handle poll、terminal result redelivery、legacy无handle/revision row明确non-resumable，零synthetic receipt或fallback。

## 7. Migration 与 current cutover

- [ ] 7.1 增加workspace job/dispatch intent/handle/observation/result migrations、immutability/owner-match/fence triggers与rollback guards，旧artifact/expected-output rows保持historical且不可current replay。
- [ ] 7.2 将Host API、engine adapters、pipeline SDK、worker、events和workspace projection一次性切到new job schema，禁止dual writer、missing-new-field fallback和legacy synchronous dispatch。
- [ ] 7.3 审计并删除current production path中`expected_outputs`、artifact staging/fetch/materialization与replacement submit branches，保留的历史reader必须隔离于current admission。
- [ ] 7.4 建立target-by-target、mode-by-mode activation gate：Slurm需unique marker/ledger、authoritative accounting和one-occurrence submit credential，direct需queryable process/terminal receipt；任一资格失败保持该mode explicit unavailable且不切换替代mode。

## 8. 验证、架构文档与 change receipt

- [ ] 8.1 运行clean/private/published revision、dirty/drift、LFS closure/Gitless tree、duplicate worker、Slurm/direct dispatch response loss、marker/process conflict、poll/cancel/restart/deadline、direct handle qualification failure、ambient/未登记Slurm submit拒绝、one-occurrence credential、no-expected-output和task-separation focused tests及 touched Ruff/integration fixtures，并保存exact results。
- [ ] 8.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` execution/reliability/control-plane/runtime 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确clean revision、Gitless compute、Slurm/direct可靠ExternalJobHandle、runner-only one-occurrence scheduler authority、no-blind-resubmit、无expected_outputs/stage/fetch及普通job无逐job审批。
- [ ] 8.3 运行 `DO_NOT_TRACK=1 openspec validate execute-hpc-jobs-from-workspace-revisions --strict`、`git diff --check`、forbidden artifact/HpcStageRef/expected_outputs/fetch/fallback/replacement-submit/unhandled-direct/ambient-scheduler-authority audit 与 `./scripts/check-mainline.sh`，不触发真实HPC/live effect。
- [ ] 8.4 生成并 pure-verify `execute-hpc-jobs-from-workspace-revisions` change receipt，绑定 prerequisite receipts、source/schema/migration/target-profile digests、focused/mainline/docs results、dispatch/recovery invariants和`implementation_complete=true`；receipt 不得证明任何真实job已运行或task/scientific outcome成立。
