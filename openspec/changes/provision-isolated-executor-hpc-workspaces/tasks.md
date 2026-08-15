## 1. 前置 change receipts

- [ ] 1.1 用 pure verifier 核验 `establish-project-repository-bindings` 与 `establish-agent-capability-leases` change receipts，确认 pinned internal remote、target-scoped executor scope、native SSH/Git/LFS/rsync/scp 与无逐命令 approval 已闭合。
- [ ] 1.2 用 pure verifier 核验 `provision-independent-agent-git-workspaces` 与 `publish-and-sync-workspace-revisions` change receipts，确认 local generation、independent `.git`、private namespace、immutable publication refs与 explicit fetch 已闭合。
- [ ] 1.3 用 pure verifier 核验 `support-git-lfs-work-products` change receipt，确认 standard LFS endpoint、actual-byte closure、native HPC-login client 与 compute Gitless contract 已闭合；只存在 interface draft 或并行实现不得满足该 gate。
- [ ] 1.4 生成并验证本 change 的 prerequisite receipt，绑定五个前置 receipts、当前 commit、design/spec digests 与 HPC target qualification inputs；缺失时不得 provision remote root、签发 SSH credential或启用runner workspace mode。

## 2. ExecutorHpcWorkspace canonical model

- [ ] 2.1 在 domain 中实现 versioned `ExecutorHpcWorkspace`，绑定 project repository binding、session、executor member、local workspace generation、target profile digest、remote generation、opaque handle、state/version和timestamps。
- [ ] 2.2 增加 repository/migration/unique constraints，保证 exact tuple至多一个active remote workspace，generation replacement新建identity且旧record不可重绑、update owner或删除。
- [ ] 2.3 实现 closed lifecycle transitions（provisioning、ready、invalid/missing、retention-eligible、cleaning、cleaned、reconciliation-required）与 optimistic version/fence checks，不从mutable remote marker反推canonical identity。
- [ ] 2.4 实现 owner-authorized workspace projection：向拥有者返回usable login alias/path和safe Git/generation facts；向其他agent/public event只返回opaque id/state且隐藏credential、sidecar、其他路径。
- [ ] 2.5 将 session end、agent retirement、lease revoke和generation replacement映射为“停止新admission + cleanup eligible”，证明它们不推断active job/transfer/process已settled。

## 3. Reliable remote provisioning 与 same-handle reconciliation

- [ ] 3.1 扩展 trusted HPC target config，固定remote workspace root policy、OS principal、internal Git/LFS reachability、tool versions、credential provider、sidecar root与target identity digest，RunSpec不得覆盖。
- [ ] 3.2 在Host任何SSH effect前持久化 immutable provision intent/idempotency key，并将provisioning作为canonical controlled external operation绑定owner、lease/fence和absolute deadline。
- [ ] 3.3 在runner-private local/remote sidecar实现same-key compare-and-create、opaque path allocation、safe ownership/mode setup、independent clone、binding/base/remote verification和immutable provision receipt。
- [ ] 3.4 实现accepted response丢失后的exact reconciler，只查询同一intent/key/handle/sidecar/path；matching receipt幂等adopt，conflict fail closed，unknown保持`dispatch_in_doubt`且零replacement create。
- [ ] 3.5 增加runner/Host restart恢复与stale worker fencing，证明只有current execution owner可提交canonical workspace state，authoritative receipt不得被old callback覆盖。

## 4. Owner-scoped native HPC login data plane

