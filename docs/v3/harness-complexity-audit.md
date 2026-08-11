# OpenZyme V3 Harness 复杂度审计

## 1. 文档目的

本文记录架构探索过程中发现的 V3 harness 复杂度风险。

本文是追踪文档，不是实现变更。每个发现项前面都带复选框。后续 change 修正一个或多个问题后，应回到本文勾选对应项，并补充简短说明或 change / PR 引用。

默认校准目标：

**OpenZyme V3 应采用严格 harness 边界。**

Harness 负责 tools、canonical state、permissions、failure/effect facts、projection 和
execution boundaries。Master agent 与 teammate agents 负责用户意图理解、任务拆解、完成
判断、诊断策略和下一步决策；Harness 不建立第二套 recovery workflow 证明这些策略。

## 2. 评审规则

评审或修改 V3 时，使用以下规则：

- Harness 应提供世界，而不是编码业务判断。
- Control-plane 对象应保持稳定名词：`session`、`task`、`lane`、`approval`、`artifact`、`run`、`report`、`inbox`、`memory` 和 `workspace_projection`。
- Tool 应保持原子、可组合；避免把多步策略隐藏在 tool handler 里。
- Scheduler / runtime 可以唤醒 agent 并执行边界约束，但不应决定业务完成状态或修复策略。
- Protocol 是通用通信机制，不应拥有领域特定的 diagnostic 或 HPC retry policy。
- 即使替换 LangGraph 或模型适配层，V3 产品级真状态也应继续成立。

## 3. 发现项

- [x] `AgentRuntimeService` 直接把 teammate loop 结果映射为 task 终态或阻塞态。

  证据：`packages/openzyme-core/src/openzyme_core/agent_runtime.py` 基于 `run_teammate_loop` / `finalize_teammate_result` 的结果，将 task 状态更新为 `COMPLETED`、`BLOCKED`，或进入失败处理路径。

  Doctrine 风险：task 是否完成变成 runtime 推断，而不是 agent 通过 `task.update` 做出的显式决策。

  目标边界：runtime 可以标记 runtime signal completed / failed，也可以标记 agent working / idle / blocked。业务 task 状态原则上应只通过显式 task tool 改变，或通过极少数已文档化的机械状态迁移改变。

  后续修正方向：要求 teammate loop 显式调用 `task.finish` 写入 task 业务出口；或者定义一份最小、明确、已文档化的 runtime 机械状态迁移例外清单。

  修正记录：已收窄 runtime 状态写入。`AgentRuntimeService.wake_agent()` 不再根据 teammate `final_status` 自动写 `COMPLETED` / failure-derived `BLOCKED`；teammate 需通过 `task.finish` 显式写业务出口。保留的机械迁移为 task claim 时进入 `IN_PROGRESS`，以及 pending approval 时进入 `BLOCKED`。

- [x] Host API 在用户消息和 task 更新后隐式 drain agent runtime。

  证据：`apps/openzyme-host-api/src/openzyme_host_api/v3_service.py` 曾在 `post_message()`、`create_task()` 和 `update_task()` 中调用 runtime drain。

  Doctrine 风险：Host API 开始像 orchestration engine 一样，把用户消息处理、teammate wakeup 和后续工作串在一次 service call 里。

  目标边界：Host API 应暴露清晰命令，例如 post message、resolve approval、read projection，以及 debug/operator 的 drain pending signals。普通产品路径中，Host API 只写入用户动作和 control-plane 状态并排队 wakeup signal；后台 scheduler 是唯一正常 runtime 入口。

  后续修正方向：将 master 与 teammate 都建模为 resident agent member，`post_message()` 只排队 `agent:master` wakeup，approval resolve 只排队相关 agent wakeup，`/runtime/drain` 只保留为 debug/manual scheduler command。

  修正记录：已移除 `create_task()` / `update_task()` / `post_message()` 的隐式 drain。下一步产品语义是：`task.delegate` 只创建 protocol delegation、resident teammate 与 wakeup signal；master 与 teammate turn 都只能由 scheduler claim signal 后执行。

  追加修正记录：`runtime/drain` 现在通过 scheduler claim lease 语义认领 signal；repository 层记录 `claimed_by`、`claim_expires_at`、`attempt_count` 与 `last_error`，支持 stale claim recovery 与失败重试边界。

  追加修正记录：runtime 推进权已从 signal-level claim 扩展为 session-level `SessionRuntimeLease`。background runtime、manual `/runtime/drain`、recovery/test scheduler 共享同一 session ownership；signal claim 绑定 lease token / fencing token，过期 worker 迟到 complete/fail 会被拒绝并产生 diagnostic，而不是覆盖新 owner 的状态。

  追加修正记录：长时 provider/runner 调用期间的 session heartbeat 不再复用 coordinator connection；每次续租与 SQLite contention retry 都使用 fresh scope，只对 `BUSY` / `LOCKED` 在当前 lease deadline 内有界重试。其他错误显式失败，确认 stale 的任何 sandbox/adapter 写回统一以 non-retryable `runtime_write_fenced` fail closed。

  追加修正记录：message admission 不再把临时 `SessionRuntimeContext.restore_focus` 当作异步 turn 的权威。去重后的显式 `skill_keys` 与 canonical user conversation document 一起持久化，`AgentRuntimeSignal` 仍只保留 `source_ref`；master 在 `working` / `agent.woken` / provider 之前按 exact source 校验并恢复。普通 agent protocol inbox 只提供 wakeup context、不授予 workflow refs；损坏 public user binding fail closed；每条 user source 独立生效，background/manual drain 都不能注入、sticky 或 union authority。

  追加修正记录：public `/runtime/drain` 已从同步 scheduler 调用改为严格 durable command admission。POST 原子创建 command/outbox、始终返回 `202`，独立 `RuntimeCommandWorker` 后续获取 session lease 并执行 bounded batch；GET 返回闭集脱敏状态。HTTP request、command 和 session lease 均不拥有 approval/provider/HPC wall time。

  追加修正记录：r79 暴露 command 在无 mutation scope 时 claim、同一 batch 打开 attempt scope 后，heartbeat 仍继承空 authority 的跨 scope 缺口。late-scope heartbeat 现按 exact command id 为每次续租创建并立即退休短 `runtime_command` writer；repository把精确mutation-guard rejection翻译为包内typed exception，worker不解析原始SQLite文本，只对该authority-transition类型与SQLite `BUSY/LOCKED`在当前lease内有界处理，executor返回取消待执行retry，真实state/token/fence drift与expired-claim recovery继续fail closed且不replay scheduler。core覆盖authorized heartbeat、typed transition、raw-text rejection、contention/cancel、fence-loss与旧no-replay负例；production-composition qualification用真实public FastAPI、thin CLI与file SQLite及authorized-renew Event屏障证明attempt scope后heartbeat writer terminal、command/event closure且无`runtime_command_claim_expired`，不再依赖固定亚秒sleep。

