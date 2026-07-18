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

每次 attempt 建立独立空 SQLite、artifact/blob、sandbox 和 HPC roots，记录 cache bypass 和只读允许 prerequisite，并继续使用既有 MICU 持久 500M 账本；历史 usage 不清零，campaign 初始化也不得重置。旧固定 100M policy 只迁移 policy ceiling，全部历史 attempt/charged token 原样保留，显式 lower limit 不被抬高。`aox_blank_world_attempt_bundle@1` 必须绑定 commit/config/workflow/scoring/image/SDK/provider/toolchain/root/approval/operation/task/artifact/report/final-answer/warning/degradation/outcome 身份。offline verifier 无网络重算 canonical JSON、所有可达 sealed artifact、科学计算、lineage 和 report references。

`run-live` 在构造 runner/campaign 和创建任何 root 前先从 clean checkout、digest-pinned workflow、`aox_motif_rule_score@1`、实际 sandbox image preflight 与 Pipeline SDK source tree 计算 canonical 七字段 launch identity。`config_digest` 不是任意 operator 标签，而是 safe `aox_blank_world_runtime_config@1` preimage 的 canonical digest；该 preimage 绑定 single-process SQLite/trusted Host、HPC runner-config digest、runner-owned manifest digest 与 exact AOX `tool_id` → adapter/template/runner-contract expectation map、post-budget MICU/research/tracing/test opt-in、driver/Chrome bounds、现有累计 500M ledger identity，且不暴露 credential、NCBI email 或 Host/runner/ledger path。MICU/OpenAI-compatible endpoint 必须显式配置 `context_window_tokens <= 200000`，不能按模型名继承未经 endpoint 证明的百万级 context。每个 attempt root 创建前都重新执行 launch guard，checkout 或 effective config 漂移直接 fail closed；exact-nine prerequisite 顶层字段不因此增加。

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

每个 MAFFT/hmmbuild/hmmalign/CD-HIT cutover receipt 还必须来自 runner-issued `mcp_hpc_toolchain_runtime_identity@1`：runner-owned manifest 决定私有 SIF locator；当前 SSH 窄保证在同一 login shell 中直接用该 resolved pathname 执行，并在 payload 前后哈希同一路径，两个 digest 必须相同。Host 只逐层传递闭集 public projection，collector/verifier 将观察到的 digest 与 sealed prerequisite 精确比较；caller override、missing/mismatch 均 fail closed。该机制证明“同一路径前后未变并被直接执行”，尚不证明 immutable inode/content-addressed snapshot；后者单独记录在 [immutable HPC SIF execution snapshot](../architecture-proposals/immutable-hpc-sif-execution-snapshot.md)，不在本 Goal 实现。Slurm 本身仍可用于一般 runner 任务，但当前没有 job-internal same-execution SIF attestation，因此 Slurm execution 不能构成此 cutover identity。跨层 toolchain 定义收敛属于大改，只记录在 [single-source HPC toolchain contract registry](../architecture-proposals/single-source-hpc-toolchain-contract-registry.md)，不在本 Goal 实现。

GO 只由顺序固定的三次 campaign 聚合得出：

1. positive 1：全新 roots，published report，offline verification passed；
2. positive 2：不同 roots 且 task/operation/invocation/job 证据独立，但 commit/config/workflow/scoring/image/SDK identity 与 positive 1 完全相同；
3. fault：`derived_required_artifact_blob_byte_flip@2` 精确到达 real NCBI exact-14 `proteins.fasta` → `aox_hmm_reference_set_selection@1` → derived `AOX_ref21.fasta` → pending MAFFT seam，产生 `artifact_blob_digest_mismatch`。封存的 `aox_fault_negative_state_closure@1` 必须证明 execution task failed/blocked/cancelled、reporting 未完成/发布、无 ready/published report 或 draft、无 successful alternate consumer、无 downstream fixed deliverable、durable events 与 conversation/final failure receipt 一致；fault attempt 的 MICU 增量同样必须全部归因到本 campaign。

正式 campaign 使用 `--approval-mode chrome-once` 时，只把 positive 1 的首个 formal approval 暴露给同进程 loopback Host 提供的 Web UI。driver 不调用 resolve route；它在触发该 drain 前先记录 durable event cursor，再从该 cursor 重建 resolution/continuation，避免即时浏览器批准与事后 snapshot 竞争。浏览器审批 timeout 从 handoff 发出时独立计时，同时受 attempt 总 deadline 上界约束。用户在 approval card 上批准后，driver 必须从有序 durable events 证明同一 approval、operation digest、sandbox run/workspace 和 continuation 恢复到同一 operation 的 terminal state，并在完成后保留 bounded UI observation window。handoff 对动态身份是完整的：发出 sealed page、Host/UI identity 和 receipt schema id，而 exact 23-field builder 合同由稳定 guide/code 定义。trusted operator 必须使 final target 在 hold 内不存在，hold 后使用另一个写入 config digest 的正有限 submission timeout 完成 sibling-temp/fsync/atomic-rename。当前 Host 证据只覆盖 hold polls 未观察到提前 target、post-hold mtime 与两次 stat/read 稳定，不声称证明轮询间连续缺失或 atomic/fsync provenance。该 receipt 加上 browser console 无 application error 才构成当前 trusted-operator Chrome proof；`auto` 模式不能满足这一 GO 条件。任一必需 quorum、digest、分支 closure、published report、offline verification、Chrome proof 或 MICU ledger 条件失败，campaign 只能产生最小 evidence-backed **NO-GO** blocker。

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
