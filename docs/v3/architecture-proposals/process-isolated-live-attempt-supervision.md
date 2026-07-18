# Deferred: process-isolated live-attempt supervision

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 AOX/HMM cutover driver 在一个 Python 进程内启动 loopback Host，使用独立
HTTP 连接协调同步 `runtime/drain` 与 approval，并在 Host context 退出后才读取
SQLite、artifact root 和 MICU ledger。当前局部修复会追踪全部 ASGI mutation；只要
这些 handler 最终返回，就能证明 evidence materialization 晚于所有已知 Host 写入。

这一保证无法转化为有界失败：Python 线程不能被安全强杀。若一个 mutation 永久阻塞、
清理路径也不能使其返回，或者 handler 返回后留下 detached writer，同进程 driver 只能
永久等待；它不能在 deadline 后继续读取可能仍在变化的状态，更不能封存一个看似完整的
NO-GO artifact。给等待函数增加 timeout 只会把“永久挂起”变成“竞态取证”，不构成修复。

要同时满足 bounded fail-stop、完整 ledger-after 和不可变 attempt evidence，必须把一次
live attempt 的全部 mutable Host authority 放入可由操作系统退休的子进程，并由不持有
attempt 写权限的父进程监督。该变化涉及进程模型、SQLite owner、credential 传递、Chrome
handoff、receipt channel、HPC orphan reconciliation 与 campaign artifact 语义，属于大型
harness 架构调整。本 Goal 只记录方案，不实施；当前同进程路径继续严格 fail-closed，
无法退休时不产生 eligible evidence。

## Relationship to other proposals

[non-blocking supervised continuation](nonblocking-supervised-continuation.md)
解决产品 runtime 中 approval park、resolve 和 continuation resume 长期占用同步 drain、
session lease 与 request worker 的问题。本提案解决 cutover/eval harness 如何在任意 Host
mutation 永久阻塞时有界终止并安全证明“该 attempt 已无本地 writer”。二者独立：

- product continuation 即使非阻塞，provider、runner、SQLite 或 shutdown 仍可能卡死，
  live attempt 仍需要进程级监督；
- attempt 已经进程隔离，也不表示产品 drain 异步化或 continuation 可重启恢复；
- 两项未来都落地时，子进程仍运行 canonical 产品路径，父进程只做 harness supervision，
  不接管 agent 策略、operation 或 task 真状态。

## Current evidence and failure mode

1. loopback Host、FastAPI service、repository provider、sandbox supervisor、driver 和 evidence
   runner 当前位于同一进程。
2. `httpx` timeout 或 driver thread join 只证明 client call 返回；Starlette/FastAPI 的同步
   handler 可能仍在线程池中继续写 SQLite、artifact 或 ledger。
3. 当前 mutation tracker 能跨 client disconnect 追踪 ASGI call lifetime，并在正常
   `finally` 下准确减计数；它不能终止永久阻塞的 Python/foreign-code 线程。
4. Uvicorn `should_exit`/`force_exit` 不能证明线程池任务已退休，也不能撤销已提交的外部
   provider/HPC 副作用。
5. 在仍有 writer 时由同一进程生成 failure evidence，会让 `ledger_after`、artifact index、
   event high-watermark 或 SQLite closure 成为时间竞态；该 evidence 不可封存。
6. 若 handler 返回后创建未登记线程、async task、subprocess 或 callback writer，ASGI
   tracker 即使归零也是假静默。因此“mutation 不得留下 detached writer”必须成为
   Host contract，而不是只靠 attempt driver 猜测。

## Agent-harness principles

- 父 supervisor 只施加真实资源、时间与完整性约束，不替 agent 选择科学策略、自动重试
  替代 plan、批准 operation 或推导 task 业务终态。
- 子进程必须运行与普通产品相同的 Host API、scheduler、approval、provider、execution
  和 report path；进程隔离不能演化成第二套 fixture control plane。
- deadline、termination reason、未完成 external operation 和证据完整性必须结构化呈现给
  operator/verifier。无法证明的事实标为 unknown，不用默认值补齐。
- fatal harness outcome 与科学 empty result、agent blocked、task failed、provider degraded
  明确分离。只有 canonical product path 自己能写业务状态。
