> 统一整改证据解释见 [final-acceptance-policy.md](../close-file-workspace-cutover-verification-gaps/evidence/final-acceptance-policy.md)；source-only gate、旧 receipt 和 PostHog telemetry 均不构成最终 acceptance。

## 1. C3 实现依赖 snapshot 与最终 receipt gate

- [x] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1`，确认C0 legacy NO-GO仍有效且没有旧AOX live、c001或8.3--8.8状态漂移。
- [x] 1.2 验证 immutable `project_repository_binding_acceptance@1`；对尚待最终统一验收的 C2 生成 `agent_capability_lease_implementation_snapshot@1`，精确绑定当前source/schema/policy/interface digests和未完成验收tasks，并固定`acceptance_proven=false`、`final_source_revision_bound=false`、`production_effect_authorized=false`、`live_authorized=false`。snapshot只允许继续源码实现，不能替代最终C2 receipt或任何runtime/production authority。
- [x] 1.3 生成C3 source-only dependency gate record，记录pinned internal remote、durable roots、private ref ACL接口与C2 persisted pending generation、matching lease intent、`provisioning_required`的当前实现事实；禁止从legacy sandbox/runtime/tool exposure推断授权，禁止据此实际provision workspace、激活lease、签发credential、运行live/effect或宣称任一production proof。
- [x] 1.4 冻结当前 `SandboxWorkspaceRecord`、lane cwd/branch、Podman lifecycle、agent/subagent creation与tool image基线，列出必须替换的authority reads和禁止采用的Host mount/linked-worktree fallbacks。

## 2. AgentGitWorkspace domain、migration 与 repositories

- [x] 2.1 在 `openzyme-domain` 增加 `AgentGitWorkspace` identity/status/blocker types，绑定workspace id、session、agent member、generation、repository binding/base、volume identity、clone logical root、HEAD、private namespace、policy digest、C2 pending lease intent identity和lifecycle facts。
- [x] 2.2 添加单一forward SQL migration与repository，建立每个 `session + agent_member + generation` 唯一workspace、显式generation replacement关系、状态转换和必要FK/index constraints。
- [x] 2.3 实现workspace lifecycle service的provisioning/ready/blocked/frozen/replaced transitions，ready transition必须要求matching C2 pending generation/lease；禁止把另一agent/generation record、legacy sandbox directory、runtime lease、role或现有tool exposure重新标记为当前workspace或active authority。
- [x] 2.4 实现safe workspace identity digest与restore comparator，精确校验volume、独立 `.git`、remote identity、object format、base、generation、HEAD readability和policy。
- [x] 2.5 增加domain/migration/repository/lifecycle focused tests，覆盖duplicate generation、cross-agent volume、invalid transition、identity drift和explicit replacement。

## 3. Versioned capsule image 与 persistent full-clone provisioner

- [x] 3.1 建立versioned capsule image/build manifest，安装并版本固定Git、Git LFS、OpenSSH client、rsync、scp与curl，同时保留普通filesystem/shell工具。
- [x] 3.2 增加image qualification，实际执行每个required binary/version和Git LFS initialization，并证明镜像不依赖Host checkout、Host home或Host SSH directory。
- [x] 3.3 实现generation-specific durable volume allocator，确保clone root、working tree、完整 `.git`、Git/LFS objects和agent files全部落在同一专属persistent volume。
- [x] 3.4 实现provisioner从session-pinned HTTPS internal remote完整clone、checkout exact base commit并验证remote/object format/HEAD/tree/private namespace/policy后形成readiness candidate；只有3.6的原子汇合可将workspace置ready。
- [x] 3.5 明确拒绝linked worktree、shared `.git`、`--reference`/shared alternates、Host repository copy/mount、ambient origin/cwd、guessed branch和empty-repository fallback。
- [x] 3.6 将verified `AgentGitWorkspace.ready`、matching `AgentCapabilityLease.active`与exact `provisioning_required`清除实现为单一原子状态转换；clone、image、identity、policy或任一持久化步骤失败时三者均不部分可见，lease保持inactive且不启动agent capsule。
- [x] 3.7 增加provisioner integration tests，覆盖两个agents/subagents同base但不同volume/`.git`、remote/base drift、pending lease/generation mismatch、原子提交失败无partial state、失败无fallback以及ready后lease activation和blocker清除。

## 4. Podman runtime、tooling 与 agent operating contract

- [x] 4.1 将Podman command runtime切换为短命 `--rm` process挂载owning generation volume为唯一writable cwd，process退出、turn结束和Host重启均复用原volume。
- [x] 4.2 为generation-owned native capsule配置deployment ordinary network；launch policy不得包含Host destination allowlist，reachable endpoint按原请求访问，unreachable endpoint保留native exit/stderr且不retry、replay、换endpoint、走SDK fallback或重开approval。
- [x] 4.3 将native filesystem/shell/Git/LFS/curl/upload/download tool exposure改为同时消费ready `AgentGitWorkspace`和matching active capability lease；provisioning/inactive/mismatched lease在process启动前显式拒绝且不按role或旧descriptor fallback。
- [x] 4.4 将Git/LFS与其他Host-issued service credentials限定为exact lease/agent/generation/service/target/protocol/audience的process-scoped injection；禁止写入persistent repo config/helper store/volume、argv、Host home/SSH storage、command logs、artifact/catalog或public/workspace projection，并在持久化任何process output前按本次issued exact secret material清除。
- [x] 4.5 保持ordinary credentialless network不调用credential broker；credential到期/拒绝仅令当前显式action失败，后续显式action可重新签发，但不得auto retry/replay、fallback endpoint、降权或重开approval。
- [x] 4.6 将agent/subagent runtime cwd从lane metadata切换到`AgentGitWorkspace`，保留lane的task focus/claim语义并停止用`Lane.cwd/branch_name`选择clone、branch或HEAD。
- [x] 4.7 更新agent operating contract：unfinished exploration可保留staged/unstaged/untracked状态；每个被agent明确宣告完成且产出持久文件的coherent research/implementation/verification step必须由agent自行选文件、commit并create/fast-forward到append-only private ref后才能报告durable checkpoint。
- [x] 4.8 在operating contract中明确Host绝不auto-stage、auto-commit、auto-push、auto-clean或替agent选择coherent files；Git/network错误直接返回，由agent决定修正、继续dirty探索或新建private ref。
- [x] 4.9 为publication、handoff、external-job和task-terminal formal boundaries定义checkpoint-proof input seam，要求exact workspace generation、commit/tree、private ref和create/fast-forward remote observation；C4只消费该seam并拥有publication创建，C3不得创建`PublishedRevision`。
- [x] 4.10 增加Podman/runtime tests，覆盖 `--rm` 后tracked/untracked/index/refs/objects/private downloaded bytes完整恢复、Host restart reuse、active-lease native tool exposure、required binaries可用、reachable ordinary endpoint无Host destination allowlist和无per-command approval、unreachable endpoint无retry/fallback、credential不落volume/repo config/Host home/logs/projection、inactive/revoked lease无process以及forbidden mounts。
- [x] 4.11 对旧Host-supervised execution、`openzyme_pipeline` SDK和AOX路径增加回归断言，证明其现有`--network=none`、Host-mediated external operation、approval、artifact/provenance和execution fence语义未被native capsule network修改。

## 5. Private refs、projection 与 boundary validation

- [x] 5.1 实现agent显式private push支持，仅允许own namespace ref create或fast-forward；分叉必须创建新ref，force-update/delete和cross-agent writes直接失败。
- [x] 5.2 实现read-only private checkpoint validator，证明remote private ref精确指向agent声明commit、属于pinned binding/generation且相对上一checkpoint为create/fast-forward；validator不得执行任何Git mutation。
- [x] 5.3 扩展workspace projection，分别展示dirty status、exact local HEAD、last verified private checkpoint、checkpoint lag和published state，不向其他agents投影private ref、private downloaded bytes、credential/service locator或把private checkpoint标为team truth。
- [x] 5.4 在durable-checkpoint reporting与formal boundary admission中消费checkpoint proof：已完成file-producing step若未commit/private-fast-forward必须被拒绝，且Host不得自动补做Git操作。
- [x] 5.5 实现clean committed revision validator，为后继publication与private-source external job返回working tree clean、expected HEAD一致且commit属于pinned binding的proof；C3不得创建`PublishedRevision`，也不得add/commit/stash/clean/merge/ignore/discard。
- [x] 5.6 保持existing immutable `PublishedRevision` handoff例外：只验证publication/ref/path，producer后来dirty不得使旧publication handoff失效或触发其working-tree mutation。
- [x] 5.7 增加private-ref/projection/boundary tests：两步coherent file work产生两个顺序commit与private fast-forward checkpoints；unfinished step保持dirty；跨container private bytes不产生artifact/engine/scientific/publication/task/protocol/cross-agent truth；未checkpoint completed step被boundary拒绝；Host全程无auto-stage/commit/push。
- [x] 5.8 接入 repository-binding 的整代 retention receipt，证明 agent 永远不能删除 private ref，retention owner 只能在 generation closed、deadline 已过且所有 hold 清除后整代退役 namespace，并拒绝选择性 checkpoint pruning。

## 6. Recovery 与 legacy workspace migration boundary

- [x] 6.1 在Host restore中重开exact workspace record/volume并重验独立 `.git`、remote/object format/generation/HEAD、matching active lease和已清除的exact provisioning blocker；完整时复用，缺失/损坏/drift时置明确blocked且不复制旧process credential或tool authority。（整改登记：[GAP-AGW-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
- [x] 6.2 实现explicit replacement command，保留old generation/volume/checkpoint facts、终止旧capability lease并从pinned base创建新generation；禁止auto-reclone、delete或copy另一个agent workspace。
- [x] 6.3 为existing agents消费C2 pending intent建立显式new-generation migration，冻结legacy sandbox volumes且不自动复制其中files或继承tool authority；legacy bytes等待独立historical migration change。
- [x] 6.4 增加recovery tests，覆盖missing volume、corrupt `.git`、unreadable HEAD、remote drift、lease/workspace generation drift、replacement、old lease revocation、provisioning blocker保持与未发布private work不被静默覆盖。（整改登记：[GAP-AGW-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）

## 7. 最终统一测试、文档与 C3 验收 receipt

- [x] 7.1 在全部连续 change 组合实现完成后运行domain/core/engine/Host与native-client focused suites，覆盖独立完整clones、C2 pending-to-active原子汇合、persistent `--rm` volume、active-lease required tools、reachable/unreachable ordinary network无Host destination allowlist和无per-command approval、process credential isolation、private bytes不成shared truth、private create/fast-forward ACL、两步durable checkpoints、unfinished dirty与无Host auto-Git。
- [x] 7.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/01-target-architecture.md`、`docs/v3/03-capability-engines.md`、`docs/v3/05-agent-runtime.md`、`docs/v3/06-top-level-llm-loop.md` 及sandbox/execution文档，记录C2 pending lease汇合、agent-owned clone、native ordinary network与旧Host-supervised no-network边界、process credential isolation、private bytes、checkpoint operating contract、lane降级和recovery边界。
- [x] 7.3 在最终统一验收阶段运行 `DO_NOT_TRACK=1 openspec validate provision-independent-agent-git-workspaces --type change --strict --no-interactive` 并保存通过结果。
- [x] 7.4 在最终统一验收阶段运行 `./scripts/check-mainline.sh`，确认不得以shared `.git`、Host mount、auto-commit/push、temporary clone或live integration绕过失败。
- [x] 7.5 在最终组合源码上审计Git diff、migration、image manifest、Podman mounts/network args、credential injection/redaction、tool exposure与agent instructions，确认未弱化旧Host-supervised execution/AOX `--network=none`，且C4 publication/auto-sync、HPC remote与legacy迁移仍由各自指定后继change拥有。
- [x] 7.6 最终统一验收全部通过后生成 immutable `agent_git_workspace_acceptance@1` change receipt，绑定正式C0/C1/C2 receipts、最终source revision、pending-to-active atomic proof、code/schema/image/policy digests、focused tests、reachable/unreachable native network proof、credential non-persistence proof、private-bytes proof、two-step checkpoint proof、docs、strict OpenSpec、mainline、restart/recovery proof与`eligible_successor = C4`；实现期 snapshot 不得被升级为该 receipt。（整改登记：[GAP-AGW-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)、[GAP-RECEIPT-001](../close-file-workspace-cutover-verification-gaps/evidence/evidence-gap-registry.json)）
