# OpenZyme V3 Harness 复杂度审计

## 1. 文档目的

本文记录架构探索过程中发现的 V3 harness 复杂度风险。

本文是追踪文档，不是实现变更。每个发现项前面都带复选框。后续 change 修正一个或多个问题后，应回到本文勾选对应项，并补充简短说明或 change / PR 引用。

默认校准目标：

**OpenZyme V3 应采用严格 harness 边界。**

Harness 负责 tools、state、permissions、recovery、projection 和 execution boundaries。Master agent 与 teammate agents 负责用户意图理解、任务拆解、完成判断、诊断策略和下一步决策。

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

  追加修正记录：message admission 不再把临时 `SessionRuntimeContext.restore_focus` 当作异步 turn 的权威。去重后的显式 `skill_keys` 与 canonical user conversation document 一起持久化，`AgentRuntimeSignal` 仍只保留 `source_ref`；master 在 `working` / `agent.woken` / provider 之前按 exact source 校验并恢复。普通 agent protocol inbox 只提供 wakeup context、不授予 workflow refs；损坏 public user binding fail closed；每条 user source 独立生效，background/manual drain 都不能注入、sticky 或 union authority。

- [x] Host API 在 teammate 终态结果后触发 service-level master response turn，而不是排队 master wakeup。

  证据：历史实现中的 service helper 会在 teammate outcomes 后启动另一次 top-level master loop。

  Doctrine 风险：service 代码决定“teammate 终态结果应触发 master response turn”。这是产品 workflow policy，被嵌入 Host service 逻辑。

  目标边界：teammate result 应表达为 task / protocol / report state 加 `agent:master` wakeup signal；master loop 由 scheduler claim signal 后启动，并由 master agent 自己决定是否回复以及如何回复。

  后续修正方向：将 teammate result 表达为 inbox / protocol state 加 master wakeup signal，让 master loop 自己决定是否回复以及如何回复。

  修正记录：`post_message()` 和 approval resolve 不再在隐藏副作用中触发 master response turn。teammate terminal outcome 只写 task/protocol/report state 并排队 `agent:master` wakeup；master loop 只能由 scheduler claim signal 后启动，由 master 自己决定是否回复用户以及如何回复。配置化 Host 默认由 background runtime worker 推进 scheduler claim，显式 `/runtime/drain` 仅作为 debug/operator/manual recovery 命令。

- [x] `protocol.send(await_response=true)` 同时承担消息投递和同步 teammate 执行。

  证据：`packages/openzyme-core/src/openzyme_core/protocol_tools.py` 在 `await_response=true` 时，会在 `protocol.send` 内部调用 `AgentRuntimeService.drain_session()`。

  Doctrine 风险：通信 tool 变成同步 workflow runner。protocol 语义更难推理，inbox delivery 也和 runtime execution 耦合。

  目标边界：`protocol.send` 应持久化消息并排队 wakeup。运行 recipient 应是单独的 runtime / scheduler action，除非明确文档化为测试或受限便利路径。

  后续修正方向：从正常 protocol 语义中移除 `await_response`，或拆成单独的 `runtime.drain` / `agent.resume` tool 或 API。

  修正记录：已从正常 `protocol.send` 语义中移除同步 teammate 执行。`protocol.send` 现在只持久化 message 并排队 wakeup signal；`await_response` / `max_steps` 参数会返回 `sync_execution_not_supported`，recipient turn 由 scheduler claim signal 后运行。`/runtime/drain` 只能作为 debug/manual claim 工具。

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

  追加修正记录：workspace projection 新增 diagnostic-only `runtime_state`，明确区分 `agent_turn_failed`、`runtime_signal_failed`、`task_failed`、`runtime_attention` 与 `outcome_unconsumed` / `capability_outcome_ready`。terminal capability outcome 只表示 evidence ready 和 owner wakeup，不代表 teammate/task completed。该 projection 和 `runtime.consistency.warning` / `runtime.state_attention` events 只提示 follow-up，不自动写 task completed/failed；业务终态仍由 `task.finish` 写入。

- [x] Design / deep-research planner fallback 会掩盖真实 provider 或 contract 失败。

  证据：已删除的旧 graph 路径曾在 LLM planner 异常或非法 action 时调用 heuristic next action，并把 blocked action 重新加入 `allowed_actions`。已删除的旧 deep research graph 曾在缺少 model 或 researcher 未调用 search 时编造 supervisor plan、tool call 和硬编码 enzyme search query。

  Doctrine 风险：生产路径看似推进成功，但实际的 LLM/tool/provider contract 已失败；测试可能验证的是 fallback 行为，而不是产品真实语义。

  目标边界：planner/provider 失败应产出明确 failed decision / failed dossier；tool argument validation 可以作为 tool error observation 返回给 LLM；unexpected exception 应直接暴露给测试和 live gate。

  修正记录：design graph 保留 state-machine recommendation 作为 prompt guidance，但不再作为恢复 action 执行；missing model、planner exception 和 illegal action 均持久化 failed decision。deep research 删除 fallback supervisor / researcher / query，缺 model 或缺 unit plan 返回 failed dossier，tool 参数 validation 返回 failed observation，unexpected tool/provider exception 继续抛出。

## 4. 后续工作流

每次后续简化时：

1. 选择一个 checklist item，或一小组强相关 item。
2. 创建 focused implementation task。
3. 为目标 harness 边界补充或更新测试。
4. 实现完成后，回到本文勾选对应项，并补充简短说明或 change / PR 引用。

不要静默删除发现项。如果某个发现项被有意接受为产品策略，应保留该项并勾选，同时说明接受原因。
