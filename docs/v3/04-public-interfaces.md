# OpenZyme V3 公共接口

## 1. 总体原则

V3 允许引入破坏性新接口，并以替代 V2 为目标。

目标：

- 给前端、CLI、外部调用方一个新的 harness-first 语义面
- 不要求调用方理解 LangGraph、phase graph、internal engine state

说明：

- `/v3` namespace 仍然保留，便于在迁移窗口内识别新接口
- 但 V3 默认不承担长期兼容 V2 语义的义务
- 任何兼容层都只应视为短期迁移措施，而不是长期产品承诺

## 2. API 设计默认值

建议最小接口按两层理解。

面向普通用户与 Web UI 的主入口：

- `POST /v3/sessions`
- `GET /v3/sessions/{session_id}`
- `POST /v3/sessions/{session_id}/messages`
- `GET /v3/sessions/{session_id}/workspace`
- `GET /v3/sessions/{session_id}/events`
- `POST /v3/approvals/{approval_id}/resolve`

`POST /v3/approvals/{approval_id}/resolve` 是普通用户/Web UI 改变 approval 状态的唯一入口。approval resolve 后，runtime signal 唤醒对应 resident teammate、harness 或 execution supervisor 内部恢复路径；在 resolve 前，任何 `execution.resume` / SDK resume 机制都不能被当成批准入口，也不应暴露为用户或 agent 必须手工编排的主流程。

面向 harness tools、CLI/ops、测试与迁移调试的 control-plane secondary endpoints：

- `POST /v3/tasks`
- `PATCH /v3/tasks/{task_id}`
- `POST /v3/lanes`
- `POST /v3/lanes/{lane_id}/claim`
- `POST /v3/lanes/{lane_id}/keep`
- `POST /v3/lanes/{lane_id}/remove`

默认内部 tool surface 还应包括最小 report draft 操作：

- `report_draft.get`
- `report_draft.update`
- `report.publish`

默认 master 内部 team coordination tool surface 还应包括：

- `protocol.thread`
- `protocol.send`

这些是 agent team 内部协调工具，不新增 REST endpoint，也不要求 Web UI 直接暴露操作入口。master 可用它们读取 delegation correlation thread，并在 teammate 失败、`max_steps_exceeded` 或摘要不足时发送 `diagnostic_request`。workspace projection 继续通过 `delegation`、`inbox` 与 `activity_feed` 展示 unread、wakeup、thread 与 responded 状态。

默认内部只读文档工具还应包括：

- `docs.search`
- `docs.read`

`docs.search(query, tags?, limit?)` 返回受控文档库的匹配条目，条目至少包含 `doc_id`、`title`、`summary`、`tags`、`version` 和 `path`；`docs.read(doc_id | path)` 只读取 registry 中登记的文档，不能读取任意 repo 文件，返回同样 metadata 加 `content`。首批必须索引 `docs/v3/execution-pipeline-docs/`，供 execution teammate 按需学习 pipeline SDK。该工具是通用 V3 内部能力，后续 research/reporting 文档也可接入同一接口。

旧式 `skill.list` / `skill.load` 可以作为迁移期兼容机制存在，但不再是 V3 execution pipeline / HPC SDK 用法说明的主路径。executor 应优先使用 `docs.search` / `docs.read`。

### Internal Tool Result Envelope

V3 internal tools must return an LLM-readable envelope. The Python `ToolResult.content` field remains available for compatibility, but tool messages fed back into master/teammate models are serialized as JSON with at least:

- `ok`: whether the tool's core semantic action completed
- `status`: machine-readable outcome such as `delivered`, `wakeup_queued`, `responded`, `recipient_not_found`, `runtime_failed`
- `summary`: short human-readable outcome
- `error_code`: stable failure code, or `null`
- `hint`: actionable next step, or `null`
- `details`: structured diagnostic metadata
- `content`: legacy content string
- `payload`: parsed JSON payload when `content` is JSON

`ok=true` must not mean "no downstream work remains"; it only means that the specific tool completed its promised action. `ok=false` means the model must not assume the requested action happened.

默认 research direct-tool surface 还应允许 provider-specific 轻量动作：

- `pubmed.search`
- `semantic_scholar.search`
- `uniprot.lookup`
- `uniprot.download_fasta`
- `rcsb_pdb.search`
- `rcsb_pdb.download_structure`
- `interpro.query`

这些 direct provider tools 的返回内容应统一为 `ResearchObservation` JSON，而不是暴露各 provider 的原始 response shape。

最低语义：

- search / lookup 返回 `summary + findings + sources + unresolved_gaps`
- download 返回 `summary + artifacts`，并在可能时附带来源 `findings / sources`
- `sources` 是 evidence 的引用来源，不是 workspace artifact
- 只有真实下载或生成的文件资产才进入 `artifacts`
- raw provider payload 默认不进入长期 LLM restore context；需要调试时使用 `raw_ref` 或 engine document 追踪

说明：

