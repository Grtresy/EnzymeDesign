# OpenZyme V3 公共接口

## 1. 总体原则

V3 公共接口以 harness-first 语义为唯一主线。

目标：

- 给前端、CLI、外部调用方一个新的 harness-first 语义面
- 不要求调用方理解 LangGraph、phase graph、internal engine state

说明：

- `/v3` namespace 是当前公共产品接口
- 公共接口不暴露 workflow graph、checkpoint 或 capability-local engine state
- 旧 `episode`、phase rail、supervisor-route 词汇不得重新进入公共接口

## 2. API 设计默认值

建议最小接口按两层理解。

面向普通用户与 Web UI 的主入口：

- `POST /v3/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/events`
- `GET /v3/runtime/health`
- `POST /v3/approvals/{approval_id}/resolve`

Public JSON contract 由 Host API 的 request/response DTO 双向校验。未知请求字段、空 mutation、越界长度和非法 enum 返回 `422`，不得被静默忽略；response 顶层 shape 与 event envelope 同样经过 schema 校验，防止内部字段偶然泄漏或调用方依赖未声明字段。所有 JSON 错误统一为 `{"error":{"code","message","hint?","details?"}}`；调用方必须按稳定 `code` 分支，不能解析异常字符串。

公开诊断采用 fail-closed sanitizer contract。ToolResult、workspace/run read model、runtime signal、`harness.failed`、event、eval 与 HTTP error 中由 schema 指定的 diagnostic/locator field，在 durable/public 落点前先把精确 sandbox workspace/control-socket Host root 映射为 `/workspace` 和 `/openzyme/control.sock`，再删除当前已测试的 high-risk Unix/HPC roots、Windows drive、UNC、`file://`、private/special-use URL、storage/runner locator 与 credential corpus。该 producer sanitizer 不声称识别任意自由文本中的所有 private path，也不得无类型改写 user conversation、scientific evidence 或 report 正文；更完整的 typed/versioned 边界见 [deferred proposal](architecture-proposals/canonical-public-diagnostic-boundary.md)。public projection 对历史 diagnostic 与 schema-declared locator field 再次投影；无法确认安全时退化为稳定 redacted diagnostic。原始异常与完整 stdout/stderr bytes 只能留在受保护 Host-private log，public event/API 只得到 sanitized summary、raw-byte digest/size、truncation marker 与 opaque non-readable ref。AOX verifier 对 surviving Host path/private locator 的独立严格拒绝不得因 sanitizer 存在而放宽。

`GET /v3/runtime/health` 是经过脱敏的产品运维投影，返回 `v3.runtime_health.v1`、整体 `ready|degraded`、deployment/storage profile，以及 control plane、model、background runtime、execution、research、sandbox 的公开状态。它不得返回 worker identity、原始 exception、Host path、runner 配置或 secret；更深诊断仍属于受 operator/admin gate 保护的 `/debug/*`。`fixture_non_cutover`、`unavailable` 与 `disabled` 必须与 `ready` 区分，不能为获得绿色 health 而把 fixture 伪装成真实 provider。

`POST /v3/sessions/{session_id}/messages` 是用户消息 ingress。它持久化用户消息并排队 `agent:master` wakeup signal，正常产品推进由 background runtime worker claim signal 后完成。显式 `skill_keys` 经去重后绑定到同一 canonical user conversation document；worker 从 signal 的 exact source message 恢复该 focus，因此 admission 与 background/manual drain 解耦不会丢失 workflow 授权。`/runtime/drain` 自身不能提交或扩张 `skill_keys` / `workflow_refs`。该请求不提供 `max_steps` 字段，也不允许调用方控制本次后台 turn。后台 worker 的 agent turn budget 来自 `OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT`，debug/manual `/runtime/drain` 的 turn budget 则来自 `max_steps_per_agent`。

`POST /v3/approvals/{approval_id}/resolve` 是普通用户/Web UI 改变 approval 状态的唯一入口。approval resolve 后只写入 approval resolution 与对应恢复状态，随后按 approval kind 分流：agent-level approval 可以排队相关 agent wakeup signal，由 scheduler claim 后恢复 agent turn；S10 SDK controlled-operation approval 必须先恢复 Host-owned blocked SDK RPC / sandbox continuation，`sandbox.exec` tool result 返回后 agent loop 才继续。配置化 Host 默认由 FastAPI lifespan 中的 background runtime worker 自动推进 agent wakeup；SDK continuation 由 Host supervisor continuation worker 推进。`/runtime/drain` 只保留为 worker 禁用、测试 scheduler claim lease 或 operator recovery 时的手动入口。在 resolve 前，任何 `execution.resume` / SDK resume 机制都不能被当成批准入口，也不应暴露为用户或 agent 必须手工编排的主流程。

AOX blank-world campaign 的 `chrome-once` 是该公共合同的一次可封存观察模式，不是第二条 approval API。它只在 positive 1 的首个 formal gate 启动 same-process loopback Host 并提供 digest-pinned Web UI dist；campaign driver 不调用 resolve endpoint，只有浏览器中的认证用户动作可以解决该 approval。driver 在触发可能生成 handoff 的 runtime drain 之前记录 durable event cursor，随后从该 cursor 重建 `approval.resolved` 与 controlled-operation continuation，因此即时浏览器批准也不会与事后 snapshot 竞争。浏览器 approval timeout 从 handoff 独立计时，但始终受 attempt 总 deadline 的上界约束。driver 只读观察有序 durable events，并要求 approval id、operation id/digest、sandbox run/workspace 与 continuation identity 都指向同一 terminal operation。`aox_browser_approval_receipt@2` 封存 pre/post workspace semantic preimage、public response binding、完整 resolution/continuation durable-event record、same-process Host/UI identity 和 `driver_resolve_route_absent=true`；ordered public API receipt 使用包含 `response_semantic_digest` 的 exact 七字段闭集。approval 与 terminal handoff 动态身份完整：它们发出 sealed logical page URL、Host process id、served UI dist digest 和 observation schema id；完整 23 字段 builder 合同仍由稳定 guide/code 定义。formal terminal 后 Host 强制保持 completion window。trusted operator 必须使 final target 在 hold 内不存在，并在 not-before 后按 sibling-temp/fsync/atomic-rename 协议发布；当前 Host 只验证 bounded polls 中未观察到提前 target、final mtime 不早于 hold 结束，且 non-symlink regular file 经两次 stat/read 稳定，不声称证明轮询间的连续缺失或 atomic/fsync provenance。窗口结束后才开始由 effective config 固定的独立 submission timeout。`aox_browser_observation_receipt@2` 绑定 clean console、terminal page state、DevTools transcript、完整可解码 PNG 和 Host acceptance timing。最后一次 workspace GET 与 `after_cursor=0,replay=true` 全事件 GET 只作为 bundle-level semantic preimage 封存，不回写产品 repository。`auto` mode、Host poll 观察到提前 receipt 或重开替代 operation 都不满足 Chrome cutover proof。

