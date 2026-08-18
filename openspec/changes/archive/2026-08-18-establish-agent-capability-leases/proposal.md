## Why

现有 `SessionRuntimeLease`、execution lease 和 mutation fence 分别解决 scheduler 与 canonical mutation ownership，不能表达“一次授予后 agent 在自己的 workspace generation 中持续拥有一组明确能力”的产品语义。与此同时，当前代码没有 canonical workspace generation readiness、长期 capability grant 或可供 credential/admission boundary 原子验证的 owner；若继续从旧 sandbox process、runtime lease、tool exposure 或 caller 自报 assertion 推断能力，就会产生不可审计的隐式授权。

## What Changes

- 新增独立的 `AgentCapabilityLease` control-plane，精确绑定 `session + agent_member + workspace_generation + profile + policy`，状态为 `pending_workspace | active | revoked`。
- 新增 workspace generation reservation/readiness seam。C2 只持久化 generation identity、reservation 与 verified-readiness fact，不创建 clone、volume、capsule、network 或 toolchain；C3 提供真实 workspace readiness 后才能激活 lease。
- 从 C2 落地开始，在 agent runtime 与 delegation admission 强制校验 exact-generation active lease。缺少 ready workspace 或 active lease 的 existing/new agent 一律显式返回 `provisioning_required` 并保持 non-runnable，直到 C3 完成 provisioning 与 activation；不得回退到旧 sandbox、parent capsule 或 ambient process authority。
- 冻结 closed general/executor capability profiles、target scope 与 policy digest，但本 change 只建立 policy、credential 和 admission seams。executor profile 中的 SSH、rsync/scp、HPC login CRUD 与 Slurm 名称只是后继边界可消费的授权声明，不在 C2 签发真实远程 HPC credential、执行远程 CRUD、自动创建 approval-free job 或实现 one-occurrence `sbatch`。
- delegation 为 child 登记独立 generation reservation 与 derived pending lease provenance，不共享 parent token、workspace 或 credential；child 只有在自己的 C3 workspace ready 且 lease 激活后才可运行。
- 新增明确的 revoke topology：默认只撤销 exact lease；session end 与 policy invalidation 按适用范围 bulk revoke；operator 只有显式请求时才可撤销一个 derived subtree；child revoke 不反向影响 parent。
- 新增 canonical `AgentRetirementRequest` admission freeze、与其精确绑定的 cleanup proof，以及最终 `AgentRetirementRecord` / shutdown-completed fact。request 提交后停止该 exact member 的新 signal/turn/credential admission；已 claim occurrence 必须先显式结算，cleanup proof 才可持久化。只有最终 retirement closure 终止该 agent 的全部 pending/active leases；`FAILED`、`COMPLETED`、`STOPPED` 状态均不得被推断为 retirement。
- 将 C1 repository credential boundary 从 caller 构造的临时 capability assertion 升级为同一 transaction 内读取 canonical active lease 的 credential/admission seam；credential TTL 不结束 capability lease。
- capability lease 与 session runtime lease、controlled-operation execution lease/fence、mutation authority 和 scientific authorization 保持正交。C2 不创建万能 budget owner：scientific ceilings 仍属于 `ScientificAttemptAuthorization`，prompt/step budget 仍是机械 runtime constraint。真实 publication intent / `PublishedRevision` owner 与交叉矩阵留给 C4。
- 所有 missing、pending、revoked、identity/generation/profile/target/policy mismatch 与 credential failure 都直接返回稳定错误；不做 silent retry、fallback、自动重放、隐式降权或自动 task transition。

## Capabilities

### New Capabilities
- `agent-capability-lease`: 定义 generation-bound capability lease 的 reservation/readiness、pending/active/revoked lifecycle、派生、撤销拓扑、credential/admission seam 与 authority 正交语义。

### Modified Capabilities

## Impact

影响 `openzyme-domain`、SQLite migration/repositories、agent runtime/delegation admission、C1 repository credential broker、Host API/workspace projection、restore 与验收 verifier。C2 不实现真实 C3 agent Git workspace/capsule/network/toolchain，不实现 C4 publication，不实现远程 HPC credential/CRUD、approval-free job admission 或 one-occurrence `sbatch`。C2 acceptance 必须如实声明这些 production 能力尚未证明；其后由 C3 消费 C1 repository binding 与 C2 lease/readiness seams，使 agent 恢复可运行。

在连续迁移的实现阶段，C3 可以消费 `agent_capability_lease_implementation_snapshot@1` 开始后继源码实现。该 snapshot 只绑定当时可读的 C2 source/schema/policy/interface 事实和仍待统一验收的任务，必须声明 `acceptance_proven=false`、`production_effect_authorized=false`，不能替代 `agent_capability_lease_acceptance@1`、不能证明 production readiness，也不能授权 live、外部 effect 或最终 cutover。正式 acceptance receipt 只在全部连续 change 的组合实现完成并统一运行 focused、strict OpenSpec、mainline 与最终审计后生成。
