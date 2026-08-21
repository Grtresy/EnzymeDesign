# openzyme-extension-spi

`openzyme-extension-spi` 定义 OpenZyme 的显式组合和 Plugin 通信协议，只依赖
`openzyme-contracts`。它不扫描并自动启用环境中的包，也不拥有 canonical business state。

## 组件种类

- Adapter 实现既有 Port，不增加顶层产品 entity 或 Agent tool；
- Plugin 增加 namespaced state、tools、workers、projections、validators 或 qualification specs；
- Driver 隶属于一个 Plugin，只把 typed request 编译成 exact route workload并校验 result；
- Distribution 只选择 exact Kernel、Adapters、Plugins、Drivers 和 delivery surfaces。

Python entry point 只能定位纯 manifest。安装本身不是 capability、authority 或 activation；实际启用集合
由版本化 Distribution manifest 决定。

当前 `openzyme.extensions` discovery 返回 `ExtensionManifestLocator`，只含 component kind、exact Python
distribution name/version、包内资源名和 manifest digest。`parse_component_manifest_json()` 对 Adapter、Plugin、
Driver 三种 JSON 执行 closed-field、duplicate-key、schema-version 和 bounded-byte 检查；
`verify_located_component_manifest()` 再把 canonical manifest digest 与 locator/installed distribution identity
求交。普通 wheel 从 `RECORD` 定位资源；editable wheel 只读取纯路径 `.pth`，遇到可执行 `.pth` 内容直接拒绝，
不会执行它。只有 Distribution 已选择的 locator 才可继续读取资源；unlisted locator 不形成 activation。

## Plugin 能调用的 Kernel API

SPI 暴露十二组窄 application services：

`Task`、`Protocol`、`Approval`、`Authority`、`Publication`、
`ControlledOperation`、`Continuation`、`Failure`、`CapabilityQuery`、
`ExtensionInvocation`、`ExtensionState` 和 `TaskEvidence`。

每个 mutation 使用 immutable `KernelCommandContext`，绑定 Session、actor、owning Plugin、
authority lease generation/fence、expected Session version、extension bundle、capability binding、
idempotency key、workspace generation 和 explicit route。Plugin 提交 typed command；它拿不到
`CoreRepositories`、raw SQLite connection、Host private service、Git locator 或任意 mutation callback。

## Typed contributions

Manifest 分别声明 capability provision/requirement、tool、qualification、capability route、规范化 HTTP
route、projection、worker、finish validator、schema、migration 和 transaction participant。HTTP route
固定 method enum，path 去除非根尾斜线并拒绝 query、fragment、percent encoding、空/越界/非 canonical
segment；全局唯一键是 `METHOD + normalized path`。Plugin tool 必须使用 canonical dotted name。closed
dataclass 不接受
`on_any_event` 等任意 hook；duplicate identity 或 owner mismatch 在 activation 前失败。

`openzyme-composition.toml` 的 parser 同时保留 selection slot/target 和 exact component/package/version/digest，
并拒绝 ambient activation 与 Session hot swap。Adapter 可由同一 manifest 绑定多个显式 target，但 bundle
digest 包含每个 slot/target binding；Driver selection 保留 slot，必须匹配 owning Plugin contract、选定 Port
和 owning Plugin 声明的 route。

Projection 有 section contract、byte/item budget、cursor 与 exact digest。Worker 使用 bounded claim、
source version 和 fence。Task evidence validator 只返回 read-only closed validation result，不能直接写
Task terminal。

Runtime contribution 不通过 import-time global registry 注入。activation 成功后，composition root 才能为
selected Plugin 构造 `ToolRuntimeContribution`、`CapabilityRouteRuntimeContribution`、
`HttpRouteRuntimeContribution`、projection、worker、validator 和 transaction participant；Kernel 将这一组与
manifest exact ID/owner/contract/Driver binding 比较后一次性 mount。`ToolRuntimeContribution` 必须公开
owning Plugin 与 runtime ID；route runtime 必须公开 owning Plugin 和 exact Driver。SPI 不向这些对象传
`CoreRepositories`、Host app、raw SQLite connection 或 Adapter private client。

## 受限事务参与者

`ExtensionTransactionParticipant` 只有：

1. `prepare(command, ExtensionStateReader) -> ExtensionMutationPlan`；
2. `apply(plan, ExtensionStateWriter) -> ExtensionMutationResult`。

Plan 固定 namespace、entity/version precondition、statement/payload/time budget 和 digest。Reader/Writer
不暴露 SQL、ATTACH、PRAGMA、Core table 或其他 Plugin namespace。prepare/apply 位于 Kernel-owned 短
transaction 内，禁止 Provider、Git、process、SSH、scheduler 或网络 I/O；失败必须使整个 Unit of Work
rollback。

`ExtensionStateApplicationService` 是 Plugin 可见的唯一写入口；`ExtensionTransactionCoordinatorPort` 是
Store Adapter 实现的机制 Port。Kernel 在调用 coordinator 前重验 exact Session pin、Extension bundle、
capability binding、Plugin/participant/namespace owner 与 authority generation/fence；Plugin 不能自行选择
participant、绕过 Session guard 或直接调用 SQLite coordinator。

## Driver 边界

`SubordinateDriver` 只公开 `compile` 与 `validate_result`。它必须匹配 exact
`DriverManifest.owning_plugin_id`、route kind、required Adapter Port、workload/result contract
digest。Driver 没有 dispatch 方法，不拥有 tool/state namespace，也不能在 Session pin 后替换 route。

## 跨层与同层通信

```text
Plugin -> typed Kernel application service -> Kernel canonical mutation
Kernel -> Port -> selected Adapter
Plugin manifest -> capability requirement -> Kernel resolver -> exact route
owning Plugin -> subordinate Driver -> typed workload -> Compute/ControlledOperation
```

同层 Plugin 不 import 彼此 repository/service；按 capability contract 解析。同层 Adapter 不互相推断
语义，由 owning Kernel/Plugin service 编排。同层 Driver 不直接调用另一个 Driver，也不自行 fallback。
共享大文件只传 `PublishedRevision + RevisionPathRef`；跨边界外部效果只传 intent/operation/receipt。

详细 authoring 规则见
[`docs/v3/plugin-authoring-guide.md`](../../docs/v3/plugin-authoring-guide.md)。
closed schema reference 见
[`extension-composition-manifest-reference.md`](../../docs/v3/extension-composition-manifest-reference.md)。

```bash
uv run pytest packages/openzyme-extension-spi/tests
uv run python scripts/qualify-openzyme-contract-wheels.py
```
