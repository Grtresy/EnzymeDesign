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

### 6. Workflow refs are explicit per delegation

`task.delegate` 增加可选 `workflow_refs` 参数，值只能是当前 turn 已授权的 active workflow refs 的无重复子集；payload 持久化所选 manifest snapshot。省略或传空数组均表示不绑定 workflow，不再从 parent focus 隐式继承全部 refs。若 ref 与目标 role/tool/capability 不兼容，delegation 在 claim 前返回 LLM 可读错误。master prompt/tool result 会列出可选 refs，使 agent 能把 executor pack 只交给 executor，同时让 researcher/reporter 使用各自工具面。

这是局部、可测试的 harness 修复：它消除隐式传播但不改变 scheduler、task ownership 或 workflow manifest 顶层模型。若实施中证明需要 role-scoped multi-pack composition、动态 capability negotiation 或 workflow schema 重构，则每项写入 `docs/v3/architecture-proposals/` 独立文档并在本 Goal 中停止该大改。

### 7. Campaign is a product-path driver plus an offline verifier

新增 campaign CLI/模块而不是把 cutover 判定塞进 pytest fixture。每个 attempt 创建唯一空目录，随后初始化 SQLite、artifact/blob root、sandbox root 和独立 HPC workspace label；preflight 记录目录清单与 digest，并拒绝预载科学文件。允许项仅为 checkout commit、配置摘要、immutable image/toolchain、workflow pack、credentials 和用户 accession/prompt。

正向 attempt 只通过一个 `/messages` 请求进入，之后使用公开 runtime drain、approval API 和读取接口推进，不直接调用 repository/service 写入真状态。driver 可自动轮询，但不得 seed task/approval/artifact/report。至少一次 attempt 在 Chrome 中人工批准同一 operation。attempt 完成要求 researcher/executor/reporter participation、task business exits、published report、final master response 和所有规范 artifact。

独立健康证明使用已实现的 `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"`：NCBI `NP_000509.1` / `NP_000549.1`、UniProt `P68871` / `P69905`，以及 MAFFT、hmmbuild、protein CD-HIT identity `1.0`、一次同时消费真实 HMM 与 clustered UniProt FASTA 的 HMMalign，总共 exact six controlled operations。probe 使用单独 task/workspace/sandbox/source snapshot，绑定 raw HTTP response-body digest，不重复正式图必然到达的 EBI HMMER，也不允许任何 probe identity/bytes 进入正式 artifact 或 report claim。合同已实现不代表 live 已通过；仍必须由当前 attempt 封存并离线验证。

offline verifier 使用 canonical JSON（排序 key、稳定 separators、UTF-8）重算 bundle digest，遍历 sealed artifact closure，重算 scoring rows、schema、provenance links 和 report references；不得发网络请求。tamper test 修改 artifact byte和 provenance 字段，必须定位精确 mismatch。

### 8. GO is derived, never asserted by prose

campaign manifest pin `git_commit/config_digest/workflow_ref/scoring_contract_digest/image_digest/sdk_digest`。attempt 1 和 2 必须使用不同 clean roots 且以上 identity 完全相同；两者均通过 offline verifier并发布 report。attempt 3 注入一个受控且可证明到达目标 seam 的 required-provider/schema/artifact-digest fault，预期 operation/task 失败，且不存在 cutover-eligible report/bundle。只有聚合 verifier 同时确认三项才生成 GO decision；否则只能输出带最小 blocker 的 NO-GO。

MICU token 使用现有持久 100M ledger，不在 campaign 初始化时重置。真实测试在 focused/non-live gates 后运行，并在每个 attempt 前后记录累计账本快照。

### 9. Evidence projection is summarized, not a storage escape hatch

workspace/events/API/UI 只呈现 provider、status、citation、operation/artifact/report identity、digest prefix、warning/degradation 和 verifier status。Host path、remote path、credential、private header、原始受限全文不进入 public projection。approval UI 必须显示并续接同一 operation id/digest；若恢复创建新 operation，attempt 失败。

### 10. Harness findings follow a two-tier change rule

实施中发现的 harness 问题先判断是否能以单一局部合同、现有状态模型和 focused regression 解决。满足者可直接修复并同步稳定文档；涉及新增顶层真状态、跨包 ownership 重划、scheduler/approval/protocol 语义迁移或 workflow schema 总体重构者视为大架构调整。每个大调整单独成文，至少包含现状证据、agent 受限方式、目标不变量、候选方案、迁移、兼容/回滚、风险和验收；本 Goal 只引用文档，不实现代码。

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
