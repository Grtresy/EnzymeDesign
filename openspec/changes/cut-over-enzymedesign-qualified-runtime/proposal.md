## Why

EnzymeDesign 的 exact-source Batch 1 已取得 44 个当前真实资格 receipt，但这些证据仍未被部署采用，产品运行时也没有 cutover receipt。现在需要一个独立、可恢复、无 fallback 的部署 change，把未过期资格证据转成受保护的 operation-scoped resource facts，并证明真实 runtime 启动；AlphaFold 因目标 GPU 容量不可用继续排除在本次范围外。

## What Changes

- 建立 source-bound cutover dry plan，绑定 Batch 1 receipt set、资格源码、部署源码、exact wheels/Distribution/config/target inventory、受保护 runtime root、quiescence、backup、rollback 和 monitoring closure。
- 要求 distinct durable one-shot cutover authority；资格、P0–P16 决策或环境变量都不能替代它。
- 独立重验 Batch 1 的 44 个未过期 receipt，并仅按 exact capability + operation + route + subject + source/build/config digest 形成 adopted facts；禁止扩大、自动刷新、route/target fallback 或采用 AlphaFold。
- 在 owner-local `0700` runtime root 下持久化 `0600` plan、authority、backup manifest、adoption ledger、deployment state、startup proof、cutover receipt 与 redacted monitoring evidence；拒绝 symlink 和 ambient `.env` runtime truth。
- quiesce 所有声明 writer，要求零 unsettled/unknown effect，完成 SQLite/config/target inventory/wheel lock/qualification evidence/adoption ledger 的可恢复备份，再原子激活 exact runtime。
- 在第一条 post-cutover live occurrence 前允许 compare-and-restore exact backup；一旦首条 live occurrence 被接受，只允许 forward-only repair 并保留全部证据，禁止 dual write 和自动回退旧 runtime。
- 启动 readback 必须证明 exact Distribution、wheels、schema、adapter/plugin/driver mount、adopted facts、blocked AlphaFold 与 monitoring wiring；另行授权的 post-cutover live smoke 只使用 Batch 1 能力且产生独立 occurrence receipt。
- 只创建本地 seal commits，不 push，不向 GitHub 或其他托管平台同步本地资格 Git/LFS subject。

## Capabilities

### New Capabilities

- `enzymedesign-qualified-runtime-cutover`: 定义 cutover plan/authority、receipt adoption、protected deployment state、quiescence/backup、activation/startup proof、rollback/forward-only、monitoring 与 post-cutover live smoke。

### Modified Capabilities

- `openzyme-layered-qualification`: 明确 qualification source 与 deployment source 的双重 identity、compatibility proof，以及 cutover receipt 不能授权后续 live occurrence。
- `openzyme-target-toolchain-inventory`: 规定 Batch 1 exact per-operation facts 的 deployment adoption ledger、TTL recheck 与 AlphaFold omission。
- `openzyme-extension-composition`: 要求 operational Adapter selection 从已验证 deployment adoption 装载 qualification admission，禁止 ambient 或 mounted-only route。
- `enzymedesign-product-composition`: 固定本次 adopted profiles 为 Batch 1 五个 profile，并把 AlphaFold 显式投影为 deferred/non-qualified/not-advertised。
- `host-quiescence-sealing`: 将 EnzymeDesign external runtime writers、unsettled effect set 和 first-live rollback boundary 纳入 cutover sealing。

## Impact

- 主要影响 `packages/enzymedesign-distribution` 的 deployment/cutover contracts、CLI 与 application composition root，复用 `openzyme-contracts` 资格事实和 `openzyme-store-sqlite` 的 offline planning/backup primitives。
- 新增受保护 operator deployment root `/home/grtresy/.local/state/openzyme/deployments/enzymedesign-qualified-runtime`，不把 secret material、私有诊断、原始输出或 credential value 写入仓库。
- 部署 effect 只发生在 owner-local runtime state、local SQLite/config/adoption 文件和已选择的本机 runtime activation；post-cutover smoke 的 Provider/HPC/容器 effect 必须是单独 occurrence。
- **BREAKING**：cutover 后 runtime 不再接受缺失、过期、drifted 或未 adopted 的 external route；AlphaFold 不出现在有效 affordance 中，且不存在自动 fallback。