`POST /v3/sessions/{session_id}/runtime/drain` 是 debug / operator / manual scheduler command。Session B background worker 启用后，它只用于本地诊断、测试 scheduler claim lease、或 worker 禁用时的有界推进入口。请求字段：

- `max_signals: int = 3`
- `max_steps_per_agent: int = 8`
- `auto_enqueue_ready_tasks: bool = false`

该 endpoint 返回 `V3CommandResult` shape。它内部必须先 acquire session-level runtime lease，再通过 scheduler claim signal 语义认领 work，而不是直接顺序调用 `wake_agent()`、`run_agent_harness_loop()` 或任何 service-level master response helper。它可以 claim `agent:master` 与 teammate signals，但不能绕过统一 scheduler runtime 入口。`auto_enqueue_ready_tasks` 是显式 scheduler option，默认关闭；只有 operator/debug/recovery 调用明确传入 `true` 时才扫描 ready unassigned tasks 并创建 `TASK_AVAILABLE` wakeup。

若同一 session 已有未过期 background/manual/recovery lease，`/runtime/drain` 不得并发推进。service 层必须给出可测试的结构化结果，例如 `status="locked"` 并包含当前 `owner_id`、`mode`、`expires_at`、`fencing_token` 与 `retry_after_seconds`；HTTP endpoint 可以继续返回 command result，也可以映射为 409，但不能静默等待或绕过 ownership。

面向 harness tools、CLI/ops、测试与迁移调试的 control-plane secondary endpoints：

- `POST /v3/tasks`
- `PATCH /v3/tasks/{task_id}`
- `POST /v3/lanes`
- `POST /v3/lanes/{lane_id}/claim`
- `POST /v3/lanes/{lane_id}/keep`
- `POST /v3/lanes/{lane_id}/remove`

task secondary endpoints 是非出口 CRUD：`POST /v3/tasks` 和 `PATCH /v3/tasks/{task_id}` 必须拒绝把 status 设为 `blocked` / `completed` / `failed` / `cancelled`。已经 blocked 的 task 在请求不携带 status 时仍可修正描述等 metadata；completed / failed / cancelled task edit fail closed。除已文档化 approval block 机械迁移外，业务出口只有 agent-facing `task.finish` command；它只能改变 status / updated_at / failure fields，并在同一 UoW 原子写入 finish document、task row 与 durable event，commit 后 SSE 才可见。已经处于任一 business-exit status 的 task 必须先显式 resume/reopen，不能直接再次 finish。operator 若未来需要 reopen/repair，必须设计独立、可审计的 command，不能把 generic PATCH 或 repository save 当作隐藏后门。task dependency mutation 还必须保持 same-session DAG；service cycle error 与 SQLite INSERT / UPDATE triggers 是同一 contract 的两层防线。

所有 `/v3` mutation endpoint 接受 `Idempotency-Key` header。`local-dev` profile 可省略；提供时，Host 以 command type、resource scope 与 canonical request JSON 计算 digest：相同 key/digest 返回首次完成响应且不重复写入，key 相同但 digest 不同返回 `409`。`shared` profile 强制该 header，缺失返回 `428`。`POST /v3/sessions/{session_id}/messages` 只做本地 conversation admission 与 signal enqueue，因此使用短 write UoW；真正 provider work 只在显式 runtime drain 中发生。

### Deployment profile、认证与授权

Host 只有两个显式 profile：

- `local-dev`：只能 bind loopback；请求映射为固定 `user:local-dev` principal，适合单人本机开发；debug 仍默认关闭。
- `shared`：可对外 bind，但启动时必须提供 principal 配置。所有 `/v3` 与已启用的 `/debug` 请求使用 Bearer 认证；token 进入 settings 前即转为 SHA-256 digest，不能出现在 settings repr、event、projection 或 debug record。

共享部署的 principal 声明 `roles` 与允许访问的 `project_ids`。创建 session 时，Host 在同一 write UoW 中持久化唯一 owner `SessionAccessRecord`；project claim 不是 session 可见性的替代品，同 project 的其他 principal 默认也不能 list/read/mutate 该 session。admin 可在其获准 project 内做全局访问；operator 仍需 session access，且 `POST /runtime/drain` 只允许 operator/admin。不可见资源统一按 `404` 处理，避免通过 ID 探测存在性。

approval resolve 的 `actor_ref` 只能来自已认证 principal；请求体提交该字段会被拒绝，canonical `approval.resolved` event 同时记录服务端 actor。lane claim 同样使用认证 principal，不信任调用方提交的 claimed identity。

`/debug/*` 默认返回 `404`。显式启用后，shared profile 只允许 operator/admin，且 LLM request/response/error 在入 recorder 时已经做 secret、Bearer、credentialed URL、Host path 与长度脱敏。debug 页面与 endpoint 使用相同 gate，不存在只保护 JSON 而遗漏静态 debug UI 的旁路。

默认内部 tool surface 还应包括最小 report draft 操作：

- `report_draft.get`
- `report_draft.update`
- `report.publish`

默认 executor sandbox tool surface 还应包括：

- `sandbox.workspace.status`
- `sandbox.file.list`
- `sandbox.file.read`
- `sandbox.file.write`
- `sandbox.file.patch`
- `sandbox.file.delete`
- `sandbox.exec`
- `artifacts.materialize`
- `artifacts.register`
- `artifacts.snapshot_code`

