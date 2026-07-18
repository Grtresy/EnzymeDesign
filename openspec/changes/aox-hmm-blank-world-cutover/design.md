## Context

当前 AOX/HMM 路径同时存在三类断点：产品内没有可执行、可版本化的参考位点评分实现；research provider 的成功、失败和降级尚未形成 cutover quorum；现有 S15 live eval 仍是单 executor、fixture 兼容且不能封存完整报告链的证明。只读参考 notebook 和 runner 给出了坐标规则，但其历史运行被分页中断，且 Python 二进制浮点把数学上的 `33.6` 计算为 `33.599999999999994`，导致边界样本被错误拒绝。因此本变更以参考公式而非历史候选行数为标准答案，并以 correctional breaking change 建立新的科学合同。

系统边界保持不变：SQLite 仍限单进程，runner 只面向可信 Host，Deep Agents 只提供 teammate 工作面，canonical session/task/lane/approval/artifact/event/report 仍由 OpenZyme control plane 持久化。真实外部依赖包括 NCBI E-utilities、PubMed、EBI HMMER、UniProt、MICU LLM 和 Host-supervised HPC；任何必需依赖失败都必须留下结构化证据而不是生成替代结果。

本设计涉及科学 SDK、research adapter、execution engine、Host API/eval、Web UI、workflow pack、campaign tooling 和稳定文档。reference 目录只用于开发期只读复核和最小 golden 的来源审计，绝不进入 live roots。

## Goals / Non-Goals

**Goals:**

- 固化 `aox_motif_rule_score@1`，用精确整数十分制消除边界误判，并提供独立 golden 与严格前置校验。
- 把 PubMed 必需证据、Semantic Scholar/Tavily enrichment、NCBI/EBI/UniProt 身份链表达为可持久化、可投影、可故障验证的合同。
- 用一条真实 product path 产生 normalized artifacts、published report 和可离线重算的 sealed evidence bundle。
- 用两个独立 clean-root 正向 attempt 加一个 fail-closed attempt 形成机器判定的 local GO/NO-GO。
- 修复会把不适用 workflow pack 强制传播给 teammate 的小型 harness 摩擦，同时保持 agent 对具体研究与执行策略的选择自由。

**Non-Goals:**

- 不把 motif heuristic 描述为实验活性模型，不引入新的 ML 模型或校准结论。
- 不把 LangGraph/Deep Agents 变成顶层产品真状态，不引入多进程 SQLite 或不可信 runner。
- 不把 notebook、历史 CSV/FASTA/HMM、fixture adapter 或 seeded task 当作 live 证据。
- 不在本 Goal 内实施需要重塑顶层 harness、workflow schema 或调度模型的大架构调整；每个此类问题只在独立文档中记录背景、方案、迁移和验收。
- 不承诺外部共享环境 cutover；GO 只覆盖当前 commit/config 下的 local trusted-Host 边界。

## Decisions

### 1. Scoring contract lives in the sandbox SDK and uses exact tenths

在 `openzyme_pipeline` 增加无第三方依赖的 AOX motif 模块。模块负责 FASTA alignment 解析、唯一 reference 解析、ungapped-reference 到 alignment column 映射、逐行评分、规范化 CSV 字段和 contract metadata。内部权重为 `50/20/-1`，threshold 为 `336`；`33.6` 只在展示/序列化边界用固定一位小数生成。contract digest 由规范化 rule payload 计算，implementation digest 由实现源码字节计算，workflow manifest 同时 pin 两者及 SDK source digest。

Host/evidence verifier 显式依赖同一 SDK 代码来重算，不复制第二份规则。`openzyme-pipeline` 因此成为 Host 的声明依赖；这与 Host 已负责 seal/copy SDK source 的现有边界一致。备选方案是把规则放入 `openzyme-domain`，但该包承载 control-plane 领域真相而非科学计算；另一个备选是只在 eval 内嵌脚本，但无法提供可复用、可离线复核的合同，均不采用。

最小 golden 只保留授权参考中可解释的少量 alignment 行、期望 residue vector、score/pass 和输入 digest。历史 2689-row 输出只用于开发期对照，不入测试夹具和 live 输入。golden 必须覆盖精确边界、一个高于阈值、一个因关键位点低于阈值以及 missing/duplicate/truncated/unequal-width/drift 失败。

### 2. Canonical schema is breaking and legacy fixture output is quarantined

