# Deferred: product-level non-blocking supervised continuation

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只允许为 live cutover driver 增加局部、同进程、bounded 的并发协调：driver 可以在独立线程中发起一次 canonical `/runtime/drain`，同时通过另一组短连接读取 workspace/event、把 pending approval 交给 Chrome UI，并在用户 resolve 后等待原 drain 收口。该协调必须复用同一个 drain idempotency key、绑定同一 approval/operation/continuation，并为正常协调和 HTTP transport 设置总 deadline；退休阶段在短 cooperative grace 后无界 join，无法退休时保持 fail-stop，任何线程、HTTP 或 identity 异常都保持 NO-GO。

这项局部修复不改变产品 runtime 合同。它没有让 `/runtime/drain` 变成异步 command，没有释放 scheduler session lease，没有把 sandbox Python 调用栈变成可持久化 checkpoint，也没有提供 Host restart 后的 continuation resume。把 supervised continuation 从同步 drain/request 生命周期中拆出，会改变 control-plane 状态、lease ownership、scheduler 队列、sandbox supervisor、API response、background runtime、UI observation 与 recovery 语义，属于跨包大架构调整；本 Goal 只记录，不实施。

## Current implementation evidence

1. `POST /v3/sessions/{session_id}/runtime/drain` 当前在 request 内直接调用 `V3HostApiService.drain_runtime()`，后者同步执行 `AgentRuntimeScheduler.run_once_sync()`，直到本批 claimed signal 的 bounded agent turn 返回才构造 HTTP response。
2. executor 的 `sandbox.exec` 遇到首次 S10/S12 controlled operation 时，会先持久化 `ControlledOperation(WAITING_APPROVAL)`、`ApprovalRequest(PENDING)` 和 `ContinuationState(WAITING_APPROVAL)`；随后 control-socket worker 在 `_wait_for_approval_and_claim()` 内轮询 continuation，而不是向 agent turn 返回 durable suspension outcome。
3. 因此 pending approval 已经可被另一 request 从 workspace/event 观察并 resolve，但原 agent worker、sandbox process、scheduler drain 和 HTTP request仍保持调用链。顺序式 operator/client只有等 drain 返回后才会读取 approval，形成“等待 response 才能批准，而 response 等待批准”的应用层死锁。
4. 即使独立浏览器或第二线程能打破该死锁，session runtime lease、agent concurrency slot、background runtime tick和request资源仍被一个人类时长的approval占用。其它本可独立推进的agent/signal会受到不必要阻塞。
5. canonical continuation row已经记录approval/operation关联与claim状态，但可继续执行的Python栈、control socket和container process仍是Host内存/进程事实。Host restart后只能识别recoverable row并显式失败，不能据此重建任意sandbox程序的准确执行位置。
6. approval resolve当前可以原子更新approval/continuation并排队必要wakeup；但正在轮询的旧worker会直接观察该row并继续。这把“授权状态变化”和“谁在何时拥有恢复执行权”耦合在一个长生命周期调用中。
7. 默认产品方向已经是 durable signal + background scheduler；manual drain只应是debug/operator/recovery命令。同步等待人类approval使manual drain和background tick都承担了不属于scheduler bounded turn的长期supervision责任。

## Impact on agent autonomy

- agent应在发起需要批准的真实操作后得到结构化`waiting_approval`事实，并释放当前turn，而不是把token/turn、session lease或worker线程耗在人类等待上。
- approval只约束已经冻结的具体operation plan/digest；它不能让scheduler替agent生成替代plan、默认批准后续动作或把operation成功机械解释为task完成。
- 同一executor/workspace在continuation未收口前必须保持冲突边界，但其它互不依赖的resident teammate应能继续处理自己的signal、inbox和科学工作。
- approval resolve后先恢复Host-owned supervised operation；只有同一个tool result形成并持久化后，才唤醒原agent消费结果。不能用一个新的agent turn猜测、重做或替代旧operation。
- harness应把`waiting_approval`、`continuation_ready`、`resuming`、`recovery_failed`和agent/task业务状态分开呈现，避免agent或用户把基础设施挂起误读成task blocked/completed。

## Non-goals

