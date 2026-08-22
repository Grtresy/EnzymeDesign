> 本 change 的工件完成只表示 apply-ready。以下实现任务必须在同一 source identity 上同时闭合代码、配置、migration、测试和文档；任何阶段不得启动 live LLM、Tavily、HPC、Chrome、MICU 或 AOX campaign，也不得把临时兼容层当成最终 authority。

## 1. 冻结拆分前基线与 owner inventory

- [x] 1.1 从根 `pyproject.toml`、所有 member `pyproject.toml`、实际 `src/`/entry point/launcher/config 生成唯一 component inventory，记录 distribution、namespace、用途、依赖和当前 composition owner。
- [x] 1.2 生成当前 Python import dependency graph，逐条登记 `openzyme-core -> research/runtime`、`runtime -> research`、Host -> AOX/HPC/runner、CLI -> runtime 等反向依赖，并保存 source-bound baseline。
- [x] 1.3 清点 SQLite schema、migration asset、repository class、table/index/trigger/FK，形成每个对象唯一的目标 owner 与“本 change 不重命名表”的 table-owner manifest。
- [x] 1.4 清点全部 tool、route、projection、worker、finish validator、schema/event、pytest marker 和 qualification scenario，形成当前 catalog identity、目标 Plugin owner、Adapter slot 与 Driver 归属图。
- [x] 1.5 只读清点当前部署 proof、Session contract pin、non-terminal Session、saved continuation、unsettled ControlledOperation、workspace backend、authority lease、HPC target qualification 和 Plugin-owned rows，定义离线分类输入；不得修改运行状态。
- [x] 1.6 在当前 source identity 上运行并保存拆分前 focused non-live tests、`./scripts/check-mainline.sh` 与当前 executable architecture qualification 的有效范围，明确任何 skip/unproven/环境限制。
- [x] 1.7 新增 ADR `What is OpenZyme?`，固定“Contracts/Extension SPI -> Kernel -> Capability Plugin -> Product Plugin”语义所有权轴，以及“Kernel + Adapters + Plugins + Drivers + delivery surfaces = Distribution”部署组合轴；明确 Standard/EnzymeDesign 都是 Distribution 而非语义层。
- [x] 1.8 建立 source-to-document traceability registry，把每个 owner/seam 绑定到 `docs/OpenZyme架构设计.md`、相关 `docs/v3/`、package/app README、operator/deployment 文档和可执行测试。
- [x] 1.9 记录“无仓外消费者”与“当前保留 Git-shaped revision contract”两个已确认决策，并把未来多 backend/仓库拆分列为独立后续 change 而非隐藏任务。
- [x] 1.10 为所有 inventory、ADR、baseline 和 traceability 文件增加 schema/完整性测试，拒绝重复 owner、孤儿对象、缺失 source ref 和过期路径。
- [x] 1.11 建立四类 capability 事实基线：ExtensionCapabilityFact、ResourceCapabilityFact、AuthorityGrant/现有 AgentCapabilityLease、当前静态 tool visibility，记录各自 writer、变化频率、持久化和被混用的位置。
- [x] 1.12 建立 Workspace Runtime 基线，逐条登记本地/HPC workspace identity、Shell/CRUD/transfer、credential、scheduler、effect/reconcile 和 cleanup 当前调用路径及目标 Port/Plugin/Adapter owner。

## 2. 建立目标 wheel、Distribution 配置与依赖门禁

- [x] 2.1 在 uv workspace 中创建 `openzyme-contracts`、`openzyme-extension-spi`、`openzyme-kernel`、`openzyme-store-sqlite`、`openzyme-workspace-git-lfs`、`openzyme-runtime-spi`、`openzyme-runtime-llm`、`openzyme-process-podman`、`openzyme-client` 和 `openzyme-standard` 的 src-layout wheel 骨架。
- [x] 2.2 创建 `openzyme-reporting`、`openzyme-science`、`openzyme-compute`、`openzyme-execution-contracts`、`openzyme-execution-sdk`、`openzyme-hpc`、`openzyme-hpc-ssh`、`openzyme-hpc-slurm` 及目标 `enzymedesign-*` wheel 骨架，并为每个 package 声明唯一 namespace 与 component kind。
- [x] 2.3 在可选 `distributions/` 配置目录创建 Standard 与 EnzymeDesign manifest/schema 骨架；继续只把 `packages/`、`apps/` 作为 Python workspace roots，不创建新的 Python `extensions/` 或 `products/` 根。
- [x] 2.4 更新根 workspace/source mapping/lock 配置，移除漂移的旧 component 名称并证明每个新 member 可独立 build；不得先删除仍有 caller 的旧 member。
- [x] 2.5 实现 AST/import-linter 规则：Kernel 只能依赖 Contracts/Extension SPI；Adapter 只能实现其 Port；Plugin 只能依赖 SPI、公共 Kernel application contracts 与 capability contracts；Product Plugin 不得依赖 provider internals；Distribution composition root 采用精确 allowlist。
- [x] 2.6 实现 component-kind 门禁，拒绝 Adapter 声明顶层业务 entity/tool、Driver 脱离所属 Plugin 激活、Distribution 拥有 canonical state，以及 Standard 被源码或文档当作语义依赖层。
- [x] 2.7 建立按 owner/package 的 forbidden dependency 与 forbidden vocabulary matrix，覆盖 FastAPI/LangChain/Provider/Tavily/Biopython/NumPy/RDKit/Meeko/Podman/SSH/Slurm 及 AOX/HMMER/Vina/fpocket/AlphaFold 等边界。
- [x] 2.8 实现 wheel build/`METADATA`/content/import 检查，在独立临时环境验证 Contracts+SPI-only、Kernel-only、Standard-only、runner-only 和 EnzymeDesign 安装闭包。
- [x] 2.9 建立 temporary re-export ledger，逐 symbol 记录旧 namespace、canonical 新 owner、caller、引入/删除阶段和测试；禁止未登记 shim 与双 implementation。
- [x] 2.10 加入 `archive/`、archived migrations 和 historical verifier 的 active import/test/entry-point 排除门禁，保留显式离线历史读取但不进入产品路径。
- [x] 2.11 为依赖图、component kind、wheel 闭包、forbidden vocabulary、shim ledger 和 archive path 编写正负向测试，包括间接 dependency 与 import side effect。
- [x] 2.12 同步根 README、开发/构建文档、component inventory 和主架构双轴包图，确保所有示例路径/命令对应已创建的实际 member 与 Distribution manifest。

## 3. 抽取 implementation-free Contracts 与 Extension SPI