- [x] Host 在 scheduler 释放 runtime authority 后重扫 mutable repository，并重建
  max-step handoff 与 scheduler success/failure。

  证据：r55 的 teammate signal、exact budget observation、nonterminal task 与 pending master
  wakeup 已 durable 闭合，但 Host 的 dict/object-identity 分类仍把 `outcome.ok=false` 展平成
  `runtime_scheduler_batch_failed`；此前局部修补又要求 Host 联读 signal、task、failure、
  agent 与 wakeup 当前行。

  Doctrine 风险：Core 已完成的 occurrence settlement 会被 Host 的第二套 read-model
  interpreter 重新定义；后续 task/successor 状态变化还能反向改写旧 command receipt，
  scheduler/runtime 也可能借 task business status 推断策略结论。

  目标边界：Core 在 exact session runtime authority 内产生 immutable typed settlement；
  scheduler 只消费 batch barrier，Host 只聚合闭集 disposition。task business exit、
  signal terminal state、scheduler batch settlement 与 projection settlement保持正交。

  修正记录：新增 `AgentRuntimeOutcomeSettlement`，在 teammate finalization 的短 transaction
  中绑定 source occurrence、task/agent/lane/correlation snapshot、failure observation 与唯一
  pending master successor；任一 master/teammate max-step 在当前 claim wave 后结束 bounded
  batch。Host core receipt 直接消费 typed outcome，删除 `id(outcome)`、typed-to-dict
  interpreter、repository rescan 与 task-status 反向映射。file-backed SQLite 的两条真实
  `RuntimeCommandWorker` command 已证明默认 `max_signals=3` 的第一条只形成 handoff，第二条
  才 claim successor，且显式 failed task 不会把 completed signal 重分类。

- [x] Host API 在 teammate 终态结果后触发 service-level master response turn，而不是排队 master wakeup。

  证据：历史实现中的 service helper 会在 teammate outcomes 后启动另一次 top-level master loop。

  Doctrine 风险：service 代码决定“teammate 终态结果应触发 master response turn”。这是产品 workflow policy，被嵌入 Host service 逻辑。

  目标边界：teammate result 应表达为 task / protocol / report state 加 `agent:master` wakeup signal；master loop 由 scheduler claim signal 后启动，并由 master agent 自己决定是否回复以及如何回复。

  后续修正方向：将 teammate result 表达为 inbox / protocol state 加 master wakeup signal，让 master loop 自己决定是否回复以及如何回复。

  修正记录：`post_message()` 和 approval resolve 不再在隐藏副作用中触发 master response turn。teammate terminal outcome 只写 task/protocol/report state 并排队 `agent:master` wakeup；master loop 只能由 scheduler claim signal 后启动，由 master 自己决定是否回复用户以及如何回复。配置化 Host 默认由 background runtime worker 推进 scheduler claim；显式 `/runtime/drain` 仅 admission debug/operator/manual-recovery durable command。

- [x] `protocol.send(await_response=true)` 同时承担消息投递和同步 teammate 执行。

  证据：`packages/openzyme-core/src/openzyme_core/protocol_tools.py` 在 `await_response=true` 时，会在 `protocol.send` 内部调用 `AgentRuntimeService.drain_session()`。

  Doctrine 风险：通信 tool 变成同步 workflow runner。protocol 语义更难推理，inbox delivery 也和 runtime execution 耦合。

  目标边界：`protocol.send` 应持久化消息并排队 wakeup。运行 recipient 应是单独的 runtime / scheduler action，除非明确文档化为测试或受限便利路径。

  后续修正方向：从正常 protocol 语义中移除 `await_response`，或拆成单独的 `runtime.drain` / `agent.resume` tool 或 API。

  修正记录：已从正常 `protocol.send` 语义中移除同步 teammate 执行。`protocol.send` 现在只持久化 message 并排队 wakeup signal；`await_response` / `max_steps` 参数会返回 `sync_execution_not_supported`，recipient turn 由 scheduler claim signal 后运行。`/runtime/drain` 只能 admission durable debug/manual command，不能由 POST 直接 claim 或运行 recipient。

