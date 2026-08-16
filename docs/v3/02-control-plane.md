# OpenZyme V3 Control Plane

> Repository binding、agent workspace、publication、revision/path handoff、external
> job/result、scientific deliverable 与 historical import 的候选资源合同见
> [file-workspace-migration.md](file-workspace-migration.md)。它们处于 source-only gate
> 时不得与下文 current artifact ledger 形成 dual truth。

## 1. 目标

V3 control plane 负责保存所有**跨对话、跨压缩、跨后台执行**仍然成立的顶层状态。

设计原则：

- 能投影给 UI / CLI 的状态，不得只存在于 prompt
- 能跨多轮对话恢复的状态，不得只存在于 graph checkpoint
- 能驱动行为的状态，要么是 canonical object，要么是它的派生 projection
- 能并发恢复的 capability execution，不得只靠 engine 内部状态识别

SQLite schema 兼容策略：

- 本地 V3 SQLite 是开发/runtime control-plane state，不是长期兼容的归档格式
- 空库在一个 `BEGIN IMMEDIATE` 原子事务内按当前 migration 列表初始化并写入
  `PRAGMA user_version`；任一 migration 失败时整体回滚，不暴露部分 fresh schema
- `user_version` 等于当前 schema version 的库只做关键表校验后复用
- 旧版本、未知版本、非空但 `user_version = 0` 的库 fail fast
- Host 不做隐式 migration、自动修复、自动删除或自动备份；operator 需要手动删除旧库，或指定新的 `--v3-sqlite-db` 路径

SQLite connection / transaction ownership：

- `SQLiteRepositoryProvider` 只接受 file-backed database，并在 composition 时校验/初始化当前 schema；产品路径不使用 `:memory:` 作为跨线程状态锚点
- repository service 的 file-backed control-plane database 必须是 Host uid 持有的普通非 symlink 文件且 mode 精确为 `0600`；新文件按 `0600` 创建，已有权限漂移直接使 preflight 失败，不由启动路径静默 chmod
- 每个 request、background worker、scheduler agent turn 和 sandbox SDK callback 在其实际线程内获得独立、默认 thread-affine connection，并由 scope 关闭；不得把 request thread 的 connection 交给 `asyncio.to_thread`
- read scope 开启 `query_only`，不抢占 write lock；短 canonical command 使用 `BEGIN IMMEDIATE` Unit of Work，repository 内部 `commit` 在 owning UoW 中被抑制，异常统一 rollback
- 会跨 LLM/provider/runner/sandbox 的流程使用非长事务 connection scope；repository 写入仍是短提交，不能用一个 write UoW 包住外部等待
- 同内容 durable event replay 在 standalone connection scope 中必须关闭 duplicate INSERT 打开的 SQLite 隐式事务后再返回既有 event；owning UoW 内仍由外层统一提交。幂等 replay 不得遗留 transaction，使随后的 mutation-writer retirement、freeze 或 quiescence 在嵌套 `BEGIN` 上失败
- WAL、foreign keys 与有限 `busy_timeout` 是固定连接配置；它们不允许跨线程复用，也不构成 command 幂等、outbox 或 lease fencing 的替代品
- `020_v3_task_integrity` 将 task dependency 的 INSERT / UPDATE integrity triggers 纳入 current schema；缺少这些 triggers 的旧本地库不是 current-version input，必须按 fresh database 流程重建
- `021_v3_durable_event_outbox` 将 durable event、command receipt 与 append-only/immutable triggers 纳入 current schema；缺少任一项同样 fail fast
- `022_v3_session_access_control` 将 session principal/role 授权事实纳入 current schema；授权不能只存在于 API token claims、浏览器状态或 project 字符串比较
- `026` 至 `031` 将 canonical controlled-operation execution、runtime command/continuation、mutation scope/writer/receipt、immutable dispatch request、result artifact set 与 external snapshot 纳入 current schema；缺少 closed enum、identity、append-only 或 writer-fence trigger 的数据库不是 current-version input
- `038_v3_project_repository_bindings` 增加 immutable binding versions、project active pointer、mapping receipts、session pins、credential issuance、private namespace/hold/retirement 与 binding retirement；repository identity ownership、pinned-session consistency、receipt owner identity 和 referenced-retirement 由 FK/unique/trigger fail closed
- C2 agent-capability forward migration 增加 workspace generation reservations/readiness、`pending_workspace | active | revoked` leases、append-only lifecycle events，以及 immutable retirement request、cleanup proof 与 final records；它只建立 generation/control-plane truth，不从 038 的 acceptance-only assertion/hold 追溯升级 production lease，也不伪造 C3 workspace/capsule readiness
- C4 publication forward migration 增加 frozen publication intents、publication-bound controlled executions/events、exact remote receipts、append-only published revisions、supersedes links 与事务型 event outbox。intent、execution、receipt、revision 的 binding/generation/commit/tree/manifest/policy/publisher identity 由 FK、unique 与 trigger 联合约束；不回填 local commits、private refs、legacy artifacts 或 remote branches
- C5 Git LFS forward migration 增加 immutable binding policies、quota reservations、upload sessions、repository/binding object metadata、workspace-generation object links、object-read receipts、stable closure manifests、fresh closure verifications、frozen publication-intent proofs、publication closure/pins、private reachability receipts 与 dry-run/deletion GC receipts。closure identity 与观测时间分离，但每个 publication 必须绑定一枚 exact fresh verification；published pin、receipt 和 policy rows 不允许更新或删除
- C7 revision-path handoff forward migration 增加 immutable revision path refs、protocol file handoffs、task finish/evidence rows、research file indexes，以及 report content/version/supersedes identity。数据库重验 publication、session、owner、participant、exact task、invocation 与 LFS closure；current research/report/task-finish 正文不得再写入 `EngineDocument`。scientific evidence variant 在 C10 前拒绝

## 2. Canonical Objects

### 2.0.0 Revision-path handoff closure

`RevisionPathRef` 不是可变路径别名。它绑定 exact `PublishedRevision`、tree manifest entry 与可选
Git LFS closure，且 row immutable。`ProtocolFileHandoff` 的 producer/recipient 必须是同 session/project
的 distinct agents，entry 的 producer/recipient/session 必须与 envelope 完全一致。handoff、inbox 与 wakeup
由一个短事务写入；它们不改变 task 或 recipient workspace。

`TaskFinishRecord` 与 `TaskEvidenceRef` 由 task current assignee 写入并绑定 exact task。revision/report/
controlled-result evidence 分别重验 publication owner、report owner task 和 execution owner task；unknown、
null task、cross-task 或 digest-only reference 一律拒绝。`SessionReportRecord` 的正文身份是 owner-published
revision path，修订只允许 new id/version 与 explicit supersedes。`research_tool_file_index` 只索引 exact
invocation/task owner 发布的 research layout，不存文件正文。

上述 session-owned rows 纳入 mutation writer/freeze/quiescence；repository-global LFS pin、retention 和 GC
仍由 repository owner 管理，不能借 session freeze 删除或重算。

### 2.0 Git LFS object closure

