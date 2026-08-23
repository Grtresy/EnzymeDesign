# V3 Runtime 与 HPC Reliability

> revision-execution DTO 与 runner wire parser 位于 `openzyme-execution-contracts`，runner 只依赖该窄 wheel。
> 运行时语义 owner 是 `openzyme-compute` Plugin、`openzyme-hpc` Plugin、`openzyme-hpc-ssh` 与
> `openzyme-hpc-slurm` Adapters。HPC workspace DTO、纯 lifecycle、manifest、inventory、8 个 workspace
> tool runtime、两条 capability route runtime、完整 workspace application/SQLite writer，以及 SSH/Slurm
> Adapter 均由目标包拥有；Host 只保留窄 Kernel-facts/tool composition gateway。是否激活取决于 exact
> Distribution、deployment epoch、Session pin、inventory binding 与 Agent affordance；任何 non-live mount
> 都不表示 live route 已可用。

## Authority 分层

session runtime lease、agent process epoch、controlled-operation execution fence、continuation delivery
fence、executor workspace generation、scheduler occurrence credential 和 mutation writer fence 相互独立。
任何跨层借权均拒绝。

## Executor workspace

`ExecutorHpcWorkspace` 绑定 project/session/executor member、target qualification、generation 和 root identity。
login/file credential 只允许 owner root 内 SSH、Git/LFS、rsync/scp 和 CRUD，不包含 scheduler submit。
其他 owner/generation、runner sidecar 和 Host path 不可见。

`hpc.workspace.sync_source` 只准备 exact private checkpoint 或 immutable publication；fetch、checkout、merge、
rebase 和冲突处理由 agent 显式决定。它不发布 revision、不完成 task，也不提交 job。

HPC Plugin 现在贡献 `hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec`，除首次
request 外的请求都携带 Host 发出的
opaque workspace ID，并重新验证 owner、local/remote generation、target qualification 与 operation-specific
authority。SSH/SFTP/rsync Adapter 执行具体 I/O；Plugin import、Agent turn 和 tool visibility 计算均不得临时
SSH/`which` 探测软件。远端 response loss 进入同一 ControlledOperation reconcile，不自动重发。

远端 transport 只允许调用 target profile 已资格化的 exact absolute `openzyme-workspace-runtime` helper。Diannan
当前绑定 `/home/grtresy/.local/libexec/openzyme-workspace-runtime`。它必须作为
`software.openzyme-workspace-runtime == 1.0.0` 出现在 adopted target inventory 中，并由 qualification receipt
绑定 build digest、target generation 与 environment；缺失或版本漂移时 remote workspace tools 为
`blocked_qualification`，Adapter 不临时 SSH 探测或自动安装。

fleet target 可采用 exact login-principal-owned `.local/libexec`，但该选择必须在 target qualification 中显式绑定
observed principal、absolute home、deployment scope、exact path、目标文件 pre-state/build digest、same-parent
staging/backup、owner/group/mode 与 rollback owner，并使用独立一次性 authority。不得在运行时展开 `$HOME`、搜索
`PATH`、根据权限改到 `/usr/local`、相邻 helper 或另一用户目录。principal/home/parent identity 不闭合时稳定进入
`blocked_deployment_authority`，不能把可执行文件存在当资格。
安装后 native positive/negative qualification 任一失败时，只能在 destination 仍匹配本 occurrence 安装 digest
时恢复 exact backup 或删除本 occurrence 首次创建的文件；destination identity 不明时保持
`deployment_in_doubt` 并阻断 dependent qualification。

普通 login Shell 与 scheduler 永远分开：`hpc.workspace.exec` 不能调用/模拟 `sbatch`、`scancel` 或 runner
API；formal occurrence credential 只由 Compute admission 为 exact workload/route 签发。

## Target inventory 与领域工具

HPC qualification 将当前 opaque toolchain digest 扩为 immutable inventory generation，逐项记录 software/
hardware/data/asset/license capability、version、operations、environment/binary/qualification digest 和 validity。
只有 operator/admin 能 publish/adopt/revoke；Session 通过 capability binding revision 采用 exact generation。

HMMER/Vina 等 Product Plugin 声明 capability/version/operation/same-target requirements，不 import HPC 或 Slurm。
Resolver 只有在 Plugin、inventory、route、Agent authority 与 workspace 均满足时才暴露 formal tool；Agent 必须
选择 exact route，Driver 再编译 typed `ExecutionWorkloadSpec` 交给 Compute。直接在 HPC Shell 运行二进制只
是 exploratory process receipt，不等于 formal result、Science adoption、publication 或 Task finish evidence。

## Job admission

`workspace_revision_execution_request@1` 必须绑定 exact source revision、commit/tree、LFS closure、clean
observation、cwd、command、environment、resources、target/runner policy、executor lease/generation、operation/
execution identity 和 absolute deadline。formal scientific job 还绑定 attempt admission 与 workflow digest。

admission 后 Host 发放一次 scheduler occurrence credential。runner 从 revision 构造 compute source manifest；
payload 不携带 `.git`、repository credential、LFS endpoint、object-store locator 或 Host path。

