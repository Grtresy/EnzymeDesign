## Why

r54 已证明当前 scientific selection 的真实约束虽然存在于 Host validator，却没有作为 attempt-bound、机器可读的 facts/affordances 交给 agent；同一次运行又因 selection head 读取错误，在 scheduler 已推进后把可恢复的 step-budget outcome 误报成零进度 runtime command failure。现在需要把合同可观察性、显式原子选择和真实 runtime receipt 作为一条通用 V3 control-plane 能力闭合，而不是把 AOX 角色或恢复步骤写死在 prompt。

## What Changes

- 增加 digest-bound scientific workflow contract 的安全观察面：validator、agent projection 与 verifier 必须消费同一份角色、scope、operation signature、cardinality 和 reuse 约束，且只呈现约束，不推荐或代替科学决策。
- 增加纯读取、可复用的 scientific selection evaluation：解析 CAS head 指向的 canonical selection，投影每个 occurrence 的 disposition/adoption、兼容角色、缺口、硬 blocker 与 seal readiness，并让 seal validation 使用同一评估结果。
- 增加显式原子 adoption 命令：agent 仍须选择 exact operation、workflow role 与理由，Host 在一个事务中校验并写入 adopted disposition 和 effect adoption，失败时不得留下半完成选择。
- 修改 runtime command outcome：scheduler 已产生的 durable 进度不得被后续 consistency/event/workspace projection failure 抹成零；command 必须分别暴露 bounded scheduler facts 与 projection outcome，并禁止不安全重放。
- 修改 step-budget recovery：一次 bounded turn/signal 可以终止，但 task 保持非终态，failure observation 必须表达 agent 可重新规划且同一 signal 不会被静默重放。
- **BREAKING（仅限新 scientific attempts）**：新增完整覆盖角色到 operation signature 映射的 workflow contract 版本；旧 contract 与 r54 evidence 保持冻结、只读、永久 NO-GO，不被原地升级。
- 对齐 active AOX cutover 中仍残留的“任一 terminal failure 强制 fresh attempt”旧规则与 selected-chain 合同：known terminal/no-effect occurrence 可显式处置，unknown effect、活动 writer/continuation、authority/resource breach 仍 fail closed。

## Capabilities

### New Capabilities

- `scientific-workflow-contract-observation`: versioned scientific workflow contract 的单一真源、digest closure、scope/role/operation compatibility 以及 agent-safe constraint projection。
- `scientific-selection-readiness`: resolved selection head、纯读取 readiness evaluation、结构化 precondition error 与显式原子 operation adoption。

### Modified Capabilities

- `runtime-continuation`: runtime command 必须保留已发生的 scheduler 进度并区分 projection outcome；step-budget exhaustion 必须保持 signal occurrence、agent recovery 与 task business status 的边界。

## Impact

- 影响 `packages/openzyme-domain` 与 `packages/openzyme-core` 的 scientific contract/selection 对象、repository read model、service、tool catalog、runtime consistency、failure observation 和 tests。
- 影响 `apps/openzyme-host-api` 的 AOX scientific contract composition、runtime command executor、V3 drain/projection 协调、eval 与 file-backed integration tests。
- 影响 `scientific.attempt.inspect`、`world.inspect`、runtime command status/event 的 bounded public projection；不得新增 Host path、lease/fence、provider/runner locator 或推荐动作泄漏。
- 需要同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/` 稳定文档、active AOX cutover 的 r54 诊断/规格引用，并完成 focused、mainline、eval 与前端 non-live 验证。
- 不消费新的 AOX authority plan，不创建新的 numbered live root，不调用 provider/HPC/Chrome；r54 保持历史失败证据。