规范字段为 `motif_rule_score_tenths`、`motif_rule_score`、`passes_motif_rule`、逐位点观察、`scoring_contract_id`、`scoring_contract_digest`、`scoring_implementation_digest`、reference identity 和 alignment/input digests。`activity_score`、`seq_score`、`pass_rule` 不做隐式 alias；validator 看到 legacy-only schema 时直接拒绝 cutover eligibility。

现有 deterministic/fixture eval 可继续为非 cutover 回归服务，但必须改用显式 `fixture_non_cutover` 标记与不会通过科学 validator 的 fixture schema，且不得再声称 live success。候选数、cluster 和 edge 不再由固定常数产生。备选的兼容读取会让旧 artifact 被误当作新合同，违反 fail-closed，因此不采用。

### 3. Provider calls return a structured outcome, not an exception-only side channel

research adapter 增加共享的 bounded HTTP invocation seam，统一 timeout、attempt、`Retry-After`、transient/quota/auth/schema/empty 分类、request identity、safe response digest 和 retrieval time。服务方法返回或抛出带稳定 error taxonomy 的类型化结果；tool boundary 必须先建立 canonical invocation/operation，再执行网络调用，并在成功、degraded 或失败时终结同一个 operation。凭据和私有 header 永不进入 payload、artifact 或 public projection。

PubMed query 使用 NCBI identity，至少一个 schema-valid PMID 才满足 required quorum；DOI 只从 PubMed article identifiers 提取。Semantic Scholar/Tavily 是独立 enrichment attempt，其 429 或 retry exhaustion 在 PubMed 完整时写 `degraded`，不抹除主证据，也不触发备用 synthetic search。NCBI reference、EBI HMMER 和 UniProt 则按科学阶段被标记为 required，其失败/空结果语义由阶段合同决定。

researcher 可以在同一 bounded policy 内按科学需要迭代 PubMed query；harness 不固定 query、不要求 one-call，也不按 first/latest/result-count 猜测主证据。研究 task 完成前，agent 必须在 `task.finish.evidence_refs` 中显式采用 exactly one succeeded、source-bearing PubMed `artifact:<id>`。collector、positive blocker 与 offline verifier 只以这个结构化 adoption 为 primary receipt authority，并要求 researcher task、invocation、artifact、全部数字 PMID source 的 task/lane 完全闭合；可选 `lane_id` 允许整条链一致为 `None`。零个或多个 PubMed artifact adoption 均 fail closed，report 还必须引用所选 artifact 内的 PMID/source。未采用 invocation 继续留在 canonical SQLite；把 accepted/exploratory/failed/empty/superseded 全量历史与 completeness root 封入 bundle 需要 `@2` schema，已独立提案而不在本 Goal 实施。

备选方案是保留各 provider 私有 retry 并在 eval 汇总异常，但那会丢失 attempt/operation 关联且容易出现调用发生在 invocation 持久化之前的证据洞；不采用。

### 4. Sequence identity is append-only across providers

正式 NCBI protein fetch 一次请求 exact 14 个 identity：原 notebook 的 13 个 HMM model accession（包括以固定规则解析的 `9AVH_A`）加坐标 reference `AAB57849.1`。provider aggregate 必须封存全部 requested/resolved identity、原始 FASTA record、sequence SHA-256 和 aggregate FASTA digest，不允许缺失、重复、多余或身份替换。两个 versioned calculation 从同一份封存 bytes 分别生成 exact-13 `AOX_ref21.fasta`（`aox_hmm_reference_set_selection@1`）和单条 `AOX_coordinate_reference_AAB57849.1.fasta`（`aox_reference_selection@1`）；后者不得进入 MAFFT/hmmbuild 的 model-training input。

EBI HMMER `refprot` hit 的 candidate 主身份是 UniProt accession。`hmmer_score_filtered_accessions@1` 只从严格 provider parsed schema 中保留 score `>200` 的 accession，其 canonical artifact 和 exact non-empty accession set 是唯一允许的 UniProt 请求输入；HMMER 不提供下游 sequence/length 真值。UniProt lookup/fetch 增加 reviewed status、release header、retrieved_at、response/sequence digest，再由 `aox_sequence_length_join@1` 按 accession 严格连接并筛选长度 `650..700` 产生 `target.fasta` 与 `hits_len650_700_200.csv`。cross-reference mapping 只追加 annotation edge；若两源序列不同，保留双方 bytes/digest 并要求显式 selection，禁止 overwrite。

`aox_scoring_input_assembly@1` 把单条 AAB 坐标 reference 放在首位，再按 target id 字典序追加 post-UniProt target，生成 `AOX_scoring_input.fasta`。非空 target 时 HMMalign 必须同时消费 `AOX_ref.hmm` 和该 scoring input；空 target 时不伪造一次 HMMalign，而是用 `aox_reference_only_scoring_alignment@1` 将已验证的 AAB-only scoring input 物化为 scoring alignment。