这些工具面向 executor 的 persistent sandbox working copy。它们允许 executor 在隔离容器中读写文件、运行 bash/Python、把 catalog artifact 显式搬入 sandbox、登记输出 artifact，并在 dry-run / execution 前把源码快照固化为 `ArtifactKind.CODE`。它们不得暴露 Host repo path、Host artifact path、sandbox host path、runner private path、`storage_uri`、SSH/Slurm config 或 credentials。

默认 master 内部 team coordination tool surface 还应包括：

- `protocol.thread`
- `protocol.send`

这些是 agent team 内部协调工具，不新增 REST endpoint，也不要求 Web UI 直接暴露操作入口。master 可用它们读取 delegation correlation thread，并在 teammate 失败或摘要不足时选择发送 follow-up、更新 task、请求用户澄清或汇报结果。`protocol.send` 只投递 message 并排队 wakeup signal，不同步运行 recipient；recipient turn 由 scheduler claim signal 后启动。配置化 Host 默认由 background runtime worker 推进 claim，debug/manual 场景也只能通过同一 scheduler claim path 推进。workspace projection 继续通过 `delegation`、`agent_traces` 与 `activity_feed` 展示用户可理解的 agent team 状态和 thread 进展，raw wakeup / unread / signal counters 默认只属于 debug 视图。

`task.delegate(task_id, agent_role, agent_ref?, instructions?, correlation_id?, workflow_refs?)` 的 `workflow_refs` 是 opt-in binding。它只能选择当前 step 已授权 workflow refs 的子集；省略或空数组都表示不绑定，不能隐式继承 master 的全部 focus。role/tool/engine requirement 与 manifest digest 在 task claim 前校验，失败不产生 teammate、assignment、delegation message 或 wakeup。成功委派把 exact refs 和 resolved manifest snapshot 持久化在 `delegation_request` document；cutover collector 可以据此证明某个 binding 确实到达指定 teammate，而不是只出现在 entry prompt。该参数是 agent 选择工作知识的结构化边界，不是 harness 自动匹配领域关键词或固定编排步骤的入口。

默认内部只读文档工具还应包括：

- `docs.search`
- `docs.read`

`docs.search(query, tags?, limit?)` 返回受控文档库的匹配条目，条目至少包含 `doc_id`、`title`、`summary`、`tags`、`version` 和 `path`；`docs.read(doc_id | path)` 只读取 registry 中登记的文档，不能读取任意 repo 文件，返回同样 metadata 加 `content`。首批必须索引 `docs/v3/execution-pipeline-docs/`，供 execution teammate 按需学习 pipeline SDK。该工具是通用 V3 内部能力，后续 research/reporting 文档也可接入同一接口。

旧式 `skill.list` / `skill.load` 可以作为迁移期兼容机制存在，但不再是 V3 execution pipeline / sandbox SDK / backend adapter 用法说明的主路径。executor 应优先使用 `docs.search` / `docs.read`。

默认 agent-facing 世界读取工具还应包括：

- `world.inspect`

`world.inspect(sections?, task_id?, agent_id?, limit?)` 返回当前 session 的结构化事实快照，面向 master 和 teammate。它可以包含 session focus、task board、assigned/delegated task、agent roster、inbox、runtime signals、artifact catalog 安全投影、capability invocation、controlled operation、pending approval、capability outcome、runtime consistency warning、模型当前可见 tool schema、route policy、approval requirement 与输入约束。teammate 的 `capabilities` 查询默认绑定当前 task，显式 mismatch 返回 typed error；master 保留既有可选 `task_id` / session-wide 权限。facts page newest-first，最多返回 20 个 invocation、每类最多 8 个 closed opaque refs，serialized facts 最大 64 KiB；每项只含 invocation identity/status/time/`output_ref`、安全 refs 和 document/artifact/evidence/source/gap counts，禁止内联 UI rich documents、output payload 或 evidence 正文。当前 hard cap 仅封闭公开投影；窄列 repository query、lazy section read 与 cursor 另见 `architecture-proposals/bounded-capability-facts-query.md`，尚未实施。

该工具只表达 facts / constraints / affordance metadata，不输出 `recommended_actions`，不固定 “RCSB 后必须 fpocket” 或 “所有任务必须 report” 之类 workflow，不替 agent 判断 task 是否完成。terminal capability outcome 只表示 evidence ready；业务 task terminal 仍由 agent 通过 `task.finish` 写入。

`artifacts.register` 的 normal FASTA contract仍要求真实记录。显式
`validation_profile="fasta_zero_records@1"` 只接受 `kind=sequence`、FASTA
format、exact zero bytes、stable `empty_result_reason` 与 versioned
`derivation_contract_id`；任何非零 sentinel 都失败。该 profile只验证
artifact byte shape，不赋予 healthy-empty 科学语义，后者仍由 workflow collector
和 offline verifier从 sealed upstream artifacts重算。cutover collector 还封存
`openzyme_typed_empty_artifact_validation@1` receipt；offline verifier从 receipt
重建 catalog validation payload/digest，并拒绝 zero-byte sequence 的 missing/drift。

### Internal Tool Result Envelope

V3 internal tools must return an LLM-readable envelope. The Python `ToolResult.content` field remains available for compatibility, but tool messages fed back into master/teammate models are serialized as JSON with at least:

- `ok`: whether the tool's core semantic action completed
- `status`: machine-readable outcome such as `delivered`, `wakeup_queued`, `recipient_not_found`, `wakeup_not_created`, `sync_execution_not_supported`
- `summary`: short human-readable outcome
- `error_code`: stable failure code, or `null`
- `hint`: actionable next step, or `null`
- `details`: structured diagnostic metadata
- `content`: legacy content string
- `payload`: parsed JSON payload when `content` is JSON
- `terminal_action`: explicit terminal action name such as `task.finish`, or `null`
- `terminates_turn`: whether the harness must stop the current master/teammate loop immediately after this result

`ok=true` must not mean "no downstream work remains"; it only means that the specific tool completed its promised action. `ok=false` means the model must not assume the requested action happened.

`terminates_turn=true` 只允许由显式 terminal tool 设置。当前推荐出口是 `task.finish`；普通 tool success、capability success、engine invocation terminal state 或 protocol message 都不能自动设置该标记，也不能自动把业务 task 写为 completed / failed。

