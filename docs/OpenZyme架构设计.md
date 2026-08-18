# OpenZyme V3 架构设计

## 1. 当前架构结论

OpenZyme V3 的当前产品真状态是：

`session + task board + lane/workspace + approval + resident teammate + explicit runtime/drain`

文件内容由项目 Git 仓库、私有工作区修订、不可变发布修订和 Git LFS 对象承载。SQLite
保存身份、权限、租约、意图、回执、状态机和投影索引，不保存第二套通用文件目录真相。
历史 artifact 子系统不属于当前 runtime、domain、tool、SDK、API、UI 或 fresh-install
schema；它只在隔离的离线迁移和删除 operator 中以冻结旧输入的名字出现。

这次切换是 breaking cutover，不存在 dual-write、read-through、旧工具自动改名或旧请求
翻译。旧数据库只能在停机、备份、精确清单和回执门禁下由专用离线程序升级；普通 Host
启动不会执行兼容迁移。

## 2. 模块边界

- `apps/openzyme-host-api`：V3 组合根、REST 接口、后台 runtime command worker、durable
  work supervisor，以及 revision-bound job 的 Host 监督边界。
- `apps/openzyme-host-cli`：只使用公开 `/v3` 契约的薄客户端。
- `apps/openzyme-web-ui`：消费 `file_workspace_public@1` 投影，不保存权威业务状态。
- `apps/mcp-hpc-runner`：revision-to-compute、Slurm/SSH 生命周期和 opaque run handle
  的执行边界；它不能读取 Host 本地路径或项目凭据。
- `packages/openzyme-domain`：结构化领域对象和状态枚举，不执行 I/O。
- `packages/openzyme-core`：task、protocol、runtime、repository、workspace、publication、
  scientific、projection 和 control-plane 服务。
- `packages/openzyme-engines`：能力引擎及受监督进程实现；不得成为顶层产品真状态。
- `packages/openzyme-pipeline`：executor 代码可调用的受控 SDK；当前跨边界操作以修订、
  路径、job/result 和 scientific file contract 表达。
- `packages/openzyme-execution`、`packages/openzyme-runtime`、`packages/openzyme-tools`：
  runner adapter、runtime seam 和工具目录，不持有新的顶层权威状态。

LangGraph、LangChain 或其他 agent framework 可以用于局部能力实现，但不能替代上述
control plane。

## 3. 身份与所有权

### 3.1 项目仓库绑定

每个 project 拥有版本化 `ProjectRepositoryBinding`。session 启动时固定 binding version、
base commit、repository identity、Git/LFS endpoint identity 和 policy digest。后续 active
binding 变化不会静默重绑已有 session。

repository credential 必须同时绑定 session、agent member、workspace generation、
capability lease 和允许的 ref class；过期、撤销、跨 owner 或跨 generation 的 credential
均拒绝。私有 ref、credential、Host path、runner handle 和远端目录不进入共享投影。

### 3.2 独立 agent 工作区

每个 resident teammate 拥有独立 `AgentGitWorkspace`、generation、私有命名空间和清理
生命周期。agent 可以自由决定 fetch、merge、rebase、cherry-pick、编辑和何时请求发布；
harness 只呈现 clean/dirty、base、commit/tree、冲突、配额、租约和权限等真实约束。

workspace checkpoint 是私有可变事实。`workspace.publish` 是唯一将 exact clean commit
变为共享不可变 `PublishedRevision` 的边界。发布时必须重新验证：

1. binding、workspace generation、capability lease 和 clean observation；
2. commit/tree、父修订、publication intent 和 idempotency identity；
3. Git LFS closure 的 path、OID、size、actual bytes、quota 和 fresh readback；
4. remote push receipt、publication ref 和 immutable pin。

任何缺失、损坏、策略漂移或歧义都会在共享修订出现前失败，不自动改写 commit 或补造对象。

### 3.3 文件交接

跨 agent、task、report 和 scientific 边界只传递 typed revision/path reference：

- `RevisionPathRef` 绑定 publication、commit、tree、path、object identity、content digest
  和 size；
- research index 只索引已发布路径；
- protocol handoff、task finish evidence 和 report content ref 必须引用已验证的发布路径；
- 后续私有 workspace 变脏不影响已经发布的不可变引用。

### 3.4 产品真值的 owner 与生命周期

