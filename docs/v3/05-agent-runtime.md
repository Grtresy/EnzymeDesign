# OpenZyme V3 Agent Runtime

## 1. 目标

V3 master 与 teammate 默认都是 resident agent member。master 不在 REST handler 调用栈中同步运行，teammate 也不是一次性 subagent。

resident 的含义是：agent identity、role、status、task focus、inbox、protocol thread 与 workspace 读视野持久存在；LLM loop 不常驻占用资源，只在 runtime / scheduler 收到明确 wakeup signal 并 claim lease 后恢复执行。

参考模型来自 `/home/grtresy/VSCodeRepo/learn-claude-code` 的 s09 Agent Teams、s10 Team Protocols、s11 Autonomous Agents，但 OpenZyme 不采用 JSONL inbox 或 Python thread 作为架构要求。V3 的 canonical truth 仍然是 control plane、event log 与 workspace projection。

## 2. Lifecycle

默认 agent 生命周期：

```text
---------+
| spawned |
+----+----+
     |
     v
+---------+      no immediate work       +------+
| working | ---------------------------> | idle |
+----+----+                              +--+---+
     ^                                      |
     | wakeup signal                        | idle timeout / shutdown request
     +--------------------------------------+
     |
     v
+---------+      unrecoverable issue      +--------+
| blocked | ----------------------------> | failed |
+---------+                               +--------+

idle --shutdown handshake--> shutdown
```

Status 语义：

- `spawned`：roster 已创建，但尚未完成首次 restore / work turn
- `working`：runtime 正在为该 teammate 执行 bounded LLM turn loop 或工具调用
- `idle`：没有立即可执行工作，LLM loop 已停止，等待 wakeup
- `blocked`：等待 approval、dependency、resource、human input 或 peer response
- `failed`：发生需要 master 或 operator 处理的异常
- `shutdown`：完成收尾，默认不再接收普通 wakeup

## 3. Wakeup Sources

runtime / scheduler 应把以下 control-plane 变化转化为 wakeup signal：

- user message created，唤醒 `agent:master`
- master 创建或更新 delegation / assignment
- `protocol.send` 投递给该 teammate 的 unread inbox message
- teammate task completed / failed / blocked、protocol reply、report publish 等需要 master 判断的变化，唤醒 `agent:master`
- task board 出现 role 匹配、未阻塞、可认领的 pending task
- approval 被 resolve，且关联 task / protocol thread 需要继续
- engine invocation completed / failed，且关联 task 需要 teammate 消费结果
- background job completion、artifact recorded、report draft feedback 等可继续工作的事件
- user message 或 manual resume 明确要求继续某个 task / teammate

wakeup signal 至少需要记录 recipient agent、reason、session、task/lane/correlation 关联与创建时间。scheduler 恢复 master 或 teammate 时，应把 reason 注入 restore context，而不是只让模型从全局状态中猜测发生了什么。

## 3.1 Scheduler / Worker Boundary

第一版采用单进程 async scheduler：同一 Host 进程内的 scheduler/worker pool 从持久化 `AgentRuntimeSignal` 队列 claim work，并运行 bounded master 或 teammate turn。agent 本身不是常驻进程；常驻的是 `AgentMember` identity、inbox、task focus、memory 和 protocol state。

session ownership 与 signal claim 是两层不同语义：

- `SessionRuntimeLease` 是 session-scoped ownership：同一 session 同时只能有一个 active runtime owner，不同 session 可并行推进
- `AgentRuntimeSignal.claimed_by / claim_expires_at` 是 signal-scoped lease：它只避免同一条 signal 被重复处理，不足以阻止同一 session 内不同 signal 被多个 worker 并发推进
- background runtime、manual `/runtime/drain`、recovery worker 和测试 scheduler 在推进某个 session 前都必须先 acquire session lease
- `/runtime/drain` 是 debug/operator/manual recovery command；如果 session 已由 background/manual/recovery worker 持有未过期 lease，它必须返回结构化 locked/blocked 结果或等价 HTTP conflict，而不能并发推进
- session lease 过期后可由新 owner reclaim，并通过单调 fencing token 让旧 worker 迟到写回失败
- session lease 只管理 runtime 推进权，不判断 task 是否完成或失败

signal claim 语义：

