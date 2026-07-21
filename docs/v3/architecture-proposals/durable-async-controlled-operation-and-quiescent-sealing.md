# Deferred: durable async controlled operations and quiescent sealing

Status: implemented by `runtime-hpc-reliability-refactor` for single-Host durable
execution, attached-process delivery, and generic mutation freeze/receipt/seal.
Process-isolated hard-kill and distributed writers remain deferred.

Stable contract: [`../07-runtime-hpc-reliability.md`](../07-runtime-hpc-reliability.md).
The decision-boundary and current-facts sections below are the pre-refactor baseline.

重构收敛说明：本文继续作为 external-operation 与 quiescence 的详细设计；`ControlledOperationExecution` 是 external effect 的 canonical owner，相邻 admission/delivery/continuation 草图只能作为其周围的 facets 实现，不能成为并列 operation 真状态。统一 ownership 与 decision gates 见
[`runtime-hpc-reliability-refactor-roadmap.md`](runtime-hpc-reliability-refactor-roadmap.md)。

## Decision boundary for the current Goal

r14 暴露的不是一个可以通过“把某个 timeout 调大”修复的局部参数问题，而是三个本应
独立的生命周期被同一个同步调用栈包裹：

1. sandbox 内 Pipeline SDK 的一次逻辑调用；
2. Host 对真实外部 provider operation 的提交、轮询、结果物化；
3. agent turn、public `/runtime/drain` 与 live attempt 的请求/封存生命周期。

当前 `bio.hmmer_search` 可以在 Host adapter 内轮询 EBI HMMER 最长 `1800s`，而
在 r14 失败现场，`sandbox.exec` 的公开资源上限是 `900s`，cutover public drain/request 与整个 attempt 的
deadline 又同为 `1800s`。sandbox SDK 通过 Unix control socket 同步等待完整 adapter
result；Host control worker 也在同一个 handler 中同步运行 adapter。结果是 sandbox 或
HTTP transport 先超时并不意味着 adapter writer 已停止：旧 worker 仍可能完成 provider
轮询、写 SQLite、登记 artifact 或完成 operation。r14 进一步观察到 attempt bundle 已在
world 尚未 quiescent 时封存，随后出现 SQLite mutation。该 bundle 因此永久不具备 cutover
资格；“封存后没有被 verifier 当场发现变化”不能补救缺失的静默证明。

这个故障横跨 Pipeline SDK、sandbox supervisor、controlled-operation repository、provider
adapter、runtime scheduler、Host shutdown、live harness、artifact/ledger 与 evidence
verifier。r25 的真实计时进一步否定了“先把全局 timeout 放宽”的 containment：EBI HMMER
job 约 `24s` 已 terminal，旧 adapter 随后却用约 `52m` 物化 `686` 个 result payload。该路径
还把 terminal poll 的默认 `page_size=50` payload 当作第一页，然后从 `page=2` 开始按
`page_size=100` 拉取，确定性漏掉索引 `50..99`。provider 的完整结果是 `68,592` 条，旧路径
只封存 `68,542` 条；单纯允许 request 再等待更久只会更稳定地封存错误结果。

当前 Goal 允许的局部修复是不新增 durable operation 真状态的 correctness/performance 修复：terminal
poll payload 只证明 job terminal；结果物化必须从 `page=1` 开始使用同一 page width，当前 route 固定
`page_size=1000`，完整结果应为 `69` 页；publish 前同时校验 page coverage、重复/缺口、page metadata
与 provider `nreported`。任一不一致严格 fail closed。现有分层预算先保持不变：HMM-capable
`sandbox.exec=3600s`，formal session/public request 至少 `7200s`；只有 corrected live recovery 证明
某一语义层级仍不足时才依据分层计时重新决策，不能继续把全局 timeout 调大。
这项小修不提供 durable async、checkpoint、restart recovery 或 cancellation receipt，也不被称为本文
架构已实现。当前 Goal 不实施本文迁移，不吞掉 late result、不忽略 SQLite diff，也不在封存后重算
digest 来掩盖问题。本文件只记录完整目标架构、迁移与验收。

近期约束保持不变：

- 一个可信 Host 进程拥有运行时权威；
- canonical control plane 继续使用单进程 file-backed SQLite；
- runner 只供可信 Host 使用；
- 不引入 Redis、Celery、Kafka、跨进程 SQLite writer 或新的顶层 workflow graph；
- agent 继续决定科学策略、调用顺序、是否基于结果重试或早停；
- harness 只呈现并执行真实约束，不替 agent 选择替代 plan 或推导 task 业务终态。

## Relationship to existing proposals

本提案与现有三份 deferred proposal 相邻但不重合：

- [non-blocking supervised continuation](nonblocking-supervised-continuation.md)
  主要解决 approval park/resolve/resume 不应长期占住 agent signal、session lease 和同步
  drain。本文把同一原则扩展到**已经批准但仍在远端运行的长时 controlled operation**，
  并定义 provider handle、分段 polling、result delivery 和 operation timeout。
- [process-isolated live-attempt supervision](process-isolated-live-attempt-supervision.md)
  解决同进程 writer 永久不退休时，harness 如何由 OS 有界强制停止并只生成 parent-owned
  fatal evidence。本文定义正常产品路径如何主动达到 mutation quiescence；进程隔离是
  最终 fail-stop，不替代正确的 async operation state machine。
- [bounded streaming sandbox stdio capture](bounded-streaming-sandbox-stdio-capture.md)
  解决 stdout/stderr 内存与完整性边界，不负责外部 operation 的 ownership、deadline 或
  result delivery。

未来实施时应共享 continuation、lease/fencing、writer registry 与 public projection 基础
类型，不能让四份提案各自生成相互冲突的队列和“真状态”。本提案中的 operation execution
record 是既有 `ControlledOperation` / `EngineInvocation` / `SandboxRun` 的窄执行扩展，不是
第二套 task board 或 workflow engine。

## Observed failure anatomy

### r25: remote terminal 与 result materialization 必须分开计时

r25 对同一个已经 terminal 的 HMMER job 做了只读恢复诊断：用统一 `page_size=1000` 从
`page=1` 到 `page=69` 可恢复 `68,592` 条命中，最后一页 `592` 条；旧 adapter 的组合结果是
`68,542` 条，差集恰好为索引 `50..99` 的 `50` 条。该缺口不是低分尾部：这 `50` 条分数均高于
AOX `200` 分阈值，因此会改变下游科学集合，r25 永久 non-eligible。

