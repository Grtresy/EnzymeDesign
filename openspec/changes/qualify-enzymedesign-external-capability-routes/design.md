## Context

前置 change `operationalize-enzymedesign-external-qualification` 已在当前 checkout 建立 45 个 `ExternalQualificationUnit`、6 个 profile、recording backend、readiness verifier 和 required non-live CI。其证据明确为 `ready_non_live`，不能发行 real-subject `qualified` receipt。

本 change 开始前，operator 已确认：第一批采用推荐的 `base + research-provider + hpc-primary + hmmer + docking`；AlphaFold 第二批独立启用；预算、副作用、fault injection、TTL/storage 采用推荐值；允许只读发现当前非 secret identity；缺失 identity 必须给出解决方案后再确认；当前 live authority 仅到 dry plan，首次真实 effect 前必须再次人工授权。

gap packet 展示后，operator 又明确选择：LLM 采用当前 intended account 的资格 locator；Tavily 采用 dedicated qualification account；Git/LFS 只创建本地隔离仓库且不向 GitHub 或其他托管平台同步；Podman/科学软件采用 digest-pinned image；HPC 采用 `Diannan/3090`；protected evidence 采用 operator state root。该选择只冻结 candidate，不表示 subject 已存在、identity 已闭合或任何 effect 已获授权。

具体实现继续收紧为：operator state root 必须由当前 uid 持有、精确 `0700` 且禁止 symlink，layout、credential bundle、SQLite ledger 与私有配置精确 `0600`；凭据只从 `credential.llm.micuapi.qualification`、`credential.tavily.qualification`、`credential.hpc.diannan.qualification` 三个 plan-bound locator 解析，不读取 ambient environment fallback。Podman preparation 只有 `base`、`hmmer`、`docking` 三个 repository-owned recipe group，统一绑定 digest-pinned Python base、当前 `uv.lock` 与官方 HMMER/Easel/Vina/fpocket source commit。HPC preparation 生成独立 `aox-qualification-diannan` 配置，保持 `activated=false`、`scheduler_submit_enabled=false`，并使用 exact host/port（当前端口为 `22222`）、identity file/known-hosts file 做只读 `Diannan/3090` identity observation；不得覆盖既有 runner 配置。

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
- 唯一例外是 operator 已选择并另行 exact-authorize 的 workspace runtime helper 部署；该 effect 只建立 qualification prerequisite，不构成 target inventory adoption、runtime activation 或 cutover。
- 不更新 Session capability binding，不启用生产 runtime，不 cut over。
- 不把 AlphaFold 第二批缺失扩大为第一批失败，也不把第一批成功推导为 AlphaFold 合格。

## Decisions

### 1. Identity discovery 是独立、无 effect 的 source-bound 阶段

新增 `ExternalSubjectIdentityObservation` 与 `ExternalSubjectIdentityDiscoveryReport`。observer 只接受显式 allowlisted source：Distribution/readiness catalog、credential-free Adapter config projection、hard-coded public endpoint manifest、Podman read-only metadata、HPC runner safe projection、binary/module/image metadata。它不得加载 `.env` 中的 secret keys、调用 network、SSH、scheduler 或运行科学程序。

每个 observation 分为 `resolved`、`partial`、`missing`、`unsafe`、`drifted`。`resolved` 仍不是 qualified；它只允许 unit 进入 dry-plan 构造。

`external_qualification_unit@2` 必须从 selected Plugin resource requirement 复制 exact `subject_version_spec` 并纳入 unit digest。safe subject projection 对每个 versioned capability 提供独立 canonical version field；一个 preprocess image 可以同时闭合 RDKit、Meeko、Open Babel 三个不同 spec，不能把整个 target 压成单一版本。HPC Adapter 负责把原始 banner 规范化，原始文本只进入 inventory digest。version field 缺失为 `partial`，不可解析或不满足 spec 为 `drifted`；两者都生成 gap 并阻止 authority，而不是接受 opaque software fact。

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