- [x] Delegation 存在多条重叠路径。

  证据：V3 曾同时存在 `task.delegate`、`HarnessStep.delegation_requests` 和 `ProtocolService.delegate()`，它们都能创建 delegation 相关状态。

  Doctrine 风险：多条 delegation seam 会增加不同路径写出不同 task、inbox、protocol 和 signal 行为的概率。

  目标边界：delegation 应只有一条 canonical control-plane write path。其他接口应调用这条路径，或被移除。

  后续修正方向：选择 `ProtocolService.delegate()` 或一个单一 delegation service 作为 canonical path，然后让 `task.delegate` 和任何 harness step abstraction 都路由到它。

  修正记录：已删除 `HarnessStep.delegation_requests` harness-level seam 和对应 `HarnessResult.delegations` handle。`task.delegate` 是唯一正常产品入口，继续负责参数校验、role / agent 推导与 payload 持久化；`ProtocolService.delegate()` 是唯一真实 control-plane 写路径，负责 agent member、inbox delegation message、runtime wakeup signal 与 delegation events。

- [x] Runtime 包含领域特定 diagnostic 和 HPC retry 指令。

  证据：`AgentRuntimeService._instructions_for_signal()` 包含 execution approval recovery、HPC failure handling、retry advice 和 diagnostic-request prompting 等指导。

  Doctrine 风险：scheduler / runtime 正在编码 executor reasoning policy。领域策略应属于 teammate prompt、docs、tool result 或 agent 决策，而不是 runtime。

  目标边界：runtime 应注入 wakeup reason 和相关结构化证据，但不应规定领域修复策略，安全边界除外。

  后续修正方向：将 execution / HPC diagnostic policy 移到 executor system prompt、execution docs 或结构化 tool result hints 中。

  修正记录：已移除 runtime 中关于 HPC retry、等价重试禁止、具体失败处置和 fpocket 输出摘要的策略性指令。runtime 只注入 approval、task、invocation/status、artifact 与 sanitized failure evidence 等恢复事实。

- [x] Diagnostic request 语义在 protocol 和 runtime 中被特殊处理。

  证据：`protocol.send` 会为 diagnostic messages 校验 focused task；`AgentRuntimeService._is_diagnostic_signal()` 会改变 diagnostic signals 的 task completion 行为。

  Doctrine 风险：通用 team protocol 积累了 failed delegation repair 的 workflow-specific behavior。

  目标边界：diagnostic messages 应只是普通 protocol payload。特殊含义应由接收 agent 解释，而不是由 protocol / runtime infrastructure 解释。

  后续修正方向：保留 `message_type=diagnostic_request` 作为数据；移除 runtime 状态例外，除非这些例外被明确文档化为机械安全规则。

  修正记录：已移除 `AgentRuntimeService._is_diagnostic_signal()` 及其对 task completion / blocked 迁移的例外影响；同时移除了 `_instructions_for_signal()` 中按 `message_type=diagnostic_request` 生成专门 prompt 文案的分支。`diagnostic_request` 仅作为普通 protocol payload 出现在 thread / restore context 中，由接收 teammate 解释。

- [x] Auto-claim 行为有演变成业务优先级策略的风险。

  证据：`AgentRuntimeService.auto_enqueue_ready_tasks()` 会扫描 ready tasks，将 task kind 映射到 teammate role，并为 idle agents 排队 wakeup signals。

  Doctrine 风险：auto-claim 是有用的 harness 机制，但如果继续增长策略，就可能替代 master / teammate 的优先级判断。

  目标边界：auto-claim 只应做窄范围机械匹配：ready task、无 owner、role match、idle agent、无 blockers。

  后续修正方向：保持 auto-claim policy 最小化并写入文档。任何更复杂的优先级判断都应交给 master 或 teammate。

  修正记录：已将 `auto_enqueue_ready_tasks` 默认值改为 `false`，默认产品路径改为 master 显式 `task.delegate`。auto-claim 保留为显式 operator/debug/recovery option，且 runtime 只允许 `TASK_AVAILABLE` 认领 `todo + unassigned + no blockers` 的 task。`task.delegate` 和 runtime wakeup 均已加入 `blocked_by` ready gate；blocked task 不再能被提前委派或被普通 wakeup 推进到 `in_progress`。

- [x] Top-level 与 teammate prompts 依赖嵌在代码里的恢复策略。

  证据：`packages/openzyme-core/src/openzyme_core/llm_driver.py` 和 `packages/openzyme-core/src/openzyme_core/teammates.py` 构建较长 operational prompts，其中包含 delegation failure、protocol inspection 和 execution behavior 等具体规则。

  Doctrine 风险：prompt construction 是合理的 harness 职责，但散落在代码里的 policy 比 docs / tool descriptions 更难审计和演进。

  目标边界：代码应负责组装 restore context 和稳定 role instructions；可变 operational doctrine 应放在 V3 文档或类似 skill 的受控文档中。

  后续修正方向：将高层 operational rules 抽取到版本化 V3 docs 中，让代码里的 prompt assembly 保持轻量。

  修正记录：已移除 master prompt 中按 `diagnostic_request` 固定处理 teammate failure / unclear summary 的恢复流程。master prompt 现在只保留通用处理原则：读取 task state 与 `protocol.thread(correlation_id)`，再用现有 `protocol.send`、`task.update`、用户澄清或用户汇报路径做判断。`protocol.thread` tool result 增加 latest status / summary / task / failure observation fields，V3 runtime 与 top-level loop 文档已同步为 follow-up flow。

