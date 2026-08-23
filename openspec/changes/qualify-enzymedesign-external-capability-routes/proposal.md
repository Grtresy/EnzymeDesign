## Why

EnzymeDesign 已完成 45 个精确 external qualification unit 的 deterministic `ready_non_live` 闭包，但当前 checkout 仍缺少多个 real subject identity、真实 target software closure 和 operator-authorized occurrence，因此不能把 mounted/readiness 证据升级为 `qualified`。本 change 将把已确认的 Provider/target/profile、预算、credential locator、fault injection、TTL 与 receipt storage 变成可审计 dry plan，并在另一次明确 occurrence 授权后才执行真实资格探测。

## What Changes

- 从当前显式配置、Distribution、Adapter/Driver manifest、Podman metadata 和 HPC runner config 只读发现非 secret subject identity，生成 source-bound discovery report；禁止读取 secret material、访问网络或启动外部 effect。
- 为缺失或不完整的 LLM、Tavily、Git/LFS、Podman、SSH/Slurm/HPC 与科学软件 identity 生成 typed `blocked_identity` gap，并为每项给出 mutually exclusive resolution candidates、影响、风险和推荐项，未经 operator decision 不得填默认值。
- 把 operator 已选 candidate 固化为 source-bound decision，并先生成独立 `ExternalIdentityPreparationPlan`；建账号、建本地仓库、build/pull image 或补齐 HPC profile/inventory 都属于 preparation effect，不能借未闭合的 qualification dry plan 获得隐式授权。
- 固定第一批 profile 为 `base + research-provider + hpc-primary + hmmer + docking`，AlphaFold 作为第二批独立 optional profile；任一批只对 exact unit 产生资格结果，不扩大为 package/product-wide claim。
- 建立 identity preparation plan 和 real qualification dry-plan 两级 plan、各自独立的 occurrence authorization、budget ledger、effect allowlist、credential locator binding、fault-injection schedule、TTL/storage policy 与独立 verifier。
- 增加真实 Provider/Git/Podman/SSH/Slurm/科学软件 probe backend 的显式 Port/factory wiring，但默认处于 plan-only 状态；没有 exact occurrence authorization 时，任何 dispatch 必须在 credential resolution 和 effect 前 fail closed。
- 在后续 occurrence 授权后，按 exact unit 执行 bounded probes、same-attempt reconcile、negative tests，产生 real-subject qualification evidence；成功只得到 `qualified`，不自动 adoption、cutover 或 live-by-default。
- 保持 required non-live CI；live workflow 继续仅允许 `workflow_dispatch`，普通 pull request/push 不得读取 credentials 或触发外部系统。

## Capabilities

### New Capabilities

- `enzymedesign-external-route-qualification`: 定义 real-subject identity discovery/gap resolution、operator dry plan、budget/effect/credential/fault/TTL/storage closure、真实 probe execution 与 exact qualification receipt。

### Modified Capabilities

- `enzymedesign-external-qualification-readiness`: 将 `ready_non_live` catalog 明确交接给 source-bound identity discovery 和 operator-authorized dry plan，禁止 readiness receipt 被就地升级。
- `enzymedesign-product-composition`: 固定第一批五个 profile 与第二批 AlphaFold 的独立 closure、阻塞和声明语义。
- `openzyme-extension-composition`: 要求 live qualification backend 只能由 exact selected binding、resolved subject identity 和 occurrence authorization 构造。
- `openzyme-layered-qualification`: 增加 `qualified` 层的 real-subject、real-occurrence 和 source-bound evidence 要求，继续禁止推导 cutover。
- `openzyme-target-toolchain-inventory`: 规定真实 Provider/target receipt 的 TTL、存储、revocation、per-operation adoption 与 private diagnostic 关联规则。

## Impact

- 主要影响 `openzyme-contracts`、`enzymedesign-distribution`、LLM/Tavily/Bio HTTP/本地隔离 Git-LFS/Podman/SSH/Slurm Adapter qualification seams、HPC inventory 与 HMMER/Vina/fpocket/preprocess/AlphaFold Driver qualification wiring；当前 Git scope 明确不包含 GitHub 或其他托管服务。
- 新增 operator-facing identity discovery report、gap-resolution document、dry-plan CLI/schema、plan verifier、manual workflow inputs 和 protected receipt-ledger 接口；不新增 Agent-facing raw credential、SSH、Slurm 或 provider bypass。
- 第一实施阶段只做 read-only discovery、方案矩阵、dry plan 与 non-live verification。首次真实 Provider、Git mutation、container、SSH、Slurm、HPC 或科学程序 occurrence 前必须再次暂停并取得用户明确授权。
- 本 change 不执行 deployment adoption、Session capability binding 更新、cutover、quiescence、迁移或自动 fallback；这些仍属于独立 `cut-over-enzymedesign-qualified-runtime` change。