- 第一阶段同 UID `spawn` 不能在 OS 层撤销 parent 对已知 root path 的 reopen 权限；因此
  supervisor 合同和实现审计必须禁止父进程在子进程存活时读取或修改 attempt
  SQLite/artifact。它只能观察窄控制 channel 与 Host 明确发布的 public handoff。需要更强
  隔离时再用不同 UID、mount namespace、Landlock 或 brokered read-only handoff 加固，不能
  把逻辑禁令误写成 kernel-enforced capability。

## Target topology

```text
campaign coordinator (parent, must not exercise attempt data-plane access)
  |-- validates clean commit/config and allocates exclusive attempt roots
  |-- creates one authenticated private control channel
  |-- starts one attempt child in a new process/session
  |     |-- owns loopback Host + SQLite connection pool
  |     |-- owns artifact/blob/sandbox/private-log writers
  |     |-- owns provider/runner calls and MICU attribution records
  |     |-- serves the digest-pinned UI and public V3 API
  |     `-- reports bounded lifecycle/Chrome handoff frames to parent
  |-- supervises deadline, process identity and resource limits
  |-- on timeout: TERM -> bounded grace -> KILL process group/cgroup
  |-- waits for OS-confirmed child death and retires every descendant
  |-- reconciles external opaque handles without mutating attempt truth
  `-- only then opens roots read-only and materializes eligible/fatal evidence
```

推荐第一阶段使用本机可信 Host 下的 `spawn` 子进程或一个专用 CLI subprocess，而不是
`fork` 继承现有线程、SQLite connection、HTTP client 或 credential-bearing runtime state。
每个 attempt 单独一个 process group；若部署环境支持，优先使用 cgroup/systemd scope 形成
可枚举的 descendant 与资源边界。父进程继续单写 campaign reducer，但绝不同时写 attempt
SQLite。

## Core invariants

1. 一个 attempt 在任一时刻只有一个 child process epoch 拥有其 SQLite、artifact、sandbox、
   private log 和 local receipt channel 的写 capability。
2. 父进程在 child 存活或 descendant 未退休时，不读取 attempt SQLite、不扫描 mutable
   artifact root、不观察 MICU-after、不生成 attempt evidence。第一阶段这是可测试、可审计
   的逻辑边界，不是同 UID 下的 OS 权限撤销；所有 root open/read/write 必须经过带 lifecycle
   gate 的窄 adapter，并在测试中记录调用。
3. 所有 Host mutation 必须 structured-concurrency：handler 返回前 join/cancel 并确认其
   child tasks、threads、subprocess callbacks 与 local writers 已收口；detached writer
   是 contract violation。
4. child 正常完成必须先停止接受 mutation、等待 mutation registry 为零、关闭 provider/
   runner callbacks、checkpoint/fdatasync SQLite WAL、fsync declared roots，再发送
   `quiescent` frame；发送 frame 不等于进程已退休。
5. 父进程只有在收到 matching quiescent frame、child exit code 为零、OS 确认 process
   group 无 descendant，且 control channel 完整闭合后，才允许构造 eligible evidence。
6. timeout、signal、nonzero exit、protocol gap、missing quiescent、descendant leak 或 root
   identity drift只能产生 fatal non-eligible evidence；不得复用 child 的 partial bundle。
7. fatal evidence由父进程写入 attempt roots 之外的 append-only campaign failure area，
   明确记录它没有声明 `ledger_after`/SQLite closure/artifact completeness。
8. child death证明本机 writer 退休，不证明远端 provider/HPC action 已停止。任何已提交
   external operation必须按 opaque handle/idempotency receipt reconciliation；unknown 保持
   unknown，不能重投或冒充 terminal。
9. Chrome 仍只通过 child 提供的 public loopback Host resolve canonical approval。父进程
   不能代替浏览器调用 resolve，也不能用 private channel写 approval。
10. process isolation 不改变 task、approval、operation、continuation、runtime signal、report
    或 artifact 的产品 ownership；supervisor lifecycle 不是新的业务真状态。
11. MICU 的 100M 累计 ledger 仍是 Host-owned persistent authority。父进程只能在 child
    退休后读取 snapshot；fatal child 若 ledger write 状态未知，campaign 必须保守计费并
    阻止继续，直到 canonical ledger reconciliation 完成。
