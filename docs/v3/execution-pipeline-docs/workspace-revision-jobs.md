# Workspace Revision Jobs

## Admission

一次 job request 必须包含 `workspace_revision_execution_request@1`，并匹配：

- executor member、capability lease、remote workspace generation；
- repository binding/version；
- source class、revision id/ref、commit、tree 和 LFS closure；
- fresh clean observation；
- cwd、command、environment、resources、target profile 和 runner policy digest；
- operation/execution/request identity、absolute deadline；
- formal workflow 所需的 scientific admission identity。

Host 会重新解析这些对象，而不是信任 SDK dictionary。任何 owner、generation、digest、deadline 或 policy
drift 都在 runner effect 前拒绝。

## Compute tree cache

可复用 compute tree 的 key 精确绑定 workspace generation、repository binding/version/policy、
commit/tree/ref、LFS closure、target/runner policy、toolchain 和 owner identity。cache 命中仍必须
调用受保护的 `validate-source-cache`，并验证带摘要的
`verified_compute_tree_cache_validation@1` 回执。cache binding、entry set 或回执任何
drift 都在 payload effect 前失败；runner 不得回退到 mutable login clone、重建新 tree
或选择旧 snapshot。

## Submit

`workspace_revision.submit(...)` 只接受 exact operation、execution request 和 clean observation object。
返回的 `WorkspaceRevisionJob` 保存 execution/operation/request 与 source revision identity。submission pending
时由 durable continuation 恢复同一 call；不要自行 polling submit。

## Observe 与 cancel

`job.observe()` 读取同一 occurrence 的 bounded public state。raw runner handle/log/path 被 Host 私有化。
`job.cancel(reason_code=...)` 只发起一次 typed cancel intent。transport error、timeout 或 missing response 不
证明 cancellation，也不允许创建 replacement execution。

## Results

terminal result 包含 effect certainty、state、result digest 和可选 result revision link。consumer 若需要
文件，必须验证 result revision/publication 的 exact path；不能从 backend filename 或 mutable workspace
取值。scientific adoption 还要求 current selection disposition 和 matching producer effect。