`GitLfsBindingPolicy` 是 `ProjectRepositoryBinding` version 的不可变组成，不是运行时默认配置。
`GitLfsClosureManifest` 只编码 commit/tree/policy/endpoint/authorization 与排序后的
`path + mode + pointer blob OID + LFS OID + size`，因此相同 revision 的 closure identity 可重放；
`GitLfsClosureVerification` 则绑定本次逐对象读取 receipts 与 observed time，证明 cache hit 后仍
重新读取了 authoritative bytes。`git_lfs_publication_intent_proofs` 在 frozen intent 创建时将两者
锁定，materialization 只能消费该 proof，不能查询“最近一次成功”或补造替代 proof。

quota reservation 与 upload session 精确绑定 session、agent member、workspace generation、
credential 和 binding version；失败或过期只能显式 settle/release。workspace object link 记录
哪个 generation 通过标准 upload/download 使用了 OID。private reachability receipt 必须绑定
整代 namespace retirement receipt 与 terminal ref/commit digests；GC candidate 是 repository-
scoped、先 dry-run 后 exact revalidation 的闭包事实，不是凭 wall-clock deadline 直接删除的许可。

### 2.1 Session

用途：

- 代表一次用户与系统的长期工作上下文
- 作为 memory、tasks、lanes、approvals 的上层锚点

建议字段：

- `session_id`
- `project_id`
- `title`
- `objective`
- `status`
- `created_at`
- `updated_at`

#### Session access

共享部署中，`SessionAccessRecord(session_id, principal_id, access_role, created_at)` 是 session 可见性与写权限的 canonical truth。每个 session 恰有一个 owner，未来可以显式增加 collaborator/viewer；同 project 不自动获得 session access。session row、owner access row、`session.created` durable event 与 command receipt 必须在一个短 write UoW 中提交或整体回滚。

认证 principal 与 agent identity 是两套命名空间：外部用户使用 `user:<opaque-id>`，resident agent 使用 `agent:<role>:<opaque-id>`。审批审计、lane claim 和 user message context 使用服务端认证得到的 user principal，不能接受客户端伪造 actor。

### 2.1.1 ProjectRepositoryBinding / SessionRepositoryBindingPin

`ProjectRepositoryBinding` 是 project repository universe 的 immutable version。canonical fields
包括：

- `binding_id + project_id + binding_version + repository_id`
- internal Git/LFS service id 与 endpoint
- 独立 upstream identity/URL
- object format、default base ref 与 exact base commit
- private/publication/historical namespace policy
- policy version/digest、canonical digest、created by/at

同一 `repository_id` 只能归属一个 project；一个 project 只有一个 active pointer，但旧
version不会因 rollover 被改写。lifecycle 是 `registered | active | retired` 的 repository
派生状态；retirement 必须先证明 active/session/mapping/credential/private-namespace references
全为零并写 immutable receipt，不能靠 UPDATE binding row 表达。

`SessionRepositoryBindingPin` 保存 session 创建/显式 legacy mapping 时解析到的 exact
`binding_id + version + repository_id + resolved_base_commit + binding_canonical_digest`。新
session row 与 pin 在一个 write UoW 内提交；`repository_binding_status=pinned` 却没有 pin、
pin 与 session/project/binding/receipt identity 不一致均由 migration trigger 拒绝。既有 rows
默认保持 `repository_binding_required`，只有 operator mapping command 及其 immutable receipt
可以闭合。

session restore 和后续 agent workspace/publication/HPC/historical migration prerequisite只从
pin读取，不重解 active pointer。binding 原 base ref 后续前进不影响旧 session，只要 pinned
commit object仍存在；配置 identity、canonical digest 或 object drift 则显式失败，不从 ambient
Git state、临时 repository 或 upstream补全。

`repository_credential_issuance_records` 只保存 token digest 与 closed claims，不保存 bearer。
claims 绑定 binding/session/agent/workspace generation/capability lease/protocol/ref classes；
revocation/expiry 是显式状态。C2 production issuance 不接受 caller 自报的
`ActiveCapabilityLeaseAssertion`；它在同一 `BEGIN IMMEDIATE` 中通过 canonical
active-lease validator 重读 exact `session + member + public agent + generation + profile + target +
policy`，再闭合 session pin、namespace/hold 与 issuance row，commit 后才允许返回短期
bearer。Git/LFS read 与 write authentication 每次都重读 canonical active lease；write
另外必须找到 exact `binding + session + agent + generation` 的 `open` private
namespace 和 owner ref 等于 lease id 的未释放 `active_capability_lease` hold。
namespace close/retire、hold release 或 lease revoke 提交后，旧 bearer 即使未过 TTL 也不能再认证。
C1 本机验收的 assertion/hold 仍只是不可升级的历史审计事实。private namespace、hold
和 terminal receipt 行保存 retention authority，agent 永远没有 delete owner。

publication 与 historical refs 不经 agent bearer：`RepositoryOwnerRefService` 分别要求固定的
Host publication owner 与 migration historical owner，先消费 publication create-only / historical
create-or-fast-forward ACL，再要求每个新目标都是 commit object，并对 bare repository 执行原子
exact-old/new CAS。agent pre-receive hook 同样拒绝 blob、tree 或 tag 目标，确保 private ref 与
retirement receipt 保存的确实是逐步 commit trace。这里仅建立 C4 与
历史迁移将消费的内部 authority primitive，不创建 publication workflow、migration orchestration
或 upstream effect。

### 2.2 Task

用途：

- 持久化 master agent 对内部工作的正式安排
- 作为 session 内可调度、可委托、可恢复、可完成的工作单元
- 支持依赖、assignment、lane 绑定、delegation、结果回填

补充定义：

- `task` 不是普通聊天消息，也不是 capability tool call 的临时参数
- `task` 默认由 master agent 基于用户对话创建和编排
- `task` 是 delegated teammate、lane、approval、engine invocation、artifact、report draft、report、protocol thread 的默认关联锚点
- `task` 的存在意义是让内部执行和外部对话解耦：用户与 master agent 对话，内部团队围绕 task 推进工作
- `blocked_by` 是执行闸门：下游 task 可提前创建，但在 blocker terminal 前不能被 `task.delegate`、auto-claim 或普通 wakeup 推进执行
- `blocked_by` 同时是 canonical same-session DAG：service 写前验证 cycle path，SQLite INSERT / UPDATE triggers 拒绝跨 session edge 与任意长度的 cycle；task row 和该 task 的完整 dependency replacement 原子提交
- generic create/edit 不能写入或跨越 business-exit status。除 agent-level / legacy pending approval block 这类已文档化机械迁移外，`blocked`、`completed`、`failed`、`cancelled` 只能由 `task.finish` 写入；durable SDK attached continuation 的 park 是 runtime suspension，task 保持 `in_progress`，不能借用业务 `blocked`。blocked task 保持 blocked 时允许描述修正、lane unbind 等非状态 edit，completed / failed / cancelled task 的 edit 则 fail closed。测试构造历史状态必须显式标记 fixture seed intent
- 已处于任一 business-exit status 的 task 不能再次调用 `task.finish`；blocked task 必须先经显式 resume/reopen 回到 `in_progress`。finish intent 只允许改变 status、updated_at、failure_summary 与 failure_ref
- `task.finish` 将 `task_finish` document、task status 与 durable canonical event 写入同一 transaction，commit 后才允许 SSE 读取；不能出现 finish document 已存在而 task 未退出，或 rollback 后仍泄漏 `task.finished` event
- task claim、agent-level / legacy pending approval block、approval resume 是窄范围、已文档化的 mechanical commands；它们必须发生允许的 status transition，且除 status / updated_at 与 claim 必需的 assigned_ref 外不能夹带字段修改。durable SDK approval 由 controlled-operation / continuation owner 推进，不触发 task block/resume

