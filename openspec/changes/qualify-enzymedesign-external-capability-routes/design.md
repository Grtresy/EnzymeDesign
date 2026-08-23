## Context

前置 change `operationalize-enzymedesign-external-qualification` 已在当前 checkout 建立 45 个 `ExternalQualificationUnit`、6 个 profile、recording backend、readiness verifier 和 required non-live CI。其证据明确为 `ready_non_live`，不能发行 real-subject `qualified` receipt。

本 change 开始前，operator 已确认：第一批采用推荐的 `base + research-provider + hpc-primary + hmmer + docking`；AlphaFold 第二批独立启用；预算、副作用、fault injection、TTL/storage 采用推荐值；允许只读发现当前非 secret identity；缺失 identity 必须给出解决方案后再确认；当前 live authority 仅到 dry plan，首次真实 effect 前必须再次人工授权。

gap packet 展示后，operator 又明确选择：LLM 采用当前 intended account 的资格 locator；Tavily 采用 dedicated qualification account；Git/LFS 只创建本地隔离仓库且不向 GitHub 或其他托管平台同步；Podman/科学软件采用 digest-pinned image；HPC 采用 `Diannan/3090`；protected evidence 采用 operator state root。该选择只冻结 candidate，不表示 subject 已存在、identity 已闭合或任何 effect 已获授权。

具体实现继续收紧为：operator state root 必须由当前 uid 持有、精确 `0700` 且禁止 symlink，layout、credential bundle、SQLite ledger 与私有配置精确 `0600`；凭据只从 `credential.llm.micuapi.qualification`、`credential.tavily.qualification`、`credential.hpc.diannan.qualification` 三个 plan-bound locator 解析，不读取 ambient environment fallback。Podman preparation 只有 `base`、`hmmer`、`docking` 三个 repository-owned recipe group，统一绑定 digest-pinned Python base、当前 `uv.lock` 与官方 HMMER/Vina/fpocket source commit。HPC preparation 生成独立 `aox-qualification-diannan` 配置，保持 `activated=false`、`scheduler_submit_enabled=false`，并使用 exact identity file/known-hosts file 做只读 `Diannan/3090` identity observation；不得覆盖既有 runner 配置。

只读发现得到的当前事实如下：

- LLM：`base_url=https://www.micuapi.ai/v1`、`model=gpt-5.5`、Chat Completions 路径、runtime retry 当前为 1；qualification dry plan 必须把 occurrence retry 收紧为 0。
- Tavily：route、bounded query 参数已声明，但没有独立 endpoint/account subject identity。
- Bio HTTP：UniProt、RCSB、InterPro 公共 HTTPS endpoint 由 Adapter 源码明确声明。
- Git/LFS：本机 `git` 与 `git-lfs` 可定位；operator 选择本地隔离 repository/LFS subject，因此不再要求 hosted HTTPS origin，但仓库尚未创建，local endpoint/policy identity 仍待 preparation occurrence 产生。
- Podman：rootless Linux/amd64、VFS、Podman 4.3.1 可读；现有 image 只有 pipeline sandbox 与 Python base，没有 HMMER/Vina/fpocket/preprocess/AlphaFold exact image closure。
- HPC：runner config 指向 `Diannan`、deployment `aox-live-local`、partition `3090`、ControlMaster transport；缺少 structured target profile、inventory generation/digest、native positive/negative proofs、credential provider/authenticator identity。
- 本机未发现 HMMER、Vina、fpocket、RDKit、Meeko、Open Babel 或 AlphaFold 软件实现。

这些事实只证明 identity discovery，不证明连接、凭据、健康、软件可用性或资格。

## Goals / Non-Goals

**Goals:**

- 将 readiness catalog 的 45 个逻辑 unit 重新绑定到 exact real Provider/target identity，任何 unresolved field 都产生 typed gap。
- 为每个 identity gap 生成有限候选方案、风险、前置条件、预计 effect/cost 和一个明确推荐，但由 operator 决定后才能冻结。
- 建立 source-bound、secret-safe、可独立验证的 qualification dry plan，闭合 budget、effect allowlist、credentials、fault schedule、TTL、storage、cleanup 和 authorization。
- 实现真实 backend 的显式 factory/Port wiring 与 plan-only guard，使未授权执行在 credential resolution 和 effect 前失败。
- 在后续授权后按 exact unit 执行 real probe、same-attempt reconcile 和 negative tests，产生 real-subject qualification evidence。
- 成功 evidence 只代表 `qualified`；adoption、cutover 和日常 live occurrence 仍需独立证据与授权。