当前只读发现确认 `Diannan/3090` 已存在管理员维护的 AlphaFold 3.0.1 wrapper、Apptainer SIF、模型参数与数据库。
Batch 2 因此采用 `observe-existing-alphafold3-resource-closure`，不执行 build、copy、install 或 license acceptance。
preparation 将 wrapper/image/model/database metadata、GPU partition、source commit/dirty observation 与 Apptainer
version 固定为受保护 identity；qualification 在 dispatch 前重算 effect-bearing resource digest。真实 workload 固定为
20 aa monomer、seed `20260824`、一张 3090、30 分钟与 inference-only，输出只接受 exact CIF 和 summary
confidence；cleanup 失败或资源漂移均阻断，不重试、不换 target、不 fallback。
若已终态 observation 后只在 effect-free rediscovery 暴露源码缺陷，新 source-bound preparation 必须重新只读观测；
既有 protected config 只有在 digest、owner/mode 与全部稳定 target/resource fields 精确相等时，才可
compare-and-replace plan/authority 及当前 source 编译的 `fixed_monomer_input_digest`，并记录 prior digest。不得删除
残留配置、跳过新 authority、改变 target resource 或将其计为旧 occurrence retry。
AlphaFold Batch 2 的单一 `predict` 是 terminal scientific route，不声明虚假的 response-loss unit；live negative gate
以 fail-closed/no-redispatch policy 闭合 `response.loss`，并保留 auth、operation、schema、timeout pre-effect 负例。
resource/GPU/output/cleanup 失败由 route regression 闭合。只有实际声明 reconcile operation 的 Batch 1 unit 才采用
same-attempt reconcile。
固定 20 aa 输入采用 Diannan 既有成功 AlphaFold 3 样例已证明的单链 `id: "A"` schema。route 以单次
`sbatch --parsable` 提交并按 exact job id 有界轮询 `sacct`，不使用可能悬挂的 `sbatch --wait`。失败 observation
在 workspace cleanup 前以同一非零命令携带 bounded stdout/stderr 到 protected diagnostic，随后仍执行 cleanup；
公共 receipt 不暴露 raw log，轮询或诊断也不能触发 redispatch、换 route 或保留残留 workspace。

### 3. Subject identity 是类型化闭包，不是显示名称或 probe 结果

Provider identity 至少包含 provider ID、credential-free endpoint identity、account/project locator digest、API/contract variant 和 bounded configuration digest。Target identity 至少包含 target/deployment ID、host/runtime identity、environment/image/inventory digest、route mechanism 和 relevant policy digest。

逻辑 ID（如 `provider.llm.primary`、`git.primary`、`hpc-primary`）只用来关联 catalog；real-subject digest 必须从上述闭包派生。unit 的 source/build/config digest 也必须基于 resolved identity 重建，readiness unit digest 不得沿用为 real receipt identity。

软件版本、image/manifest、model/database asset、inventory generation 和 route policy 属于 identity/resource facts；`hmmbuild`、`hmmsearch`、Vina、fpocket、preprocess、SSH/Slurm positive/negative smoke receipt 属于后续 qualification occurrence evidence。不得要求 smoke receipt 才能生成待执行该 smoke 的 dry plan，否则会形成循环证明。

### 4. 两批 profile 独立封闭

Batch 1 固定包含 `base`、`research-provider`、`hpc-primary`、`hmmer`、`docking`；Batch 2 只包含 `alphafold`。每批有独立 batch digest、authorization、budget、receipt set 和 terminal verdict。

Batch 1 内 required base 缺项阻塞 batch；optional profile 缺项只阻塞该 profile，但不能从 batch 结果中删除而继续宣称该 profile qualified。Batch 2 不影响 Batch 1 已产生的 exact receipts。

### 5. Identity preparation 与 qualification 使用两级独立授权对象

operator candidate decision 只选择如何补齐 identity，不授权执行。若所选方案本身需要建账号、写 locator、创建本地 Git/LFS repository、build/pull image、写安全 HPC profile 或通过 SSH 观察 inventory，则先生成 `ExternalIdentityPreparationPlan`。该 plan 精确绑定 source、discovery、gap/decision digest、batch、action、owner component、逐动作 credential locator、secret-safe input fields、canonical input-binding digest、budget、cleanup、protected storage 与 hard constraints，并固定 `live_effect_authorized=false`。计划级 locator 集合必须与逐动作 locator 并集完全相等；input、owner 或 locator 任一漂移都必须在 credential resolution 和 owner builder 之前失败。

