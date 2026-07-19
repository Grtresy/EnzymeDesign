# Session 10：SDK Supervisor RPC / External Capability Bridge

## 目标

把 persistent sandbox 与 Host-supervised external capabilities 连接起来，但只做到 SDK supervisor RPC substrate 这一层。Session 10 建立的是通用受控 SDK call 拦截、generic operation digest、approval 阻塞/恢复、backend category route freezing 和结构化失败；它不锁定最终 public SDK import surface、领域 operation、typed params、adapter envelope、`hpc.workspace`、remote workspace/file-transfer API，也不实现真实 runner 上传下载。

本 session 的顺序含义是“先铺 bridge 底座，再在 Session 11/12 定义这座桥上承载的 public SDK 和 adapter envelope”。S10 可以用 generic controlled operation / fake SDK operation 验证拦截、approval 和恢复语义；不能用未定型的 `bio_tools.*`、`structure_tools.*`、`docking.*` 或 `hpc.workspace` API 反向固化后续 SDK 形状。

## 当前缺口

- 旧 dry-run plan / execution tool 让 executor 介入 approval 编排；新的边界要求 Host 在 `sandbox.exec` 运行中的受控 SDK call 处自动拦截、阻塞、审批和恢复。
- 本地 Apptainer、HPC 软件环境、provider 网络访问和 sandbox Python 环境容易被混成一个执行环境。
- 后台 runtime 如果自动切换 backend 或 fallback，会接管 executor 判断。
- 当前 `hpc.*` SDK 每次调用通常编译独立 runner `RunSpec`；但连续 HPC workspace、声明式 stage/fetch API 和真实 runner 文件流必须由 Session 11/14 分别定义和实现，不能提前塞进 S10。
- 如果在 bridge 底座里提前锁定 public SDK module、typed params 或 adapter output fields，后续 S11/S12 会被实现细节倒逼，产生返工和边界漂移。
- 现有 approval 文档容易把两类恢复路径混成一种：agent-level approval 可以唤醒 agent turn；S10 的 SDK controlled-operation approval 必须恢复同一个 blocked SDK RPC / sandbox continuation，agent 只能在 `sandbox.exec` tool result 返回后继续。

## 实施范围

- Host 管理 SDK supervisor RPC 的通用入口；S10 只识别 backend category 和 prerequisite/approval 级别，不定义最终领域 SDK API：
  - `provider_http` category。
  - `host_local_tool` category。
  - `hpc_runner` category，占位到 backend category、prerequisite 和 approval 级别，不定义 remote workspace API。
