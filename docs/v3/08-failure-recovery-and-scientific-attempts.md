# Failure recovery、显式拒绝与 scientific attempt

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

## 2. FailureObservation 与 agent hypothesis

`FailureObservation` 是 immutable canonical fact，绑定 session/task/lane/agent、
source kind/ref/version、phase、稳定 error code、recoverability、effect certainty、
retry eligibility、safe facts、规则化 likely causes、evidence refs 与 actor identity。
private exception 只保留不可逆 digest，不能进入 public projection。

三类内容必须保持分离：

1. `facts`：Host/Harness 已确认的事实；
2. `likely_causes`：由稳定 error code 确定性映射出的候选原因；
3. `FailureHypothesis`：agent 通过 `failure.hypothesis.record` 追加的解释，绑定真实
   canonical agent、confidence、evidence refs 和 idempotency identity。

`FailureHypothesis` 是独立 append-only row，不能回写或覆盖
`FailureObservation`。`failure.get` 和 workspace projection 可以把两者联读；投影中的
`agent_hypothesis` 只是 latest compatibility view，`agent_hypotheses` 才是完整归属历史。
记录 hypothesis 不提供 retry authority，不消除 unknown effect，也不改变 task status。

## 3. Runtime recovery

ordinary failed tool result 成功交给 agent 后，不另造重复 wakeup；harness 将它作为下一轮
tool observation 继续 bounded loop。若失败只在原 turn 结束后可见，例如 continuation
delivery recovery failure 或 Host-finalized transition failure，Host 使用 exact source/version
创建去重 wakeup，并在 claim 时从 canonical repository 重建 recovery brief。

`recovery_required` brief 只能陈述事实和安全边界。agent 可选择：

- 在同一 logical operation 的预声明、effect-safe retry policy 内重试；
- 创建新的显式 operation/plan；
- reconciliation；
- 请求 user/operator/authority；
- `task.finish(status="blocked")`；
- 在 objective 确知无法完成时 `task.finish(status="failed")`。

Harness 不得静默改参数、切 provider/backend、重开 operation、创建新 formal attempt 或把
known failure 擦除。step budget 用尽只是 non-business runtime outcome。

step-budget exhaustion 使用 canonical `agent_turn_budget_exhausted` observation。exact
signal/turn 以 `retry_eligibility=terminal` 结束且不会自动 replay；
`recoverability=agent_can_replan` 属于 task/agent 的下一步决策层，表示 master 可用一个新的
source-bound wakeup 显式 replan。`effect_certainty=no_effect` 的 scope 是 runtime signal
transition，不得擦除同 turn 已经持久化的 controlled-operation execution/result。task status、
failure summary/ref 保持原样。

Core 必须在同一个短 transaction/session runtime authority 中形成 typed
`AgentRuntimeOutcomeSettlement`，而不是让 receipt assembly 在 lease 释放后重建交接。
settlement 绑定 exact teammate occurrence、同 attempt observation、task/agent/lane/correlation
snapshot 与 exactly one source-bound pending master wakeup。全部一致时 scheduler batch
可以记为 completed handoff，但 exact signal 仍是 failed，新的 wakeup 才是可 claim 的
recovery work；任一要素缺失/歧义、cancelled/duplicate successor、普通 runtime failure 或
master 自身 max-step 仍然是 scheduler failure，不能靠重标状态绕过。

任一 master 或 teammate max-step outcome 都是当前 bounded batch barrier。scheduler 允许
已经 claim 的 wave 完成，然后停止新 claim；即使 `max_signals > 1`，该 occurrence 新建的
successor 也必须等下一条 command/background tick。后续 task 或 successor 状态变化不会
反向改写 immutable settlement。task business exit 与 scheduler settlement 正交：例如 agent
显式 `task.finish(status="failed")` 后 signal 正常 completed，scheduler batch仍可 completed。

manual runtime drain 在 scheduler batch 后先形成 immutable
`RuntimeDrainCoreReceipt`，再独立结算 trace/activity/consistency/event/workspace
projection。`runtime_command_outcome@2` 同时保存 scheduler 与 projection 两层状态；若
post-core projection 失败，真实 processed count、suspension 和 output/event identities 仍保留，
且只要 count 大于零就固定 `replay_safe=false`。只有 core receipt 尚未形成的 boundary
exception 才能报告 count `0`；旧 `@1` receipt 只读，不回填推导值。Host core receipt
直接聚合 Core typed settlement，不做 typed-to-dict-to-classifier 往返，不依赖对象 identity，
也不重扫 mutable signal/task/failure/agent/wakeup repository。

