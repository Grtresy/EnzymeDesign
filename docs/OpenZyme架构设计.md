# OpenZyme 主线架构设计

## 1. 文档定位

本文档描述当前根仓库主线的 OpenZyme V3 架构边界与实现事实。

它回答四类问题：

1. 当前主线仓库保留哪些系统能力
2. V3 当前产品真状态与顶层架构如何分层
3. 一次 session 在 Host、Harness、Agent Runtime、Capability Engines、Storage、UI 之间如何流动
4. 当前哪些机制已经落地，哪些仍是切换期约束或未完成证明

当前主线采用 V3 的
`session + task board + lane/workspace + approval + resident teammates + explicit runtime commands`
语义。旧 `episode + phase graph` 产品面、接口、包和规格已经从主线删除；新产品行为不再以
`intake -> design -> report_review` 作为顶层真状态，也不再维护双栈兼容入口。

部署边界采用显式双 profile：`local-dev` 只允许 loopback 且使用固定本地 principal；`shared` 必须配置 Bearer principal、project allowlist 与 role，并以 SQLite `SessionAccessRecord` 保存 session owner/access 真状态。共享模式的 mutation 强制 `Idempotency-Key`，approval/lane actor 由 Host 认证结果确定；debug 默认关闭，启用后仍要求 operator/admin 且只返回脱敏记录。近期运行边界仍是单进程、file-backed SQLite，不把该 profile 设计误称为多进程扩展已经完成。

`local-dev` 只放宽本地认证，不放宽科学真实性：configured Host 缺真实 execution/research backend 时保留 unavailable 能力或返回结构化失败，绝不自动装配 deterministic success。deterministic adapters 只能由 `build_local_eval_foundation()` 或 `dev_web_ui --fixture-non-cutover` 显式选择，所有 outcome 必须标记 `fixture_non_cutover`、`synthetic_source=true`、`cutover_eligible=false`。`dev_web_ui` 默认走 configured foundation；未配置 execution backend 的默认值是 `disabled`。bio research service 为 `None` 时不注册对应工具，不能隐式创建 fixture service。

V3 稳定文档入口见：

- [docs/v3/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/README.md)
- [docs/v3/00-harness-doctrine.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/00-harness-doctrine.md)
- [docs/v3/01-target-architecture.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/01-target-architecture.md)
- [docs/v3/02-control-plane.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/02-control-plane.md)
- [docs/v3/03-capability-engines.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/03-capability-engines.md)
- [docs/v3/04-public-interfaces.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/04-public-interfaces.md)
- [docs/v3/05-agent-runtime.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/05-agent-runtime.md)
- [docs/v3/06-top-level-llm-loop.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/06-top-level-llm-loop.md)
- [docs/v3/07-runtime-hpc-reliability.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/07-runtime-hpc-reliability.md)
- [docs/v3/runtime-hpc-reliability-operations.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/runtime-hpc-reliability-operations.md)

本文档是主线架构入口；`docs/v3/` 是 V3 主题细则。若两者与当前代码实现出现差异，必须同时核对代码、V3 稳定文档与最近验收事实后修正文档或实现，不能用旧 workflow 叙述压过当前 V3 代码事实。

---

## 2. 当前主线边界

本仓库是基于 `uv` 的 Python monorepo。应用入口位于 `apps/`，共享库位于 `packages/`，Python 子项目采用 `src/` 布局。

当前主线保留的主要应用：

- `apps/openzyme-host-api`：FastAPI Host API，包含 V3 `/v3` 产品接口；作为 HTTP/SSE composition root 装配 repositories、engine registry、runtime foundation、background worker 和 runner server，评测/fixture 模块仅保留迁移兼容，不再作为新增 V3 runtime/eval 逻辑落点
- `apps/openzyme-host-cli`：Thin CLI client
- `apps/openzyme-web-ui`：浏览器工作区 UI
- `apps/mcp-hpc-runner`：SSH/Slurm/HPC runner 边界

当前主线 V3 优先落点：

- `packages/openzyme-domain`：control-plane 领域对象，如 `Session`、`Task`、`Lane`、`ApprovalRequest`、`InboxMessage`、`AgentMember`、`AgentRuntimeSignal`、`ControlledOperationExecution`、`RuntimeCommandRecord`、`ContinuationState`、`MutationScope`、`MutationWriter`、`MutationQuiescenceReceipt`、`EngineInvocation`、`RunRecord`、`SessionArtifactRecord`、`SessionReportDraftRecord`、`SessionReportRecord`
- `packages/openzyme-core`：V3 harness、task board、lane manager、protocol、projection、agent runtime、scheduler、tool registry、report draft tools、docs tools；对 runtime SPI 保留旧 public import 的兼容重导出
- `packages/openzyme-engines`：capability engines，尤其是 execution pipeline engine 与 sandbox supervision；不得依赖 `openzyme-core` 的 concrete harness 类型
- `packages/openzyme-pipeline`：受控 execution pipeline sandbox 内 SDK
- `packages/openzyme-research`：research provider 与 research capability 相关实现
- `packages/preprocess-backend`：受控 preprocess 能力后端

共享能力包：

- `packages/openzyme-runtime`：settings、LLM、limits、research seams、engine/tool SPI、artifact projection / artifact boundary service、static route policy 等无顶层产品真状态的 runtime seam
- `packages/openzyme-tools`：HPC catalog 的唯一权威来源、tool execution contract、command rendering、RunSpec compiler helper 与 result parser
- `packages/openzyme-execution`：runner adapter normalization；不得直接依赖 `apps/mcp-hpc-runner`，真实 runner server 由 Host API composition root 注入

这些包不拥有顶层产品真状态。新增产品状态、协议、调度、workspace projection、report draft、execution pipeline 语义时，默认应优先放在 V3 harness/control-plane 相关包中。

---

## 3. V3 核心结论

### 3.1 顶层真状态是 Control Plane，不是 Graph

V3 的产品真状态由 Host control plane 持久化，并通过 workspace projection 对外暴露。核心对象包括：

- `session`
- `task`
- `lane`
- `approval`
- `inbox`
- `agent_member`
- `agent_runtime_signal`
- `controlled_operation_execution`
- `runtime_command`
- `continuation_state / continuation_delivery`
- `mutation_scope / mutation_writer / quiescence_receipt`
- `engine_invocation`
- `artifact`
- `run`
- `report_draft`
- `report`
- `research evidence / source refs / gaps`

LangGraph / LangChain 可以继续作为 `deep_research`、局部 research loop 或其他内部能力实现工具，但不能重新成为 V3 产品级 workflow truth owner。

### 3.2 用户只与 Master 对话，Teammate 是内部团队成员

V3 默认角色模型：

- 用户是甲方
- OpenZyme 是乙方
- `master agent` 是对外负责人，理解用户目标、创建 task、委托 teammate、汇报结果
- `teammate agent` 是内部执行者，围绕明确 task/lane/correlation 推进研究、执行或报告
- `harness` 是系统层，负责状态、协议、约束、恢复、工具分发和投影

当前固定 teammate roster 为：

- `researcher`：literature and data research
- `executor`：approved computational execution
- `reporter`：report drafting and publishing

不要把 provider tools 或 capability engines 说成 teammate；例如 fpocket、Vina、PubMed、UniProt、RCSB PDB 是工具/能力/数据源，不是 agent team 成员。

### 3.3 Resident Teammate 不等于常驻 LLM 进程

V3 的 teammate 是 resident agent member，常驻的是 identity、role、status、task focus、inbox、protocol thread、memory 和 workspace 读视野；LLM loop 只在明确 wakeup signal 被 scheduler claim 后执行 bounded turn。

当前实现已经具备：

- `AgentRuntimeSignal` 持久化 signal queue
- `AgentRuntimeScheduler` claim lease、bounded drain 和并发限制参数
- stale claim recovery、attempt 计数、失败记录和 duplicate wakeup dedupe 相关 repository 覆盖
- FastAPI lifespan 中的单进程 `V3BackgroundRuntimeService`，通过 durable signal + in-process notifier 自动唤醒 scheduler
- 单进程 `V3DurableWorkSupervisor`，分别运行 runtime-command、controlled-operation、continuation-delivery 等短 claim worker
- 显式 `POST /v3/sessions/{session_id}/runtime/drain`，作为 durable debug/operator/manual recovery command admission

当前默认产品路径是：REST handler 持久化状态并排队 `AgentRuntimeSignal`，后台 runtime service claim pending 或 expired-lease signal 后启动 bounded master / teammate turn。显式 `/runtime/drain` 只原子写入 durable command/outbox，始终返回 HTTP `202`；独立 `RuntimeCommandWorker` 再认领 command 并调用 bounded scheduler，调用方通过 session-scoped GET 查询结果。HTTP request、command、signal claim 和 session lease 都不拥有 approval、provider、sandbox 或 HPC wall time；旧同步 response fallback 已退休。

`V3DurableWorkSupervisor` 不从 action name、claim/lease 活动、state version 或 event 数量猜测进展。runtime-command、controlled-operation 与 continuation-delivery worker 的每个 outcome 都必须显式携带 typed `semantic_progress: bool`；缺失或非 boolean 在 worker-thread serialization seam fail closed。controlled-operation owner 只比较 canonical lifecycle、terminal/effect/retry、dispatch generation、backend/result identity 与 result digest/artifact-set digest；lease/fence/version/timestamp/diagnostic churn 和 unchanged poll/reconcile observation 不计进展。supervisor 保留这些 no-progress outcome 作为 bounded diagnostic，但不增加 `processed_count`，也不即时 self-wake；一个 coordinator slot 若先观察到 `claim_raced` / `not_claimable`、随后其他 worker kind 仅返回 `idle`，必须保留最后一个 non-idle observation，不能用尾部 `idle` 抹去该 bounded diagnostic。只有当前 bounded tick 的全部 concurrency slots 都提交 semantic progress 时才允许发出一次 backlog notification，随后仍由下一独立 tick 推进。periodic poll 与显式 operator notification 保持存在，该计数绝不写 task business status。

message admission 与 runtime 推进解耦时，结构化 focus 的 canonical truth 仍属于 source message，而不是 signal 或 worker 内存：显式 `skill_keys` 去重后写入同一 user conversation document，signal 只保存 `source_ref`。master 在进入 `working`、发出 `agent.woken` 或调用 provider 前，必须从 exact source 恢复；public user-message 的 participant/session/document identity 任一损坏都 fail closed。普通 agent protocol inbox 可以唤醒 master，但不携带 workflow authority；background worker 与手动 `/runtime/drain` 走相同恢复规则，均不能注入或合并 refs。

compaction 只提供 historical continuity，绝不成为 workflow authority 或当前 runtime
truth。自动 summary 不再写入 focus、ready task、pending approval、active invocation 或
active skill；session 与 lane summary 必须分别从各自 scope 重建，不能把某个 actor/lane
snapshot 复制成 session memory。历史自动 compaction 在 prompt projection 时只移除旧版
generated volatile/authority sections，原 row 保持 immutable。每个 master/teammate prompt
都从当前 canonical focus 显式投影 exact `Current authorized workflow refs`，包括空集合；
memory、task text 与 protocol text 均只作为历史事实，不能扩张该集合。

### 3.4 No Hidden Fallback

V3 默认失败策略是显式失败传播，而不是隐藏 fallback。

要求：

- provider/model/runtime 异常不得被静默吞掉并伪造成成功
- ordinary validation/tool/adapter/local-engine 失败在 effect 已知时返回 LLM 可读的
  structured `FailureObservation`，agent 在剩余 bounded step 内可修复、改道、求助或拒绝
- fencing、authority、permission、budget、integrity、process cancellation 和
  `dispatch_in_doubt` 仍停止对应 ownership boundary，不能降级为自由重试
- 意图不清或前置条件不满足时，应让 task/approval/protocol 表达
  blocked/failed/needs clarification；需要 user/operator/harness/authority 时用
  `task.finish(blocked)`，只有 objective 本身确知不可能时才用 `failed`
- 不得通过隐藏 fallback 重新打开 blocked action、替换用户目标、默认选择可运行工具或合成虚假 plan
- bounded loop 到达上限可以标记 runtime signal/agent failure，但不能据此推断业务 task 已完成或失败

`FailureObservation` 是 immutable Host/Harness fact；`failure.get` 是唯一 active failure
tool。模型对原因和策略的判断保留在当次 reasoning、普通 protocol message 或用户回复中，
不再升级成 `FailureHypothesis` / `FailureRecoveryDisposition` control-plane 对象。历史
SQLite migration 与旧表只为兼容既有数据库保留，runtime 不再读写或投影这些表。

effect-known ordinary failure 只做一次事实结算：产生标准 `ToolResult`、持久化
`FailureObservation`、闭合 provider transcript，然后把 observation 回灌同一 bounded
model loop。Harness 不再从失败派生 turn-local recovery obligation、settlement matcher、
response veto 或第二条 `RECOVERY_REQUIRED` wakeup；它也不要求 agent 用某个特定 read/write
证明“已经恢复”。agent 可以在剩余 step 内修正、换路、读取状态、求助、解释限制或显式
`task.finish`。这些选择的业务含义只由实际调用及其 canonical state 决定。

Harness `COMPLETED` 只表示本次 bounded turn 正常处理完，不表示 task completed。
step budget 用尽返回 `MAX_STEPS_EXCEEDED` runtime outcome，task 仍保持原业务状态；空回复或
prose 也不因前序安全失败变成 harness fatal。pending approval 是独立 durable suspension
边界：只有 canonical pending approval 可产生 `WAITING_APPROVAL`，且 runtime status 与
approval identity 必须一致。unknown effect、fencing、authority、integrity、permission、
provider/driver failure 与 process cancellation 仍在各自边界 fail closed。

`task.get` not-found、`task.next` no-ready-work 是成功的 closed empty read；只有 canonical
identity 与 postcondition 完全相等的 `task.finish` / execution start replay 才返回
already-satisfied。execution request 同时显式给出 invocation id 与 idempotency key 时二者
必须全部匹配，任一冲突都继续失败。continuation 或 controlled execution 在原 turn 之后
产生失败时，现有 source-bound `ENGINE_COMPLETED` wakeup 携带可重读的 failure facts；
runtime 不再为同一事实制造 recovery-specific signal taxonomy。

`Lane` 保留为 cwd、branch、workspace projection 与 task execution isolation 的具体资源，
但不再充当 ordinary failure 的普适 causal/recovery proof identity。只有确实发生在某 lane
内的对象才绑定 lane；session-scoped research/provenance 允许 `lane_id=None`，不得为了通过
恢复 matcher 将历史事实嫁接到当前 lane。

所有 `structured`、`tool_calling`、`chat` 与 connectivity smoke 的 provider 调用都必须经过 `openzyme_runtime.LlmInvocationRuntime`。invoker 只负责构造 payload、结构化解析或 tool response 还原；runtime 统一负责 limiter、timeout、retry/backoff、`Retry-After`、错误 taxonomy 与 LLM debug 记录。502/503/504、transport timeout/connection failure 属于 retryable；429 只有 transient 或带 `Retry-After` 时 retryable，usage/quota/invalid/context 类 429 不重试；400/401/403、schema/tool argument/context window 错误不重试。runtime 不拥有 session compaction、restore context rebuild 或 harness/engine 状态机。

tool-calling provider schema 必须经过 `openzyme_runtime.ProviderToolAdapter`。OpenZyme 内部 truth 是 dotted canonical `ToolSpec.tool_name`，例如 `task.create`、`execution.pipeline.start`；adapter 将 canonical `ToolSpec` 投影为 provider-visible tools，并输出 `canonical_to_provider` / `provider_to_canonical` 映射。MICU 的 `task.create -> task_create` 这类 dotted alias 只存在于 adapter 生成的 provider request 与 LLM debug 记录中；provider response 返回后必须先恢复 canonical tool name，再进入 driver、`ToolRouter.dispatch()`、tool invocation、tool result、workspace `agent_traces` 与 `tool.invoked` / `tool.rejected` / `tool.completed` events。非 MICU / 不需要 alias 的 OpenAI-compatible base URL 保持 canonical 名称。

Router 在 schema、visibility、tool governance 与 writer fence 通过后直接进入 owning
runtime/domain handler；Host composition 不再拥有 generic `tool_dispatch_precondition`，也不能
按 session、campaign、task cardinality、report handoff 或某条 agent trace 在 handler 前加 phase
gate。actor/assignment、lifecycle、authority、fencing、unknown effect、quiescence、integrity、
provenance、isolation、budget 与 atomicity 仍由各 mutation owner 结构化拒绝。AOX exact-three、
owner-authored finish、source-linked report、final answer、selected chain 与 17 deliverables 只由
public product-closure evaluator 和 offline verifier 从最终 canonical facts 判断；早委派 reporter、
插入 read/prose、调整独立 action 顺序或在 known-no-effect 后选择不同安全后继不会成为 Harness
failure。incomplete state 可以诚实保持 nonterminal/ineligible，不能被策略 interceptor 改写。

master 与 teammate 的单个 provider response 仍只允许顺序 dispatch 前 `3` 个 tool call，但
driver 不得静默丢弃 overflow。全部 returned calls 都进入同一 public LLM trace；第 `4+`
项转成 `parallel_tool_call_limit_exceeded` 的结构化 no-effect ToolResult，持久化
failure observation，并发送 `tool.rejected` / `tool.completed` 而不发送
`tool.invoked`。下一次 provider request 前，assistant response 中每个 function-call id
都必须有匹配 ToolMessage，包括未 dispatch 的 overflow，否则 transcript 不闭合并会被
provider 拒绝。该边界只忠实呈现“未执行且可由 agent 重排”的事实，不提高并发上限、
不替 agent 选策略，也不授权隐藏 retry。