- Sandbox SDK 只通过受控 RPC 进入 Host supervisor；pipeline code 不暴露 SSH、Slurm、runner path、SIF path、database mount、Host path、provider credential 或 raw command。
- 每个受控 SDK call 都生成 generic operation record：`operation_id`、operation digest、input digests、params digest、resource estimate、expected outputs summary、backend category route 和 approval requirement。
- S10 测试和 smoke 使用 generic controlled operation / fake SDK operation；最终 `bio.*`、`bio_tools.*`、`structure_tools.*`、`docking.*`、`hpc.*` public API 由 Session 11 定义，统一 adapter envelope 由 Session 12 定义。
- Host 根据 operation digest 检查是否已有有效 approval；缺 approval 时创建 canonical `ApprovalRequest`，把 sandbox run / SDK operation 置为 `waiting_approval`，并阻塞该 SDK RPC。
- approve 后 Host supervisor 通过 continuation worker 恢复同一个 blocked SDK RPC，让 sandbox 内代码继续执行；reject 后 Host 向 sandbox SDK 返回 approval rejected，SDK 在代码中抛 `ApprovalRejectedError` 或等价结构化异常。
- S10 approval、resume 和 reject 都是 Host-用户 contract；executor 不调用 resume 工具、不轮询 approval、不判断敏感性。`AgentRuntimeSignal(APPROVAL_RESOLVED)` 不是 S10 SDK RPC continuation 的恢复机制；agent loop 只在 `sandbox.exec` 最终返回 tool result 后继续。
- backend category route 在 approval 绑定后冻结，记录 selected backend category、route reason、runtime/tool digest placeholder、input digests、expected outputs summary 和 resource class。最终 selected backend 字段、placement/stage/fetch 字段和 artifact metadata 由 S11/S12 扩展。
- local/HPC/provider failure 只产生结构化失败并返回到 sandbox SDK / `sandbox.exec` result；是否换 backend 必须由 executor 在下一次 agent turn 读取 tool result 和 workspace 诊断后修改 workspace 或参数，再重新运行 `sandbox.exec`。
- approval 绑定 operation digest、`sandbox_workspace_id`、source snapshot digest、logical operation key、params digest、backend category route、artifact reads、expected outputs summary 和 quota/resource estimate。
- durable pause/resume 必须持久化 sandbox run、SDK operation、approval id、operation digest 和 continuation state。S10 的重启策略固定为 fail-closed：Host 进程重启后如果不能安全恢复同一个 blocked SDK RPC / continuation，就把 operation 结束为 `operation_recovery_failed`，保留 approval 和诊断证据，并让等待中的 `sandbox.exec` 返回结构化失败；后续由 executor 读取 tool result / workspace 诊断后修改 workspace 或重新运行 `sandbox.exec`。不得只做内存恢复，也不得静默成功。
- 同一 session 内完整 `operation_digest` 相同且 approval 仍为 approved 时复用 approval；digest 漂移必须新建 approval 或返回 drift failure。已 rejected 的 digest 不自动重开。

## 接口变化

- S10 落到现有 control-plane 通道上：`ApprovalRequest` 仍是用户/Web UI 改变 approval 状态的 canonical 记录；`SandboxRunRecord` 仍是 `sandbox.exec` 的 canonical run 记录；S10 另外新增/持久化 `ControlledOperation` 与 `ContinuationState`，用于表达 SDK RPC 等待、恢复、route freezing 和 operation evidence。不得把 continuation 私有状态塞进 approval card，也不得用 agent runtime signal 代替 SDK RPC continuation。
- S10 实施任务必须同步修正文档 `docs/v3/04-public-interfaces.md` 与 `docs/v3/05-agent-runtime.md` 中关于 approval resolve 的泛化表述：agent-level approval 可以排队 agent wakeup；SDK controlled-operation approval 应先恢复 Host-owned continuation，只有 `sandbox.exec` tool result 返回后 agent loop 才继续。
- S10 generic operation record 增加：
  - `sandbox_workspace_id`
  - `sandbox_run_id`
  - `operation_id`
  - `operation_digest`
  - `approval_id`
  - `approval_state`
  - `backend_category`
  - `route_reason`
  - `input_artifact_digests`
  - `source_snapshot_artifact_id`
  - `expected_outputs_summary`
  - `resource_estimate`
- S10 generic supervised SDK RPC request envelope 固定为 bounded structured data，至少包含：
  - `schema_version`
  - `idempotency_key`
  - `sandbox_workspace_id`
  - `sandbox_run_id`
  - `source_snapshot_artifact_id`
  - `source_snapshot_digest`
  - `logical_operation_key`
  - `params_digest`
  - `input_artifact_digests`
  - `backend_category`
  - `expected_outputs_summary`
  - `resource_estimate`
