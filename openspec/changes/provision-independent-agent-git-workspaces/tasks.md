## 1. C3 前置 receipts 与汇合 gate

- [ ] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1`，确认C0 legacy NO-GO仍有效且没有旧AOX live、c001或8.3--8.8状态漂移。
- [ ] 1.2 同时验证 `project_repository_binding_acceptance@1` 与 `agent_capability_lease_acceptance@1`，精确绑定其source/code/schema/policy digests；任一receipt缺失或失配时不得provision workspace。
- [ ] 1.3 生成C3 dependency gate receipt，证明pinned internal remote可由native Git/LFS访问、durable roots可恢复、private ref ACL为create/fast-forward only，并且generation-bound lease可在workspace ready后激活。
- [ ] 1.4 冻结当前 `SandboxWorkspaceRecord`、lane cwd/branch、Podman lifecycle、agent/subagent creation与tool image基线，列出必须替换的authority reads和禁止采用的Host mount/linked-worktree fallbacks。

## 2. AgentGitWorkspace domain、migration 与 repositories

- [ ] 2.1 在 `openzyme-domain` 增加 `AgentGitWorkspace` identity/status/blocker types，绑定workspace id、session、agent member、generation、repository binding/base、volume identity、clone logical root、HEAD、private namespace、policy digest和lifecycle facts。
- [ ] 2.2 添加单一forward SQL migration与repository，建立每个 `session + agent_member + generation` 唯一workspace、显式generation replacement关系、状态转换和必要FK/index constraints。
- [ ] 2.3 实现workspace lifecycle service的provisioning/ready/blocked/frozen/replaced transitions，禁止把另一agent/generation record或legacy sandbox directory重新标记为当前workspace。
- [ ] 2.4 实现safe workspace identity digest与restore comparator，精确校验volume、独立 `.git`、remote identity、object format、base、generation、HEAD readability和policy。
- [ ] 2.5 增加domain/migration/repository/lifecycle focused tests，覆盖duplicate generation、cross-agent volume、invalid transition、identity drift和explicit replacement。

## 3. Versioned capsule image 与 persistent full-clone provisioner

- [ ] 3.1 建立versioned capsule image/build manifest，安装并版本固定Git、Git LFS、OpenSSH client、rsync、scp与curl，同时保留普通filesystem/shell工具。
- [ ] 3.2 增加image qualification，实际执行每个required binary/version和Git LFS initialization，并证明镜像不依赖Host checkout、Host home或Host SSH directory。
- [ ] 3.3 实现generation-specific durable volume allocator，确保clone root、working tree、完整 `.git`、Git/LFS objects和agent files全部落在同一专属persistent volume。
- [ ] 3.4 实现provisioner从session-pinned HTTPS internal remote完整clone、checkout exact base commit并验证remote/object format/HEAD/tree/private namespace/policy后才置ready。
- [ ] 3.5 明确拒绝linked worktree、shared `.git`、`--reference`/shared alternates、Host repository copy/mount、ambient origin/cwd、guessed branch和empty-repository fallback。
- [ ] 3.6 将workspace ready与matching `AgentCapabilityLease` activation按persisted state顺序连接；clone或验证失败时lease保持inactive且不启动agent capsule。
- [ ] 3.7 增加provisioner integration tests，覆盖两个agents/subagents同base但不同volume/`.git`、remote/base drift、失败无fallback和ready后lease activation。

## 4. Podman runtime、tooling 与 agent operating contract

- [ ] 4.1 将Podman command runtime切换为短命 `--rm` process挂载owning generation volume为唯一writable cwd，process退出、turn结束和Host重启均复用原volume。
- [ ] 4.2 将Git/LFS/SSH/transfer credentials限定为process-scoped injection，禁止写入persistent repo config/volume或挂载Host home/SSH/credential storage。
- [ ] 4.3 将agent/subagent runtime cwd从lane metadata切换到`AgentGitWorkspace`，保留lane的task focus/claim语义并停止用`Lane.cwd/branch_name`选择clone、branch或HEAD。
- [ ] 4.4 更新agent operating contract：unfinished exploration可保留staged/unstaged/untracked状态；每个被agent明确宣告完成且产出持久文件的coherent research/implementation/verification step必须由agent自行选文件、commit并create/fast-forward到append-only private ref后才能报告durable checkpoint。
- [ ] 4.5 在operating contract中明确Host绝不auto-stage、auto-commit、auto-push、auto-clean或替agent选择coherent files；Git错误直接返回，由agent决定修正、继续dirty探索或新建private ref。
- [ ] 4.6 为publication、handoff、external-job和task-terminal formal boundaries定义checkpoint-proof input seam，要求exact workspace generation、commit/tree、private ref和create/fast-forward remote observation；C4只消费该seam，不在C3实现publication。
- [ ] 4.7 增加Podman/runtime tests，覆盖 `--rm` 后tracked/untracked/index/refs/objects完整恢复、Host restart reuse、tool binaries可用、credential不落盘和forbidden mounts。

## 5. Private refs、projection 与 boundary validation

- [ ] 5.1 实现agent显式private push支持，仅允许own namespace ref create或fast-forward；分叉必须创建新ref，force-update/delete和cross-agent writes直接失败。
- [ ] 5.2 实现read-only private checkpoint validator，证明remote private ref精确指向agent声明commit、属于pinned binding/generation且相对上一checkpoint为create/fast-forward；validator不得执行任何Git mutation。
- [ ] 5.3 扩展workspace projection，分别展示dirty status、exact local HEAD、last verified private checkpoint、checkpoint lag和published state，不向其他agents投影private ref或把private checkpoint标为team truth。
- [ ] 5.4 在durable-checkpoint reporting与formal boundary admission中消费checkpoint proof：已完成file-producing step若未commit/private-fast-forward必须被拒绝，且Host不得自动补做Git操作。
- [ ] 5.5 实现clean committed revision validator，publication与private-source external job要求working tree clean、expected HEAD一致且commit属于pinned binding；不得add/commit/stash/clean/merge/ignore/discard。
- [ ] 5.6 保持existing immutable `PublishedRevision` handoff例外：只验证publication/ref/path，producer后来dirty不得使旧publication handoff失效或触发其working-tree mutation。
- [ ] 5.7 增加private-ref/projection/boundary tests：两步coherent file work产生两个顺序commit与private fast-forward checkpoints；unfinished step保持dirty；未checkpoint completed step被boundary拒绝；Host全程无auto-stage/commit/push。
- [ ] 5.8 接入 repository-binding 的整代 retention receipt，证明 agent 永远不能删除 private ref，retention owner 只能在 generation closed、deadline 已过且所有 hold 清除后整代退役 namespace，并拒绝选择性 checkpoint pruning。

## 6. Recovery 与 legacy workspace migration boundary

- [ ] 6.1 在Host restore中重开exact workspace record/volume并重验独立 `.git`、remote/object format/generation/HEAD；完整时复用，缺失/损坏/drift时置明确blocked。
- [ ] 6.2 实现explicit replacement command，保留old generation/volume/checkpoint facts、终止旧capability lease并从pinned base创建新generation；禁止auto-reclone、delete或copy另一个agent workspace。
- [ ] 6.3 为existing agents建立显式new-generation migration，冻结legacy sandbox volumes且不自动复制其中files；legacy bytes等待独立historical migration change。
- [ ] 6.4 增加recovery tests，覆盖missing volume、corrupt `.git`、unreadable HEAD、remote drift、replacement、old lease revocation与未发布private work不被静默覆盖。

## 7. Focused tests、文档与 C3 验收 receipt

- [ ] 7.1 运行domain/core/engine/Host与native-client focused suites，覆盖独立完整clones、persistent `--rm` volume、required image tools、private create/fast-forward ACL、两步durable checkpoints、unfinished dirty与无Host auto-Git。
- [ ] 7.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/03-capability-engines.md`、`docs/v3/05-agent-runtime.md`、`docs/v3/06-top-level-llm-loop.md` 及sandbox/execution文档，记录agent-owned clone、checkpoint operating contract、lane降级和recovery边界。
- [ ] 7.3 运行 `DO_NOT_TRACK=1 openspec validate provision-independent-agent-git-workspaces --type change --strict --no-interactive` 并保存通过结果。
- [ ] 7.4 运行 `./scripts/check-mainline.sh`，确认不得以shared `.git`、Host mount、auto-commit/push、temporary clone或live integration绕过失败。
- [ ] 7.5 审计Git diff、migration、image manifest、Podman mounts、credential paths与agent instructions，确认未实现C4 publication/auto-sync，也未迁移legacy artifacts。
- [ ] 7.6 生成 immutable `agent_git_workspace_acceptance@1` change receipt，绑定C0/C1/C2 receipts、code/schema/image/policy digests、focused tests、two-step checkpoint proof、docs、strict OpenSpec、mainline、restart/recovery proof与`eligible_successor = C4`。
