# openzyme-standard

官方无必需语义插件 Distribution。

本包已打包 exact composition document，并通过纯 factory 选择 Kernel、SQLite、
Git/LFS、LLM 和 Podman 四个 Adapter slot；required/optional semantic Plugin 集合均为空。
`activate_standard_composition()` 只解析 allowlisted locator、读取 canonical manifest resource 并构建 exact
catalog，不构造 runtime implementation、不打开数据库、不启动进程、不产生外部效果。

`StandardLocalWorkspaceAdapterFactory` 是 Standard 对本地 workspace Adapter 的显式 factory：它只用已固定的
absolute Podman binary identity 与 deployment network 构造 capsule process runner、named-volume backend 和
Git restore observation provider。构造本身不执行 Podman、不探测环境、不分配 volume，也不创建 canonical
workspace。Host 只依赖窄 factory Protocol；配置了 capsule 却未由 Distribution 注入 factory，或 factory identity
与 Host 配置不一致时，创建 runtime surface 前 fail closed。

`StandardRepositoryAdapterFactory` 同样冻结 exact repository settings 与 durable-root boundary，并唯一构造
Git/LFS root manager、binding mechanism、`LocalGitRevisionBackend`、workspace recovery mechanism 和 credential
issuance store。Host 不再拼接 bare/LFS locator、不实例化 Git/LFS mechanism，也不能从 endpoint 或环境自动选择
Adapter；配置了 repository service 却没有这个 Distribution factory 时，在开放 repository writer/route 前
fail closed。factory 构造不执行 Git、创建 ref、签发 credential 或写 canonical state。

`StandardLlmAdapterFactory` 唯一构造 Standard 选择的 `LlmRuntimeAdapter`、exact
`LangChainProviderBackend`；迁移期 chat-model factory 仅供待删除的旧 harness caller，不能进入目标 Host
surface。generic Host 只提交已解析 settings、
limiter 与 credential material，不 import LangChain、不选择 Provider，也不创建 token ledger；LLM 已启用但
没有显式 Distribution factory 时在 provider import/network 前 fail closed。factory 构造本身不访问网络，
live connectivity 仍是另行授权的显式诊断操作。

当前 composition 是结构上可激活的 `active` manifest：恰有四个 Adapter、零 Plugin、零 Driver、零
extension tool。Kernel 唯一贡献 13 个基础工具：八个稳定协作动词
`approval.request/capabilities.inspect/protocol.send/task.create/task.delegate/task.finish/task.update/world.inspect`
以及五个 `workspace.status/fs.read/fs.list/fs.mutate/exec` 工具。
`mount_standard_kernel_workspace_tool_set()` 在 exact deployment epoch 通过后挂载 collaboration、gateway-owned
`capabilities.inspect` 与 workspace runtime，再以 active declared catalog 逐项核对 owner/runtime/contract；空
Plugin mount 与非空 Kernel base runtime mount 是两个不同事实，Standard 不会把 Kernel 伪装为 Plugin，也不会留下
“目录可见但 runtime 缺失”的半激活状态。

`StandardLocalWorkspaceRuntimeFactory` 把上述 Kernel runtimes 所需的通用 coordinator 连接到 Standard 选定的
Podman filesystem/process Port。它消费 Host 提供的 exact workspace mount resolver、process-isolation Port、
Kernel authority service 与 controlled-operation service，构造阶段不调用 Podman；真实调用仍必须绑定当前
Git-shaped local workspace provider identity、generation、authority 和 controlled-operation receipt。
`StandardOperationalAdapterSelection` 进一步固定本次部署的 bounded Agent runtime、Podman mount resolver、
process-isolation、Git-shaped revision backend 与 exact workspace provisioner；
`build_standard_operational_runtime_ports()` 只在同一个
`SQLiteControlStore` writer 上构造 authority、controlled-operation、workspace、affordance gateway、runtime
outcome、durable command worker 与 provisioning worker graph。生产 capability gateway 的 command-scoped expansion
使用同一 Control Store owner，不使用 in-memory expansion fallback。一个 SQLite connection 不会创建两个竞争
mutation gate 的 writer；该组合过程仍不调用模型、Podman、文件系统、Git 或网络。
`build_standard_fresh_install_seed()` 可把完整 declared catalog 与 Standard owner schema、七类 catalog、wheel set、
Host/client 和 migration sources 绑定，并生成 deterministic fresh deployment proof。`active` 不绕过
`DeploymentActivationEpoch` 的 schema/wheel/composition verification，也不表示真实历史 deployment 已完成 cutover；
没有 exact deployment proof 时所有 runtime surface 仍必须关闭。

fresh factory 现在只通过 Kernel 的 composition/schema/wheel 三 proof coordinator 生成持久化
epoch。`verify_standard_deployment_startup_read_only()` 在进程重启时重算 Store/catalog/schema
proof，检查 installed wheel set 与全部 Session pin/binding/inventory reference，只重新授权原
epoch；随后通过 Kernel `mount_extension_surfaces()` 挂载 manifest 所声明的 exact 空 Plugin runtime set。
该 mount 的 tools/routes/projections/workers/validators/participants 全部为空并有独立 digest；它不打开 Host
writer、不创建 Session、不运行 Adapter，也不激活 ambient Plugin。这样 Plugin-free 不是“尚未 mount”的缺省值，
而是经过 composition/epoch 校验的明确运行事实。

