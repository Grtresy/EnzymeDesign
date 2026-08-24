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
8 个 selected Adapter runtime binding 的 component/manifest/contract/build/slot/target identity；所有 effectful
operational object 都从这些 binding 内的 exact runtime 派生，不再由调用者另传第二套实现。随后精确合并 5 个
Kernel 与 32 个 Plugin tool runtime，再构造 SQLite
writer、capability registry、bounded Agent runtime gateway、Kernel command routes、projection、worker 与 validator
bindings。`build_enzymedesign_v2_host_app()` 把这个 runtime 注入通用 Host API；它不经过也不依赖
`openzyme-standard`。non-live 回归已从该组合根执行真实 Kernel Session bootstrap，并证明缺少任一 Adapter 时
`mutation_applied=false` 且不暴露 writer。

产品组合根同时把 `openzyme.compute` 的 transaction participant 绑定到 Kernel-admitted extension-state
application、Store-owned SQLite coordinator/query 和 `openzyme_compute/execution` namespace，并构造 Kernel
continuation service。Plugin 不获得 raw connection，也不直接写 Core table。真实 SQLite restart 回归会重新构造
这些 service/repository，再证明原 invocation、route、opaque handle、terminal result 与 owner continuation 可读，
且同一 request 的 external dispatch count 始终为 1。Compute 现在会在 route effect 前持久化
`not_started -> reconcile_required` occurrence；即使 response loss 没有 provider handle，或 dispatch 抛出 typed
uncertain error，跨 Host epoch 也只允许按 occurrence identity reconcile，不能重新 dispatch。

HMMER/Vina 的正式 application bridge 由一次性
`EnzymeDesignFormalComputeApplicationBinding` 在 runtime writer 可达前绑定：Kernel gateway 先重验 affordance
并下传 exact `ToolDispatchBinding`，Driver 只编译 typed workload，Compute 才拥有 ControlledOperation 与声明式
runner Port。formal source resolver 只读取 canonical `PublishedRevision`、publication-owned
`RevisionPathVerificationReceipt`、ready owner workspace 和 adopted Session capability binding；verification receipt
没有虚构的 Session 字段，SQLite Adapter 通过其明确的 publication foreign key 查询。submit 前还会重新验证
authority generation/fence、workspace generation、inventory generation/digest、capability proof 与 exact route。
compiled Driver workload、Driver/validator identity 和 result contracts 会随 Compute request 持久化；terminal
result 只有通过 exact HMMER/Vina `validate_result()` 后才可落库并注册 owner continuation，`raw_shell=true` 不得
进入正式结果链。

Compute 自身的 durable result/continuation restart 闭环已经证明；Workspace operations 与 Slurm
submit/cancel 也分别使用持久 SQLite ledger，跨 Adapter epoch 只 reconcile 原 occurrence。远端
`openzyme-workspace-runtime` helper 已作为 exact version/build/qualification/target-generation resource fact
进入 affordance。

状态必须逐级说明，不能混用：

| 状态 | 只证明什么 | 不证明什么 |
| --- | --- | --- |
| `selected` | exact Distribution manifest 选择了组件 | runtime 已构造或 target 可用 |
| `runtime_mounted` | exact runtime identity/surface 已装配 | 外部 target 已通过资格或部署已切换 |
| `ready_non_live` | exact 资格单元/profile/Port/fixture/receipt verifier 在禁止 live 下闭合 | 真实 target/provider/software 可用 |
| `qualified` | exact target/provider 的当前 receipt 满足要求 | Session 已采用该 inventory 或生产流量已切换 |
| `cutover` | 真实部署已采用该 Adapter/Plugin/configuration | 某次 live 外部调用已获授权 |
| `live` | 一次明确授权的真实外部调用实际发生 | 结果自动成为 publication、Science adoption 或 Task terminal |

