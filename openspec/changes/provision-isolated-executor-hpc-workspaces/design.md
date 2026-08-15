## Context

当前 `mcp-hpc-runner` 为每个 RunSpec 创建 remote run directory，将 artifact inputs staging 到远端，并把 declared outputs fetch 回 Host。该模型让 executor 无法把 HPC login side 当作自己的持续工作空间，也重复了 local clone、artifact catalog、`HpcStageRef` 与 per-run copy 的文件生命周期。

目标架构已经为每个 agent 建立独立 Git clone，并通过 `AgentCapabilityLease` 一次授予 scope 内的原生工具。本 change 将相同 `session + agent_member + workspace_generation` 延伸到一个 executor-owned HPC login workspace：它具有独立 clone、可读写工作目录、标准 Git/LFS、SSH 与 rsync/scp 能力。login node 可访问 Host-managed internal Git/LFS remote；compute node 的 Gitless source tree由后续 `execute-hpc-jobs-from-workspace-revisions` 定义。

Provision、generation replacement、sync 与 cleanup 都是外部 effect，不能与 Host SQLite 事务原子完成。它们必须使用持久 intent、唯一 idempotency identity、opaque runner handle、immutable receipt 与 exact reconciliation，不能因 response loss 创建第二个目录。

## Goals / Non-Goals

**Goals:**

- 为每个 executor workspace generation 和 HPC target provision 一个身份闭合、持久、隔离的 login-side clone/workspace。
- 允许拥有者在 capability lease scope 内直接使用 Git、Git LFS、SSH、rsync/scp 和普通文件 CRUD。
- 让 private revisions 通过 agent-private ref namespace同步，让 published revisions 通过 immutable publication refs同步，并保持二者真相边界。
- 使 owner 可使用其 remote workspace handle/path，同时向其他 agent和普通公共 projection隐藏该定位信息。
- 以 reliable handle/receipt 处理 provisioning、sync、replacement 与 cleanup，response loss 只 reconcile同一 effect。
- 移除 per-run artifact staging、Host output fetch 与 `HpcStageRef` 目标合同。

**Non-Goals:**

- 不允许多个 executor共享 clone、remote directory、credential或 mutable branch。
- 不把 private push、rsync、scp 或 remote file mutation解释为 team publication。
- 不让 Host typed transfer gateway代理普通文件或网络 I/O。
- 不定义 Slurm job source tree、job result identity 或 `expected_outputs` 的最终删除；由后续 workspace-revision execution change完成。
- 不允许 compute node访问 Git/LFS remote、credential或 login clone的 `.git`。
- 不在 provisioning ambiguity时猜测 directory、重建替代 workspace或改用另一个 target。

## Decisions

### 1. Remote workspace identity 与本地 workspace generation 一一绑定

新增 canonical `ExecutorHpcWorkspace`，身份至少绑定 project repository binding version、session、executor agent member、本地 workspace generation、HPC target profile digest、remote workspace generation 与 lifecycle version。一个 exact tuple 至多存在一个 active remote workspace；generation replacement创建新 identity，旧 generation不能被新 lease隐式复用。

Host-visible record保存 opaque `executor_hpc_workspace_id`、provision intent、runner handle/receipt、state/version和 safe timestamps。拥有者的授权 projection可额外得到可直接用于 SSH/rsync 的 remote login alias和workspace path；其他 agent、protocol payload、task evidence和普通公共诊断只看到 opaque id与safe state。

备选的 per-run目录没有持续 workspace语义；按 project共享远端目录无法隔离任意 shell和Git state，均不采用。

### 2. Login side 使用独立完整 clone 和持久可写 workspace

每个 remote workspace包含独立 `.git`、working tree、LFS local object state和workspace-owned scratch/run directories，不使用 linked worktree、共享 `.git` 或其他 agent目录。workspace跨 sandbox turn、runner restart和多个 job持续存在，直到显式 generation replacement/cleanup完成。

Agent可以修改、删除或重建自己 workspace中的普通文件，但 canonical identity不从 remote marker或当前路径反推。若 canonical root缺失、owner marker不匹配或 repository identity漂移，系统将 workspace标为明确 invalid/missing并停止；不会在同一 generation下静默创建替代目录。

### 3. Executor lease 直接授予原生 HPC login 数据面

有效 executor `AgentCapabilityLease` 包含 exact target与remote workspace generation后，Podman capsule可获得到该 login account/root的短期 SSH credential，并直接运行 SSH、Git、Git LFS、rsync、scp及普通 shell/file命令。Host不逐命令代理、审批或记录普通 transfer bytes。

Credential必须限制到 executor、target、workspace root和lease lifecycle；不得读取其他 agent workspace或Host runner私有 receipt/metadata。lease revoke/retirement停止新 credential发行并撤销可撤销 credential，但不能由此推断已启动的 transfer/job被取消。

备选的 Host typed transfer gateway违背已裁决的原生工作方式，故不保留。

### 4. Internal Git/LFS remote 是 local 与 HPC workspace 的同步面

Local capsule和HPC login clone都使用 repository binding固定的 internal remote。agent可将 clean commit推到自己的private namespace，并在另一侧fetch；这些 private refs只对拥有者授权，不进入team projection。`PublishedRevision` 的immutable refs可被有权限的executor正常fetch，但不会自动merge、checkout或改变remote workspace。

