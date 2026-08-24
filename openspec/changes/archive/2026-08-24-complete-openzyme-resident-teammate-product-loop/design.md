## Context

当前代码已经完成 Kernel/Adapter/Plugin/Driver/Distribution 分层和 `file_workspace_public@2` 公开 envelope，但产品闭环在五处断开：

1. `SessionBootstrapKernelApplicationService` 创建的 master 没有 `workspace_generation`，bootstrap receipt 明示 `workspace_created=false`；同时 `MessageIngressKernelApplicationService` 要求 active lease、member 和 ready workspace generation 完全一致，因此 fresh Session 不能通过公开路径接收第一条消息。
2. `skill_keys` 只被写入 `conversation_message`，没有解析、授权、继承、撤销或 signal fence；runtime admission 也没有读取它。
3. Standard 和 EnzymeDesign runtime admission 以空 `policy_decisions` 计算 subject policy，只把近期 conversation 拼成 prompt；task board、lane、workspace、inbox、approval、failure、workflow authority 等 canonical truth 没有形成 closed turn context。
4. Standard 仅声明 5 个 workspace tools，EnzymeDesign 仅在其上叠加 Plugin tools；稳定 collaboration verbs 没有 model-facing runtime，全部 available Plugin tools又会一次性进入 function list。
5. `RuntimeTurnOutcome.messages` 和 `failure` 在 Adapter 返回后没有作为 canonical transcript、完整 outcome 和 `FailureObservation` 原子落库，后续 turn 与 UI 看不到 assistant/tool truth。

本 change 的利益相关方包括使用 Host API/CLI/Web UI 的操作者、resident master/teammate、Distribution 维护者、Plugin 作者以及负责持久化和恢复语义的 Kernel/Adapter 维护者。设计遵循仓库既有原则：agent 保留策略自由，harness 只把世界真实约束结构化、低摩擦地呈现出来。

## Goals / Non-Goals

**Goals:**

- fresh Standard 或 EnzymeDesign 进程在 file-backed SQLite/Git roots 上创建 Session 后，无人工直写数据库即可异步进入 ready，接收消息，并通过显式 runtime drain 产生可恢复的 assistant transcript 与 collaboration truth。
- 为 workspace provisioning、workflow authority、turn context、tool exposure、runtime settlement 定义 closed schema、唯一 owner、稳定 identity、生命周期、CAS/fence、持久化与公开 projection。
- 让模型直接拥有稳定 collaboration verbs 和角色必需工具，同时可通过 `capabilities.inspect` 发现并显式扩展 long-tail Plugin tools；任何扩展都不扩大 authority、不改变 route、不解除 approval/qualification blocker。
- 让 root message、delegation、protocol wakeup、approval resolution 和 continuation 都沿 request lineage 携带 exact workflow authority。
- 保持消息入口和 runtime command 分离，保持 task 业务终态只由 `task.finish` 或已文档化机械迁移产生。
- 同步 Standard/EnzymeDesign executable launcher、Thin CLI、Web UI、AGENTS 与稳定架构文档，并建立 fresh non-live E2E。

**Non-Goals:**

- 不启动或恢复 AOX rNN、真实 LLM/provider、HPC、SSH、Slurm、Chrome、外部 deployment/cutover 或任何 live qualification。
- 不把 LangGraph/LangChain、prompt、浏览器状态、workspace 文件或 transcript 当成顶层产品真状态。
- 不实现多 Host/distributed consensus；本 change 的 durable worker 资格范围仍是已声明的 trusted-Host、file-backed SQLite 单进程 profile。
- 不让 harness 根据 runtime idle、step limit、tool result 或 assistant prose推断 Task 已完成；不让 `protocol.send` 同步执行 recipient。
- 不提供旧 Session 的猜测性在线修复、默认 workflow、默认 route、provider fallback、automatic drain 或 automatic ready-task enqueue。

## Decisions

### 1. Session bootstrap 原子保留 workspace generation，provisioning 由独立 durable occurrence 推进

采用现有 `WorkspaceGeneration@1` 作为 workspace identity 真相，以 `WorkspaceProvisioningIntent@1` 表示异步工作 occurrence，并以 immutable `WorkspaceProvisioningReceipt@1` 和独立 `WorkspaceProvisioningReconciliation@1` 表示外部 effect 与观察式恢复；不另造第二套 workspace lifecycle。bootstrap 在同一 Unit of Work 中创建：

