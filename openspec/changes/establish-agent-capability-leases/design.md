## Context

现有 `SessionRuntimeLease` 只协调 bounded agent turn，`ControlledOperationExecution` lease/fence 只拥有 durable external effect，mutation writer 只保护 canonical writes。它们都不能表达产品需要的长期 capsule 能力：agent 在一次授予后，应能在自己的 workspace generation 中反复使用 filesystem、shell、Git、Git LFS、network 和传输工具，而不对每条命令重新请求 approval；executor 还需要独立的 HPC 登录与 Slurm 能力。

本设计新增正交的 `AgentCapabilityLease`。它是 agent/capsule 生命周期的能力授予，不是 scheduler claim、canonical mutation fence、scientific authorization、publication intent 或 external-operation ownership。

## Goals / Non-Goals

**Goals:**

- 把一次性能力授予绑定到 `session + agent_member + workspace_generation`，并在该 generation 生命周期内复用。
- 给一般 agent 提供原生 filesystem、shell、Git/LFS、network、upload/download 能力，scope 内不逐命令 approval。
- 给 executor 额外提供 scoped SSH、rsync/scp、HPC login workspace CRUD 与 Slurm operation capability，而不扩散 HPC credential。
- delegation 为每个 subagent 建立独立 derived lease，既不共享 parent token，也不共享 workspace。
- 在 revoke 或 lifecycle 终止时立即停止新能力使用，并对错误显式失败，不做 fallback 或自动重试。

**Non-Goals:**

- 不替代 session runtime lease、execution lease/fence、mutation authority、scientific attempt authorization、budget gate 或 explicit publication intent。
- 不定义 agent clone、HPC remote workspace、job state machine、Git publication 或 Git LFS storage 的具体实现。
- 不为一般角色授予 HPC login 或 Slurm credential，也不允许 capability profile 隐式升级。
- 不保证任意外部 endpoint 成功，不缓存或投影长期 credential。

## Decisions

### 1. Lease identity 精确绑定 workspace generation

`AgentCapabilityLease` 至少包含 `lease_id`、session、agent member、workspace generation、closed capability set/profile、derived-from lease identity（如适用）、issued/revoked facts、policy digest 和状态。对同一有效 identity/profile 的 issuance 使用稳定幂等 key，只能得到一个 canonical active lease；workspace generation 替换必须结束旧 lease 并为新 generation 建立新 lease。

选择 generation-bound lease，而不是 session-wide token，是为了防止 workspace 被替换后旧 credential 继续写入错误 volume/ref namespace。复用 `SessionRuntimeLease` 被否决，因为 turn claim 会频繁释放且不应控制 agent 的持久文件权限；复用 execution lease 被否决，因为文件编辑和外部 operation ownership 的生命周期不同。

### 2. 生命周期由 closed canonical facts 终止，而非逐命令 TTL

lease 从显式授予开始持续有效，直到 session 结束、agent retirement、workspace generation 被替换或显式 revoke。短期 Git/SSH/network credentials可以在 active lease 下重新签发，但 credential TTL 不结束 capability lease。每次开启 capsule、注入 credential 或调用 Host-supervised capability 时都重读 lease identity/status；已经 revoke 的 lease 不恢复或降级。

选择生命周期 lease 配合短期 credential，是为了同时减少 approval 摩擦和支持 secret rotation。为每条命令创建 approval/lease 的方案被否决；把长期 secret 固化进 volume 的方案也被否决。

### 3. 一般 profile 与 executor profile 是闭合集合

一般 profile 固定包含 workspace filesystem read/write、shell process、Git、Git LFS、ordinary network access、upload 和 download。ordinary network 不经过 Host destination allowlist：agent 可以访问 deployment 网络实际可达的 endpoint；只有需要 Host-issued credential 的 Git/HPC service 按 credential audience 限定。executor profile 是明确的 superseding set，额外包含 scoped SSH、rsync/scp、其 own HPC login workspace CRUD 和 Slurm operations。角色、target 和 policy 必须在 issuance 时解析并写入 lease；不存在“能力缺失时尝试 executor profile”的 fallback。