12. 同一 commit/config 的第二个 positive 或 fault attempt 只有在前一个 attempt 已完成
    retirement/reconciliation 后才能启动；禁止以并行 attempt 绕过单进程 SQLite/ledger
    边界。

## Attempt process protocol

建议新增 versioned、长度前缀、canonical-JSON 私有协议，例如
`aox_live_attempt_supervision@1`。它不是 public API，也不承载 credential 或完整科学 bytes。
每个 frame 至少绑定：

```text
schema_id / campaign_id / attempt_id / attempt_kind
parent_process_nonce / child_process_nonce / process_epoch
git_commit / config_digest / workflow_ref
monotonic sequence / emitted_at_monotonic_ns
frame_type / payload_digest / previous_frame_digest
```

闭集 frame 类型：

- `child_started`：child PID、process group identity、root capability digest；
- `host_ready`：loopback logical URL、actual ephemeral URL、Host process、UI dist digest；
- `approval_handoff`：现有 browser handoff 的 safe fields 与 challenge digest；
- `progress`：bounded public counters/high-watermark，不含 prompt、credential、private path；
- `external_handle_registered`：operation、backend category 与 opaque reconciliation ref digest；
- `quiescing`：停止接受 mutation 的时间与 mutation high-watermark；
- `quiescent`：mutation count zero、writer registry zero、SQLite checkpoint、root sync 与 final
  public high-watermark digest；
- `child_terminal`：normal/fatal outcome、result manifest digest 与 intended exit code。

父进程验证 sequence、hash chain、process epoch 和 exact attempt identity。frame 丢失、重复
冲突、乱序、oversize、unknown type 或 nonce mismatch 均 fail closed。control channel EOF
只表示 transport closed，不表示 quiescent。child 输出到 stdout/stderr 仍走 bounded private
spool，不能与控制协议复用一条无 framing 的文本流。

## Root and SQLite ownership

- campaign coordinator先用 exclusive no-replace 创建 attempt root capability，并为
  `sqlite`、`blob`、`sandbox`、`private_log`、`hpc_label` 生成不可拆分的 identity。
- 启动后 child 独占所有已打开的写 fd；父进程关闭继承的目录 fd/SQLite handle，只保留
  root identity 和未来 read-only reopen 所需信息。关闭 fd 不会撤销同 UID 对 path 的权限，
  parent 的 repository/artifact/verifier adapter必须在 lifecycle gate打开前拒绝 reopen。
- child 必须拒绝 symlink、pre-existing leaf、跨 filesystem 替换和 root epoch drift；所有
  canonical artifact 都由 Host registry登记。
- 正常 shutdown 依次停止新请求、退休 mutation、关闭 sandbox/adapter worker、SQLite
  `wal_checkpoint`/commit/close、fsync files/directories，再发送 quiescent。
- 父进程在 child death 后重新进行 no-symlink/no-replace/stat identity 验证，并以 SQLite
  read-only/immutable 或复制后的 verified snapshot 做 verifier 输入。WAL/SHM 未解释、锁仍
  活跃、integrity check失败或 schema drift均使 attempt non-eligible。
- fatal kill 不得把 partial SQLite 修补成产品终态。父进程只记录可验证的文件身份、exit/
  signal和“不具备 closure”；需要业务恢复时另开 operator recovery，不污染 cutover evidence。

## Structured writer registry

ASGI mutation tracker 应扩展为 child-private writer registry：

- 每个 request mutation、background runtime tick、sandbox callback、artifact registration、
  provider ledger commit、runner reconciliation callback与report publication必须登记 owner、
  epoch和生命周期；
- 新 writer 只能从已登记 scope 派生，scope 关闭前必须 join child scope；
- raw thread/task/process creation 在 Host package 中默认禁止，统一经 registry factory；
- handler 返回时 registry校验该 handler 的 descendant writer set 为空；违反时将 child
  标为 fatal 并拒绝 quiescent；
- shutdown gate先禁止新注册，再等待 active set归零；late callback因 closed epoch/fencing
  token不能写 canonical state；
- registry metadata只进入 private diagnostic，public surface只投影 safe count/status/code。

这一 registry 是防止“handler 返回但 writer 留存”的必要条件；process kill只是最终
fail-stop，不能替代正常路径的 structured concurrency。

## Deadline and termination ladder

