# Session 15：AOX/HMM Cutover Live E2E（历史 non-cutover 记录）

## 当前结论

2026-05-31 记录的 S15 `passed` 已撤销为 local Live cutover 证据。它证明了当时的 persistent sandbox、approval bridge、Host-supervised provider/HPC 路由与 artifact 登记控制流，但使用旧评分字段、常量 candidate/cluster/edge、合成序列和只检查表头的 validator，不能重算科学结论。

因此：

- 历史 S15 workspace、operation、artifact 和 inline digest 只是迁移审计线索，不得复制进新 live roots；
- `AoxHmmFixtureSandboxRunner`、`DeterministicBioDatabaseAdapter`、seeded state 和 deterministic/fixture artifact 一律是 `fixture_non_cutover`；
- `live_e2e` marker 只证明显式配置的外部依赖路径，不单独等于可封存的一消息完整报告证明；
- `seeded_live_smoke` 只是辅助回归，不是 cutover proof；
- 当前 local Live cutover 保持 **NO-GO**，直到同一 commit/config identity 下的两次独立正向 blank-world E2E 和一次受控 fail-closed 故障验证全部封存并通过离线复核。

现行运营者/证据合同见 [../aox-hmm-blank-world-cutover.md](../aox-hmm-blank-world-cutover.md)，领域 SOP 见 [../execution-pipeline-docs/aox-hmm-live.md](../execution-pipeline-docs/aox-hmm-live.md)。本文保留 S15 命名，用于解释历史证据为何不再可用以及当前的替代验收面。

## 现行 product-path 边界

正向 attempt 只允许从一次
`POST /v3/sessions/{session_id}/messages` 进入。之后只使用 public message/runtime drain/approval/workspace/events/report API 推进，不直接调 repository/service 写入真状态：

1. master 显式创建并委派 researcher、executor 和 reporter task；
2. `task.delegate(..., workflow_refs=[<exact aox-hmm-live ref>])` 只把 AOX workflow pack 绑定给 executor，通过受权子集、role/tool/capability 和 manifest snapshot 验证；省略或 `[]` 就是不绑定，不从 master focus 或关键词隐式继承；
3. researcher 可作有界迭代 PubMed 检索，但必须在 `task.finish.evidence_refs` 中用 exactly one `artifact:<id>` 明确采用唯一 succeeded、含数字 PMID 的 PubMed primary receipt；零个或多个 adoption 均 fail closed，不能按 prose/latest/首成功猜测；Semantic Scholar/Tavily 只作 enrichment；
4. executor 在 persistent sandbox 中 author source，Host 封存 source snapshot，`sandbox.exec` 通过 `openzyme_pipeline` SDK 请求 provider/HPC；
5. canonical approval 必须续接同一 `operation_id` / `operation_digest`，不得唤醒 agent 后重开替代 operation；
6. artifact catalog 登记当前运行的 normalized sealed outputs 和 lineage；
7. 三个 teammate 分别显式写入 task 业务终态，reporter 通过 `report.publish` 发布报告，master 产生非空 final response。

collector 不只相信 task projection：它从三份 durable delegation request
重建 role-scoped binding，要求 executor 精确携带 campaign workflow ref 与
完整 manifest snapshot，researcher/reporter 必须为空绑定；offline verifier
复算不含 raw instructions 的 closed request projection、manifest content/core
digest，并把 projected agent 与 task assignment 绑定。`world.inspect(sections=["capabilities"], task_id=..., limit=...)`
只返回 task-filtered、limit/byte-bounded invocation facts/opaque refs，不把文档正文、tool output 或 evidence body 内联回 agent context。

pipeline source snapshot 作为 `openzyme_sealed_source_tree@1` canonical
envelope 封存，只接受 `kind=code`，并对 base64 解码后的 UTF-8 源码再次执行
public-safety 检查，而不是把目录当普通文件读取。科学 empty FASTA 也不是通用
空文件例外：只有 exact zero bytes、`fasta_zero_records@1`、稳定 empty reason
与版本化 derivation contract 同时成立时可登记；attempt bundle 封存并离线
复算 catalog validation receipt；sentinel header/text 直接 fail closed。

Runtime idle、max steps、tool success、protocol message 或 capability terminal 都不代表 task completed。缺真实 provider/backend、runner output、approval continuation、artifact closure 或 published report 时必须显式失败，不用 Host-local binary、deterministic adapter、cached payload 或 synthetic output fallback。

## 纠正后的科学数据链

### Exact-14 NCBI 与参考身份拆分

一次正式 NCBI protein fetch 必须请求 exact 14：

- 13 个 HMM-model reference：`AAC72747.1`、`KDQ24956.1`、`9AVH_A`、`XP_014653549.1`、`KIS68002.1`、`XP_003660923.1`、`AMW87253.1`、`AFP17823.1`、`WP_190019735.1`、`WP_138089821.1`、`WP_176407597.1`、`CAQ19343.1`、`CAQ19344.1`；
- 1 个坐标 reference：`AAB57849.1`。

provider aggregate 上的 missing/extra/duplicate/mismatch 全部 fail closed；`9AVH_A` 以固定 NCBI PDB chain 规则解析，不改写 requested identity。三个独立计算合同处理该封存 aggregate：

- `aox_hmm_reference_set_selection@1` 生成 exact-13 `AOX_ref21.fasta`，它是唯一可进入 MAFFT/hmmbuild 的 model reference input；
- `aox_reference_selection@1` 生成 AAB-only `AOX_coordinate_reference_AAB57849.1.fasta`；
- `aox_scoring_input_assembly@1` 把 AAB 放在首位，再按 target id 字典序追加 post-UniProt target，生成 `AOX_scoring_input.fasta`。

`AAB57849.1` 不得进入 13-reference HMM training；13-reference model FASTA 也不得冒充 motif 坐标 reference。

executor 必须调用已安装的 `openzyme_pipeline.aox_reference`、
`aox_hmmer`、`aox_sequence_join`、`aox_motif` 和 `aox_similarity` 中的版本化
函数，不近似重写。provider bytes 通过声明的 `/provider_parsed/...` transcript
suffix 选择；MAFFT/hmmbuild/CD-HIT/HMMalign bytes 通过 runner-owned canonical
path 对应的唯一 `fetch_refs[].declared_output_path` 选择，并用真实 fetched HMM
artifact id/digest 绑定 HMMER search。

### HMMER → UniProt → identity-preserving join

EBI HMMER REST 固定使用 `refprot`。其 provider parsed artifact 保留 exact 11 columns：`target`、`accession`、`evalue`、`score`、`page`、`hit_index`、`evalue_numeric`、`score_numeric`、`raw_page_digest`、`raw_hit_digest`、`parsed_row_digest`。

`hmmer_score_filtered_accessions@1` 只保留 score 严格 `>200` 的 canonical UniProt accession；其七列 output artifact 和 exact non-empty accession set 是 `bio.uniprot_fetch` 的唯一允许输入。HMMER 的记录不提供下游 sequence/length 真值。

UniProt 使用 `uniprot_primary_sequence_identity@2`，对 complete requested set 精确分为 active sequence records 与 exact-requested typed `Inactive/DELETED|MERGED` records。active 的 provider `entryType` 只能精确为 `UniProtKB reviewed (Swiss-Prot)` 或 `UniProtKB unreviewed (TrEMBL)`，分别派生 `reviewed=true|false`；若 raw result 另有 `reviewed` 字段，它必须是与该派生值相同的 boolean，active 带 `inactiveReason` 或任何组合漂移都 fail closed。active 保留 primary accession、reviewed status、release/version、retrieved time、raw response/record/sequence digest 和 append-only cross-source mapping；`DELETED` 保留非空 canonical reason，`MERGED` 保留非空、去重 replacement-target annotations，两类 inactive 均保留 UniParc id、release/retrieval 与 response/record digests，固定 `identity_replaced=false`，无 sequence/audit，不跟随或抓取 replacement。`DEMERGED`、unknown 或 malformed inactive fail closed。`aox_sequence_length_join@2` 先确定性排除两类 inactive，再对 active UniProt sequence 实际长度应用 inclusive `650..700` 过滤，产生 `target.fasta` 和 `hits_len650_700_200.csv`，并封存可离线重算的 active/inactive-reason/output/rejected counts 与 mappings。两源 sequence bytes 不一致时保留双方 digest 并要求显式 selection，不静默 overwrite。

任何到达 UniProt 的 cutover-eligible positive 都必须在
`scientific_checks.sequence_join.uniprot_raw_response_artifact_id` 指明同一个
formal `uniprot_fetch` operation 的 output，并与 artifact provenance、该
operation 的 UniProt provider receipt `artifact_ids` 三方闭合。provider
`request_digest` 必须等于同一 operation 由封存 canonical params 重算的
`params_digest`。completed operation outputs 与 completed provider
`artifact_ids` 必须精确包含三个不同且各出现一次的 same-operation artifact：
`uniprot_raw_response`、`uniprot_metadata`、`uniprot_sequences`；role、formal
scope、origin operation 与 content digest 必须逐项一致，request/observation/error
diagnostic 不得混入或替代。offline verifier
从 closed raw envelope/response rows 重放 canonical base64、size、ordinal、status、
body digest 与 ordered response chain；所有页的 `x-uniprot-release` 必须同值并
等于 metadata，optional release-date 只允许全缺/null 或全页同值。raw result
经 engine sanitizer 与 metadata 做 requested/primary 双射；active sequence 的
规范化 bytes、raw/metadata length 与 digest 必须闭合并继续绑定 FASTA，inactive
明确禁止 sequence/entryAudit 且必须重建 exact DELETED reason 或不跟随的 MERGED
annotation。未来无关 raw result 字段不会按 census exact-five shape 锁死，但必须
把完整 sanitized non-sequence object 保存在 `provider_metadata`，并由
`record_digest` 绑定完整 sanitized result。

最终代码路径的只读 full-set diagnostic 用时 `679.154s`，确认
`37,772 = 32,176 active + 5,596 inactive`、`5,594 DELETED + 2 MERGED`、
`378` 个 response digest、release `2026_02` 和 `2,561` 个 length-filtered hit。
score-filter input、provider metadata、hits CSV 与 join manifest 的完整 digest
依次为
`sha256:c4f1e134c4e38fcda5424706544cccf0bf65b4187be2ce6d2f30114aeaf69b8f`、
`sha256:9deaebcf2c674cc8a7af52c1c00384fe2798b6d364f7d09e50c002abdcc89109`、
`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`、
`sha256:d768beb08f1bf5e5905e63249db352e1bcfe3e9eaea2d5be871e3adba39d8bca`。
这些 `/tmp` 文件没有 seal，也不是 cutover/GO evidence，不得 adoption。

### Scoring 与结果分支

非空 target 时 HMMalign 同时消费真实 `AOX_ref.hmm` 和 `AOX_scoring_input.fasta`，产生 `AOX_scoring_alignment.fasta`。`aox_motif_rule_score@1` 在 AAB 的 one-based ungapped coordinate 上使用 exact integer tenths，threshold 是 `336`，`33.6` 只是展示值；它是 reference-coordinate heuristic，不是实验活性预测。旧 `activity_score`、`seq_score`、`pass_rule` 无 alias，直接使 attempt 失效。

HMMalign AFA 统一绑定 `hmmer_afa_alignment_canonicalization@1`：只按 LF
分段，只有 LF 终止段可去掉一个紧邻 CR，header 的 `>` 必须在 raw column 0，
只忽略真正空物理行；raw sequence line 必须先完整匹配 ASCII
`^[A-Za-z.-]+$`，再做 ASCII uppercase 和 `.`→`-`。因此 whitespace、lone/重复/
其他 CR、非 ASCII 与 Unicode uppercase expansion 都 fail closed。raw input digest
绑定原 bytes，合法大小写和 `.`/`-` 差异只在 canonical alignment digest 收敛。

`aox_global_sequence_identity@1` 以 `R=max(m,n)+1` 将
`(score_half_units, exact_matches, aligned_residue_pairs)` 精确编码为
`score_half_units * R^2 + exact_matches * R + aligned_residue_pairs`，整数比较
与原 tuple lexicographic tie-break 完全等价。冻结 backend
`biopython_trace_guarded_numpy_gotoh@1` 使用 Biopython `1.87`、NumPy `2.4.4`
和经 `<2^53` bound 证明的 binary64 integral packed score；首个 optimal trace
出现相邻 opposite gap-state switch 时，必须调用 exact NumPy `int64`
`numpy_three_state_gap_switch_correction@1`。这是 calculation contract 内的纠正，
不是 fallback；import/version/algorithm/numeric/trace/correction drift 一律 fail closed，
也不得切换到纯 Python、其它 NumPy patch 或其它 library。
reference recurrence state order 仅是 tie provenance；graph 不发布或承诺 alignment
coordinates/path。未来需要 path 时必须新建 calculation id 和显式 trace contract。

