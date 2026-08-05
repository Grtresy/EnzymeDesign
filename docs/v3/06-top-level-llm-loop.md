# OpenZyme V3 Top-Level LLM Loop

## 1. 目标

本文定义 V3 顶层真实 LLM master-agent harness loop 的实现边界。

它只描述 master agent 如何在 scheduler 启动的顶层会话回合中与模型、tools、memory、workspace projection 协作，不描述 capability engine 或 teammate agent 内部 loop 的细节。

## 2. 基本原则

- 顶层 loop 由 OpenZyme 自己维护
- 顶层只复用 LangChain / LangGraph 的模型接入与 tool-calling 能力
- 顶层不引入新的 graph / agent orchestration
- capability engine 内部可以继续使用 LangGraph
- conversation、task、lane、approval、memory、engine invocation、controlled-operation execution、continuation 与 mutation scope 仍以 control plane 为真状态
- 顶层 loop 的职责是支撑 master agent 与用户对话、编排 task、发起 delegation，而不是直接承担所有具体工作执行
- 顶层 loop 默认不直接扮演 teammate worker；delegation 后的具体推进应由 teammate loop 在共享 workspace 上继续完成
- 顶层 loop 只能由 scheduler acquire session runtime lease 并 claim `agent:master` wakeup signal 后启动；REST handler 只持久化用户动作并排队 signal

一句话约束：

`Top-level harness loop stays custom, but scheduler is the only normal loop launcher. Reuse LangChain for model binding and tool-calling only.`

## 3. 顶层回合流程

```text
user message
  -> persist message content + inbox envelope
  -> enqueue agent:master wakeup signal
  -> scheduler acquires session runtime lease
  -> scheduler claims signal with lease token / fencing token
  -> build restore context
  -> build AgentStepContext + typed tool router
  -> preflight prompt budget
       >= 85%, including initial emergency -> one bounded compaction -> rebuild
       rebuilt >= 90% -> fail before provider
       >= 90% after rebuild -> structured context_budget_exceeded failure, no provider call
  -> call top-level master-agent model with router-derived V3 tool catalog
  -> tool calls?
       yes -> dispatch tools through the same router -> persist side effects
              -> artifactize over-budget tool results if needed
              -> feed bounded tool observations back into model
              -> effect-known failure remains an ordinary observation;
                 agent retains the remaining bounded strategy space
       no  -> persist assistant output and end turn
  -> waiting state?
       delegation -> persist wait state and return
       durable approval/external operation -> park exact process, persist continuation, release turn
  -> auto compact
  -> project workspace
```

session runtime lease 只限制“谁有权推进当前 session runtime”。它不判断业务完成，也不替代 signal claim lease、execution lease、continuation delivery claim 或 mutation writer fence。background runtime、`RuntimeCommandWorker` 与测试 scheduler 在执行 bounded batch 时共享 session ownership；`/runtime/drain` POST 只写 durable command 并返回 `202`，不持有 lease。locked command 应返回脱敏 diagnostic，而不是并发推进。durable approval/provider/HPC wait 必须 park continuation 并释放当前 signal/session authority，不能让 agent turn 继续占有 external-operation wall time。

After every tool call, master must first read the tool-result envelope fields `ok`, `status`, `summary`, `error_code`, `hint`, and `details`.

- if `ok=false`, master must not assume the requested action completed
- if `status` is `recipient_not_found`, master should choose an existing agent id or a valid role alias
- if `status` is `wakeup_not_created`, master should treat the protocol delivery as incomplete even if the message was persisted
- if `status` is `sync_execution_not_supported`, master should remove synchronous protocol execution arguments and rely on scheduler wakeup
- if `task.delegate` returns `wakeup_queued`, master should treat delegation as queued, not completed; teammate execution starts only after scheduler claims the teammate signal
- if a later scheduler turn, runtime consistency warning, or protocol thread shows failure / unclear summary, master should inspect task state and `protocol.thread(correlation_id)`, then choose an existing action: send a follow-up with `protocol.send`, update non-terminal task fields with `task.update`, call `task.finish` for an explicit business exit, ask the user for clarification, or report the result

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

每次 provider 调用前，harness 先构造 `AgentStepContext`，再用当前 `ToolRegistry` 和允许暴露的 tool descriptors 构造 typed tool router。router 输出模型可见 canonical `ToolSpec`，`ProviderToolAdapter` 再把 `ToolSpec` 转成 OpenAI-compatible provider schema，并保留 `canonical_to_provider` / `provider_to_canonical` 映射。模型返回 tool call 后，adapter 必须先把 provider-visible name 恢复为 canonical dotted name，harness 再用同一个 router 和同一个 `AgentStepContext` dispatch tool invocation。

