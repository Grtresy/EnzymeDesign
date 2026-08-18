## Why

独立 clone 解决私有工作，却不能定义 researcher 如何把结果交给 executor。必须把 local edit、commit、private push 和 team publication 分开，确保只有显式 publish 才进入共享文件真相。

## What Changes

- 新增显式 `workspace.publish`，只接受 whole-repository clean commit，并创建 append-only `PublishedRevision`。
- `PublishedRevision` 绑定 repository binding version、exact commit/tree、parent/base、publisher、publication ref、path manifest 和 policy digest；修订只能新建记录并用 `supersedes` 关联。
- agent local commit 和 private ref push 均不改变 team projection；内部 remote 的 publication namespace 由 Host 独占写入并禁止 force-update/delete。
- publication 使用冻结 intent、幂等 key、exact remote ref receipt 和现有 effect-certainty/reconciliation 语义；不把 response loss 当成 no-effect，也不创建替代 publication。
- 本 change 消费 C2 的 canonical capability-lease status/profile seam 与 `agent_capability_lease_acceptance@1` receipt，但由 C4 自己实现并验收 publication intent × active capability lease × `ControlledOperationExecution` 的真实三轴组合矩阵；C2 不创建 publication execution、ref 或 shared truth。
- 其他 agent 通过标准 `git fetch` 获取 exact published ref，自行 fast-forward/merge/rebase/cherry-pick；系统不自动更新 clone或解决冲突。
- protocol/task handoff 可以引用 `publication_id + revision + path`，但 publish 不自动完成 task 或投递消息。

## Capabilities

### New Capabilities
- `workspace-publication`: 定义私有 Git 状态、显式不可变发布、发布收据与 agent 间 exact revision 同步。

### Modified Capabilities

## Impact

影响 Git service/ref ACL、domain/repository/migrations、publication authority composition、workspace tools、protocol/task evidence、projection/events 以及后续 LFS、HPC 和 report handoff。

连续迁移实现阶段以 `workspace_publication_source_only_dependency_gate@1` 绑定当前 C2/C3 source、schema、policy 与 interface 事实；它固定声明 predecessor acceptance、最终 source revision、production effect 与 live 资格均未证明，只允许继续 C4 源码和未运行测试的编写。最终 C4 acceptance 仍须在全部连续 change 合并实现后重新验证正式 C0--C3 receipts 与组合源码。