pair 依 lexical order；少于 `128` 必串行，至少 `128` 时 parallel-eligible。
worker count 取 pair count、`16`、affinity（仅 affinity 不可用时使用 `cpu_count`）
以及所有可用 cgroup v2/v1 quota/period 向上取整值的最小值；存在但不可读、
不完整或 malformed 的 cgroup limit fail closed。worker=`1` 在执行前选择串行；只有
worker>`1` 才使用 `chunksize=64` 的 ordered process map。parallel branch 开始后的
pool/worker/serialization/result failure 固定为
`scientific_prerequisite_missing:similarity_parallel_execution_failed`，不得隐藏
串行 fallback。offline verifier 每次 invocation 只重算一次 graph，并将该本地结果
同时比对 nodes、edges 和 manifest；它不跨 invocation/attempt 缓存。

offline verifier 从封存 bytes 推导分支，而不信任 execution summary 或 agent 自报：

| branch | stable reason | formal omission |
|---|---|---|
| `hmmer_upstream_empty` | `no_hmmer_hits` / `no_filtered_hmmer_accessions` | UniProt、HMMalign、CD-HIT |
| `length_filter_empty` | `no_candidates_after_length_filter` | HMMalign、CD-HIT |
| `motif_filter_empty` | `no_candidates_after_motif_filter` | CD-HIT |
| `nonempty` | n/a | 无 |

upstream empty 的 `provider_upstream_empty_receipt@1` 必须绑定 HMMER score-filter trigger artifact、derivation operation、reason 和 `provider_io_performed=false`，不得伪造 UniProt invocation/operation/request/response digest。target 为空时不伪造 HMMalign；`aox_reference_only_scoring_alignment@1` 把已验证的 AAB-only scoring input 物化为 scoring alignment。motif 为空时不伪造 CD-HIT representative。独立 probe 可以证明未到达 capability 健康，但不能给正式图补数据。

## Fixed normalized deliverables

正向 attempt 至少登记以下当前运行产生的 normalized sealed artifacts；provider raw/transcript、HPC logs 和其他中间 artifact 可额外存在，但不能替代这些路径：

| relative path | contract |
|---|---|
| `aox_hmm/AOX_ref21.fasta` | exact-13 `aox_hmm_reference_set_selection@1` output |
| `aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta` | AAB-only `aox_reference_selection@1` output |
| `aox_hmm/AOX_scoring_input.fasta` | AAB-first `aox_scoring_input_assembly@1` output |
| `aox_hmm/target.fasta` | post-UniProt length-joined target; may be empty |
| `aox_hmm/AOX_ref.hmm` | HMMER3 profile built only from the exact-13 model references |
| `aox_hmm/hits_raw.csv` | exact 11-column sealed EBI parsed bytes |
| `aox_hmm/hmmer_score_filtered_accessions.csv` | exact seven-column score-`>200` result |
| `aox_hmm/hits_len650_700_200.csv` | canonical `aox_sequence_length_join@2` result |
| `aox_hmm/AOX_scoring_alignment.fasta` | HMMalign output or verified AAB-only empty-target materialization |
| `aox_hmm/scored_ref_plus_hits.csv` | exact canonical `aox_motif_rule_score@1` rows |
| `aox_hmm/AOX_candidates.fasta` | real target rows with `passes_motif_rule=true` |
| `aox_hmm/AOX_candidates_cdhit85.fasta` | real CD-HIT representatives; empty when branch omits CD-HIT |
| `aox_hmm/AOX_candidates_cdhit85.clusters.csv` | one member per row under `cdhit_cluster_membership@1` |
| `aox_hmm/nodes.csv` | canonical real-sequence graph nodes |
| `aox_hmm/edges_similarity.csv` | recomputable real-sequence graph edges |
| `aox_hmm/similarity_graph_manifest.json` | candidate/membership/node/edge digest closure |
| `aox_hmm/execution_summary.json` | counts, identities, branch, omissions, warning/empty status and artifact ids |

`execution_summary.json` 必须带 HMMER filter、sequence join、两个 reference selection、scoring-input assembly、motif、membership 和 similarity 的 contract/implementation/input/output digest，各阶段真实 count，`scientific_branch`、`omitted_operation_roles`、`upstream_empty_skip_receipt_digest`、provider/tool status 和 normalized path list。verifier 重算这些字段；summary 本身不是 branch 真值。

schema-valid empty 分支保留 AAB scoring row，candidate/representative FASTA 为空，membership/nodes/edges 只有 canonical header，graph manifest 和 summary 保留稳定 empty reason。不得生成假 row 来避免空表。

## Known-positive probe 边界

产品 collector 与 offline verifier 已实现 `aox_known_positive_probe@2`，其 `probe_id="independent_globin_provider_hpc_probe"`。这只证明 attestation contract 已存在，不声称已有真实 `@2` pass；AAB-only + MAFFT 的 `@1` 证据不足且不被当前 verifier 接受。

`@2` 使用 NCBI `NP_000509.1` / `NP_000549.1`、UniProt `P68871` / `P69905`，并只有六个隔离的 controlled operations：NCBI fetch、UniProt fetch、MAFFT、hmmbuild、protein CD-HIT identity `1.0`、一次同时消费真实 HMM 与 clustered UniProt FASTA 的 HMMalign。它只用一个独立 task/workspace/sandbox/source snapshot，provider response digest 从 raw HTTP body 计算。形式路径必然到达 EBI HMMER，所以 probe 不重复该 provider。

probe 的 task、operation、invocation、artifact 与 bytes 不得进入 formal roles、report claim 或 AOX outcome。在真实 run 产生该已实现 schema 并通过当前 offline verifier 前，probe 仍是 NO-GO blocker，不能用代码存在或文档自报代替 live 证据。

## Blank-world campaign 验收

每次 attempt 建立独立空 SQLite、artifact/blob、sandbox 和 HPC roots，记录 cache bypass 和只读允许 prerequisite，并继续使用既有 MICU 持久 500M 账本；历史 usage 不清零，campaign 初始化也不得重置。旧固定 100M policy 只迁移 policy ceiling，全部历史 attempt/charged token 原样保留，显式 lower limit 不被抬高。`aox_blank_world_attempt_bundle@1` 必须绑定 commit/config/workflow/scoring/image/SDK/provider/toolchain/root/approval/operation/task/artifact/report/final-answer/warning/degradation/outcome 身份。offline verifier 无网络重算 canonical JSON、所有可达 sealed artifact、科学计算、lineage 和 report references。

`run-live` 在构造 runner/campaign 和创建任何 root 前先从 clean checkout、digest-pinned workflow、`aox_motif_rule_score@1`、实际 sandbox image preflight 与 Pipeline SDK source tree 计算 canonical 七字段 launch identity。`config_digest` 不是任意 operator 标签，而是 safe `aox_blank_world_runtime_config@2` preimage 的 canonical digest；该 preimage 绑定 single-process SQLite/trusted Host、HPC runner-config digest、runner-owned manifest digest 与 exact AOX `tool_id` → adapter/template/runner-contract expectation map、post-budget MICU/research/tracing/test opt-in、driver/Chrome bounds、controlled-operation owner policy、durable route allowlist、command drain、generic mutation closure、bounded shadow observation与现有累计 500M ledger identity，且不暴露 credential、NCBI email 或 Host/runner/ledger path。pin 在 forced-SSH attestation 前、run-live 在 campaign/attempt root 前必须证明全部 AOX provider/HPC route 使用 `durable_async_v1`、drain 为 `command_v1` 且 closure 为 `generic_v1`；旧 `@1` 仅为历史 frozen evidence 离线复核保留。MICU/OpenAI-compatible endpoint 必须显式配置 `context_window_tokens <= 200000`，不能按模型名继承未经 endpoint 证明的百万级 context。每个 attempt root 创建前都重新执行 launch guard，checkout 或 effective config 漂移直接 fail closed；exact-nine prerequisite 顶层字段不因此增加。

blank-world prerequisite 只接受 exact nine：`git_commit`、`config_digest`、`workflow_ref`、`image_digest`、`sdk_digest`、`toolchain_image_digests`、`credential_slots`、`ncbi_identity`、`prompt_accessions`。前五项必须与 launch identity 一致；toolchain map 必须精确包含 MAFFT 7.525、hmmbuild 3.4、hmmalign 3.4 和 CD-HIT 4.8.1 四个 versioned route identity，且两个 HMMER operation 绑定同一 SIF digest；credential slots 只含四个 availability boolean，LLM/NCBI 必须 ready；prompt accession 只含 formal exact-14 与固定 known-positive probe 集合。

fresh SQLite 不继承任何 sandbox image row。campaign 在第一个 session / model / provider 调用前读取 public runtime health，只接受与 campaign identity 完全一致的 canonical image digest 和 Pipeline SDK digest，再把 digest-pinned、cutover-grade image 身份登记进本 attempt；缺失、格式非法、预存 registry row 或任一 digest 漂移均直接 fail closed。该 preflight identity 进入 sealed launch receipt，offline verifier 再对 image/SDK identity 做精确比对。

r12b 的真实 formal path 证明 rich provider/fetch response 会在 canonical direct
field 与 nested provenance 中重复描述同一 artifact。agent 的递归 selector 因此在
首次 NCBI 和首次 MAFFT 都已完成后误报两个匹配，整段脚本重跑又产生第二个 NCBI
和第二个 MAFFT operation。该 attempt 违反 exact operation set，已在 HMMER 未完成时
主动终止为 NO-GO；不能选择最后一次成功或按相同 content digest 合并历史。SDK 现以
`artifacts.provider_file_ref`、`registered_artifact_ref`、
`fetched_output_ref` 固定 canonical direct-field 选择，executor 必须在本地解析前把
completed response 写到 attempt-local `/workspace/work` 并在 source 修复后复用。live
driver 则在 approval 前拒绝同一 method 的第二个 operation，或已有
`failed|recovery_failed` 后的任何新增科学 approval，从而在 provider/runner dispatch
前停止已确定不合格的 attempt。跨 run 显式 adopted/superseded chain 是
[canonical scientific chain adoption and attempt closure](../architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md)
提案，本 Goal 不实现。

r13 在 commit `240420676396aaa67120bc07fdc55ee443cbe69e` 上完成了 exact-six
真实 known-positive probe；formal researcher 的四次真实 PubMed invocation 中，两次
empty/failed、两次成功。后两者分别封存十条 citation 与定点 PMID `30530468`，属于
合理的有界迭代检索。但 researcher `task.finish.evidence_refs` 同时列出两个 PubMed
artifacts，仅在 summary prose 中称其中一个为 primary。旧 collector 又错误地要求整个
session 的 PubMed source 只来自一个 invocation。没有结构化选择 authority 时，不能按
prose/latest/首成功/结果数事后猜测；因此 operator 停止 r13，未生成 eligible bundle 或
Chrome observation receipt，r13 永久 NO-GO。ledger 保守累计
`33,878,587 / 500,000,000`，含仍按 reservation 计费的 `921,516` token，零 breach。
当前小修允许多次 bounded PubMed query，但要求 researcher finish exactly-one PubMed
artifact adoption，并由 collector/blocker/verifier 闭合 nullable task/lane lineage。完整
invocation universe 与 disposition 的 `@2` 设计只记录在
[canonical research evidence adoption and invocation history](../architecture-proposals/canonical-research-evidence-adoption-and-invocation-history.md)，本 Goal 不实现。

r14 在 commit `1e0b5cfdb2d3014433d76e128ff9467611c8fbe3` 上证明新的 PubMed
adoption 合同可工作，probe 也再次完成 exact-six；formal NCBI/MAFFT/hmmbuild/HMMER
各只有一次。但旧 `sandbox.exec` 最大 `900s` 先于耗时约 `1375.8s` 的真实 EBI HMMER
完成而超时，随后 `1800s` public/session deadline 产生
`host_public_api_transport_failed`；HMMER 又在 failure bundle decision 后迟到完成。
r14 因此永久 NO-GO，无 terminal Chrome receipt，不能追认或复用。其 MICU 增量
`1,397,357`，累计 `35,275,944 / 500,000,000`，无 breach。当前小修仅把 AOX
HMM-capable path 固定为 poll `1800s`、`sandbox.exec=3600s`/`s09.exec_policy.v2`、
formal session/public request `>=7200s`，并在 launch 与 HMMER approval 前 fail-fast；
通用 async continuation/cancellation/quiescent sealing 只记录在
[durable async controlled operation and quiescent sealing](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/durable-async-controlled-operation-and-quiescent-sealing.md)，该历史 Goal 当时未实现，后续已由独立 reliability change 落地。