这份证据把一个 wall-clock 现象拆成两类问题：

1. remote lifecycle 约 `24s` 到达 terminal，未触及长时 remote deadline；
2. 同步 result materialization 额外发起约 `685` 次 result GET，连同 terminal payload 共形成
   `686` 个 payload，并占用约 `52m`；
3. mixed-width pagination 又产生科学完整性缺口，耗时再长也不能补救。

因此大规模结果分页的 durable checkpoint、park/resume、crash recovery 和 quiescent sealing 仍属于
本文未来架构；本 Goal 的同宽分页、`page_size=1000` 与 `nreported` closure 只是先修复一个有明确
局部边界的 adapter bug。后续架构不得把 terminal poll payload 隐式复用为任意 page width 的数据页，
也不得把“job terminal”投影成“result 已完整物化”。

### Current synchronous stack

当前主要调用关系可概括为：

```text
agent turn
  -> sandbox.exec tool handler                         <= r14 active limit 900s
    -> sandbox Python process
      -> openzyme_pipeline.bio.hmmer_search(...)
        -> blocking Unix control-socket request
          -> Host control-socket worker
            -> adapter_executor(...)
              -> EBI submit
              -> blocking poll loop                    <= remote poll 1800s
              -> result page fetch
              -> artifact/catalog/operation SQLite writes
        <- only one final SDK response
    <- sandbox process terminal
  <- synchronous runtime drain HTTP response           <= r14 request 1800s
<- live attempt deadline / evidence collection         <= r14 attempt 1800s
```

这里至少存在六种不同含义的“等待”，但实现把它们压成一个 wall-clock call：

- sandbox CPU/本地进程 active runtime；
- sandbox 等待 approval；
- sandbox 等待 Host-owned external operation；
- provider 单个 HTTP request 的 transport timeout；
- provider remote job 的业务 poll deadline；
- agent/drain/attempt 的 orchestration deadline。

approval wait 已经从 sandbox active elapsed 中排除，但 approved adapter execution 没有。
因此一个完全健康、只是超过 `900s` 的 EBI job 会先触发 sandbox timeout。杀掉 sandbox
client 只会关闭或破坏 control-socket transport；正在 Host worker 中执行的 Python adapter
并不会因 peer disconnect 自动被安全取消。

### Why transport timeout is not cancellation

transport timeout 只证明某个 caller 不再等待 response。它不证明：

- EBI 已取消或停止 remote job；
- Host adapter 的 poll loop 已退出；
- adapter 不会再 fetch result pages；
- artifact bytes 没有正在写入临时或最终位置；
- controlled operation / continuation / run / event row 不会再提交；
- MICU 或其它 provider ledger 不会再结算；
- detached callback、thread 或 task 已退休；
- public drain handler、repository scope 或 SQLite connection 已关闭。

同理，`sandbox_exec_timeout`、HTTP `ReadTimeout`、attempt deadline、ASGI response 已返回、
server thread 的 `should_exit` 和“最近一段时间文件没变化”都不是 cancellation receipt，也
不是 writer quiescence receipt。

### Why post-seal mutation is fatal

eligible evidence 的基本前提是 bundle 中的 SQLite snapshot、event high-watermark、artifact
manifest、provider receipts 与 ledger-after 都来自同一个已经闭合的 world。若封存后仍有
canonical mutation：

1. bundle digest 只证明一个中间瞬间，不证明 attempt 的最终事实；
2. operation 可能在 bundle 中是 running/failed，却在真实 DB 中成为 completed；
3. artifact catalog 与 sealed bytes 可能不一致；
4. ledger-after 可能漏掉已经发生的真实调用或结算；
5. fail-closed blocker 与 later success/failure 可能同时存在且没有权威仲裁；
6. 离线 verifier 无法判断哪个 snapshot 是 canonical terminal world。

因此 post-seal mutation 不是“补一条诊断”即可接受的 warning。任何观察到的 post-seal
canonical write 都使该 attempt 永久 non-eligible，并必须阻止同 root 上重新封存。

## Harness principles

### Preserve agent strategy freedom

- agent 仍调用 `bio.hmmer_search`、选择参数、根据结果决定 UniProt/HMMalign/CD-HIT 分支；
  harness 不因为 operation 变成 async 就固定科学流程或自动追加下一步。
- approval 与 execution policy 只冻结 exact operation digest、输入、资源与 route；它不授权
  harness 在 timeout 后缩小数据库、换 provider、降低阈值或创建 replacement operation。
- external operation terminal 只产生可消费 capability outcome。task 是否完成、失败、阻塞、
  重试或早停仍由 agent 通过显式工具决定。
- agent 不需要理解 provider job id、poll URL、lease、worker 或 SQLite 细节。world projection
  应提供稳定、结构化、可行动的状态和 safe diagnostic。
- async 不能退化为 agent 反复调用 status 的 busy loop。scheduler 在重要 durable transition
  后唤醒 owner；agent也可在需要时读取状态，但不承担后台 supervision。

### Harness owns mechanics and truth

- Host 在 external submit 前建立 durable identity 与 idempotency intent；
- Host 负责 provider polling、quota、approval、cancellation、reconciliation、artifact
  materialization、result delivery 与 mutation quiescence；
- SQLite state transition、event、outbox 与 command receipt 使用短 UoW；
- 任一长等待发生在 transaction 外，并由 lease/fencing 约束 writer；
- public request、agent turn、sandbox active compute、remote job 与 attempt seal 各有独立
  deadline，不能互相冒充。

## Non-goals

- 不承诺所有外部 provider 都具备真正的 server-side cancellation 或 exactly-once submit。
- 不把 provider job id、poll URL 或 backend credential 暴露给 sandbox、agent、UI 或 bundle。
- 不通过序列化任意 Python 栈实现通用 crash-safe checkpoint。
- 不让 sandbox 自己创建 background thread 绕过 Host supervision。
- 不把一次 accepted operation 当作 completed result，也不在 remote outcome unknown 时自动
  重投。
- 不让 attempt verifier、campaign reducer 或浏览器成为 canonical operation writer。
- 不把 async queue 变成新的 task/workflow/phase truth。
- 不在第一阶段支持多个 Host 进程同时 claim SQLite 中的 operation work。
- 不允许为兼容旧同步 caller 同时运行一次 async 和一次 sync external dispatch。
- 不用更大的 timeout 代替 durable continuation、cancellation fence 或 seal barrier。