- [x] Workspace projection 暴露的 runtime internals 可能变成产品界面语义。

  证据：UI 和 projection 暴露 delegation agent status、pending signal counts、wakeup reasons、unread inbox counts 和 protocol thread summaries。

  Doctrine 风险：projection 应让工作状态可理解，但不应把内部 scheduler queues 变成用户可见产品语义，除非这是有意设计。

  目标边界：UI 可以展示 teammate working / idle / blocked / failed 和 pending approval state。低层 runtime counters 默认应保留为 developer / debug detail，除非用户需要它们来采取行动。

  后续修正方向：拆分用户侧 projection 与 debug projection，或明确把 runtime internals 标注为 diagnostic-only。

  修正记录：默认 delegation projection / Web UI 不再暴露 `pending_signal_count`、raw `wakeup_reason`、`latest_signal_reason` 和 unread inbox count 作为用户界面语义；低层 runtime signal 仍保留在 event/debug 路径中用于诊断。

  追加修正记录：workspace projection 新增 diagnostic-only `runtime_state`，明确区分 `agent_turn_failed`、`runtime_signal_failed`、`task_failed`、`runtime_attention` 与 `outcome_unconsumed` / `capability_outcome_ready`。terminal capability outcome 只表示 evidence ready 和 owner wakeup，不代表 teammate/task completed。Phase 2 保留该请求时只读 projection，但删除每次 drain 重复追加的 `runtime.consistency.warning` / `runtime.state_attention` derived durable events；业务终态仍由 `task.finish` 写入。

- [x] Composite workspace 被当作 approval control poll，导致科学 metadata 反向放大 runtime coordination。

  证据：AOX r38 formal session 的 Artifact metadata JSON 合计约 36.96 MiB；旧 projection 将同一 metadata 重复放入 artifacts、artifact index、activity feed 与 capability branches，产生约 106.36 MiB workspace。live driver 在同步 drain 内每 0.5 秒 GET workspace，approval resolve 的 write UoW 又通过 activity-event backfill 与 command response 重复构造它。

  Doctrine 风险：harness 把“是否存在 pending approval”这个小控制事实绑定到无关科学 payload 大小，既增加低摩擦世界读取成本，也延长 single-process SQLite write transaction，使 agent 已批准的 continuation 无法及时推进。

  目标边界：approval control read 只投影 durable Approval / ControlledOperation / SandboxRun identity；workspace 仍是 UI composite snapshot，但所有 Artifact collection occurrence 必须有界，exact metadata 留在 canonical catalog 并按需分页读取。activity-event backfill 不得递归构造 workspace。

  修正记录：新增同源只读 `GET /v3/sessions/{session_id}/pending-approvals`；cutover hot loop/cleanup 只读 compact view，Chrome handoff和 drain 退休后证据才读取 workspace。workspace/activity/capability 统一复用 bounded artifact item，activity backfill 直接构造 sanitized feed。r38 DB 只读 benchmark 降至约 0.69 MiB / 2.77 秒，compact read 约 1.3 ms；canonical Artifact metadata 未删除或截断。

- [x] Design / deep-research planner fallback 会掩盖真实 provider 或 contract 失败。

  证据：已删除的旧 graph 路径曾在 LLM planner 异常或非法 action 时调用 heuristic next action，并把 blocked action 重新加入 `allowed_actions`。已删除的旧 deep research graph 曾在缺少 model 或 researcher 未调用 search 时编造 supervisor plan、tool call 和硬编码 enzyme search query。

  Doctrine 风险：生产路径看似推进成功，但实际的 LLM/tool/provider contract 已失败；测试可能验证的是 fallback 行为，而不是产品真实语义。

  目标边界：planner/provider 失败应产出明确 failed decision / failed dossier；tool argument validation 可以作为 tool error observation 返回给 LLM；unexpected exception 应直接暴露给测试和 live gate。

  修正记录：design graph 保留 state-machine recommendation 作为 prompt guidance，但不再作为恢复 action 执行；missing model、planner exception 和 illegal action 均持久化 failed decision。deep research 删除 fallback supervisor / researcher / query，缺 model 或缺 unit plan 返回 failed dossier，tool 参数 validation 返回 failed observation，unexpected tool/provider exception 继续抛出。

