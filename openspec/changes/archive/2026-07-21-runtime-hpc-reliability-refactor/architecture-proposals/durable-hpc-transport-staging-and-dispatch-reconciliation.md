# 待决策：Durable HPC transport、staging 与 dispatch reconcile

状态：已由 `runtime-hpc-reliability-refactor` 实现 deterministic 机制；fake
ControlMaster 与外部 real-SSH transport-only soak、disabled-mode rollback audit 均已通过。
当前 deployment 配置已恢复 disabled，未启动任何 `rxx`。

稳定合同见 [Runtime/HPC reliability](/docs/v3/07-runtime-hpc-reliability.md)，
操作与回滚见 [operations runbook](/docs/v3/runtime-hpc-reliability-operations.md)。
下文“当前实现边界”保留的是重构前基线，不得覆盖当前代码与 OpenSpec checkpoint。

本文补齐 staging diagnostic、durable controlled-operation lifecycle 与 outcome-unknown reconcile 之间缺失的 runner 专项架构。它不新增第二套 task、workflow、approval 或 controlled-operation 真状态。

跨 proposal ownership 与实施顺序以 [`runtime-hpc-reliability-refactor-roadmap.md`](runtime-hpc-reliability-refactor-roadmap.md) 为准。

## 已观察到的故障

- r35/r36：payload 前 `remote_layout` SSH 返回 255；
- r37：payload 前 `input_parent` SSH 失败；
- r40：layout 和 input upload 已成功，下一条 preflight SSH 等待 60 秒后超时，MAFFT 未 dispatch。

根因不是某一个命令坏了，而是一个 logical runner operation 依赖多次独立 SSH/rsync/scp 建连；上一阶段或 probe 成功不能把 transport health 延续到下一阶段。

## 当前实现边界

```text
MCPHpcServer（一个 Host 内长生命周期）
  -> CommandRunner（每次 subprocess.run）
  -> SSHRunner.exec_run
       -> ssh remote layout
       -> 每个 input：ssh mkdir + rsync/scp
       -> ssh preflight
       -> ssh remote payload
       -> rsync/scp declared outputs
       -> local validation + 单次最终 response
```

必须保留的优点：

- trusted Host-only runner；
- server-generated opaque run id；
- catalog-authorized input 和 declared output；
- strict toolchain/command validation 与 same-shell attestation；
- bounded timeout、Host-private raw log；
- closed safe diagnostic、无 hidden backend fallback；
- Slurm 已有 opaque submit/status/cancel/fetch handle。

尚缺：

- 共享 SSH transport generation 与 connection health owner；
- ssh/scp/rsync 的统一 options/compiler；
- ControlMaster socket lifecycle、并发上限和 stale socket recovery；
- dedup-cache hit 的远端 byte/digest 复核；
- preflight 与 layout/input 一致的 typed transport failure；
- durable per-phase runner attempt journal；
- SSH payload dispatch receipt/reconcile handle；
- command 未开始与已经开始但失联的 effect certainty 区分；
- public `retryable=true` 背后的安全恢复 authority。

## 设计原则

1. 复用 authenticated SSH transport，不复用 interactive shell；每条命令继续拥有明确 argv、cwd/env、timeout、stdout/stderr、stage 和 exit status。
2. connection liveness 与 payload effect certainty 是两个事实；reconnect 不授权 replay。
3. 自动恢复只能发生在同一个 runner run、controlled operation、approval、operation digest、route 与 input/output contract 内。
4. runner 拥有 SSH options、connection identity、private paths、phase journal 和 remote reconcile；agent/sandbox 永远拿不到这些 authority。
5. retry classification 是 versioned world policy；terminal capability outcome 后是否做 materially changed scientific retry 仍由 agent 决定。
6. RunnerAttempt 只是链接 canonical controlled-operation execution 的从属 execution evidence，不是 task/workflow state machine。

## 目标 SSH transport

由 runner 按 exact target authority 管理 `SshTransportManager`：

```text
SshTransportIdentity@1
  cluster deployment/config digest
  ssh target identity digest
  credential/host-key policy identity digest
  effective SSH policy digest

SshTransportGeneration（runner-private）
  identity digest / generation
  state: starting | healthy | degraded | closing | closed
  private control socket ref
  opened / last-used / last-health timestamps
  active channel count
```

第一阶段采用 OpenSSH `ControlMaster`/`ControlPersist`。control socket 必须位于 runner-owned mode-0700 私有目录，路径有界且足够短，不进入 public result/evidence。