## Target lifecycle

### Logical phases

一次长时 controlled operation 应拆成以下 durable phases：

```text
SDK submit
  -> validate exact plan/runtime/input/output identity
  -> persist operation + dispatch intent
  -> return/park on an opaque Host operation handle

Host execution scheduler
  -> claim dispatch lease
  -> submit once or reconcile prior submit
  -> persist private provider handle
  -> poll in bounded slices, releasing worker between polls
  -> stage and verify provider result
  -> atomically publish terminal operation result

Sandbox continuation
  -> observe result-ready for the exact original SDK call
  -> resume attached/journaled sandbox execution
  -> finish sandbox.exec
  -> publish original tool-call result

Agent runtime
  -> wake owner only after the original tool result is durable
  -> agent evaluates scientific outcome and chooses next action
```

SDK authoring 可以继续提供同步外观，但该外观必须由 Host suspension 语义实现，而不是由
一个 control worker 同步执行 1800 秒 adapter：

```python
# existing ergonomic form; internally submit + await/park
hits = bio.hmmer_search(...)

# optional explicit form for pipelines that can overlap independent work
handle = bio.hmmer_search.submit(...)
hits = operations.await_result(handle)
```

显式 form 只能扩大 agent 可表达的并发策略，不能成为 AOX workflow 的强制顺序。默认同步
form 与显式 form 对同一 canonical call identity 必须生成相同 operation digest 与 result
semantics。

### Proposed state model

在既有 `ControlledOperation` 旁增加 versioned execution detail，或以等价窄字段扩展，不建议
复制完整 operation payload：

```text
ControlledOperationExecution@1
  execution_id
  operation_id / operation_digest
  session_id / task_id / lane_id / agent_id
  sandbox_run_id / sandbox_workspace_id
  source snapshot / runtime identity / SDK call identity

  lifecycle_state:
    accepted
    waiting_approval
    dispatch_ready
    dispatch_claimed
    submit_in_doubt
    remote_pending
    poll_ready
    poll_claimed
    result_staging
    result_ready
    delivery_ready
    delivered
    failed
    cancel_requested
    cancelling
    cancelled
    outcome_unknown
    recovery_failed

  provider_category / route_policy_id
  private_backend_handle_ciphertext_or_ref
  external_idempotency_key_digest
  dispatch_generation / state_version
  next_poll_at / remote_deadline_at
  result_envelope_digest / terminal_artifact_set_digest
  cancellation_reason_code / reconciliation_state

  claim_owner / claim_expires_at / fencing_token
  created_at / submitted_at / terminal_at / delivered_at
```

具体可合并状态，但必须保留以下语义差异：

- `dispatch_ready` 与 `remote_pending` 不同，前者尚未证明 provider 接收；
- `submit_in_doubt` 与 `failed` 不同，前者可能已产生外部副作用；
- `result_ready` 与 `delivered` 不同，前者可在 sandbox 已丢失时仍是真实科学结果；
- `cancel_requested` 与 `cancelled` 不同，请求取消不证明远端停止；
- `outcome_unknown` 与 retryable failure 不同，unknown 禁止盲目 resubmit；
- infrastructure terminal 与 task business terminal 完全独立。

### Opaque operation handle

Sandbox SDK 只得到 Host-issued opaque handle：

```text
sdk_operation_handle@1
  public_handle_id
  operation_id
  operation_digest
  sandbox_run_id
  SDK call index
  result schema id
```

在可信 Host / 单进程 SQLite 阶段，handle 可以是不可预测 ID 加 canonical row binding；不必
伪称它是跨 trust domain 的 cryptographic capability。即便如此，所有 lookup 仍必须验证
session、sandbox run、agent、source/runtime identity 和 SDK call index，禁止只凭一个 ID
跨 session 读取或等待。

handle 不包含：

- EBI job id 或 poll URL；
- Host path、SQLite rowid、worker/thread id；
- lease owner、expiry、fencing token；
- provider credential、request body 或 private response locator。

public workspace 可以展示 `operation_id` 和 safe state；opaque SDK handle 默认不需要出现在
UI。若为诊断投影，只展示 digest/ref，不提供可用于内部 claim/resume 的 token。

## Idempotency and external dispatch

### Canonical call identity

operation digest 至少绑定：

- session/task/lane/agent 与 originating agent step/tool call；
- sandbox run、workspace、source snapshot、SDK/runtime image identity；
- SDK module/function、route policy、provider/database logical name；
- canonical params digest；
- ordered input artifact ids + sealed digests；
- declared expected outputs 与 resource estimate；
- execution plan、approval 与 call-budget consumption identity；
- SDK call index或等价 deterministic call-site journal identity。

agent 重复发送相同 tool message 不足以复用 operation。复用必须由同一 canonical SDK call
identity 与同一 idempotency key/digest共同证明；不同 digest 使用同一 key fail closed。

### Dispatch journal

external submit 使用短状态转换：

1. `dispatch_ready -> dispatch_claimed`，分配新的 monotonic fencing token；
2. 持久化 `dispatch_intent`、external idempotency digest 与 request digest；
3. transaction 外执行一个 bounded provider submit request；
4. 将 provider acceptance receipt/opaque handle 与 exact fence 一起提交；
5. 进入 `remote_pending`，设置 `next_poll_at`；
6. 释放 execution lease。

若 provider 原生支持 idempotency key，Host 使用 sealed key并验证 replay receipt。若 provider
不支持（包括不能证明 EBI HMMER submit exactly-once 的情况），crash/timeout 发生在 submit
之后、acceptance handle 持久化之前时必须进入 `submit_in_doubt`。系统只允许按 provider
明确支持的 request lookup/reconciliation 查询；无法确认时保持 `outcome_unknown`，不能
因为 agent 或 scheduler 再次醒来就重发 HMM。

### Polling slices

EBI HMMER 的 `1800s` 代表 remote operation deadline，不应是一段持续占用 control worker 的
poll loop。每次 poll 是一个短 work item：

```text
poll_ready
  -> claim(fence N)
  -> one bounded HTTP request outside transaction
  -> persist observation/status under fence N
  -> terminal result | next_poll_at
  -> release claim
```