建议字段：

- `task_id`
- `session_id`
- `subject`
- `description`
- `status`
- `blocked_by`
- `priority`
- `kind`
- `assigned_ref`
- `created_at`
- `updated_at`

### 2.3 Lane

用途：

- 表达 task 的隔离执行上下文
- 记录工作目录、资源绑定、生命周期

建议字段：

- `lane_id`
- `session_id`
- `name`
- `status`
- `cwd`
- `branch_name`
- `claimed_ref`
- `created_at`
- `updated_at`

### 2.4 Approval

用途：

- 统一所有人工审批与 agent protocol gating

建议字段：

- `approval_id`
- `session_id`
- `task_id`
- `lane_id`
- `kind`
- `requested_action`
- `status`
- `request_ref`
- `resolution_ref`
- `created_at`
- `resolved_at`

补充约束：

- frozen `legacy_sync` controlled operation 的首次 admission 必须在一个短
  `BEGIN IMMEDIATE` Unit of Work 中同时写入 `WAITING_APPROVAL` operation、
  `PENDING` approval、operation 的 approval binding 与
  `WAITING_APPROVAL` continuation；commit 前不得向其他 connection 暴露 pending
  approval。approval wait 与 Host adapter execution 只在该事务提交后开始，不能持有
  SQLite write lock 跨人工等待或外部调用
- approval resolver 因而不能观察到“已有 pending approval、尚无对应 continuation”的
  部分状态；admission 任一步失败时四项写入整体回滚。该兼容不变量不把
  `legacy_sync` 变成新 durable route 的 fallback，也不改变 `durable_async_v1` 的唯一
  execution-owner admission contract

### 2.5 InboxMessage

用途：

- 支持 request-response 协议、agent team 协同、后台通知
- 作为 resident teammate 的 wakeup source，而不只是调试消息记录

建议字段：

- `message_id`
- `session_id`
- `sender`
- `sender_kind`
- `recipient`
- `recipient_kind`
- `message_type`
- `correlation_id`
- `payload_ref`
- `status`
- `created_at`

状态语义：

- `unread` 表示消息尚未被 recipient teammate 的 restore context 消费
- `delivered` 表示消息已进入 recipient 的一次 work turn
- `acknowledged` 表示 recipient 已处理并完成必要回复或状态更新
- request-response message 必须通过 `correlation_id` 回链到同一 protocol thread

### 2.6 MemoryEntry

用途：

- 存储压缩摘要、连续性摘要、长期记忆

建议字段：

- `memory_id`
- `session_id`
- `scope_kind` (`session` / `lane` / `task`)
- `scope_ref`
- `kind`
- `summary`
- `source_range`
- `importance`
- `created_at`

### 2.7 AgentMember

用途：

- 表达可被 harness 恢复、投影、协议化通信的 teammate agent
- 表达哪个 teammate 正在代表 agent team 推进哪个 task，以及它当前的 role / focus / 生命周期
- 表达 resident teammate 在 working / idle / blocked / failed / shutdown 之间的可恢复运行状态

建议字段：

- `agent_id`
- `session_id`
- `lane_id`
- `task_id`
- `name`
- `nickname`
- `display_name`
- `handle`
- `role`
- `status`
- `runtime_state`
- `parent_agent_id`
- `current_correlation_id`
- `wakeup_reason`
- `last_active_at`
- `idle_since`
- `shutdown_requested_at`
- `created_at`
- `updated_at`

`agent_id` 是 runtime/protocol/task ownership 使用的 canonical identity。master 保留 `agent:master`；teammate 不得把 `researcher`、`executor`、`reporter` 或 `agent:{role}` 当作身份，必须使用 `agent:<role>:<opaque-id>`。`role` 只表示能力类型；`nickname` / `display_name` / `handle` 用于 prompt、UI 与 `protocol.send`/`task.delegate` 的人类可读解析。

补充约束：

- teammate 在“是否是 agent”这件事上与 master 平级；差异在于职责，而不是本体类型
- master 是 team leader 与 user-facing agent；teammate 是 internal worker / specialist
- master 也必须作为 resident member 建模，例如默认 `agent:master`，由 scheduler wakeup signal 启动 loop
- teammate 应拥有自己的 restore context、tool surface、protocol thread 与状态投影
- master 与 teammate 的身份与 inbox 默认常驻；idle 状态不持续调用 LLM，但必须可被 scheduler 恢复
- master 显式 delegation 是默认产品路径；teammate auto-claim 仅用于显式 recovery/debug/operator 场景中的 role 匹配认领

### 2.7.1 AgentRuntimeSignal

用途：

- 表达哪些事件需要唤醒 resident master 或 teammate
- 将 inbox、task、approval、engine completion、manual resume 等变化统一接入 scheduler
- 避免 `protocol.send` 只写入数据库但无人消费

建议字段：

- `signal_id`
- `session_id`
- `agent_id`
- `task_id`
- `lane_id`
- `correlation_id`
- `reason`
- `source_ref`
- `status`

`agent_id` 必须是 canonical identity；duplicate wakeup、claim lease、runtime drain 与 teammate resume 都不得用 role 字符串替代。
- `created_at`
- `claimed_at`
- `claimed_by`
- `claim_expires_at`
- `attempt_count`
- `completed_at`
- `error_message`
- `last_error`
- `session_lease_token`
- `session_fencing_token`

补充约束：

- `reason` 至少覆盖 `user_message`、`delegation_assigned`、`inbox_unread`、`task_available`、`approval_resolved`、`engine_completed`、`manual_resume`
- `inbox_unread` 不只来自 teammate-to-teammate 消息，也包括 master-to-teammate 的 follow-up message
- signal 的 `task_id`、`lane_id`、`correlation_id` 与 `source_ref` 应足够让 runtime 恢复 focused master / teammate turn，并从 source inbox payload 或 user message 渲染 wakeup context
- user message admission 选择的结构化 `skill_keys` 必须去重后与该 user conversation document 一起持久化；master 只能从 `inbox_unread` signal 所引用且 identity/session/type 完整匹配的 canonical user message payload 恢复该 focus，manual drain/operator 参数和普通 protocol payload 都不是 workflow 授权来源
- scheduler 只能 claim `pending` signal 或 lease 已过期的 `claimed` signal；claim 时必须写入 `claimed_by`、`claim_expires_at` 并递增 `attempt_count`
- claim 后必须要么 `completed`，要么释放回 `pending`，要么写入 `failed`；失败重试只允许在明确 retryable 且未超过 attempt 上限时回到 `pending`
- duplicate wakeup 去重按 `session_id + agent_id + reason + source_ref` 作用于未完成 signal，避免同一 inbox message 或 engine completion 被重复排队
- task dependency 只由 canonical `Task.blocked_by` 表达；ordinary `task.delegate`
  rejection 不创建 failure disposition、condition subscription 或
  `reason=recovery_required` signal