普通 ssh、rsync 和 scp 全部从同一个 manager 获得 options 和 `ControlPath`。per-target semaphore 将 channel 数限制在有效 SSH `MaxSessions` 预算以内。master 在 versioned idle timeout 后关闭；runner shutdown 显式请求退出，异常退出后的 stale socket 只能在验证 ownership 后由新 generation 清理。

pool identity 必须包含全部 authority-relevant config，不能只因 hostname 相同就跨 credential/host-key/deployment 共用连接。

## Runner attempt 与 phase journal

增加 runner-private、可持久化且链接 Host operation/invocation metadata 的 manifest：

```text
RunnerAttempt@1
  run_id
  controlled-operation / engine-invocation digest refs
  runner-contract / toolchain / RunSpec digests
  transport identity digest / connection generation
  phase:
    allocated | transport_ready | remote_layout_ready
    input_staging | inputs_verified | preflight_passed
    dispatch_prepared | dispatching | remote_pending
    remote_terminal | outputs_fetching | outputs_verified | terminal
  phase version / attempt counters
  effect_certainty: no_effect | dispatch_in_doubt |
                    effect_known | terminal_known
  safe failure / retry eligibility / reconciliation requirement
  private receipt refs / public-safe manifest digest
```

每个 input entry 绑定 ordinal、artifact id/digest、destination digest 和 verification state。本地 cache equality 不能直接证明 staged；必须进行 bounded remote verification，或以后使用能给出 immutable receipt 的 content-addressed remote cache。

第一阶段 phase journal 可以进入现有 runner artifact store；canonical Host operation state 继续属于 SQLite。Host 只保存 opaque runner run id 与验证后的 safe receipt，不保存 SSH locator 或 mutable remote path。

## 故障恢复分类

| 失败位置 | Effect certainty | 允许的自动动作 |
| --- | --- | --- |
| remote layout 命令发送前 | `no_effect` | 重建 transport，在同一 run 重试当前 phase |
| layout/input-parent transport failure | scientific payload `no_effect` | reconnect 后重试幂等 mkdir |
| input transfer failure | payload 未 dispatch，remote bytes 可能 partial | reconnect，校验 destination digest，再 resume/replace 同一 staged input |
| preflight transport timeout | scientific payload `no_effect` | 重验 inputs 后 reconnect 并重试 exact preflight |
| deterministic preflight check failure | `no_effect`，但非 transport | terminal；不能通过 reconnect 重复同一无效环境 |
| dispatch write/receipt 前 | 只有 runner 能证明未被接收才是 `no_effect` | 重试同一 dispatch generation |
| dispatch 已发送但 ack/connection 丢失 | `dispatch_in_doubt` | 禁止 blind replay；reconcile exact receipt/Slurm handle，否则保持 unknown |
| remote terminal 已知、output fetch 失败 | `effect_known` | reconnect 并 fetch/verify 同一 declared outputs，不重跑 payload |
| output digest/contract 冲突 | `terminal_known` 但 result invalid | quarantine/recovery failure，禁止 last-writer-wins publish |

现有 boolean `retryable` 应降为更严格闭集的兼容投影：

```text
retry_eligibility = same_phase_safe | verify_then_retry |
                    reconcile_required | terminal
```

## SSH payload reconcile 的三种路线

ControlMaster 只能降低连接失败概率，不能让 payload 自动具备 durability。每条 route 必须显式选择：

1. `ssh_direct`：保留 foreground command；ControlMaster 提升稳定性，但 dispatch 后 transport ambiguity 必须 `outcome_unknown`，绝不自动重投。
2. `ssh_supervised_receipt`：runner-owned remote wrapper 原子记录 dispatch-started 与 terminal receipt，reconnect 后能 reconcile 同一 process/result；wrapper、signal、cleanup、receipt atomicity 与 security 需要独立审查。
3. `slurm_job`：复用现有 opaque submit/status/cancel/fetch；AOX 切换前必须先用 job-internal same-execution attestation 替代当前 SSH-only attestation 假设。

推荐第一阶段：先实现 ControlMaster 与 payload 前安全恢复；payload 后继续 `ssh_direct` fail closed；supervised SSH 或 job-internal Slurm attestation 作为后续显式决策。这样可以关闭 r35-r37/r40 已观察到的故障类别，同时不伪称 outcome-unknown 已解决。

## 配置与 authority

只增加 runner-owned、startup validation 且进入 effective config digest 的配置：

