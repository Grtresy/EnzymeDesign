## Context

当前产品路径已经有 `ControlledOperation`、`ApprovalRequest`、`ContinuationState`、`AgentRuntimeSignal` 和 `SessionRuntimeLease`，但这些对象仍由一条同步调用栈串在一起：agent turn 调用 `sandbox.exec`，sandbox 内 SDK 通过 control socket 建立 operation/approval/continuation，Host control worker 在 `_wait_for_approval_and_claim()` 中轮询，批准后同一 worker 直接调用 adapter，`AgentRuntimeScheduler` 则在整个 turn 返回前持有 signal claim 与 session lease。`POST /v3/sessions/{session_id}/runtime/drain` 同步调用 scheduler，并在 agent turn 收口后才返回 `V3CommandResponse`。

HPC 侧的 Host composition root 已经为一个 Host 生命周期构造单一 `MCPHpcServer`，但 server 内的 `CommandRunner` 每个动作都启动独立子进程。`SSHRunner.exec_run()` 顺序执行 remote layout、input parent/transfer、preflight、payload 和 output fetch；普通 ssh、rsync 与 scp 分别拼接连接参数，没有共享 transport generation。现有 dedup cache 只比较本地 digest 与 remote destination，不能证明远端 bytes 仍然一致；direct SSH payload 也没有可查询 dispatch receipt。

现有安全基础必须保留：

- session lease 与 signal fencing 阻止 stale agent worker 覆盖新 owner；
- approval 绑定 immutable operation digest、route、输入和 runtime identity；
- runner 只接受 catalog-authorized input、declared output 与 server-generated opaque `run_id`；
- public projection 不暴露 credential、SSH target、remote path、ControlPath、provider handle 或 Host storage path；
- capability terminal 只表示 outcome/evidence ready，业务 task 仍只能由 agent 显式 `task.finish` 终结；
- 单进程 SQLite 是当前唯一 writer deployment，不为未来多 Host 预引入分布式队列或共识。

本设计整合以下 proposal，但不让其中任何对象草图形成并列 authority：

- `runtime-hpc-reliability-refactor-roadmap.md`
- `durable-hpc-transport-staging-and-dispatch-reconciliation.md`
- `nonblocking-supervised-continuation.md`
- `durable-async-controlled-operation-and-quiescent-sealing.md`
- `controlled-operation-outcome-unknown-after-response-failure.md`
- `process-isolated-live-attempt-supervision.md`

## Goals / Non-Goals

**Goals:**

- 用一个 canonical `ControlledOperationExecution` 表达 external effect 的 admission、dispatch、等待、result、reconcile 和 terminal truth。
- approval 或 external wait 出现后，在短且有界的时间内 park 当前 agent/tool invocation，释放 signal claim、session lease 和 HTTP drain request。
- 由独立、可 fencing 的 Host durable-work supervisor 推进 operation execution、attached continuation delivery 和 explicit runtime command。
- 将 `/runtime/drain` 改为 durable command admission：POST 返回 `202 + command_id`，状态通过 session-scoped GET 查询。
- 由每个 Host 的 runner server 按 target/config/credential policy identity 持有 OpenSSH ControlMaster pool，并让 ssh/rsync/scp 共享同一连接编译器。
- 仅在能够证明 scientific payload 尚未发生时执行同 operation、同 approval、同 digest 的 bounded recovery；dispatch ambiguity 永远不 blind replay。
- 以通用 mutation authority、writer registry、seal generation 和 quiescence receipt 阻止 post-freeze canonical write。
- 通过 additive schema、owner-mode freeze、route gate 和 drain-before-disable 使每个 slice 可回滚，且 legacy/new owner 永不同时 dispatch 同一 operation。

**Non-Goals:**