r15 在 commit `8a5a98fc483784c222e7a5c2e35f50114e559822`、config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`
上验证了 r14 timeout 小修：probe exact-six 全部各执行一次；formal NCBI
`op_d49fa261d272`、MAFFT `op_5b585f37d2a9`、hmmbuild
`op_82884ee33093`、EBI HMMER `op_d07bbe65636e` 也各只有一个并全部完成，
其中 HMMER 约 24.5 分钟后仍在 `1800s < 3600s < 7200s` 层级内成功。首个 formal
NCBI approval `appr_06a653364c9b` 由同进程 Chrome UI 真实批准，driver 没有代行该
resolve route。

但 HMMER 后的 score-filter 产生 37,722 个 accession；metadata object 精确为
`513,565 B`，artifact register request frame 精确为 `513,803 B`。旧 control server
把一次 `recv(65536)` 当成完整 JSON-RPC frame，截断 NDJSON 并让 socket worker 因
unterminated JSON 退出。checkpoint recovery 未重放任何已完成外部 operation，但后续
约 `514,234 B` 的 UniProt request frame 再次触发 transport failure，且在
`bio.uniprot_fetch` controlled operation/provider I/O 建立前停止。execution 明确 failed，
research completed，reporting 保持 `todo` 且无 published report；browser terminal target
不存在。收口后 nonterminal controlled operation、nonterminal sandbox run 和 pending
approval 均为零，因此可以封存失败证据，但不能解释成正向完成。

r15 attempt `positive-fb3cd26654cc4c3eb955a1f7c2384c90` 的 non-eligible bundle
digest 是
`sha256:011fc6163c83fde37f7da7cd8045b2213fd42277f6deecc36f7d297f190817ba`；
离线 verifier 通过只证明 failure bundle 内部完整。campaign decision 仍是 **NO-GO**，
digest
`sha256:76897f22f344440465572fe31a3781443ff46a2c3c994506838a6f2529ce7e41`，
blocker 为 `task_failed` / `attempt[1].scientific_outcome`。MICU 从
`35,727,334` 增至 `40,115,002 / 500,000,000`，r15 delta `4,387,668`，零
breach/overage；两个历史 unsettled reservation 合计 `2,187,716` 已同时包含在前后
snapshot，不是 r15 新消费，也不得静默释放。r15 永久 NO-GO，其 roots、operations、
artifacts、browser state 与 scientific responses 均不得复用。

该缺陷按小型 harness 修复处理：sandbox control channel 每个 Unix socket connection
只接受一个 JSON-RPC 2.0 NDJSON frame，请求和响应 payload 均以 `4 MiB` 为硬上限
（不含终止 newline）；receiver 必须跨任意 `recv` chunk 聚合到 newline，不能把
`64 KiB` chunk size 当 frame 上限。畸形 UTF-8/JSON、残帧、response identity 漂移和超限
均结构化 fail closed；首 newline 后已观察到的非空 trailing bytes 在 dispatch 前拒绝。
硬保证是每 connection 最多执行一个 request；首帧接受后才晚到的第二帧可以只遇到连接关闭、
不保证第二个 error，但绝不执行第二个 method/operation。单连接失败不能杀死 accept worker，
SDK 对请求 preflight 和响应聚合实施对称边界。此 correction 不新增 canonical state，
不升级 sandbox protocol/image version；后续正向证明仍须 fresh commit/config pin 与 roots。

非 null JSON-RPC request id 只允许 UTF-8 bytes `<=256` 的 string 或 signed int64，bool
不合法。request 其他 semantic validation 失败时 error 保留已安全提取的 id；id 自身超限、
非法或无法提取时 error 使用 `id=null`，SDK 仍要求 response id 精确相等。

后续 UniProt correction 固定为 `provider_config:uniprot:v3` / `uniprot_primary_sequence_identity@2`，但 route policy id 仍是
`bio.uniprot_fetch.provider:v1`。exact HMMER accession set 通过一次 SDK call、一次
approval 和一个 controlled operation 提交；operation 总 cap 是 `100000`，Host 固定按
每 query 最多 `100` accession 拆分。SDK `batch_size` 仍是每 response page 的 `size`
（上限 `100`），每个 query 独立跟随 `Link: rel=next` 且各自最多 `100` 页。approval
前 resource estimate 显式记录 accession/query batch 数：历史有缺口的 r15 集合是 37,722，纠正后当前完整集合是 37,772，两者都是 378 个内部 query，而不是 378 个 operation/approval。transcript 记录 query/page index、
accession range/count/digest 与 response digest；duplicate 检测使用 frequency-map 单次扫描，
只对重复 key 稳定排序。当前输入已是 primary UniProt accession，切换 async ID Mapping
会引入 durable job handle、submit/poll/result resume、幂等、approval 以及 evidence/verifier
schema 迁移，属于本 Goal 不实施的大架构调整。

每个 UniProt response page 还必须绑定 producing query 的 exact accession slice/digest；即使
record identity 在 operation-wide set 内，只要属于另一个 query，也以
`provider_identity_mismatch` 拒绝 cross-query swap。`378` 只是默认 query cap `100` 下 SDK
向 approval 展示的透明预测，不是 limit authority；Host 注入 config 可收紧 actual cap，并在
provider I/O 前最终校验。Host-authoritative canonical estimate/limit snapshot 与 approval/config
binding 的大改单独记录在
[Host-authoritative controlled-operation resource estimate and limit snapshot](../architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md)，
本 Goal 不实现。

UniProt `Link: rel=next` 还必须停留在 exact
`https://rest.uniprot.org[:443]/uniprotkb/search`，不得携带 userinfo/fragment。malformed 或
off-origin link 以 `provider_schema_drift` fail closed；diagnostic 只记录 link digest 和固定
expected endpoint，不回显潜在私有/恶意 URL。

active sequence 与 exact-requested typed `Inactive/DELETED|MERGED` 必须对 complete
requested set 形成互斥分区。`DELETED` 封存非空 canonical reason，`MERGED`
封存非空、去重 replacement-target annotations；两类均封存 UniParc id、
release/retrieval 与 response/record digests，固定 `identity_replaced=false`，不含
sequence/audit，不跟随或抓取 replacement。`DEMERGED`、unknown/malformed/missing
identity 仍 fail closed。UniProt HTTP failure 只附 query-batch
index/count/start/count/digest 和 completed/requested page progress，不回显 raw URL、
accession values/list 或 cursor。

EBI HMMER correction 绑定 `provider_config:ebi_hmmer:v2`，result `page_size`
默认/上限是 `1000`。poll 显式请求 `page=1&page_size=<configured>`，但
terminal payload 只作 status 和 `stats.nreported` closure；result 必须从独立
显式 page 1 开始并用同宽读取全部稳定 `page_count`。非截断 raw
count 必须等于 `nreported`，SUCCESS empty 只是
`nreported=0/page_count=0/hits=[]`；terminal body 的 hits 不得当 page 1。
`max_hits`、provider order、score filter 和 parsed schema 不变。

sandbox provider request draft 建立后的 `PipelineSdkFailure` 先通过同一 artifact
boundary 登记 request/observation/error exact-three diagnostic artifacts，再保留原
canonical failure 并附 safe refs；不 retry/replay，不改变 17 件 deliverable。

public evidence scanner 的修复同样保持窄边界：只新增四个 AOX logical manifest suffix
`/provider_parsed/metadata.json`、`/provider_parsed/parsed_hits.csv`、
`/provider_parsed/proteins.fasta`、`/provider_parsed/sequences.fasta`，并仅在 sealed Python
source 中识别 `Path("aox_hmm")/p.name` 这类真实 `/` path-join syntax，避免把 `/p.name`
误判为 Host absolute path。它不开放整个 `/provider_parsed/`；unknown suffix、traversal、
任意 `prefix)/p.name`、`/home/...`、`/tmp/...` 与其他未知 absolute path 仍 fail closed。

