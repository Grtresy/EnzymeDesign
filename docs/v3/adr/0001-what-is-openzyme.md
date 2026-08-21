# ADR-0001：What is OpenZyme?

- 状态：accepted，分阶段迁移中
- 决策日期：2026-08-19
- 实施 change：`separate-openzyme-kernel-from-capability-extensions`

## 决策

OpenZyme 是一个让多个长期存在的 Agent，在可授权、可恢复、可审计、基于不可变文件修订的环境中
协作，并安全调用外部能力的执行内核。它不以 AOX、HMMER、Vina、Research、HPC、SQLite、Git、
Podman 或某个模型 Provider 定义自身。

架构必须用两条正交轴表达，不能再把所有组成排成一条“五层依赖链”。

语义所有权轴：

```text
Contracts / Extension SPI
          ↓
OpenZyme Kernel
          ↓
Capability Plugins
          ↓
Product Plugins / EnzymeDesign
```

部署组合轴：

```text
Kernel
+ 选定的基础设施 Adapters
+ 显式启用的 Plugins 与其 subordinate Drivers
+ API / Client / CLI / UI delivery surfaces
= 一个版本化、digest-bound Distribution
```

`OpenZyme Standard` 和 `EnzymeDesign` 都是 Distribution，不是新的语义层。Standard 的 required
semantic Plugin 集合为空；EnzymeDesign 可以把 Science、Compute、HPC、HMMER、AOX 等 Plugin
标成产品必需项，但这不改变它们是 Plugin 的性质。

## 四类组件

| 类别 | 回答的问题 | 可否增加顶层语义 | 依赖规则 |
|---|---|---:|---|
| Kernel | 什么是真实状态、谁能改变 | 是，限跨领域基础语义 | 只依赖 Contracts 与 Extension SPI |
| Adapter | 已有 Port 怎么实现 | 否 | 依赖相应 Port contract，不反向定义 Kernel 状态 |
| Plugin | 系统还能做什么 | 是，限自己的 namespace | 依赖 SPI、公共 Kernel application contract 与 capability contracts |
| Driver | 一个 Plugin 的 typed request 如何落到某 route | 否，隶属于 Plugin | 不能脱离 owning Plugin 激活或拥有顶层 tool/state namespace |
| Distribution | 本次安装选择哪些组件 | 否，只组合 | 显式 allowlist、exact identity、无 ambient activation |

## 层级之间如何沟通

调用方向与状态所有权分开处理：

1. Kernel 通过 implementation-free Port 调用 Adapter；Adapter 返回 typed receipt/outcome，不能直接写
   Kernel repository 或把 mechanism success 推断成 Task 完成。
2. Plugin 通过 narrow Kernel application services 提交 Task、Protocol、Approval、Publication、
   ControlledOperation、Continuation、Failure、CapabilityQuery、ExtensionInvocation 或 TaskEvidence
   command/query；它不能拿 raw SQLite connection、`CoreRepositories` 或 Host 私有 service。
3. Kernel 不 import Plugin runtime。Plugin 只通过 manifest 贡献 tool、capability、route、qualification、
   projection、worker、validator、schema 和 migration descriptor；Host composition root 验证后原子注册。
4. Product Plugin 与通用 Plugin 按 capability ID、contract/version、operation、same-target 和 route 组合，
   不按 Python 包名调用对方内部实现。
5. 跨边界的共享文件只通过 `PublishedRevision + RevisionPathRef`；跨边界外部效果只通过
   `ControlledOperation` 或其受约束的正式 Compute lifecycle。prompt、路径、进程退出或 provider
   response 都不是第二真值。

同一层级之间也不建立任意互调：

- 两个 Adapter 不相互获取内部 client；需要协作时由 owning service 按两个 Port 编排，或由一个明确的
  aggregate Adapter 实现复合 Port。
- 两个 Plugin 不直接访问彼此 repository/service；consumer 声明 capability requirement，resolver 返回
  exact provider/route，交互使用共享 typed contract 和 Kernel invocation identity。
- 两个 Driver 不能互相 fallback；Agent 选择 exact route，dispatch 前重验，route 漂移以
  `tool_affordance_stale / no_effect / fallback_performed=false` 失败。
- 两个 Distribution 不在运行时嵌套。EnzymeDesign 可以复用 Standard-compatible Adapter profile，
  但不能把 Standard 当作语义依赖层或继承一组隐式插件。

## HMMER 经 HPC 执行的例子