- 第一阶段不恢复任意 Python 调用栈；只有同进程 `attached_process` 可以继续原 SDK call，Host restart 后缺失 process 必须显式 recovery-fail。
- 不承诺外部 provider/HPC exactly-once；只承诺本地 admission/dispatch authority 单一、可验证幂等/reconcile，以及无法证明时保持 unknown。
- 不在本变更中实现 remote SSH daemon、交互式持久 shell、通用 content-addressed remote cache 或 Slurm job-internal AOX attestation。
- 不引入 Redis、Celery、Kafka、多 Host writer 或跨进程共享 SQLite ownership。
- 不自动改变 backend、科学参数、approval、plan 或 task status；retry policy 只恢复完全相同的机械 phase。
- 不把 `ControlledOperationExecution`、runtime command、continuation 或 quiescence 变成第二套 task/workflow graph。
- 不用新的 live `rxx` attempt 代替 deterministic、focused 和 non-live verification。

## Decisions

### 1. 一个 umbrella change 与一条 canonical ownership 链（D1）

本重构保持在 `runtime-hpc-reliability-refactor` 一个 OpenSpec change 中，按 migration slice 和语义提交拆分。Runner 私有状态与 Host 产品状态使用稳定引用关联，但不共享 authority：

```text
agent/task strategy
        |
        v
ControlledOperation + ApprovalRequest       logical intent / approval
        |
        v
ControlledOperationExecution                only external-effect owner
        |                         \
        v                          v
backend adapter             RunnerAttempt / provider attempt
        |                          (private execution evidence)
        v
immutable result handle + artifact set
        |
        v
ContinuationState + delivery generation     SDK/tool delivery owner
        |
        v
AgentRuntimeSignal wakeup                    next short agent turn
```

`ControlledOperation` 继续拥有 logical operation identity、approved digest、route、inputs/outputs 与 approval binding。它现有的 `status/result/error` 字段在迁移期成为由统一 transition service 写入的 compatibility projection，不再允许 sandbox worker、execution worker 和 recovery path 分别 raw-save 成为多 writer。

选择 umbrella change 而不是 runner/runtime 两个 change，是因为 operation identity、effect certainty、result handle 与 reconcile policy 必须在 transport 和 continuation 两边使用同一闭集。拆分 change 容易在中间形成两个 execution owner。

### 2. Canonical `ControlledOperationExecution`（D2）

为每个进入新 owner mode 的 `ControlledOperation` 创建且只创建一个 execution record；同一 execution 内可以有多个 lease claim 或 proven-no-effect phase attempt，但 agent 想做 materially changed retry 时必须创建新的 logical operation。

```text
ControlledOperationExecution@1
  execution_id
  operation_id (UNIQUE)
  session_id / task_id / lane_id
  owner_mode: durable_async_v1
  operation_digest / approval_digest
  route_policy_id / selected_backend / adapter_policy_id
  lifecycle_state:
    awaiting_approval | ready | claimed | dispatching
    waiting_external | result_staging | result_ready
    reconcile_required | terminal
  terminal_outcome: succeeded | failed | cancelled | recovery_failed | null
  effect_certainty:
    no_effect | dispatch_in_doubt | effect_known | terminal_known
  retry_eligibility:
    same_phase_safe | verify_then_retry | reconcile_required | terminal
  dispatch_generation / state_version
  lease_owner / lease_token / lease_expires_at / fencing_token
  backend_handle_ref (Host-private, nullable)
  result_handle_ref / result_digest / artifact_set_digest (nullable)
  error_code / safe_error_summary
  created_at / updated_at / terminal_at
```

配套使用两个从属记录：

1. append-only `ControlledOperationExecutionEvent` 保存 state version、dispatch generation、phase、effect certainty、fence、safe receipt digest 与时间；它是审计 journal，不是另一个 reducer；
2. immutable `ControlledOperationResultHandle` 保存 Host-owned bounded result envelope、artifact set digest、origin、operation/dispatch identity 与 terminal outcome。大 payload 只能进入 sealed artifact，不能内联进 SQLite 或 control socket。

核心 transition：

