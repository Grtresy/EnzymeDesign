# Failure observation、显式拒绝与 scientific attempt

## 1. 当前稳定结论

OpenZyme 的 harness 负责忠实、结构化、低摩擦地呈现真实约束；它不替 agent
选择科学策略，也不把任意失败机械地提升为业务终态。稳定语义如下：

- 普通 validation、tool、adapter 或本地 engine 失败，在 external effect 已知时返回
  LLM 可读的失败结果；同一 bounded turn 仍可继续。
- fencing、lease/authority、permission、budget、integrity、process cancellation 和
  `dispatch_in_doubt` 保持 fail closed，必须先恢复 authority 或完成 reconciliation。
- tool、turn、signal、continuation 或 Host finalizer 失败都不自动写 task
  `completed`、`blocked`、`failed` 或 `cancelled`。
- agent 可以修复、改道、请求帮助，或显式调用 `task.finish` 说“不”。需要
  user/operator/authority/harness 修复时用 `blocked`；只有 objective 本身确知不可能时才用
  `failed`。
- provider/driver 使 agent 根本无法作出决定时，Host 只发布 system-attributed
  diagnostic，并明确 `agent_decision_produced=false`；不得伪造 agent 回复。

## 2. FailureObservation

`FailureObservation` 是 immutable canonical fact，绑定可确认的 source、phase、稳定
error code、recoverability、effect certainty、retry eligibility、safe facts、规则化
likely causes、evidence refs 与 actor identity。session/task/agent/lane 只在事实确实属于
该 scope 时绑定；session-scoped provenance 允许 `lane_id=None`。private exception 只保留
不可逆 digest，不能进入 public projection。

`failure.get` 是唯一 active failure tool。agent hypothesis、rationale 或下一步策略保留在
模型 reasoning、普通 protocol/memory 文本或用户回复中，不再写入独立
`FailureHypothesis` / `FailureRecoveryDisposition` control-plane row。历史 migration
`034`/`036` 及其表只为打开旧 SQLite 保留；runtime/repository/tool/projection 不再使用它们。

## 3. Runtime failure delivery

ordinary failed tool result 成功交给 agent 后，不另造重复 wakeup；Harness 将它作为下一轮
tool observation 继续 bounded loop。normal dispatch、context normalization rejection、
parallel overflow 与 interrupted call 的每个 `ToolResult` 只进入一次 accounting boundary。
`no_effect|terminal_known` 表示安全事实已经闭合，不需要第二个 obligation 或“恢复证明”。

agent 可自由选择 corrected retry、verified replan、read、help/authority request、prose、
explicit terminal task action 或 durable suspension；Harness 不改写参数、不自动
retry/delegate，也不拒绝 narration。`COMPLETED` 只表示 turn 正常结束，
`MAX_STEPS_EXCEEDED` 只表示 bounded budget 用尽；二者都不改变 task。provider/driver
不可运行、unknown effect、fencing、authority、integrity、permission 与 process
cancellation 仍停止对应 ownership。

若 continuation 或 controlled execution 的结果只在原 turn 之后可见，runtime 使用现有
source-bound `ENGINE_COMPLETED` signal，并在 claim 时从 canonical repository 重建
result/failure facts。Host scientific finalizer 的 admitted attempt、immutable closure
与 nonretryable failure 共用 source-bound `MANUAL_RESUME` 和 canonical wake-facts
projector；projector 直接解析 canonical record identity，不匹配字符串 prefix，也不写新的
workflow state。facts 在 fresh prompt 中先于 task prose；invalid binding 在 provider
前 fail closed。两类路径都不使用 `RECOVERY_REQUIRED` reason，也不从 ordinary failure
派生 condition subscription。

empty read 与 replay 使用显式 convergence semantics：`task.get` not-found 和 `task.next`
no-ready-work 是 successful closed observation；exact `task.finish` / source-bound execution
start replay 只有在 canonical identity 与 postcondition 相等时 already-satisfied，conflict
继续失败。`WAITING_APPROVAL` 只来自 successful terminal `runtime_suspended` 与可重读的
durable approval id，runtime 要求 status 与 id 双向一致。

blocked dependency 只由 canonical `Task.blocked_by` 表达。`task.delegate` 对 open dependency
返回 LLM-readable no-effect facts，但不写 disposition、不订阅 condition、不排队 synthetic
wakeup。未来 user/task/protocol/approval/engine/continuation 等真实事件若产生 signal，
agent 再读取最新状态并自主决定。

step-budget exhaustion 使用 canonical `agent_turn_budget_exhausted` observation。exact
signal/turn 以 `retry_eligibility=terminal` 结束且不会原地 replay 或增加 budget；task
status 与业务 failure fields 保持原样。Core 的 `AgentRuntimeOutcomeSettlement` 只固化
signal occurrence、bounded batch barrier 与可验证的 budget handoff，不承担 ordinary
tool-failure recovery proof。Host 不得在 lease 释放后从 mutable read model重建更“成功”的
receipt。

任一 master 或 teammate max-step outcome 都是当前 bounded batch barrier。scheduler 允许
已经 claim 的 wave 完成，然后停止新 claim；即使 `max_signals > 1`，该 occurrence 新建的
successor 也必须等下一条 command/background tick。后续 task 或 successor 状态变化不会
反向改写 immutable occurrence settlement。task business exit 与 scheduler settlement 正交。

manual runtime drain 在 scheduler batch 后先形成 immutable
`RuntimeDrainCoreReceipt`，再独立结算 trace/activity/consistency/event/workspace
projection。`runtime_command_outcome@2` 同时保存 scheduler 与 projection 两层状态；若
post-core projection 失败，真实 processed count、suspension 和 output/event identities 仍保留，
且只要 count 大于零就固定 `replay_safe=false`。只有 core receipt 尚未形成的 boundary
exception 才能报告 count `0`；旧 `@1` receipt 只读，不回填推导值。Host core receipt
直接聚合 Core typed settlement，不做 typed-to-dict-to-classifier 往返，不依赖对象 identity，
也不重扫 mutable signal/task/failure/agent/wakeup repository。

AOX bounded consumer 只接受经 validator 验证的 v2 command outcome。连续两个 outcome
必须同时满足 `processed_signal_count=0`、`replay_safe=true`、canonical work fingerprint
一致，并证明 pending/claimed signal、pending approval、active invocation/continuation、working agent 与
mutation writer 均不存在，才是 no-wakeup stall。ready unfinished work 若仍绑定 actionable
failure，返回 `formal_agent_recovery_unresolved`；否则返回
`formal_runtime_stalled_no_wakeup`。fingerprint 排除 timestamp、lease/fence、event/cursor
和 command id，单次 empty 或任一 semantic/wakeup progress 都重置确认；该 diagnostic 不
auto-enqueue 或创造 recovery work。前一个 error code 是历史 AOX diagnostic 名称，只表示
ready work 仍关联 failure facts，不表示存在 turn recovery obligation。