- runtime work 只来自上面列出的真实 user/task/protocol/approval/engine/manual sources。
  signal 不自动授予 unassigned target task ownership，task exit 仍要求 canonical owner
- `last_error` 保存最近一次失败原因；`error_message` 表达当前 terminal failure 或待重试错误摘要
- signal claim lease 只保护单条 signal 不被重复处理，不代表 worker 拥有整个 session runtime 推进权
- scheduler 在 claim signal 时应绑定当前 `SessionRuntimeLease` 的 `lease_token` / `fencing_token`；complete / fail / release 写回必须校验当前 worker 仍持有有效 session lease
- stale worker 在 session lease 过期或被新 owner reclaim 后，不能把旧 signal 写为 completed / failed；应安全失败并产生 runtime diagnostic
- signal 是调度语义，不替代 canonical task、inbox、approval 或 engine invocation；signal failed 也不等于业务 task failed

状态转换：

```text
pending --claim lease--> claimed --success--> completed
pending --claim lease--> claimed --retryable failure under limit--> pending
pending --claim lease--> claimed --non-retryable / exhausted--> failed
claimed --lease expired--> claimed --reclaim by worker--> claimed
claimed --operator release--> pending
```

### 2.7.2 SessionRuntimeLease

用途：

- 表达某个 session 当前由哪个 runtime worker 拥有推进权
- 阻止 background runtime、runtime-command worker、recovery 或测试 worker 同时推进同一 session 的不同 signal
- 为 signal claim / complete / fail 提供 fencing token，防止过期 worker 迟到写回

建议字段：

- `session_id`
- `owner_id`
- `lease_token`
- `mode` (`background` / `manual_drain` / `recovery` / `test`；`manual_drain` 是 command worker 的内部 scheduler mode，不表示 HTTP ownership)
- `acquired_at`
- `heartbeat_at`
- `expires_at`
- `released_at`
- `last_error`
- `fencing_token`

补充约束：

- 同一 session 同时只能有一个未过期 active lease；不同 session 的 lease 互不阻塞
- lease 过期后可由新的 owner reclaim，并分配新的单调 `fencing_token`
- heartbeat / extend / release 必须校验 `owner_id + lease_token`
- scheduler 在 blocking provider/tool turn 期间按 lease TTL 的有界分数持续 heartbeat；heartbeat 更新失败或返回 no-match 表示 ownership 已丢失，不得继续 claim 新 signal
- runtime worker connection 绑定 `session_id + lease_token + fencing_token`；write commit 前必须重新确认 lease 未过期且未释放，session-scoped write 还必须与 leased session 一致
- scheduler worker 重建的 session-turn engine 继承 exact session fence；attached sandbox control process、durable adapter/HPC callback 与 continuation delivery 分别使用 process epoch、execution fence 与 delivery fence，并共同接受 mutation-writer authority。它们不能因为切换线程/connection 而退化成 unfenced Host write，也不能互借 authority。所有 sandbox-to-Host engine call 只经 typed `SandboxHostCallContext/SandboxHostGateway`，不得回退到 engine 创建时捕获的 repository scope
- write/approval/external tool 在 side effect 前做 fence preflight；commit fence 是竞态条件下的第二道防线。超时或取消后迟到返回的旧 callback 不得写 task、operation、run、artifact、report 或 event
- session runtime lease 只管理“谁有权推进 session runtime”，不判断 task 是否完成或失败
- `/runtime/drain` POST 只 admission command；其 `RuntimeCommandWorker`、background runtime、recovery worker 和测试 scheduler 在实际推进 bounded batch 时都必须尊重同一 session lease。已被占用时 command 终结为脱敏 `locked` diagnostic

### 2.7.3 Runtime/HPC reliability authority objects

这些对象属于 control-plane runtime truth，但不形成第二套 task graph：

- `ControlledOperationExecution`：`durable_async_v1` operation 的唯一 external-effect owner，冻结 operation/session/approval/route/backend/input/expected-output/runtime identity，记录 lifecycle、effect certainty、dispatch generation、state version、execution lease/fence、opaque backend handle、terminal/result refs 与 reconciliation state
- `ControlledOperationExecutionEvent`：append-only transition journal；用于审计与 recovery，不是并列 reducer
- `ControlledOperationDispatchRequest`：在 dispatch 前冻结的 immutable request；worker 不从 mutable workspace 或 prompt重建外部 side effect
- `ControlledOperationResultArtifactSet`：Host-owned immutable result handle、declared artifact identity/digest 与 promotion state；partial 或 drifted set 不得发布
- `RuntimeCommandRecord`：显式 `/runtime/drain` 的 durable admission、idempotency、closed limits、claim/fence 与 bounded terminal outcome；不持 approval/provider/HPC wall time
- `ContinuationState` / delivery attempt：绑定 sandbox run/workspace/runtime identity/process epoch/tool call/invocation/signal、resume strategy、result digest 与 delivery generation；只拥有 exact result delivery
- `MutationScope` / `MutationWriter` / `MutationQuiescenceReceipt`：冻结 session/attempt generation、coverage manifest、writer ancestry/fence、两次一致 snapshot 与 immutable closure proof
- `SandboxHostCallContext`：ephemeral typed composition boundary，只把一个 session-turn、sandbox-process、durable-execution 或 continuation-delivery owner 绑定到 thread-owned repositories；它不持久化，也不成为新的 control-plane reducer

五个 authority boundary 独立存在：session lease/signal claim、sandbox process epoch、execution lease/fence、continuation delivery claim/fence、mutation scope generation/writer fence。process identity 不等于 delivery authority，delivery 也不把已释放的 session lease 交还给 process。它们的 acquire、heartbeat、stale recovery 与 terminal 条件不可互相替代；任何一个对象的 terminal 都不能自动 terminalize task。

durable supervision 的进展也是 owner-produced closed fact，而不是 action-name projection。`RuntimeCommandWorkerOutcome`、`ControlledOperationExecutionWorkerOutcome` 与 `ContinuationDeliveryWorkerOutcome` 必须携带 typed `semantic_progress`；Host seam 对缺失/非 boolean 值 fail closed。execution owner 只把 lifecycle、terminal/effect/retry、dispatch generation、backend/result identity 或 result/artifact-set digest 的 canonical 变化算作进展；lease/fence/version/timestamp、event/diagnostic 写入、claim race、not-claimable、database busy 与 unchanged poll/reconcile 都是可观察但不驱动即时继续的 no-progress。coordinator 在同一 slot 继续轮询其他 worker kind 时，后续 `idle` 不得覆盖已经观察到的 `claim_raced` / `not_claimable` bounded diagnostic。supervisor 只有在一个 bounded tick 的全部 slots 都报告 semantic progress 时才可通知一次可能的 backlog，且该事实不授权 effect、task transition 或 scientific decision。

