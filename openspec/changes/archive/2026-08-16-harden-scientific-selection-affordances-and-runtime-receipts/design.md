## Context

r54 的 scientific I/O 与六项 formal controlled operations 已经产生 canonical durable facts，但 executor 在 selection 阶段先后遇到两类 agent-facing 摩擦：

1. `scientific.effect.adopt` 要求事先存在 exact adopted disposition，却只返回缺少 disposition 的笼统错误；
2. AOX workflow role 与 operation signature 的真实映射只存在于 Host validator，既不在 model-visible schema，也不在 attempt inspection/readiness facts 中。

executor 因错误顺序、错误 role 和补查文档消耗 bounded step budget。这个结果按 V3 doctrine 本应是 non-business runtime outcome：task 保持非终态，master 获得恢复注意力并决定继续、求助或拒绝。实际 drain 在 scheduler 已处理该 signal 后构造 runtime consistency projection，`RuntimeConsistencyService` 却读取了 `ScientificSelectionHead.state`；head 只有 CAS identity/version，selection lifecycle state 位于 `ScientificChainSelection`。异常穿过 `V3Service.drain_runtime()`，最终被 runtime command worker 统一改写为 `processed_signal_count=0`。

当前实现还存在合同闭包缺口。`AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT` 的 digest preimage 包含 role 名称和 cardinality，却不包含 validator 使用的 `role -> (sdk_module, function_name)` 映射。因而 attempt 绑定的 digest、Host 校验真相和 agent 可观察事实不是同一个对象。

本设计遵守以下既有边界：

- Harness 忠实、结构化、低摩擦地呈现真实约束，agent 保留 operation/disposition/role/repair/closure 策略；
- full occurrence universe、effect certainty、authority、quiescence 和 cross-attempt 禁止规则不降低；
- runtime stop、selection closure 和 task business terminal 相互独立；
- r54 与旧 contract evidence 保持 immutable historical NO-GO；
- SQLite 继续是单进程 canonical store，本变更不引入 graph-first 或新的顶层 workflow 真状态。

## Goals / Non-Goals

**Goals:**

- 让新 scientific attempt 绑定一份同时驱动 validation、agent-safe projection 和 verifier 的 versioned workflow contract。
- 通过 repository-level resolved head 消除 CAS pointer 与 selection lifecycle 的错误混用，同时保持单一状态真源。
- 提供纯读取、deterministic、bounded 的 selection evaluation，使 inspect、tool error、seal 和 consistency audit 对同一 canonical facts 得出一致结论。
- 让 agent 用一个显式命令选择 exact operation、workflow role 与 reason，并原子写入 adopted disposition 和 effect adoption。
- 让 runtime command receipt 永远保留已经发生的 scheduler 进度，并把 post-scheduler projection outcome 单独表达。
- 把 step-budget exhaustion 表达为 exact turn/signal 终止但 agent 可重新规划、task 非终态的结构化失败。
- 以 file-backed SQLite 和真实 Host composition 覆盖 r54-shaped 跨层回归，完成稳定文档和 active AOX 规格对齐。

**Non-Goals:**

- 不由 Harness 选择“最佳”operation、workflow role、replacement、scientific branch 或 task 终态。
- 不从 operation 成功、时间顺序、相同 bytes、下游使用或报告文本推断 adoption。
- 不通过增大全局 step budget、prompt 固定 AOX role、静默 role alias、自动补 disposition 或自动重放 signal 规避问题。
- 不复制 `ScientificChainSelection.state` 到 `ScientificSelectionHead`，不增加可漂移的第二份 lifecycle 真相。
- 不吞掉未知 projection/programming error；已发生进度必须保真，但完整性失败仍显式 fail closed。
- 不把整个 selection 作为一个大而全的 workflow batch 交给 Harness 路由；第一版保持逐 occurrence 的 agent 决策。
- 不迁移、升级、恢复或继续 r54，不消费新 authority plan，不运行 provider、HPC、Chrome 或 numbered live campaign。

## Decisions

### 1. Workflow contract registry 是角色约束的唯一运行时真源

在 `openzyme-core` 定义通用、不可变的 scientific workflow contract 对象和 registry。Host composition 注册具体合同；`ScientificAttemptService` 按 attempt 的 `workflow_id + workflow_contract_digest` 精确解析合同。

