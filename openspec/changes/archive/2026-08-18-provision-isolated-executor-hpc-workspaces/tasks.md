> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 1. 前置 change source-only gate

- [x] 1.1 纯读取核验 C1 immutable acceptance；对 C2 绑定当前 source snapshot/interface identity 和 deferred acceptance，明确它不证明真实 SSH credential provider、target authentication、OS/root isolation或native SSH/Git/LFS/rsync/scp/CRUD可用。
- [x] 1.2 绑定 C3/C4/C5 当前 source-only gates，确认 local generation、independent `.git`、private namespace、immutable publication refs、explicit fetch、standard LFS/actual-byte closure 的源码接口存在；不得据此 provision、publish、传输或宣称验收闭合。
- [x] 1.3 绑定 C7 revision-path handoff source-only gate 与当前 schema/service/migration identity，确认后续 HPC workspace 只消费 revision/file identity而不恢复artifact staging；不得据此发送handoff、完成task或读取生产内容。
- [x] 1.4 生成 `executor_hpc_workspace_source_only_dependency_gate@1`，绑定 C1 receipt、C2 snapshot、C3--C7 gates、当前 commit 与关键 runner baselines；仅允许继续源码、延后测试和文档，不授权 credential、SSH、Git/LFS network、remote root、runner、cleanup、scheduler、live/effect，正式 prerequisite receipt 延后至统一验收从 combined final source 重建。

## 2. ExecutorHpcWorkspace canonical model

- [x] 2.1 在 domain 中实现 versioned `ExecutorHpcWorkspace`，绑定 project repository binding、session、executor member、local workspace generation、target profile digest、remote generation、opaque handle、state/version和timestamps。
- [x] 2.2 增加 repository/migration/unique constraints，保证 exact tuple至多一个active remote workspace，generation replacement新建identity且旧record不可重绑、update owner或删除。
- [x] 2.3 实现 closed lifecycle transitions（provisioning、ready、invalid/missing、retention-eligible、cleaning、cleaned、reconciliation-required）与 optimistic version/fence checks，不从mutable remote marker反推canonical identity。
- [x] 2.4 实现 owner-authorized workspace projection：向拥有者返回usable login alias/path和safe Git/generation facts；向其他agent/public event只返回opaque id/state且隐藏credential、sidecar、其他路径。
- [x] 2.5 将 session end、agent retirement、lease revoke和generation replacement映射为“停止新admission + cleanup eligible”，证明它们不推断active job/transfer/process已settled。

## 3. Reliable remote provisioning 与 same-handle reconciliation

- [x] 3.1 扩展 trusted HPC target config，固定remote workspace root policy、target-native OS security principal/isolation mechanism、internal Git/LFS reachability、tool versions、真实credential provider/authenticator、sidecar root与target identity digest，RunSpec不得覆盖；仅配置声明不得通过activation。
- [x] 3.2 在Host任何SSH effect前持久化 immutable provision intent/idempotency key，并将provisioning作为canonical controlled external operation绑定owner、lease/fence和absolute deadline。
- [x] 3.3 在runner-private local/remote sidecar实现same-key compare-and-create、opaque path allocation、safe ownership/mode setup、independent clone、binding/base/remote verification和immutable provision receipt。
- [x] 3.4 实现accepted response丢失后的exact reconciler，只查询同一intent/key/handle/sidecar/path；matching receipt幂等adopt，conflict fail closed，unknown保持`dispatch_in_doubt`且零replacement create。
- [x] 3.5 增加runner/Host restart恢复与stale worker fencing，证明只有current execution owner可提交canonical workspace state，authoritative receipt不得被old callback覆盖。

## 4. Owner-scoped native HPC login data plane

- [x] 4.1 接入真实credential provider与target authenticator，实现绑定session、executor、target profile、local/remote generation、canonical root、lease id/version和login/file operation classes的短期SSH credential issuance/authentication/revocation；credential不得包含`scheduler.submit`/`sbatch` claim或落入workspace/public projection。
- [x] 4.2 在HPC login环境安装并资格验证native Git、Git LFS、OpenSSH、rsync、scp和shell工具，使clone使用session-pinned internal remote且不挂Host repo/home/SSH或runner-private metadata；在target OS principal/root层落实owner、mode/ACL/jail或等价强制隔离。
- [x] 4.3 将owner login alias/path/credential注入到executor capsule的scoped native view，使用真实native path证明SSH/rsync/scp/Git/LFS与create/read/update/delete直接运行而不调用Host typed transfer gateway或逐命令approval。
- [x] 4.4 增加native positive/negative qualification tests，覆盖跨executor、跨target、跨generation、stale/revoked credential、`..`/absolute path、symlink/hardlink、rsync/scp destination与sidecar tamper；任何失败不得改用shared account、alternate path、Host proxy或其他credential，mock/config-only proof不得激活target。
- [x] 4.5 证明native transfer、remote CRUD、local/private commit和private-ref push仅改变owner private state，不创建`PublishedRevision`、protocol handoff、task completion、artifact或job result。
- [x] 4.6 验证C2 exact/session-policy/subtree revoke的canonical结果会停止对应exact lease的新credential与connection admission且child revoke不反向影响parent；本change不得自行遍历genealogy，也不得把revoke推断为既有transfer/job settled。

