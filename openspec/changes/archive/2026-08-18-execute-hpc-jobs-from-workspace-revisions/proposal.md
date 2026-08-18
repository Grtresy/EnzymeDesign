## Why

远程 workspace 解决文件自由，但 Slurm job 仍需精确 source identity、可靠句柄和 response-loss recovery。新合同应直接从 committed workspace revision 启动作业，并让结果留在 executor workspace，而不是重新建立 artifact/expected-output publication 管线。

## What Changes

- 在连续源码迁移期间生成 `workspace_revision_execution_source_only_dependency_gate@1`，绑定 C8、Git LFS、controlled-operation、scientific-attempt 与 runner 当前接口 identity，并明确所有 predecessor/current acceptance 均未证明。该 gate 只允许源码、延后测试和文档工作，不授权 compute-tree、credential、SSH、Slurm、direct payload 或其他 external effect。
- external job admission 绑定 executor lease、remote workspace generation、clean private/published commit、command、resources、cwd 和 target；dirty source 直接拒绝。
- 本 change 消费 C2 的 canonical executor-lease identity/status/profile seam 与 receipt，但由本 change 自己实现普通non-scientific job无逐job human approval的canonical `ControlledOperationExecution` admission；C2 不提前创建job execution或证明route已闭合。
- scientific route绑定已经canonical admitted的exact `ScientificAttempt`、其`state_version`与immutable `ScientificAttemptAdmissionRequest`；不得简单要求作为来源的`ScientificAttemptAuthorization` envelope仍为`ACTIVE`，因为它可在成功admit attempt后合法转为`EXHAUSTED`。
- HPC login side 从 exact commit/LFS closure 准备 compute tree；compute node 不包含 `.git`、Git/LFS binary 或 credential。
- 每个 accepted external job（Slurm 或 bounded direct SSH）都由 remote dispatch ledger 支撑可靠 `ExternalJobHandle`；本地尚未拿到 handle 且不能证明 no-effect 时只 reconcile 同一 dispatch，禁止 replacement submit。
- Slurm submit由runner在每个frozen dispatch occurrence上获得并原子消费one-occurrence `sbatch` credential；target在scheduler acceptance前拒绝ordinary login/file credential、credential replay和未登记dispatch，且Host永不扫描或自动采纳绕过路径的job。
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

影响 controlled-operation domain/repositories/worker、scientific-attempt admission binding、runner RunSpec/JobHandle/result、one-occurrence scheduler credential、target submit gate、execution engine/SDK、Slurm scripts、projection、recovery tests 和 HPC docs。