合同的 canonical public-safe preimage 至少包含：

- schema id、contract id、workflow id；
- 每个 attempt scope 的合法 workflow roles；
- 每个 role 的一个或多个 closed operation signatures：`sdk_module + function_name`；
- role cardinality；
- effect/adoption 与 same-attempt reuse 约束的稳定标识；
- projection schema/version。

合同对象提供三类无写入能力：

1. `resolve(attempt)`：精确匹配 workflow id 与 digest；
2. `compatible_roles(attempt, operation)`：只计算当前 operation 满足的确定性角色集合；
3. `validate_role(...)`：执行与 projection 同源的 closed validation。

AOX 新合同升级为 `aox_blank_world_selected_chain@2`，digest 覆盖 role-to-operation mapping。旧 `@1` preimage/digest/reader 冻结，只服务历史 evidence 与明确的 validation-only compatibility；它不向新 attempt admission 提供 active contract authority。

**替代方案：继续注入 callable validator。** 拒绝。callable 只能回答“合法/非法”，无法安全投影约束，也无法证明 digest 覆盖实际校验数据。

**替代方案：把 AOX roles 写进 prompt 或静态 tool enum。** 拒绝。prompt 不是 contract authority；静态 enum 无法绑定 exact attempt scope/digest，也会把领域合同固化到通用 Core schema。

### 2. Selection head 保持 CAS pointer，新增 resolved read model

`ScientificSelectionHead` 保持现有五字段，不增加 `state`。`ScientificSelectionRepository` 新增单次 SQL join 的 `resolve_head(attempt_id)`，返回：

```text
ResolvedScientificSelectionHead
  head: ScientificSelectionHead
  selection: ScientificChainSelection
```

join 必须校验：

- head 与 selection 的 attempt id 相同；
- head `selection_id` 指向存在的 canonical row；
- head revision 与 selection revision 相同。

无 head 返回 `None`。dangling/mismatched head 产生稳定 `ScientificSelectionIntegrityError`，携带 closed error code，不包含 SQL、路径或私有诊断。

普通 service mutation 在 integrity error 时 fail closed。`RuntimeConsistencyService` 将已知 cross-row integrity error 转换为 `scientific_selection_head_invalid` warning/attention，而不是抛出语言级异常；未知 DB/programming error 仍向 projection boundary 传播，由真实 receipt 机制记录。

**替代方案：把 state 冗余写进 head。** 拒绝。它要求额外迁移、触发器和双写校验，却仍可能与 immutable selection row 漂移。

### 3. 一个纯 selection evaluator 同时服务 inspect、error、seal 与 audit

在 Core 增加无 mutation authority 的 `ScientificSelectionEvaluator`。输入 exact attempt/selection/contract 和 canonical repositories，输出内部 `ScientificSelectionEvaluation`：

- resolved head identity、selection lifecycle、universe identity；
- 每个 occurrence 的 operation signature、terminal/effect facts；
- current disposition/adoption/materialization refs；
- allowed roles 与 operation-compatible roles；
- closed issues：missing/unexpected disposition、missing/unexpected adoption、duplicate role、invalid role/signature、unknown effect、active/unretired work、cross-attempt or authority mismatch；
- aggregate gap counts/ids 与 `seal_ready`。

issue 使用稳定 code 和安全、bounded details；不包含 recommended action。`seal_ready=true` 仅表示当前 canonical facts 满足 seal invariants，不表示 agent 应该 seal，更不表示 task 完成。

`ScientificAttemptService.seal_selection()` 和 closure revalidation 必须消费 evaluator 的同一 internal result，不再维护另一套 `_validate_complete_selection` 分支。mutation command 的局部 precondition validation也复用 evaluator/contract primitives。

投影分两层：

- `world.inspect` 只提供 attempt/head、gap counts、blocker codes 等 bounded summary；
- `scientific.attempt.inspect` 支持 exact attempt/selection filter 和 bounded occurrence paging，返回详细 evaluation page、contract digest/constraints 与 page identity。

现有无参数 inspect 保持兼容，返回 session summary；模型需要逐 occurrence 决策时显式请求 exact selection page。公共投影继续拒绝 Host locator、lease/fence、credentials、raw backend handles 和 recommended actions。

**替代方案：只丰富错误 hint。** 拒绝。错误只能在 agent 猜错后出现，且容易与 seal validator 再次漂移。

