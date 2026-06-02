# Session 15：AOX/HMM Cutover Live E2E

## 目标

完成 persistent sandbox 模型下的 AOX/HMM 真实 cutover 验收：产品默认路径不得 fallback 到 deterministic bio/bio_tools adapter；live AOX/HMM E2E 必须从用户 prompt 进入，经过 master、executor、approval、scheduler、persistent sandbox、Host supervisor、artifact catalog 和 final answer。

## 当前缺口

- fixture prompt E2E 可以证明控制流，但不能证明真实 provider/toolchain/HPC cutover。
- 旧一次性 pipeline gate 无法证明 persistent sandbox workspace、source snapshot、file/command runtime 和 external bridge 的完整路径。
- live prerequisite 缺失必须报告 `prerequisite_missing`，不能计为 passed。

## 当前实现债 / Cutover Blockers

当前 AOX/HMM eval 和 live wrapper 仍保留旧的 fixture / deterministic 证明路径。S15 实现前必须把这些路径从 live passed 证明中移除或改造成明确 fixture scenario：

- `AoxHmmFixtureSandboxRunner` 只能用于 fixture/unit/eval fixture dependency injection，不能进入 S15 live scenario。
- `DeterministicBioDatabaseAdapter` 和 `v3_allow_bio_fixture_adapter=True` 只能用于 fixture scenario；产品默认路径缺真实 provider adapter/config 时必须结构化失败。
- `run_v3_live_evals()` 默认仍是通用 V3 live task-plan smoke，不能计为 AOX/HMM live cutover proof；S15 live gate 必须通过显式 `v3_aox_hmm_cutover_live_e2e` scenario 运行。
- 旧 AOX/HMM eval required paths 例如 `aox_hmm/filtered.fasta`、`aox_hmm/filtered.csv`、`aox_hmm/scoring.csv`、`aox_hmm/candidates.fasta`、`aox_hmm/candidates.csv` 和 `aox_hmm/candidate_cdhit85.fasta` 必须迁移到本文件的 fixed deliverable contract；旧名不能作为 compatibility passed 条件。
- 任何仍通过手工构造 execution invocation、dry-run plan、approval、artifact 或 deterministic output 让 AOX/HMM scenario 变绿的路径，都只能标记为 fixture/control-flow coverage，不能标记为 S15 passed。
- persistent sandbox 内的公开 `openzyme_pipeline` SDK 必须走 Host supervisor 可审计路径：`bio.*` / `bio_tools.*` 在 `sandbox.exec` 中不得直接调用旧 control method 名称导致 `sandbox_transport_method_forbidden`；`artifacts.*` 和 `hpc.workspace` / `hpc.stage_artifact` / `hpc.fetch_outputs` 必须有 control socket 覆盖或结构化 fail-closed。仅完成 approval bridge、但没有真实 provider/HPC adapter result 的 operation，approve 后必须以 `adapter_execution_unavailable` 失败；仅有 approval/operation 但缺 `backend_run_id`、adapter result 和 registered final artifacts 的 live evidence 必须返回 `live_evidence_incomplete`，不能计为 S15 passed。

## 当前审查结论（2026-05-31）