首次 preparation effect 需要独立、持久、一次性的 `ExternalIdentityPreparationOccurrenceAuthorization` 绑定 exact preparation-plan digest、batch 和 operator，不设置 wall-clock 有效期。该 authority 只允许启动或恢复同一 exact occurrence：已持久化的 terminal action 直接恢复且不得重复派发；source、plan、batch、operator 任一漂移都会失效，也可由绑定 exact authorization 的私有 revocation evidence 显式撤销。没有 authority 或 authority 已撤销时，preparation backend 必须在 credential resolution、建仓、容器、SSH/Slurm 或其他 effect 前 fail closed。Preparation terminal observation 只能补齐/否决 subject identity，不能生成 `qualified` evidence。

当同一 occurrence 的全部 action result、prepared snapshot 与 post-preparation packet 已终态持久化时，后续调用必须在 credential resolver 与 owner backend 构造前验证并恢复 exact 私有证据；不得以新的 wall-clock 时间重建 snapshot/packet，也不得再次访问 credential 或 redispatch effect。

每个成功 preparation action 产生 `ExternalIdentityPreparationResult`，绑定 occurrence、preparation plan、authorization、owner、input-binding digest、terminal observation 与 exact safe identity fields。结果写入 protected SQLite ledger；effect-free rediscovery 只消费这些安全字段。重新构造 live qualification dry plan 时，readiness catalog 中的 `nonlive.locator.*` 必须被 exact LLM/Tavily/HPC locator 取代，本地 Git/LFS 的 non-live credential placeholder 必须移除，变化后的 unit digest 才可进入 real-subject plan。

`ExternalQualificationDryPlan` 绑定 source identity、readiness catalog/plan digest、resolved subjects、unit set、probe/fault sequence、budgets、credential locators、effect allowlist、cleanup、TTL/storage policy 和 `live_effect_authorized=false`。独立 verifier 必须证明 exact closure、no secret、no fallback、所有 effect 尚未发生。

credential locator 必须逐 unit 绑定，而不能只出现在 batch 级列表中。batch 级 locator 集合必须与 unit bindings 的 locator 并集完全相等；generic probe request、owner bridge binding 和 authorized router 三者都要逐字匹配该 locator。这样同一 batch 中的 LLM、Tavily 与 HPC locator 不能交叉使用。

identity preparation 完成并重新观察后，首次 qualification probe 仍要使用另一个持久一次性的 `ExternalQualificationOccurrenceAuthorization`，绑定 exact dry-plan digest、operator 和 batch，不设置 wall-clock 有效期。该 authority 只允许启动或恢复同一 exact occurrence：terminal unit 只能从 protected ledger 恢复，不得 redispatch；source、plan、batch、operator 任一漂移都会失效，也可由绑定 exact authority 的私有 revocation evidence 显式撤销。Preparation authorization、plan approval、环境变量或旧 occurrence 均不能替代；没有 qualification authorization 或 authority 已撤销时，live backend factory 只能返回 `blocked_live_authorization`，不得解析 credential、reserve budget 或构造 owner bridge。

真实 Batch 1 证明 44 个相互独立的外部 unit 若被强制在一个长网络会话内同时成功，会把 `max_retries=0` 错误放大成 batch 级全量重发。恢复语义因此固定为：新的一次性 authority 仍以完整 dry plan 作为 effect 上限，但 occurrence 可在首次 effect 前把 exact checkout source identity 与非空 unit 子集 create-once 写入 protected ledger；同一 authority 的 source/scope 漂移在 credential resolution 和 budget reserve 前拒绝。后续 failed-unit occurrence 只执行缺失 unit，不重发已有 current receipt 的 LLM、Tavily、Git、Podman 或其他 operation。Batch verdict 由独立 receipt-set verifier 跨 occurrence 验证同一 checkout source identity 与 dry-plan digest 下每份 receipt 的 authority、scope、negative gate、budget、cleanup、TTL 和 exact unit/subject/route/schema closure；dry-plan digest 偶然未变不能替代 checkout source binding，subset report 永不自行宣称整批 `qualified`。