attempt 的总 deadline在 parent monotonic clock 上计算并进入 effective config digest。推荐
终止顺序：

1. parent发送 authenticated `request_quiesce`，child停止接收新 mutation；
2. 等待短且配置化的 graceful interval，允许 reject-only approval cleanup与已知 adapter
   cancellation；绝不自动 approve；
3. 向 child process group发送 `SIGTERM`，记录 signal/clock/process identity；
4. 等待 bounded termination grace，并持续枚举 descendants；
5. 对仍存活 group/cgroup发送 `SIGKILL`；
6. `waitpid`/pidfd 等待 OS-confirmed exit，并确认 group/cgroup空；
7. 关闭 control channel，验证最后完整 frame；
8. 执行 external-handle/MICU reconciliation；
9. 仅在本地 writer 已全部退休后写 parent-owned fatal evidence。

PID 必须与 pidfd/start-time/process nonce 绑定，防止 PID reuse。若平台无法证明 descendant
已退休，该平台不具备 cutover-grade bounded supervision，attempt保留 NO-GO。kill 命令本身
成功不是 retirement evidence。

## External provider and HPC reconciliation

- child 在 dispatch 前先持久化 operation/idempotency identity，并通过 control frame登记
  opaque backend handle；父进程永不接收 SSH config、runner credential或Host path。
- child异常退出后，父进程只调用 Host-owned、read-only reconciliation adapter，按已登记
  handle查询 remote state；不得重发 scientific request或runner job。
- remote `running` 时可在 campaign-level bounded monitor继续观察，但本地 attempt仍 fatal、
  non-eligible；remote terminal result不能补造成原 child 的成功 bundle。
- remote `unknown`、network unavailable或handle frame缺失时显式记录
  `external_outcome_unknown`，保留资源泄漏告警并禁止后续 attempt复用相同 HPC workspace。
- cleanup/cancel是独立 privileged operator action，不能由 cutover reducer静默执行；其
  receipt与原 attempt evidence分离。

## MICU ledger semantics

MICU ledger不应被复制到每个 attempt root或由父子同时写。推荐由一个 Host-owned append-only
ledger broker或当前单进程锁保护的独立 ledger authority接受 child attribution。第一阶段仍可
保留文件 ledger，但必须满足：

- 只有 child通过 canonical invocation runtime写 charge record；parent read-only；
- record在provider request前/后使用现有 reservation/charge 状态，进程死亡留下明确
  in-doubt reservation；
- parent在启动下一 attempt前调用版本化 reconciliation，按最保守可计费上界处理未知
  request；不得重置100M累计值；
- `ledger_before`和`ledger_after`都绑定同一 authority identity。正常 eligible evidence要求
  child retirement后完整 after snapshot；fatal evidence只记录 verified lower bound、in-doubt
  ids和禁止继续原因，不伪造 exact delta。

若无法在文件模式下证明 crash-consistent reservation，这部分应先单独落地再启用 process
kill；不能用“调用方大概率未收费”放宽预算边界。

## Credential and environment boundary

- parent从已验证 settings生成 credential availability与sealed slot descriptors；真实 secret
  通过 `close-on-exec` 的定向只读 fd、短生命周期 secret broker或最小 env allowlist传入
  child，不进入 argv、control frame、diagnostic、core dump或campaign artifact。child
  bootstrap读取后立即关闭secret fd；sandbox、provider helper、runner或其它descendant不得
  继承该fd或原始secret env。
- child启动时重建环境 allowlist，继续 scrub `APPTAINER_*`/`SINGULARITY_*` 等 runtime-control
  变量；不得继承父进程浏览器、测试或developer shell的无关配置。
- crash dump默认关闭或放入 Host-private受限目录；fatal evidence只投影 safe failure code。
- NCBI identity仍用现有配置，但只封存允许公开的 identity digest/availability，不封存 email
  或 API key。

## Chrome handoff under process isolation

1. UI和public API仍由 attempt child同一个loopback Host提供；parent只转发已验证 handoff
   record给operator/Codex，不做代理或替代Host。
2. actual ephemeral URL只存在于trusted local operator channel；sealed logical page、Host PID、
   UI digest、session/approval/operation/challenge仍进入 browser receipt。