- S15 的本地实现 blocker 已从外部 prerequisite 推进到真实 live product path：persistent sandbox control socket 已覆盖 `artifacts.*`、`hpc.workspace`、`hpc.stage_artifact`、`hpc.fetch_outputs`；S12 public `bio.*` / `bio_tools.*` approve 后走 Host adapter executor，缺 executor 时仍结构化 fail-closed。
- `bio_tools.*` 在 supervised sandbox mode 下返回可链式传给 `ws.fetch_outputs(run)` 的 Host-supervised HPC run handle；`hpc.fetch_outputs` 通过 Host fetch executor 登记 declared outputs，并把 `fetch_refs` / `registered_artifact_ids` 回写到同一个 S12 `ControlledOperation`。
- live AOX/HMM scenario 已加硬 guard：`scenario_class="live"` 时禁止 fixture dependency injection，避免 `AoxHmmFixtureSandboxRunner` / deterministic adapter 误进入 live passed 路径。
- fixed deliverable validator 已覆盖 fixed thresholds、`refprot`、13 accession metadata、空 `target.fasta` warning、`AOX_ref.hmm` provenance、`scored_ref_plus_hits.csv` bounded-score columns 和 normalized final path 列表；旧路径仍不能作为 pass contract。
- background runtime 已修复 live 场景中的 event loop 阻塞风险：长 LLM/agent step 通过 worker thread 推进，避免 `/workspace`、`/events` 和 `/debug/v3-runtime` 在 Web UI 手测时被同一事件循环长时间堵住。
- master prompt 和 `task.delegate` 写路径已补强 AOX/HMM execution contract：AOX/HMM、HMM、`refprot` 或 sequence-mining execution task 委派给 executor 时，delegation payload 会强制要求读取 `docs.read doc_id="aox-hmm-live"`，使用 persistent sandbox + Host-supervised SDK，并禁止 ClustalW/MUSCLE、direct MAFFT/CD-HIT/HMMER binaries、direct provider files、pseudo computation、synthetic hits 和 dependency installs。
- 已通过本地门禁：focused sandbox/runtime 与 execution tests、V3 API focused tests、repository/projection focused tests、provider/HPC focused tests、delegation focused tests、`git diff --check`，以及 background runtime non-blocking focused regression。非 live 门禁只能证明实现路径和前端构建可用，不能替代真实 AOX/HMM live cutover proof。
- 当前 `uv run python -m openzyme_host_api.evals --live --scenario v3_aox_hmm_cutover_live_e2e` 已通过真实 S15 live AOX/HMM cutover gate：`scenario_id="v3_aox_hmm_cutover_live_e2e"`、`status="passed"`、`live_cutover_eligible=True`，并在 eval result 中返回 sealed inline evidence payload 与 `evidence_bundle_digest`。
- 本次 passed evidence 覆盖完整 product path：单一用户 prompt、master `task.delegate` 到 executor、persistent sandbox workspace `sw_37166764122b691b7afb5ba6`、source snapshot `art_4881f9b0f879` / source digest `sha256:96ca9f136ccb00362724c5f997146cfada60644a918a4d2eb02a3abe79188eb4`、sandbox run `srun_de41e91a41d8`、9 个 canonical SDK approval、9 个 completed controlled operations、provider/HPC route policies、registered artifacts 和 final answer digest。
- 本次 passed evidence 注册了全部 11 个 fixed deliverables：`aox_hmm/AOX_ref21.fasta`、`aox_hmm/target.fasta`、`aox_hmm/AOX_ref.hmm`、`aox_hmm/hits_raw.csv`、`aox_hmm/hits_len650_700_200.csv`、`aox_hmm/scored_ref_plus_hits.csv`、`aox_hmm/AOX_candidates.fasta`、`aox_hmm/AOX_candidates_cdhit85.fasta`、`aox_hmm/nodes.csv`、`aox_hmm/edges_similarity.csv`、`aox_hmm/execution_summary.json`；`final_output_validation`、`live_product_path_validation` 和 `evidence_bundle_validation` 均为 passed。
- 本次 live route evidence 覆盖 `bio.ncbi_fetch_proteins.provider:v1`、`bio.uniprot_fetch.provider:v1`、`bio.hmmer_search.provider:v1`、`bio_tools.cdhit.hpc:v1`、`bio_tools.mafft.hpc:v1`、`bio_tools.hmmbuild.hpc:v1`、`bio_tools.hmmalign.hpc:v1`；`bio_tools.hmmer_search_cli` 保持 `disabled/unsupported_in_s14`，不作为当前主路 passed 条件。
- 可以进入 Web UI 开发者手动测试准备阶段。手动测试仍必须验证同一 canonical approval card 在浏览器中可见、approve 后恢复同一个 blocked SDK operation，并确认 `/workspace`、`/events?replay=1`、`/debug/v3-runtime` 与 evidence bundle 一致；不得把本次自动 live pass 当成人工 approval UI 已验证。

