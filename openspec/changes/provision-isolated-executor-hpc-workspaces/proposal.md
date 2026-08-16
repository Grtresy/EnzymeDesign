## Why

当前 HPC runner 为每次 RunSpec staging/fetch 文件，executor 无法直接管理自己的远程目录。已决定的目标是每个 executor 在 HPC login side 拥有隔离 clone/workspace，并在一次 lease 后自由使用 Git、LFS、SSH 与传输工具。

## What Changes

- 在连续 14-change 源码迁移期间，先生成 `executor_hpc_workspace_source_only_dependency_gate@1`：绑定 C1 immutable acceptance、C2 当前 source snapshot、C3--C7 source-only gates 与关键接口 digest，并明确 `acceptance_proven=false`、`final_source_revision_bound=false`。该 gate 只允许源码、延后测试与文档工作，不授权 credential、SSH、remote root、runner/HPC 或其他 external effect。
- 为每个 executor workspace generation provision 独立 HPC login clone 和可读写 remote workspace，身份绑定 project repository、session、agent 和 target。
- 本 change 消费 C2 的 executor target-eligibility/lease-status seam 与 `agent_capability_lease_acceptance@1` receipt，但由本 change 自己接入真实 SSH credential provider、签发/认证 target-scoped SSH/rsync/scp/login-workspace CRUD credential，并在 target OS principal/root 层强制隔离；C2 不提前实现或证明这些 deployment effects。
- HPC login node 安装 Git/Git LFS 并可访问 Host internal remote；executor 可在 lease scope 内直接使用 Git、SSH、rsync/scp 和普通文件 CRUD。
- remote workspace path/handle 对拥有它的 executor 可见和可用，对其他 agent 隔离；credential 仍按 executor/target scope 注入。
- private revisions 可同步到 executor remote private namespace但不成为 team shared truth；published refs 可正常 fetch。
- **BREAKING**：runner 不再按 input artifact 建 per-run staging copy，也不再要求 `HpcStageRef`；remote workspace 本身是输入和输出工作面。
- remote provisioning/sync 的外部 effect 必须留下 exact handle/receipt，response loss 只 reconcile 同一 workspace，不重复创建替代目录。

## Capabilities

### New Capabilities
- `executor-hpc-workspace`: 定义 executor-owned HPC login clone、隔离、CRUD、同步和恢复。

### Modified Capabilities
- `mcp-hpc-runner`: 从 per-run artifact staging 边界迁移为 executor remote workspace 与原生 transfer/Git 边界。

## Impact

影响 `mcp-hpc-runner` config/models/staging/server、execution adapter、C2 lease consumer seam、真实 SSH credential provider、target OS/root enforcement、HPC deployment qualification 和 integration tests。
