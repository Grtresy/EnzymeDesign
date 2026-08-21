# Science Extension

`openzyme-science` 是通用科学生命周期语义的目标唯一 owner；它不是 Kernel，也不包含 AOX、HMMER、Vina、
Slurm 或任一具体研究策略。非科学 Distribution 可以完全不安装它，EnzymeDesign 则可以在自己的 composition
manifest 中把 exact Science Plugin 列为 required。

## 身份、状态与当前迁移阶段

Plugin ID 为 `openzyme.science`，状态 namespace 为 `openzyme_science`，公共投影 section 为
`openzyme.science@1`。exact manifest 固定 6 个 lifecycle tools、只读 HTTP route、projection、UI renderer、
bounded worker、finish validator、schema、migration 和 transaction participant。entry point 只定位包内 manifest；
wheel 可 import、entry point 可发现或 EnzymeDesign manifest 引用它都不等于已经激活。activation 必须在部署门禁中
校验 exact component/build/contract/manifest digest 和完整 contribution set，Session 创建后固定 bundle。

当前源码状态是 `target_implemented_not_cutover`。目标 manifest/runtime surfaces 已实现，通用 workflow
contract registry、attempt lifecycle、文件采用、deliverable finalization 和 offline verifier 由 Science 拥有。
旧 mixed Host wiring、在线 `file_workspace_public@1` scientific writer 和包内 raw-SQLite repository 已删除；
旧物理表只属于 Store 的离线 migration/proof 输入。当前仓库没有执行真实 deployment activation，因此不能把源码
收口解释为生产 cutover，也不得同时注册旧、新同名工具或双写状态。

## 生命周期和文件边界

Science 拥有 attempt、selection、occurrence disposition、effect adoption、deliverable、validation 和 closure。每个
formal identity 都必须绑定 exact Project/Session/Task、attempt、selection revision、workflow contract digest、
authority generation/fence，以及所消费的 operation/publication identity。跨 Session、跨 attempt、stale generation、
缺失 adoption 或不确定 effect 必须拒绝，不能自动复制、修补或寻找替代结果。

`ScientificDeliverableRef` 仍暂时保留既有 Git-shaped immutable revision contract：repository binding、publication、
commit/tree、normalized relative path、Git blob/LFS byte identity、producer operation/result 和 selection adoption 全部
进入 digest。它不接受 mutable workspace path、Host path、remote path、URL 或 artifact-era ID。Shell/HPC job success
只是一项 process/Compute receipt；Agent 必须检查结果、显式提交和发布，Science 才能登记 adoption/deliverable。

## 通信和事务边界

Agent-facing tools 为：

- `scientific.attempt.inspect`；
- `scientific.selection.begin`；
- `scientific.operation.disposition`；
- `scientific.operation.adopt`；
- `scientific.selection.seal`；
- `scientific.attempt.close`。

这些工具只把 Agent 的显式策略决定交给 Science application service，不代替 Agent 选 selection、role、provider、
route 或 fallback。Science 与 Research、Compute、HPC、HMMER 等同层 Plugin 不互相 import implementation；它只通过
Kernel application services 和 capability requirements 交换 opaque identity、generic `EvidenceRef`、
`RevisionPathRef`、controlled-operation receipt 和 explicit route binding。

当前目标 application 是 `ScienceLifecycleToolApplication`。它只接收窄 `ScienceStateQuery`、由 composition
提供的 `ScienceInvocationContextResolver` 和 `ScienceStateMutationApplication`；前两者提供 exact Session record 与
Kernel authority/bundle/binding context，后者只能调用声明的 Science participant。selection/disposition/adoption/
seal/closure 的 entity ID 由 exact Session、attempt/generation、显式输入和 idempotency identity 稳定生成，receipt
返回 exact entity/state-version/record digest。它不持有 Core repository、SQLite connection、Host service、SSH 或
scheduler client。

transaction participant 只接受 namespace `openzyme_science` 内一个 closed upsert，一次最多一个 entity，带 expected
state version 和固定 read/mutation/payload/time budget。attempt-scoped record 必须引用同一 namespace 中 exact
attempt ID 与 attempt generation；participant 在写入前重验 record/attempt 的 Session、generation 与 entity ID。
Store 提供 namespace-confined reader/writer；participant 不接收 raw connection，不访问 Core table，不做
网络/process/publication，也不改变 Task。Kernel 在 participant 运行前验证 Session bundle、authority lease
generation/fence 与 capability binding，任一 stale fact 均在 Store 前失败。

Science command 只能接收 Kernel 已授权的 `KernelCommandContext`、不可变验证快照和 participant mutation
receipt，不能接收 `CoreRepositories`、raw SQLite connection、Host internal 或同构替身。历史表读取只能发生在
显式离线 migration/proof 中，不是 Plugin 通信接口。

## Projection、finish 与错误语义

只读 route `/v3/extensions/openzyme.science/sessions/{session_id}` 和 projection 都输出授权、分页、byte-bounded 的
namespaced view，并递归拒绝 credential、Host/remote path、raw log、storage URI 和 artifact-era字段。
`ScienceExtensionStateProjectionApplication` 只消费窄 `ScienceProjectionStateQuery`；SQLite Adapter 的
`SQLiteExtensionStateProjectionQuery` 只读取 activation allowlist 中的 namespace，并在 SQL 边界按 exact Session 和
稳定 `(entity_kind, entity_id)` 游标分页。`ScienceUiRenderer` 是只读 renderer，输出不会并入 Core reducer，且固定
`task_finished=false`。Core reducer 不读取该 section 决定策略或终态；不安装 Science 时 Core projection 不产生这一
section。

attempt close request、closure receipt、deliverable validation、worker completion、continuation wakeup 和 runtime idle 都
不是 Task completion。只有 Task owner 显式调用 `task.finish` 后，Kernel 才把 immutable finish context 与 exact
`EvidenceRef(contract_id=openzyme.science.closure@1)` 交给只读 validator。validator 只核对既存 closure evidence，
不现场运行科学计算、不补 deliverable、不写 Science/Core 状态，也不执行外部 I/O。

stale fence、identity/digest drift、unknown effect 或 migration/manifest mismatch 一律 fail closed；effect 之前失败为
`no_effect`，response 丢失保留原 occurrence 的 `dispatch_in_doubt` 并只允许 reconcile。禁止自动 retry、换 target、
把缺失结果解释为科学阴性、从报告/文件/job 存在推导 adoption，或由 worker/validator 自动完成 Task。

## 迁移与验收

后续真实 offline cutover 必须 inventory 所有旧 `scientific_*` rows 和 writer，quiesce 后备份，按 owner manifest 转为
namespaced records，验证 row/key/FK/digest/version 等价，再一次性切换 manifest/runtime/projection authority。
activation forward-only，不提供 online translation、dual-write 或旧 Core fallback。focused tests覆盖 exact manifest、
runtime mount shape、namespace/Session confinement、private locator rejection、workflow digest compatibility、finish
separation、Plugin-absent Standard、restricted participant 的原子回滚和旧在线 authority 缺失；真实 activation
仍需要后续明确授权。