| 产品真值 | canonical owner | 生命周期与持久化 | 禁止的推断或替代 |
| --- | --- | --- | --- |
| agent workspace | `AgentGitWorkspace` 与 generation owner | SQLite 保存身份、状态、租约关联和安全投影；文件与完整 Git 状态位于 owner volume | lane cwd、Host checkout、另一个 agent workspace 或临时目录不能替代 |
| published revision | `WorkspacePublicationIntent`、`ControlledOperationExecution` 与 append-only `PublishedRevision` | intent、dispatch fence、remote receipt、publication ref 和 manifest 持久化；只允许 create-once/supersedes | private ref、mutable branch、相同 bytes 或 remote scan 不能自动成为 shared truth |
| external job/result | revision-bound execution owner、runner ledger 与 opaque handle | request、dispatch intent、handle、observation、cancel receipt、terminal result 和 deadline 持久化 | timeout、lease expiry、SSH 断开、文件存在或新 submit 不能冒充 settlement |
| scientific deliverable | scientific attempt/selection authority 与 finalization transaction | adopted producer effect、published path、actual-byte validation、bundle 和 receipt 原子持久化 | 文件存在、digest 相同、历史 import、job success 或 report claim不能自动 adopt/close |
| task terminal | task owner 通过显式 `task.finish` | terminal decision 与 closed typed evidence 在同一事务写入 | runtime idle、protocol delivery、publication、job/scientific terminal 不能机械完成 task |

这些对象可以互相引用，但任何一个对象的成功、失败、过期或不可见都不能替另一个 owner
做生命周期决策。projection、prompt、UI state、runner response 和离线 receipt 都只是各自权限内的
事实载体，不是第二套 canonical state。

## 4. Runtime 与协作语义

`POST /v3/sessions/{session_id}/messages` 只写入用户消息并排队 durable signal，不隐式
执行 teammate runtime drain。`POST /v3/sessions/{session_id}/runtime/drain` 只创建有界
runtime command，并返回 `202`；独立 worker 认领后推进 bounded turn。

`task.delegate` 的真实写路径是 `ProtocolService.delegate()`。`protocol.send` 只投递 inbox
并排队 wakeup，不同步运行 recipient。`auto_enqueue_ready_tasks` 默认关闭。

task 业务终态只能由 agent 显式 `task.finish` 或已文档化的机械迁移写入。runtime idle、
max steps、tool result、protocol message、job terminal、report publication 或 scientific
closure 都不自动等于 task completed。

session runtime lease、signal claim、agent process epoch、controlled-operation execution
lease、continuation delivery fence、workspace generation 和 mutation writer fence 是不同
authority。一个 authority 的 idle、过期或终态不能推断另一个 authority 已完成。

后台 supervisor 只把结构化 `semantic_progress=true` 计作进展；lease、timestamp、poll、
version 或诊断变化不能冒充业务进展。未知 effect、缺失 handle 和序列化错误都显式失败。

## 5. Approval 与外部 effect

危险操作先创建结构化 approval request。批准只授予 exact operation digest、scope、owner
和时限，不允许 agent 在批准后替换参数、扩大路径或重开 blocked action。

`ControlledOperationExecution` 是通用外部 effect 的唯一 lifecycle owner。每次 worker slice
只做短 claim、dispatch、observe、materialize-result 或 reconcile，外部调用期间不持 SQLite
写事务。只有已证明 `no_effect` 的同 phase 才允许有界恢复；请求可能已经送达但结果未知时
进入 `dispatch_in_doubt`，禁止重发。

provider dispatch/observation receipt、opaque backend handle、absolute deadline、result
digest 和 fencing token 必须持久化。timeout 只说明观察窗口结束，不能推断 effect settled。

所有失败必须同时形成同一 `diagnostic_id` 关联的两层证据：公开
`failure_observation@2` 只包含稳定 `error_code`、component、operation、phase、typed identities、
effect certainty、retry/reconcile policy、`mutation_applied`、`fallback_performed`、安全 cause chain
和 next action；Host 私有 immutable diagnostic 保留完整 traceback、异常 `__cause__`/`__context__`、
errno/return code、bounded stdout/stderr、私有路径/handle 和相关 source identity。跨边界包装必须
使用 `raise ... from exc`。公开层按 allowlist 脱敏，但不得把未知原因改写为 not-found、corruption
或 retryable，也不得吞掉 cleanup、reconcile 或 diagnostic persistence failure。

## 6. Revision-bound HPC

executor 的登录数据面是 owner-scoped `ExecutorHpcWorkspace`。它可在自己的 generation
root 内使用原生 SSH、Git/LFS、rsync/scp 和文件 CRUD，但登录 credential 不含 scheduler
submit 权限。

计算提交使用 `workspace_revision_execution_request@1`，必须绑定：

- exact private checkpoint 或 immutable publication；
- source ref、commit、tree、LFS closure 和 fresh clean observation；
- executor member、capability lease、remote workspace generation；
- cwd、command digest、environment policy、resource digest、target qualification；
- operation/execution identity、absolute deadline，必要时还包括 scientific admission。

runner 从修订准备计算源，计算 payload 不携带 `.git`、Git/LFS credential、LFS endpoint、
Host path 或 storage locator。公开生命周期只使用 opaque run handle。无 expected output 的
成功仍由 terminal observation 和 result receipt 表达；不能补造空文件。cancel 必须绑定同一
RunSpec、dispatch intent 和 opaque handle，并返回包含 `receipt_id` 的 canonical cancellation
receipt；cancel request 与 receipt 都不能冒充 backend terminal settlement。dispatch、observe、cancel
和 reconcile replay 在返回任何已存 handle/receipt 前都重新执行相同 identity/digest 校验。