Schema/composition 激活本身不等于 Kernel writer 已可用。真实 writer 必须再经过
`build_standard_kernel_control_store()`；该入口按 `STANDARD_KERNEL_ENTITY_TYPES` 核对每一种
Plugin-free Kernel canonical entity 都有显式 existing-owner-table codec。当前
`STANDARD_KERNEL_ENTITY_TYPES` 的 42 种类型已全部闭合，包括 repository binding/pin、workspace
generation/provisioning intent/receipt/reconciliation/runtime binding、workflow authority/signal link、runtime command/context/
outcome、tool exposure、command-scoped expansion、checkpoint/publication/revision verification、task evidence 与 immutable
`kernel_command_receipt`；入口在 exact
deployment gate 通过后返回真实 `SQLiteControlStore`。缺失、重复或未声明 codec 仍以
`standard_kernel_store_codec_incomplete`、零 mutation、零 fallback 拒绝；不得用 generic JSON payload table、
测试 codec 或旧 `CoreRepositories` 绕过检查。

`build_standard_kernel_publication_runtime()` 只在同一 activation gate 的 repository-writer、runtime 与
external-effect surface 全部授权后，用上述 Store、Kernel authority/publication/controlled-operation services、
选定的 Git-shaped revision backend 和 manifest policy 构造唯一 publication coordinator。构造本身不观察或修改
Git/LFS；缺少 policy 直接拒绝。目标 SQLite focused qualification 已用 fake revision backend 跑通
intent preparation、generic controlled effect、terminal receipt、command receipt 与 immutable
`PublishedRevision` 的完整事务链；这仍不是对真实部署执行 cutover。

Standard focused qualification 已用真实 Plugin-free owner profile、fresh deployment epoch 和 SQLite Store
证明：经测试 verifier 批准的 operator bootstrap 可在一个 UoW 中接纳 exact project repository binding/head、
Session/master、pending exact-generation authority、revision-1 binding/composition pin 与 durable workspace provisioning
intent；HTTP 不执行 clone、volume、provider 或 workspace effect。
`StandardHostKernelCommandGateway` 负责把通用 Host bootstrap invocation 翻译为上述 Kernel command：它创建
root Agent 的 operation-scoped grant、空 Plugin capability binding 和 immutable composition pin，但 operator
authorization 只能由注入的 `StandardSessionBootstrapAuthorityPort` 签发并验证，Distribution 不把 HTTP
authentication 当作 canonical authority。其 Session-scoped route application map 对缺失 route 一律
`standard_kernel_route_unconfigured`，不回退任何 legacy writer。
`build_standard_kernel_application_runtime()` 进一步把同一 target `SQLiteControlStore` 注入 Session bootstrap、
Task/Lane/Agent、Protocol、Approval、AgentAuthorityLease 和 message ingress application services；
`build_standard_v2_host_app()` 将该 gateway、真实 Core projection 与通用 Host security 组装为可运行的
Plugin-free `@2` Host。公开消息 wire 只接受 canonical `message`，并要求 `workflow_refs` 或兼容
`skill_keys` 二选一；内部 route 层保留显式、互斥的 `content` compatibility。用户消息由独立 ingress service
在一个 UoW 中写 conversation document、request-lineage empty workflow authority、signal authority link、user-kind
inbox 和 pending runtime signal，只排队 durable wakeup，不执行 drain、不完成 Task。Standard 的 exact-empty workflow
registry 不扫描安装包、不选择 latest/all/default；master/teammate 两个 resident role 对完整 13-tool catalog 都有
release-bound、全覆盖、Direct exposure policy，缺失或漂移在 startup/preflight fail closed。共享用户身份始终保存在
`sender_actor_id`，root Agent 仅作为 `admitted_by_actor_id` 消费自己的 authority lease，二者不能互相冒充。
`build_standard_kernel_public_projection_provider()` 现在从同一 target Store 的 Session-scoped query index 和
42/42 codec closure 构造 `KernelPublicWorkspaceProjectionService`；
`build_standard_file_workspace_v2_host_surface()` 再把它与 active release 及 exact empty Plugin mount 注入通用
Host delivery surface。真实 HTTP → Distribution gateway → Kernel application → SQLite 路径已经证明 Session
bootstrap、inspection、Task mutation 与消息排队可得到 closed `@2` Core、完整 declared-tool affordance 分类和空
`extensions`，没有 fake provider、`@1` translator 或 ambient Plugin。Distribution route graph 已继续接通
runtime drain、local workspace filesystem/process、checkpoint、publication 与 handoff：`POST .../runtime/drain`
只 admission 一个 durable `RuntimeCommandRecord@1` 并返回 202，receipt 明确
`runtime_executed=false/task_transition_performed=false/fallback_performed=false`；独立 bounded worker 才 claim/fence、
取得 exact workflow/context/exposure、执行 turn 并 terminal settle。workspace effect 只经选定 Adapter Port；
checkpoint/publication/handoff 仍由对应 Kernel application owner 写真值。fresh non-live E2E 已从空 SQLite/空 workspace
root 跑通 bootstrap → provisioning tick → ready → message → durable drain → worker turn → canonical assistant transcript →
同库重启恢复，并显式拒绝外部 filesystem/process/revision fallback；它仍不等于真实 provider 或 production cutover。
显式恢复入口由 Host direct gateway method 接线：reconcile 对公开 precondition 与 canonical Store 的
Session/intent digest/version 双重核对后，只接纳 durable pending reconciliation occurrence 并返回 202；独立 bounded
worker tick 才按该 occurrence 持久化的 claim duration 执行 observation-only `reconcile=True`。successor 只创建单调的
新 generation/intent/lease graph。两者都保留 HTTP actor、idempotency 和 correlation lineage；HTTP 不 claim、调用
Adapter、自动 tick、redispatch、更换 Adapter 或触发 runtime/Task。

