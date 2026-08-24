# EnzymeDesign Distribution

该 wheel 是显式、版本化、可做 digest 的产品组合，不定义新的 canonical state。它选择
OpenZyme Kernel、基础设施 Adapters、通用 Plugins、EnzymeDesign Product Plugins 与
Drivers；它不依赖 `openzyme-standard` 作为语义层。

当前 manifest 已是结构上可激活的 `active` composition。纯 factory 已闭合 8 个 Adapter、14 个 Plugin、
8 个 subordinate Driver、32 个 Plugin 声明工具和 13 个 Kernel resident/workspace 基础工具（合计 45 个）；
`build_enzymedesign_fresh_install_seed()` 还能将这些 catalog 与
EnzymeDesign owner schema 和 deterministic bootstrap receipt 绑定。该状态不授权 live Provider/HPC，也不
替代 Host startup、installed-wheel proof 或真实 offline cutover；production surface 仍必须先通过 exact
`DeploymentActivationEpoch` gate。

`EnzymeDesignPluginRuntimeSurfaceSet` 与
`mount_enzymedesign_extension_surfaces()` 已进一步把 Plugin-owned runtime 对象转换为 exact Kernel
mount bundles。当前 non-live mount 闭合 32 个 Plugin tools、13 条 capability routes、2 条 HTTP routes、
5 个 projections、5 个 workers、2 个 finish validators 和 3 个 transaction participants；任一声明缺失、
多余、owner/driver/digest 漂移都会在 mount 前失败。该 factory 要求 composition root 注入真实
application/repository/Adapter Ports，不提供空 runtime 或 Provider fallback。

fresh factory 通过 Kernel 三 proof coordinator 产生 epoch；
`verify_enzymedesign_deployment_startup_read_only()` 仍只负责在不 mount Plugin runtime 的前提下闭合 Store
deployment proof、installed wheel set、Session composition pin、capability-binding revision 和 target
inventory reference，并且只重新授权数据库中的原 exact epoch。`build_enzymedesign_application_runtime()` 随后
核对全部 8 个 selected Adapter runtime identity，mount 上述 exact Plugin surface，闭合 13 个 Kernel tools 与
32 个 Plugin tools 的 45-tool runtime catalog，再构造 SQLite writer、capability registry、bounded runtime
gateway、Kernel coordination/operational routes、finish validator registry 和公共投影。任一 proof、Adapter 或
surface 漂移都会在 writer 对外可达前失败。`build_enzymedesign_v2_host_app()` 只把该完整 product runtime 注入
通用 `openzyme-host-api`；EnzymeDesign 没有依赖 `openzyme-standard`。non-live 测试还通过真实 Kernel gateway
完成了 Session bootstrap，证明该入口不再只是 catalog proof。

resident teammate 产品入口现在固定为异步两阶段：Session bootstrap 在一个 Kernel Unit of Work 内原子接纳 exact
`ProjectRepositoryBinding`、repository pin、`WorkspaceGeneration` reservation、pending root authority 和 durable
provisioning intent，公开 readiness 为 `provisioning`；独立 bounded provisioning worker 只调用所选 workspace
Adapter，terminal `ready` 后才激活 runtime binding/authority。`POST .../messages` 只持久化 canonical `message`、
exact `workflow_refs`、request lineage、`WorkflowAuthorityBinding`、`RuntimeSignalAuthorityLink` 和 wakeup signal；
`POST .../runtime/drain` 只接纳 durable command，独立 worker claim/fence/execute/settle，不在 HTTP 内同步运行
Agent。显式空 workflow 选择保持为空；registry 不接受 `latest`、`all`、prose 或隐式 union。

`dispatch_in_doubt` 不会自动 retry、重新 provision 或切换 Adapter。Host 的显式
`POST .../workspace/provisioning/reconcile` 只按 exact intent digest/version/Session 接纳 durable pending
reconciliation，HTTP 内不观察 Adapter；独立 bounded lifecycle worker 后续优先认领 pending/expired-claimed occurrence，
并使用 admission 持久化的 claim duration 执行同一原请求的 observation。terminal occurrence 不自动派生下一 attempt。只有
operator 再显式调用 `POST .../workspace/provisioning/successor`，并提交 exact failed intent 与已解析的 reconciliation
identity（如需要），Kernel 才原子建立下一 generation 的 pending reservation/intent/lease。两个入口都绑定原 HTTP
actor、idempotency key 与 correlation id；successor admission 本身不调用 Adapter。