trace 只保存公开 step metadata：`step_id`、`agent_id`、`actor_kind`、`role`、focus ids、runtime signal ids、`restore_context_digest` 和 `tool_catalog_digest`。`llm_trace_step -> workspace.agent_traces` 必须经过稳定 public projection helper / allowlist：trace entry 只暴露 `trace_id`、`actor_ref`、`actor_kind`、`display_name`、`role`、`call_index`、`created_at`、`response_text`、`tool_calls`、`step_id`、`tool_catalog_digest`、`restore_context_digest`、`projection_schema_version` 与 sanitized `agent_step`；`agent_step` 只暴露 `step_id`、`session_id`、`agent_id`、`actor_kind`、`role`、`call_index`、`task_id`、`lane_id`、`correlation_id`、`signal_id`、`wakeup_reason`、`restore_context_digest`、`tool_catalog_digest`、`created_at`。trace 不保存完整 restore context、完整 prompt / `initial_prompt`、memory summary、完整 tool schema、artifact storage URI、Host path、runner path、SSH/runner config、provider secret、tool result content 或 sandbox host path。

`tool.invoked` / `tool.rejected` / `tool.completed` 保持 diagnostic/runtime event 语义，用 `agent_id`、`actor_kind`、`role`、`call_index`、`step_id`、`tool_catalog_digest` 与 `restore_context_digest` 关联回当前 step，并只带 `side_effect`、`supports_parallel`、`ok` / `status` / `error_code` 等公开诊断字段。Web UI 可以把这些事件追加到 `activity_feed` 并按事件去重，但不能由此新增 Codex thread / turn 顶层状态或默认 workspace 顶层分区。

legacy function handler 仍可通过 `registry.register(name, handler)` 注册；进入模型调用前由 router 包装成 `ToolRuntime`。长期方向是把 tool spec、visibility gating 和 dispatch 放入 typed runtime，而不是让 prompt catalog、provider adapter 和真实 dispatch 各自维护一份 truth。

capability engine tools 必须走 first-class runtime path：engine 的 `register_tools()` 调用 `registry.register_runtime(runtime)`，runtime 的 `spec()` 生成模型可见 schema，`governance()` 决定 master / teammate / role surface，`validate()` 负责 dispatch 前参数错误，`dispatch()` 进入真实 engine handler。`EngineDescriptor.tool_names` 只作为 engine 摘要和一致性约束；兼容期的 `engine_tool_descriptors()` 只能从 registered runtimes 派生，不能再作为 execution / deep_research 的第二份 schema 权威。

runtime governance 也是 router contract 的一部分。每个 `ToolRuntime` 必须提供 `governance(step_context)`，至少表达 role scope、side effect、approval requirement、parallel support 与 result budget policy。legacy function handler 的默认治理保持保守：不可并行、写 side effect、不隐式要求 approval、role scope 为空。

模型返回 tool call 后，harness 不再以 driver 私有 descriptor map 作为最终 tool availability truth。`ToolRouter` 负责判断 tool 是否注册、当前 step 是否可见，以及 `required` / `enum` schema 是否满足；不可见工具返回 `ok=false/status=tool_not_visible` 的标准 tool result，未注册工具继续返回 `unknown_tool`。`task.delegate` 的缺参友好提示保留在 router validation 返回的 tool result envelope 中。master 与 teammate driver 都走同一 router validation/dispatch 路径。

Host 不得把 session/workflow-specific `tool_dispatch_precondition` 注入 master 或 teammate
runtime。Router 只拥有通用 schema、visibility、governance 与 writer-fence 边界，随后直接进入
owning handler。外部 authority 固定的是 owner-local actor/assignment/lifecycle/effect/fencing/
quiescence/integrity 等真实 mutation constraints，不是 tool 顺序、task cardinality、report
handoff 或某个 phase。agent 对 ordinary no-effect observation 可以修正、换路、读取、解释、
求助或结束 bounded turn；这些差异不能产生 recovery obligation、synthetic wake 或 Harness fatal。
AOX exact-three、report/fault closure 与 deliverable completeness只在 final public product
closure/offline verification中判定。

