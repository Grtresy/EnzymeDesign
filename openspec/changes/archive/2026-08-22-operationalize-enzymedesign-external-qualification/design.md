## Context

当前仓库已经具备三类重要基础：组件 manifest/wheel 与运行时 binding 的闭合验证；`openzyme-hpc` 中面向目标软件的 `TargetQualificationWorkflow`、`SoftwareQualificationReceipt` 和 inventory；以及 LLM、Tavily、Bio HTTP、Git/LFS、Podman、SSH、Slurm 等真实 Adapter 实现。但这些基础尚未形成一个能安全进入 live qualification 的产品级执行面：HPC receipt 没有统一表达 Provider、route、source/build/config identity，产品也没有声明 base/optional profile 的闭包，credential 通常由具体 factory 单独处理，CI 更没有一条明确区分 required non-live 与 manual live 的证明链。

本 change 位于架构闭合和真实资格验证之间。它必须交付真实可执行的模型、编排、验证器、确定性 backend 与 CI gate，但必须保证运行时无法在普通测试中触发外部 effect。后续真实 qualification change 才会提供真实 resolver、target/provider 配置与 operator 授权；再后续 cutover change 才能采纳有效 receipt 并启用生产 occurrence。

约束如下：

- 顶层产品真状态仍属于 Kernel/Plugin 持久化边界；readiness artifact 是部署与资格证据，不是新的 Session 真状态。
- Agent 保留 route/target 策略选择自由，但只能在 Kernel 呈现的、当前有效且精确绑定的候选集合内选择；harness 不得暗选 fallback。
- secret 不进入计划、receipt、日志、公共诊断或 digest payload；只有 locator identity 和 resolver-produced consumption proof 可见。
- non-live 路径必须在 `OPENZYME_ALLOW_LIVE=0`、无 API key、无网络/SSH/容器/调度器 effect 的条件下完整运行。
- 本 change 不把 deterministic fake receipt 标记为真实 `qualified`。

## Goals / Non-Goals

**Goals:**

- 建立跨 Provider、Adapter 和科学 Driver 的统一资格 identity 与生命周期词汇。
- 生成并验证一个闭合的 EnzymeDesign readiness plan，覆盖 required base profile 和全部显式 enabled optional profiles。
- 提供受控 probe backend Port、credential locator/resolver Port、recording backend、response-loss/reconcile 与 negative fixture。
- 产生 secret-safe、可重放、digest-bound 的 non-live readiness receipt 和独立验证报告。
- 将该证明接入 required non-live CI，并把所有 live marker 隔离到 operator-triggered manual workflow。

**Non-Goals:**

- 不调用真实 LLM、Tavily、UniProt/RCSB/InterPro、Git service、Podman、SSH、Slurm 或科学二进制。
- 不获取或验证真实 credential material，不创建 HPC 账号/目录/job，不承担费用。
- 不声明任何 route 已 `qualified`、部署已 `cutover` 或 occurrence 已 `live`。
- 不实现正式部署、quiescence、rollback、监控或 cutover receipt。
- 不以本 change 修复与资格 readiness 无关的既有 OpenSpec/spec 漂移。

## Decisions

### 1. 使用一等六维资格单元，而不是按包名或测试名汇总

新增 `ExternalQualificationUnit`，其 identity 至少包含：`capability_id`、一个 `operation`、`route_id`、`subject_kind + subject_id`（target 或 provider）、`source_digest`、`build_digest` 和 `configuration_digest`。单元还绑定 owning component/Driver、contract digest、credential slot locator（若需要）与 qualification spec digest。

operation 是单值而不是列表，避免一个通过的 smoke 被泛化成未执行的其他 operation。多个 operation 必须形成多个单元，但可以在一个 profile/plan 中共享同一 bounded probe session。选择六维 identity 而不是复用现有仅面向软件 capability 的 receipt，是因为 Provider 与 Git 等外部边界同样需要 route/config/source 绑定。

备选方案是扩展 `SoftwareQualificationReceipt` 承载所有外部系统。该方案会把 Provider quota、Git response loss、容器 lifecycle 等非“软件版本”语义塞进 HPC inventory，并让 `openzyme-hpc` 错误拥有产品级 Provider 真相，因此不采用。现有 HPC receipt 可被后续 live backend 转换为通用 receipt 的 evidence ref。

### 2. 通用证据 schema 属于 contracts，产品目录与编排属于 Distribution

`openzyme-contracts` 新增不依赖 Adapter 的不可变 DTO、枚举、digest 与 verifier primitives。`enzymedesign-distribution` 新增 exact catalog、profile closure、plan builder、credential locator policy、probe coordinator、recording backend 和 report verifier。各 Adapter/Driver 后续只需实现 Port，不反向依赖 Distribution。

这保持 generic contract 与产品选择分离，也避免在 Kernel 中新增外部资格产品状态。readiness plan/receipt 可以作为部署 artifact 存档；只有后续明确 adoption 才能转化为运行时 resource facts。

### 3. profile 是闭合集合，optional 只在未启用时可缺席

产品定义一个 required base profile，并为 optional capabilities 定义命名 profile。plan request 必须显式列出 enabled profiles；builder 计算 `base ∪ enabled` 的 exact unit closure。缺失、重复、unexpected、跨 profile identity collision 或 profile 名未知都拒绝。

base 覆盖产品启动和核心外部边界 readiness；可选 profile 按实际部署启用科学/算力能力。optional profile 一旦启用，其全部单元与 negative tests 就与 base 一样 required。这样避免“optional”成为失败时跳过验证的 fallback。

### 4. readiness 与 live 使用同一 Port 形状，但不同 backend policy