r16-r19 继续提供真实诊断，但全部是严格、永久 **NO-GO**。r16 的 launch env 漏掉
`OPENZYME_LLM_CONTEXT_WINDOW_TOKENS=200000`，在任何科学 I/O 前以
`aox_launch_effective_config_schema_invalid` 停止；r17 随后因 transient
`aox_launch_toolchain_pin_execution_failed` 停止，紧接的独立只读 full-pin probe 虽通过，
也不能复活该失败 pin root。r18 在 commit
`e6aaa085c94cb1b63bbda5ff44395817495a88cc` 上成功 pin，config digest 为
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`；
attempt `positive-bb0e97ce9db847c58c9c0dc0b7d0bddf` 的 NCBI probe 完成后，MAFFT
controlled operation 在约 `64s` 以 `hpc_runner_timeout` 停止，与 runner 的 `60s`
preflight/default bound 一致。后续独立四工具链 recovery probe 通过，因此保持 transient
failure 分类而没有放宽 gate。r18 non-eligible
bundle 为
`sha256:4770bdb0d327adfd55826181b5fafbc6de3312e5953e745fefc7562627e5fbf1`，
sealed decision 为
`sha256:f5521eb8e0de8dab60c7dc139dcdfd22515859d7701e234c1f17fa0108e8f520`，
ledger 累计 `41,023,337 / 500,000,000`，零 breach/overage。

r19 attempt `positive-98b4c1cdab5a47e6bd83d3c91b64d9fe` 最终完成六个真实 probe
operation：NCBI `op_2bfe8f7ec798`、UniProt `op_077c1756762a`、MAFFT
`op_4b74f52b785f`、hmmbuild `op_6d911baa02ef`、CD-HIT
`op_0c33b3927655` 与 HMMalign `op_cfd9780670c5`。但第一段 operation-bearing
`sandbox.exec` 在 NCBI 完成后把
`registered_artifact_ref(provider_file_ref(...))` 错误串联，产生
`artifact_registration_projection_invalid` / `sandbox_exec_nonzero`；修复 source 后，
第二段 run 复用 attempt-local NCBI checkpoint 并执行其余五个 operation。结果横跨两个
operation-bearing run、两个 source snapshot，且历史中仍有 failed sandbox run，不满足 probe
exact-one successful run/source 与无 failed-run history 的资格合同。non-eligible bundle
`sha256:d811da6e9fd0f291413c7f0369c6399f24e38d94997dc0d24516155773a72f16`
和 sealed **NO-GO** decision
`sha256:f067ac844a5cd2df557d8b03b6ad89eb05c2b58f94fc502f04e976d9e55ccf84`
均只封存失败事实；ledger 累计 `41,557,461 / 500,000,000`，remaining
`458,442,539`，零 breach/overage。r16-r19 的 pin/campaign roots、operation、artifact、
browser state 与 scientific response 均不得进入 fresh attempt。

对应小修不改变 exact-operation-set：三个 selector 是互斥终点，而非可组合转换。
`provider_file_ref` 只消费 direct provider response，`fetched_output_ref` 只消费 direct
`ws.fetch_outputs` response，`registered_artifact_ref` 只消费 direct real
`artifacts.register` response；禁止 selector chaining 与 synthetic registration envelope。
任何 operation-bearing sandbox run 一旦 failed，该 attempt 在下一次外部 dispatch approval 前
即 fail closed，checkpoint 只作失败诊断。artifact source provenance 由 Host 绑定：control
socket register、provider artifactization 与 HPC fetch 必须显式使用当前 Host-sealed run/operation
source snapshot，不能从 stale `last_command_summary` 猜测，也不能信任 sandbox 自报。若未来要
采用 r19 式 same-attempt cross-run completed effect，必须实施
[canonical scientific chain adoption and attempt closure](../architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md)
中的 durable adoption/closure 与 bundle/verifier 升级；该大改不在本 Goal 实现。

r20-r22 在 commit `8791dac334a2418d9ef5ad15b89ff32b19429f32` 上继续使用全新且
不可复用的 roots。r20 pin 因 bounded remote preflight timeout 停止；r21 的 MAFFT、
CD-HIT、hmmbuild 已通过，但 HMMalign pin command timeout，随后独立只读 replay 在约
`1.12s` 完成五项检查也不能复活 r21。r22 clean pin 则完整通过，config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`，
identity digest
`sha256:6a4ff9508d322c6c56e39c88a8a3fc9e2f3e45c940bde7316c0d6a7121ec7da6`，
prerequisite digest
`sha256:efd49d9f9c05c8766a8c50237329147f5414e37bb368552a99734affb47f5f9e`，
workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:b4585974e9e7aa04151974abb53fe085af0c98e701a687bead38c058d9ed0481`，
SDK digest
`sha256:8512749df96ba1efa61ccd19a010e8051b57b67b2f0b9a6947f147c2c8695409`。

r22 attempt `positive-8f9cc348326244939469da424daf046b` 的 known-positive probe 在唯一
成功 run `srun_cf22230c4b99` / source snapshot 内精确完成六项：NCBI
`op_9a42e4bd8a1d`、UniProt `op_534d9a14e6f0`、MAFFT `op_58935fca200d`、
hmmbuild `op_a70cf75b40f9`、CD-HIT `op_5da62f58a783`、HMMalign
`op_207a26459721`。独立 formal session 中，Chrome context `aox-r22-cutover` 对 approval
`appr_a09dd0d824b5` 批准 exact NCBI operation `op_ca8f635e43b9`，operation identity
`sha256:f5d99a6bf789ffdcc155c550a8edb20254e7866a8493eda2dadba0637ab7b0a6`，
并恢复同一 `srun_86107f5b8e3f` / `sw_a2320c75a37b5f96751de797`。这证明 canonical
approval-resume，但没有 terminal Chrome observation receipt，不能作为 GO 的浏览器验收。

formal run 随后完成真实 NCBI、MAFFT `op_f71b4d392554` 与 hmmbuild
`op_81853557a565`，但把规范化 `AOX_ref.hmm` 登记为自由文本 `kind="model"`。
`model` 不属于九值 `ArtifactKind`，因此本地 artifact registration fail closed；failed-run
pre-dispatch guard 阻止 EBI HMMER、formal UniProt、CD-HIT、HMMalign 及其他后续
operation，execution task 被显式置为 failed。r22 永久 **NO-GO**：offline verifier
无问题通过的 non-eligible bundle 为
`sha256:2825e71fdde04d705591a97cc5184371c1735c9e24cbf64fd1fcac67818c05fe`，
sealed decision 为
`sha256:2338261b56076744bfdab7b12d78b0f0ebf5436a8e64bd814b8c145101ee0345`，
blocker `task_failed`；MICU 累计 `43,593,190 / 500,000,000`，remaining
`456,406,810`，零 breach/overage。r20-r22 任何 state、operation、artifact 或 response
bytes 均不得进入新 attempt。

对应局部修复不扩充 artifact kind：SDK 在 control call 前用闭集校验，Host boundary 为旧
SDK/绕过路径重复校验，非法值统一返回 non-retryable `artifact_kind_invalid`；bio-tool
runner declaration 的显式 invalid kind 不再按扩展名静默回退，显式 valid-but-wrong
kind/format 也在 runner dispatch 前 fail closed。AOX final
contract 固定 FASTA=`sequence/fasta`、HMM=`result/hmm`、CSV=`result/csv`、
JSON=`result/json`；只有三个声明的 derived-empty FASTA 额外允许
`fasta_zero_records@1`。online copy/cache-hit、fault target 与 offline verifier 都必须以
`aox_fixed_deliverable_artifact_contract@1` 同时绑定 exact path/kind/format；任一字段漂移或
缺失均不能形成 cutover-eligible evidence。该 correction 不新增顶层状态、重放或跨 run
adoption 语义。

r23 在 commit `3e9d9d3ddc74bbce063d68cb7ee4c802b05c585a` 上建立全新 pin/campaign，
effective config digest 仍为
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`，
workflow ref 为
`workflow:aox-hmm-live@2.0.0#sha256:1afbeb39a02202c3a583c30dc189f611b5dda6150d192a738719956ea766ac8c`；
pin identity/prerequisite 文件的 byte digest 分别是
`sha256:6ec59662e93fadc3304869e0fcc6d28c9bb88f3f479e50b1e57e6e46f332ddca` 与
`sha256:9ba810d3603528a052bf38f97190f34f9bcf4afa863721916ba8064b3e080a7e`。
真实 known-positive run 精确完成 NCBI `op_fa2b75ad4e98`、UniProt
`op_1927c012673f`、MAFFT `op_4bebc9b67883`、hmmbuild `op_ec1ccc3a9872`、
CD-HIT `op_42ebf76047a7` 和 HMMalign `op_a987f91a77aa`。但生成源码使用
`f"{OUT}/provider/ncbi"` / `f"{OUT}/provider/uniprot"`，public-safe raw source
scanner 把其中 slash-prefixed suffix 误判为未知 Host absolute path，最终以
`probe_attestation_unavailable` 把六项全标失败。该结果是 attestation false negative，
不能事后追认为 probe pass。局部修复要求完整 `/workspace/output/provider/...` literal，
并用真实 sealed-source envelope verifier 做回归；全局 public-safe scanner 没有放宽。

独立 formal run 完成真实 NCBI `op_68e06baa18d6`、MAFFT
`op_cc9aa132aa4c`、hmmbuild `op_344f8fcce571` 与 EBI HMMER
`op_df69465ad7a8`。HMMER 产生 68,542 条 parsed row，score-filter 精确产生
37,722 个 UniProt accession。Chrome 对 formal NCBI approval
`appr_3c8927f9fcb6` 批准并恢复同一 operation；这只证明 approval-resume，
不是缺失的 terminal Chrome receipt。随后唯一 UniProt operation
`op_b5db24e5be07` 进入 running/approved，并开始 378 个 Host 内部 query batch。
session lease 最后一次 heartbeat 是 `2026-07-19T07:44:21Z`，expiry 为
`07:49:21Z`；旧 scheduler 在 approval/provider 等待期间遇到一次 SQLite contention 后
永久停止 heartbeat。租约过期后 repository 正确拒绝下一次 canonical write。
`RUN_FAILURE.json` digest 为
`sha256:d294b1e243c274c444b3a7b6655d2397c6877c8b40a2e599738d2ab820688a80`，
记录 `bio.uniprot_fetch` 的 stale-business-write fence。这是 runtime ownership failure，
不是科学 empty/negative；不存在 post-UniProt target、HMMalign、motif、CD-HIT、graph、
summary、published report 或 terminal browser receipt。

r23 永久 **NO-GO**。离线 verifier 无问题通过的 non-eligible failure bundle 是
`sha256:cd48188a02cf970a2c392a226d97972675a548c86eb8abe67b9fe4d134d2def8`，
sealed decision 是
`sha256:93d652032d8098bdab668fe3e4cc7c5d7311a8632c57b0cb78b9838c0c1376c9`，
blocker 为 `internal_error` / `attempt[1].scientific_outcome`。MICU 从
`43,593,190` 增至 `45,455,060 / 500,000,000`，remaining `454,544,940`，
零 breach/overage；driver 没有浪费预算继续 positive 2 或 fault。r23 的 root、operation、
provider response、browser state 与 scientific bytes 均不得进入新 attempt。

对应小修让 file-backed heartbeat 的每次尝试和 contention retry 都新建/关闭独立
repository connection，只对 SQLite `BUSY` / `LOCKED` 在 active lease deadline 内有界退避，
其他异常显式传播，confirmed lease loss 与 commit fencing 保持 fail closed。stale write
跨 sandbox control、Pipeline SDK 与 Host API 稳定映射为 non-retryable
`runtime_write_fenced`，不再退化为 generic `sandbox_transport_error`。原始异常文本不进入公开
投影；既有 Host-private logging 语义保持不变。
这不把 37,722-accession request 拆成多个 controlled operation，也不实施 durable async
controlled-operation continuation；后者仍属于已记录但本 Goal 不实施的大架构调整。

r25 pinned commit `6b9ac473fe01376d144ae800352a06e5d016223c`，但其 scientific
artifact 与 operation-bearing run 都不可用，因此永久 **NO-GO**。EBI HMMER
remote job 约 `24s` 已 terminal；旧 adapter 把 provider 默认 50-hit terminal body
当 page 1，再从 `page=2&page_size=100` 开始，漏掉索引 50..99。terminal
`stats.nreported` 是 68,592，r25 却只封存 68,542，且缺失的 50 条全部
高于 AOX score threshold。同 job 的只读恢复诊断以统一
`page_size=1000` 显式读取 page 1..69，得到完整 68,592 条（末页
592）与 37,772 个 score-`>200` accession。这些恢复 bytes/count 只是
diagnostic，不能回填 r25 bundle 或当 cutover result。

旧有缺口的 37,722-accession UniProt request 还首次确认 `A0A034VJ94`
是 exact typed inactive identity：`entryType=Inactive`、
`inactiveReasonType=DELETED`、reason `Not part of a reference proteome`、
`uniParcId=UPI000453BEA2`，无 sequence/audit。旧 contract 将这一 provider-valid
outcome 错误归类为 schema drift。纠正后完整 `37,772` accession set 的 read-only
census 覆盖 `378/378` query batches，枚举出 `5,596` 个 inactive：
`5,594 DELETED`、`2 MERGED`、无其他 reason type；全部 UniParc identity 有效且
raw inactive record 共享 exact-five-key 顶层 shape：`entryType`、
`primaryAccession`、`uniProtkbId`、`inactiveReason` 和
`extraAttributes`。两条 MERGED 分别为
`A0A2U8U0K3 → P18173`（`uniParcId=UPI000A0F4040`）和
`A0A8N4L368 → A0A034VJ86`（`uniParcId=UPI001114BBC8`），均为单
replacement target、无 sequence/audit。
scan manifest 为
`sha256:4d734dd881829450178ed260ef331f7c3a21cdf0006f14ad3daa886c36125458`；
该 census 只是 schema diagnostic，不固定未来 provider cardinality，也不能作为
positive/cutover artifact。当前 correction 接受 exact
requested-primary `DELETED|MERGED` 判别联合，在 length filter 前排除两类 inactive；
MERGED target 只作为 annotation 封存，不跟随、不抓取、不从 replacement/UniParc/HMMER
取 sequence。`DEMERGED`、malformed/unknown/missing partition 仍 fail closed。

r25 的 HMMER bytes、provider responses、checkpoint、operation、artifact refs 和只读
recovery 都不得 adoption。fresh attempt 仍必须独立产生无缺口 HMMER closure、
UniProt active/inactive exact partition、`aox_sequence_length_join@2`、原 17 件固定
deliverable、published report 与 passed offline verification。

collector 当前仍是逐文件写最终 evidence root，单文件 no-replace 不等于 attempt 事务，
也不能统一证明 actual artifact root 与 declared root exact equality。两阶段 prepare/commit、
artifact-root 全闭包、失败原子性与迁移计划已单独记录在
[transactional attempt evidence collection and root closure](../architecture-proposals/transactional-attempt-evidence-collection-and-root-closure.md)，
本 Goal 不实现，也不能用该 proposal 补足任何 live GO evidence。

每个 MAFFT/hmmbuild/hmmalign/CD-HIT cutover receipt 还必须来自 runner-issued `mcp_hpc_toolchain_runtime_identity@1`：runner-owned manifest 决定私有 SIF locator；当前 SSH 窄保证在同一 login shell 中直接用该 resolved pathname 执行，并在 payload 前后哈希同一路径，两个 digest 必须相同。Host 只逐层传递闭集 public projection，collector/verifier 将观察到的 digest 与 sealed prerequisite 精确比较；caller override、missing/mismatch 均 fail closed。该机制证明“同一路径前后未变并被直接执行”，尚不证明 immutable inode/content-addressed snapshot；后者单独记录在 [immutable HPC SIF execution snapshot](../architecture-proposals/immutable-hpc-sif-execution-snapshot.md)，不在本 Goal 实现。Slurm 本身仍可用于一般 runner 任务，但当前没有 job-internal same-execution SIF attestation，因此 Slurm execution 不能构成此 cutover identity。跨层 toolchain 定义收敛属于大改，只记录在 [single-source HPC toolchain contract registry](../architecture-proposals/single-source-hpc-toolchain-contract-registry.md)，不在本 Goal 实现。

GO 只由顺序固定的三次 campaign 聚合得出：