- [x] 3.1 从 `openzyme-domain` 迁移 Project/Session/Task/Lane/Agent/Protocol/Approval/AgentAuthorityLease 的核心 ID、枚举和 DTO；公开 `@2` 不导出 AgentCapabilityLease，现有物理表名先由 store/migration ledger 保留。
- [x] 3.2 迁移通用 FailureObservation/error code/effect certainty、ToolSpec/ToolResult、catalog identity、EvidenceRef 和 canonical digest helpers，删除实现库类型泄漏。
- [x] 3.3 在 Contracts 定义 ExtensionCapabilityFact、ResourceCapabilityFact、AuthorityGrant/AgentAuthorityLease、ToolAffordance、RouteRef、SessionCapabilityBindingRevision 与 layered digest 基础 DTO，四类事实不得互为证明。
- [x] 3.4 定义 repository/UoW、runtime、workspace/revision、controlled-operation、clock/id、event/outbox 和 Plugin participant 所需的 implementation-free Protocol/application ports。
- [x] 3.5 把 runtime command/outcome需要的纯协调DTO与 process/provider-free failure contract迁入Contracts/SPI边界，并验证没有LangChain消息或process handle穿透。
- [x] 3.6 将 Scientific、Report、Research、Compute/HPC、HMMER/Vina 和 EnzymeDesign DTO 从基础 Contracts 候选集中剔除，分别放入其 owner contract package。
- [x] 3.7 收紧 `openzyme-contracts.__init__` public exports 和pyproject依赖，加入import-time无I/O、closed serialization和跨wheel兼容测试。
- [x] 3.8 为旧 `openzyme_domain` 核心symbol建立单向临时re-export与caller迁移测试，并禁止新代码import旧namespace。
- [x] 3.9 更新 Contracts README、主架构、`docs/v3/02-control-plane.md`、public contract/failure 文档，逐项描述 identity、owner、lifecycle、compatibility 和禁止实现依赖。
- [x] 3.10 在 `openzyme-extension-spi` 定义 closed Adapter/Plugin/Driver/Distribution manifest schemas，以及 tool/capability/route/qualification/projection/worker/validator/schema/migration contribution protocols。
- [x] 3.11 定义 Plugin 可用的 narrow Kernel application service contracts：Task、Protocol、Approval、Authority、Publication、ControlledOperation、Continuation、Failure、CapabilityQuery、ExtensionInvocation 与 TaskEvidence；禁止 CoreRepositories/raw connection/Host internals。
- [x] 3.12 定义 subordinate Driver contract，绑定 owning Plugin、route kind、所需 Adapter Ports 和 exact digest；禁止 Driver 单独拥有顶层 tool/state namespace。
- [x] 3.13 定义 restricted ExtensionTransactionParticipant 与 immutable command context，禁止任意 `on_any_event` hook 和事务内 Provider/Git/process/SSH/scheduler I/O。
- [x] 3.14 收紧 `openzyme-extension-spi` wheel 依赖和 exports，增加 closed manifest、unknown field、concrete type leakage、import-time I/O 与独立安装测试。
- [x] 3.15 更新 Extension SPI README、Plugin authoring guide、主架构与 `docs/v3/03-capability-engines.md`，同步公共 service、contribution、Driver 与禁止 authority。

## 4. 建立唯一 Kernel application owner、能力解析与 Workspace Runtime 语义

- [x] 4.1 迁移 Session/Task/dependency/lane/Agent roster/delegation/inbox/protocol/conversation/Memory/retirement application services，保持显式 `task.finish` 与事务语义。
- [x] 4.2 迁移 Approval、AgentAuthorityLease、operation-specific AuthorityGrant、owner/generation/lease/fence、mutation writer/quiescence/settlement 和 durable event 应用逻辑，全部只依赖 Contracts Ports。
- [x] 4.3 迁移 AgentRuntimeSignal/claim、SessionRuntimeLease、bounded RuntimeCommand/Outcome消费、continuation delivery、process epoch/fence和runtime settlement协调逻辑。
- [x] 4.4 迁移 ProjectRepositoryBinding identity/session pin、WorkspaceGeneration、checkpoint/publication intent、PublishedRevision、RevisionPathRef、handoff和generic EvidenceRef状态机。
- [x] 4.5 迁移 generic ControlledOperation admission/approval/identity/effect certainty/observe/reconcile/deadline/cancel/result/receipt状态机，并删除能力特定reducer。
- [x] 4.6 迁移 domain-neutral ToolRouter、schema validation、declared catalog/invocation identity 和 failure envelope，确保 Kernel base catalog 没有 Research/Science/HPC/AOX 分支且 duplicate tool 不再覆盖。
- [x] 4.7 实现generic finish-validator registry与只读validation result，确保只有Task owner显式 `task.finish` 能写终态，validator/receipt/runtime/publication不能自动完成。
- [x] 4.8 删除 `DeepResearchTaskPlanner` 及 `task.kind == "research" -> deep_research.start` 路径，删除Kernel对engines/research/runtime implementation的imports和pyproject dependencies。
- [x] 4.9 将report/scientific/revision-execution/HPC/AOX实现移出Kernel exports；在迁移窗口只保留ledger登记的单向shim，不复制逻辑或repository。
- [x] 4.10 收紧Kernel wheel依赖与public exports，证明无SQLite/FastAPI/LangChain/provider/Git执行/容器/科学/HPC依赖且import不触发I/O。
- [x] 4.11 建立Kernel-only deterministic fake repositories/runtime/workspace/effect adapters，覆盖协作、authority、restart/fence、publication/handoff、operation和explicit finish正负例。
- [x] 4.12 同步主架构及`docs/v3/00-harness-doctrine.md`、`01-target-architecture.md`、`02-control-plane.md`、`03-capability-engines.md`、`05-agent-runtime.md`、`06-top-level-llm-loop.md`和complexity audit，删除Core自动选择领域策略的旧描述。
- [x] 4.13 实现 ExtensionBundleRegistry 与 CapabilityRegistry，只接收已验证的 SPI descriptors 和安全 capability facts，不 import Plugin/Adapter runtime。
- [x] 4.14 实现 package-independent dependency resolver，支持 capability ID、contract/version、operation、same-target 与 multi-route constraint，拒绝 missing/incompatible/ambiguous/cyclic graph。
- [x] 4.15 从 Kernel base tools 与 activated Plugin manifests 构建 deterministic DeclaredToolCatalog，保留 owner/schema/governance/required authority/capability/digest 并对 canonical collision all-or-nothing 失败。
- [x] 4.16 实现 ToolAffordanceResolver 与 closed states，按 Session bundle、capability binding、Agent authority、workspace readiness、task/role policy、route/health/approval 生成 subject/turn snapshot。
- [x] 4.17 让模型 function list 只包含 `AVAILABLE`/`AVAILABLE_WITH_APPROVAL`；实现安全 `capabilities.inspect`，blocked 显示 typed blocker，HIDDEN 对 function list 与 inspection 同时不可见。
- [x] 4.18 实现 explicit `route_id` admission 和 dispatch revalidation，漂移统一返回 `tool_affordance_stale`、`effect_certainty = no_effect`、`fallback_performed = false`，continuation 不迁移 route。
- [x] 4.19 实现 immutable SessionCapabilityBindingRevision 与 operator/admin-only publish/adopt/revoke command；Agent 只能选择当前 binding 中 route，不能自动采用 inventory generation。
- [x] 4.20 定义 WorkspaceRuntimeBinding、WorkspaceObservationPort、WorkspaceFilesystemPort、WorkspaceProcessPort、WorkspaceTransferPort 及 root-relative request/receipt/failure contracts，不合并 AgentGitWorkspace 与 ExecutorHpcWorkspace 生命周期。
- [x] 4.21 把 filesystem mutation、process exec 与 transfer 接入 durable ControlledOperation；status/stat/list/read/hash 保持 query-only，拒绝 absolute/parent/glob/link escape、interactive/background/unbounded process。
- [x] 4.22 新增 capability four-fact、cycle/collision、catalog/affordance、hidden/redaction、route omission/stale、operator binding、workspace path/effect 和 no-fallback Kernel fake-Port 测试。
- [x] 4.23 更新主架构及 `docs/v3/02-control-plane.md`、`03-capability-engines.md`、`04-public-interfaces.md`、`05-agent-runtime.md`，完整描述四类事实、分层 digest、route/affordance 与 Workspace Runtime contracts。

## 5. 迁出 SQLite store、migration 与受限 extension state

