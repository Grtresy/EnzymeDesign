# V3 Agent Runtime

## Resident teammate

agent member 是 session-scoped durable identity，拥有 role、capability lease、workspace generation、
private namespace 和 runtime state。LLM process 可以重启，但 member/task/protocol/workspace 状态继续由
control plane 持有。

## Signal 与 drain

message、delegation、protocol delivery 或显式 operator action 产生 durable `AgentRuntimeSignal`。
scheduler claim pending/expired signal 后，在 session runtime lease 下执行一个 bounded turn。

`POST .../messages` 不 drain。`POST .../runtime/drain` 只写 durable command/outbox；独立 command worker
调用 scheduler。`auto_enqueue_ready_tasks` 默认 false，只用于显式 operator/debug/recovery。

## Bounded turn

每个 turn 有 signal、step、tool-result 和时间上限。结束原因（idle、max steps、provider error、lease loss）
写入 runtime outcome，但不自动完成 task。LLM blocking call 在 worker thread 中运行时，coordinator 仍按
TTL 有界 heartbeat；确认 lease 丢失后停止 canonical write。

## Protocol

`task.delegate` 通过 `ProtocolService.delegate()` 原子更新 task assignment、agent relation、inbox 和
wakeup。`protocol.send` 只追加 inbox message/wakeup。recipient 在后续独立 claim 中运行。

handoff 中的文件只能是 verified published `RevisionPathRef`。mutable path、private ref、Host path 或
历史不可采用 ref 均拒绝。

## Task terminal

`task.update` 只编辑普通字段和非终态。`task.finish` 校验 assignee、dependency、finish evidence 和
idempotency 后写业务终态。下列事实都不等价于完成：

- runtime idle 或 signal consumed；
- protocol message sent；
- external job succeeded；
- report/scientific receipt exists；
- workspace clean 或 revision published。

## Agent workspace

workspace provision/observation/recovery 与 agent process lifecycle 分离。generation 变化会使旧
credential、process callback 和 clean observation stale。agent 可自由进行 Git 操作；publication
service 只在 agent 明确请求共享时验证 exact commit/tree/LFS closure。

## Prompt 与 context

prompt 呈现 task/lane、inbox、approval、workspace/revision、jobs、scientific state 和 safe failure facts，
不嵌入隐藏 scheduler policy。oversized context 使用 durable engine document 或结构化摘要，但不能创建
第二套文件权威 identity。

## Retirement

agent retirement 需要停止新 claim、等待或 fencing 当前 process/workspace authority、完成 namespace/
credential cleanup proof，再写 retirement receipt。retirement 不删除 immutable published revision，也不
改变已完成 handoff/task/scientific evidence。