### 6. 预算按 batch 和 occurrence 设置宽松硬上限

预算用于阻止配置错误、循环或失控消费，不作为压缩正常资格测试的目标。每项同时记录告警阈值和高于告警阈值的硬上限；达到告警阈值只产生诊断，不缩小 probe、切换 route 或自动终止，只有达到硬上限才在下一次 dispatch 前以 `blocked_budget` 停止。

- LLM：一个 bounded turn；10 次 request 告警、20 次 request 硬上限；USD 50 告警、USD 100 occurrence 硬上限；qualification occurrence `max_retries=0`。
- Tavily：一个 bounded query、最多 3 个结果；USD 20 告警、USD 50 occurrence 硬上限。
- Bio HTTP：每个 Provider 一次只读 smoke。
- Git/LFS：一个隔离 repository/branch；32 MiB 告警、64 MiB payload 硬上限。
- Podman：每个 smoke 最多一个 container；3000 秒告警、3600 秒硬上限；2 GiB 内存告警、4 GiB 硬上限。
- Slurm：一个 terminal job + 一个 cancel job；120 CPU-min 告警、180 CPU-min 硬上限。
- 非 AlphaFold Batch 1：USD 100 告警、USD 250 硬上限；各 occurrence 上限仍独立生效。
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

Repository-owned scientific image recipes 从各自官方 Git URL 完整取得固定 commit，并显式固定 Git HTTP/1.1；HMMER Git source 按官方构建闭包另行固定 Easel 0.49 commit，不把 Easel 误当 submodule 或浮动 master。禁止 partial-clone promisor checkout、自动 retry 或镜像源 fallback。这样 checkout 只消费本地完整对象闭包，网络或依赖闭包失败仍以单次 occurrence 的 terminal failure 暴露并由 operator 决定后续处理。

本地镜像 subject closure 同时绑定 immutable image digest 与当前 repository-owned recipe digest；recipe digest 是从 Containerfile、固定 base、source commits 和 `uv.lock` 重新计算的 source fact，不能由既有 image digest 或旧 preparation receipt 代替。effect-free rediscovery 若发现 recipe 字段缺失则保持 `partial`，若字段与当前源码不一致则标记 `drifted`，均不得生成 authorizable dry plan。recipe 变化使用新的 output image ref，并保留旧镜像；禁止覆盖、重标记、自动采用旧镜像或把旧 tag 当 fallback。

当前源码已闭合 LLM、Tavily、公共 Bio HTTP、Git/LFS、Podman、SSH、Slurm 的 exact owner operation bridge，以及 HMMER、Vina、fpocket、RDKit、Meeko、Open Babel 的固定小型 workload、正式 Compute route 与 Driver terminal validator。authorization-bound Distribution router 会在任何 credential resolution 和 owner builder 前验证 exact dry-plan authority；live coordinator 以 protected SQLite 恢复 terminal outcome/receipt，in-doubt 只允许同一 attempt reconcile，无法安全恢复的 Provider attempt 稳定阻断而不 redispatch。Diannan route 只探测并执行 target 已安装软件，不安装、升级或重建远端工具；post-deployment rediscovery 必须重新只读观测 exact HMMER、Vina、fpocket SIF digest 并把它们纳入 scientific target subject closure，authority 创建端在落盘前验证这些字段与 helper identity 均可构造正式 live bridge。本地科学 route 只采用 preparation 已固定 digest 的 qualification image。上述实现与 fake-command 回归仍不等于真实外部资格通过，只有授权 occurrence 的 terminal receipt 能形成 `qualified`。

