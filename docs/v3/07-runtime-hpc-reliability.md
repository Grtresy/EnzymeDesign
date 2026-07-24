# Runtime / HPC 可靠性边界

## 1. 文档定位与当前状态

本文描述已经进入主线实现的 Runtime/HPC 可靠性合同。它是
`runtime-hpc-reliability-refactor` 的稳定架构读物，不是 live campaign 的
GO 证明。

截至 2026-07-21：

- schema、durable execution、attached-process continuation、command-based drain、
  generic mutation quiescence 与 runner persistent transport 已落地；
- deterministic/focused/non-live 验证已全部通过；
- 外部 real-SSH transport-only soak 与 disabled-mode rollback audit 已通过；
- 当前配置已恢复 disabled，且没有启动任何编号 `rxx` 实验；是否恢复 campaign 仍由
  operator 显式决定。

这套机制只忠实表达执行与闭包事实。它不替 agent 选择科学策略，不把 capability
terminal、runtime idle 或 quiescence seal 解释为业务 task terminal；业务任务仍由
agent 显式调用 `task.finish` 或经已文档化的机械迁移终结。

## 2. 单一 ownership 链

```text
agent / task strategy
        |
        v
ControlledOperation + ApprovalRequest        logical intent and approval
        |
        v
ControlledOperationExecution                 only external-effect owner
        |                         \
        v                          v
provider / HPC adapter          RunnerAttempt
        |                       private execution evidence
        v
immutable result handle + atomic artifact set
        |
        v
ContinuationState + delivery generation      exact SDK/tool delivery owner
        |
        v
AgentRuntimeSignal                            next bounded agent turn
```

`ControlledOperation.status/result/error` 是 compatibility projection。对于
`owner_mode=durable_async_v1` 的 row，只有
`ControlledOperationExecutionTransitionService` 可以派生这些字段；sandbox、adapter、
callback 和 recovery path 的 raw save 会在 repository boundary 被拒绝。

Runner 的 `runner_attempt@1` 冻结 run、operation/execution、approval、RunSpec、route、
expected outputs、input、effective config、transport identity 与 policy digest。它提供
phase/effect/recovery 证据，但不成为 task、approval 或 Host execution 的并列 reducer。

## 3. 五个彼此独立的 authority boundary

| Authority | 负责什么 | 明确不负责什么 |
| --- | --- | --- |
| session runtime lease + signal claim | 某个 bounded agent turn 谁能推进 session runtime | 外部 effect、结果投递、task 终态 |
| sandbox process identity + process epoch | 同一 attached process 发起的后续 Host call，以及其 process-scoped writer parentage | session 调度、external effect ownership、result delivery claim |
| execution lease + fence | 某个 `ControlledOperationExecution` 谁能 dispatch/poll/reconcile/materialize | session agent 调度、SDK process identity |
| continuation delivery claim + fence | exact result 向 exact process epoch 的一次投递 | 接管该 process 后续 Host call、重放 scientific effect、任意 Python stack 恢复 |
| mutation scope generation + writer fence | 哪些 Host writer 仍可改变 canonical evidence，以及何时可出具 receipt/seal | 业务成功、报告质量、下一步科学策略 |

这些 authority 不得互相推断。例如 session lease 过期不表示 provider/HPC 已取消；合法
continuation delivery 不会把 delivery 或旧 session authority 安装到 sandbox process；本地
sandbox process 退出只证明对应 local writer 可以退休；execution success 不表示
continuation 已投递；continuation delivery 也不表示 task completed。

## 4. Durable controlled operation

进入 `durable_async_v1` 的 operation 在一个 transaction 中创建：

- operation 与 frozen owner mode；
- approval binding；
- canonical execution；
- immutable dispatch request；
- attached continuation origin/process identity；
- append-only admission event。

Execution worker 每次只做一个短 slice：claim、dispatch、poll/reconcile、result staging、
materialize 或 terminalize。外部调用期间不持有 SQLite transaction，也不借用 session
lease。每次外部调用前，以及每次 callback canonical commit 前，必须重新比较 execution
lease token、fence、state version、immutable identity 与当前 mutation writer authority。

