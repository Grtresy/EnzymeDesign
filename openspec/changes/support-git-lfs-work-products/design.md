## Context

独立 agent clone 和显式 `workspace.publish` 把普通文件真相绑定到 Git revision，但研究数据、模型和 HPC 结果可能不适合作为普通 Git blob。该 change 在 Host-managed internal remote 上增加标准 Git LFS 服务，使大文件仍由 Git commit 中的标准 pointer 定位，同时由 publication validator 证明 pointer、OID、size 与实际 bytes 的闭包完整性。

本设计以 `ProjectRepositoryBinding` 固定的 remote、object format、LFS endpoint 与 binding policy 为前置，也依赖 `PublishedRevision` 的冻结 publication intent 和不可变 publication ref。Podman capsule 与 HPC login workspace 使用原生 `git`/`git-lfs`；compute tree 只接收已经解析并验证的文件 bytes，不安装 Git、Git LFS 或 credential。任意 `curl`、`scp`、`rsync` 等传输只改变私有 workspace，不自动形成共享真相。

## Goals / Non-Goals

**Goals:**

- 通过标准 Git LFS protocol 管理正式 revision 中的大文件，并保持普通 Git client 互操作。
- 将 LFS patterns、普通 blob threshold、quota、retention 与 publication 完整性规则纳入版本化 repository policy。
- 在创建 `PublishedRevision` 前证明 commit 的完整 Git/LFS object closure 可读且逐字节一致。
- 使 published LFS objects 不受普通 scratch/private GC 影响，同时为私有对象提供明确的生命周期。
- 保持原生 Git/LFS 与任意网络传输，不增加 agent-facing CAS、artifact catalog 或 Host typed transfer gateway。

**Non-Goals:**

- 不把任意上传、下载或 private ref push 解释为 publication。
- 不自动编辑 `.gitattributes`、重写 commit、把 oversized blob 转成 LFS pointer，或为错误 commit 创建替代 publication。
- 不在 compute node 安装 Git/LFS、注入 repository credential 或直接访问 internal remote。
- 不迁移历史 artifact bytes；历史迁移由 `migrate-historical-artifacts-to-git-lfs` 负责。
- 不定义 external upstream push、GitHub PR 或公共对象分发。

## Decisions

### 1. 仅暴露标准 Git LFS，不建立通用 CAS 产品面

Internal remote 提供标准 Git LFS Batch API、basic transfer 和 `oid sha256` 语义。底层可以使用对象存储实现，但其 locator、bucket 与内部去重结构不进入 agent、Git pointer、publication 或 control-plane contract。agent 只通过原生 `git-lfs` 与 repository endpoint 工作。

选择该方案是为了保留 Git 生态互操作和单一 revision identity。备选的 agent-facing CAS 会重新形成与 Git 并列的文件真相；自定义 Git pointer 则要求所有客户端理解私有协议，均不采用。

### 2. LFS policy 是 repository binding 的版本化组成

每个 binding version 固定：允许或要求使用 LFS 的 path patterns、普通 Git blob 最大尺寸、单对象与 workspace/repository quota、LFS endpoint identity、published/private retention class，以及 policy digest。session 和 publication intent 使用固定 binding version，不读取漂移的全局默认值。

`.gitattributes` 仍由 agent 在 repository 中显式维护。发布校验同时检查 commit 中实际 attributes 与 binding policy；不符合时返回具体 path、observed representation、size 与 policy rule，并停止 publication。

备选的 server-global threshold 无法重放历史 publication，也无法解释不同项目策略，因此不采用。

### 3. Podman 与 HPC login 使用原生 Git LFS，compute 保持 Gitless

具备有效 `AgentCapabilityLease` 的 Podman capsule 和 executor HPC login workspace 安装原生 Git LFS，并使用其 scope 内的短期 repository credential。clone、fetch、checkout、push private ref 和 LFS transfer 走标准 client/protocol，不经 Host 文件代理。

HPC 作业启动前由 login side 从 exact revision 解析 LFS closure，再将不含 `.git`、LFS binary 或 credential 的普通文件树交给 compute。备选的 compute-side LFS fetch 会扩大 credential 与网络边界，故不采用。

### 4. Publication validator 对完整 closure 做 fail-closed 验证

冻结 publication intent 后，validator 遍历 exact commit tree，按该 revision 的 `.gitattributes` 和标准 pointer grammar 分类每个文件。每个 LFS pointer 必须是规范格式，OID algorithm 必须受 policy 允许，声明 size 必须与实际对象长度一致，实际 bytes 的 SHA-256 必须等于 OID，并且对象必须从 intent 固定的 LFS endpoint 完整读取。