| 真相 | 初始状态 | owner | 持久化 |
| --- | --- | --- | --- |
| Session | `active`，公开 readiness=`provisioning` | Kernel | ControlStore/SQLite |
| master `AgentMember` | `workspace_generation=1`，runtime eligibility 未激活 | Kernel | ControlStore/SQLite |
| root `AgentAuthorityLease` | `PENDING`，绑定 generation 1 | Kernel | ControlStore/SQLite |
| `WorkspaceGeneration@1` | generation/state version 1，`RESERVED` | Kernel | ControlStore/SQLite |
| `WorkspaceProvisioningIntent@1` | `pending`，绑定 exact generation、repository pin、selected Adapter binding | Kernel | ControlStore/SQLite |

`WorkspaceProvisioningIntent@1` 的 identity 由 `intent_id + session_id + agent_member_id + workspace_id + generation + repository_pin_digest + provider_id + target_id + adapter_binding_digest` 构成；生命周期只允许 `pending -> claimed -> ready | blocked | cancelled`。claim 包含 `claim_owner_id`、`claim_token`、`claim_epoch`、`claim_expires_at`，任何 callback 都必须匹配当前 claim 和 intent digest。

Distribution 启动一个 bounded provisioning worker。worker 只通过选定 `WorkspaceProvisionerPort` 调用 Adapter mechanism，不能扫描替代 provider。成功 receipt 先作为 generic controlled-operation terminal receipt 落库，然后一个 Kernel settlement Unit of Work 原子完成：`WorkspaceGeneration PROVISIONING -> READY`、runtime binding 创建、root lease `PENDING -> ACTIVE`、member readiness 更新、intent `claimed -> ready`、event/outbox。失败按 effect certainty 记录 `FailureObservation`：

- `no_effect`：intent 转 `blocked`，不会自动 retry；
- `dispatch_in_doubt`：intent 转 `blocked` 且 `reconcile_required=true`，禁止重新 dispatch；
- `terminal_known` 失败：intent 转 `blocked`，保留 mutation fact；
- stale/duplicate callback：幂等返回或以稳定 fence error 拒绝，绝不部分激活 lease。

`dispatch_in_doubt` 不允许原地重开 intent。operator 调用 exact reconcile command 时，Kernel 创建一条带 attempt、parent、claim fence、原 intent state-version/digest、原 request/dispatch receipt 的 durable reconciliation；worker 只以原请求调用 Adapter 的 observation-only reconcile。reconciliation 自身只允许 `pending -> claimed -> ready | blocked`。READY 可原子激活原保留 generation/runtime binding/lease，但原 blocked intent、receipt 与 failure 仍保持原字节；terminal blocked diagnosis 也保留历史，并把 next action 收敛为显式 successor。successor command 创建下一 monotonic generation、新 pending lease 与新 intent，不能改写旧 occurrence。

`POST /v3/sessions` 在 durable reservation 提交后返回，不等待 clone/volume/provider。公开 projection 只显示 `provisioning | ready | blocked`；`workspace_provisioning_public@2` 同时公开 exact `intent_state_version` 和 nullable safe reconciliation facts。`blocked` 必须携带 safe `failure_id/diagnostic_id/next_action`。恢复只可经 `POST /v3/sessions/{session_id}/workspace/provisioning/reconcile` 与 `/successor`，以 exact Session、intent digest/state-version 和 reconciliation identity 做前置条件；两个 HTTP 入口均返回 `202`，不隐式 provision、drain、创建 Task 或选择替代 Adapter。

备选方案是让 bootstrap 同步 clone，或继续让测试/操作者直接 seed workspace。前者把外部时延和不确定 effect 放进 HTTP ownership，后者没有产品路径和恢复合同，均不采用。

### 2. Workflow 选择是 request-lineage authority，不是消息 metadata

新增两个 Kernel-owned closed records：

- `WorkflowAuthorityBinding@1`：`authority_id`、Session/project、`request_lineage_id`、source message/principal、authorized actor、exact selected workflow refs/digest、registry snapshot digest、parent authority、derivation kind、task/lane scope、status、epoch、created/updated/revoked timestamps、binding digest。
- `RuntimeSignalAuthorityLink@1`：`signal_id`、`authority_id`、authority epoch/digest、causation ref、source kind、link digest。