- [x] 5.1 将Core repository实现、repository provider、connection lifecycle和schema bootstrap从旧Core迁入`openzyme-store-sqlite`，Kernel tests仅通过ports使用它。
- [x] 5.2 实现短 `BEGIN IMMEDIATE` Unit of Work、single-writer/fence、all-or-nothing event/outbox语义并迁移现有repository focused tests。
- [x] 5.3 将现有schema/migration按table-owner manifest拆为Core与extension bundle；保持既有业务表名/字段/状态含义，不在本change做命名DDL。
- [x] 5.4 为公开 AgentAuthorityLease 建立 store mapping，在不改首轮物理 capability lease table 名的前提下验证 row/state 序列化、owner、generation、fence 和 migration ledger 一致。
- [x] 5.5 实现 closed migration catalog 与 owner validator，拒绝重复/孤儿 table/index/trigger/FK、跨 namespace DDL 和 digest drift。
- [x] 5.6 实现 `ExtensionStateStore` 与 SQLite wrapper/authorizer，只允许声明 namespace，禁止 Kernel/其他 Plugin/ATTACH/未声明 PRAGMA 或 DDL 访问。
- [x] 5.7 实现 `ExtensionTransactionParticipant` prepare/apply/result 及 statement/time budget，使 Kernel 与 Plugin 写入同一短事务且 participant 失败全量 rollback。
- [x] 5.8 持久化 Extension bundle、各 catalog identity、SessionCapabilityBindingRevision、TargetCapabilityFact 安全索引与 ControlledOperation workspace receipts，禁止把 transient health 写入 release proof。
- [x] 5.9 升级 startup read-only verifier 与 deployment schema proof，使其在 writer/Plugin import 前验证 Kernel/Plugin migration、Adapter/Extension bundle 和 table ownership。
- [x] 5.10 增加 fresh Kernel-only、fresh EnzymeDesign、authority legacy-table mapping、existing-table adoption、namespace 越权、participant rollback、binding monotonicity、schema drift 和 startup 零 mutation 测试。
- [x] 5.11 同步 store README、schema/migration/operator 文档、`docs/v3/02-control-plane.md`、persistence/failure-recovery 文档和 table-owner source refs。

## 6. 迁出 Git/LFS 与本地 Workspace Runtime Adapters

- [x] 6.1 将 repository provisioning/storage/binding mechanism、credential issuance、private refs/hooks 和 transport 从旧 Core/Host 迁入 `openzyme-workspace-git-lfs`。
- [x] 6.2 将Agent workspace provision/recovery/generation/volume机制迁入adapter，保留owner/generation/lease/fence与recovery classification合同。
- [x] 6.3 将checkpoint和publication的Git命令、clean observation、push/sync/ref机制迁入adapter；Kernel只接收exact verification/receipt DTO。
- [x] 6.4 将Git LFS policy/object/link/closure/actual-byte verification/pin/GC和retention迁入adapter，保持commit/tree/OID/size identity。
- [x] 6.5 将RevisionPathRef native fetch、path/object verification和Gitless compute-tree preparation实现迁入adapter，禁止返回Host storage locator。
- [x] 6.6 定义并 pin `openzyme.workspace.git-lfs@1` backend identity/digest，纳入 Adapter bundle、deployment activation、Session pin 和 public release identity。
- [x] 6.7 删除Kernel中的git subprocess、filesystem root、credential、LFS store、mount和Podman workspace实现依赖与exports。
- [x] 6.8 迁移/新增clean publication、dirty rejection、later-private-dirty independence、LFS missing/tamper、restart/recovery、credential redaction和GC retention测试。
- [x] 6.9 同步workspace adapter README、repository operator文档、主架构与`docs/v3/00/01/02/04/05`文件原则，明确Git-shaped语义保留但机制owner已迁移。
- [x] 6.10 由本地 workspace/filesystem Adapter 实现 WorkspaceObservationPort 与 WorkspaceFilesystemPort，结构化支持 status/stat/list/read/hash/write/mkdir/move/copy/remove/apply-patch 及 content-digest precondition。
- [x] 6.11 在 `openzyme-process-podman` 实现本地 WorkspaceProcessPort，使用 exact argv、root-relative cwd、timeout、bounded stdin/stdout/stderr、process group cleanup 与 explicit shell argv。
- [x] 6.12 实现 WorkspaceTransferPort 的 revision sync/upload/download 受控机制，并与普通小文件 read/write、Git publication 和 workspace root cleanup 分离。
- [x] 6.13 实现 Kernel base `workspace.status`、`workspace.fs.read/list/mutate`、`workspace.exec` tool runtimes；Host 从 current Session/member/authority/generation 解析本地 binding，不接受 caller workspace ID。
- [x] 6.14 删除 local `workspace.exec` 的 HPC target/SSH credential issuance 与 remote locator 参数；任何远端操作必须进入 HPC Plugin 的独立工具命名空间。
- [x] 6.15 为每个 local exec/mutation/transfer 建立 pre-dispatch ControlledOperation、terminal receipt 与 response-loss reconciliation；禁止自动重试、target switch、checkpoint/publication/Task finish 推断。
- [x] 6.16 新增 structured CRUD path escape/glob/symlink、CAS mismatch、argv/shell、timeout/output bound、operation replay/restart、local-only credential 和 raw-receipt non-terminal 测试。
- [x] 6.17 同步 workspace/process Adapter README、base tool schemas/prompts、主架构与 `docs/v3/04/05`，删除“通过 workspace.exec 获取 HPC SSH”的全部 current 描述。

## 7. 拆分 runtime SPI、LLM 与 process adapter

- [x] 7.1 在 `openzyme-runtime-spi` 实现 closed `AgentRuntimeAdapter`、RuntimeTurnCommand/Outcome/failure DTO 和受限 capability gateway，确保只依赖 Contracts。
- [x] 7.2 让 Kernel runtime coordinator 构造并验证包含 Session/member/signal/runtime lease/fence/process epoch/budget、Distribution/Extension/DeclaredToolCatalog、SessionCapabilityBindingRevision 与 ToolAffordanceSnapshot identity 的 immutable command。
- [x] 7.3 实现outcome closed-schema、once-only consumption、duplicate idempotency、stale/cross-Session/wrong-member rejection和continuation/settlement分离。
- [x] 7.4 将LangChain、model/provider选择、prompt/context、compaction、token/model limits和LLM diagnostics迁入`openzyme-runtime-llm`。
- [x] 7.5 将 Podman/capsule image、environment/mount、bounded stdout/stderr、process supervision 和 retirement 迁入 `openzyme-process-podman`；与 Agent LLM turn SPI 分开实现 ProcessIsolationPort。
- [x] 7.6 删除runtime SPI对Research及具体Provider/process实现的依赖，删除CLI/Kernel对旧`openzyme-runtime` implementation的imports。
- [x] 7.7 统一runtime/process failure mapping，保留stable code、phase、identity、effect/mutation/fallback、retry/reconcile、cause chain和diagnostic redaction。
- [x] 7.8 新增fake adapter、provider failure、no-silent-provider-switch、process nonzero/timeout、late epoch、duplicate outcome、step limit和Task不自动完成测试。
- [x] 7.9 为 LLM/process Adapter 分别声明 component manifest/config/preflight 和 implementation identity，禁止环境变量或可用 import 静默替换 Distribution 选择。
- [x] 7.10 同步各runtime README、配置/诊断文档及`docs/v3/05-agent-runtime.md`、`06-top-level-llm-loop.md`、failure/recovery与complexity audit。

## 8. 实现显式 component manifests、Distribution composition 与 activation registry