**Non-Goals:**

- 当前已授权阶段不调用 Provider、Git service、Podman container、SSH、Slurm、HPC 或科学程序。
- 不读取 credential material，不把 secret name/path/value写入公共 artifact。
- 不在缺少 subject identity 时生成 placeholder receipt 或把逻辑 ID 当成真实 identity。
- 不自动安装软件、pull image、创建 repository、修改 HPC 配置或选择替代 target。
- 不更新 Session capability binding，不启用生产 runtime，不 cut over。
- 不把 AlphaFold 第二批缺失扩大为第一批失败，也不把第一批成功推导为 AlphaFold 合格。

## Decisions

### 1. Identity discovery 是独立、无 effect 的 source-bound 阶段

新增 `ExternalSubjectIdentityObservation` 与 `ExternalSubjectIdentityDiscoveryReport`。observer 只接受显式 allowlisted source：Distribution/readiness catalog、credential-free Adapter config projection、hard-coded public endpoint manifest、Podman read-only metadata、HPC runner safe projection、binary/module/image metadata。它不得加载 `.env` 中的 secret keys、调用 network、SSH、scheduler 或运行科学程序。

每个 observation 分为 `resolved`、`partial`、`missing`、`unsafe`、`drifted`。`resolved` 仍不是 qualified；它只允许 unit 进入 dry-plan 构造。

备选方案是让 live backend 在 dispatch 时补全 identity。该方案会在 effect 发生后才发现 endpoint/target 漂移，无法 source-bind budget 和 authorization，因此不采用。

### 2. 缺失 identity 必须形成 operator decision packet

`ExternalIdentityGap` 绑定 logical subject、缺失字段、发现来源、affected unit/profile digests 和稳定 error code。每个 gap 至少给出两个 mutually exclusive `ExternalIdentityResolutionCandidate`：

1. 配置/采用 intended real subject；
2. 禁用对应 optional profile 或把 required profile 保持 blocked；
3. 仅在确有多种安全机制时增加“新建隔离 qualification resource”。

candidate 记录 effect、cost、credential、operator action、compatibility 和 security implications，并标记一项推荐。未经 `ExternalIdentityResolutionDecision`，plan builder 不得选择 candidate。

当前推荐方案：

- Tavily：固定官方 Tavily service identity + dedicated qualification account/locator；不使用匿名或相邻 Provider。
- Git/LFS：只新建本地隔离 qualification repository 与 local LFS endpoint；不使用当前源码仓库/生产分支，不 push 或同步到 hosted service。
- Podman 科学软件：构建/采用 digest-pinned qualification images；不在 Host 全局安装。
- HPC：补齐 `executor_workspace@2` target profile、inventory 与 native proof，再绑定 `Diannan/3090`；不以旧 runner config 或 SSH 可达性代替。
- 科学软件：local route 使用 digest-pinned Podman image，HPC route 使用 adopted target inventory；缺一侧只阻塞该 route。
- AlphaFold：第二批使用独立 GPU image/model/database closure；资源未就绪时维持 `blocked_identity`。

### 3. Subject identity 是类型化闭包，不是显示名称或 probe 结果

Provider identity 至少包含 provider ID、credential-free endpoint identity、account/project locator digest、API/contract variant 和 bounded configuration digest。Target identity 至少包含 target/deployment ID、host/runtime identity、environment/image/inventory digest、route mechanism 和 relevant policy digest。

逻辑 ID（如 `provider.llm.primary`、`git.primary`、`hpc-primary`）只用来关联 catalog；real-subject digest 必须从上述闭包派生。unit 的 source/build/config digest 也必须基于 resolved identity 重建，readiness unit digest 不得沿用为 real receipt identity。