- `POST /v3/sessions/{session_id}/messages` 是默认的 harness command ingress，可触发普通消息处理、task updates、delegation、engine 调用与 report draft 推进
- 当 `model_factory` 可用时，该入口默认走真实 top-level LLM harness driver
- Web UI 默认不要求用户手动创建或编排 task / lane；这些对象主要由 master agent 在 loop 中创建和编排，再通过 workspace projection 展示
- task / lane endpoints 可以存在，但不得反向主导产品交互，把 V3 退化成手工 workflow 管理后台
- V3 初期不要求单独暴露 `agents` REST 资源，但 workspace projection 必须能显示 teammate / delegation / protocol / wakeup 状态
- 默认主路径是 `conversation -> master planning -> task -> resident teammate wakeup -> teammate work surface -> user feedback`，而不是用户消息直接裸触发 capability

## 3. Workspace Contract

`GET /v3/sessions/{id}/workspace` 返回统一 snapshot。

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

说明：

- `conversation` 来源于持久化的 user / assistant message content，是用户与 master agent 的 canonical read model
- `conversation` 只承载产品级对话记录；带 `tool_calls` 的 LLM response content 即使包含自然语言，也不写入 `conversation`
- UI 刷新后必须可以仅靠 workspace projection 恢复 conversation timeline，而不是依赖浏览器本地消息历史
- `agent_traces` 来源于 canonical session storage 的 `engine_documents(document_kind="llm_trace_step")`，不是 `/debug/llm-calls`。它按 `actor_ref` 分组，`harness` 表示 master agent，teammate 使用对应 `agent_id`
- 每个 trace entry 至少包含 `trace_id`、`actor_ref`、`actor_kind`、`display_name`、`role`、`call_index`、`created_at`、`response_text` 与 `tool_calls`
- `agent_traces` 是过程级可观测性 read model；每次 master / teammate LLM response 后都应生成 trace entry，供 Web UI 展示中间 response text 与工具调用请求
- `tool_calls[]` 只展示 LLM 请求调用工具的公开投影：`call_id`、`tool_name`、`task_id`、`lane_id`、`args_public`。本读模型不展示 tool result
- teammate 首个 trace entry 可包含 `initial_prompt`，只展示角色种子信息：identity、role、task、lane、correlation、instructions 与 seed message；不得暴露完整 system prompt 或 tools schema
- `args_public` 必须清洗 secret/token/password/credential、Host path、storage URI、SSH/runner config、pipeline/source code 与超长字段；保留工具名、任务/车道关联、公开 instructions 和结构化意图
- `capabilities` 是可扩展分区，按 `capability_key` 挂载各 engine 的投影
- 不应把当前 engine 名称直接固化为 workspace 顶层 contract，避免后续每新增一种能力都破坏接口
- `task_board`、`delegation`、`lane_board` 共同表达内部执行状态；它们不是 conversation 的附属调试信息，而是与 conversation 并列的 control-plane 读模型
- `delegation.agents` 默认表达 resident team roster：agent identity、role、status、task/lane focus、correlation thread、unread inbox count、wakeup reason 与 last active time
- `artifacts` 默认是 session 共享工作面的只读投影，供 UI 呈现，也供后续 agent loops 作为可读取 catalog 理解当前工作面
- `report_drafts` 默认表达 report teammate 的中间交付面；它不是一次 capability invocation 的临时输出
- research 过程中下载的 sequence / structure 默认也进入 `artifacts` 共享投影，而不是只停留在 lane 私有目录
- 这类 research artifact 至少应带 provider、external id、format、source locator、task linkage 与 provenance / evidence linkage
- execution 输入 artifact 必须通过 compiler 映射为 runner staging input；public workspace/read model 不暴露 Host repo path、sandbox host path、`storage_uri`、runner credentials、SSH/Slurm config
- execution 输出 artifact 必须来自 runner declared `expected_outputs` 的下载结果，并保留 output relative path
- `capabilities.deep_research[]` 默认承载每个 research invocation 的 `canonical_summary`、`evidence`、`source_refs`、`gaps` 与 output document 投影
- `capabilities.execution[]` 默认承载每个 execution pipeline invocation 的 `pipeline_invocation_id`、`code_digest`、`sandbox_status`、`hpc_run_ids`、`tool_contract`、`input_artifact_ids`、`preprocess_artifact_ids`、`output_artifact_ids` 与 terminal summary
- execution pipeline 的 public read model 不暴露 Host repo path、sandbox host path、`storage_uri`、pipeline source code、SSH/Slurm config 或 runner credentials
- direct provider search 产出的 normalized findings 后续也应能进入同一 canonical research evidence / source ref 读模型；不应只作为一次性 tool message 存在
- `source_refs` 与 `artifacts` 是并列的 canonical workspace 信息：前者回答“证据来自哪里”，后者回答“哪些文件资产可被后续 agent / UI 读取”

## 4. CLI 语义

V3 CLI 不再围绕 `episode phase` 渲染。