每一科学跳转都以 `input_artifact_ids + input_digests + operation_id + provider/toolchain identity + output_artifact_ids + output_digests` 连接。空 hit/空 candidate 可输出 schema-valid 空 artifact 和 empty-result explanation，但 known-positive probe 必须另行证明 provider/HPC 健康，probe 数据不得合入正式结果。

### 5. AOX execution remains agent-authored within a strict manifest

workflow pack pin required outcomes、contract/digests、13 个 HMM model accession + AAB 坐标 accession 的 exact-14 NCBI 身份和拆分合同、数据库 `refprot`、artifact schema 和 fail-closed 条件，但不硬编码唯一命令序列。executor 仍可选择合理的分批、重试和中间检查策略；Host 只提供真实约束与受控 `openzyme_pipeline` SDK。MAFFT、hmmbuild/hmmalign、CD-HIT 和 similarity 都由真实 input/output 产生并 seal tool version/params。similarity 采用版本化的全局 alignment identity 计算；不得用常数边或复制 HMM/motif score。

manifest 声明完整 capability set，但正式 operation closure 由封存 artifact 重算实际到达分支，不用静态“全工具必须调用”清单惩罚正确早停：

- HMMER upstream empty：省略 UniProt、HMMalign 和 CD-HIT；UniProt 以 `provider_upstream_empty_receipt@1` 记录 `provider_io_performed=false`，不允许 request/response digest。
- length-filter empty：已到达 UniProt 与 sequence join，省略 HMMalign 和 CD-HIT。
- motif-filter empty：已到达 HMMalign 与 motif scoring，省略 CD-HIT。
- nonempty：执行完整正式链。

分支必须由 raw/parsed HMMER、score-filter、sequence join、motif/candidate artifact 重算，不信任 execution summary 或 agent 自报。正式分支省略的 capability 由独立 known-positive probe 覆盖，probe bytes/operation/task/workspace 不得进入正式图或 report claim。将这一逻辑抽象为通用 harness 的调整已单独记录为 `artifact-derived-conditional-capability-closure.md`，本 Goal 不实施通用化。

formal prompt 只呈现实际安装的 `openzyme_pipeline.aox_reference`、`aox_hmmer`、`aox_sequence_join`、`aox_motif`、`aox_similarity` callable 及 canonical serializer，不允许 agent 近似重写。provider artifact 按 transcript manifest 的唯一声明后缀选择；HPC artifact 按 runner-owned canonical path 对应的唯一 `fetch_refs[].declared_output_path` 选择，HMMER search 精确绑定 fetched HMM artifact id/digest。合法零记录 FASTA 必须是 exact zero bytes，并携带 `fasta_zero_records@1`、稳定 empty reason 和版本化 derivation contract；通用空文件或 sentinel 不能通过 artifact boundary。

r12b 证明 rich operation/fetch envelope 会在 nested provenance 中重复描述同一 artifact，若让 agent 自行递归扫描，很容易在外部 operation 已完成后因本地 parser 误判而整段重跑。当前 Goal 的小修是在 `openzyme_pipeline.artifacts` 提供只读 canonical direct field 的 `provider_file_ref`、`registered_artifact_ref`、`fetched_output_ref`，missing/duplicate/malformed/nested-only 均以 non-retryable SDK error fail closed。executor 在下游本地解析前把已完成 response 写入 attempt-local `/workspace/work`；source 修复只复用已有 response/artifact。cutover driver 在 approval 前检查 method operation budget，同一 method 的第二个 operation 或既有 terminal failed operation 直接拒绝，避免已确定无效的 attempt 继续触达 provider/runner。该修复不改变 exact-operation-set，也不选择最新或成功子集。

### 6. Workflow refs are explicit per delegation

`task.delegate` 增加可选 `workflow_refs` 参数，值只能是当前 turn 已授权的 active workflow refs 的无重复子集；payload 持久化所选 manifest snapshot。省略或传空数组均表示不绑定 workflow，不再从 parent focus 隐式继承全部 refs。若 ref 与目标 role/tool/capability 不兼容，delegation 在 claim 前返回 LLM 可读错误。master prompt/tool result 会列出可选 refs，使 agent 能把 executor pack 只交给 executor，同时让 researcher/reporter 使用各自工具面。

