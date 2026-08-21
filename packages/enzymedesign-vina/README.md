# enzymedesign-vina

`enzymedesign-vina` 是 EnzymeDesign 的 AutoDock Vina Product Plugin 与 subordinate Driver 包。exact Plugin
manifest、local/HPC Driver manifests、`enzymedesign.vina.dock` runtime、
`software.autodock-vina>=1.2,<2` qualification spec、typed workload compiler 和 non-live tests 已实现，并由
EnzymeDesign Distribution 精确选择。旧 `openzyme-tools` catalog 已删除，preprocess 已迁入独立
EnzymeDesign Plugin。Plugin runtime bundle 现在同时提供 dock tool runtime 和 manifest/Driver 一一对应的
local/HPC capability route runtimes，可通过 Kernel exact mount。EnzymeDesign Distribution 的正式 application
bridge 已消费 Kernel-admitted `ToolDispatchBinding`，调用 subordinate Vina Driver 编译 typed workload，并经
`ComputeExecutionApplicationService` 及声明式 runner Port 提交原 exact route。durable restart 与 non-live 产品级
qualification 已闭合，但不等于真实 HPC/Slurm cutover 或 live。

Plugin 只声明 `openzyme.execution.revision-job@1` 与 resource capability `software.autodock-vina@1`，后者用
`same_target_as` 固定到同一 Compute route。它不 import HPC、SSH、Slurm、Core、Host 或 preprocess implementation，
也不在 Agent turn 探测 `vina --version`。operator qualification 发布 exact target inventory；Kernel resolver 再把
Plugin、route、inventory、authority 和 workspace readiness 求交。

local/HPC Driver 都是 compile/validate-only。closed request 必须提供 immutable receptor PDBQT、ligand PDBQT 和
Vina config 三个 revision inputs，Driver 生成固定 argv 和 root-relative poses/log outputs，并绑定 resource/
environment policy、result contract 与软件 requirement。caller 提交 argv、shell command、credential、Host/remote
path 或 scheduler ID 会在 dispatch 前被拒绝。Driver 不选 target、不 dispatch、不 retry、不 fallback。

正式 docking 只能进入 Compute lifecycle。通过 `hpc.workspace.exec` 直接运行 Vina 是 exploratory Shell，其 receipt
不能通过 formal result validator，也不能成为 Science adoption、publication 或 Task finish evidence。任何 tool/
driver/route/result digest 或 inventory drift 均 fail closed，并由 Compute 对同一 occurrence reconcile。

route runtime 仅接受 exact route/capability/Driver identity；正式 tool runtime 还拒绝缺少 Kernel admission
proof 的直接调用。Kernel gateway 在 dispatch 前重验 affordance，并下传 exact authority fence、workspace
generation、route/driver/target、inventory 与 capability proof；Distribution bridge 不直接导入 HPC、SSH 或
Slurm，也不 retry、redispatch 或换 target。result validation、持久恢复与完整产品路径已由真实 non-live 产品
场景闭合：generic Host、immutable publication、adopted inventory 与 exact Vina route 进入 mounted Driver 和
durable Compute，并验证 result、owner continuation、Science validator 及 Task 不自动完成。声明式 fake external
runner 不证明真实 docking/HPC target 已 qualified、cutover 或 live。