3. Chrome通过public UI POST resolve。parent/control channel不得拥有resolve command。
4. browser observation receipt写入 parent预先创建的独立 no-replace handoff root；child只读
   并验证，或由parent验证后通过digest-bound frame交付，二选一合同必须固定，不能双写。
5. child在completion observation hold内必须存活；若parent deadline、browser deadline或
   child crash先发生，attempt fatal，不复用截图或approval receipt到新child。
6. browser receipt的 `host_process_id` 必须等于child identity，不得误填parent PID；DevTools
   transcript、console和PNG仍按现有closed schema离线复核。

## Evidence classes

### Normal eligible attempt

只有以下全部成立才允许现有 positive/fault verifier读取 attempt roots：

- matching `quiescent`和`child_terminal` frame链完整；
- child正常exit，process group/cgroup无descendant；
- mutation/writer registry均为零且shutdown epoch closed；
- SQLite/root/ledger closure检查通过；
- public API receipt reservation连续、无in-flight/failed gap；
- external operations均有合同要求的terminal/reconciliation receipt；
- 原有科学、Chrome、fault与offline verifier全部通过。

### Parent-owned fatal evidence

fatal evidence建议使用独立schema，例如`aox_live_attempt_fatal@1`，至少包含：

- campaign/attempt/commit/config identity；
- parent/child nonce、pidfd/process group identity摘要；
- deadline、termination ladder时间、exit code/signal；
- 最后完整control-frame sequence/digest；
- quiescent是否缺失、descendant retirement是否证明；
- external handle reconciliation摘要；
- MICU verified lower bound与in-doubt状态；
- stable blocker code，例如`attempt_child_quiescence_timeout`、
  `attempt_child_descendant_retirement_unproven`；
- 明确的`cutover_eligible=false`、`sqlite_closure_claimed=false`、
  `artifact_completeness_claimed=false`。

fatal artifact写在campaign failure root，不写入或修补child attempt root。它可以证明“本次
campaign安全地拒绝GO以及父进程看到了什么”，不能声称产品task/report的最终状态。

## Security and trust boundary

- parent/child control socket使用filesystem权限加随机nonce或socketpair，不监听非loopback；
- frame大小、频率与字段闭集有硬上限，所有文本经public-diagnostic policy；
- child不能指定parent将读取/删除/kill的任意path或PID；所有target来自parent创建的capability；
- process group/cgroup只包含该attempt，禁止kill共享Host/runner/browser进程；
- parent只允许可信Host启动，runner仍是trusted Host-only；本提案不扩大多租户边界；
- root、socket、handoff、fatal artifact均拒绝symlink与replacement，权限默认`0700/0600`；
- supervisor code/version/digest进入config identity与bundle，避免换监督器而复用旧pin。

## Migration plan

1. 为当前同进程路径补telemetry：mutation/writer类别、shutdown时长、thread/process残留、
   ledger in-doubt与external handle coverage；不改变现有authority。
2. 引入Host-private structured writer registry，先shadow audit所有mutation descendant。发现
   detached writer立即修正所属模块；在registry不完整前不声称quiescent。
3. 定义并golden-test supervision protocol、root capability、fatal evidence schema与safe
   diagnostics；使用fake child验证乱序、截断、oversize、PID reuse和nonce drift。
4. 把一个non-live synthetic attempt迁入spawn child，父进程只做lifecycle supervision；保持
   product API、SQLite schema和verifier不变。
5. 加入normal quiescence与OS retirement gate；用instrumented root adapter证明父进程在
   child death前没有发生任何open/read/write，并验证绕过lifecycle gate的调用被拒绝。
6. 加入permanently blocked mutation、uncooperative subprocess、descendant leak和SIGKILL
   tests；只生成parent fatal evidence，绝不生成eligible attempt bundle。
7. 接入MICU crash-consistent reservation与external handle reconciliation；未解决in-doubt时
   阻止下一live attempt。
8. 接入Chrome handoff，验证browser只对child Host操作、PID/digest/challenge准确且child
   crash后receipt不可复用。
9. 在feature flag下运行seeded live smoke与一轮non-cutover真实campaign，对照同进程路径；
   两条路径绝不同时写同一root/ledger reservation。
10. 满足以下验收后，cutover driver默认切到process-isolated模式；盘点外部caller后退役
    same-process live attempt。普通产品Host是否进程隔离不由本迁移决定。

## Verification and acceptance criteria

