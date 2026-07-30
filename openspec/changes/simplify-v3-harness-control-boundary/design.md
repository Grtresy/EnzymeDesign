## Context

V3 已经拥有足以防止 false completion 的 canonical state：

- task 业务终态只能由 `task.finish` 或极少数明确机械迁移写入；
- runtime signal 的 terminal 只描述一次 wake occurrence，不代表 task 完成；
- external operation 由 durable execution/effect record、lease/fence 与 continuation
  约束；
- ordinary tool rejection 已携带 `effect_certainty`、`recoverability` 与安全诊断。

在这些边界之上，r60/r61 又引入了一套 turn-local recovery proof machine。它把
`no_effect|terminal_known` 失败登记为 obligation，拒绝普通 assistant response，只接受
closed matcher 证明的 corrected retry、特定 inspection、condition disposition、
same-task exit 或 suspension。为了支持 dependency wait，系统进一步增加 disposition
repository、tool、reconciler 与 `RECOVERY_REQUIRED` signal。

这套机制没有保护新的不可逆安全性质。它试图保证“agent 在本 turn 做了一个被 Harness
认可的后续策略”，但策略完整性本来就不应由 Harness 推断。它同时把开放的模型行为映射到
不断增长的 matcher 闭集，导致每个合法新轨迹都需要再增加代码、schema、测试和 prompt。

本变更必须在当前唯一声明支持的
`local_single_process_file_sqlite@1` profile 上保持外部 effect、authority、approval、
artifact provenance 与 mutation closure 的既有安全性，并以生产代码净删除完成。

## Goals / Non-Goals

**Goals:**

- 让 ordinary known-effect tool/domain rejection 只影响当前 tool call，不导致
  Harness/runtime boundary fatal，也不自动改变 task。
- 删除 recovery obligation、settlement、disposition、hypothesis 与 synthetic recovery
  wakeup 的 active control-plane path。
- 让 `HarnessStatus.COMPLETED` 只表示本 turn 正常返回；继续依赖 explicit
  `task.finish` 表达业务完成，不增加新的 yield/phase/status 抽象。
- 把 AOX workflow completeness 从 generic response veto 移回 domain command
  precondition 与最终 acceptance evaluation。
- 让 scientific lifecycle/readiness 只有一个 canonical evaluator，其他层只消费
  immutable evaluation payload。
- 明确 Lane 只服务真实 workspace isolation；任何并非隔离所需的 failure/recovery/
  occurrence identity 复制随相应机制删除。
- 用状态不变式而非已知模型剧本验证：任意 ordinary no-effect error、成功 read、prose、
  corrected retry 或 step exhaustion 的有限组合都不得产生 boundary-fatal ownership loss。

**Non-Goals:**

- 弱化 unknown effect、dispatch-in-doubt、authority、permission、fencing、integrity、
  provenance、secret 或 external-operation idempotency。
- 自动替 agent 重试、delegate、finish task、选择 scientific chain 或生成报告。
- 在本 slice 删除真实仍承载 workspace/worktree isolation 的 Lane entity/API；只有
  evidence 证明其没有实际消费者时才另行删除。
- 重新设计 scheduler、增加新状态机、引入新的 workflow engine 或增加新的 durable
  recovery schema。
- 启动 MICU、provider、HPC、Chrome 或任何 live attempt。

## Decisions

### 1. Known-effect rejection is already safely settled

`no_effect` 表示请求没有改变世界；`terminal_known` 表示 effect 的终态已知。两者都可以继续
作为 ToolResult/failure evidence 回灌模型，但 Harness 不再为它们创建第二个 obligation。
模型可以继续调用工具、输出 prose、达到 step bound 或正常结束。task 仍保持原状态，因此
不会把 narration 误解为业务完成。

不新增 `YIELDED`。已有结果足够：

- 普通 turn 返回 `COMPLETED`；
- step budget 返回 `MAX_STEPS_EXCEEDED`；
- durable approval 返回 `WAITING_APPROVAL`；
- 只有 provider/driver 不可运行或 boundary-fatal error 返回 `FAILED`。

替代方案“继续补全 exact matcher”被拒绝，因为合法策略关系是开放集；matcher 的风险清单
本身已承认每出现一种新关系就需要新增实现。

### 2. Failure evidence is data, not a second task system

删除 active `FailureRecoveryDisposition`、`FailureHypothesis` repository/tool/projection 与
condition reconciler。普通 validation/domain rejection 由 durable LLM trace、ToolResult 和
必要时的 `FailureObservation` 提供证据。agent 的推测属于 task/protocol/memory 文本，不再
占有独立 canonical table。

历史 migration `034`/`036` 暂时保留，使既有 SQLite 能继续打开和接受当前 migration
digest；对应表不再被 active repositories 暴露，也不再产生新记录。待下一个明确的 storage
major-version cleanup 再物理删除历史表。这样回滚不需要重写用户数据库。

### 3. Runtime wakeup only represents a real event

删除 `RECOVERY_REQUIRED` signal reason 及其 source-specific prompt/claim/reconciliation。
blocked task 的依赖已经存在于 `Task.blocked_by`；依赖完成、teammate response、protocol
message、approval resolution、engine completion 或 user message 是正常 wake source。
Harness 不为了证明 agent 曾经说“等待”而创建 synthetic subscription。