- [x] 8.1 实现 closed canonical Adapter/Plugin/Driver manifests、canonical bytes/digest 和 `openzyme.extensions` manifest-locator entry point；entry point 只返回纯 locator，不允许 import side-effect registration。
- [x] 8.2 实现 `openzyme-composition.toml` Distribution parser 与 closed schema，验证 Distribution/Kernel/Adapter slots/required+optional Plugins/Drivers/delivery surfaces 的 exact ID/package/version/digest。
- [x] 8.3 实现 deterministic Adapter bundle、Extension bundle、declared tool、route、projection、worker、validator、migration 和 qualification catalog 构建及独立 digest 重算。
- [x] 8.4 对 capability ID 的唯一 provider 约束、dotted tool、normalized method/path、projection contract、worker、validator、Driver ID 和 migration namespace 实现 all-or-nothing collision rejection；移除 EngineRegistry last-write-wins。
- [x] 8.5 实现 capability dependency graph 验证，拒绝 package-name dependency、missing/incompatible required provider、single-valued Adapter ambiguity、same-target conflict 与 direct/transitive cycle。
- [x] 8.6 实现 required/optional activation state：required absent 阻止启动；optional absent 为 inactive；contract-valid 但 resource route 不足为 degraded；任一 manifest/schema/digest/migration/collision/cycle 完整性错误均阻止 activation。
- [x] 8.7 实现 deployment activation epoch，在任何 repository writer、route、worker、runtime 或 external effect 前完成 read-only schema/composition/wheel验证。
- [x] 8.8 实现 Session composition pin，使创建时原子绑定 Kernel/schema、Adapter bundle、Extension bundle、declared tool/route/projection/migration、workspace backend、initial capability binding 与 Host-client epoch identities。
- [x] 8.9 在 message、drain、approval、tool、workspace、publication、operation 和 restore 入口实施 Session-pin/capability-binding fail-closed guard。
- [x] 8.10 实现 Plugin route/worker/projection/finish-validator/state participant 的受控 mount，禁止 Plugin 获得 Host internals 或 CoreRepositories；Driver 仅挂到所属 Plugin route。
- [x] 8.11 实现 Plugin 升级/移除 offline verifier，检查 non-terminal Session pin、continuation、owned rows、unsettled operation 和 state disposition；新增 Plugin 不热进入既有 Session。
- [x] 8.12 实现 discovery/activation/dependency/collision/namespace/participant/qualification-binding failures 的公共安全诊断与 private cause chain，禁止 secret/Host path 泄漏。
- [x] 8.13 增加 unlisted installed entry point、required missing、optional absent、optional invalid、resource degraded、version/digest/core-contract drift、cycle、每类 collision、import side effect 和 partial registration 负例。
- [x] 8.14 增加 Session restore bundle/binding drift、hot addition/replacement拒绝、inventory adoption revision、unused Plugin removal 和 pinned/unsettled Plugin removal拒绝测试。
- [x] 8.15 同步 composition/Extension SPI README、manifest schema reference、deployment/operator guide、主架构和 `docs/v3/01/02/03/04`，记录双轴模型、状态机、ambient capability 与 fallback 禁令。

## 9. 以 Research Plugin + Tavily Adapter 建立 reference composition

- [x] 9.1 将 provider-neutral Research request/source/evidence DTO、Provider Port 和 bounded orchestration迁入 `openzyme-research` Plugin contracts/state/services。
- [x] 9.2 将`deep_research.start` tool、engine/worker/projection和相关tests从`openzyme-engines`迁入Research manifest，不保留Host/Core硬编码注册。
- [x] 9.3 将 Tavily 迁入独立 Provider Adapter/optional Distribution selection，显式声明 owning Research Plugin、secret locator、configuration 和 controlled-operation mapping。
- [x] 9.4 将generic web/document/browser provider定义为可选adapter，验证provider absence/failure不触发silent fallback。
- [x] 9.5 将PubMed、Semantic Scholar和literature quorum迁入独立science-research capability；从base Research移除科学来源policy。
- [x] 9.6 将Research durable prose/index交接改为Agent workspace + explicit PublishedRevision/RevisionPathRef，保留provider transcript非publication/非Task evidence边界。
- [x] 9.7 删除旧`openzyme-engines`第二authority与Core/Runtime/Host对其Research实现imports，迁移全部caller和fixtures。
- [x] 9.8 新增Research absent/core-only、explicit Agent invocation、no task-kind auto-plan、provider lost response/reconcile、source provenance和published-file handoff测试。
- [x] 9.9 同步Research/provider README、tool/config/docs、`docs/v3/03-capability-engines.md`、runtime/prompt文档和主架构，删除Core自动Research路线描述。
- [x] 9.10 用 reference composition 证明 Adapter 替换不改变 Research state/tool semantics、Plugin removal 不改变 Kernel projection、optional Tavily 缺失不触发 Browser fallback。

## 10. 建立 OpenZyme Standard 官方 Distribution

- [x] 10.1 实现 `openzyme-standard` manifest/factories，显式选择 Kernel、SQLite、Git/LFS、default LLM 和 Podman process Adapters；required semantic Plugin set 固定为空，并证明 Plugin-free profile 可启动。
- [x] 10.2 收紧 `openzyme-host-api` 为通用 security/Kernel route/activation/Plugin mount composition root，删除 Deep Research、AOX finalizer/qualification、Science、Compute/HPC 和 runner 直接 imports。
- [x] 10.3 将Host中adapter-specific repository/Git/runtime construction迁入Standard factories，通过公开ports注入并保留startup fail-closed顺序。
- [x] 10.4 创建`openzyme-client`的`@2` HTTP DTO/client，迁移共享auth/contract/error handling且不依赖runtime/repository实现。
- [x] 10.5 让`openzyme-host-cli`只依赖Client/Contracts，迁移命令与tests并删除对旧runtime和Host内部service的依赖。
- [x] 10.6 将Web UI拆为Core shell与manifest-declaredextension renderer loader，Core reducer只消费`@2.core`并在bundle/renderer drift时阻止mutation。
- [x] 10.7 实现 Plugin-free Host/CLI/UI 启动和 Session/Task/Agent/Approval/AgentAuthorityLease/runtime/local workspace CRUD+exec/checkpoint/publication/handoff 完整 Kernel 路径。
- [x] 10.8 构建fresh Standard-only environment，证明不安装Tavily/Biopython/NumPy/RDKit/Meeko/SSH/Slurm/EnzymeDesign且不存在ambient extension。
- [x] 10.9 迁移Host/CLI/UI focused tests，新增absent-extension tool、route/projection、stale renderer和Core UI不读extension payload负例。
- [x] 10.10 同步Host/Client/CLI/UI/Standard README、启动配置和命令、主架构及`docs/v3/01/04`公共组合说明。

## 11. 迁出 Reporting extension

- [x] 11.1 将SessionReportDraft/ReportRecord/version/lifecycle repositories和services迁入`openzyme-reporting` contracts/state namespace。
- [x] 11.2 将report tools、format/section schema、renderer/validator workers和Host routes注册到Reporting manifest。
- [x] 11.3 将report正文约束为workspace file + PublishedRevision/RevisionPathRef，只保留bounded metadata并删除Core top-level report repository/projection。
- [x] 11.4 实现Reporting finish validator的read-only closed result，证明draft/render/publication/business report均不自动完成Task。
- [x] 11.5 将Reporting projection和UI renderer迁入`extensions[openzyme.reporting@1]`，加入budget/pagination/redaction和renderer digest。
- [x] 11.6 增加extension absent、dirty private path、renderer drift/failure、exact report version、finish rejection/acceptance和Task terminal分离测试。
- [x] 11.7 删除Kernel/Host/Standard中的report-specific imports/exports/tables owner和旧`@1`顶层写路径，只保留迁移ledger允许的临时shim。
- [x] 11.8 同步Reporting README、tool/format/route/UI文档、主架构、`docs/v3/02/03/04/05`和report验收说明。

## 12. 迁出 Science extension

- [x] 12.1 将ScientificAttempt/Selection/Occurrence/Disposition/Adoption/Deliverable/validation/closure DTO从Domain迁入Science contracts。
- [x] 12.2 将attempt lifecycle、selection evaluation、rollover、adoption、deliverable finalization和formal closure services/repositories迁入Science namespace。
- [x] 12.3 将Science workflow registry、tools、workers、projection、routes和migration bundle注册到exact Science manifest。
- [x] 12.4 用Kernel authority/context + restricted participant重连Science mutation，删除Science对CoreRepositories/raw SQLite/Host internals的访问。
- [x] 12.5 保持ScientificDeliverable绑定PublishedRevision/RevisionPathRef和exact workflow/attempt identity，删除artifact/Host path/materialization兼容。
- [x] 12.6 实现Science finish validator并证明attempt closure/receipt/deliverable/runtime wake均不自动完成Task。
- [x] 12.7 将AOX-specific references/roles/threshold/finalizer contract从base Science剥离到EnzymeDesign注册面。
- [x] 12.8 将Science投影/UI renderer放入`extensions[openzyme.science@1]`，Core runtime/reducer不得读取scientific字段选择策略或terminal。
- [x] 12.9 迁移现有scientific focused tests并新增extension absent、cross-attempt/generation/Session、stale fence、atomic rollback和finish separation负例。
- [x] 12.10 同步Science README、lifecycle/migration/tool/projection文档、主架构、`docs/v3/01/02/03/04/05`与scientific验收文档。