1. positive 1：全新 roots，published report，offline verification passed；
2. positive 2：不同 roots 且 task/operation/invocation/job 证据独立，但 commit/config/workflow/scoring/image/SDK identity 与 positive 1 完全相同；
3. fault：`derived_required_artifact_blob_byte_flip@2` 精确到达 real NCBI exact-14 `proteins.fasta` → `aox_hmm_reference_set_selection@1` → derived `AOX_ref21.fasta` → pending MAFFT seam，产生 `artifact_blob_digest_mismatch`。封存的 `aox_fault_negative_state_closure@1` 必须证明 execution task failed/blocked/cancelled、reporting 未完成/发布、无 ready/published report 或 draft、无 successful alternate consumer、无 downstream fixed deliverable、durable events 与 conversation/final failure receipt 一致；fault attempt 的 MICU 增量同样必须全部归因到本 campaign。

正式 campaign 使用 `--approval-mode chrome-once` 时，只把 positive 1 的首个 formal approval 暴露给同进程 loopback Host 提供的 Web UI。driver 不调用 resolve route；它在触发该 drain 前先记录 durable event cursor，再从该 cursor 重建 resolution/continuation，避免即时浏览器批准与事后 snapshot 竞争。浏览器审批 timeout 从 handoff 发出时独立计时，同时受 attempt 总 deadline 上界约束。用户在 approval card 上批准后，driver 必须从有序 durable events 证明同一 approval、operation digest、sandbox run/workspace 和 continuation 恢复到同一 operation 的 terminal state，并在完成后保留 bounded UI observation window。handoff 对动态身份是完整的：发出 sealed page、Host/UI identity、receipt schema、not-before、target 与 exact expected page state。trusted operator 以 `aox_browser_observation_capture@1` 封装其 Chrome console、page target、exact ordered `list_console_messages` → `evaluate_script` → `take_screenshot` request/response 和 PNG 投影；`openzyme-aox-cutover browser-receipt` 校验闭集并自动计算 raw 23-field receipt，但不证明投影与 MCP 原始 response 的对应关系。final target 必须在 hold 内不存在，且只在 not-before 后执行 mode-0600 sibling-temp、file fsync、atomic no-replace install 与 parent fsync。当前 Host 证据只覆盖 hold polls 未观察到提前 target、post-hold mtime 与两次 stat/read 稳定，不声称证明轮询间连续缺失、operator 原子/fsync provenance 或 browser-origin-complete transcript。该 receipt 加上 browser console 无 application error 才构成当前 trusted-operator Chrome proof；`auto` 模式不能满足这一 GO 条件。任一必需 quorum、digest、分支 closure、published report、offline verification、Chrome proof 或 MICU ledger 条件失败，campaign 只能产生最小 evidence-backed **NO-GO** blocker。

Chrome resolution consumer 只把带闭合 `decision=approved|rejected` 的 canonical
`approval.resolved` command event 当作 operator decision。当前 activity backfill
可能以同一 event type 投影 ApprovalRequest 的 `status`，但不带 `decision`；这种
projection echo 必须忽略，既不能证明批准，也不能解释为拒绝。真正的 canonical
`decision=rejected` 仍立即 fail closed；若有界 deadline 内始终没有 canonical closed
decision，则以 timeout/缺失证据 fail closed。

同进程 coordinator 在成功 drain worker terminal 后还必须发起一次确定发生在
response 之后的 public workspace GET，才能排除最后时刻投影出的
`waiting_approval`。后台 drain 自身异常保持
`runtime_drain_command_failed`；只有 workspace/approval coordination 或 cleanup
异常才归入 coordination failure。一旦 coordination 已失败，后续科学操作不再
允许继续；coordinator 在既有 attempt deadline 内持续轮询并通过 public approval
API reject 后来出现的 pending approval，cleanup 的瞬时 GET/resolve 失败只作为次要
诊断并使用同一 idempotency key 重试，原始失败保持权威。Web UI 同时以五秒、
single-flight-per-generation 的只读 workspace reconciliation 补充 SSE refresh；
session 切换、workspace mutation 和 SSE reducer 写入必须 abort/失效旧 generation，
阻止旧在途响应覆盖较新状态，也不能让挂起的旧 session GET 饿死新 session。

## r26 post-correction 只读预检

最终冻结的 motif implementation/contract digest 分别为
`sha256:795535d9d6c232a79bc9791f8c2780c2f4aa64b234b15a83deb8c76d3406871c`
与
`sha256:71aff3b872aaef3254550db53c7554011923d19293f9c5837ddc4bb8ca0bec10`；
similarity implementation/calculation digest 分别为
`sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5`
与
`sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`。

最终 parser/scorer 对真实 HMMER 3.4 AFA 的只读预检覆盖
`12,273,402` raw bytes、`2,562` records、width `4,700`；raw digest 是
`sha256:d72e36bc5c0431d8f3806eb4d0d0cadb51e7d3825c873610d8e4c0098eccf7a6`，
canonical alignment digest 是
`sha256:2df12971eae2d83c390f22e689e04e493539cf6be2d79599f33823f0f52df836`，
结果为 `517` total pass（含 AAB）和 `516` non-reference pass，约 `0.507s`。
历史 pure-v3 similarity receipt 位于
`/tmp/openzyme-aox-similarity-diagnostic-20260720-final-v3/receipt.json`，digest 为
`sha256:caf483bedbe2865cdf3be0677dbcb3a27d6ccfb9fd1a57bbc0093a35ef90bcf5`。
它在 516 candidates / 132,870 pairs 上得到 516 nodes / 13,778 edges，旧 affinity-only
16-worker graph 用时 `2929.494427s`，32-pair tuple oracle 用时 `16.717732s` 且
mismatch=0；但它绑定的
`sha256:9df7a2afb72ae46473fc20c0a8ceb7b5d3f83ad5e2144bfebeb9bbd88800548d`
与
`sha256:31df5ca6eaf079073bd290550f70646f2ab845faf2dcdae43ffb3fff0c3a7499`
均为 superseded identities，只能作为 `non_cutover=true` 历史诊断，绝不是当前 pin。

临时真实 Podman 2-CPU calibration receipt 位于
`/tmp/openzyme-aox-bio-podman-audit/comparison-receipt.json`，digest 为
`sha256:b9749e6c3f23dd553a1e33b55f7cb9a67a1aee6dfbfae8fb4235ce0aa52f563c`。
它使用 Python `3.12.13`、Biopython `1.87`、NumPy `2.4.4`，完整 132,870 pairs
的 affinity-only 16-worker 和 forced 2-worker 用时分别为 `168.766s` 和 `84.087s`，
均得到 13,778 edges，且 nodes/edges/manifest bytes 与 pure-v3 一致。该普通 `/tmp`
receipt 只证明当前 2-CPU/3600s sandbox 足够且 worker 必须识别 cgroup quota，同样未 seal、
不是 cutover evidence。

reference validation 使用 NumPy `2.4.6`，cutover runtime 则 exact pin NumPy `2.4.4`；
两者 patch 不同且不存在 fallback。最终 independent current-backend comparison receipt
位于 `/tmp/openzyme-aox-final-backend-podman-20260720/aggregate-comparison-receipt.json`，
digest 为
`sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`。
两次 authoritative-source/no-monkeypatch、NumPy `2.4.4`、2-CPU/2-worker run receipt
分别为
`sha256:e48ab741b511aa40e3b056421b3222245ca4e0de2a16eda5843663603d423234`
与
`sha256:e3e89cd85e9cf99756b0fba7ba329baa03cb746d3bcf1993193b282be4f4453b`；
graph/total time 分别为 `393.206478s`/`393.835379s`、
`397.540161s`/`398.171785s`，均完成 516 nodes / 132,870 pairs / 13,778 edges。
两次 raw current-contract nodes/edges/manifest 完全相同；只规范化 pin fields 与
pin-induced manifest closure 后又与 old pure-v3 逐字节相等，non-pin fields 全相等。
production 无 activation counter 且禁止 wrapping，故 correction activation 如实记录
`unavailable`，不伪造 zero。

这不是一次 direct full-set NumPy `2.4.6`/`2.4.4` patch A/B；前者仍仅是 reference
validation context，后者是唯一 cutover pin。最终 receipt 完成 r26 diagnostic/reviewer 与
workflow knowledge repin 前置条件，但自身仍是 ordinary `/tmp`、`non_cutover=true`，
不会改变当前 **NO-GO**，也不得被 fresh attempt adoption。

## r27 blank-world live attempt：永久 NO-GO

r27 以 clean commit
`d922f136fa44fe1142ad58a65647a0eee58ce281` 和 fresh roots 启动 positive
attempt `positive-a02c118c11dc4e7fb0ef516157ad9100`。formal public session 为
`sess_formal_positive-a02c118c11dc4e7fb0ef516157ad9100`，同一 source-bound
sandbox run 为 `srun_d113874405da`。formal NCBI
`op_03f66d724571`、MAFFT `op_df5fcd35a6a5`、hmmbuild
`op_f204992a915e`、EBI HMMER `op_34b43ff3008e` 和 UniProt
`op_3de913af306f` 均达到 `completed`。Chrome 在 canonical approval
`appr_edfdc623cbe0` 上批准并恢复同一个 NCBI operation；由于 attempt 后续失败，
没有 terminal Chrome receipt，不能把这次 approval-resume 单独解释为 Chrome GO proof。

真实 EBI HMMER result 覆盖 69 页、68,592 hits 且 `truncated=false`，版本化
score filter 得到 37,772 个 accession。唯一真实 UniProt operation 对该 exact set
执行 378 个 query batch，闭合为 32,176 active 加 5,596 inactive，其中
5,594 `DELETED`、2 `MERGED`；随后 active-sequence length join 得到 2,561 hits。
这些真实 count 只证明纠正后的 provider/scientific path 到达 post-UniProt join，
不等于 positive 已完成。

join 所需的 sorted identity mappings 使 logical catalog metadata 达到
17,016,803 canonical JSON bytes。旧 SDK 将它内联进 exact 17,767,360-byte control
request，超过保持不变的 4 MiB frame cap。首次登记
`hits_len650_700_200.csv` 因而在 Host dispatch 前以 non-retryable
`sandbox_transport_request_too_large` / `control_socket_request` fail closed。
catalog 中没有该路径的 Artifact row，也没有可供后续采用的 partially registered
scientific artifact。该结果是 harness transport blocker，不是科学 empty，也不授权删除或
截断 identity mappings、提高 frame cap，或把 sandbox working copy 当作 canonical output。

通过自身完整性校验但明确 non-eligible 的 failure bundle digest 为
`sha256:4920739cde6aa9bb7f5fd484674bbbccbc8d385bf7c6c98b872390d922ccac3c`。
sealed campaign decision 是永久 **NO-GO**，blocker 为
`host_public_api_transport_failed` / `attempt[1].scientific_outcome`，decision digest 为
`sha256:4628f5f2a91eed77808b09b875e3daaddf893160503d60850985b714aedd0c0b`。
持久 MICU 账本从 `47,528,993` 增至
`49,959,197 / 500,000,000`，remaining `450,040,803`，hard-limit breach 为零；
positive 1 已失格后，driver 没有继续浪费额度运行 positive 2 或 fault。

r27 永久不可追认为 positive 1，也不得复用或 adoption 其 roots、旧 pin、operation、
provider bytes、mutable sandbox outputs、metadata、artifact refs、browser state、bundle 或
decision。完成 bounded metadata-transport correction 后，下一轮必须生成新的 clean
commit/SDK pin 与全新 blank-world roots，再独立执行两次 positive 和一次 controlled fault；
当前文档不得预写其结果。

correction 后的只读 transport diagnostic 使用 r27 保留的 exact HMMER/UniProt
输入，在 campaign root 外的全新单进程 file-backed SQLite/workspace 重新执行当前
`aox_sequence_length_join@2` 与真实 Unix-socket registration。它重现 2,561 hits、
`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`
CSV 和 17,016,803-byte / `sha256:873a5ff9be6114f761b0ed48a9be2509c74bbb024955555dfe4700d015524f25`
logical metadata；current SDK 产生同 digest/size 的唯一 sidecar，Host catalog 逐字段保留完整
logical metadata，而 `artifact_registration_response@2` 仅 1,234 bytes 并可由 strict
selector 选出同 CSV digest。该诊断没有 provider/HPC/MICU I/O，`diagnostic_only=true`，
不改变 r27 的永久 NO-GO，也不是下一轮可采用的 Artifact 或 cutover evidence。

## r28 blank-world live attempt：永久 NO-GO