### 4. 新增显式原子 `scientific.operation.adopt`

新增 model-visible command：

```text
scientific.operation.adopt(
  selection_id,
  operation_id,
  workflow_role,
  reason_code,
  idempotency_key
)
```

agent 明确提供全部策略字段。Host 在一个 repository transaction / mutation writer turn 中：

1. 解析 draft current head 与 exact contract；
2. 确认 operation 属于 selection universe；
3. 校验 successful terminal known execution/result/approval；
4. 校验 exact workflow role 与 operation signature；
5. 写入 adopted `ScientificOperationDisposition`；
6. 写入 matching `ScientificEffectAdoption`。

两条 canonical row 使用同一 normalized command request digest 和 idempotency identity。重放时必须同时找到两条 exact matching rows；只有一条存在视为 integrity failure，不能补写另一半。任一步失败整笔回滚，公开结果明确 `mutation_applied=false`。

`scientific.operation.disposition` 继续处理 `failed`、`superseded`、`abandoned`。它不再接受 `kind=adopted`，防止新 surface 重新产生半完成 adoption。Core 可暂时保留旧 `adopt_effect()` service primitive 用于 frozen compatibility tests/readers，但 `scientific.effect.adopt` 从新 model-visible catalog 移除，且不得用于 `@2` selection。

第一版不增加整条 selection batch command。逐 occurrence 原子命令已经消除双写与主要 step 浪费，同时保留 agent 在每个事实上的独立决策。

### 5. Tool rejection 返回 precondition facts，不返回替代决策

所有 scientific command error 继续使用 `ScientificAttemptError`，但 adoption/role/seal 相关错误增加闭合 details：

- exact attempt/selection/head state version；
- current disposition/adoption 的安全 identity；
- required disposition kind 与 requested role；
- allowed roles、compatible roles 和 operation signature；
- missing ids、blocker codes；
- `mutation_applied=false` 与 retryable/recovery boundary。

例如 invalid role 可以告诉 agent “该 scope 允许 A/B/C，当前 operation 兼容 B”，但不得自动把 requested role 改成 B，也不得输出 `recommended_actions`。这种映射是合同事实，不是 scientific strategy。

### 6. Runtime drain 分离 authoritative scheduler outcome 与 projection settlement

`V3Service.drain_runtime()` 在 scheduler batch 结束后立即形成不可丢失的 internal core receipt：

```text
RuntimeDrainCoreReceipt
  scheduler_status
  processed_signal_count
  suspended
  output/event identities
```

随后进行 trace/activity/consistency event、event append 和 workspace projection settlement。settlement 形成独立结果：

```text
RuntimeDrainProjectionOutcome
  status: complete | failed
  error_code?
  safe_summary?
```

公开 runtime command bounded outcome 升级为 `runtime_command_outcome@2`，至少包含：

- scheduler status；
-真实 `processed_signal_count`；
- suspended；
- projection status；
- `replay_safe`，只要 scheduler 已处理任何 signal 就固定为 `false`。

若 scheduler 完成但 required projection 失败，overall command 仍可为 `failed`，error code 使用 `runtime_projection_failed`；但是 `processed_signal_count` 必须保留，safe hint 必须禁止盲目重放并要求读取当前 canonical state。旧 `@1` receipts 保持可读，不回填新字段。

`HostRuntimeCommandExecutor` 接收 typed drain result，而不是依赖任意对象 `getattr` 丢失语义。只有 scheduler 尚未产生 core receipt 的 boundary exception 才允许 worker 使用 `processed_signal_count=0`。worker catch-all 保留为最后防线，但不能覆盖一个已经形成的 partial/core receipt。

每个 `AgentRuntimeOutcome` 还必须携带 Core-owned typed settlement。普通完成、等待 approval、
普通失败与 closed budget-replan handoff 使用闭集 disposition；settlement 绑定 source signal
occurrence 的 session/task/lane/agent/correlation/attempt snapshot。budget handoff 额外绑定 exact
failure observation 与 exact successor master signal。Host 只能聚合这个 typed settlement，
不得在 scheduler 释放 session lease 后重新读取 mutable task/signal/failure/wakeup rows 来猜测
同一 outcome 是否已经结算。task 的显式 `failed`/`blocked` 等业务出口仍是 agent 决策，不得
反向把一个成功完成的 signal/batch 改写成 scheduler failure。

