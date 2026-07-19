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
[durable async controlled operation and quiescent sealing](../architecture-proposals/durable-async-controlled-operation-and-quiescent-sealing.md)，本 Goal 不实现。

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

后续 UniProt 小修固定为 `provider_config:uniprot:v2`，但 route policy id 仍是
`bio.uniprot_fetch.provider:v1`。exact HMMER accession set 通过一次 SDK call、一次
approval 和一个 controlled operation 提交；operation 总 cap 是 `100000`，Host 固定按
每 query 最多 `100` accession 拆分。SDK `batch_size` 仍是每 response page 的 `size`
（上限 `100`），每个 query 独立跟随 `Link: rel=next` 且各自最多 `100` 页。approval
前 resource estimate 显式记录 accession/query batch 数，因此 37,722 accession 等于
378 个内部 query，而不是 378 个 operation/approval。transcript 记录 query/page index、
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
