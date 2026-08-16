## Context

当前 sandbox 同时暴露 `sandbox.file.*`、`artifact.*`、`artifacts.materialize/register/snapshot_code` 与 `hpc.stage_artifact`，普通文件因此被迫经历 workspace、catalog、materialization 和 HPC stage 多套身份。独立 agent Git clone、repository binding、capability lease 和 explicit publication 建立后，clone 内的普通文件、目录、Git revision 与原生命令足以构成工作面；artifact/catalog/stage 不再是 agent 或 execution 的通用边界。

目标 capsule 以 `session + agent_member + workspace_generation` 的独立 clone 为持久根。agent 在有效 `AgentCapabilityLease` 内直接使用 shell、filesystem、Git、Git LFS、network 和 transfer tools，不逐命令经过 Host gateway。Host typed context 继续承载 approval、publication、controlled external job、continuation 与其他 canonical control-plane effect，因为这些行为需要独立 owner、lease/fence、receipt 与 projection。

## Goals / Non-Goals

**Goals:**

- 让 agent 直接在自己的 clone 中以普通 OS 文件、目录、原生 shell 和 Git 工作。
- 删除 model/SDK-facing artifact、materialize/register/snapshot、`sandbox.file.*` 与 `hpc.stage_artifact` authoring surface。
- 将 execution source 绑定到 clean private 或 published Git revision，而不是 source snapshot artifact。
- 将 sandbox-to-Host typed gateway 收缩为 closed control-plane effects，普通文件和网络 I/O 不再由 Host 代理。
- 对 OS、Git、network、SSH 与 runner 错误 fail closed，不猜路径、不改参数、不切换 endpoint 或旧接口。

**Non-Goals:**

- 不删除 artifact 数据库与历史 bytes；物理删除属于后续 `remove-artifact-control-plane-and-storage`。
- 不迁移 research/report/scientific 内容引用；这些必须由前置 writer-migration changes 完成，本 change 只在其完成后切断残余通用 artifact/sandbox surface。
- 不定义 `PublishedRevision`、repository binding 或 capability lease 本身。
- 不自动 commit、push、publish、merge、完成 task 或运行 recipient。
- 不保留 Host typed transfer gateway、artifact compatibility authoring、`HpcStageRef` 或 expected-output 文件代理作为 current fallback。

## Decisions

### 1. Clone 是唯一普通文件工作面

每个 sandbox process 把该 agent generation 的独立完整 clone 挂载为工作目录。所有普通文件 CRUD、目录遍历、临时文件、chmod、archive、diff 与 local Git 操作由 OS 和原生命令完成；Host 不为这些动作创建 catalog row、file RPC 或 mutation writer。

clone 外只允许运行环境明确声明的临时目录和只读 runtime assets。Host checkout、Host home、Host `.ssh`、共享 `.git`、linked worktree 和 ambient cwd 不得挂入 capsule。

备选的 `sandbox.file.*` wrapper 无法覆盖 shell/tool 自身的全部文件行为，并继续制造双重语义，故删除而非保留。

### 2. Capability lease 在 capsule 启动时授予原生能力

Sandbox launch 必须绑定 exact `AgentCapabilityLease`、agent、session 和 workspace generation。lease scope 决定 capsule 获得的 filesystem、shell、Git、Git LFS、network、upload/download，以及 executor 专属 SSH/rsync/scp/HPC credential。scope 内原生命令不重复请求 approval，也不为每次 transfer 调用 Host。

lease 失效、generation 漂移或 role 不包含所需能力时，新的 process/admission 直接失败；系统不改用 Host proxy、另一个 credential、另一个 endpoint 或受限替代命令。运行中外部 effect 的事实仍由其所属 external-job/publication 合同结算，不能用 lease expiry 推断取消。

备选的 command-by-command allowlist/approval 会重新引入已裁决移除的交互摩擦，因此不采用。

### 3. 普通网络与 transfer 不经过 typed Host gateway

具备 network/upload/download scope 的 capsule 获得直接网络路径，并使用原生 Git/LFS、curl、SSH、scp、rsync 等工具。普通 transfer 只改变私有 filesystem/remote state；Host 不持久化逐命令 intent、bytes receipt 或 artifact alias，也不将传输成功升级成 commit、publication 或 task evidence。

网络策略、DNS、credential issuance 和撤销由 capability lease/deployment 管理，但数据面不回流为 Host 文件 API。备选的 typed transfer gateway 被明确删除。

### 4. Typed gateway 只承载 canonical control-plane effects

`SandboxHostGateway` 保留 closed、版本化操作集，例如 approval resolution/request、`workspace.publish` admission、controlled external-job creation/inspection、continuation settlement、protocol/task canonical mutation与 bounded runtime inspection。每次调用仍携带 exact `SandboxHostCallContext`，并分别校验 owner authority 与 mutation writer。

gateway 不提供 file read/write/list、artifact get/register/materialize、source snapshot、network fetch/upload、Git transport、SSH/rsync/scp、HPC staging 或 output fetch。未知操作和 stale schema 直接拒绝。

完全删除 gateway 会迫使 canonical effects 依赖 shell side effects，破坏 authority/fencing；保留全能 gateway 又会延续 artifact/transfer 代理，因此采用收缩后的 control-plane-only boundary。

### 5. Revision-bound effect 只接受 clean committed source