当工具本身已经执行完成，但完整 result 或下一轮 prompt 会超过 token budget 时，harness 返回 context-budget observation，而不是把完整 result 塞回模型：

- 外层 `ok=false`
- `status="tool_result_context_over_budget"`
- `error_code="tool_result_context_over_budget"`
- `details.original_tool_ok` / payload `original_tool_ok` 记录原始工具语义是否成功
- `original_status` 记录原始工具 status
- `artifact_id` 指向完整结果保存的 `ArtifactKind.RESULT`
- `read_hint` 指示使用 `artifact.get` 分页读取

这个 envelope 不表示原始工具业务失败；它只表示 observation 被降载。agent 必须先读取 `original_tool_ok` / `original_status`，再按需要通过 artifact 工具恢复完整 payload。

默认 research direct-tool surface 还应允许 provider-specific 轻量动作：

- `pubmed.search`
- `semantic_scholar.search`
- `uniprot.lookup`
- `uniprot.download_fasta`
- `rcsb_pdb.search`
- `rcsb_pdb.download_structure`
- `interpro.query`

这些 direct provider tools 的返回内容应统一为 `ResearchObservation` JSON，而不是暴露各 provider 的原始 response shape。

其中 `pubmed.search` 为 AOX/HMM required literature provider；`semantic_scholar.search` 与配置后出现的 `web.search/web.fetch` 为 enrichment。provider envelope 的 outcome 保留 `completed/empty/degraded/failed`，enrichment degradation 使用 `ok=true + ResearchObservation.status=partial` 告知 agent“主路径可继续但必须披露缺口”；required PubMed failure、empty、fixture 或 schema-invalid citation 都使用 `ok=false + ResearchObservation.status=failed`，同时封存原始 typed outcome 与 call-local quorum，不能把“网络调用正常结束”误写成“科学证据可用”。任何路径都不得为获得非空 findings 生成 fixture/synthetic hit。

在 executor sandbox SDK 中，`rcsb_pdb.download_structure` 不是 direct control-socket tool，而是 `rcsb_pdb.download_structure.provider:v1` 受控 provider operation：sandbox 提交 typed params，Host supervisor 负责真实 RCSB 下载、输出校验、artifact boundary 登记和 `content_digest` / `sealed_digest` / provenance manifest 返回。

最低语义：

- search / lookup 返回 `summary + findings + sources + unresolved_gaps`
- download 返回 `summary + artifacts`，并在可能时附带来源 `findings / sources`
- `sources` 是 evidence 的引用来源，不是 workspace artifact
- 只有真实下载或生成的文件资产才进入 `artifacts`
- provider direct download 产物进入 control plane 时默认是 sealed artifact：artifact metadata 必须记录基于实际 bytes 的 SHA-256 `content_digest` / `sealed_digest`、`provider`、`external_id`、`source_locator`、`format`、`retrieved_at` 和结构化 `provenance`；后续 `hpc.stage_artifact` 只消费这些 catalog digest 与 session 授权，不负责判断 PDB/FASTA 是否满足某个 execution tool 的输入质量
- raw provider payload 默认不进入长期 LLM restore context；需要调试时使用 `raw_ref` 或 engine document 追踪
- direct provider invocation 在网络 I/O 前可见为 `RUNNING`，随后在每个 outcome 变为 terminal；同一 call 不得因 retry、degradation 或 sealing 恢复创建替代 invocation
- literature evidence artifact 使用 `provider_literature_evidence@1`（Tavily 使用对应 safe web evidence schema），只封存 citation/source metadata、typed failure、attempt/provenance、call-local quorum 与 digest；artifact 必须写入当前 session/attempt 注入的 sealed Blob root，而不是指向 mutable `/tmp` 下载文件或共享进程级默认目录
- PubMed provenance 使用不可逆 `identity_digest` 绑定实际 NCBI tool、email 与可选 API-key identity；raw email、API key 和带 credential 的请求 URL 不进入 engine document、artifact payload 或 public projection

说明：

- `POST /v3/sessions/{session_id}/messages` 是默认的 user command ingress；它持久化用户消息并排队 `agent:master` wakeup，不直接执行 master loop，也不隐式执行 bounded teammate runtime drain
- 当 `model_factory` 可用时，scheduler claim `agent:master` signal 后默认走真实 top-level LLM harness driver；配置化 Host 默认由 background runtime worker 自动触发，`/runtime/drain` 只用于 debug/manual 场景
- Web UI 默认不要求用户手动创建或编排 task / lane；这些对象主要由 master agent 在 loop 中创建和编排，再通过 workspace projection 展示
- task / lane endpoints 可以存在，但不得反向主导产品交互，把 V3 退化成手工 workflow 管理后台；task create/update endpoint 是 control-plane mutation，不应隐式 drain agent runtime
- V3 初期不要求单独暴露 `agents` REST 资源，但 workspace projection 必须能显示 teammate / delegation / protocol 的用户可理解状态；低层 wakeup queues 和 signal counters 默认留在 debug/event 面
- 默认主路径是 `conversation -> agent:master wakeup -> scheduler starts master -> master planning -> task -> resident teammate wakeup -> scheduler starts teammate -> teammate work surface -> master wakeup -> user feedback`，而不是用户消息直接裸触发 capability

## 3. Workspace Contract

`GET /v3/sessions/{id}/workspace` 返回统一 snapshot。

术语边界：

- `workspace projection` / `session workspace` 指本 endpoint 返回的 session 级产品读模型，包含 conversation、task board、lane board、approval、delegation、artifacts、reports 与 capability projections。
- `sandbox workspace` 指 executor 在受控 sandbox 内持久化、可恢复的 `/workspace` working copy；它是隔离执行壳内的文件工作面，不是 session workspace，也不是 artifact catalog。
- executor sandbox 工作区的稳定身份字段写作 `sandbox_workspace_id`；裸 `workspace_id` 不应在新的 execution / provenance contract 中指代 sandbox working copy。

最低字段分区：

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
- `runtime_state`

说明：