## 实施范围

- 产品默认 `ExecutionEngine` 缺少真实 provider/tool backend 时必须结构化失败，不得创建 synthetic FASTA、fixture HMM 或 synthetic hits。
- fixture adapter 只能通过 unit/eval fixture dependency injection 出现。
- live AOX/HMM E2E 必须从固定用户 prompt 进入：
  - `POST /v3/sessions/{session_id}/messages`
  - master task decomposition
  - `task.delegate` 给 executor
  - executor 使用 persistent sandbox 创建/修改脚本
  - Host snapshot execution source 为 CODE artifact
  - `sandbox.exec` 运行脚本
  - SDK operation 触发 Host approval 并在 Web UI 阻塞等待
  - approve 后 Host 恢复同一个 SDK operation；reject 时 sandbox 代码收到结构化异常
  - scheduler 只负责唤醒 executor 消费运行结果或失败证据
  - sandbox 通过 SDK 请求真实 Host-supervised provider 和 Host-supervised HPC backend
  - artifact catalog 登记结果和 provenance
  - executor 显式 `task.update`
  - master 生成 final answer
- live prerequisite 检查的主路硬门槛覆盖 NCBI、UniProt、EBI HMMER REST `refprot`、S14 已启用的 MAFFT / CD-HIT / `hmmbuild` / `hmmalign` HPC route、HPC runner、staging/fetch 和 output validation。
- Host-local Apptainer / SIF、Host-local HMMER observation 或 sandbox 内 binary 只能作为非 route 诊断背景，不能进入 S15 passed 条件，也不能作为缺失 provider/HPC prerequisite 的 fallback。
- HMM search 主路固定为 `bio.hmmer_search(..., database="refprot")` 的 Host-supervised EBI HMMER REST provider path。`bio_tools.hmmer_search_cli` 可以产生补充 toolchain evidence，但不能替代 S15 的 EBI REST 主路；其 production target database 缺失不阻塞当前 S15 主场景 passed。若后续显式启用 offline/HPC HMM search 子场景，该子场景必须单独报告 `prerequisite_missing` 或 passed evidence。
- S15 fixed prompt 必须包含 13 个 AOX accession、`refprot` HMM search、长度过滤 `650-700`、HMM score `>200`、参考坐标序列 `AAB57849.1`、activity score threshold `33.6` 和 similarity threshold `0.85`。
- live run 可以产生额外 raw/provider/tool artifacts，artifact ids 不要求一致；但必须通过规范化导出层登记下方固定最终 deliverable relative paths 和 schema。

## Fixed AOX/HMM Deliverable Contract

这一节是 AOX/HMM recipe / eval 的验收面，不是 harness 运行时 schema。最终 deliverable 必须登记在 `aox_hmm/` 下，使用 notebook 基名。S13 provider transcript / raw hits、S14 tool raw outputs / logs 和 sandbox 中间 artifacts 只是诊断或规范化输入；它们不能替代最终交付面。executor pipeline 必须汇总真实 provider / tool observations，在 sandbox 中生成下列 normalized outputs，并通过 S08 artifact boundary / `artifacts.register(...)` 登记。验收只把下列路径作为稳定用户交付面；artifact catalog / harness 不理解 AOX/HMM 专用字段或阈值。