- [x] Approval 与长时 external operation 占用原 agent signal、session lease 和同步 HTTP request。

  证据：历史 sandbox control worker 在 `_wait_for_approval_and_claim()` 中轮询 approval，批准后由同一调用栈 dispatch adapter；`runtime/drain` 只有等 agent turn、sandbox/provider/HPC 与 composite workspace 全部返回后才能结束。rxx 失败表明 SSH 抖动和 session fencing 会在 scientific payload 之外互相放大。

  Doctrine 风险：一个 bounded agent turn 同时成为 HTTP、approval wait、external-effect dispatch、result delivery 与 closure owner。任何 timeout/restart 都无法区分 effect 是否发生，也无法在不重放科学动作的前提下恢复。

  目标边界：保持 task/agent 策略自由，同时把真实世界约束拆为五个显式 authority boundary：session signal/turn、sandbox process epoch、external execution、exact continuation delivery 与 mutation closure。每类 worker 只认领自己的短 slice，任一 terminal/idle 不推断 task 终态。

  修正记录：`runtime-hpc-reliability-refactor` 已建立唯一 `ControlledOperationExecution`、immutable dispatch/result records、execution fence/effect certainty、attached-process continuation、durable `202` runtime command、generic mutation scope/writer/receipt 与 runner-owned per-target ControlMaster。durable wait 会 park exact sandbox process并在 bounded deadline 内释放 signal/session/request；direct SSH dispatch ambiguity fail closed，只有 proven pre-effect 允许一次有界恢复；closure 等待显式 writer retirement 和两次一致 snapshot，不以 runtime idle 代替。真实 SSH transport-only soak 仍是恢复 rxx 前的独立外部门禁，不因本项代码/文档完成而自动获得 GO。

  追加修正记录：r44 证明 control server 虽拥有 exact process resume，engine callback 仍可能回到创建时捕获的 stale turn scope。`simplify-sandbox-host-authority-handoff` 将 session/process/execution/delivery owner 固化为 immutable `SandboxHostCallContext`，所有 adapter/fetch 只经 typed gateway；删除 reflected callback、双 scope factory 与 optional repository escape hatch。AOX 对 suspension/writer/runtime work 的直接数据库 helper 同时被 bounded read-only runtime barrier 替代，driver 不再复制 runtime ownership 规则。

  追加修正记录：post-r79 HMMER incident 证明“operation 已 durable”仍不足以让 provider adapter 在单次 dispatch callback 内安全等待完整外部 job。现行修复没有新增 HMMER state machine 或 AOX driver，而是在同一个 `ControlledOperationExecution` owner 下增加 Host-private immutable dispatch/observation receipts：submit-once 后立即绑定 exact job 与 absolute deadline，后续 bounded slice 只 poll/reconcile 同一 handle，`RETRY` 非终态，terminal success 才 materialize，timeout 形成 typed terminal handoff。restart 不重置 deadline；accepted submit 在 receipt commit 前丢 callback 的窗口保持 `dispatch_in_doubt`，禁止 replay。

  剩余债务：EBI 当前接口没有由 OpenZyme request digest 驱动的 idempotency key 或反查 job 能力，因此“provider 接受 submit”和“Host canonical receipt commit”无法成为跨系统原子事务。该窗口只能显式保留歧义；若未来 provider 提供 idempotency/query contract，应在版本化 adapter receipt 中接入，而不是增加猜测、自动 successor 或 AOX 专用 observer。append-only poll receipts 已按 frozen deadline/interval 限制数量，但生产数据保留/压缩策略仍应随通用 canonical-history retention 一并治理，不能由 HMMER 路径私自删除。

- [x] Harness 将大小故障统一提升为 turn death，agent 无法修复或明确拒绝。

  证据：旧 `ToolRouter.dispatch()` 让 ordinary runtime exception 穿透到 harness；harness
  直接返回 `FAILED`，owner agent 没有机会读取 error/effect/retry facts。与此同时，provider/
  driver 失败只有 Harness 文本，后续 runtime 无 canonical source-bound recovery context。

  Doctrine 风险：Harness 既夺走 agent 的策略自由，又无法区分可修复 local error 与真正必须
  fail closed 的 unknown effect/authority violation。统一“死掉”不是安全设计，只是缺少
  failure control plane。

  目标边界：ordinary effect-known failure 返回同一 bounded turn；boundary-fatal failure
  停止 ownership；两者都形成 immutable safe observation，且都不自动改变 task。agent 可以
  repair/replan/help/refuse，Host 只在 agent 无法运行时使用 system voice。

  修正记录：第一阶段建立 `FailureObservation` 与 ordinary failed-result continuation，
  并保留 fencing、authority、integrity、permission/budget、process cancellation 和
  `dispatch_in_doubt` 的 fail-closed 边界。随后 r60/r61 为了强迫 internal signal turn
  产生 Harness 可识别的“durable decision”，逐步加入 hypothesis、turn-local obligation、
  exact settlement matcher、response rejection、dependency disposition、reconciler 与
  `RECOVERY_REQUIRED` signal。

  2026-07-28 复杂度复盘认定后半段是元问题本身：它没有保护新的不可逆安全性质，却把开放的
  agent 策略变成必须不断补充的闭集 matcher。`simplify-v3-harness-control-boundary` 因此
  删除 hypothesis/disposition active control plane、turn recovery machine、synthetic wakeup
  与 response veto，只保留 `FailureObservation`、ordinary continuation 和真实安全边界。
  `COMPLETED` / `MAX_STEPS_EXCEEDED` 都不推断 task terminal；approval 仍要求 durable identity，
  unknown effect/authority/fencing 等负控不变。历史 migration 表保留兼容，但 runtime 不再
  读写或投影。

  r64 追加修正记录：旧 runner closed result 丢失
  `transport_connect_failed/no_effect`，Host 又以 local failed `Run` 抢先覆盖真实 cause；
  AOX failure evidence 只带 probe subset，driver 还在 exact recoverable owner wake 已排队时
  立即停止。当前 runner attempt 封存 safe terminal code/effect/retry，runner observation
  成为 runner-backed execution 的唯一 causal input；AOX 以一份 bounded
  formal/probe operation facts 服务 observation/evidence。failed supervision 默认不变，
  仅在 attempt、operation、execution、continuation、failure、task 与 session 内唯一
  pending zero-attempt owner signal 全部 exact 时允许一次 later drain。该 handoff 不创建
  recovery machine、不 replay effect、不选择 agent 策略，任何 drift 仍 fail closed。

