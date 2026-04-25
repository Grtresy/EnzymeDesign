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

## 5. Task Auto-Claim

idle teammate 可以自动扫描 task board 并认领工作，但必须受 control-plane policy 约束：

- task status 为 pending / ready
- task 没有未解决 `blocked_by`
- task kind / role requirement 与 teammate role 匹配
- task 未被其他 active teammate claim，或满足显式抢占规则
- priority、dependency 与 lane availability 允许执行

auto-claim 成功后，runtime 将 teammate 状态改为 `working`，把 claim 作为 wakeup reason 写入 restore context，并在 workspace projection 中反映 task owner 与 teammate focus。

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
- 如果 bounded loop 到达 max steps，但 protocol thread、task state 或 artifact 已显示工作完成，runtime 应优先恢复并交付 completion，而不是只把 delegation 标记为失败。
- 如果 engine completed 但 teammate 未消费结果，scheduler 应唤醒 owner teammate 或 report teammate 进行收尾。
- shutdown 必须通过 protocol handshake：request -> cleanup / approve -> shutdown status；不得默认直接丢弃未读 inbox 或未发布 report draft。
- failed teammate 的 task 应回到可诊断状态，由 master 或其他 teammate 接管，workspace projection 必须显示失败原因与关联 thread。

## 8. Projection Requirements

Workspace projection 中的 `delegation` 不应只表达最近一次 `task.delegate` 调用结果，而应表达 resident team roster：

- agent identity、role、status、task/lane focus
- current correlation id 与最新 message type
- unread inbox count 或 blocked reason
- last active time、idle since、wakeup reason
- shutdown / failed 状态与可诊断摘要

UI 可以保持 conversation-first，不需要把 agent runtime 暴露成运维控制台；但用户和开发者必须能看出 teammate 是 working、idle、blocked、failed 还是 waiting approval。
