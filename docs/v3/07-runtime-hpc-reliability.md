# V3 Runtime 与 HPC Reliability

## Authority 分层

session runtime lease、agent process epoch、controlled-operation execution fence、continuation delivery
fence、executor workspace generation、scheduler occurrence credential 和 mutation writer fence 相互独立。
任何跨层借权均拒绝。

## Executor workspace

`ExecutorHpcWorkspace` 绑定 project/session/executor member、target qualification、generation 和 root identity。
login/file credential 只允许 owner root 内 SSH、Git/LFS、rsync/scp 和 CRUD，不包含 scheduler submit。
其他 owner/generation、runner sidecar 和 Host path 不可见。

`hpc.workspace.sync_source` 只准备 exact private checkpoint 或 immutable publication；fetch、checkout、merge、
rebase 和冲突处理由 agent 显式决定。它不发布 revision、不完成 task，也不提交 job。

## Job admission

`workspace_revision_execution_request@1` 必须绑定 exact source revision、commit/tree、LFS closure、clean
observation、cwd、command、environment、resources、target/runner policy、executor lease/generation、operation/
execution identity 和 absolute deadline。formal scientific job 还绑定 attempt admission 与 workflow digest。

admission 后 Host 发放一次 scheduler occurrence credential。runner 从 revision 构造 compute source manifest；
payload 不携带 `.git`、repository credential、LFS endpoint、object-store locator 或 Host path。

## Runner lifecycle

公开 runner handle 是 server-issued opaque `run_id`。raw Slurm job id、remote directory 和 recovery RunSpec
不跨边界。dispatch 前 crash 可证明 `no_effect`；payload 已交给 transport 但 receipt 未落盘则
`dispatch_in_doubt`，只能 query/reconcile exact occurrence。

observe、logs、cancel 都必须匹配 occurrence credential 和 opaque handle。cancel intent 不等于 backend 已
取消；cancellation receipt 使用唯一 canonical wire contract，必须包含 `receipt_id`、cancellation/handle
identity、requested/settlement facts、backend receipt digest、时间与完整 receipt digest。只有经过 exact
parser/serializer 校验的 receipt/observation 可更新 effect certainty。dispatch、observe、cancel 与
reconcile replay 在返回持久化对象前重新比对当前 RunSpec、dispatch intent、handle 和 digest；不匹配时
在 backend action 前失败。

## Results

terminal success 形成 `WorkspaceJobResult`，可选择绑定 result revision。runner 不声明、枚举或验证
`expected_outputs`；结果文件留在 owner executor workspace，由 agent 通过原生 SSH/rsync/scp 检查并
显式形成新的 clean result revision。job 可以在没有结果文件时成功，但仍需要 terminal observation、
result digest 和 lifecycle receipt；不得创建占位文件、自动 fetch/commit/publish 或从文件存在推断成功。

## Restart

restart 从 durable dispatch intent、handle、observation、deadline 和 fence 恢复，不重新 submit。lease expiry
只允许另一个 worker 认领同一 occurrence。absolute deadline 不因 restart 重置。

## Mutation quiescence

迁移/发布或 scientific closure 需要时，mutation scope 先 freeze admission，再等待所有显式 writer/descendant
带 terminal proof 退休，获取两次一致的 SQLite/event/file high-watermark snapshot，最后签发 immutable
quiescence receipt。空队列、runtime idle、HTTP 返回和 timeout 都不是静默证明。

## 验证

non-live tests 应覆盖 duplicate dispatch、pre-effect failure、dispatch-in-doubt、restart fencing、deadline、
cancel ambiguity、receipt-id/digest tamper、replay handle drift、no-output success、cross-owner/generation denial
和 locator redaction。每个失败同时断言稳定公开诊断、私有 cause chain、mutation/fallback facts 与零
replacement dispatch。real SSH/HPC 只在独立 opt-in 与明确授权下执行。

运维验收还必须检查 explicit cleanup：主操作和 cleanup 同时失败时按顺序保留两个 cause；effect 已成功
但临时路径残留时记录 `cleanup_incomplete`、exact temporary identity 与 `mutation_applied=true`，不得
静默删除诊断或回退成 `no_effect`。