- `conversation` 来源于持久化的 user / assistant message content，是用户与 master agent 的 canonical read model
- `conversation` 只承载产品级对话记录；带 `tool_calls` 的 LLM response content 即使包含自然语言，也不写入 `conversation`
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline，而不是依赖浏览器本地消息历史
- `agent_traces` 来源于 canonical session storage 的 `engine_documents(document_kind="llm_trace_step")`，不是 `/debug/llm-calls`。它按 `actor_ref` 分组，`harness` 表示 master agent，teammate 使用对应 canonical `agent_id`，并通过 display_name/role 辅助展示
- `agent_traces` 使用稳定 public projection helper / allowlist 生成；每个 trace entry 只允许暴露 `trace_id`、`actor_ref`、`actor_kind`、`display_name`、`role`、`call_index`、`created_at`、`response_text`、`tool_calls`、`step_id`、`tool_catalog_digest`、`restore_context_digest`、`projection_schema_version` 与已清洗的 `agent_step`
- `agent_step` 只允许 `step_id`、`session_id`、`agent_id`、`actor_kind`、`role`、`call_index`、`task_id`、`lane_id`、`correlation_id`、`signal_id`、`wakeup_reason`、`restore_context_digest`、`tool_catalog_digest`、`created_at`
- `agent_traces` 是过程级可观测性 read model；每次 master / teammate LLM response 后都应生成 trace entry，供 Web UI 展示中间 response text 与工具调用请求
- `tool_calls[]` 只展示 LLM 请求调用工具的公开投影：`call_id`、canonical dotted `tool_name`、`task_id`、`lane_id`、`args_public`。本读模型不展示 tool result；provider-safe alias 只允许出现在 LLM debug request 中，不进入 workspace trace
- `args_public` 必须清洗 secret/token/password/credential、Host path、storage URI、SSH/runner config、pipeline/source code 与超长字段；保留工具名、任务/车道关联、公开 instructions 和结构化意图
- `agent_traces` 不暴露 restore context、memory summary、完整 tool schema、prompt / `initial_prompt`、Host path、storage URI、runner path、SSH/runner config、provider secret 或 tool result content
- `capabilities` 是可扩展分区，按 `capability_key` 挂载各 engine 的投影
- 不应把当前 engine 名称直接固化为 workspace 顶层 contract，避免后续每新增一种能力都破坏接口
- `runtime_state` 是 diagnostic-only projection：区分 `agent_turn_failed`、`runtime_signal_failed`、`task_failed`、`runtime_attention` 与 `outcome_unconsumed` / `capability_outcome_ready`，但不自动改变 task business status。terminal capability outcome 只表示可作为证据的结果已经 ready，并可用于 wake owner；它不代表 teammate、master 或 task 已完成
- `task_board`、`delegation`、`lane_board` 共同表达内部执行状态；它们不是 conversation 的附属调试信息，而是与 conversation 并列的 control-plane 读模型
- `delegation.agents` 默认表达 resident team roster：agent identity、role、status、task/lane focus、correlation thread 与 last active time。默认用户 projection 不暴露 unread inbox count、pending signal count 或 raw wakeup reason；这些属于 diagnostic-only 信息
- `artifacts` 默认是 session 共享工作面的安全投影，供 UI 呈现，也供后续 agent loops 作为可读取 catalog 理解当前工作面；普通投影不直接返回文件内容或 Host 私有路径
- `artifacts[].relative_path` 是 artifact browser 的 workspace-facing path；Web UI 默认按 `/` 分隔构造目录树，重复 path 仍保留为多个以 `artifact_id` 区分的文件叶子
- `artifacts[].provenance` 是 projection-derived 展示对象，不是新的 canonical DB 字段。稳定输出字段为 `task_id`、`lane_id`、`invocation_id`、`run_id`、`produced_by`、`source`、`format`、`provider`、`external_id`、`source_locator`、`source_artifact_ids`、`input_artifact_ids`、`preprocess_artifact_ids`、`runner_run_id`、`pipeline_invocation_id`、`code_digest` 与 `tool_contract`
- `ArtifactKind.CODE` 表示 agent-authored pipeline source 的 canonical 审计快照。兼容 catalog 单文件源码版本使用 `metadata.format="python"`、`metadata.semantic_type="pipeline_source"`、`content_digest`、`lineage_root_artifact_id`、`version` 与 `parent_artifact_id`；sandbox source tree snapshot 使用 `metadata.format="source_tree"`、`metadata.semantic_type="pipeline_source_snapshot"`，并记录 `sandbox_workspace_id`、`entrypoint`、`source_tree_digest`、file digest manifest 与 parent snapshot
- 普通 artifact browser 只展示 metadata/provenance 摘要；内容读取和源码版本化由受控 agent tools 提供，不通过 workspace projection 直接返回文件内容，也不提供 delete/rename/move/edit 语义
- `artifact.list` 返回当前 session 内的安全 artifact catalog，可按 task / invocation / kind 过滤，并默认分页返回 `{artifacts,total_count,offset,limit,next_offset}`，避免 artifact 数量增长后撑爆上下文
- `artifact.get` 返回单个 artifact 的安全 catalog record 及关联 invocation / output document 摘要；大字段通过 `path`、`offset`、`limit` 分页读取
- `tool_result_full` result artifact 默认只返回 `tool_name`、`call_id`、`original_tool_ok`、`original_status`、`tool_result_summary` 和 omitted field hint；完整结果通过 `path="output_payload.tool_result"` 分页读取
- `artifact.preview`、`artifact.read_text`、`artifact.range` 只读取 UTF-8 文本类 artifact，适合 FASTA、PDB、log、JSON、Markdown 等；二进制或不可读内容返回结构化 tool error
- `artifact.create_text` 创建不可变 Python pipeline source artifact，并写入 SHA-256 `content_digest` 与 version 1 lineage metadata；只接受安全 `.py` basename，不接受 Host path 或目录路径。它是兼容/直接 catalog 编辑面，不是 executor 在 persistent sandbox 中日常 authoring 的主路径
- `artifact.patch_text` 基于 `base_artifact_id + base_content_digest + content` 创建新的不可变源码版本；digest 不匹配、非 code artifact、非法文件名、非 UTF-8 或超限内容必须返回结构化 tool error，不得覆盖旧 artifact。它保留为受控源码版本工具，不替代 sandbox file CRUD
- `artifact.diff_text` 返回两个 Python pipeline source artifact/version 之间的 bounded unified diff，结果只包含安全 artifact 投影和 digest
- `artifacts.materialize` 通过 catalog 授权把 artifact 显式复制或映射到 executor sandbox；返回 sandbox-safe path，不返回 Host `storage_uri`；Host 必须验证 catalog 声明 digest、实际 sealed Blob、复制后 target 三者一致，并在复制后复核 source 未漂移；同一 artifact digest、target path 和 mode 幂等复用，目标或 Blob digest 冲突结构化失败，`target` 必须位于 `/workspace/input`
- `artifacts.register` 只登记 `/workspace/output` 下的 sandbox output 或 Host-supervised fetched output；Host 在创建 visible Artifact row 前必须完成 validator、copy/seal、sealed digest recheck 和 provenance 完整性检查；同一路径不同 digest 创建不同 `artifact_id`，不覆盖旧 artifact
- `artifacts.snapshot_code` 把 sandbox `/workspace/src` 中的 pipeline source 固化为 `ArtifactKind.CODE`；execution plan、approval、run 与 output provenance 必须引用这个快照，而不是引用可漂移的 working copy；source tree digest canonicalization 必须稳定
- `sandbox.exec` 在同一 `sandbox_workspace_id` 下默认单活执行；active run 期间第二个 exec 和 agent-facing write/patch/delete 返回 conflict，read/list 可并发
- `hpc.workspace(label)` 按 `sandbox_workspace_id + normalized_label` 复用 logical remote placement workspace；`stage_artifact` / `fetch_outputs` 只返回 opaque refs、artifact refs 和 bounded summary，不返回真实远端路径
- artifact tool results、workspace projection、events 与 capability projection 都不得返回 Host repo path、Host artifact path、sandbox host path、runner private path、`storage_uri`、`source_storage_uri` 或 `intermediate_storage_uri`
- `report_drafts` 默认表达 report teammate 的中间交付面；它不是一次 capability invocation 的临时输出
- research 过程中下载的 sequence / structure 默认也进入 `artifacts` 共享投影，而不是只停留在 lane 私有目录
- 这类 research artifact 默认按外部下载 sealed：至少应带 provider、external id、format、source locator、retrieved_at、SHA-256 content/sealed digest、task linkage 与 provenance / evidence linkage；execution-ready 语义由后续 capability tool 校验，不与 sealed 状态混用
- execution 输入 artifact 必须通过 compiler 映射为 runner staging input；public workspace/read model 和普通 artifact browser 不暴露 Host repo path、sandbox host path、`storage_uri`、runner credentials、SSH/Slurm config
- execution 输出 artifact 必须来自 runner declared `expected_outputs` 的下载结果，并保留 output relative path
- `capabilities.deep_research[]` 默认承载每个 research invocation 的 `canonical_summary`、`evidence`、`source_refs`、`gaps` 与 output document 投影
- `capabilities.execution[]` 默认承载每个 execution pipeline invocation 的 `pipeline_invocation_id`、`code_digest`、`sandbox_status`、`hpc_run_ids`、`tool_contract`、`input_artifact_ids`、`preprocess_artifact_ids`、`output_artifact_ids` 与 terminal summary
- execution pipeline 的 public read model 不暴露 Host repo path、sandbox host path、`storage_uri`、pipeline source code、SSH/Slurm config 或 runner credentials
- direct provider search 产出的 normalized findings 后续也应能进入同一 canonical research evidence / source ref 读模型；不应只作为一次性 tool message 存在
- paper source ref 的稳定 bibliographic/provenance 字段包括 provider、external id、PMID、provider-supplied DOI、authors、venue、publication date、retrieved_at、request/response digest、safe provider provenance 和 evidence artifact id；缺 DOI 时保留空值，禁止推断
- workspace/capability projection 对 source ref 和 provider artifact 二次执行 safe projection；不返回 credential、private URL/query/header、unlicensed全文、`storage_uri` 或 Host/runner path
- `source_refs` 与 `artifacts` 是并列的 canonical workspace 信息：前者回答“证据来自哪里”，后者回答“哪些文件资产可被后续 agent / UI 读取”