- worker 只 claim `pending` signal 或 lease 已过期的 `claimed` signal
- claim 写入 `claimed_by`、`claim_expires_at`，递增 `attempt_count`，并绑定当前 session lease token / fencing token
- worker 完成 turn 后把 signal 写为 `completed` 或 `failed` 前必须确认仍持有有效 session lease
- retryable failure 在 attempt 上限内可释放回 `pending`，否则保持 `failed`
- stale signal claim recovery 只基于 signal lease，不依赖进程内内存；stale session worker recovery 还必须通过 session lease fencing 拒绝迟到写回
- 没有 LLM 配置或 model factory 不可用时，后台 worker 不应 claim 需要 LLM 的 signal；缺失配置应作为诊断状态暴露

第一阶段不要求跨进程 worker、Redis queue 或共享分布式 limiter。代码边界必须保留这些演进点：session lease 与 signal claim API 是 repository 层能力，scheduler 通过 worker id、session lease 和 signal lease 认领 work，provider/tool quota 通过 limiter 抽象表达，而不是靠线程池大小间接表达。

runtime state consistency guard 是只读诊断层。它可以在 workspace projection 与 events 中报告：

- active/running engine invocation 关联的 task 或 agent 已 terminal / 缺失
- `runtime_signal_failed`、`agent_turn_failed` 与 `task_failed` 的层级差异
- `max_steps_exceeded` / `runtime_exception` 属于 agent turn 或 signal 层，不自动代表 task failed
- task 仍 `in_progress` 但相关 runtime work 全部 terminal failed/cancelled 时标记 `runtime_attention` / `needs_attention`
- capability / engine invocation terminal 而 task 非 terminal 时标记 `outcome_unconsumed` / `capability_outcome_ready`，表示 terminal capability outcome 尚未被 owner 消费；它只作为 evidence 与 wakeup source，不自动 completed

guard 不写 task status。业务终态仍由 master/teammate 显式 `task.finish` 写入；max loop、runtime failure 或 agent turn failure 只产生 runtime attention，不自动写 task failed。

## 3.2 Concurrency And Provider Limits

runtime 并发限制分层表达：

- agent/session/global：限制同时运行的 master / teammate turn 数
- LLM provider：限制 chat/structured/tool-calling model 调用
- research provider：限制 Tavily、PubMed、Semantic Scholar、UniProt、RCSB PDB 等外部检索调用
- execution provider：限制 sandbox/HPC submission 和 runner-side expensive operation

异步调用应直接 await limiter。同步阻塞 SDK 只能通过受控 adapter 在 limiter 内 `to_thread`，不能把线程池大小当成 quota 策略。

LLM provider 调用的统一治理边界是 `openzyme_runtime.LlmInvocationRuntime`：

- structured / tool-calling / chat / connectivity invoker 只构造 provider payload、工具 alias、结构化解析与响应还原
- runtime 统一执行 limiter、timeout、retry/backoff、`Retry-After`、错误 taxonomy 与 LLM debug 记录
- debug 记录必须包含 `kind`、`purpose`、`attempt`、`max_attempts`、`retry_reason`、`backoff_seconds`、`provider_status`、`error_taxonomy`、`final_status` 与可得 usage
- prompt budget preflight、auto compaction、restore context rebuild 与 tool dispatch 状态机仍属于 harness/runtime service，不下沉到 invocation runtime

provider 错误 taxonomy 的默认语义：

- 502/503/504、transport timeout、connection failure：retryable
- 429：只有 transient rate limit 或带 `Retry-After` 时 retryable；usage/quota/invalid/context 类 429 不重试
- 400/401/403、schema/tool argument、context window exceeded：non-retryable

当一次 runtime/provider 失败进入 signal 处理时，scheduler/runtime service 必须复用同一 taxonomy：runtime 内部 retry 成功则 turn 继续；runtime retry 耗尽但 signal 仍有剩余 attempt 时释放回 `pending`；non-retryable 或 signal attempt 耗尽时写为 `failed`。

## 4. Inbox And Protocol Flow

`protocol.send` 的默认流程：

```text
sender teammate
  -> protocol.send(recipient, message_type, correlation_id, payload)
  -> persist InboxMessage + payload_ref
  -> mark message unread for recipient
  -> emit inbox.delivered / agent.inbox_unread
  -> create wakeup signal for recipient
  -> scheduler resumes recipient when capacity allows
  -> recipient restore context includes unread inbox + protocol thread
  -> recipient handles message and acknowledges / replies
```