## 配置与启动边界

唯一发行组合源是包内 `openzyme_standard/openzyme-composition.toml`；仓库级
`distributions/openzyme-standard/openzyme-composition.toml` 必须逐字段相等。manifest 定位不会自动启用已安装
Plugin。普通启动顺序固定为：离线安装 owner schema/seed → `SQLiteConnectionProvider` 对 exact absolute path 做
Adapter preflight 并打开只读 verifier → deployment factory 只读构造/验证组件 → 关闭 verifier → Adapter 以 exact
deployment schema proof 打开 writer → `preflight_standard_product_composition()` 校验 activation、catalog、完整 role
policy、runtime identity、每项目 repository/workspace/provisioner defaults → `StandardProductLifecycle.start()` 才开放
HTTP admission 并启动 bounded provisioning/runtime worker。Session 轮询只通过 bounded
`KernelSessionDiscoveryPort` cursor，不读取 owner table 或 raw SQL；worker 失败会关闭 admission；stop 先关闭
admission，再等待 worker、执行显式 retirement hook、关闭 opaque Store writer。没有隐式建库、in-memory Store、
provider discovery 或 Adapter fallback。
应用启动应向 `build_standard_v2_host_app()` 传入一个 exact `operational_selection`；仅测试或嵌入式组合可以传入
已经闭合的 `operational_ports`，两者必须且只能选一个。Host app 保存的 runtime graph 只供进程生命周期管理和
诊断，不构成公共 API，也不允许 Plugin 取得 Store。

console entry point 为 `openzyme-standard`，强制 `--config` 指向 absolute
`openzyme_standard_launcher@1` JSON。配置是 closed schema，必须逐项给出 file-backed database path、exact
`module:factory` locator、factory id/digest、component configuration、worker bounds 与 server host/port；不从 cwd、
环境变量或已安装 provider 猜测缺失值。支持 `preflight`、`worker-tick` 与 `serve`：

```bash
uv --project packages/openzyme-standard run openzyme-standard --config /absolute/path/standard.json preflight
uv --project packages/openzyme-standard run openzyme-standard --config /absolute/path/standard.json serve
uv run pytest packages/openzyme-standard/tests/test_standard_v2_host.py
uv run pytest packages/openzyme-standard/tests
```

部署 factory 负责显式提供真实 credential、operator bootstrap authority、repository binding、workspace target 与
Adapter selection；launcher 用 factory id/digest 锁定它，但不会把这些部署私密事实写死进发行包。某条 route 只有
进入 active Distribution surface 且其 exact operational selection 已闭合时才可用，缺失实现不得回退 legacy
surface。

## 发行闭包验证

发行闭包使用仓库根目录的以下 non-live gate 验证：

```bash
uv run python scripts/qualify-openzyme-contract-wheels.py
```

该 gate 从当前 source 离线构建 wheelhouse，并分别在 fresh virtual environment 安装
Contracts+SPI-only、Kernel-only、Standard-only、runner-only 和 EnzymeDesign component set。
Standard Distribution 现在显式依赖通用 Host delivery Adapter；最终 fresh wheel closure 必须在 Host 删除
Science/Compute/HPC/runner 等硬编码依赖后重新封存。目标闭包是 Contracts、Extension SPI、Kernel、Runtime SPI、
SQLite、Git/LFS、LLM、Podman、Host、Client/CLI 与本 Distribution；FastAPI/Pydantic 是 delivery/transport 的普通
基础设施依赖，不形成 extension。gate 会枚举全部已安装工作区发行包和
`openzyme.extensions` entry point owner，拒绝 ambient component，并明确验证 Tavily、Research、
Reporting、Science、Compute/HPC、runner、EnzymeDesign、Biopython、NumPy、RDKit、Meeko 与
Open Babel 均未进入 Standard-only 环境。这个安装证明不等于 deployment activation；Host writer
仍需 exact epoch/schema/wheel/Session binding startup proof。