整个 provider response 必须作为一个有序 batch 结算。harness 在 dispatch 前预先持久化
全部 overflow 的 no-effect observation，公开 result/event 仍保持原始 call 顺序；若前三项
中的某项因 pending approval、`task.finish`、成功的 `attempt.create` /
`scientific.attempt.close`、runtime
suspension 或 boundary-fatal failure 提前结束本 turn，其后的 eligible calls 必须记录为
`tool_call_batch_interrupted/no_effect/verify_then_retry`，第 `4+` 项仍保持
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`。已经 dispatch 的 causal call
保留其精确 failure observation、effect certainty 与 retry eligibility，包括
`dispatch_in_doubt/reconcile_required`，不得伪装成未执行。未 dispatch 项只有
`tool.rejected` / `tool.completed`，没有 `tool.invoked`。overflow 预持久化不得提前解析
eligible call 的 task/lane 引用；每项只在自身 dispatch 前读取前序 call 已提交的最新
durable state，以保留同批 `task.create -> lane.bind_task` 等合法顺序依赖。未 dispatch
项在 ToolResult/observation facts 中保留 provider 返回引用，但 observation 关系字段只
绑定当前真实 step context，不要求未来对象已存在或把它变成 authority。该结算不执行、
重试或重排后续工作；agent 在新的 turn 中读取真实 durable state 后自行选择策略。

成功的 `attempt.create` 与 `scientific.attempt.close` 是通用 scientific transition
terminal action：它们在 Core SQLite atomic boundary 内分别只持久化 immutable admission /
closure request，随后立即结束 requesting turn，不把结果再次送入模型，也不 dispatch
同批后续 call；失败的 request
不写对应 admission / closure request 并保持 non-terminal，使 agent 可根据结构化 blocker 修正。closure
request 与 assistant response、conversation document/message、report publication
彼此独立，不创建 closure-response binding。report publication eligibility 仍从现有
真状态派生：`ready` 或 `published` report 必须与同 session/task 的
`published` draft、精确 `published_report_id` 和非空 content ref 闭合；消费者不得各自
缩窄枚举或静默归一化实际状态。
只有 attempt exact task 当前 `assigned_ref` 才能请求 closure，Core 在 request 与
finalization 两处重核该 canonical assignee。requesting `AGENT_TURN` writer 及其 batch
settlement 全部退休后，Host 才能 finalization、建立 quiescence receipt 与 final closure。
这个 turn barrier 不完成 task，也不把 closure request 冒充 `scientific_closure`
evidence；反向地，bound attempt 尚未 immutable closed 时，
`task.finish(status=completed)` 以 typed no-effect error 拒绝。
successful scientific transition handoff 不进入 ordinary teammate-result 的 generic
`agent:master` successor 路径；否则 generic master wake 会先于 Host finalization 排队，
与随后 canonical owner wake 竞争。requesting turn 只退休，Host finalizer 提交的 exact
source-bound owner wake 是该 transition 唯一 successor。ordinary teammate completion
与 budget-replan master notification 保持原行为。

### 3.5 Token-Budgeted Harness

V3 master / teammate LLM 调用必须先经过统一 token budget preflight。harness 按模型 profile 估算完整 prompt，包括 system prompt、conversation/messages、tools schema 和 tool observation；达到 80% 记录 warning，达到 85%（包括已经达到 90% emergency 的输入）先且只先执行一次 bounded session/lane compaction、刷新 restore context 并重算。只有重算后仍达到 90% 才显式返回 `context_budget_exceeded`，不得把超限 prompt 交给 provider。prompt-budget compaction 改变的是后续 LLM restore prompt projection，不删除或改写持久 conversation history，也不改变 workspace conversation read model；它按 session/lane 各自 scope 生成 authority-free historical summary，不能复用当前 actor 的 workflow focus 或把 lane-local 状态提升为 session truth。

当工具结果本身或加入该结果后的下一轮 prompt 超预算时，完整 tool result 写入 `engine_documents(document_kind="tool_result_full")`，并登记为 `ArtifactKind.RESULT` artifact。LLM 只收到小型 observation，包含 `tool_result_context_over_budget`、`original_tool_ok`、`original_status`、`artifact_id` 和 `read_hint`。这不是业务失败判定，也不自动摘要原始 payload；agent 需要时通过 `artifact.get` 分页读取完整结果。

### 3.6 本地 V3 SQLite State 的兼容策略

开发与本地手动测试使用的 V3 SQLite 文件是 runtime/control-plane state，不是长期归档格式。当前主线只支持两类启动输入：

- fresh empty SQLite：启动时在一个 `BEGIN IMMEDIATE` 原子事务内按当前 migration
  列表初始化并写入 `PRAGMA user_version`；任一 migration 失败必须回滚全部 fresh
  schema 对象，不能留下部分初始化状态
- current-version SQLite：启动时校验关键表存在后复用

旧 schema、未知 schema、非空但未标记 `user_version` 的 SQLite 文件不做隐式修复、备份或删除；启动路径必须 fail fast。`026` 至 `036` migrations 已把 canonical controlled-operation execution、runtime command/continuation、dispatch request、immutable result artifact、mutation authority/snapshot、failure observation/hypothesis/recovery disposition 和 scientific attempt authority/selection 纳入 current schema 与升级校验。migration `035` 及其 closure-response table 继续保留，用于读取 frozen historical evidence；active domain/repository/service 和 current write path 已删除，不得把历史表重新解释为当前 product state。需要长期保留的研究结果、execution 输出与报告应通过 artifact、report 或 export 留存，而不是依赖旧 SQLite runtime 文件跨 schema 版本继续可用。

Python import shim、CLI alias、`execution.pipeline.*`、Podman runner、runtime/tools/execution 包 seam 与旧 HTTP/runner call shape 的 sunset 证据统一由 `scripts/audit-v3-compat-callers.py` 和 `docs/v3/compatibility-sunset.md` 管理。仓库内零 caller 只证明当前 checkout，不证明外部零 caller；所有 `DEPRECATE` / `RETIRE-BLOCKED` surface 在 external inventory/telemetry/owner evidence 仍为 unknown 时必须保留。已经不存在的 `/v1`/`/v2`、raw runner lifecycle 参数和 legacy workspace activation 标为 `RETIRED` 防回归，不得把归档源码本身误删。

单进程不等于共享一个 SQLite connection。Host 以 file-backed `SQLiteRepositoryProvider` 为 composition root；每个 request、background worker、scheduler bounded turn 与 sandbox SDK control callback 都在实际执行线程内创建并关闭自己的 thread-affine connection。纯读使用 `query_only` read scope；不跨外部边界的 canonical command 使用短 `BEGIN IMMEDIATE` Unit of Work，使多个 repository mutation all-or-nothing；可能等待 LLM、provider、runner 或 sandbox 的长流程只能使用无长事务的 connection scope，由内部短写自行提交，严禁持有 SQLite write lock 跨外部调用。WAL 与 `busy_timeout` 只改善单进程并发，不替代 ownership、UoW 或后续 fencing。同内容 durable event replay 虽然语义幂等，失败的 duplicate INSERT 仍会打开 SQLite 隐式事务；standalone repository path 必须在返回既有 event 前提交该隐式事务，owning UoW 内则继续由 UoW 统一提交。不得让幂等 replay 遗留 transaction，阻塞后续 mutation-writer retirement 或 quiescence。

scheduler 持有 session runtime lease 期间必须按 TTL 的有界分数持续 heartbeat；blocking provider call 在 worker thread 中执行时 coordinator event loop 仍负责续租。file-backed Host 的每次 heartbeat（包括 contention retry）都使用新建并及时关闭的独立 repository connection，不能复用 coordinator 或长时 worker scope；只把 SQLite `BUSY` / `LOCKED` 视为瞬态，并以 capped backoff 持续重试到成功或当前 lease expiry，其他异常显式传播。repository 必须先取得 SQLite writer lock，再计算 heartbeat/acquire 的 `now` 与新 expiry；锁等待跨过旧 expiry 时不得复活旧 lease。确认 lease 已丢失或 observed expiry 已到达即停止续租，但 cleanup 仍必须恢复 context 并 release 可释放的 row。bounded agent worker 与其 session-turn engine registry 绑定 exact `session_id + lease_token + fencing_token`；sandbox control process、durable execution callback 与 continuation delivery 则分别使用 process epoch、execution lease/fence 和 delivery lease/fence，绝不继承或复活该 turn lease。composition root 以 typed `SandboxHostCallContext` 构造 thread-owned repository connection，`SandboxHostGateway` 是 adapter/HPC fetch 的唯一入口；engine 不得回退到创建时捕获的 scope。每类 owner 的 canonical commit 都再次检查自身 fence 与 mutation-writer authority。stale session worker、process epoch、execution callback 或 delivery worker 的迟到写入在各自边界 fail closed；已经开始但超时返回的 callback 也不能应用 late business effect。fencing 只拒绝 canonical 写回，外部系统重试仍必须依赖 operation digest、idempotency key 与 opaque run handle，不能把 fencing 冒充外部取消。

V3 public event log 不是 Host 进程内缓存。`durable_event_records.cursor` 是数据库分配的单调游标；事件、对应的短 canonical mutation 与可选 `command_receipt_records` 在同一 UoW 提交，rollback 不得泄漏 SSE event。event rows 只能 append，receipt rows 完成后不可更新或删除；`event_id` 全局唯一，`llm.response.created` 的 `trace_id` 在 session 内唯一。SSE 以 cursor 作为 `id:`，通过 `after_cursor` 或 `Last-Event-ID` 从 SQLite 重放，Host 重启不得改变既有 event id/cursor。所有 `/v3` mutation 接受 `Idempotency-Key`：同 scope、command type、key 与相同 request digest 返回首次完成响应且不重做副作用；同 key 不同 digest 返回冲突。local-dev 当前允许省略 key；shared profile 的强制认证阶段将同时把 key 设为必需。

### 3.7 Runtime/HPC 的 authority 与静默闭包

可靠性主线把五个 authority boundary 明确分开：session runtime lease/agent signal claim 只拥有一次 bounded agent turn；sandbox process epoch 只拥有同一 attached process 的后续 Host call；execution lease/fence 只拥有一次 external-effect lifecycle；continuation delivery claim/fence 只拥有 exact result 向 exact process 的一次投递；mutation scope generation/writer fence 只拥有 canonical evidence 的写入与静默封存。任一 authority 的 idle、expiry 或 terminal 都不能推断其他 authority，更不能自动写入 task 业务终态。

`ControlledOperationExecution` 是 durable operation 唯一 external-effect owner。worker 只做短 claim/dispatch/poll/materialize slice，外部调用前重新检查 fence，且不持 session lease 或 SQLite transaction跨外部 wall time。恢复只允许在 proven `no_effect` 的同一 phase 内有界进行；direct SSH payload 已写出却丢失响应时进入 `dispatch_in_doubt`，只能 reconcile，不能 replay。

generic mutation closure 先 freeze admission 并推进 fence，再等待每个显式 writer/descendant 退休，获取两次一致的 bounded SQLite/event/artifact/report/live-ledger snapshot，签发 immutable receipt，最后 seal exact generation。runtime idle、空队列、HTTP 返回、timeout 或 missing handle 都不是 writer retirement 证明；seal 也不表示 task completed。完整合同见 `docs/v3/07-runtime-hpc-reliability.md`，迁移和回滚步骤见 `docs/v3/runtime-hpc-reliability-operations.md`。在 deterministic、non-live 与经单独批准的 real-SSH transport-only soak 全部通过前，`rxx` campaign 保持冻结。

frozen `legacy_sync` sandbox controlled operation 仍只承担兼容同步路径，但其首次
admission 也必须满足 control-plane 可见性原子性：`WAITING_APPROVAL` operation、
`PENDING` approval、operation→approval binding 与
`WAITING_APPROVAL` continuation 在同一个短 `BEGIN IMMEDIATE` Unit of Work 中提交，
任一步失败整体回滚。approval resolver、workspace/UI projection 与其他 connection 不得
观察到没有 continuation 的 pending approval；人工等待和 Host adapter execution 只在
commit 后发生，不能持有 write lock 跨外部 wall time。该约束不升级 legacy owner，也不
允许 durable route 回退到同步 adapter。

### 3.8 Scientific attempt、selected chain 与 fresh authority

formal scientific work 的策略自由由显式 attempt control plane 承载。每个 attempt 先消费
durable authorization envelope，绑定 grantor、session/task/campaign/workflow/root/scope、
effect/route allowlist、attempt count、MICU/cost/wall-time、expiry 与 policy digest。
`attempt.create` 只写 admission request，并以 `terminal_action="attempt.create"` /
`terminates_turn=true` 形成非业务终态 bounded handoff；Host 必须等 agent writer 退休后
才在独立短 slice 中最终校验、消费 envelope 并打开 attempt。Host 以 exact attempt id
唤醒原 assignee，runtime 在 provider 前从 canonical attempt/request/lifecycle 重建 facts，
不能仅把旧 task prose 交给 fresh teammate。

r67 起，AOX 不再拥有 runtime observer、Core runtime barrier/observer-writer 或任何
drive-until-terminal/no-wakeup/scope-rollover policy。Codex 测试员只通过 public Host
API/CLI 明确发送 message、一次一次执行 bounded drain、处理 pending approval，并读取
workspace/events/receipt；每个动作的继续、停止或重计划都由测试员根据 public facts 决定，
Harness 不代替它作业务判断。删除 observer 不删除 Host authority：mutation scope、writer
fence、attempt transition、approval、unknown/external effect 与 sandbox/process isolation
继续由 canonical service 原子验证和持久化。

`ScientificAttemptService.finalize_closure_request()` 独占 attempt scope seal、immutable
closure 与唯一 post-attempt child scope 的短事务。public consumer 只会看到提交前态或
提交后态；真正的 missing/ambiguous scope、active writer、identity mismatch 或未退休
external effect 继续 fail closed。测试编排器不得注册 synthetic observer、调用 private
repository helper、盲重试 rollover，或把空 drain、无 wakeup、进程退出解释成业务终态。

Host 从 exact attempt scope 导出完整 operation/run occurrence universe。agent 使用
CAS-protected selection revision，把每项显式标为 `adopted`、`superseded`、`failed` 或
`abandoned`，并选择唯一 workflow role chain。已知失败保留审计但不必污染最终链；未知
effect、未退休 process/writer、authority/resource breach 或不完整 disposition 仍 fail
closed。同一 formal attempt 可跨 run adoption/materialization，跨 attempt/campaign/
positive/probe/fault reuse 禁止。closure 需同时验证 sealed selection、exact quiescence、
authorization consumption 和 materialization lineage，但 closure 仍不是 task terminal。
attempt closure 的 scope transition 还必须在一个短本地 write transaction 中原子提交：
attempt scope seal、immutable closure 与唯一 post-attempt session scope open 对并发
public reader 只能看到前态或后态，不能暴露 committed 零 open scope 中间态；真正
missing/ambiguous scope 继续 fail closed，不能以 conductor blind retry 掩盖 non-atomic
finalizer。当前该事务由 Core 的 `ScientificAttemptService.finalize_closure_request()`
直接拥有，而不是依赖某个 Host caller 恰好选择 write scope；两个并发 finalizer 通过同一
`BEGIN IMMEDIATE`/savepoint 语义串行化并只留下一个规范 child scope。Host 的 admission
与 closure 调用面再共用一个 transition settlement，把 deterministic durable transition
event 与 source-bound runtime wakeup 放入包含 Core transition 的同一事务；commit 后才触发
进程内 notifier。pending finalizer 不再跳过已存在 attempt/closure，而是按 event/source
identity 幂等补齐旧崩溃留下的缺失 delivery，已完成 signal 不会被重新排队。

admission、closure 与 typed finalizer failure wake 共用 canonical wake-facts projector。
它按 exact source record 解析 attempt / closure / `FailureObservation`，验证
source/correlation、claimed status、actor、session/task/lane、request graph、resolved
lifecycle 与当前 assignment，不依赖 assistant response、隐藏 conversation state、字符串
prefix 或 AOX policy。bounded facts 必须先于 task prose进入 fresh master 或 teammate
prompt；master 通过一次性 system context 接收同一投影，facts 不写 user/assistant
conversation。admission 明确 exact attempt 已提交，closure 不完成业务 task，failure
不自动 retry。failure 的 optional facts/evidence 使用 count、digest、truncation marker
有界投影，critical source/error/effect/retry identity 保持 exact。task 已 terminal 时只
复用 generic stale-signal mechanical completion。durable transition event 无 canonical
record或任一 binding 漂移都在 provider 前 fail closed；完全无 canonical source 的普通
resume 保持既有行为。

`ScientificAttempt.status` 是 admission 时写入且保持 append-only 的
`record_status`，不是 closure 之后的唯一 lifecycle 真相。Core 统一通过
`ResolvedScientificAttemptLifecycle` 联读 attempt、immutable closure request 与
immutable closure，派生 `open | closure_requested | closed | blocked`：request 一旦存在
就立即撤销 scientific mutation affordance；exact closure 一旦存在，即使 base row 仍为
`active`，effective lifecycle 也必须是 `closed`。为保持现有 `@1` read contract，
request-only projection 可以继续显示 `status=active`，但必须同时显示
`record_status=active`、`effective_status=closing`、`lifecycle_phase=closure_requested`
和 `accepts_scientific_mutation=false`。identity/selection/status 互相矛盾的 record graph
统一以 `scientific_attempt_lifecycle_invalid` fail closed。

selection inspection、session readiness、workspace/world projection、agent recovery、
runtime consistency、closed-evidence export、mutation/approval gate 与 AOX terminal
consumer 都消费这一派生 lifecycle；业务路径不得再用裸 `attempt.status` 作 closure
判断。AOX 在第一次 post-closure observation 看到 exact closure 时立即导出 closed
control 并返回，不能等待 base row 改写，也不能把 replay-safe 空 drain 当作收尾进展。

每个新 attempt 还必须绑定 registry-resolved、digest-closed 的
`ScientificWorkflowContract`。合同 preimage 同时覆盖 workflow/scope、合法 roles、每个
role 的 closed `sdk_module + function_name` signatures、cardinality、adoption 与
same-attempt reuse policy；validator、agent-safe projection 与 bundle verifier 都消费同一个
contract object，不能再由 prompt 或 Host 私有 role map 各自维护真相。selection head 只保留
CAS pointer/version；读取 lifecycle 必须使用 repository `resolve_head()` 联读 canonical
selection，不在 head 上复制 `state`。

`ScientificSelectionEvaluator` 对 exact attempt/selection/universe/contract 做纯读取、
deterministic evaluation。`scientific.attempt.inspect` 可按 exact attempt/selection 分页显示
occurrence signature、allowed/compatible roles、disposition/adoption/materialization、issues
和 `seal_ready`；`world.inspect` 只给 bounded gap summary。`seal_ready` 只说明当前 facts
满足封存不变量，不替 agent 决定是否 seal。对新合同，采用 operation 的唯一 model-visible
写路径是原子 `scientific.operation.adopt`：agent 指定 exact selection、operation、role、
reason 与 idempotency key，Host 在同一事务写 adopted disposition 与 effect adoption；旧的
两步 `scientific.effect.adopt` 不再暴露给模型。

AOX 是该通用控制面的首个消费者：新 production collector 只发
`aox_blank_world_attempt_bundle@3`；历史 `@2` verifier 和 r48-r59 NO-GO evidence
保持冻结且不得升级或采用。r54 使用的
`aox_blank_world_selected_chain@1` 同样只读；新 attempt 只接受 digest 覆盖完整
role-to-operation mapping 的 `@2`，current `aox_blank_world_runtime_config@5` 把该合同身份
封入 config pin，且不包含外部 conductor/driver policy object；历史 `@1`–`@4` 仅只读。
r52-r56 都没有 eligible positive attempt/campaign closure；任何
后继 live 必须重新 commit、full admission、pin、authorize 并取得新 plan 的精确消费授权。完整合同见
`docs/v3/08-failure-recovery-and-scientific-attempts.md`。

从 r56 起，AOX target contract 把 live execution 拆成 schema-disjoint 的两个 run class。
diagnostic live 只消费独立 one-use 单 positive authority，使用独立 root/consumption/
decision schema，并永久 `acceptance_eligible=false`；它不得生成 `@3` bundle、不得进入
GO reducer，也不得把 operation/effect/artifact/report/browser receipt/bytes 交给 formal。

r59 closure-stage logical fork 已完成其一次性诊断目的，但 historical state 无法满足
current close/finalization contract，且永久不能进入 formal acceptance。r65 Phase 2
因此删除 `closure_stage_diagnostic` 的 authority、source qualifier、reconstruction、
live driver、CLI 与 dedicated runnable tests。历史 SQLite schema/rows 和 sealed
`aox_closure_stage_*` evidence 继续可离线读取；architecture qualification 只保留 raw
run-class/attempt-id 的 formal non-adoption negative gate，不提供兼容命令或 reconstruction
fallback。

current AOX fixed deliverable path 改由 exact typed scientific calculations 所有：
`aox_motif_candidate_filter@1` 只消费 canonical target FASTA 与 motif-scoring CSV；
`aox_upstream_empty_materialization@1`、
`aox_reference_only_scoring_alignment@1` 与 `aox_empty_membership@1` 只消费 installed
source calculation 的 typed zero receipt；`aox_final_deliverable_normalization@1`
固定全部 17 path 与 serializer identity，并生成
`aox_final_deliverable_normalization_result@1`；该 calculation result 不等同于 Host
签发的 `aox_final_deliverable_validation_receipt@1`。任意 source snapshot、agent-authored script 或
metadata 只能证明 provenance，不能替代 calculation implementation identity。

executor 只能通过 `artifacts.finalize_bundle` 发布 final bundle。Host 先用
`ArtifactBoundaryService.read_registration_draft` 对 17 个 immutable preimage 做零写入
预校验，再以 unified live/eval/offline validator 保留 earliest typed cause。成功时在单一
transaction 中提交 17 artifacts 与 source-bound
`aox_final_deliverable_validation_receipt@1`；失败时不留下部分 artifact、document 或
attempt closure。scientific close owner重新验证该receipt的exact attempt/selection/task/agent/
run/source/calculation/artifact bindings。generic execution task finish、report delegation/
publication/completion只服从各自domain约束；它们可以形成诚实但AOX-ineligible的canonical
state。public product-closure evaluator/offline verifier最终要求同一receipt、exact-three owner
finishes、source-linked report/final answer与17-deliverable facts完整，不能把这些要求前移为
agent tool-order gate。

r66/r67 将 sandbox-local pre-admission failure 纳入同一 canonical causal projection。
`openzyme_pipeline` SDK 保留 caller 的 exact stage descriptor/provider output authority，
由 Host 在 ControlledOperation admission 前验证并封存
`hpc_stage_ref_required|provider_output_path_invalid/no_effect`；
terminal SandboxRun 再以 source-bound `sandbox_exec_nonzero` 包装该唯一 cause。
`sandbox.exec` 返回 failed ToolResult，`ENGINE_COMPLETED` wake facts 继续投影相同
cause/wrapper。该路径证明 operation 未 admit、external dispatch 未开始；missing、
ambiguous、cross-source 或 cross-attempt binding 均 fail closed。

Host/canonical wake facts 与 offline evidence projection 对 exact selected attempt 的 local
sandbox failure 和 controlled-operation failure 使用同一 source binding。safe disposed history
保持可查询但不污染 closed selected-chain eligibility；probe、unsafe/unknown effect、显式
task failed/blocked/cancelled 或 identity drift 仍由 Host/verifier fail closed。r67 已删除
one-shot handoff、drain override 及整个 automatic observer/convergence policy；Codex conductor
只能逐次调用 public bounded drain，不能从 no-wakeup或历史 failure 自动合成业务终态。

首次消费的非 `rNN` closure-stage plan
`sha256:81cc5ba229775fee8bdc327a14f00efe0a8e15c01ccf567749b5cc0e2457a7e4`
已成为永久 diagnostic failure evidence：executor、reporter 与 master task 均完成，
report `report_ec02d118b9a5` 已发布，immutable closure
`attempt_closure_b8683b040385bfe1fc16b3bc` 也已写入并产生 cursor `276` 的
`scientific.attempt.closed`；但 base attempt row
`attempt_ffd9d5a7e86c9b86f4d8a189` 仍按设计保持 `status=active`。旧 AOX terminal
consumer 错把该 snapshot 当成最终真相，于 6 次有语义进展后继续执行 114 次零
signal/零 event/零 output drain，最终以 `formal_runtime_drain_exhausted` 有限失败。
该 consumed plan、root、decision 与 fatal 不得重试、重标或改写；其 runnable
closure-stage successor contract 已在 r65 退役。

repair commit `4bf4c4244fae68beff8e5d47717e83824ff2367e` 的一次性 successor
`sha256:7394c5200582b114a72fa08b0711dc993f4c7164dd66c1fb20dd1cf837060ae2`
已证明上述 agent forward path 收敛：master 以 empty workflow refs 委派 reporter，三个
task、published report `report_16937278db9c`、co-terminal response 与 immutable closure
`attempt_closure_a2f78d1fd2199e239696b99e` 均形成，5 个 command 各推进 1 条 signal，
没有 empty drain。它随后在 terminal-command observer 撞上 exact attempt scope 的
committed freezing window，被旧 driver 错报为
`mutation_driver_writer_identity_invalid`；decision
`sha256:470df988b817867c5fb80b859fd60c414d99a873e66a839283beb13fe1bef237`
与 fatal
`sha256:a3c4a24fcb6e9342dc11faa48bdb393481c0c9e1f4a1b9559c83b4fada0e8123`
永久 non-acceptance。上述 bounded same-command rollover coordination 是该真实证据后的
非 live correction；它不授权复用 plan 或再跑一次 live。

随后 clean commit `4122df0749c78f4ae011b6d804bf76cc3a9f8c1f` 的 fresh
non-`rNN` plan
`sha256:d062f81d803256e7ccca7ef63cba8fc0420022e5b731e65f1eced9d9e17b4cd5`
也只消费一次。product path 再次完成三个 task、published report
`report_71ffe6a0e718`、co-terminal response
`attempt_closure_response_67b0ae6ad2b9391c4ac18c2d` 与 immutable closure
`attempt_closure_d1e450291c10454855e07248`。最后 command 于
`07:08:16.801844Z` 完成；attempt scope 随后依次于
`07:08:16.853472Z/16.930602Z/17.039405Z` 进入
freezing/quiescent/sealed，closure 与 exact post scope 于
`07:08:17.379767Z/17.399815Z` 可见。observer admission 在 finalizer 前态正确看到零 open
scope，但旧 AOX-local classifier 读取时后态已提交，因只接受 pending 前态而再次误报
`mutation_driver_writer_identity_invalid`；closure transition 同时留下唯一 pending
source-bound signal `sig_c318716ba42c`。这证明 classification 也必须接受同一 Core
projector 的 committed 后态，且 terminal notification 应机械 settlement，不能再调用模型
复制已交付回答。decision
`sha256:7077a5ffe17f903cf93132d4b9384280228c1e562dd45b8de7bacdb5fe0c00e3`
与 fatal
`sha256:ed96bdd37285d3c1f56c12a515086bc5e9d25688bfff36ef9127ccb44a75e09b`
仍是永久 non-acceptance；该 plan、target、MICU 与证据不可复用。

formal acceptance 保留 exact-three `positive, positive, fault` authority 与全部 GO门槛。
本段前述 diagnostic plan/decision只解释r56-r67历史：当时
`authorize-diagnostic`/`consume-diagnostic-authority`生成永久non-eligible单槽证据；post-r69
current product已删除该module与命令，只保留historical schema/SQLite/evidence的只读
non-adoption validator。现行`authorize`/`consume-authority`只发布并原子消费exact-three formal
plan，生成source-bound receipt后停止，不创建root/session或执行attempt。实现完成不等于live
获批，任何后继campaign仍须取得精确授权并由public-only Codex conductor编排。

---

## 4. 顶层架构

当前 V3 主线分层如下：

```text
User
  |
  v
React Web UI / Thin CLI / API Client
  |
  v
FastAPI Host API
  |
  v
V3 Host Control Plane
  |
  +--> session manager
  +--> task board
  +--> lane manager
  +--> approval protocol
  +--> inbox / team protocols
  +--> agent roster
  +--> shared workspace / artifact catalog
  +--> report draft / report records
  +--> event log / projection builder
  |
  v
Agent Runtime / Scheduler
  |
  +--> durable runtime signals
  +--> claim lease / stale recovery
  +--> bounded master turns
  +--> bounded teammate turns
  +--> background signal drain
  |
  v
