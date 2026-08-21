# openzyme-compute

`openzyme-compute` 是 revision-bound formal Compute 生命周期的目标 Plugin owner。它负责 typed workload、
dispatch/observe/reconcile/cancel/result 语义，并复用 Kernel ControlledOperation；HPC、Slurm 或本地容器只是
可选 route/provider，不属于 Compute 本身。

## 已实现边界

本包已成为旧 `session_run_records` 所用 `RunStatus`/`RunRecord` DTO，以及 formal revision-bound
request、clean observation、source manifest、target qualification、dispatch/result lifecycle DTO
的唯一代码 owner；仓内 writer 已直接 import `openzyme_compute`，旧
`openzyme_domain.compute_contracts` 与 `openzyme_domain.workspace_revision_executions`
兼容模块及顶层别名均已删除。兼容 DTO
保留现有 row shape，包括兼容期的 `runner_run_id`/`remote_run_dir`，但它不是最终 `@2` public wire
contract，不能泄露为 Host locator 或被当成 formal result proof。

Plugin 现在提供纯 locator、`openzyme_plugin_manifest@1`、3 个
`workspace_revision_job.*` ToolSpec/runtime、`openzyme.compute@1` 安全投影、bounded worker、
`openzyme_compute` transaction participant、namespaced schema/migration，以及 provider-neutral
`ComputeExecutionApplicationService`。application service 通过窄的 admission verifier、
`ControlledOperationApplicationService`、route port 和 continuation service 工作，不 import
HPC、SSH、Slurm、Host、Science 或 EnzymeDesign。

正式请求使用 `openzyme_compute_execution_request@1`，组合 closed `ExecutionWorkloadSpec` 与
`ExecutionRouteIdentity`，并绑定 exact owner/authority fence、workspace generation、Git revision/ref/
commit/tree、LFS closure、clean observation、Session capability binding、inventory generation、
idempotency 和 absolute deadline。Plugin repository 只保存 request、opaque provider handle、route receipt
和 terminal result；effect certainty、retry/reconcile/cancel truth 只由 Kernel ControlledOperation 持有。
每个 controlled phase 使用 request/route receipt 派生的独立 command/idempotency identity；Provider 返回
`effect_known` 时 Kernel operation 保持 active，后续只能在原 route/operation 上 observe/reconcile，不能重发或
替换 handle。terminal result 通过 closed continuation payload 只声明 source、recipient 与 resume strategy，
process epoch 由 Kernel 从 canonical AgentMember 固定。

正式 execution record 不由 Plugin 直接写 SQLite，也不写 Core table。Distribution 注入
`ExtensionStateKernelApplicationService` 与 Store-owned query/coordinator 后，
`ExtensionStateComputeExecutionRepository` 只向 `openzyme_compute/execution` namespace 提交闭合
`upsert_execution` command；Kernel 先重验 Session pin、capability binding、Plugin owner、authority
generation/fence，再由 Store 在短事务中执行 CAS。持久 payload 顶层固定 `session_id`，同时保存完整
invocation/request、exact route、opaque provider handle、route receipt 与 terminal result。

SQLite restart qualification 已证明：首次 dispatch 后 record 为 state version 2；重新构造 Kernel service、
query、repository 和 route wrapper 后，同一 request 只重复 admission 校验并返回既有 record，external
dispatch count 保持 1；随后使用原 handle 观察到 terminal result，写入 version 3 和 Kernel-owned durable
continuation；再次重启仍可读回两者。不同 request 复用同一 execution identity 会在任何新 dispatch 前拒绝。

通用 Host 不硬编码 Compute writer；Compute 只在选择它的 Distribution 通过 exact mount 后可用。本包状态是
`target_implemented_not_cutover`：目标生命周期和 SQLite restart recovery 可独立 qualification，但安装 wheel 或发现 entry point 不会
创建表、启动 worker、暴露工具或授权真实历史 deployment cutover。EnzymeDesign non-live 产品图已将它
`selected + runtime_mounted`，并以声明式 fake external runner 运行 HMMER/Vina 正式路径；这不表示真实 runner、
SSH/Slurm target 已 `qualified`、`cutover` 或 `live`。

目标请求必须绑定 immutable source revision/tree/LFS closure、exact route/inventory、authority fence、
idempotency 与 absolute deadline。未知 dispatch 保持 `dispatch_in_doubt`，禁止重放或换 target。job terminal
只 wake owner；Agent 仍需显式检查、提交、发布和选择是否作为 Science/Task evidence。

直接 `workspace.exec` / `hpc.workspace.exec` 只产生探索性进程回执；它们不能伪装为本 Plugin 的 formal
result。Compute terminal result 同样不自动生成 publication、Scientific evidence 或 `task.finish`。