- [x] Exact-occurrence AOX gate 把任何中间试错永久等同于最终 scientific failure。

  证据：历史 `aox_blank_world_attempt_bundle@2` 以 exact occurrence/history poison
  验收，无法表达同一 formal attempt 中“保留 failed trial，但显式采用后续合法 chain”。

  Doctrine 风险：Harness 把过程策略写死为 first-try success，反向逼 agent 隐藏失败或开新
  attempt；同时仍缺少 full occurrence completeness、authority consumption 和 closure truth。

  目标边界：保留完整 occurrence universe，由 agent 显式 disposition/adopt；known closed
  failure 不污染合法 selected chain，unknown effect/process/writer/authority/resource breach
  仍 fail closed。same-attempt cross-run materialization 可以，cross-attempt reuse 禁止。

  修正记录：generic scientific-attempt authority/selection/materialization/closure 已落地，
  AOX 新 production bundle 升为 `@3`，历史 `@2` verifier 与 r48-r51 NO-GO evidence 冻结。
  fresh three-slot authority plan 在任何 root 前一次性消费。本轮只完成 non-live 验证，明确
  停在下一次编号 live attempt 之前。

  历史修正记录：r57 证明 prompt-only 的 exact task set / close-last 约束仍可被同一 agent
  turn 违反，当时曾加入 composition-injected `tool_dispatch_precondition`。后续 transformation
  audit 证明这条 seam 本身会把某条 AOX trace 固化为 Harness policy；current 已整体删除。
  Router 只保留通用 schema/visibility/governance/fence，真实 mutation constraints 回到各 domain
  owner，AOX workflow completeness 回到 final product-closure/offline verifier。

  post-r57 历史修正记录：precondition 只判断 close 是否可 dispatch，不能替代 turn
  lifecycle。successful `scientific.attempt.close` 现复用通用 terminal action 与 ordered
  batch settlement，持久化 closure intent 后立即退休 requesting turn；同批后续 mutation
  不 dispatch，Host 只在外层 writer 连同 no-effect settlement 退休后 finalization。AOX
  readiness/collector 还要求每个 finish receipt 都是 `finished_by == assigned_ref`；
  generic master recovery authority 未被删除，但不再能冒充 cutover owner exit。该边界由
  real SQLite repository-backed task/report/close/finalizer regression 覆盖，普通 session
  仍保持原 task semantics。

  r58/post-r59 曾把 co-terminal conversation 与 report handoff 扩展为 generic
  `assistant_response_precondition`，并在 AOX `@4` 中拒绝 premature prose。后续复杂度复盘
  认定“文本是否足以作为下一步策略”不是 safety invariant；Phase 2 进一步删除 companion
  text、closure-response repository/conversation transaction 与 scientific-specific
  settlement。current close handler 只接受 exact attempt-task canonical assignee，只写
  immutable request；AOX dispatch precondition `@1`–`@6` 已全部退为 historical，current
  final verifier仍拒绝task/report/selection/closure不完整的attempt，但不再拦截generic task/
  report strategy。assistant prose
  本身不会完成任何对象，也不再因 Harness 期待另一种策略而被丢弃。r58–r62 及
  closure-stage diagnostics 的历史 verdict、authority 与不可复用性不变。

  同期保留的其他修正包括 authority-free/scope-correct compaction、prompt 中 exact current
  workflow refs，以及两次 stable zero-signal/no-wakeup diagnostic。它们呈现 canonical
  state，不要求 agent 走固定 handoff 剧本。

- [x] Scientific transition 是否同时生成 generic master 与 canonical owner 两个 successor。

  证据：post-r63 production composition audit 证明 successful `attempt.create` 的 teammate
  result transaction 先按 ordinary completion 排队 `source_ref=<teammate signal>` 的 master
  wake；Host 在 command batch 结束后才 finalization 并排 exact attempt-id owner wake。
  master claim 又丢弃已验证 canonical wake facts。两个 wake 都是 durable truth，但只有后者
  与 transition source 闭合，前者会在 finalization 前形成竞争 turn。

  Doctrine 风险：Harness 把“teammate turn 结束”误当成“master 必须先接手”，制造了不属于
  scientific lifecycle 的后继，并让 actor routing 决定 agent 是否能看到同一份世界事实。
  AOX failure collector 又用另一套 latest-finish 读库，使 current cause 与 evidence 可能分叉。

  修正记录：successful admission/closure handoff 不再创建 generic master successor；
  Host-finalized exact owner wake 是唯一 successor。canonical wake facts 以同一 bounded
  ephemeral contract 注入 master/teammate，不写 conversation。AOX 以一个 current-exit
  projection 接受历史 resume exits、同刻矛盾 fail closed，按 causal timestamp/stable id
  选择 actionable candidate，并把同一 bounded task/evidence facts 交给 failure evidence。
  ordinary teammate completion 与 max-step budget-replan master wake 不变。