- 不把`runtime drain command`或continuation queue变成新的业务task真状态；task board、approval、operation、run和artifact仍是产品事实。
- 不把approval resolve改成同步执行provider、runner、sandbox或agent loop的入口。
- 不尝试序列化任意Python栈、线程、socket或container process作为通用checkpoint。
- 不承诺exactly-once外部副作用；远端动作仍依赖operation digest、idempotency key、opaque handle和结果reconciliation。
- 不允许caller提交continuation lease、resume token、checkpoint locator、worker id或Host process identity。
- 不让pending approval解除同一workspace的active-run互斥，也不允许另一个agent接管原executor的未完成sandbox调用。
- 不在本提案中引入Redis、跨进程worker或多进程SQLite写入；近期实现仍可从可信Host、单进程、file-backed SQLite开始。
- 不把cutover driver的临时线程协调解释为产品级非阻塞、crash recovery或GO证据增强。

## Target semantics

产品级语义应把一次supervised operation拆成三个独立阶段：

```text
agent/sandbox requests controlled operation
  -> persist frozen operation + pending approval + parked continuation
  -> return a durable suspension outcome to the agent runtime
  -> complete/release the current runtime signal and session lease

user resolves approval
  -> atomically persist approval decision + continuation readiness
  -> append durable events/outbox work
  -> return without running the continuation

continuation scheduler claims ready work
  -> fence and resume the exact operation under an execution lease
  -> persist terminal operation/run/tool result
  -> enqueue owner-agent wakeup to consume the result
```

“return a durable suspension outcome”不代表把pending operation作为普通tool failure返回给模型。它是runtime层的park outcome：当前LLM turn停止、原tool call identity保持未完成、agent状态投影为waiting approval；approval后的恢复仍必须把结果关联回原call/operation，而不是要求模型重新发起调用。

## Target invariants

1. pending approval建立后，HTTP drain、agent scheduler turn和session runtime lease都必须在短且可配置的上界内释放；等待时长不受LLM/provider/runner timeout伪装。
2. approval、operation、continuation、sandbox run、source snapshot、workspace、agent step/tool call与runtime signal identity必须形成exact binding；任一digest或epoch漂移均fail closed。
3. approval resolve只执行短canonical mutation：`PENDING -> APPROVED|REJECTED`、continuation readiness与outbox/event提交；request内不得claim或运行continuation。
4. runtime signal被park后不保持`CLAIMED` lease。它应以显式`suspended_waiting_approval` outcome收口，或由versioned suspension record关联；approval resolve创建新的Host continuation work，而不是复活过期signal claim。
5. Host continuation work与agent wakeup分队列：前者恢复sandbox/adapter并形成tool result，后者只在结果terminal后唤醒agent。S10/S12 approval不能直接产生agent-level`APPROVAL_RESOLVED` turn。
6. session runtime lease与supervised execution lease职责分离。pending/ready continuation不能占住session lease；resume worker必须持独立、可fence的continuation/execution lease。
7. 同一continuation只能有一个有效claim；stale worker、late callback和旧process在更高fencing token出现后不得写operation、run、artifact、report或event。
8. 同一sandbox workspace在parked/running continuation期间保持write/exec冲突；其它不共享该workspace且没有task依赖的agent signal可正常调度。
9. resume必须继续同一operation id/digest和approval，不得静默创建replacement operation、重开approval或选择更容易运行的adapter/backend。
10. approval rejection、expiry、operator cancellation和Host shutdown必须有closed terminal path，清理或隔离live process，并产生稳定tool/runtime outcome；不能把它们映射成task业务终态。
11. Host restart后，只有声明了受支持resume strategy且checkpoint验证通过的continuation可以恢复；其它row必须显式`recovery_failed`并唤醒owner agent，不能猜测重放任意代码。
12. public workspace/event/API只投影stable ids、state、timestamps、retryability和safe diagnostic；process id、socket、checkpoint path、lease token、worker locator与private log不得公开。
13. manual drain、background runtime和recovery worker必须消费同一durable work/lease语义，不能各自实现一套approval等待规则。
14. operation terminal不等于task terminal。恢复后的agent仍保留核对结果、重试科学策略、委派或调用`task.finish`的自由。

## Proposed control-plane model

在现有`ApprovalRequest`、`ControlledOperation`、`ContinuationState`、`SandboxRunRecord`和`AgentRuntimeSignal`之上，引入versioned suspension/dispatch字段或窄记录，而不是另建第二套workflow状态：

```text
SupervisedContinuation@next
  continuation_id / session + task + lane + agent identity
  operation_id / operation_digest / approval_id
  sandbox_run_id / sandbox_workspace_id / source snapshot + runtime identity
  originating_signal_id / step_id / tool_call_id / SDK call index
  state: waiting_approval | ready | claimed | running |
         completed | rejected | cancelled | failed | recovery_failed
  resume_strategy: attached_process | replayable_checkpoint
  checkpoint_digest / workspace_epoch / SDK protocol version
  claim owner / lease expiry / fencing token / attempt count
  created / resolved / claimed / terminal timestamps

RuntimeDispatchCommand@1 (operator/debug projection)
  command_id / session_id / requested bounds / idempotency digest
  accepted_at / high-watermark / status / bounded outcome summary
```