## 13. 迁出 Compute、Target Inventory、HPC 与 runner contracts

- [x] 13.1 抽取 `openzyme-execution-contracts` closed wire DTO，仅包含 typed workload/request/observe/cancel/result/opaque handle/failure 与 exact route/inventory identity，并只依赖 implementation-free contracts。
- [x] 13.2 让 `mcp-hpc-runner` 仅依赖 execution wire contracts，删除对 `openzyme-domain`、Kernel、Host、Science 和 EnzymeDesign 的 imports/metadata。
- [x] 13.3 将 revision-bound formal execution admission/request/repository/worker/result lifecycle 迁入 `openzyme-compute` Plugin namespace 和 manifest。
- [x] 13.4 定义 closed `ExecutionWorkloadSpec`，绑定 workload contract、argv/entry point、root-relative cwd、resource/environment policy、RevisionPathRefs、result contract 与 capability requirements；禁止 SSH/Slurm client、credentials、remote/Host paths 和 domain objects。
- [x] 13.5 将 Compute dispatch/observe/reconcile/cancel 接入唯一 Kernel ControlledOperation，删除重复 effect certainty/retry/cancel 状态机并保持 exact route 无替换。
- [x] 13.6 从 `openzyme-pipeline` 抽取无生物依赖的 `openzyme-execution-sdk` control-socket/revision/workload protocol 及 closed errors。
- [x] 13.7 实现 immutable `TargetToolchainInventory`、TargetCapabilityFact、SoftwareQualificationReceipt、InventoryGeneration 与 aggregate closure digest；迁移现有 opaque toolchain digest 为可解释 closure。
- [x] 13.8 让 Tool Plugin 通过 SPI 声明 versioned QualificationSpec，包括 version query、deterministic smoke、expected schema、software/hardware/dataset/asset/license requirements，但 import/turn 不执行 probe。
- [x] 13.9 实现 operator-controlled target qualification workflow，由选定 Adapter 在 exact target/environment 执行 probe，使用 ControlledOperation/reconcile 并仅向 Kernel 发布安全 fact/digest。
- [x] 13.10 实现 operator/admin-only inventory publish/adopt/revoke 与 SessionCapabilityBindingRevision；Agent turn 不得 SSH/`which` 探测、缓存 unbound version 或采用新 generation。
- [x] 13.11 区分 qualification validity 与 transient health；expired/revoked/down 阻止新 dispatch，queue busy 但 scheduler 接受工作时 route 不消失，health 不改变 release digest。
- [x] 13.12 将 executor HPC workspace provisioning/generation/credential/opaque owner view/sync/retention/cleanup 迁入 `openzyme-hpc` Plugin。
- [x] 13.13 在 HPC Plugin 注册 `hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec`，所有后续调用携带 opaque workspace ID 并重验 owner/local+remote generation/target/qualification/operation authority。
- [x] 13.14 将 SSH process、SFTP filesystem、rsync/scp transfer 分别迁入 `openzyme-hpc-ssh` subordinate Adapters，并支持 root confinement、bounded result 与 dispatch-in-doubt reconciliation。
- [x] 13.15 将 Slurm submit/observe/cancel 迁入 `openzyme-hpc-slurm` scheduler Adapter；login/file credential 永不包含 scheduler authority，formal occurrence credential 只由 Compute admission 创建。
- [x] 13.16 让 HPC Plugin 通过 Extension SPI 贡献 target inventory 与 workspace/compute routes；Compute/HMMER/Vina 不 import HPC/SSH/Slurm implementation。
- [x] 13.17 删除 generic Compute/HPC contracts 中的 Host path、artifact catalog、implicit staging、raw scheduler ID/log、login alias/remote root public input 和 `expected_outputs` 要求。
- [x] 13.18 将 Compute/HPC projection/routes/workers/UI renderer 注册到各自 Plugin manifests，只公开 opaque workspace/route/operation/result safe facts。
- [x] 13.19 新增 runner-only fresh install、wire closed schema、clean/dirty revision、LFS closure、typed workload、route omission/stale、lost dispatch/cancel response、restart/reconcile 和 no-replacement 测试。
- [x] 13.20 新增 inventory immutable/qualification/adoption/expiry/health、no-turn-probe、HPC owner isolation、credential redaction、remote CRUD/exec response loss、scheduler separation 和 cleanup settlement 测试；不得运行 live SSH/Slurm。
- [x] 13.21 新增 raw HPC Shell receipt 不等于 formal Compute/Science/publication/Task evidence，以及正式 result 只 wake owner、由 Agent 显式检查提交发布的测试。
- [x] 13.22 同步 Compute SDK、runner、HPC/SSH/Slurm README/config examples、target qualification/operator guide、主架构、`docs/v3/execution-pipeline-docs/`、capability engine 和 failure/recovery 文档。

## 14. 抽出 EnzymeDesign Product Plugins 与 Distribution

- [x] 14.1 创建 versioned EnzymeDesign Distribution，显式选择 Kernel、Standard-compatible Adapter profile、Research/Reporting/Science/Compute/HPC Plugins、Drivers 与全部垂直 manifest/digest；不得把 Standard 当语义依赖层。
- [x] 14.2 将AOX workflow/scientific contract、fixed references、roles、threshold、motif、similarity graph、finalizer和qualification从Core/Host/Pipeline迁入`enzymedesign-aox`。
- [x] 14.3 将 UniProt、RCSB、InterPro、HMMER/hmmbuild/hmmsearch、sequence parsing 和 bio research tools 迁入 EnzymeDesign Product Plugins；HMMER manifest 按 capability ID/version/operations/same-target 声明依赖。
- [x] 14.4 实现 HMMER local/HPC Drivers，把正式 build/search 请求编译为 typed ExecutionWorkloadSpec 并验证 result contract；Driver 不直接 dispatch 或 import provider。
- [x] 14.5 将 fpocket、Vina、AlphaFold catalog 和结构/对接 tool specs 迁入 EnzymeDesign structure/docking Plugins；Vina manifest 依赖 Compute 与 `software.autodock-vina` capability。
- [x] 14.6 实现 Vina local/HPC Drivers，经 explicit route + typed workload + Compute lifecycle 执行正式 docking；raw Shell 结果仅标记 exploratory。Kernel-admitted `ToolDispatchBinding`、Distribution formal bridge 与声明式 runner Port 已由 19.4 闭合；durable result validation 与产品 qualification 由 19.5、19.8 单独验收。
- [x] 14.7 将 `preprocess-backend` 重归属为 EnzymeDesign docking preprocess，绑定 RDKit/Meeko/Open Babel 依赖与 vertical manifest。
- [x] 14.8 将 `openzyme-pipeline` 剩余 AOX calculations/reference resources/Biopython 依赖迁入 EnzymeDesign executor package，并删除旧通用 wheel 第二 authority。
- [x] 14.9 删除或重命名只含酶工具的 `openzyme-tools` 通用 surface，将全部 tool/spec/qualification/resource digest 由垂直 manifests 拥有。
- [x] 14.10 将 AOX qualification/finalizer/fixtures 从 generic Host 迁入 Product Plugin/Driver，由 EnzymeDesign Distribution 通过公开 Science 端口注入现有垂直 contribution；对 source inventory 中不存在的 vertical routes/workers/projections/UI renderers 保持精确为空，不虚构占位语义。
- [x] 14.11 对 EnzymeDesign AST/import 和 wheel 建立反向依赖门禁，禁止 Kernel repositories、SQLite implementation、Host internals、Git locator、HPC/Slurm internals 和 private runtime classes。
- [x] 14.12 建立 generic Standard absent-vertical 测试和 EnzymeDesign product composition 正向测试，证明增加 code-review 等非生物 Plugin 无需改 Kernel。Kernel composition 测试已激活独立 code-review Plugin；Standard 保持零 required semantic Plugin；真实 EnzymeDesign non-live 跨层场景由 19.2、19.3、19.8 闭合。
- [x] 14.13 迁移 AOX/HMMER/structure/docking/preprocess 现有单元与 non-live integration fixtures，覆盖 capability route、typed workload、raw-shell non-formal 和既有 scientific identity/acceptance 语义；不启动 live。组件 fixtures 与 formal HMMER/Vina 产品路径均已闭合，真实外部 runner/HPC 未启动。
- [x] 14.14 同步 EnzymeDesign 各 package README、product 部署/能力/tool/resource/qualification 文档、主架构和相关 `docs/v3/` Plugin 示例，删除旧 package/path/Host hardcode 描述。

