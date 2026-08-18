## Context

当前 `SandboxWorkspaceRecord` 可以把 Host volume 跨 turn 保留，但该 volume 不是由 repository binding 建立的完整 Git clone；`Lane.cwd` 和 `Lane.branch_name` 只是元数据，不是可验证的工作目录或 revision authority。若多个 agents 共享 `.git` 或使用 linked worktree，任意 shell/capsule 的 ref、index、reflog、hooks、locks 和 credentials 都会跨身份耦合，无法形成真正的 workspace isolation。

本 change 在 `ProjectRepositoryBinding` 和 `AgentCapabilityLease` 基础上，为每个 canonical agent/subagent provision 独立完整 clone。C2 已持久化 pending workspace generation、matching capability lease intent 与 `provisioning_required`；C3 必须消费这些事实，而不是自行合成 lease 或把 legacy sandbox/tool exposure 解释为授权。Podman command process 仍可短命并使用 `--rm`，但 workspace volume 与 Git object database 必须持久。

连续迁移实现阶段不把尚未生成的 `agent_capability_lease_acceptance@1` 当作虚构前置。C3 先记录 `agent_capability_lease_implementation_snapshot@1`，绑定当前 C0/C1 receipts 与 C2 source/schema/policy/interface 事实，并显式保留 `acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`。该 snapshot 只允许继续修改源码；实际 production provisioning、live/effect 资格和最终 C3 acceptance 仍必须等待全部连续 change 的组合验收及正式 predecessor receipts。

## Goals / Non-Goals

**Goals:**

- 以 `session + agent_member + workspace_generation` 为唯一身份建立独立 clone、独立 `.git` 与独立持久 volume。
- 从 session-pinned repository binding 的 exact base commit 可复现地创建 workspace。
- 在 versioned capsule 中提供 filesystem/shell、Git、Git LFS、OpenSSH client、rsync、scp/curl、upload/download 等原生工具，并且只在 matching capability lease active 后暴露。
- 让 native capsule 使用 deployment ordinary network，访问实际 reachable endpoint 时不经过 Host destination allowlist；保留 unreachable endpoint 的原始失败且不自动 retry、replay 或切换 endpoint。
- 将 Git/LFS 与其他 Host-issued service credential 按 process scope 注入并限定 exact audience，确保 credential 不进入 volume、repository config、Host home、command logs 或 public projection。
- 让普通 download/upload bytes 保持 generation-private，可跨短命 container 持久，但不自动成为 team/scientific/publication truth。
- 让 agent 自由保留 dirty/untracked exploration，并用 local commits/private refs逐步留痕；任何 commit 都不自动 publication。
- 对 publish、cross-agent handoff 和 external job 提供 clean committed revision gate。
- 把 lane 保留为任务 focus/隔离元数据，不再让 lane 的 cwd/branch 字段充当 workspace 真相。

**Non-Goals:**

- 不实现 `workspace.publish`、自动 merge/rebase/cherry-pick 或其他 agent 的 sync。
- 不实现 Git LFS server/closure、HPC login clone、compute tree 或 Slurm execution。
- 不实现 HPC remote workspace、target credential、remote CRUD 或 scheduler authority；capsule 中存在通用 client binary 不授予这些能力。
- 不修改旧 Host-supervised execution、`openzyme_pipeline` SDK、provider/HPC adapter 或 AOX `--network=none` 的隔离、approval、artifact/provenance 与 fence 语义。
- 不迁移 legacy artifact bytes、旧 sandbox files 或当前 Host checkout 到新 clone。
- 不挂载 Host repository、Host home、Host SSH directory或共享 `.git`，也不提供这些路径的 compatibility fallback。

## Decisions

### 0. 实现准入 snapshot 不替代 predecessor acceptance

C3 的实现准入分为两个层次。第一层是连续迁移期间的 source-only dependency gate：重读 immutable C0/C1 receipts，直接读取当前 C2 domain/migration/service/policy/interface，生成 `agent_capability_lease_implementation_snapshot@1`，列出尚未运行的 C2 focused、strict OpenSpec、mainline、scope audit 与最终 receipt tasks。第二层是全部连续 change 组合实现完成后的正式 acceptance：重新绑定最终 source revision并验证 `agent_capability_lease_acceptance@1`。

