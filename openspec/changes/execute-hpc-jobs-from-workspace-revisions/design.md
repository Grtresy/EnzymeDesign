## Context

Executor-owned HPC login workspace解决了原生文件管理和跨turn持续性，但任意 mutable directory仍不能作为可重放作业source。Slurm submission又跨越Host、runner、SSH和scheduler，accepted response与本地receipt无法组成单一事务；response loss不能被当作no-effect或replacement submit许可。

本 change在`provision-isolated-executor-hpc-workspaces`之后，把每个formal external job绑定到exact clean private或published Git commit、remote workspace generation、normalized cwd、command、resources和target。login side从该revision解析Git/LFS closure，原子准备不含`.git`、Git/LFS binary或credential的job-specific compute tree。普通结果文件继续留在executor remote workspace，agent自行检查、下载、commit与publish；runner不再声明/抓取`expected_outputs`或创建artifact set。

Canonical owner继续是现有`ControlledOperationExecution`。Runner提供subordinate `run_id`、immutable dispatch receipt、append-only observations和Host-private backend handle；不会创建第二套job FSM。

## Goals / Non-Goals

**Goals:**

- 让external job admission精确绑定executor lease、remote workspace generation、clean commit/tree、LFS closure、cwd、command、resources、target和absolute deadline。
- 在HPC login side从exact revision构造verified Gitless compute tree，使compute不需要Git/LFS/network credential。
- 为每个 accepted external job（Slurm 或 bounded direct SSH）持久化可权威查询的 `ExternalJobHandle` 与 dispatch receipt。
- 对response loss使用`dispatch_in_doubt`和exact reconciliation，永不盲目replacement submit。
- 复用`ControlledOperationExecution`的唯一owner、lease/fence、effect certainty、journal和restart recovery。
- 移除public `expected_outputs`、declared-output fetch、artifact set/result artifact和自动task completion。
- 让结果文件留在executor workspace，由agent自由决定检查、传输、commit或publish。

**Non-Goals:**

- 不从dirty workspace、uncommitted files、mutable branch name、Host path、artifact id或`HpcStageRef`启动formal job。
- 不要求private exploratory job先形成team publication；clean private commit可以作为policy允许的source。
- 不让compute nodefetch Git/LFS、获得repository/SSH credential或接触login clone的`.git`。
- 不自动识别、筛选、下载、commit或publish job生成的文件。
- 不把exit zero、job terminal、文件存在或result receipt机械解释为task/scientific success。
- 不在backend不可用时切换ssh/sbatch、target、command、resources、revision或local execution。

## Decisions

### 1. Admission 使用冻结的 workspace revision execution identity

`WorkspaceRevisionExecutionRequest@1`绑定controlled operation/admission digest、executor capability lease id/version、workflow明确要求的可选scientific或operation authorization digest、executor HPC workspace id与generation、repository binding version、source class（`private`或`published`）、commit/tree OID、LFS closure manifest digest、clean-state observation、normalized repository-relative cwd、argv/command digest、environment policy digest、resource request、execution mode、target profile digest、runner policy digest和absolute deadline。普通non-scientific executor job在有效lease与policy内自动创建canonical execution，不逐命令或逐job等待人工approval；若enclosing workflow明确要求scientific authorization，则它仍是额外且正交的dispatch gate。

Admission同时在canonical record和remote login clone验证该commit可读、HEAD/selected revision一致、index与tracked tree干净、policy定义的untracked状态允许、Git attributes/LFS closure有效，且cwd位于revision tree内。任何漂移在dispatch前失败；系统不stash、clean、commit、snapshot、checkout替代ref或复制mutable files。

只绑定branch/cwd无法重放；重新创建source artifact会恢复被删除的双重真相，因此不采用。

### 2. Private 与published commit都可执行，但不互相提升

Policy可以允许executor从自己的clean private ref/commit执行，以保留探索自由；该作业及结果默认仍是private。Published commit通过immutable publication ref解析并验证。Private job不会自动创建`PublishedRevision`，published source也不会使job result自动published。

Source class和exact commit进入immutable execution identity。recovery不能将private替换为published、或反向替换，即使tree digest相同。

### 3. Login side原子构造Gitless compute tree