Durable Work Supervisor
  |
  +--> runtime command worker
  +--> controlled-operation execution worker
  +--> continuation delivery worker / attached-process registry
  +--> mutation writer retirement and recovery
  |
  v
Agent Harness Kernel
  |
  +--> top-level master loop
  +--> role-scoped teammate restore context
  +--> tool registry and tool result envelope
  +--> token budget preflight / bounded compaction
  +--> over-budget tool result artifactization
  +--> docs.search / docs.read
  +--> protocol.send / protocol.thread
  +--> task.delegate / task.update
  |
  v
Capability Engines
  |
  +--> deep_research / provider tools
  +--> sandbox.workspace.* / sandbox.file.* / sandbox.exec / openzyme_pipeline SDK
  +--> execution pipeline internals and migration bridge
  +--> report_draft.* / report.publish
  |
  v
Persistence + Infra
  |
  +--> relational store
  +--> artifact store
  +--> event log
  +--> rootless Podman sandbox
  +--> mcp-hpc-runner / per-target ControlMaster / SSH / Slurm
```

顶层边界：

- Web UI / CLI 不持有 workflow truth；它们消费 Host API 和 workspace projection
- Host API 是共享入口，`/v3` 是当前产品语义面
- Control plane 持有跨对话、跨压缩、跨后台执行仍然成立的 canonical objects
- Agent runtime/scheduler 负责消费 wakeup signals，不决定业务任务内容
- Durable work supervisor 负责独立推进 command、external effect 与 result delivery；这些 worker 不借用 agent session lease 表示自身 ownership，并只用 owner 显式返回的 typed semantic-progress fact 做计数与一次性 backlog wakeup，不按 action name 推断进展
- Harness kernel 负责 top-level loop、工具分发、restore context 和协议推进
- Capability engines 是被 harness 调用的专业能力，不拥有产品顶层真状态
- HPC runner 仍是外部执行边界，不被 Host 或 executor 直接替代

---

## 5. 一次 V3 Session 的主路径

典型 V3 主路径如下：

```text
POST /v3/sessions
  -> create session
  -> workspace projection

POST /v3/sessions/{session_id}/messages
  -> persist user message
  -> ensure resident agent:master
  -> queue agent:master AgentRuntimeSignal
  -> return without running master or teammate loop

POST /v3/sessions/{session_id}/runtime/drain
  -> validate access, strict request and Idempotency-Key
  -> atomically admit RuntimeCommandRecord + outbox
  -> return HTTP 202 + command_id + status_url

V3DurableWorkSupervisor / RuntimeCommandWorker
  -> claim one accepted command
  -> AgentRuntimeScheduler claims pending signals with session lease
  -> if signal is agent:master, run bounded top-level master loop
  -> if signal is teammate, wake focused resident teammate
  -> agent reads task / lane / inbox / protocol / workspace
  -> master creates / updates tasks and delegates with task.delegate
  -> teammate calls role-scoped tools or capability engines
  -> task / artifact / run / report draft / approval state updates
  -> ordinary terminal teammate outcome queues agent:master wakeup
  -> scientific transition handoff waits for the sole Host-finalized owner wake
  -> terminalize command when bounded batch finishes, fails, locks or parks work

GET /v3/sessions/{session_id}/runtime/commands/{command_id}
  -> return closed, redacted command status/outcome

GET /v3/sessions/{session_id}/workspace
  -> project current canonical state for UI / CLI

GET /v3/sessions/{session_id}/pending-approvals
  -> project only durable approval / operation / sandbox identity for control polling