**替代方案：在 consistency projection 外包一层 broad `except` 并继续 success。** 拒绝。它会隐藏真实完整性故障。

**替代方案：所有 post-processing failure 都按零进度失败。** 拒绝。它与 durable scheduler rows 矛盾，并可能诱导重复 drain。

### 7. Step-budget exhaustion 区分 occurrence terminal 与 task recoverability

teammate bounded loop 达到 max steps 且没有 terminal task action 时：

- 当前 `AgentRuntimeSignal` 终止为 failed，不自动 replay；
- failure observation 使用稳定 `agent_turn_budget_exhausted`；
- `recoverability=agent_can_replan`；
- exact signal 的 `retry_eligibility=terminal`，表示该 occurrence 不再执行；
- `effect_certainty=no_effect` 仅描述 runtime signal 本身，不覆盖同 turn 已产生的 controlled-operation effects；
- task status、failure summary/ref 保持不变；
- master wakeup 保持 source-bound、去重，并从 canonical failure + selection evaluation 构造 recovery facts。

agent member 可以保留 runtime-failed attention，后续由 master 显式 resume/redelegate；Harness 不自动增加 budget、重开 selection、选择 role 或创建 fresh attempt。

core receipt 还必须区分“signal occurrence failed”与“scheduler batch 没有完成结算”。
如果且仅如果 teammate max-step outcome 同时闭合到 canonical failed signal、同 attempt
version 的结构化 `agent_turn_budget_exhausted` observation、非终态 business task，以及
exactly one source-bound master wakeup，则该 outcome 已由 scheduler 完成有界结算：
exact signal 继续保持 failed/terminal，新的 master wakeup 是独立 turn，而 core receipt
的 scheduler layer 可为 `completed`。缺 observation、缺失或重复/取消 wakeup、task 已终态、
projection identity drift、普通 runtime failure，或 master 自身 max-step 均继续令
scheduler layer `failed`。这个 completed 只表示 batch settlement，不表示 signal、task、
scientific attempt、report 或 campaign 成功。

teammate finalization 在持有 session runtime lease、runtime write fence 与短 transaction 时形成
上述 typed settlement；settlement 一旦返回就是该 bounded occurrence 的 immutable snapshot。
任何 max-step outcome——无论 handoff 是否闭合、发生在 master 还是 teammate——都会结束当前
claim wave 之后的 scheduler batch。已经在该 wave 中 claim 的独立 signal 可以完成，但 scheduler
不得再从 repository claim 本次 finalization 新建的 successor；它只能由下一条 runtime command
或下一次 background tick 获得新的 session authority 后 claim。这样 `max_signals > 1` 不会把
“创建 successor”和“执行 successor”折叠到同一 command。

Host receipt 聚合只接受 Core settlement 的闭集 schema/disposition。closed
`budget_replan_handoff` 可以把 `ok=false` 的 exact occurrence 解释为 completed batch
settlement；任何缺失、unknown 或普通 failed settlement 继续 fail closed。Host 不检查当前 task
是否后来 terminal，也不接受 `id(outcome)`、自由文本、可变 wakeup status 或 repository rescan
作为结算 authority。

`RuntimeConsistencyService` 不再依赖错误字符串识别 max steps；它优先使用 failure observation error code，旧 signal 文本匹配只作为 frozen compatibility。

### 8. Active AOX contract 与历史 evidence 明确分层

active `aox-hmm-blank-world-cutover` 中“任一 prior terminal failure 强制 fresh attempt”的旧 scenario 改为：

- known terminal/no-effect occurrence 可在同一 authorized formal attempt 内显式 `failed`/`superseded` disposition，并由 agent 采用合法 replacement；
- unknown/dispatch-in-doubt effect、活动 process/writer/continuation、缺失 disposition authority、cross-attempt reuse、resource/permission breach 仍阻止后续 dispatch 或 seal。

active change 增加 r54 诊断 addendum，记录：

- r54 保持永久 NO-GO；
- scientific operations 的成功事实不等于 attempt/report/campaign 成功；
- selection 未 seal/close；
- runtime command receipt 被 projection bug 错报；
- 修复只适用于新 contract/new attempt；
- 后续 live 仍需要 fresh clean commit、full non-live qualification、fresh authority plan 和用户精确批准。

