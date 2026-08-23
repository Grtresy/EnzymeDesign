## 1. 通用资格身份与证据契约

- [x] 1.1 在 `openzyme-contracts` 实现生命周期层级、subject kind、六维 `ExternalQualificationUnit`、canonical digest 和严格字段验证
- [x] 1.2 实现 readiness plan/profile ref、probe request/outcome、credential locator scope、readiness receipt/report 与结构化 failure DTO
- [x] 1.3 实现独立 verifier，拒绝 digest drift、重复/缺失/越界 operation、过期、secret-bearing public payload 及层级冒充
- [x] 1.4 为所有 schema 的 round-trip、canonical ordering、tamper、expiry、operation isolation 和 secret-safety 添加 focused tests

## 2. EnzymeDesign 产品 catalog 与 profile 闭包

- [x] 2.1 在 `enzymedesign-distribution` 定义 required base 和命名 optional profile catalog，覆盖 LLM、Tavily、Bio HTTP、Git/LFS、Podman、SSH、Slurm、HMMER、Vina、fpocket、AlphaFold 与 preprocess
- [x] 2.2 从 exact Distribution composition、Adapter manifest、Plugin qualification spec 和 Driver binding 构建 unit，禁止维护第二套独立 component selection graph
- [x] 2.3 实现 profile plan builder，拒绝未知 profile、missing/unexpected/duplicate/colliding unit 和 selected-operation coverage gap
- [x] 2.4 添加 catalog golden identity、base/optional closure、disabled optional、enabled incomplete 与 manifest drift tests

## 3. Non-live probe、凭据与故障语义

- [x] 3.1 定义 `ExternalQualificationProbePort` 与 `QualificationCredentialResolverPort`，请求绑定 exact unit/attempt/timeout/schema/locator
- [x] 3.2 实现仅消费 deterministic fixtures 的 recording backend 与 rejecting credential resolver，并证明无 network/SSH/container/scheduler/process effect
- [x] 3.3 实现 coordinator 的 dispatch/settle/reconcile 状态机；unknown effect 只 reconcile 同一 attempt，禁止 retry 和 route/subject fallback
- [x] 3.4 实现 success、typed auth/config failure、timeout-before-effect、schema mismatch、operation mismatch、response-loss-after-terminal 与 unresolved reconcile fixtures
- [x] 3.5 生成 `ready_non_live`/`blocked_readiness` receipt、公共/私有 diagnostic correlation 和 component/operation disclosure matrix
- [x] 3.6 添加 credential-resolution violation、secret redaction、response-loss exactly-once、negative-fixture completeness 和 no-fallback tests

## 4. Inventory 与运行时资格消费边界

- [x] 4.1 扩展 target/provider resource fact 或 bridge，使 adopted fact 保存 operation、route、subject、source/build/config、validator、receipt 和 validity identity
- [x] 4.2 添加 readiness receipt 不能作为真实 qualification receipt 采用的 fail-closed guard 和 tests
- [x] 4.3 在 EnzymeDesign operational binding/admission 边界验证 qualification-aware identity，并对 missing/expired/drifted receipt 输出 `blocked_qualification`
- [x] 4.4 添加多个独立 qualified route 可呈现、单个失效 route 被移除但不隐式切换 occurrence 的 tests

## 5. Required non-live CI 与 manual live 隔离

- [x] 5.1 增加仓库级 non-live readiness 执行脚本，强制 `OPENZYME_ALLOW_LIVE=0`、清除已知 credential vars 并运行 focused suite/verifier
- [x] 5.2 将 readiness 脚本接入 `scripts/check-mainline.sh`，确保普通主线验证 required 且不依赖外部配置
- [x] 5.3 增加 pull-request/mainline non-live CI workflow，并验证其中不存在 live marker、secret 或外部 effect opt-in
- [x] 5.4 增加仅 `workflow_dispatch` 的 live qualification workflow skeleton，要求 profile/operator/environment 明示输入，默认拒绝且不在本 change 调用真实 backend
- [x] 5.5 增加 pytest marker/gate tests，证明 live markers 无双重 opt-in 时不能计为 live pass，manual workflow 不监听 pull request/push/schedule

## 6. 文档、声明矩阵与变更验收

- [x] 6.1 更新 `docs/OpenZyme架构设计.md` 与相关 `docs/v3/` 稳定文档，记录六维 unit、profile、credential、receipt 和 selected→live 分层
- [x] 6.2 更新 EnzymeDesign/Adapter/Driver qualification 文档，明确 current non-live 状态、fake/no-op 边界和后续 live/cutover 人工 gate
- [x] 6.3 生成可机器验证的 readiness report，逐 component/operation 披露 mounted、non-live exercised、substituted、qualified、cutover 与 live occurrence
- [x] 6.4 运行 focused tests、non-live readiness gate、`./scripts/check-mainline.sh`、OpenSpec strict validation 与独立 receipt verifier
- [x] 6.5 对照 proposal/design/spec/tasks 进行完成度审计，确保没有真实 credential access、外部 effect、qualification adoption、cutover、fallback、commit 或 push
- [x] 6.6 完成并归档 readiness change 后暂停，在创建 `qualify-enzymedesign-external-capability-routes` 前向用户提交具体 Provider/target/profile/credential/预算/窗口决策清单
