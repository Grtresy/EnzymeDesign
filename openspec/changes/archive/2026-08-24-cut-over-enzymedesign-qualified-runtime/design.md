## Context

Batch 1 已在 qualification source commit `bb6af997c369dd03d4d637ca27c284d9006447fd` 下形成 44 个真实 receipt，并由独立 receipt-set verifier 判为 `qualified=true`、`cutover=false`。Provider receipt 的最短 TTL 为 24 小时。AlphaFold Batch 2 因 `Diannan/3090` 无可调度 GPU 被 operator 取消并清理，0 receipt、未资格、未采用。

cutover implementation 本身必然产生晚于 qualification source 的 deployment source。两者不能伪装成同一 checkout：cutover plan 同时绑定 qualification source identity、deployment source identity，以及“所有被资格验证的 Adapter/Driver/route/config/build closure 未发生漂移”的 compatibility proof。只有 cutover-only governance/runtime-adoption paths 可以新增；任何 qualified owner、workload、validator、image recipe、target subject 或 plan unit 漂移都要求重新 qualification。

部署 root 固定为 `/home/grtresy/.local/state/openzyme/deployments/enzymedesign-qualified-runtime`，由 `operator.enzymedesign-owner` 控制。没有时间窗口，但 quiescence、零 unsettled effect、backup、startup readback 和 distinct one-shot authority 都是硬门。代码与证据只提交本地，不 push。

## Goals / Non-Goals

**Goals:**

- 从 exact Batch 1 receipt set 创建 44 个 operation-scoped adopted facts 和 runtime admission。
- 在 protected owner-local root 中生成可重验 plan、authority、backup、activation、startup、monitoring、rollback 与 cutover receipts。
- 真实构建并 readback EnzymeDesign application runtime，只有 adopted routes 可用。
- 第一条 live occurrence 前支持 exact compare-and-restore；之后只允许 forward-only repair。
- 运行单独 post-cutover smoke，证明部署采用而不是重复 qualification。

**Non-Goals:**

- 不重新运行 AlphaFold，不采用或发布 AlphaFold route。
- 不重用 qualification/preparation/helper authority，不自动续期过期 receipt。
- 不接受 ambient `.env`、installed package discovery、mutable tag、adjacent Adapter 或 alternate target fallback。
- 不 push、不部署 hosted Git/LFS、不执行 dual write。
- cutover receipt 不授权任意未来 live occurrence。

## Decisions

### 1. 独立 cutover contracts 由 EnzymeDesign Distribution 拥有

新增 `qualified_runtime_cutover.py`，定义 canonical immutable DTO 和 verifier：source compatibility、deployment inventory、receipt adoption、quiescence/backup closure、plan、authority、activation、startup、rollback boundary、monitoring 与 cutover receipt。它只依赖公开 contracts 与 store planning DTO，不让 Plugin/Agent 取得部署权。

备选是扩展通用 offline file-workspace cutover ledger。该 ledger 面向 schema/session migration，不能表达 external qualification receipt TTL、route adoption 与 first-live boundary，因此不复用为同一真状态，只复用其类型化 planning/backup 原语。

### 2. qualification source 与 deployment source 分开绑定

`QualificationSourceCompatibilityProof` 固定 qualification commit/source identity、deployment commit/source identity、允许的 cutover-only path closure、被资格组件 closure digest 和 diff digest。proof verifier 要求所有 44 个 unit 的 source/build/config/validator/subject closure 与 receipt set 一致；被资格 owner 路径或 unit closure 改变立即阻断。

这不是 source fallback，也不把新 HEAD 称为已 qualification。部署 receipt 明确记录两个 source identity 及 compatibility proof digest。

### 3. plan 是完全 no-effect 的 closed inventory

plan 绑定：protected root identity；operator；exact Distribution/manifest/wheel lock/config/schema；Batch 1 plan/report/receipt-set paths 与 digests；44 个 selected safe receipt；compatibility proof；target inventory；credential locator identities；quiescence requirements；backup scopes；adoption entries；monitoring policy；rollback policy；AlphaFold omission；`mutation_applied=false`、`live_occurrence_authorized=false`、`fallback_performed=false`。

receipt 在 plan build 和 authority execution 两次按 `valid_until` 检查。任何过期、missing、duplicate、rejected、digest drift 或 private evidence mismatch 都停止，不减少 scope。

### 4. authority 持久、一次性且绑定 exact plan

`QualifiedRuntimeCutoverAuthority` 绑定 plan digest、deployment source、operator、authority id 和 created_at，不设任意 maintenance window。protected create-once storage 防止覆盖。terminal deployment 恢复 receipt，in-progress residual 停止人工 reconcile，不重派、不推断成功。

