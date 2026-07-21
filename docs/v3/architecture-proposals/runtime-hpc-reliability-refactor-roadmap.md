# Runtime 与 HPC 可靠性重构总路线（已落地）

状态：D1-D8 与 umbrella OpenSpec change 的 Slice 1-4 已完成；stable-doc/OpenSpec、
完整 non-live、真实 SSH transport-only soak 与 disabled-mode rollback audit 全部通过。
当前没有启动 `rxx`，实际 campaign 恢复仍需 operator 显式决定。

实施权威入口已归档为
`openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/`。其中
`implementation/slice-0-baseline.md` 与
`implementation/slice-1-checkpoint.md` 分别记录已落地证据和回滚边界。
本文后续的“尚未实现”“需要确认”段落保留的是当时的设计基线；不得用它们
覆盖当前代码、OpenSpec tasks 或 checkpoint。

当前稳定产品合同见 [`../07-runtime-hpc-reliability.md`](../07-runtime-hpc-reliability.md)，
迁移与回滚见 [`../runtime-hpc-reliability-operations.md`](../runtime-hpc-reliability-operations.md)。

本文是 AOX/HMM live campaign 暴露出的两个未闭环根因的跨提案总入口：

1. runner 的 layout、staging、preflight、payload 与 fetch 由多次独立 SSH 子进程完成，既没有共享 transport 生命周期，也没有按副作用阶段恢复的 authority；
2. approval 与长时 external operation 仍被包在同一个 sandbox control call、agent signal claim、session runtime lease 和同步 `/runtime/drain` request 中。

现有详细 proposal 继续作为设计参考，但其中各自草拟的表名和类型名不再独立具有权威性。后续 OpenSpec change 必须先采用本文统一的 ownership 和 decision gates，再创建 migration 或产品代码。

## 重构冻结与当前基线

- `rxx` live campaign 已主动暂停；不能再用下一次 positive/fault/cutover attempt 代替架构修复。
- 本轮核对的源码基线是 `dev@290e085`，检查开始时工作树干净。
- `aox-hmm-blank-world-cutover` 是唯一 active OpenSpec change，当前 68/76 tasks；剩余 live/cutover tasks 是本重构的证据消费者，不是承载跨 runner/runtime 重构的正确 change 边界。
- 用户确认本文 decision gates 后，应建立新的 OpenSpec change；不得继续把重构追加到科学 cutover change。
- 在各 migration slice 真正落地前，稳定 `docs/v3/` 仍描述当前同步产品合同；proposal 不等于已实现能力。

## 最新实现事实

### Runner / HPC

- Host composition root 会构造长生命周期 `MCPHpcServer`；它持有一个 `CommandRunner`、`StagingManager`、`SSHRunner` 和 `SlurmRunner`，天然适合作为私有 SSH transport manager 的 owner。
- `CommandRunner.run()` 每次调用都会执行新的 `subprocess.run()`；普通 ssh、rsync 和 scp 重复连接参数，但没有共享 `ControlMaster`、connection generation 或 health state。
- `SSHRunner.exec_run()` 是同步调用：remote layout、逐输入 parent/transfer、preflight、remote payload、output fetch 和验证全部完成后，`exec.run` 才返回。
- `remote_layout`、`input_parent`、`input_transfer` 已有闭集 `runner_failure@1`；preflight transport failure 走另一份 `preflight_manifest.json`，对上仍粗略映射为 `hpc_staging_failed`。
- staging dedup cache 只凭本地 digest 和 remote destination 判断可跳过，没有重新证明远端 bytes 仍存在且 digest 一致。
- SSH payload 没有 durable dispatch receipt 或可查询 remote handle；dispatch 后失联不能安全重投。Slurm 已有 opaque submit/status/cancel/fetch handle，但 AOX 当前强制 SSH，因为只有 SSH 路径具备 same-login-shell toolchain attestation。
- `retryable=true` 目前只是诊断，不授权自动 replay、重开 approval、backend fallback 或 replacement operation。