| From | Trigger | To | Effect rule |
| --- | --- | --- | --- |
| `awaiting_approval` | exact approval approved | `ready` | 未触发 external effect |
| `awaiting_approval` | rejected/expired/cancelled | `terminal` | `no_effect`, failed/cancelled result |
| `ready` | fenced worker claim | `claimed` | 只取得 execution authority |
| `claimed` | persist dispatch intent | `dispatching` | generation 单调增加 |
| `dispatching` | backend acceptance/known sync start | `waiting_external` 或 `result_staging` | 保存 opaque receipt；不得保存 public locator |
| `dispatching` | transport lost and no no-effect proof | `reconcile_required` | `dispatch_in_doubt`; automatic replay count = 0 |
| `waiting_external` | bounded poll observation | `waiting_external` / `result_staging` / `reconcile_required` | 每个 poll 是独立 lease slice |
| `result_staging` | result/artifacts atomically promoted | `result_ready` | immutable result handle 成为 delivery source |
| `result_ready` | terminal commit | `terminal` | execution terminal 与 delivery terminal 分离 |
| any pre-effect state | deterministic failure | `terminal` | `no_effect`, failed result |

execution lease 与 session lease、signal claim、sandbox process epoch、mutation seal generation 是四种不同 authority。每次 claim 分配单调 fencing token；外部调用前做 fence preflight，每次 canonical commit 在同一 SQLite transaction 中比较 `state_version + lease_token + fencing_token`。lease 过期只允许新 owner 重新 claim，不证明远端 effect 未发生。旧 callback 只能写 Host-private late-callback diagnostic，不能写 canonical result/artifact/event。

替代方案是扩展 `ControlledOperation.status` 承载所有 execution 字段；拒绝该方案，因为 logical intent 与可多次 claim/reconcile 的 external lifecycle 更新频率、fencing 与 retention 不同，且会继续让 continuation 和 adapter 争写同一 row。

### 3. Durable-work supervisor 与 recovery level（D2）

FastAPI lifespan 拥有一个 `V3DurableWorkSupervisor`，使用独立 repository scope 轮询/接收 notifier，并运行三类 typed worker：

- `RuntimeCommandWorker`：claim 一条 explicit drain command，运行 bounded agent scheduler batch；
- `ControlledOperationExecutionWorker`：claim/dispatch/poll/materialize execution，不持 session lease；
- `ContinuationDeliveryWorker`：claim ready continuation，把 exact result/error 交回 attached sandbox 或记录不可恢复 delivery，并排队 agent wakeup。

这些 worker 可以共享一个 lifecycle service 和并发 limiter，但各自使用不同表、lease type 和 fence。它们不能通过一个全局 `operation_lock` 包住 provider/HPC 等待；每个数据库 mutation 是短事务，外部等待发生在事务外。

现有可选 `V3BackgroundRuntimeService` 继续负责“没有显式 drain command时是否自动消费 agent signals”的产品配置。explicit runtime command worker 不依赖该开关，否则 AOX 关闭 background runtime 时 `202` command 会永久无人消费。

启动 recovery 按 canonical state 分流：

- `ready` 或具有 runner/provider no-effect proof 的 work 可在更高 fence 下继续；
- 有 opaque Slurm/provider handle 的 work 查询 exact handle；
- direct SSH `dispatch_in_doubt` 进入 `reconcile_required`，没有 receipt 时保持 unknown 且不重投；
- result handle 已存在时只恢复幂等 delivery；
- `attached_process` continuation 的 process/socket 不存在时，delivery 进入 `recovery_failed`，但已完成 external result 保留为 evidence 并唤醒 agent；
- 历史 legacy continuation 不补造 fence、handle 或 success，继续使用显式 legacy recovery failure。

第一阶段因此提供“同进程 non-blocking park + durable external effect/result”，不宣称任意 sandbox Python stack restart-safe。

### 4. `attached_process` 后再做 registered SDK journal（D3）

第一实现只支持 `resume_strategy=attached_process`：

1. sandbox control handler 在一个事务中写入 operation、approval、execution、continuation 与 durable event；
2. outer sandbox supervisor 收到 canonical park notification 后，把仍存活的 sandbox process/control channel 交给 Host-private live-process registry；
3. agent tool runtime 返回结构化 `suspended_waiting_approval`/`suspended_external_operation`，完成原 signal claim并释放 session lease；该结果不是 tool terminal 或 task terminal；
4. approval resolve 只更新 approval/continuation/execution readiness 与 outbox，不直接调用 adapter或 drain agent；
5. execution result durable 后，delivery worker 在 process epoch/fence 匹配时向原 channel发送 bounded result；sandbox 可以继续并产生后续 SDK call；
6. sandbox run 真正 terminal 后，engine/capability outcome ready，才排队 owner agent 的新 signal。

