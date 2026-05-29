# OpenZyme V3 Top-Level LLM Loop

## 1. 目标

本文定义 V3 顶层真实 LLM master-agent harness loop 的实现边界。

它只描述 master agent 如何在 scheduler 启动的顶层会话回合中与模型、tools、memory、workspace projection 协作，不描述 capability engine 或 teammate agent 内部 loop 的细节。

## 2. 基本原则

- 顶层 loop 由 OpenZyme 自己维护
- 顶层只复用 LangChain / LangGraph 的模型接入与 tool-calling 能力
- 顶层不引入新的 graph / agent orchestration
- capability engine 内部可以继续使用 LangGraph
- conversation、task、lane、approval、memory、engine invocation 仍以 control plane 为真状态
- 顶层 loop 的职责是支撑 master agent 与用户对话、编排 task、发起 delegation，而不是直接承担所有具体工作执行
- 顶层 loop 默认不直接扮演 teammate worker；delegation 后的具体推进应由 teammate loop 在共享 workspace 上继续完成
- 顶层 loop 只能由 scheduler claim `agent:master` wakeup signal 后启动；REST handler 只持久化用户动作并排队 signal

一句话约束：

`Top-level harness loop stays custom, but scheduler is the only normal loop launcher. Reuse LangChain for model binding and tool-calling only.`

## 3. 顶层回合流程

```text
user message
  -> persist message content + inbox envelope
  -> enqueue agent:master wakeup signal
  -> scheduler claims signal
  -> build restore context
  -> call top-level master-agent model with V3 tool catalog
  -> tool calls?
       yes -> dispatch tools -> persist side effects -> feed tool results back into model
       no  -> persist assistant output and end turn
  -> waiting state?
       approval / delegation -> persist wait state and return
  -> auto compact
  -> project workspace
```

After every tool call, master must first read the tool-result envelope fields `ok`, `status`, `summary`, `error_code`, `hint`, and `details`.

- if `ok=false`, master must not assume the requested action completed
- if `status` is `recipient_not_found`, master should choose an existing agent id or a valid role alias
- if `status` is `wakeup_not_created`, master should treat the protocol delivery as incomplete even if the message was persisted
- if `status` is `sync_execution_not_supported`, master should remove synchronous protocol execution arguments and rely on scheduler wakeup
- if `task.delegate` returns `wakeup_queued`, master should treat delegation as queued, not completed; teammate execution starts only after scheduler claims the teammate signal
- if a later scheduler turn or protocol thread shows failure or an unclear summary, master should inspect task state and `protocol.thread(correlation_id)`, then choose an existing action: send a follow-up with `protocol.send`, update task state with `task.update`, ask the user for clarification, or report the result

## 4. 顶层模型接入

顶层模型接入直接复用现有 OpenAI-compatible / LangChain 封装：

- chat model 初始化
- `bind_tools(...)`
- tool-calling response 解析

顶层不使用：

- 顶层 `StateGraph`
- 顶层 graph node / edge orchestration
- graph checkpoint 作为产品顶层状态真源

## 5. 顶层允许暴露给模型的工具

首批默认暴露工具集：

- `task.create`
- `task.update`
- `task.get`
- `task.list`
- `task.next`
- `task.delegate`
- `memory.compact`
- `docs.search`
- `docs.read`

默认使用原则：

- 顶层模型优先通过 `task.*` 与 `delegation` 相关工具编排内部工作
- 顶层模型和 teammate 需要能力用法说明时，默认通过 `docs.search` / `docs.read` 读取受控文档库，而不是通过 skill 文档把 execution 用法塞入上下文
- 顶层模型不应把用户请求直接裸翻译成 capability invocation
- `deep_research.start` 以及迁移兼容的 execution engine start 调用默认应由 teammate loop 围绕明确的 `task_id` 发生，而不是由 master 直接调用；execution teammate 的稳定 authoring path 是 sandbox-first，不是让 master 或 executor 直接编排 `execution.pipeline.start`
- 任一 capability tool 或其下游 SDK/supervisor 创建 pending approval 后，当前 loop 必须硬阻塞并返回 `waiting_approval`；不得继续执行同批后续 tool calls，也不得再进入下一轮 LLM planning
- reporting 默认不要求 engine start；report teammate 应优先围绕 `report_draft` 推进交付

首批不默认暴露给模型的高风险操作：

- `lane.remove`
- `lane.keep`
- `lane.unbind_task`
- 直接 engine start tools，例如 `deep_research.start` 或迁移兼容的 execution pipeline start bridge

## 6. Conversation 与 Projection

- user / assistant message content 必须被持久化
- `workspace.conversation` 是 canonical chat read model
- conversation 拓扑固定为 user <-> master；teammate output 是内部 protocol/task result，不直接写入 user chat
- waiting approval 的 canonical 信号是 approval card / `workspace.pending_approvals`；后端不得把 pending approval 投影成“执行已完成”类 assistant message
- approved execution pipeline completion 不直接进入 chat；Host 记录 invocation/run/artifact/activity 后只排队 executor wakeup signal。scheduler 恢复 executor；executor 读取 workspace evidence，并通过 `task.update` 与 protocol result 显式写入业务结果，再排队 `agent:master` wakeup。master 由 scheduler 恢复后，基于 restore context 和 `protocol.thread(correlation_id)` 决定是否向用户汇报工具级结果摘要。`Pipeline sandbox completed` 只能作为内部 wrapper/run metadata，不得包装为 `Execution finished: ...` 发送给用户。
- streaming events 继续存在，但不再是刷新恢复聊天内容的唯一来源
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline

## 7. Compaction 规则

- auto compaction 默认写入 `session` scope
- 有 focused lane 时同时写入 `lane` scope
- `task` scope compaction 仍保留显式 tool 或高价值触发
- compaction 不得替代 canonical conversation / task / approval / lane state

## 8. 测试

- 有 `model_factory` 时，`POST /v3/sessions/{session_id}/messages` 默认只排队 `agent:master` signal；scheduler claim 后运行真实顶层 LLM driver。配置化 Host 默认由 FastAPI background runtime worker 自动推进；`/runtime/drain` 只用于 debug/operator/manual recovery
- live LLM smoke 至少覆盖一次真实 tool call
- 顶层单回合 tool call 并发上限固定为 `3`
