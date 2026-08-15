## Context

当前 `SandboxWorkspaceRecord` 可以把 Host volume 跨 turn 保留，但该 volume 不是由 repository binding 建立的完整 Git clone；`Lane.cwd` 和 `Lane.branch_name` 只是元数据，不是可验证的工作目录或 revision authority。若多个 agents 共享 `.git` 或使用 linked worktree，任意 shell/capsule 的 ref、index、reflog、hooks、locks 和 credentials 都会跨身份耦合，无法形成真正的 workspace isolation。

本 change 在 `ProjectRepositoryBinding` 和 `AgentCapabilityLease` 基础上，为每个 canonical agent/subagent provision 独立完整 clone。Podman command process 仍可短命并使用 `--rm`，但 workspace volume 与 Git object database 必须持久。

## Goals / Non-Goals

**Goals:**

- 以 `session + agent_member + workspace_generation` 为唯一身份建立独立 clone、独立 `.git` 与独立持久 volume。
- 从 session-pinned repository binding 的 exact base commit 可复现地创建 workspace。
- 在 capsule 中提供普通文件工作面以及 Git、Git LFS、OpenSSH client、rsync、scp/curl 等原生工具。
- 让 agent 自由保留 dirty/untracked exploration，并用 local commits/private refs逐步留痕；任何 commit 都不自动 publication。
- 对 publish、cross-agent handoff 和 external job 提供 clean committed revision gate。
- 把 lane 保留为任务 focus/隔离元数据，不再让 lane 的 cwd/branch 字段充当 workspace 真相。

**Non-Goals:**

- 不实现 `workspace.publish`、自动 merge/rebase/cherry-pick 或其他 agent 的 sync。
- 不实现 Git LFS server/closure、HPC login clone、compute tree 或 Slurm execution。
- 不迁移 legacy artifact bytes、旧 sandbox files 或当前 Host checkout 到新 clone。
- 不挂载 Host repository、Host home、Host SSH directory或共享 `.git`，也不提供这些路径的 compatibility fallback。

## Decisions

### 1. `AgentGitWorkspace` 是 agent-generation-owned canonical resource

新增 `AgentGitWorkspace`（或等价持久 record），identity 为 `workspace_id + session + agent_member + workspace_generation`，并绑定 session 的 exact repository binding version/base commit、volume identity、clone root logical name、current HEAD、private ref namespace、状态、policy digest和 lifecycle timestamps。同一 generation最多一个 canonical workspace；新 generation必须通过显式 replacement创建。

选择 agent-generation ownership，而不是 lane ownership，是因为一个 resident agent会跨多个 tasks/lanes保留自己的工作历史，而 lane只表达 focus和claim。选择完整 clone而不是 linked worktree，是为了给每个 capsule独立 object database、index、refs、reflogs、locks和config。

### 2. Clone 只能来自 pinned internal remote 和 exact base

provisioner 使用 session-pinned `ProjectRepositoryBinding`、Host签发的 provision credential和 resolved base commit创建完整 clone，并验证 `remote identity + object format + HEAD/tree + policy digest` 后把 record置为 ready。不得从当前 Host checkout复制、不读取 ambient `origin`，也不得在 remote失败时初始化空仓库或选择另一个 branch。

选择 exact commit checkout 而不是 mutable default branch，是为了让所有 agents的起点可复现。使用 local mirror、reference repository或共享 alternates作为隐藏 object source被否决，因为它们会重新引入共享 `.git` 生命周期和 Host path依赖；未来若增加缓存，必须是内容只读且不成为 correctness prerequisite的独立设计。

### 3. Persistent volume 拥有全部文件与 Git state

clone root、`.git`、working tree、Git/LFS objects和 agent-created files全部位于该 generation专属 persistent volume。Podman执行可继续为每条命令启动短命 `--rm` container，并把同一 volume挂载为工作目录；container退出、Host进程重启或 bounded turn结束都不能删除或重建 volume。image中预装原生工具，credential仅在进程级注入，不写入 repo config、volume或Host home mount。

选择 ephemeral process + persistent data，是为了保持隔离和可恢复性，同时不把 container本身提升为持久真相。持久 container方案被否决，因为进程状态不可作为文件/commit的 canonical lifecycle；Host repository mount方案也被否决。

### 4. Local commit、private ref 和 publication 是三个不同状态

