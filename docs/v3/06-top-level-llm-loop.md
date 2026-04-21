# OpenZyme V3 Top-Level LLM Loop

## 1. 目标

本文定义 V3 顶层真实 LLM harness loop 的实现边界。

它只描述顶层会话回合如何与模型、tools、memory、workspace projection 协作，不描述 capability engine 的内部 graph 细节。

## 2. 基本原则

- 顶层 loop 由 OpenZyme 自己维护
- 顶层只复用 LangChain / LangGraph 的模型接入与 tool-calling 能力
- 顶层不引入新的 graph / agent orchestration
- capability engine 内部可以继续使用 LangGraph
- conversation、task、lane、approval、memory、engine invocation 仍以 control plane 为真状态

一句话约束：

`Top-level harness loop stays custom. Reuse LangChain for model binding and tool-calling only.`

## 3. 顶层回合流程

```text
user message
  -> persist message content + inbox envelope
  -> build restore context
  -> call tool-calling model with V3 tool catalog
  -> tool calls?
       yes -> dispatch tools -> persist side effects -> feed tool results back into model
       no  -> persist assistant output and end turn
  -> waiting state?
       approval / delegation -> persist wait state and return
  -> auto compact
  -> project workspace
```

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
- `lane.create`
- `lane.bind_task`
- `lane.list`
- `memory.compact`
- `skill.list`
- `skill.load`
- engine tools such as `deep_research.start`, `execution.start`, `reporting.start`

首批不默认暴露给模型的高风险操作：

- `lane.remove`
- `lane.keep`
- `lane.unbind_task`

## 6. Conversation 与 Projection

- user / assistant message content 必须被持久化
- `workspace.conversation` 是 canonical chat read model
- streaming events 继续存在，但不再是刷新恢复聊天内容的唯一来源
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline

## 7. Compaction 规则

- auto compaction 默认写入 `session` scope
- 有 focused lane 时同时写入 `lane` scope
- `task` scope compaction 仍保留显式 tool 或高价值触发
- compaction 不得替代 canonical conversation / task / approval / lane state

## 8. 回退与测试

- 有 `model_factory` 时，`POST /v3/sessions/{session_id}/messages` 默认走真实顶层 LLM driver
- 无 `model_factory` 时，允许回退到 deterministic driver
- live LLM smoke 至少覆盖一次真实 tool call
- 顶层单回合 tool call 并发上限固定为 `3`
