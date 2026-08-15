## 1. C2 前置 receipt 与 authority-separation gate

- [ ] 1.1 验证 immutable `aox_artifact_cutover_supersession_acceptance@1` receipt、source revision和legacy NO-GO；缺失或漂移时停止C2，且不得借C2启动任何AOX live工作。
- [ ] 1.2 记录现有 `SessionRuntimeLease`、`ControlledOperationExecution` lease/fence、mutation writer、approval与scientific authorization的owner/lifecycle基线，生成不得复用或互相推断的authority matrix receipt。
- [ ] 1.3 冻结closed general/executor capability profiles与policy digest：general包含filesystem、shell、Git/LFS、ordinary network、upload/download；executor额外包含scoped SSH、rsync/scp、HPC login CRUD和Slurm operations。
- [ ] 1.4 记录C2可与C1并行的gate：C2只定义generation-bound lease与admission seams，不建立clone；C3必须等待C1和C2两个acceptance receipts。

## 2. Lease domain、migration 与 lifecycle service

- [ ] 2.1 在 `openzyme-domain` 增加closed capability/profile/status/revocation enums与`AgentCapabilityLease`，绑定lease id、session、agent、workspace generation、profile/set、policy digest、derived-from provenance及issued/revoked lifecycle facts。
- [ ] 2.2 添加单一forward SQL migration和repository，建立exact identity/profile幂等唯一约束、active lookup、append-only lifecycle events与parent/child provenance constraints。
- [ ] 2.3 实现一次性issuance service：同一exact identity/profile重复调用只返回同一canonical active lease，任何generation/profile/policy drift都拒绝而不另发替代lease。
- [ ] 2.4 实现session end、agent retirement、workspace generation replacement与explicit revoke transitions，并确保终止后不再签发或接受新credential/capsule action。
- [ ] 2.5 实现active-lease validation seam，供capsule activation、credential broker、Git/HPC service和Host-supervised operations精确校验identity/status，不从runtime lease、process id或ambient config推断。
- [ ] 2.6 为domain/repository/issuance/revoke/idempotency/generation rollover增加focused tests，覆盖stale lease、duplicate active lease与cross-agent identity rejection。

## 3. Capsule general profile、network 与 credentials

- [ ] 3.1 将capsule filesystem/shell/Git/LFS/ordinary network/upload/download tool exposure改为消费active general lease，scope内命令不创建逐命令approval。
- [ ] 3.2 配置capsule ordinary network，使agent可访问deployment网络实际reachable的endpoint，并移除Host destination allowlist检查；仅Host-issued service credential继续按audience/scope限制。
- [ ] 3.3 增加network negative tests，证明unreachable endpoint返回原始明确失败，而reachable ordinary endpoint不因destination缺少Host allowlist而被拒绝或切换endpoint。
- [ ] 3.4 实现process-scoped credential broker，按lease、agent、generation、service/target/protocol签发短期credentials，并禁止写入public projection、persistent workspace、repo config或Host-home mount。
- [ ] 3.5 实现credential到期/拒绝后的显式错误与下一次显式动作重新签发，证明不会auto retry、replay、fallback endpoint、隐式降权或重开approval。
- [ ] 3.6 增加general-profile tests，覆盖跨turn复用同一lease、自由upload/download、private bytes不成为team/scientific truth、revoke后立即拒绝和无per-command approval。

## 4. Executor、Slurm 与 delegation 派生

- [ ] 4.1 实现executor profile解析与target-scoped SSH/rsync/scp/HPC login CRUD credential issuance，证明general role即使拥有shell/network也无法获得HPC credential。
- [ ] 4.2 将普通非scientific Slurm job admission改为：active executor lease验证通过后自动创建唯一canonical `ControlledOperationExecution`，不请求逐命令或逐job human approval。
- [ ] 4.3 保持Slurm execution lease/fence、dispatch intent、handle与reconciliation为独立owner facts，并证明capability lease不能直接提交未canonical化job或写execution状态。
- [ ] 4.4 将普通 executor login/file credential 与 scheduler submit authority 分离：只有 runner 为 frozen dispatch identity 签发的 one-occurrence credential 可调用原生 `sbatch`，target 必须在 scheduler acceptance 前拒绝 ambient login credential 或未登记 dispatch 的 submission，且 Host 不得事后扫描并采纳绕过路径的 job。
- [ ] 4.5 在仅当enclosing scientific workflow已声明时额外验证exact scientific authorization；普通job不得因使用Slurm被隐式升级为scientific attempt或approval-required job。
- [ ] 4.6 实现canonical delegation issuance intent：child agent建立后登记derived lease provenance，并在其own workspace generation ready后激活独立lease id/audience/private namespace。
- [ ] 4.7 为child provisioning failure保留non-runnable blocker，禁止共享parent token、workspace、credential或退回parent capsule执行。
- [ ] 4.8 增加executor/delegation focused tests，覆盖普通job无human approval、automatic execution ownership、ambient/unregistered Slurm submit rejection、one-occurrence runner credential、scientific authorization有/无、target drift、role escalation、child isolation与parent revoke边界。

## 5. Projection、恢复与 authority 正交

- [ ] 5.1 增加safe Host API/workspace projection，只公开lease id、owner identity、workspace generation、closed capabilities、policy digest、lifecycle/revocation facts，隐藏bearer credentials和private service locators。
- [ ] 5.2 在session/runtime restore中重读canonical active lease而非复制旧turn/process authority，并对legacy agent缺lease返回明确provisioning requirement。
- [ ] 5.3 为existing agents定义显式迁移：只有verified session identity和workspace generation可获得新lease；不得把旧sandbox process、runtime lease或现有tool exposure解释成已授予能力。
- [ ] 5.4 增加authority cross-product tests，逐项证明capability lease不替代runtime claim、mutation writer、execution fence、publication intent、budget或scientific authorization，反向也不成立。
- [ ] 5.5 增加failure-path tests，覆盖missing/revoked/mismatched lease、credential issuance failure、endpoint rejection和policy drift，并证明无silent retry、route fallback、local substitution或automatic task transition。

## 6. Focused tests、文档与 C2 验收 receipt

- [ ] 6.1 运行domain/core/engine/Host focused tests，覆盖一次性lifecycle lease、跨turn reuse、reachable capsule network无Host destination allowlist、credential isolation、delegation与普通Slurm job无逐job approval。
- [ ] 6.2 更新 `docs/OpenZyme架构设计.md`、`docs/v3/02-control-plane.md`、`docs/v3/03-capability-engines.md`、`docs/v3/05-agent-runtime.md` 与execution/HPC相关稳定文档，记录capability lease与其他authority的正交关系及network/job裁决。
- [ ] 6.3 运行 `DO_NOT_TRACK=1 openspec validate establish-agent-capability-leases --type change --strict --no-interactive` 并保存通过结果。
- [ ] 6.4 运行 `./scripts/check-mainline.sh`，确认无live/provider/HPC opt-in，且不得用临时allowlist、manual approval或fallback route掩盖失败。
- [ ] 6.5 审计Git diff、migration、credential/redaction、approval call sites和tool exposure，确认未提前实现C3 clone或C4 publication，也未弱化existing execution/scientific fences。
- [ ] 6.6 生成 immutable `agent_capability_lease_acceptance@1` change receipt，绑定C0 receipt、authority matrix、code/schema/policy digests、focused tests、docs、strict OpenSpec、mainline与`eligible_successor = C3 when C1 receipt also passes`。
