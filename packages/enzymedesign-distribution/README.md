# EnzymeDesign Distribution

该 wheel 是显式、版本化、可做 digest 的产品组合，不定义新的 canonical state。它选择
OpenZyme Kernel、基础设施 Adapters、通用 Plugins、EnzymeDesign Product Plugins 与
Drivers；它不依赖 `openzyme-standard` 作为语义层。

当前 manifest 已是结构上可激活的 `active` composition。纯 factory 已闭合 8 个 Adapter、14 个 Plugin、
8 个 subordinate Driver、32 个 Plugin 声明工具和 5 个 Kernel workspace 基础工具（合计 37 个）；
`build_enzymedesign_fresh_install_seed()` 还能将这些 catalog 与
EnzymeDesign owner schema 和 deterministic bootstrap receipt 绑定。该状态不授权 live Provider/HPC，也不
替代 Host startup、installed-wheel proof 或真实 offline cutover；production surface 仍必须先通过 exact
`DeploymentActivationEpoch` gate。

`EnzymeDesignPluginRuntimeSurfaceSet` 与
`mount_enzymedesign_extension_surfaces()` 已进一步把 Plugin-owned runtime 对象转换为 exact Kernel
mount bundles。当前 non-live mount 闭合 32 个 Plugin tools、13 条 capability routes、2 条 HTTP routes、
5 个 projections、5 个 workers、2 个 finish validators 和 3 个 transaction participants；任一声明缺失、
多余、owner/driver/digest 漂移都会在 mount 前失败。该 factory 要求 composition root 注入真实
application/repository/Adapter Ports，不提供空 runtime 或 Provider fallback。

fresh factory 通过 Kernel 三 proof coordinator 产生 epoch；
`verify_enzymedesign_deployment_startup_read_only()` 仍只负责在不 mount Plugin runtime 的前提下闭合 Store
deployment proof、installed wheel set、Session composition pin、capability-binding revision 和 target
inventory reference，并且只重新授权数据库中的原 exact epoch。`build_enzymedesign_application_runtime()` 随后
核对全部 8 个 selected Adapter runtime identity，mount 上述 exact Plugin surface，闭合 5 个 Kernel tools 与
32 个 Plugin tools 的 37-tool runtime catalog，再构造 SQLite writer、capability registry、bounded runtime
gateway、Kernel coordination/operational routes、finish validator registry 和公共投影。任一 proof、Adapter 或
surface 漂移都会在 writer 对外可达前失败。`build_enzymedesign_v2_host_app()` 只把该完整 product runtime 注入
通用 `openzyme-host-api`；EnzymeDesign 没有依赖 `openzyme-standard`。non-live 测试还通过真实 Kernel gateway
完成了 Session bootstrap，证明该入口不再只是 catalog proof。

同一 composition root 还构造 Store-backed Session pin/capability-binding reader、
`ExtensionStateKernelApplicationService`、SQLite extension transaction coordinator/query、
`ExtensionStateComputeExecutionRepository` 与 Kernel continuation service。Compute Plugin 因而只提交
namespaced command，不接触 SQLite/Core table；restart 测试已证明 invocation、exact route、opaque handle、
terminal result 和 owner continuation 可从原 SQLite truth 恢复且 external dispatch 不增加。

这一状态是 `runtime_mounted`，不是 `cutover` 或 `live`。composition root 以一次性
`EnzymeDesignFormalComputeApplicationBinding` 在 writer 可达前，把 HMMER/Vina 的 Kernel-admitted tool
invocation、subordinate Driver、typed workload、Compute ControlledOperation lifecycle 与声明式 runner Port
接通；它只从 canonical `PublishedRevision`、publication-owned path verification、ready owner workspace、当前
authority lease 和 adopted capability binding 推导 admission，不接受调用方伪造这些事实，也不自动换 route、
redispatch 或完成 Task。Compute durable repository/continuation recovery 已闭合。远端 Workspace operation 与
Slurm submit/cancel occurrence 分别使用持久 ledger，跨 Adapter epoch 只 reconcile 原 effect；远端 helper 也已
进入 exact resource qualification。

`enzymedesign_local_single_process_file_sqlite@1` 现在另有真实 non-live 跨层场景：它从通用 Host 创建 Session，
固定 composition pin 和 authority，生成真实 immutable publication，采用含 HMMER/Vina 软件事实的 target
inventory，经 affordance/route、实际 mounted Drivers 和 durable Compute lifecycle 到达声明式 fake runner，
验证 terminal result、两条 owner continuation 与 Science finish validator，同时证明 Task 仍为 `todo`。该场景只
替换显式的 Agent-turn、Git-shaped revision 和 external Compute runner Ports；它证明产品内部组合闭合，但不证明
真实 SSH/Slurm/HPC target 已 `qualified`、已 `cutover` 或任何 live 调用获授权。

状态词固定如下：`selected` 仅表示 manifest 选中；`runtime_mounted` 表示 exact runtime identity 已装配；
`qualified` 表示特定 target/provider 有当前有效 receipt；`cutover` 表示真实部署已采用该实现；`live` 表示某次
外部调用另获授权并实际发生。后一个状态不能由前一个状态自动推导。

`build_enzymedesign_scientific_contributions()` 是 Product composition factory：它构造 AOX
workflow registry、scientific finalization handler 与 exact executor receipt validator，再通过
通用 Science application ports 注入 Host。Host 不直接 import AOX 或 executor。