每个 durable worker outcome 还必须显式携带 typed `semantic_progress`。execution worker 只比较
canonical lifecycle、terminal/effect/retry、dispatch generation、backend/result identity 与
result/artifact-set digest；claim/lease/fence/version/timestamp、diagnostic/event churn 或 unchanged
poll/reconcile 不计进展。runtime-command 只在 terminal command commit 后为 true，continuation
只在 delivered/recovery-failed commit 后为 true；idle、race、fenced/unclaimable work 和
database busy 均为 false。Host serialization seam 不为缺失/非 boolean 字段提供 action fallback。
supervisor 保留 no-progress diagnostics，但只统计 true，且只有一个 bounded tick 的全部 slots
都为 true 时才可通知一次可能 backlog；periodic poll 负责之后的 unchanged external state，
该 scheduling fact 不授权 replay、effect、task terminal 或科学策略。

Effect certainty 是闭集：

- `no_effect`：只允许完全相同 phase 的有界机械恢复；
- `dispatch_in_doubt`：禁止 replay，只能保留 reconciliation-required；
- `effect_known`：只能查询 exact persisted handle；
- `terminal_known`：可以恢复结果落盘或 declared-output fetch，不能重跑 payload。

Result handle 与 artifact set 是 Host-owned immutable records。partial、digest-invalid 或
identity-drifted outputs 不得 promotion。Execution terminal、result ready、continuation
delivery、agent wakeup 与 task business terminal 是五个不同事实。

Provider 的成功 callback 不是唯一 result materialization 入口。若 external effect 已完成、
同一 request 的完整 artifacts 与最后一个 `provider_observation.json` 已登记，但 callback 在
canonical commit 前丢失，reconcile 只能读取该 operation/request 的 sealed
`provider_request.json` 与 `provider_observation.json`：逐件核 content/sealed digest、strict
JSON closed schema、route/provider/config/output-dir/artifact identity，再恢复原 provider
summary、validation、warnings 与 `transcript_manifest`。control document 限 `8 MiB`；完整
canonical immutable result envelope 与 core 共用 `256 KiB` 上限，inline `bounded_summary` 只是
其中一部分，bulk identities 必须保留在 digest-bound artifact。EBI HMMER 的完整候选身份只由
`provider_parsed/parsed_hits.csv` 承载，不复制进 summary。missing、tamper、schema/identity drift
或任一 envelope 超限均转为 `terminal_known` failure；若 terminal-known observation 本身未通过
closed validation，execution 直接以 `recovery_failed` 终结，不允许通用 recovered 摘要、provider
replay、alternate route 或重复 claim/reconcile 热循环。

## 5. Non-blocking continuation 与 runtime command

Durable SDK call 遇到 approval/external wait 时，Host 会 park exact sandbox process，记录
`sandbox_run/workspace/runtime_identity/process_epoch/tool_call/invocation/signal`，并把进程
交给 Host-private live-process registry 与 outer sandbox supervisor。原 agent turn、signal
claim、session lease 和 HTTP request 在 bounded 时间内返回。等待中的 process 不占 agent
并发槽，也不完成、失败、取消或替换 task。

当前唯一启用的 resume strategy 是 `attached_process`：

- 同一 Host 进程内可向 exact process epoch 投递一次结果；
- delivery generation、result digest 与 process identity 任一不符即 fail closed；
- Host restart 后 registry 丢失时，continuation 明确进入 recovery failure，已完成的外部
  execution/result 仍被保留且绝不重跑；
- `journaled_sdk_call_boundary` 只是关闭的 schema 值，任意 Python stack replay 尚未实现。

同一 attached process 在一次 durable result delivery 后可以继续执行 source 中的下一条 SDK
语句，但这不会复活原 agent turn 的 session lease。control server 在 process epoch 启动时
获取 immutable sandbox-process Host context，并跨 park/delivery 保持；delivery worker 只完成
短投递，不替换该 context。`hpc.fetch_outputs` 经 typed `SandboxHostGateway` 使用 control-server
当前 repositories 与 nested artifact-publisher mutation writer；engine 不能持有 scope factory、
反射 callback 或接受可选 repository escape hatch。若 durable HPC materialization 已在
immutable adapter envelope 中冻结 `run_id/fetch_refs/registered_artifact_ids/output_artifact_ids`，
SDK fetch 对 `run_id` 与逐项 `fetch_refs` 做 exact comparison，对两组 artifact-id
列表按 durable artifact-set 合同规范化排序后检查完整、唯一成员，并保持
operation row 不变；任何 identity/membership drift 都 fail closed。

`POST /v3/sessions/{session_id}/runtime/drain` 只做 durable command admission：