## 4. CLI 语义

V3 CLI 不再围绕 `episode phase` 渲染。

默认能力：

- 查看 session workspace
- 查看 task board，并在高级/ops 场景下更新 task board
- 处理 approvals
- 观察 lane 状态
- 发起消息 / 继续 agent loop
- 通过 `openzyme runtime health` 查看脱敏 runtime readiness

CLI 可以保留 task / lane mutation 命令，作为自动化、调试、迁移和 operator 用途；这不代表 Web UI 的默认用户需要手动维护这些对象。

## 5. Web UI 语义

V3 Web UI 默认是 conversation-first。

主交互：

- 用户发送自然语言消息
- top-level master agent loop 决定如何创建和编排 task
- 具体 research / execution / reporting task 默认由 master 显式委托给 resident teammate agent 推进；auto-claim 仅用于显式 operator/debug/recovery 场景
- `research teammate` 围绕 task 读取共享 workspace / artifacts、按需绑定 lane、调用 `deep_research` 或直接调用 provider-specific research tools、请求 approval，并可通过 protocol 与 peers 沟通
- `execution teammate` 围绕 task 读取共享 workspace / artifacts、按需绑定 lane、在自己的 persistent sandbox 中编辑和运行 pipeline，并可通过 protocol 与 peers 沟通；具体 HPC / 长耗时 / 高 quota SDK operation 是否需要 approval 由 Host supervisor 的 tool policy 决定，teammate 不需要判断敏感性
- execution teammate 不直接调用 HPC runner tool，也不把 `execution.pipeline.start` 当作必须调用的 authoring 主路径；它通过 sandbox file/command tools 与 sandbox SDK 表达执行意图，由 Host supervisor 间接访问 runner
- execution teammate 默认拥有 `docs.search` / `docs.read`，并应按需检索 `persistent sandbox`、`sandbox file command`、`artifact materialize register snapshot_code`、`preprocess`、`tool adapter`、`hpc placement`、`stage_artifact`、`fetch_outputs`、`batch ligand docking`、`sandbox rules` 与 `dry-run` 文档；`hpc` 是稳定 executor-facing placement namespace，领域工具通过 `structure_tools` / `docking` / `bio_tools` 表达，公开 SDK / docs / prompt 不暴露旧 runner-backed shorthand
- report teammate 默认直接读写 `report_draft` 并在合适时机 `publish` 为 final `report`
- approval 以对话流中的卡片形式出现，用户只需要 approve / reject
- task、lane、engine、artifact、report 变化通过 workspace projection 和 control-plane events 回填
- teammate idle 不代表任务失败；它表示当前没有可立即执行的 work turn，后续 inbox、approval、engine completion 或 task availability 可再次唤醒