消息 wire 可以继续接受 `skill_keys` 作为兼容的“选择请求”别名，并新增 canonical `workflow_refs`；它们都必须经过 Distribution 提供的 `WorkflowRegistryResolverPort`，解析为 exact versioned refs。raw key 永远不直接授权。即使选择为空，root message 也创建显式空 binding，避免“缺失”被误读为“全部/默认”。

root message admission 在一个 Unit of Work 中写入 conversation、inbox、root authority binding、runtime signal 和 signal link。`task.delegate` 只能从当前 active binding 派生 scope/selection 子集；child selection 不是 parent selection 的子集时拒绝。`protocol.send`、approval resolution、continuation delivery和其他 downstream wakeup复制同一 authority或按 recipient/scope 派生子 binding，并把 causal ref 写进 signal link。

revoke/expire/consume 通过 CAS 增加 epoch 并改变 status。runtime admission、provider 调用前、每次 tool dispatch 前和 delegation settlement 前都重新读取 exact binding/link；任一 epoch/digest/status 漂移 fail closed。禁止：读取“最新 workflow”、扫描所有 workflow、隐式 union parent/child、从 memory/task/protocol prose 恢复 authority、在 revoke 后重开 action。

备选方案是把 `skill_keys` 拼进 system prompt，或只在 signal 上复制 raw refs。两者都没有 owner、subset、epoch 和 causal fence，不采用。

### 3. Kernel 构造 `RuntimeTurnContext@1`，Adapter 只负责模型机制

`RuntimeTurnCommand` 升级为 `runtime_turn_command@2`，加入 `RuntimeTurnContext@1`、workflow authority identity 和 tool exposure identity。context 是 bounded、canonical、可 digest 的事实快照，至少包含：

- Session objective/status/version 与 request lineage；
- current Agent identity/role/process epoch/authority lease；
- scoped Task、task board 摘要、dependency 与明确 terminal facts；
- lane/workspace generation/readiness/revision/status；
- unread inbox、delegation/protocol causal refs；
- pending/resolved approval 与 continuation；
- current/public-safe failures及 `diagnostic_id`；
- exact workflow authority selection、scope、epoch；
- capability binding、affordance、tool exposure 和 route identities；
- bounded recent user/assistant/tool conversation。

Kernel projection builder按固定 collection/byte bounds 排序并生成 `context_digest`；超界数据以 typed truncation facts和 cursor 表达，不能由 Adapter悄悄删除某一事实类。LLM Adapter 把 context 序列化为一个固定 system contract，再附 conversation；它可以在输入预算内确定性压缩旧 transcript，但不能压缩 current authority、workspace、task/approval/failure 或 exposure identities。context 不包含策略指令，例如“应当选择哪个任务/工具”。

Standard 与 EnzymeDesign 共用 Kernel builder；Distribution 只提供 role policy、workflow registry 和 Plugin projection contributions，不复制 context 拼装逻辑。

### 4. Tool exposure 使用 `Direct / Deferred / Hidden`，与 affordance/authority 正交

在每个 turn 的 `ToolExposureSnapshot@1` 中，Distribution-owned closed role policy 对 declared catalog 的每个 tool 给出唯一 exposure：

- `Direct`：稳定 collaboration verbs 与当前角色必需工具，若 affordance 为 available，则进入当前 provider function list；
- `Deferred`：long-tail Plugin tool，出现在 `capabilities.inspect` 的 safe reflection 中，但仅在模型明确提交 exact tool name 扩展后进入同一 command 的后续 provider step；
- `Hidden`：不进入 function list，也不进入 public/model inspection。

初始 Kernel direct baseline 为 `world.inspect`、`capabilities.inspect`、`task.create`、`task.update`、`task.finish`、`task.delegate`、`protocol.send`、`approval.request` 以及适合角色的 `workspace.status/fs/exec`。Distribution 可以把角色必需 Plugin tools设为 Direct，但必须在 manifest/policy测试中逐项声明；其余 available Plugin tools默认 Deferred，而不是全部 Direct。