role surface 由同一个 router 判定：master 即使注册了 engine runtimes，也不会直接看见 `deep_research.start` 或 `execution.pipeline.start`；researcher 可见 deep research runtime tools；executor 可见 execution compatibility runtime tools 与 sandbox-first 工具。provider adapter 只能消费 router 输出的 `ToolSpec`，不能绕回 engine descriptor 或 teammate descriptor 拼 schema。MICU 的 `task.create -> task_create` alias 只属于 provider request / LLM debug 层；workspace trace、tool invocation、tool result 和 runtime events 必须只出现 canonical dotted name。

当 session/attempt 启用 generic mutation closure 时，harness turn 是显式 `agent_turn` writer。router 只为真正 mutating 的 producer 注册额外 writer：artifact/research publication 使用 `artifact_publisher`，report draft/publish 使用 `report_publisher`；对应 read tool 不得虚构 writer。所有模型请求进入 `LlmInvocationRuntime` 前注册 `live_token_ledger` writer，完成或失败后显式退休。event/outbox、sandbox process、controlled execution 和 continuation delivery 由各自 composition boundary 注册；不能仅因 tool dispatch 返回就推断这些 child writer 已退休。

`supports_parallel` 只记录为 runtime governance metadata；本阶段顶层 loop 仍不启用真实并行 dispatch。

master 与 teammate 的单个 provider response 最多按返回顺序 dispatch 前 `3` 个
tool call。该上限不能靠静默截断实现：driver 必须把 provider 返回的全部 call 投影到
同一个公开 LLM trace，并为每个 overflow call 产生
`ok=false/status=rejected/error_code=parallel_tool_call_limit_exceeded` 的结构化
`ToolResult`，明确 `effect_certainty=no_effect` 与
`retry_eligibility=same_phase_safe`。harness 为其持久化 failure observation，发送
`tool.rejected` 与 `tool.completed`，但不发送 `tool.invoked`、不进入 router dispatch。
下一次 provider request 前，每个原始 call id（包括 overflow）都必须有且仅有一个匹配
的 `ToolMessage`；否则 assistant message 中残留的未闭合 function call 会让 provider
拒绝整个后续 transcript。这个纠正不提高并发上限，也不授权 harness 代 agent 选择要
重试的工作。