- [ ] 4.1 实现绑定executor、target、remote generation和lease lifecycle的短期SSH credential issuance/revocation，并在remote OS/account/root层拒绝跨agent与跨generation访问。
- [ ] 4.2 在HPC login环境安装并资格验证native Git、Git LFS、OpenSSH、rsync、scp和shell工具，使clone使用session-pinned internal remote且不挂Host repo/home/SSH或runner-private metadata。
- [ ] 4.3 将owner login alias/path/credential注入到executor capsule的scoped native view，证明SSH/rsync/scp/Git/LFS直接运行而不调用Host typed transfer gateway或逐命令approval。
- [ ] 4.4 增加跨executor、跨target、跨generation、stale/revoked credential与sidecar tamper隔离测试，任何失败不得改用shared account、alternate path、Host proxy或其他credential。
- [ ] 4.5 证明native transfer、remote CRUD、local/private commit和private-ref push仅改变owner private state，不创建`PublishedRevision`、protocol handoff、task completion、artifact或job result。

## 5. Revision sync、drift handling 与 cleanup

- [ ] 5.1 实现local/HPC login clone通过agent-private refs同步exact clean commits的路径，并验证private push/fetch不进入team projection、不force-update/delete既有checkpoint。
- [ ] 5.2 实现authorized immutable publication ref fetch与commit/tree/LFS identity验证，保持checkout/merge/rebase/cherry-pick/conflict resolution为agent显式Git动作。
- [ ] 5.3 实现formal sync/job前的exact root、owner、generation、repository binding、remote、`.git`和safe ownership检查；missing/corrupt/drift将workspace置为closed invalid状态且不same-generation reprovision。
- [ ] 5.4 实现explicit higher-generation replacement flow，保留旧record/receipt并签发新lease/credential；禁止重命名旧root或把其他workspaceadopt为replacement。
- [ ] 5.5 实现retention/cleanup exact-handle operation，删除或封存前重验无active controlled execution/unsettled effect并写immutable receipt；cleanup response loss只reconcile同一路径。

## 6. mcp-hpc-runner workspace cutover

- [ ] 6.1 将runner provisioning/inspection API切换为exact executor workspace id/generation与opaque handle，删除new path中的artifact input、Host path、`stage_to`、catalog ref和`HpcStageRef`字段。
- [ ] 6.2 删除per-run artifact staging、Host output-fetch publication、artifact-store manifest与对应stage/fetch callbacks/mutation writers，使job-specific目录只属于persistent executor workspace。
- [ ] 6.3 将runner preflight、phase/effect journal、normalized result和transport diagnostics切换为workspace owner/generation/root/clone facts及safe opaque ids，不公开raw path给非owner。
- [ ] 6.4 将provision/validation/payload/lifecycle的runner-private ControlMaster与agent-native SSH sessions明确分离，补socket ownership/generation/shutdown/ambiguous process tests。
- [ ] 6.5 对旧artifact-staging RunSpec做versioned hard rejection，并在`execute-hpc-jobs-from-workspace-revisions`尚未完成时让current HPC job admission明确返回`workspace_revision_execution_required`，不得双写或fallback到旧runner。

## 7. 验证、架构文档与 change receipt

- [ ] 7.1 运行domain/repository、provision response-loss/restart、owner isolation、native SSH/Git/LFS/rsync/scp、private/published sync、drift/replacement/cleanup、runner schema与no-stage/fetch focused tests及 touched Ruff/integration fixtures，并保存exact results。
- [ ] 7.2 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` control-plane/capability/runtime 文档、`docs/v3/execution-pipeline-docs/README.md` 与 `docs/v3/harness-complexity-audit.md`，明确owner-visible login locator、isolated remote clone、native data plane、same-handle provisioning与C9 admission gate。
- [ ] 7.3 运行 `DO_NOT_TRACK=1 openspec validate provision-isolated-executor-hpc-workspaces --strict`、`git diff --check`、HpcStageRef/staging/fetch/Host-gateway/fallback audit 与 `./scripts/check-mainline.sh`，确认测试不触发真实HPC/live effect。
- [ ] 7.4 生成并 pure-verify `provision-isolated-executor-hpc-workspaces` change receipt，绑定 prerequisite receipts、source/config/schema/migration digests、target qualification、focused/mainline/docs results和`implementation_complete=true`；receipt 不得证明C9 job path、task/scientific completion或外部job settlement。