HMMER 与 HPC 保持分离：

```text
enzymedesign.hmmer Plugin
  声明 software.hmmer >=3.3,<4、hmmsearch operation、typed workload/result
        ↓ capability requirement
openzyme.hpc Plugin
  提供绑定 target inventory generation 的 compute/workspace route
        ↓ Port
openzyme.hpc.ssh / openzyme.hpc.slurm Adapters
  执行资格检查、远端 workspace 操作或 scheduler lifecycle
        ↓ typed receipt
openzyme.compute Plugin
  以 exact route 监督正式 workload 的 dispatch/observe/reconcile/cancel/result
```

操作员先在 exact target/environment 上运行 qualification，并发布不可变 inventory generation；Session
只能显式采用一个 binding revision。Agent turn 不执行 `ssh which hmmer`，也不自动采用新 inventory。
Resolver 将 Plugin 激活、resource fact、route、Agent authority、workspace readiness 和 health 求交后，
才把 HMMER tool 放入本 turn 的 function list。Agent 调用时必须选择已绑定 route；Kernel 在真正 dispatch
前重新验证 snapshot、lease、generation 和 route，绝不偷偷换集群、版本或本地执行。

目标 `enzymedesign-hmmer` 已按这一边界实现 exact Plugin manifest、`software.hmmer>=3.3,<4` qualification
requirement，以及 local/HPC 两个 compile-only Driver；当前仍处于 legacy callers pending，尚未获得生产 activation。
正式 HMMER 请求编译为 closed `ExecutionWorkloadSpec` 并进入 Compute lifecycle。直接通过
`hpc.workspace.exec` 运行 `hmmbuild`/`hmmsearch` 可以保留为探索性操作，但其进程回执不等于正式
Compute result、Scientific adoption、publication 或 Task finish evidence。

## Workspace Runtime

Shell 与文件 CRUD 是平台底层能力，但 Kernel 只定义 identity、authority、generation、root-relative
request、receipt 和 effect certainty。Local filesystem/Podman、SSH/SFTP/rsync 是 Adapter；HPC Plugin
拥有远端 workspace target 与生命周期；Slurm scheduler 永远与 login/file credential 分离。

`status/stat/list/read/hash` 是 query-only。`write/mkdir/move/copy/remove/apply-patch`、process exec 和
transfer 是 durable ControlledOperation；远端响应丢失可能进入 `dispatch_in_doubt`，不允许自动重发。
Agent 本地工具由 Host 从 current Session/member/generation 推导 binding，不接受 caller workspace ID；
HPC 工具只接受 Host 发出的 opaque workspace ID，不接受 hostname、login、remote root 或 scheduler ID。

## 兼容与迁移

- 已确认没有仓外消费者，因此本 change 不提供旧包跨 release 兼容窗口。
- `AgentCapabilityLease` 的公开名称在 `@2` 改为 `AgentAuthorityLease`；首轮保留物理 SQLite 表名，避免把
  package、语义和数据迁移混成一次不可审计变更。
- 当前保留 Git-shaped revision contract；多 workspace backend 和物理拆 Git repository 均属于后续
  独立 change。
- Python wheel 仍只位于 `packages/`/`apps/`；`distributions/` 只保存配置，不是 Python workspace root。
- optional Plugin 只有“未安装”可成为 inactive；合法但 resource route 不足可 degraded；manifest、
  schema、digest、migration、collision 或 cycle 错误即使发生在 optional Plugin 也阻止 activation。
- 已有 Session 固定 extension bundle、workspace backend 与 capability binding，不支持 hot swap。

## 当前实施状态

当前仓库已经以 `openzyme-contracts`、`openzyme-extension-spi` 和 `openzyme-kernel` 作为唯一基础
语义 owner；SQLite、Git/LFS、LLM 与 Podman 是显式 Adapter，两个 Distribution manifest 可构建 exact
active graph 和 isolated fresh proof。旧 `openzyme-core`、`openzyme-domain`、`openzyme-runtime`、
`openzyme-execution` 及旧 Host composition 已从 workspace、wheel、entry point 和生产 import graph 删除。

这表示目标代码与组合已经实现，不表示真实历史部署已经迁移。相关组件仍以
`target_implemented_not_cutover` 明确区分 source implementation 与 deployment activation；在获得单独 cutover
授权、完成 quiescence/ledger 检查和离线 `@2` migration proof 前，不得修改真实部署或把 diagnostic/fresh
proof 误述为设备 activation。
