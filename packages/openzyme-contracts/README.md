# openzyme-contracts

`openzyme-contracts` 是 OpenZyme 的纯协议包，也是跨 Distribution 可复用基础语义的 canonical owner。
它不选择 Adapter、不加载 Plugin，不执行数据库、文件、进程、网络或 Provider I/O。

## 当前 canonical surface

- identity：closed identifier、canonical JSON、SHA-256 digest；
- control plane：`Session`、`Task`、`Lane`、`AgentMember`、Inbox/Approval、runtime signal/lease、
  `ControlledOperation` 与 `ContinuationState` 的纯 DTO 和 closed enum；
- repository binding：Git-shaped `ProjectRepositoryBinding`、ref namespace policy 与 immutable
  `SessionRepositoryBindingPin`；
- checkpoint/publication：workspace observation、private-ref proof、verified checkpoint、publication
  intent/manifest/remote receipt、append-only `PublishedRevision` 与 fetch identity；
- revision collaboration：`RevisionPathRef`、`ProtocolFileHandoff` 与 generic
  `ControlledOperationResultRef`，以及只返回 typed observation/receipt 的
  `WorkspaceRevisionBackendPort`；
- authority：operation-scoped `AuthorityGrant` 与公开 `AgentAuthorityLease`；
- pre-Session authority：短时 `SessionBootstrapAuthorization` 与只读
  `SessionBootstrapAuthorityVerifierPort`，用于在 root Agent lease 尚不存在时验证 operator 的 exact
  project/Session/root-lease/composition-pin/binding 权限；
- capability：Extension/Resource facts、`RouteRef`、`SessionCapabilityBindingRevision`；
- tools：`ToolSpec`、provider-independent `ToolInvocation` 和 public-safe `ToolResult`；
- evidence：domain-neutral `EvidenceRef`；
- reliability：ControlledOperation execution/event/private dispatch receipts、runtime command、
  continuation delivery、mutation scope/writer、quiescence receipt；
- failure：`FailureObservation`、private diagnostic record、effect certainty 与 retry eligibility；
- workspace runtime：closed `WorkspaceGeneration` lifecycle、ready-only runtime binding、
  Observation/Filesystem/Process/Transfer requests、receipts 和 Ports。
- infrastructure Ports：`ControlStorePort`/bounded `KernelUnitOfWork`、CAS mutation、durable event/outbox、
  `ClockPort`、`IdGeneratorPort`、credential material 与 controlled-effect Adapter Port。

`ExternalEffectCertainty` 是通用 effect certainty 的唯一枚举。Workspace Runtime 不再维护另一套
`settled` 布尔/枚举。四类 capability facts 也不能互相作证：安装了 Plugin 不证明 target 有软件，
resource fact 不证明 Agent 有权，authority 不证明 route 可用，affordance 不证明 effect 已发生。

`ToolSpec` 是唯一公共工具规格，嵌套 JSON schema 在内存中被冻结，`to_dict()` 和
Provider projection 恢复标准 JSON list/object。`ToolInvocation`/`ToolResult` 只表达完整身份与公开
安全回执；旧 Runtime 过渡期的 handler 对象已明确改名为
`ToolDispatchInvocation`/`ToolDispatchResult`，其 `private_diagnostic` 绝不得穿透公共契约。

## Identity、owner 与生命周期

Contracts 只定义不可变 DTO、closed enum 和 Protocol；Kernel 或 owning Plugin 才定义状态转换：