- S10 request/response 都承载在 S09 的一连接一帧 JSON-RPC 2.0 NDJSON boundary 上：payload hard cap 是对称 `4 MiB` 且不含终止 newline，receiver 必须跨任意 `recv` chunk 聚合完整 frame。非 null request id 只允许 UTF-8 `<=256` bytes string 或 signed int64；其余 request semantics 非法时 error 保留 safe id，id 自身超限/非法时使用 null。畸形 UTF-8/JSON、残帧、response identity drift 和超限均在 method dispatch、operation creation 或 result acceptance 前结构化 fail closed；首newline后已被receiver观察到的非空trailing bytes也在dispatch前拒绝。每connection硬保证最多执行一个request；首request接受后才晚到的第二帧可只遇到connection关闭，不保证第二个error，但绝不创建第二个operation。一个坏连接不能终止 Host accept worker。SDK 对 request preflight 和 response assembly 实施相同 cap，Host 不能通过返回 oversized operation summary 绕过 bounded response。该 framing correction 不改变 S10 operation/approval/continuation schema，也不触发 sandbox protocol 或 image version bump。
- S10 RPC response envelope 只返回 bounded summary、`operation_id`、`operation_digest`、`approval_id`、approval state、backend category route、status 和 structured error；不返回 Host path、runner path、credential、SSH/Slurm config、raw command 或未声明 backend 文件。
- Session 11/12 再扩展和锁定 public SDK result / adapter envelope，例如 `sdk_module`、`function_name`、`placement`、`hpc_workspace_id`、`stage_refs`、`fetch_refs`、`selected_backend`、`output_artifact_ids` 和 `backend_run_id`。
- `run.wait` / `run.fetch_artifacts` 保持只读状态/结果查询语义，不触发未声明输出下载。
- public workspace 只能展示 selected backend category、safe digest、artifact refs 和 diagnostic summary，不展示 private path 或 backend command。
- `operation_digest` 使用 canonical JSON 生成：对象 key 稳定排序，默认值显式写入，列表顺序只在语义有序时保留，路径先转为 public/sandbox-relative identity，artifact 输入使用 artifact id + digest，不包含 Host path、credential、socket path、process id、temporary file path 或 in-memory coroutine id。digest 漂移时必须创建新 approval 或返回 `operation_drift_detected`。

## Resource Identity / Lifecycle

本 session 锁定三类 Host-owned 资源对象：`ControlledOperation`、`ApprovalBinding` 和 `ContinuationState`。

- `ControlledOperation`
  - identity：`operation_id` 由 Host 创建；`operation_digest` 由 logical operation key、params digest、source snapshot digest、input artifact digests、backend category、resource class 和 expected outputs summary 组成。
  - owner：Host SDK supervisor 创建和持久化；sandbox SDK 只能发起受控 RPC。
  - lifecycle：`created -> waiting_approval -> running -> completed|failed|recovery_failed`；approval 前不得执行真实 provider/local/HPC work。
  - persistence：operation record、digest、artifact reads、route、resource estimate、approval state、result/error summary 持久化。
- `ApprovalBinding`
  - identity：`approval_id` 由 canonical approval service 创建，绑定 session、operation digest、source snapshot digest、backend category route 和 expected outputs summary。
  - owner：Host approval service 创建和更新；executor 不调用 resume、不轮询 approval、不判断敏感性。
  - lifecycle：`pending -> approved|rejected|superseded`。approve/reject 重复提交必须幂等；digest 漂移 supersede 旧 pending approval 或创建新 approval。
  - reuse：同 session 内相同 `operation_digest` 可复用 approved approval；不同 digest、不同 session 或 rejected approval 不能复用。
- `ContinuationState`
  - identity：`continuation_id = sandbox_run_id + operation_id`。
  - owner：Host supervisor 持久化；supervisor continuation worker 通过 claim lease 恢复 blocked SDK RPC，不通过 agent runtime wakeup 恢复。
  - lifecycle：等待 approval 时 pause；approve 后由单个 continuation worker claim lease 并继续同一个 SDK RPC；lease 过期可重新 claim；Host 进程重启后若原 blocked RPC 无法安全续接，必须写 `operation_recovery_failed` 并让 `sandbox.exec` 返回结构化失败，而不是尝试重放未获批准的真实 work。
  - persistence：continuation state 是 canonical recovery state；in-memory coroutine、process id 或 socket connection 只是 disposable runtime envelope。