`RuntimeDispatchCommand`只表达一次operator请求的接收与可观察结果，不拥有task、signal或continuation。默认background runtime可直接消费signals，不必先创建该对象。若复用现有command receipt/outbox已经能提供相同不变量，则不应新增独立表。

`resume_strategy`必须是Host根据execution contract选择的闭集：

- `attached_process`：把仍存活的sandbox supervisor转交给独立execution worker/lease，HTTP和session scheduler均可释放；Host restart后不能伪称可恢复，必须进入明确recovery path。
- `replayable_checkpoint`：仅对能够证明source/runtime/workspace epoch、SDK call journal和副作用幂等的versioned pipeline启用。它不是“重新运行整段Python并希望命中缓存”。

任意未声明strategy、checkpoint drift或journal不完整都default-deny。

## Persistence and transaction boundaries

### Park transaction

首次触达approval gate时，一个短Unit of Work必须原子写入：

- frozen controlled operation及operation digest；
- pending approval及完整plan/identity binding；
- waiting continuation/suspension record；
- sandbox run与originating signal/step/tool call关联；
- `approval.requested`、`continuation.parked` durable events；
- 必要outbox通知。

commit前不得向public surface声称approval存在；rollback不得留下孤立approval、operation或event。commit后旧agent worker只负责返回suspension outcome和释放lease，不继续轮询approval。

### Resolve transaction

approval resolve在一个短Unit of Work内完成：

- authenticated actor与expected pending version检查；
- approval terminal transition；
- continuation `waiting_approval -> ready|rejected`；
- operation approval projection更新；
- continuation-ready outbox或terminal rejection outcome；
- `approval.resolved`及`continuation.ready|rejected` events。

重复相同decision按idempotency replay；不同decision或已被其它actor解决返回state conflict。事务提交后才notify scheduler。

### Claim and terminal transactions

continuation scheduler以独立短事务claim ready work，写claim lease/fencing token，再在事务外执行可能阻塞的resume。每个callback/side effect前检查fence，每次canonical commit再次校验。terminal写入必须把continuation、operation、sandbox run、engine invocation、tool-result availability与后续agent wakeup/outbox收口；外部结果未知时记录reconciliation-required，不盲目重复提交。

## Scheduler and ownership

### Agent runtime scheduler

- claimed agent signal到达supervised gate后，把agent member投影为`waiting_approval`，持久化park outcome并完成本次signal处理。
- scheduler立即释放agent/session lease；pending approval本身不是失败、idle或max-steps。
- 同一agent的新普通signal应根据blocked tool-call policy合并、延后或返回attention状态，不能启动第二个冲突turn；其它independent agent仍可运行。

### Continuation scheduler

- 独立扫描/接收`ready` continuation outbox，只负责Host supervisor恢复，不调用LLM。
- 按session、workspace、operation维度执行并发限制；至少保证同一workspace一次只有一个active exec/continuation。
- claim使用execution lease/fencing；heartbeat丢失后旧worker不能写回。新worker只在resume strategy允许时reclaim。
- terminal tool result形成后，创建`engine_completed`或专用`controlled_operation_completed` signal唤醒原owner agent；该signal携带原tool call/operation identity。

### Live process registry

单进程第一阶段可以维护Host-private live supervisor registry，把process/control socket从request worker转交给continuation executor。但registry只是优化和`attached_process`实现，不是canonical truth。row存在而process不存在时必须走resume strategy/recovery，不得创建替代process并冒充原continuation。

## API semantics

### Runtime drain

推荐把manual drain改为“接受bounded dispatch command”，而不是“HTTP连接等待所有claimed work完成”：

- `POST /v3/sessions/{session_id}/runtime/drain` 接受command并快速返回`202 Accepted`，包含`command_id`、accepted high-watermark、bounds和status URL；或在兼容期支持很短的`Prefer: wait=<bounded>`，但一旦遇到approval/external wait必须立即返回parked状态。
- `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` 返回closed状态：`accepted|running|waiting_approval|completed|failed|locked|cancelled`及bounded identities。
- workspace/events仍是pending approval、continuation和agent状态的canonical public observation面；command status不能替代它们。
- 请求断开只影响等待response，不取消已接受的durable work；显式cancel需要独立command、权限与state transition。