这是局部、可测试的 harness 修复：它消除隐式传播但不改变 scheduler、task ownership 或 workflow manifest 顶层模型。若实施中证明需要 role-scoped multi-pack composition、动态 capability negotiation 或 workflow schema 重构，则每项写入 `docs/v3/architecture-proposals/` 独立文档并在本 Goal 中停止该大改。

cutover collector 不把 task row 当作 workflow binding 的充分证明。它从 durable delegation document 重建 researcher/executor/reporter 三个 role receipt：executor 必须精确绑定 campaign workflow ref 和完整 manifest snapshot，其他两者必须空绑定；bundle 封存不含 raw instructions 的 closed public request projection，offline verifier 独立重算 projection digest、manifest content/core digest，并把 projected agent 与 task assignment 绑定。这样仍不引入新的 product truth，只封存既有 durable record 的安全投影。

### 7. Campaign is a product-path driver plus an offline verifier

新增 campaign CLI/模块而不是把 cutover 判定塞进 pytest fixture。`run-live` 在构造 runner、campaign 或任何 attempt root 前先生成 canonical launch snapshot。launch identity 是 exact-seven 闭集：`git_commit`、`config_digest`、`workflow_ref`、`scoring_contract_digest`、`scoring_implementation_digest`、`image_digest`、`sdk_digest`。这些字段分别从 canonical clean checkout 的完整 commit、digest-pinned workflow registry selection、`aox_motif_rule_score@1` contract/implementation、实际 Podman sandbox preflight 和 Pipeline SDK source tree 计算；operator 提交的 identity 只用于逐字段精确比较，不能成为真值来源。dirty checkout、字段缺失/多余、mutable/malformed identity 或任一 mismatch 都在 root 创建前失败。

`pin` 是生成 `run-live` declaration pair 的 canonical supported operator bootstrap。它使用 production `compile_hpc_tool_request` 和受信 Host 的 forced-SSH `MCPHpcServer` 执行 deterministic non-scientific MAFFT、CD-HIT、hmmbuild 与 chained hmmalign payload，只从 runner-issued same-shell runtime identity 构造四个 toolchain image digest。writer 把 exact-seven 与 exact-nine payload 以 mode `0600` canonical JSON 落在 checkout 外同一 existing real transaction directory，并要求两个 payload 与 fixed marker 三个 reserved target 初始不存在；两个 payload fsync/no-replace publish 后才最后发布 exact closed `.aox-cutover-pin-commit.json`，用两个 basename 及 canonical payload digest 作为单一 consumer-visible commit point。`run-live` 在 settings/launch/root 之前拒绝 marker 缺失、symlink、跨目录、malformed/open 字段或 digest drift。marker 发布前 crash 可留下 orphan payload，但它们不可消费，operator 必须使用新 transaction directory。该无签名 marker 只证明 pair 的 transaction integrity，不证明 producer provenance、目录整体 freshness 或消费时 file mode。随后 `run-live` 仍重算 actual launch snapshot，pinned pair 只是 exact comparison declaration，真实 toolchain identity 仍由 live operations 的 runner-issued receipts fail-closed。

`config_digest` 是 safe `aox_blank_world_runtime_config@1` preimage 的 canonical JSON digest，而不是任意配置标签。preimage 绑定 effective post-foundation 设置：trusted `local-dev`、single-process SQLite、background runtime disabled、HPC backend 与 runner-config file digest、runner-owned manifest bytes digest 与 exact AOX `tool_id` 到 adapter/template/runner-contract digest 的闭集 expectation map、provider limits、MICU endpoint/model/policy/token/runtime bounds、research bounds/credential availability/opaque NCBI identity、tracing digest、显式 live opt-ins、driver approval/time/drain/agent/browser bounds、`chrome-once` UI dist digest，以及 scenario、固定累计 500M ceiling 和既有 ledger identity digest。raw credential、NCBI email、Host/runner/ledger path 不进入 preimage；launch receipt 封存 preimage 与 digest，offline verifier 重算 canonical digest 并核对这些 fail-closed 约束。runner expectation map 只是 config preimage 的内部闭集字段，不扩展 exact-nine prerequisite 顶层 schema。

MICU/OpenAI-compatible endpoint 的 blank-world live context 必须显式声明且 `context_window_tokens <= 200000`；不能用模型名推导第三方 endpoint 未证明的百万级窗口。`world.inspect(sections=["capabilities"], task_id=..., limit=...)` 同时改为 bounded facts index：teammate 绑定当前 task，master 保留既有 session-wide 权限；页面 newest-first，最多 20 个 invocation、每类 8 个 closed opaque refs、serialized facts 64 KiB，不回填文档、output、evidence 或 source body。当前 rich hydration 的读取成本尚未有界，窄列/lazy/cursor 大调整只记录在独立 proposal。

