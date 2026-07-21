## Why

AOX/HMM live campaign 已反复证明，OpenZyme 当前把一次 logical HPC operation 拆成无共享生命周期的独立 SSH 调用，同时让 approval 与长时 external operation 占用原 agent signal、session lease 和同步 `/runtime/drain`；这使 transport 抖动与 runtime fencing 分别在 scientific payload 前制造重复失败。继续增加局部 timeout、诊断或 campaign 协调不能闭环 ownership、恢复与 post-dispatch safety，因此必须在恢复 `rxx` 前完成一次跨 runner、operation runtime 与 Host closure 的结构性重构。

## What Changes

- 建立唯一 canonical `ControlledOperationExecution`，持有 external-effect dispatch generation、effect certainty、execution lease/fence、backend handle/ref、durable result 与 reconciliation；admission、delivery 和 outcome-unknown 只作为其 versioned facets，不创建第二套 task/workflow 真状态。
- 让 approval/external wait 产生 durable suspension outcome，释放原 `AgentRuntimeSignal` claim 与 `SessionRuntimeLease`；approval resolve 由独立 fenced owner 恢复同一 operation，result delivery 后再 wake agent。
- **BREAKING**：将 `POST /v3/sessions/{session_id}/runtime/drain` 从可能同步等待长 operation 的 `200` 合同迁移为 `202 Accepted + command_id + status`，只允许可选的短 `Prefer: wait`；HTTP request 与 session lease 均不再拥有 provider/HPC wall time。
- 修改 HPC runner，使长生命周期 runner server 按 target/config/credential identity 持有有界 OpenSSH `ControlMaster`/`ControlPersist` transport；ssh、rsync、scp 复用认证连接但继续使用隔离 command channel，禁止 interactive persistent shell。
- 为 runner 增加 durable phase/effect journal、remote staged-byte verification 与 closed retry eligibility；只在同一 run/operation/approval 内对 proven pre-effect transport failure 做小而 versioned 的自动恢复，direct SSH dispatch ambiguity 保持 fail closed，绝不 blind replay。
- 建立通用 Host mutation authority、writer registry、seal generation 与 quiescence receipt；AOX 是首个 consumer，但 capability 不绑定单一 campaign。operation/runtime success 仍不自动完成业务 task，唯一业务终态继续由 agent 显式 `task.finish` 决定。
- 按可回滚 slices 迁移并退休 legacy 同步 owner；增加 deterministic fault injection、public projection/security、restart/reconcile、non-scientific SSH soak 与 non-live mainline gates。在这些闸门全部通过前保持 `rxx` campaign 冻结。

## Capabilities

### New Capabilities

- `controlled-operation-execution`: canonical external-effect execution lifecycle、effect certainty、独立 lease/fencing、durable result、single-effect delivery 与 outcome reconciliation。
- `runtime-continuation`: approval/external wait 的 non-blocking park/resume、exact continuation identity、agent wakeup，以及 command-based bounded runtime drain 合同。
- `host-quiescence-sealing`: Host mutation authority、writer registration/retirement、seal generation、quiescence proof 与 post-seal canonical-write rejection。

### Modified Capabilities

- `mcp-hpc-runner`: 增加 runner-owned persistent SSH transport、统一 phase/effect failure taxonomy、staged-byte verification、proven pre-effect bounded recovery，以及 direct SSH post-dispatch fail-closed/reconcile 边界。

## Impact

- 影响 `packages/openzyme-core` 的 control-plane repository/schema、agent scheduler、continuation、protocol、projection 与 task/runtime boundary。
- 影响 `packages/openzyme-engines` 和 `packages/openzyme-pipeline` 的 controlled-operation execution、sandbox SDK suspension/result delivery、runner/provider adapter 与 restart reconciliation。
- 影响 `apps/openzyme-host-api` 的 composition root、runtime command API、background execution/recovery、mutation authority 与 public projection。
- 影响 `apps/mcp-hpc-runner` 的 SSH option compilation、transport lifecycle、staging/preflight、attempt store、failure manifests 与 direct/Slurm reconcile 边界；继续使用现有 OpenSSH/Slurm 部署，不引入 Redis、Celery、Kafka 或 remote daemon。
- 需要版本化 SQLite migration、兼容读取/投影与显式 rollback/retirement gates；legacy 与新 worker 不得同时拥有同一 operation。
- 需要同步 `docs/OpenZyme架构设计.md`、相关稳定 `docs/v3/`、runner 配置示例和测试说明；现有 `aox-hmm-blank-world-cutover` change 只消费最终可靠性证据，不承载本重构任务。