Runner在executor workspace的job-specific、server-issued run root中准备`source/`与writable work area。它从exact commit读取tree和Git attributes，在login side解析并逐字节验证所有LFS objects，生成排序的source manifest，然后写入temporary directory并以atomic rename封存为ready tree。封存tree不得包含`.git`、Git/LFS binary、repository/SSH credential、Host path或runner sidecar。

Compute job只看到该ready tree、明确writable directories与target toolchain。requested cwd由normalized repository-relative path映射到tree内；symlink/submodule遵循binding policy且不能逃逸tree。Job开始后source/result workspace可以产生普通mutable files，但initial source identity始终由sealed manifest证明。

直接在login clone中运行会把job输出与source cleanliness混在一起，也允许并发job互相污染；compute-side Git checkout扩大credential边界，均不采用。

### 4. 每个 external job dispatch 使用唯一 marker 与 reliable handle

Canonical execution 和 runner 在启动任何 external payload 前分别持久化 immutable dispatch intent，绑定 `dispatch_id`、run id、workspace generation、source manifest、command/resources、mode 和 deadline。Target qualification 必须提供 runner-owned remote dispatch ledger。Slurm mode 还必须提供 scheduler 可权威查询的唯一 marker（例如受保护 comment/name 字段与 `squeue`/`sacct` lookup）；bounded direct SSH mode 必须由 remote wrapper 以同一 dispatch id compare-and-create 一个可查询的 process/terminal receipt。Remote wrapper 对同一 `dispatch_id` 只允许一次 accepted payload，并将 raw scheduler 或 process handle 写入 immutable receipt。

`ExternalJobHandle@1` 绑定 runner run id、dispatch id、target、workspace generation、source revision/manifest、backend kind、accepted time 和 Host-private raw scheduler/process handle。public surface 只暴露 opaque run/execution id 与 safe facts。executor 的普通 login/file credential 不具备绕过 ledger 的 scheduler submission authority；Slurm target 必须拒绝没有 frozen dispatch identity/one-occurrence runner credential 的直接 `sbatch`。

如果 target 不能保证持久 ledger、mode-specific unique marker/handle 与 terminal query，相关 mode 资格失败；系统不降级为 untracked `sbatch`、handle-less direct SSH、另一个 mode 或 local execution。

### 5. Dispatch uncertainty只查询同一effect

Accepted response、remote ledger 与 Host/runner receipt 无法跨系统事务提交。只要 request 可能到达 scheduler 或 direct wrapper 但缺少 accepted/no-effect proof，execution 进入 `dispatch_in_doubt`，retry eligibility 关闭。Reconciler 在新 execution fence 下只查询同一 dispatch id、remote ledger、mode-specific marker 和 raw handle；找到 matching receipt 后 adopt 该 exact handle，冲突则失败，无法证明则保持 unknown。

Direct SSH 只有在 remote ledger 证明 payload 未接受时才能在有限 pre-effect budget 内重试；传输开始后的 connection loss 只查询同一 dispatch id 的 process/terminal receipt，零自动 replay。Timeout、lease expiry、runner restart、missing local receipt或empty poll都不证明job不存在。无法提供这一 handle/receipt 合同的 target 不允许 direct durable mode。

### 6. Poll、cancel与restart均围绕exact handle

Runner按persisted raw handle查询queue/accounting并追加单调observation receipt；absolute deadline在admission固定，restart不重置。Terminal observation必须绑定same target/job/dispatch/workspace identity。Cancel是独立显式external effect，只提交到same handle并记录receipt；cancel request或SSH断开不代表remote process terminal。

Host restart扫描nonterminal`ControlledOperationExecution`：pre-dispatch proven no-effect work可继续；accepted/known handle只poll；`dispatch_in_doubt`只reconcile；terminal result只redeliver。任何路径都不创建新logical operation或replacement job。

### 7. Result identity描述job事实，不枚举文件

成功或失败terminal后，Host创建immutable `ControlledOperationResultRef`/workspace job result，绑定operation/execution、runner run id、safe terminal status、exit code、source revision/manifest、workspace generation、normalized job root/cwd、command/resource/target digests、terminal observation digest与时间。raw scheduler handle和remote absolute path仍Host-private或仅在owner workspace view中可用。

