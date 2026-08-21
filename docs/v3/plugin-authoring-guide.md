# OpenZyme Plugin 开发指南

本文定义 `separate-openzyme-kernel-from-capability-extensions` 迁移目标下的 Plugin/Driver 作者契约。
当前 target wheels 即使可构建也不会 ambient activate；本指南不表示任一未被 Distribution/Session 精确选择的
能力已经可用。

## 1. 先判断组件种类

如果组件只是实现已存在 Port，例如 SQLite 存储、Git/LFS workspace、Tavily search provider、
SSH/SFTP 或 Slurm，它是 Adapter。如果组件新增研究、科学 attempt、正式计算、HMMER 或 Vina 语义，
它是 Plugin。如果它只把某个 Plugin 的 typed request 转为 local/container/HPC workload，它是
subordinate Driver。安装选择属于 Distribution。

一个组件不能同时利用名字规避边界：声明为 Adapter 却注册 Agent-facing semantic tool、声明为 Driver
却拥有顶层 state namespace，activation 都必须失败。

## 2. Manifest 必须纯且闭合

manifest construction 只能创建不可变 descriptors，不得：

- 读取 secret、数据库、workspace 或部署状态；
- 执行 `which`、SSH、HTTP、Provider、Git 或 subprocess；
- 枚举所有已安装包并自动激活；
- 根据瞬时 health 改写 contract digest；
- 注册未被 Distribution 选择的 tool/route/worker。

`PluginManifest` 固定 component/build/contract identity、required Kernel/SPI contracts、provided/required
capabilities，以及每种 contribution 的 exact ID/digest。若拥有状态，必须同时声明唯一
`state_namespace`、schema/migration contributions、aggregate migration bundle digest 和受限 transaction
participant。

wheel 通过 `[project.entry-points."openzyme.extensions"]` 暴露一个 locator factory。factory 只能返回纯
`ExtensionManifestLocator`，不得注册 runtime、读取 secret 或探测环境。实际 manifest 是包内 closed JSON；
loader 会拒绝 duplicate/unknown field，重算 canonical digest，并验证 locator 与 installed distribution 的
exact name/version/kind。editable install 的 `.pth` 只允许纯路径行，绝不执行其中的 Python。entry point 被
发现不等于 component 被启用，只有 Distribution allowlist 才是 activation authority。

## 3. 调用 Kernel

Plugin 只能依赖 `openzyme-extension-spi` 的 application Protocol。每个 command 必须携带 Host 生成的
`KernelCommandContext`；Plugin 不能自行补造 authority generation、fence、Session version、
capability binding 或 route。

| 需求 | 使用的 service | 禁止替代 |
|---|---|---|
| 查询/显式完成 Task | `TaskApplicationService` | 直接 repository write；worker 自动完成 |
| delegation/message/handoff | `ProtocolApplicationService` | 同步运行 recipient |
| 请求/消费 approval | `ApprovalApplicationService` | 把用户文本当 approval |
| admission 权限检查 | `AuthorityApplicationService` | Plugin-local role 判断 |
| checkpoint/publication/path verification | `PublicationApplicationService` | mutable path/Host locator |
| 外部 effect | `ControlledOperationApplicationService` | 直接 Provider/SSH/Slurm dispatch |
| durable resume | `ContinuationApplicationService` | process-local callback 当真值 |
| 安全错误 | `FailureApplicationService` | 吞异常或返回伪 success |
| route/affordance 查询 | `CapabilityQueryApplicationService` | 自行探测 target 或换 route |
| tool invocation audit | `ExtensionInvocationApplicationService` | 私有日志替代 canonical identity |
| evidence register/validate | `TaskEvidenceApplicationService` | receipt 自动完成 Task |

Kernel receipt 必须保留 `mutation_applied`、effect certainty、event/entity refs 和
`fallback_performed=false`。Plugin 不得把 stale/no-effect command解释为已经发生。

## 4. Plugin 之间如何协作

Plugin A 不 import Plugin B 的 implementation。A 在 manifest 中声明 capability ID、contract/version、
operations 和必要的 `same_target_as`；Kernel resolver 从当前 Distribution、Session binding、target
inventory 和 route catalog 返回满足约束的 route。

例如 HMMER Plugin 声明 formal revision execution 与 `software.hmmer>=3.3,<4`。HPC Plugin 可以提供
qualified route，但 HMMER 不知道 SSH/Slurm 包名。Agent 在当前 binding 中显式选 route；dispatch 前
Kernel 再验证 affordance。没有 route 时返回 typed blocker，不自动改为 local、另一集群或 raw shell。

## 5. Tool 与 affordance

`ToolContribution` 必须绑定 owning Plugin、`ToolSpec`、runtime identity、required authority、
capability requirements、approval policy、workspace 和 explicit-route requirement。canonical tool name
碰撞会拒绝整个 activation，不存在后注册覆盖。

canonical Plugin tool name 必须是 dotted name。HTTP route 使用 closed method enum 和 normalized absolute
template path；尾斜线折叠后相同的 `METHOD + path` 视为同一 key。capability route ID、HTTP route ID、
Driver ID、projection、worker、validator、qualification 和 state/migration namespace 同样是全局
all-or-nothing collision domain。