若保留同步response shape，最低要求也是：drain在遇到park outcome时立即返回`waiting_approval`，而不是等待approval resolve。不能用增加HTTP timeout掩盖同步耦合。

### Approval resolve

- `POST /v3/approvals/{approval_id}/resolve` 在resolve transaction提交后立即返回；不等待sandbox、provider、runner或agent。
- response明确给出continuation state和可观察event cursor，但不返回private resume handle。
- UI通过SSE/workspace观察`continuation.ready -> running -> terminal -> owner agent resumed`，不假设resolve response代表execution完成。

### Events and projection

事件至少区分：

- `approval.requested`；
- `continuation.parked`；
- `approval.resolved`；
- `continuation.ready`；
- `continuation.claimed|resumed`；
- `controlled_operation.completed|failed`；
- `agent.wakeup_queued`。

cursor顺序必须来自durable commit；UI刷新后可仅凭workspace + replay重建waiting/resuming状态。重复delivery可以发生，重复canonical transition和外部dispatch不能发生。

## Recovery semantics

- Host startup扫描nonterminal continuation，先检查lease expiry、operation/approval状态、sandbox run、workspace epoch、runtime identity和resume strategy。
- `waiting_approval`保持等待，不因restart自动失败或批准；若attached process已丢失，可保留approval但必须标记`resume_unavailable`，由policy决定在resolve时recovery_failed或允许operator cancel。
- `ready/claimed/running`只有在checkpoint或attached process ownership可证明时恢复；否则进入`recovery_failed`，terminalize相关operation/run并唤醒owner agent。
- remote adapter/runner可能已接受动作时，先按opaque handle/idempotency查询reconcile；unknown不能重投。
- recovery不能创建新approval来替代旧approval，也不能把旧批准扩大到drifted plan/runtime/workspace。

## Compatibility and migration

1. 先为现有同步路径补telemetry：approval park到resolve时长、drain request时长、session lease占用、background tick阻塞、live process与continuation mismatch。
2. 扩展continuation schema和state-machine tests，shadow写originating signal/tool-call/workspace/runtime binding；现有pollingworker仍是authority，shadow不得触发第二次resume。
3. 让agent scheduler识别并持久化`suspended_waiting_approval`，但先只在explicit feature flag/test profile启用；对比旧路径的operation/result identity。
4. 引入continuation scheduler和独立execution lease；先支持同进程`attached_process`转交，证明drain/request/session lease可释放。该阶段明确不声称restart resume。
5. 将manual drain发布为async command或bounded-wait response；保留旧sync形状的versioned兼容入口，仅用于非cutover debug，并建立外部caller inventory与sunset期限。
6. 为可证明幂等的execution pipeline设计`replayable_checkpoint`，加入SDK call journal、workspace epoch与source/runtime binding；任意generic Python默认不启用。
7. background runtime和manual/recovery全部切到同一park/continuation scheduler；删除control-socket busy wait作为产品authority。
8. 在确认无外部sync drain caller且UI/CLI已按events/workspace观察后，退役legacy synchronous wait。历史continuation不补造checkpoint，只能按原版本读取或显式recovery_failed。

迁移期不能让新continuation scheduler与旧pollingworker同时拥有同一operation。feature flag必须按session/profile冻结并进入effective config/diagnostic，不能在一次run中途切换。

## Current cutover-driver workaround

当前Goal允许的局部driver协调必须被明确限制为：

1. 在发起可能产生formal approval的drain前封存durable event cursor；
2. 用独立线程/HTTP client发起一次同步drain，主协调器只读workspace/events；
3. 观察到exact pending approval后，Chrome用户通过同一Host公共API resolve；
4. driver验证resolution/continuation event与原operation/sandbox identity后，先给原 drain 短 cooperative grace，再无界 join 直到其真实退休；
5. 同一drain若串行产生后续approval，driver必须按固定策略逐个协调（Chrome只处理首个指定approval，其余auto），原worker与server-side drain handler返回前不得开启第二个concurrent drain、读取attempt evidence或重复resolve；client timeout不代表handler terminal。注入后的fault路径又请求approval、跨线程异常、Host shutdown或receipt不完整均NO-GO。

该workaround不能进入普通产品路径，也不能作为以下声明的证据：drain已异步化、session lease已释放、Host restart可恢复、pending approval不消耗worker、或任意client无需并发协调。

## Risks