`ContinuationState` 在 additive migration 中增加：originating signal/agent/task/lane/tool-call 或 invocation identity、sandbox workspace/runtime identity、process epoch、resume strategy、delivery state/generation/result digest、state version、claim lease/fence。它不保存 external backend handle，也不拥有 dispatch。

后续 `journaled_sdk_call_boundary` 只允许 registered `openzyme_pipeline` SDK method：输入必须完全 artifact/digest-addressed、method policy 声明 replayable boundary，且新 sandbox 从 immutable source/runtime identity 恢复。任意 Python locals、open file、network socket 或未登记 side effect 不进入 journal。该策略不在第一阶段启用。

替代方案 journal-first 会延后最关键的 lease 释放并扩大 checkpoint 信任面；attached-only 作为永久终态又无法支持 restart，所以采用分阶段策略并在 public projection 中诚实暴露 recovery level。

### 5. Command-based `/runtime/drain`（D4）

现有 `command_receipt_records` 受 `status='completed'` CHECK 和 immutable trigger 约束，只适合保存已完成 command response，不能直接变成 mutable async command。因此新增窄 `RuntimeCommandRecord@1`：

```text
command_id / session_id / command_type=runtime.drain
request_digest / idempotency_key
status: accepted | claimed | completed | failed | locked | cancelled
max_signals / max_steps_per_agent / auto_enqueue_ready_tasks
claim owner / lease expiry / fencing token / state version
bounded outcome summary / safe error
accepted_at / started_at / completed_at
```

API 合同：

- `POST /v3/sessions/{session_id}/runtime/drain` 在 admission transaction 中验证 access、request 与 idempotency，创建 command/outbox，然后始终返回 HTTP `202`；
- response 使用新的 closed DTO，至少包含 `session_id`、`command_id`、`status`、`status_url`、`accepted_at`；不返回 composite workspace；
- `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` 返回当前状态与 bounded outcome，严格校验 command 属于该 session；
- 可选 `Prefer: wait=<seconds>` 只在 server cap（首版不超过 2 秒）内等待同一 command 状态，POST 仍返回 `202`，绝不等待 approval/provider/HPC；
- 同一 idempotency key 与同一 digest 返回同一 command id；digest 冲突为 `409`。immutable command receipt 可以保存 admission response，但 mutable status 只来自 runtime command row；
- command 在 bounded scheduler batch完成或产生 suspension 后即 terminal。被 park 的 external operation 不属于 command lifetime；结果稍后通过 continuation/agent signal推进；
- session lease conflict 令该 command 以 `locked` terminal 收口并给出 safe retry hint，不并发推进，也不自动建立 replacement command。

这是一项明确 breaking change。调用方、CLI、eval、UI/debug 与 AOX driver 必须迁移到 POST admission + GET status；不保留静默同步 fallback。

### 6. Runner-owned ControlMaster transport（D5）

`MCPHpcServer` 创建并终止 `SshTransportManager`，pool key 是 Host-private `SshTransportIdentity@1` digest：runner deployment/config digest、normalized target、operator SSH policy identity、credential/host-key policy identity和 effective transport policy。caller、RunSpec、sandbox 与 agent 都不能覆盖这些字段。

第一阶段使用 OpenSSH ControlMaster/ControlPersist，不使用交互式 shell：