历史 DB、bundle、decision、ledger 与 root 不做 migration 或回写。

## Risks / Trade-offs

- **[Contract `@2` 使现有 AOX fixtures/digests 大量变化]** → 冻结并显式命名 `@1` preimage/reader；集中由一个 `@2` contract object 生成 digest、validator 和 projection，使用 digest golden/tamper tests 防止再次分叉。
- **[Evaluator 可能复制 seal 逻辑或产生观察/执行漂移]** → seal/closure 只消费 evaluator internal issues；公开 projection只是同一 result 的 sanitizer/page view，禁止独立重写规则。
- **[Atomic adoption 两仓库写入的 idempotency 部分损坏]** → 单事务、同一 request digest、双记录 replay closure；单边 row 作为 integrity failure fail closed，不自动修补。
- **[详细 constraints 使 public payload 膨胀]** → `world.inspect` 只给 summary，selection detail 使用 exact filter、cursor/limit、stable ordering 和 payload budget；bulk identities不进入 error hint。
- **[Projection failure 仍导致 command failed，调用方误以为可重试]** → `@2` 明确 `processed_signal_count` 与 `replay_safe`，safe hint 禁止盲重放；status UI/CLI 同时展示 scheduler/projection 两层。
- **[step-budget signal terminal 与 agent-can-replan 看似矛盾]** → 文档和 schema 明确：terminal 属于 exact signal occurrence，recoverability 属于 task/agent decision；新 wakeup 必须是独立 canonical signal。
- **[旧 model/provider 仍尝试 `scientific.effect.adopt`]** → tool catalog 移除其 model visibility，unknown/hidden tool 返回普通 no-effect error；workflow docs 与 tests只展示原子命令。
- **[把 compatible role 暴露给 agent 被误解为 Harness 选策略]** → projection只报告 operation signature 满足哪些合同 role；是否 adopt、选哪一个 occurrence、如何处置其他 occurrence仍由 agent 显式决定。

## Migration Plan

1. 先同步本 change 的 specs/design/tasks，并在 active AOX spec 中解决 known failure 规则冲突；此阶段不改 runtime、不运行 live。
2. 增加 resolved head 与 r54-shaped runtime consistency regression，先消除 deterministic crash；不改变数据库 schema 或历史 rows。
3. 增加 generic contract registry、冻结 AOX `@1`、引入 AOX `@2` 与 digest/compatibility/tamper tests；在所有新 admission/config/workflow pins 中只接受 `@2`。
4. 增加 selection evaluator、bounded inspection/readiness projection、结构化 errors，并让 seal/closure 切换到同一 evaluator。
5. 增加原子 adoption command，移除旧两步 adopted path 的 model visibility，完成 transaction/idempotency/rollback tests。
6. 增加 runtime drain core receipt、projection outcome 和 `runtime_command_outcome@2`，更新 API/CLI/UI projection与旧 `@1` reader tests。
7. 修正 max-step failure classification和 recovery brief；增加 Core typed settlement、max-step batch barrier 与 Host-only aggregation，并用 scheduler/protocol/runtime consistency/真实 command worker tests 闭合。
8. 同步 `docs/OpenZyme架构设计.md`、`docs/v3/00-harness-doctrine.md`、`04-public-interfaces.md`、`05-agent-runtime.md`、`06-top-level-llm-loop.md`、`08-failure-recovery-and-scientific-attempts.md` 及 AOX runbook。
9. 运行 focused tests、file-backed Host integration、ruff、`git diff --check`、`./scripts/check-mainline.sh`、V3 eval、Web UI tests/build 和 OpenSpec strict validation。
10. 停在 non-live verified/ready 状态。任何 live authorization/consumption/root/effect 都需要目标之外的用户新批准。

回滚时可在尚未产生新 `@2` attempt 前整体回退代码。若已有 non-live `@2` rows，旧代码只允许读取/导出已知 schema，不得用 `@1` validator 继续 mutation；本 Goal 不产生 live `@2` evidence，因此无需历史 live data rewrite。

## Open Questions

无。上述 ownership、versioning、compatibility、failure status 和 no-live 边界均在实现前闭合；若实现发现必须新增顶层产品真状态或无法由同一 evaluator 支撑 seal，则暂停 apply 并回到本设计修订，而不是引入隐藏 fallback。