四个 adopted resident roles（`master | researcher | executor | reporter`）对完整 45-tool catalog 都有闭合 subject
policy 和 `Direct | Deferred | Hidden` exposure policy。Provider 初始只看到可调用的 Direct；
`capabilities.inspect` 只能把当前 command 的 Deferred 显式扩展为可调用，不扩大 workflow/authority/route；Hidden
既不进入 Provider，也不进入 inspection 或公共投影。每个 turn 同时绑定 workflow authority、signal causal link、
tool exposure snapshot 和结构化 world context；provider step 与每次 dispatch 都重验当前 fence。

可执行入口为 `enzymedesign-host --config /absolute/launcher.json
<preflight|serve|provision|provision-tick|drain|drain-tick>`；closed JSON 精确固定 file-backed database、factory
locator/id/digest、component configuration、server 与 provisioning/runtime worker bounds，factory 必须显式返回配置一致的
`EnzymeDesignHostLauncher`，没有 ambient/default fallback。launcher 在 HTTP admission 前启动 bounded background
lifecycle，停止时先关闭 admission，再 join workers、retire 显式 owners，最后关闭 Store。fresh file-backed non-live 回归覆盖
bootstrap → provisioning → ready → message enqueue → explicit drain → assistant/tool transcript → SQLite reload，并
断言 Direct 可调用、Deferred 可反射且 command-scoped expansion 后可调用而 route/authority 不变、Hidden 零披露、
network/subprocess/browser/live provider/HPC 路径零触达，以及 restart 后没有重复 external dispatch。

`preflight` 不是配置回显，也不硬编码 `file_backed=true`。它通过 SQLite `PRAGMA database_list` 只读观测实际 Store，
要求唯一 `main` 数据库是与配置完全相同的绝对文件路径且没有附加数据库；随后重验 official Store/runtime 类型、active
epoch/release、Extension bundle、declared tool catalog、完整 8-Adapter runtime set、实际 workflow resolver、实际 runtime
admission/全角色 policy 与 workspace binding。输出 receipt 绑定上述 digest；任何 declared/actual identity 漂移都会先关闭
launcher，再以 `no_effect`、`mutation_applied=false`、`fallback_performed=false` 失败，不能改用 in-memory 或 Standard。

同一 composition root 还构造 Store-backed Session pin/capability-binding reader、
`ExtensionStateKernelApplicationService`、SQLite extension transaction coordinator/query、
`ExtensionStateComputeExecutionRepository` 与 Kernel continuation service。Compute Plugin 因而只提交
namespaced command，不接触 SQLite/Core table；restart 测试已证明 invocation、exact route、opaque handle、
terminal result 和 owner continuation 可从原 SQLite truth 恢复且 external dispatch 不增加。

这一状态是 `runtime_mounted`，不是 `cutover` 或 `live`。composition root 以一次性
`EnzymeDesignFormalComputeApplicationBinding` 在 writer 可达前，把 HMMER/Vina 的 Kernel-admitted tool
invocation、subordinate Driver、typed workload、Compute ControlledOperation lifecycle 与声明式 runner Port
接通；它只从 canonical `PublishedRevision`、publication-owned path verification、ready owner workspace、当前
authority lease 和 adopted capability binding 推导 admission，不接受调用方伪造这些事实，也不自动换 route、
redispatch 或完成 Task。Compute durable repository/continuation recovery 已闭合。远端 Workspace operation 与
Slurm submit/cancel occurrence 分别使用持久 ledger，跨 Adapter epoch 只 reconcile 原 effect；远端 helper 也已
进入 exact resource qualification。

`enzymedesign_local_single_process_file_sqlite@1` 现在另有真实 non-live 跨层场景：它从通用 Host 创建 Session，
固定 composition pin 和 authority，生成真实 immutable publication，采用含 HMMER/Vina 软件事实的 target
inventory，经 affordance/route、实际 mounted Drivers 和 durable Compute lifecycle 到达声明式 fake runner，
验证 terminal result、两条 owner continuation 与 Science finish validator，同时证明 Task 仍为 `todo`。该场景只
替换显式的 Agent-turn、Git-shaped revision 和 external Compute runner Ports；它证明产品内部组合闭合，但不证明
真实 SSH/Slurm/HPC target 已 `qualified`、已 `cutover` 或任何 live 调用获授权。

状态词固定如下：`selected` 仅表示 manifest 选中；`runtime_mounted` 表示 exact runtime identity 已装配；
`ready_non_live` 表示外部资格单元/profile/Port/fixture/receipt verifier 在禁止 live 下闭合；`qualified` 表示
特定 target/provider 有当前有效真实 receipt；`cutover` 表示真实部署已采用该实现；`live_occurrence` 表示某次
外部调用另获授权并实际发生。后一个状态不能由前一个状态自动推导。