r28 以 clean commit `bea16bef2a54c8fb75a7649fe8a17a0c6ee7bc07`、config
digest `sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`
和 fresh roots 启动 positive attempt
`positive-cfddd24986bf465fa49ef70449c5ec63`。known-positive probe 的两个真实
provider 与四个真实 HPC operation 全部完成；formal researcher 也选择了唯一 PubMed
artifact `art_provider_0f7b34ba9a29`，其中包含真实 PMID `39273329` 与 `37659597`。
formal executor 尚未进入任何 controlled operation，因此这次运行没有验证正式路径的
large-metadata transport correction。

formal executor 有三次独立 MICU 请求精确触达 sealed `120s` timeout；当前配置
`max_retries=0`，scheduler 虽保持同一 durable task 恢复，却增加了 restore/diagnostic
压力。恢复过程中，`world.inspect` 因错误复用 closed opaque-ref namespace 规则，三次拒绝
安全且合法的 canonical task id
`aox_execution_cutover_daf581ffa2b34590940f55322e6bb5ec`。最终
`srun_9b0a7b28365f` 将 `- <<'PY'...` 作为 Python 的 literal argv element；
`sandbox.exec` 没有隐式 shell parsing，故 Python exit `2` / `sandbox_exec_nonzero`。
该 run 的 operation list 为空，但真实 nonzero run 仍按既定规则使 attempt 失格；executor
随后显式 `task.finish(failed)`。formal 没有 approval，也没有可提交的 Chrome terminal
observation。

bundle `sha256:be8edc94d95f9800dfae403270372447e6b4335388b0d2f51bd23cbfa472c577`
经独立 offline verify 无 integrity issue，但科学资格明确为 non-eligible。sealed decision
保持 **NO-GO**，blocker 为 `task_failed` / `attempt[1].scientific_outcome`，decision
digest 为 `sha256:5b832c85c1c79e0903a3a6cfa1ab1696b8d58642c2f79f47bd5125c312e57d56`。
MICU 累计从 `49,959,197` 增至 `55,691,311 / 500,000,000`，remaining
`444,308,689`，零 breach/overage；positive 1 失格后没有继续运行 positive 2 或 fault。

r28 永久不可复用。局部 correction 让 `world.inspect` 接受安全 product task id，在
agent-facing schema 明示 direct argv，并在 source snapshot、SandboxRun 与进程产生前拒绝
未包裹的 Python heredoc，返回 typed corrective hint；不得自动包成 shell，也不放宽真实
nonzero-run fail-closed。下一次 fresh pin 只把 live request envelope 调整为 `300s`
timeout、一次 pre-response retry 与 configured `max_tokens=8192` request cap；这些是
请求设置而不是消费目标，且必须进入新 config identity。

## r29 blank-world live attempt：永久 NO-GO

r29 以 clean commit `2c0adce5adf5905560fa552c3efabc70c6f7d31d`、config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
和 fresh roots 启动 positive attempt
`positive-39ce51e320414f149023e2ddc5f55e18`。sealed config 已精确绑定
`timeout=300`、`max_retries=1`、`max_tokens=8192` 与
`context_window_tokens=200000`。

attempt-local 持久状态和 probe failure record 显示，真实 NCBI
`op_09ec33fb0dd8`、MAFFT `op_7a35f469bd77`、hmmbuild
`op_d80afc32de56`、UniProt `op_f4b0261fb759` 已完成。CD-HIT
`op_9d6144ff379a` 使用的 UniProt FASTA digest 为
`sha256:fbaf487d05f7a9cdff8afae156367ae521378aa67036e62ae7ea514b762add97`，
但在 payload 执行前的 staging 阶段失败；HMMalign 未运行。Host-trusted
`runner_failure@1` 精确记录 `phase=input_parent`、`input_ordinal=1`、
`returncode=255`、`timed_out=false`、`elapsed_seconds=60.267664`。这只能证明
SSH input-parent staging command 失败；private stderr 没有越过安全边界，不能进一步断言
DNS、认证或具体网络层根因。此前 exact toolchain pin 和随后只读 SSH connectivity probe
均成功，只能说明现象与已恢复的 transient connectivity 一致，不能授权续跑或复用。

故障发生在 independent probe 内且早于 formal product session；formal task、controlled
operation、approval、Chrome receipt 与 report 均未产生。bundle 的六项 known-positive
check 因 `probe_attestation_unavailable` 诚实保持 failed；上述四个已完成 operation 来自
attempt-local 持久状态，不能写成 bundle 已证明四项 check passed。non-eligible bundle 自身
offline integrity verify 通过，digest 为
`sha256:84c5083e6b1bc562ffb7c6826fb74010c6ea2807998c7cd074962ed263feae1e`。
sealed campaign decision 保持 **NO-GO**，blocker 为 `hpc_staging_failed` /
`attempt[1].scientific_outcome`，decision digest 为
`sha256:d7073ddcff93146fdc72330de4143bf78b1e03a13075038ca680d56ac7270867`。
MICU 从 `55,691,311` 增至 `56,276,589 / 500,000,000`，本次 delta
`585,278`，remaining `443,723,411`，零 breach/overage；positive 2 与 fault 未运行。

r29 的 roots、pin、operation、artifact 与 browser state 永久不可复用。本次局部 harness
correction 只把 adapter 已产生的安全顶层 `stage`、boolean `retryable`、sanitized hint 与
closed `details.runner_failure` 经 sandbox control response 传入 `PipelineSdkError`；不新增
自动 retry、reconnect、重开 approval、backend fallback 或 effect adoption。下一轮必须基于
新的 clean commit/SDK pin 与全新 blank-world roots。

## r30 blank-world live attempt：永久 NO-GO

r30 以 clean commit `24c403effb2a5f30821392384c552c83a03f4cf5`、config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
和 fresh roots 启动 positive attempt
`positive-7d634900da8c4cc3b1580f68a9c055df`。独立 known-positive probe 的真实
NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 check 全部通过。formal
路径随后完成真实 NCBI、MAFFT、hmmbuild 与 EBI HMMER；HMMER 完整物化
`68,592` hits / `69` pages，`truncated=false`。formal UniProt 在唯一受控 operation
内完成 `378` 个 query batch，抓取并校验全部 `37,772` 个 requested identity，其中
`32,176` 个是 active sequence、`5,596` 个是 typed inactive identity。

失败发生在 UniProt provider artifactization，而不是 provider 抓取或科学 empty 分支。
`providers/uniprot/provider_parsed/sequences.fasta` 已形成 `20,297,730` bytes 的
FASTA draft，但其 Artifact metadata 内联了 `32,176` 项 active-sequence
`sequence_digests` map，超过
ArtifactBoundary 的 `256 KiB` metadata limit；此时 `69,353,082` bytes 的 raw pages
Artifact 已登记。Host 以 `provider_artifactization_failed`、stage
`bio_artifact_registration`、`retryable=false` 显式失败，sandbox exit `1`。不得把已登记的
raw pages、尚未登记的 FASTA draft 或既有 provider effects 追认为可消费的 formal output。

Chrome 确实通过 Web UI 批准了 formal operation `op_a6d1d125c83c`，但运行没有到达
terminal observation handoff，因此没有 terminal Chrome proof。formal report 未生成，
positive 2 与 controlled fault 也未运行。non-eligible bundle 自身 offline verify 通过且
`issues=[]`，digest 为
`sha256:825d2a13c9188c3fadc5c130c2c7ce0b10444c0a957ed2fb44e4c67f04d92887`；
sealed decision 保持永久 **NO-GO**，digest 为
`sha256:e8122845ff9e9b2467990da4cfacee02782311c0c11d6bef636721e824a45ecb`。
MICU 从 `56,276,589` 增至 `58,976,497 / 500,000,000`，delta `2,699,908`，
remaining `441,023,503`，零 breach/overage。

r30 的 roots、pin、operation、provider bytes、artifact、browser state、bundle 与 decision
永久不可复用。局部 correction 要求完整 active/inactive identity partition 留在独立
canonical `metadata.json`，FASTA Artifact metadata 仅以 sequence count、exact canonical
index digest 与 contract id 替代线性 active-sequence digest map，并继续保留固定 provider
provenance。该 bounded catalog summary 不作为 cutover eligibility 输入；formal UniProt
既有的 raw→parsed metadata→FASTA 科学闭包仍须由 offline verifier 独立重算，其他
provider 路径继续依赖各自既有 byte-Artifact/operation contract，不能把摘要当作 raw
normalization 证明；
`batch_size` 必须是 exact non-bool integer，并在登记任一 draft 前对全部 artifact draft
执行 path-conflict preflight。该 correction 不提高 metadata limit、不重放 provider、不采用
r30 effects，也不改变 fail-closed 语义。下一轮必须使用新的 clean commit/config/SDK pin
与全新 blank-world roots。

## r31 blank-world live attempt：永久 NO-GO

r31 以 clean commit `d430be9d106f5a978794a0c588e8fcd28e013e7f`、相同 config
digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
及当时 workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:eb4a36e2d4ef3e294406d6fcf93d8414c00afa8fff8d7060ef7fed34f7632d98`
和 fresh roots 启动 positive attempt
`positive-9dfa89f23352424f8ba0f1d993ad6a3f`。独立 known-positive probe 再次完成
真实 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 check，且保持 formal
data isolation；formal researcher 也选择了真实 PubMed artifact
`art_provider_5eaf6f6b2864`。

formal executor 随后在 `/workspace/src` 没有任何显式源码文件时，以
`sandbox.exec` 的 `python -c` 请求探测已安装 package/callable signature。现有 runtime
正确地在创建 `SandboxRun`、process 和任何 controlled operation 前对整个 source tree
执行 snapshot，因此以 `source_snapshot_empty` fail closed。execution task
`aox_execution_cutover_4f9d1ec865484a73b4544cdb8ccedfcb` 显式 failed，reporter 保持
blocked；没有 formal approval、Chrome handoff、formal provider/HPC operation、published
report、positive 2 或 controlled fault。

non-eligible bundle 的 network-free verification 为 `issues=[]`，digest
`sha256:72a118a7b888cecc066274e9b101a36d0d95cce8d3cf4e7e93c0c0f5d9db730a`；
sealed decision 保持永久 **NO-GO**，digest
`sha256:762cabdc53719ce4129755a35a33656d13ed6899f3164cf8113b60b57c31313c`。
MICU 从 `58,976,497` 增至 `59,877,108 / 500,000,000`，delta `900,611`，
remaining `440,122,892`，零 breach/overage。

r31 的 roots、effects、artifacts、browser state、bundle 与 decision 永久不可复用。局部
correction 不改变正确的 snapshot runtime，只通过 tool descriptor、executor contract、受控
docs 与 probe/formal prompt 明示：通过前序校验并进入 source preflight 的每次
`sandbox.exec`，包括 `python -c`、package/signature inspection 和 diagnostics，都要求
eligible non-empty `/workspace/src` 并封存 whole-tree snapshot；前序校验仍可先返回自身
错误。只读 API facts 优先来自 controlled docs，确需 runtime introspection 时先 author 显式
inspection source。empty-source error 增加 `sandbox.exec` whole-tree factual pre-run hint，
direct `artifacts.snapshot_code` 则返回 selection-aware recovery；不得生成 placeholder source、
增加无审计 inspection fallback 或放宽 provenance。变更后的 workflow knowledge 与 manifest
必须重算 digest；下一轮必须使用 fresh clean commit/config/workflow pin 与全新 roots。

## r32 blank-world live attempt：永久 NO-GO

r32 以 clean commit `f54ea431ceaeff9274527afb20816c8110e39ee3`、相同 config
digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
及当时 workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:0d78c5246018b71a7ef79258cc410dfd4f300495bb4e5a37af58e096a0e29241`
和 fresh roots 启动 positive attempt
`positive-9f2badd3274d42fdabb4e1421f7d5e47`。独立 known-positive probe 完成
真实 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 check；formal researcher
完成真实 PubMed。Chrome UI 对 canonical approval `appr_3ea9addd5614` 批准 formal NCBI
operation `op_b5857f8371a9`，driver 观察到同 operation/digest continuation，NCBI operation
真实完成。

同一 source-bound sandbox run `srun_0ee366725cd1` 随后在封存源码
`aox_cutover.py:268` 将 `result.to_fasta()` 返回的 Python `str` 直接传给 bytes-only
`Path.write_bytes` helper，以
`TypeError: memoryview: a bytes-like object is required, not 'str'` / `sandbox_exec_nonzero`
fail closed。execution task 显式 failed；reporter 发布诚实失败报告，但没有后续 formal
provider/HPC operation、terminal Chrome observation、eligible report、positive 2 或 fault。

