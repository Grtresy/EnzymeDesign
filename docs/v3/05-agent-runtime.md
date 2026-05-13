# OpenZyme V3 Agent Runtime

## 1. 目标

V3 teammate 默认是 resident agent member，而不是一次性 subagent。

resident 的含义是：agent identity、role、status、task focus、inbox、protocol thread 与 workspace 读视野持久存在；LLM loop 不常驻占用资源，只在 runtime / scheduler 收到明确 wakeup signal 后恢复执行。

参考模型来自 `/home/grtresy/VSCodeRepo/learn-claude-code` 的 s09 Agent Teams、s10 Team Protocols、s11 Autonomous Agents，但 OpenZyme 不采用 JSONL inbox 或 Python thread 作为架构要求。V3 的 canonical truth 仍然是 control plane、event log 与 workspace projection。

## 2. Lifecycle

默认 teammate 生命周期：

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

- master 创建或更新 delegation / assignment
- `protocol.send` 投递给该 teammate 的 unread inbox message
- task board 出现 role 匹配、未阻塞、可认领的 pending task
- approval 被 resolve，且关联 task / protocol thread 需要继续
- engine invocation completed / failed，且关联 task 需要 teammate 消费结果
- background job completion、artifact recorded、report draft feedback 等可继续工作的事件
- user message 或 manual resume 明确要求继续某个 task / teammate

wakeup signal 至少需要记录 recipient agent、reason、session、task/lane/correlation 关联与创建时间。scheduler 恢复 teammate 时，应把 reason 注入 restore context，而不是只让模型从全局状态中猜测发生了什么。

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

teammate 完成或失败时必须通过 `task.update` 显式写入 task 业务终态，并在同一 correlation thread 上写 `delegation_result` 或普通 follow-up response。runtime 不根据 teammate loop 的 `idle`、`failed` 或 `max_steps_exceeded` 推断业务 task 已完成或失败。显式 Host runtime drain 发现 terminal teammate outcome 后，当前实现最多继续一次 top-level master loop；master 通过 restore summary 和 `protocol.thread(correlation_id)` 读取结果并回复用户。approval resolve 只负责写入 approval / execution continuation 状态并排队必要 wakeup，不直接 drain teammate 或触发 master follow-up。

### Failed Delegation Follow-up Flow

失败委托的后续处理由 master 主动判断，不由 `task.delegate`、protocol tool 或 runtime 自动追问：

```text
explicit runtime drain or protocol.thread shows failed / unclear summary
  -> master inspects task state and protocol.thread(correlation_id)
  -> master chooses an existing action:
       protocol.send follow-up to the same teammate
       task.update to mark blocked / failed / completed with evidence
       ask the user for clarification
       report the result in user-facing language
  -> protocol persists unread inbox + inbox_unread wakeup signal
  -> an explicit scheduler/runtime drain wakes the same resident teammate with task/lane/correlation focus
  -> restore context / seed message includes the protocol thread payload; runtime does not generate message-type-specific instructions
  -> teammate replies on the same thread with a normal protocol message
```

`protocol.send` does not run the recipient. It only persists the message, creates the wakeup signal, and returns message / signal / thread metadata. Synchronous execution parameters such as `await_response` and `max_steps` are not part of normal protocol semantics; if a bounded teammate turn is required, it must be performed through an explicit scheduler/runtime drain action.

`protocol.send` recipient resolution:

- exact `AgentMember.agent_id` wins first
- `researcher`, `executor`, and `reporter` are role aliases for default resident agents `agent:{role}`
- if a default resident agent does not exist, `protocol.send` creates it in the current session with `status=idle`
- unresolvable agent recipients return `ok=false/status=recipient_not_found/error_code=recipient_not_found`

Delivery success semantics:

- non-agent recipient: persisted message is `ok=true/status=delivered`
- agent recipient: an `inbox_unread` wakeup signal must exist for `ok=true/status=wakeup_queued`
- persisted message without a wakeup signal is `ok=false/status=wakeup_not_created/error_code=wakeup_signal_missing`
- attempts to pass synchronous execution parameters return `ok=false/status=sync_execution_not_supported`