普通探索允许 dirty、modified 和 untracked files，并在 projection 中直接呈现 Git status。publication 或从 private workspace 发起的 external execution admission 必须绑定 exact repository binding、workspace generation、commit/tree 与 normalized repository-relative cwd/path，并证明工作树、index、submodule/LFS policy状态满足该 effect 的 clean contract。handoff 只能引用既有 immutable `PublishedRevision`/path，因此只验证该 publication identity，不读取 producer 当前 working tree。

不从 mutable path 现场复制出“等价 snapshot”，也不自动 stash、commit、clean 或选择 HEAD 之外的 revision。private commit 与 published commit 都可作为允许的 source class，具体 effect policy 决定是否要求 publication。

### 6. Artifact authoring 与 `HpcStageRef` 一次性切断

本 change 的 current tool catalog、SDK、prompt 与 engine adapter 不再注册或调用 `artifact.*`、`artifacts.*`、`sandbox.file.*`、`hpc.stage_artifact`。`source_snapshot_artifact_id`、catalog ref 与 `HpcStageRef` 不得进入新 execution identity。历史 reader 可在后续迁移工具中读取旧 rows，但 current runtime 不根据缺失新字段退回旧合同。

### 7. 原生命令失败保持原操作语义

Sandbox process 返回真实 exit status 和该进程可见的 stdout/stderr。Host 不捕获宽泛异常后伪造成功，不猜测路径或文件类型，不自动创建目录/替代输入，不切换工具、endpoint、credential、execution mode 或 backend。canonical control-plane surface 仍按既有安全规则限制公开诊断，但不得把失败重分类为已完成。

## Risks / Trade-offs

- [原生 shell/network 扩大 capsule 行为面] → 以独立 clone、container/user namespace、capability lease、role-scoped credential 和 network policy隔离；不通过重新引入逐命令 Host proxy 缓解。
- [dirty workspace 被误用于正式 effect] → publication 和从 private workspace 发起的 execution admission 验证 exact generation/revision/clean status；既有 immutable publication 的 handoff 只验证 publication/path，失败时均不自动 stash 或 snapshot。
- [移除 artifact/file tools 使旧 prompt/SDK 立即失效] → 以一次性 schema/tool-catalog cutover 同步所有 current consumers，stale client 返回明确 unsupported schema；不维持双 authoring surface。
- [原生命令输出可能很大或含敏感信息] → capsule 内部直接输出遵循 process budget；进入公共 control-plane record 的诊断仍做 bounded redaction，原始 transfer 不自动进入公共 record。
- [Host control gateway 收缩过度导致 canonical mutation 被 shell 绕过] → control-plane resources 继续只由 repository/service 写入，clone 文件或 native remote side effect不能直接修改 task、approval、publication、execution 或 report 状态。

## Migration Plan

1. 先完成 repository binding、capability lease、独立 clone、Git LFS 与 explicit publication，并证明每个 agent generation 可恢复且 `.git` 互不共享。
2. 验证 research/report/task handoff、executor HPC workspace、workspace-revision job 和 scientific deliverable changes 已迁移全部 current writers；枚举 current tool catalog、SDK、prompt、engine、Host callback 与 schema 中剩余的 `artifact.*`、`artifacts.*`、`sandbox.file.*`、source snapshot 和 `hpc.stage_artifact` consumer，为每一项确认已存在的 file/revision/control-plane owner。任何仍在写旧合同的 consumer 都阻止本 change 开始切断。
3. 将 sandbox image 和 launch contract 切换为 clone cwd、原生 toolchain 与 lease-scoped direct network；验证普通 transfer 不经过 Host gateway且不会创建 canonical work-product row。
4. 将 `SandboxHostGateway` 收缩为 closed control-plane operations，删除 artifact publisher/stage/fetch callback 与对应 mutation scope；durable external-job adapter继续使用 exact execution context。
5. 验证前序 execution change 已把 source identity 和调用参数切到 repository binding、workspace generation、commit/tree、cwd/path；任何仍提交 artifact id、`HpcStageRef` 或 `expected_outputs` 的 current caller 均使 cutover gate 失败，而不是由本 change 猜测转换。
6. 在 disabled `file_workspace_public@1` fixture 下删除 backend tool/SDK registrations、compatibility authoring 与 prompt/schema 实现，并生成供 `cut-over-workspace-public-interfaces` 消费的 exact catalog/schema digest；本 change 不单独激活 Host/CLI/UI public epoch，也不保留双 writer或缺字段读取旧 artifact path。
7. 运行 clean/dirty、native network、credential scope、stale generation、control-plane fencing、unknown tool、error propagation 与 no-fallback 验收；生成 internal boundary readiness receipt，证明旧 artifact writers 已冻结且 public cutover 可以原子消费，但不把未切换的 public clients宣称为已迁移。
8. public activation 前可回退尚未启用的 internal implementation；一旦后继 public cutover 激活，只能前向修复，不能在新 runtime 内动态回退到 artifact、materialize、stage 或 Host transfer gateway。已产生的 Git revisions必须保留供前向恢复。

## Open Questions

无未决产品问题。具体 container network implementation、tool versions 与 credential provider 是 deployment qualification 项，必须在启用对应 lease scope 前通过，失败即阻止 rollout。
> **连续源码 gate：** `file_workspace_source_only_deletion_gate@1` 绑定三个直接
> 前序 source gate 和当前残余 surface inventory。正式 deletion admission、内部
> activation-ready receipt 与 public cutover 均继续封闭，直到 14 项源码完成后的
> 统一非 live 验收重建精确证据。