- 必须带 `Idempotency-Key`；
- 始终返回 HTTP `202 Accepted` 与 `runtime_command_status@1`；
- `Prefer: wait=<seconds>` 只允许 `0..2` 秒，超时仍返回 `202`，不会取消 command；
- 通过 response 中的 `status_url` 或
  `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` 查询；
- `locked` 是 command terminal，表示 session lease 被另一个合法 owner 持有；它不会创建
  replacement command 或并发 scheduler；
- public DTO 不含 claim owner、lease/fence、process/socket、Host path 或 private locator。

旧同步 HTTP fallback 已退休。`V3HostApiService.drain_runtime()` 仍作为
`RuntimeCommandWorker` 内部 bounded scheduler executor 存在，不是 public request owner。

## 6. Runner-owned persistent SSH

一个 `MCPHpcServer` 生命周期拥有一个 `SshTransportManager`。manager 按
deployment/config、normalized target、credential policy、host-key policy 与 transport
policy 派生 identity，并为每个 identity 持有隔离的 OpenSSH ControlMaster generation。

关键约束：

- Control root 必须是私有 `0700` 真实目录；symlink、foreign owner、ambiguous socket
  一律拒绝；
- ssh/scp/rsync 共享同一 option compiler 与 `ControlPath`，每个 remote command 仍是
  isolated channel，不依赖持久 shell cwd/env；
- channel concurrency、connect attempts、pre-effect recovery、backoff、health check、
  ControlPersist 与 shutdown 全部由 trusted bounded policy 决定，RunSpec/caller 不能覆盖；
- file staging 使用 exact remote SHA-256；directory staging 使用 ordered bounded canonical
  tree manifest；cache hit 不能代替远端 bytes 验证；
- 只允许一次额外 same-run、same-identity、proven `no_effect` recovery；
- direct SSH 写出 payload 后丢失响应一律进入 `dispatch_in_doubt`，dispatch count 不增加；
- Slurm 只用 exact opaque handle poll/reconcile；当前 AOX 仍不允许把缺 job-internal
  attestation 的 Slurm 当 cutover proof；
- known terminal 后的 output fetch interruption 只恢复 fetch/verify，不重跑 payload；
- shutdown 只退出 proven-owned master，active direct ambiguity 被持久化为 reconcile-required，
  不宣称 remote cancellation。

Transport responses 只公开 closed phase/effect/retry facts、opaque run/artifact refs 与安全
计数；target/user、ControlPath/generation、command、remote/Host path、PID/job id、credential、
private receipt 与 raw log 保持 Host-private。

## 7. Generic mutation quiescence

Mutation scope 是 session 或 attempt 的通用 Host authority，不是 AOX reducer。一个 session
同一时刻至多有一个 `open/freezing/quiescent` scope。Scope 固化 policy、coverage manifest、
generation 与 mutation fence。

Covered canonical writers包括 agent turn、runtime command、sandbox process、controlled
operation、continuation delivery、runner/provider callback、artifact/report publisher、
event/outbox publisher 与 live-token ledger writer。异步 child 必须绑定 active parent；只有
composition root、attempt driver 等明确 trusted root 可以无 parent 注册。

Closure 顺序固定：

```text
open
  -> freeze transaction closes admission and advances fence
  -> old-fence canonical commits fail
  -> every writer/descendant explicitly retires
  -> capture two identical bounded SQLite/event/external snapshots
  -> issue one immutable quiescence receipt
  -> verify receipt + private snapshot
  -> seal exact scope generation
```

Writer retirement不能由 runtime idle、空队列、lease expiry、HTTP 返回、timeout、disconnect
或 missing handle 推断。Exact local process epoch 可以证明 local writer 退休，但不改变外部
effect certainty。

Coverage manifest 列举 session-scoped SQLite、event/outbox、artifact、report 与 ledger
categories。Database triggers 在 commit 时调用 connection-bound authority verifier；artifact、
report、tool-result 与 callback publication 还在 producer boundary 检查对应 category。AOX
consumer 的 external snapshot 同时固化 catalog artifact bytes/tree 与 bounded MICU ledger
rows/high-watermark；public projection 只给 scope/receipt/snapshot ids、state、safe digests、
timestamps、writer counts/categories 与 blocker code。

Receipt 是 private bounded evidence，可离线重算 receipt、writer proof、high-watermark 与
snapshot digests。Sealed generation 不可重开；后续合法工作必须创建显式链接的新 generation。
Seal/closure failure只产生 authority blocker，不改变 task 或自动选择替代 plan。