每个 attempt 创建唯一空目录，随后初始化 SQLite、artifact/blob root、sandbox root 和独立 HPC workspace label；preflight 记录目录清单与 digest，并拒绝预载科学文件。`allowed_prerequisites` 是 exact-nine 闭集：`git_commit`、`config_digest`、`workflow_ref`、`image_digest`、`sdk_digest`、`toolchain_image_digests`、`credential_slots`、`ncbi_identity`、`prompt_accessions`。前五项必须与 launch identity 相等；toolchain map 只含 `mafft_7.525.hpc_apptainer_sif:v1`、`hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`、`hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`、`cdhit_4.8.1.hpc_apptainer_sif:v1` 四个 immutable image digest，且 hmmbuild/hmmalign 必须绑定相同 HMMER SIF bytes；credential slots 只含 `llm/ncbi/semantic_scholar/tavily` 四个 boolean 且 LLM/NCBI 必须 ready；NCBI identity 是 opaque digest；prompt accessions 只含 formal exact-14、固定 probe NCBI 与 probe UniProt 集合。未知字段、credential value、private locator 或 scientific bytes 直接拒绝。

source snapshot 是 `kind=code` 的 typed directory artifact，evidence collector 将其规范化为 `openzyme_sealed_source_tree@1`：relative path 必须安全、唯一并排序，每个 entry 绑定 size/content digest/canonical base64，envelope 再绑定 source-tree digest。bundle builder 与 offline verifier 都重算 envelope 内外 digest，并对 base64 解码后的 UTF-8 source 执行 public-safety 检查；symlink、FIFO、empty tree、kind drift、非规范 JSON/base64、private decoded source 或任一 digest drift 均 fail closed。零记录 FASTA 的 catalog validation payload 另封存为 `openzyme_typed_empty_artifact_validation@1`，offline verifier重建 validation digest并与科学 empty reason闭合。

首次 live campaign 证明 sandbox root 不能只在 composition 层声明：workspace status 若独立使用共享默认 root，会把同一 `sandbox_workspace_id` 标成 READY，而 file/exec/Podman 实际解析到 attempt root，最终以缺失 bind source 消耗 agent turn。小型纠正因此锁定为：status、显式/隐式 lookup、file/exec、snapshot 与 Podman bind 共享 Host-injected attempt root；显式 id 仍校验 executor ownership；无 canonical row 时派生 leaf 必须不存在并以 no-replace/exclusive-create 建立六目录，预存目录/文件/symlink不得接管或修改；已有 layout 缺失、非目录或 symlink 直接 `sandbox_volume_corrupt`，且失败先于 snapshot/run/process。此修复沿用现有 canonical state 与错误 taxonomy，不新增顶层真状态，属于本 Goal 可直接实施的小改动。

launch snapshot 还提供 attempt-boundary guard。`AoxCutoverCampaign` 在每次调用 `create_blank_world_roots` 之前重新计算 checkout、workflow/scoring、sandbox image、SDK 和 effective-config identity；任何 drift 以稳定 launch failure 终止 campaign，封存 safe driver-failure/NO-GO decision，不创建该 attempt root，也不触达 model、provider 或 runner。已创建 attempt 内的 runtime/artifact failures 仍走 attempt evidence，不被 guard 伪装成 launch success。

正向 attempt 只通过一个 `/messages` 请求进入，之后使用公开 runtime drain、approval API 和读取接口推进，不直接调用 repository/service 写入真状态。driver 可自动轮询，但不得 seed task/approval/artifact/report。`chrome-once` 只把 positive 1 的首个 formal approval 暴露给 same-process loopback Host 所服务的 digest-pinned Web UI；driver 不调用该 approval 的 resolve route。driver 在触发可能产生 handoff 的 drain 前记录 durable event cursor，然后从该 cursor 重建 resolution/continuation，避免即时 UI resolve 与事后 snapshot 竞争。浏览器 approval timeout 从 handoff 发出时独立计时，同时受 attempt 总 deadline 上界约束。用户从 UI resolve 后，driver 必须观察顺序严格递增的 pre/resolution/continuation event cursor，并保留同一 `approval_id`、`operation_id`/digest、sandbox workspace/run 和 continuation identity，直到同一 operation 到达 terminal state，再进入 bounded UI observation window。