`ControlledOperation.status/result/error` 对 durable owner 只是由唯一 transition service 在同一 transaction 中派生的兼容投影。immutable result handle 若承载 S12 adapter envelope，完整 envelope 只投影到 `adapter_result_envelope`，其中 exact object `bounded_summary` 单独投影到 `result_summary`；不得把外层 envelope 再嵌入 `result_summary`，否则 sandbox SDK 会看到错误的 wire shape。存在但非 object 的 `bounded_summary` 必须使 transition fail closed；没有该字段的 HPC run handle 与 terminal failure envelope 保持 direct summary 投影。provider callback 丢失后的 materialization 只能从同一 execution handle 已封存且实际 digest 复核通过的 request/observation transcript 重建相同 envelope，不得把 artifact count 通用摘要当作 provider result；closed schema、route/config/output identity、`8 MiB` control-document 或完整 canonical result envelope 的 `256 KiB` core 上限任一不满足即 terminal-known failure。inline summary 只是该完整 envelope 的一部分，bulk identities 必须留在 digest-bound artifacts；EBI HMMER 的 exact candidates 由 `provider_parsed/parsed_hits.csv` 承载而不复制进 summary。terminal-known observation 若不能通过 closed result validation，execution 直接以 `recovery_failed` 终结，不能回到 reconcile queue。raw repository save、legacy adapter、approval row、continuation 或 runtime signal 都不得成为第二个 dispatch/reducer owner。恢复边界由 effect certainty 决定：仅 `no_effect` 可做同 phase 有界恢复，`dispatch_in_doubt` 禁止 replay，`effect_known` 只查询 exact handle，`terminal_known` 只恢复 result/materialization。

runner-backed execution 已存在 exact reservation 时，Host 必须先读取 runner 的 sealed
terminal observation，再决定 execution transition；本地 `Run` 只参与成功 result 的
materialization/recovery，不能先把 runner cause 压成 Host-local generic failure。runner
attempt 的 closed public envelope 固定 terminal status、safe machine error code、
effect certainty 与 retry eligibility，private target/path/command/raw transport diagnostic
仍不投影。合法的 `transport_connect_failed/no_effect` 必须原样贯穿 execution、
compatibility operation、continuation 与 exact `FailureObservation`；missing、非法或与
sealed attempt 冲突的 typed cause fail closed，不回退成更宽泛的成功、terminal-known
effect 或自动 retry。

AOX 等 bounded consumer 若需要跨层读取 operation history，必须从 canonical
`ControlledOperation + unique execution + continuation + scientific-attempt binding +
FailureObservation` 联合投影一份 operation facts，而不是分别重读 workspace/runner/local
Run。每个 fact 显式标记 `probe|formal` scope；投影公开 deterministic prefix、total count、
canonical digest 与 truncation state。该 read model 不成为 reducer，也不授予 retry、
replay、replacement operation 或 task terminal authority。

Mutation scope 的 closure 顺序固定为 close admission/advance fence、显式等待全部 writer/descendant 退休、捕获两次一致的 bounded SQLite/event/external snapshot、签发 receipt、验证后 seal exact generation。runtime idle、空队列、lease expiry、HTTP 返回、timeout、disconnect 或 missing handle 不能推断 writer retirement；receipt/seal 也不表示 task completed。后续合法写入必须进入显式链接的新 generation。

`MutationWriter` 的 session admission 必须把 scope 列表、唯一 open scope 证明、parent
authority 校验、writer registration 与 authority issuance 放在同一个 SQLite write
transaction 中。公开失败只携带 bounded typed reason 与 open-scope count：
`zero_open_scope`、`scope_closed_during_registration` 或
`ambiguous_open_scopes`；它不暴露 scope id、writer ancestry、authority token 或私有路径。
若同一 repository connection 已持有 Host 管理的 `BEGIN IMMEDIATE`，且该事务内
snapshot 证明 session 从未有过 mutation scope，nested writer turn 必须在本连接保留
untracked compatibility，不能再通过外部 factory 打开第二个 writer connection 并等待
自己持有的 SQLite write lock。该兼容分支不创建 authority；只要存在任何 scope 历史，
仍走正式 admission/fence 路径。
consumer 只能对前两种 closed-admission reason 进一步验证特定 lifecycle rollover，
ambiguous 永远 fail closed。

### 2.7.4 Agent workspace generation、capability lease 与 retirement

`AgentWorkspaceGenerationReservation` 是 C2 的最小 workspace-generation truth。它只包含
session/member/generation identity、strictly monotonic replacement、readiness status 与 typed
readiness owner/ref/digest。它不包含 clone path、volume、`.git`、HEAD、capsule、network
或 toolchain 事实。C2 可以通过显式 test provisioner 测试这个 seam，但 production
readiness 由 C3 的真实 workspace provisioner 提交；legacy sandbox/process 不作回填。

`AgentCapabilityLease` 是 exact
`session + internal member + public agent identity + workspace generation` 的 canonical capability
authority。immutable fingerprint 还包含 closed profile/capability set、target scope digest、policy
version/digest、parent provenance 和 idempotency identity。status 闭集为：

- `pending_workspace`：generation 已保留，但没有 exact verified readiness，不授权 runtime、credential 或 capsule action；
- `active`：matching reservation/readiness 已由注册 provisioner 确认，admission boundary 仍必须当场重读；
- `revoked`：终态，不恢复、不降级、不复用。

同一 `(session, member, generation)` 最多一枚 lease。同一 immutable fingerprint 的
issuance replay 返回原 record；任一 generation/profile/capability/target/policy/parent drift
显式冲突。workspace replacement 必须先关闭旧 generation、撤销其 lease，再保留严格更大
generation；旧 generation 不能重新 active。

C2 的 runtime/delegation gate 从 activation 起立即生效。runtime claim、turn 和
restore-to-runtime 要先解析 current reservation/generation，再重读 exact active lease。
missing reservation/readiness、pending、missing/revoked/mismatched lease 必须投影
`provisioning_required` 或更精确 typed error，并让 agent non-runnable。
`SessionRuntimeLease`、signal claim、old process、tool exposure、namespace hold、caller assertion 与
legacy sandbox 都不能代替。delegation 先校验 parent 自身的 exact active lease；可在一个
canonical operation 中创建 child identity、generation reservation 与 derived pending lease，但在
child 自身 ready/active 前不产生 runnable wakeup，不借 parent capsule/workspace/token/credential。

revocation scope 固定为：

- ordinary explicit revoke 默认只撤销 exact lease；parent exact revoke 不隐式级联；
- session end 撤销该 session 全部 pending/active leases；
- policy invalidation 只撤销 matching policy version/digest scope；
- workspace replacement 只撤销被替换 generation；
- agent retirement 撤销 exact member 跨 generation 的全部 pending/active leases；
- subtree 只在 operator 明确提交 root 与 scope 时递归，不影响 ancestor 或 subtree 外 siblings；child revoke 也不反向影响 parent/siblings。

每次 revoke 在一个 write transaction 内停止新 credential issuance、撤销 revocable
derived credentials、释放 matching capability holds、写 lease revoked state 并 append exact
lifecycle event。任一步失败整体 rollback，不得留下 partial closure。