| Contract | canonical writer | 生命周期事实 | 持久化 owner |
|---|---|---|---|
| `Session` / `Task` / `AgentMember` | Kernel application service | 显式 command、owner 与 terminal rule | Control Store Adapter |
| `ProjectRepositoryBinding` / `SessionRepositoryBindingPin` | Kernel repository-binding service | versioned binding 与 Session immutable pin | Control Store Adapter |
| checkpoint/publication contracts | Kernel publication service | private checkpoint proof、frozen intent、remote receipt、immutable published revision | Control Store Adapter；Git/LFS bytes 由 Workspace Adapter |
| `WorkspaceRevisionBackendPort` | Kernel checkpoint/publication service | observe commit/manifest/private ref、dispatch/observe publication、verify/read immutable path | Git/LFS Workspace Adapter |
| `AgentAuthorityLease` | Kernel authority service | generation/fence/active/revoked/expired | Control Store Adapter |
| `SessionCapabilityBindingRevision` | operator/admin Kernel command | immutable monotonic revision | Control Store Adapter |
| `ControlledOperationExecution` | Kernel ControlledOperation service | admission 到 terminal/reconcile | Control Store Adapter |
| `FailureObservation` | Kernel Failure service | append-only source-version observation | Control Store Adapter |
| `WorkspaceRuntimeBinding` | Kernel/HPC owning service | exact owner/generation/provider/target binding | owning service + Store Adapter |
| `WorkspaceGeneration` | Kernel workspace-identity service | monotonic generation/state version、closed lifecycle、settled transition receipt | owning service + Store Adapter |

Workspace request contracts 以 content-bound intent digest 固定 exact binding、root-relative path、operation、
argv/cwd、authority generation/fence、process epoch、timeout/output/stdin budget、transfer ref 与
idempotency。`WorkspaceOperationReceipt` 还把 bounded result payload 的 digest/media type/size 纳入 receipt
identity，但安全投影不复制原始 payload；它对
`no_effect`、`dispatch_in_doubt` 和 known effect 使用互斥 mutation fact：不确定 dispatch 必须保留
`mutation_applied=null`，不能伪装成未修改；所有 receipt 都固定 `fallback_performed=false`。
三个 effectful Port 都额外提供 `reconcile(original_request)`：调用方必须复用原 operation、intent、authority、
workspace generation 与 route；该方法只能观察已有 Adapter receipt/ledger，不能再次执行 argv、文件 mutation
或传输。没有足够证明时仍返回同一 identity 的 `dispatch_in_doubt`，不得猜成 `no_effect`。

DTO 自身不能完成 Task、采用 inventory、选择 route、发布文件或重试外部 effect。
`KernelUnitOfWork` 只暴露 immutable snapshot、expected-version mutation、event/outbox 与 commit/rollback；
它不暴露 SQLite connection、SQL、Host service 或 Provider client，也不会被直接交给 Plugin。

## 兼容性

通用 control-plane、repository-binding、checkpoint/publication、reliability 与 failure contracts 均由
本包唯一实现。旧 `openzyme_domain` compatibility modules、顶层别名和 mixed aggregate 已删除；
`docs/v3/architecture/temporary-reexport-ledger.json` 的 active entries 为空，架构门禁拒绝重新引入旧 namespace。

公开 `@2` 只使用 `AgentAuthorityLease`，不导出 `AgentCapabilityLease` alias。首轮仅保留旧物理
SQLite 表名，由 store mapping 与离线 migration ledger 证明；不在 Contracts 中泄露表名。

首次 Session 是唯一不能由 Session-bound Agent lease 自我授权的入口。Contracts 为此定义的 bootstrap
authorization 绑定 root lease、immutable composition pin、revision-1 capability binding 与 Extension bundle
identity；具体 HTTP principal、RBAC、签名或 operator credential 验证仍由 delivery security 实现。它不是
AgentAuthorityLease alias，也不能授权后续 Task、workspace、runtime 或 external effect mutation。

当前明确保留 Git-shaped revision contract：commit/tree、private/public ref、Git object mode/OID 与 LFS
OID/size 仍是 checkpoint/publication 的精确身份字段。这是已确认的协议选择，不授权 Contracts 执行 Git
命令、读 repository root、签发 credential、验证 LFS bytes 或 push remote；这些机制只能由选定的
Workspace Adapter 实现。未来若引入非 Git backend，必须另开 change 版本化协议，不能在本契约中静默兼容。