source-only gate 不是 production gate。它不能调用 provisioner、创建 volume/clone、激活 lease、清除 blocker、签发 credential、执行 network transfer、启动 live 或外部 effect；也不能让 C3/C4 或更后继 change 把 C2 标为 accepted。其唯一作用是避免为了形成中间 mainline 或中间 receipt 而引入最终架构不需要的兼容层。若 snapshot 所列接口在后继实现中发生预期修改，后继 change 必须继续以当前 source 为真并在最终统一验收中重建正式绑定，不得 fallback 到 snapshot 中的旧实现。

### 1. `AgentGitWorkspace` 是 agent-generation-owned canonical resource

新增 `AgentGitWorkspace`（或等价持久 record），identity 为 `workspace_id + session + agent_member + workspace_generation`，并绑定 session 的 exact repository binding version/base commit、volume identity、clone root logical name、current HEAD、private ref namespace、状态、policy digest和 lifecycle timestamps。同一 generation最多一个 canonical workspace；新 generation必须通过显式 replacement创建。

选择 agent-generation ownership，而不是 lane ownership，是因为一个 resident agent会跨多个 tasks/lanes保留自己的工作历史，而 lane只表达 focus和claim。选择完整 clone而不是 linked worktree，是为了给每个 capsule独立 object database、index、refs、reflogs、locks和config。

### 2. Workspace ready 与 C2 pending lease 必须原子汇合

C3 provisioner 只消费 C2 已持久化且 identity 精确匹配的 pending workspace generation、capability lease intent 和 `provisioning_required` blocker。只有专属 volume、完整 clone、repository binding/base、private namespace、policy digest 与 image qualification 全部验证通过后，Host 才在同一原子提交中把 `AgentGitWorkspace` 置为 ready、激活 matching generation-bound `AgentCapabilityLease` 并清除该 agent 的 `provisioning_required`。任一写入失败时三者均不得部分可见，agent/capsule/tool exposure 保持不可运行。

选择消费 pending intent 而不是 C3 自行创建 active lease，是为了保持 C2 对 capability lifecycle 的唯一所有权。根据 role、旧 runtime lease、legacy sandbox row、现有 tool descriptor 或进程身份推断授权均被否决；workspace identity、lease identity、agent member、generation 或 policy 任一不匹配都直接阻塞，不创建替代 generation 或 lease。

### 3. Clone 只能来自 pinned internal remote 和 exact base

provisioner 使用 session-pinned `ProjectRepositoryBinding`、Host签发的 provision credential和 resolved base commit创建完整 clone，并验证 `remote identity + object format + HEAD/tree + policy digest` 后形成只读 readiness candidate，交由前述原子汇合转换置为 ready。不得从当前 Host checkout复制、不读取 ambient `origin`，也不得在 remote失败时初始化空仓库或选择另一个 branch。

选择 exact commit checkout 而不是 mutable default branch，是为了让所有 agents的起点可复现。使用 local mirror、reference repository或共享 alternates作为隐藏 object source被否决，因为它们会重新引入共享 `.git` 生命周期和 Host path依赖；未来若增加缓存，必须是内容只读且不成为 correctness prerequisite的独立设计。

### 4. Persistent volume 拥有全部文件与 Git state

clone root、`.git`、working tree、Git/LFS objects、普通 download bytes 和 agent-created files 全部位于该 generation 专属 persistent volume。Podman执行可继续为每条命令启动短命 `--rm` container，并把同一 volume挂载为工作目录；container退出、Host进程重启或 bounded turn结束都不能删除或重建 volume。image中预装原生工具，但 volume 不保存 bearer credential、Host home 或 Host credential store。

选择 ephemeral process + persistent data，是为了保持隔离和可恢复性，同时不把 container本身提升为持久真相。持久 container方案被否决，因为进程状态不可作为文件/commit的 canonical lifecycle；Host repository mount方案也被否决。