Result不包含artifact set、`expected_outputs`、Host-local fetched paths或自动生成的file manifest。普通output files按workspace lifecycle保留，agent通过native SSH/rsync检查；若要形成可交付证据，agent自行将选定文件复制/整理到clone、commit，并可显式publish。可选`result_revision`只有在agent完成该commit后由显式link动作绑定，不由runner自动创建。

### 8. Terminal job、delivery与business completion保持分离

Backend terminal、result materialization、continuation delivery、agent wakeup、task finish、report/scientific publication都是不同状态。Job exit zero不校验科学内容；缺少某个预期文件也不由runner把job改成failed，因为`expected_outputs`合同已删除。Agent读取结果后可继续、修正、提交新operation、请求帮助或显式`task.finish`。

### 9. 普通文件自由不削弱canonical effect fencing

Agent对remote workspace files和native transfer有策略自由；只有job dispatch/poll/cancel/result、明确要求的authorization、publication和task状态进入Host control plane。每个external callback仍须匹配execution lease、monotonic fence、state version和mutation writer。Stale worker不能更新canonical execution/result，但authoritative backend receipt可由当前reconciler在新fence下安全adopt。

## Risks / Trade-offs

- [Agent误提交dirty source] → local/canonical/remote三方identity和clean/LFS closure在dispatch前验证；不自动清理或snapshot。
- [Compute tree准备成本高] → 可按binding+commit+LFS manifest缓存只读verified source tree，但每个job仍验证cache identity/ownership；cache miss不改用mutable clone。
- [Slurm response loss留下未知job] → unique dispatch marker、runner-owned ledger、authoritative accounting和same-handle reconciliation；无法提供者不获durable Slurm资格。
- [移除expected outputs后runner不知道科学产物是否完整] → 这是有意边界：runner只证明job事实，agent/scientific workflow通过revision-path/scientific contracts验收内容。
- [结果文件无限增长] → 使用executor workspace quota/retention与显式cleanup；不恢复Host artifact fetch白名单。
- [Owner可见remote path可能进入task/protocol] → typed evidence/schema拒绝裸remote path；只有owner native workspace view可使用它。
- [多个job并发污染同一clone] → 每个run使用由exact commit构造的独立Gitless tree和job root，不在mutable login clone中直接执行。

## Migration Plan

1. 完成executor HPC workspace provisioning、native Git/LFS/SSH/rsync、workspace handle receipts与per-run artifact staging删除；未资格target不得进入本change。
2. 为每个 target 部署并验证 runner-owned dispatch ledger；Slurm mode 验证 unique marker、one-occurrence `sbatch` credential、unregistered-submit rejection、receipt、`squeue`/`sacct` authoritative query，direct mode 验证 process handle/terminal receipt query；共同验证 restart 和 terminal retention。缺一项即关闭对应 mode，不 fallback。
3. 引入versioned workspace-revision execution request、ExternalJobHandle、source manifest与workspace job result schema；复用现有ControlledOperationExecution tables/owner/lease/fence/journal，而非新增FSM。
4. 实现login-side exact revision/LFS validation和atomic Gitless tree builder；验证dirty/untracked、missing LFS、symlink escape、submodule policy、cache drift与compute credential absence。
5. 将RunSpec/runner API切到workspace generation、revision、cwd、command/resources；删除artifact inputs、`HpcStageRef`、`expected_outputs`、output fetch和artifact result fields。旧schema request明确拒绝，不翻译。
6. 切换 dispatch/poll/cancel/reconcile 到 immutable intent/marker/handle receipts；覆盖 accepted-response loss、Host/runner restart、duplicate worker、stale fence、direct SSH same-dispatch reconciliation、unregistered `sbatch` rejection 与 absolute deadline 测试。
7. 切换ControlledOperation result/projection/continuation到job/revision/workspace identity；结果文件保持remote mutable，task/report/scientific状态无机械迁移。
8. 停止旧staging/fetch/result artifact writers并冻结历史records供后续migration。不得dual-write或在missing新handle时调用旧runner path。
9. 回滚只允许在新job尚未dispatch前恢复整套旧deployment。已有new-contract job必须由new handle/reconciler结算；不得用旧expected-output fetch或replacement submit“完成”它们。

## Open Questions

无未决产品问题。各target的dispatch marker字段、accounting retention、atomic rename/filesystem能力、Git/LFS版本和compute mount方式属于显式qualification profile，必须先证明满足合同，不能在运行时猜测或降级。