| relative_path | kind/format | required columns / summary fields |
| --- | --- | --- |
| `aox_hmm/AOX_ref21.fasta` | sequence / fasta | 13 个输入 accession 对应的 reference FASTA，metadata 记录 accession count 和 provider request ids。 |
| `aox_hmm/target.fasta` | sequence / fasta | EBI/refprot search 或后续 fetch 得到的 candidate target sequences；允许为空时必须有 structured empty-result warning。 |
| `aox_hmm/AOX_ref.hmm` | result / hmm | HMMER HMM format marker。 |
| `aox_hmm/hits_raw.csv` | result / csv | `target`, `uniprot_accession`, `hmm_score`, `evalue`, `length`。 |
| `aox_hmm/hits_len650_700_200.csv` | result / csv | `target`, `uniprot_accession`, `hmm_score`, `evalue`, `length`, `sequence`。 |
| `aox_hmm/scored_ref_plus_hits.csv` | result / csv | `id`, `seq_score`, `pass_rule` plus bounded rule-score columns. |
| `aox_hmm/AOX_candidates.fasta` | sequence / fasta | Candidates with `seq_score >= 33.6` after length/HMM filtering. |
| `aox_hmm/AOX_candidates_cdhit85.fasta` | sequence / fasta | CD-HIT 85 percent deduplicated candidates. |
| `aox_hmm/nodes.csv` | result / csv | `node_id`, `label`, `score`, `cluster_id`. |
| `aox_hmm/edges_similarity.csv` | result / csv | `source`, `target`, `similarity`. |
| `aox_hmm/execution_summary.json` | result / json | `accession_count`, `candidate_count`, `length_filter`, `hmm_score_threshold`, `activity_score_threshold`, `similarity_threshold`, `hmmer_database`, `provider_status`, `tool_status`, `warning_count`, `artifact_ids`. |

### Minimum Final-output Validators

- 每个 fixed `aox_hmm/*` relative path 都必须在当前 live run 的 artifact catalog 中存在为 registered artifact；只出现在 sandbox working copy、provider transcript、tool raw output 或 runner logs 中不算通过。
- FASTA deliverables 必须是可解析 FASTA。`aox_hmm/target.fasta` 允许为空；recipe/eval 可以检查 agent 是否基于 artifact 内容与 execution summary 正确解释空结果或 fallback，但 harness 不硬编码 AOX/HMM warning 字段，也不替 agent 生成领域解释。
- `aox_hmm/AOX_ref.hmm` 必须包含 HMMER3 profile marker，且 source provenance 能回链到 13 个 fixed AOX accession 的 reference FASTA、MAFFT alignment 和 `hmmbuild` operation。
- CSV deliverables 必须包含表中 required columns；额外列允许存在，但不能替代 required columns。`scored_ref_plus_hits.csv` 的 bounded rule-score columns 必须来自固定 reference coordinate `AAB57849.1` 和 activity score threshold `33.6` 的可审计计算摘要。
- `aox_hmm/execution_summary.json` 是 AOX/HMM pipeline 自己的任务产物；recipe/eval 可以要求它包含表中字段，并记录 `hmmer_database="refprot"`、阈值、candidate count、provider/tool status、warning count、registered artifact ids 和 normalized final deliverable paths。Harness 只负责执行、注册、读取和投影该 artifact。
- artifact ids 是 run-specific 证据，不能成为 deliverable identity；验收以 normalized `relative_path`、kind/format 和 schema 为准。

## 接口变化

- live result 状态固定区分：
  - `passed`
  - `failed`
  - `prerequisite_missing`
- live summary 只暴露 provider/tool/backend prerequisite 状态、selected backend、route reason、artifact count、通用错误摘要、`sandbox_workspace_id` 和 final answer availability；领域 warning 由 recipe/eval 或 agent 通过 artifact 内容解释。
- source execution evidence 回链到 `sandbox_workspace_id`、source snapshot artifact id、source digest、SDK call trace、output artifacts 和 final answer。

## Resource Identity / Lifecycle

本 session 锁定 S15-specific live evidence payload，而不是新增 control-plane 顶层真状态。live cutover passed 必须来自当前真实运行证据，不能来自 fixture、seeded smoke、test collection 或旧 Session 06 evidence。

