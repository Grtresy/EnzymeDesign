# Workspace Revision Jobs

## Admission

目标 Compute Plugin 的一次 formal request 使用 `openzyme_compute_execution_request@1`，组合 closed
`ExecutionWorkloadSpec` 与 exact `ExecutionRouteIdentity`，并匹配：

- owner member、authority lease generation/fence、workspace generation；
- repository binding/version；
- source class、revision id/ref、commit、tree 和 LFS closure；
- fresh clean observation；
- typed argv/entry point、root-relative cwd、environment/resource policy、result contract 和 capability
  requirements；
- Agent 显式选择的 route、provider、target、inventory generation/digest 和 qualification digest；
- operation/execution/request identity、absolute deadline；
- formal workflow 所需的 scientific admission identity。

Host/Kernel admission verifier 会重新解析这些对象，而不是信任 SDK dictionary。任何 owner、generation、
authority fence、capability binding、digest、deadline 或 route drift 都在 provider effect 前拒绝。现有
`workspace_revision_execution_request@1` 仍是 production compatibility wire；迁移完成前不得把两者在线
双写或把新 manifest 误报为已激活。

## Compute tree cache

可复用 compute tree 的 key 精确绑定 workspace generation、repository binding/version/policy、
commit/tree/ref、LFS closure、target/runner policy、toolchain 和 owner identity。cache 命中仍必须
调用受保护的 `validate-source-cache`，并验证带摘要的
`verified_compute_tree_cache_validation@1` 回执。cache binding、entry set 或回执任何
drift 都在 payload effect 前失败；runner 不得回退到 mutable login clone、重建新 tree
或选择旧 snapshot。

## Submit

`openzyme_execution_sdk.workspace_revision.submit(...)` 的当前 compatibility 入口只接受 exact operation、execution request 和 clean observation object。
返回的 `WorkspaceRevisionJob` 保存 execution/operation/request 与 source revision identity。submission pending
时由 durable continuation 恢复同一 call；不要自行 polling submit。

## Observe 与 cancel

`job.observe()` 读取同一 occurrence 的 bounded public state。raw runner handle/log/path 被 Host 私有化。
`job.cancel(reason_code=...)` 只发起一次 typed cancel intent。transport error、timeout 或 missing response 不
证明 cancellation，也不允许创建 replacement execution。

目标 Compute lifecycle 中，dispatch、observe、reconcile 与 cancel 全部写入同一个 Kernel
ControlledOperation。Compute namespaced state只保存 request、opaque provider handle、route receipt 和 result，
不得复制 effect certainty、retry eligibility 或 cancel truth。取消响应丢失后只观察同一 provider handle，
不再发 cancel，也不改 route。

## Results

terminal result 包含 effect certainty、state、result digest 和可选 result revision link。consumer 若需要
文件，必须验证 result revision/publication 的 exact path；不能从 backend filename 或 mutable workspace
取值。scientific adoption 还要求 current selection disposition 和 matching producer effect。

terminal Compute result 只注册给 owner 的 durable continuation；它不发布 owner workspace 文件、不创建
Scientific evidence、也不完成 Task。Agent 必须显式检查结果、提交/checkpoint、发布，再决定是否 handoff 或
adopt。