因此，team protocol 不是普通 chat log。它是有 recipient、correlation、payload、status 和 wakeup 语义的内部协调通道。

request-response protocol 统一使用 correlation id 追踪 pending、approved、rejected、completed、failed 等状态。shutdown、plan review、handoff、clarification、result completion 都应复用同一套 thread/read model，而不是各自发明独立消息机制。

teammate 完成、阻塞、失败或取消当前 task stage 时必须通过 `task.finish` 显式写入 task 业务出口，并在同一 correlation thread 上写 `delegation_result` 或普通 follow-up response。`task.update` 保留为普通 task 字段编辑和 `todo` / `in_progress` 等非出口状态迁移工具；tool handler 必须拒绝 completed / failed / blocked / cancelled 业务出口。runtime 不根据 teammate loop 的 `idle`、`failed` 或 `max_steps_exceeded` 推断业务 task 已完成或失败。teammate terminal outcome 只更新 canonical state / protocol，并排队 `agent:master` wakeup；master 由 scheduler claim signal 后读取 restore context 和 `protocol.thread(correlation_id)`，再决定是否回复用户、追问 teammate、更新 task 或请求用户澄清。approval resolve 只负责写入 approval 与对应恢复状态：agent-level approval 可以排队必要 wakeup；S10 SDK controlled-operation approval 先恢复 Host-owned sandbox continuation，不能直接 drain teammate 或触发 master response turn。

### Failed Delegation Follow-up Flow

失败委托的后续处理由 master 主动判断，不由 `task.delegate`、protocol tool 或 runtime 自动追问：

```text
scheduler master turn or protocol.thread shows failed / unclear summary
  -> master inspects task state and protocol.thread(correlation_id)
  -> master chooses an existing action:
       protocol.send follow-up to the same teammate
       task.finish to mark blocked / failed / completed / cancelled with evidence
       task.update to edit task wording, priority, owner, or non-terminal state
       ask the user for clarification
       report the result in user-facing language
  -> protocol persists unread inbox + inbox_unread wakeup signal
  -> scheduler wakes the same resident teammate with task/lane/correlation focus
  -> restore context / seed message includes the protocol thread payload; runtime does not generate message-type-specific instructions
  -> teammate replies on the same thread with a normal protocol message
```

`protocol.send` does not run the recipient. It only persists the message, creates the wakeup signal, and returns message / signal / thread metadata. Synchronous execution parameters such as `await_response` and `max_steps` are not part of normal protocol semantics; recipient execution is performed by the scheduler after claim. `/runtime/drain` may manually claim signals for debug/operator use, but it is not the product path.

`protocol.send` recipient resolution:

- exact `AgentMember.agent_id` wins first within the current `session_id`
- `researcher`, `executor`, and `reporter` are role aliases for default resident agents `agent:{role}`
- if a default resident agent does not exist, `protocol.send` creates it in the current session with `status=idle`
- unresolvable agent recipients return `ok=false/status=recipient_not_found/error_code=recipient_not_found`

Agent role definitions may be reused across sessions, but `AgentMember` is session-scoped runtime state. `agent:master`, `agent:researcher`, `agent:executor`, and `agent:reporter` are session-local ids; repository and scheduler lookups must use `(session_id, agent_id)`. The internal `member_id` is the storage primary key and should not replace the public session-local `agent_id` in normal workspace/API flows.

Delivery success semantics:

- non-agent recipient: persisted message is `ok=true/status=delivered`
- agent recipient: an `inbox_unread` wakeup signal must exist for `ok=true/status=wakeup_queued`
- persisted message without a wakeup signal is `ok=false/status=wakeup_not_created/error_code=wakeup_signal_missing`
- attempts to pass synchronous execution parameters return `ok=false/status=sync_execution_not_supported`

Protocol payloads may carry follow-up questions, instructions, task ids, summaries, or expected response hints, but message type names such as `diagnostic_request` are ordinary protocol data. A follow-up wakeup must not automatically mark the original task completed. The task reaches a business terminal/exit decision only when master or teammate explicitly calls `task.finish`; protocol messages are coordination context, not task terminal state.

## 5. Task Auto-Claim

默认产品路径是 master 显式调用 `task.delegate`。auto-claim 默认关闭，只作为 operator/debug/recovery 的显式 scheduler option 使用。

