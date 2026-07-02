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
  -> build AgentStepContext + typed tool router
  -> preflight prompt budget
       >= 85% -> bounded compaction -> rebuild restore context
       >= 90% after rebuild -> structured context_budget_exceeded failure, no provider call
  -> call top-level master-agent model with router-derived V3 tool catalog
  -> tool calls?
       yes -> dispatch tools through the same router -> persist side effects
              -> artifactize over-budget tool results if needed
              -> feed bounded tool observations back into model
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

### 4.1 Step Context And Tool Router

每次 provider 调用前，harness 先构造 `AgentStepContext`，再用当前 `ToolRegistry` 和允许暴露的 tool descriptors 构造 typed tool router。router 输出模型可见 `ToolSpec`，provider adapter 再把 `ToolSpec` 转成 OpenAI-compatible tool schema。模型返回 tool call 后，harness 必须用同一个 router 和同一个 `AgentStepContext` dispatch tool invocation。

trace 只保存公开 step metadata：`step_id`、`agent_id`、`actor_kind`、`role`、focus ids、runtime signal ids、`restore_context_digest` 和 `tool_catalog_digest`。`llm_trace_step -> workspace.agent_traces` 必须经过稳定 public projection helper / allowlist：trace entry 只暴露 `trace_id`、`actor_ref`、`actor_kind`、`display_name`、`role`、`call_index`、`created_at`、`response_text`、`tool_calls`、`step_id`、`tool_catalog_digest`、`restore_context_digest`、`projection_schema_version` 与 sanitized `agent_step`；`agent_step` 只暴露 `step_id`、`session_id`、`agent_id`、`actor_kind`、`role`、`call_index`、`task_id`、`lane_id`、`correlation_id`、`signal_id`、`wakeup_reason`、`restore_context_digest`、`tool_catalog_digest`、`created_at`。trace 不保存完整 restore context、完整 prompt / `initial_prompt`、memory summary、完整 tool schema、artifact storage URI、Host path、runner path、SSH/runner config、provider secret、tool result content 或 sandbox host path。

`tool.invoked` / `tool.completed` 保持 diagnostic/runtime event 语义，用 `agent_id`、`actor_kind`、`role`、`call_index`、`step_id`、`tool_catalog_digest` 与 `restore_context_digest` 关联回当前 step，并只带 `side_effect`、`supports_parallel`、`ok` / `status` / `error_code` 等公开诊断字段。Web UI 可以把这些事件追加到 `activity_feed` 并按事件去重，但不能由此新增 Codex thread / turn 顶层状态或默认 workspace 顶层分区。

legacy function handler 仍可通过 `registry.register(name, handler)` 注册；进入模型调用前由 router 包装成 `ToolRuntime`。长期方向是把 tool spec、visibility gating 和 dispatch 放入 typed runtime，而不是让 prompt catalog、provider adapter 和真实 dispatch 各自维护一份 truth。

capability engine tools 必须走 first-class runtime path：engine 的 `register_tools()` 调用 `registry.register_runtime(runtime)`，runtime 的 `spec()` 生成模型可见 schema，`governance()` 决定 master / teammate / role surface，`validate()` 负责 dispatch 前参数错误，`dispatch()` 进入真实 engine handler。`EngineDescriptor.tool_names` 只作为 engine 摘要和一致性约束；兼容期的 `engine_tool_descriptors()` 只能从 registered runtimes 派生，不能再作为 execution / deep_research 的第二份 schema 权威。

runtime governance 也是 router contract 的一部分。每个 `ToolRuntime` 必须提供 `governance(step_context)`，至少表达 role scope、side effect、approval requirement、parallel support 与 result budget policy。legacy function handler 的默认治理保持保守：不可并行、写 side effect、不隐式要求 approval、role scope 为空。

模型返回 tool call 后，harness 不再以 driver 私有 descriptor map 作为最终 tool availability truth。`ToolRouter` 负责判断 tool 是否注册、当前 step 是否可见，以及 `required` / `enum` schema 是否满足；不可见工具返回 `ok=false/status=tool_not_visible` 的标准 tool result，未注册工具继续返回 `unknown_tool`。`task.delegate` 的缺参友好提示保留在 router validation 返回的 tool result envelope 中。master 与 teammate driver 都走同一 router validation/dispatch 路径。

