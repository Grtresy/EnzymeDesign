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
contribution 精确为空。不能为了让清单看起来完整而注册无真实 runtime 语义的占位实现。

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

该命令不证明 production activation 或 cutover；最终仍需 exact wheel closure、三种 composition profile、
startup proof 和离线迁移验收。