`ExternalQualificationProbePort` 接受完整 unit、bounded input identity 和 credential locator identity，返回 `dispatch`/`reconcile` outcome。outcome 必须给出 effect certainty、attempt identity、observed operation、backend receipt digest、safe observation 和可选 evidence refs。未知 effect 只能 reconcile，不能重新 dispatch。

本 change 的 `RecordingQualificationProbeBackend` 仅消费确定性 fixture，记录调用并显式声明 `external_effect_performed=false`、`credential_material_accessed=false`。它支持 success、typed failure、timeout-before-effect、response-loss-after-terminal 与 reconcile，以验证未来 live adapter 的控制语义。后续 change 注入真实 backend；本 change 不提供环境变量开关把 recording backend 自动换成 live backend。

### 5. credential 采用 locator/resolver，禁止 ambient fallback

计划只记录 `credential_slot_id`、`credential_locator_id`、scope digest 和 subject/operation 约束。`QualificationCredentialResolverPort` 只能在 operator-authorized live execution 中按 exact unit 解析 ephemeral credential，返回 consumption proof；material 不进入对象 repr、异常或 receipt。无 locator、scope mismatch、过期或解析失败时返回 `blocked_qualification`，不尝试环境变量、default profile、相邻账号或匿名模式。

non-live coordinator 使用 rejecting resolver，任何 material resolution 尝试都会使 readiness 失败。这既证明 wiring 可注入，也证明普通 CI 不会读取 secrets。

### 6. receipt 明确是 readiness，不冒充 qualified

本 change 产生 `ExternalQualificationReadinessReceipt`，状态限于 `ready_non_live` 或 `blocked_readiness`。它绑定 plan digest、unit digest、fixture/backend identity、negative-test set、observed operation、diagnostic ID、effect/credential/fallback flags 和有效期。独立 verifier 必须检查所有 required unit 一一对应、digest 重算一致、无外部 effect、无 credential material、无 fallback、failure fixture 被正确拒绝。

真实 qualification receipt 使用独立 schema/status，由后续 change 创建；只有真实 backend、真实 subject identity 和 operator authorization 才能产生 `qualified`。cutover receipt 又是第三种 schema，不可由资格 receipt 推导生成。

### 7. 公共与私有诊断共享 diagnostic_id

公共 failure envelope 至少包含稳定 error code、component、phase、unit/plan identity、effect certainty、mutation/fallback/retry/reconcile policy、operator action 与 `diagnostic_id`，并经过 secret-safe validator。私有诊断可以保存 cause chain、bounded stdout/stderr、return code 与 provider request identity，但不进入公共 artifact；异常包装使用 `raise ... from exc`。

### 8. CI required non-live，live 仅 manual

增加独立 non-live readiness 命令/pytest 集，强制清空已知 secret 环境并设置 `OPENZYME_ALLOW_LIVE=0`。普通 CI 和主线脚本执行该 gate。增加或规范 manual workflow：只允许 `workflow_dispatch`，逐 profile 显式 opt-in，并由 environment protection/secrets 提供配置；workflow 不监听 `pull_request`、`push` 或 schedule。pytest live markers 在无双重 opt-in 时 collection/执行均 fail closed 或 skip-with-explicit-reason，不能退回 recording backend 后仍报告 live pass。

## Risks / Trade-offs

- [资格单元数量随 operation/profile 增长] → 使用 canonical catalog 和 plan digest 机械生成，禁止手工复制 receipt；共享 probe session 只能优化执行，不能合并 identity。
- [readiness schema 与现有 HPC inventory 重叠] → 保持 adapter-neutral readiness receipt 与 adopted target inventory 分层，通过 evidence ref 显式桥接，不迁移或伪造现有 receipt。
- [recording backend 可能被误读为真实验证] → schema/status 固定为 `ready_non_live`，报告强制列出 `external_effect_performed=false`，文档使用声明矩阵而非笼统“verified”。
- [manual workflow 配置错误导致意外费用或 mutation] → live workflow 只在后续 change 创建真实 job，要求 environment approval、profile allowlist、bounded budget 和 dry plan review；本 change 的 workflow 不具备 live backend。
- [credential locator 暴露基础设施信息] → locator 使用稳定不透明 ID 与 scope digest，公共证据不包含 secret name/path/value；详细映射仅存在受保护 operator 配置。
- [过期 receipt 阻塞可用 route] → fail closed 是有意选择；Agent 可在多个已资格 route 中自由选择，但 harness 不会用过期或其他 identity 作为隐式替代。

## Migration Plan

1. 先加入 contracts、产品 catalog/profile 与 deterministic backend，保持现有 runtime/adapters 行为不变。
2. 建立 non-live readiness 计划和 verifier，补齐所有 selected external capability 的目录条目与 negative fixtures。
3. 将 focused tests、OpenSpec validation、文档一致性和 secret/effect guard 接入 required non-live CI/mainline。
4. 完成本 change 后仅得到“可进入真实资格 change”的 readiness 结论，不自动创建 live receipt 或采用 inventory。
5. 在创建 `qualify-enzymedesign-external-capability-routes` 前暂停，由用户确认真实 provider/target、profile、凭据 locator、费用/配额、mutation/cancel policy 与执行窗口。
6. 若本 change 需要回滚，删除新增 readiness wiring/CI gate 即可；它没有外部 mutation、数据库迁移或 cutover 状态。

## Open Questions

本 change 内没有阻塞性产品决策。真实 Provider/target、启用 profile、凭据映射、预算、Slurm cancel/response-loss 策略和 AlphaFold 资源门槛被有意推迟到下一 change 的强制人工确认点；cutover deployment、回滚边界和监控策略推迟到第二个人工确认点。