- `PrerequisiteReport` payload
  - identity：`prerequisite_report_digest` 由当前 prerequisite payload 计算。
  - owner：S15 live eval harness/provider/tool/backend probe 创建。
  - lifecycle：只反映当前真实检查；Session 06 evidence 可作为参考 ref，但不能替代当前 passed 证据。
  - persistence：不写入 core/domain repository；作为 eval result 的 inline payload 返回。
- `EvidenceBundle` payload
  - identity：`evidence_bundle_digest` 由 sealed evidence payload 计算。
  - owner：S15 live eval harness 聚合，artifact catalog 和 event log 提供证据来源。
  - lifecycle：run 结束时在 eval result 中 sealed；rerun 产生新的 payload/digest。
  - content：fixed prompt、session id、sandbox workspace id、sandbox image digest、adapter schema version、route policy id、toolchain ids、provider config digests、approval ids、source snapshot digest、SDK operation trace、backend run ids、registered artifact ids、normalized final deliverable paths、通用 error summary、final answer digest。
  - privacy：只保存 safe refs/digests/summaries，不保存 provider credentials、Host paths、remote paths、runner config 或 full private logs。
- `safe_summary`
  - identity：与当前 eval result 绑定，不单独建表。
  - lifecycle：随 scenario result 返回，用于人工审查和可选 trace upload。

固定错误码/状态：

- `live_fixture_forbidden`
- `live_prerequisite_missing`
- `live_evidence_incomplete`
- `live_artifact_missing`
- `live_final_answer_missing`

## Approval Evidence

- 自动 live gate 必须通过 canonical approval resolve API approve pending SDK operation，不能预先注入 approved state、绕过 approval service 或让 executor 自己调用 resume。
- pending approval 必须绑定 `operation_id`、完整 `operation_digest`、`sandbox_workspace_id`、`source_snapshot_artifact_id`、selected backend、route policy id、expected outputs 和 resource summary。
- approve 后 evidence bundle 中必须能看到同一个 `operation_id` / `operation_digest` 从 `waiting_approval` 继续到 completed 或 structured failure；digest 漂移必须产生新 approval 或 `operation_drift_detected`，不能复用旧 approval。
- reject 演示必须证明 sandbox SDK 收到结构化 approval rejection，`sandbox.exec` 返回失败证据，executor 只能在后续 agent turn 修改 workspace 或参数后重新运行。
- 人工 Web UI 演示必须使用同一 canonical approval card；点击 approve 后恢复同一个 blocked SDK operation，而不是唤醒 agent 后重开一个替代 operation。

## 推荐实施顺序

这一段是 S15 动工顺序，不是当前完成状态。每一步先补 focused failing test 或 schema assertion，再改实现；只在前一步验收通过后进入下一步。