### Runtime / approval / continuation

- `SessionRuntimeLease` 与 `AgentRuntimeSignal` fencing 已能阻止旧 worker 覆盖新 session owner；这是应保留的安全机制。
- `AgentRuntimeScheduler.run_once()` 在 claimed signal 执行期间持有 session lease。heartbeat 能续租，但 heartbeat 丢失不会把正在运行的 Python/control-socket 栈持久 park 并转交。
- `V3HostApiService.drain_runtime()` 同步等待 bounded agent turn 返回后才构造 HTTP response。
- SDK approval gate 会先持久化 `ControlledOperation`、`ApprovalRequest`、`ContinuationState`，随后 `_wait_for_approval_and_claim()` 在原 sandbox control worker 内每 50 ms 轮询。approval resolve 只改变 durable rows，不会调度一个独立 owner 的 continuation。
- 现有 continuation row 没有 originating signal、agent step/tool call、workspace/runtime epoch、resume strategy、state version 或 fencing token；它的 claim 不能替代 controlled-operation execution lease。
- Host 启动时会把 recoverable SDK continuation 全部转成 `operation_recovery_failed`，不能恢复原 Python 栈。
- capability terminal 仍只能作为 evidence/wakeup；业务 task terminal 必须继续由 agent 显式 `task.finish` 决定。

### 已锁定范围的 live 证据

- r35/r36：正式 scientific payload 前失败于 `remote_layout`；
- r37：正式 payload 前失败于 input-parent staging；
- r38：前序 HPC/provider 已通过，HMMalign approval 已批准但未 backend dispatch；长期占用的 runtime lease 过期后，旧 signal 写被 fencing 拒绝；
- r40：provider 与 input upload 成功，下一条 MAFFT preflight SSH 在 payload dispatch 前等待 60 秒超时。

这证明两个根因相互独立：SSH soak 成功不能关闭 continuation ownership；异步 drain 也不能自动使 SSH dispatch 可恢复。

## 统一 ownership 模型

不能把相邻 proposal 中的对象草图分别实现成多套 workflow 真状态。

| 关注点 | Canonical owner | 唯一职责 |
| --- | --- | --- |
| 科学意图与 approval binding | 现有 `ControlledOperation` + `ApprovalRequest` | immutable logical operation、approved digest、route、input/output 与 capability-facing 状态 |
| 外部副作用生命周期 | 新的窄 `ControlledOperationExecution` | dispatch generation、effect boundary、backend handle/ref、next work、result state、execution lease/fence、reconcile |
| SDK 挂起与结果交付 | 演进后的 `ContinuationState` | 绑定原 call/signal/workspace/runtime 与 delivery strategy；不拥有外部科学意图 |
| Agent 调度 | 现有 `AgentRuntimeSignal` + `SessionRuntimeLease` | 只拥有短 agent turn 与 wakeup，不拥有 approval/provider/HPC wall time |
| Runner 私有机制 | runner-owned `RunnerAttempt` + `SshTransportManager` | SSH generation、phase journal、staged-byte verification、dispatch receipt、runner reconcile；不是 task/session truth |
| Durable result | bounded result envelope + sealed artifacts | 同一 Host-owned result 可重复消费，不重复 external effect |
| Attempt closure | mutation authority + writer registry + seal generation | freeze 后拒绝新/晚 canonical write，snapshot 前证明 quiescence |

```text
Task / agent strategy
        |
        v
ControlledOperation + ApprovalRequest
        |
        v
ControlledOperationExecution  <---->  RunnerAttempt / provider attempt
        |
        v
durable result envelope + artifacts
        |
        v
ContinuationState delivery
        |
        v
AgentRuntimeSignal wakeup
        |
        v
agent 检查 evidence，自主继续、重试或显式 task.finish
```

outcome-unknown proposal 中的 `ControlRequestAdmission`、dispatch journal、response delivery 和 reconciliation 应实现为同一个 `ControlledOperationExecution` 周围的 versioned facets/records，不能成为另一套 external-effect owner。

