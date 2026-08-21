# enzymedesign-sequence-toolpack

EnzymeDesign 的序列解析与生物数据库能力插件。

当前包已提供 exact manifest、严格 FASTA/plain-sequence 解析、四个 ToolSpec 和 provider-neutral runtime。
`enzymedesign.sequence.parse` 是无外部效果的纯解析；UniProt、RCSB 与 InterPro 工具只声明 provider capability，
由 Distribution 选择的 Adapter 经 Kernel ControlledOperation 提供。插件不 import Research、Host、HTTP client、
HPC/SSH/Slurm 或数据库实现，也不会在 import/catalog/Agent turn 中自行联网探测。

数据库下载结果仍是私有 workspace 数据；Provider receipt、解析成功或文件存在都不自动成为 publication、
Science adoption 或 Task finish evidence。缺少 provider route 时工具为 blocked/degraded，不得切换到浏览器、
其他数据库或本地缓存。