固定错误码：

- `operation_drift_detected`
- `approval_rejected`
- `approval_state_conflict`
- `operation_recovery_failed`
- `operation_lease_conflict`
- `sdk_rpc_schema_unsupported`
- `operation_prerequisite_missing`

## 推荐实施顺序

这一段是动工顺序，不是实现状态清单。每一步完成后再进入下一步，避免用后续 S11/S12 的 public SDK 或 adapter envelope 反向固化 S10。

1. 文档边界先行：同步 `docs/v3/04-public-interfaces.md` 与 `docs/v3/05-agent-runtime.md`，把 approval resolve 明确拆成两类。agent-level approval 可以排队 agent wakeup；S10 SDK controlled-operation approval 只能先恢复 Host-owned continuation，`sandbox.exec` tool result 返回后 agent loop 才继续。完成判定：稳定文档不再把 `AgentRuntimeSignal(APPROVAL_RESOLVED)` 描述成 SDK RPC continuation 的恢复机制。
2. 先落 durable control-plane 资源：新增 `ControlledOperation` / `ContinuationState` 领域对象、migration 与 repository；固定 `ApprovalRequest.kind="sdk_controlled_operation"`、`request_ref=operation_id`。完成判定：approval resolve 能从持久化记录可靠区分 SDK continuation 与 agent-level approval，不依赖 in-memory socket、coroutine 或 UI 字段。
3. 改造 approval resolve 路由：`POST /v3/approvals/{approval_id}/resolve` 遇到 `sdk_controlled_operation` 时只更新 approval / operation / continuation 状态并触发 supervisor continuation worker，不排 `AgentRuntimeSignal(APPROVAL_RESOLVED)`；其他 agent-level approval 继续走现有 agent wakeup 语义。完成判定：同一个 endpoint 下两类 approval 的恢复路径分叉清楚，重复 approve/reject 保持幂等。
4. 扩展 S09 control socket：在现有 sandbox control channel 上增加 S10 generic supervised SDK RPC substrate，按 `4 MiB` 一连接一帧 NDJSON 合同跨 chunk 校验 bounded request/response envelope、计算 canonical `operation_digest`、创建或复用 approval、返回 waiting / approved / rejected / structured failure response。完成判定：测试只使用 fake controlled operation，不引入最终 `bio.*`、`bio_tools.*`、`structure_tools.*`、`docking.*` 或 `hpc.workspace` public API；malformed/oversized/incomplete frame 不能创建 operation，且不能杀死下一连接。
5. 实现 continuation claim / recovery：approve 后由 supervisor continuation worker claim lease 并恢复同一个 blocked SDK RPC；无法恢复同一 continuation 时写 `operation_recovery_failed`，让 `sandbox.exec` 返回结构化失败并保留 operation evidence。完成判定：并发 claim 只有一个 worker 成功，其他 worker 得到 `operation_lease_conflict` 或等价结构化失败；Host 重启后不能静默成功。
6. 补齐 projection / event / diagnostics：pending approval、operation summary、backend category route、digest、failure code 和 recovery evidence 必须能从 workspace projection、events、`sandbox.exec` result 与 controlled operation record 追踪。完成判定：public projection 只暴露 safe summary，不泄露 Host path、runner path、credential、raw command 或未声明 backend 文件。
7. 最后补 focused tests 与回归栈：覆盖 pending approval blocks SDK RPC、approve resumes same RPC、reject raises SDK error、digest drift requires new approval or structured failure、approved digest reuse、rejected digest no reuse、duplicate approve/reject idempotent、parallel continuation claim returns one winner、S10 SDK approval 不产生 `APPROVAL_RESOLVED` agent wakeup。完成判定：focused tests 通过后，再跑相关 V3 runtime / protocol / API 回归，确认没有把 S10 变成隐藏 fallback 或 agent-level wakeup。