## 15. 推出 `file_workspace_public@2`

- [x] 15.1 定义 closed `file_workspace_public@2` schema、media type 和 release block，分别绑定 Kernel contract/schema、Adapter bundle、Extension bundle、declared tool、route、projection、migration、workspace backend 与 Host-client build digests。
- [x] 15.2 将基础 projection 重构为 closed `core` section，仅保留 Session/Task/Lane/Agent/Protocol/Approval/AgentAuthorityLease/SessionCapabilityBinding/runtime/workspace/publication/operation/failure 等 Kernel facts；拒绝旧 AgentCapabilityLease 公共别名。
- [x] 15.3 实现 `extensions[plugin_contract_id]` projection assembly、schema/digest validation、authorization、global/section budget、pagination 和 redaction。
- [x] 15.4 将 Research、Reporting、Science、Compute/HPC 和 EnzymeDesign 数据迁出 `@1` 顶层字段，分别接入其 exact Plugin projection provider。
- [x] 15.5 实现 DeclaredToolCatalog 与 per-turn EffectiveToolCatalog/ToolAffordanceSnapshot 的公共/reflection 边界，以及安全 `capabilities.inspect` projection/query。
- [x] 15.6 升级 Host request/response、event envelopes/reducers、tool reflection、prompts、workflow manifests、restore/continuation 和 eval fixtures到 exact `@2` bundle/binding/affordance identities。
- [x] 15.7 升级 `openzyme-client`、CLI rendering 和 SDK contract guard，使任一 contract/catalog/bundle/backend/build/binding drift 在 mutation 前失败。
- [x] 15.8 升级 Web UI Kernel reducer/view/controller 和 Plugin renderer loader，覆盖 no-Plugin Standard、inactive/degraded Plugin、missing renderer、section drift、blocked affordance 和 artifact-era payload拒绝。
- [x] 15.9 公开 local `workspace.*` 与 opaque-ID `hpc.workspace.*` schema，禁止 local exec 携带 HPC credential/target，禁止远端输入/投影泄露 SSH host/login/root 或 scheduler handle。
- [x] 15.10 保留 Git-shaped commit/tree/ref/LFS/RevisionPathRef 在 Kernel contract 中，同时确保 Git credentials/roots/LFS locator 和 HPC private data不公开。
- [x] 15.11 冻结 `@1` 为 offline historical reader only，删除 current mutation、dual-write、online translation、automatic event/tool conversion 和 per-Session legacy mode。
- [x] 15.12 新增 `@2` closed-schema、catalog/affordance split、Plugin absence/degraded、bounded pagination、secret redaction、stale `@1`/bundle/binding/snapshot/renderer/continuation 和 unknown-effect测试。
- [x] 15.13 更新 public schema/JSON fixtures/TypeScript types/client snapshots，并证明移除 unused Plugin 时 Kernel projection 除 release identity 外语义不变。
- [x] 15.14 同步 `docs/v3/04-public-interfaces.md`、Host/CLI/UI/SDK README、contract migration 和 compatibility-sunset 文档，所有示例使用实际 `@2` shape、layered digests、authority 与 capability inspection。

## 16. 实现 offline composition/session cutover 与 deployment proof

- [x] 16.1 定义 `@2` deployment activation、Session composition pin、SessionCapabilityBindingRevision、table-owner/migration 和 offline cutover ledger schema/receipt 及 canonical digest。
- [x] 16.2 实现 non-mutating dry run，闭合 source/wheel/Distribution/Adapter/Plugin/Driver/schema/table/import/catalog/inventory/authority/workspace/Session/continuation/unsettled-effect inventory 和 expected disposition。
- [x] 16.3 实现 maintenance/quiescence verifier，证明 Host、所有 Plugin worker、runtime/process、runner、UI、SQLite/Git writer 停止且 unknown effect 不被丢弃。
- [x] 16.4 实现exact database/config/storage backup与independent verification，明确activation前rollback和activation后forward-only恢复边界。
- [x] 16.5 实现 table-owner adoption/migration，在不重命名现有业务表的情况下把旧 capability lease 行映射为公开 AgentAuthorityLease、加入 composition/session binding pin，并验证 row/key/FK/constraint/digest 等价。
- [x] 16.6 实现逐 Session 分类：exact `@2` migratable、closed historical `@1` 或 blocked；非终态 Session 任何 ambiguous Plugin/authority/inventory/continuation/effect 都阻止 activation。
- [x] 16.7 在单一offline transaction/closed sequence中提交migration与receipt，失败时全量rollback且不得生成complete proof。
- [x] 16.8 升级 fresh-install bootstrap，使 Plugin-free Standard 与 EnzymeDesign Distribution 产生各自 deterministic schema/composition receipt 且不创建未选 Plugin state。
- [x] 16.9 升级 startup read-only proof verifier，验证 installed wheels、Adapter/Extension/migration/catalog digests、Session pins、capability bindings 和 workspace backend 后才加载 runtime surfaces。read-only proof 本身保持 writer-disabled；19.3 的 application composition root 只在其通过后核对 Adapter、mount Plugin runtime 并构造 writer，missing Adapter 负例证明零 mutation。
- [x] 16.10 升级 device reset inventory/quiescence/deletion/bootstrap/reset receipts，按 component kind/owner/Distribution 精确归属并保留 Git/OpenSpec/source/current Git-LFS exclusions。
- [x] 16.11 增加 fresh Standard/EnzymeDesign、offline success、ambiguous Session、missing/invalid optional Plugin、authority mapping、inventory binding、table-owner drift、unknown effect、pre-activation rollback 和 post-activation no-downgrade 测试。
- [x] 16.12 同步offline migration、deployment、reset、rollback/forward-repair、startup error文档和`docs/v3/`persistence/compatibility/failure说明，不执行真实部署cutover。

## 17. 建立三种 composition profile qualification 与代码—文档一致性门禁