- control socket 位于 runner-owned mode-`0700` 私有目录，socket/path 不进入 artifact/public diagnostic；
- 每个 command、preflight、mkdir、hash、rsync/scp transfer 仍是独立 channel，保留独立 argv、cwd/env、timeout、stdout/stderr 和 phase；
- ssh、scp、rsync 的 options 由一个 compiler 产生；rsync `-e` 只序列化该 compiler 的安全 options；
- per-target semaphore 限制 active channels，首版默认 4；manager 使用 ownership nonce/generation 识别 stale socket；
- 首版 policy 默认 `ControlPersist=300s`、一次 initial connect 加最多一次 pre-effect recovery、bounded exponential backoff；具体值进入 versioned effective-config digest并可由 operator config下调，caller不可提交；
- shutdown 先停止新 channel，等待 bounded active channel收口，记录任何 post-dispatch unknown，再请求 master exit。master 关闭不被解释为 remote payload 已取消。

per-run master 仍会重复握手且难以让 upload/preflight 共享 health；remote daemon 扩大部署与信任边界；interactive shell 会引入 cwd/env 状态泄漏。因此选择 per-Host/per-identity ControlMaster pool。

### 7. Runner phase journal、remote verification 与 retry authority（D6）

runner 在现有 artifact store 内为每个 server-generated run id 原子写入 `runner_attempt@1` snapshot，并追加 phase event journal。它是 runner-private execution evidence，包含 operation/execution digest refs、transport identity/generation、phase/state version、attempt counts、effect certainty、retry eligibility 与 opaque receipt ref；Host 只保存 opaque runner run id 和经过验证的 safe receipt digest。

phase 闭集：

```text
allocated -> transport_ready -> remote_layout_ready
-> input_staging -> inputs_verified -> preflight_passed
-> dispatch_prepared -> dispatching -> remote_pending
-> remote_terminal -> outputs_fetching -> outputs_verified -> terminal
```

每个 staged input 绑定 ordinal、authorized artifact/content digest、remote destination digest 与 verification state。cache hit 或 partial transfer 后必须运行 runner-owned remote verifier：普通文件使用 SHA-256；目录使用 versioned canonical tree manifest。verifier缺失、输出不闭合或 digest 不等时不得跳过 transfer/preflight。首版不建立跨 run immutable remote content cache。

自动动作由 `retry_eligibility` 而不是 boolean `retryable` 决定：

| Phase/failure | Certainty | Automatic action |
| --- | --- | --- |
| master/layout 发送前 | `no_effect` | 重建 generation，重试 exact phase |
| layout/input-parent transport failure | scientific payload `no_effect` | 重试幂等 mkdir |
| partial input transfer | payload `no_effect` | remote verify 后 resume/replace exact input |
| preflight transport timeout | payload `no_effect` | 重验 inputs，再重试 exact preflight |
| deterministic preflight failure | `no_effect` | terminal，不因 reconnect 重复 |
| dispatch 前且 runner 证明未被接收 | `no_effect` | 同 generation policy 下重试 exact dispatch |
| dispatch 发送后丢失 receipt | `dispatch_in_doubt` | `reconcile_required`，禁止 replay |
| remote terminal 后 fetch failure | `effect_known` | fetch/verify exact outputs，不重跑 payload |
| output digest/contract conflict | `terminal_known` | quarantine + terminal failure |

每次恢复必须仍绑定相同 run id、operation/execution id、approval digest、route policy、RunSpec digest 与 expected outputs；任一漂移立即 terminal。runner policy首版只给一个额外 pre-effect attempt，预算耗尽后返回一个 terminal safe failure，不把 retry decision交给隐式 while-loop。

### 8. Direct SSH post-dispatch fail closed（D7）

ControlMaster 只降低连接建立失败率，不提供 payload receipt。首版保留 `ssh_direct`：

- payload dispatch 前可以按上述 proof recovery；
- payload bytes 可能被 remote shell接收后若连接/ack丢失，runner写 `dispatch_in_doubt`，Host execution写 `reconcile_required`；
- 没有同一 process/job 的 durable receipt 时，reconcile只能报告 unknown，automatic resubmit count 必须为零；
- 已知 remote terminal 而仅 output fetch失败时可以继续 fetch同一 run outputs；
- Slurm 继续使用既有 opaque submit/status/cancel/fetch handle，但 AOX 不切换到 Slurm，直到 job 内部 same-execution toolchain attestation 成立。