poll interval 由 adapter policy 决定，但每次 poll receipt、response digest、observed provider
status 和 monotonic attempt counter 都需 durable。scheduler 可以在同一 Host event loop/thread
pool中执行，不需要外部 queue；SQLite `next_poll_at` 是近期单进程实现的 durable queue truth。

provider response 为 terminal 时先写 Host-private staged bytes并验证 schema/digest，再进入
result publish transaction。polling worker不得在发现 terminal 后直接向已断开的 socket
send 一次“best effort”response并顺便写 catalog。

### Result materialization idempotency

- staged bytes 以 operation id + output role + content digest 唯一；
- temp write、fsync、validation、blob promotion、artifact row与operation result publish有明确
  顺序；
- duplicate terminal delivery复用已验证 bytes/row，不创建第二套 artifact id；
- conflicting bytes、metadata、provider response digest 或 output set使 operation进入
  `recovery_failed`，不得最后写入者获胜；
- result envelope 的 Host-owned origin、operation fence、artifact set digest 与 runtime identity
  必须共同验证后才能交给 SDK。

## Timeout hierarchy

### Timeout classes

所有配置必须使用带语义的独立字段，禁止一个 `timeout_seconds` 同时控制多层：

| Timeout | Bounds | Expiry semantics |
| --- | --- | --- |
| `provider_request_timeout` | 单个 submit/poll/result HTTP request | 本次 transport attempt 失败；不自动判定 remote job terminal |
| `external_operation_deadline` | 从 provider acceptance 到 terminal 的 remote lifecycle | 发起 cancel/reconcile；不是 sandbox timeout |
| `poll_lease_timeout` | 一个 worker 的单次 poll claim | lease 可被更高 fence 接管；旧 callback失去写权限 |
| `sandbox_active_compute_timeout` | sandbox 真正在执行本地代码的 active 时间 | 停止 sandbox process；不包含 approval/external-result parked 时间 |
| `sandbox_continuation_ttl` | attached/journaled sandbox 从开始到最终 delivery 的总 wall time | delivery recovery path；不隐式取消已接受 external operation |
| `agent_turn_timeout` | 一个 LLM/agent bounded turn | park 后应快速收口；不包裹 remote operation |
| `runtime_command_timeout` | operator/debug drain command 等待 admission/park 的时间 | command 返回 accepted/parked snapshot；不取消 operation |
| `attempt_deadline` | 一次 cutover attempt 从开始到 closure | 关闭 admission、请求 cancel/reconcile、进入 quiesce；未静默不得封存 |
| `campaign_deadline` | 多 attempt campaign governance | 不改变任一子 attempt 的 canonical operation state |
| `quiesce_timeout` | 正常退休 writer 的 grace | 超时后进入进程隔离 fail-stop；不是“忽略 writer 后封存” |

### Accounting rules

- approval wait 和 external-result wait 都不计入 `sandbox_active_compute_timeout`；sandbox
  本地预处理、Python循环和下游文件计算计入。
- provider sleep/poll wait 计入 `external_operation_deadline`，不计入 agent turn 或 public
  request。
- reconnect/restart不重置 remote deadline、attempt deadline、quota 或 call budget。
- timeout 使用 Host monotonic clock做进程内判断，同时持久化 wall-clock timestamp供恢复；
  恢复时使用最保守的剩余预算，禁止因 clock drift延长已到期 operation。
- public client disconnect既不取消也不续期 operation。显式 cancel command才改变
  cancellation state。
- task blocked/failed/completed不能由任一 timeout机械推导。

### Configuration validation

cutover pin 阶段应拒绝明显不可闭合的 deadline 组合。对于必须在 attempt 内完成的 route，
至少满足：

```text
provider_request_timeout < external_operation_deadline
poll_lease_timeout < external_operation_deadline
external_operation_deadline
  + cancellation/reconciliation grace
  + host quiesce grace
  + evidence materialization budget
  < attempt_deadline
attempt deadline < campaign deadline remaining
```

`sandbox_active_compute_timeout` 不再要求大于 external operation deadline，因为 parked external
wait不消耗 active compute。但 `sandbox_continuation_ttl` 必须覆盖该 route 的 external deadline、
结果 delivery 与剩余本地计算，或明确选择不支持 attached continuation 的 async authoring
模式。

r14 的 `sandbox.exec=900s`、HMMER poll=`1800s`、attempt=`1800s` 组合必须在 live admission
前 fail closed，而不是跑到三层同时到期后再仲裁。

## Lease and fencing model

### Separate leases

至少分离四类 ownership：

1. **session runtime lease**：谁可以 claim/推进 agent signals；
2. **sandbox execution lease**：谁拥有一个 sandbox run/process epoch；
3. **controlled-operation execution lease**：谁可以 submit/poll/materialize某一 external
   operation；
4. **attempt mutation/seal lease**：attempt 是否仍允许注册 writer，或已进入 freeze/seal。

任何一类 lease 都不能被另一类 token 替代。尤其：

- remote operation pending时不占 session runtime lease；
- agent turn park 后不保持原 runtime signal `CLAIMED`；
- provider poll worker不能凭 sandbox process仍活着写 canonical state；
- seal barrier不能只检查HTTP request count，而要检查全部 operation/sandbox/artifact writer。

### Fencing token rules

- 每次 operation claim、sandbox process epoch与attempt freeze都分配单调 fencing token；
- writer 在外部调用前做 fence preflight，在每个 SQLite commit中再次比较 token/state version；
- artifact promotion、catalog insert、event append、continuation complete与result delivery均携带
  exact token；
- lease expiry后旧 worker即使拿到成功 response，也只能写 Host-private late-callback diagnostic，
  不能写 canonical operation/artifact/event；
- cancellation 或 attempt freeze递增/撤销相关 writer epoch；
- SQLite repository必须在 transaction内校验 fence，不能只依赖进程内 `Event`；
- 同一 token 的重复相同 terminal commit按幂等返回；冲突 payload fail closed。

在近期单进程模型中，token仍有价值：thread pool、control worker、async callback和client
timeout足以产生 stale writer，不需要多进程才会发生竞态。

## Cancellation and reconciliation

### Cancellation is a protocol

显式 cancellation 流程：

```text
running/pending
  -> persist cancel_requested + reason + new fence
  -> stop scheduling new polls under old fence
  -> call provider cancel if supported (bounded request)
  -> reconcile remote state
  -> cancelled | completed-before-cancel | outcome_unknown
  -> close result-delivery path consistently
```