一个 provider response 是一个有序 tool-call batch，不能把“前三项 eligible”与
“第 `4+` 项 overflow”当成两个互不相关的生命周期。harness 在 dispatch 任何 eligible
call 前，先为全部 overflow 持久化 no-effect failure observation；公开 tool results 和
events 仍按 provider 原始 call 顺序结算。若前 `3` 项中的某一项创建 pending approval、
成功执行 `task.finish` / `attempt.create` / `scientific.attempt.close` / runtime suspension，或因 authority、integrity、
`dispatch_in_doubt` 等边界失败而提前返回，则其后的 eligible call 必须显式结算为
`tool_call_batch_interrupted/no_effect/verify_then_retry`，并记录 causal call 与
interruption reason；原有 overflow 仍保持
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`。已经进入 dispatch 的
causal call 必须保留自己的精确 failure observation、effect certainty 与 retry
eligibility，例如 `dispatch_in_doubt/reconcile_required`，不得被降级成 no-effect
rejection。所有未 dispatch 项只产生 `tool.rejected` / `tool.completed`，绝不产生
`tool.invoked`。overflow 的预持久化不得提前解析前三项的 task/lane 引用；每个 eligible
call 仍在自身 dispatch 前读取前序 call 已提交的最新 durable state，因此同批
`task.create -> lane.bind_task` 是合法顺序依赖。never-dispatched call 的 ToolResult 与
observation facts 保留返回引用，但 observation 关系字段只绑定当前真实 step context，
不要求未来 task/lane 已存在，也不把未执行目标伪装成 authority。这套结算只呈现世界
事实并闭合 transcript，不自动执行、重试或重排任何后续工作；是否在新的 agent turn
重发，由 agent 读取 durable state 后决定。

## 5. 顶层允许暴露给模型的工具

首批默认暴露工具集：

- `task.create`
- `task.update`
- `task.finish`
- `task.get`
- `task.list`
- `task.next`
- `task.delegate`
- `world.inspect`
- `memory.compact`
- `docs.search`
- `docs.read`

默认使用原则：

- 顶层模型优先通过 `task.*` 与 `delegation` 相关工具编排内部工作
- 顶层模型和 teammate 应优先用 `world.inspect` 读取 task、artifact、approval、operation、outcome、runtime warning、tool schema 和 route policy 等结构化事实；该工具不得提供 recommended_actions 或硬编码 workflow template
- `task.finish` 是推荐的业务任务出口；成功调用后 harness 立即停止当前 master/teammate loop，不再执行同批后续 tool calls，也不把该 tool result 喂回模型继续探索。同批后续 call 仍按上面的 batch interruption 契约获得持久 no-effect observation。可选 `evidence_refs` 必须使用 schema 显式给出的 closed `<kind>:<id>` wire contract；agent 选择 evidence，repository 解析当前 session ref，runtime 不猜 kind 或补 prefix。`task.update` 保留为普通字段编辑和非终态状态迁移。
- successful `attempt.create` 使用相同 terminal-action/batch-settlement 机制，只记录 admission intent，不写 task terminal。当前 teammate turn 在 request 提交后结束；Host 等 writer 退休再 finalization，并以 exact admitted attempt id 排队 source-bound wake。
- successful `scientific.attempt.close` 使用同一 terminal-action/batch-settlement 机制，但只记录 closure intent：它不写 task terminal，也不代表 final closure。失败的 close 保持 non-terminal；成功后只有在 requesting `AGENT_TURN` writer 与其 interrupted-call settlement 全部退休后，Host finalizer 才可建立 quiescence 与 immutable closure。
- `scientific.attempt.close` 不要求或持久化同一 response 的 companion text；assistant answer 走普通 conversation path。Core 只接受 exact attempt task 当前 canonical assignee，并在 request 与 finalization 两处验证 assignment。successful close 只写 immutable intent 并退休 turn，失败/rejected close 不留下部分 closure state。
- successful scientific transition handoff 不走 ordinary teammate-result 的 generic
  master notification。Host-finalized exact owner wake 是该 transition 唯一 successor；
  ordinary teammate completion 与 max-step budget-replan 仍保留各自 master wake 合同。
- Host finalizer 为 admitted attempt、immutable closure 或 typed finalizer failure 排队
  source-bound `MANUAL_RESUME`。runtime 使用一个通用 canonical wake-facts projector：
  先按 source identity 解析 attempt / closure / `FailureObservation`，再精确核对 claimed
  signal、actor、session/task/lane/correlation、request graph、derived lifecycle 与当前
  task assignment。facts 必须先于 task prose 进入 fresh master 或 teammate prompt；
  master 以有界 ephemeral system context 接收，不把 facts 写入 conversation。不得依赖上一
  turn conversation、字符串 prefix、隐藏状态或 AOX policy。admission facts 明确该 exact
  attempt 已提交，不能用重复 `attempt.create` 代替继续执行；closure facts不完成业务
  task；failure facts保留 exact source/error/effect/retry，并对 optional facts/evidence
  暴露 count、digest 与 truncation marker，不自动 retry。task 已 terminal 时复用 generic stale-signal
  mechanical completion。binding 漂移或 durable event 无 canonical record 时在模型前
  fail closed；完全不解析为 canonical transition/failure 的 ordinary manual resume
  保持原行为。
- assistant text 本身从不完成 task、委派 reporter、请求 scientific closure 或产生
  acceptance eligibility；它可以正常持久化，不再经过 session-scoped response veto。需要
  durable state change 时，agent 必须实际调用相应 domain tool。
- historical AOX `aox_cutover_formal_tool_precondition@1`–`@6` 只用于解释旧 evidence；
  current runtime 没有该 policy 或 generic hook。canonical task/report/scientific mutation
  分别由其 domain owner 校验，source-bound finalization receipt 与 exact AOX completeness
  由 product-closure evaluator/offline verifier复核；它们不检查或拒绝 assistant response，
  不自动 delegate/auto-enqueue，也不规定 handoff 策略。
- 顶层模型和 teammate 需要能力用法说明时，默认通过 `docs.search` / `docs.read` 读取受控文档库，而不是通过 skill 文档把 execution 用法塞入上下文
- 领域 SOP 不得由 prompt 关键词、task subject 或模型调用 `skill.load` 隐式激活。调用方只能通过结构化 `skill_keys` 传入完整 `workflow:<id>@<semver>#sha256:<manifest-digest>`；message admission 将去重后的选择绑定到 canonical user conversation document，scheduler 仅从 exact user-message signal source 恢复，不能由 drain/operator 或普通 inbox payload 注入。registry 在 provider call 前校验 manifest digest、固定 document version/digest，并在实际 teammate tool/capability surface 上验证 requirements。delegation payload 持久化同一 binding，teammate restore 时再次对照当前 registry，任何缺失或 drift 都 fail closed
- workflow knowledge pack 只表达版本化知识、所需 capability/tool 与真实约束，不替 master/executor 选择步骤；普通用户文本即使包含 AOX、HMM、research 等词也不得改写 delegation 或隐藏可用工具
- 顶层模型不应把用户请求直接裸翻译成 capability invocation
- `deep_research.start` 以及迁移兼容的 execution engine start 调用默认应由 teammate loop 围绕明确的 `task_id` 发生，而不是由 master 直接调用；execution teammate 的稳定 authoring path 是 sandbox-first，不是让 master 或 executor 直接编排 `execution.pipeline.start`
- 任一 capability tool 或其下游 SDK/supervisor 创建 pending approval 后，当前 loop 必须停止当前 planning batch；不得继续执行同批后续 tool calls，也不得再进入下一轮 LLM planning。同批后续 call 必须先按 batch interruption 契约写入持久 no-effect observation。只有 canonical durable pending approval 与 terminal `runtime_suspended` ToolResult 可以产生 `WAITING_APPROVAL`；status 与 approval identity 必须双向一致。durable SDK operation 则 park exact sandbox process、持久化 continuation，并让当前 bounded turn 在有界时间内释放 signal/session authority
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
- approved execution pipeline completion 不直接进入 chat；Host 记录 invocation/run/artifact/activity 后只排队 executor wakeup signal。scheduler 恢复 executor；executor 读取 workspace evidence，并通过 `task.finish` 与 protocol result 显式写入业务结果，再排队 `agent:master` wakeup。master 由 scheduler 恢复后，基于 restore context 和 `protocol.thread(correlation_id)` 决定是否向用户汇报工具级结果摘要。`Pipeline sandbox completed` 只能作为内部 wrapper/run metadata，不得包装为 `Execution finished: ...` 发送给用户。
- `workspace.runtime_state` 是请求时计算的 diagnostic projection：`agent_turn_failed`、`runtime_signal_failed`、`runtime_attention` 或 `outcome_unconsumed` / `capability_outcome_ready` 都不能自动写 task terminal state，也不在每次 drain 追加 derived warning event。terminal capability outcome 只作为 evidence 和 wakeup source；业务 task exit 仍只能由 `task.finish` 或已文档化机械迁移完成。
- `world.inspect` 可把 `workspace.runtime_state`、pending approval、paused/blocked/outcome-ready、controlled operation 与 engine invocation 对应关系聚合为模型可读事实；它不能替代 `task.finish`，也不能把查询结果解释为固定下一步。teammate 的 `capabilities` section 绑定当前 task，master 保留既有显式 session-wide 权限；newest-first facts page 最多 20 个 invocation、每类 8 个 closed opaque refs、serialized facts 64 KiB，只返回状态、时间、`output_ref` 与 document/artifact/evidence/source/gap counts，不复用 UI rich projection，也不内联 `documents`、`output_document`、`output_payload`、evidence 正文、source refs 或 gaps。当前 repository hydration 成本尚未有界，后续窄列/lazy/cursor 重构按独立架构提案推进。
- streaming events 继续存在，但不再是刷新恢复聊天内容的唯一来源
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline

