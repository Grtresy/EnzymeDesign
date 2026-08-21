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

fresh factory 通过 Kernel 三 proof coordinator 产生 epoch；
`verify_enzymedesign_deployment_startup_read_only()` 在不 mount Plugin runtime 的前提下闭合 Store
deployment proof、installed wheel set、Session composition pin、capability-binding revision 和 target
inventory reference，并且只重新授权数据库中的原 exact epoch。

`build_enzymedesign_scientific_contributions()` 是 Product composition factory：它构造 AOX
workflow registry、scientific finalization handler 与 exact executor receipt validator，再通过
通用 Science application ports 注入 Host。Host 不直接 import AOX 或 executor。