首次授权 Batch 1 occurrence 的裁决进一步收紧了实现：本地 Git publish ref 按 occurrence workspace 形成稳定 namespace，后续 LFS fetch 绑定同一 exact remote-tracking ref，不能复用固定 `qualification` branch；HPC credential material 中的 `ssh_user`、`workspace_root` 和 `isolation_command` 必须在构造 SSH state 前逐字等于已资格 helper 的 principal、workspace parent 和 absolute path。live report 不能只投影 cleanup/budget digest，受保护 SQLite 还必须持久化 exact cleanup resources 与逐 unit budget settlement payload，恢复时缺失或漂移即停止。Provider public outcome 继续只保留安全 error code，受保护 diagnostic 可额外记录 Adapter 已去敏的 provider status/summary。科学 workload 的 expected output 必须来自实际 argv/程序 cwd：HMMER build 采用 argv output，fpocket 采用 cwd 下 `structure_out/structure_info.txt`；本地 docking image recipe 补齐 pinned SciPy 与 Open Babel 所需 Xrender runtime，新 output ref 为 `localhost/openzyme-qualification-docking:20260823-r2`，safe identity 另行绑定 `docking_image_recipe_digest`。以上变化只为生成新的 source-bound plan，绝不复用已终态 authority。

operator 已选择 Vina route-specific 双版本：产品级 capability 支持闭包为 `>=1.1.2,<2`，Diannan HPC route
精确要求 `==1.1.2` 并使用 legacy `--log`/poses+log result profile；本地 route 精确要求 `>=1.2,<2`，使用
modern 无 `--log` argv，并从 poses `REMARK VINA RESULT:` 形成带固定 semantics 的 score artifact。每条 route
在 Plugin manifest 中拥有独立 resource requirement，Kernel 只为 exact bound target/version 发布 route ref；
Driver manifest、workload/result digest、qualification unit 和 subject identity 均绑定相同 profile。任一路漂移只
阻断该 route，不自动切换、探测式改写 argv、重试另一 profile、重建远端工具或 fallback。

### 11. Receipt 只能由真实终态 evidence 形成

`ExternalQualificationEvidence` 需要真实 backend、real-subject digest、terminal validation、required negative test closure、operator authorization digest 与 TTL。response loss unresolved、cleanup unknown、schema drift、missing negative 或 budget violation 都不能产生 qualified fact。

成功 receipt 不自动 adopted。后续 operator adoption 才能形成 target/provider resource fact；cutover 还需要独立 cutover receipt。

### 12. CI 与 manual workflow 继续隔离

普通 CI 运行 discovery fixtures、gap/candidate validation、dry-plan verifier、backend factory no-effect tests 和 receipt tamper tests，固定 `OPENZYME_ALLOW_LIVE=0`。manual workflow 在本阶段只生成 plan；只有未来 occurrence authorization 输入与 protected environment 同时存在时才能进入 live job，且每个 batch 单独触发。

### 13. Workspace runtime helper 使用 target-qualified exact principal path 与可恢复回滚

`openzyme-hpc-ssh` 拥有 `software.openzyme-workspace-runtime == 1.0.0` 的标准库单文件实现。helper 只接受 `policy-digest`、`provision`、`verify`、`cleanup` 和 `version`，不接受 raw command 或 scheduler operation。workspace 必须是 root-policy 绑定父目录下的 exact `hpcws_<uuid>` 直接子目录；policy 同时绑定 OS principal、policy ID、helper version 和父目录。provision marker、owner identity、runner handle、cleanup settlement 与 helper state 都以 canonical digest 封闭；symlink、跨 root、principal/owner/handle drift 必须在 mutation 前拒绝。cleanup 先在同一父目录原子 rename，再删除，并以 durable `deleting/deleted` state 支持同一 occurrence response-loss reconcile。

fleet target 不再共享一个必须由管理员写入的全局 helper 路径；每个 target profile 选择并资格化一个由 exact login principal 拥有的绝对路径。Diannan 明确选择 `/home/grtresy/.local/libexec/openzyme-workspace-runtime`，这项 operator decision 替代此前 `/usr/local/libexec` 唯一路径设计，不是运行时 fallback。不得在执行时展开 `$HOME`、搜索 `PATH`、采用相邻 executable 或根据权限自动换路径。远端 deployment plan 必须绑定 source identity、helper bytes/build digest、目标 host key、login principal、observed absolute home、deployment scope、exact path、当前目标文件状态/digest、same-parent staging/backup、安装机制、文件 owner/group/mode、positive/negative probes、rollback owner 和 deadline。

