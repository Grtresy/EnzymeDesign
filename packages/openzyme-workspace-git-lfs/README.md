# openzyme-workspace-git-lfs

Git/LFS workspace、publication 与 immutable-byte mechanism Adapter。

当前迁移阶段，本包已经是下列机制的目标代码 owner：

- `AgentGitWorkspace`、observation、restore comparison 与 Git identity drift；
- `AgentGitWorkspaceRepository` 的 generation-owned SQLite row mapping；事务边界由注入的 Store fenced
  commit callback 拥有，Adapter 不 import Core/Store，也不自行提交；旧 Core 模块只是 same-object alias。
- Git-LFS binding policy、pointer、closure manifest/verification；
- upload、private reachability、object-read 与 GC candidate receipts；
- `LocalGitRevisionBackend`：private ref、commit/tree、whole-tree manifest、create-only
  publication ref、restart observation、immutable path 与 actual LFS bytes 的本地 repository-service 实现。
- Agent workspace 的 exact-base Git clone runner：只接受 provisioning workspace 与进程作用域 credential，
  在注入的 Podman command port 中创建独立 `.git`，重验 remote/object-format/base commit/tree，禁止
  alternates、worktree/reference 共享；secret 只进入受限 environment，不进入 argv 或安全 receipt。
- restore observation provider：通过注入的 workspace process port 只读检查 remote/object format/HEAD/tree/
  Git directory kind，以 typed stage 区分 permission、corruption、base drift 与 infrastructure failure；它不
  replacement、不 repair、不自动创建新 generation。
- workspace lifecycle mechanism：provisioning mechanism 只组合注入的 volume allocator 与 exact-base clone runner，
  返回 volume identity 和完整 observation；recovery mechanism 只组合 provider-neutral volume Port 与 Git observation
  provider，结构化分类 missing/cross-owner/corrupt/base-drift/infrastructure/permission/internal failures。二者不访问
  Core repository、不激活 lease、不阻塞 Agent、不替换 generation。Kernel application service 仍唯一执行这些
  canonical mutation，并记录 failure observation。
- durable repository storage：`DurableRepositoryRootManager` 独占 Git/LFS/backup root confinement、bare
  repository provisioning/identity/base/ref、pre-receive hook installation/verification 与 exact Git argv；
  `DurableLfsObjectStore` 独占 incoming/object byte SHA-256、size、fsync 与 exact deletion。设置接口是窄结构
  Protocol，不依赖旧 Runtime settings 类型。hook 资产随 Adapter wheel 打包；旧 Core 不再保留实现文件。
- SQLite-backed LFS mechanism：`GitLfsRepository` 及其 policy/quota/session/closure/read/retention/GC receipt
  persistence 由本包实现，但不拥有事务边界；调用方必须注入 Store/UoW 的 fenced commit callback，Adapter
  不得自行 `connection.commit()` 绕过 mutation writer、ControlledOperation 或 runtime fence。
- LFS work-product mechanism：`.gitattributes`/pointer/whole-tree closure validation、immutable read receipt、
  private reachability finalization 与 receipt-bound GC 已迁入本包；GC 只消费窄 `GitLfsRepositoryBundle`
  Protocol，并借用上层 `atomic()`，不 import Core repository 容器，也不把 deletion receipt 推导为 publication、
  Science adoption 或 Task 完成。
- private namespace retention：open/hold/close、receipt-before-delete、whole-generation reachability 与 exact
  ref retirement 由 Adapter 实现；legacy Core factory 只注入 fenced commit/transaction-depth observer，不包含
  namespace 状态机或 Git deletion 实现。
- client qualification：native Git/LFS Batch API v2/basic、credential non-persistence 和 Gitless compute
  qualification DTO/validator 由 Adapter 拥有；测试与实现不再经旧 Core re-export。
- repository HTTP transport：Git smart HTTP v2 的 CGI streaming、Git LFS Batch v2/basic、upload/verify/download、
  bounded stderr 与 fail-closed error mapping 由 Adapter 实现。它只消费窄的已认证请求、repository scope、root
  manager 与 preflight receipt Ports；Host 临时组合类负责 Bearer 解析后的 Kernel authority admission、Session pin、
  lease/generation 与 binding lifecycle 重验，Adapter 不 import Core、Host 或 Runtime。
- repository binding mechanism：`GitLfsRepositoryBindingMechanism` 实现 Contracts 的窄 Port，验证 configured
  endpoint、durable roots、exact base/pinned commit 和 default HEAD；Kernel 服务仍唯一拥有 binding 注册/激活、
  Session pin、lifecycle 与 retirement canonical mutation，并将 endpoint mismatch 转换为稳定的 control-plane error。