- **双执行：** 旧pollingworker与新continuation worker可能同时resume；需要单一owner切换、fencing与migration gate。
- **外部副作用重复：** crash发生在remote accept与local terminal commit之间；必须reconcile opaque handle，不能用at-least-once queue直接重投。
- **错误的通用replay：** 重跑Python可能重复文件写、随机计算或非SDK副作用；generic code必须default non-replayable。
- **lease拆分后的竞态：** session scheduler继续其它agent时可能触碰同一task/workspace；需要agent/workspace级blocked ownership与dependency检查。
- **SQLite饥饿：** 大量pending/ready continuation和heartbeat可能增加短写竞争；需要索引、bounded polling/notifier和公平claim。
- **orphan process/resource leak：** detached process可能长期等待；需要approval TTL、operator cancel、resource accounting与shutdown handshake，但TTL不能静默reject用户仍可见的approval。
- **UI状态混淆：** approval approved不等于operation completed；projection和UI必须展示resuming/terminal两阶段。
- **兼容漂移：** sync client可能把HTTP 200当成全部work已完成；async变更需要versioned response、caller audit和明确sunset。
- **agent重复调用：** agent恢复时若看不到原tool-call pending/result identity，可能重新提交；restore context必须注入closed continuation状态和原operation。
- **安全边界扩大：** command/status/cancel API可能泄露worker/checkpoint locator或允许越权resume；public DTO必须allowlist且所有mutation复用session access/role/idempotency。
- **shutdown不完整：** Host退出时attached process、ready queue和lease可能分离；shutdown必须停止claim、fence workers、记录可恢复状态后再终止process。

## Test strategy

### State-machine and repository tests

- property-test所有approval/continuation transition、重复resolve、conflicting decision、claim expiry、fencing和terminal idempotency；
- 验证park/resolve/terminal各自的row + event + outbox原子提交与rollback零泄漏；
- 验证历史schema读取不补造resume strategy或checkpoint。

### Scheduler concurrency tests

- unresolved approval持续数小时的fixture中，drain response、agent signal和session lease都在bounded时间释放；
- 同一workspace的第二exec被阻止，不同workspace/agent signal可继续；
- 两个continuation worker、lease expiry/reclaim、late callback与shutdown竞态下只有一个terminal write；
- background/manual/recovery对同一session竞争时遵守相同session与execution fencing。

### API and UI tests

- async drain command接收、idempotency replay、status polling/SSE、disconnect和cancel；
- approval resolve在continuation执行慢或失败时仍快速返回，UI随后观察ready/running/terminal顺序；
- browser刷新/Host API重启后仅凭workspace与durable replay重建pending/resuming状态；
- shared profile验证operator drain权限、user approval权限、session access和public projection无private locator。

### Sandbox and recovery tests

- attached process正常resume、approval reject、process提前退出、control socket丢失与Host shutdown；
- replayable checkpoint对source/runtime/workspace/call journal任一digest漂移均在副作用前fail closed；
- provider/runner在remote accept后Host crash的reconciliation不会重复submit；
- non-replayable generic Python在restart后稳定`recovery_failed`并唤醒agent，不伪装成功。

### Live tests

- 用户在真实UI延迟批准至少一个远长于HTTP timeout的operation，产品API/其它agent仍可用；
- approval前后重启Host：支持的strategy恢复同一operation，不支持的strategy给出明确recovery outcome；
- 高并发pending approvals下测量worker/thread、SQLite、memory和lease占用保持bounded；
- AOX cutover在产品语义迁移完成后删除driver线程workaround，仍能用同一approval/operation/event证据通过两正一负验收。

## Acceptance criteria

- 任意supervised approval保持pending时，`/runtime/drain`和background tick不会保持HTTP request、agent signal claim或session runtime lease超过配置上界。
- approval resolve request只做canonical decision/readiness提交，P99 latency不随实际provider/runner/sandbox执行时长增长。
- 同一continuation在重复delivery、双worker、lease expiry、Host restart和late callback下最多产生一次有效external dispatch/terminal result；未知远端状态不会盲目重投。
- owner agent在approval前看到waiting状态、operation terminal后收到原tool call结果；不会被迫重新构造plan，task状态也不被scheduler机械终结。
- 其它independent teammate可在pending approval期间推进，而同一agent/workspace的冲突work被结构化阻止。
- UI/CLI可从public workspace + durable events完整观察park、resolve、resume与terminal；不依赖发起drain的浏览器连接或进程内callback。
- Host restart后，可恢复strategy继续同一operation identity；不可恢复strategy显式失败并提供agent可行动诊断，绝不创建replacement operation/approval。
- legacy synchronous waiting path在外部caller审计后退役；cutover/live不再需要driver线程协调即可完成同等Chrome approval证明。