软件版本、image/manifest、model/database asset、inventory generation 和 route policy 属于 identity/resource facts；`hmmbuild`、`hmmsearch`、Vina、fpocket、preprocess、SSH/Slurm positive/negative smoke receipt 属于后续 qualification occurrence evidence。不得要求 smoke receipt 才能生成待执行该 smoke 的 dry plan，否则会形成循环证明。

### 4. 两批 profile 独立封闭

Batch 1 固定包含 `base`、`research-provider`、`hpc-primary`、`hmmer`、`docking`；Batch 2 只包含 `alphafold`。每批有独立 batch digest、authorization、budget、receipt set 和 terminal verdict。

Batch 1 内 required base 缺项阻塞 batch；optional profile 缺项只阻塞该 profile，但不能从 batch 结果中删除而继续宣称该 profile qualified。Batch 2 不影响 Batch 1 已产生的 exact receipts。

### 5. Identity preparation 与 qualification 使用两级独立授权对象

operator candidate decision 只选择如何补齐 identity，不授权执行。若所选方案本身需要建账号、写 locator、创建本地 Git/LFS repository、build/pull image、写安全 HPC profile 或通过 SSH 观察 inventory，则先生成 `ExternalIdentityPreparationPlan`。该 plan 精确绑定 source、discovery、gap/decision digest、batch、action、owner component、逐动作 credential locator、secret-safe input fields、canonical input-binding digest、budget、cleanup、protected storage 与 hard constraints，并固定 `live_effect_authorized=false`。计划级 locator 集合必须与逐动作 locator 并集完全相等；input、owner 或 locator 任一漂移都必须在 credential resolution 和 owner builder 之前失败。

首次 preparation effect 需要独立 `ExternalIdentityPreparationOccurrenceAuthorization` 绑定 exact preparation-plan digest、batch、operator 和 validity window。没有该 authorization，preparation backend 必须在 credential resolution、建仓、容器、SSH/Slurm 或其他 effect 前 fail closed。Preparation terminal observation 只能补齐/否决 subject identity，不能生成 `qualified` evidence。

每个成功 preparation action 产生 `ExternalIdentityPreparationResult`，绑定 occurrence、preparation plan、authorization、owner、input-binding digest、terminal observation 与 exact safe identity fields。结果写入 protected SQLite ledger；effect-free rediscovery 只消费这些安全字段。重新构造 live qualification dry plan 时，readiness catalog 中的 `nonlive.locator.*` 必须被 exact LLM/Tavily/HPC locator 取代，本地 Git/LFS 的 non-live credential placeholder 必须移除，变化后的 unit digest 才可进入 real-subject plan。

`ExternalQualificationDryPlan` 绑定 source identity、readiness catalog/plan digest、resolved subjects、unit set、probe/fault sequence、budgets、credential locators、effect allowlist、cleanup、TTL/storage policy 和 `live_effect_authorized=false`。独立 verifier 必须证明 exact closure、no secret、no fallback、所有 effect 尚未发生。

credential locator 必须逐 unit 绑定，而不能只出现在 batch 级列表中。batch 级 locator 集合必须与 unit bindings 的 locator 并集完全相等；generic probe request、owner bridge binding 和 authorized router 三者都要逐字匹配该 locator。这样同一 batch 中的 LLM、Tavily 与 HPC locator 不能交叉使用。

identity preparation 完成并重新观察后，首次 qualification probe 仍要使用另一个 `ExternalQualificationOccurrenceAuthorization`，绑定 exact dry-plan digest、operator、validity window 和 batch。Preparation authorization、plan approval、环境变量或旧 occurrence 均不能替代；没有 qualification authorization，live backend factory 只能返回 `blocked_live_authorization`，不得解析 credential。

### 6. 预算按 batch 和 occurrence 设置宽松硬上限

预算用于阻止配置错误、循环或失控消费，不作为压缩正常资格测试的目标。每项同时记录告警阈值和高于告警阈值的硬上限；达到告警阈值只产生诊断，不缩小 probe、切换 route 或自动终止，只有达到硬上限才在下一次 dispatch 前以 `blocked_budget` 停止。