## 7. Compaction 规则

- 每次 master / teammate 发起 tool-calling provider 调用前，harness 必须按模型 profile 估算完整待发送 payload：system prompt、messages、tools schema 和待回灌 tool observation。
- 默认阈值是 context window 的 `80% / 85% / 90%`：达到 80% 记录 `llm.context_budget.warning`；达到 85%（包括初始已经达到 90% emergency）先执行一次 bounded auto compaction 并刷新 restore context；只有 rebuilt payload 仍达到 90% 才返回结构化 `context_budget_exceeded`，不得调用 provider。该单次补救不能循环压缩或绕过最终门槛。
- GLM-5.1 默认 profile 为 `context_window_tokens=200000`、默认输出预留 `65536`、最大输出 `131072`。未知模型必须使用显式 env override，否则使用保守 fallback 并在事件中标记 profile unknown。
- 第三方 OpenAI-compatible endpoint 不得仅凭 model name 继承另一个 provider 的 context profile。AOX blank-world live effective config 要求显式 `context_window_tokens`，并将当前 campaign ceiling 保守限制为 `200000`；缺失或更大的声明在创建 attempt 前 fail closed。provider tokenizer 不可用时仍可用本地保守估算，但不得重新启用 model-name 的 `1050000` 假设。
- auto compaction 默认写入 `session` scope；有 focused lane 时同时写入 `lane` scope；`task` scope compaction 仍保留显式 tool 或高价值触发。
- session 与 lane auto-compaction 必须分别从 session-wide 与 exact-lane restore scope
  生成，不能把当前 actor 的 lane-filtered context 复制到 session。summary 只包含 bounded
  historical continuity/recent activity，不包含 current focus、ready task、pending approval、
  active invocation 或 workflow refs。