### 5. Native capsule network 与 Host-supervised execution 是两个明确边界

generation-owned native capsule command runtime 使用 deployment 配置的 ordinary network。Host launch policy 只绑定 network identity/mode，不包含 destination allowlist；拥有 active general capability lease 的 agent 可访问该 deployment network 实际 reachable 的任意 endpoint。reachable ordinary transfer 不创建逐命令 approval，unreachable endpoint 或原生 client 错误以同一次 process 的 exit status/stderr 直接失败，Host 不 retry、replay、切换 endpoint、选择 SDK route 或创建替代 operation。

该 native private workspace 路径不替代既有 Host-supervised execution。旧 `sandbox.exec` / `openzyme_pipeline`、provider/HPC adapter、scientific execution 与 AOX blank-world/probe 的 `--network=none`、artifact staging、source snapshot、approval、quota、execution fence 和 provenance 语义保持原样；C3 不通过全局删除 `--network=none` 或放宽受控 runner 来实现 ordinary network。

### 6. Host-issued credentials 只属于 exact process 和 audience

每次显式 Git/LFS 或其他授权 service action 启动前，Host 使用 active matching capability lease 请求 C2 process credential broker，并绑定 agent member、workspace generation、service/target、protocol 和 exact audience。credential 只经该 process 的受控 helper、environment 或等价 ephemeral channel 注入；不得写入 persistent volume、`.git/config`、credential helper store、Host home/SSH directory、argv、command logs、workspace/public projection 或 artifact/catalog。ordinary credentialless network不调用 broker，也不因 endpoint 不在 credential audience 中而被 Host 阻断。

credential 到期或 endpoint 拒绝只终止当前 process。Host 不自动重放 command、不换 endpoint、不降级 scope、不重开 approval；后续由 agent 发起的另一显式 action 可以在同一 active lease 下获得新 credential。process 输出进入任何持久日志或 projection 前必须移除该次签发的 exact secret material，而不是依赖 catch-all 或关键词猜测。

### 7. Local commit、private ref 和 publication 是三个不同状态

agent 可在一个尚未完成的探索步骤内自由保持 dirty 状态。每当 agent/subagent 明确宣告一个产生持久文件的 research、implementation 或 verification 步骤完成时，它必须自行选择该步骤的文件，创建一个 coherent local commit，并显式 create/fast-forward push 到其受 ACL 保护的 append-only private namespace，随后才可把该步骤报告为 durable checkpoint 或跨越 publication、handoff、external-job、task-terminal 边界。agent 不允许 force-update 或 delete private ref，分叉时创建新 ref。只有 repository retention owner 可以依照 pinned policy，在整代 workspace generation 已关闭、retention deadline 已过且全部 lease/pin/hold 已清除后，先记录 exact terminal ref/commit set receipt，再整代退役 namespace；不能选择性裁剪 checkpoint。Host 不自动 stage、commit 或 push，也不把 local commit、private push或 branch name投影为 team shared truth；只有后继 `workspace.publish` 创建的 `PublishedRevision` 才能进入 team projection。

选择 agent 主动创建的标准 Git commit/private ref 作为逐步留痕，而不是每次文件写入创建 artifact record，是为了在保留步骤内策略自由的同时得到 durable checkpoints。Host 自动 stage/commit/push 和 auto-publish 均被否决：前者会替 agent 选择文件与语义，后者会把探索状态无意提升为共享事实。

### 8. Dirty exploration允许，跨边界必须精确且 clean

普通探索期间，working tree可以有staged、unstaged和untracked changes；workspace projection必须直接呈现porcelain-equivalent状态与exact HEAD。创建 publication 或从 private workspace 发起 external-job admission前，Host validator必须证明working tree clean、目标revision等于预期exact commit并属于该clone/repository binding。发送已经存在的 `PublishedRevision` handoff只验证该 immutable publication/ref/path，不重新检查 producer 后续可能已变脏的 working tree。validator不自动 `git add`、commit、stash、clean、merge或改写 `.gitignore`。

选择边界时验证而不是全程强制clean，是为了保留agent策略自由。自动commit或丢弃untracked files的替代方案被否决；只接受branch name而不检查commit/tree也被否决。