`build_enzymedesign_external_qualification_catalog()` 从当前 activated composition 的 8 Adapter、Plugin
`QualificationSpec` 与 selected Driver manifest 派生 45 个精确 operation 单元；required `base` 加显式 enabled
optional profiles 形成 closed plan。`RecordingQualificationProbeBackend`、rejecting credential resolver 和独立
verifier 只生成 `ready_non_live` evidence；它们不能生成或 adopt `qualified`/`cutover`/live receipt。仓库 required
gate 是 `./scripts/check-external-qualification-readiness.sh`，普通 CI 固定 `OPENZYME_ALLOW_LIVE=0`。

`qualification_planning` 在此基础上只消费显式 secret-safe snapshot，不读取 raw `.env`，也不访问网络、container、
SSH、scheduler 或科学程序。它生成 typed identity observation/gap/candidate packet，并为 Batch 1
（`base + research-provider + hpc-primary + hmmer + docking`）和独立 AlphaFold Batch 2 建立 source-bound dry plan。
预算采用宽松 circuit breaker：LLM/Tavily occurrence 分别以 USD 25/USD 10 为硬上限，batch 为 USD 100；warning
只记录诊断。operator selections 先生成独立 `ExternalIdentityPreparationPlan`；当前 Git action 只允许创建本地隔离
repository/LFS endpoint，不允许 hosted sync。Preparation plan 与 qualification dry plan 各自固定零 retry、无
fallback，并要求独立 exact occurrence authorization；任一 plan-only backend factory 在授权前都不会调用 credential
resolver。Preparation 只能补齐 subject identity，不能产生 `qualified`。

本地 preparation 使用三个显式 operator 入口：`bootstrap-external-qualification-operator-state.py` 只创建 root/layout，
`create-external-identity-preparation-authorization.py` 只规范化已批准授权，
`execute-external-identity-preparation.py` 才在 `OPENZYME_ALLOW_LIVE=1`、当前 source/packet/authorization 全部一致后读取
exact credential bundle 并执行 Batch 1。执行器先预检全部 locator，再逐 action 写 protected ledger；已有 residual state
不自动覆盖或改用别的 target。输出状态固定为 `prepared_not_qualified`。

当前还实现了 authorization-bound exact-unit qualification router：它在调用任何 owner builder 前验证 dry-plan、
batch、validity window、readiness plan、unit、subject、route、input/schema、credential locator 和 authorization
digest，并禁止重复 dispatch 或跨 unit reconcile。LLM、Tavily 与公共 Bio HTTP 已有 typed Adapter bridge；
Git/LFS、Podman、SSH、Slurm 以及 HMMER/Vina/fpocket/preprocess 已有严格 owner binding guard。后者的真实 typed
operation builder 与 fixed scientific smoke 仍依赖 preparation 后的 exact local repository、image 和 target
identity，当前 fake-Port 绿色结果不属于 live qualification。

AlphaFold Batch 2 使用独立的 preparation 与 live bridge：preparation 只读观测 `Diannan/3090` 上已安装的
AlphaFold 3.0.1 wrapper、SIF、模型参数、数据库 metadata closure、GPU partition 与 source/runtime identity，
不构建、复制或安装远端资源。Driver 只编译固定 20 aa monomer、seed `20260824`；Slurm route 在 submit 前重验
全部资源 digest，只允许一张 3090、30 分钟、inference-only、零 retry、无 fallback 的 job，并验证 CIF、summary
confidence、实际 GPU identity 与 cleanup。该路径不执行 license acceptance；任何资源缺失/漂移只阻断 Batch 2，
也不会被 Batch 1 receipt、另一 target 或 image fallback 替代。

Batch 1 qualified runtime 的 operator 入口是：

```bash
.venv/bin/python scripts/cut-over-enzymedesign-qualified-runtime.py plan
.venv/bin/python scripts/cut-over-enzymedesign-qualified-runtime.py authorize
.venv/bin/python scripts/cut-over-enzymedesign-qualified-runtime.py apply
.venv/bin/python scripts/cut-over-enzymedesign-qualified-runtime.py status
```

该入口不读取 ambient `.env`。它固定 owner-local `0700` root，创建 `0600` 的 plan/authority/backup/adoption/activation/
startup/monitoring/cutover evidence，并在 effect 前重验资格 source、部署 source、qualified-owner closure 与 44 个 receipt
TTL。`apply` 只完成部署采用，不授权 live occurrence。独立的 `smoke-plan`、`smoke-authorize`、`smoke-apply` 使用已采用的
公共 UniProt 只读 route 建立 first-live boundary，零 retry、无 fallback；`rollback` 只允许在 first-live 前且 activation
digest 精确匹配时执行。AlphaFold 不进入本轮 adoption 或广告。

`build_enzymedesign_scientific_contributions()` 是 Product composition factory：它构造 AOX
workflow registry、scientific finalization handler 与 exact executor receipt validator，再通过
通用 Science application ports 注入 Host。Host 不直接 import AOX 或 executor。