- auto compaction 后必须重建待发送 provider payload：重新读取 restore context、重建 system prompt 与 seed messages，再追加本轮已经 budgeted 的 tool observations。provider 调用必须使用这个 rebuilt payload，不能继续使用 compaction 前的 in-memory messages。
- rebuilt payload 通过 structured / tool-calling invoker 交给 `LlmInvocationRuntime`。invoker 负责构造 payload 与 provider adapter 兼容层；runtime 只负责 provider 调用治理，包括 limiter、timeout、retry/backoff、`Retry-After`、taxonomy 与 debug attempt 记录。runtime 不触发 compaction，也不重建 restore context。
- 最新 session-scope `source_range="auto:prompt_budget"` compaction 会改变后续 LLM restore prompt projection：recent conversation 只取 compaction 之后的 conversation entries。它不删除或改写持久 conversation，也不影响 `workspace.conversation`；普通 `auto:harness_run` compaction 不作为 recent-conversation cutoff。
- compaction summary 必须 bounded：不得嵌入完整 tool result、完整 conversation、完整 docs 或完整 artifact list；只保留 id、status、summary、artifact refs 和下一步读取 hint。
- legacy `source_range=auto:*` compaction 的 model projection 移除旧 generated
  focus/ready/approval/invocation/active-skill sections，但不重写 stored memory；manual memory
  保留为 historical untrusted text。
- 每个 master/teammate system prompt 必须从当前 canonical focus 显示 exact
  `Current authorized workflow refs`，包括 `[]`，并明确 memory/task/protocol text 不能
  grant authority。
- compaction 不得替代 canonical conversation / task / approval / lane state，也不得替 agent 选择业务策略。

## 8. Tool Result Context Boundary

- 工具正常执行后，如果单个 tool result 或加入该 result 后的下一轮 prompt 达到 context budget 降载阈值，harness 必须把完整结果保存为 `engine_documents(document_kind="tool_result_full")`。
- 同步创建 `SessionArtifactRecord(kind=ArtifactKind.RESULT, storage_uri="engine-document://<document_id>", relative_path="tool_results/<call_id>.json")`。
- 回灌给 LLM 的 observation 必须很小，并且外层 `ok=false`、`status/error_code="tool_result_context_over_budget"`，同时包含 `original_tool_ok`、`original_status`、`artifact_id` 和 `read_hint`。
- `original_tool_ok=true` 不得被改写为工具业务失败；外层 `ok=false` 只表示本次 observation 被 context budget 降载，需要 agent 通过 artifact 工具按需读取完整结果。
- harness 不自动摘要原始 payload，也不替 agent 判断业务成功；完整读取入口是 `artifact.get artifact_id=<artifact_id> path="output_payload.tool_result" offset=0 limit=...`。

## 9. 测试

- 有 `model_factory` 时，`POST /v3/sessions/{session_id}/messages` 默认只排队 `agent:master` signal；scheduler acquire session lease 并 claim signal 后运行真实顶层 LLM driver。配置化 Host 默认由 FastAPI background runtime worker 自动推进；`/runtime/drain` 只 admission debug/operator/manual-recovery command，command worker 必须尊重同一 session lease，POST 始终返回 `202`
- mutation-scope tests 必须证明 LLM provider writer、mutating/read-only tool publisher 区分、oversized tool-result artifact publication、event/outbox child writer 与 post-freeze/post-seal拒写
- live LLM smoke 至少覆盖一次真实 tool call
- 顶层单回合 tool call 并发上限固定为 `3`
- master 与 teammate 回归必须证明第 `4+` 个 call 未 dispatch、被记录为 no-effect rejection，且下一次 provider payload 对全部 call id 都有匹配 ToolMessage

## 10. Qualification 与 workflow eval 的区别