同一个 provider response 中的多个 tool call 作为有序 batch 结算。若某个已 dispatch call
触发 approval、terminal action、runtime suspension 或 boundary-fatal failure，harness
停止 dispatch 余下 call，但不能让它们消失：后续 eligible call 记录
`tool_call_batch_interrupted/no_effect/verify_then_retry`，overflow call 记录
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`。causal call 若已跨过外部
dispatch boundary，则保留原始 effect certainty 和 retry eligibility；
`dispatch_in_doubt/reconcile_required` 绝不能被后续批次收尾覆盖成 `no_effect`。这些
disposition 是事实与恢复边界，不是 retry authority；agent 必须在新 turn 中先检查
durable state，再决定是否重发、改道、reconcile 或请求帮助。

批次结算也不能把 pre-batch snapshot 当成所有调用的验证真相。eligible call 的 task/lane
引用在各自 dispatch 前依次解析，使前序 create/bind 的 durable effect 对后续调用可见；
never-dispatched call 的 no-effect observation 则保留原始引用，不为获得 metadata 而
提前验证未来对象。

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

agent 的 `attempt.create` 只写 admission request。它自己的 mutation writer 退休后，
Host finalizer 才在新的短 authority slice 中原子校验和消费 envelope、打开 attempt scope，
再唤醒原 agent。这样不会让同一 writer 既申请又自批 authority。非 retryable finalizer
拒绝必须生成 system-attributed failure observation 并返回 responsible agent；不得静默吞掉。

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
terminal authority。

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

上述 transition 必须是一个短本地 write transaction：attempt scope seal、closure row 与唯一
post-attempt session scope open 对并发 reader 原子可见。runtime barrier 可以看到 transition
前的 attempt scope 或 transition 后的 post-attempt scope，但不能看到已提交的零 open scope
中间态。真正 missing/ambiguous scope 仍 fail closed，driver 不以 blind retry 掩盖
non-atomic finalizer。实现上由 `ScientificAttemptService.finalize_closure_request()` 自身
打开 Core transaction 并在事务内重新读取 immutable request/attempt/selection/quiescence；
因此 direct Host endpoint、pending finalizer 与任意后续 Core caller 都不能绕开 rollover
原子性。规范 post scope 使用 deterministic id/ref，已有 child 必须唯一且身份完全一致；
并发 finalizer 只能 replay 同一 closure。

Host 的两个 scientific transition 调用面共用一条 delivery settlement：canonical
transition、deterministic public event、以及对原 agent 的 source-bound
`MANUAL_RESUME` signal 在包含 Core transition 的同一 write transaction 内提交，notifier
只在 commit 后触发。pending scan 必须处理“transition 已存在但 event/signal 缺失”的旧崩溃
状态，并以 record/event/source identity 补齐一次；terminal signal 不重开。这样既没有
scope gap，也没有 closure commit 后 agent 永久失联的第二条 crash seam。

quiescence 只证明“不会再变”，selection 只证明“采用什么”，两者互不替代。closed attempt 是
agent 可消费的 evidence，不是 `task.finish`；owner 仍需显式决定完成、继续、blocked 或 failed。

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
回填 selection、与 `@3` row 混合或被新 campaign 采用。r48-r56 永久保持 NO-GO；
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

r56 触发后，AOX target contract 将 live execution 分为两个不可互换的类别：

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

两类 closed validator、publisher、consumer、slot identity、root namespace/ancestor marker、
collector 与 verifier 已有 cross-mode negative 回归；即使删除 diagnostic run-class 字段或
把 plan digest 伪造成与 formal 相同，也会在 root/effect 前失败。architecture qualification
增加 `evidence-projection.aox-run-class-disjoint-closure`，使用 file-backed SQLite 且记录
零真实外部 effect。实现和非 live gate 通过不授权真实 diagnostic 或 r57；diagnostic plan
与后续 formal exact-three plan 仍必须分别取得 operator 精确批准，普通失败的 `run-live`
也永远不能事后改称 diagnostic。
