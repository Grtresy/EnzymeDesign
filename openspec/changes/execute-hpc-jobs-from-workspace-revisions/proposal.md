## Why

远程 workspace 解决文件自由，但 Slurm job 仍需精确 source identity、可靠句柄和 response-loss recovery。新合同应直接从 committed workspace revision 启动作业，并让结果留在 executor workspace，而不是重新建立 artifact/expected-output publication 管线。

## What Changes

- external job admission 绑定 executor lease、remote workspace generation、clean private/published commit、command、resources、cwd 和 target；dirty source 直接拒绝。
- HPC login side 从 exact commit/LFS closure 准备 compute tree；compute node 不包含 `.git`、Git/LFS binary 或 credential。
- 每个 accepted external job（Slurm 或 bounded direct SSH）都由 remote dispatch ledger 支撑可靠 `ExternalJobHandle`；本地尚未拿到 handle 且不能证明 no-effect 时只 reconcile 同一 dispatch，禁止 replacement submit。
- 复用 canonical `ControlledOperationExecution` 的 ownership、lease/fence、effect certainty 和 reconciliation，不创建第二套 job FSM。
- **BREAKING**：移除 public `expected_outputs`/declared-output fetch 白名单；job 产生的普通文件留在 executor remote workspace，由 executor 自由检查、下载、commit 和 publish。
- result identity 改为 job receipt、terminal status、revision/cwd 和可选 committed result revision，不创建 artifact set 或自动完成 task。

## Capabilities

### New Capabilities
- `workspace-revision-execution`: 定义 committed workspace 到 Git-free compute tree、可靠 job handle 和 workspace result 的执行合同。

### Modified Capabilities
- `controlled-operation-execution`: 以 revision/file result identity 取代 artifact-set/expected-output identity，同时保留 effect certainty 与唯一 owner。
- `mcp-hpc-runner`: 以 executor workspace/cwd 执行并保留 job handle，移除 staging/fetch/expected-output 合同。

## Impact

影响 controlled-operation domain/repositories/worker、runner RunSpec/JobHandle/result、execution engine/SDK、Slurm scripts、projection、recovery tests 和 HPC docs。