- ref policy：`private_ref_prefix`、`GitRefUpdate`、`GitRefAclValidator` 与 publication/historical
  `RepositoryOwnerRefService` 由本包唯一实现。它们只把已经通过 Kernel authority admission 的意图转换为
  exact Git namespace/fast-forward/create-only 约束，不签发 authority，也不能从 ref 成功推导 publication。
- credential contract/material：closed `RepositoryCredentialClaims`、read-only
  `RepositoryProvisionCredentialClaims`、对应 schema/error envelope 与 issued token DTO 由本包唯一定义；
  provision claims 精确绑定 provisioning workspace、binding、owner、generation 与 pending lease，且不能扩张为
  write/ref authority。`HmacRepositoryCredentialMaterialAdapter` 独占 owner-only
  key 验证、canonical claims bytes、token envelope/HMAC 和 token digest。旧 broker 仍负责 Kernel
  binding/pin/authority/lease/private-namespace admission；`RepositoryCredentialIssuanceStore` 与
  `RepositoryProvisionCredentialIssuanceStore` 只在 admission 后编码 token、写读/revoke 各自 issuance ledger，
  且不自行 commit。Store/UoW 继续拥有事务与 fence；claims、ledger
  或 token 验证成功本身都不构成 authority。

backend contract identity 固定为 `openzyme.workspace.git-lfs@1`。contract digest 表示 Git-shaped backend
语义，implementation digest 等于 exact Adapter manifest digest；Distribution 通过
`workspace.backend` 单值 slot 选择 component，activation 将 manifest digest 写入 release 的
`workspace_backend_digest`，Session composition pin 再不可变继承该 release identity。安装 wheel 或发现
entry point 都不能改变这一绑定。

旧 `openzyme_domain.agent_git_workspaces`、`openzyme_domain.git_lfs_work_products`
兼容模块与顶层别名均已删除；仓内生产 caller 已直接 import 本包。

`GitRepositoryLocator` 只接受 operator 显式配置的 logical repository ID 到 absolute bare/LFS root
映射；endpoint、Agent 参数和公共 DTO 都不能成为 locator。`LocalGitRevisionBackend` 用 exact argv、
无 shell 的 Git subprocess 独立观察 commit/tree/private ref，按 whole-tree manifest 解析 Git mode/OID，
并逐个读取、重算 LFS object size/SHA-256。错误只返回稳定 code 和 effect certainty，私有诊断中的物理
root 会被脱敏。

publication dispatch 必须携带 `WorkspacePublicationDispatchIdentity`，把 ControlledOperation 的
execution ID、dispatch generation、fence 和 receipt ID 传入 Adapter。Adapter 以 zero-old-value
`git update-ref` create-only 写 immutable ref；Kernel materialize 时携带同一 durable remote receipt，
Adapter 重启后只观察、绝不重发，再由 Kernel create-only 写 `PublishedRevision`。response loss 路径调用
`reconcile_publication` 并绑定原 dispatch identity；ref 缺失保持 in-doubt，exact ref 才返回新的 observation
receipt，冲突 ref 返回 terminal-known integrity error。namespace audit 由 Adapter 返回只含 publication
prefix 的 digest observation，不把 raw `list_refs` 暴露给 Kernel。immutable path read
最多返回 1 MiB；LFS 返回 pointer OID/size 重新验证过的 actual bytes，而不是 pointer 文本。

`LocalGitlessComputeTreePreparer` 从 exact `PublishedRevision` 重新观察 commit/tree/whole-tree manifest，在
Adapter-private staging root 中逐文件 materialize ordinary blob 与已验证 LFS actual bytes，再原子安装到显式
compute destination。它只接受 regular published files，拒绝 symlink/gitlink、额外路径、`.git`、byte budget
或 LFS identity drift；安全 receipt 只含 binding/publication/commit/tree/manifest、file/byte count 和 closure
digest，不含 destination locator、credential 或 remote。response loss 后 `observe()` 只重验既有树，不重新
fetch/materialize。

这仍不表示整个 Adapter 已可由 Standard 激活：完整 workspace lifecycle/recovery、transfer result path、LFS pin/GC writer、
统一 Store writer 与 Distribution activation proof
尚未闭合。
安装 wheel 不产生 ambient capability，composition manifest 继续 fail closed。

本包只能实现 Contracts 已定义的 Port，不能拥有 Session/Task/publication canonical state，不能从
Git push、LFS receipt 或 workspace clean 状态推断文件已发布或 Task 已完成。