## Proposal 收敛关系

| Proposal | 在重构中的角色 | 收敛规则 |
| --- | --- | --- |
| `durable-hpc-transport-staging-and-dispatch-reconciliation.md` | SSH transport、phase journal、安全 reconnect/retry、dispatch certainty | 新增的 runner 必需 workstream；runner 私有状态只链接 canonical operation execution |
| `nonblocking-supervised-continuation.md` | approval park/resolve/resume 与 signal/session lease 释放 | runtime parking 组件设计，统一使用本文 continuation identity |
| `durable-async-controlled-operation-and-quiescent-sealing.md` | external-operation scheduler、result materialization、独立 lease、cancel、quiescence | 主要产品生命周期；其中 execution record 是 external effect 的 canonical owner |
| `controlled-operation-outcome-unknown-after-response-failure.md` | admission/effect/delivery 分离与 reconcile | canonical execution record 的 protocol facet，不另建 operation owner |
| `process-isolated-live-attempt-supervision.md` | 同进程 writer 无法退休时的 bounded fail-stop | 最终 closure 层，不替代正常 continuation/recovery |
| `runner-owned-hpc-command-compiler.md` | typed command compilation 与 attestation | 相邻 correctness/security 重构，不混入第一阶段可靠性修改 |

## 建议实施切片

### Slice 0：冻结合同并增加 shadow observability

- 固化统一 state/ownership 与 transition table；
- 新增 runner phase、effect certainty、operation timing、park/resume timing、writer scope 的 versioned diagnostic schema，但不改变 dispatch；
- 盘点全部同步 drain、sandbox SDK、execution adapter、runner 与 evidence caller；
- 先建立 deterministic fault injection，再增加恢复行为。

### Slice 1：先稳定 payload 前的 runner transport

- 引入 runner-owned OpenSSH ControlMaster/ControlPersist；只复用 transport，每个动作仍是独立 channel，禁止 stateful interactive shell；
- ssh、rsync、scp 使用同一个 target/config/credential-scoped transport identity 和私有 control socket；
- 只对已证明 payload effect 尚未发生的阶段做 bounded reconnect；
- 统一 layout/input/preflight taxonomy，cache/retry 前验证 staged bytes；
- 以 unit、integration 和 non-scientific soak 验证生命周期、cleanup、并发和 safe projection。

### Slice 2：建立 durable controlled-operation execution

- 增加唯一 canonical execution record、state version、dispatch journal、execution lease/fence、bounded result handle 与 reconciliation outcome；
- runner/provider 统一使用 `failed_before_effect | committed | outcome_unknown | reconcile_required`；
- 按 route 逐项迁移；legacy sync worker 与新 async worker 不得同时拥有同一 operation。

### Slice 3：park sandbox/agent runtime，并有界化 drain

- approval/external wait 产生 durable suspension outcome；
- park 后完成/释放原 agent signal 与 session lease；
- approval resolve 只做短事务，独立 fenced continuation/execution worker 恢复同一 operation；
- 原 SDK result delivery 完成后才 wake owner agent；
- `/runtime/drain` 按 D4 迁为 accepted/bounded command。

### Slice 4：quiescence、restart 与兼容路径退休

- 引入 writer registry、mutation authority、seal generation、quiescence receipt 和 parent-owned process-isolation fail-stop；
- 启动时按 state reconcile；不支持恢复的 Python stack 明确失败，不能猜测重放；
- caller/row-version 审计后退役 control-socket approval busy wait 与同步长 adapter path；
- 最后才更新稳定合同并恢复 cutover attempts。

## 需要用户确认的 decision gates

以下选择故意保持未决。确认后才能生成新的 OpenSpec proposal/design/specs/tasks。