- LLM：一个 bounded turn、最多 3 个 provider request；USD 5 告警、USD 25 occurrence 硬上限；qualification occurrence `max_retries=0`。
- Tavily：一个 bounded query、最多 3 个结果；USD 2 告警、USD 10 occurrence 硬上限。
- Bio HTTP：每个 Provider 一次只读 smoke。
- Git/LFS：一个隔离 repository/branch、总 payload 不超过 10 MiB。
- Podman：每个 smoke 最多一个 container；单 container 10 分钟、2 GiB。
- Slurm：一个 terminal job + 一个 cancel job；合计不超过 15 CPU-min。
- 非 AlphaFold Batch 1：USD 20 告警、USD 100 硬上限；各 occurrence 上限仍独立生效。
- AlphaFold Batch 2：一个 GPU、30 分钟、一个固定小型 monomer、一个 seed；USD 25 告警、USD 100 硬上限。

budget ledger 在 dispatch 前按硬上限 reserve、terminal/reconcile 后 settle；告警阈值不阻断，硬预算不足是 `blocked_budget`，不得缩小测试、切换 route 或用低价 Provider fallback。dry plan 必须显示每个 occurrence 与 batch 的告警/硬上限，首次 effect 授权绑定这些精确值。

### 7. 真实副作用只允许隔离资源并要求 cleanup receipt

Git 只能作用于 dedicated qualification repository/branch；Podman 只能创建 qualification-labeled disposable container；SSH 只能使用 qualification workspace root；Slurm 只能使用 approved test partition/account；科学产物只能写入该 occurrence workspace。每个 mutation unit 必须声明 cleanup action、cleanup deadline 和残留观察。

cleanup 失败不改变原 probe 的 effect certainty，并产生独立 failure；不能为了“绿”而重建或隐藏残留。

### 8. Fault injection 位于 Adapter 控制点

允许的 fault 包括 timeout-before-effect、auth/config no-effect、schema mismatch、operation mismatch，以及 Git publish、SSH exec、Slurm submit/cancel 的 acceptance-after-response-loss。response loss 必须由受控 interceptor 在 exact backend acceptance 后触发，并通过同一 attempt identity reconcile。

禁止共享网络 chaos、quota exhaustion、无限等待、自动 retry、另一 credential/Provider/target fallback。Provider auth negative test 使用 dedicated underprivileged/expired test locator；若 operator 未提供，则该 negative unit blocked，不使用随机无效 secret 冲击真实服务。

### 9. TTL、storage 与 diagnostic 分层

采用已确认推荐 TTL：Provider 24 小时；Git/LFS、Podman、SSH、Slurm 7 天；HMMER/Vina/fpocket/preprocess 30 天；AlphaFold 7 天。任何 exact identity drift、operator revoke 或 protected evidence integrity failure 立即失效。

canonical public receipt 存入 protected SQLite qualification ledger 并导出 secret-safe JSON；private cause chain、bounded stdout/stderr、return code 和 request identity 存在 protected evidence root，以 `diagnostic_id` 关联。credential material 不持久化。

### 10. Real backend 由 Adapter-owned probe bridge 提供

Distribution 只负责编排和验证，不直接实现 Provider/Git/Podman/SSH/Slurm effect。每个 Adapter 提供 `ExternalQualificationProbePort` bridge，将 generic request 编译成现有 typed Adapter operation，并把现有 receipt 转换为 generic outcome。科学 Driver bridge 编译固定 smoke workload，由 Compute/route lifecycle 执行，不能 raw shell 绕过。

plan-only factory 可以构造 bridge metadata，但不会构造 credential-bearing backend。live factory 需要 exact selected binding、resolved subject、credential locator、budget lease 和 occurrence authorization 全部一致。

在 preparation authority 之前可实现和非 live 测试 bridge 代码，但不得构造真实 backend。当前已闭合 LLM、Tavily、公共 Bio HTTP 的 typed Adapter bridge，以及 Git/LFS、Podman、SSH、Slurm 和科学 Driver 的 owner/route/subject guard；authorization-bound Distribution router 会在任何 owner builder 前验证 exact dry-plan authority。基础设施的真实 typed operation builder、科学 fixed-smoke workload 与 terminal validator 仍需在 preparation 产生 exact repository/image/target identity 后完成，因此这些 guard 测试不得表述为真实外部资格已通过。

