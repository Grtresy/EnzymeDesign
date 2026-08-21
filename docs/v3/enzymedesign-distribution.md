# EnzymeDesign Distribution

本页描述 `enzymedesign@0.1.0` 的产品组合边界。它是显式 Distribution，不是 OpenZyme 的新语义层，也不把
`openzyme-standard` 当作源码依赖。

## 组合与身份

canonical 配置是 `distributions/enzymedesign/openzyme-composition.toml`；
`enzymedesign-distribution` wheel 内携带完全相同的资源。启动前必须通过 manifest digest 精确选择 Kernel、
Adapters、通用 Plugins、Product Plugins 与 subordinate Drivers。环境中已安装但未列入 manifest 的包不会形成
ambient capability；重复 tool name、缺失 required Plugin、Driver owner 漂移或 manifest digest 漂移均在加载
runtime surface 前失败。

当前 manifest 状态是 `active`，表示其 exact component graph 已通过结构化 activation：8 个 Adapter、14 个
Plugin、8 个 Driver、32 个 Plugin declared tool 与 5 个 Kernel workspace base tool（总计 37 个），并且 Driver
只声明实际消费的 process/workspace/scheduler Adapter
Port。`build_enzymedesign_fresh_install_seed()` 把这些 catalog 与 EnzymeDesign owner schema、migration sources、
wheel set 和 layered release identity 绑定。该状态不等于生产 activation；Host 仍须验证并持久化 exact epoch，
真实 offline cutover 仍需独立授权，也不能据此启动 live Provider/HPC。

当前 source 还提供 typed `EnzymeDesignPluginRuntimeSurfaceSet`。在 read-only startup proof 成功后，
`mount_enzymedesign_extension_surfaces()` 将 32 个 Plugin tools、13 条 capability routes、2 条 HTTP routes、
5 个 projections、5 个 workers、2 个 finish validators 和 3 个 transaction participants 交给 Kernel exact
mount gate；少一项、多一项、owner/driver/digest 漂移都会 fail closed。

`build_enzymedesign_application_runtime()` 是产品 application composition root：它在 read-only proof 之后核对
8 个 selected Adapter runtime binding，精确合并 5 个 Kernel 与 32 个 Plugin tool runtime，随后才构造 SQLite
writer、capability registry、bounded Agent runtime gateway、Kernel command routes、projection、worker 与 validator
bindings。`build_enzymedesign_v2_host_app()` 把这个 runtime 注入通用 Host API；它不经过也不依赖
`openzyme-standard`。non-live 回归已从该组合根执行真实 Kernel Session bootstrap，并证明缺少任一 Adapter 时
`mutation_applied=false` 且不暴露 writer。

产品组合根同时把 `openzyme.compute` 的 transaction participant 绑定到 Kernel-admitted extension-state
application、Store-owned SQLite coordinator/query 和 `openzyme_compute/execution` namespace，并构造 Kernel
continuation service。Plugin 不获得 raw connection，也不直接写 Core table。真实 SQLite restart 回归会重新构造
这些 service/repository，再证明原 invocation、route、opaque handle、terminal result 与 owner continuation 可读，
且同一 request 的 external dispatch count 始终为 1。

HMMER/Vina 的正式 application bridge 由一次性
`EnzymeDesignFormalComputeApplicationBinding` 在 runtime writer 可达前绑定：Kernel gateway 先重验 affordance
并下传 exact `ToolDispatchBinding`，Driver 只编译 typed workload，Compute 才拥有 ControlledOperation 与声明式
runner Port。formal source resolver 只读取 canonical `PublishedRevision`、publication-owned
`RevisionPathVerificationReceipt`、ready owner workspace 和 adopted Session capability binding；verification receipt
没有虚构的 Session 字段，SQLite Adapter 通过其明确的 publication foreign key 查询。submit 前还会重新验证
authority generation/fence、workspace generation、inventory generation/digest、capability proof 与 exact route。

Compute 自身的 durable result/continuation restart 闭环已经证明；Workspace operations 与 Slurm
submit/cancel 也分别使用持久 SQLite ledger，跨 Adapter epoch 只 reconcile 原 occurrence。远端
`openzyme-workspace-runtime` helper 已作为 exact version/build/qualification/target-generation resource fact
进入 affordance。

状态必须逐级说明，不能混用：

| 状态 | 只证明什么 | 不证明什么 |
| --- | --- | --- |
| `selected` | exact Distribution manifest 选择了组件 | runtime 已构造或 target 可用 |
| `runtime_mounted` | exact runtime identity/surface 已装配 | 外部 target 已通过资格或部署已切换 |
| `qualified` | exact target/provider 的当前 receipt 满足要求 | Session 已采用该 inventory 或生产流量已切换 |
| `cutover` | 真实部署已采用该 Adapter/Plugin/configuration | 某次 live 外部调用已获授权 |
| `live` | 一次明确授权的真实外部调用实际发生 | 结果自动成为 publication、Science adoption 或 Task terminal |