```text
ssh_transport.mode = disabled | controlmaster
ssh_transport.persist_seconds
ssh_transport.max_channels_per_target
ssh_transport.connect_attempts
ssh_transport.pre_effect_retry_attempts
ssh_transport.backoff_policy_id
ssh_transport.health_policy_id
```

agent、sandbox、RunSpec caller 和 Host request 都不能覆盖这些值；禁止 infinite persist/retry、任意 SSH options 和 caller-supplied control path。

## 生命周期与 shutdown

- `MCPHpcServer` 在整个生命周期内拥有 transport manager；
- construction 校验 private socket root 和 target identities，首次使用时再连接；
- health failure 先把 generation 标为 degraded，再决定 reconnect；
- pre-effect recovery 隔离旧 generation、验证 stale socket ownership、创建更高 generation；
- shutdown 停止新 channel，收口 active pre-effect work，记录未决 post-dispatch reconcile，再关闭 master；
- runner/Host shutdown 完成不能被解释为 remote payload 已停止。

## 安全与 public projection

- 保留严格 host-key 与 non-interactive auth，不增加 permissive fallback；
- control socket 不挂载进 sandbox；
- public diagnostic 只允许 opaque run id、safe phase、timed-out、elapsed、已允许的 input ordinal/digest、retry eligibility 与 reconciliation requirement；
- SSH target/user、control path、argv、stderr、credential、remote dir、PID、Slurm id 和 private receipt locator 全部禁止投影；
- 不同 credential、host-key policy 或 deployment config 绝不共享 master。

## Migration

1. 先统一 ssh/scp/rsync option compilation，但不启用复用；建立 differential argv tests。
2. 在 config gate 后加入 transport manager 与 private socket lifecycle；先 shadow-record generation，仍只有一个真实 dispatch path。
3. 先为 non-scientific probe，再为 registered SSH tools 启用 ControlMaster；证明单一 master + 独立 channels。
4. 统一 layout/input/preflight failure schema 与 staged-byte verification。
5. 增加 versioned pre-effect classification 和很小的同 run retry budget。
6. 把 RunnerAttempt receipt 接入 canonical `ControlledOperationExecution` 与 reconcile。
7. 决策并实施 supervised SSH receipt 或 Slurm job-internal attestation。
8. 退役 duplicated SSH option builder 和不能证明 remote bytes 的 cache path。

迁移期不能让 legacy 与 new launcher 对同一个 operation 都执行 payload；feature gate 必须按 runner/attempt config digest 冻结。

## 验收

### Unit/property

- authority-relevant config 任一漂移都会改变 transport identity；
- socket path 私有、有界、非 symlink、不可由 caller 指定；
- ssh/rsync/scp 使用同一 connection policy/ControlPath；
- channel 并发有界且 stdout/stderr/exit 独立；
- stale cleanup 不能删除其他 manager 的 active socket；
- deterministic preflight failure terminal，preflight transport timeout pre-effect recoverable；
- phase/effect/retry transition 闭合、幂等；
- public projection 对 private SSH/remote corpus 零命中。

### Fault injection

- 在 layout、每个 input、preflight、dispatch 前后、fetch 前主动杀 master；
- 注入 partial input 与 cache drift，必须通过 digest 校验；
- retry budget 用尽后只产生一个 terminal failure；
- 带 stale socket/nonterminal attempt 重启 runner；
- 两个并发 operation 不互相污染 cwd/env/output；
- 所有 ambiguity case 的 payload dispatch count 最多为一。

### Non-scientific soak

- 连续执行约定次数的 layout/upload/preflight/fetch deterministic cycle；
- connection generation 数必须有界且显著小于 SSH command 数；
- reconnect 只恢复 pre-effect failure；
- runner-private manifest 与 Host-safe projection 完全一致。

上述 gates 和 runtime continuation gates 通过前，编号 AOX campaign 保持暂停。

## Runner 专项 decision gates

- **H1**：是否采用 ControlMaster pool，而不是 per-run master 或 interactive shell；
- **H2**：是否允许 runner 对 proven pre-effect phase 做 bounded automatic recovery；
- **H3**：第一阶段 post-dispatch contract 选择 direct fail-closed、supervised SSH receipt 还是 job-internal Slurm attestation；
- **H4**：remote content verification 先做 per-run hashing，还是本轮直接引入 immutable content-addressed remote cache；
- **H5**：transport pool 是否由每个 Host 的 runner server 按 config identity 持有，而不是每个 operation 各自持有。

推荐默认：H1 ControlMaster、H2 允许、H3 先 direct fail-closed、H4 先 per-run remote hash、H5 per-Host runner server。