当前 non-live 产品场景已闭合 `selected + runtime_mounted` 下的 HMMER/Vina formal cross-layer slice：从通用 Host、Session composition pin、authority、
真实 immutable publication、adopted inventory 和 affordance/route，经 mounted HMMER/Vina Drivers、durable Compute
lifecycle 与声明式 fake runner，到 terminal result、owner continuation 和 Science finish validator；Task 在整个
流程后仍为 `todo`。场景使用 fake Git-shaped backend、fake runner、固定接受的 Science evidence reader、
no-op Slurm/credentials 和其他 Plugin applications，并直接 seed 部分合法 canonical 前置事实；因此它不证明
14 个 Plugin 的全部生产 application lifecycle 已由正式产品命令自然闭合，也不声称真实 SSH/Slurm/HPC target
`qualified`、`cutover` 或 `live`。

HMMER/Vina package 的 `current_composition_owner=enzymedesign` 表示当前源码确由该 Distribution mount；
`migration_state=target_implemented_not_cutover` 则独立说明真实部署尚未切换，两者不可互相替代。

产品另提供 `build_enzymedesign_external_qualification_catalog()` 与
`build_enzymedesign_external_qualification_plan()`。catalog 从当前 activated Distribution 的 exact Adapter、
Plugin `QualificationSpec` 与 Driver manifest identity 派生 45 个不可拆分单元，不维护第二套 component
selection graph。单元固定绑定 capability、单一 operation、route、target/provider subject、source/build/config、
contract、validator 和 credential locator scope。profiles 为：

| profile | 单元数 | 边界 |
| --- | ---: | --- |
| `base` | 18 | LLM bounded turn、Git/LFS、Podman、UniProt/RCSB/InterPro HTTP readiness |
| `research-provider` | 1 | Tavily bounded query |
| `hpc-primary` | 12 | SSH helper/workspace 与 Slurm submit/observe/cancel/reconcile |
| `hmmer` | 4 | local/HPC `hmmbuild` 与 `hmmsearch` |
| `docking` | 9 | local/HPC Vina/fpocket 与 RDKit/Meeko/Open Babel exact operations |
| `alphafold` | 1 | HPC AlphaFold predict capability/resources smoke |

普通 CI 运行 `./scripts/check-external-qualification-readiness.sh`，显式清除 credential-bearing environment、
设置 `OPENZYME_ALLOW_LIVE=0`，并用 recording backend 完成 success、auth/config failure、timeout、schema/operation
mismatch、response-loss/reconcile negative fixtures。输出 claim 固定为 `ready_non_live`，逐 operation 披露
`deterministic_substitute=true`、`qualified=false`、`cutover=false`、`live_occurrence=false`。真实 qualification
change 现已实现 plan-only identity discovery：当前安全快照对 45 个 unit 做无凭据、无网络、无进程 effect 的
source-bound 观察，已闭合的公共 Bio endpoint 仍只算 `resolved identity`，其他 Provider/target/software 缺口形成
typed operator decision packet，不能自动选择推荐方案。

operator 已选择 LLM/Tavily 推荐方案、local-only Git/LFS、digest-pinned Podman/scientific images、`Diannan/3090`
与 protected operator state root。选择只形成 source-bound decision。需要建账号/locator、创建本地 repository、
build/pull image 或补齐 HPC profile/inventory 时，Distribution 先生成独立 `ExternalIdentityPreparationPlan`；其
authorization 不能产生 qualification receipt，也不能替代后续 qualification occurrence authorization。科学软件
version/image/inventory 是 subject identity，真实 smoke result 是 qualification evidence，两者不得循环依赖。

当前 preparation runtime 已显式组合七个 Batch 1 owner action。受保护状态根为当前 uid 所有的 `0700` 目录，私有
文件为 `0600` 且禁止 symlink；凭据只由 exact plan locator 解析。Podman 只接受仓库内 `base`、`hmmer`、`docking`
三个 source/lock/digest-bound recipe。HPC 只生成独立 `aox-qualification-diannan`、`executor_workspace@2`
qualification-only 配置，并保持 activation 与 scheduler submit 关闭；existing runner config 不会被覆盖。构造 runtime
本身不读 credentials、不建仓、不 build image、不 SSH，也不创建 ledger。