### 11. Receipt 只能由真实终态 evidence 形成

`ExternalQualificationEvidence` 需要真实 backend、real-subject digest、terminal validation、required negative test closure、operator authorization digest 与 TTL。response loss unresolved、cleanup unknown、schema drift、missing negative 或 budget violation 都不能产生 qualified fact。

成功 receipt 不自动 adopted。后续 operator adoption 才能形成 target/provider resource fact；cutover 还需要独立 cutover receipt。

### 12. CI 与 manual workflow 继续隔离

普通 CI 运行 discovery fixtures、gap/candidate validation、dry-plan verifier、backend factory no-effect tests 和 receipt tamper tests，固定 `OPENZYME_ALLOW_LIVE=0`。manual workflow 在本阶段只生成 plan；只有未来 occurrence authorization 输入与 protected environment 同时存在时才能进入 live job，且每个 batch 单独触发。

## Risks / Trade-offs

- [当前 identity 大量缺失，change 不能立即产生 qualified receipt] → 先产出机械可验证 gap/candidate packet；保持 batch/profile blocked，不伪造 placeholder。
- [读取本机配置可能意外接触 secret] → observer 只解析 allowlisted safe fields，secret-bearing key/value/path 不进入模型或输出；测试注入 canary secret 验证零泄漏。
- [同一个逻辑 target 可能包含多个环境] → real subject digest 纳入 deployment、inventory/image、policy 和 route mechanism；每个环境单独 unit。
- [fault injection 可能制造重复 mutation] → injection 位于 acceptance 边界并绑定 same-attempt reconcile；unknown effect 永不 redispatch。
- [TTL 过短造成频繁资格运行] → TTL 按外部漂移风险分层；digest 未变也必须在 TTL 后重新探测，不能延长旧 receipt。
- [AlphaFold 资源重且依赖复杂] → 第二批独立授权与预算；最小 smoke 只验证实际推理 closure，不声称科学准确性。
- [旧 HPC config 能连通但缺少 v2 inventory proof] → 明确列为 partial/blocked，提供 config migration 方案，不把 SSH host/partition 当资格。

## Migration Plan

1. 加入 identity observation/gap/candidate/decision 和 dry-plan/budget/authorization/receipt contract；全部使用 deterministic tests。
2. 实现 repository-local safe observer 与当前 checkout discovery report，禁止 network/credential/process effect。
3. 生成 Batch 1/Batch 2 identity gap-resolution packet；把 unresolved 项交给 operator 确认。
4. 将 operator selections 冻结为 exact decisions，生成 Batch 1/Batch 2 identity-preparation plan；未授权时保持零 effect。
5. 在首次 preparation effect 前暂停；用户批准 exact preparation-plan digest、window 和 batch 后，才创建 preparation occurrence authorization。
6. Preparation 完成后重新观察 subject identity，重建 authorizable qualification dry plan。
7. 再次取得 exact qualification-plan occurrence authorization，分 unit 执行真实 qualification、settle/reconcile、验证 receipt。任何未闭合 profile 保持 blocked。
8. 完成真实资格后同步/归档本 change，并进入 cutover 前第二个人工决策门。

回滚当前 plan-only implementation 只需移除新增 contract/wiring/workflow；它不包含数据库 migration 或外部 mutation。真实 occurrence 开始后的回滚只能停止新 dispatch、reconcile 已知 attempt、执行声明的 cleanup，并保留证据。

## Open Questions

以下不再是 candidate 选择问题，而是已批准 preparation plan 必须产生的 exact identity outputs：

- Tavily exact service/account locator identity。
- 本地隔离 Git repository 与 local LFS endpoint；禁止 hosted sync。
- Podman 各科学工具 qualification image digest 或建设方案。
- `Diannan/3090` 的 executor workspace v2 profile、inventory/proof、credential provider/authenticator 与 Slurm account/QOS。
- local/HPC HMMER、Vina、fpocket、preprocess software closure。
- AlphaFold GPU image、model parameters、database closure 和固定 smoke input。
- protected SQLite ledger 与 private evidence root 的部署位置（只在 operator config 中记录，不进入公共 artifact）。
