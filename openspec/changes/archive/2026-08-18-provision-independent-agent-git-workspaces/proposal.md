## Why

当前 sandbox volume 虽可跨 turn 保留，但它不是 Git clone，`Lane.branch_name` 也只是元数据；不同 agent 无法用标准 Git 留痕和交换精确 revision。linked worktree 共享 `.git`，不能作为任意 shell/capsule 的隔离边界。

## What Changes

- 为每个 canonical agent/subagent 建立 `session + agent_member + workspace_generation` 身份的独立完整 clone 和独立 `.git`。
- 消费 C2 已持久化的 pending workspace generation / capability lease intent；只有真实 `AgentGitWorkspace` 完整 clone 验证后，才在同一原子状态转换中将 workspace 置为 ready、激活 matching lease 并解除 `provisioning_required`。
- clone 位于持久 volume，Podman 命令进程仍可短命 `--rm`；container 重启不得丢失文件、commits、branches 或 Git/LFS objects。
- versioned capsule image 安装 filesystem/shell、Git、Git LFS、OpenSSH client、rsync、scp/curl 等原生工作工具，并把 clone 作为可任意读写的工作目录；只有 active matching capability lease 才暴露相应 native tools。
- native capsule 使用 deployment ordinary network，访问实际 reachable endpoint 时不经过 Host destination allowlist 或逐命令 approval；unreachable endpoint 保留原始明确失败，不重试、不切换 endpoint。该语义不得修改旧 Host-supervised execution、pipeline SDK 或 AOX `--network=none` 隔离路径。
- Git/LFS 与其他 Host-issued service credential 仅按 exact lease/agent/generation/service/protocol audience 做 process-scoped injection；credential 不写入 volume、repository config、Host home、command logs 或 public projection。
- 普通 upload/download 产生的 private bytes 可跨短命 container 保留，但不自动进入 artifact/catalog、team projection、scientific truth 或 publication。
- 每个 agent/subagent 对已声明完成的文件产出步骤都要主动创建 coherent commit 并 fast-forward 到 append-only private ref 形成逐步留痕；未完成探索仍可 dirty，任何 checkpoint 都不自动 publish 或进入其他 agent projection。
- 禁止 linked worktree、共享 `.git`、Host repository mount、Host home/SSH directory mount 和 ambient checkout fallback。
- handoff、external job 与 publish 前必须引用 clean committed revision；普通探索期间允许 dirty/untracked files 并直接呈现 Git 状态。

## Capabilities

### New Capabilities
- `agent-git-workspace`: 定义独立 clone 的身份、生命周期、持久化、私有 revision 和 capsule toolchain。

### Modified Capabilities

## Impact

影响 C2 capability-lease provisioning seam、sandbox workspace domain/repository、Podman image/runner、agent/lane projection、workspace creation/recovery、tool catalog、process credential injection 与测试基础设施。Lane 保留任务隔离和 focus 语义，但不再拥有 clone/cwd/branch 真相。`workspace.publish` 及 `PublishedRevision` 创建仍归 C4；HPC remote workspace、target credential 与 Slurm execution 仍归后继 change。

连续迁移期间，C3 以显式 `agent_capability_lease_implementation_snapshot@1` 记录当前 C2 实现依赖并继续源码工作；该 snapshot 固定声明未完成 acceptance、最终 source binding、production effect 与 live 资格，不能替代最终 C2 receipt 或触发实际 provisioning。全部连续 change 组合实现完成后，C3 acceptance 仍须重新绑定正式 C2 receipt、最终 source revision 与本 change 的完整验证证据。