drain worker 的成功 response 与最后一个 `waiting_approval` workspace projection 存在并发可见性 seam。coordinator 在观察到 worker terminal 后必须再完成一次确定从 response 之后开始的 public workspace GET，才可结束本轮；后台 drain exception 保留 command-failure taxonomy，只有 workspace/approval coordination 或 cleanup exception 归为 coordination failure。一旦 coordination 失败，已有及后来出现的 unresolved approval 都在既有 attempt deadline 内通过 public API 明确 reject，不能 approve cleanup 或继续 science；cleanup GET/resolve 瞬时失败只记 safe secondary type，并以同一 idempotency key 重试，原始 blocker 保持权威。由于 approval row 可能先于 drain response 和 `approval.requested` 回填持久化，Web UI 以五秒、single-flight-per-generation、只读的 selected-session workspace reconciliation 补充 SSE refresh；session switch、workspace mutation 与 applied SSE reducer 都 abort/失效旧 token，token identity 保护旧 `finally` 不清除新请求，避免旧 snapshot 覆盖较新状态或挂起旧 GET 饿死新 session，且不新增 UI 真状态。

`aox_browser_approval_receipt@2` 记录 mode/channel/Host process、session/approval/operation/sandbox identity、pre/post workspace semantic preimage 与 public response binding、resolution/continuation 的完整 durable-event record 与 replay binding、authenticated actor、continuation id、post-operation status 和 `driver_resolve_route_absent=true`。positive 1 还必须封存 `aox_browser_observation_receipt@2`：challenge、page/Host/UI-dist identity、Host-held completion window timing、console entry digest 与 `application_error_count=0`、terminal page state、DevTools transcript 以及可完整解码且 digest-bound 的 PNG。approval/terminal handoff 对动态身份是完整的：它发出 sealed logical page、Host process、served UI dist digest 和 schema id；exact 23-field builder 合同由稳定 guide/code 定义。trusted operator 必须使 final target 在 hold 内不存在，并在 not-before 后通过 sibling-temp + fsync + atomic rename 交付；窗口结束后再进入独立、正有限并计入 effective-config digest 的 submission timeout。当前 Host 只证明 bounded hold polls 未观察到提前 target，且 final 是 post-hold mtime、non-symlink、两次 stat/read 稳定的 regular file；它不证明轮询间的连续缺失或 atomic/fsync provenance。closed `public_api_receipts` 每项 exact 七字段 `sequence/method/route/status_code/request_digest/response_digest/response_semantic_digest`；query semantics、response semantic preimage 和 canonical list digest 都由 verifier 重算。另以 bundle-level `aox_public_final_workspace_snapshot@1` 与 `aox_public_final_event_replay@1` 封存最后一次只读 public workspace 和 `replay=true,after_cursor=0` 全事件 preimage，fault closure 必须与 task/report/draft/conversation/event/consumer 全集合 exact equality。`auto` mode 不产生 browser receipt，不能满足 Chrome GO criterion。attempt 完成还要求 researcher/executor/reporter participation、task business exits、published report、final master response 和所有规范 artifact。

Chrome resolution 的局部判定只接受带闭合
`decision=approved|rejected` 的 canonical `approval.resolved` command event。
当前 activity backfill 可能复用同一 event type，但其 ApprovalRequest projection
只有 `status`、没有 `decision`；consumer 必须忽略这种 projection echo，不能把它
推断成批准或拒绝。真正的 canonical `decision=rejected` 仍立即 fail closed；若在
既有 bounded approval deadline 内没有 canonical closed decision，则以缺失浏览器
决策证据 fail closed。把 canonical command 与 derived activity projection 在全局
event taxonomy 中分型是单独记录的大架构调整，本 Goal 不实施。

MAFFT、hmmbuild、hmmalign 和 CD-HIT 的 cutover execution identity 只能由 runner 签发。runner-owned manifest 绑定 tool、adapter、command template、contract digest 和 private SIF locator；caller 提交 locator、runtime request/identity 或环境 override 均被拒绝。当前 SSH runner 在执行真实 payload 的同一个 login shell 中先 scrub 所有 inherited `APPTAINER_*` / `SINGULARITY_*` runtime-control 变量并二次确认不存在；任一变量无法移除就在 payload 前 fail closed。随后 runner 直接执行 resolved SIF pathname，并在 payload 前后对同一 pathname 计算 SHA-256。只有两次 digest 相等且 payload 成功才返回现有 closed `mcp_hpc_toolchain_runtime_identity@1`：`attestation_scope=same_ssh_login_shell_pre_exec`、`execution_mode=ssh`、exact tool/adapter/template ids、`runner_contract_digest` 和单一 equal `image_digest`；private pathname 和 pre/post 中间 digest 不进入 Host 投影。Host 各层 closed-reconstruct 该 public identity，collector/verifier 把 observed image digest 与对应 exact-nine prerequisite 比较。当前保证仅限于“受控 runtime 环境中同一 pathname 前后未变且被直接执行”，immutable inode/content-addressed snapshot 的大架构调整已单独记录在 `docs/v3/architecture-proposals/immutable-hpc-sif-execution-snapshot.md`，本 Goal 不实施。Slurm 仍是一般 runner backend，但当前没有 job-internal same-execution SIF attestation；submit/preflight metadata 不得冒充 runtime identity，因此 Slurm operation 不是本 cutover 的有效 toolchain identity。跨层 single-source toolchain registry 属于已记录的大架构提案，本 Goal 不实施。

