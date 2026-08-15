## Context

当前 `Session` 只持有 `project_id`。`Lane.branch_name` 与 sandbox `cwd` 是协作元数据，不提供 canonical remote、exact base revision、Git object format、ref authority 或 LFS policy；当前 Host checkout 和 ambient cwd 也不能成为可恢复的产品依赖。后续独立 clone、immutable publication、HPC login clone 和历史数据迁移都需要先共享一个 Host 管理、版本化的项目仓库事实。

这个 change 建立 `ProjectRepositoryBinding`、session pinning 与可供标准 client 使用的 durable Git/LFS transport baseline。它不创建 agent clone、不实现 publication，也不实现后继 change 所属的 LFS threshold、quota、retention、完整 object closure 或 publish validator，并且不执行 GitHub push/PR。

## Goals / Non-Goals

**Goals:**

- 为每个 project 建立不可变、版本化的内部 Git/LFS remote、上游 origin、object format、default base revision、ref namespace 与 policy digest 绑定。
- 让 session 创建时固定 exact binding version，并在恢复期间拒绝 remote、base 或 policy 漂移。
- 明确内部协作 refs、Host-only publication refs 与外部 upstream effects 的 authority 分离。
- 由 Host 按 agent/workspace scope 签发短期 repository/LFS credentials，同时保持 Host path 与长期 secret 私有。
- 在配置缺失或不兼容时明确失败，永不使用当前 checkout、ambient cwd 或本地目录 fallback。

**Non-Goals:**

- 不 provision agent 或 HPC clone；这些由后继 workspace changes 完成。
- 不定义 `workspace.publish`、同步策略、merge 策略或 upstream push/PR 工作流。
- 不实现 Git LFS object closure、quota/GC 或大文件 publish validator；本 change 只固定相关 service identity 和 policy digest。
- 不把 repository binding、credential 或 Git ref 当作 scientific authorization、capability lease 或 execution ownership。

## Decisions

### 1. `ProjectRepositoryBinding` 是 project 下的 immutable version

新增 Host-owned `ProjectRepositoryBinding`，核心 identity 为 `binding_id + project_id + binding_version`。记录至少包含内部 collaboration remote identity 与规范 endpoint、独立的 upstream origin identity/URL、Git object format、default base ref 及其 resolved exact commit、private/publication/historical ref namespace policy、LFS service identity、repository policy version/digest、创建时间和状态。所有会改变 clone identity 或 authority 的更新都创建新 version；既有 version 不原地修改。

选择 immutable version 而不是可变 project config，是为了让 session、commit、publication、HPC job 与 migration receipt 都能复现同一 repository universe。只保存 URL 的替代方案被否决，因为它没有 base、object format、ref ACL 和 policy identity；只保存 `project_id` 更无法证明实际 clone 来源。

内部服务实现固定为 Host-owned bare repositories、Git smart HTTP v2 over HTTPS 与 Git LFS Batch API v2/basic transfer。bare repository root 与 LFS object root 都必须来自显式 durable deployment configuration，不能落到 `/tmp`、当前 checkout 或进程 cwd；两套协议共享同一 repository identity、binding version 与 bearer-token authority。采用标准协议而不是自定义 RPC，是为了让 Podman 与 HPC login 直接使用原生 `git`/`git-lfs`。

### 2. Session 在创建事务中 pin exact binding 和 base

创建 session 时，Host 必须解析一个 active binding version，把 `repository_binding_id`、`binding_version` 和 resolved default base commit 与 session 原子持久化。恢复、创建 agent workspace或解释 revision 时只读取该 pin；project 的新 active version只影响之后创建或显式迁移的 session。恢复时若配置提供的 remote、object format、base 或 policy digest 与 pin 不同，Host 直接报告 drift。

选择 session pin 而不是每次 clone 动态解析 latest，是为了避免长生命周期协作过程中无声换 remote/base。自动把现有 session 漂移到新 version 的替代方案被否决；旧 session 的迁移必须是独立、显式、有 receipt 的管理动作。

### 3. 内部协作 remote 与 upstream 是不同 authority domain