## 7. Scientific file contract

scientific attempt、selection、occurrence、disposition、effect adoption、deliverable 和 task
终态相互独立。一个 deliverable 必须引用已发布 revision 中的 exact file，并绑定一个当前
selection 内显式采用的成功 producer effect。

finalization 会从不可变 publication fresh-read Git blob 或 LFS bytes，逐项验证 path、role、
format contract、digest、size、producer adoption 和 bundle completeness，原子写入
`ScientificDeliverableRef`、bundle 与 validation receipt。未知、缺失或不匹配永不解释为
negative scientific result。

AOX/HMM 仍可作为显式 scientific workflow contract 使用，但历史 cutover campaign、旧
catalog identity 和历史导入修订不能被当前 attempt、publication、report 或 GO/NO-GO
自动采用。

## 8. 公开接口

当前公开媒体类型为：

`application/vnd.openzyme.file-workspace+json;version=1`

`file_workspace_public@1` 投影只包含授权后的：workspace status、private revision fact、
published revision、report、scientific deliverable、external job/result、capability lease、
conversation、task/lane board、agents、approval、activity 和 failure observation。只有 owning
executor 的专用 view 可以返回经裁剪的 workspace locator。

旧 media type、旧 schema、旧 tool name 和旧 saved catalog context 返回不可重试的 closed
错误；Host 不做 alias 或 silent translation。CLI、UI、prompt、restore schema 和 tool catalog
作为同一 release bundle 由 digest 绑定。

## 9. 持久化与 final schema

fresh install 只加载 `001_file_workspace_final.sql`。当前 schema generation 是
`openzyme_file_workspace_final@1`，manifest digest 由 `migration_assets.py` 固定并在启动时
重算。fresh install 必须生成 deterministic typed bootstrap receipt；offline removal 必须保留独立的
完整 ledger/receipt。普通启动按 proof kind 重验 generation、manifest、receipt digest 与 fresh/offline
closure。非空未知库、旧 generation、legacy structure、missing/tampered receipt、空缺或不完整 offline
ledger、以及 manifest drift 都在 mutation 前拒绝，并报告 expected/observed digest 且
`mutation_applied=false`。

SQLite connection 是 thread-affine 的。request、worker 和 bounded turn 在实际线程内创建
并关闭自己的 connection；短 canonical mutation 使用 `BEGIN IMMEDIATE`，任何 LLM、provider、
Git、runner 或进程等待都不能跨 SQLite 写事务。

历史升级分两阶段，且都只允许由 `openspec/changes/.../operator/` 下的离线程序执行：

1. 冻结旧数据库和 storage，建立 exact object/reference inventory，将 bytes 写入
   `refs/openzyme/history/*`，fresh-fetch 回读，写 typed rewrite 和不可采用回执，同时保留源；
2. 再次验证 13 个前序 receipt、历史迁移、静默、备份和 dry-run manifest，事务性重建 final
   schema，之后才按 explicit allowlist 删除 receipt 指定的旧字节。

部分删除会留下 `offline_removal_incomplete` 并阻止普通启动；重试只能处理同一 receipt 的
精确剩余 identity。恢复只能进入隔离旧环境，不能把已移除子系统重新接回 current runtime。
所有离线 operator 的临时 worktree、fresh clone 与 final-copy 都必须位于操作员显式给出的受界
绝对 working root；不允许从系统临时目录、当前目录或环境变量推断。非 historical replacement
必须复用冻结时已经存在的 typed revision/path/result/scientific identity，不生成通用字符串或
synthetic current record。

## 10. 验收边界

架构验收至少包括：focused unit/integration tests、12-family architecture qualification、
fresh-install/restart、old-startup rejection、isolated offline migration/removal fixture、静态
source/schema/catalog scan、OpenSpec strict validation、前端 test/build 和
`./scripts/check-mainline.sh`。

focused gate 通过不等于主线验收；mainline 失败时不得生成 acceptance receipt。live LLM、
provider、HPC 和 seeded smoke 需要独立 opt-in，也不能由非 live 结果推断完成。真实部署的
迁移或删除必须另有明确目标、维护窗口、备份和 operator 授权；源码实现本身不构成执行授权。

## 11. 不变量

- harness 忠实、结构化、低摩擦地呈现世界约束，同时保留 agent 策略自由。
- authority、effect certainty、scientific truth、publication 和 task terminal 不互相推断。
- shared truth 只来自 typed repository 与 immutable revision，不来自 prompt、浏览器状态或临时目录。
- 没有隐藏 fallback、自动重试、silent schema translation、ambient path 或 manual override。
- external shell、plugin、framework 和 runner 是集成层，不替代 canonical control plane。
- 历史证据可以验证和读取，但不能升级为当前权限、发布、科学证据或产品真状态。