deployment 成功还不能直接充当 route qualification。独立 read-only rediscovery 必须把 deployment plan/authority/terminal receipt、native qualification digest、exact build、root-policy、OS principal 和目标文件 owner/group/mode 纳入新的 `hpc-control` subject closure；公开 snapshot 只保留 path identity digest，不暴露私有绝对路径。随后 `openzyme.hpc.ssh:helper-identity` live occurrence 必须再次调用 exact absolute helper 的 `version` 与 `policy-digest` 并与 subject closure 全量比较，旧的 `command -v sh`/`sha256sum` 形状不得被视为 helper qualification。

target home、principal、parent owner/mode 或 direct-write mechanism 任一未闭合时，plan 保持 `blocked_deployment_authority`，不写 staging、不创建 qualification receipt。获独立一次性 deployment authority 后，部署器才可在 exact principal-owned libexec 下创建 protected parent、上传 exact bytes、核对 staging digest并执行同 filesystem 原子替换。若目标已有文件，替换前保存 exact backup digest；若安装后 version/build、policy、positive/negative 或 cleanup probe 任一失败，部署器只在当前目标 digest 仍等于本 occurrence 安装 digest 时恢复 backup，或删除本 occurrence 首次创建的文件。回滚失败保留 `deployment_in_doubt` 与私有诊断，禁止 qualification dispatch。

helper deployment receipt 只证明 exact software 安装和 native isolation contract；它不 adoption inventory、不激活 runner、不授权 SSH/Slurm 或后续 44-unit batch。effect-free rediscovery 必须消费 deployment/qualification safe fields 重建 target subject，随后仍需新的 qualification dry plan 与独立 occurrence authority。

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
5. 在首次 preparation effect 前暂停；用户批准 exact preparation-plan digest、batch 与 operator 后，才创建持久一次性的 preparation occurrence authorization；后续只能恢复同一 occurrence，或通过 exact revocation 显式撤销。
6. Preparation 完成后重新观察 subject identity，重建 authorizable qualification dry plan。
7. 为 Diannan exact `/home/grtresy/.local/libexec/openzyme-workspace-runtime` 生成独立 deployment plan；只有 principal/home/path、direct-user-libexec mechanism、pre-state、backup 和 rollback owner 全部闭合并获得一次性 authority 后才执行原子安装与 native positive/negative probe，失败按 exact digest 回滚。
8. effect-free 重建 target subject 和 44-unit Batch 1 plan，再次取得 exact、持久一次性的 qualification-plan occurrence authorization，分 unit执行真实 qualification、settle/reconcile、验证 receipt；只能恢复同一 occurrence 的已持久化终态，禁止 redispatch，也允许 exact 私有撤销。任何未闭合 profile 保持 blocked。
9. 完成真实资格后同步/归档本 change，并进入 cutover 前第二个人工决策门。

helper 部署的回滚独立于产品 cutover：只允许 compare-and-restore exact backup，或 compare-and-remove 本 occurrence 首次创建的 exact helper；不得删除未知文件。其他真实 occurrence 开始后的回滚只能停止新 dispatch、reconcile 已知 attempt、执行声明的 cleanup，并保留证据。

## Open Questions

以下不再是 candidate 选择问题，而是已批准 preparation plan 必须产生的 exact identity outputs：

- Tavily exact service/account locator identity。
- 本地隔离 Git repository 与 local LFS endpoint；禁止 hosted sync。
- Podman 各科学工具 qualification image digest 或建设方案。
- `Diannan/3090` 的 executor workspace v2 profile、inventory/proof、credential provider/authenticator 与 Slurm account/QOS。
- Diannan observed home、principal-owned `.local/libexec` parent identity 与 direct-write preflight；任一漂移时保持 `blocked_deployment_authority`，不得回退到 `/usr/local`、`PATH` 或另一用户目录。
- local/HPC HMMER、Vina、fpocket、preprocess software closure。
- AlphaFold GPU image、model parameters、database closure 和固定 smoke input。
- protected SQLite ledger 与 private evidence root 的部署位置（只在 operator config 中记录，不进入公共 artifact）。