Declared catalog 表示 Session 固定 bundle 理论上定义的工具；per-turn affordance 才表示某 Agent 此刻
可调用的子集。模型 function list 只包含 `AVAILABLE` 与 `AVAILABLE_WITH_APPROVAL`；
`capabilities.inspect` 可显示非隐藏 blockers；`HIDDEN` 对两者均不可见。

Tool runtime 的 public `ToolResult` 不能携带 raw exception、process/client handle 或 private path。
完整 traceback 用同一 `diagnostic_id` 写 Host private diagnostic。

## 6. 状态与事务

Plugin state 使用独立数据库或同库 namespaced tables，但语义 owner 始终是 Plugin。若需要与 Kernel command
原子提交，只能注册 `ExtensionTransactionParticipant`：

- prepare 只读 declared namespace，返回 immutable mutation plan；
- apply 只通过 namespace-confined writer 执行 plan；
- plan 声明 expected version、最大 reads/mutations/payload/duration；
- participant failure 使 Kernel + Plugin mutation 全量 rollback；
- transaction 内禁止任何外部 I/O；
- 不允许 `on_any_event`、raw SQL connection 或 arbitrary Core table access。

Plugin 的 receipt、worker、publication 或 scientific closure 都不能自行写 `Task=completed`。只有 Task
owner 的显式 `task.finish` 触发 read-only validators 后，Kernel 才能提交终态。

## 7. Projection、worker 与迁移

Projection 只进入 `extensions[plugin_contract_id]`，必须有独立 schema/digest、授权、redaction、
item/byte budget 和 pagination cursor。Core reducer 不读取 extension payload 推导策略或终态。

Worker claim 绑定 activation epoch、source version、lease/fence 和 bounded payload。worker restart 不得
重复 unknown effect；continuation 固定原 route。

Migration 只操作 manifest 声明的 namespace。required/optional Plugin 的 schema、digest、namespace、
collision、cycle 或 migration 错误都阻止 activation。optional 未安装为 inactive；contract-valid 但
resource route 不足可以 degraded。

Runtime implementation 不在 import 时注册。Plugin 为每个 manifest contribution 提供 structural SPI object，
并组成一个 exact `PluginRuntimeContributions`：tool runtime 回显 owner/runtime/ToolSpec；capability route 回显
owner/route/Driver；HTTP route、projection、worker、validator 和 participant 回显各自 canonical ID。
composition root 只能在 `DeploymentActivationGate` 已 active 后构造这些对象，Kernel 先验证所有 Plugin bundle，
再一次性返回 mount set。少一个 contribution、多一个 ambient contribution、manifest digest drift 或 Driver
owner 不匹配都会使整个 mount 失败，不能先挂成功的 route 再降级其他部分。

Plugin factory 的依赖只应是本指南第 3 节的 application services、namespace-confined state store 与明确 Port；
不得接收 FastAPI app、Host foundation、`CoreRepositories`、raw connection 或 provider client。AST/wheel gate
与 runtime mount owner checks 同时约束这一边界。

## 8. Driver

Driver 的 `compile` 输入含 owning Plugin、tool、route 与 exact contract digests；输出是 closed typed
workload。它不持有 credential、不调用 scheduler/provider、不选择 target。`validate_result` 只按 owning
Plugin result contract 验证返回；dispatch、observe、reconcile、cancel 由 Compute/ControlledOperation
及选定 Adapter 执行。

## 9. 验收清单

- wheel 运行依赖只有允许的 Contracts/SPI/public capability contracts；
- import/manifest construction 零 I/O；
- unknown manifest field、duplicate contribution、wrong owner、orphan Driver 均失败；
- no Plugin profile 中 Kernel 仍可运行基础协作；
- absent/degraded Plugin 不泄露 tool/route/projection；
- direct repository/Host/Adapter implementation imports 被 AST gate 拒绝；
- lost dispatch response 保留 `dispatch_in_doubt`，无 retry/fallback；
- source、README、主架构、相关 `docs/v3/` 与 tests 同步。

manifest 字段、selection key、catalog digest 和 activation epoch 的精确定义见
[Extension composition manifest reference](extension-composition-manifest-reference.md)；部署/Session/upgrade
操作见 [Deployment composition operator guide](deployment-composition-operator-guide.md)。

本地基础验证：

```bash
uv run pytest packages/openzyme-extension-spi/tests
uv run python scripts/check-openzyme-architecture.py
uv run python scripts/qualify-openzyme-contract-wheels.py
```

最后一条命令不是单一“大环境”import smoke。它离线构建当前目标工作区 wheel，并在五个独立 venv 中分别验证
Contracts+SPI、Kernel、Standard、runner 与 EnzymeDesign component set；同时核对 wheel `METADATA`、精确
安装闭包、显式允许且已缓存的锁定第三方 wheel、禁止的旧 distribution 和 import-time I/O。缓存缺失直接失败，
不得联网获取依赖。新增 Plugin/Adapter/Driver 若进入 Distribution，必须
更新对应 profile roots/预期闭包测试；不得只让它在开发 workspace 的 ambient editable imports 中可用。