Protocol payloads may carry follow-up questions, instructions, task ids, summaries, or expected response hints, but message type names such as `diagnostic_request` are ordinary protocol data. A follow-up wakeup must not automatically mark the original task completed. The task changes only when the teammate explicitly updates it through `task.update`; protocol messages are coordination context, not task terminal state.

## 5. Task Auto-Claim

idle teammate 可以自动扫描 task board 并认领工作，但必须受 control-plane policy 约束：

- task status 为 pending / ready
- task 没有未解决 `blocked_by`
- task kind / role requirement 与 teammate role 匹配
- task 未被其他 active teammate claim，或满足显式抢占规则
- priority、dependency 与 lane availability 允许执行

auto-claim 成功后，runtime 将 task owner 设为该 teammate，并可机械地把 `todo` / `blocked` task 推进到 `in_progress`。runtime 将 teammate 状态改为 `working`，把 claim 作为 wakeup reason 写入 restore context，并在 workspace projection 中反映 task owner 与 teammate focus。除 task claim 和 pending approval 这类已文档化机械迁移外，业务终态必须由 agent 显式 `task.update` 写入。

master delegation 仍然存在；auto-claim 是减少 master 微管理的补充机制，不是取消 master 的 team leader 职责。

## 6. Restore Context

每次唤醒 teammate 时，restore context 至少包含：

- teammate identity：agent id、name、role、parent/master、session
- current focus：task、lane、correlation thread、wakeup reason
- unread inbox messages 与相关 protocol thread
- task board 中与该 role/focus 相关的任务
- session-wide artifact catalog、report drafts、engine invocations 与 source refs 的摘要
- memory summary 与压缩后的 continuity notes

发生 compaction 或长时间 idle 后，identity 必须重新注入，避免 teammate 忘记自己是谁、负责什么、应该向谁回复。

## 7. Failure And Recovery Defaults

- teammate work loop 仍然必须 bounded，避免无限 tool-call 循环。
- 任一 tool call 创建 pending approval 后，当前 teammate/master work loop 必须停止并进入 `blocked` / `waiting approval`；同批后续 tool calls 不再执行。
- approval resolved 是唤醒 resident teammate 的 runtime signal；恢复执行前必须先通过 harness/API resolve approval。
- approved execution pipeline 的成功、失败和取消都回到原 executor：Host 只继续 engine invocation、记录 run/artifact/activity 证据并发出唤醒信号，不直接合成用户最终答复。
- task canonical 终态由 task board 表达；protocol/chat 只承载沟通内容。成功执行由 executor 总结结果后通过 `task.update(status="completed")` 完成 task，失败执行只在明确不可修复时由 executor 写入 `status="failed"`、`failure_summary` 与 `failure_ref`。
- 如果 bounded loop 到达 max steps，runtime 可以标记 runtime signal / agent 状态为 failed，但不能据此推断 task 业务终态；master 或 teammate 应通过 protocol thread、task state 与 artifacts 决定下一步。
- 如果 engine completed 但 teammate 未消费结果，scheduler 应唤醒 owner teammate 或 report teammate 进行收尾。
- shutdown 必须通过 protocol handshake：request -> cleanup / approve -> shutdown status；不得默认直接丢弃未读 inbox 或未发布 report draft。
- failed teammate 的 task 应回到可诊断状态，由 master 或其他 teammate 接管，workspace projection 必须显示失败原因与关联 thread。

## 8. Projection Requirements

Workspace projection 中的 `delegation` 不应只表达最近一次 `task.delegate` 调用结果，而应表达 resident team roster：

- agent identity、role、status、task/lane focus
- current correlation id 与最新 message type
- last active time、idle since
- shutdown / failed 状态与可诊断摘要

UI 可以保持 conversation-first，不需要把 agent runtime 暴露成运维控制台；但用户和开发者必须能看出 teammate 是 working、idle、blocked、failed 还是 waiting approval。默认用户 workspace 不展示 raw pending signal count、unread inbox count 或 wakeup reason；这些低层字段只属于 event/debug/diagnostic 视图。等待 approval 时，approval card 与 `workspace.pending_approvals` 是 canonical UI 信号；后端不得把 waiting approval 表述成最终完成消息。
