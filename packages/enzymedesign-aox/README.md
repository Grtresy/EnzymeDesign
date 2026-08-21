# enzymedesign-aox

AOX workflow、规则与验收 Product Plugin。

本包是 AOX 科学语义的 canonical owner，当前已经拥有：

- 冻结历史 `aox_blank_world_selected_chain@1` reader；
- 当前 `aox_blank_world_selected_chain@2` workflow contract；
- 17-role scientific file-bundle contract 与 AOX file-bundle finalizer；
- AOX architecture qualification receipt 的 current/historical closed contract 与纯 evidence derivation；
- exact Plugin manifest，以及对 Science、HMMER、sequence toolpack 的显式 capability requirements。

AOX calculations、fixed references、Biopython/NumPy 与受监督 execution SDK 调用位于独立 subordinate
`enzymedesign-aox-executor` Driver，避免 semantic Product Plugin 直接依赖执行机制。

EnzymeDesign Distribution 通过 `build_enzymedesign_scientific_contributions()` 组装 workflow
registry、finalizer handler 和 executor receipt validator。通用 Host 只提供 Science read/finalization
ports，不是 AOX 语义 owner。当前 AOX 没有独立 HTTP route、worker、projection 或 UI renderer，
manifest 对这些 contribution 保持精确为空，而不创建无运行语义的占位实现。

finalizer 只消费 `openzyme-science` 的不可变 published-file read/finalization ports 和 Distribution 选择的
AOX calculation-receipt validator，不导入 Core repository、Host 或 executor 实现。代码 owner 与 Distribution
注入已完成，EnzymeDesign Distribution 也能构建 active exact graph、fresh proof 和 generic `@2` Host surfaces；
真实历史 deployment 的离线 cutover 尚未执行。manifest active 不授权 AOX live execution，
也不改变 AOX 的语义 owner。

插件只定义 AOX 语义，不直接探测 HPC、不导入 SSH/Slurm/Host/Core repositories，也不从 scientific receipt、文件或 runtime 状态推导 Task 完成。