architecture qualification 在 non-live、credential-scrubbed 环境验证顶层 loop 所依赖的 authority、
bounded progress、restart/effect/evidence 不变量，不调用真实 LLM，也不评价回答质量。workflow eval
验证产品行为样例，seeded/live smoke 验证特定配置或外部路径；三者不能替代 clean full
qualification admission，qualification 也不能替代 live availability 或 scientific cutover proof。

## 11. Failed-result continuation

每次 tool call 后，top-level 与 teammate driver 都读取 `ok/status/summary/error_code/hint/details`
及 `failure_observation`。`ok=false` 不自动结束 turn：effect 已知时继续把 observation 回灌模型，
由 agent 选择修复、替代策略、求助或 refusal；step budget 不因失败自动增加。

`failure.get` 可恢复完整 safe observation；active tool surface 不再提供
`failure.hypothesis.record` 或 `failure.recovery.record`。agent interpretation 是模型策略，
不建立第二套 canonical task/recovery system。driver/provider 自身失败时不存在可归属的
agent decision，harness 返回 system diagnostic 并结束本次 runtime turn，但不写 assistant
conversation message 或 task terminal state。unknown effect/fencing/authority/integrity
exception 仍穿透普通 tool-result 路径并停止当前 ownership。

normal dispatch、context normalization rejection、parallel overflow 与 interrupted call 的
每个 `ToolResult` 都经过同一个 observation/accounting boundary exactly once。对
`no_effect|terminal_known` ordinary failure，这一步已经完成安全结算；Harness 不再建立
turn-local obligation、closed matcher、settlement event、response veto 或 synthetic
recovery signal。后续成功 read、corrected retry、unrelated action、prose 或空回复均按它们
自己的语义处理，不能反向把已知无副作用错误升级成 boundary fatal。

empty inspection 与 replay 也必须诚实收敛：`task.get` not-found、`task.next` no-ready-work
是 successful closed result；exact `task.finish` 或 source-bound execution start replay
只有在 canonical identity/postcondition 相等时返回 already-satisfied，冲突仍失败。
`WAITING_APPROVAL` 只来自 successful terminal `runtime_suspended` 与可重读的 durable
approval id；runtime 要求 status 与该 id 双向一致，所以失败结果不能靠附带 approval id
冒充成功暂停。open task dependency 仍以 canonical `Task.blocked_by` 表达；它不再创建
failure disposition、condition subscription 或 `RECOVERY_REQUIRED` signal。

step budget 用尽不授权继续同一 signal。driver 写入结构化
`agent_turn_budget_exhausted` 后终止 exact occurrence；scheduler 不原地重放、不追加 steps、
不重开 operation/selection。`agent_can_replan` 只说明 master 可在新的 canonical turn 中读取
task/protocol/artifact/failure/selection facts 后选择策略，不与 exact-signal terminal 冲突。
Core 用 typed `AgentRuntimeOutcomeSettlement` 固化该 runtime occurrence；budget handoff
绑定 source/task/agent/lane/correlation、exact budget observation 与 pending master
successor，而不是让 Host 在 turn 结束后从可变 read model 猜测。这是 signal/batch
ownership receipt，不是 ordinary tool-failure recovery proof。

core receipt 中的 scheduler `completed` 是 batch-settlement 事实，不是 agent/task success。
teammate occurrence 只有在 failed signal、exact canonical budget observation、nonterminal
task 与 unique source-bound pending master wakeup 全部闭合时才可完成这个 handoff；
original signal 仍 failed，master wakeup 仍是独立 turn。master 自身耗尽或任何闭包缺失不能
通过制造 self-wakeup 改成 completed。任何 master/teammate max-step 同时结束当前 bounded
batch：已 claim wave 完成后不再 claim 新 signal，所以 successor 即使在
`max_signals > 1` 的 command 内创建，也只能由下一次 scheduler authority 推进。Host 只聚合
typed occurrence settlement；一次显式 `task.finish(status="failed")` 不会把正常 completed signal
反向改成 scheduler failure。

scientific selection 的真实约束不应靠模型从错误信息或 SOP 猜。详细
`scientific.attempt.inspect` 提供 digest-bound contract、operation signature、
compatible roles 和 readiness gaps；模型显式选择 occurrence/role，并用一次
`scientific.operation.adopt` 原子表达 disposition + effect adoption。Harness 不因
compatible role 唯一就自动调用 adoption，也不把 `seal_ready` 当作 seal/task-finish 指令。
inspection 将 closure intent 与 finalization 分开：
`closure_request_ready=true` 表示 sealed selection 已由 canonical evaluator 证明当前
universe、authority、workflow、process、continuation 与 evidence 都满足本 turn 持久化
agent-authored intent 的 selection-side 条件；sealed state 单独不构成 readiness。
`closure_finalization_ready=false` 可以只说明 requesting turn writer 尚未退休。legacy
`closure_ready` 仍指后一个 Host 阶段，不能被模型解释为“等待另一个 master wake 才能
call close”。