`attempt_deadline`、operator cancel、approval rejection、Host shutdown和sandbox loss使用不同
reason code，不应全部映射成 `timeout`。policy可以决定“sandbox delivery lost后是否仍完成已接受
provider operation”，但该决定必须在 plan/config 中预先声明，不能由 cleanup临时猜测。

### Race arbitration

- terminal provider success与cancel request并发时，由SQLite expected state/version决定唯一
  canonical winner；
- 若 success receipt在cancel transaction之前已经持久化，允许完成并标记
  `completed_before_cancel`；
- 若cancel fence先提交，旧success callback无写权限，结果只能进入private quarantine；
- provider声明cancel accepted仍需确认terminal cancelled或达到明确reconciliation终态；
- provider不支持cancel时保持poll/reconcile至deadline，或进入`outcome_unknown`；
- unknown outcome禁止启动same-operation replacement，除非agent创建新plan且policy明确允许，
  同时旧attempt保持non-eligible。

### Sandbox termination

sandbox process被终止与external operation被取消是两个事实：

- 终止sandbox先撤销delivery/process epoch，防止旧socket response改变workspace；
- external operation按预声明policy继续、取消或reconcile；
- 已经result-ready但尚未delivery的结果继续作为canonical capability outcome存在；
- agent得到`delivery_recovery_required`或直接读取result artifact，由agent决定是否重新运行
  downstream script；
- harness不得因为sandbox死掉而再次submit provider request。

## Host mutation quiescence

### Structured writer registry

Host 必须为每个 attempt/session epoch维护结构化 writer scope。所有可能改变 canonical attempt
world 的工作都通过一个 registry factory创建：

- ASGI/public mutation handler；
- background runtime tick与agent turn worker；
- sandbox process/supervisor/control connection；
- controlled-operation submit/poll/reconcile worker；
- provider callback与ledger reservation/charge commit；
- artifact temp writer、validator、promoter、catalog writer；
- continuation/result delivery与outbox/event publisher；
- runner/HPC reconciliation/fetch callback；
- SQLite write UoW。

writer scope具有parent、attempt epoch、owner type、stable operation/ref、fencing token与lifecycle。
child thread/task/process只能由已登记parent派生；raw detached thread/task默认禁止。scope返回前
必须join/cancel并确认child set为空。

registry只追踪已知writer还不够。repository write入口必须要求有效`MutationAuthority`：

```text
MutationAuthority@1
  attempt/session epoch
  writer_scope_id
  owner kind + canonical ref
  mutation fence token
  seal generation
```

没有authority、authority已关闭、epoch不匹配或seal generation过期的写在SQLite transaction
内拒绝。这样即使代码错误留下late callback，它也不能形成post-seal canonical mutation。

### Quiescence state machine

attempt lifecycle增加Host-private但可证明的状态：

```text
OPEN
  -> DRAINING_ADMISSION
  -> CANCELLING_OR_RECONCILING
  -> FREEZING_WRITERS
  -> QUIESCENT
  -> SNAPSHOTTING
  -> SEALED
```

- `DRAINING_ADMISSION`：拒绝新message/drain/approval/operation等会产生writer的命令；只允许
  exact cleanup/reconciliation path。
- `CANCELLING_OR_RECONCILING`：按operation policy收口所有非terminal external work。
- `FREEZING_WRITERS`：获取exclusive seal generation，禁止注册普通writer，等待所有旧
  generation scope退休。
- `QUIESCENT`：registry active count为零，且所有canonical repository write都被freeze fence
  阻止；这是一道generation barrier，不是sleep后观察无变化。
- `SNAPSHOTTING`：只有sealer authority可执行checkpoint、manifest与bundle写入；产品数据
  writer仍被禁止。
- `SEALED`：root identity和最终manifest被原子提交；任何attempt-scoped mutation永远拒绝。

若失败收口必须写canonical blocker，该写发生在`FREEZING_WRITERS`之前；freeze之后不得再
“补充”产品状态。snapshot/sealer metadata写入独立parent-owned evidence area或预留的seal
record，不应重新打开已冻结产品repository。

### Quiescence receipt

eligible bundle应包含可离线验证的`host_mutation_quiescence_receipt@1`，至少绑定：

- attempt/session/commit/config/workflow/root identity；
- seal generation与freeze timestamp；
- writer registry high-watermark、final active count `0`和scope completeness root；
- terminal/nonterminal controlled-operation set digest；
- sandbox/process/continuation closure set digest；
- final durable event cursor与outbox closure digest；
- SQLite main/WAL/SHM identity、checkpoint/integrity result与snapshot digest；
- artifact catalog/blob manifest digest；
- provider/MICU ledger-after authority snapshot digest；
- no-post-freeze-write counter与rejected-late-write diagnostic digest；
- sealer implementation/schema identity。

receipt由可信Host生成不等于可以省略离线交叉验证。verifier必须重算SQLite、artifact、events、
ledger和bundle之间的关系，并拒绝缺字段、unknown writer kind、未闭合operation、WAL漂移、
seal generation不一致或root在seal后变化。

### What does not prove quiescence

以下事实单独或组合都不够：

- HTTP client/thread已经return；
- ASGI request counter为0；
- `sandbox.exec` row为terminal；
- control socket path已unlink；
- sandbox process PID不存在；
- SQLite connection当前没有active transaction；
- `time.sleep()`后两次stat相同；
- artifact manifest已写出；
- offline verifier在某一瞬间通过；
- server收到shutdown signal。

必须同时有writer admission fence、旧generation retirement和repository commit fence。

## Failure sealing order

任何positive、negative或driver-failure attempt都使用同一closure protocol。推荐严格顺序：

1. **Persist authoritative blocker/outcome intent**：在普通writer仍开放时，以短UoW记录最早
   authoritative failure、safe secondary diagnostics与attempt closure intent；不推导task
   terminal。
2. **Close new admission**：拒绝新message/drain/approval/operation；固定event high-watermark
   下界。
3. **Stop agent scheduling**：不claim新signal；收口当前agent turn或park outcome。
4. **Fence sandbox delivery**：阻止旧socket/client把结果写回workspace；按policy退休或park
   sandbox process。
5. **Cancel/reconcile external operations**：对每个handle形成terminal、cancelled或unknown
   outcome；unknown使eligible seal失败。