原生 upload/download 和私有文件操作在 lease scope 内直接执行且不形成 team shared truth。Slurm submission 不再次请求逐命令或逐 job 人工 approval；submission admission 自动创建 canonical controlled-operation execution，由 execution lease/fence 拥有 exact dispatch/handle/reconciliation。executor 的普通 SSH/file credential 不携带可绕过该路径的 ambient scheduler submission authority；qualified target 只允许 runner 以冻结 dispatch identity 和 one-occurrence credential 调用原生 `sbatch`，并拒绝未登记的直接 submission。只有某个上层 scientific workflow 已经明确要求 scientific authorization 时才额外验证该独立 authority，一般 HPC job 不因使用 Slurm 自动获得这项要求。

选择 closed profiles 而不是自由字符串 scopes，是为了可审计、可投影且防止隐式提权。让任意 network-capable role 获得 HPC credential 的替代方案被否决。

### 4. Delegation 派生 identity，不传递 bearer authority

canonical delegation 创建 subagent identity后，Host 为其独立 workspace generation provision 流程登记一个 derived lease。记录可以引用 parent lease用于 provenance和“不超过允许 profile”的校验，但 child 使用不同 lease id、credential audience、private ref namespace和 volume。subagent 只有在自己的 workspace 与 lease 均 ready 后才能运行；失败保持明确 provisioning blocker，不回退到 parent capsule。

选择派生新 lease，而不是把 parent token 注入 child，是为了保持 least privilege、撤销隔离和 Git ownership。让多个 agent 共用 workspace或 credential 被否决。

### 5. 四类 authority 始终正交

每个 Host boundary 都要分别检查它实际需要的 authority：capsule 文件/网络访问检查 capability lease；bounded agent turn 检查 session runtime lease；durable publication/job dispatch 检查 controlled-operation execution owner及其 fence；scientific/admission动作检查 exact scientific authorization；`workspace.publish` 还检查冻结 publication intent。任何一项存在都不能合成或推断另一项。

选择组合检查而不是建立“万能 agent lease”，是为了保留当前可靠性和科学治理边界。把 capability lease 作为 canonical mutation token、publication approval 或 job handle 的替代方案被否决。

### 6. 失败直接返回，不修改 intent 或重放命令

lease 缺失、已 revoke、identity/generation/profile/target/policy 不匹配、credential issuance 失败或 endpoint 拒绝时，当前动作直接返回稳定错误并停止。Host 不切换 endpoint、不隐式降权、不自动重开 approval、不把 executor 命令改成本地命令，也不自动重试失败的 upload/download/Git/SSH/Slurm 动作。

credential 可在下一次显式命令前按同一 active lease重新签发；这不是对已失败命令的 replay。该边界让 agent 保留依据事实自行修正、求助或终止 task 的策略自由。

## Risks / Trade-offs

- [长生命周期授权扩大凭据泄露窗口] → lease 本身不含 bearer secret；使用短期、audience-bound credential并在 revoke/retirement 时停止续发和撤销可撤销凭据。
- [native network/transfer 绕过 artifact catalog 后可观测性降低] → 保留 capsule audit facts和明确 owner identity，但不把普通 bytes 提升为 control-plane truth；shared truth只由 publication 建立。
- [executor profile 误配会放大 HPC 权限] → role/target/policy digest 在 issuance 时闭合，projection显示 capability names但不显示 credential，任何 drift fail closed。
- [delegation 需要异步 workspace provisioning] → subagent 保持 non-runnable provisioning state，直到独立 workspace和lease都 ready；不借用 parent 环境继续。
- [credential rotation 导致命令中途失败] → 直接呈现认证错误；允许后续显式动作获取新 credential，但绝不自动 replay effectful command。

## Migration Plan

1. 新增 lease domain、closed capability/profile enums、repository、lifecycle events、唯一约束和安全 projection；不修改现有三类 lease/fence。
2. 在 agent creation/delegation 路径登记 workspace-generation-bound issuance intent；在独立 workspace ready 后原子激活对应 lease。
3. 将 capsule tool exposure、network policy和credential broker切换为只消费 active capability lease；移除逐命令 approval依赖，但保留 publication/scientific/execution的独立 gate。
4. 为 executor 接入 target-scoped SSH/HPC profile，并证明一般角色无法获得该 credential；Slurm dispatch继续使用 canonical `ControlledOperationExecution`。
5. 对已有 agent，只在其 session已有 verified repository binding且建立新 workspace generation后签发 lease；不得把旧 sandbox process或runtime lease推断成 capability grant。
6. 回滚时停止新 lease issuance并撤销未消费 credentials；已持久化 lease/events保留为审计记录，不能恢复逐命令动作或 replay失败命令。

## Open Questions

无。lease identity、能力集合、派生、终止、authority 正交和错误语义均已裁决。