## 5. Revision sync、drift handling 与 cleanup

- [x] 5.1 实现local/HPC login clone通过agent-private refs同步exact clean commits的路径，并验证private push/fetch不进入team projection、不force-update/delete既有checkpoint。
- [x] 5.2 实现authorized immutable publication ref fetch与commit/tree/LFS identity验证，保持checkout/merge/rebase/cherry-pick/conflict resolution为agent显式Git动作。
- [x] 5.3 实现formal sync/job前的exact root、owner、generation、repository binding、remote、`.git`和safe ownership检查；missing/corrupt/drift将workspace置为closed invalid状态且不same-generation reprovision。
- [x] 5.4 实现explicit higher-generation replacement flow，保留旧record/receipt并签发新lease/credential；禁止重命名旧root或把其他workspaceadopt为replacement。
- [x] 5.5 实现retention/cleanup exact-handle operation，删除或封存前重验无active controlled execution/unsettled effect并写immutable receipt；cleanup response loss只reconcile同一路径。

## 6. mcp-hpc-runner workspace cutover

- [x] 6.1 将runner provisioning/inspection API切换为exact executor workspace id/generation与opaque handle，删除new path中的artifact input、Host path、`stage_to`、catalog ref和`HpcStageRef`字段。
- [x] 6.2 删除per-run artifact staging、Host output-fetch publication、artifact-store manifest与对应stage/fetch callbacks/mutation writers，使job-specific目录只属于persistent executor workspace。
- [x] 6.3 将runner preflight、phase/effect journal、normalized result和transport diagnostics切换为workspace owner/generation/root/clone facts及safe opaque ids，不公开raw path给非owner。
- [x] 6.4 将provision/validation/lifecycle的runner-private ControlMaster与agent-native SSH sessions明确分离，补socket ownership/generation/shutdown tests，并证明agent login/file credential与runner transport credential都没有scheduler-submit authority；C9 payload只有额外present并consume exact one-occurrence credential后才能使用isolated runner channel调用`sbatch`。
- [x] 6.5 对旧artifact-staging RunSpec做versioned hard rejection，并在`execute-hpc-jobs-from-workspace-revisions`尚未完成时让current HPC job admission明确返回`workspace_revision_execution_required`；不得在本change提前实现one-occurrence `sbatch` credential、target unregistered-submit rejection、ordinary-job execution admission、双写或fallback到旧runner。

## 7. 验证、架构文档与 change receipt

- [x] 7.1 运行domain/repository、provision response-loss/restart、真实credential issuance/authentication/revoke、target OS/root owner isolation、native SSH/Git/LFS/rsync/scp/CRUD正反向、private/published sync、drift/replacement/cleanup、runner schema与no-stage/fetch focused tests及 touched Ruff/integration fixtures，并保存exact results；每个activated target必须有native proof而非config/mock assertion。
- [x] 7.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` control-plane/capability/runtime 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确owner-visible login locator、isolated remote clone、native data plane、same-handle provisioning与C9 admission gate。
- [x] 7.3 运行 `DO_NOT_TRACK=1 openspec validate provision-isolated-executor-hpc-workspaces --strict`、`git diff --check`、HpcStageRef/staging/fetch/Host-gateway/fallback audit 与 `./scripts/check-mainline.sh`，确认测试不触发真实HPC/live effect。
- [x] 7.4 生成并 pure-verify `provision-isolated-executor-hpc-workspaces` change receipt，绑定 prerequisite receipts、source/config/schema/migration digests、credential provider/authenticator、target-native OS/root与native CRUD qualification、focused/mainline/docs results和`implementation_complete=true`；receipt必须声明C2仅提供lease seam，且不得证明C9 job path、one-occurrence scheduler credential、unregistered-submit rejection、task/scientific completion或外部job settlement。（整改登记：[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