- [x] Sandbox-local pre-admission failure 是否被 SDK 丢弃，或被 generic process exit
  覆盖成错误业务终态。

  证据：r66 formal executor 直接把 fetched MAFFT descriptor 交给
  `bio_tools.hmmbuild`；缺少 exact `ws.stage_artifact` ref 的
  `hpc_stage_ref_required/no_effect` 在旧 SDK/Host boundary 没有 durable observation，
  随后的 `sandbox_exec_nonzero` 又被 successful ToolResult 与 AOX failed-history scan
  分别掩盖/放大。

  修正记录：SDK 保留 exact request，Host 在 operation admission 前封存 local cause，
  SandboxRun 封存 source-bound wrapper，failed ToolResult 与 canonical owner wake 复用
  同一 chain。AOX local/controlled formal failure 统一按 selected-chain disposition 判断，
  删除 one-shot handoff 与 drain override。r67 又删除整个 AOX automatic convergence
  reducer；public conductor 逐次请求 bounded drain，Host facts 与 offline verifier 分别承担
  canonical truth 和 eligibility。Harness 不自动 retry/replay，也不从历史 failure 推断当前
  业务终态。

- [x] AOX observer/driver 是否仍是 safety mechanism，还是把测试策略写进 Harness 的重复控制面。

  证据：r67 的首个 provider request 使用 malformed `output_dir`；agent 在同 turn 修正后，
  exact NCBI operation 已完成，但旧 observer 继续扫描 failed history并终止测试。该轮永久
  NO-GO，decision 为
  `sha256:d9356b0bdd25885f19e2452773dfac03bfa09e39562ed4c00c8fca9828ef480b`，
  共计 `3,903,566` charged tokens / `81` attempts。observer 既不拥有 Host canonical
  state，也不能替 offline verifier判定 eligibility，却重复实现 continue/stop/rollover policy。

  修正记录：删除 AOX runtime observer、Core runtime-barrier/observer-writer、automatic
  drive-until-terminal/no-wakeup/scope-rollover chain 及 runnable live commands。Codex 测试员
  仅通过 public Host API/CLI 编排；Host 保留 state/approval/fencing/effect/isolation authority，
  process supervisor 只证明进程退休，offline verifier/reducer 仍是唯一 GO 权威。保留
  authority/pin/preflight/evidence shell，但它们不做业务判断。

- [x] Formal launch plan 是否在 canonical objects 存在前预造 attempt/lane/admission shadow truth。

  证据：r69 outer plan预声明attempt/lane，Codex又通过public generic scientific command代发
  `attempt.create`；真实execution task没有lane，Host正确返回
  `attempt_lane_scope_invalid/no_effect`。该轮已消费authority/root/session、provider与MICU，
  但SQLite没有admission request或attempt。预声明identity没有帮助agent满足真实isolation，反而
  让receipt/bundle把尚不存在的control当成truth。

  追加证据：r70已消费authority/slot/root/session/receipt，却在首个runtime drain前停止；Host
  没有scientific authorization/admission/attempt。把task/envelope继续放在outer launch会要求
  conductor在entry message创建canonical task之前猜测control identity，因此r70只封存为
  pre-runtime conductor blocked，全部state不可复用，当前没有r71。

  修正记录：current plan/claim/root proof/preflight/supervision只绑定campaign/ordinal/session/
  root/policy与launch id；task/envelope/request也从outer launch删除。Codex先封存entry message、
  bounded drain admission、terminal status和唯一execution-task workspace read，随后才原子grant
  authority。executor通过canonical lane tools建立lane，current assignee使用极小
  `attempt.create`，Host finalizer二次校验assignee并late-bind canonical attempt。finalization
  policy删除hidden exact `task.create` matcher，exact-three closure改从canonical kind/role/
  assignee/finish cardinality计算。每个terminal response exact绑定
  `runtime.command.finished`；digest-only status不是proof。qualification以real public FastAPI
  client、production composition/file-SQLite和deterministic runtime覆盖positive、wrong task/
  actor、reassignment、legacy route和deleted surface，不用private service/manual registry/
  synthetic receipt。Harness不替agent选择task、lane或scientific action，只拒绝不真实的binding。

- [x] Generic dispatch hook 与 scripted happy path 是否把 AOX acceptance 反向写成 agent phase policy。

  证据：即使删除 automatic observer/driver，composition-injected precondition 仍能在 owning
  handler 前拒绝早 reporting delegation、不同 task order 或 incomplete-but-authorized action；
  原有 AOX reachability scenario 只证明一条预写 trace 可达，无法对这种策略收窄报红。

  修正记录：删除 `tool_dispatch_precondition` 全传播链与 AOX policy module，把 source-linked
  report evaluator移到public product closure。新增closed owner/constraint registry、Core bounded
  Hypothesis trace properties，以及 real FastAPI/file-SQLite 的 `strategy-neutrality` 和
  `world-fidelity` qualification families；current report/AOX receipt `@3` 绑定 owner registry 与
  transformation results。authority/effect/fence/quiescence等不可违反边界仍留在canonical owner，
  exact-three/report/17-deliverable只作为最终eligibility，不固定agent tool序列。

