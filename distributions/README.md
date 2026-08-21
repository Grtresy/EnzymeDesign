# OpenZyme Distribution manifests

本目录只保存版本化部署组合，不是 Python workspace root，也不定义新的业务语义。

- `openzyme-standard` 选择 Kernel、SQLite、Git/LFS、本地进程、默认 Agent runtime 以及
  Host/Client/CLI/Core UI；它的 required semantic Plugin 集合固定为空。
- `enzymedesign` 在相同 Kernel/Adapter 约束上显式选择通用及酶设计 Plugins/Drivers。

两个组合均标记为结构上可激活的 `active` manifest。`openzyme-standard` 由 `openzyme-standard` wheel
打包；EnzymeDesign 组合由 `enzymedesign` Distribution wheel 打包。纯 composition factory 已能读取 exact
manifest、闭合 dependency/Driver/route/catalog，并分别生成绑定目标 owner schema 的 deterministic fresh
seed。`active` 只解除早期 scaffold gate；Host 仍须先验证 schema、installed wheels 和 composition，持久化
exact activation epoch 后才能开放 writer/runtime。安装 wheel 或发现 entry point 本身不等于启用能力。

配置采用 closed `openzyme_composition@1`：Kernel、每个 Adapter slot/target、required/optional Plugin、
Driver slot/owner 和 delivery surface 都携带 exact package/version/digest。所有当前选择都绑定
真实 package-resource manifest digest。`active` 只证明结构闭包；runtime/writer/public contract
的旧 Host cutover 仍未完成。不得把单个 `manifest_state` 当作 production activation
证明，也不得绕过 deployment proof/epoch 直接开放 surface。

目标启动器必须先完成 composition/core-schema/installed-wheel 三类 read-only verification，再生成
`DeploymentActivationEpoch`。epoch 之前不得创建 repository writer、挂 route/worker、启动 runtime 或调用
external effect。新 Session 必须原子保存 `SessionCompositionPin + initial SessionCapabilityBindingRevision`；
后装 optional Plugin 不会热进入旧 Session。完整顺序见
[`deployment-composition-operator-guide.md`](../docs/v3/deployment-composition-operator-guide.md)。