独立健康证明使用已实现的 `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"`：NCBI `NP_000509.1` / `NP_000549.1`、UniProt `P68871` / `P69905`，以及 MAFFT、hmmbuild、protein CD-HIT identity `1.0`、一次同时消费真实 HMM 与 clustered UniProt FASTA 的 HMMalign，总共 exact six controlled operations。probe 使用单独 task/workspace/sandbox/source snapshot，绑定 raw HTTP response-body digest，不重复正式图必然到达的 EBI HMMER，也不允许任何 probe identity/bytes 进入正式 artifact 或 report claim。合同已实现不代表 live 已通过；仍必须由当前 attempt 封存并离线验证。

offline verifier 使用 canonical JSON（排序 key、稳定 separators、UTF-8）重算 bundle digest，遍历 sealed artifact closure，重算 scoring rows、schema、provenance links 和 report references；不得发网络请求。tamper test 修改 artifact byte和 provenance 字段，必须定位精确 mismatch。

### 8. GO is derived, never asserted by prose

campaign manifest pin exact-seven `git_commit/config_digest/workflow_ref/scoring_contract_digest/scoring_implementation_digest/image_digest/sdk_digest`。attempt 1 和 2 必须使用不同 clean roots 且以上 identity 完全相同；两者均通过 offline verifier并发布 report。attempt 3 只接受 `derived_required_artifact_blob_byte_flip@2`：从 real NCBI exact-14 `proteins.fasta` 经 `aox_hmm_reference_set_selection@1` 得到 derived `AOX_ref21.fasta`，在 pending MAFFT 消费前翻转一个 byte，并要求 exact `artifact_blob_digest_mismatch`。`aox_fault_negative_state_closure@1` 封存 task business exit、report/draft 状态、conversation/final failure、durable events、所有直接 consumer 及 fixed-deliverable path 集；offline verifier 必须证明无 ready/published report/draft、无 successful alternate consumer、无 downstream final deliverable，且 fault MICU 增量全部归因于本 campaign。只有聚合 verifier 同时确认三项才生成 GO decision；否则只能输出带最小 blocker 的 NO-GO。代码与非 live gate 的完成不代表这些真实 attempt 已运行；在三份 live bundle 与 sealed reducer decision 存在前状态保持 NO-GO。

MICU token 使用现有持久 500M ledger；summary、reserve 与 campaign 初始化不自动重解释旧 policy。operator 必须显式调用 canonical migration，且只有 exact legacy fixed 100M→500M；事务不重置历史 usage，500M 幂等，caller-selected lower limit fail closed。真实测试在 focused/non-live gates 后运行，并在每个 attempt 前后记录累计账本快照。

### 9. Evidence projection is summarized, not a storage escape hatch

workspace/events/API/UI 只呈现 provider、status、citation、operation/artifact/report identity、digest prefix、warning/degradation 和 verifier status。Host path、remote path、credential、private header、原始受限全文不进入 public projection。approval UI 必须显示并续接同一 operation id/digest；若恢复创建新 operation，attempt 失败。

公开诊断不仅检查字段前缀，还必须处理异常文本内部的 Host path。control-socket/adapter error、sandbox stdio summary、workspace last-command、runtime signal、failed ToolResult、`harness.failed` 与 eval 在各自 schema-declared diagnostic/locator field 使用共享 high-risk sanitizer：精确 sandbox/control-socket Host root 映射到逻辑路径，随后对当前测试覆盖的常见 Unix/HPC roots、Windows、UNC、file URI、private/special-use URL、storage/runner locator 与 credential corpus fail-closed 脱敏；lane `cwd`、memory `source_range` 等历史 structured locator在 projection再次处理。该 producer不声称识别任意自由文本中的所有 private path，也不无类型改写 user/scientific/report正文；跨全部 surface 的 typed/versioned diagnostic envelope 已单独记录，本 Goal 不实施。进程 stdio 以 binary capture，raw digest/size 证明捕获的原始 bytes，完整 payload 仅写 attempt-local Host-private log；AOX offline verifier 仍独立拒绝 surviving absolute Host path/private locator，不降低任何既有阈值。