`AgentRetirementRequest` 先绑定 session/member、exact current generation/lease、shutdown ref、
registered cleanup provider、actor/time 与 canonical digest。request commit 是 admission freeze：
该 member 的新 signal enqueue/claim/turn、lease issuance/activation、repository credential issuance
与 capability hold 都被拒绝；它不取消或结算已经 claimed 的 occurrence。只有该 agent 零 claimed
signal 时才能持久化 exact request-bound cleanup proof；过早 proof 必须拒绝，不能等 occurrence
事后结算再复用。

request、cleanup proof 与 final record 三相 insert 分别要求 service-only、transaction-local、
exact-record retirement lifecycle authority；generic mutation writer 不能替代 registered cleanup
provider。所有进入或离开 `claimed` 的 signal 迁移也要求 exact active `SessionRuntimeLease`
token/fence 并由数据库 trigger复核，raw SQL 或 capability lease 都不能结算、释放或重领他人
occurrence。

最终 transaction 再次重读 request/proof、current owner/generation/lease 与零 claimed signal，
撤销该 member 全部 live leases、写 `AgentRetirementRecord` 并把 member 置为
`SHUTDOWN/retired`。只有这个 immutable shutdown-completed fact 可触发 `agent_retired` 及
member-wide revoke。`AgentMemberStatus.FAILED | COMPLETED | STOPPED`、task terminal、runtime
failure/idle/budget exhaustion、单独 shutdown request 或 process disappearance 都不构成
retirement。

这个 authority 与 `SessionRuntimeLease`、`ControlledOperationExecution` lease/fence、mutation
writer/fence 和 `ScientificAttemptAuthorization` 正交。attempt/MICU/cost/wall-time ceilings
仍属于 scientific authorization，prompt/context/step budgets 仍是机械 runtime constraint。C2
不创建 `WorkspacePublicationIntent`、`PublishedRevision`、remote HPC credential/workspace/job 或
`ControlledOperationExecution`；这些真实 owner 分别留给 C4 与后继 remote-HPC/job changes。

### 2.8 EngineInvocation

用途：

- 统一追踪 capability engine 围绕某个 task 的启动、恢复、重试、并发与结果回填

建议字段：

- `invocation_id`
- `session_id`
- `task_id`
- `lane_id`
- `engine_name`
- `status`
- `input_ref`
- `output_ref`
- `approval_id`
- `idempotency_key`
- `started_at`
- `finished_at`

### 2.9 Artifact / Run / ReportDraft / Report

用途：

- 保留 artifact-first 的工作面优势
- 但将其纳入更大的 harness control plane
- `report_draft` 作为 report teammate 的共享中间工作对象，用于承载可修订、可恢复、可发布的总结过程

要求：

- `run` 与 `artifact` 必须可回链到 session / task / lane / engine invocation
- `report_draft` 必须可回链到 session / task / teammate / protocol thread，并可被 workspace projection 直接消费
- `report` 必须能被 workspace projection 直接消费
- final `report` 默认来自 `report_draft` 的发布结果，而不是强依赖一次 capability invocation
- 大体积、engine-specific、调试型数据优先存入 artifact store，由 control plane 通过 typed ref 引用，而不是塞入 canonical row
- session 级 artifact catalog 必须可被 master 与 teammate 共同读取；artifact 不是只给 UI 看的投影附件
- artifact 默认是 team 共享工作面的一部分，task / lane 决定焦点与归属，而不是决定可见性的唯一边界
- execution input artifact 必须先由 control plane 校验属于当前 session，才能被编译成 runner input；LLM 或用户提供的任意本地路径不得绕过 artifact catalog
- execution output artifact 只来自 runner declared output fetch，必须记录来源 run、engine invocation、tool contract、relative path 与 provenance
- preprocess 生成的中间文件也是 session artifact；它们可以作为后续 execution input，但必须保留来源 artifact 与转换工具 metadata
- `artifact.relative_path` 是 workspace-facing path，用于 UI 路径树、CLI 列表和 agent 对共享工作面的理解；它不是 Host 本地 filesystem path，也不能替代 artifact catalog 授权
- artifact storage 采用两层模型：Host-private Blob 层按 `content_digest` / `tree_digest` 封存与去重内容；Artifact 层按不可变 `artifact_id` 记录 session/task/lane/run/invocation、kind、format、validation、producer metadata、provenance、sealed digest 与展示用 `relative_path`
- Blob 路径只是 content-addressed locator，不是完整性证明。register 幂等复用、source snapshot 复用、materialize 读取和复制完成后都必须从实际 bytes/tree manifest 重算 digest；与 Artifact row 声明不一致时必须 fail closed、记录 quarantine/GC 原因并保留异常 Blob 供取证，绝不能以同 digest 路径存在为由跳过验证或覆盖异常内容
- 外部 provider 下载产物进入 Artifact 层时默认必须 sealed：Host 按实际下载 bytes 记录 SHA-256 `content_digest` / `sealed_digest`、provider、external id/source locator、format、retrieved_at 与 provenance。sealed 只证明 catalog 内容不可变且可授权搬运；PDB/FASTA 内容是否满足 fpocket、docking 或其它 execution tool 的业务输入要求，由对应 capability/tool validator 单独判断
- Host 已持有的 licensed/safe provider bytes 可通过 artifact boundary external ingress 进入同一 Blob/Artifact 两层模型：ingress 必须复制 bytes、重算 digest、安装只读 content-addressed Blob，再 immutable commit Artifact row。临时 Host 文件和 provider metadata 本身都不是 sealing 证明
- `storage_uri` 或后续等价 Host-private storage field 只能指向 sealed Blob/Artifact storage；不得指向 mutable sandbox `/workspace/output`、sandbox host path、runner path 或 Host repo path
- 同一 `relative_path` 可以存在多个 artifact leaf；重复 path 不覆盖、不合并、不作为唯一键，UI/CLI 只能用 `artifact_id` 区分，并可按 created_at、version、run 或 artifact id 排序
- executor sandbox 的 `/workspace` working copy 不是 canonical artifact store；只有 `artifacts.materialize`、`artifacts.register`、`artifacts.snapshot_code` 产生或回链的 Host-owned records 才进入 canonical workspace
- `artifacts.register` 的 canonical visible boundary 是 Artifact row commit；validation、Blob 写入、sealed digest recheck、provenance 完整性或 row commit 任一步失败都不得创建 visible Artifact record，也不得 fallback 到 mutable workspace path
- `artifacts.snapshot_code` 生成 `ArtifactKind.CODE` source tree snapshot，记录 `sandbox_workspace_id`、entrypoint、`source_tree_digest`、file digest manifest 和 parent snapshot；snapshot 必须先在同 Blob store 内构造并核对临时树，再原子安装为只读 sealed tree，后续复用仍重算 tree digest；后续 run、approval、SDK operation 与 registered output provenance 必须绑定 snapshot id / digest
- `ArtifactBoundaryService.read_registration_draft` 只读取并验证 immutable registration preimage；它不写 Blob、Artifact row 或 workspace registered ids。需要 bundle-level 原子性的 capability 必须先对全部 draft 完成 path、bytes、digest、metadata、validator 与 source snapshot 校验，再进入唯一 transaction
- AOX fixed 17 deliverables 由 Host-owned `artifacts.finalize_bundle` boundary 原子提交。它绑定 exact formal attempt、sealed selection、execution task/agent、sandbox run、source snapshot/tree 和 installed calculation receipts；任一 draft 或 unified validator 失败都保持零 visible artifact/document mutation
- successful AOX bundle transaction 同时提交 17 个 immutable Artifact row 与一个 `aox_final_deliverable_validation_receipt@1` EngineDocument。receipt 是 source-bound validation capability，不是 workspace 路径清单；persisted verifier 必须从 sealed bytes 和 exact bindings 重算，drift 时不得用于 attempt closure、execution completed 或 report handoff
- canonical artifact 来源仍是 artifact row 的关系字段与 `metadata_json`；workspace projection 中的 `artifact.provenance` 是从这些 canonical 字段派生的展示模型，不是新的数据库字段或 migration 要求

