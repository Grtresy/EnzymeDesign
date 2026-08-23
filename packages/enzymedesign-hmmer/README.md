# enzymedesign-hmmer

`enzymedesign-hmmer` 是 EnzymeDesign 的 HMMER Product Plugin 与 subordinate Driver 包，不属于 OpenZyme
Kernel、Compute 或 HPC。exact Plugin manifest、local/HPC Driver manifests、tool runtimes、qualification spec、
typed workload compiler 和 non-live tests 已实现，并由 EnzymeDesign Distribution 精确选择。Plugin runtime
bundle 现在同时提供两个 tool runtimes 和与 manifest/Driver 一一对应的 local/HPC capability route runtimes，
可通过 Kernel exact mount。EnzymeDesign Distribution 的 `EnzymeDesignFormalComputeToolApplication` 已把
Kernel-admitted dispatch proof、subordinate Driver 和 `ComputeExecutionApplicationService` 接通；声明式 runner
Port 仍由 composition 注入，HMMER 不接触其实现。durable repository、result/continuation restart 与 non-live
产品级跨层 qualification 已证明；真实外部 cutover/live 未执行。

## 跨插件通信

Plugin manifest 只声明两类依赖：

- `openzyme.execution.revision-job@1`，需要 `submit/observe`；
- resource capability `software.hmmer@1`，版本 `>=3.3,<4`，需要 `hmmbuild/hmmsearch`，并通过
  `same_target_as=openzyme.execution.revision-job` 约束同一执行 target。

HMMER 不 import HPC、SSH、Slurm、Host 或 Core。operator-controlled qualification 按 manifest 中的 version/smoke
argv 在 exact target/environment 执行，产出 inventory fact；Agent turn 不 SSH/`which` 探测。Kernel resolver 把
Plugin activation、Session binding、inventory generation、route、workspace readiness 和 Agent authority 求交，
只向 Agent 暴露真正可用的 `enzymedesign.hmmer.build/search`。

## Driver 边界

`enzymedesign.hmmer.local` 与 `enzymedesign.hmmer.hpc` 都只实现 compile/validate：它们把 closed request 转成
`ExecutionWorkloadSpec`，生成固定 `hmmbuild` 或 `hmmsearch --noali --tblout` argv，并绑定 immutable
revision inputs、root-relative cwd/output、resource/environment policy、result contract 和
`software.hmmer` requirement。caller 不能提交 argv、shell command、credential、Host/remote path 或 scheduler ID。

Driver 不 dispatch、不持有 credential、不选 target、不自动 fallback。formal workload 必须由 Compute 以 Agent
显式选择的 exact route 执行；HPC Plugin/Adapters 只提供合格 route 与远端机制。直接 `hpc.workspace.exec` 运行
HMMER 是允许的 exploratory Shell，但其 receipt 固定不能通过 HMMER formal result validation，也不能成为
Science adoption、publication 或 Task finish evidence。

route runtime 只接受 manifest 声明的 exact route、capability 与 subordinate Driver identity。Kernel gateway
在调用前把 revalidated affordance、authority generation/fence、workspace generation、route/driver/target 与
inventory proof 封装为 `ToolDispatchBinding`；缺失该 binding 的直接 runtime 调用 fail closed。Distribution bridge
据此编译 workload，并只向原 route 对应的 Compute runner Port dispatch；不会探测或替换 target。正式
result validation、durable restart recovery 与产品级跨层证明已经闭合：真实 non-live 产品场景从 generic Host、
immutable publication 与 adopted inventory 进入 exact HMMER route，验证 terminal result、owner continuation 和
Task 不自动完成。该证明使用声明式 fake external runner，不表示真实 HMMER/HPC target 已 qualified、cutover 或
live。

## 失败与迁移

tool/driver/route/request/result digest、软件版本、inventory generation 或 affordance snapshot 任一漂移都在 effect
前 fail closed，`fallback_performed=false`。响应丢失由 Compute/ControlledOperation reconcile 原 occurrence；HMMER
不重试、不换 route。后续 production cutover 只能通过 EnzymeDesign exact Distribution activation 与 public `@2`
离线验收，不能恢复旧 engine/Pipeline caller。
