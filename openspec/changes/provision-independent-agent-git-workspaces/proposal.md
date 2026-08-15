## Why

当前 sandbox volume 虽可跨 turn 保留，但它不是 Git clone，`Lane.branch_name` 也只是元数据；不同 agent 无法用标准 Git 留痕和交换精确 revision。linked worktree 共享 `.git`，不能作为任意 shell/capsule 的隔离边界。

## What Changes

- 为每个 canonical agent/subagent 建立 `session + agent_member + workspace_generation` 身份的独立完整 clone 和独立 `.git`。
- clone 位于持久 volume，Podman 命令进程仍可短命 `--rm`；container 重启不得丢失文件、commits、branches 或 Git/LFS objects。
- sandbox image 安装 Git、Git LFS、OpenSSH client、rsync、scp/curl 等原生工作工具，并把 clone 作为可任意读写的工作目录。
- 每个 agent/subagent 对已声明完成的文件产出步骤都要主动创建 coherent commit 并 fast-forward 到 append-only private ref 形成逐步留痕；未完成探索仍可 dirty，任何 checkpoint 都不自动 publish 或进入其他 agent projection。
- 禁止 linked worktree、共享 `.git`、Host repository mount、Host home/SSH directory mount 和 ambient checkout fallback。
- handoff、external job 与 publish 前必须引用 clean committed revision；普通探索期间允许 dirty/untracked files 并直接呈现 Git 状态。

## Capabilities

### New Capabilities
- `agent-git-workspace`: 定义独立 clone 的身份、生命周期、持久化、私有 revision 和 capsule toolchain。

### Modified Capabilities

## Impact

影响 sandbox workspace domain/repository、Podman image/runner、agent/lane projection、workspace creation/recovery、tool catalog 与测试基础设施。Lane 保留任务隔离和 focus 语义，但不再拥有 clone/cwd/branch 真相。
