## Why

V3 Harness 已把普通、已知无副作用的 agent 试错提升为必须在同一 turn
命中闭集 proof matcher 的恢复义务；真实模型只要采用安全但未枚举的检查、等待或结束方式，
runtime 就会把未改变业务状态的 turn 判为 fatal。r60/r61 以及随后不断扩张的
`make-turn-recovery-semantically-complete` 证明该方向不能通过继续增加 matcher 收敛，
因此本变更以净删除方式恢复“Harness 提供真实约束、agent 保留策略自由”的边界。

## What Changes

- **BREAKING**：废弃 turn-local `AgentTurnRecoveryObligation`、typed settlement matcher、
  response rejection 与 `agent_turn_recovery_unresolved` fatal gate；`no_effect` /
  `terminal_known` 的普通失败只作为结构化 ToolResult 返回，不能自动改变 task 或把
  source signal 判为系统失败。
- **BREAKING**：退出 `failure.recovery.record`、
  `failure_recovery_disposition@1`、condition reconciler 与
  `RECOVERY_REQUIRED` signal 的活跃运行路径。task dependency 已由 canonical task graph
  表达，不再建立第二套 condition subscription。
- **BREAKING**：删除没有不可替代消费者的 durable
  `failure.hypothesis.record` 控制面；agent 诊断继续使用普通 task、protocol、memory 与
  immutable tool/failure evidence。
- 删除 composition-injected AOX assistant-response veto 和策略型 handoff/close
  强制；domain command 仍在 mutation 前校验权限、effect 与必要业务前置条件，最终
  acceptance verifier 仍拒绝不完整产品状态。
- 所有 live、supervisor、evidence 与 reconstruction 消费同一 canonical scientific
  lifecycle/readiness evaluation，不得根据 mutable base row 或局部枚举重新推导旧真相。
- 审计 Lane 与 single-process runtime 的实际价值：首先从 failure/settlement/signal
  等 occurrence identity 中删除重复 Lane 约束；若没有真实并发 worktree 隔离消费者，
  后续直接移除 Lane tool/entity/API，而不是继续把可选 workspace metadata 扩散到每层。
- 保留 unknown external effect、authority、permission、fencing、integrity、provenance、
  secret 与 mutation atomicity 的 fail-closed 边界。
- 本变更明确 supersede
  `make-turn-recovery-semantically-complete` 的“每个可恢复失败必须同 turn 精确结算”
  前提；不得执行该变更剩余的真实 MICU 任务。
- 本变更同时只 supersede
  `harden-compaction-authority-and-runtime-recovery` 中的 turn-recovery
  obligation/settlement/response-rejection 部分；其 authority-free compaction 与 bounded
  no-wakeup diagnostic 保持有效。

## Capabilities

### New Capabilities

- `minimal-harness-control-boundary`: 定义普通 tool/domain rejection、turn completion、
  business task state 与 boundary-fatal ownership loss 的最小正交语义。

### Modified Capabilities

- `runtime-continuation`: 删除 failure-disposition condition subscription 与
  `RECOVERY_REQUIRED` continuation，恢复仅由真实 user/task/protocol/approval/engine
  事件驱动的 runtime wakeup。
- `live-attempt-supervision`: supervisor 直接消费 canonical lifecycle 与根因链，不再用
  catch-all 状态覆盖已经存在的内层错误。
- `scientific-attempt-terminal-rollover`: AOX/scientific close 不再依赖对普通 assistant
  response 的 composition veto；未满足 closure 的状态保持 nonterminal，而不是杀死
  agent turn。

## Impact

- Core/domain/runtime：`harness.py`、failure domain/repository/tools、scheduler/runtime、
  signal reason、migration compatibility 与相关 projection。
- Host/AOX：composition hooks、cutover/closure-stage tool policy、runtime observation、
  lifecycle/readiness consumer、supervision/evidence reducer。
- Public surface：移除内部 bookkeeping tools；历史 failure/disposition/hypothesis 数据只作
  兼容读取，不授权新运行路径。
- Tests/docs：删除按 r60/r61 已知轨迹编码的 exact-settlement 测试，改为“任意已知无副作用
  错误序列不得造成 boundary fatal”的性质回归；同步主架构文档与 `docs/v3/`。
- 复杂度约束：本变更生产代码必须净删除，不得以新增状态表、状态枚举、phase router 或
  generic recovery abstraction 替代被删除机制。