6. **Retire adapter/runner/artifact workers**：等待所有registered child scopes和callback结束；
   stale fence拒绝late commit。
7. **Drain canonical outbox/events and ledger commits**：形成final cursor与ledger-after；不得在
   ledger snapshot后再允许provider charge writer。
8. **Acquire exclusive seal generation**：repository进入freeze，只剩sealer authority。
9. **Prove writer registry zero**：校验scope completeness和所有operation/sandbox terminal set；
   不用quiet period替代。
10. **Checkpoint SQLite and fsync data roots**：解释或清空WAL/SHM，执行integrity检查，固定
    filesystem identity。
11. **Materialize immutable snapshots/manifests**：复制/读取sealed bytes，计算bundle与artifact
    tree digest。
12. **Run offline verifier**：从只读snapshot重算合同；发现漂移直接non-eligible。
13. **Atomic no-replace seal**：提交final bundle/receipt并fsync parent目录。
14. **Post-seal mutation trap**：repository持续拒绝同attempt写；任何拒绝事件记录在attempt
    root之外的Host-private/campaign fatal log，并永久降级该attempt。

步骤5或6无法有界收口时，当前同进程模式不得跳到步骤8。它必须保持fail-stop/block；未来
由process-isolated supervisor终止整个child writer authority，确认OS retirement后，只能生成
parent-owned fatal non-eligible evidence，不能把partial attempt root包装成普通failure bundle。

## Restart semantics

### Bootstrap recovery scan

Host 启动时在接受普通mutation前扫描所有nonterminal operation execution：

- 验证operation、plan、approval、runtime identity、input artifacts与state version；
- 使旧process/thread lease过期并分配新Host epoch；
- 按状态决定reconcile、resume poll、resume materialization、resume delivery或显式
  `recovery_failed`；
- 先完成in-doubt external operation与ledger reconciliation，再允许same-scope新attempt；
- append stable recovery events，不重写历史event。

### State-specific behavior

- `dispatch_ready`：尚无submit attempt receipt，可在新fence下正常dispatch。
- `dispatch_claimed`且无已发请求证据：只有能证明旧worker未跨外部边界时才重新dispatch；
  否则进入`submit_in_doubt`。
- `submit_in_doubt`：只做provider-supported reconciliation，禁止blind retry。
- `remote_pending/poll_ready`：若private handle和identity完整，继续poll同一job和原deadline。
- `result_staging`：按staged byte digest、artifact manifest与fence恢复或丢弃未promote temp；
  不重新submit。
- `result_ready/delivery_ready`：复用canonical result envelope，恢复delivery；不重新调用provider。
- `cancel_requested/cancelling`：继续同一cancel/reconcile protocol，不把restart当作cancel成功。
- `outcome_unknown`：保持needs-attention并阻止隐式replacement。

### Sandbox continuation strategies

近期至少明确两种闭集strategy：

- `attached_sandbox_process`：正常Host进程内可在external result ready后恢复原process；Host
  restart后不能重建任意Python栈。operation result仍可保留，但continuation进入
  `delivery_recovery_required`，owner agent收到可行动的结果/诊断并自行决定downstream策略。
- `journaled_sdk_call_boundary`：仅对versioned、可证明source/runtime/workspace epoch和SDK call
  journal的pipeline启用。恢复从已完成call边界继续，所有先前external calls按canonical
  result replay，不重新产生副作用。

默认是前者；不能把“重新运行整段Python，期待idempotency命中”冒充journaled resume。未来
若实现后者，journal格式、local file effects、random/time/env输入和每个call boundary都需
单独设计与测试。

## Public projection and API semantics

### Workspace projection

`workspace.capabilities` / `runtime_state`可以投影：

- operation id、logical capability和safe provider category；
- status：waiting approval / queued / running / waiting remote / cancelling /
  result ready / delivered / failed / outcome unknown；
- submitted/updated/terminal timestamps；
- bounded progress，例如poll count、last safe provider status、next check time；
- originating task/lane/agent/sandbox run/tool call关系；
- retryable、needs_attention与safe error code；
- result artifact refs（仅terminal verified时）；
- delivery status与owner wakeup状态。

不得投影：

- provider job id、poll/result URL、raw request/response；
- SQLite ids、Host path、socket、PID/thread/worker name；
- lease/fencing token、claim expiry、private checkpoint；
- credential、NCBI email、runner config或private log；
-未经验证的partial artifact。

### Events

建议复用/扩展durable engine/operation events：

```text
controlled_operation.accepted
controlled_operation.waiting_approval
controlled_operation.dispatch_ready
controlled_operation.remote_started
controlled_operation.progress
controlled_operation.cancel_requested
controlled_operation.result_ready
controlled_operation.delivery_ready
controlled_operation.delivered
controlled_operation.failed
controlled_operation.outcome_unknown
sandbox.continuation_parked
sandbox.continuation_resumed
host.attempt_quiescing
host.attempt_quiescent
```

事件是projection refresh/replay事实，不是worker queue的唯一claim机制。高频poll不能每次都向
public event流写大量噪音；可按state change或bounded interval投影，完整request receipt留在
受限artifact/private log。

### Runtime command behavior

`POST /runtime/drain`或background tick在触发长operation后，只等待到以下任一bounded outcome：

- operation/continuation被durably parked；
- immediate terminal result已提交；
- admission/validation失败已提交。

它不等待remote job terminal。response带accepted/parked counters和public high-watermark，
但不拥有后续operation。client timeout也不改变operation。approval resolve同样只做decision/
readiness短事务，不在request中运行adapter。

取消如果对普通用户开放，必须是单独typed command，绑定expected state/version与幂等key；
不能复用generic task update或approval reject。cutover harness不得为赶deadline静默调用取消，
除非pin config明确声明该cleanup policy并把receipt纳入evidence。

### UI behavior

- approval card只控制frozen operation plan；批准后显示running/waiting-remote，不保持按钮loading
  直到1800s；
-页面刷新后从workspace+events恢复progress；
- session切换不取消operation；
- terminal result与task status分别展示；
- outcome unknown/recovery required显示明确operator/agent attention，不提供“再次运行”默认按钮
  绕过idempotency；
- UI不需要知道opaque SDK handle或provider job id。

## Persistence and SQLite transaction boundaries

当前单进程SQLite可以实现该方案，但必须遵循：