- [x] 17.1 升级 architecture invariant registry schema，加入三个 closed profiles、双轴 owner/import/wheel/document refs、layered composition digests 和 allowed external Ports。
- [x] 17.2 实现 `kernel_fake_adapters@1` 全量场景和预算，验证 Kernel 不 import/启动 SQLite/Git/Host/runtime implementation/Plugin，同时覆盖 authority、capability/affordance、workspace contract 与 controlled operation。
- [x] 17.3 实现 `openzyme_standard_local_file_sqlite_git@1` 真实 Plugin-free Host/SQLite/local Git-LFS/client/Kernel UI 场景和 restart/fencing/local workspace oracle。
- [x] 17.4 实现 `enzymedesign_local_single_process_file_sqlite@1` 真实 Distribution/Plugin/Driver composition 场景，只替换登记的 LLM/provider/runner/Chrome/process external Ports。catalog-only 场景已与真实 product cross-layer 场景分离；后者使用 generic Host、真实内部 runtime mount 和声明式 non-live Agent-turn/revision/runner Ports。
- [x] 17.5 把dependency graph、pyproject/lock、wheel metadata/content/fresh import、forbidden vocabulary和archive exposure纳入machine report。
- [x] 17.6 把 Plugin add/remove/required-missing/optional-absent/resource-degraded/invalid/drift/collision/cycle/namespace/participant/Session-pin/ambient capability 负例纳入 closed scenario selection。
- [x] 17.7 把四类 capability facts、operator inventory adoption、qualification validity/health、declared/effective catalog、全部 affordance states、explicit route 与 dispatch stale 负例纳入 closed selection。
- [x] 17.8 把 local/HPC Workspace Runtime、structured path safety、operation receipts/response loss、opaque ID、scheduler separation 与 raw-shell non-formal 负例纳入 closed selection。
- [x] 17.9 把拆分前 authority、lease/fence、effect certainty、restart/reconcile、boundedness、redaction、revision handoff 与各类 terminal 分离不变量映射到拆分后 owners。19.5—19.7 已补齐 Compute、Workspace 与 Slurm 的 Store-owned durable occurrence/receipt/handle recovery；19.8 再以真实产品组合验证 revision/route/result/continuation 与 Task 终态分离。
- [x] 17.10 实现 source-to-document drift 检查，验证 owner、identity、lifecycle、persistence、compatibility、error、forbidden fallback、命令/路径/配置与当前 source 一致，而非关键词扫描。
- [x] 17.11 更新 qualification runner/verifier/report schema 与 resource manifest，使报告绑定 OpenSpec、source、wheels、Distribution/bundles/catalogs/inventory/schema/docs/test selection 和 budget digests。
- [x] 17.12 增加 no-network/no-live guard；任何未声明 socket/SSH/Slurm/provider/Chrome/MICU/container effect、skip 或 xfail 使 profile 失败。
- [x] 17.13 更新 `./scripts/check-mainline.sh` 的 bounded package/profile gates 并保留 final full qualification 独立性；不得把 mainline subset 描述为 cutover proof。
- [x] 17.14 同步 qualification README、invariant registry refs、主架构、`docs/v3/harness-complexity-audit.md` 和开发测试命令说明。

## 18. 删除旧 authority 并完成最终验收

- [x] 18.1 对temporary re-export ledger逐项迁完caller并删除shim、旧implementation/export/entry point；证明`openzyme-domain`、旧Core/Runtime/Engines/Tools/Pipeline不再是第二authority。
- [x] 18.2 删除generic Kernel/Host/Standard中的AOX/HMMER/Vina/fpocket/AlphaFold/RDKit/Meeko/Biopython/Slurm/Tavily垂直imports，确认它们只存在于声明extension或archive/qualification allowlist。
- [x] 18.3 运行所有受影响 package/app focused pytest、Host API 回归、`uv run python -m openzyme_host_api.evals`、Web UI `npm test`/build 和 runner wire tests，记录 exact selection/result。修复后的受影响包集合为 269 passed；`./scripts/check-mainline.sh` 又覆盖完整 non-live Python、Host、runner、Web UI test/build 并产生 verified pass receipt。
- [x] 18.4 构建并在 fresh environments 安装全部目标 wheels，重算 dependency/import/content/component manifests、Adapter/Extension bundles 与 catalogs，并验证 Contracts+SPI-only、Kernel-only、Standard-only、runner-only 和 EnzymeDesign 闭包。2026-08-22 最新 source 的 37 个 component wheels 全部构建，五个 fresh profile 均 pass，`network_used=false`、`external_effects_real=false`。
- [x] 18.5 运行三种 profile 的完整 non-live architecture qualification，要求所有 required scenario 执行、零 skip/xfail/undeclared effect、零 open owner/document drift 和全部 invariant satisfied。最新 diagnostic report payload `sha256:5a2d431bda66536e71c43ba26fe1e3796c49ab4261638b7e067c282f808afa9c` 为 28/28 scenario、28/28 invariant satisfied，独立 verifier `valid=true`；dirty diagnostic source 仅拒绝 admission，不影响本项行为资格结论。
- [x] 18.6 运行 `./scripts/check-mainline.sh` 与本 change/受影响 spec 的 strict OpenSpec validation，分开记录命令成功与任何非权威 telemetry 失败。mainline receipt `sha256:79354555b69939b9e679b48324b750f79cb98ed5bf63bc600b1774d23c405710` 为 authoritative pass；strict OpenSpec 返回 `valid=true`，PostHog `EAI_AGAIN` 仅为非权威 telemetry。
- [x] 18.7 从当前 source/config/schema/manifest/wheel 反向审计 `docs/OpenZyme架构设计.md`、全部相关 `docs/v3/`、package/app README 和 operator docs，修复所有 stale owner/path/command/contract/fallback 描述后重跑受影响 gate。文档已统一 `selected`、`runtime_mounted`、`qualified`、`cutover`、`live`，并与产品 runtime、durable reconciliation、SSH helper qualification 和 Slurm ledger 实现对齐。
- [x] 18.8 执行 requirement-by-requirement 与 scenario-family 审计，把本 change strict validation 得到的全部 delta requirements 映射到直接 source/test/doc evidence；任何 unproven 项恢复为未完成，不使用硬编码旧计数。`requirement-evidence.md` 覆盖 18 个 delta specs/162 requirements，`behavior-test-disposition-ledger.md` 覆盖旧行为语义处置，closed registry 由当前内容重算为 28 scenario/invariant；clean-source completion/admission 由 18.10/19.12 独立闭合。
- [x] 18.9 仅在明确的后续cutover授权和quiescent环境中执行real offline `@2` migration/activation proof；本change的普通代码实施、测试或文档完成不得自行修改真实部署或启动live。
  - 2026-08-21 第二次 reset 已在提交 `5548ca85b0b581584379b4810e0777a6d97683b6` 上取得单独授权并完整执行：Store-owned executor 在任何删除前冻结数据库与空 repository-service 的 4 项 inventory，逐项生成 durable occurrence，随后以 exact 31-wheel EnzymeDesign 闭包 fresh bootstrap，并由独立只读进程和 zero scan 复核。正式 receipt 为 `sha256:f523f08d26b928395c2d9269163b699f7feba954cce089a0045ea60544d20bcc`；第一轮缺失子项日志的历史事实不被补造或改写。详见`operator/device-fresh-install-20260821.md`。
- [x] 18.10 在exact clean final source上生成completion evidence，确认代码、配置、migration、OpenSpec、文档、wheels和qualification同一identity后才允许archive；不得因artifacts apply-ready、旧receipt或单一绿色gate提前完成。20.x correctness 修复后的 seal SHA 已按整组门禁复跑；最终 SHA/报告/digest 仅记录在 checkout 外的交付说明中，避免仓内证据自引用。第二次 reset receipt 保持独立有效且本轮未重置数据库。

## 19. 审计纠偏与产品运行闭环修复