`ssh_supervised_receipt` 和 job-internal Slurm attestation 保留为后续显式 change。现在实现 remote wrapper 会扩大安全、cleanup、signal 与 receipt atomicity范围；立即迁 Slurm 会削弱当前 AOX same-login-shell identity证明。

### 9. Generic Host mutation authority 与 quiescence（D8）

新增通用 attempt/session-scoped mutation authority，不把 AOX campaign row变成产品真状态：

```text
MutationScope@1
  scope_id / scope_kind / scope_ref / parent_scope_id
  state: open | freezing | quiescent | sealed | failed
  generation / mutation_fencing_token / policy_id
  writer_coverage_manifest_digest
  opened_at / freeze_requested_at / quiescent_at / sealed_at

MutationWriter@1
  writer_id / scope_id / owner_kind / owner_ref / process_epoch
  state: registered | retiring | retired | rejected
  parent_writer_id / fencing_token / registered_at / retired_at

QuiescenceReceipt@1 (immutable)
  scope_id / seal_generation / policy and coverage digests
  writer-set digest / terminal-proof digest
  SQLite/event/artifact high-watermarks
  snapshot digest / issued_at
```

freeze transaction 先把 scope 从 `open` 改为 `freezing` 并提高 fence；此后禁止新 writer registration。已登记 writer 必须显式 retired，或由可信 parent/process supervisor证明对应 process epoch 已终止。lease expiry、HTTP response、thread handle丢失、runtime idle、empty queue 或 remote timeout都不证明 quiescence。

所有纳入 coverage manifest 的 canonical repository/artifact/event write 在 transaction/atomic-publish 前比较 scope generation/fence。旧 generation callback 只能进入 scope外的 Host-private quarantine diagnostic。只有 writer active count为零、coverage完整、SQLite/outbox checkpoint与 artifact publish高水位稳定时才能写 immutable receipt并进入 `quiescent`；seal使用该 receipt和同一 generation，seal后任何 canonical write fail closed。

AOX 是第一个 consumer，但必须通过 generic scope API登记 runtime command、agent turn、sandbox process、controlled-operation worker、runner callback、artifact publisher与event/outbox writer。若 coverage 未知或 writer不能退休，只能保持 NO-GO，不能生成普通 eligible seal。process-isolated fatal evidence仍是独立后续能力；本变更不把杀死本地 child解释为远端 effect取消。

### 10. Result、delivery 与 public projection 分离

external effect outcome 与 response delivery outcome必须分别持久化：

- execution terminal表示 external result/failure已成为 Host canonical evidence；
- continuation delivery表示 exact SDK/tool consumer是否收到该 result；
- agent wakeup表示新 turn可以读取 evidence；
- task terminal仍只由 `task.finish` 表示。

public workspace/world facts只投影 stable operation/execution/continuation ids、lifecycle、effect certainty、safe phase、timestamps、retry eligibility、recovery action、result/artifact refs和bounded diagnostic。以下字段永不公开：lease/fencing token、claim owner/expiry、backend handle、provider poll URL、SSH target/user、ControlPath、remote dir/PID/job id、credential、private receipt locator与raw stdout/stderr。

兼容 `ControlledOperation.status` 由同一 transition service按如下规则投影：waiting approval前后保持现有语义；execution active映射 `RUNNING`；result和delivery都成功后映射 `COMPLETED`；external failure已向consumer收口映射 `FAILED`；结果存在但attached delivery在restart后丢失映射 `RECOVERY_FAILED`，同时新字段仍显示external outcome，避免把delivery failure伪装成effect未发生。

### 11. Module与repository边界

预期代码归属：

- `packages/openzyme-domain`：新增 closed enums/dataclasses/DTO，不包含scheduler逻辑；
- `packages/openzyme-core`：execution/runtime-command/continuation/quiescence repositories、transition services、fencing、projection、world facts和migrations；
- `packages/openzyme-engines`：route-specific adapter executor/reconcile policy和durable result materialization；不得维护第二个operation state machine；
- `packages/openzyme-pipeline`：registered SDK suspension/result protocol与bounded result decoding；不接触runner/SSH；
- `apps/openzyme-host-api`：durable-work supervisor lifecycle、202/GET API、composition、recovery、security与health；route handler保持薄；
- `packages/openzyme-execution`：Host到runner的opaque adapter和status/reconcile调用；
- `apps/mcp-hpc-runner`：SSH transport manager、option compiler、attempt journal、staging verification和runner-private recovery；
- `packages/openzyme-tools`：现有tool/RunSpec command contract authority不变。