同一个 provider response 中的多个 tool call 作为有序 batch 结算。若某个已 dispatch call
触发 explicit `runtime_suspended` approval、成功的 `task.finish` /
`attempt.create` / `scientific.attempt.close` terminal action或 boundary-fatal failure，harness
停止 dispatch 余下 call，但不能让它们消失：后续 eligible call 记录
`tool_call_batch_interrupted/no_effect/verify_then_retry`，overflow call 记录
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`。causal call 若已跨过外部
dispatch boundary，则保留原始 effect certainty 和 retry eligibility；
`dispatch_in_doubt/reconcile_required` 绝不能被后续批次收尾覆盖成 `no_effect`。这些
observations 是事实与 effect/retry 边界，不是 retry authority；agent 必须在新 turn 中先检查
durable state，再决定是否重发、改道、reconcile 或请求帮助。

批次结算也不能把 pre-batch snapshot 当成所有调用的验证真相。eligible call 的 task/lane
引用在各自 dispatch 前依次解析，使前序 create/bind 的 durable effect 对后续调用可见；
never-dispatched call 的 no-effect observation 则保留原始引用，不为获得 metadata 而
提前验证未来对象。

### Recoverable controlled-operation owner handoff

AOX session observation 从 canonical operation、唯一 execution、continuation、
scientific-attempt binding 与 exact `FailureObservation` 生成一份 bounded operation facts
projection。每项明确标记 `probe|formal` scope，并携带 operation/task/lane/sandbox、
attempt、execution、continuation 与 exact failure ref；total count、canonical digest 与
truncation state 由 runtime observation、diagnostic raw facts 和 failure evidence 共用。
probe attestation 仍是独立证明，但 failure operation list 必须与 formal projection 合并，
不能用成功 probe 子集替代完整 formal occurrence。

failed observation 默认立即结束 supervision。只有同时满足下列 exact facts，driver 才可
在本地记住 source，并额外执行一次 later bounded drain：

- 当前 formal attempt 中恰有一个同源 terminal
  operation/execution/continuation，typed cause 为
  `controlled_effect/agent_can_replan/no_effect/terminal`；
- continuation 已 delivered，且 exact `FailureObservation`、attempt binding、
  task/lane/agent/source/correlation 全部一致；
- owner task 仍是 `todo|in_progress` 且 assignment 未漂移；
- 整个 session 恰有一个 pending、unclaimed、`attempt_count=0` 的
  `engine_completed` owner signal，并且没有 pending approval、active invocation、
  nonterminal execution/continuation 或其他 runtime signal。

该例外只让已经排队的 owner wake 获得一次 agent turn；它不创建 signal、task、
operation、attempt、approval 或 authority，不 retry/replay failed effect，也不规定 agent
策略。source 不能再次使用。缺失、重复、claimed、cancelled、已消费、跨 identity、
retryable、unknown effect、`dispatch_in_doubt`、nonterminal 或 authority/attempt drift
全部返回原 failed observation，不再 drain。

## 4. Fresh scientific-attempt authority

每个 formal scientific attempt 必须先有 durable
`ScientificAttemptAuthorization` envelope。envelope 固定 grantor、session/task、campaign、
workflow、root、scope、effect classes、provider/HPC target allowlist、最大 attempt 数、
MICU/cost/wall-time ceiling、expiry、policy digest 与 idempotency identity。

新 attempt 还必须按 `workflow_id + workflow_contract_digest` 精确解析一个 active
`ScientificWorkflowContract`。canonical preimage 覆盖 contract/schema id、scope、合法
workflow roles、每个 role 的 closed `sdk_module + function_name` signatures、cardinality、
effect/adoption policy 与 same-attempt reuse policy。validator、inspection/readiness 与
bundle verifier 都消费这个 registry object；unknown digest、近似版本或 historical-only
contract 不得 fallback 到 prompt、静态 enum 或 Host 私有 callable。

agent 的 `attempt.create` 只写 admission request。successful ToolResult 标记
`terminal_action="attempt.create"` 与 `terminates_turn=true`，作为非业务终态 bounded
handoff 立即结束当前 writer turn；它不要求 agent 同轮再叙述、inspect 或
`task.finish`。writer 退休后，Host finalizer 才在新的短 authority slice 中原子校验和消费
envelope、打开 attempt scope，再以 exact attempt id 唤醒原 agent。fresh prompt 的
canonical admission facts明确 attempt 已提交、request/envelope/session/task/lane/campaign/
workflow/scope/effect/resource identity 与当前 lifecycle，避免模型从旧 task prose重复
`attempt.create`。这样不会让同一 writer 既申请又自批 authority。非 retryable finalizer
拒绝必须生成 system-attributed `FailureObservation` 并以 exact failure id 返回
responsible agent；不得静默吞掉或自动重放。

successful admission/closure request 不是 ordinary teammate completion：runtime 不为该
result 预先排 generic `agent:master` successor。requesting writer 退休后，Host finalizer
在 transition transaction 中创建的 exact source-bound owner wake 是唯一 successor。
该 wake 可以属于 master 或 teammate，两条模型路径都接收同一 bounded canonical facts；
master 使用 ephemeral system context，facts 不成为 conversation message。

canonical wake-facts projector 对 admission、closure 与 failure 采用相同 closed binding：
claimed signal 的 source/correlation/session/task/lane/agent 必须与 canonical records 和
当前 task assignee 一致；attempt/request、closure/request/lifecycle graph 也必须一致。
durable transition event 已存在但 canonical record 缺失属于 orphan transition，必须
fail closed。projector 只提供事实与 effect/retry 边界，不输出 recommended action；
failure projection 保留 exact source/error/effect/retry identity，但 optional facts 与
evidence refs 使用 deterministic prefix、total count、canonical digest 和 truncation
marker；整个 prompt context 有硬界。agent 仍可自主选择继续 attempt、修复、改道、
reconcile、请求 authority 或显式结束 task。

AOX observer 若看到 owner-authored terminal `task.finish`，应从 immutable finish document
的 `failure_ref` 解析 exact `FailureObservation`，而不是依赖仅在 `failed` row 上复制的
task failure fields。outer `task_blocked` / `task_failed` 是 wrapper；sealed diagnostic 与
failure evidence 的首要 blocker 使用最早 typed error code，同时保留 wrapper、cause 的
recoverability/effect certainty/retry eligibility 和真实 completed/blocked/todo task
projection。current-exit projection 允许同一 task 在 resume 前保留多个历史 exact
`task_finish`，只选择与当前 status/assignee 匹配的最新 causal exit；同一 causal time
出现非等价 current binding 时以 `task_finish_current_binding_ambiguous` fail closed。
recovered historical exit 不重新成为 actionable cause。operation、current task 与 sandbox
候选按解析到 UTC 的 causal timestamp 排序，再用 stable identity 打破同刻平局，不按
repository/category 顺序。observation 与 failure evidence 共用这份 bounded task facts；
task/evidence 总数、digest、truncation 明示，不再二次读取 task board。非 eligible
evidence可以记录未终态 task，但绝不能因此获得 cutover eligibility。

AOX formal runtime barrier 不能用一个跨 session drive 的长期 outer writer 包住上述
rollover，否则 pre-attempt scope 永远无法证明 writer 已退休。campaign driver 在每次
barrier snapshot 前，必须只在当前唯一 open scope 上登记一个 root
`aox-attempt-driver:<outer-attempt-id>:formal` observer writer；barrier 读取期间只排除
这个 exact writer，并继续统计所有其他 root/child writer。snapshot 返回或失败后
observer 立即退休，不能跨 runtime drain、admission/closure finalizer、provider/HPC
dispatch 或 approval wait。缺 scope、多 scope、observer identity 缺失或 retirement
失败均 fail closed，不能解释成 idle 或 quiescent。

完整 session observation 与 terminal runtime command 的 attached-writer settlement 都会
读取该 barrier，因此必须走同一个 bounded observer context。drain coordinator 显式传递
`purpose + attempt_authority`，不得在 formal 路径直接调用 writer-only projection。
observer 必须早于 sleep、下一次 compact approval read、下一次 drain、return 或 error
propagation 退休。

terminal runtime command 可以先于 closure finalizer 完成。此时 exact attempt scope
可能已提交 `freezing|quiescent`，writer admission 按设计关闭，而 post-attempt scope
尚未 open。`MutationWriterTurnFactory` 的
`mutation_writer_admission_closed` 在这里不是 observer identity 损坏。driver 仅当
formal authority envelope 精确解析到唯一 attempt、该 exact attempt scope 为
`freezing|quiescent|sealed`、session 为 zero open 且没有 competing nonterminal scope
时，在当前 command 原 deadline 内等待 rollover 后重新形成短 observer barrier。它不
admit 新 drain、不重开 scope、不重试 agent/tool；超时 typed fail
`scientific_attempt_scope_rollover_stalled`。parent mismatch、缺失/多重 attempt、
任意 open/竞争 scope 仍立即保留原 fail-closed error。

AOX 使用更窄的 `aox_live_attempt_authority_plan@1`：

- plan 精确包含 `positive, positive, fault` 三个槽；
- 每槽绑定预声明 attempt/session/task/lane/root、exact operator grantor、同一 identity 和
  qualification、`max_attempts=1`、effect/route/resource/expiry policy；
- `run-live` 只能把 plan 消费到 deterministic sibling
  `<plan-name>.consumed.json`，并且必须在创建任何 attempt root 前通过 atomic no-replace
  完成一次性消费；current receipt 是
  `aox_live_attempt_authority_consumption@2`，显式绑定
  `run_class=formal_acceptance`、formal plan schema/digest 与 sibling filename；
- 复制 plan 文件不能获得新的 campaign authority；当前信任边界要求 operator 保护原 plan
  与其 deterministic consumption sibling，并以 durable in-attempt envelope 证明每槽消费。

## 5. Full occurrence universe 与 selected chain

scientific attempt 允许中间路径试错，但不允许隐藏历史。Host 从 exact attempt scope 导出全部
controlled-operation 和 covered sandbox-run occurrence，计算 digest-bound universe。selection
head 只保存 current selection 的 CAS pointer/revision；读取 lifecycle 必须用 repository
`resolve_head()` 联读 canonical `ScientificChainSelection`，不能在 head 上复制或猜测
`state`。agent 显式创建 CAS-protected selection revision，并为每个 occurrence 给出且只给出
一个 disposition：

- `adopted`：进入唯一 selected workflow chain；
- `superseded`：保留事实并指向 replacement/adopted role；
- `failed`：绑定 terminal known failure；
- `abandoned`：仅限 no-effect，或已 reconciliation、已退休且不会再活动的 occurrence。

对 active contract，`adopted` 不能通过 generic disposition 单独写入。agent 调用一次
`scientific.operation.adopt`，显式提供 exact selection/operation/workflow role/reason/
idempotency key；Host 在同一个 repository transaction 和 mutation-writer turn 中校验 current
draft head、universe、terminal-known result/approval/effect 与 contract signature，同时写入
adopted disposition 和 matching `ScientificEffectAdoption`。两条 row 共享 request digest；
exact replay 返回原 identities，单边或 digest 不一致 replay 是 integrity conflict，整笔不
修补。历史 split-record adoption 只读保留。

纯读取 `ScientificSelectionEvaluator` 从 resolved head、完整 universe、contract、
dispositions/adoptions/materializations、executions/results 和 authority/ownership 计算稳定
issues、bounded gap summary 与 `seal_ready`。seal、closure revalidation、详细
`scientific.attempt.inspect` 和 workspace summary 都消费同一 evaluation；公开 detail 只分页
投影 safe operation signatures、allowed/compatible roles 与 blocker codes，不含 Host
locator、lease/fence、credentials 或 recommended actions。`seal_ready` 不是自动 seal 或 task
terminal authority。readiness 同时区分 `closure_request_ready` 与
`closure_finalization_ready`：前者要求 current selection 已 sealed 且满足 request-time
selection evidence，后者还要求 active writers 已退休。legacy `closure_ready` 保留为
`host_finalization_after_request` 阶段的兼容字段；请求 closure 的 agent turn 本身是 expected
writer，不能因为 `selection_active_writers` 而等待另一个 turn 才表达 intent。

同一个 formal attempt 内可以跨 sandbox run 采用已完成 operation，并由 Host 通过 artifact
catalog grant、digest 和 target authority 物化其 bytes。跨 formal attempt、campaign、
positive/probe/fault 的 effect、operation、materialization、browser receipt 或 scientific bytes
不得采用。相同 provider 内容 bytes 可以独立出现，但 execution/effect identity 必须 fresh。

`dispatch_in_doubt`、未知 effect、活动 process/writer、未退休 continuation、authorization/cost
breach 或不完整 universe 不能靠 disposition 消失；selection seal 必须拒绝。

## 6. Closure 与 task 独立

`scientific.attempt.close` 先写 closure intent，并立即禁止该 attempt 继续绑定 run、
operation 或新 selection revision。agent writer 退休后，Host：

1. freeze exact mutation scope；
2. 获取同 generation 的 quiescence receipt；
3. 重算 universe、dispositions、adoptions、materializations、authorization consumption 与
   unresolved effect；
4. 验证 selected workflow roles 和 lineage；
5. 写 immutable closure。

base `ScientificAttempt.status` 是 admission snapshot（对读模型显式称为
`record_status`），finalizer 不更新它。Core 的唯一 lifecycle resolver 联读三个
canonical immutable record，派生：

- `open`：没有 request/closure，且 record active；允许 scientific mutation；
- `closure_requested`：有 exact request、尚无 closure；effective status 为 `closing`，
  不再允许 mutation；
- `closed`：request 与 exact closure 的 attempt/request/selection identity 全部一致；
  effective status 为 `closed`，不受 base row 仍为 `active` 影响；
- `blocked`：没有 terminal evidence 且 record blocked；不允许 mutation。

request/closure 缺失、跨 attempt、request identity、selection identity 或 record-status
冲突统一返回 `scientific_attempt_lifecycle_invalid`。inspection/readiness、
workspace/world projection、agent recovery、runtime consistency、mutation admission、
AOX approval/terminal observation 与 evidence export 必须使用同一 resolved object；
任何一个业务消费者都不能从裸 `attempt.status` 自行推导 closure。

成功写入 intent 的 close result 必须携带
`terminal_action="scientific.attempt.close"` 与 `terminates_turn=true`。harness 不把该
result 再喂给模型；同批后续 call 全部以
`tool_call_batch_interrupted/no_effect/verify_then_retry` 持久结算而不 dispatch。该
settlement 仍属于 requesting `AGENT_TURN` writer；writer 退出前 final closure 必须不存在。
close validation/readiness 失败则保持 non-terminal，允许 agent 读取 blocker 后修正。

上述 final transition 必须是一个短本地 write transaction：attempt scope seal、closure row
与唯一 post-attempt session scope open 对并发 reader 原子可见。此前 generic quiescence
会先提交 attempt scope 的 `freezing`，关闭新 writer admission 并等待已登记 writer 退休；
这段状态是显式 bounded coordination，不是“缺 scope”。runtime barrier 可以看到 open
attempt scope、admission-closed `freezing|quiescent` scope，或 final transaction 后的
open post-attempt scope；它不能把中间两种状态伪装成 ready，也不能把它们当成永久 identity
损坏。真正 missing/ambiguous scope 仍 fail closed，driver 只在当前 terminal command
deadline 内识别 exact rollover，不以新 drain 或 blind retry 掩盖 non-atomic finalizer。
实现上由 `ScientificAttemptService.finalize_closure_request()` 自身打开 Core transaction
并在事务内重新读取 immutable request/attempt/selection/quiescence；因此 direct Host
endpoint、pending finalizer 与任意后续 Core caller 都不能绕开 final rollover 原子性。
规范 post scope 使用 deterministic id/ref，已有 child 必须唯一且身份完全一致；并发
finalizer 只能 replay 同一 closure。

任何 session-scoped observer admission 都先在一个 atomic writer-admission transaction
中完成 scope cardinality、parent、registration 与 authority。Core rollover projector
随后消费完整 authority envelope，而不是 AOX 自己重建部分状态；它的合法投影只有：

- `rollover_pending`：exact lifecycle 为 `closure_requested`，attempt scope 为
  `freezing|quiescent|sealed`，open scope 为零且没有 child/competitor；
- `post_closure_scope_open`：exact lifecycle 为 `closed`，attempt scope 已 `sealed`，
  且恰有一个 deterministic id/ref/parent 的 open `session` child。

original admission 必须是 typed `zero_open_scope` 或
`scope_closed_during_registration` 才可进入该 projector；
`ambiguous_open_scopes`、binding drift、错误 parent/kind/ref、lifecycle/scope mismatch
立即 fail closed。这样 observer 抛出 admission error 后即使 finalizer 已提交，classifier
读取 committed 后态也能在原 deadline 内重建一次短 barrier，而不是把正确 post scope
误报成 identity failure。

process-isolated attempt supervision 与该产品投影是两个独立证明。current
`aox_live_attempt_supervision@3` 不再把“全局 nonterminal scope 数为零”命名成
quiescence；child 在 result 落盘后投影 bounded mutation-authority rows，要求 active
writer 为零并同步 SQLite/root，随后发出 `local_state_settled`。writer-free 的合法 open
post scope 会进入 snapshot/count，但不会阻止本地 settlement。parent 必须等 exact
process group 为空后 read-only 重算相同 snapshot digest，之后才读取 child result 并签发
`aox_live_attempt_supervision_receipt@3`。terminal scientific evidence 只有同时具备
上述 process receipt 与 Core `post_closure_scope_open` projection 才可接受：前者不能证明
scope id/ref/parent/kind/lifecycle，后者也不能证明 child/descendant 已退休。历史
supervision/receipt `@1/@2` 只能由显式 offline path 原样验证，current bundle 不做
lossy down-projection。

Host 的两个 scientific transition 调用面共用一条 delivery settlement：canonical
transition、deterministic public event、以及对原 agent 的 source-bound
`MANUAL_RESUME` signal 在包含 Core transition 的同一 write transaction 内提交，notifier
只在 commit 后触发。pending scan 必须处理“transition 已存在但 event/signal 缺失”的旧崩溃
状态，并以 record/event/source identity 补齐一次；terminal signal 不重开。这样既没有
scope gap，也没有 closure commit 后 agent 永久失联的第二条 crash seam。

closure notification 被 claim 后先核对 signal kind/source/correlation、requesting actor、
session/task/lane、attempt/request/closure 与 derived `closed` lifecycle。task 仍
business-nonterminal 时，runtime 沿普通 claimed-signal model path 唤醒 canonical
assignee；task 已 terminal 时复用 generic stale-task mechanical completion。两条路径都受
原 claim lease/fence 保护，不追加 closure-bound assistant response，不创建
closure/response/report/signal，也不发 scientific-specific settled event。普通
resume、admission 或 attempt notification 保持既有行为；closure-like binding 缺失或漂移
在 model 前 fail closed。

quiescence 只证明“不会再变”，selection 只证明“采用什么”，两者互不替代。closed attempt 是
agent 可消费的 evidence，不是 `task.finish`；canonical task assignee 仍需显式决定完成、
继续、blocked 或 failed。对 bound attempt 调用 `task.finish(status=completed)` 时，
Core 要求至少一个 immutable closed attempt 且不存在 open/closure-requested attempt；
closure 前完成以 `scientific_attempt_task_not_closed` no-effect error 拒绝，非 completed
显式出口保持普通 task 语义。
只有 final closure id 才能形成 `scientific_closure:<closure_id>` evidence ref；closure request
不能被 runtime 替换成该证据。`task.finish.evidence_refs` 的 schema 与 invalid-result details
共同暴露 closed `<kind>:<id>` format，repository 仍负责当前 session 解析。

## 7. AOX evidence migration

新的 AOX production collector 只生成 `aox_blank_world_attempt_bundle@3`。`@3` 在保留原有
科学、artifact、public API、browser、MICU 和 fault 验收门槛的同时，增加：

- exact authorization envelope/consumption；
- full controlled-operation universe 与每个 occurrence disposition；
- unique selected workflow roles；
- same-attempt adoption/materialization lineage；
- sealed selection、quiescence 和 closure；
- unknown-effect、writer/process、cross-attempt reuse 与 tamper rejection。

历史 `aox_blank_world_attempt_bundle@2` verifier 保留为只读历史入口。旧 bundle 不得升级、
回填 selection、与 `@3` row 混合或被新 campaign 采用。r48-r59 永久保持 NO-GO；
对应 authority、root、effect、provider job、artifact、browser evidence 和 scientific
bytes 均不得复用。r53 的 probe scope 已密封，但 formal pre-attempt scope 因旧 driver
缺少 exact barrier observer writer 而保持 open；parent fatal 只证明进程退休，不声明
SQLite/quiescence/artifact closure，也没有 eligible attempt bundle。

post-r53 的第一次纠正 commit `6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8`
只覆盖完整 session observation；非-live 真实 SQLite 审计随后发现 terminal-command
writer settlement 仍绕过 observer lifecycle，既有测试桩没有暴露该缺口。当前纠正统一
两个 formal 消费面，并验证其他 root/child writer 仍可见、observer 均退休且 pre-attempt
scope 可密封。所有绑定旧纠正 commit 的未消费后继计划均已过时；本次工作不启动新的
numbered live attempt。

r54 已产生 canonical scientific I/O 和六项 terminal formal controlled-operation 成功事实，
但 selection 仍是 draft，disposition/adoption、seal、attempt close、eligible report 与 campaign
reducer 都未闭合；operation success 因此不等于 attempt/report/campaign success。旧
`aox_blank_world_selected_chain@1` digest 没有覆盖 Host 实际执行的
role-to-operation signature map，inspection 也没有把 compatible roles/readiness gaps 给
agent；executor 在错误的两步 adoption 顺序与错误 role 后耗尽 step budget。随后 consistency
projection 错读 `ScientificSelectionHead.state`，又把 scheduler 已处理的一个 signal 错报为
零进度 runtime command failure。

r54 的数据库、root、contract `@1` preimage/digest、operation/effect、bundle/decision/ledger
全部 immutable/read-only，绝不原地升级。新 AOX attempt 只接受
`aox_blank_world_selected_chain@2`，其 digest 覆盖 formal/fault/probe roles 到 closed SDK
signatures；active `aox_blank_world_runtime_config@3` 把 exact `@2` identity 封入
`config_digest`，新 `@3` bundle verifier 拒绝历史 config/contract crossgrade。该 correction
只提供未来 attempt 的可观察 contract、统一 evaluator、原子 adoption、resolved head 与真实
runtime receipt，不继续 r54。

r55 在 formal operation 前暴露 max-step handoff 的 scheduler receipt 分类缺口；r56 已跨过
该缺口，完成 probe、Chrome approval、六项 formal operation、17 deliverables、sealed
selection 与 scientific-attempt closure，却在 report 形成前撞上新的 scope rollover 缺口。
r56 attempt scope 的 sealed commit 与 post-attempt scope 的 open commit 相隔约 144 ms；
并发 AOX barrier 在其中观察到零 open scope，以
`mutation_driver_writer_identity_invalid` 终止。post scope 与已退休 Host finalizer writer
随后出现，证明这是 non-transactional transition，而不是科学、provider 或 HPC 失败。
r56 无 report、final browser observation 或 eligible `@3` bundle；parent fatal 也不声明
ledger-after/SQLite/artifact/quiescence closure，因此 r56 不能成为 positive slot。

## 8. Diagnostic live 与 formal acceptance 分离

r56 触发后，AOX target contract 先将 live execution 分为两个不可互换的类别：

- **diagnostic live run**：单 positive-shaped、独立 one-use authority 与独立
  root/consumption/decision schema；可在精确权限内走真实 LLM/provider/HPC/approval/browser，
  但固定 `acceptance_eligible=false`，不生成 `aox_blank_world_attempt_bundle@3`，不进入
  GO reducer；
- **formal acceptance campaign**：继续精确消费 `positive, positive, fault` 三个 slot，
  只有它可生成 `@3` bundle 与 campaign decision，原 GO 门槛不变。

两类 authority validator、consumption receipt、root namespace 与 output schema 必须 closed
且互斥。diagnostic 的 operation/effect/artifact/report/browser receipt/bytes 即使与 formal
内容 digest 相同也不得 adoption、copy、upgrade 或参与 reducer。formal attempt 仍需 fresh
authority、blank roots 与全部真实 effect。

该拆分现已作为显式命令和闭集 schema 落地。`authorize-diagnostic` 生成
`aox_diagnostic_attempt_authority_plan@1` 的唯一单槽；`run-diagnostic-live` 只消费
`aox_diagnostic_attempt_authority_consumption@1`，创建 plan-bound
`aox-diagnostic-*` root marker / `aox_diagnostic_root_proof@1`，并只封存 append-only
`aox_blank_world_diagnostic_decision@1`。`AoxLiveRunClass` 驱动共享的单-attempt
execution core，正式与诊断 runner 不复制 product path；collector 边界则完全分离：
formal 独占 selected-chain `@3` builder/reducer，diagnostic 对所有嵌套
`acceptance_eligible|cutover_eligible` 强制 false，只投影 completed/blocker、计数与 digest。

r59 之后曾增加 `closure_stage_diagnostic` 作为第三个 schema-disjoint 类别，而不是上述
full-path diagnostic 的参数模式。它当时只能以只读 immutable source qualifier 限定 r59
cursor 614 cut，在 fresh current-schema、非 `rNN` root 重建 execution handoff 前的等价
状态；不重跑、采用或物化 source scientific effect。其 authority/consumption/source/
reconstruction/parity/live/decision schema、MICU scenario 与 root namespace 当时均与前
两类互斥，并永久 `acceptance_eligible=false`。r65 已删除该类别的 production authority、
source qualifier、reconstruction、live driver、CLI 与 runnable tests；只保留 historical
SQLite/evidence 兼容和 formal non-adoption gate，不存在 current collector、bundle、
reducer、promotion、operator endpoint 或 numbered continuation。

full-path diagnostic 与 formal 的 closed validator、publisher、consumer、slot identity、
root namespace/ancestor marker、collector 与 verifier 仍有 cross-mode negative 回归；
即使删除 diagnostic run-class 字段或把 plan digest 伪造成与 formal 相同，也会在
root/effect 前失败。architecture qualification 的
`evidence-projection.aox-run-class-disjoint-closure` 现在只以 raw historical literals 和
file-backed SQLite compatibility 证明 closure-stage evidence 永远不能进入 formal
acceptance，并记录零真实外部 effect，不加载已删除的 production modules。实现和非 live
gate 通过不授权真实 diagnostic；full-path diagnostic plan 与后续 formal exact-three plan
仍必须分别取得 operator 精确批准，普通失败的 `run-live` 也永远不能事后改称 diagnostic。

## 9. r57 后的 formal tool precondition

r57 是第一轮真实 diagnostic-mode attempt。其 run-class 隔离正确，但在 exact-six probe
和 exact-seven formal operation 完成后，executor 将 representative-only candidate FASTA
与 full CD-HIT membership 绑定，得到正确的
`candidate_membership_set_mismatch`。同时 master 在 canonical 三项 task 之外创建 suffixed
report task，并在 execution/report 未业务终结、零 report 时请求 attempt close，随后耗尽
turn budget。该轮没有 fully settled diagnostic receipt，永久 NO-GO 且不可复用。

forward correction 不把 report/task/conversation 状态并入 scientific-attempt 真状态，也
不让 Host 推断业务终态。historical AOX precondition `@1`–`@4` 曾复制 exact board、
master close、report publication 与 response handoff；Phase 2 `@5` 删除这些共终止 veto，
r65 current `aox_cutover_formal_tool_precondition@6` 在其基础上保留：

- `task.create` 的显式 id 与 kind 必须属于 authority-bound canonical
  research/execution/report 闭集；
- scientific operation 必须属于 exact session-scoped allowed universe；
- report publication 仍必须满足 source-link guard。
- attempt close、execution completed 与 report handoff 必须通过 exact persisted
  source-bound final-deliverable validation receipt。

scientific closure 的唯一 lifecycle owner 是 `ScientificAttempt.task_id` 当前
`assigned_ref`。Core 在 closure request 和 Host finalization 两处验证该 assignee，同时
保持 selection、operation、authority、provenance、writer 与 quiescence fail-closed
controls。guard 不生成 task/report、不完成 task、不选择 selection/operation 或 retry，
也不应用于 probe/其他 session。generic master recovery finish authority 不变，但
master 代写 researcher/executor/reporter exit 仍不满足 AOX final evidence collector 的
owner-authored receipt 要求。

## 10. r58 historical co-terminal contract 与 Phase 2 supersession

r58 在 clean commit `d00ada97f8eb13af35f9c83247cd51e14138f428` 消费 diagnostic
plan `sha256:691cf17bd8548fa3bfd4e338cb61ce608bb97c4cde17f0e66483b84ff65397e3`。
probe 与 formal exact operations、516 candidates、78 representatives、13,778 edges、
17 outputs、sealed selection、published report 和三个 owner-authored completed task exits
均已形成；但 master 在最后一次 inspect 后发出 assistant-only final response，没有调用
`scientific.attempt.close`。active attempt 保持 open，120 次 drain 后以
`formal_runtime_drain_exhausted` 结束。decision
`sha256:8c877189130838b29030200d9c592e8e096cd028cd60a5c5bc38dd424c718a57`
永久 NO-GO，r58 状态/effect/bytes 不得复用。

当时根因是两个旧合同不相容：assistant-only response 可以成为 conversation truth，但
没有新 signal 让 master close；tool-call response 中即使已有最终文本，successful close
又会立即退休 turn。r58/post-r58 correction 因此曾引入 response veto、master-only
co-terminal close、deterministic conversation binding 和 response digest。那些记录仍是
解释 r58–r62 的 frozen historical contract，migration `035` 和旧 table 也继续可读，但
它们不再是 active product contract。

Phase 2 删除 active closure-response domain/repository/service、ToolInvocation companion
field、conversation transaction 和 scientific-specific settlement。current close
command 只允许 exact attempt-task canonical assignee，且只写 immutable request；
assistant answer、report publication 与 resident-master delivery 完全独立。Host 在
requester writer 退休后 finalization，ordinary source-bound wake 再让 assignee 显式
完成 task。tool guard 不自动关闭 attempt、不推断 selection、不合成答案、不改变
task/report 真状态。

report publication 仍由一个共享派生谓词判断：
`report.status in {ready,published}`、`draft.status=published`、同 session/task、精确
`published_report_id` 与非空 content ref 必须同时成立；policy/projection/collector/
offline verifier 不得各自缩窄。但该 predicate 只服务 report/acceptance，不参与
scientific closure authorization。formal exact-three acceptance 仍需 fresh clean
commit/full admission/pin 与独立精确授权。

### 10.1 r62 failure chain 与 bounded supervision

r62 full-path diagnostic 在 clean commit
`5265c7813c64880c03bef3aee15e552e4f4d1c49` 上产生 13 项 completed controlled
operation、三个 completed canonical task、sealed selection 与 published report，但
executor 的 close 被旧 `aox_cutover_close_actor_violation` 拒绝；master 随后遇到
`aox_cutover_task_identity_not_ready`，写出普通终答而没有 duplicated close。attempt
因此保持 open，124 个 runtime command 中后续空 drain 最终包装为
`formal_runtime_drain_exhausted`，decision 再包装为
`scientific_attempt_control_missing`。zero closure request/response/closure 是该轮的真实
lifecycle fact；consumed authority、root、SQLite、effects 与 failed decision 永久
non-acceptance、不可复用。

current observation 把 formal product readiness 与 exact immutable closure 联读：前者已
满足但 attempt open 时返回 `scientific_attempt_open`。若连续两次 runtime command 都是
`processed_signal_count=0/replay_safe=true`、canonical work fingerprint 相同，且没有
pending/claimed signal、approval、invocation、continuation、working agent 或 in-flight
writer，则 driver 立即以 `scientific_attempt_open_no_wakeup` 终止；已有更早 actionable
typed failure 时仍优先保留该 cause。这个 bounded stop 不创建 synthetic wake、fallback、
task mutation 或 closure。

diagnostic collection 不再因缺 immutable control 丢弃已观察事实：operation/task/report/
lifecycle counts、raw facts、process state 与 measured MICU 保留，decision 仍强制
`acceptance_eligible=false`。formal acceptance 则继续要求 exact
`scientific_attempt_control`。probe execution/check status 与后续 attestation status 分开；
attestation unavailable 不把已证明的 passed check 改写为 failed，未执行 check 记为
`unobserved`。

## 11. r59 后的 positive execution handoff

r59 在 clean commit `431e2c558c13ebd1f99dcc9e3eae6758630a843d` 消费 formal
exact-three plan
`sha256:168aa86c433b3c3b90aab4c665453a56cb796f99056f7d04567bc8f453b8e7de`，
只到达 positive 1。probe exact six 与 formal NCBI/MAFFT/hmmbuild/EBI-HMMER/UniProt/
HMMalign exact six 全部 terminal-known success；formal result 是诚实 healthy empty：
37,772 个 score-filter accession、2,561 个 length target、0 motif candidate，
`no_candidates_after_motif_filter`。executor 已 sealed current selection，reporter 已发布
source-linked report。

executor 随后调用 master-only `scientific.attempt.close`，正确收到
`aox_cutover_close_actor_violation/no_effect/same_phase_safe`，却把预期 handoff 误写成
owner-authored `task.finish(blocked)`。master 不能把已终态 task 改回 completed，也没有
reopen/resume 合同；随后又把 `selection_active_writers` / `closure_ready=false` 当成不能在
当前 turn 请求 intent，最终零 closure request、120 drains exhausted。decision
`sha256:8b05ef13dfaf79f9a15a647fbbafa446e7ef75656b16db77a7b32baa8b4c6ccc`
永久 NO-GO；MICU verified lower bound 为 `100,114,267 / 500,000,000`，全部 r59
authority/root/state/effect/bytes 不可复用。

`aox_cutover_formal_tool_precondition@3/@4` 是 r59 时期的 historical guard。current
policy 是 `aox_cutover_formal_tool_precondition@6`，并以 exact typed finalization
capability 取代“看到 sealed selection/17 paths 就完成或 handoff”的推断：

- `aox_motif_candidate_filter@1` 只消费 canonical target FASTA 与 canonical scoring CSV；
  conditional-empty outputs 只接受 installed source calculation 的 typed zero receipt；
- `artifacts.finalize_bundle` 在 mutation 前读取并验证全部 fixed 17 draft，绑定 formal
  attempt、sealed selection、execution task/agent、sandbox run、source snapshot/tree 与
  installed calculation identities；
- unified live/eval/offline validator 保留完整 errors、canonical digest 和
  `earliest_error_code`；失败时 Artifact 与 EngineDocument 都保持零新增；
- 成功 transaction 原子提交 17 artifacts 与
  `aox_final_deliverable_validation_receipt@1`，persisted verifier 再从 sealed bytes 与
  exact source bindings 重算；
- `aox_final_deliverable_normalization_result@1` 只是 installed normalization
  calculation result，不是 Host validation receipt，也不能用于 terminal gate；
- current attempt-task canonical assignee 调用
  `scientific.attempt.close(finalization_receipt_id=...)`。execution
  `task.finish(completed)` 必须引用 `document:<receipt_id>`；report delegation、publication、
  completion 与 handoff 也必须通过同一 receipt gate，并等待 execution task 已完成。

缺失、跨 attempt/selection/source、artifact/metadata drift 或 arbitrary source-snapshot
implementation substitute 都以 `no_effect/same_phase_safe` 拒绝，不写错误 attempt
closure、execution terminal 或 report handoff。policy 不生成 receipt、不自动完成 task、
不自动委派或发布，也不选择科学路线。

## 12. r59 closure-stage logical fork（历史，已退役）

r59 logical fork 曾以 read-only SQLite source qualifier、fresh reconstruction、sealed
operation universe、production runtime/parity 和 source-linked report 验证历史 closure
链。r65 已删除它的 authority、source qualifier、reconstruction、live driver、CLI 与
dedicated runnable tests；不存在 current operator contract 或 successor。historical
SQLite/migrations 和 sealed `aox_closure_stage_*` evidence 继续只读兼容，formal
non-adoption gate 继续拒绝 raw run class、attempt-id family、authority/root/receipt/
decision/artifact。以下记录仅用于解释已封存的 historical decisions，不能作为运行步骤。

首次实际消费的 closure-stage authority plan
`sha256:81cc5ba229775fee8bdc327a14f00efe0a8e15c01ccf567749b5cc0e2457a7e4`
已永久结束为 `formal_runtime_drain_exhausted`。fresh target 中三个 task、published
report、co-terminal response 和 immutable closure 均已形成，closed event 位于 cursor
`276`；base attempt row 仍按 append-only 合同为 `active`。旧 Host observer 因读取裸
row 共执行 120 个 runtime command：前 6 个推进 6 条 signal、131 个 event 和 3 个
output，后 114 个全部为零 signal/零 event/零 output。18 个 MICU attempt 精确产生
`645196` input、`4334` output、charged `649530`，没有 overage；r59 source database 与
inventory 的 before/after digest 分别保持
`sha256:18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`
和
`sha256:9cc10388ba7e4e9a46e68013b02cc34727bfddac04ab8ea11def7e7132fc6cd5`。
该 consumed plan、failed decision 与 fatal 都不可重试或改写；其 runnable successor
contract 已于 r65 退役。

## 13. r66 local sandbox cause 与 selected-chain disposition

r66 永久 diagnostic NO-GO。其 formal sandbox 在 `bio_tools.hmmbuild` 输入上缺少 exact
`ws.stage_artifact` ref；canonical earliest cause 是 Host pre-admission
`hpc_stage_ref_required/validation/agent_can_replan/no_effect`，terminal run 的外层事实是
`sandbox_exec_nonzero/runtime/agent_can_replan/terminal_known`。两者分别绑定 control request
与 SandboxRun，wrapper 明确引用唯一 cause；没有 ControlledOperation admission、runner/HPC
dispatch 或 unknown external effect。

`FailureObservation` 不是业务状态。AOX 只有在 cause/wrapper、current selected formal
attempt、business-nonterminal task 与 exact canonical owner handoff 全闭合时，才把该 chain
视为可重规划 history。controlled-operation 的 exact
`controlled_effect/agent_can_replan/no_effect/terminal` failure 使用同一规则。agent 可自由
repair、选择其他合法 operation、请求 authority 或显式终结 task；Harness 不自动重试、
replay、重开 task 或合成 plan。

selected attempt 达到 immutable closure 后，同一 chain 中已 disposition 的 exact safe
failure仍保留为 sealed evidence，但 observer 不再把它当作当前 fatal。显式
failed/blocked/cancelled task、probe failure、unsafe/unknown effect、retryable、
dispatch-in-doubt、missing/duplicate/cross-source/cross-attempt binding 继续 fail closed。
AOX one-shot handoff 与 drain override 已删除；ordinary pinned bounded drains、complete
selected-chain closure 和显式业务状态共同决定收敛。

lifecycle repair `c3c560dd6ede54958398fb3e55d5cd62cc956ad1` 后的 fresh successor
plan `sha256:47ebfa37d653fa51c61eb304b3df620033d57f99aee6a3fcc88ae2e396b861ab`
也已永久消费。它在 closure 前暴露另一条链：executor-scoped auto compaction 曾把 workflow
ref 与 lane-local state 写成 session-like memory；后续 empty-focus master 错把历史 ref 带入
report delegation，正确收到 `workflow_ref_not_authorized/terminal_known/agent_can_replan`，
却只叙述省略 ref 而未调用 tool。report ready/unassigned、无 successor；3 个 command 推进
signal，随后 117 个 replay-safe empty command 到 generic exhaustion。decision
`sha256:eb70608e595d64c785227e4c05b46334a3996d853177341f2da729d4bf9c1abc`
与 fatal
`sha256:27ae166969295685ed56418e6b8abc404c7e3fff88884f5e85c1fe944b7723be`
不可重试或复用。

当时的 forward repair 同时加入 authority-free/scope-correct compaction、exact current
workflow refs、turn-local recovery proof 与 AOX prose veto。2026-07-28 的
control-boundary simplification 保留前两项和两次一致 no-wakeup diagnostic，但认定后两项
把 agent 策略误升格为 Harness fatal，已从 active contract 删除。这个后续架构纠正不改写
该 run 的历史 verdict，也不使上述 target、authority、MICU/evidence 或 r59 source 可复用。

该批准已在 clean repair commit
`4bf4c4244fae68beff8e5d47717e83824ff2367e` 上恰好消费一次。fresh plan
`sha256:7394c5200582b114a72fa08b0711dc993f4c7164dd66c1fb20dd1cf837060ae2`
恢复同一 cursor-614 cut，并复现
`sha256:4a234d47b942aa0dfec15b9071f40d393d721bfcf541442d4ef3ec062f5f2e6c`
effective config。旧缺口已通过真实 MICU product path：master 以
`workflow_refs=[]` 委派 reporter，report `report_16937278db9c` published，三个 canonical
task 全部 completed；master 同一 response 产生终答与 close，co-terminal response、
closure `attempt_closure_a2f78d1fd2199e239696b99e` 和 cursor `263`
`scientific.attempt.closed` 均形成。5 个 runtime command 各处理 1 条 signal，没有
zero-signal drain。

该 diagnostic 最终仍永久 failed，但暴露的是后置 driver seam。最后 command 于
`06:20:52.471276Z` completed，command writer 于 `06:20:52.501522Z` retired；
attempt scope 于 `06:20:52.642768Z` 进入 freezing，随后 quiescent/sealed，closure 与
post scope 分别于 `06:20:53.573680Z` /
`06:20:53.574446Z` 可见。旧 coordinator 在 admission-closed window 申请 observer，
把 `mutation_writer_admission_closed` 错归为
`mutation_driver_writer_identity_invalid`。decision
`sha256:470df988b817867c5fb80b859fd60c414d99a873e66a839283beb13fe1bef237`
和 fatal
`sha256:a3c4a24fcb6e9342dc11faa48bdb393481c0c9e1f4a1b9559c83b4fada0e8123`
只封存该事实。13 个 actual `gpt-5.5` MICU rows 精确新增 `1159495` input、
`2849` output、charged `1162344`，无 overage/breach；r59 source database/inventory
digest 仍不变。post-live bounded rollover correction 只通过非 live regression 验证，
没有第二次 live、formal bundle、reducer、GO/NO-GO、push 或 PR；本次 plan、target 与
证据不可重试或复用。

下一份 correction commit
`4122df0749c78f4ae011b6d804bf76cc3a9f8c1f` 的 one-use plan
`sha256:d062f81d803256e7ccca7ef63cba8fc0420022e5b731e65f1eced9d9e17b4cd5`
在 fresh root
`/tmp/openzyme-aox-closure-stage-rollover-4122df0-01.OnCkFK` 恰好消费一次，target 为
`aox-closure-stage-c2246ed00453d4a031ae5bfc`，diagnostic attempt 为
`closure-stage-0c83c00c02258e9f766bb0f213044e9c`。三个 task completed，report
`report_71ffe6a0e718` published；request
`attempt_closure_request_149617166649b78f2320b5ba`、co-terminal response
`attempt_closure_response_67b0ae6ad2b9391c4ac18c2d` 和 closure
`attempt_closure_d1e450291c10454855e07248` 均一致。

最后 runtime command 于 `07:08:16.801844Z` 完成；attempt scope 于
`07:08:16.853472Z` freezing、`07:08:16.930602Z` quiescent、
`07:08:17.039405Z` sealed；closure 与 open post scope 分别于
`07:08:17.379767Z/17.399815Z` 可见。observer 的 admission error 在前态形成，但旧
AOX-local classifier 到后态才读取，因拒绝已有 active post child，再次返回
`mutation_driver_writer_identity_invalid`。Host 又于 `07:08:17.500476Z` 原子排队 exact
closure signal `sig_c318716ba42c`；driver 先失败使它保持 pending。这不是未 closure 或
scope identity 损坏，而是 classification-after-commit 与 redundant terminal wake 两个
收尾 seam。

该 run 的 14 个 actual `gpt-5.5` rows 精确新增 `1195537` input、`3233` output、
charged `1198770`，累计 charge 到 `103697629`，无 estimated row、overage 或 hard-limit
breach；207 个 mutation writer 全部 retired，5 个 session lease 全部 released，r59
source digest 仍不变。decision
`sha256:7077a5ffe17f903cf93132d4b9384280228c1e562dd45b8de7bacdb5fe0c00e3`
与 fatal
`sha256:ed96bdd37285d3c1f56c12a515086bc5e9d25688bfff36ef9127ccb44a75e09b`
永久 `acceptance_eligible=false`。本次 Core projector/atomic admission/mechanical
settlement correction 只获得非 live 回归证明；它不复用该 plan/target，不生成 formal
bundle、reducer、GO/NO-GO、push 或 PR。

terminal-rollover repair commit
`230ea166eb5fd4e8f383c11825899b4b8858b64d` 随后以 fresh plan
`sha256:3dd8d6d0bc8d39ae8c029f8ccd7c31d006c2aaaf1f64b41a5f45b7b0d9115e87`
恰好执行一次。target `aox-closure-stage-0feb62fe7f7e75ef21070c6a` 中三个 task、
published report `report_9169386fb35f`、co-terminal response 与 immutable closure
`attempt_closure_c8ee71f7fe423aea0c1c7c6e` 全部形成；6 个 runtime command 精确处理
6 条 signal，旧 classification/redundant-wakeup seam 没有重现。

最终 verifier 以 `pubmed_primary_receipt_invalid` fail closed。只读数据库证明 primary
PubMed artifact `art_provider_a10852772d37`、succeeded invocation
`inv_research_tool_4ed73ef29381` 与 5 条 numeric-PMID source ref 均正确保留 r59 的
`lane_id=None`，但旧 reconstruction 把 synthetic completed research task/member 错误
挂到 fresh execution lane。该 lane 只描述新的 execution attempt，不应反向改写历史
session-scoped research provenance；因此问题属于 reconstruction mapping，而非 agent
决策。

当前合同在 source qualification 阶段证明 exact primary artifact/task/invocation/source
和全链 nullable lane，在 fresh target 中让 research task/member 与 copied PubMed lineage
共同保持 `None`，仅 execution task/executor/scientific attempt/executor signal 进入 fresh
execution lane。receipt validator 与 independent verifier 都会拒绝 graft、mixed、
empty-string 或其他不精确映射。failed decision
`sha256:311ccb035989a860d34524c58d53a68c64990ad27a875c676a2842b44a3988ef`
和 fatal
`sha256:d1885f6eee9bf169c098d03afff7172d47d613af6bddd90c22573fa8146f58c2`
永久 non-acceptance；原 plan、target、MICU/evidence 不可复用。