`research teammate` 的默认决策边界：

- 简单 literature query、accession / structure id 定位、确定性 sequence / structure 下载、轻量 annotation 查询，可直接调用 provider tools
- 开放式 research、跨来源检索、query decomposition、evidence fusion、gap detection、clarification，优先调用 `deep_research`
- `deep_research` 是 teammate 的重能力工具，不等于 teammate 自身

默认展示：

- 对话 timeline：用户消息来自 `workspace.conversation`，master LLM 文本与工具调用请求来自 `workspace.agent_traces.harness`；旧 workspace 没有 trace 时回退展示 `conversation.assistant_message`
- approval cards
- tool / engine / report / artifact activity cards
- task board、lane/workspace 状态、delegation、artifacts / runs / reports 的只读 inspector
- teammate roster 中的 working / idle / blocked / waiting approval / failed / shutdown 状态
- sidebar 中的公开 runtime health 与 deployment profile；health 失败不能抹掉已可读取的 session 列表
- 当前 active session 的 `Team` 节点下展示 teammate 名字；点击 teammate 后，中间区域切换为该 teammate 的只读执行轨迹，并隐藏消息 composer。用户输入仍只能进入 master conversation 的 `POST /v3/sessions/{session_id}/messages`

Web UI 可以同时展示 conversation 与 approval card；后端在 `waiting_approval` 响应中不得把普通 assistant message 当作最终完成消息写入 conversation。

不要求用户理解：

- 哪个 graph 节点正在运行
- 哪个 subgraph 持有当前局部状态
- 如何手动创建 task / lane 才能推进工作

同时也不应要求用户理解：

- 具体哪个 teammate 在什么时刻被 spawn
- teammate runtime 如何调度 wakeup signal
- 为什么某个 capability 缺少 `task_id`
- 内部 team protocol / lane / engine / artifact catalog 是如何串起来的

## 6. Streaming

V3 streaming 默认围绕 control-plane events，而不是围绕 graph implementation 细节。

`GET /v3/sessions/{session_id}/events` 从 SQLite durable event log 读取。每个 SSE frame 必须包含整数 `id: <cursor>`；首次 replay 可传 `after_cursor`，自动重连使用标准 `Last-Event-ID`。二者同时提供返回 `400`，负数或非整数 cursor fail closed。Host 在接受请求时固定全局 durable high-watermark；`replay=true` 必须按最多 1000 条一页完整重放到该 watermark，不能把单页上限误当成 replay 上限。`replay=false` 直接把 follow 起点锚定到请求时 watermark，既不回放请求前 backlog，也不能退回进程内 list index。public endpoint 只查询 `visibility=public` rows；private/audit event 占用的 cursor gap只推进全局水位，绝不投影其 payload。完成 snapshot replay 后，follow 只发送 watermark 之后的新 public events。Host restart 后 replay 必须返回相同 event id/cursor。

浏览器等不应维护 event type allowlist 的调用方使用 `envelope=1`，此时所有 frame 的 SSE event name 固定为 `openzyme.event`，真实 `event_type` 保留在 JSON data envelope 中。默认模式继续以真实 `event_type` 作为 SSE event name，供已有调用方迁移；两种模式的数据 envelope、cursor、replay 和可见性语义完全相同。新增 durable event type 不得因为前端没有预先注册监听器而静默丢失。

推送单位：

- `conversation.user_message`
- `conversation.assistant_message`
- `llm.response.created`
- `tool.invoked`
- `tool.completed`
- `task.updated`
- `approval.requested` / `approval.resolved`
- `lane.created` / `lane.bound` / `lane.removed`
- `agent.spawned` / `agent.delegated` / `agent.woken` / `agent.idle` / `agent.task_claimed`
- `signal.queued` / `signal.claimed` / `signal.completed` / `signal.failed`
- `agent.message.delivered` / `agent.inbox_unread`
- `agent.shutdown_requested` / `agent.shutdown_completed`
- `engine.invocation.started` / `engine.invocation.updated` / `engine.invocation.completed`
- `research.evidence.recorded`
- `artifact.recorded`
- `execution.pipeline.started`
- `execution.pipeline.step.completed`
- `execution.pipeline.completed`
- `execution.pipeline.failed`
- `execution.preprocess.completed`
- `execution.artifacts.fetched`
- `report_draft.updated`
- `report.generated`
- `runtime.session_locked`
- `runtime.lease_heartbeat_failed`
- `runtime.lease_lost`
- `runtime.fencing_rejected`
- `runtime.consistency.warning`
- `runtime.state_attention`

这些事件默认服务于“用户与 master agent 的单一对话体验”，而不是把 V3 暴露成多线程运维控制台。

`llm.response.created` 是 response-step 级 streaming event。Host API 应在每次 master / teammate LLM response 与 `llm_trace_step` 持久化后尽快 append 该事件，而不是等整个 `POST /v3/sessions/{session_id}/messages` command 完成后批量发送。该事件 payload 必须与 `workspace.agent_traces` 使用同一 public projection helper / allowlist；`trace_id` 在 session durable log 内唯一，重复 identity 只有内容完全一致时才可幂等复用，冲突内容 fail closed。Web UI 用 event `cursor` / `event_id` 与 trace `trace_id` 去重；最终面向用户的 `conversation.assistant_message` 仍可在 command 完成或明确产出用户回复时发送。