`report_draft` 建议最小字段：

- `draft_id`
- `session_id`
- `task_id`
- `owner_agent_id`
- `status`
- `title`
- `summary`
- `content_ref`
- `published_report_id`
- `created_at`
- `updated_at`

### 2.10 Canonical Relationship Defaults

V3 control plane 的 canonical 关系默认如下：

- `session` 是 repository binding pin、agent workspace generation/capability lease/retirement、task、lane、approval、inbox、memory、agent member、runtime signal、engine invocation、artifact、run、report draft 与 report 的顶层锚点
- `task` 是 teammate delegation、lane focus、approval、engine invocation、artifact lineage、report draft、report 与 protocol thread 的默认业务锚点
- `lane` 只表达隔离执行上下文；它不能替代 task 业务语义，也不能成为 artifact 可见性的唯一边界
- `approval` 绑定具体 requested action、task/lane/invocation/step 与 plan digest；approval resolve 是唯一用户级 approval 状态入口
- `inbox` 和 `agent_runtime_signal` 共同表达 teammate 协作与唤醒；message 负责协议内容，signal 负责调度语义
- `engine_invocation` 只标识 capability engine 局部运行；其结果必须回写 artifact、run、report draft、task 或 activity 等 control-plane object
- `artifact` / `run` / `report_draft` / `report` 是共享 workspace 工作面，不是某个 engine 的私有输出缓存

## 3. Workspace Projection

V3 的 UI / CLI 不直接读取 raw internal state，而是读取一个统一 projection。

最小 projection 分区：

- `session`
- `task_board`
- `lane_board`
- `pending_approvals`
- `inbox`
- `memory`
- `delegation`
- `artifacts`
- `report_drafts`
- `reports`
- `capabilities`
- `agent_capability_leases`
- `runtime_state`
- `activity_feed`
- `repository_binding`

其中推荐的阅读关系是：

- `conversation` 看用户与 master agent 的往来
- `repository_binding` 看当前 session 的 immutable binding id/version、safe service identity、object format、exact base、policy digest、lifecycle 与 allowed ref classes；它不显示 Host root、upstream URL、private endpoint 或 credential
- `task_board` 看内部工作如何被拆解和推进
- `delegation` 看 resident team roster、teammate 生命周期、哪些 teammate 正在推进哪些 task、持有哪些 correlation thread、是否有 unread wakeup
- `agent_capability_leases` 看 public owner、generation reservation/readiness、lease lifecycle、closed capability names、safe target/policy digest、parent provenance 与 revocation/retirement facts；缺失 exact ready+active generation 时必须显示 `provisioning_required`，存在 durable retirement request 时显示稳定的 non-runnable retirement blocker而不泄漏provider/proof locator
- `lane_board` / `capabilities` 看 task 在什么执行上下文里运行
- `report_drafts` 看 report teammate 正在如何组织、修订、准备发布交付物
- `artifacts` 看 agent team 当前共享工作面中已产出的证据、结果与中间产物
- `runtime_state` 看只读诊断：runtime/signal/agent/invocation 层 attention、awaiting `task.finish`、以及 task business status 的区别

workspace projection 必须足够恢复 UI 和协作状态：刷新浏览器或恢复 CLI 后，调用方应能从 projection 重建 conversation timeline、task board、resident teammate roster、pending approvals、lane/artifact/report 状态与 capability invocation 摘要，而不依赖浏览器本地缓存、raw graph state 或临时 prompt 内容。

`agent_capability_leases` 与 engine `capabilities` 是两个不同 read model：前者只投影
agent/generation 的 admission authority，后者投影 capability invocation/output。前者不得暴露
bearer、signing material、private service locator/namespace、Host path 或 workspace secret，也不得把
private generation bytes、credential state 或 pending lease 投影为 publication/shared truth。

`runtime_state` 是 projection / diagnostic，不是新的业务判题器。它可以标记 `runtime_signal_failed`、`agent_turn_failed`、`runtime_attention`、`needs_attention` 或 `outcome_unconsumed` / `capability_outcome_ready`，但不得自动把 task 写为 `completed` / `failed`。terminal capability outcome 只表示可消费的 evidence 已 ready，并可用于 wake owner；task 的业务 terminal state 仍只能由 `task.finish` 或已文档化机械迁移写入。

`artifact` catalog 是 canonical 后端台账。`SessionArtifactRecord.storage_uri` 是 Host-private 字段，只能被 execution compiler、sandbox runner、preprocess adapter、controlled artifact readers 等后端代码用于授权 staging 或受控读取；它必须指向 sealed storage 或其它 Host-owned immutable backend，不是 workspace/API/agent read model 字段。

`workspace.artifacts[]` 默认带 `artifact_id`、`kind`、`title`、`description`、`relative_path`、task/lane/invocation/run 关系字段、清洗后的 `metadata`，以及 projection-derived `provenance`。UI 默认按 `relative_path` 构造路径树；重复 `relative_path` 不合并，叶子身份始终是 `artifact_id`。`provenance` 固定展示 task、lane、invocation、run、producer/source、format、provider/external id/source locator、source/input/preprocess artifact ids、runner/pipeline id、code digest 与 tool contract 摘要。普通 workspace projection 不把 Host local path、runner staging path、`storage_uri`、`source_storage_uri`、`intermediate_storage_uri` 或 private path 当作 artifact browser 字段。

`session_research_source_refs` 是 bibliographic/source identity 的 canonical row，不是 artifact metadata 副本。paper ref 可持久化 provider/external id、PMID、provider-supplied DOI、authors、venue/publication date、retrieved_at、request/response digest、safe provider provenance 与 sealed evidence artifact link；repository round-trip 和 workspace projection 保持这些字段。locator 只允许 query-free public HTTP(S) 地址；credential、private URL/header、Host path 和受限全文不得落库或投影。

Agent / public read model 只能通过 `artifact_id` 与安全 artifact 投影读取 catalog 和文本预览。agent 不得请求 Host 本地路径，也不得把 `storage_uri`、runner staging path 或 sandbox host path 作为 tool 参数、HPC 输入或用户可见输出。

## 4. Event Model