agent 可在一个尚未完成的探索步骤内自由保持 dirty 状态。每当 agent/subagent 明确宣告一个产生持久文件的 research、implementation 或 verification 步骤完成时，它必须自行选择该步骤的文件，创建一个 coherent local commit，并显式 create/fast-forward push 到其受 ACL 保护的 append-only private namespace，随后才可把该步骤报告为 durable checkpoint 或跨越 publication、handoff、external-job、task-terminal 边界。agent 不允许 force-update 或 delete private ref，分叉时创建新 ref。只有 repository retention owner 可以依照 pinned policy，在整代 workspace generation 已关闭、retention deadline 已过且全部 lease/pin/hold 已清除后，先记录 exact terminal ref/commit set receipt，再整代退役 namespace；不能选择性裁剪 checkpoint。Host 不自动 stage、commit 或 push，也不把 local commit、private push或 branch name投影为 team shared truth；只有后继 `workspace.publish` 创建的 `PublishedRevision` 才能进入 team projection。

选择 agent 主动创建的标准 Git commit/private ref 作为逐步留痕，而不是每次文件写入创建 artifact record，是为了在保留步骤内策略自由的同时得到 durable checkpoints。Host 自动 stage/commit/push 和 auto-publish 均被否决：前者会替 agent 选择文件与语义，后者会把探索状态无意提升为共享事实。

### 5. Dirty exploration允许，跨边界必须精确且 clean

普通探索期间，working tree可以有staged、unstaged和untracked changes；workspace projection必须直接呈现porcelain-equivalent状态与exact HEAD。创建 publication 或从 private workspace 发起 external-job admission前，Host validator必须证明working tree clean、目标revision等于预期exact commit并属于该clone/repository binding。发送已经存在的 `PublishedRevision` handoff只验证该 immutable publication/ref/path，不重新检查 producer 后续可能已变脏的 working tree。validator不自动 `git add`、commit、stash、clean、merge或改写 `.gitignore`。

选择边界时验证而不是全程强制clean，是为了保留agent策略自由。自动commit或丢弃untracked files的替代方案被否决；只接受branch name而不检查commit/tree也被否决。

### 6. Workspace损坏或缺失需要显式 replacement

恢复时，Host重读workspace record和volume，验证独立 `.git`、remote identity、object format与generation。volume缺失、clone损坏、HEAD不可读或identity drift时，workspace进入明确blocked状态；Host不自动reclone、不删除volume、不从另一个agent复制，也不把旧sandbox volume当作clone。操作者/agent必须选择修复或创建新generation，旧generation先冻结并保留审计事实。

选择显式 replacement 是为了避免自动恢复覆盖未发布的私有工作。catch-all后reclone方案被否决，因为它会把数据丢失伪装成成功恢复。

## Risks / Trade-offs

- [每个agent完整clone增加磁盘和网络成本] → 以retention/quota度量和显式GC管理；不以linked worktree或shared `.git`换取空间。
- [已完成步骤只留 local commit 时受节点故障影响] → durable checkpoint 要求 agent 将 coherent commit fast-forward 到 append-only private ref；projection清楚显示 local/private/published 状态，但 Host 不替 agent 自动选择、commit、push 或 publish 文件。
- [允许dirty状态会让边界操作更常失败] → 在projection提供准确Git status和修正提示，边界保持fail closed且不自动修改用户文件。
- [短命container需要反复注入toolchain/credential] → 固定versioned image和process-scoped credential broker；volume是唯一持久workspace真相。
- [旧sandbox volume含未迁移文件] → 旧volume只读冻结，由专门migration处理；不把无Git来源的内容自动混入新clone。

## Migration Plan

1. 新增 workspace identity/state/repository、generation唯一约束和安全projection，明确依赖session repository binding。
2. 构建versioned capsule image，安装Git、Git LFS、OpenSSH client、rsync、scp/curl并证明无Host home/repository mount。
3. 实现provisioner：创建专属persistent volume，从pinned internal remote clone exact base，验证identity后置ready，再激活generation-bound capability lease。
4. 将agent/subagent runtime cwd切换到owning clone；停止写入`Lane.cwd/branch_name`作为workspace authority，保留lane focus字段直到public-interface cutover删除兼容投影。
5. 接入 Git status/HEAD/private-ref projection、completed-step checkpoint contract 和 clean committed revision validator；验证未 checkpoint 的已完成步骤不能被报告为 durable 或跨正式边界，且 Host 从不自动选择、commit 或 push 文件。
6. 对既有agent创建显式新generation；legacy sandbox volumes保持冻结且不自动复制，等待历史文件迁移策略。
7. 回滚时停止新workspace provision和runtime挂载；任何已有volume、commit和private ref必须保留可恢复，不得通过reclone或删除回滚。

## Open Questions

无。完整clone、持久volume、私有revision、clean boundary、lane降级和恢复策略均已裁决。