1. Guardrail tests first：覆盖 fixture/deterministic/Host-local/sandbox binary fallback forbidden、旧 AOX/HMM eval artifact paths 不计 passed、raw provider/tool artifacts 不能替代 fixed `aox_hmm/*` outputs、S06 evidence / seeded smoke / test collection 不能作为 live cutover proof。
2. Live evidence payload：建立或收紧 S15 inline `PrerequisiteReport` / sealed `EvidenceBundle` result payload，至少能返回 fixed prompt、config snapshot digest、route policy id、provider/toolchain digests、approval ids、operation trace、registered artifact ids、normalized final paths 和 final answer digest；不新增 core/domain 顶层表。
3. Live AOX/HMM harness：把 AOX/HMM live gate 接到真实 product path，从 `POST /v3/sessions/{session_id}/messages` 进入，不注入 `AoxHmmFixtureSandboxRunner`、`DeterministicBioDatabaseAdapter` 或 fixture adapter allowance；fixture scenario 必须显式命名并从 live passed 统计中排除。
4. Current prerequisite report：运行当前真实 prerequisite 检查并作为 eval result payload 返回，主路只把 NCBI、UniProt、EBI HMMER REST `refprot`、S14 enabled HPC bio tools、runner/staging/fetch/output validation 作为 passed gate；disabled/optional `bio_tools.hmmer_search_cli` production database 单独报告，不阻塞主场景。
5. Fixed prompt and eval migration：更新 AOX/HMM live prompt、scenario id、required artifact list 和 result summary，使其使用本文件 fixed deliverable contract；旧 `filtered/scoring/candidates/candidate_cdhit85` 路径只允许作为 migration debt 或 fixture output。
6. Normalized export and validators：executor pipeline 汇总 S13/S14 raw artifacts 后，通过 `artifacts.register(...)` 登记 fixed `aox_hmm/*` outputs；实现本文件 minimum final-output validators 和 `live_artifact_missing` / `live_evidence_incomplete` failure mapping。
7. Approval verification：自动 live gate 使用 canonical approval resolve API approve pending operation，并记录同一 `operation_id` / `operation_digest` 的 continuation；人工 Web UI 演示单独验证同一 approval card 可以恢复同一 blocked SDK operation。
8. Readiness review：检查 final answer、task board、delegation、inbox/events、runtime drain、workspace artifacts、inline evidence bundle 和 safe projections；缺 fixed prompt、config snapshot、image digest、route policy id、toolchain/provider digests、operation trace、artifact ids 或 final answer digest 时不能标记 passed。

## 测试/验收

- fixture scenario 名称、trace 和 summary 必须标记 `fixture`；fixture 不计入 live cutover passed。
- live scenario 不注入 deterministic adapters，不绕过 persistent sandbox source execution，不使用 Host-local、sandbox binary 或 sibling backend 替代缺失的 provider/HPC prerequisite。
- live E2E 必须产出 fixed deliverable contract 中列出的 `aox_hmm/*` artifacts；raw provider/tool artifacts 可以额外存在，但不能替代这些 normalized outputs。只存在 raw provider/tool artifacts 而缺 fixed `aox_hmm/*` normalized outputs 时返回 `live_artifact_missing`。
- live AOX/HMM eval 必须使用本文件 fixed deliverable paths；旧 `filtered/scoring/candidates/candidate_cdhit85` 路径不能作为 S15 pass contract。
- final answer 由 master / executor agent 根据任务、artifact 和 protocol thread 自行生成；recipe/eval 可以检查它是否充分解释候选数量、过滤阈值、provider/tool/backend 摘要、重要结果条件和关键 artifact ids，但 harness 不硬编码 AOX/HMM 专用措辞。
- 主路 prerequisite 缺失只返回 `prerequisite_missing`，不能标记 passed。disabled / optional offline-HPC `bio_tools.hmmer_search_cli` production database 缺失不影响当前 EBI REST 主场景 passed；若该 route 被显式纳入 live scenario，则必须单独 `prerequisite_missing`。
- passed S15 live result 必须有 sealed inline evidence payload 和 `evidence_bundle_digest`；bundle 缺 fixed prompt、config snapshot、image digest、route policy id、toolchain/provider digests、operation trace、artifact ids 或 final answer digest 时返回 `live_evidence_incomplete`。
- approval 验收分两条：自动 live gate 必须通过正常 approval resolve API approve pending operation；人工 Web UI 演示必须证明同一 approval card 可以由用户点击 approve 后继续同一 SDK operation。两条都不能绕过 canonical approval service。

## 明确不做什么

- 不直接运行 `reference/enz_miner_hmm_aox.ipynb`。
- 不把 Session 06 evidence、seeded smoke、test collection 或 fixture success 当成 live cutover proof。
- 不通过手工构造 invocation/run/approval/artifact 绕过用户 prompt、master、executor、approval、scheduler 或 artifact catalog。
- 不把 Host-local Apptainer/SIF、sandbox binary、raw provider/tool artifacts 或 optional `bio_tools.hmmer_search_cli` evidence 当成当前 S15 主路 cutover proof。