内部 remote 是 agent private refs、Host-only immutable publication refs 和 historical refs 的唯一协作服务。Host 通过 ref ACL 分配逻辑 namespace：agent 只能 create 或 fast-forward 自己 `session + agent_member + workspace_generation` 的 private namespace，不能 force-update 或 delete；publication namespace 只允许 Host create-only；historical namespace只允许迁移 owner 写入。独立 retention owner 只能在 workspace generation 已关闭、固定 retention deadline 已过且不存在 active lease、publication/migration pin、legal/audit hold 或其他 retained reference 后，先写入绑定 exact terminal ref/commit set 的不可变 retirement receipt，再整代删除 private namespace；不得改写或选择性裁剪单个 checkpoint。upstream origin 不接受这些内部 refs，任何 upstream push、branch、PR 或 release 都是另一个显式 controlled external effect。

选择独立 internal remote，而不是让 agents 直接共用 GitHub origin，是为了隔离私有工作、publication 原子性与外部副作用。把当前 EnzymeDesign checkout 暴露成 remote 或共享 `.git` 被否决，因为它泄露 Host 状态且无法提供 ref ACL。

### 4. Binding 保存服务 identity，credential 按 scope 临时派生

Host repository service 持有 Git/LFS service identity 和长期凭据。agent-facing clone context只接收与 active `AgentCapabilityLease`、binding、agent 和 workspace generation 绑定的短期 credential，以及执行所需的 canonical remote endpoint；公开 projection只显示 binding/version、object format、safe remote identity、base commit、policy digest 和允许的 ref classes。credential 续发不改变 binding version，失败的 Git 命令不会因此被自动重试。

选择短期 scoped credential 而不是在 binding 或 volume 中保存 token，是为了在不改变 session repository identity 的情况下撤销 agent authority。把 Host home、SSH directory 或 credential file mount 进 capsule 的替代方案被否决。

### 5. 缺失或不兼容 binding 是显式产品阻塞

不存在 active binding、default base commit 无法在内部 remote 解析、object format 不受支持、policy digest 不匹配或 session pin 不可重读时，session 创建/恢复与下游 provisioning 必须停止并返回稳定错误。不得探测当前 checkout、ambient `origin`、cwd、临时 bare repository或任意本地路径作为替代。

选择 fail closed 是因为 fallback 会生成不可复现且可能指向错误项目的 revisions。自动初始化空仓库或猜测默认 branch 的方案被否决。

## Risks / Trade-offs

- [binding version 增长带来配置和迁移负担] → 只在 authority-relevant 字段变化时创建新 version，并提供 project/version 唯一约束和按引用保留。
- [内部 remote 与 upstream 双 remote 增加运维复杂度] → 使用明确 service identity、ref ACL 和健康检查；两者不得共享写权限或 fallback 顺序。
- [base ref 后续移动造成误解] → binding 同时保存人类可读 ref 和创建时 resolved exact commit，所有 identity 计算使用 commit。
- [credential rotation 与长命令冲突] → credential 生命周期独立记录；到期返回明确认证失败，可重新签发 credential，但不自动重放已失败命令。
- [existing session 没有 pin] → 通过显式 migration mapping 处理；无法证明 exact remote/base/policy 的 session 保持 blocked，而不是从 ambient state 推断。

## Migration Plan

1. 新增 binding/version 持久化、project active-version 指针和 session pin 字段，保持所有 authority 字段不可变。
2. 由部署配置显式登记每个 project 的 internal Git/LFS service、upstream、object format、ref namespaces、exact default base 与 policy digest；执行连通性和 exact commit 只读验证。
3. 切换新 session 创建，使 binding resolution 与 session insert 原子完成；缺 binding 的创建直接失败。
4. 为既有 session 提供一次显式 mapping/import：操作者必须给出 exact binding version 和 base commit并生成 receipt；无法闭合的 session 标记 `repository_binding_required`，不 provision 新 workspace。
5. 后继 clone、publication、LFS、HPC 和 historical migration changes 只消费 session pin，不读取 project latest 或 ambient Git state。
6. 回滚时先停用尚未消费的新 active version并回滚下游 readers；已经被 session、revision 或 receipt 引用的 binding rows 与 internal refs必须保留，不得改写或删除。

## Open Questions

无。内部 remote、session pinning、ref authority、credential 边界和 fail-closed 行为均已裁决。