P0–P16 与 hard-gate approval 允许机械创建该 exact authority，但不会成为 authority payload 的替代品。

### 5. adoption 是 per-operation 事实，不是 package 开关

executor 独立解析并重验 safe receipt set，然后对 exact unit 使用 `adopt_qualified_external_capability()` 语义形成 `QualifiedExternalCapabilityFact`。adoption ledger 固定 44 个 fact、receipt digest、validity、plan/authority/source compatibility 和 `fallback=false`。AlphaFold unit 不得出现。

application runtime builder 新增显式 deployment adoption 输入，把 `EnzymeDesignExternalQualificationAdmission` 放入 derived operational selection；缺失、过期或 drifted fact 保持 `blocked_qualification`。

### 6. quiescence、backup 与 activation 按顺序封闭

executor 在 mutation 前重验所有 writer surface 已 stopped/isolated、unknown/unsettled effect count 为 0。备份闭包包含 SQLite、configuration、target inventory、wheel lock、qualification receipts 和 adoption ledger，写入同一 protected root 下不可变 generation；每项记录 pre-state digest、backup digest、mode 和 restore verifier。

activation 采用 same-parent staging + fsync + atomic replace 写 deployment state，禁止 dual write。startup readback 隔离构建 runtime 并核对 Distribution、wheel/config/schema、mount、44 facts、blocked AlphaFold、monitoring wiring，成功后才签发 cutover receipt。

### 7. 回滚边界由 first-live acceptance 单向推进

cutover 完成但尚无 post-cutover live acceptance 时，失败可 compare current digest 后恢复 exact backup；未知 drift 不覆盖。第一条 live occurrence 被 backend 接受后，ledger 原子记录 first-live receipt digest 和 boundary，之后禁止 restore old deployment，只允许 quiesce + forward repair 并保留 evidence。

post-cutover smoke 使用新的 occurrence id/authority，不复用 qualification attempt。它只调用 Batch 1 已 adopted route；失败不会自动 rollback 或 fallback，而是进入 forward repair（若 effect 已 accepted）或保留 pre-first-live rollback eligibility（若确定 no-effect）。

### 8. monitoring 只公开结构化脱敏状态

public status 包含 deployment/cutover/adoption/startup/first-live digests、receipt expiry horizon、blocker/error code、effect certainty、fallback/retry facts 和 diagnostic id；credential material、private path、raw stdout/stderr/traceback 只存在受保护诊断或根本不持久化。

## Risks / Trade-offs

- [Provider receipt 在实现或部署期间过期] → 每个 effect 前重新验证；过期即停止并要求新的资格 occurrence，不自动续期。
- [部署源码晚于资格源码] → 双 source + qualified-owner compatibility proof；qualified closure 变化时 fail closed。
- [activation 后 startup readback 失败] → first-live 前 exact compare-and-restore；未知当前 digest 不覆盖。
- [首条 live effect response loss] → 保持 same-occurrence reconcile；不能确定 no-effect 时进入 forward-only，不恢复旧 runtime。
- [owner-local root 被 symlink/权限漂移污染] → 每层 `lstat`、uid/mode 检查和 no-follow atomic writes。
- [AlphaFold mounted surface 被误广告] → plan、adoption ledger、startup proof 三重断言 0 AlphaFold facts 且 affordance blocked。

## Migration Plan

1. 实现 contracts、protected storage、receipt loader/verifier、plan/authority writer 与 deterministic tests。
2. 将 adoption admission 显式接入 EnzymeDesign application composition root；补齐 expiry/drift/AlphaFold/no-fallback 测试。
3. 生成 deployment source、qualified-owner compatibility proof 和 exact dry plan；机械创建一次性 authority。
4. effect 前重验 Batch 1 receipt TTL、quiescence、unsettled effects、root 权限与 backup destinations。
5. 创建备份和 44-fact adoption ledger，原子激活 deployment state，执行 isolated startup readback。
6. 成功签发 `cutover=true` receipt；失败且 first-live 未接受时 compare-and-restore。
7. 创建单独 post-cutover smoke authority并执行最小 Batch 1 occurrence；记录 first-live boundary 和 monitoring evidence。
8. 验证、同步、归档 change，最终只运行一次 `check-mainline.sh` 并创建本地 seal commit。

## Open Questions

无。P0–P16、hard-gate mechanical approval、owner/runtime root、无时间窗口、本地 commit/no push，以及 AlphaFold capacity deferral 已由 operator 决定。