Slurm Adapter 在首次 submit/cancel effect 前，将 exact provider/kind/operation/request identity 原子写入
`openzyme_hpc_scheduler_occurrences`。raw Slurm id 只存在该 HPC-owned 私有账本；公开 receipt 只返回 opaque
handle。EnzymeDesign application root 通过 selected `SlurmSchedulerAdapterFactory` 显式注入 backend、credential
resolver 与同一 SQLite 账本，不允许 ambient backend 或 in-memory production fallback。
submit/cancel reconcile 总是先读取该 durable occurrence：terminal receipt 可在没有 credential 时直接返回；
已有 uncertain occurrence 而 credential 暂不可用时保持原 `dispatch_in_doubt`，不得以当前不可观察推断原 effect
为 `no_effect`。SSH workspace reconcile 对 locator/qualification 暂时漂移采用同一原则。

产品级 formal Compute 的 source/admission 也必须可重建：HMMER/Vina 输入引用一个 immutable
`PublishedRevision`，每个 path 有 publication-owned verification receipt；owner workspace generation、authority
generation/fence、Session capability binding、target inventory generation/digest 与 exact route 在 dispatch 前重验。
这些 facts 不从 Driver 或模型参数推断。Compute 在 terminal persistence/continuation 之前重建 exact compiled
Driver workload，并调用对应 HMMER/Vina `validate_result()`；result contract drift 或 `raw_shell=true` 会以
terminal-known validation failure 停止，不能注册 continuation。当前 non-live qualification 使用声明式 fake
external runner 验证这一 formal slice 和 continuation/Task 终态分离；它不声称真实 SSH/Slurm backend 已可达。

## Runner lifecycle

公开 runner handle 是 server-issued opaque `run_id`。raw Slurm job id、remote directory 和 recovery RunSpec
不跨边界。dispatch 前 crash 可证明 `no_effect`；payload 已交给 transport 但 receipt 未落盘则
`dispatch_in_doubt`，只能 query/reconcile exact occurrence。

Runner 配置不是领域工具目录。当前 `runner_effective_config@2` 关闭所有未知顶层 section，
明确拒绝 `[adapters.*]`、领域软件路径或版本选择；这些事实只能来自 exact
Plugin/Driver manifest、operator qualification 和 Session 已采用的 target inventory。

observe、logs、cancel 都必须匹配 occurrence credential 和 opaque handle。cancel intent 不等于 backend 已
取消；cancellation receipt 使用唯一 canonical wire contract，必须包含 `receipt_id`、cancellation/handle
identity、requested/settlement facts、backend receipt digest、时间与完整 receipt digest。只有经过 exact
parser/serializer 校验的 receipt/observation 可更新 effect certainty。dispatch、observe、cancel 与
reconcile replay 在返回持久化对象前重新比对当前 RunSpec、dispatch intent、handle 和 digest；不匹配时
在 backend action 前失败。

## Results

terminal success 形成 `WorkspaceJobResult`，可选择绑定 result revision。runner 不声明、枚举或验证
`expected_outputs`；结果文件留在 owner executor workspace，由 agent 通过 `hpc.workspace.*` 检查和同步，
具体 SSH/SFTP/rsync 只由选定 Adapter 在不泄漏 locator/credential 的边界内执行；随后 Agent 显式形成新的
clean result revision。job 可以在没有结果文件时成功，但仍需要 terminal observation、
result digest 和 lifecycle receipt；不得创建占位文件、自动 fetch/commit/publish 或从文件存在推断成功。

## Restart

restart 从 durable dispatch intent、handle、observation、deadline 和 fence 恢复，不重新 submit。Workspace
operation receipt 与 Slurm submit/cancel occurrence 都跨 Adapter epoch 保留；unknown response 只能调用原
provider 的 reconcile 方法，terminal receipt 不能被替换。lease expiry 只允许另一个 worker 认领同一
occurrence。absolute deadline 不因 restart 重置。

## Mutation quiescence

迁移/发布或 scientific closure 需要时，mutation scope 先 freeze admission，再等待所有显式 writer/descendant
带 terminal proof 退休，获取两次一致的 SQLite/event/file high-watermark snapshot，最后签发 immutable
quiescence receipt。空队列、runtime idle、HTTP 返回和 timeout 都不是静默证明。

## 验证

non-live tests 应覆盖 duplicate dispatch、pre-effect failure、dispatch-in-doubt、restart fencing、deadline、
cancel ambiguity、receipt-id/digest tamper、replay handle drift、no-output success、cross-owner/generation denial
和 locator redaction。每个失败同时断言稳定公开诊断、私有 cause chain、mutation/fallback facts 与零
replacement dispatch。real SSH/HPC 只在独立 opt-in 与明确授权下执行。

运维验收还必须检查 explicit cleanup：主操作和 cleanup 同时失败时按顺序保留两个 cause；effect 已成功
但临时路径残留时记录 `cleanup_incomplete`、exact temporary identity 与 `mutation_applied=true`，不得
静默删除诊断或回退成 `no_effect`。