## Risks / Trade-offs

- [Risk] legacy worker与新execution worker双dispatch同一operation → 以创建时冻结的 `owner_mode`、operation唯一execution row、route gate和transactional claim阻止；rollback只能停止新admission并drain新owner，不能把in-flight row切回legacy。
- [Risk] attached sandbox process仍占用本机资源 → live-process registry按process epoch登记、限制并发并纳入mutation writer；它释放agent/session/HTTP资源，但不伪称零资源或restart-safe。
- [Risk] execution lease heartbeat失效时external call仍在进行 → stale worker失去canonical commit权；新owner按effect certainty reconcile，不能仅因lease expiry重投。
- [Risk] ControlMaster socket stale、串错credential或跨deployment复用 → pool identity纳入全部authority相关config，socket目录私有，generation/nonce校验，config漂移建立新pool而非复用旧socket。
- [Risk] ControlMaster成为单点并放大并发 → per-target semaphore、health check、degraded generation隔离和bounded reconnect；每个channel仍有独立timeout与结果。
- [Risk] remote hashing增加preflight成本 → 首版只做per-run verification并缓存本次已验证receipt；正确性优先于未经证明的dedup，跨run content cache延后。
- [Risk] direct SSH payload可能实际成功但Host保持unknown → 这是D7刻意的安全trade-off；保留private evidence、禁止duplicate effect，后续用supervised receipt或Slurm attestation改善liveness。
- [Risk] async drain破坏现有CLI/eval/AOX driver → 同change迁移全部caller并加contract tests；不保留隐式200 fallback，旧caller在cutover前通过显式version gate fail fast。
- [Risk] result durable但attached delivery丢失 → 分离effect/delivery projection，保留result，wake agent查看recovery evidence；不得重跑effect来制造一个可投递结果。
- [Risk] writer registry覆盖不完整导致假quiescence → coverage manifest必须枚举writer category并由测试扫描/故障注入证明；未知category阻止receipt/seal。
- [Risk] SQLite contention被误判为provider/transport failure → DB busy/locked使用独立bounded retry taxonomy；外部effect状态不因本地lock error被重置。
- [Risk] schema与事件量增长 → execution event、runner journal和public projection全部有closed fields/retention/bounds；大payload进入artifact，workspace只给summary。
- [Risk] 多个新worker增加shutdown复杂度 → 单一lifespan supervisor先停止claim、fence active owner、drain短commit，再处理attached process；shutdown不能把remote action宣称为cancelled。

## Migration Plan

### Slice 0：contract、schema与shadow observability

1. 增加 additive migrations、domain types、repositories和transition property tests，但不切换dispatch。
2. 为现有路径shadow记录operation timing、approval park时长、session lease占用、runner phase/effect certainty、writer category与public redaction；shadow数据不授权retry。
3. 建立统一owner/caller inventory和deterministic fault seams；更新proposal引用但稳定产品文档仍描述当前行为。
4. 为每个operation冻结 `owner_mode=legacy_sync|durable_async_v1`；历史和已开始row均标为legacy/non-resumable，不补造receipt/fence。

Rollback：关闭shadow writer并保留additive tables；无行为变化、无需data downgrade。

### Slice 1：persistent SSH与pre-effect recovery

1. 先集中编译ssh/scp/rsync options，运行differential argv/security tests，行为仍为独立连接。
2. 在config gate后启用runner-owned ControlMaster、private socket lifecycle和channel limiter；每个attempt冻结effective policy digest。
3. 加入runner attempt journal、remote staged-byte verification和统一layout/input/preflight failure schema。
4. 仅为proven pre-effect phase启用一个额外attempt；dispatch/fetch fault matrix验证payload dispatch count最多为一。
5. 完成non-scientific soak后才允许AOX所用runner config启用新transport；仍不运行编号campaign。