```

关键约束：

- `POST /v3/sessions/{session_id}/messages` 是用户到 master 的入口，只持久化用户消息（含该消息显式选择并去重的 `skill_keys`）并排队 `agent:master` wakeup，不直接执行 master loop，也不隐式执行 bounded teammate runtime drain；每条 signal 只从自己的 exact source message 恢复，focus 不跨消息 sticky/union
- `POST /v3/sessions/{session_id}/runtime/drain` 是 debug/operator/manual recovery 的显式 durable command admission；它必须带 `Idempotency-Key`，只接受 closed limits，始终返回 `202`，不得绕过 command worker 直接运行 agent loop。可选 `Prefer: wait=0..2` 只短暂等待 command 状态，不改变 ownership 或取消语义
- `task.delegate` 是产品-facing delegation tool，但真实写路径是 `ProtocolService.delegate()`
- `protocol.send` 只投递消息并排队 wakeup signal，不同步运行 recipient
- `auto_enqueue_ready_tasks` 默认关闭，只用于显式 operator/debug/recovery 场景
- approval resolve 只改变 approval/resolution/continuation 状态并排队必要 wakeup，不直接恢复 execution、不直接运行 master loop，也不直接替用户或 agent 批准后续未知动作
- `world.inspect` 是 agent-facing 结构化世界读取工具，只暴露事实、约束、tool schema、route policy、approval requirement、outcome 与 runtime diagnostics；不得输出 `recommended_actions` 或替 agent 判断 workflow / 完成条件。teammate 的 `capabilities` 视图必须绑定当前 task，显式跨 task filter 返回 typed error；master 保留既有显式 session-wide 读取权限。该 facts page newest-first，最多 20 个 invocation、每类 8 个 closed opaque refs、serialized facts 最多 64 KiB，只内联 identity/status/timestamp/count/ref；不得把文档正文、output payload 或 evidence body 重新塞进 prompt context。当前实现仍会 hydrate rich repository rows，窄列 query、lazy sections 与 cursor 属于 `docs/v3/architecture-proposals/bounded-capability-facts-query.md` 的后续大调整
- 通用 harness 不按 AOX/HMM、research 或其他领域关键词注入 recipe、改写 delegation 或剥夺工具。领域 SOP 进入 `docs/v3/workflow-packs/*.workflow.json`：只有 caller 显式提交完整 `workflow:<id>@<semver>#sha256:<manifest-digest>` 才会选择；manifest 固定 knowledge document version/digest，并声明 capability/tool requirements。`task.delegate.workflow_refs` 只能显式选择 caller 当前授权 refs 的无重复子集；省略或 `[]` 表示不绑定，不能把 parent focus 的全部 workflow 隐式传播给 teammate。claim 前校验 target role/tool/engine 与 manifest snapshot，teammate restore 再校验 drift；失败保持 task、agent、inbox、signal 无副作用。blank-world collector 还必须从 durable delegation document 重建 role-scoped binding：AOX executor 精确绑定 campaign workflow ref 和完整 manifest snapshot，researcher/reporter 必须保持空绑定；bundle verifier 对 snapshot 的 core/content digest 离线复算。模型的 `skill.load` 不能自行激活 workflow pack，agent 在版本化真实约束内仍保留策略自由
- terminal task 上残留的 wakeup signal 是 stale runtime fact，应被安全消费为 completed signal，不应再次驱动 teammate loop 或制造 runtime failure
- controlled operation 进入 terminal 后，对应 `inv_sandbox_adapter_<operation_id>` engine invocation 必须稳定进入 terminal；该不变量只收口 runtime 状态，不代表业务 task completed

---

## 6. Public Interfaces 与 Workspace Projection

当前 V3 主要公开接口：

- `POST /v3/sessions`
- `GET /v3/projects/{project_id}/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `POST /v3/sessions/{session_id}/runtime/drain`
- `GET /v3/sessions/{session_id}/runtime/commands/{command_id}`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/pending-approvals`
- `GET /v3/sessions/{session_id}/events`
- `GET /v3/runtime/health`
- `POST /v3/approvals/{approval_id}/resolve`

Public HTTP contract 使用 strict request DTO 与显式 response DTO：未知字段、非法 enum、空 update 与长度越界统一返回 `422`，所有错误统一投影为 `error.code/message/hint/details`，不再混用 FastAPI `detail` 字符串。approval actor 与 lane claimant 只取认证 principal，调用方提交 identity 字段会被 DTO 拒绝。`GET /v3/runtime/health` 只返回 `v3.runtime_health.v1` 的脱敏 component 状态和 deployment/storage profile；worker id、原始错误、Host path、runner config 与 secret 只能留在受保护的 debug/内部边界。

SSE 保留默认的 typed-event 模式，并提供 `envelope=1` 的稳定 generic 模式：SSE name 固定为 `openzyme.event`，真实类型在 JSON `event_type` 中。Web UI 使用 generic envelope，因而新 event type 不依赖前端 allowlist；cursor、`Last-Event-ID`、visibility 与 restart replay 契约不变。CLI 与 Web UI 的 mutation 自动生成 `Idempotency-Key`，浏览器 approval body 不再携带 client-owned `actor_ref`。

`GET /v3/sessions/{session_id}/workspace` 是 UI/CLI 的 canonical snapshot，至少包含：

- `session`
- `conversation`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `agent_traces`
- `activity_feed`
- `artifacts`
- `report_drafts`
- `reports`
- `capabilities`

Projection 约束：

- conversation 只表达用户与 master 的产品级对话
- teammate 输出、工具调用、trace 和 protocol thread 通过 `agent_traces`、`delegation`、`activity_feed`、`inbox` 等 read model 表达
- `delegation.agents` 表达 resident team roster，而不是最近一次 `task.delegate` 的临时返回
- `artifacts` 是 session 共享工作面；session workspace 属于 collection read model，`artifacts`、`artifact_index.latest`、`activity_feed` artifact payload 与 capability-run artifacts 统一复用 `artifact.list` 的 deterministic bounded item projection。完整 canonical metadata 仍原样保存在 Artifact row 并通过 `artifact.get` 分页读取，workspace 只内联短 identity/scalar/small-container 与 versioned digest/count/size/omission/read hint；大 accession、sequence/page digest、identity mapping 或 file manifest 不得在多个 workspace branch 线性重复。`storage_uri` 只属于 Host-private catalog record，workspace/API/agent tool result 只能暴露安全 artifact 投影，不能暴露 Host repo path、Host artifact path、sandbox host path、runner private path、SSH/Slurm config 或 runner credentials
- mutation 内的 derived activity-event backfill 只能构造 sanitized activity projection，不能递归调用 composite workspace；approval resolve 可继续返回 bounded workspace command result，但 SQLite write transaction 不得随无关 Artifact metadata 的多分支全量回显线性放大
- 外部 provider 下载进入 control plane 时默认登记为 sealed artifact，metadata 记录实际 bytes 的 SHA-256 `content_digest` / `sealed_digest`、provider、external id/source locator、format、retrieved_at 与 provenance；executor sandbox 内的 `rcsb_pdb.download_structure` 走 `rcsb_pdb.download_structure.provider:v1` 受控 provider operation，由 Host 下载、校验和登记结构 artifact，sandbox 不直接联网；`hpc.stage_artifact` 只消费 catalog 授权和 sealed digest，fpocket/FASTA/PDB 等业务输入合法性由后续 capability tool 校验
- 执行相关源码必须可审计：executor 日常编辑发生在 persistent sandbox workspace 内；进入 dry-run、approval、正式执行或报告复用前，Host 必须把相关源码 snapshot 为 `ArtifactKind.CODE` artifact，记录 `metadata.semantic_type="pipeline_source"`、SHA-256 `content_digest`、`sandbox_workspace_id`、entrypoint、file digests 与 version/lineage metadata
- `report_drafts` 是 reporter 的中间交付面，不是一次 invocation 的临时字符串
- `capabilities` 按 capability key 承载 research/execution 等投影，避免把 engine 内部状态固化成顶层 contract
- `runtime_state` 是 diagnostic-only projection；agent 若需要低摩擦读取完整世界事实，应通过 `world.inspect` 查询 task、artifact、operation、approval、outcome、signal、tool surface 和 route policy，而不是从 prompt 片段或 artifact 名称中猜测

---

## 7. Control Plane、Protocol 与 Runtime

### 7.1 Task 与 Delegation

`Task` 是 session 内可调度、可委托、可恢复、可完成的内部工作单元。默认由 master agent 基于用户对话创建和编排。

`task.delegate` 的职责：

- 校验 task 是否存在
- 校验 teammate role 是否有效
- 拒绝 blocked、already assigned、非 `todo` task
- 使用 `agent_role` 表示能力选择，使用可选 `agent_ref` 解析已有 canonical teammate；不得接受 role 字符串作为 `agent_id`
- 在需要新 teammate 时创建 canonical `agent:<role>:<opaque-id>`，分配 role-specific nickname、display name 与 routeable handle
- 持久化 delegation payload
- 调用 `ProtocolService.delegate()`
- 返回 `wakeup_queued` 或明确失败 envelope

`ProtocolService.delegate()` 的职责：

- 创建或更新 canonical `AgentMember`
- 写入 `delegation_request` inbox message
- 排队 runtime wakeup signal
- 发出 `agent.spawned` / `agent.delegated` 等事件

`task.create`、`task.update`、Host `POST /v3/tasks` / `PATCH /v3/tasks/{task_id}` 与 repository 默认 edit intent 都不能写入或跨越 business-exit status；除 agent-level / legacy pending approval block 这类已文档化机械迁移外，`blocked`、`completed`、`failed`、`cancelled` 必须走唯一业务出口命令 `task.finish`，不得通过 raw `TaskRepository.save()` 绕过。durable SDK attached continuation 的 park 只暂停 agent/runtime，task 保持 `in_progress`，待 exact continuation delivery 的 `ENGINE_COMPLETED` owner wake 继续。blocked task 保持 blocked 时仍可做描述修正、lane unbind 等非状态编辑，但不能直接再次 finish；必须先通过显式 resume/reopen 迁移回 `in_progress`。completed / failed / cancelled task 连非状态 edit 也 fail closed。`task.finish` 只可改变 status、updated_at 与 failure fields，并在同一个 SQLite transaction 中写 `task_finish` document、task row 与 durable event；commit 后 SSE 才可见，任一写入失败必须整体回滚。可选 `evidence_refs` 的公开 wire contract 是闭集 `<kind>:<id>`；tool schema 与 invalid-result details 必须共享 supported kinds、格式和示例，repository 仍逐项解析当前 session identity。runtime 不按 opaque id 猜 kind、不补 prefix，也不把尚未 finalization 的 closure request 替换成 `scientific_closure:<closure_id>`。测试需要构造历史终态时必须显式使用 fixture seed intent，不能让产品写路径获得同等豁免。

业务 task 终态必须由 agent 通过 `task.finish` 或已文档化机械迁移显式写入；runtime idle、max steps、tool result 或 protocol message 本身不自动表示 task completed。允许的机械迁移只包括 task claim、agent-level / legacy pending approval block 与 approval resume 等已命名 command；durable SDK approval/continuation 不改变 task status。机械迁移使用显式 mechanical intent，必须真实改变 status，且除 status / updated_at 以及 claim 所需 assigned_ref 外不得夹带 task 字段修改。`task.finish` 授权只比较 canonical `agent_id`，role 字符串不能代表 task owner。

`blocked_by` 必须始终形成 session 内 DAG。service 在写前返回包含 cycle path 的领域错误；SQLite `task_dependencies` 的 INSERT / UPDATE trigger 同时拒绝跨 session edge 和任意长度的依赖环。Task row upsert 与该 task 的 dependency replacement 必须原子提交，不能留下“task 已更新但 dependency 只写入一部分”的中间状态。

### 7.2 Inbox 与 Protocol

`protocol.send` / `protocol.thread` 是 agent team 内部协调工具。

默认语义：

- `protocol.send` 写入有 recipient、correlation、payload、status 的 `InboxMessage`
- agent recipient 只能解析现有 canonical `agent_id`、`@handle`、唯一 nickname/display name；`researcher` / `executor` / `reporter` 是 role，不是 recipient identity
- agent recipient 的 unread inbox message 会创建 `inbox_unread` wakeup signal
- delivery 成功只表示消息和 wakeup 已排队，不表示 recipient 已执行或任务已完成
- request-response、diagnostic、handoff、clarification、result completion 都应复用 correlation thread

### 7.3 Runtime Signal

`AgentRuntimeSignal` 用于表达需要唤醒 resident teammate 的事件。

当前 signal reason 至少包括：

- `delegation_assigned`
- `inbox_unread`
- `task_available`
- `approval_resolved`
- `engine_completed`
- `manual_resume`

Claim 语义：

- scheduler 只能 claim `pending` signal 或 lease 已过期的 `claimed` signal
- claim 写入 `claimed_by`、`claim_expires_at` 并递增 `attempt_count`
- turn 成功后写为 `completed`
- retryable failure 可在 attempt 上限内回到 `pending`
- non-retryable 或 exhausted failure 写为 `failed`

provider/model 失败是否 retryable 由 `LlmInvocationRuntime` 的 taxonomy 决定。若 runtime 内部 retry 成功，当前 turn 继续执行；若 runtime retry 耗尽但 signal 仍有剩余 attempt，scheduler/runtime service 将 signal 释放回 `pending` 并记录 `signal.retry_scheduled`；非 retryable 或 signal attempt 耗尽才写为 `failed`。runtime idle、tool result、protocol message 或一次 provider transient failure 均不自动改变业务 task 终态。

bounded turn 达到 max steps 时使用结构化
`agent_turn_budget_exhausted`：exact signal/turn 以 `retry_eligibility=terminal` 结束且不
自动重放，但 `recoverability=agent_can_replan` 表示 master 可在新的 canonical signal/turn
中显式选择继续、改道、求助或拒绝。signal-local `effect_certainty=no_effect` 只描述 signal
transition，不能擦除该 turn 内已经持久化的 controlled-operation effect；task status 与业务
failure fields 保持不变。source-bound master wakeup 去重，并从 canonical failure observation
和当前 selection evaluation 构造 bounded recovery facts。

runner-backed controlled operation 存在 exact runner reservation 时，Host 先读取 sealed
runner terminal observation；本地 `Run` 只参与成功 result 的 materialization/recovery，
不能覆盖 runner causal source。closed attempt 公开 safe terminal status/error/effect/retry，
因此 pre-dispatch `transport_connect_failed/no_effect` 原样贯穿 execution、operation、
continuation 与 `FailureObservation`，private transport diagnostic 仍不投影。AOX 从
canonical operation、唯一 execution/continuation、attempt binding 与 exact failure 生成一份
有界 `probe|formal` operation facts，observation、diagnostic 与 failure evidence 共用其
count/digest/truncated 元数据。

controlled-operation failed observation 默认停止。唯一 bounded handoff 是：当前 formal
attempt、terminal no-effect execution、delivered continuation、typed
`controlled_effect/agent_can_replan/terminal` failure、业务非终态 owner task，以及整个
session 唯一 pending/unclaimed/zero-attempt `engine_completed` signal 的
source/correlation/agent/task/lane 全部 exact。driver 只允许下一次既有 drain 消费该 wake
一次；不创建 authority/work、retry/replay effect 或规定策略。任何缺失、重复、claimed、
cross-bound、unknown-effect 或 dispatch-in-doubt 事实都保持原 failed stop。

Core 为每个 `AgentRuntimeOutcome` 生成 immutable typed
`AgentRuntimeOutcomeSettlement`。闭集 disposition 只有 signal completed、signal failed、
waiting approval 和 budget-replan handoff；budget handoff 在同一个短 repository
transaction/session runtime authority 内绑定 exact source occurrence、task/agent/lane/correlation
snapshot、failure observation 与唯一 pending master successor。若 successor 缺失、重复、
cancelled 或任一 identity 漂移，Core 不生成 handoff disposition，结果保持普通 signal
failure。后续 task 或 successor 状态变化不得反向改写这个 occurrence snapshot。

任一 master 或 teammate max-step outcome 都是当前 bounded batch 的 barrier。已经 claim 的
同一 wave 可以完成收尾，但 scheduler 随后必须停止 claim；即使 command 的
`max_signals > 1`，本次 finalization 新建的 successor 也只能由下一条 command 或下一次
background tick 推进。这个规则是 runtime correctness，不依赖 AOX 等调用方把
`max_signals` 固定为 `1`。

manual runtime drain 在 scheduler batch 结束时先形成 immutable core receipt，再结算
trace/activity/consistency/event/workspace projection。公开 `runtime_command_outcome@2`
分别表达 scheduler 与 projection outcome；即使 post-scheduler projection 失败，也必须保留
真实 `processed_signal_count`、suspension/output/event identities，并在已经处理 signal 时令
`replay_safe=false`。只有 core receipt 尚未形成的 boundary failure 才能报告零 processed；
旧 `@1` outcome 只读兼容，不回填新字段。Host core-receipt assembly 直接消费 Core typed
settlement；不得先序列化再解释、按对象 identity 分类、重扫 mutable signal/task/failure/agent
repository，或把 task business status 反向映射成 scheduler failure。

r67 删除 AOX bounded driver、work fingerprint 与 two-empty/no-wakeup reducer。每个 public
runtime command 仍返回 validator-backed `processed_signal_count`、`replay_safe` 与 typed
projection outcome，但 Host 不跨 command推导继续/停止或业务 terminal。Codex conductor
显式决定是否提交下一条 command；它不能 auto-enqueue、制造 successor 或改变
`runtime/drain` / task semantics。

scheduler layer 的 `completed` 表示 bounded batch 已完成结算，不表示每个 signal、task
或业务目标成功。teammate max-step 只有在 exact failed signal、同 attempt 的 canonical
`agent_turn_budget_exhausted` observation、非终态 task 与 exactly one source-bound
pending master wakeup 全部一致时，才可作为 completed handoff；原 signal 仍保持
failed/terminal，后继是独立 master turn。任何闭包缺失、普通 failure 或 master max-step
继续令 scheduler layer failed。反过来，agent 显式把 business task finish 为
`failed`，但本次 signal 正常 completed 时，scheduler settlement 仍可 completed；两者是
正交事实。

普通失败结果已在同一 turn 交给 agent 时不额外制造 recovery wakeup。continuation 或
controlled operation 在原 turn 之后才暴露成功或失败时，统一按 exact source/version
创建 `engine_completed`；claim 后从 repository 重建 effect、result 与 failure facts，
不能复制旧 prompt 或规定固定修复策略。Host finalizer 的 nonretryable boundary failure
继续写 system-attributed observation/diagnostic，不伪造 agent recovery signal。

---

## 8. Capability Engines

### 8.1 Deep Research 与 Provider Tools

`researcher` teammate 可以直接调用轻量 provider tools，也可以在开放式、多步、跨来源综合任务中调用 `deep_research` engine。

`deep_research` 内部 researcher/synthesis 的 LLM 调用必须复用同一 `LlmInvocationRuntime`，不能维护 engine 私有 retry 或隐藏 fallback。一次 retryable 502/`Retry-After` 若在 runtime 内恢复，engine invocation 继续推进；若 provider/runner 异常无法恢复，engine 必须写入 failed dossier / failed `EngineInvocation`，不能把 invocation 留在 `RUNNING`。

默认 provider / research surface 包括：

- PubMed
- Semantic Scholar
- UniProt
- RCSB PDB
- InterPro
- Tavily / web search 类能力（按配置与 live gate 启用）

Research 输出应归一化为 evidence、source refs、gaps 和必要的 workspace artifacts。普通 search hit 是 source/evidence，不应伪装成 artifact；真实下载或生成的 sequence / structure 文件才进入 artifacts。

文献 provider 使用结构化 `completed | empty | degraded | failed` outcome 和 bounded invocation policy。PubMed 是 AOX/HMM cutover 的 required quorum：至少一个来自真实 PubMed provider、schema-valid PMID、完整 provenance、绑定 NCBI identity digest 且非 fixture 的 citation 才完整，empty/schema drift/provider failure 均 fail closed；Semantic Scholar 与 Tavily 只是 enrichment，429、retry exhaustion、absence 或 empty 必须保留为 `degraded`，不得生成 synthetic hit 或抹除有效 PubMed evidence。configured Host 即使没有 Tavily key 也必须装配 PubMed/Semantic Scholar direct tools，并从 `OPENZYME_NCBI_EMAIL` / `NCBI_EMAIL`、NCBI tool/API key 与 `SEMANTIC_SCHOLAR_API_KEY` 注入各自配置，不能把 bio literature availability 错绑到 Tavily。

AOX researcher 可以在 bounded policy 内迭代多次 PubMed query，harness 不规定固定 query、one-call 或 first-success stop。researcher 仍需在唯一 `task.finish.evidence_refs` 中显式采用 exactly one primary PubMed artifact，report claim 必须引用其中的 PMID/source。除此之外，`@3` collector 从 scientific-attempt control plane 封存全部 controlled-operation occurrence、disposition、adopted role、materialization、selection、quiescence、closure 和 authorization；未采用的探索、empty、failed 或 superseded operation 不会被删掉，也不会因“曾经失败”自动污染合法最终链。零个/多个 primary、按 latest/result-count/prose 推断、identity/lineage 漂移、unknown effect 或跨 attempt reuse 都 fail closed。

direct provider tool 在任何网络 I/O 前先写 `EngineInvocation(RUNNING)`，然后在 success、empty、degraded、typed failure、untyped failure 或 evidence-seal failure 上终结同一个 invocation；required PubMed `empty` 或 typed `failed` 必须终结为失败，不能因 callable 正常返回而被记为 success。可用于科学/报告的 citation metadata、call-local quorum 与 safe provider transcript 通过 artifact boundary 的 external ingress 复制到 Host 注入的 attempt-scoped content-addressed 只读 Blob root，按实际 bytes 重算 `content_digest/sealed_digest`；单个 search hit 仍是 source ref，不因同时存在 provider evidence artifact 而变成文件资产。source ref 持久化 PMID、provider supplied DOI、title、authors、venue/date、不可逆 NCBI identity digest、retrieval/request/response provenance 与 evidence artifact link。API/workspace 只投影安全 locator、status、identity digest 和 evidence digest，credential、private URL/query、private header、Host path 与受限全文不得进入 error/evidence/public projection。

research unit 的 `topic` 表示科学语义主题，不等于 provider 的检索类别。Tavily `web.search.topic` 只允许 `general`、`news`、`finance`，默认由 adapter 配置决定；科学主题必须放在 query/brief 中。tool schema 必须把该枚举呈现给 agent，绕过 schema 的非法值也应在 provider 调用前返回可恢复的 `invalid_tool_arguments`，不能把语义主题直接传给 provider，也不能静默改写为可运行类别。

### 8.2 Persistent Executor Sandbox 与 Execution Pipeline

V3 execution 的目标主路径是 executor-owned persistent sandbox workspace，而不是 executor 直接调用 runner、SSH、Slurm 或 runner config。executor 在自己的 sandbox 中迭代脚本、运行 Python/bash、检查中间文件；当某段源码进入 dry-run、approval、正式执行或结果审计时，Host 将相关 sandbox working-copy source snapshot 为 `ArtifactKind.CODE`，并把 snapshot digest 绑定到 execution plan、approval、run、artifact provenance 和 workspace projection。

关键接口：

- executor-facing `sandbox.workspace.status`
- executor-facing `sandbox.file.*` / `sandbox.exec`（Session 09 runtime 面）
- sandbox 内 `openzyme_pipeline` SDK
- Host/internal execution plan、run、approval、provenance 记录
- 迁移兼容 `execution.pipeline.start` / `execution.pipeline.status` bridge；它们不再是 executor 必须调用的 authoring 主路径
- docs 工具 `docs.search` / `docs.read`

执行边界：

- executor sandbox 运行在受控 rootless Podman 环境中，默认无网络、非 root、资源受限
- 默认多个 executor 使用同一个 Host-configured sandbox base image digest，分别启动各自的 rootless container process 并挂载各自独立的 persistent sandbox workspace；image layer 可以共享，sandbox workspace 不共享
- executor sandbox base image 由 Host-level image registry / bootstrap contract 管理，记录 `image_ref`、resolved `image_digest`、最低能力声明和 `sandbox_protocol_version`；缺失或不兼容返回结构化 image error，不自动换 image 或回退到旧 pipeline runner
- `image_ref` 只是配置/发现入口，不能作为执行身份。Host preflight 必须把它解析为完整 `sha256:<64hex>` immutable image id；Podman `.Id` 的裸 64 位 hex 与带 `sha256:` 前缀形式只在此处做严格等价规范化，其他格式拒绝且不得写入 image registry。同时对实际注入 sandbox 的 `openzyme_pipeline` SDK source tree（排除 bytecode/cache/symlink）计算 digest；`runtime_identity_digest` 绑定 image id、SDK digest 与 sandbox protocol。只有 exact authority-bound formal supervised child 可在 fresh SQLite 上显式登记这一 identity；dev Web UI、eval/live fixture 与普通 Host 不得根据 ambient Podman 状态静默登记。正式执行前再次解析并逐字段比对，复制 SDK 后再次验 digest，Podman `run` 必须使用 immutable image id；任何 tag 漂移、SDK 漂移或 identity 缺失都在 sandbox/runner 前 fail-closed
- 每个 executor 拥有独立 persistent sandbox workspace；`sandbox_workspace_id` 按 `session_id + canonical agent_id/member_id` 复用，`task_id` / `lane_id` 只是当前 focus metadata；持久化对象是 sandbox workspace volume、manifest、projection summary 和 canonical records，不是容器进程或 container id；容器可重启，sandbox workspace volume 保留，`sandbox_workspace_id` 进入 execution provenance
- sandbox workspace root 是 Host composition 注入的 attempt/deployment-scoped 依赖，不是 workspace status、file service 或 exec service 可各自选择的默认值；同一 runtime context 中的 `sandbox.workspace.status`、显式/隐式 workspace lookup、file CRUD、source snapshot、Podman bind 与 recovery 必须解析到同一 root。显式 `sandbox_workspace_id` 仍须按当前 `session_id + agent_member_id` 校验 ownership，不能因 id 已知而绕过 actor 绑定
- `sandbox.exec.argv` 是 direct exec-form 数组，不存在隐式 shell parsing；需要 shell 时必须由 agent 显式选择 `bash -lc`。明显把 heredoc 当作 Python argv 的请求应在 source snapshot、SandboxRun 和容器进程产生前以 typed tool error 拒绝并给出真实可行路径，Host 不静默改写为 shell，也不因此放宽真实 nonzero run 的 fail-closed 语义
- 通过前序 request、workspace、layout 与 runtime 校验并进入 source preflight 的每次 `sandbox.exec`（包括 `python -c`、package/signature inspection 与 diagnostics）都在 `SandboxRun` 和 process 产生前封存整个非空 `/workspace/src`；前序校验可以更早返回其自身错误。`sandbox.exec` 不是 read-only environment inspection shortcut；API/签名事实优先来自 `docs.search` / `docs.read`，确需 runtime introspection 时由 executor 先写入显式 inspection source。空树以 `source_snapshot_empty` fail closed，并明确未创建 run/process；Host 不自动生成占位源码或提供未审计 fallback。harness 只忠实呈现该 provenance 约束，不替 agent 固定科学策略
- `/workspace/input` 是 Host 管理并以 read-only 挂载给 sandbox process 的授权输入树；executor source 不得对 root、materialization target 或其父目录执行 `mkdir`、write、copy 或预创建。`artifacts.materialize` 由 control boundary 在 Host 侧创建并授权 target/parents，成功后只返回可读 sandbox path；可变 scratch 使用 `/workspace/work`，待登记结果使用 `/workspace/output`。该真实约束必须同时出现在 tool descriptor、受控 artifacts 文档和 workflow prompt，`EROFS` 不得触发 remount、alternate-path fallback 或重复 operation
- 无 canonical workspace row 时，派生 workspace leaf 必须不存在并由 Host 以 no-replace/exclusive-create 语义一次性建立 `/workspace/src|input|work|output|logs|manifest` 六目录；预存目录、文件或 symlink 一律进入 `sandbox_volume_corrupt`，不得接管或修改现场。已有 workspace 的根或任一必需目录若缺失、不是目录或为 symlink，同样 fail closed，status/file/exec 不得静默补成空目录。`sandbox.exec` 在 source snapshot、run record 或 container process 产生前再次校验完整布局，防止 stale READY 退化成底层 runtime path error
- Host repo、用户 home、`.ssh`、数据库、runner config、HPC credentials 不得挂载进 sandbox
- sandbox 内可做文件 CRUD、bash、python 和中间结果检查；sandbox workspace 是 working copy/cache，不是 canonical truth
- NCBI、UniProt、EBI HMMER 等网络数据库请求只能通过 `openzyme_pipeline.bio` 由 Host supervisor 托管执行；sandbox 不直接联网，也不保存 provider credential 或 Host cache path；provider outputs 必须写入 caller 指定的 `/workspace/output/...` 并经 Host artifact boundary 登记，RPC 只返回 bounded summary、manifest 和 artifact refs
- sandbox 到 Host 的 control socket 每个 connection 只传一个 JSON-RPC 2.0 NDJSON frame；request/response payload 的对称硬上限均为 `4 MiB`，不含终止 newline。`recv` 的 `64 KiB` 只是一块读取大小，Host 与 SDK 必须跨 chunk 聚合到 newline；非 null JSON-RPC `id` 只允许 UTF-8 bytes 不超过 `256` 的 string 或 signed int64（排除 bool）。其余 request semantics 非法时保留已安全提取的 id；id 本身超限/非法或无法安全提取时 error 使用 `id=null`。畸形 UTF-8/JSON、duplicate object key、`NaN`/`Infinity`、EOF 残帧、response identity 漂移、超限均以 bounded structured transport error fail closed；SDK request serializer 和 Host response serializer 同样禁止 non-finite number。首 newline 后已观察到的非空 trailing bytes 在 dispatch 前拒绝。硬保证是每 connection 最多执行一个 request：首 request 接受后才晚到的第二帧可能只观察到 connection 关闭而没有第二个 error，但不得执行第二个 method/operation。单连接错误不得终止 accept worker，SDK 必须在发送前检查 request size 并在接收时实施同一上限；Host 超大 response 只能替换为小型结构化错误。connection/read/send 与首字节后的 partial-frame 使用固定 5 秒 I/O timeout。对于 `durable_async_v1`，Host 在 admission 后把 exact socket/process epoch 交给 attached-process supervisor；approval/provider/HPC wall time 由 execution 与 continuation workers 推进，原 agent signal、session lease 和 HTTP request 已释放。只有 frozen `legacy_sync` owner 保留兼容同步等待，不能成为新 operation fallback。该 transport 不创建第二套 canonical execution state，也不升级 sandbox protocol/image version
- `artifacts.register` 的 logical metadata 与 4 MiB control frame 分离：SDK 对 ASCII-safe canonical JSON `<=256 KiB` 的 object 内联，对 `(256 KiB, 32 MiB]` 自动写入 attempt-local `/workspace/work/.openzyme/artifact-metadata/<sha256>.json`，wire 只传 exact-four-field `artifact_registration_metadata_sidecar@1`；更大 object 在连接前 non-retryable fail closed。Host 通过当前 workspace 的 fd-anchored/no-follow 路径在任何 validation、seal 或 catalog mutation 前核 exact wire path、regular file、size、SHA-256、strict UTF-8、duplicate key、non-finite、object root 与 canonical bytes；inline raw caller 也必须通过相同 canonical JSON 规则及 `256 KiB` 上限。top-level `content_digest`、`sealed_digest`、`tree_digest` 是Host-owned registration identity，caller在SDK和Host effect前均不得自报。sidecar 只是 transport spool，不是 Artifact、科学 evidence 或 canonical storage，catalog 仍保存完整 logical metadata。成功响应固定为 bounded `artifact_registration_response@2`，其中artifact是exact `{artifact_id,metadata}`闭集而非general public projection，metadata与validation分别使用versioned summary；`fasta_zero_records@1` 的回显 `derivation_contract_id` 在 effect 前限制为最多 `256` UTF-8 bytes，4 MiB 上限不提高。compat provisional response不重复回显path，并在128-item上限内有固定预算。`register_many` 另有 128-item/32 MiB unique-metadata aggregate cap，并在写入前解析全部 metadata transport；它仍是逐项 commit 的兼容 helper，晚项非 metadata 失败的跨项原子化属于 outcome-unknown 架构提案，不在本 Goal 伪称已经完成
- Host-supervised bio provider 不得把按记录线性增长的 identity map 塞进单个 FASTA Artifact 的 inline metadata。NCBI/UniProt 的完整逐序列 identity 记录保存在同一 provider result 的独立 canonical `metadata.json` Artifact；FASTA Artifact 只以 `sequence_digest_count`、exact canonical `sequence_digest_index_digest` 与 `canonical_sequence_digest_index@1` 替代线性 map，并继续保留固定 database/retrieval/release/identity/validation provenance。该 index 对 NCBI 使用产出 FASTA 的 requested accession，对 UniProt 只使用产出 FASTA 的 active primary accession；typed inactive identity 不计入。digest preimage 是按 key 排序、`indent=2`、ASCII-safe escape、末尾一个 LF 的 UTF-8 JSON object，count 同时等于 object member 与 FASTA record 数。它只是 bounded catalog summary，不是 cutover eligibility 输入；formal UniProt 的既有 raw→parsed metadata→FASTA 科学闭包仍须独立验证，其他 provider 路径继续依赖各自 byte-Artifact/operation contract 而不能把该摘要当作 raw normalization 证明。Host 在写入任何 provider draft 前必须对整组 draft 完成 path 合法性、组内重复、既有 catalog digest 冲突和 registration metadata transport 预检；这关闭已知的 conflict/oversized-metadata partial write，但 ArtifactBoundary 的逐件 validation/seal/catalog commit 仍非跨件事务，不能据此宣称 set-level atomicity
- `bio.uniprot_fetch` 的 route policy id 保持 `bio.uniprot_fetch.provider:v1`，provider config 更新为 `provider_config:uniprot:v3`，identity contract 更新为 `uniprot_primary_sequence_identity@2`。一次 SDK 调用、一个 controlled operation 和一次 approval 最多承载 `100000` 个 accession；Host 固定拆成每 query 最多 `100` 个 accession，`batch_size` 仍只控制 UniProt response page 的 `size`（上限 `100`），`Link: rel=next` page cap 按 query 独立计算。每个 response page 与生成它的 exact query accession slice/digest 绑定；返回另一个 query 中的 requested identity 也属于 cross-query swap，必须 `provider_identity_mismatch`。next link 只允许 exact `https://rest.uniprot.org[:443]/uniprotkb/search` 且无 userinfo/fragment；malformed/off-origin 以 `provider_schema_drift` 停止，public diagnostic 只保留 link digest 和固定 expected endpoint。active sequence records 与 typed inactive records 必须对 complete requested set 形成 exact 互斥分区；inactive 仅在 primary accession 精确等于 producing query 中的 requested accession 时接受，并形成 `inactiveReasonType=DELETED|MERGED` 的判别联合。`DELETED` 保留非空 canonical deleted reason，`MERGED` 保留非空、去重的 `mergeDemergeTo` replacement-target annotations；两者都保留 UniParc id、release/retrieval 与 response/record digests，固定 `identity_replaced=false`，无 sequence/audit，且不得跟随、抓取或使用 replacement、UniParc、HMMER sequence。unknown、`DEMERGED`、malformed inactive、active 缺 sequence、完全无返回或 partition 不闭合均 fail closed。approval 前 SDK 投影 accession/query batch 数（默认 `100` query cap 下当前完整 `37772` 对应 `378`）只是透明预测，不是实际 limit 或 approval authority；Host 注入的 provider config 可收紧 cap，并在 HTTP 前作最终校验。把 canonical estimate/actual limits 从 route policy+Host config 重建并绑定 approval/config identity 的大改仅记录在 [Host-authoritative controlled-operation resource estimate and limit snapshot](v3/architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md)，本 Goal 不实施。transcript 继续绑定 query/page 坐标、accession range/count/digest 与 response digest；HTTP failure 只增补 query-batch index/count/start/count/digest 和 completed/requested page 坐标，不回显 raw URL、accession list 或 cursor。duplicate detection 用 frequency-map 线性扫描并只对 duplicate keys 稳定排序。所有 query/page 仍属于同一 operation，不得拆成重复 approval。当前输入已是 primary UniProt accession；切换 async ID Mapping 所需的 durable job handle、submit/poll/result resume、幂等与 evidence/verifier schema 迁移不在本 Goal 内
- `bio.hmmer_search` 的 route policy id 保持 `bio.hmmer_search.provider:v1`，provider config 更新为 `provider_config:ebi_hmmer:v3`。它保留 v2 的无缺口 materialization：result `page_size` 默认与上限均为 `1000`；poll URL 显式携带 `page=1&page_size=<configured>`，terminal poll payload 只提供 status 与 `result.stats.nreported` closure，即使 body 含 hits 也不作 result page；result materialization 永远从同一 page size 的显式 `page=1` 开始，再逐页读到稳定 `page_count`。v3 另把 EBI/Celery `RETRY` 识别为同一 accepted job 的非终态，继续轮询原 job id，绝不重新 submit；poll deadline 为 `3300s`，在 `3600s` sandbox 上限内覆盖 provider 默认 30 分钟首次 retry 边界并保留 300 秒 retirement 余量。deadline 后仍为非终态映射为 retryable `provider_timeout`；`FAILURE`、未知状态、跨页 `page_count` 漂移、非截断 raw hit count 不等于 terminal `nreported`、或 SUCCESS empty 不是 `nreported=0/page_count=0/hits=[]` 均 fail closed。这一修复不改 `max_hits`、provider order 或 parsed-hit schema
- provider output authority 必须由 Host 在 ControlledOperation admission 前验证。SDK 保留 caller 的 exact `output_dir`；Host 只接受 canonical `/workspace/output` descendant，拒绝 alias、traversal、backslash/control character 以及与 declared `expected_outputs` 不一致的值，并封存 `provider_output_path_invalid/no_effect`。该失败不创建 operation、不 dispatch provider，仍返回 failed ToolResult；terminal SandboxRun 的 `sandbox_exec_nonzero` 只能作为 source-bound wrapper，canonical wake facts 保留 earliest typed cause
- sandbox provider operation 已建立 request draft 后遇到 `PipelineSdkFailure` 时，Host 通过同一 sandbox artifact boundary 登记 `provider_request.json` / `provider_observation.json` / `provider_error.json` 三件 diagnostic artifact，然后以原 canonical code/stage/retryable 语义重抛，仅增补 safe artifact refs。这不是 provider success，不进入 AOX 17 件 normalized deliverable，也不授权 retry、operation replay 或 alternate provider
- provider、artifact registration 与 HPC fetch 的 bounded response 允许在嵌套 provenance 中重复描述同一 artifact，但 executor 不应递归猜测 envelope。`openzyme_pipeline.artifacts.provider_file_ref`、`registered_artifact_ref` 与 `fetched_output_ref` 是按 response origin 互斥的 selector，不是可串联 pipeline：前者只读 provider manifest，中者只接受 exact `artifact_registration_response@2` 及其 bounded metadata/validation summary，后者只读 `fetch_refs`；summary 缺少原 logical metadata 字段不表示 catalog metadata 被截断或为空。durable provider 的 immutable result handle 保存完整 Host-verified S12 adapter envelope；唯一 transition service 的兼容投影把完整值写入 `adapter_result_envelope`，只把其中 exact object `bounded_summary` 写入 `result_summary`，保证 sandbox 看见与同步 executor 相同的 direct provider response。provider effect 已完成并登记完整 transcript、但 callback 因 execution fence/进程中断而丢失时，reconcile 只能从同一 operation/request 的 sealed `provider_request.json` 与 `provider_observation.json` 重建：Host 先核实际 bytes digest、strict JSON closed schema、route/provider/config/output-dir 与全 artifact metadata identity，再恢复原 provider summary、validation、warnings 和 `transcript_manifest`；不得用通用 recovered 摘要替换、再次请求 provider 或猜测 artifact。控制文档上限 `8 MiB`；完整 immutable durable result envelope 的 canonical JSON 上限与 core 统一为 `256 KiB`，inline `bounded_summary` 必须连同 envelope 其余字段一起落在该上限内。EBI HMMER 不得把全部 `candidate_accessions` 复制进 summary；候选身份真值只存在于 digest-bound `provider_parsed/parsed_hits.csv`，summary 只保留 count/schema/digest 与 transcript refs。任一 digest/schema/identity/size 漂移以 terminal-known failure fail closed；terminal-known observation 若自身不能通过 closed validation，则执行直接终结为 `recovery_failed`，不得重复 claim/reconcile 形成热循环。不存在该字段的 HPC run handle/failure envelope direct 投影，字段存在但畸形则 fail closed，不允许 SDK 递归猜测。attached process 恢复后的 `hpc.fetch_outputs` 必须使用 control-server 当前 repository 与 nested artifact-publisher mutation writer，不能重新进入已释放的 agent-turn runtime scope；durable HPC result 已冻结时只验证返回的 run/artifact/fetch refs 与 immutable adapter envelope 完全一致，不 raw save operation。兼容 `PodmanPipelineSandboxRunner` 的 run-local register 只能返回 `pipeline_provisional_registration_response@1(canonical=false)`，不得伪装成 durable catalog ref，registration selector 必须拒绝。provider/fetch selector 已返回 terminal canonical artifact ref，继续传给 registration selector 或构造 synthetic envelope 必须结构化 fail closed。三个 helper 均要求 exact-one artifact id/digest 并对 nested-only、重复或畸形投影 fail closed，不执行 I/O、fallback 或 operation replay。artifact boundary 的 source authority 是 control socket/controlled operation 所属当前 run 的 Host-owned snapshot，不能从 sandbox 参数自报，也不能因 workspace `last_command_summary` 尚指向上一命令而错绑旧 snapshot。AOX cutover 在 approval 前按 session/method 与 sandbox 历史检查 eligibility：同一 reached SDK method 的第二个 operation、已有 `failed|recovery_failed` operation 或 terminal failed sandbox run 均在 provider/runner dispatch 前停止该 attempt；checkpoint 只保留失败事实，不授权跨 run adoption。完整 cross-run effect adoption 仍只存在于对应架构提案
- durable HPC fetch 的不变性校验对 `run_id` 和带 declared path/digest 的逐项 `fetch_refs` 做 exact comparison；`registered_artifact_ids` / `output_artifact_ids` 是 durable result artifact set，必须成员唯一并在按 artifact id 规范化排序后比较完整集合。declared-output 顺序与 canonical artifact-set 顺序不同不是 identity drift，但任一成员、run、path 或 digest 变化仍 fail closed。runner terminal raw result 已携带 `mcp_hpc_toolchain_runtime_identity@1` 时，durable route 必须按 execution mode、catalog tool id、closed identifiers 与 SHA-256 字段重新验证并把 safe exact-eight-field identity 投影进 immutable result envelope；private SIF path 等 extra field 不得泄露。已存在但畸形/错绑的 identity 是 terminal-known `durable_hpc_toolchain_runtime_identity_invalid`，不得降为可重复 reconcile；缺失 identity 也不得从 toolchain id、pin 或 artifact metadata 推断，AOX collector 继续以 `toolchain_image_identity_missing` fail closed
- MAFFT、CD-HIT、HMMER CLI 等 AOX/HMM 生信工具只能通过 `openzyme_pipeline.bio_tools` 由 Host supervisor 托管执行；pipeline 不直接 shell/subprocess 调本地 binary
- MAFFT、CD-HIT、HMMER、Apptainer SIF、HPC runner 和领域 toolchain packaging 不进入 executor base image；它们属于 Host supervisor 的 backend/toolchain registry 和 bio_tools route policy
- CD-HIT cluster 真值来自完整 `.clstr`，由 Host/runner normalize 为 one-member-per-row 的 `cdhit_cluster_membership@1`；Host 必须在登记任何 CD-HIT output 前将 membership 与 staged FASTA 身份及长度闭合校验。aggregate representative/count、缺失/重复 member 或 deterministic fixture 均不能作为 cutover 证据
- 外部执行只能通过 Host-supervised SDK 进入 provider、明确配置的本地 adapter 或 HPC runner；AOX/HMM `bio_tools` 的 Session 14 产品 route 是 HPC-only，不以 Host-local Apptainer 作为 fallback。`openzyme_pipeline.hpc` 保留为 executor-facing placement / remote workspace / declarative stage-fetch namespace，领域能力优先由 `bio` / `bio_tools` / `structure_tools` / `docking` 表达，稳定边界是不暴露 SSH、Slurm、runner path、SIF path 或 database mount
- HPC catalog、fpocket / Vina / `bio_tools` tool execution contract、command rendering、RunSpec compiler helper 与 parser 的权威在 `packages/openzyme-tools`；`openzyme-engines` 只能调用这些 helper，不维护第二套 command template 或 parser；`openzyme-runtime.hpc_catalog` 仅保留迁移兼容 shim
- 科学结论只能来自可读、已登记并通过对应 parser 的 output artifact。pipeline step 的 parser 必须接收该次 runner 实际返回的 artifact refs，不能用空 artifact list 解析；fpocket 缺 `target_info.txt`、读取失败或无法解析时，即使 runner `raw_result` 自报 `pockets_found` 也不得生成 pocket count 或 `design_signal=proceed`；未知 tool parser 同样不得默认 `proceed`
- dry-run / validation 先生成 `ExecutionPlan`；需要 approval 的外部/backend operation 或显式 `inputs.approval_policy="single_plan"` plan 在用户 approve 前不得提交
- dry-run 必须列出 bio SDK operations、每种 operation 的静态 `max_calls`、route policy、approval requirement、预计 provider requests、分页/配额估计和 expected database artifacts；重复调用和 literal bounded loop 必须计入总量，函数体、动态 iterable、while/comprehension 等无法证明有限上界的外部 SDK 调用在启动 sandbox/runner 前 fail-closed；大型 FASTA、metadata、raw hits、parsed hits 与 sanitized provider transcript 均登记为 artifact，RPC 只返回 bounded summary
- dry-run 必须列出 bio_tools operations、资源估计、expected outputs 和 approval/route 需求；declared output 缺失、格式非法、资源超限、tool_missing 或 oversized log 均返回结构化状态
- runner-owned fixed bio-tool template 的 output path 是真实执行约束，不是 agent 可自由命名的逻辑标签；Host 必须在 runner/HPC dispatch 前把 agent 声明与 canonical path set 精确比较，不匹配时返回包含 expected/declared paths 的 LLM-readable `bio_tool_output_contract_mismatch`，不得静默改写后继续运行昂贵 HPC job
- plan、approval、execution invocation、RunSpec、output artifact provenance 与 workspace projection 记录 `sandbox_workspace_id`、`source_code_artifact_id`、`source_code_digest`、`source_code_version`、immutable image digest、Pipeline SDK digest、`runtime_identity_digest`、input artifact digests、operation set、backend route 和 expected outputs；正式执行前 Host 重新校验 approved source snapshot 与完整 sandbox runtime identity。persistent `sandbox.exec` 把同一 identity 写入 `SandboxRun.compatibility`，其 adapter operation 只能继承对应 run 的 identity，不得从 tag、workspace 默认值或临时兼容值重建
- approval 绑定完整 operation digest、artifact reads、SDK/toolchain/backend operation list、每种 operation 的 `max_calls`、expected outputs 和资源/配额估计；正式执行在每次 provider/tool/HPC 外部调用前原子消费 approved plan call budget，超过上界返回 `execution_plan_quota_exceeded` 且不得触达 adapter/runner；同 session 内 digest 完全一致可复用 approved approval，digest 漂移必须重新审批或结构化失败
- artifact `kind` 是 control-plane 闭集：`code|log|sequence|structure|report|research_dossier|result|cache|other`；HMM、CSV、JSON 等编码以及 model/alignment/table/graph 等科学语义只能进入 `format` 或 metadata，不能发明新的 kind。`directory` 仅是 `expected_outputs` 的既有 shape sentinel，不会写入 artifact kind。sandbox SDK 在 control call 前校验，Host artifact boundary 与 Core/Podman raw control socket 对旧 SDK/绕过调用重复校验；非法值统一以 non-retryable `artifact_kind_invalid` 在封存和外部工作前 fail closed。bio-tool runner declaration 若显式提供 kind/format，也必须与固定模板一致；显式非法 kind 不得按文件扩展名静默回退，valid-but-wrong pair 同样在 runner dispatch 前结构化拒绝。AOX 的 HMM 固定为 `result/hmm`，FASTA 固定为 `sequence/fasta`，CSV/JSON 固定为 `result/csv|json`；17 个 normalized deliverable 的 online copy/cache-hit、fault target 与 offline verifier 还以 `aox_fixed_deliverable_artifact_contract@1` 同时绑定 exact path/kind/format，任一缺失或漂移 fail closed
- sandbox `artifacts.materialize` 只能把授权 catalog artifact 安全搬入 workspace；每次读取、复用和复制前后都必须重算 sealed Blob 的 file/tree digest，并与 Artifact row 声明的 digest 一致；同一 artifact digest、target path 和 mode 幂等复用，路径或 Blob digest 冲突必须保留现场、进入 quarantine/GC 台账并结构化失败，不能覆盖同 digest Blob 或继续 materialize；`artifacts.register` 必须在登记前执行非空、FASTA/HMM/CSV 必需列等轻量校验。科学 empty result 不是通用空文件豁免：AOX 零记录 FASTA 只有在 exact-zero bytes、稳定 `empty_result_reason`、版本化 derivation contract 和 `validation_profile=fasta_zero_records@1` 同时成立时才可登记，未知 profile 或 sentinel payload 一律 fail closed。fixed 17 final bundle 不能由逐项 `register`、`register_many` 或 arbitrary source-snapshot implementation substitute 形成 acceptance；Host 先以 `read_registration_draft` 完整预校验，再由 `artifacts.finalize_bundle` 在一个 transaction 中提交 exact artifacts 与 source-bound `aox_final_deliverable_validation_receipt@1`。`artifacts.snapshot_code` 使用同 Blob root 下的临时树原子固化执行源码，复用已有 snapshot 时同样重新验哈希；cutover evidence 不把 source directory 当单文件读取，而是仅接受 `kind=code` 的 typed snapshot，规范化为 `openzyme_sealed_source_tree@1` envelope，逐文件绑定安全相对路径、size、content digest/base64 和整树 digest，并在构建与离线验证时双重重算；可解码 UTF-8 源码还必须在 base64 前后分别通过 public-safety 检查
- 同一 `sandbox_workspace_id` 同时只允许一个 active `sandbox.exec`；container process id 不是 canonical state，`SandboxRun`、file audit、command log artifact 和 changed-file summary 才是审计状态
- `sandbox.exec` 默认 `120s`，`s09.exec_policy.v2` 的有限全局上限为 `3600s`，其 CPU/memory/pids、无网络、单 active exec 与 container retirement 约束不变。AOX 中任何可能到达真实 `bio.hmmer_search` 的 command 必须使用 exact `3600s`，纯 inspection/source-repair 可更短；approval 前由 canonical `SandboxRun.resource_policy` 校验，不能只依赖 prompt。该资源事实不固定 agent 的脚本结构或合法修复策略
- AOX similarity 的当前有界纠正不提高通用 sandbox 资源：formal private-cgroup Podman 已实证可从根 `/sys/fs/cgroup/cpu.max` 得到 2-CPU quota，worker cap 取 pair count、硬上限 `16`、affinity/`cpu_count` 与所有可用 cgroup v2/v1 quota/period 向上取整值的最小值，present 但 unreadable/incomplete/malformed 的 limit fail closed。真实 516-sequence/132,870-pair 校准中 2 workers 为 `84.087s`，比 affinity-only 16 workers 的 `168.766s` 更快，故固定 2-CPU/3600s 不是当前 blocker。通用 Host、嵌套 ancestor cgroup、placement plan 与 authoritative resource receipt 的未覆盖面只记录在 [Host-authoritative scientific-calculation placement and sandbox resource class](v3/architecture-proposals/host-authoritative-scientific-calculation-placement-and-sandbox-resource-class.md)，本 Goal 不扩张 helper 为通用资源架构
- sandbox workspace 的 disk quota 是 Host 强制执行的硬边界：`sandbox.file.write` / `sandbox.file.patch` 在原子替换前按 prospective bytes 拒绝超额，`sandbox.exec` 结束后按完整 workspace 重算；子进程、control socket 或 SDK 产出导致超额时，run 必须终止为 `resource_exceeded`、workspace 必须进入 `quota_exceeded`，清理到限额内前不得再次执行
- sandbox/adapter/provider 的公开诊断只能保留稳定 error code、bounded summary、digest、size 和无读取 authority 的 opaque log ref。已知 Host workspace/control-socket root 在 schema 声明的 diagnostic/locator field 中映射为 `/workspace` 与 `/openzyme/control.sock`；随后对已测试的 high-risk corpus（常见 Unix/HPC roots、Windows drive、UNC、`file://`、private/special-use URL、storage/runner locator 与 credential forms）递归脱敏。producer sanitizer 自身也是有界控制面：credential-URI 只从真实 scheme token 左边界开始候选匹配；完整 `64 KiB` benign scalar 必须在 architecture qualification 注册的 identity-bound child deadline 内完成且不得靠截断、替代 sanitizer 或 deadline 放宽过关，长前缀后的 credential URI 仍必须被完整脱敏。该 producer sanitizer 不声称能从任意自由文本识别所有 private path，也不无类型改写用户输入、conversation 或 scientific/report 正文；AOX offline verifier 仍独立拒绝任何 surviving absolute Host path/private locator。进程 stdout/stderr 以 binary capture，public summary 才使用 replacement decode；完整 raw bytes 仅写 attempt-local Host-private command-log root，run directory/file 分别以 exclusive `0700`/no-follow `0600` 创建，公开 digest/size 按这些 raw bytes 计算。projection 只对历史 diagnostic 与 schema-declared locator field 再投影，不能通过旧 SQLite 绕过当前写边界
- AOX public evidence scanner 只把四个 exact logical manifest suffix `/provider_parsed/metadata.json`、`/provider_parsed/parsed_hits.csv`、`/provider_parsed/proteins.fasta`、`/provider_parsed/sequences.fasta` 视为非 Host locator，并在 sealed Python source 中窄识别 `Path("aox_hmm")/p.name` 这类真实 `/` path-join syntax；它不开放整个 provider directory，也不把任意右括号后的 slash 当例外。未知 suffix、traversal、任意 `prefix)/p.name`、`/home/...`、`/tmp/...` 和其他未识别 absolute path 继续 fail closed；既有 `/workspace`、`/openzyme/control.sock` 与 public `/v3/...` route 规则不变
- runner/HPC 不得直接使用 Host 本地 artifact path；输入必须通过 artifact catalog 授权并 staged 到远端工作目录
- runner 在 payload 执行前的 `remote_layout`、`input_parent`、`input_transfer` 或 Slurm `runner_control_transfer` 终态失败必须立即通过本地 `ArtifactStore` 写入 Host-trusted `runner_failure@1`；该 exact schema 闭集只含 `schema_id`、opaque `run_id`、phase、一基 input ordinal/内容 digest（layout 均为空，control transfer ordinal 为空且 digest 绑定 `job.sbatch` bytes）及 `returncode/timed_out/elapsed_seconds`。engine 继续向 agent 返回 `hpc_staging_failed`，只投影上述已校验字段；adapter → sandbox control socket → `PipelineSdkError` 必须同时保留顶层安全 `stage="hpc_staging"`、typed boolean `retryable`、sanitized hint 与 `details.runner_failure`，不得把 stage/retryability 只藏在 details 或 traceback 中。projector 存在但畸形/抛错时使用固定泛化 reason，绝不读取异常文本。SSH target、命令、stderr、credential、Host/远端 path 或 locator 均不得越界。`retryable=true` 只忠实呈现恢复可能性，不授权同 attempt 自动 replay、重开 approval、切换 backend 或采用既有 effect。该 manifest 不是成功 run/output 或 artifact authority，也不引入额外隐式重试、重连、连接复用或 timeout 数值放宽；既有 rsync→最多一次 scp fallback 保持有界，Slurm layout/control transfer 纠正性应用既有 `staging_timeout_seconds`
- payload 已进入 `remote_execution` 后，runner 必须保留 raw nonzero 的首要 transport/tool failure，不能因成功态 toolchain identity marker 缺失而覆盖；只有远端命令返回零且 marker 缺失或非法时才归类 `TOOLCHAIN_IDENTITY_MISSING`。`SSH_CONNECTION_TIMEOUT` 向 engine 投影为可重试的 `hpc_runner_timeout`，`SSH_CONNECTION_FAILED` 投影为可重试的 `hpc_runner_unavailable`；该 retryability 只是呈现给 agent/operator 的结构化事实，不触发隐藏 replay、自动重批 approval、backend fallback 或连接策略变更。任何 remote nonzero 或无效 success marker 都跳过 output fetch，不能产生科学 artifact；runner raw stdout/stderr 只保留在 Host-private artifact store，server、execution adapter、engine 和 V3 Host 公共投影仅允许 opaque run id、稳定 status/error/stage/exit 等闭集字段
- `packages/openzyme-execution` 只规范化 Host-supervised runner 调用结果，不直接构造 `MCPHpcServer`；`apps/openzyme-host-api` 作为 HTTP/SSE composition root 负责实例化 runner server 并注入 adapter
- 远端输出只有在 declared `expected_outputs` 中声明且 runner 实际返回可读内容后才会下载并登记为 artifact；missing output、失败 run、不可读 fetch source 均结构化失败，不生成占位文件或伪造科学 artifact。只有同时标记 `fixture_non_cutover` / `simulation_non_cutover` 且携带相应 fixture/simulation 证据的显式测试 outcome 才可生成 placeholder，并必须写入 `synthetic_source=true`、`cutover_eligible=false` 与非产品 scientific status
- 对 HPC-heavy 流程，Host 维护独立的 HPC placement workspace；`hpc_workspace_id` 按 `sandbox_workspace_id + normalized_label` 复用，executor 通过 `hpc.workspace`、`stage_artifact` 和 `fetch_outputs` 声明文件流，Host supervisor 负责真实 staging/fetch 和 artifact registration，不能把该远端工作区描述成 sandbox workspace 的 mirror，也不能把 remote path 暴露给 executor
- blank-world live attempt 由 Host composition 注入彼此独立的 SQLite、sandbox workspace、sealed blob/artifact 和 HPC workspace roots；execution pipeline、provider artifactization、HPC fetch 与 source snapshot 必须贯穿同一 attempt-scoped root identity，任何局部共享 `/tmp` fallback 都使该 attempt 不具备 cutover 资格。public proof 仅包含 root digest/空目录证明，不暴露 Host 或远端路径
- 现行 AOX attempt collector 的单文件 no-replace/seal 不等于 evidence archive 的 transaction，也没有统一证明 final `artifacts/` 实际文件集与 declared inventory exact equality。两阶段 private staging→验证→commit、artifact-root 全闭包、failure atomicity、crash recovery 和 schema migration 的完整方案单独记录在 [transactional attempt evidence collection and root closure](v3/architecture-proposals/transactional-attempt-evidence-collection-and-root-closure.md)，当前 Goal 不实施；在该迁移落地前不得用提案语义补强已封存 bundle 或 GO 结论
- blank-world campaign 的 fresh SQLite 不继承 sandbox image registry 状态。supervised Host child 必须在 foundation/listener/child-ready/session/model/provider 前，通过将用于 health/execution 的同一个 runner取得 exact six-field runtime identity；它与 authority-bound preflight 的 image/SDK digest 完全一致后，才在一个 transaction 内证明 image/session/workspace 三个 registry 全空、写入并重读唯一 immutable cutover-grade Core image row。Core workspace manifest protocol与Podman runtime protocol分别保持typed version。预存任意 default/non-default row、缺失、格式非法、digest/runner漂移或重读失败均在外部副作用前rollback并fail closed；source-bound bootstrap receipt同时进入child-ready、Host startup与bundle。该路径不pull/build/install/tag/fallback，普通Host继续返回canonical `sandbox_image_missing`
- **current-contract supersession**：下列仍以 `run-live`、automatic driver、observer/barrier、`chrome-once`、browser helper、diagnostic authority、public scientific mutation/finalizer、outer-plan attempt/lane id 或 AOX dispatch precondition 表述的条目只解释历史 sealed evidence，不是 current runnable operator contract。current config 为 `aox_blank_world_runtime_config@5`，不含 conductor/driver policy object；formal launch 只经 exact claim/preflight 与 policy-free supervision，scientific mutation只经 agent tools，transition finalization只在 Host内部进行，Codex只使用 public inspect/export/coordination API/CLI。不得从以下历史条目恢复已删除 surface。
- AOX/HMM `pin`、`preflight` 与 current launch 的共同最前置 operator boundary 必须显式接收 architecture qualification report，并在 settings、pin runner、attempt root、sandbox probe、provider/runner/Chrome/MICU 之前用当前 checkout 的 pure verifier 重算。只有当前 clean HEAD 的 full selection、current invariant registry `@2`、owner-constraint registry、strategy/world-fidelity transformation results、完整 source/process receipt chain、全部 invariant satisfied 且零 open P0 的 `openzyme_v3_architecture_qualification_report@3` 可生成 `aox_architecture_qualification_receipt@3`。历史 report/receipt `@1/@2`和`aox_blank_world_attempt_bundle@2`只由冻结reader读取，不得进入current pin/preflight/launch/reducer或自动升级。missing、diagnostic/subset、dirty/stale/tampered/unknown-profile/open-P0、typed run failure或receipt drift均fail closed，不存在force/debug/env/legacy/pass-boolean bypass。资格报告是checkout外operator admission evidence，不是control-plane或scientific truth；scripted happy path本身不能满足admission，通过也不创建attempt、不启动numbered live campaign。
- AOX/HMM `pin` 是 `run-live` 的 canonical supported operator bootstrap：它在 clean checkout 上使用 production compiler 和受信 Host 的 forced-SSH runner 执行四个 deterministic non-scientific MAFFT/hmmbuild/hmmalign/CD-HIT payload，只从 runner 签发的 same-shell runtime identity 得到 toolchain image digests。writer 将 exact-seven identity 与 exact-nine prerequisites 以 `0600` canonical JSON 发布在 checkout 外同一 existing real transaction directory，三个 reserved targets 初始必须不存在；Host 在两个 payload 落盘后最后发布闭集 `.aox-cutover-pin-commit.json`，用 basename 和 canonical payload digest 形成单一 consumer-visible commit point。marker 前 crash 留下的 orphan payload 不可消费；`run-live` 必须在读取 settings、构造 launch/campaign 或创建 root 前拒绝 marker 缺失、symlink、跨目录、开放/畸形字段或 digest drift。该无签名 marker 只证明 committed pair 完整性/一致性，不证明 producer provenance、目录整体 freshness 或消费时 file mode；真实运行仍依赖 trusted operator、actual launch recomputation 与每个 operation 的 runner-issued identity fail-closed
- AOX/HMM `run-live` 在构造 runner/campaign 或 attempt root 前必须从 clean checkout、digest-pinned workflow registry、`aox_motif_rule_score@1`、实际 Podman runtime preflight 与 Pipeline SDK tree 重算 canonical 七字段 identity；已提交的 pin declaration 只用于精确比较，不是真值来源。identity 解析还必须以 selected immutable image、复制后统一为目录 `0755`/文件 `0644` 且重算 digest 相等的 exact SDK tree，在 `--pull=never`、无网络、只读、限额容器内执行 `aox_sandbox_scientific_backend_probe@1`：真实导入并运行 `biopython_trace_guarded_numpy_gotoh@1` 的 Biopython `1.87`、NumPy `2.4.4`、Gotoh/IEEE-754/numeric preflight；缺包、版本/算法/数值/schema drift 必须在 pin runner attestation、attempt root、MICU/provider/runner effect 前失败。该有界 capability gate 不扩张 exact-seven/exact-nine，也不冒充 deferred reproducible dependency manifest、SBOM 或供应链 attestation。`config_digest` 必须来自 safe `aox_blank_world_runtime_config@3` preimage，绑定 trusted local Host/single-process SQLite、HPC runner config digest、runner-owned manifest bytes digest及 exact AOX `tool_id` 到 adapter/template/runner-contract digest 的闭集 expectation map、effective MICU/research/tracing/test opt-in、driver/Chrome bounds、controlled-operation owner policy、durable route allowlist、command drain、generic mutation closure、bounded shadow observation、完整 `aox_blank_world_selected_chain@2` identity 与既有累计 500M ledger identity，但不投影 credential、NCBI email 或私有路径。pin 在 forced-SSH attestation 前、run-live 在 campaign/attempt root 前必须证明全部 AOX provider/HPC route 使用 `durable_async_v1`、drain 为 `command_v1` 且 closure 为 `generic_v1`；旧 config `@1/@2` 和 selected-chain `@1` 只允许 frozen evidence 离线复核，不得启动新的 live campaign。100M→500M 只能由 operator 显式执行 exact fixed-policy migration，保留全部历史 usage，caller-selected lower limit 不被抬高，普通 summary/reserve/run-live 不自动迁移。MICU/OpenAI-compatible blank-world live 必须显式声明 `context_window_tokens` 且不大于 `200000`，不得按模型名继承第三方 endpoint 未证实的百万级 context。每个 attempt root 前重新校验 checkout/config drift，exact-nine prerequisite 顶层 schema 不因此扩张
- AOX live launcher 先用已提交 declaration pair 与当前 architecture qualification 验证对应 run-class plan 和 deterministic consumption target，再以 no-replace 私有 receipt 消费 authority；只有随后才构造 live launch snapshot、process supervisor 或 root。正式 `authorize` / `run-live` 固定为 exact-three `formal_acceptance`，独立 `authorize-diagnostic` / `run-diagnostic-live` 固定为单 positive-shaped `diagnostic`。两者共用一次 attempt 的 root、ledger、supervision、runner 与 scientific-control settlement 内核，但 collector schema 完全分离：formal 独占 `aox_blank_world_attempt_bundle@3` 与 GO reducer；diagnostic 只写 `aox_blank_world_diagnostic_decision@1`，其 root marker/proof、authority/consumption 和 decision 全部 `acceptance_eligible=false`。正式 root 若自身或任一 ancestor 带 diagnostic marker 会在创建前失败；diagnostic slot 删除 run-class、换用 formal identity，或 formal slot进入 diagnostic core 同样在 root 前失败
- blank-world prerequisites 是 exact-nine 闭集：`git_commit`、`config_digest`、`workflow_ref`、`image_digest`、`sdk_digest`、`toolchain_image_digests`、`credential_slots`、`ncbi_identity`、`prompt_accessions`。前五项必须与 launch identity 相等；toolchain map 只含 versioned MAFFT 7.525、hmmbuild/hmmalign 3.4 与 CD-HIT 4.8.1 SIF digest，两个 HMMER operation 必须绑定相同 bytes；credential 只投影 availability boolean，prompt accessions 只允许 formal exact-14 与 fixed probe
- cutover-grade HPC tool receipt 必须由 runner 签发 `mcp_hpc_toolchain_runtime_identity@1`：runner-owned manifest 决定 private SIF locator，同一 SSH login shell 先 scrub 所有继承的 `APPTAINER_*` / `SINGULARITY_*` runtime-control 变量并二次确认不存在，任一变量无法移除则在 payload 前 fail closed；随后直接执行该 resolved pathname，并在 payload 前后哈希同一 pathname。只有两次 digest 相等且 payload 成功才以现有 `attestation_scope=same_ssh_login_shell_pre_exec` 闭集 schema 投影单一 `image_digest`。Host 不接收 private pathname 或两个中间 digest，collector/verifier 将该 equal digest 与 exact prerequisite 比对。这只证明“受控运行时环境中同一路径在 payload 前后 bytes 未变且被直接执行”，不证明 immutable inode/content-addressed snapshot；更强保证单独记录在 [immutable HPC SIF execution snapshot](v3/architecture-proposals/immutable-hpc-sif-execution-snapshot.md)，本 Goal 不实施。当前 Slurm 没有 job-internal same-execution attestation，不能用于 AOX cutover identity；submit/preflight metadata 不得冒充执行证明。跨 runner/route/template/DTO/verifier 的单一合同 registry 属于 [deferred architecture proposal](v3/architecture-proposals/single-source-hpc-toolchain-contract-registry.md)，当前 Goal 不实施
- blank-world live 的 probe、两次 positive 与 fault attempt 仍通过同一 canonical loopback HTTP Host 产品路径驱动，但 numbered `run-live` 为每个 complete attempt 启动 fresh local POSIX `spawn` child；child 的 dedicated session/process group 独占 loopback Host、SQLite、artifact/blob/sandbox roots 与 child result。current supervisor 使用 `aox_live_attempt_supervision@3` 的 `child_started → settling_local_state → local_state_settled → child_terminal` hash chain：Core-owned bounded mutation-authority snapshot 记录全部 scope/writer 安全结构，零 `registered|retiring` writer 才可 local-settle，但合法 writer-free `OPEN` post-closure scope 不是进程活动。parent 只在 zero exit、empty exact process group 和 root gate retirement 后以 read-only SQLite 重算同一 snapshot digest，再核对 checkpoint/integrity、root sync 与 result digest；scope/result drift 均 fail closed。`aox_live_attempt_supervision_receipt@3` 只证明本地 writer 与进程退休，产品 closure 还必须独立由 `ScientificAttemptScopeRolloverProjector` 证明 exact `post_closure_scope_open`，两者不得互相替代。历史 supervision/receipt `@1/@2` 仅供显式 offline verifier 原样读取，current bundle 不得降投影为 `@1`。timeout、protocol gap、nonzero exit、result drift 或 descendant leak 触发 bounded `SIGTERM -> SIGKILL -> waitpid -> group-empty`，只在 campaign failure root 写 `cutover_eligible=false`、`external_outcome=unknown` 且不声明 ledger-after/SQLite/artifact closure 的 fatal evidence，随后停止 campaign；不得把 kill 解释为 task/operation terminal 或 remote cancellation。`run-live` 的 positive/fault runner 必须是同一个 process-isolated wrapper，并在 ledger-after/bundle 前校验 supervision receipt；普通 `AoxCutoverCampaign` 构造默认要求该 receipt，direct `LiveAoxAttemptRunner` 只允许通过显式 `AoxCutoverCampaign.for_non_live_test(...)` 用于 focused non-live tests。
  child 内部的 cutover effective config 固定 `max_signals_per_drain=1`：driver 为每轮 POST 一个带独立 idempotency key 的 durable command，校验 `202 + command_id + status_url`，随后轮询 exact session-scoped GET。command worker 每次最多 claim 一个 signal；command 在 bounded batch完成、失败、locked 或 park work 后即 terminal，approval/provider/HPC wall time不延长 command lifetime。command terminal 后 generic bounded runtime barrier 只读 active suspension、runtime work 与 exact observer 之外的 mutation writer；formal session 的完整观察与 terminal-command writer settlement 必须共用 bounded observer context，禁止后者直接读取 barrier。它不拿 lease、不 dispatch、不写 task/campaign状态，也不能充当科学成功或task完成判据。compact pending-approval endpoint与 `workspace.pending_approvals` 读取同一 canonical rows；普通 auto gate 热循环和失败 cleanup禁止轮询composite workspace，只有Chrome handoff与最终证据收口读取workspace。probe/非Chrome gate自动批准，positive 1首个formal approval只由浏览器批准；public coordination失败后只reject unresolved operation，绝不用approve做清理或继续科学执行。child Host的HTTP-handler tracker只辅助thread retirement，不是mutation authority；eligible closure仍使用generic mutation scope、稳定snapshot、immutable receipt与seal。process supervisor只证明本地writer退出，不证明远端effect取消；different UID/cgroup、escaped descendant与remote handle/MICU crash reconciliation留在 [live-attempt supervision hardening](v3/architecture-proposals/live-attempt-supervision-hardening.md)。产品command/continuation合同见 [Runtime / HPC可靠性边界](v3/07-runtime-hpc-reliability.md)
- drain coordinator 必须区分“请求已结束”和“最后一次 compact approval read 已发生在该 response 之后”：成功 worker terminal 后至少再执行一次 public pending-approval GET，才可断言没有新 durable `waiting_approval`，随后读取一次 bounded workspace 作为最终 semantic snapshot；若 worker 自身失败则保留 `runtime_drain_command_failed`，只有 public coordination/cleanup 失败才使用 coordination failure taxonomy
- `workspace.pending_approvals` 是 UI composite snapshot，`GET /v3/sessions/{session_id}/pending-approvals` 是同源紧凑 control snapshot。SSE 仍负责低延迟刷新，但 durable execution/continuation 可以在一个 runtime command 已 terminal 后产生后续 approval/result event，所以 event replay 不能单独证明当前无 pending approval；Web UI 还要对当前 selected session 做低频只读 workspace reconciliation。每个 active generation 请求必须 single-flight，session 切换、workspace mutation 或 SSE reducer 更新都会 abort/失效旧 generation，旧请求的 `finally` 也不能清除新 generation。挂起的旧 session GET 不得饿死新 session reconciliation，任何轮询不得写产品状态、维护第二真值或覆盖较新的 mutation/event snapshot
- AOX HMM-capable path 仍对 provider poll、sandbox process 与 formal attempt 使用分层有限 deadline；`pin`/`run-live` 在 attempt root、approval 与 provider dispatch 前校验实际 engine/core policy。durable execution/continuation 使 HTTP command 与 session lease 不再拥有这些 external deadlines，但没有取消 provider/HPC 或 process 自身的 bound。任一低于 route policy 的 timeout 仍 fail closed；完整 authority、recovery 与 quiescence合同见 `docs/v3/07-runtime-hpc-reliability.md`
- `chrome-once` 只把 positive 1 首个 formal approval 暴露给 attempt child 的 loopback Web UI；parent supervisor 与 driver 都不代替浏览器调用 approval resolve。driver 必须在触发可能产生 handoff 的 drain 前记录 durable event cursor，从该 cursor 重建即时 resolution/continuation，并立即验证 `pre_cursor < resolution_cursor < continuation_cursor`；浏览器 resolution consumer 只将带闭合 `decision=approved|rejected` 的 canonical `approval.resolved` command event 解释为 operator decision，同名但只有 ApprovalRequest `status`、没有 `decision` 的 activity projection echo 必须忽略，不能冒充批准或拒绝。真正的 canonical `decision=rejected` 仍立即 fail closed；有界 deadline 内没有 canonical closed decision 也必须 fail closed。浏览器 approval deadline 从 handoff 独立计时，同时不得超过 attempt 总 deadline；outer process-supervision deadline由两个session bound及browser approval/hold/submission bound确定性推导，不由agent临时延长。`aox_browser_approval_receipt@2` 必须绑定产生当前 pending projection 的 exact pre-workspace receipt、post workspace semantic preimage、public response receipt 与完整 resolution/continuation durable-event record；public API receipt 是含 `response_semantic_digest` 的 exact 七字段闭集。handoff 必须动态身份完整：发出 sealed logical page URL、child Host process、UI dist digest、versioned receipt schema id、not-before、exact target 与 expected page state。terminal 后 child Host 强制保持 completion observation window；trusted operator 必须使 final target 在 hold 内不存在，并把其 Chrome console、page target、三类 MCP request/response 与 PNG 投影封装为 `aox_browser_observation_capture@1`。稳定的 `openzyme-aox-cutover browser-receipt` helper 校验闭集，只在 not-before 后创建 mode-`0600` sibling temp，计算 exact 23-field receipt 的 aggregate digest/PNG dimensions，经 file fsync、atomic no-replace install 与 parent-directory fsync 发布；它不得伪造 Host acceptance timing，也不证明投影与 MCP 原始 response 的对应关系。当前 Host 只能证明每次 bounded poll 时 target 缺失，以及最终文件是 post-hold、non-symlink、mtime 合格且经两次 stat/read 稳定的 regular file；它不证明轮询间连续缺失、operator atomic/fsync provenance 或 browser-origin-complete transcript。窗口结束后的独立正有限 submission timeout 写入 effective config，不能用延长提交时间缩短 Host hold。`aox_browser_observation_receipt@2` 绑定 challenge、Host/UI/page、clean console、terminal page state、DevTools transcript、完整可解码 PNG 与 Host acceptance timing。最后一次只读 workspace 和 `after_cursor=0,replay=true` 全事件 preimage 作为 bundle-level artifact 封存而不回写产品真状态；fault closure 的 task/report/draft/conversation/event/consumer 集合必须与其 exact equality。全局 canonical command 与 derived activity projection 的 event taxonomy 分型属于 [deferred architecture proposal](v3/architecture-proposals/canonical-approval-command-vs-activity-projection-events.md)，本 Goal 不实施；`auto` campaign 不能满足 Chrome GO criterion
- AOX/HMM 正式科学链从一份 exact-14 NCBI protein aggregate 分离两类身份：13 条 fixed HMM reference 经 `openzyme_pipeline.aox_reference.select_hmm_reference_set` / `aox_hmm_reference_set_selection@1` 产生 `AOX_ref21.fasta` 并且只有该文件进入 MAFFT/hmmbuild；`AAB57849.1` 经 `select_scoring_reference` / `aox_reference_selection@1` 单独产生坐标 reference。EBI HMMER `refprot` raw/parsed hits 必须先经 `openzyme_pipeline.aox_hmmer.parse_and_filter_csv` / `hmmer_score_filtered_accessions@1` 得到 score `>200` 的 exact accession artifact，才能触发 UniProt；`uniprot_primary_sequence_identity@2` 必须将 requested set 精确分为 active sequence 与 typed inactive `DELETED|MERGED`，sequence/length 真值只由 active UniProt record 提供。`openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions` / `aox_sequence_length_join@2` 先确定性排除两类 inactive，绝不跟随 MERGED target，再对 active sequence 应用 inclusive `650..700`，并以 active/inactive-reason/output/length-rejected counts 及 sorted identity mappings 使 partition 可离线重算。`openzyme_pipeline.aox_reference.assemble_scoring_input` / `aox_scoring_input_assembly@1` 再把 AAB 放在首位、追加 post-UniProt targets，HMMalign 消费该 scoring input 与真实 HMM；motif 与 graph 必须分别调用 `openzyme_pipeline.aox_motif.score_aligned_fasta` 和 `openzyme_pipeline.aox_similarity.build_similarity_graph`。agent 必须通过 provider transcript 的声明后缀和 HPC `fetch_refs[].declared_output_path` 绑定真实 bytes，且 MAFFT/hmmbuild/CD-HIT/HMMalign 只声明 runner-owned canonical output path；不得近似重写这些计算、生成 sentinel empty、把 AAB 混入 model training，或用 HMMER/probe/reference/MERGED replacement sequence 代替 UniProt active target。当前 pinned SDK 的 primary FASTA/CSV/JSON accessors 与 `metadata_json()` 返回 Python `str`，`metadata()` 返回结构化 `dict[str, object]`；受控 workflow facts 必须披露这些类型，bytes-only writer 前只做一次 UTF-8 encode，type/annotation drift 不得触发隐式 coercion。科学计算 callable、canonical serializer、agent-facing facts 与 receipt 目前仍分散；统一 versioned capability projection 的大改动仅记录在 [versioned scientific calculation capability projection](v3/architecture-proposals/versioned-scientific-calculation-capability-projection.md)，本 Goal 不实施
- AOX graph 的当前 `aox_global_sequence_identity@1` implementation/calculation 分别固定为 `sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5` / `sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`。`biopython_trace_guarded_numpy_gotoh@1` exact pin Biopython `1.87` 与 cutover NumPy `2.4.4`，只允许 proven `<2^53` integral binary64 packed score；首个 optimal trace 出现相邻 opposite gap-state switch 时调用 exact `numpy_three_state_gap_switch_correction@1`，所有 import/version/algorithm/numeric/trace/correction drift 均无 fallback fail closed。reference recurrence 的 state order 只记录 tie provenance；当前 graph 不承诺或发布 alignment coordinates/path，未来若发布必须启用新 calculation id 与显式 trace contract。reference validation NumPy `2.4.6` 与 cutover `2.4.4` 是明确不同的 exact 环境；最终 comparison receipt `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e` 由两次独立 cutover-`2.4.4`、2-CPU/2-worker full-set run 证明 raw repeatability，并在只规范化 pin-induced fields/manifest closure 后逐字节等于 old pure-v3 输出。它不声称 direct full-set patch A/B，且与历史 pure-v3、临时 2-CPU receipt 一样始终 non-cutover；只完成 diagnostic/reviewer 与 workflow knowledge pin gate，不是 live GO evidence
- 到达 UniProt 的 cutover-eligible positive 必须通过 `scientific_checks.sequence_join.uniprot_raw_response_artifact_id` 把 raw response artifact 与同一个 formal `uniprot_fetch` operation 的 provenance/output 及 UniProt provider receipt 闭合。无网络 verifier 从 closed raw envelope/response rows 重放 page/body/header release 与 ordered digest chain，用 engine sanitizer 建立 raw-result↔metadata requested/primary 双射；active sequence 的规范化 bytes、raw/metadata length/digest 必须继续闭合到 FASTA，inactive 禁止 sequence/entryAudit 并重建 exact DELETED reason 或 MERGED non-follow annotation。无关 future raw result fields 可以存在，但完整 sanitized non-sequence object 必须等于 `provider_metadata`，`record_digest` 则绑定完整 sanitized result；本轮 diagnostic 的 exact-five inactive shape 不是未来字段 allowlist
- AOX/HMM healthy empty 不要求无意义的全工具调用；offline verifier 从封存 artifact 推导 `hmmer_upstream_empty | length_filter_empty | motif_filter_empty | nonempty` 分支，分别省略 `UniProt+HMMalign+CD-HIT`、`HMMalign+CD-HIT`、`CD-HIT` 或无省略。upstream empty 的 `provider_upstream_empty_receipt@1` 只证明 trigger/reason 和 `provider_io_performed=false`，不得伪造 operation/request/response digest；conditional-empty bytes 必须由 `aox_upstream_empty_materialization@1`、`aox_reference_only_scoring_alignment@1` 或 `aox_empty_membership@1` 消费 exact installed zero-source receipt 后生成，arbitrary source-snapshot implementation substitute 永久无效。独立 known-positive probe 覆盖正式分支未到达的 capability，但其 bytes、operation 和结论永不进入正式图与 report claim
- Provider cache 只能作为 Host-private optimization；cache key/digest 可进 provenance，但 cache hit 不能替代当前真实 provider/live prerequisite 证据
- AOX/HMM local Live cutover 只能由同一 commit/config/workflow/scoring/image/SDK identity 下两次独立 blank-world 正向 attempt 和一次受控 fail-closed attempt 的 sealed bundle 聚合得出；每个正向 attempt 必须有 published report 并通过无网络 offline verifier。故障不是任意 provider failure：必须以 `derived_required_artifact_blob_byte_flip@2` 到达 real NCBI exact-14 `proteins.fasta` → `aox_hmm_reference_set_selection@1` → derived `AOX_ref21.fasta` → pending MAFFT seam，产生 exact `artifact_blob_digest_mismatch`；`aox_fault_negative_state_closure@1` 必须证明执行 task fail/block/cancel、reporter 未完成、无 ready/published report/draft、无 successful alternate consumer 或 downstream fixed deliverable、conversation/durable event/final failure 一致，且 fault MICU 增量完全归因于本 campaign。当前在三份真实 attempt digest 封存前一律是 **NO-GO**；S15 历史 pass、seeded smoke 和 fixture 只是 non-cutover 证据，这些 attempt bundle 不是新的顶层 control-plane 真状态

### 8.3 Report Draft 与 Report

Reporter teammate 默认使用：

- `report_draft.get`
- `report_draft.update`
- `report.publish`

`report_draft` 是可恢复、可修订、可投影的中间交付物；`report.publish` 才生成 final report record。当前 live/cutover 证明不能只看 tool 注册或 seeded smoke，必须确认 workspace 中出现 published draft / ready report，且 reporter task 的创建、委托和 drain 路径实际发生。

---

## 9. 验证与 Gate

### 9.1 Repository test-gate authority

`scripts/check-mainline.sh` 现已原子切换为唯一 optimized non-live merge authority：
默认使用固定四 worker 的资源审计分区，`--forced-serial` 在同一
plan/owner/coverage/frontend/qualification 合同上固定为一 worker。旧顺序实现冻结在
`scripts/check-mainline-legacy.sh`，直接调用永远只是 rollback comparison。底层
`scripts/test_gate/` 仍是 repository/operator plane，不进入 V3 composition，也不写
session、task、lane、approval、artifact、report 或 scientific attempt 真状态。

| Profile / command | Merge authority | Architecture admission | AOX/live/scientific authority |
| --- | --- | --- | --- |
| `focused_diagnostic` | no | no | no |
| `affected_scope_diagnostic` | no | no | no |
| immutable `replay-corpus` | no | no | no |
| shadow/candidate receipt | no | no | no |
| current optimized `scripts/check-mainline.sh` | yes | no | no |
| qualification `premerge_subset` / `diagnostic` | no | no | no |
| clean full qualification `admission` | no | yes | no; AOX launch仍需独立 authority |

Versioned mainline plan 固定现有 Ruff、single-index compatibility audit、
`premerge_subset`、general non-live pytest、Web UI test/build 的顺序和 fail-fast
dependency。它收集 `G/Qh/Qs` 并为每个 distinct node 指定唯一 owner；只有同一
invocation 的已验证 qualification sidecar 才允许 general 执行
`G - (Qh ∪ Qs)`，不按目录或 broad marker 猜测去重。general residual 再由 exact resource
manifest 分成固定 `--dist=loadfile` parallel partition 与 conservative serial fallback；
未分类默认串行、worker 固定为 `1..4`、从不使用 `auto`。authoritative receipt 绑定 source、
toolchain、environment、collection、owner、resource、stage、qualification 和 frontend，
并由 wrapper 随运行调用的独立纯 verifier 从 raw evidence 重算。receipt 的
`authoritative=true` 只表示当前 non-live merge contract；其
`admission_eligible=false/live_eligible=false` 不可升级。

Focused/affected/replay 即使覆盖全仓也永久
`authoritative=false/admission_eligible=false/live_eligible=false`。affected unknown
扩大到 complete-safe，不静默缩小；credential、provider、SSH、Chrome、MICU 或 live opt-in
不能激活 diagnostic effect。详细 operator contract、命令、rollback 与 timing evidence
见 `docs/v3/test-gate.md`。

最终五对同源 cold/warm 对照已闭合：legacy median 为 424.62 / 424.14 s，fixed-four
optimized 为 255.04 / 253.77 s，缩短 39.94% / 40.17%；orchestration overhead median
2.157%、maximum 2.202%。每个历史 optimized benchmark sample 执行
2,808/2,808 distinct nodes，
84 harness + 13 scenario ownership、Web UI 两项结果与纯 receipt verification 全部通过。
二十 case corpus 的 legacy/optimized proof-node projection 也零 mismatch，
authority-mode implementation replay 20/20 green；用户已于 2026-07-29 明确同意该
immutable corpus 作为二十个 clean revisions 的等价 cutover 证据。最新切换后 shadow
collection 为 `G=2,817`、`Qh∪Qs=97`、residual `2,720`，其中 1,292 个 node 进入已审计
parallel partition，1,428 个保持 conservative serial；旧 benchmark timing 不被冒充为
该较新 source 的 timing 样本。切换后的 fixed-four / forced-serial authoritative
receipt 分别记录 `256.877 s / 393.332 s`，2,817 个 exact node 的归一化
owner/outcome、qualification、Web UI 与 stage projection 零差异；原始路径和摘要见
`openspec/changes/optimize-authoritative-mainline-testing/authority-cutover-evidence.md`。
最终 19 条 requirement、71 个 scenario 与 88 项 task 的逐条核验见
`openspec/changes/optimize-authoritative-mainline-testing/completion-audit.md`；该核验不
自动归档 change，也不扩张 architecture admission、AOX 或 live authority。

常用非 live 验证：

- `./scripts/check-mainline.sh`
- `./scripts/check-mainline.sh --forced-serial`：同一完整权威合同的一 worker 对照；不是缩小 gate
- `./scripts/check-mainline-legacy.sh`：仅作顺序 rollback comparison；直接调用永不代表当前 authority
- `./scripts/check-v3-architecture-qualification.sh premerge_subset <checkout外新目录>`：主线 deterministic P0-critical 子集；即使全绿也永不具备 admission 资格
- `./scripts/check-v3-architecture-qualification.sh diagnostic <checkout外新目录>`：允许绑定 dirty source 的完整 GAP/P0 诊断；永不具备 admission 资格
- `./scripts/check-v3-architecture-qualification.sh admission <checkout外新目录>`：只接受 canonical clean HEAD、full selection、全部 invariant satisfied 与零 open P0
- `uv run pytest`
- `uv run pytest -m "not integration"`
- `uv run pytest packages/openzyme-core/tests/test_agent_scheduler.py packages/openzyme-core/tests/test_protocols.py`
- `uv run pytest apps/openzyme-host-api/tests/test_api.py -k v3`
- `uv run python -m openzyme_host_api.evals --v3`

主要 opt-in markers：

- `architecture_qualification_scenario`（closed deterministic scenario，不调用真实外部系统）
- `integration`
- `live_llm`
- `live_tavily`
- `live_hpc`
- `live_e2e`
- `seeded_live_smoke`
- `podman`
- `quality_eval`
- `slow`

Live gate 解释：

- executable architecture qualification 使用真实 `HostApiDependencies + create_app()` composition、file-backed SQLite、当前 workers/gateway/projections 与 controlled adapters，验证注册的不变量；report/receipt 只属于 repository/operator admission，不写 session/task/campaign 产品状态，也不验证 scientific quality 或真实 external availability
- 首版 profile 仅为 trusted-Host `local_single_process_file_sqlite@1`；不得外推 shared writer、multi-process、multi-Host、distributed 或 signed/adversarial attestation 保证
- AOX r48、r49 与 r50 均为永久 NO-GO；r50 的六项真实 probe operation 完成但旧 durable HPC materializer 漏投影 runner-attested toolchain identity，formal 路径完成 PubMed/NCBI/MAFFT/hmmbuild 与 Chrome canonical approval后，EBI HMMER job `563241d6-b460-4c74-bc92-70a34ab7c18a` 返回 `RETRY` 又被旧 adapter 错判为 non-retryable invalid request。后继 numbered campaign 只有在 durable identity 与 HMMER v3 两处 correction 提交后的 clean full admission、fresh pin 与 fresh roots 全部完成后才可启动，且仍需全部 launch/live/scientific/evidence gate，不能由 mainline、focused pytest、workflow eval、seeded smoke 或历史 run 替代
- AOX r51 与 r52 同样是永久 NO-GO。r52 在 commit `5ccb0d3ba6055cd3d50b0e42437c350ee442a1f0` 精确消费 plan `sha256:c2755edc4a8f08a161618a7291ff8dad40c340c390c527c24c8f956366492bbb` 后只到达 positive 1：六项 probe operation 均 terminal-known，但旧 collector 未把 durable HPC `run_id` 规范化为 evidence `backend_run_id`；formal master 的前三项 `task.create` 成功后，旧三-call截断又让未 dispatch 的第 4 项缺少 ToolMessage，下一次 provider call 因 transcript 不闭合失败。没有 Chrome handoff、eligible attempt bundle、positive 2 或 fault；decision `sha256:7284ce153ed150688887ff1315f52ac236e1a5ef18cf7c519085380013befe8b` 只能封存该事实。当前 collector 对 completed operation 严格使用 `hpc -> run_id` / `provider_http -> provider_request_id` 后统一投影，且 master/teammate 对 overflow call 生成 no-effect rejection 和匹配 ToolMessage。r52 state/effects 不得 replay/adopt；后继必须 fresh correction commit/full admission/pin/authority/roots 并重新获得 plan 精确授权
- AOX r53 同样是永久 NO-GO。它在 commit `83475a01fb6be91ca8ba5dc39c4c0b09774504e7` 消费 plan `sha256:a0bccbb4b71b2fb60a0a7131eae692d7400831ee7b516ba8143089f0d71aaabf` 后，positive 1 的独立六项 probe 已完成并密封；formal session 尚未产生 controlled operation、approval 或 Chrome handoff，就因旧 selected-chain driver 没有在 open pre-attempt scope 上登记 runtime barrier 所要求的 exact AOX observer writer，以 `mutation_driver_writer_identity_invalid` fail closed。parent fatal 证明进程组退休，但不声明 SQLite/quiescence/artifact closure；positive 2 与 fault 未启动，decision `sha256:d506914841245e9853ef28f7023a942891c6fc2f99244cbe496c899776e3e469` 只能封存 NO-GO。commit `6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` 只修复了完整 session observation；后续非-live 真实 SQLite 审计发现 terminal-command writer settlement 仍直接读取同一 barrier，并会重现相同 identity failure，既有测试桩掩盖了该调用面。当前纠正让两个 formal 消费面共用 bounded observer context，并以真实 SQLite 覆盖其他 root/child writer 可见、observer 退休及 scope 密封；任何绑定 `6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` 的未消费后继计划均已过时且不可跨本次纠正使用。r53 authority/state/effects 不得 replay/adopt，后继仍需 fresh correction commit/full admission/pin/authority/roots 与新计划精确授权
- AOX r56 是永久 NO-GO。它在 commit `92712310df96925cabe6b88a949a33b00470cf7d` 消费 plan `sha256:a3d6ed88cca88962281eed38e29f14155701ee7be0ddb2810cc67f47b5882627` 后，positive 1 已完成独立 probe、Chrome canonical approval、六项 formal controlled operation、17 deliverables、selection seal 与 scientific-attempt closure；reporter 仍为 todo 且没有 eligible report/`@3` bundle。non-transactional finalizer 先提交 attempt scope sealed，约 144 ms 后才提交 post-attempt scope open，并发 barrier 在零 open scope 窗口以 `mutation_driver_writer_identity_invalid` 终止。fatal `sha256:4e0f23b05f8fc5dbe84b35d0781e5c08926eacd4224aa00ab27e5052917463f9` 与 decision `sha256:826bbaf5bbcd07dccff481c363d0d6bb9b4be7aae1f00a33a22ba2e4b346f87f` 只封存失败；MICU lower bound 为 `86,881,198 / 500,000,000`。r56 全部 authority/root/effect/bytes 不得复用。下一步先实现 atomic rollover 与 diagnostic/formal 双类别并完成新 commit/full admission；不得直接启动 r57
- AOX r57 是永久 diagnostic NO-GO。它在 clean commit `059b69f2c49f136a42554caa06bc029610d77a7e` 消费独立 plan `sha256:f084d934feceb31322d1d1c6789018c897315cbf27b4afb825c0398f541590b8` 后，diagnostic/formal schema 隔离正确生效，probe exact six 与 formal exact seven controlled operations 全部 terminal completed；executor 随后把 representative-only `AOX_candidates_cdhit85.fasta` 与 full membership 绑定，pinned similarity 正确以 `candidate_membership_set_mismatch` fail closed。master 又创建第四个 suffixed report task，在 canonical execution/report 未业务终结且零 report 时请求 attempt close 并耗尽 16 steps。forward correction 只明确 full pre-CD-HIT `AOX_candidates.fasta` graph identity，并通过 formal-session-only `aox_cutover_formal_tool_precondition@1` 在 handler 前 no-effect 拒绝 noncanonical task 与 premature close；不改科学计算/阈值，不约束 probe/普通 session 策略。fatal `sha256:500f7e6b183906e7d849eeaed00af3e67a2c3512d4cebdd34e7a31a560acabae`、decision `sha256:6cf0216335fdad7d08e7a11ac72c7f7f868e0c523819979514f1aa4521c16614` 与 MICU lower bound `94,243,539 / 500,000,000` 只封存失败；r57 全部 authority/root/effect/bytes/pending state 不得复用，8.3a 仍未完成，任何后继 live 仍需 fresh commit/full admission/pin/plan 与精确授权
- AOX r58 是永久 diagnostic NO-GO。它在 clean commit `d00ada97f8eb13af35f9c83247cd51e14138f428` 消费 plan `sha256:691cf17bd8548fa3bfd4e338cb61ce608bb97c4cde17f0e66483b84ff65397e3` 后，probe/formal exact chain、516 candidates、78 representatives、13,778 edges、17 outputs、sealed selection、published report 与 exact-three owner-authored completed task exits均已形成；master 最后却发出 assistant-only final response，active attempt 没有 closure request，120 drains 后以 `formal_runtime_drain_exhausted` 终止。decision `sha256:8c877189130838b29030200d9c592e8e096cd028cd60a5c5bc38dd424c718a57` 与 MICU `96,363,097 / 500,000,000` 只封存失败，formal campaign 未启动。forward `aox_cutover_formal_tool_precondition@2` 在 close-ready state 拒绝且不持久化 assistant-only response，要求 master 在同一 provider response 中提供完整终答和 explicit close；empty companion 在 effect 前失败，successful close 才持久化 exact answer 一次、结算后续 calls 并退休 turn。它不自动 close、推断 selection 或合成答案，普通 session 不受影响。r58 已先形成 meaningful result/report，故未触发再次拆分规范；其 authority/root/effect/artifact/browser/report/state 永久不可复用，任何后继 live 仍需 fresh commit/full admission/pin/plan 与精确授权
- AOX r59 是永久 formal NO-GO。它在 clean commit `431e2c558c13ebd1f99dcc9e3eae6758630a843d` 消费 exact-three plan `sha256:168aa86c433b3c3b90aab4c665453a56cb796f99056f7d04567bc8f453b8e7de` 后只到达 positive 1；probe/formal 各 exact six operation、Chrome approval、37,772 score-filter accession、2,561 length target、0-candidate healthy-empty result、sealed selection 与 published report均已形成。executor 的 teammate close 被正确以 master-only/no-effect 拒绝后，却将 execution task 错误终结为 blocked；master 无 reopen 语义，又把 `selection_active_writers` / legacy `closure_ready=false` 误解为不能在当前 turn 持久化 intent，最终零 closure request、120 drains exhausted。decision `sha256:8b05ef13dfaf79f9a15a647fbbafa446e7ef75656b16db77a7b32baa8b4c6ccc` 与 MICU lower bound `100,114,267 / 500,000,000` 只封存失败。forward inspection 区分 `closure_request_ready` 与 `closure_finalization_ready`，legacy `closure_ready` 明确只指 Host post-request finalization；`aox_cutover_formal_tool_precondition@3` 复用 canonical selection evaluator，仅在 assigned positive executor 的 sealed current selection 同时满足 `closure_request_ready=true` 时 no-effect 拒绝 `blocked|failed|cancelled`，要求 owner 显式 completed 并把 report/closure 留给 reporter/master。sealed state 本身不是成功证明；seal 后 universe、authority、workflow、process、continuation 或 evidence 漂移时仍保留 generic blocker/failure 出口。它不自动完成 task、关闭 attempt 或选择科学策略，non-ready selection、fault 与普通 V3 session 不受影响。r59 全部 authority/root/state/effect/artifact/report/browser bytes 不得复用；后继仍需 fresh commit/full admission/pin/exact-three plan/roots 与对该 plan 的单独精确批准
- AOX r62 是永久 diagnostic NO-GO。它在 clean commit `5265c7813c64880c03bef3aee15e552e4f4d1c49` 上完成 13 项 controlled operation、三项 canonical task、sealed selection 与 published report，但 executor close 被 historical `aox_cutover_close_actor_violation` 拒绝，master 后续出现 `aox_cutover_task_identity_not_ready` 并写终答而未执行 duplicated close；attempt 保持 open，空 drain 最终被 `formal_runtime_drain_exhausted` 与 `scientific_attempt_control_missing` 两层包装。Phase 2 不改写该 authority/root/SQLite/effect/decision，只删除导致分裂的 active master-only/co-terminal machinery：exact attempt-task `assigned_ref` 是唯一 close requester，finalization 再核 assignment；closure 不绑定 response/report，closure wake 走 ordinary runtime，`task.finish(completed)` 必须在 immutable closure 后显式执行。连续两次相同 replay-safe zero-signal/zero-writer open-attempt observation 以 `scientific_attempt_open_no_wakeup` 有界终止；diagnostic 保留 raw facts 与 measured MICU、始终 non-eligible，formal 仍要求 exact control。migration `035` 只保留 historical rows；本地 commit 不授权下一次 live，r62 consumed plan/state 不得复用
- AOX r63 同样是永久 diagnostic NO-GO。它在 clean commit `8e70c9ae951888a7cbc07bcfa9cf8b0bbcde7a96` 上先正确提交 formal `attempt.create`，但 exact attempt-id wake 的 fresh teammate 只收到旧 task prose，遂重复调用 drifted create；Host 正确返回 `authorization_required/no_effect/terminal`，owner 以 `task.finish(blocked, failure_ref=failure_cf29c4815df93f19feb7)` 显式终结 execution。decision `sha256:4311910ba7d18c6488092a5276a5c3a1f4e9092b3ac5af6083ced17ccd0338d4` 的 `task_blocked` 是外层 wrapper，`unknown:3` task counts 与空 tasks evidence 是投影缺陷。forward correction 令 successful create 与 close 都成为非业务终态 bounded handoff，并以通用 canonical wake-facts projector 从 exact admission/closure/failure record 重建 prompt；AOX 从 immutable task-finish ref 解析 typed cause、保留 wrapper 并封存真实 completed/blocked/todo task。该修正不改写或重跑 r63，不授权 r64/live/MICU/provider/HPC/Chrome
  post-r63 composition audit 又收口了 generic master 与 canonical owner 双 successor：
  scientific handoff 不再先排 generic wake，Host-finalized owner wake 成为唯一后继；同一
  bounded ephemeral facts 可进入 master 或 teammate。AOX 以一个 current-exit projection
  接受历史 blocked/resume/blocked receipts、同刻矛盾 fail closed，按规范化 causal
  timestamp 与 stable id 选择当前 operation/task/sandbox cause，并把同一有界 task/evidence
  facts 直接交给 failure evidence，不再二次读库。该 correction 同样不授权任何新 live action。
- AOX r64 同样是永久 diagnostic NO-GO。独立 probe 六项 operation 完成；formal 前五项完成，HMMalign 在 dispatch 前因 SSH ControlMaster connect 失败。sealed runner attempt 已证明 `transport_connect_failed/no_effect`，旧 closed metadata/adapter/Host projection 却把它压成 `durable_hpc_terminal_failure/terminal_known`；continuation 已形成 `controlled_effect/agent_can_replan` failure 并排队 exact `engine_completed` owner wake，driver 仍立即停止，failure evidence 又只保留 probe facts。forward correction 统一 SSH/Slurm sealed terminal metadata 与 runner-first Host causal projection，以一份 bounded `probe|formal` operation facts 服务 observation/evidence。r64 当时的 one-later-drain 规则已由 r66 普通 bounded-drain selected-chain policy 取代；两者都不重试/replay、创建 work/authority 或改判 r64。
- r65 Phase 2 不启动 live，而是退役已经完成、无法满足 current close contract 且永久不可进入 formal acceptance 的 closure-stage authority/reconstruction/live/CLI 全链；历史 SQLite/evidence 继续兼容，formal non-adoption negative gate 继续存在。current formal 路径安装 `aox_motif_candidate_filter@1`、三个 exact conditional-empty calculation 与 `aox_final_deliverable_normalization@1`，并用 atomic draft prevalidation + source-bound `aox_final_deliverable_validation_receipt@1` gate 阻止错误 attempt closure、execution completed 与 report handoff。live/eval/offline 共用 final deliverable validator并保留 earliest typed cause；该 local correction 不授权 r66/live/MICU/provider/HPC/Chrome。
- AOX r66 同样永久 diagnostic NO-GO。formal executor 把 fetched MAFFT artifact descriptor 直接交给 `bio_tools.hmmbuild`，没有先取得 exact `ws.stage_artifact` ref；earliest cause 是 Host pre-admission `hpc_stage_ref_required/no_effect`，外层 run 为 `sandbox_exec_nonzero`，且无 operation admission/external dispatch。Phase 2 封存 source-bound cause/wrapper、failed ToolResult 与 canonical owner wake，统一 formal local/controlled selected-chain projection，删除 AOX one-shot handoff、drain override 与 failed-history poisoning；业务收敛只看 ordinary bounded drains、complete selected-chain closure 与显式 task/report state。该 local correction 不授权 r67/live/MICU/provider/HPC/Chrome。
- r59 closure-stage isolated live diagnostic 是 historical non-`rNN` evidence，不改判上述 NO-GO。r65 已删除其 production source qualifier、reconstruction、authority、driver、CLI 与 runnable tests；`aox_closure_stage_child_evidence@3` / `aox_closure_stage_live_result@3` 及旧 SQLite rows 只供离线兼容。结果永久 `acceptance_eligible=false`，没有 formal bundle、reducer、promotion、push 或 numbered follow-on；`docs/v3/aox-closure-stage-live-diagnostic.md` 现为只读封存页，不是 operator contract
- lifecycle repair commit `c3c560dd6ede54958398fb3e55d5cd62cc956ad1` 的首个 fresh non-`rNN` successor 同样是永久 diagnostic failure。plan `sha256:47ebfa37d653fa51c61eb304b3df620033d57f99aee6a3fcc88ae2e396b861ab` 只消费一次；research/execution 已完成，但 master 从 executor-scoped historical compaction 读到旧 workflow ref，在自己的 empty explicit focus 下调用 `task.delegate`，正确得到 `workflow_ref_not_authorized/terminal_known/agent_can_replan`。下一 call 只叙述“省略 refs”而未执行，report task 保持 ready/unassigned；3 个 command 推进 signal，随后 117 个 replay-safe empty drain 以 generic exhaustion 结束。decision `sha256:eb70608e595d64c785227e4c05b46334a3996d853177341f2da729d4bf9c1abc`、fatal `sha256:27ae166969295685ed56418e6b8abc404c7e3fff88884f5e85c1fe944b7723be` 与全部 root/authority 不可复用。随后曾加入 turn-local recovery obligation 和 AOX prose-response veto；2026-07-28 的 control-boundary simplification 已认定两者把策略判断误升格为 Harness fatal，并从现行实现与合同删除。保留的修复只有 authority-free/scope-correct compaction、canonical tool/domain guards 与两次一致 no-wakeup diagnostic；历史 plan 不因此获得复用或重试资格
- repair commit `4bf4c4244fae68beff8e5d47717e83824ff2367e` 的 fresh non-`rNN` plan `sha256:7394c5200582b114a72fa08b0711dc993f4c7164dd66c1fb20dd1cf837060ae2` 已且仅已消费一次。它证明 authority-free prompt 与 durable handoff 路径：master 的 `task.delegate` 使用 `workflow_refs=[]`，reporter 发布 `report_16937278db9c` 并完成 canonical report task，research/execution/report 三 task 全部 completed；master 在同一 response 写出终答与 `scientific.attempt.close`，产生 closure response 和 immutable closure `attempt_closure_a2f78d1fd2199e239696b99e`，cursor `263` 为 `scientific.attempt.closed`。5 个 runtime command 各处理 1 条 signal，零 empty drain；该事实不再被解释为已删除 response veto/recovery matcher 的有效性证明。旧 terminal-command coordinator 随后在 attempt scope 已 `freezing`、post scope 尚未 open 的 bounded rollover window 申请 observer，被 `mutation_writer_admission_closed` 后错误归类为 `mutation_driver_writer_identity_invalid`；decision `sha256:470df988b817867c5fb80b859fd60c414d99a873e66a839283beb13fe1bef237` 与 fatal `sha256:a3c4a24fcb6e9342dc11faa48bdb393481c0c9e1f4a1b9559c83b4fada0e8123` 永久 non-acceptance。post-live correction 只对 exact authority/attempt、zero-open、无 competing scope 的 `freezing|quiescent|sealed` 状态在同一 command deadline 内等待；其他 identity/scope 错误仍 fail closed，超时为 `scientific_attempt_scope_rollover_stalled`。本 plan、target、MICU 与证据不可复用，该 correction 未经第二次 live 验证且不自行产生新 authority
- clean commit `349293b3f91976cdda99db38bb8f960530b00cd9` 的 fresh plan `sha256:428bf4820d30331a0e7ce1dfc9ceb140abb294ff762893fb46a32a2db71cc641` 同样只消费一次。真实 executor/reporter/master、report `report_dcdc48787749`、co-terminal response、immutable closure `attempt_closure_1f770b18f1760245a19fa112`、post-closure scope、Chrome observation、17 次 actual MICU 与 parent supervision 均闭合；最终 verifier 却因两个 evidence-envelope 陈旧断言 fail closed：shared summary 从已删除的 `runtime_state.controlled_operations` 得到 0，而 terminal/reconstruction 都证明 exact six；`@2` validator 又拿外层 `closure-stage-377c697db59a311988e713540ce7c6d3` 比较内层 `attempt_1f11158bdb21feceaac39613` scope。decision `sha256:fdae6390e15710332c0a46dd212ae90b588c163747b0f210052152fc3bdc9a84` 永久 non-acceptance，无 live result/formal follow-on。forward `@3` schema 只修证据分型与交叉绑定，不修改 agent 策略、科学 universe 或 supervisor 行为；旧 plan/target/MICU/browser/evidence 不可复用
- clean repair commit `4d7175c0958224ce649e1661062d033b5fad5295` 的 fresh non-`rNN` plan `sha256:df31b14becb716e2d50099c0df22a7822ea046a16dd39b3781d54e30d3b000da` 已且仅已消费一次。真实 `gpt-5.5` executor/reporter/master 在 6 次 bounded drain 内完成三项 task、exact six terminal-known operation、report `report_9e037bbde835`、co-terminal response、immutable closure `attempt_closure_ce41b066878ede97857e62fc` 与 inner attempt `attempt_1aac55d28b6f27c71356ff32` 的 exact post-attempt scope；外层 run attempt `closure-stage-f667a488a95d3b062ff994223f9c9164` 保持独立。challenged Chrome、parent supervision、SQLite/quiescence、source reconstruction、runtime parity、operation projection 与 MICU ledger 均经离线独立重算闭合；15 条 actual MICU 精确计费 `949419` tokens，无 estimate/overage/hard breach，source inventory 与原 r59 campaign decision 字节不变，也无新增 scientific provider/HPC/sandbox operation 或 materialization。`aox_closure_stage_live_result@3` `sha256:e6ff14b1453801487beccee509377d741d46f5b37d414afe4c8f7381a0fba115` 和 completed decision `sha256:ef505a31e345687821cc9f5e0e7e8ba08b222ddb2b782b4df25b9897e196e3bb` 只证明 isolated closure-stage diagnostic 成功；仍永久 `acceptance_eligible=false`，不改判 r59，不产生 formal bundle、exact-three input、reducer、GO/NO-GO、promotion、push、PR 或 numbered follow-on
- 裸 `uv run pytest` 通过 `pytest.ini` 默认排除 `integration`、全部 `live_*`、`seeded_live_smoke` 与 `quality_eval`；真实外部测试必须同时满足环境 gate 与命令行显式 `-m` 选择，已配置凭据本身不能触发默认外部调用
- `live_e2e` 是外部配置和 live 依赖的必要 gate，但不能单独证明单消息完整报告生产路径已经产品完成
- live E2E 轮询在 task 已失败、所有 agent 均非 working/active 且没有 pending signal 或 unread inbox 时必须立即以持久 failure evidence 收敛；不得把外部 provider rate limit、缺 artifact 或 fail-closed 终止包装成通过，也不得在业务已静止后空等全局超时
- `seeded_live_smoke` 是辅助回归支持，不是 blank-world cutover proof
- reporter/report publication 的验收必须检查 task board、delegation、inbox、runtime drain、workspace `report_drafts` / `reports` 和相关 events
- 缺少 live provider/HPC 配置时，应报告为 gate prerequisite missing，不得计为通过

### 9.1 r67 deletion-first 测试编排边界

r67 diagnostic id `aox_diagnostic_8c2ce426355c001253b86c1c`、attempt
`diagnostic-positive-5dfdd0686e9174a975ff85b18404e85d` 与 decision
`sha256:d9356b0bdd25885f19e2452773dfac03bfa09e39562ed4c00c8fca9828ef480b`
永久 **NO-GO**；其 `3,903,566` charged tokens、`81` attempts、authority、root、effects
与 evidence 均不可复用。它证明旧 AOX observer 会把已纠正的 pre-admission 失败历史再次
提升为 campaign stop，因此不能继续承担测试编排。

现行架构删除 AOX runtime observer、Core runtime-barrier/observer-writer、automatic
drive-until-terminal/no-wakeup/scope-rollover chain、`run-live` 与
`run-diagnostic-live`。本节之前仍提及这些符号的 r14-r66 incident/contract 条目仅用于
解释历史 sealed evidence，全部由本节取代，不是当前 runnable operator contract。

Codex 测试员是未来经单独批准 campaign 的唯一编排者，但只能调用 public Host API/CLI：
message、bounded runtime drain、command status、pending approval、approval resolution、
workspace 与 replayable events。保留的 authority/pin/preflight/process-supervision/evidence
shell 不作业务判断；authority consumption 只原子消费 exact plan，不启动 attempt。
Host 继续独占 canonical state、approval、fencing、unknown/external effect 与隔离边界；
task/attempt/report terminal 只能来自 canonical write contract。进程退休、空 drain、无 wakeup
和 ToolResult 都不是业务终态。最终 GO 仍只由 sealed attempt bundle offline verifier 与
exact-three campaign reducer产生。本 Phase 2 不授权 r68、live、MICU、provider、HPC 或
Chrome。

### 9.2 r68 prelaunch blocked 与 public conductor 正向生产路径

r68 的 exact authority 已消费，但旧 public `/v3` 无法导出 formal `@3` 所需的 closed
attempt evidence，Host startup/supervision 与 bundle builder 也没有 production caller。
Codex 测试员因此在 root、Host、session、attempt 全部尚未创建时停止。该状态是
**prelaunch blocked**，不是 canonical r68 NO-GO；没有 r68 attempt/bundle/decision 可供
verifier 或 reducer 判定。authority 不可复用；截至停止点没有 Host/provider/HPC/Chrome
effect，MICU 保持 `128,190,632 / 500,000,000`。

现行 repair 删除 generic `AttemptRunner`、legacy `@2` emitter、production module 中的
test-only evidence builder、陈旧 driver contract 与 browser helper。该阶段曾使用
`aox_blank_world_runtime_config@4`；current 已升级为 `@5`，配置中完全没有外部
conductor/driver identity或`automatic_*` shadow flags。旧 `@1..@4` 仅供历史 evidence
read-only verification；Codex tester 只使用 public Host API/CLI 的事实由 public
reachability/qualification证明，不写回 Host runtime config。

正向 production chain 固定为：

```text
fresh exact plan/consumption
  -> atomic one-use slot claim（先于任何 root）
  -> preflight 验证全部 identity 后才创建唯一 private root
  -> policy-free supervised loopback Host
  -> Codex 逐步调用 public message/drain/status/approval/read APIs
  -> append-only conductor-owned openzyme_public_api_receipt@2 chain
  -> Host public canonical control/events/product-closure export
  -> single source-bound finalize-and-seal
  -> network-free attempt verifier
  -> exact-three campaign reducer
```

`serve-attempt` 只监督固定 Host process group，不发送业务命令或判断 terminal；Host 继续独占
canonical state、approval、fencing、effect、quiescence 与隔离。closed evidence export 要求
exact session/closed attempt/sealed selection，positive 还要重验 source-bound 17-deliverable
receipt并经 artifact boundary读取 sealed bytes。finalizer 在任何输出前闭合 identity、
preflight、startup/retirement、public receipt chain、final workspace/events/evidence 与 MICU
   snapshots，然后 no-replace 封存 profile `aox_public_conductor_bundle@2` 的 `@3` bundle。

本 repair 只证明正向生产可达性，不改变 fault criterion。不能证明 exact
`derived_required_artifact_blob_byte_flip@2` 与 `artifact_blob_digest_mismatch` 的 fault bundle
必须被 reducer 记录为 `fault_contract_unproven` NO-GO。任何下一 rNN 仍需在 repair commit
上 fresh full admission、pin、authority、roots 与单独批准；本 Phase 2 不启动 live、MICU、
provider、HPC 或 Chrome。

### 9.3 post-r68 / pre-r69 deletion-first closure

public receipt chain 不再伪装 Codex conductor 发出了 agent-owned scientific mutation 或
Host-owned admission/closure finalization。`scientific-attempt-commands`、admission finalizer 和
closure finalizer 一旦出现在 conductor receipt 中，offline finalizer 必须以
`public_conductor_actor_boundary_invalid` 拒绝。receipt 只闭合 session create、entry message、
authority grant、显式 bounded drain/status、pending approval/resolve、fault capability 与最终
workspace/events/export reads；每个 drain 必须在下一 drain 或最终读取前得到 terminal command
status，CLI handoff 使用 flushed JSON stdout。

agent 与 Host 的真实转换由 `aox_closed_attempt_evidence@2` 证明。其
`aox_public_product_closure@1` 必须与最终 public workspace 和完整 event replay 一致，并固定
exact research/execution/reporting 三任务、唯一 owner identity、每任务唯一 owner-authored
`task_finish`、source-linked report/draft、最终 assistant answer 与正向三任务 completed。
fault 槽只能通过 authority-bound public byte-flip capability 在 exact derived
`aox_hmm/AOX_ref21.fasta` 的 byte 0 产生一次同尺寸 digest 变化；
`aox_fault_negative_state_closure@1` 必须闭合唯一 MAFFT consumer 的
`artifact_blob_digest_mismatch`、非成功 task/report/draft/deliverable/conversation/events 状态。

formal plan 的每个 ordinal 在 root 创建前以 private no-replace sibling 原子 claim；claim 绑定
campaign、plan/consumption、ordinal、session/task/envelope/root、campaign-root identity 与
source-derived launch id，不包含 attempt/lane/admission shadow truth，并进入
`aox_attempt_preflight@3` 及 sealed source set。campaign reducer 只接收同一 campaign/plan 的
exact ordinal `1/2/3`，分别拒绝 launch identity 与 Host late-bound
attempt/lane/admission/idempotency/selection identity collision。production reachability 不再扫描 source 名称；
资格场景通过真实 `ProductionCompositionFactory`、public FastAPI routes 与 file-backed SQLite
写读证明 composition，并对未开始的 fault/export 路径验证 typed fail-closed。

下一轮测试必须使用 [新版 r-series Codex goal](v3/aox-r-series-codex-goal.md)，从本 repair
commit 重新 full admission、pin、fresh authority 与 fresh roots；r68 consumed state 不可复用。
本 Phase 2 不启动 r69、live、MICU、provider、HPC 或 Chrome。

### 9.4 r69 pre-admission blocked 与 post-r69 late binding

r69 基于旧 clean commit `b0ed3ea767fb44c892a14f90f59a50a96d2aa58f` 消费了 campaign
`aox_campaign_2a57780d6663d57da38621d6` 的 formal authority、slot/root、Host session、
三次 PubMed provider request 与 `512,357` MICU；账本到达
`128,702,989 / 500,000,000`。execution task没有 canonical lane，public scientific command
中的 `attempt.create` 因 `attempt_lane_scope_invalid/no_effect` 返回 409。SQLite 中不存在
admission request、scientific attempt或closure，bundle/reducer均未运行。因此 r69 是
authority/root/session/provider/MICU 已消费但 attempt未创建的 **pre-admission blocked**，
不是 canonical NO-GO。其 plan、slot、root、session、effect、receipt与 MICU attribution全部
封存且不可复用；后续不能为它追认 attempt id。

forward contract把 launch identity 与 scientific control identity严格分开：

```text
formal plan@2 / consumption@3
  -> slot claim@2(session, task, envelope, root, launch_id)
  -> root proof@3 / preflight@3 / Host supervision@2
  -> session + exact execution task
  -> executor: lane.create -> lane.bind_task
  -> current assignee: attempt.create(envelope_id, idempotency_key)
  -> Host internal finalizer rechecks assignee and creates canonical attempt
  -> canonical owner wake carries late-bound attempt/lane/admission facts
  -> inspect/export -> public bundle@2 -> offline verifier/reducer
```

outer plan、claim、root proof、preflight与supervision不再包含或推导 `attempt_id`、`lane_id`、
admission request id或admission idempotency key。`attempt.create` 的 tool contract只让agent选择
何时使用哪份 envelope与自己的幂等 key；Host从 durable authority、focused task、真实 lane及
唯一 workflow contract推导 campaign/scope/resources/effect/private route。request write和
finalizer均要求 actor仍是 current task assignee；wrong actor、reassignment、missing/foreign
lane或ambiguous authority均在无 attempt/no effect状态 fail closed。

current product删除 diagnostic authority mint/consume模块与命令、public
`scientific-attempt-commands`、public admission/closure finalizer API/CLI、Core
`create_attempt` compatibility和private admission argument projection。agent-owned
selection/adoption/seal/close仍通过 Harness tools；Host-owned finalization仍在 bounded writer
退休后内部执行；Codex conductor只协调 public message/drain/approval并读取 canonical
inspect/workspace/events/export。历史 SQLite/schema/evidence继续只读，formal non-adoption gate
不变。该 repair只授权 non-live验证、文档和本地提交，不启动 r70、live、MICU、provider、HPC
或Chrome。

### 9.5 r70 pre-runtime conductor blocked 与 post-r70 terminal handoff

在 r70 冻结时尚无 r71。r70 已消费 formal authority、slot、root、session 与 public receipt，但首个
`runtime/drain` 从未提交；Host scientific authorization、admission request 与 scientific
attempt 均未创建。因此 r70 是 **pre-runtime conductor blocked**，不是 canonical r70 NO-GO。
r70 的 plan、claim、root、session、receipt 与全部派生状态不可复用，也不能在 repair 后补写
task、grant、drain 或 attempt。

current launch contract进一步删除 pre-task shadow truth：

```text
formal plan@3 / consumption@4
  -> slot claim@3(campaign, ordinal, session, root, authority policy)
  -> root proof@3 / preflight@4 / Host supervision@3
  -> public session create + entry message
  -> bounded drain admission response（sealed）
  -> terminal command status（sealed + runtime.command.finished exact binding）
  -> public canonical workspace（exact one execution task）
  -> operator scientific authority late-bound to that task
  -> executor lane.create / lane.bind_task / attempt.create
  -> Host late-bound admission/attempt + canonical owner wake
  -> public inspect/export -> conductor bundle@3 -> offline verifier/reducer
```

plan、claim、root、preflight、supervision 与 bundle launch slot不得包含 speculative task、
预生成 authority envelope/request、lane、attempt 或 admission identity；Host scientific
authorization只能在 sealed workspace确定唯一真实execution task后原子创建。finalization
precondition不再隐藏匹配 exact `task.create`，而是从 canonical task board按 kind、agent role、
assignee和immutable owner finish cardinality闭合 exact research/execution/reporting三任务。
task scope、lane owner、approval/fencing、unknown/external effect、provenance/isolation、exact
17-deliverable finalization和Host process settlement边界不变。

每个bounded drain的HTTP 202 admission response和唯一terminal status response都必须作为
bounded sealed handoff进入 `aox_public_conductor_bundle@3`。terminal response必须与唯一
`runtime.command.finished` event在command identity、status、completion、bounded outcome与safe
error/retry字段上逐项相同；digest-only GET receipt、未封存status、synthetic response或多余
handoff不构成terminal proof。thin CLI对non-2xx payload先递归脱敏，再用与2xx相同的canonical
semantic digest、链大小/条数上限和fsync/no-replace封存合同记录。

若runtime command开始时尚无mutation scope、执行期间由canonical transition打开scope，Host仅在
terminal settlement与post-transition projection时获取绑定exact command id的短writer authority，
完成后立即退休；这不是observer、retry或业务终态判断。production qualification通过real public
FastAPI应用、thin client、file SQLite与deterministic model/runtime composition证明正向路径，
禁止private service、手工`ToolRegistry`、直接canonical write或synthetic receipt自证。该repair
只运行non-live验证、更新规格/文档/qualification资源并提交本地commit；不启动r71、live、MICU、
provider、HPC或Chrome。下一fresh rNN仍需clean commit、full admission/pin、fresh authority和
独立用户批准，GO只由offline verifier/reducer产生。

### 9.6 r71 pre-attempt sandbox-bootstrap blocked 与 post-r71 fresh Host bootstrap

r71 campaign `aox_campaign_0356c33b043b00e1ea64d08c` 已消费 authority、positive ordinal 1、
root、session、三任务、late-bound scientific authorization、public receipt及9次model attribution；
MICU从`128,702,989`增至`129,139,238`，增量`436,249`。execution task首次读取
`sandbox.workspace.status`时，cursor 74返回typed `sandbox_image_missing`。Host尚未创建scientific
admission request/attempt，也没有provider、HPC、sandbox command或browser effect。因此r71只封存为
authority-bound **pre-attempt sandbox-bootstrap blocked**，不是canonical NO-GO；全部r71 authority、
slot、root、session、task、authorization、receipt、MICU attribution与派生identity不可复用。事后
观察到image存在不能反推cursor 74时的物理状态，durable根因限定为
`aox_supervised_host_sandbox_image_identity_not_registered`。

post-r71 contract删除dev/eval ambient registration，只保留一个Host-owned bootstrap：supervised
child创建一个`PodmanPipelineSandboxRunner`，在任何ready/业务活动前把它的
`configured_image_ref`、`immutable_image_ref`、`image_digest`、`pipeline_sdk_digest`、
`sandbox_protocol_version`与`runtime_identity_digest`闭合到preflight，然后将同一实例注入public
health与execution。fresh SQLite transaction检查完整image/session/workspace表均为零，写入并重读
一个`repo@sha256` Core image record；任何duplicate/preexisting/mismatch/drift/tamper/reread failure
都rollback。`aox_supervised_host_sandbox_bootstrap@1` receipt进入child-ready、startup `@4`及最终
bundle source binding。Codex不写SQLite；executor只从public tool result读取真实envelope，自行
`lane.create`/`lane.bind_task`后调用`attempt.create`。本repair只授权non-live验证、文档和本地提交，
不启动下一rNN、live、MICU、provider、HPC或Chrome。

### 9.7 r72 prelive conductor blocked 与 qualification single-flight

r72没有形成canonical scientific attempt bundle或campaign reducer decision。原full qualification
返回yielded handle后，Codex在其未terminal时又对同output启动等价full command，随后又执行focused
recheck；另一次recovery把不存在parent的路径作为output，重复跑完collection/harness/scenario后才在
publication失败。这些full report、duplicate、recheck、recovery与stop facts只能封存为
**prelive conductor blocked**，不是canonical r72 NO-GO，且全部不可复用或拼接。

qualification现在有一个明确的repository/operator run-admission边界：任何pytest collection、
harness self-test或scenario前，先校验primary output和optional mainline sidecar为checkout外、absolute、
lexically canonical、target absent、parent existing real directory且无symlink/alias。失败只返回
`architecture_qualification_output_invalid`，不会创建parent、启动matrix或选择alternate output。
获得run admission后立即重验，final publication再重验并保留mkdir/file no-replace与file/directory/
parent fsync，所以mid-run target race不能覆盖既有evidence。

同一canonical checkout的全部`admission|diagnostic|premerge_subset`与任意output共享一个
canonical-root device/inode key。runner在private per-UID trusted-local lock root中以
`O_NOFOLLOW|O_CLOEXEC`打开inert regular file，并从collection前到report pure verification及mainline
sidecar publication结束持有`flock(LOCK_EX|LOCK_NB)`。竞争者立即得到
`architecture_qualification_run_active`；lock不记录business owner/lifecycle，不建立blocking wait、
steal、observer、retry queue或recovery truth，fd close/process crash由kernel释放。

Codex conductor收到yielded `cell_id|session_id`后只能恢复同一handle。handle unresolved时禁止等价
command、focused recheck与recovery output；handle失联时只读检查process和原target后停止并记录prelive
blocked。该correction不改变full matrix/bounded timeout、pure verifier、mainline sidecar non-adoption、
live fail-closed或AOX offline verifier/reducer权威，也不授权下一rNN/live/MICU/provider/HPC/Chrome。

### 9.8 r73 stale conductor source 与 source-bound causal qualification

r73没有创建root、session、scientific attempt或canonical bundle，也没有offline reducer decision。
Codex用外部保存的stale HEAD shadow truth错误丢弃首份实际绑定
`789f1c177552ece953564932f9e29753179cb2fa`的report，并在terminal report后串行重启等价full
admission。两次qualification harness都达到bounded timeout；旧`@1`只留下output digest并为未运行
scenario生成fallback/unproven GAP cascade。全部r73 report/reproduction/stop state与旧persistent
goal只读封存且不可复用；r73是**prelive conductor/qualification blocked**，不是canonical NO-GO。

qualification pytest runner不再属于Host production package。repository CLI进入产品无关
`scripts/test_gate`包之外的`scripts/architecture_qualification_runner.py`，所有
collection/harness/scenario process只由`scripts/test_gate/runner.py`统一执行和process-group
containment。single-flight lock内首份source
identity是admission truth；runner在collection前后、harness后、每个scenario前后与publication前
复核，并把source digest与matched flag封入current qualification report；当前 `@3` 还绑定
owner-constraint registry 与 strategy/world-fidelity transformation results。
每个实际process receipt闭合safe command、exit/outcome、bounded stdout/stderr digest/bytes/tail、
timeout与TERM/KILL。首个collection/harness/scenario/source-drift typed failure立即终止selected
chain，exact not-run ids进入report，不再生成fallback result或GAP/P0 cascade。

AOX只消费current `aox_architecture_qualification_receipt@3`；历史report/receipt`@1/@2`只有显式历史
reader可只读加载。operator-retirement业务语义由identity、raw exit/signal、final descendant count与
forced-unproven的pure calculation决定；real clock只保留一个秒级宽限的bounded containment probe。
Codex不再拥有`started_head`、drift/recovery/adoption truth，也不得在terminal qualification failure后
equivalent relaunch。本correction只授权non-live验证、文档与本地commit，不启动下一rNN、live、MICU、
provider、HPC或Chrome。

### 9.9 启动失败的公开因果与证据纪律

ec69fd8 上的 `pin` 仅执行一次，公开回执只证明
`aox_launch_effective_config_schema_invalid`；因事务目录没有产生启动身份、前置条件或提交标记，
具体出错字段仍是 `exact_identity_unproven`。`ResearchSettings.mcp_enabled` 及
`OPENZYME_RESEARCH_MCP_ENABLED` 没有进入 AOX 的有效配置构造，不能据此推定本次根因。该状态属于
prelaunch blocked，而非 canonical NO-GO；没有 root、session、attempt 或外部 effect，也没有重试权限。

当前 `openzyme-aox-cutover` 以 `aox_cutover_launch_failure@3` 公开失败。稳定的
`failure_code` 始终保留；只有失败源明确声明可公开的 closed tagged-union 原因，才会通过
`failure_details` 输出。`kind=schema_field` 只允许逻辑 schema 字段 `identity/missing/unexpected`；
`kind=runner_attestation` 只允许 exact AOX `tool_id`、可选安全 run/attempt-receipt identity、
`runner_call|runner_result`、closed effect certainty 与可选安全 `runner_error_code`。内部 `details`、
配置值、Host/runner 路径、凭据、消息与
异常链不会自动越过公开边界。历史 `@1/@2` 只作为冻结记录读取。无产品消费者的
`ResearchSettings.mcp_enabled` 已删除；AOX 的 `research.mcp_enabled=true` 继续由 Host 权威配置
明确投影，避免并存的环境影子真值。

Codex 测试操作员可以自由检查当前代码、公开回执和封存状态，但必须区分三类信息：已经观测到的封存
事实、依据当前源码得出的推论、尚未证实的假设。假设可以指导只读调查，却不能改写封存事实，也不能
单独取得纠正后重试（corrected retry）、授权消费（authority consumption）或其他状态变更权限。公开
证据未给出内部原因时，应如实保留不确定性并停在现有授权边界；这一规则约束的是证据与动作之间的关系，
不规定 agent 的调查顺序。

public `openzyme-aox-cutover check-config` 是 pin 前唯一可执行的配置闭合入口。它复用 production
settings resolver、ledger identity、effective-config builder 与 closed normalizer，只返回
`aox_cutover_config_check@1` 的 schema id 和 config digest；不读取 qualification，不写 state，不创建
runner，也不产生 SSH/provider/MICU/Chrome effect。Codex 不得再直接 import Host private
settings/builder/service 来自证配置。静态源码检查仍可帮助理解合同，但只属于推论。

`pin` 与 `check-config` 的 effect 边界不同：`pin` 会通过 forced SSH 依次执行 MAFFT、CD-HIT、
hmmbuild、hmmalign 的 deterministic non-scientific fixture，并产生真实 runner staging/output；因此准备
授权必须如实覆盖 runner attestation，不能描述为“未接触 HPC”。一次 terminal pin failure 后立即停止；
goal 为满足状态协议进行的后续只读审计不等于再次执行 pin，报告必须分开列出
`pin_execution_count` 与 `blocked_audit_count`。

---

## 10. Legacy Boundary

V1 已迁入 legacy。旧 `episode + phase graph` 产品面已从主线删除，主线不再维护回滚用的 graph/storage/API/UI 双栈。

当前 V3 的产品语义：

- `session`
- `task DAG`
- `lane / workspace`
- `approval`
- `inbox / protocol thread`
- `resident teammate`
- `runtime signal`
- `workspace projection`
- `report draft / report`

因此，新变更的默认判断规则是：

- 新产品状态写入 V3 control plane，而不是只写 prompt、browser state 或 graph checkpoint
- 新 agent/team 行为通过 task、inbox、protocol、signal 和 explicit drain 表达
- 新 execution 行为走 pipeline sandbox、artifact catalog、SDK、approval 和 runner staging
- 不新增 `episode`、phase graph、supervisor-route 或旧 workspace projection 入口