## 8. Bounded runtime barrier

operator/campaign 只能通过 `RuntimeBarrierProjectionService` 读取运行时是否仍在变化。该投影在
一个 read scope 中读取现有 task、operation/execution、continuation、sandbox run、runtime
command/signal、session lease、engine invocation 与 mutation writer；输出固定 blocker enum、
有界计数、exact durable-suspension task ids 和 `ready` fact。达到 record bound、scope/observer
identity 不精确或任一 owner仍 active 时一律 non-ready。

Barrier 不持久化 row、不 acquire authority、不 drain/dispatch、不 resolve approval、不退休
writer，也不写 task/campaign 状态。AOX driver 只消费该通用事实；scientific completion、失败、
deadline 与 evidence reducer 仍属于 AOX policy。重复读取必须保持所有 canonical row version 与
authority record 不变。

该通用 projection 也不会替 consumer 建立 observer identity。需要排除自身 writer 的 consumer
必须在每一次 projection 外显式建立 exact bounded observer，并保证其在返回或异常时退休。
AOX formal 的完整 session observation 与 terminal-command attached-writer settlement 因而
共用同一个 observer lifecycle 入口；drain coordinator 必须携带 exact purpose 与 attempt
authority，不能从 command terminal 推断 identity，也不能让窄 boolean 检查直接绕过该入口。
observer 不得跨 sleep、approval read、下一次 drain 或任何外部调用。

## 9. Feature gates 与回滚边界

Host gates：

- `OPENZYME_RELIABILITY_SHADOW_OBSERVABILITY=disabled|shadow_v1`
- `OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=legacy_only_v1|route_allowlist_v1|durable_only_v1`
- `OPENZYME_RELIABILITY_DURABLE_EXECUTION_ROUTE_ALLOWLIST=<sorted route ids>`
- `OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1`；`sync_v1` 已退休且启动失败
- `OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=legacy_v1|generic_v1`

Runner gate 是 trusted TOML 的 `ssh_transport.mode=disabled|controlmaster_v1`。它只适用于
新启动 deployment 的 admission policy。不能 hot-rebind active attempt；回滚必须先停止新
admission，让旧 process 按 frozen policy drain/reconcile，再启动 disabled deployment。

`owner_mode` 是 operation 创建时冻结的 immutable field。回滚 durable ownership 只能停止
新 durable admission；所有 nonterminal durable rows 仍由 durable worker 与 frozen adapters
推进或保持 reconcile-required，绝不能 relabel 为 legacy、同步执行或创建 replacement。

完整操作步骤与 SQL audit 见
[runtime-hpc-reliability-operations.md](runtime-hpc-reliability-operations.md)。

AOX numbered `run-live` 的 complete-attempt harness 已在产品 runtime 之外增加
local POSIX `spawn`/process-group supervisor。它只在 matching quiescence、SQLite/root
sync、zero exit 与 empty group 后交付 child result；否则 bounded TERM/KILL 并写
parent-owned fatal evidence，不读取 ledger-after、不封 normal bundle，也不把进程退出解释为
task/operation terminal。该边界不改变本文件的产品 ownership；different UID/cgroup 与
remote-handle/MICU crash reconciliation 仍是独立 hardening。

## 10. Executable qualification 与 AOX admission

`local_single_process_file_sqlite@1` 的 deterministic matrix 使用真实 file-backed composition 验证
runtime-command、controlled-operation、continuation、sandbox authority、restart/fence、reconcile、
operator retirement、boundary scale 与 evidence projection。它不证明 distributed writer、真实
SSH/HPC/provider availability 或 remote cancellation。

AOX `pin`、`preflight`、`run-live` 在任何 runner bootstrap、root 或外部 effect 前必须用当前
checkout pure verifier 接受同一 clean/full/zero-P0 report，并把其 commit/digest-bound receipt
贯穿 pin/root/launch/bundle/offline verifier。通过只解除 architecture blocker；不会自动恢复
`rxx`、修改 owner policy、重放 operation 或放宽 scientific/live gate。

## 11. 明确延后

- 任意 Python stack / journaled SDK replay；
- supervised remote SSH daemon 或 stateful persistent shell；
- direct SSH exactly-once；
- Slurm job-internal scientific attestation；
- multi-Host writer、distributed queue/consensus；
- 自动恢复 `rxx` campaign。

这些项目不得由 fallback、best-effort inference 或 proposal 草图冒充已实现能力。