`WorkspaceRevisionBackendPort` 不暴露 repository root、Git subprocess、credential、transport client 或
LFS object locator。Adapter 只能返回 exact commit/manifest/path observation、publication remote receipt
和有界 byte receipt；Kernel 仍是 checkpoint/publication lifecycle 与 canonical state 的唯一 writer。
dispatch 必须显式接收 `WorkspacePublicationDispatchIdentity`，其中只含 receipt/execution identity、
dispatch generation 与 fence；这解决 Adapter 生成受控回执时的身份来源。已持久化回执通过
`observe_publication(binding, intent, original_receipt)` 重验；dispatch response 丢失时只能调用
`reconcile_publication(binding, intent, original_dispatch_identity)` 观察同一 create-only intent。后者在 ref
缺失时返回 absent，在 exact ref 存在时签发一份新的 observation receipt，绝不重发 effect，也不冒充丢失的
原响应。`observe_publication_namespace` 只返回 publication prefix 下排序、带 digest 的 ref facts，不能扫描
private/historical namespace。
Contracts 的 checkpoint、publication、runtime binding 与 Session repository pin DTO 提供 closed
`from_dict`/`to_dict` 边界；从 Control Store 冻结后的 nested mapping 恢复时仍会重验 schema、digest、枚举、
Git object identity 和 path safety，不能把松散 Adapter/Plugin 字典直接提升为 canonical fact。

## 错误与闭合序列化

- unknown dataclass field、unknown enum、非 JSON payload、NaN/Infinity、无效 digest/identifier 均拒绝；
- public `ToolResult` 不允许携带 process handle、traceback、raw exception 或 private diagnostic object；
- `FailureObservation` 只携带安全事实；完整诊断由 Host 私有 record 保存；
- `dispatch_in_doubt` 永不被改写为 `no_effect`，receipt 不允许声明 hidden fallback；
- interactive/background/unbounded workspace process 在 contract construction 阶段拒绝；symlink/root
  confinement 与 CAS 由 exact Adapter 检查并以 typed no-effect receipt/error 返回；
- contract import 不建立 connection、不扫描 entry point、不读部署配置，也不启动线程/进程。

本包不得依赖 FastAPI、SQLite、LangChain、模型 Provider、Git 实现、Podman、SSH、Slurm、Research、
Science 或 EnzymeDesign。

## `file_workspace_public@2`

`public_workspace` 定义 closed `file_workspace_public@2` DTO 与 media type。root 只有
`schema_version/release/core/extensions`；`release` 包含 `LayeredReleaseIdentity`、release digest 和 public
contract digest；`core` 只允许 Kernel facts 的固定字段；Plugin payload 只能进入 exact
`extensions[section_id]`，并绑定 section contract、projection digest 和分页 cursor。
`core` 还固定每个 section 是 object 或 array，并递归拒绝 artifact-era、`AgentCapabilityLease`、
Research/Reporting/Science/Compute/HPC/EnzymeDesign owner 字段以及 credential、Host/remote locator；这些
规则参与 public contract digest，不能靠调用方约定绕过。
`FileWorkspaceToolReflection` 绑定 declared catalog 与同一 turn 的 affordance snapshot，不公开
`HIDDEN` 工具；公开 affordance state、closed 字段、available tool names 与 capability binding 必须相互一致。
发行 wheel 同时包含 `openzyme_contracts/schemas/file_workspace_public_v2.schema.json`，并通过
`load_file_workspace_public_v2_json_schema()` 读取；JSON Schema、Python DTO/validator、Client snapshots 与 Web
UI `file_workspace_v2_types.d.ts` 由回归测试保持同一字段集合。`ToolAffordanceSnapshot.workspace_generation=0`
只表示该 Agent 尚无已 provision 的 workspace；真实 `WorkspaceGeneration`、checkpoint 和 publication generation
仍必须从 1 开始。`KernelRecordQueryPort` 只允许 Adapter 按 exact Session 和显式 item budget 枚举已由 target codec
重建的 canonical record，不能成为 raw Store 查询或 Plugin 写入口。这些契约本身不会启用 `@2` writer；现有 `@1`
仍只能在离线 cutover 时一次性退出。

```bash
uv run pytest packages/openzyme-contracts/tests
uv run python scripts/qualify-openzyme-contract-wheels.py
```