attempt 的 append-only base row 只提供 `record_status`；top-level loop、readiness 与
terminal observation 统一消费 Core 派生 lifecycle。request-only 的现有 `@1`
`status=active` wire 值可以保留，但 `effective_status=closing`、
`lifecycle_phase=closure_requested` 与
`accepts_scientific_mutation=false` 才是决策事实。immutable closure 一旦存在，
effective lifecycle 立即为 `closed`，即使 base row 仍是 `active`；第一次 post-closure
observation 必须返回 exact closed evidence，不得继续等待 row mutation。空的
replay-safe runtime drain 只能证明本次没有可处理 signal/event/output，不是 semantic
progress，也不能替代 terminal convergence。

AOX 不再有 bounded driver 或 two-empty/no-wakeup reducer。Codex 测试员只经 public Host
API/CLI 查看一次 command outcome、pending approval、workspace 与 events，再显式决定下一次
message/drain/approval action。Harness 不生成 campaign-level继续/停止判断，不注册 observer，
也不把 empty outcome、无 wake source 或达到 operator 自定观察次数写成 task、attempt 或
campaign terminal。Host 的 canonical lifecycle/effect/isolation checks 与 offline
bundle/campaign verifier 仍独立 fail closed。

historical closure-stage isolated live loop 已退役；current runtime 不提供从冻结 SQLite
重建 fresh executor signal 的 authority、CLI 或 fallback。sealed historical evidence 只
参与离线 non-adoption 验证。

current AOX executor 在 sandbox 内完成 exact calculations 后，只能调用一次
`artifacts.finalize_bundle`。Host 在任何 artifact/document mutation 前预校验完整 17
draft、source/attempt/selection/calculation identity 与 unified validation，并原子返回
source-bound finalization receipt。后续 `scientific.attempt.close`、execution
`task.finish(completed)` 和 report handoff 都重新验证同一 receipt；缺失或 earliest typed
validation failure 会作为 model-readable no-effect observation 返回。runtime idle、drain
terminal、sandbox success、17 个可见路径或 healthy-empty prose 都不自动生成 receipt、
业务完成、报告、closure 或终答。

AOX formal evidence 对 exact selected attempt 的 controlled-operation no-effect failure 与
sandbox-local `hpc_stage_ref_required|provider_output_path_invalid -> sandbox_exec_nonzero`
chain 使用同一 canonical wake/evidence contract。
绑定的 task 仍为 business-nonterminal 且 canonical owner handoff 闭合时，失败只作为
replan evidence；probe、unsafe/unknown effect、retryable/dispatch-in-doubt、binding drift
或显式 task terminal failure 仍立即停止。

public conductor 不维护 per-source one-shot consumption，也不通过 private override 扩大
command；每次请求都受 Host public DTO 和 bounded scheduler contract 约束。immutable closure
出现后，同一 selected chain 的 exact disposed safe history仍可查询但不污染 offline
eligibility；task/report/closure 仍须完整。work 未闭合且不存在 wake source时，conductor
只能报告当前 public facts并停止或请求新 authority，不能由 Harness 合成业务失败。

## 12. AOX launch 与 agent control 的分界

formal claim/preflight/supervision只建立一次launch slot和local Host process，不建立scientific
attempt。entry message之后，top-level/master可创建exact execution task并delegation；真正的
executor在自己的bounded turn中使用`lane.create`/`lane.bind_task`，再调用极小
`attempt.create(envelope_id,idempotency_key)`。Codex conductor不能通过public generic
scientific mutation route绕过agent，也不能调用Host finalizer；这些public surfaces已删除。

Host finalization产生的owner wake是唯一把canonical late-bound attempt facts送回模型的路径。
top-level loop不得把slot `launch_id`、root name、outer task id、command terminal或process exit
提升为attempt/lane/admission truth。后续inspect/export/bundle只消费repository中的真实control
graph。这样outer conductor负责何时提供世界变化，agent负责策略性scientific actions，Host
负责authority、identity、fencing与effect truth。