auto-claim 启用时也只能做窄范围机械匹配：

- task status 必须为 `todo`
- task 必须没有未完成 `blocked_by`
- task 必须没有 `assigned_ref`
- task kind / role requirement 必须与 teammate role 匹配
- 目标 teammate 必须处于可接收工作的 idle / active resident 状态

`blocked_by` 表示下游输入尚未形成，不是只用于展示的 UI 状态。blocked task 不能被 auto-claim，也不能被 `task.delegate` 提前委派；master 应在上游完成后读取 protocol thread、artifacts 或 task result，更新下游 task 的 description / instructions，再显式委派。

runtime wakeup 也必须执行同一防线：`TASK_AVAILABLE` 只允许 claim `todo + unassigned + no blockers` 的 task；普通 delegation / inbox wakeup 不得把 `blocked` task 机械推进到 `in_progress`。agent-level approval resume 是例外：`APPROVAL_RESOLVED` 可以把已 assigned 给该 agent、且没有未完成 `blocked_by` 的 approval-blocked task 恢复到 `in_progress`。S10 SDK controlled-operation approval 不使用 `APPROVAL_RESOLVED` 恢复 agent turn；它恢复 blocked SDK RPC / sandbox continuation，agent 只在 `sandbox.exec` tool result 返回后继续。

除 task claim 和 pending approval 这类已文档化机械迁移外，业务终态必须由 agent 显式 `task.finish` 写入。

## 6. Restore Context

每次唤醒 agent 时，restore context 至少包含：

- agent identity：agent id、name、role、parent/master、session
- current focus：task、lane、correlation thread、wakeup reason
- unread inbox messages 与相关 protocol thread
- task board 中与该 role/focus 相关的任务
- session-wide artifact catalog、report drafts、engine invocations 与 source refs 的摘要
- executor restore context 还应包含其 persistent sandbox workspace 摘要：`sandbox_workspace_id`、最近显式 materialized artifacts、working copy dirty 状态、最近 source snapshot、最近 execution plan/run 与可检索 sandbox docs 关键词
- memory summary 与压缩后的 continuity notes

master restore context 还必须包含最新 user message、conversation timeline、pending approvals、teammate protocol threads、task state、approval / execution / artifact / report 变化，以及每个 teammate 的 runtime status。发生 compaction 或长时间 idle 后，identity 必须重新注入，避免 agent 忘记自己是谁、负责什么、应该向谁回复。

restore context 受统一 token budget 管理。每次 master / teammate 模型调用前都必须估算完整 prompt；达到 80% 只记录 warning，达到 85% 写 bounded session/lane compaction 并刷新 restore context，达到 90% 显式 `context_budget_exceeded` 失败并停止 provider call。最新 session-scope `MemoryKind.COMPACTION` 且 `source_range="auto:prompt_budget"` 的记录是 LLM restore prompt 的 recent-conversation cutoff：后续 restore 只加载该 compaction 之后创建的 conversation entries；`auto:harness_run` 不触发这个剪枝。自动 compaction 只做上下文治理，不改变 task、approval、lane、conversation、workspace conversation projection 或 protocol 的 canonical 状态。

### 6.1 Agent Step Context

每次 master / teammate 发起 tool-calling provider 调用前，harness 必须构造一个 `AgentStepContext`。它是单个模型调用 step 的执行上下文，不是新的产品真状态，也不能替代 session、task board、lane、approval、protocol 或 runtime signal。

`AgentStepContext` 至少包含：

- `step_id`、`session_id`、`agent_id`、`actor_kind`、`role`、`call_index`
- 当前 `task_id`、`lane_id`、`correlation_id`
- runtime signal 元数据：`signal_id` 与 `wakeup_reason`
- `restore_context_digest` 与 `tool_catalog_digest`

digest 只基于公开 control-plane 元数据和模型可见 tool spec 计算。它不得暴露 full restore context、conversation content、memory summary、artifact `storage_uri`、lane `cwd`、Host local path、runner path、sandbox host path、provider secret 或完整 tool schema。workspace `agent_traces` 可以展示 `step_id` 与 digest，帮助诊断“本次模型调用看见了哪一版 restore / tool catalog”，但不能把 Codex thread / turn 或 provider transcript 当成 OpenZyme 顶层产品状态。