当前真实 non-live 产品场景已闭合 `selected + runtime_mounted`：从通用 Host、Session composition pin、authority、
真实 immutable publication、adopted inventory 和 affordance/route，经 mounted HMMER/Vina Drivers、durable Compute
lifecycle 与声明式 fake runner，到 terminal result、owner continuation 和 Science finish validator；Task 在整个
流程后仍为 `todo`。该场景不声称真实 SSH/Slurm/HPC target `qualified`、`cutover` 或 `live`。

## 产品能力

Distribution 精确选择以下垂直 owner：

- `enzymedesign.aox`：AOX workflow、roles、scientific file contract、finalizer 和 qualification receipt；
- `enzymedesign.aox.executor`：fixed references、motif/threshold、similarity 与 deterministic calculations；
- `enzymedesign.hmmer`：HMMER ToolSpec、qualification、local/HPC typed workload Drivers；
- `enzymedesign.sequence.toolpack` 与 `enzymedesign.bio-providers`：序列解析及 UniProt/RCSB/InterPro 产品语义；
- `enzymedesign.bio-provider-http`：上述数据库能力的 HTTP mechanism Adapter；
- `enzymedesign.structure`、`enzymedesign.vina`、`enzymedesign.alphafold`：结构、对接和预测能力；
- `enzymedesign.docking.preprocess`：RDKit/Meeko/Open Babel 前处理语义与 qualification。

HMMER/Vina 等 Plugin 不 import HPC/SSH/Slurm。它们声明 capability requirements 和 closed workload；Compute/HPC
Plugin 提供 route/target inventory，SSH/Slurm Adapter 执行机制，Kernel 对 Plugin activation、resource facts、
Agent authority 与 workspace readiness 求交。Agent 必须选择 Session 已绑定的 exact route，不允许自动切 target、
local fallback 或 turn-time SSH 探测。

## AOX 注入边界

`build_enzymedesign_scientific_contributions()` 构造 AOX workflow registry、
`AoxScientificDeliverableRequestHandler` 与 exact executor calculation-receipt validator。通用 Host 只接收
`ScientificWorkflowContractRegistry`、`ScientificDeliverableRequestHandler`、
`ScientificPublishedFileReadPort` 和 `ScientificDeliverableFinalizationPort`，不 import AOX 或 executor。

当前 AOX source inventory 中没有独立 HTTP route、worker、projection 或 UI renderer，因此 manifest 对这些
contribution 精确为空；其唯一 sandbox capability route 由 AOX Plugin runtime bundle 绑定 exact
`enzymedesign.aox.executor` Driver。不能为了让清单看起来完整而注册无真实 runtime 语义的占位实现。

## 文件、执行与终态

Product Plugin 输入输出使用 workspace-root-relative path 和 immutable `PublishedRevision`/
`RevisionPathRef`。正式 HMMER、Vina、AlphaFold 和结构分析通过 typed `ExecutionWorkloadSpec` 进入 Compute
lifecycle；`hpc.workspace.exec` 的原始 Shell receipt 仅是 exploratory execution evidence。

以下事实彼此不等价：Provider/Driver/进程成功、私有 workspace 中存在文件、revision 已
checkpoint/publish、Science operation 已显式 adopt、Task owner 已调用 `task.finish`。任何层都不得从前一项
自动推导后一项。

## Non-live 验证

```bash
.venv/bin/pytest -q \
  packages/enzymedesign-aox/tests \
  packages/enzymedesign-aox-executor/tests \
  packages/enzymedesign-hmmer/tests \
  packages/enzymedesign-sequence-toolpack/tests \
  packages/enzymedesign-bio-providers/tests \
  packages/enzymedesign-bio-provider-adapters/tests \
  packages/enzymedesign-structure/tests \
  packages/enzymedesign-vina/tests \
  packages/enzymedesign-alphafold/tests \
  packages/enzymedesign-docking-preprocess/tests \
  packages/enzymedesign-distribution/tests
```

产品级跨层证明可以单独运行：

```bash
.venv/bin/pytest -q \
  packages/enzymedesign-distribution/tests/test_distribution.py::test_real_product_composition_runs_hmmer_and_vina_through_one_pinned_graph
```

该命令证明真实内部 composition、明确 fake 外部 Ports 与终态分离，不证明真实 target 的 production cutover 或
live 可达性；最终仍需 exact wheel closure、三种 composition profile、startup proof 和离线迁移验收。