- [x] 19.1 建立 source-bound implementation gap audit，区分 manifest/catalog activation、runtime mount、formal product execution、external live cutover 和 final acceptance；恢复被当前行为反驳的 checkbox，并保留 18.9 第二次正式 reset 的独立有效性。
- [x] 19.2 为 EnzymeDesign 所选 required Plugins/Drivers 构建 exact runtime contribution bundles，闭合 manifest 声明的 tool、route、projection、worker、validator、migration 与 transaction participant；缺失或多余 surface 必须在 mount 前失败。当前 exact non-live mount 闭合 32 tools、13 capability routes、2 HTTP routes、5 projections、5 workers、2 finish validators 与 3 transaction participants；故意删除 HMMER route 会以 `plugin_runtime_surface_incomplete` fail closed。
- [x] 19.3 实现 `build_enzymedesign_application_runtime(...)` 与通用 Host 组合入口：先验证 exact startup proof，再核对 8 个 selected Adapter runtime bindings、mount exact Plugin surfaces、闭合 37 个 Kernel/Plugin tool runtimes，并绑定 bounded runtime gateway、Kernel command routes、worker/projection/validator；SQLite writer 仅在全部成功后构造。真实 Session bootstrap 与 missing-Adapter no-mutation 负向测试均通过，且 EnzymeDesign 不依赖 `openzyme-standard`。
- [x] 19.4 实现 HMMER 与 Vina 的生产 application bridge，使 formal invocation 经 subordinate Driver 编译 typed workload、重验 exact affordance/route、进入 Compute ControlledOperation lifecycle 并通过声明的 runner Port；禁止直接 import SSH/Slurm/HPC internals、自动换 target、redispatch 或把 tool success 推断为 Task/Science terminal。新增 admitted-tool SPI 将 exact authority/workspace/route/driver/inventory proof 从 Kernel gateway 传给 Plugin；两个产品工具的 non-live 测试均证明 Driver argv、Compute admit/observe、单次原 route dispatch 与 `task_finished=false`。
- [x] 19.5 为 Compute 和需要 durable extension state 的产品路径选择并实现 SQLite-backed repositories/UoW 绑定，证明 Host restart 后 invocation、continuation、route identity 与 result settlement 可恢复且 Plugin 不直接写 Core tables。Compute record 现经 `ExtensionStateKernelApplicationService`、`ComputeTransactionParticipant` 与 Store-owned namespaced table 做 CAS 持久化；EnzymeDesign composition root 构造 exact Session pin/binding reader、SQLite coordinator/query、durable Compute repository 和 Kernel continuation service。最初的 SQLite restart 测试闭合有 opaque handle 的恢复路径；20.1/20.2 进一步闭合无 handle response loss。continuation `source_version` 从兼容 TEXT 列读回时的类型/digest 漂移已修复。
- [x] 19.6 为 local/remote Workspace filesystem、process 与 transfer Adapter 增加 Store-owned durable occurrence/receipt ledger：Contracts 固定 provider/operation/intent/session/workspace generation identity 与 reserve/read/settle Port，SQLite 以 CAS ledger version 持久化 bounded receipt；Podman filesystem/process/transfer、SSH Adapter 和 Standard/EnzymeDesign composition root 均已注入。真实 SQLite 跨 Adapter epoch 测试证明 terminal proof 可恢复，uncertain SSH occurrence 只 reconcile 原 transport identity，exact duplicate 的 dispatch 计数保持 1 且无 fallback。
- [x] 19.7 为 Slurm opaque handle 映射实现持久 ledger 和具体可注入 backend composition，并把远端 `openzyme-workspace-runtime` helper 建模为 exact target resource capability，绑定版本/build digest/qualification receipt/target generation；manifest selected 不得被描述为 runtime cutover。HPC-owned `openzyme_hpc_scheduler_occurrences` 现持久化 submit/cancel occurrence 与私有 raw handle，跨 Adapter epoch 的 uncertain submit/cancel 仅 reconcile 原 effect；EnzymeDesign proof 后用 exact selected factory、显式 backend/credential resolver 和同一 SQLite ledger 构造 Slurm runtime。helper `1.0.0` 的 build/qualification/inventory generation 已进入 manifest、private locator 与 affordance，缺失时为 `blocked_qualification`；全部证据均为 non-live，不声明真实 target cutover。
- [x] 19.8 建立 `enzymedesign_local_single_process_file_sqlite@1` mounted product graph 的非 live HMMER/Vina formal slice：从 generic Host、Session composition pin、authority、PublishedRevision、adopted inventory、affordance/route 到 HMMER/Vina、Compute、声明式 fake external runner、result validation、owner continuation 和 Science validator；同时证明 Task 不自动完成。场景直接 seed 部分合法 canonical 前置事实，并替换其他 product application/external Ports，因此不声明完整产品生命周期。
- [x] 19.9 同步 `docs/OpenZyme架构设计.md`、相关 `docs/v3/`、EnzymeDesign/Compute/HPC/SSH/Slurm/Podman README 与 operator 文档，明确 `selected`、`runtime_mounted`、`qualified`、`cutover`、`live` 五种状态及持久 reconciliation 机制。文档现明确 product non-live proof、当前最终 source 未 cutover、远端 helper/Slurm/Workspace ledger 的 exact occurrence recovery，以及后继状态不得由前态推断。
- [x] 19.10 建立拆分前行为测试的语义处置账本，逐项记录“保留不变量→新测试”“明确退休 surface→负向 absence test”“迁移 capability→新 owner test”“live/integration→显式后续资格”，不要求机械的一对一文件映射。`behavior-test-disposition-ledger.md` 按 collaboration、authority、runtime、effect、Git/publication、process、HPC/Compute、Science/AOX、Research、Reporting、delivery、migration 与 live gate 分类，明确新 owner/test 和剩余边界。
- [x] 19.11 将 catalog-only 场景改为 `wire-contract.enzymedesign-catalog`，另以 `identity-semantics.enzymedesign-product-cross-layer` 运行 mounted graph 的 HMMER/Vina formal slice；closed registry 为 28 scenario/invariant。该 scenario ID 是稳定身份，不把 slice 扩张为完整产品 E2E 声明。
- [x] 19.12 在 exact clean final source 上按冻结顺序重跑 focused tests、fresh wheels、三 profile qualification、mainline、evals、strict OpenSpec 和独立 verifier，生成新的 source-bound completion evidence；20.x 修改前的 candidate 与报告只保留为历史证据。最终 seal SHA、报告路径和 digest 仅记录在 checkout 外的交付说明中；后续 delivery change 仍须独立验收，不能从本 change 推断可开始。

## 20. 修复 exact occurrence、effect truth 与产品终态验证缺口

- [x] 20.1 为 Compute dispatch 建立 Store-owned durable occurrence state：在任何 route effect 前持久化 `dispatch_state`、`dispatch_occurrence_id` 与 receipt identity；扩展 `ComputeRoutePort.reconcile(request, occurrence_identity)`，并保证任何非 `not_started` record 的 `submit()` 都不会再次调用 `dispatch()`。
- [x] 20.2 增加两类跨 Host epoch response-loss 回归：dispatch 返回 `dispatch_in_doubt` 且无 provider handle，以及 dispatch 抛出 typed `dispatch_in_doubt`；两者均须证明原 occurrence 可 reconcile 且 `dispatch_count == 1`。
- [x] 20.3 修复 SSH Workspace 与 Slurm submit/cancel reconciliation 顺序：先读取 durable occurrence，terminal receipt 不依赖 credential；uncertain occurrence 遇到 credential、locator 或 qualification 暂不可用时保持原 `dispatch_in_doubt`，不得降级为 `no_effect`。
- [x] 20.4 为 mounted runtime tool failure 建立 typed effect contract，并修复 unknown effect 的 `mutation_applied=null`；普通未分类异常可保守映射为 unknown，但不得与 `mutation_applied=false` 自相矛盾，测试覆盖 typed 与 untyped failure。
- [x] 20.5 持久化 exact Driver、compiled workload contract 与 result-validator identity；Compute 在写 terminal result 和注册 owner continuation 前调用 owning HMMER/Vina Driver 的 `validate_result()`，validator drift 或 `raw_shell` 结果必须 fail closed。
- [x] 20.6 消除 EnzymeDesign Adapter metadata/runtime 双通道：所有 operational objects 必须从 exact selected Adapter runtime bindings 派生，并校验 component/contract/build/slot/target identity；增加任一对象替换均在 writer/effect 前拒绝的负例。
- [x] 20.7 收窄当前产品资格与 metadata/documentation 声明，明确产品场景只证明 mounted graph 下的 HMMER/Vina formal cross-layer slice、Podman 无 durable terminal proof 时可长期 uncertain、真实 external qualification/cutover 未执行；最终 clean seal source 已重跑全部 closure evidence。