| ID | 必须决策的问题 | 推荐默认值 | 其他选择的影响 |
| --- | --- | --- | --- |
| D1 | 重构如何装入 OpenSpec | 一个 umbrella change，内部按 slice 设置 gate 和语义提交 | 拆成 runner/runtime 两个 change 更小，但共享 execution identity/reconcile 容易漂移 |
| D2 | 第一阶段承诺到什么恢复级别 | 同进程 non-blocking park + durable external effect/result；任意 Python 栈跨 Host restart 延后 | 一开始要求任意 Python restart 会显著扩大 SDK journal/workspace checkpoint；只做同进程且没有 durable effect 又保留 outcome ambiguity |
| D3 | sandbox continuation 路径 | 先 `attached_process`，再只为 registered Pipeline SDK 实现 `journaled_sdk_call_boundary` | journal-first 更强但会延后 lease 释放；attached-only 永远不具备 restart-safe |
| D4 | `/runtime/drain` 产品合同 | `202 Accepted + command_id + status`，可选很短 `Prefer: wait`，绝不拥有长任务 | 保留 HTTP 200 bounded parked response 兼容较好，但 command ownership 较模糊 |
| D5 | SSH transport | runner-owned per-target ControlMaster pool，有界 idle persist，独立 command channels | per-run master 仍重复握手；interactive shell 明确拒绝；remote daemon 是更大的部署/信任调整 |
| D6 | payload 前 retry authority | runner 在同一 run/operation/approval 内，对已证明 pre-effect 的 transport failure 执行小而 versioned 的自动重试 | 只让 agent 重试会重复 approval/upstream work；广义自动 retry 会产生 duplicate effect 风险 |
| D7 | SSH payload 的第一阶段 durability | 先保留 direct SSH，dispatch ambiguity 明确 fail closed；supervised receipt 或 Slurm job attestation 后续实现 | 现在实现 remote wrapper 可更完整但扩大 Slice 1；立即迁 Slurm 需先补 job-internal attestation |
| D8 | sealing 的作用域 | 建 generic Host mutation authority/quiescence，AOX 作为首个 consumer | AOX-only 更快，但会固化另一套 campaign-specific lifecycle，不能解决产品级 post-seal safety |

`ControlPersist` 时长、reconnect 次数、backoff 和 per-target channel limit 属于 versioned runner policy 参数，不属于 agent/user 科学策略；实现时应由配置和 fault tests 固定，caller 不可提交。

## 明确不在本重构中做的事

- 不引入 Redis/Celery/Kafka、多 Host writer 或跨进程 SQLite ownership；
- 不从 operation/continuation status 推导第二套 task/workflow truth；
- 不自动改变科学阈值、provider/backend、plan 或生成 synthetic fallback；
- 不使用 interactive persistent shell，不向 sandbox/agent 投影 SSH target、control path、remote handle 或 Host path；
- payload dispatch 后没有幂等/reconcile 证明时绝不自动 replay；
- operation success、runtime idle、max steps 或 retry success 都不自动完成 task。

## 恢复 `rxx` 前的最低闸门

1. connection reuse、private socket lifecycle 与 cleanup 的 deterministic tests 通过；
2. layout、每个 input、preflight、payload dispatch、output fetch 的注入故障均得到正确 effect-certainty；
3. non-scientific 多 operation SSH soak 达到约定连续次数，connection generation 数显著低于 command 数；
4. approval park 在 bounded deadline 内释放 signal claim、session lease 与 drain request；
5. approval resolve 只恢复一次 exact operation/result delivery；
6. 人为 lease expiry 时旧 worker 被 fence，新 owner 能恢复或明确 recovery-fail，dispatch 不重复；
7. success/failure closure 都取得真实 quiescence receipt，freeze 后无 canonical mutation；
8. focused tests、non-live mainline、public projection/security、migration compatibility 全部通过。

下一次编号实验应该验证一个已经闭环的架构，而不是继续用昂贵 live run 发现基本 ownership/transport 问题。

## 从探索进入实施的条件

先把 D1-D8 的用户决定写入新 OpenSpec `design.md`，再生成与上述 slices 一一对应的 requirements/tasks，同时包含稳定文档、migration/rollback、验证和语义提交边界。在 blocking decision 仍隐含时，不修改应用代码。