non-eligible bundle 的 network-free verification 为 `issues=[]`，digest
`sha256:039cbb6551cd785f9c5c9ac023cfa6d899503d52a0df7c570ced942e603411a6`；
sealed decision 保持永久 **NO-GO**，digest
`sha256:7b168335c45f7e8865aea8e92f591596c5a743d24894d1a958adc2882e45e5e8`。
MICU 从 `59,877,108` 增至 `62,008,441 / 500,000,000`，delta `2,131,333`，
remaining `437,991,559`，零 breach/overage。

r32 的 roots、effects、artifacts、browser state、bundle 与 decision 永久不可复用。局部
correction 不修改科学 callable 或 implementation digest，而是把 primary FASTA/CSV/JSON
accessor 与 `metadata_json()` 的 agent-facing 类型明确为 `str`、`metadata()` 明确为
`dict[str, object]`，并要求 bytes-only writer 前 exactly-once UTF-8 encode；type/annotation
drift 必须 fail closed，禁止 best-effort coercion。AOX SOP digest 更新为
`sha256:d325d4e72bd89217b9506d79e168b6d4f177c348082efd067a425217a415fe26`，
workflow ref 更新为
`workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`；
下一轮必须使用 fresh clean commit/config/workflow pin 与全新 roots。

## r33 blank-world live attempt：永久 NO-GO

r33 以 clean commit `2ef39e02273ceb3784f6f77f53100ce2af26228b`、相同 config
digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`、
workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`
及 fresh declaration commit
`sha256:b783665a70b36f475b582bde3486eda65ed82cc7f9f43d8d8083793459635316`
和 fresh roots 启动 positive attempt
`positive-44e0487fd8fb49569facd6d93d77f69e`。独立 known-positive probe 再次完成
真实 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 check；formal researcher
完成真实 PubMed PMID `42278471`。formal source 已正确执行 r32 的 text-to-bytes 修复。

但 executor 在 module import 阶段执行
`Path('/workspace/input/aox_cutover').mkdir(...)`。sandbox process 看到的
`/workspace/input` 正确为 read-only mount，因此 source-bound run
`srun_0e6b36a1f5e2` 在任何 formal provider/HPC operation 或 approval 前以
`OSError: [Errno 30] Read-only file system` / `sandbox_exec_nonzero` fail closed。
execution task 显式 failed，reporter 发布诚实失败报告；没有 Chrome handoff/approval、
eligible report、positive 2 或 fault。

non-eligible bundle 的 network-free verification 为 `issues=[]`，digest
`sha256:5abc24e21fee44da499e6b01f051e0cf34503ab4fbb749ac462aae06d2d72a2f`；
sealed decision 保持永久 **NO-GO**，digest
`sha256:318d3d623d42395684e0af52a96576e3fef046990c94ed6a3a846eb89596c8c8`。
MICU 从 `62,008,441` 增至 `64,808,804 / 500,000,000`，delta `2,800,363`，
remaining `435,191,196`，零 breach/overage。

r33 的 roots、effects、artifacts、browser state、bundle 与 decision 永久不可复用。局部
correction 不改变只读 mount，而是在 materialize tool descriptor、强制 artifacts 文档、
AOX SOP 与 formal prompt 中明示：caller 不得在 `/workspace/input` mkdir/write/copy/
pre-create，`artifacts.materialize()` 自身通过 Host 创建并授权 target/parents；mutable
scratch 与 registerable output 分别使用 `/workspace/work` 与 `/workspace/output`，`EROFS`
不授权 remount、alternate-path fallback 或 duplicate operation。AOX SOP digest 更新为
`sha256:a9f636a1ba9c974b31c984db900fd07687ce2399d0412e80b73d69fee3ff2c0a`，
workflow ref 更新为
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`；
下一轮必须使用 fresh clean commit/config/workflow pin 与全新 roots。

## r35-r36 blank-world live attempts：永久 NO-GO

r35 与 r36 都使用 clean commit
`94ee5eb74a7b0e9b3d0fa65dc49efa43580a4f65`、config digest
`sha256:bc83b3c14973a513279361f220710e137d0da8f259f68e7026badad69fe68485`
和 workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`
在各自 fresh roots 启动。两轮 known-positive probe 都完成 exact 两项真实 provider 与四项真实
HPC check；formal PubMed、NCBI 与 MAFFT 也完成，Chrome approval 能恢复同一 controlled
operation。r36 的 browser proof 明确绑定 `appr_695463728f65` 与
`op_2198e01dc526`。

两轮 formal hmmbuild 随后都在 payload 前以 `hpc_staging_failed` 停止。runner-private
failure manifest 分别证明 `phase=remote_layout`、return code `255`、约 `60s`；稍后的独立
只读 `ssh -o BatchMode=yes -o ConnectTimeout=15 Diannan true` 健康检查成功，只说明登录节点
恢复，不授权重放、采用或把失败 attempt 追认为 positive。

r35 attempt `positive-ed6e23d5a63843a0800f71c7e12a95a9` 的 non-eligible bundle
digest 为
`sha256:9de50d9f24e5521d1022c69f2c1f3d7aabd08ecef7c47d9b7deb022d113f9a90`，
campaign decision digest 为
`sha256:e1699b0b28f2a2f561eeb3b027d795684860d17e481babab2e703e29476d8c15`；
MICU 从 `66,138,051` 增至 `67,127,906 / 500,000,000`。r36 attempt
`positive-a7286a020bbb4fb6a18211fbced008ad` 的 bundle digest 为
`sha256:d3a421ef4bbbee57879be457671344537e60414273f948fc5db109589d73bef6`，
decision digest 为
`sha256:1c06f3f0995c5c369f502b6fa496dab03b3021c20a560401cf0aacf69c370319`；
MICU 增至 `67,949,791 / 500,000,000`。两轮均永久 **NO-GO**，所有 roots、effects、
artifacts、browser state、bundle 与 decision 不可复用。

## r37 launch：未封存、非 evidence

r37 的 shell wrapper 错误地把含未引用空格/括号的 `.env` 当作 zsh source；解析失败后外层
shell 仍继续，产生 incomplete root，但没有 canonical attempt bundle 或 campaign decision。
它不能作为 live 证据或后续输入，也不能复用。持久账本仍诚实保留其实际消耗：r38 启动前累计
为 `68,091,186 / 500,000,000`，不因 r37 不具备 evidence 资格而回滚。

## r38 blank-world live attempt：永久 NO-GO

r38 继续使用相同 clean commit/config/workflow identity，并在 fresh root 启动 attempt
`positive-f53ef36dcdf04817baebfdaeed1bbf59`。known-positive probe 再次完成 exact six
真实 checks；formal PubMed、exact-14 NCBI、MAFFT 与 hmmbuild 均完成。Chrome UI 对 formal
approval `appr_d1fc2d27fa5a` / operation `op_236676e6a836` 给出 durable same-operation
proof。真实 EBI HMMER 随后完成 `68,592` hits、`69` pages 与 `37,772` 个 score-`>200`
accessions；唯一 UniProt operation 真实完成约 `378` 个 100-accession query batch。sequence
join、length filter 与 scoring-input assembly 已继续推进到 HMMalign approval
`appr_df15c554b6cf` / operation `op_6fdb7e5a9f64`。

该次没有在科学计算处失败。formal session 的 43 个 Artifact row 合计包含约
`36,963,643` bytes metadata JSON，最大单项约 `17,769,460` bytes；旧 workspace 把相同
metadata 同时复制到 artifact、artifact index、activity 与 capability branches。r38 DB 上旧代码
构造 workspace 需约 `57.766s`，JSON response 为 `106,364,236` bytes。cutover driver 又在
同步 drain 的完整 EBI/UniProt 生命周期内每 `0.5s` GET 该 composite workspace；approval
resolve 在 SQLite `BEGIN IMMEDIATE` write UoW 内还通过 activity backfill 与 command response
重复构造 workspace。HMMalign approval 虽已 durable approved，continuation 在放大事务/轮询下
未及时 claim，最终 public command 以 `internal_error` fail closed。该错误不能改写为科学成功。

r38 non-eligible bundle 的 network-free verification 为 `issues=[]`，digest
`sha256:66a3582c593b9ac979f21ce039385eb00fe1fe07e3c1dce543b7c22e5fdb0669`；
sealed decision digest
`sha256:1f0870318927623b124895b4d370ea5b00fd23ebfe2f50cf9a72280e3b3c8e32`
保持永久 **NO-GO**。MICU 从 `68,091,186` 增至
`69,063,458 / 500,000,000`，remaining `430,936,542`，零 breach/overage。

局部 correction 不改变 Artifact canonical truth、approval 状态机、single-process SQLite 或
同步 continuation：新增同源只读
`GET /v3/sessions/{session_id}/pending-approvals`，只投影 approval/operation/sandbox identity；
driver 热循环与 cleanup 不再 GET composite workspace，Chrome handoff 与 drain 退休后的最终
snapshot 才读取 workspace。workspace/artifact activity/capability branches 复用已有
`artifact.list` bounded item contract，完整 metadata 仍原样保存在 catalog 并可由
`artifact.get` 分页读取；mutation 的 activity-event backfill 直接构造 sanitized activity feed，
不再递归构造整个 workspace。对 r38 DB 的 correction 后只读 benchmark 为 pending projection
约 `0.0013s`，workspace build `2.771s`，JSON `727,362` bytes；该 benchmark 只是修复验证，
绝不把 r38 追认为 positive。下一 campaign 必须使用 fresh clean commit/config pin 与全新 roots。

## r41-r44：可靠性重构后的逐层 integration 暴露，全部永久 NO-GO

`runtime-hpc-reliability-refactor` 的 deterministic、non-live 与 real-SSH transport-only
资格门通过后，operator 曾允许恢复独立编号 attempt；该资格不是 campaign GO，也不保证
尚未被 composition-root 生命周期测试覆盖的所有边界已经正确。r41-r44 随后依次暴露四个
不同 integration seam，旧 roots/effects/evidence 均不可 adoption：

- **r41** 在 campaign pin/launch 边界失败：可靠性 runner 正确返回 opaque
  `runner-artifact://` 输出引用，旧 AOX launcher 却仍把它当 Host path 消费。纠正提交
  `d2d5b0a` 只允许 trusted Host resolver 把 exact runner artifact 交给下一 pin；不可解析或
  caller-supplied path 继续 fail closed。r41 没有证明正式科学链，也不是旧 SSH staging 故障
  复发。
- **r42** 暴露 AOX campaign driver 的观察错误：durable SDK call 正确 park attached process
  并结束 bounded runtime command 后，driver/agent runtime 仍可能把 infrastructure suspension
  写成 task `blocked`，或在 process/operation writer 尚未退休时过早推进/冻结。这是测试编排层
  把“command terminal”误当“工作已经静止”，不是 agent 科学程序选择错误。纠正提交
  `d68408e` 让 task 保持 `in_progress`，并要求 driver 等待 attempt-driver 之外的 writer；r42
  仍无 eligible bundle。
- **r43** 已产生 Host-verified durable provider result，但 compatibility transition 把完整
  adapter envelope 错嵌进 `result_summary`，continuation 恢复后的 SDK 因 wire shape 漂移无法
  读取 direct provider response。纠正提交 `7941209` 分开保存完整
  `adapter_result_envelope` 与其中 exact bounded summary。已发生 provider effect 不因投影修复
  被重放或追认为新 attempt。
- **r44** 的 NCBI、MAFFT 与 MAFFT declared-output 登记均真实成功；同一 attached sandbox 在
  continuation delivery 后调用不产生新 external effect 的 `ws.fetch_outputs()` 时，Host executor
  仍回到 engine 创建时捕获、已经释放的 agent-turn session lease，因而被正确 fence 拒绝。
  `342d20b` 的窄修复让 fetch 使用 control-server 当前 repository，但仍保留可选 repository
  escape hatch。后续 `simplify-sandbox-host-authority-handoff` change 用 typed
  `SandboxHostCallContext/SandboxHostGateway` 统一替换该弱路径，并以 file-backed 整体生命周期
  测试证明 process authority 不继承 turn/delivery lease。

r41-r44 都说明真实调用在跨 owner 组合处发现了测试矩阵未覆盖的 seam；它们不推翻各自已通过
的局部机制，也不能被解释为“只修测试就能得到 GO”。authority-handoff 与独立
process-isolation change 随后完成全部 gate，operator 才在新 pin/root 上启动 r45；旧 attempt
仍全部不可复用。

## r45-r46：artifact-set 与 provider reconcile 纠正，全部永久 NO-GO