`tool.invoked` 与 `tool.completed` 是 diagnostic/runtime events，不新增 Codex thread / turn 顶层产品状态。二者 payload 至少包含 `call_id`、canonical dotted `tool_name`、`task_id`、`lane_id`，并附加公开 actor / step / runtime metadata：`agent_id`、`actor_kind`、`role`、`call_index`、`step_id`、`tool_catalog_digest`、`restore_context_digest`、`side_effect`、`supports_parallel`。`tool.completed` 还包含 `ok`、`status` 与 `error_code`。这些 payload 不得包含 provider alias、完整 prompt、完整 tool schema、tool result content、artifact `storage_uri`、Host path、runner path、sandbox host path、SSH/runner config 或 provider secret。Web UI 可以把这些事件记录到 `activity_feed`，但它们不创建新的 workspace 顶层 turn / thread 状态。

迁移兼容 `execution.pipeline.start` 语义：

`execution.pipeline.start` 不再是 executor-facing authoring 主路径。稳定目标是 executor 在 persistent sandbox workspace 中通过 `sandbox.file.*` / `sandbox.exec` 工作，Host/supervisor 在内部创建 execution plan、approval、run 和 provenance。若当前实现或迁移期仍暴露 `execution.pipeline.start`，其语义必须满足：

- 默认入口绑定 executor `sandbox_workspace_id` 与 `entrypoint`，Host 在 dry-run / execution 前通过 `artifacts.snapshot_code` 创建 Python pipeline source 审计快照；`code_artifact_id` 可作为兼容入口或显式复现入口，但不再是 executor 日常编辑 pipeline 的唯一主路径；inline `code` 不再是公开 contract，传入时返回 `unsupported_inline_pipeline_code` tool failure
- 默认执行 dry-run / validation 并持久化 `ExecutionPlan`；该阶段不提交 HPC，也不把 Host `storage_uri` 交给 sandbox code
- `dry_run=true` 只返回 plan，用于 executor 修正代码或预览 artifact reads、external operations、expected outputs、resource / quota estimate 与 doc hints；它不创建 approval
- `dry_run=false` 仍先生成 plan；若 plan 含 approval-gated external operation，或调用方通过 `inputs.approval_policy="single_plan"` 要求单一 plan approval，响应 `waiting_approval` 表示用户正在批准该 plan，而不是等待 executor 手工 resume
- plan approval approve 后由 harness/API runtime signal 继续正式 sandbox 执行；若 `sandbox.exec` runtime 中出现未被 approved plan 覆盖的 SDK controlled operation，或 operation/参数摘要超出 approved plan policy，则进入 secondary approval gate。secondary approval approve 后恢复同一个 blocked SDK RPC / sandbox continuation，而不是唤醒 agent 重新规划。
- plan、approval、execution invocation、output artifact provenance 与 workspace projection 必须携带 `sandbox_workspace_id`、`source_code_artifact_id`、`source_code_digest`、`source_code_version`；Host 在正式执行前重新读取 code snapshot 并校验 digest

事件语义：

- `research.evidence.recorded` 表示 normalized finding / source ref 已进入 canonical research storage
- `artifact.recorded` 表示下载或生成的 workspace file asset 已进入 session artifact catalog
- `execution.pipeline.started` 表示受控 pipeline sandbox 已开始一次 plan-approved run；payload 应包含 `sandbox_workspace_id` 与 source code artifact provenance；plan approval 阶段以 `approval.requested` 和 `engine.invocation.updated(waiting_approval)` 表达，runtime SDK secondary approval gate 也使用同一等待态
- `execution.pipeline.step.completed` 表示 pipeline 内一个 SDK step 完成；payload 必须能回链到 pipeline invocation 与 step id
- `execution.pipeline.completed` / `execution.pipeline.failed` 表示 pipeline terminal state，不能替代每个 run / artifact 的 canonical record
- `bio.*` SDK step 的成功、warning 和失败通过 `execution.pipeline.step.completed`、`execution.pipeline.failed`、engine invocation output payload 与 artifact provenance 投影；大型 FASTA/metadata/raw hits/parsed hits 不进入 RPC 全文
- `bio_tools.*` SDK step 的成功、warning 和失败使用同一投影路径；MAFFT/CD-HIT/HMMER 输出必须先通过 declared output 与最小格式校验，stdout/stderr 或 oversized log 以 artifact ref 暴露
- `artifacts.register` / `artifacts.register_many` 可携带 `format` 与 `metadata.required_columns`；sandbox control server 必须先做非空、FASTA/HMM/CSV 必需列轻量校验，再允许 output artifact 进入 catalog
- `execution.preprocess.completed` 表示 pipeline 内格式转换或输入准备已生成新的可信 workspace artifact
- `execution.artifacts.fetched` 表示 runner 已按 declared `expected_outputs` 下载远端结果，随后应产生对应 `artifact.recorded`
- 同一次 research observation 可以同时产生 evidence 与 artifact，但二者不应混用同一个记录类型
- `agent.woken` 表示 scheduler 已为 resident master 或 teammate 开始一次 work turn；wakeup reason 必须能回链到 user message、inbox、task、approval、engine invocation 或 manual resume
- `agent.idle` 表示 agent 没有立即可执行工作，LLM loop 已停止，但 agent identity、inbox 与 status 继续保留
- `signal.*` 是 scheduler/debug 诊断事件，默认不作为用户 workspace projection 的产品语义
- `runtime.session_locked` 表示某个 session 当前由另一个 runtime owner 持有推进权；manual drain / background tick 必须尊重该状态
- `runtime.lease_heartbeat_failed` / `runtime.lease_lost` 表示当前 scheduler 无法继续证明 session ownership；payload 只暴露非凭据型 fencing/worker identity 与安全 error type，不暴露 lease token、数据库路径或内部异常全文
- `runtime.fencing_rejected` 表示 stale worker 的 signal 写回被 session lease fencing 拒绝，不能覆盖新 owner 的结果
- `runtime.consistency.warning` / `runtime.state_attention` 是只读诊断事件；它们可提示 operator 或 master follow-up，但不得自动把 task 写为 completed / failed

## 7. Legacy Boundary

- 主线不再维护旧 workflow API/UI/CLI 双栈。
- `current_phase`、phase rail、supervisor-route 等词汇不是公共接口基线。
- 新接口必须以 `session_id`、task、lane、approval、engine invocation、artifact、report draft 与 report 为锚点。
