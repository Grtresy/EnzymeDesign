# Extension composition manifest reference

本文记录 `openzyme-composition@1` 与 Adapter/Plugin/Driver manifest 的当前 closed contract。它是
`separate-openzyme-kernel-from-capability-extensions` 的 schema reference，不代表两个 scaffold
Distribution 已经可用于生产 Session。

## 1. 唯一激活来源

Python entry-point group 固定为 `openzyme.extensions`。每个 entry point 只能返回
`ExtensionManifestLocator`：component ID/kind、exact distribution name/version、package resource name 与
manifest digest。locator import 不得导入 runtime implementation、注册 route/worker/tool、读取配置、探测
target 或产生外部效果。

Host 的顺序固定为：

1. 解析 closed `openzyme-composition.toml`；
2. 枚举 locator，但只选择 Distribution 明列的 component；
3. 从 exact installed wheel resource 读取 manifest bytes；editable `.pth` 只允许纯路径行；
4. 拒绝 duplicate key、unknown field、unsupported schema 与超过 4 MiB 的 manifest；
5. canonicalize、重算 digest，并与 locator、installed distribution、Distribution selection 逐项比较；
6. 在内存完成依赖图、collision 和 catalog 构建；
7. schema/composition/wheel 三类只读 verification 全部成功后，才生成 deployment activation epoch。

未列入 Distribution 的 installed entry point 只作为 ignored identity 记录，不读取其 manifest resource，
不 import runtime provider，更不能形成 ambient capability。

## 2. Distribution document

顶层字段是：

- `schema_id = "openzyme_composition@1"`；
- `manifest_state = "active" | "scaffold_not_activatable"`；
- exact `distribution` identity；
- 一个 exact Kernel selection；
- `adapters[]`，唯一键为 `slot + target_id-or-none`；
- required/optional `plugins`；
- `drivers[]`，唯一键为 slot，且 Driver ID 全局唯一；
- delivery surfaces；
- policy 中 `ambient_discovery_enables_components=false`、`session_hot_swap=false`。

每个 selection 都绑定 component ID、distribution name/version 和 manifest digest。target-scoped Adapter
可把同一 manifest 绑定到多个显式 target；每个 slot/target binding 都进入 Adapter bundle digest。
Driver selection 必须同时选择 owning Plugin，并在 activation 时验证 owning capability contract、required
Adapter Port 和 exact Plugin route。

`scaffold_not_activatable` 是硬门禁。缺少目标 manifest 时不能只把该字段改为 `active` 来试跑。

## 3. Adapter manifest

`openzyme_adapter_manifest@1` 只允许：

- `ComponentIdentity(kind=adapter)`；
- required contracts；
- 已实现 Port contract IDs/digests；
- configuration schema digest；
- read-only preflight contract digest；
- `target_scoped`。

Adapter 不声明 Agent-facing semantic tool、Plugin state、finish validator 或业务 entity。替换 Adapter 只改变
机制与 Adapter bundle，不改变 Task/Session 等 Kernel 语义。

## 4. Plugin manifest

`openzyme_plugin_manifest@1` 绑定：

- component/build/contract identity、required Kernel 与 Extension SPI contract；
- capability `provides` 和 package-independent `requires`；
- dotted tool contract、runtime ID、authority/approval/workspace/route requirements；
- qualification spec；
- capability route 与 normalized HTTP route；
- projection、UI renderer、worker、finish validator；
- schema、migration、transaction participant、唯一 state namespace 与 migration bundle；
- non-secret configuration schema digest。

Resource capability requirement 可以声明 version、operations 和 `same_target_as`；不得写 Python package
name。HTTP path 是 bounded canonical absolute template；query、fragment、percent、反斜线、空 segment、重复
parameter 和非根尾斜线 alias 均拒绝。

## 5. Driver manifest

`openzyme_driver_manifest@1` 只能声明 owning Plugin/capability contract、route kind、required Port contracts、
workload/result contract digest。Driver 没有顶层 tool/state，也没有 dispatch authority。runtime mount 时，
Driver ID、owning Plugin 和 route declaration 必须完全一致；不能把一个 Driver 挂到另一个 Plugin 或临时
fallback route。

## 6. Deterministic catalogs

activation 分别重算：

- Adapter、Extension、Driver bundle；
- DeclaredToolCatalog；
- capability RouteCatalog 与 HttpRouteCatalog；
- projection、UI-renderer、worker、finish-validator、schema、migration、transaction-participant、qualification catalog。

下列 key 任一冲突都拒绝整个 activation，不存在 last-write-wins：single capability provider（当 cardinality
要求唯一）、dotted tool name、两类 route ID、`METHOD + normalized path`、projection、worker、validator、
schema、migration、participant、qualification、UI renderer、Driver ID 与 state namespace。

## 7. Activation 与 runtime mount

required component 缺失或依赖不满足会失败；optional wheel 缺失是 `inactive`；manifest 完整但当前 resource
route/qualification 未满足可以是 `degraded`。optional 的 version/digest/schema/migration/collision/cycle
错误仍是 activation failure。

`DeploymentActivationEpoch` 绑定 composition activation、Kernel/Distribution document、Adapter/Extension/
Driver bundles、tool/route/projection/migration、workspace backend、Host/client build，以及 schema/wheel
verification receipts。`DeploymentActivationGate` 在 epoch 形成前拒绝 repository writer、HTTP route、worker、
runtime 和 external effect。

Plugin runtime bundle只能实现自己 manifest 中的 exact contribution set。`mount_extension_surfaces()` 先验证
全部 bundle，再一次性返回 immutable mount；少一个 worker、多一个 route、contract drift、ambient bundle、
Host internal implementation 或 Driver owner mismatch 都不会留下 partial registration。

## 8. Session 与升级

新 Session 通过一次 repository call 原子创建 Session、`SessionCompositionPin` 和 revision 1 的
`SessionCapabilityBindingRevision`。pin 固定 composition/release/catalog/workspace backend/Host-client identity；
后续 inventory adoption 只追加 capability-binding revision，不改 extension bundle。

message、drain、approval、tool、workspace mutation、publication、controlled operation 和 restore 都必须通过
`SessionCompositionGuard`。bundle/binding drift 只允许安全 inspection，并返回
`session_composition_upgrade_required`；不得执行 callback、热加 Plugin 或换 Adapter。

Plugin upgrade/removal 是 quiescent offline operation。verifier 检查 non-terminal Session pin、continuation、
owned rows/state disposition、migration plan 和 unsettled operation。它只产生 no-mutation verification；真实
migration/cutover 属于后续显式授权流程。

## 9. Failure contract

composition failure 的公开记录固定为 `no_effect`、`mutation_applied=false`、`fallback_performed=false`，只含
allowlisted component/digest/collision facts和操作员动作。Host path、credential、secret、traceback 与原始
异常文本不进入公开 projection。受保护 `PrivateDiagnosticRecord` 用同一 `diagnostic_id` 保存有界 traceback、
cause chain 和已做 secret redaction 的 private context。
