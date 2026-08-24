## Why

当前分层架构已经明确 Kernel、Adapter、Plugin、Driver 与 Distribution 的边界，但“创建 Session 后即可与常驻队友完成一次可恢复协作”的产品闭环仍未成立：首个 workspace 缺少公开且持久的异步 provisioning 路径，模型看不到完整协作世界与稳定协作动词，workflow 选择没有 request-lineage authority，runtime outcome 也没有把 assistant/tool/failure 真相完整结算回 control plane。继续在这些缺口上叠加垂直能力会让文档心智模型、公开接口和真实执行语义进一步分叉，因此需要一次跨层但边界明确的产品闭环变更。

## What Changes

- Session bootstrap 原子创建 master workspace provisioning intent/reservation，并由有界 durable worker 异步完成选定 workspace Adapter 的 provisioning；公开状态严格区分 `provisioning`、`ready`、`blocked`，HTTP 请求不等待外部 provisioning。
- 保持 `POST /v3/sessions/{session_id}/messages` 只持久化用户消息、workflow authority 与 wakeup；保持 `POST /v3/sessions/{session_id}/runtime/drain` 为唯一显式 bounded scheduler/runtime command，不在消息入口隐式 drain。
- 引入 request-lineage workflow authority：root message、delegation 子集、continuation/approval/downstream causation 都绑定 exact selection、registry snapshot、epoch 与 fence；禁止 raw `skill_keys` 直接授权、latest/all 扫描、隐式 union 或撤销后的继续执行。
- 为每个 runtime turn 构造结构化 world context，覆盖 objective、task board、lane、workspace、inbox、approval、failure、workflow authority、capability affordance 和近期 conversation；上下文是事实投影，不替 agent 作策略选择。
- 将模型可见工具划分为 `Direct`、`Deferred`、`Hidden`：稳定协作动词和角色必需工具直接暴露，long-tail Plugin 工具通过 `capabilities.inspect` 显式发现和扩展，Hidden 永不暴露；扩展不得扩大 authority 或改变已选择 route。
- Kernel 对 runtime outcome 做 durable、fenced、idempotent settlement，持久化 assistant/tool transcript、完整 outcome receipt 和 canonical `FailureObservation`，再决定 continuation；provider/tool/runtime 失败保持显式、结构化、脱敏且无隐藏 fallback。
- 补齐 Standard 与 EnzymeDesign Distribution-owned executable Host launcher，以及 Host API、Thin CLI、Web UI 对 provisioning、消息、显式 drain、assistant transcript、task/delegation/inbox/approval/workspace/failure，以及经验证的投影变化观测的端到端产品闭环；投影变化观测不得冒充 Host/Kernel canonical event stream。
- 增加 fresh、file-backed、非 live 的 Standard 与 EnzymeDesign 端到端验收，证明从 Session 创建到 assistant 回复和 durable collaboration truth 的恢复闭包；不执行真实 provider、HPC、SSH、部署 cutover 或其他 live effect。
- 更新 `AGENTS.md`、`docs/OpenZyme架构设计.md` 与相关 `docs/v3/` 稳定文档，统一当前包布局、身份/owner/lifecycle/persistence/compatibility/error 语义、forbidden fallback 和 Session/runtime 分离。
- **BREAKING**：旧 Session 若缺少当前 workspace generation、workflow authority epoch、runtime catalog/affordance fingerprint 或新 transcript settlement 所需身份，将 fail closed；不提供猜测性兼容、默认 workflow、默认 route 或自动 workspace 修复。

## Capabilities

### New Capabilities

- `resident-teammate-product-loop`: 定义 Session 创建、异步 workspace readiness、消息排队、显式 runtime drain、持久协作、assistant transcript 与 Standard/EnzymeDesign 恢复验收的完整产品闭环。
- `request-lineage-workflow-authority`: 定义 root/derived workflow authority binding、signal link、subset delegation、epoch/revocation/fencing 与 downstream causal propagation。

### Modified Capabilities

- `agent-git-workspace`: 将首个及后续 agent workspace provisioning 纳入 durable reservation、异步 worker、显式 readiness/blocker 与恢复合同。
- `openzyme-kernel-boundary`: 扩展 Kernel 所有权到 provisioning intent、workflow authority link、结构化 turn context 事实与 assistant/tool/failure outcome settlement。
- `openzyme-runtime-adapter`: 要求 Adapter 消费 closed structured turn context，并返回可由 Kernel 完整、幂等结算的 transcript/tool/failure outcome。
- `openzyme-capability-resolution`: 将 model-visible affordance 明确为 `Direct`、`Deferred`、`Hidden`，并约束 inspect/expand 不扩大 authority 或改变 route。
- `file-workspace-public-interfaces`: 扩展 Host/CLI/UI 的 Session provisioning、assistant transcript、collaboration truth、runtime command 与 failure projection，同时保持消息入口与 drain 分离。
- `openzyme-standard-composition`: 要求 Standard 提供 Distribution-owned executable launcher 和 fresh non-live resident-teammate E2E。
- `enzymedesign-product-composition`: 要求 EnzymeDesign 提供同样的 executable product loop，并在 role essentials 与 deferred Plugin capabilities 下通过产品级非 live 验收。

## Impact

- 领域与合同：`packages/openzyme-contracts`、`packages/openzyme-extension-spi`。
- Kernel 与持久化：`packages/openzyme-kernel`、`packages/openzyme-store-sqlite`、workspace/runtime Adapter seams。
- Runtime 与 composition：`packages/openzyme-runtime-llm`、`packages/openzyme-standard`、`packages/enzymedesign-distribution` 及相关 Plugin manifests。
- 公开产品面：`apps/openzyme-host-api`、`apps/openzyme-host-cli`、`apps/openzyme-web-ui`。
- 规格、操作约束与架构说明：`AGENTS.md`、`docs/OpenZyme架构设计.md`、`docs/v3/`、`openspec/specs/` 与本 change 工件。
- 验收仅使用 fake/recording Adapter、临时 file-backed SQLite/Git roots 和非 live 测试；不获得 live/provider/HPC/deployment 授权。