`capabilities.inspect` 支持 safe query 和 exact `expand_tool_names`。expand 只改变一个 command 内的 model presentation；Kernel 仍用原 `ToolAffordanceSnapshot` 在调用前复核 authority、approval、workspace、qualification、route 与 health。expand 不会创建 authority、不解除 blocker、不选择另一 route、不跨 continuation 自动继承。LLM Adapter 在每个 provider step 前重新读取当前 model-visible list，使一次 inspect 后的显式 expansion 可在下一 step 使用。

`ToolSubjectPolicyDecision` 增加明确 deferred 语义，Standard/EnzymeDesign runtime admission 不再使用 `decisions=()`。role policy 缺失、catalog 未全覆盖或 policy digest 漂移均拒绝 admission，禁止“全部可见”的默认值。

### 5. Stable collaboration verbs 通过 Kernel application services 写 canonical truth

新增 Kernel-owned tool specs/runtimes，runtime 只能通过 current `RuntimeToolScope` 和 application services调用；不把 repository/store/runner暴露给 Adapter或模型。

- `task.create/update/finish` 调用 Task/Collaboration application service；`task.update` 不接受业务终态，`task.finish` 要求明确 disposition/evidence。
- `task.delegate` 是唯一 product-facing delegation verb，写路径固定为 `ProtocolService.delegate()`，并派生 workflow authority 子集。
- `protocol.send` 只写 inbox + wakeup signal/link，不同步运行 recipient。
- `approval.request` 只创建 pending approval；human decision 仍由 Host API/CLI/UI resolution path 写入并排队 continuation/wakeup。
- `world.inspect` 与 `capabilities.inspect` 只读 current scoped projection，不产生产品 mutation。

tool 参数/contract错误返回 LLM 可读 `ToolResult` error；canonical mutation/effect错误形成 `FailureObservation`。任何 tool result、runtime idle、step limit或 protocol prose都不自动完成 Task。

### 6. Runtime outcome 在一个 fenced Unit of Work 中形成完整 transcript/failure truth

`RuntimeOutcomeConsumption@2` 携带 exact closed `RuntimeTurnOutcome`，Kernel 在消费前验证 command/outcome/signal/lease/process/workflow authority/tool exposure identities。首次接受时原子写入：

- immutable `runtime_turn_outcome` receipt（full outcome + digest）；
- assistant/tool `conversation_message` rows，保持 outcome message identity/order、command/task/lane/correlation；
- outcome 内的 canonical `FailureObservation`；
- signal terminal state、consumption、settlement intent、可选 continuation intent、event/outbox。

duplicate exact outcome 返回同一 consumption digest且不重复 transcript；同 command 的不同 outcome、message collision、failure collision或 stale fence在 mutation 前拒绝。public conversation按 canonical created/order字段呈现 user/assistant/tool消息，下一 turn从同一 transcript恢复。失败 projection 必须能由 settlement 中的 `failure_id` 找到实体；private traceback/stdout/stderr只保留在 private diagnostic store，公开面仅含脱敏字段。

### 7. 公开 envelope 保持 `file_workspace_public@2`，新增内部版本化 projection facts

不改变 `file_workspace_public@2` 的 root/core section集合；在现有 `session`、`agents`、`conversation`、`runtime`、`workspace`、`failures`、`tool_reflection` section内加入版本化的 provisioning、workflow authority、transcript和tool exposure facts。这样已有正确实现的 workspace/release compatibility保持不变，同时旧 Session 若缺少本产品闭环要求的 canonical records，会返回结构化 `resident_teammate_state_incompatible`，不会猜测填充。

Host API 保持：

- `/messages` 只 admission + enqueue，响应明示 `runtime_executed=false`；
- `/runtime/drain` 只提交显式 bounded command，可按已有 contract polling；
- Session bootstrap 返回 provisioning identity/state；
- workspace inspection返回完整 collaboration projection；
- approval decision只 schedule exact downstream work。

Thin CLI 增加 readiness/status、conversation/tasks/agents/approvals/failures 的可读渲染和 runtime command status/poll；Web UI显示 provisioning blocker、assistant/tool transcript、task/delegation/inbox、approval、runtime drain和失败诊断。UI不得把按钮点击或本地状态当 canonical success。

### 8. Executable launcher 由 Distribution owner 提供