- [x] Lane 与 session lease 是否只是历史复杂度，应随 recovery machine 一并删除。

  证据：Lane symbols 仍有 105 个 Python 文件消费者，覆盖 Host/CLI API、cwd/branch、
  task/executor workspace isolation 与 projection；session lease 则隔离 background runtime、
  durable command 与 manual/test scheduler 对同一 session 的并发 mutation，并提供 fencing
  token。二者都仍保护可观察的资源边界。

  决定：本 slice 保留 Lane entity/API，但降级为 concrete isolation resource；删除随
  obligation/disposition 消失的 lane equality/copy，不把 nullable session-scoped provenance
  强接到当前 lane。保留 single-process `SessionRuntimeLease`，因为同进程也存在多个独立
  worker/command authority，去掉它会重新引入 concurrent advancement 与 stale write，而不是
  单纯减少策略代码。后续若要删除 Lane，必须先把 cwd/branch/workspace ownership 迁移到一个
  更小的 task-owned binding；不得以字段数量代替消费者证据。

- [x] AOX public authority consumption target 是否把 owner truth 重复交给 operator 组合。

  证据：r80 的 plan basename 是 `attempt-authority.json`，public `consume-authority` 却要求调用者再次
  提供 deterministic sibling；操作员去除 `.json` 后组合出 `attempt-authority.consumed.json`，canonical
  owner 正确以 `attempt_authority_consumption_target_mismatch` 在 receipt 前拒绝。authority 未消费且
  零 product execution，说明 safety guard 正常，但 public composition 对没有策略自由度的内部派生值
  产生了不必要摩擦。CLI 自己还复制了一次 expected-target 检查，而 focused tests 都由 helper 预填正确值，
  qualification 也用 monkeypatch 绕过真实 target seam。

  修正记录：保留 `attempt_authority_consumption_path(plan_path)` 为唯一 owner；consume/preflight 正常
  路径从 canonical resolved plan 推导完整 basename sibling。旧参数仅作 exact compatibility assertion，
  错误值仍 fail closed；same-directory、no-replace/no-follow、fsync、`0400`、one-use/tamper 与 schema
  不变。public parser-to-handler 与 qualification 覆盖默认/无后缀/多点名、正确/错误断言和 no-effect
  负例。外部 caller 状态 unknown，因此本轮不 breaking-remove 参数。该收口减少 shadow truth，不替 agent
  选择任何 scientific action、task、drain cadence 或失败策略。

- [ ] AOX formal preflight failure 的 current stage 是否仍能准确表达实际 launch 边界。

  当前债务：`aox_formal_preflight_failure@1` 的 `failed_stage` 保留
  `effective_config_pre_slot_claim` 历史措辞，但 current preflight 已在 claim 前执行完整
  Podman/image/SDK/runtime identity launch guard。inner typed cause 仍保持准确，因此该债务
  不阻断当前 verifier、NO-GO 或后续 fresh preparation。

  实施触发：下一次修改 `FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID`、对应 writer/verifier，或新增
  pre-claim launch failure kind 时，必须引入准确命名的 current schema/stage 闭集，并将 `@1`
  保留为只读兼容；不得在原 schema 下静默改写历史 stage 语义。代码搜索标记：
  `AOX-DEBT-PREFLIGHT-STAGE-V2`。

- [ ] AOX Host supervision 与 formal slot-failure 模块是否需要先拆分纯证据职责。

  当前债务：`aox_host_supervision.py` 同时包含 POSIX process supervision、root/SQLite
  settlement、receipt seal/validation；`aox_formal_slot_failure.py` 同时包含 public-host 与
  pre-child-ready 两种 source reconstruction、seal、verification 和 reduction。当前仍由同一
  canonical owner 管理且没有第二产品真状态，但继续增长会削弱单一职责和审查摩擦。

  r77 bounded extraction：exact session/message entry 与 runtime-drain closed validation 已提取到
  纯 `aox_public_conductor_contract.py`，由 positive bundle、retirement readiness、pre-grant 与
  formal slot-failure reconstruction 共享；这删除了 `formal_slot_failure` 对 entry bytes 的复制和
  bundle 对历史 `1/8` cadence 的写死。POSIX/root/SQLite supervision 以及两种 failure mode 的整体
  reconstruction/seal/verifier/reducer 仍未拆分，因此本项保持未勾选，不能把这次窄提取描述为全部债务
  已解决。

  实施触发：向前者新增 process/root/SQLite/receipt responsibility，或向后者新增 closure
  mode/evidence reconstruction branch 前，先提取纯 projection/receipt validator 模块；保留
  现有 public import/re-export、JSON bytes、digest、schema、error code 与历史只读兼容，并用
  等价回归证明没有 evidence contract 漂移。代码搜索标记：
  `AOX-DEBT-EVIDENCE-MODULE-SPLIT`。

## 4. 后续工作流

每次后续简化时：

1. 选择一个 checklist item，或一小组强相关 item。
2. 创建 focused implementation task。
3. 为目标 harness 边界补充或更新测试。
4. 实现完成后，回到本文勾选对应项，并补充简短说明或 change / PR 引用。

不要静默删除发现项。如果某个发现项被有意接受为产品策略，应保留该项并勾选，同时说明接受原因。