`AgentStepContext` 进入 workspace / SSE 时必须经过 trace public projection allowlist。公开 `agent_step` 只包含 `step_id`、`session_id`、`agent_id`、`actor_kind`、`role`、`call_index`、`task_id`、`lane_id`、`correlation_id`、`signal_id`、`wakeup_reason`、`restore_context_digest`、`tool_catalog_digest`、`created_at`。trace projection 不暴露 prompt / `initial_prompt`、restore context、memory summary、完整 tool schema、Host path、storage URI、runner path、SSH/runner config、provider secret 或 tool result content。

`tool.invoked` / `tool.completed` 只作为 diagnostic/runtime events。它们必须带上 `agent_id`、`actor_kind`、`role` 与 `call_index`，用于把 tool request/result status 关联回对应 LLM step；同时保留 `step_id`、`tool_catalog_digest`、`restore_context_digest`、`side_effect`、`supports_parallel`、`ok` / `status` / `error_code` 等公开诊断字段。它们不能成为新的 Codex-style turn 顶层状态，也不能携带 tool result content 或私有路径。

模型可见 tool spec 与 dispatch runtime 必须来自同一个 typed tool router。legacy `registry.register(name, handler)` 可以继续存在，但进入模型调用前要被包装为 `ToolRuntime`：同一个 runtime 对象负责生成 canonical `ToolSpec` 并执行 `dispatch(step_context, invocation, runtime_context)`。这保证 provider-visible catalog、trace metadata 和真实 tool execution 不会走三套不一致路径。

`ProviderToolAdapter` 是 `ToolSpec` 与 provider-visible schema 之间的唯一转换边界。它接收 router 输出的 canonical `ToolSpec` 或显式 legacy compatibility dict，输出 provider tools、`canonical_to_provider` 和 `provider_to_canonical`。MICU dotted alias 只允许在这里发生；provider response 必须先通过 adapter 恢复为 canonical dotted tool name，再进入 driver/router/harness。`ToolRouter.dispatch()` 只接受 canonical tool name；`task_create` 这类 provider alias 在内部 dispatch 中仍应是 `unknown_tool`，不能作为隐藏 fallback。

`ToolRuntime` 同时承载最小治理 contract：

- `governance(step_context)` 返回 `role_scope`、`supports_parallel`、`side_effect`、`approval_required` 与 `result_budget_policy`
- `validate(step_context, invocation)` 在 handler 执行前返回结构化 validation error 或 `None`
- legacy function handler 默认采用保守治理：`supports_parallel=false`、`side_effect=write`、`approval_required=false`、`role_scope=[]`

`ToolRegistry` 支持两条注册路径：

- `registry.register_runtime(runtime)`：first-class typed path，runtime 必须提供稳定 `tool_name`
- `registry.register(name, handler)`：legacy compatibility path，只有在进入 router 时被 descriptor 包装为 `LegacyFunctionToolRuntime`

构造 `ToolRouter` 时必须先纳入 typed runtimes，再包装剩余 legacy handlers。同名重复的确定性规则是 typed runtime 优先；legacy handler 不得覆盖 typed runtime 的 spec、governance、validation 或 dispatch。非 engine 工具可以暂时继续使用 legacy register，但 engine tools 的模型可见 schema、governance、validation 与 dispatch 必须来自 registered runtime。

迁移期 capability engines 的规则：

- `execution.pipeline.start` / `execution.pipeline.status`、`deep_research.start` / `deep_research.resume` / `deep_research.status` / `deep_research.dossier` 均通过 `register_runtime` 注册
- execution start runtime 只对 executor role 可见，标记 `side_effect=approval` 与 `approval_required=true`；status 是 read
- deep research start/resume runtime 只对 researcher role 可见，标记 external/write 类 side effect；status/dossier 是 read
- `engine_tool_descriptors()` 若仍存在，只能从 registered runtime 的 `ToolSpec` 派生兼容 `ToolDescriptor`，不能再维护 parallel schema
- `ToolRegistry.dispatch(context, invocation)` 只保留 legacy fallback 兼容；master / teammate 模型调用路径必须使用当前 step 的 `ToolRouter.dispatch(...)`