Owner terminal output 使用 `ExternalIdentityPreparationResult` 写入 protected SQLite。后续 effect-free rediscovery
验证 exact action coverage，并用专用 LLM/Tavily/HPC locator 重建 qualification units；本地 Git/LFS 不携带 non-live
credential placeholder。Preparation receipt 仍不是 `qualified` receipt，real probe 需要另一份 exact authorization。
正式本地入口由 root/layout-only bootstrap、canonical authorization writer 与 source-bound Batch 1 executor 三段组成。
executor 在 mutation 前一次性预检全部 locator，不允许 partial credential setup 导致先建仓后失败；已有 image 或 HPC
qualification config 但缺少 terminal ledger result 时必须阻塞人工 reconcile，不能覆盖后伪装成首次 occurrence。成功只生成
`prepared_not_qualified` 私有 packet 和 effect-free rediscovery，不更新 Distribution adoption。

Batch 1 固定为 `base + research-provider + hpc-primary + hmmer + docking`，Batch 2 独立包含 AlphaFold。
`ExternalQualificationDryPlan` 对每批绑定 exact unit/gap、宽松熔断预算、effect allowlist、fault/reconcile、cleanup、
TTL/storage 与 `max_retries=0`。LLM/Tavily occurrence 的现金硬上限分别是 USD 25/USD 10，batch 现金硬上限是
USD 100；较低 warning 只记录诊断，不缩小资格测试。manual workflow 仍固定 `OPENZYME_ALLOW_LIVE=0`，缺少另行的
exact occurrence authorization 时在凭据解析前 fail closed。完成真实 qualification 只得到 `qualified`；cutover
需要第二个 change 和独立确认。

资格恢复不允许通过新 authority 全量重发已经有 current receipt 的 unit。后续 occurrence 可把完整 dry plan 内的
exact checkout source identity 与 failed-unit 子集在首次 effect 前持久化并只执行该子集；同一 authority 的 source/scope 不可改变。subset 全绿只表示
该 occurrence 闭合，batch `qualified` 仍由独立 receipt-set verifier 跨 occurrences 检查全部 unit 的 exact authority、
scope、negative gate、budget、cleanup 和 TTL 后给出，且不会产生 adoption 或 cutover。

资格 bridge 的当前实现边界也保持分层：Distribution 的 exact-unit router 在 owner builder 前验证 occurrence
authorization 及 unit/subject/route/input/schema/credential locator；LLM、Tavily、公共 Bio HTTP 已编译到 typed
Adapter 调用，基础设施与科学 owner 已有防 identity 漂移、hosted Git sync、未固定 image、非隔离资源、raw
scientific execution 和重复 dispatch 的 guard。真实 Git/Podman/SSH/Slurm typed operation builder 与科学 fixed-smoke
workload 尚未执行或裁决，只有 preparation 后形成 exact subject 才能继续实现并在独立 qualification authority 下运行。

## Qualified runtime cutover

Batch 1 cutover 由 Distribution owner 管理，不能由 Plugin、Agent、Host route 或 ambient `.env` 触发。operator CLI
依次执行 `plan`、`authorize`、`apply`，并把 qualification source、deployment source、qualified-owner tree closure、
Distribution/wheel/configuration inventory、44 个未过期 receipt、quiescence 与六类 backup source 绑定为一个不可覆盖
plan。authority 持久且一次性；apply 在任何 mutation 前重新验证全部 receipt 和当前 source，随后按 backup → adoption →
atomic activation → isolated startup readback → cutover receipt 的顺序闭合。

运行时 composition 只消费 adoption ledger 派生的 `EnzymeDesignExternalQualificationAdmission`。该 ledger 精确包含 44 个
operation-scoped fact；AlphaFold 保持 mounted/deferred，但不进入 qualified affordance。缺失、过期、route/subject drift
统一为 `blocked_qualification`，禁止自动换 route、target、版本或 Provider。

上线后 smoke 是另一个 plan/authority/occurrence，当前最小路径使用已采用的公共 UniProt 只读 Adapter route，不读取
ambient credential，也不占用 HPC。dispatch 在 effect 前持久化；零 retry、无 fallback。首次 effect 接受后写
`first-live` 单向边界，之后禁止恢复旧 deployment，只能隔离后前向修复。`status` 只输出 schema、digest、状态和脱敏事实；
私有路径、credential、raw traceback/stdout/stderr 不进入公开状态。

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
.venv/bin/python scripts/verify-external-qualification-readiness.py /tmp/enzymedesign-readiness.json
./scripts/check-external-qualification-readiness.sh

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