### 10. Harness findings follow a two-tier change rule

实施中发现的 harness 问题先判断是否能以单一局部合同、现有状态模型和 focused regression 解决。满足者可直接修复并同步稳定文档；涉及新增顶层真状态、跨包 ownership 重划、scheduler/approval/protocol 语义迁移或 workflow schema 总体重构者视为大架构调整。每个大调整单独成文，至少包含现状证据、agent 受限方式、目标不变量、候选方案、迁移、兼容/回滚、风险和验收；本 Goal 只引用文档，不实现代码。

本轮发现“科学 callable、canonical serializer、agent-facing facts 与 receipt 分散”会迫使 agent 自行猜测计算入口，但统一 registry/projection 涉及跨 SDK、workflow、tool catalog 和 evidence schema ownership，属于大改；详细方案单独记录在 `docs/v3/architecture-proposals/versioned-scientific-calculation-capability-projection.md`，本 Goal 不实现。

本轮还发现跨 `sandbox.exec` 显式采用一个既有 completed operation、同时保留 failed/superseded/abandoned 全历史，需要 durable chain-selection 真状态、operation disposition、approval/public projection 与 bundle/verifier schema 升级，不能用“最新成功”或 content-digest 去重局部修补。详细方案单独记录在 `docs/v3/architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md`，本 Goal 不实现。

## Risks / Trade-offs

- [整数十分制会显著改变历史候选数] → 将其声明为 correctional breaking change，以公式级 golden、边界测试和 legacy non-cutover 标记替代对历史行数的兼容。
- [外部 provider 限流或 schema 变化导致真实 campaign 不稳定] → 使用 bounded retry、明确 required/enrichment、known-positive probe 和完整失败 evidence；不放宽 GO。
- [两次 live E2E 消耗高且运行时间长] → 先通过所有 focused/non-live gate，复用 immutable image 但不复用科学 payload，持续核对 MICU 账本。
- [LLM 可能选择不同合法策略，使输出顺序不稳定] → contract 固定规范化 schema、排序和 digest，而不固定内部推理/命令顺序。
- [Host 依赖 sandbox SDK 形成耦合] → 依赖只用于共享纯计算与离线验证，SDK source digest 已是现有 sandbox identity；禁止 SDK 反向依赖 Host/control plane。
- [显式 workflow ref 是 breaking behavior] → tool schema、prompt、错误信息和回归测试同时更新；旧 implicit inheritance 不保留隐藏 fallback。
- [Chrome/真实 HPC 不可达] → 保存精确 preflight/operation failure，campaign 保持 NO-GO，不用 seeded smoke 替代。
- [evidence bundle 误收敏感内容] → canonical safe projection allowlist、secret scanners 和 negative tests；原始 provider payload按许可边界封存，不直接投影。

## Migration Plan

1. 先落评分 contract、golden、validator 和 workflow pin；将 legacy AOX fixture 标为 non-cutover，并更新 S15 schema。
2. 落显式 delegation workflow selection 小修，补 role mismatch/no-inheritance/drift tests 与 runtime 文档。
3. 落 provider invocation taxonomy、PubMed quorum、UniProt identity/release 和 required/enrichment failure tests。
4. 把真实 AOX execution source迁移到新 SDK/scoring schema，删除产品路径中的常数 candidate/cluster/edge 生成。
5. 落 evidence bundle/verifier、blank-world preflight、campaign CLI、fault injection 和 tamper tests。
6. 更新 Host API projection、Web UI、workflow pack、主架构和 V3 稳定文档；历史 S15 改为 historical non-cutover。
7. 依次执行 focused tests、全量非 live gates、eval、live probes、两次 positive 和一次 fault attempt；最后才生成 GO/NO-GO。

回滚以语义提交为单位。评分 schema 不提供旧字段回滚兼容；若新实现失败，回滚到明确 NO-GO 的旧版本，而不是恢复旧 live-passed 声明。campaign/evidence artifacts 是 append-only，失败 attempt 保留且不能被后续成功覆盖。

## Open Questions

无待用户决策。实施期仍需由 live preflight 回答的外部事实包括当前 NCBI/PubMed/EBI/UniProt schema、HPC toolchain/image digest、Chrome MCP 可用性和 MICU 账本余量；这些是运行证据，不授权变更验收标准。