role surface 由同一个 router 判定：master 即使注册了 engine runtimes，也不会直接看见 `deep_research.start` 或 `execution.pipeline.start`；researcher 可见 deep research runtime tools；executor 可见 execution compatibility runtime tools 与 sandbox-first 工具。provider adapter 只能消费 router 输出的 `ToolSpec`，不能绕回 engine descriptor 或 teammate descriptor 拼 schema。

`supports_parallel` 只记录为 runtime governance metadata；本阶段顶层 loop 仍不启用真实并行 dispatch。

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

- 每次 master / teammate 发起 tool-calling provider 调用前，harness 必须按模型 profile 估算完整待发送 payload：system prompt、messages、tools schema 和待回灌 tool observation。
- 默认阈值是 context window 的 `80% / 85% / 90%`：达到 80% 记录 `llm.context_budget.warning`；达到 85% 写入 bounded auto compaction 并刷新 restore context；达到 90% 返回结构化 `context_budget_exceeded`，不得调用 provider。
- GLM-5.1 默认 profile 为 `context_window_tokens=200000`、默认输出预留 `65536`、最大输出 `131072`。未知模型必须使用显式 env override，否则使用保守 fallback 并在事件中标记 profile unknown。
- auto compaction 默认写入 `session` scope；有 focused lane 时同时写入 `lane` scope；`task` scope compaction 仍保留显式 tool 或高价值触发。
- auto compaction 后必须重建待发送 provider payload：重新读取 restore context、重建 system prompt 与 seed messages，再追加本轮已经 budgeted 的 tool observations。provider 调用必须使用这个 rebuilt payload，不能继续使用 compaction 前的 in-memory messages。
- 最新 session-scope `source_range="auto:prompt_budget"` compaction 会改变后续 LLM restore prompt projection：recent conversation 只取 compaction 之后的 conversation entries。它不删除或改写持久 conversation，也不影响 `workspace.conversation`；普通 `auto:harness_run` compaction 不作为 recent-conversation cutoff。
- compaction summary 必须 bounded：不得嵌入完整 tool result、完整 conversation、完整 docs 或完整 artifact list；只保留 id、status、summary、artifact refs 和下一步读取 hint。
- compaction 不得替代 canonical conversation / task / approval / lane state，也不得替 agent 选择业务策略。

## 8. Tool Result Context Boundary

- 工具正常执行后，如果单个 tool result 或加入该 result 后的下一轮 prompt 达到 context budget 降载阈值，harness 必须把完整结果保存为 `engine_documents(document_kind="tool_result_full")`。
- 同步创建 `SessionArtifactRecord(kind=ArtifactKind.RESULT, storage_uri="engine-document://<document_id>", relative_path="tool_results/<call_id>.json")`。
- 回灌给 LLM 的 observation 必须很小，并且外层 `ok=false`、`status/error_code="tool_result_context_over_budget"`，同时包含 `original_tool_ok`、`original_status`、`artifact_id` 和 `read_hint`。
- `original_tool_ok=true` 不得被改写为工具业务失败；外层 `ok=false` 只表示本次 observation 被 context budget 降载，需要 agent 通过 artifact 工具按需读取完整结果。
- harness 不自动摘要原始 payload，也不替 agent 判断业务成功；完整读取入口是 `artifact.get artifact_id=<artifact_id> path="output_payload.tool_result" offset=0 limit=...`。

## 9. 测试

- 有 `model_factory` 时，`POST /v3/sessions/{session_id}/messages` 默认只排队 `agent:master` signal；scheduler claim 后运行真实顶层 LLM driver。配置化 Host 默认由 FastAPI background runtime worker 自动推进；`/runtime/drain` 只用于 debug/operator/manual recovery
- live LLM smoke 至少覆盖一次真实 tool call
- 顶层单回合 tool call 并发上限固定为 `3`