Rollback：新attempt改回`transport_mode=disabled`；已经用ControlMaster创建的attempt继续按其冻结policy收口，不由另一launcher重复payload。关闭/清理私有master不删除run evidence。

### Slice 2：durable controlled-operation execution

1. 启动durable-work supervisor、execution claim/fence、result handle和reconcile service，先接fixture/non-cutover route。
2. 按route迁移provider和HPC adapter；每个route必须声明dispatch proof、poll/reconcile和result policy。未知route fail closed。
3. Host startup改为逐execution state reconcile；direct SSH unknown不重投，Slurm/known handle只查询exact handle。
4. projection/world facts读取新execution并事务性写compatibility operation status；移除新owner路径中的直接adapter调用。

Rollback：停止新`durable_async_v1` admission，继续drain/reconcile现有新owner rows；legacy只处理其原有rows。不得把新row改为legacy或重复调用adapter。

### Slice 3：non-blocking continuation与202 drain

1. 扩展continuation identity/fence/delivery字段和live-process registry，先在fixture sandbox证明park后释放signal/session lease。
2. approval resolve改成短transaction + outbox；execution/delivery worker恢复同一operation，原control-socket busy wait从新owner路径移除。
3. 增加runtime command records、POST 202、GET status、dedicated command worker和bounded `Prefer: wait`。
4. 迁移Host API tests、CLI、eval、UI/debug和AOX driver到command polling；明确background runtime开关不影响explicit command worker。
5. restart tests证明attached process缺失时delivery recovery-fail但external result不丢、不重跑。

Rollback：API切换前保留显式deployment contract gate；切换后若回滚应用，只允许在没有active durable command/continuation且migration audit通过时降级。in-flight新owner必须先drain或保持新版本恢复，禁止同步fallback接管。

### Slice 4：generic quiescence、retirement与稳定合同

1. 对runtime command、agent turn、sandbox、operation worker、artifact/event publisher接入writer registry和repository commit fence。
2. AOX attempt通过generic mutation scope请求freeze、等待writers显式retire、生成quiescence receipt，再seal evidence；unknown coverage或late write保持NO-GO。
3. 退役legacy control-socket approval polling、新owner同步adapter调用和duplicated SSH option builder；用`rg` caller audit和row-version metrics证明无active consumer。
4. 同步 `docs/OpenZyme架构设计.md`、`docs/v3/04-public-interfaces.md`、`05-agent-runtime.md`、`06-top-level-llm-loop.md`、execution pipeline与runner配置文档。
5. 运行focused tests、完整non-live mainline、security/public projection、migration/rollback、restart/fault和non-scientific SSH soak。

Rollback：seal capability可以停止新scope admission，但已经freeze/sealed的generation绝不reopen；回滚只能创建新的scope/generation。writer fence和历史receipt保持可读。

### 恢复 `rxx` 的独立闸门

只有以下证据同时成立才允许另行决定恢复live campaign：ControlMaster lifecycle/soak通过；每个runner phase fault得到正确effect certainty；approval park在bounded deadline内释放signal/session/HTTP；exact operation只dispatch和deliver一次；lease expiry/restart的stale writer被fence；success/failure closure都有真实quiescence receipt；focused和non-live mainline全绿；稳定文档与public projection一致。恢复live不是本change实现完成的替代证明。

## Open Questions

没有阻塞本change开工的用户决策；D1-D8均按推荐值冻结。以下是明确延后的独立设计，不得在实现中静默选择：

- direct SSH后续采用 `ssh_supervised_receipt` 还是job-internal Slurm attestation；首版保持unknown-safe。
- registered Pipeline SDK何时从`attached_process`升级到`journaled_sdk_call_boundary`；首版只建立schema/strategy枚举，不启用replay。
- 是否为bounded fatal attempt evidence引入process-isolated supervisor/cgroup；generic quiescence本身只在writers确实退休时签发receipt。
- 单进程SQLite以外的多Host/HA模型；当前fencing只在受信单Host deployment合同内成立。
