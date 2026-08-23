## Why

EnzymeDesign 已证明组件声明、wheel 闭包、运行时挂载和若干 non-live 跨层组合，但尚未把真实外部资格验证所需的精确资格单元、profile 闭包、凭据边界、可重放 receipt、故障诊断与 CI/live gate 落成统一可执行契约。若直接进入 live qualification，容易把 `runtime_mounted` 误报为 `qualified`，或让测试通过隐式环境变量、fallback 与不可追溯的目标差异产生假阳性。

## What Changes

- 新增 EnzymeDesign 外部资格就绪模型：以 `capability + operation + route + target/provider + source/build/config digest` 为不可拆分的资格单元，显式区分 `selected`、`runtime_mounted`、`qualified`、`cutover` 与单次 `live occurrence`。
- 定义 required base profile 与按部署启用的 optional profile 闭包；缺项、过期、重复、越界 operation 或 identity drift 均 fail closed，不允许 fallback 到其他 route、target 或 Provider。
- 为 LLM、Tavily、Bio HTTP、Git/LFS、Podman、SSH、Slurm 以及 HMMER、Vina、fpocket、AlphaFold、preprocess Driver 建立统一的 non-live 资格计划、受控 backend Port、确定性 fixture、reconcile/negative-test 语义和 receipt 验证器。
- 将凭据限定为显式、可审计、作用域受限的 locator/resolver 输入；公共诊断只暴露 secret-safe identity，禁止从 ambient environment 猜测或自动换用凭据。
- 把 non-live readiness 设为普通 CI 的 required gate；所有 live marker 仅能由显式 operator/manual workflow 触发，并要求独立 opt-in、配置和 secret，不进入普通 pull-request 自动执行。
- 本 change 只实现 live qualification 的安全、可执行前置条件和 non-live 证明，不连接真实 Provider、Git 服务、容器、SSH、Slurm、HPC 或科学软件，也不产生 `qualified`/`cutover` 声明。

## Capabilities

### New Capabilities

- `enzymedesign-external-qualification-readiness`: 定义跨 Adapter/Driver 的资格单元、profile 闭包、计划与 receipt、凭据定位、结构化诊断、non-live fixture 及 CI/manual-live 执行边界。

### Modified Capabilities

- `openzyme-layered-qualification`: 将架构、运行时挂载、外部资格、cutover 与 live occurrence 的证据和声明严格分层，并禁止跨层推导。
- `openzyme-target-toolchain-inventory`: 使资格 receipt 和资源事实绑定精确 operation、route、target/provider 及 source/build/config identity，并对过期和漂移 fail closed。
- `openzyme-extension-composition`: 要求 operational Adapter/Driver runtime 只能从已验证的显式绑定与 credential locator 构造，且资格缺失只能降级/阻塞，不得 fallback。
- `enzymedesign-product-composition`: 要求产品级 non-live qualification 覆盖全部已选外部 route 的 readiness profile，同时准确披露哪些路径仅挂载、哪些只使用 fake/no-op Port。

## Impact

- 主要影响 `openzyme-contracts`、`openzyme-extension-spi`、`openzyme-hpc`、EnzymeDesign Distribution/qualification 支持代码及相邻单元测试。
- 增加可机器验证的 readiness plan/receipt/diagnostic schema、确定性 recording backend 与 profile closure verifier；现有 live Adapter 的业务实现不在本 change 中替换或调用。
- 更新 `.github/workflows`、pytest marker/gate 和 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` 文档，明确 required non-live 与 operator-gated live 的边界。
- 后续 `qualify-enzymedesign-external-capability-routes` 只能消费本 change 产生的闭合计划和 resolver 配置；正式 cutover 仍属于独立 change，并需要再次人工确认。
