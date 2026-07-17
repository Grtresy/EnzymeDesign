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
3. researcher 产生真实 PubMed/PMID 必需证据，Semantic Scholar/Tavily 只作 enrichment；
4. executor 在 persistent sandbox 中 author source，Host 封存 source snapshot，`sandbox.exec` 通过 `openzyme_pipeline` SDK 请求 provider/HPC；
5. canonical approval 必须续接同一 `operation_id` / `operation_digest`，不得唤醒 agent 后重开替代 operation；
6. artifact catalog 登记当前运行的 normalized sealed outputs 和 lineage；
7. 三个 teammate 分别显式写入 task 业务终态，reporter 通过 `report.publish` 发布报告，master 产生非空 final response。

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

### HMMER → UniProt → identity-preserving join

EBI HMMER REST 固定使用 `refprot`。其 provider parsed artifact 保留 exact 11 columns：`target`、`accession`、`evalue`、`score`、`page`、`hit_index`、`evalue_numeric`、`score_numeric`、`raw_page_digest`、`raw_hit_digest`、`parsed_row_digest`。

`hmmer_score_filtered_accessions@1` 只保留 score 严格 `>200` 的 canonical UniProt accession；其七列 output artifact 和 exact non-empty accession set 是 `bio.uniprot_fetch` 的唯一允许输入。HMMER 的记录不提供下游 sequence/length 真值。

UniProt 保留 primary accession、reviewed status、release/version、retrieved time、raw response/record/sequence digest 和 append-only cross-source mapping。`aox_sequence_length_join@1` 按 identity 严格连接 HMMER accession 与 UniProt record，用 UniProt sequence 实际长度应用 inclusive `650..700` 过滤，产生 `target.fasta` 和 `hits_len650_700_200.csv`。两源 sequence bytes 不一致时保留双方 digest 并要求显式 selection，不静默 overwrite。

### Scoring 与结果分支

非空 target 时 HMMalign 同时消费真实 `AOX_ref.hmm` 和 `AOX_scoring_input.fasta`，产生 `AOX_scoring_alignment.fasta`。`aox_motif_rule_score@1` 在 AAB 的 one-based ungapped coordinate 上使用 exact integer tenths，threshold 是 `336`，`33.6` 只是展示值；它是 reference-coordinate heuristic，不是实验活性预测。旧 `activity_score`、`seq_score`、`pass_rule` 无 alias，直接使 attempt 失效。

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
| `aox_hmm/hits_len650_700_200.csv` | canonical `aox_sequence_length_join@1` result |
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

每次 attempt 建立独立空 SQLite、artifact/blob、sandbox 和 HPC roots，记录 cache bypass 和只读允许 prerequisite，并继续使用既有 MICU 持久 100M 账本，不在 campaign 初始化时重置。`aox_blank_world_attempt_bundle@1` 必须绑定 commit/config/workflow/scoring/image/SDK/provider/toolchain/root/approval/operation/task/artifact/report/final-answer/warning/degradation/outcome 身份。offline verifier 无网络重算 canonical JSON、所有可达 sealed artifact、科学计算、lineage 和 report references。

GO 只由顺序固定的三次 campaign 聚合得出：

1. positive 1：全新 roots，published report，offline verification passed；
2. positive 2：不同 roots 且 task/operation/invocation/job 证据独立，但 commit/config/workflow/scoring/image/SDK identity 与 positive 1 完全相同；
3. fault：`sealed_provider_artifact_byte_flip@1` 确实到达必需 provider artifact seam，产生 `artifact_content_digest_mismatch`，不得存在 cutover-eligible report 或 success bundle。

至少一个 positive attempt 使用 Chrome 解决 canonical approval card，并证明同一 operation 续接、workspace/events/report/evidence 一致且 browser console 无 application error。任一必需 quorum、digest、分支 closure、published report、offline verification、Chrome proof 或 MICU ledger 条件失败，campaign 只能产生最小 evidence-backed **NO-GO** blocker。

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
