# enzymedesign-vina

`enzymedesign-vina` 是 EnzymeDesign 的 AutoDock Vina Product Plugin 与 subordinate Driver 包。exact Plugin
manifest、local/HPC Driver manifests、`enzymedesign.vina.dock` runtime、
`software.autodock-vina>=1.2,<2` qualification spec、typed workload compiler 和 non-live tests 已实现，并由
EnzymeDesign Distribution 精确选择。旧 `openzyme-tools` catalog 已删除，preprocess 已迁入独立
EnzymeDesign Plugin；剩余阻塞是整体 `file_workspace_public@2`/offline cutover，不是 vertical ownership。

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