### 9. Workspace损坏或缺失需要显式 replacement

恢复时，Host重读workspace record和volume，验证独立 `.git`、remote identity、object format与generation。volume缺失、clone损坏、HEAD不可读或identity drift时，workspace进入明确blocked状态；Host不自动reclone、不删除volume、不从另一个agent复制，也不把旧sandbox volume当作clone。操作者/agent必须选择修复或创建新generation，旧generation先冻结并保留审计事实。

选择显式 replacement 是为了避免自动恢复覆盖未发布的私有工作。catch-all后reclone方案被否决，因为它会把数据丢失伪装成成功恢复。

## Risks / Trade-offs

- [每个agent完整clone增加磁盘和网络成本] → 以retention/quota度量和显式GC管理；不以linked worktree或shared `.git`换取空间。
- [已完成步骤只留 local commit 时受节点故障影响] → durable checkpoint 要求 agent 将 coherent commit fast-forward 到 append-only private ref；projection清楚显示 local/private/published 状态，但 Host 不替 agent 自动选择、commit、push 或 publish 文件。
- [允许dirty状态会让边界操作更常失败] → 在projection提供准确Git status和修正提示，边界保持fail closed且不自动修改用户文件。
- [短命container需要反复注入toolchain/credential] → 固定versioned image和process-scoped credential broker；volume是唯一持久workspace真相。
- [ordinary network扩大native capsule可达面] → deployment决定实际网络可达性，Host不维护destination allowlist；service credential仍按exact audience签发，受控execution网络边界保持不变。
- [credential可能经输出或配置落盘] → 使用process-scoped ephemeral injection并在任何持久日志/projection前按exact issued secret清除；credential拒绝直接失败且不重放动作。
- [downloaded private bytes绕过artifact catalog] → volume audit只记录owner/generation/process事实，不提升普通bytes；只有后继明确publication或受控boundary才能建立shared truth。
- [旧sandbox volume含未迁移文件] → 旧volume只读冻结，由专门migration处理；不把无Git来源的内容自动混入新clone。

## Migration Plan

1. 记录非验收 C2 implementation snapshot；它只开放后继源码实现，不开放实际 provisioning、live 或 effect。
2. 新增 workspace identity/state/repository、generation唯一约束和安全projection，明确引用 C2 pending generation/lease intent 与 session repository binding。
3. 构建versioned capsule image，安装filesystem/shell、Git、Git LFS、OpenSSH client、rsync、scp/curl并证明无Host home/repository mount。
4. 实现provisioner：创建专属persistent volume，从pinned internal remote clone exact base；验证全部 identity 后，以单一原子状态转换置 workspace ready、激活 matching lease 并解除 `provisioning_required`。
5. 实现generation-owned Podman command runtime、deployment ordinary network、active-lease tool exposure和process-scoped credential injection；用真实reachable/unreachable endpoint证明无Host destination allowlist、无retry/fallback且credential不落盘/日志/projection，同时保持旧Host-supervised/AOX no-network路径不变。
6. 将agent/subagent runtime cwd切换到owning clone；停止写入`Lane.cwd/branch_name`作为workspace authority，保留lane focus字段直到public-interface cutover删除兼容投影。
7. 接入 Git status/HEAD/private-ref projection、completed-step checkpoint contract 和 clean committed revision validator；验证未 checkpoint 的已完成步骤不能被报告为 durable 或跨正式边界，且 Host 从不自动选择、commit 或 push 文件。
8. 对既有agent消费C2 pending intent建立显式new generation；legacy sandbox volumes保持冻结且不自动复制，等待历史文件迁移策略。
9. 全部连续 change 的组合实现完成后统一验证 predecessor/current receipts、focused/strict/mainline/scope evidence；回滚时停止新workspace provision和runtime挂载，保留已有volume、commit和private ref，禁止reclone、删除或旧lease复活。

## Open Questions

无。实现准入 snapshot 与 final acceptance 分离、完整clone、持久volume、私有revision、clean boundary、lane降级和恢复策略均已裁决。