validator 生成排序且无重复的 LFS closure manifest，绑定 path、mode、pointer blob OID、LFS OID 和 size；manifest digest 进入 publication identity。任一对象缺失、损坏、无权读取或 policy 漂移都会使同一 intent 失败，系统不创建 `PublishedRevision`、不移动其他 ref，也不替换对象来源。

只检查 pointer 文本或相信 upload response 无法证明发布可读性，因此不采用。

### 5. Oversized 普通 blob 只拒绝，不改写

validator 对 commit tree 中非 LFS 文件使用 repository policy threshold。超过阈值时，错误返回所有违规 path、blob OID、实际 size 与适用 rule，要求 agent 自行更新 `.gitattributes`、重新 add/commit 后发起新的 publication intent。

自动重写 commit 会改变 agent 审阅过的历史并模糊 publisher authority，因此不采用。

### 6. Retention 由不可变引用闭包决定

成功 `PublishedRevision` 固定其 Git objects 与 LFS closure；只要 revision 可引用，对应 LFS objects 就不得被 GC。private refs、未发布 commits、进行中的 workspace generation 与 upload session 使用 binding policy 中的 private retention。deadline 到期本身不能裁剪 checkpoint：retention owner 必须先按 repository binding 合同验证整代 workspace generation 已关闭且无 lease/pin/hold，写入 exact terminal-ref/commit retirement receipt，再整代删除 private namespace。GC 随后重新计算 Git ref 与 publication pin 的可达闭包，只删除超期且已经不可达的对象。

相同 OID 可以物理去重，但授权、retention 和 publication adoption 仍按 repository/binding/ref 计算；digest 相等不授予跨项目读取权限。

### 7. 原生 transfer 与共享真相正交

agent 可以在 capability lease scope 内直接使用 `curl`、`scp`、`rsync`、Git 与 Git LFS 上传下载。新 bytes 只存在于其私有 workspace、private ref 或 LFS upload session，直到 agent 创建 clean commit 并成功执行显式 `workspace.publish`。Host 不为普通 transfer 创建 artifact record、publication 或逐命令 approval。

## Risks / Trade-offs

- [LFS object 已上传但 publication 失败，形成暂时不可达对象] → 以 upload-session/private retention 保留有限时间，GC 仅删除已证明不被 ref 或 publication pin 引用的对象。
- [LFS server 与 Git ref/Host DB 不存在跨系统 ACID] → 使用冻结 intent、不可变 publication ref、closure manifest 与 exact reconciliation；响应丢失进入 `publish_in_doubt`，不创建替代 ref。
- [大 repository 的 closure 验证成本高] → 按 commit/tree/policy digest 缓存已验证 manifest，但 cache hit 仍须确认 endpoint identity、授权与 object 可读性，cache 不是 publication proof 的替代品。
- [agent 误把大文件作为普通 blob 提交] → publication 返回完整可操作诊断；不自动修改其 repository。
- [私有原生传输增加容量消耗] → 在 binding policy 与 capability lease 上实施明确 quota；超限直接失败，不降级成普通 blob 或外部 endpoint。
- [底层对象去重导致跨项目数据泄露] → authorization 以 repository/binding principal 判断，OID 存在性和 physical locator 均不对未授权 agent 暴露。

## Migration Plan

1. 先完成 `ProjectRepositoryBinding`、独立 agent clone、`AgentCapabilityLease` 与 `workspace.publish` 的 identity/ref ACL；没有固定 binding version 的 session 不进入本 change。
2. 为每个目标 binding 部署并资格验证标准 Git LFS endpoint、authentication、OID/size round trip、quota、retention 与 authoritative object read；资格不通过则阻止该 binding 启用 LFS。
3. 发布新 binding policy version，安装 Podman/HPC login 的 Git LFS client，并验证 clone、fetch、private push 与 credential revocation；compute image 保持无 Git/LFS。
4. 上线 publication closure validator、oversized blob rejection、immutable manifest 与 pin accounting；在测试 repository 验证 missing object、wrong size、wrong OID、policy drift 和 response-loss reconciliation。
5. 只在上述 gate 全部通过后允许新 `PublishedRevision` 引用 LFS。历史 artifact 和既有 publication 不在此步骤隐式迁移。
6. 启用 reachability-based GC，并先以只报告模式核对 publication pins；随后切换为删除超期不可达 private objects。
7. 回滚仅允许回退新的 publication admission；任何已被 `PublishedRevision` 引用的 Git/LFS 服务、objects、manifests 与 readers 必须继续保留。系统不得通过普通 blob、CAS 或旧 artifact path 读取这些 revision。

## Open Questions

无未决产品问题。LFS endpoint、quota 数值、retention 时长与集群 client 版本是 deployment binding 的显式配置和资格 gate，不允许在运行时猜测或 fallback。