rsync/scp可用于agent自由传输未提交scratch data，其结果仍是remote mutable state。只有显式commit和`workspace.publish`能建立shared file truth。

### 5. Provisioning 采用 intent、唯一 key、runner handle 与远端 sidecar receipt

Host在任何SSH effect前持久化冻结 `ExecutorHpcWorkspaceProvisionIntent`，包含workspace identity、binding、target、remote generation、requested root policy与idempotency key。runner在其私有状态根和远端runner-owned sidecar namespace中用该key执行compare-and-create，选择一次opaque remote path，创建目录/clone，验证repository remote与owner，然后写immutable provision receipt并返回opaque handle。

Agent对workspace root可读写，但不能修改runner sidecar receipt。若 response在远端effect后丢失，canonical state进入`dispatch_in_doubt`；reconciler只能按同一 intent/key/handle查询sidecar与exact path。它不得创建第二个目录、改变target或宣布no-effect。若target不能提供权威query与idempotent compare-and-create，该target资格失败。

### 6. Sync 与 repair 不替代 agent 的 Git策略

系统级sync只负责明确请求的exact private/published ref fetch/checkout或workspace identity核验，并同样留下effect receipt。普通agent sync仍由原生Git/rsync完成。系统不自动force-update branch、clean dirty tree、解决冲突、选择另一个ref或把local/private state发布给team。

Remote workspace损坏时，repair只能在proven no-effect或exact existing handle上继续同一操作。需要新目录时必须显式创建higher generation；不存在“发现失败便重建同generation”的fallback。

### 7. Runner 从 per-run staging 迁到 workspace ownership

Runner API不再接收input artifact、`stage_to`、Host local artifact path或`HpcStageRef`，也不把declared output fetch到Host。run仍可拥有server-issued opaque `run_id`和workspace内job-specific目录，但这些目录属于同一executor workspace，而非独立artifact staging/publishing面。

Provisioning/sync preflight验证exact workspace handle、generation、owner、target、repository binding、root存在性和所需原生toolchain。普通结果文件留在remote workspace，供executor直接检查、下载、commit与publish。

### 8. Cleanup 是独立、受保护的外部 effect

Session结束、agent retirement、lease revoke或generation replacement只停止新admission，并将workspace转为retention/cleanup eligible；它们不证明远程job、transfer或process已经settled。Cleanup必须确认该generation无活跃controlled execution和未结算effect，使用exact handle删除或封存同一root，并持久化receipt。ambiguous cleanup保持unknown，不尝试另一个path。

## Risks / Trade-offs

- [Agent拥有原生SSH和可写remote目录，误操作范围扩大] → 用独立OS principal/root、target-scoped短期credential和workspace generation隔离；不通过恢复Host file proxy来缓解。
- [Agent删除或污染自己的remote clone] → canonical record不相信remote mutable marker；preflight明确报告missing/dirty/drift，修复需agent操作或显式新generation。
- [Provision response loss导致重复目录] → 远端runner-owned idempotency sidecar与same-intent reconciliation；没有可靠query的target不获资格。
- [Private ref/LFS bytes占用增长] → repository binding和workspace retention/quota管理；publication pin与private retention分离。
- [Remote path对owner可见增加信息暴露] → 仅owner executor projection和scope credential可见；其他agent与公共event只使用opaque id。
- [仍在运行的旧per-run staging caller与新workspace合同冲突] → 以版本化breaking cutover拒绝artifact/`HpcStageRef` request，不并行运行两套runner writer。

## Migration Plan

1. 先完成 repository binding、AgentCapabilityLease、独立 local clone、Git LFS 和 workspace publication；这些前置 change 已向 capsule 提供原生文件/Git/网络工具，本 change 不依赖后续统一删除 legacy sandbox/artifact surface。HPC target 必须证明 login node 可访问 internal Git/LFS，compute node 无需这些能力。
2. 为每个target部署runner-owned provisioning sidecar、opaque handle store、idempotency lookup、workspace root/OS principal policy和scoped credential issuance；通过create-response-loss-reconcile、restart、owner isolation与path tamper资格测试。
3. 增加canonical `ExecutorHpcWorkspace` 与provision/sync/cleanup intent/receipt；所有external callbacks使用existing controlled-operation owner、lease/fence和effect-certainty语义。
4. Provision新workspace generations，验证independent `.git`、native Git/LFS、SSH/rsync/scp、private ref sync、published ref fetch和owner-only path visibility。
5. 将runner从artifact inputs/`HpcStageRef`/Host output fetch切到exact executor workspace handle/generation。任何旧RunSpec进入current endpoint均明确schema rejection。
6. 与`execute-hpc-jobs-from-workspace-revisions`共同切换job admission/result surface；在后者完成前不得把workspace runner标为current production path。
7. 停止旧staging writer后保留其历史records只供后续迁移，不允许current read fallback或dual writer。最终数据结构删除由artifact removal change完成。
8. Cleanup旧remote staging roots只能在job/effectsettlement与历史迁移证明后执行，并保存不可变receipt。
9. 回滚仅可在新workspace尚未承载current job前恢复整个旧deployment。切换后采用前向修复；不能在新workspace故障时动态恢复per-runartifact staging或`HpcStageRef`。

## Open Questions

无未决产品问题。每个HPC target的OS principal方式、remote root、Git/LFS版本、SSH credential provider和Slurm authoritative query能力属于显式deployment qualification；任一不满足即阻止该target启用。