`openzyme-standard` 与 `enzymedesign-distribution` 各自提供 console entry point/`main()`，负责从显式配置构造 file-backed Store、workspace Adapter、runtime Adapter、workers、Host dependencies和 `create_v2_app()`，然后交给 ASGI server。`apps/openzyme-host-cli` 保持纯 HTTP client，不进口 runtime实现。

launcher startup先做 closed configuration/preflight；缺 provider、repository binding、workspace root或manifest时结构化失败，不切换到另一个 Adapter。shutdown按 composition owner顺序停止 HTTP admission、drain/provision workers、runtime process owner、store connection；不得把进程退出解释为业务完成。

### 9. Fresh non-live E2E 是产品闭环验收，不是 live readiness

Standard 与 EnzymeDesign 分别从全新临时 file-backed roots构造真实 Distribution composition，使用 deterministic fake LLM provider和recording/no-effect Plugin adapters，执行：Session create → provisioning worker bounded tick → ready projection → message admission（断言未 drain）→ explicit drain → assistant transcript → task/delegation/inbox/approval/workspace/failure projection → process retirement/restart →同根恢复。Web UI 从每次经过 exact contract 与 release/projection digest 校验的 Host projection 派生浏览器本地投影变化观测；该观测只说明两次已验证 projection 的差异，不是 Host outbox/Kernel canonical event stream。EnzymeDesign额外证明 role essentials Direct、long-tail Plugin Deferred、Hidden不可检查及 expansion不改变route/authority。

测试设置 network/provider/HPC/SSH/browser deny guards。此 E2E 只证明 non-live composition和产品语义，不声明真实外部availability、deployment cutover或完整科学报告生产已经完成。

## Risks / Trade-offs

- [跨层变更面较大，可能发生 schema/codec 漂移] → 先冻结 contracts和OpenSpec，子代理按互斥目录实施；每个新 entity都增加 closed codec、round-trip、unknown-field、CAS/fence负向测试。
- [异步 provisioning 让 create→message 之间出现可见等待] → 公开 `provisioning/ready/blocked`，提供poll/refresh和稳定 blocker；不以同步HTTP隐藏不确定性。
- [tool exposure policy 配置不完整导致模型无工具可用] → policy必须全覆盖catalog并在startup/preflight fail closed；Standard baseline有固定 collaboration verbs。
- [完整 world context 增加 token成本] → Kernel使用固定collection/byte bounds与cursor/truncation facts；Adapter只压缩旧 transcript，不丢 current authority/constraint facts。
- [workflow revoke 与 provider/tool 并发仍存在窗口] → provider前、每次tool/delegation前重验epoch/fence；已发外部 effect按certainty记录并reconcile，绝不伪称撤销回滚了已发生effect。
- [保留 public envelope @2 可能让旧 client不知道新增内层事实] →新字段均位于既有object sections并有自己的schema/digest；mutating clients仍按release/projection identity CAS，旧 Session缺核心records时明确incompatible。
- [Distribution launcher可能误触 live provider] → default/test profile只允许显式fake/disabled provider；真实provider必须另行配置和opt-in，本change验收设置deny guard。

## Migration Plan

1. 先加入 contracts、SQLite codecs/migrations和读取兼容；尚未启用新写路径。
2. 更新 bootstrap/provisioning worker，使所有 fresh Session只写新 generation/intent/lease合同；旧 Session继续可读，但不能进入新 resident runtime。
3. 加入 workflow authority root/derived binding、signal link及runtime/tool fence；切换消息、delegation、approval、continuation写路径。
4. 切换 runtime command/context、tool exposure和outcome settlement；更新 Standard/EnzymeDesign composition与launchers。
5. 更新Host/CLI/UI projection并运行fresh non-live E2E、restart恢复、focused tests、OpenSpec strict validation和mainline gate。
6. 不在本change执行生产deployment。未来部署必须先备份store并以fresh Session canary验证；rollback是退回旧binary并只读保留新schema rows，不能让旧binary继续写已进入新epoch的Session。

## Open Questions

用户已通过 1A、2A、3A、4A、5A、6C 冻结本 change 所需产品决策；当前没有阻塞实施的开放决策。实现中若发现现有代码无法满足上述 owner/identity/fence，而需要扩大授权范围或改变产品语义，必须先更新本 design/specs，不得以 fallback 代替设计修正。