control plane 事件流由 `durable_event_records` 持久化，不以 Host 进程内 list/cache 为 truth。数据库分配的 `cursor` 单调递增并作为 SSE `id:`；public consumer 用 `after_cursor` 或 `Last-Event-ID` 重放，跨 Host restart 保留原 `event_id` 与 cursor。event row 只能 append；`event_id` 全局唯一，`llm.response.created` 的 `trace_id` 在 session 内唯一，identity/trace 冲突且内容不同时 fail closed。

不跨外部边界的 canonical command 必须在同一个 `BEGIN IMMEDIATE` UoW 中提交领域 mutation、durable event 和可选 `command_receipt_records`，event insert 失败必须回滚领域 mutation。receipt 以 `(scope_ref, command_type, idempotency_key)` 唯一，完成后不可更新或删除；相同 request digest 返回首次响应且不得重复 mutation/event，不同 digest 使用同一 key 必须冲突。会跨 provider/runner/sandbox 的长流程仍不得持有长事务；其每个 bounded durable state transition 必须用后续短 UoW 和 lease/fencing 收口，不能把最终 receipt 当作 crash recovery 的替代品。

稳定事件类型包括：

- `session.created`
- `task.created`
- `task.updated`
- `task.claimed`
- `lane.created`
- `lane.bound`
- `lane.removed`
- `agent.spawned`
- `agent.woken`
- `agent.idle`
- `agent.status_updated`
- `agent.message.delivered`
- `agent.inbox_unread`
- `agent.delegated`
- `agent.task_claimed`
- `agent.shutdown_requested`
- `agent.shutdown_completed`
- `approval.requested`
- `approval.resolved`
- `memory.compacted`
- `inbox.delivered`
- `engine.invocation.started`
- `engine.invocation.updated`
- `engine.invocation.completed`
- `report_draft.updated`
- `report.generated`

## 5. Legacy Boundary

- `session` 是唯一顶层产品锚点。
- `approval`、`run`、`artifact`、`report_draft` 与 `report` 均以 session/task/lane/invocation 关系进入 control plane。
- Graph checkpoint 不作为产品顶层真状态来源。
- 若有 state 仍需存于 LangGraph，只允许是某 capability engine 的局部运行态。
- 不新增 `episode`、phase rail 或 supervisor-route 语义。

## 6. Qualification observer boundary

架构资格场景可以通过当前 repository、event、artifact、workspace 和 public projection 读取并闭合
canonical observations，但不得为了得到 green 直接 seed success、写 task terminal state、制造
approval/effect 或新增 campaign row。qualification report 与 AOX
`architecture_qualification` receipt 是 checkout 外 operator evidence，不是 control-plane object；
control plane 不以其存在推断 session/task 完成。AOX 只在独立 launch admission 边界验证 receipt，
失败必须先于 root、sandbox、provider、runner、Chrome 与 MICU effect。

qualification 的 owner/constraint registry 只登记 canonical owner、consumer 与 forbidden edge，
不复制对象值也不在产品 runtime 读取。current strategy-neutrality/world-fidelity 场景可以通过
public API、events、workspace 与 export 观察 trace 变换和 source-bound cause，但不能 seed 目标
终态、调用 private service、直接写 SQLite 或让 report 反向决定 product mutation。scripted
reachability 单独通过不构成 current admission。

## 7. Failure 与 scientific-attempt objects

顶层 canonical objects：

- immutable `FailureObservation`；active failure surface 只有 `failure.get`，agent
  hypothesis/恢复策略不另建 control-plane object；
- `ScientificAttemptAuthorization`、admission request 与 exact attempt scope；
- immutable selection revisions/head、operation/run occurrence bindings、
  dispositions、effect adoptions 与 artifact materializations；
- closure intent 与 immutable scientific-attempt closure。

它们不属于 graph state。authorization 只授予一组闭合资源/effect boundary；agent 仍选择
scientific chain。Host 导出的 occurrence universe 必须完整，四种 disposition 不删除事实。
closure intent 后禁止新增 binding/selection，closure 必须消费 exact quiescence receipt；但
closed attempt 仍只是一份 task 可引用 evidence，不能机械完成 task。

AOX current production evidence 读取这些对象生成
`aox_blank_world_attempt_bundle@4`。历史 `@2/@3` rows/bundles 不回填、不升级、不跨
attempt adoption。

### 7.1 Sandbox-local pre-admission failure chain

Host control validation 也是 canonical failure source。sandbox SDK 不在 RPC 前丢弃 malformed
HPC stage descriptor 或 provider output authority；Host 在 ControlledOperation admission 之前写 immutable
`FailureObservation(source_kind="sandbox_control_request")`，以
`hpc_stage_ref_required/validation/agent_can_replan/no_effect` 绑定 exact
session/workspace/source tree/agent/task/lane/origin signal、request digest 与 idempotency
digest，并证明 operation 未 admit、external dispatch 未开始。provider route 对非 canonical
`/workspace/output` descendant、path alias/traversal 或与 declared expected output 不一致的
caller value使用 `provider_output_path_invalid`，具有相同的 no-effect source binding。

terminal non-completed SandboxRun 另写
`FailureObservation(source_kind="sandbox_run")`。当且仅当它有一个 exact local cause 时，
`sandbox_exec_nonzero/runtime/agent_can_replan/terminal_known` wrapper 绑定该 cause、
selected scientific attempt 与 owner continuation。cause 与 wrapper 都是 append-only truth；
wrapper 不覆盖 earliest cause，也不把 no-effect validation 改成业务终态。

### 7.2 AOX public-only external operator

AOX 不再把 observer、barrier 或 automatic campaign driver 存入 control plane。测试员通过
public message/runtime-drain/approval/workspace/event commands推进；approval只在operator获得明确
授权时解决。Host仍独占上述 canonical
objects 与 mutation/external-effect authority。public command receipt 只证明一次请求的结果，
空 drain、无 wakeup 或进程退出不创建 task/attempt/campaign terminal。sealed attempt bundle
与 campaign decision 是 checkout 外 evidence，由 offline verifier/reducer 判定 eligibility，
不能回写或替代 control-plane truth。external operator不调用generic scientific mutation/
finalizer，不保存agent action order，也不把incomplete canonical state纠正为规定的handoff；agent
策略与pure final-state acceptance保持分离。

## 8. Executor HPC login workspace control-plane

C8 增加 `executor_hpc_target_qualifications`、provision intents/workspace records/provision receipts、credential claims以及cleanup intents/receipts。workspace identity和remote locator一旦建立不可重绑；state transition使用optimistic `state_version`，且把provision和cleanup的response-loss状态分开。target qualification不可变并绑定credential provider、authenticator、OS principal policy、protected root、runner sidecar、toolchain与native positive/negative receipts；没有外部exact evidence verifier时不得写activation。

Shared `SessionWorkspaceProjection.executor_hpc_workspaces`只投影opaque workspace id、remote generation、closed lifecycle与safe timestamps。只有exact owner且lease仍active时，agent restore context/tool result才额外得到binding/generation、login alias、remote path/root digest和credential audience；raw credential、secret、Host path、runner sidecar与其他owner locator始终不投影。