r45 使用 commit `792d1c1` 与 fresh roots 启动 attempt
`positive-d0aecafb68dc4b5db4ffcdb24d4de191`。真实 probe/provider/HPC 已推进到 CD-HIT
multi-output fetch；run handle 与 fetch 都携带相同两个 artifact 成员，但顺序分别来自 declared
output 与 canonical artifact-set ordering。旧比较把顺序误当身份，返回
`durable_hpc_fetch_projection_drift`。这不是 runner 输出成员漂移，也不能把 r45 追认为成功。
其 non-eligible bundle 离线验证通过，digest
`sha256:521f366b695cca7bf722d0298eeb17c004ba1725726a7d87404123b3c47dc3a8`；decision digest
`sha256:e2637cead771a5fab9a5f39c48d0c6f5c52d9604da90e85151d0eeae8d34d61f`，MICU 累计到
`70,047,485 / 500,000,000`。后续纠正只把 artifact-id list 作为唯一成员集合规范化比较，仍对
run、declared path、digest 或成员变化 fail closed。

r46 使用 commit `0c1911784b9941f415a43638dc3e5555825df546`、config digest
`sha256:caaccb44ae1d84d94c0b7bda2e5d7ad2461bf68ed0039d27f799296d56267376`
与 fresh roots 启动 attempt `positive-387c72ff34da43dfaf60683820f26dfb`。known-positive probe
exact six、formal PubMed、NCBI、MAFFT、hmmbuild 与 Chrome approval
`appr_ba43fe15b520` / operation `op_28535057f25c` 均真实完成；EBI HMMER operation
`op_223adc212478` 又真实完成 `82,719` hits、`83` pages，并封存 request/raw/parsed/observation
四件 artifact。该长调用在 effect/artifact 完成后进入 durable reconciliation；旧
`reconcile-from-records` 只生成 `status=recovered + artifact_count` 通用摘要，丢失
`result_summary.transcript_manifest`，attached pipeline 因而以
`provider_file_projection_invalid` fail closed。它不是 provider 或 HMM 科学失败，也不授权重发
该 HMMER request。

r46 non-eligible bundle digest 为
`sha256:1553ddddff9a791b3069e529f83f28764d339738ba123f439328f0e5aa7b7638`，network-free
verification 为 `issues=[]`；decision digest
`sha256:3f39ca42e1273d3dcb92bff079165ae1d8f1a587ef34f1bce8734c85d1268d06`。
MICU 累计到 `70,742,820 / 500,000,000`，remaining `429,257,180`，零 breach/overage。
r46 及其 effect、roots、artifacts、Chrome receipt、bundle 与 decision 永久不可复用。

局部 correction 让 provider reconciliation 从同一 operation/request 的 sealed
`provider_request.json` 与 `provider_observation.json` 重建原 S12 result：实际 bytes digest、
strict closed JSON schema、route/provider/config/output-dir 与 artifact metadata 全部精确核验，
恢复原 summary、validation、warnings 与 transcript manifest；control document 限 `8 MiB`，
完整 canonical immutable result envelope 与 core 统一限 `256 KiB`。任一
tamper/schema/identity/size drift 以 terminal-known failure 停止，且不 replay provider。对 r46
原 DB/artifact 的只读回放已恢复同一 HMMER request 的 `82,719` candidates 与四件 transcript
refs，但该回放只是修复验证，绝不使 r46 eligible。

r47 使用 correction commit `3e2c7bad448b7f0c297f40417e72ebc313d63dc1`、同一 config digest
`sha256:caaccb44ae1d84d94c0b7bda2e5d7ad2461bf68ed0039d27f799296d56267376`
和 fresh roots 启动 attempt `positive-3da05d7870264c2e86c4c56324cb7c94`。Chrome UI 对 formal
approval `appr_5df01a7b5490` / operation `op_03aa13ad5dd0` 执行一次真实 approve，Host receipt
digest 为 `sha256:c659855c2c80689a559aec2fc4b1e3f97e4933d81d3ca725af6ecac3d3c4a79d`；
NCBI、MAFFT、hmmbuild 随后真实完成。EBI HMMER operation `op_1b2d55f1d8bc` / request
`provider_req_766862b4d3993d72e390b962` 真实完成 `68,592` unique candidates、`69` pages，封存
`provider_request.json=1,104` bytes、`raw_hits.json=125,225,501` bytes、
`parsed_hits.csv=22,833,564` bytes 与 `provider_observation.json=1,388,557` bytes。

r47 同时证明先前 `1.5 MiB` inline-summary 约束不成立：HMMER summary 把完整
`candidate_accessions` 从 parsed artifact 重复内联后达到 `862,426` bytes，Host route 返回
terminal-known materialized observation，但 core 的既有 `256 KiB` complete-envelope validator
正确拒绝；旧 worker 又把这类 invalid terminal observation 改写回 `reconcile_required`。在未重放
effect、`dispatch_generation=1` 且没有 result handle 的前提下，同一 execution 最终写出
`9,780` events，其中 `4,888` claim、`4,887` reconcile，形成纯 control-plane 热循环。operator
在确认根因后终止 fresh process group；该 attempt 无 bundle、无 terminal Chrome observation、无
GO 资格，roots/effects/artifacts/approval 永久不可复用。MICU 累计从 `70,742,820` 增至
`71,562,612 / 500,000,000`，remaining `428,437,388`，零 breach/overage。
operator interrupt 绕过当前 supervisor `except Exception` retirement ladder 的生命周期缺口已单独
记录在 [operator-interrupt-safe live-attempt retirement](../architecture-proposals/operator-interrupt-safe-live-attempt-retirement.md)；它涉及 signal/exit/fatal-evidence 语义，本 Goal 不实现。

当前局部 correction 不新增 owner 或 fallback：EBI HMMER summary 删除完整
`candidate_accessions`，exact identities 只由 digest-bound `provider_parsed/parsed_hits.csv`
承载，summary 保留 count/schema/digest/transcript refs；Host 在 materialize 前按 core `256 KiB`
完整 envelope 上限校验；worker 对不能通过 closed validation 的 terminal-known observation 直接
以 `recovery_failed` 终结，不再重复 claim/reconcile。下一次 live 必须使用该 correction 的 clean
commit/config pin 与全新 r48 roots。

## r48 launch-precondition attempt：永久 NO-GO

r48 在 clean commit `2b75929855cf45fb4bb13b82ee67b216bc174cf9` 上完成 fresh pin，
pin receipt 绑定 full architecture admission、config digest
`sha256:caaccb44ae1d84d94c0b7bda2e5d7ad2461bf68ed0039d27f799296d56267376`
与 workflow
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`。
但旧 `aox_blank_world_runtime_config@1` preimage 没有绑定 reliability settings，pin 因而
没有发现 operator environment 仍解析为 legacy controlled-operation owner 与 legacy mutation
closure。正式 `run-live` 创建 positive attempt
`positive-79a33a42e0d645209037171f45060351` 后，attempt 内部 gate 在 session、provider、HPC
或 MICU 调用前以 `aox_durable_operation_ownership_required` 正确 fail closed。

该 non-eligible bundle 的 network-free verification 为 `issues=[]`，digest
`sha256:00358d3b82c265ca81ae0aef0bbde2c5f3e2c345f16dbe788be36df6582bf2ac`；
sealed decision digest
`sha256:6c18c1309259745c73fc5b6401871bb9b6e48252aa7c4d3d7e3bdbc1a8c45cbb`
保持永久 **NO-GO**。MICU before/after 均为
`71,572,868 / 500,000,000`，remaining `428,427,132`，零 breach/overage。
r48 root、bundle、decision 与 pin 永久不可复用。

局部 correction 将新 live config 升级为
`aox_blank_world_runtime_config@2`，把 owner policy、durable route allowlist、command drain、
generic mutation closure 与 bounded shadow observation 纳入 canonical digest。pin 在任何
forced-SSH attestation 前、run-live 在 campaign/attempt root 前要求全部 AOX provider/HPC
route 为 `durable_async_v1`、drain 为 `command_v1`、closure 为 `generic_v1`；任一配置漂移
都会改变 pin identity 并 fail closed。旧 `@1` 仅保留 frozen evidence 离线读取兼容，不能再
启动新的 live attempt。下一次实验必须重新生成 architecture admission、pin 与全新编号 roots。

## r49 durable-event replay transaction attempt：永久 NO-GO

r49 使用 clean commit `d413a51ad8eecc118bf051c54c0ef40c78bb1a25`、fresh full admission
payload digest `sha256:e4dba3ed9fc702911b07d13208f4c6830fa92b29cfedde6278215b359fc45124`
与 `aox_blank_world_runtime_config@2` config digest
`sha256:a799a41159688b5bc6df2b060468fc4176f7780a7855721ecc7c1ab40a3a982e`
启动 fresh positive attempt `positive-77e54e3df18b4d0e89ddc4b7790bee5a`。它真实穿过可靠性
preflight，创建 master/executor team，发生 MICU 调用，并通过 canonical approval
`appr_1aa968c97657` 将首个 NCBI durable operation `op_966d30ce9f19` 推进到 execution
`exec_bb73137fa448`。

失败发生在 single-process SQLite event replay：runtime drain 在收集 scheduler 已经逐条发布的
event 后再次幂等 append 同一 event。旧 `DurableEventRepository.append()` 对 exact same-content
duplicate INSERT 返回既有 row，却没有关闭该失败 INSERT 打开的 standalone 隐式 transaction；
随后 event-outbox mutation writer 退役执行 `BEGIN IMMEDIATE`，以
`cannot start a transaction within a transaction` 失败。该失败留下 execution
`dispatching`、continuation `awaiting_result`、sandbox run `running` 与一个 registered
event-outbox writer；attempt freeze 因 `mutation_writers_still_active` 失败。child 因而不能签发
quiescence receipt，parent supervisor 正确拒绝读取/封存普通 attempt bundle，并写出
`aox_live_attempt_fatal@1`，而不是把不静止的 root 追认为普通科学失败。

r49 fatal digest 为
`sha256:c9d814158d92be18d8e0eb17333dacc124ade9c10f223a2d426ab0272fb73b45`，
driver-failure digest 为
`sha256:8e0c9f334212f9a07f1e79da8d3658199c053e28c5eff79d554c2aafe35cdeb4`，
sealed decision digest 为
`sha256:5056abd190a58c046b887f1210947e88c1c925404bbe297876e5728da268f8cf`。
supervisor 只能封存 MICU verified lower bound
`71,727,249 / 500,000,000`（remaining `428,272,751`），没有声称 ordinary
`ledger_after`、SQLite closure、artifact completeness 或 external outcome。r49 root、pin、
approval、operation/effect、fatal evidence 与 decision 永久不可复用。

局部 correction 不新增 owner、状态或 fallback：same-content durable event replay 在 standalone
path 返回既有 event 前调用现有 `_commit()` 收口隐式 transaction；owning UoW 内 `_commit()`
仍保持 no-op，由外层 transaction 统一提交。回归测试要求 replay 后
`connection.in_transaction == false`，并证明同一 connection 上 event-outbox mutation writer
可以正常 terminal retirement。后继 numbered campaign 必须在该 correction 的 clean commit 上
重新生成 full admission、fresh pin 和全新 roots。

## 当前实施状态的表述规则

- focused/unit/eval/frontend/mainline 测试通过只能说明实现行为满足对应非 live gate，不能写成 cutover GO；
- provider/HPC/Chrome preflight 是当前外部状态证据，不得用旧日志或本地 fixture 替代；
- 实现中尚未被当前 validator 实际接受的 schema/contract 只能写为 target/pending，不能因为文档已定义而声称 completed；
- 直到两个 positive bundle、一个 fault bundle 和 sealed campaign decision 真实存在，所有文档、UI 和交付结论保持 **NO-GO**。

## 明确不做什么

- 不直接运行或复制 `reference/enz_miner_hmm_aox.ipynb` 产物；只用它审计公式、reference identity 和最小 golden。
- 不把 Host-local Apptainer/SIF、sandbox binary、raw provider/tool artifact、optional `bio_tools.hmmer_search_cli` 或 seeded smoke 当作 EBI REST + Host-supervised HPC 主路 cutover proof。
- 不手工构造 task、invocation、run、approval、artifact、report 或 evidence 来跳过用户消息、agent team、scheduler/runtime drain、approval 或 artifact boundary。
- 不为了让结果非空而重试成无界循环、替换 provider、放宽阈值、复制 HMM/motif score、伪造 candidate/cluster/edge，或把 probe 数据注入正式结果。