### Unit and state-machine tests

- frame hash chain、sequence、nonce、epoch、schema与size闭集；
- exclusive root identity、parent lifecycle gate与read-before-retirement拒绝/访问审计；
- writer registry nested scope、late registration、detached thread/task/process拒绝；
- quiescent/terminal/exit/process-group组合真值表；
- fatal schema不允许ledger-after、SQLite closure或artifact completeness伪声明；
- MICU reservation crash前、request中、response后、charge commit后各故障点；
- Chrome handoff PID、Host/UI digest、challenge与receipt single-use。

### Integration fault matrix

- FastAPI sync mutation永久阻塞且忽略client disconnect；
- async mutation吞掉cancellation；
- handler返回后尝试late SQLite/artifact write；
- sandbox child忽略SIGTERM并再spawn descendant；
- Uvicorn thread退出但provider callback仍活跃；
- SQLite WAL checkpoint失败或child在commit各阶段被kill；
- provider request已接受但local receipt未提交；
- HPC job已提交、running、terminal与unknown四种reconcile状态；
- control frame截断/乱序/伪造、child exit前发送假quiescent；
- Chrome approval前、resolve commit后、observation hold中child分别死亡。

### Required proofs before adoption

1. 所有normal测试中，父进程第一次打开attempt SQLite/artifact的时间严格晚于
   OS-confirmed child/descendant retirement。
2. 所有permanent-block测试在固定上界内结束parent command，并只产生可离线验证的fatal
   non-eligible evidence；没有后台writer在command返回后改变root。
3. kill/restart测试重复运行后，attempt root和campaign reducer不出现GO、partial eligible
   bundle或重复external dispatch。
4. MICU总账在每个crash point都不下降、不重置、不超过100M硬上限；in-doubt阻止继续而非
   乐观扣零。
5. Chrome正向证明仍绑定同一child Host/operation/continuation，driver/parent没有调用
   reserved resolve route；child死亡负测不能复用receipt。
6. 两次独立positive加一次fault campaign在同一commit/config上通过现有offline verifier、
   tamper负测和campaign reducer；process supervisor digest也纳入identity。
7. security review证明credential、private root、socket、PID target、HPC locator与raw logs
   不进入public workspace、event、fatal evidence或browser receipt。
8. 文档明确：process isolation只证明本地attempt bounded retirement，不提升单进程SQLite、
   trusted Host-only runner或外部provider exactly-once的共享部署声明。

## Risks

- **错误的静默证明：** child发送quiescent后仍有未登记writer；必须同时依赖structured
  registry、OS retirement和root post-check，不能只信frame。
- **PID/process-group误杀：** PID reuse或共享group可能伤及其它服务；必须使用spawn、
  pidfd/start-time、专属group/cgroup与capability绑定。
- **SQLite crash语义：** kill虽退休writer，但partial WAL不等于一致snapshot；eligible与fatal
  evidence必须区分closure claims。
- **远端孤儿：** local kill不能停止HPC/provider；reconciliation与operator cleanup必须显式。
- **凭据扩大：** 新subprocess/env/control channel增加泄漏面；采用fd/broker、allowlist和
  private diagnostics。
- **Chrome时间耦合：** browser hold延长child生命周期；parent deadline必须覆盖并绑定配置，
  不能在失败后移植receipt。
- **双authority迁移：** same-process和child路径若同时启用会双写root/ledger；feature flag按
  campaign冻结并在启动时互斥。
- **supervisor变成control plane：** parent不能写task/approval/operation/report，也不能解释
  agent策略；协议只允许lifecycle与safe handoff。

## Explicit non-goals

- 不在当前 AOX/HMM Goal 中实现本提案任何代码、migration或feature flag。
- 不把所有普通OpenZyme session强制改成一session一进程。
- 不承诺跨机器、多租户或多进程共享SQLite安全；近期仍是单进程SQLite部署约束。
- 不让parent直接调用runner、SSH、Slurm、provider或approval resolve。
- 不用process restart重放任意agent turn或sandbox Python栈；continuation recovery属于独立
  产品架构问题。
- 不把OS kill解释成task failed、operation cancelled或report rejected；这些业务状态只有
  canonical product mutation能写。
- 不在fatal evidence中补造final workspace、event high-watermark、ledger-after或artifact
  completeness。