- scheduler scan、claim、state transition、event/outbox使用短`BEGIN IMMEDIATE`；
- provider HTTP、sleep、HPC wait、artifact大文件写、sandbox process wait全部在transaction外；
- claim commit后worker使用自己的repository scope/connection；
- terminal commit比较operation state version、execution fence、attempt seal generation；
- event/outbox与domain state在同一UoW，commit后才notify worker/UI；
- `next_poll_at + state`、operation idempotency key和active claim需要相应index/unique constraint；
- SQLite trigger或repository guard阻止sealed attempt/session epoch继续mutation；
- busy timeout/lock contention不能被解释为provider failure；lease expiry和DB retry使用不同taxonomy；
- migration前的old row不自动获得async/restart保证，必须显式legacy state或拒绝恢复。

单进程意味着同一时刻只有一个Host scheduler authority，不意味着可以用进程内dict替代durable
queue。反过来，第一阶段也不需要为未来多Host提前引入分布式共识；monotonic fence与SQLite
transaction足以封住当前thread/task stale writer。

## Migration plan

### Phase 0: contract and observability

1. 为timeout类别、operation lifecycle、cancellation reason、delivery strategy和quiescence
   receipt建立versioned schema。
2. 在不改变dispatch的前提下记录当前sync call各层开始/结束时间、writer scope与transport
   disconnect，证明没有遗漏worker。
3. pin/config validator拒绝`external deadline + closure budget >= attempt deadline`等不可能组合。
4. 为所有provider/runner adapter声明`execution_mode=immediate|async_job`、cancel/reconcile能力、
   request timeout、remote deadline与result schema。
5. 建立post-seal mutation trap测试；任何现存路径触发时先保持NO-GO。

### Phase 1: durable async adapter execution

1. 增加operation execution table/fields、dispatch journal、private handle与SQLite polling queue。
2. 先迁移EBI HMMER，因为它原生具有submit/job/poll/result生命周期且已暴露timeout矛盾。
3. 把1800s blocking poll loop拆成one-request poll work item；每次释放worker/lease。
4. 建立result staging/materialization幂等与late callback fence。
5. 尚未实现sandbox park时，只允许显式async SDK或配置保证delivery wall-time；不得把旧sync
   path悄悄双发。

### Phase 2: sandbox and runtime parking

1. SDK sync外观改为submit+await/park；control transport支持返回suspension outcome，而不是
   control worker执行完整adapter。
2. `sandbox.exec`区分active compute与Host external wait；实现attached process ownership和
   exact original call result delivery。
3. agent signal/session lease在park后释放；operation result ready后先恢复sandbox，再唤醒agent。
4. public drain改为bounded command，不包裹remote lifetime。
5. approval continuation与external-operation continuation共享同一identity/fence框架。

### Phase 3: quiescence barrier and evidence schema

1. 所有Host writer迁入structured registry与`MutationAuthority`。
2. 实现admission freeze、seal generation、repository transaction guard和quiescence receipt。
3. evidence bundle/verifier升级，要求operation/sandbox/writer/SQLite/artifact/ledger完整closure。
4. live driver删除“client timeout后直接收集”及任何quiet-period近似。
5. 与process-isolated supervisor对接：无法quiesce时只生成parent-owned fatal evidence。

### Phase 4: restart and compatibility retirement

1. 启动recovery scan与state-specific reconciliation；先支持private handle完整的remote poll。
2. 支持result-ready但delivery未完成的canonical outcome恢复。
3. `attached_sandbox_process`在restart后显式delivery recovery failure；不伪称resume。
4. 若有真实需求，再单独实施`journaled_sdk_call_boundary`。
5. 审计所有外部caller后退役legacy sync adapter/control-socket execution path。

## Compatibility and breaking changes

允许纠正性breaking change，推荐规则：

- 新SDK/protocol schema明确major版本；旧sandbox image/SDK不能连接新async-onlyHost时在dispatch
  前报`adapter_protocol_incompatible`。
- legacy synchronous adapter只允许`execution_mode=immediate`且最大wall time严格小于sandbox/
  request安全预算的operation；async-job provider必须走新path。
- 旧`bio.hmmer_search`源代码可保留同步语法，但runtime行为变为durable park/resume；若某caller
  依赖“一个socket handler持续占用直到结果”，该依赖不受兼容保护。
- old SQLite rows标记legacy/non-resumable；不能伪造handle、fence或quiescence receipt。
- evidence schema major升级；旧bundle仍可用旧verifier做历史诊断，但永远不能满足新cutover
  GO标准。
- public status字段只做additive迁移期projection；旧模糊`running/failed`最终退役前提供明确
  mapping和deprecation窗口。
- 确认无外部caller后删除sync EBI poll、control worker内adapter execution和旧seal shortcut。

## Rollback strategy

rollback只能回滚**新operation admission**，不能把已创建async operation转回sync执行：

1. feature gate按adapter/schema控制，关闭后拒绝新的async EBI operation并给出稳定诊断；
2. 已存在operation继续由同版本worker收口、取消或reconcile；不得由旧binary接管重投；
3. downgrade前必须证明async queue为空、无in-doubt handle、无pending result delivery；
4. old binary读取到未知schema或nonterminal async row时拒绝启动writer mode，只允许read-only
   operator诊断；
5. schema采用additive migration，rollback不删除operation、receipt、artifact或event；
6. 若quiescence guard自身误报，允许阻止seal并由operator修复，绝不提供“force seal”开关；
7. live cutover在rollback期间保持NO-GO，不能回退到已知会post-seal mutation的旧path取证。

## Test plan

### State-machine unit tests

- 每个合法transition与非法skip；terminal state不可重开；
- approval、dispatch、poll、cancel、result、delivery各自的idempotency replay/conflict；
- submit response与timeout/crash各个边界点生成`remote_pending`或`submit_in_doubt`；
- result ready与cancel并发只有一个canonical winner；
- task状态不随operation terminal机械改变；
- handle跨session/run/source/runtime/call-index使用全部拒绝。

### Lease/fencing concurrency tests

- 双worker同时claim只允许一个token；
- lease expiry后旧poll response不能commit；
- cancel/freeze与late success callback并发，late writer被transaction guard拒绝；
- stale sandbox process不能delivery新epoch result；
- duplicate terminal response不创建重复artifact/event/wakeup；
- SQLite busy/rollback不泄漏claim、event或partial result。

### Timeout hierarchy tests