默认能力：

- 查看 session workspace
- 查看 task board，并在高级/ops 场景下更新 task board
- 处理 approvals
- 观察 lane 状态
- 发起消息 / 继续 agent loop

CLI 可以保留 task / lane mutation 命令，作为自动化、调试、迁移和 operator 用途；这不代表 Web UI 的默认用户需要手动维护这些对象。

## 5. Web UI 语义

V3 Web UI 默认是 conversation-first。

主交互：

- 用户发送自然语言消息
- top-level master agent loop 决定如何创建和编排 task
- 具体 research / execution / reporting task 默认由 resident teammate agent 推进；master 可显式委托，idle teammate 也可按 role 自动认领 ready task
- `research teammate` 围绕 task 读取共享 workspace / artifacts、按需绑定 lane、调用 `deep_research` 或直接调用 provider-specific research tools、请求 approval，并可通过 protocol 与 peers 沟通
- `execution teammate` 围绕 task 读取共享 workspace / artifacts、按需绑定 lane、提交受控 execution pipeline，并可通过 protocol 与 peers 沟通；具体 HPC / 长耗时 / 高 quota SDK operation 是否需要 approval 由 Host supervisor 的 tool policy 决定，teammate 不需要判断敏感性
- execution teammate 不直接调用 HPC runner tool；它只能通过 `execution.pipeline.*` 提交或恢复 pipeline，由 sandbox SDK 和 Host supervisor 间接访问 runner
- execution teammate 默认拥有 `docs.search` / `docs.read`，并应按需检索 `pipeline`、`artifact read/register`、`preprocess`、`hpc.vina`、`hpc.fpocket`、`batch ligand docking`、`sandbox rules` 与 `dry-run` 文档
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

这些事件默认服务于“用户与 master agent 的单一对话体验”，而不是把 V3 暴露成多线程运维控制台。

`llm.response.created` 是 response-step 级 streaming event。Host API 应在每次 master / teammate LLM response 被持久化为 `llm_trace_step` 后尽快推送该事件，而不是等整个 `POST /v3/sessions/{session_id}/messages` command 完成后批量发送。Web UI 用它实时增量更新 `workspace.agent_traces`；最终面向用户的 `conversation.assistant_message` 仍可在 command 完成或明确产出用户回复时发送。

`execution.pipeline.start` 语义：

- 默认执行 dry-run / validation 并持久化 `ExecutionPlan`；该阶段不提交 HPC，也不把 Host `storage_uri` 交给 sandbox code
- `dry_run=true` 只返回 plan，用于 executor 修正代码或预览 artifact reads、HPC operations、expected outputs、resource / quota estimate 与 doc hints；它不创建 approval
- `dry_run=false` 仍先生成 plan；若 plan 含 approval-gated `hpc.*` operation，响应 `waiting_approval` 表示用户正在批准该 plan，而不是等待 executor 手工 resume
- approve 后由 harness/API runtime signal 继续正式 sandbox 执行；若 runtime 出现未被 approved plan 覆盖的 `hpc.*` call，则进入 secondary approval gate

事件语义：

- `research.evidence.recorded` 表示 normalized finding / source ref 已进入 canonical research storage
- `artifact.recorded` 表示下载或生成的 workspace file asset 已进入 session artifact catalog
- `execution.pipeline.started` 表示受控 pipeline sandbox 已创建并开始运行；plan approval 阶段以 `approval.requested` 和 `engine.invocation.updated(waiting_approval)` 表达，runtime SDK secondary approval gate 也使用同一等待态
- `execution.pipeline.step.completed` 表示 pipeline 内一个 SDK step 完成；payload 必须能回链到 pipeline invocation 与 step id
- `execution.pipeline.completed` / `execution.pipeline.failed` 表示 pipeline terminal state，不能替代每个 run / artifact 的 canonical record
- `execution.preprocess.completed` 表示 pipeline 内格式转换或输入准备已生成新的可信 workspace artifact
- `execution.artifacts.fetched` 表示 runner 已按 declared `expected_outputs` 下载远端结果，随后应产生对应 `artifact.recorded`
- 同一次 research observation 可以同时产生 evidence 与 artifact，但二者不应混用同一个记录类型
- `agent.woken` 表示 scheduler 已为 resident teammate 开始一次 work turn；wakeup reason 必须能回链到 inbox、task、approval、engine invocation 或 manual resume
- `agent.idle` 表示 teammate 没有立即可执行工作，LLM loop 已停止，但 agent identity、inbox 与 status 继续保留

## 7. 弃用策略

- V2 进入 `deprecated / frozen` 状态，不再继续功能性演进
- V3 完成后应直接制定 V2 retirement plan，而不是默认长期双栈并行
- 若迁移窗口内仍需保留少量兼容入口，它们只能作为临时 shim，不能反向主导 V3 设计
- `current_phase`、phase rail、supervisor-route 等 V2 词汇不再是 V3 公共接口基线