## 测试/验收

- generic controlled SDK call 能在执行真实 provider/local/HPC work 前展示 operation summary、backend category route、expected outputs summary、resource estimate 和 approval requirements。
- 大于单个 `64 KiB` chunk、但不超过 `4 MiB` 的合法 controlled-operation envelope 必须完整到达同一 operation；SDK oversized request 在发送前失败，Host malformed/incomplete/oversized request 不创建 operation，oversized response 返回小型结构化 error，且 per-connection failure 不影响后续请求。
- 缺 approval 时，`sandbox.exec` 内的 SDK RPC 被阻塞在 `ControlledOperation.status=waiting_approval`；pending approval 和 safe operation summary 出现在 workspace projection / events，agent 不收到 `APPROVAL_RESOLVED` wakeup 作为恢复机制。
- approve 后必须由 continuation worker 恢复同一个 blocked SDK RPC；sandbox code 继续执行，最终 `sandbox.exec` tool result 返回给 agent loop。
- approval 后同一个 SDK operation 不得静默改变 backend category、resource class、params digest、expected outputs summary 或 source snapshot digest；漂移必须触发新的 approval 或结构化 failure。
- 同 session 内相同 `operation_digest` 复用 approved approval；rejected 或 drifted digest 不复用。
- approve/reject 重复提交幂等；并发 recovery claim 只有一个 worker 成功，其他返回 `operation_lease_conflict`。
- reject approval 后 sandbox SDK 抛结构化异常，`sandbox.exec` 返回非零/failed 状态并保留日志和 operation evidence。
- Host 进程重启或 worker recovery 后，waiting SDK operation 必须恢复同一 continuation 或明确失败为 `operation_recovery_failed`，不能丢失 approval state；本 session 不要求恢复 in-memory coroutine 或原进程。
- local backend 缺 Apptainer/SIF、HPC backend 缺 runner/tool/database、provider 缺 credential 都返回结构化 prerequisite failure。
- failure 后不会自动 fallback 到 sibling backend；失败必须作为 sandbox SDK exception、`sandbox.exec` result、controlled operation record、events 和 workspace safe diagnostic summary 可见，由 executor 在下一次 agent turn 总结、修改 workspace 或重新运行 `sandbox.exec`。
- declared outputs 以外的 backend 文件不会进入 artifact catalog；需要诊断时只能通过安全日志、manifest artifact 或后续 S11/S14 定义的 stage/fetch 路径暴露。
- 本文档不引入远端工作区同步模型；只描述 bridge、approval 和 route freezing。
- 测试不得依赖最终 public SDK naming；S10 用 fake controlled operation 验证 RPC substrate，S11/S12 再验证 public SDK/import surface 和 adapter envelope。

## 明确不做什么

- 不在本 session 实现具体 NCBI/UniProt/MAFFT/CD-HIT/HMMER adapter。
- 不锁定 `bio` / `bio_tools` / `structure_tools` / `docking` / `hpc` 的最终 public import surface、函数参数或 result payload。
- 不定义统一 adapter envelope；这些由 Session 12 定义。
- 不定义 `hpc.workspace`、`stage_artifact`、`fetch_outputs` 或 remote workspace file-flow API；这些由 Session 11 定义。
- 不实现真实 HPC runner staging、remote execution、declared output fetch 或 artifact registration；这些由 Session 14 接入。
- 不提供动态 route、按输入大小自动 backend 选择或 hidden fallback。
- 不把 remote workspace path 暴露给 executor 或 public workspace。
- 不新增 agent-facing `execution.plan.*` / `execution.run.*` 工具。
- 不使用 `AgentRuntimeSignal(APPROVAL_RESOLVED)` 作为 S10 SDK RPC continuation 的恢复机制；agent wakeup 只属于 agent-level approval 或 `sandbox.exec` tool result 已返回之后的正常 agent loop 推进。