- provider request timeout只结束一次request，不把已接受job标为failed/cancelled；
- external deadline触发cancel/reconcile，不触发sandbox active timeout；
- sandbox active compute超过900s时终止本地process，但external outcome按policy收口；
- synthetic remote job等待超过900s、少于1800s时，sandbox active budget不增长且最终可delivery；
- public drain在operation parked后快速返回，远早于remote terminal；
- client disconnect不取消operation、不续期deadline、不复制dispatch；
- pin validator拒绝r14式`900/1800/1800`不可闭合组合。

### Provider adapter tests

- EBI submit、pending/running/success、failed、empty、pagination与schema drift逐步持久化；
- provider job id仅在private repository/log，public/evidence safe projection无泄漏；
- Host restart从private handle继续同一job poll；
- submit-in-doubt在无provider lookup能力时保持unknown且不重发；
- provider cancel unsupported/accepted/failed/timeout各有不同terminal semantics；
- result pages冲突或digest漂移不publish artifacts。

### Sandbox and continuation tests

- sync SDK语法park/resume后得到exact原call result；
-显式submit/await handle不能伪造或跨run复用；
- approval wait、external wait、local compute三类time accounting独立；
- attached process正常resume、sandbox先死、Host先restart、result先ready的全排列；
- result-ready但delivery失败仍可由agent观察canonical artifacts，不重跑provider；
- downstream script只在result delivery后继续，不能读partial output。

### Quiescence and sealing tests

- 每类writer都进入registry；测试故意创建未登记thread/task时quiescence拒绝；
- freeze与新writer注册并发，新writer确定性失败；
- freeze前已登记writer必须退休，不能仅因ASGI counter为0通过；
- WAL/SHM、event cursor、artifact tree、ledger snapshot在seal前后identity稳定；
- seal后对每个attempt-scoped repository执行write均被拒绝；
- 注入late adapter callback，证明SQLite/blob/event不变且attempt永久non-eligible；
- bundle materialization前失败、fsync失败、verifier失败均不留下eligible partial seal；
-无法quiesce时同进程harness不读取mutable root；进程隔离path只生成fatal external evidence。

### Restart and recovery tests

- 在dispatch intent前后、submit前后、handle commit前后、每次poll、result staging/promotion、
  terminal commit、delivery与seal各点强制restart；
- 每个恢复点最多一个external submit，或明确`submit_in_doubt`；
- deadline、quota、approval、call budget和fence不因restart重置；
- old binary面对new schema只读/拒绝，不写坏queue；
- recovery scan完成前普通same-scope admission被阻止。

### Public/API/UI tests

- workspace/event在refresh与SSE replay后重建waiting remote/result ready/delivery state；
- public projection无provider handle、path、lease、credential/private log；
- approval resolve与runtime drain latency不随remote operation时长增长；
- UI切session、刷新、client断开都不取消operation；
- UI显示operation terminal与task terminal分离；
- outcome unknown不能被普通用户按钮隐式重试。

### Real live acceptance tests

- 用真实EBI HMMER `refprot` operation证明remote等待可超过`900s`而不触发
  `sandbox_exec_timeout`，并最终只产生一个operation/result artifact set；
- operation pending期间public API、workspace读取和独立teammate仍可用；
- Chrome approval后浏览器不需保持单个1800s mutation request即可观察progress和terminal；
- 对真实operation在poll期间断开public client，证明同job继续且无duplicate submit；
- 在可控环境中于result callback前触发attempt cancellation/freeze，证明late write被fence；
- 两次独立positive和一次fail-closed attempt都包含有效quiescence receipt，seal后持续监测无
  SQLite/WAL/artifact/ledger变化；
- MICU等真实provider调用按连续ledger记账，不因retry/restart/timeout漏记或重复计费。

## Acceptance criteria

本提案只有在以下条件全部满足后才可标记implemented：

1. EBI HMMER等async-job adapter不再在control-socket/agent-drain handler中执行完整blocking
   poll loop；每次external work是durable、bounded、fenced work item。
2. `sandbox.exec` active compute、external operation、agent turn、public command、attempt和seal
   使用独立timeout语义；配置可在admission前拒绝不可闭合组合。
3. 一个健康remote job等待超过900s时不会因Host wait耗尽sandbox active budget，也不会占住
   session runtime lease或public drain request。
4. 每个operation有canonical idempotency identity、opaque handle、dispatch journal、private
   backend handle和exact result artifact set；重复delivery/restart不产生第二次external submit。
5. submit outcome无法确认时稳定进入in-doubt/unknown，绝不blind retry。
6. cancellation、lease expiry、Host restart、sandbox termination和attempt freeze均通过monotonic
   fence阻止stale worker写canonical SQLite/artifact/event/ledger。
7. Host可以从SQLite恢复remote pending/result-ready operation；不支持恢复的Python continuation
   明确delivery recovery failure，不伪造checkpoint。
8. public workspace/API/UI完整表达operation进度、terminal result、delivery与attention，同时不
   泄露provider handle、Host path、lease token或credential。
9. attempt seal前建立generation-based writer freeze，全部registered writer退休，SQLite/WAL、
   artifact、event/outbox和ledger形成同一个quiescence receipt。
10. seal后任何attempt-scoped canonical write在transaction边界被拒绝；一旦观察到post-seal
    mutation，该attempt永久non-eligible且不能在同root重封。
11. 正常无法quiesce时不生成普通failure bundle；process-isolated supervisor只在OS确认writer
    退休后生成parent-owned fatal evidence。
12. migration、downgrade和rollback均不删除历史operation/receipt，不把async in-flight work
    转回legacy sync执行。
13. 真实live测试覆盖长时EBI HMMER、client disconnect、restart/cancel/fence、Chrome projection
    与seal后稳定性，而不以fixture、seeded smoke或人为缩短provider等待替代。
14. capability outcome不自动写task业务终态；agent仍能基于结构化结果自由选择后续科学策略。

在这些条件落地前，单独提高 `--timeout-seconds` 或 sandbox 上限、忽略 client timeout、
在 bundle 后重新 snapshot 或允许 late writer“补齐结果”都不是本文所称的架构修复。当前
Goal 的 `1800 < 3600 < 7200` 层级只是经过 admission guard 的局部可用性 containment，
不能证明通用 cancellation/quiescence。对于 r14 已发生的事实，唯一正确结论仍是 NO-GO。