`task.delegate` 对 open dependency 的 no-effect response 保持结构化、LLM-readable；
它不自动 delegate，也不改变 task。后续是否再尝试由未来真实 wake 中的 agent 决定。

### 4. AOX policy may guard mutation, not narration

删除 `assistant_response_precondition` 从 Host composition、runtime context、master/teammate
driver 和 AOX closure/cutover wiring 的传播。系统不再拦截并丢弃普通 assistant response。

AOX tool precondition 只可在 handler 前拒绝不具 authority 或当前 domain precondition
不成立的 mutation；该拒绝为 no-effect ToolResult。report handoff、何时 delegate、先检查
还是等待等策略不再通过 response veto 强制。最终 attempt 只有在 canonical task/report/
selection/closure facts 完整时才能被 verifier 接纳。

### 5. Lifecycle/readiness is computed once

`ScientificSelectionEvaluation`/derived attempt lifecycle 是唯一 canonical truth。Host
supervisor、AOX runtime observation 与 evidence collector 不得再从 mutable base attempt
row、report enum 子集或局部 event window重建另一个 readiness。historical closure-stage
consumer 已由 r65 退役删除，其 SQLite/evidence 兼容 reader 也不得成为 active readiness
owner。

实现时优先删除重复判断并传递现有 evaluation payload，而不是建立新的 projection/service。
outer error 只可在没有内层根因时生成自己的 code；已有 causal error 必须原样保留。

### 6. Lane is an isolation resource, not universal causal identity

Lane 当前仍承载 `cwd`、branch 与 execution workspace 隔离，因此本变更不先验删除实体。
但 recovery obligation/disposition 被删除后，相关 `lane_id` proof equality 同时删除；
ordinary tool failure 不再因为 Lane snapshot 漂移转成 fatal。后续以实际 UI/API/executor
消费者清单决定是否把 Lane 降为 task-owned workspace binding 或完全移除。

替代方案“一次提交删除 Lane、runtime lease、recovery 和 AOX policy”被拒绝：它会同时改变
隔离、安全和策略三条轴，无法证明失败时没有弱化 external-effect boundary。破而后立仍需
保持每个删除 slice 可验证。

### 7. Tests prove invariants under trace variation

删除期望 ordinary failure 最终 `HarnessStatus.FAILED` 的脚本测试，保留
`FakeModelFactory` 作为 deterministic driver，但用同一 state invariant 覆盖多种后续动作：

- prose-only；
- successful read；
- corrected same-tool retry；
- unrelated successful tool；
- multiple ordinary failures；
- step bound。

所有场景必须证明 task/approval/external operation 未被隐式改变、source occurrence 没有
被误报为 boundary fatal。另保留 unknown-effect/authority/fencing negative controls，确保
真正危险路径仍 fail closed。

## Risks / Trade-offs

- [Agent 在普通错误后结束 turn，工作暂时停滞] → task 保持 nonterminal，等待真实
  user/task/protocol/approval/engine event；这是模型质量或产品 liveness，不是安全故障。
- [删除 hypothesis/disposition 后历史 projection 字段缺失] → public schema 不再承诺这些
  internal bookkeeping fields；历史 DB 表保留只读兼容，当前 projection 忽略它们。
- [某个消费者暗中依赖 `RECOVERY_REQUIRED`] → 先用全仓 reference audit 和 focused
  scheduler/runtime tests证明删除闭包；不得用新 signal reason 替代。
- [取消 response veto 后出现未完成 AOX assistant text] → 未满足 domain facts 的 attempt
  仍不能 close/finalize/accept；conversation text 不授予 scientific success。
- [canonical lifecycle consumer 迁移遗漏] → 将重复检查清单写入 tasks，并以 r59
  closure truth、r60 corrected retry、r61 dependency wait 的历史 trace regression 验证。
- [净删除时误删 external safety] → 对每个保留边界建立 negative-control test；production
  diff 若不是净删除则视为设计回归。

## Migration Plan

1. 建立 baseline reference/line-count 与 safety-invariant tests。
2. 删除 Harness obligation/settlement/rejection/fatal exit，改写 ordinary-failure tests。
3. 删除 disposition/hypothesis active repositories、tools、signal reason 与 reconciler；
   保留历史 migration assets。
4. 删除 assistant-response precondition 全链路与 AOX response veto，收窄 tool policy。
5. 收敛 scientific lifecycle/readiness consumer 与 outer root-cause projection。
6. 审计 Lane/lease 的实际消费者，只删除可证明与 workspace/external safety 无关的复制。
7. 同步 `docs/OpenZyme架构设计.md`、`docs/v3/` 与 active OpenSpec 状态。
8. 运行 focused regression、OpenSpec strict validation、ruff、非 live pytest/eval/mainline；
   审查生产代码净删除后创建一个本地提交。

回滚使用代码回滚；历史数据库无需数据 rewrite。任何 live 运行仍需独立 operator 授权。

## Open Questions

- Lane 是否存在 UI/API 之外的真实并行 worktree 使用者？本变更实施阶段通过引用和运行测试
  决定“保留为隔离资源”或提出后续完全删除 change，不凭字段数量直接猜测。
- `FailureObservation` 是否应仅对 external/boundary failure 持久化，ordinary validation
  只保留 ToolResult trace？本变更先删除其策略门禁；若仍无跨 turn 消费者，再做第二阶段
  evidence slimming。