`ToolRouter` 是当前 step 的最终 tool boundary。它负责根据 runtime visibility 与 governance role scope 生成模型可见 catalog，也负责 dispatch 前的 `unknown_tool`、`tool_not_visible`、schema `required` 与 `enum` 校验。master 与 teammate driver 不应各自维护独立 descriptor map 作为最终可用性判断；它们只能做同-turn 参数补全这类产品语义辅助，然后把 tool invocation 交回 router validation。

`supports_parallel` 目前只作为治理 metadata 暴露和记录；runtime 仍按现有 bounded loop 串行 dispatch，不启用真实并行 tool execution。

master 与 teammate 都可以通过 `artifact.list` / `artifact.get` / `artifact.preview` / `artifact.read_text` / `artifact.range` 读取当前 session 的共享 artifact catalog 与文本类 artifact 内容。`artifact.list` 必须分页返回 catalog；`artifact.get` 必须支持对 large output 和 `tool_result_full` 的 `path` / `offset` / `limit` 分页读取。executor 额外通过 `artifacts.materialize` 把授权 artifact 显式搬入 sandbox，再通过 sandbox file/command tools 操作 working copy。读取入口必须使用 `artifact_id` 和安全投影，不得要求用户、teammate 或 pipeline 暴露 Host local path、`storage_uri`、runner path 或 sandbox host path。

## 7. Failure And Recovery Defaults

- teammate work loop 仍然必须 bounded，避免无限 tool-call 循环。
- 任一 tool call 创建 pending approval 后，当前 teammate/master work loop 必须停止并进入 `blocked` / `waiting approval`；同批后续 tool calls 不再执行。
- agent-level approval resolved 是唤醒相关 resident agent 的 runtime signal；恢复 agent turn 前必须先通过 harness/API resolve approval。S10 SDK controlled-operation approval resolved 不是 agent runtime signal，它只授权 Host supervisor 恢复同一个 blocked SDK RPC / sandbox continuation。
- approved execution pipeline 的成功、失败和取消都回到原 executor：Host 只继续 engine invocation、记录 run/artifact/activity 证据并发出唤醒信号，不直接合成用户最终答复。
- task canonical 终态由 task board 表达；protocol/chat 只承载沟通内容。成功执行由 executor 总结结果后通过 `task.finish(status="completed")` 完成 task，失败执行只在明确不可修复时由 executor 调用 `task.finish(status="failed")` 并提供 `failure_summary` 或 `failure_ref`。阻塞退出必须提供 `blocked_reason` 或 `recovery_hint`。
- scheduler 只根据 user message、approval、engine completion、inbox、task availability 等信号唤醒 agent；它不根据 sandbox dirty state、可用 backend 或工具探测结果替 executor 选择 plan、切换本地/HPC 后端、自动重写 pipeline，或把 run 结果自动解释成任务终态。
- 如果 bounded loop 到达 max steps，runtime 可以标记 runtime signal / agent 状态为 failed，但不能据此推断 task 业务终态，也不能把 task 机械写成 failed；master 或 teammate 应通过 protocol thread、task state 与 artifacts 决定下一步。
- 如果 engine/capability completed 但 teammate 未消费结果，scheduler 应唤醒 owner teammate 或 report teammate 进行收尾；teammate 必须用 outcome 作为 evidence 显式调用 `task.finish`，或发送 follow-up / blocked 语义后再通过 task/protocol/report 变化唤醒 master。
- shutdown 必须通过 protocol handshake：request -> cleanup / approve -> shutdown status；不得默认直接丢弃未读 inbox 或未发布 report draft。
- failed teammate 的 task 应回到可诊断状态，由 master 或其他 teammate 接管，workspace projection 必须显示失败原因与关联 thread。

## 8. Projection Requirements

Workspace projection 中的 `delegation` 不应只表达最近一次 `task.delegate` 调用结果，而应表达 resident team roster，包括 master 与 teammates：

- agent identity、role、status、task/lane focus
- current correlation id 与最新 message type
- last active time、idle since
- shutdown / failed 状态与可诊断摘要

UI 可以保持 conversation-first，不需要把 agent runtime 暴露成运维控制台；但用户和开发者必须能看出 teammate 是 working、idle、blocked、failed 还是 waiting approval。默认用户 workspace 不展示 raw pending signal count、unread inbox count 或 wakeup reason；这些低层字段只属于 event/debug/diagnostic 视图。等待 approval 时，approval card 与 `workspace.pending_approvals` 是 canonical UI 信号；后端不得把 waiting approval 表述成最终完成消息。
