# Session 14：真实 Bio Tools HPC Backends

## 目标

把真实 HPC runner 的 physical stage / remote run / declared output fetch 接到 Session 11 的 placement / declarative stage-fetch API 后面，并为 AOX/HMM `bio_tools` 接入第一批真实 HPC backend。S14 的完成门槛只覆盖 `bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild` 和 `bio_tools.hmmalign`；公共 HPC stage/run/fetch 边界可复用于后续 `structure_tools.fpocket`、`docking.vina` 和其它 placement operation，但这些不属于本 session 完成条件。

文件名中的 `local-hpc` 不表示 Host-local 产品 route。AOX/HMM 生信 CLI 工具统一通过 Host-supervised HPC backend 执行；Host 本机和 executor sandbox 不作为产品 route 或 fallback。

## 当前缺口

- 现有 fixture tool adapter 不能证明真实 MAFFT、CD-HIT、hmmbuild 或 hmmalign cutover。
- Session 06 evidence 显示 Host-local HMMER 只有非 route SIF smoke；MAFFT、CD-HIT、hmmbuild 和 hmmalign 的产品 route 只能来自 HPC evidence。
- 缺少 `BioToolSupervisor`、typed params schema、command template、resource cap、HPC stage/fetch adapter、产品级 declared output validation 和 log artifactization；optional offline/HPC `bio_tools.hmmer_search_cli` 仍缺 production target database inventory。

## 实施范围

- 实施前必须读取 `06-adapter-foundation-evidence.md`，把每个 backend route 绑定到当前 evidence 或 prerequisite failure。
- 交付 `bio_tools` route policy v1：
  - `bio_tools.cdhit`：`selected_backend="hpc"`。
  - `bio_tools.mafft`：`selected_backend="hpc"`。
  - `bio_tools.hmmbuild`：`selected_backend="hpc"`。
  - `bio_tools.hmmalign`：`selected_backend="hpc"`。
  - `bio_tools.hmmer_search_cli`：保留 public SDK 名称，但本 session route entry 固定为 `disabled`，调用返回 `unsupported_in_s14`。该 route 不计入 S14 完成条件，也不因 database inventory 缺失标记为 `route_prerequisite_missing`。
- 启用 route 只能是 `hpc` 或 `unsupported/prerequisite_missing`；禁用 route 只能是 `disabled/unsupported_in_s14`。不做 dynamic route、Host-local route、sandbox binary route 或 hidden fallback。
- Host-local HMMER/SIF 观察只能作为迁移背景和参数参考，不能成为 `bio_tools.*` route、fallback 或 S14 completion evidence。
- 本 session 管理 MAFFT、CD-HIT、HMMER、HPC runner、HPC runtime packaging 和 toolchain digest；它不创建、不替换、不扩展 executor sandbox base image。executor base image 已由 s07 锁定，sandbox 只通过 Host-supervised SDK 请求这些领域能力。
- S14 必须复用 S10/S12 approval 与 adapter envelope：真实 runner physical stage、remote workspace materialization、remote command、declared output fetch、log retrieval 和 output registration 只能在 `AdapterApprovalEnvelope` 创建且对应 approval 通过后执行。
- approval 前只允许 Host 本地校验 route policy、toolchain/runtime packaging registry、typed params schema、declared outputs、planned fetch intent 和 prerequisite status；不得创建远端目录、上传用户输入、提交 Slurm/job、运行领域命令、fetch 输出或登记 artifacts。
- `HpcBioToolBackend` 实现 Session 11 的 `hpc` placement contract：接收已批准 operation 中冻结的 `hpc_workspace_id`、stage refs、workspace-relative input paths 和 declared outputs，通过 runner staging、remote execution、declared output fetch 和 S08 artifact boundary registration 完成真实工作。
- static route 为 `hpc` 的 `bio_tools.*` 调用必须由 executor code 显式提供 `hpc.workspace` placement、stage refs、declared outputs 和 fetch/register intent；Host 不创建隐式 default HPC workspace，也不把 placement 当成事后 provenance 字段。
- params 是 typed allowlist，拒绝 Host path、HPC path、database mount、raw args、shell、redirect 和 arbitrary command。
- 每个 output 通过 FASTA/HMM/MSA/CSV 最小格式或 required columns 校验。
- S14 不发明新的 public envelope；pre-run 使用 S12 `AdapterApprovalEnvelope` 冻结 selected backend、route reason、runtime packaging、toolchain id、stage refs、declared outputs 和 planned fetch intent，post-run 使用 S12 `AdapterResultEnvelope` 返回 backend run id、fetch refs、registered artifact ids、validation results、bounded summary、warnings 和 structured error。
- `structure_tools.fpocket` 与 `docking.vina` 可继续使用同一个通用 placement backend contract，但本 session 不以它们的真实 runner 接入作为完成门槛。

## 实现落点

S14 的实现落点按模块职责划分，不改变 S11 public SDK surface，也不新增 S12 之外的 public envelope。

- `openzyme-core`：持久化 route policy snapshot、S12 approval/result envelope、operation digest、approval 状态、`BackendRun` / recovery 记录和 safe projection 所需字段。
- `openzyme-engines`：实现 `BioToolSupervisor` / `HpcBioToolBackend`、typed params schema、command template rendering、resource estimate、runner handoff、declared output validation、S08 artifact registration 和 public payload scrubber。
- `openzyme-pipeline`：保持现有 `bio_tools.*(..., placement=ws, expected_outputs=[...])` contract；不新增 Host-local route、runner path 参数、raw args 参数或 `hmmer_search_cli` product route。
- `apps/mcp-hpc-runner`：承载 MAFFT / CD-HIT / HMMER runtime packaging、command template、runner preflight 和 runner-level contract smoke；runner-level smoke 是 product-route live smoke 的 prerequisite evidence，不是 S14 completion proof。

## 接口变化

- output artifact metadata 包含 tool name/version、placement、selected backend、route reason、runtime packaging safe digest、command template id、sanitized args digest、input artifact ids、stage refs、params digest、resource estimate、source snapshot、run id、declared output path 和 validation result。
- SDK operation approval/provenance 记录 `route_reason="static_policy:v1"` 或后续明确 policy id。
- `AdapterApprovalEnvelope` 中的 pre-run frozen fields 不得被运行后字段原地改写；`backend_run_id`、`fetch_refs`、output sealed digest、`registered_artifact_ids`、validation result 和 safe diagnostics 只能进入 `AdapterResultEnvelope` 或 output artifact provenance。
- `bio_tools.hmmer_search_cli` 的 disabled route 返回 `unsupported_in_s14`，message 指向 provider-side `bio.hmmer_search(..., database="refprot")` 作为当前 AOX/HMM 主路；不得尝试 Host-local HMMER、fixture 或 sibling backend。
- 结构化错误码覆盖 `unsupported_in_s14`、`tool_missing`、`container_runtime_missing`、`database_missing`、`invalid_params`、`forbidden_param`、`nonzero_exit`、`timeout`、`hpc_runner_timeout`、`hpc_runner_unavailable`、`declared_output_missing`、`output_validation_failed`、`hpc_staging_failed`。runner-issued `SSH_CONNECTION_TIMEOUT` 与其他 `SSH_CONNECTION_FAILED` 不得降格为工具 `nonzero_exit`；二者分别投影为 retryable runner timeout/unavailable，但不触发 harness 自动重放或本地 fallback。

## Declared Outputs / Validators

S14 product-route live smoke 使用 `apps/mcp-hpc-runner/fixtures/hpc_tool_samples/aox_hmm` 作为最小数据集。runner raw outputs 可以额外 artifactize，但 S14 completion 只看下列 canonical declared outputs 和 validator。

| SDK operation | staged inputs | canonical declared outputs | validator |
| --- | --- | --- | --- |
| `bio_tools.cdhit` | `input_fasta` | `bio_tools/cdhit/clustered.fasta`; `bio_tools/cdhit/clusters.csv` | FASTA 非空；完整 `.clstr` normalize 为 `cdhit_cluster_membership@1` 的 one-member-per-row CSV，并在任何 output 注册前核对 staged FASTA 成员全集、长度和每簇唯一 representative；fixture 标记为 `fixture_non_cutover` |
| `bio_tools.mafft` | `input_fasta` | `bio_tools/mafft/alignment.fasta` | FASTA/MSA 非空，至少两个 aligned sequence record |
| `bio_tools.hmmbuild` | `alignment` | `bio_tools/hmmbuild/model.hmm` | HMMER3 profile marker 存在，文件非空 |
| `bio_tools.hmmalign` | `hmm`; `fasta` | `bio_tools/hmmalign/aligned.fasta` | FASTA/MSA 非空；runner 的 Stockholm raw output 可作为 diagnostic/raw artifact，但 product declared output 必须被 normalize/validated 后登记 |
| `bio_tools.hmmer_search_cli` | `hmm`; `target_fasta` | none in S14 | disabled route，返回 `unsupported_in_s14`，不进入 completion gate |

## Resource Identity / Lifecycle

本 session 锁定 `ToolchainRegistry`、`RuntimePackagingRecord`、`DatabaseRecord`、`CommandTemplate` 和 `BackendRun`。

- `ToolchainRegistry`
  - identity：`toolchain_id = tool_name + tool_version + runtime_packaging_id + command_template_id + database_ref`；无外部 database 的工具使用固定 `database_ref="none"`，不得省略该字段。
  - owner：Host bio tool supervisor/toolchain registry 管理；executor 不选择 binary、SIF、database mount 或 runner path。
  - lifecycle：toolchain 缺失返回 `toolchain_not_configured`；digest/version 与 route policy 不匹配返回 `toolchain_digest_mismatch`。
  - persistence：tool name/version、safe digest、route policy id、command template id 和 database id 进入 provenance。
- `RuntimePackagingRecord`
  - identity：`runtime_packaging_id` 绑定 HPC module/spack/container/admin-wrapper 标识、版本、safe digest、container runtime version（如适用）和 safe packaging metadata。
  - owner：Host packaging registry 管理；不扩展 executor sandbox base image。
  - lifecycle：缺 HPC runtime、module/container/admin wrapper 或 digest 不匹配时返回 `container_runtime_missing` / `toolchain_not_configured` / `toolchain_digest_mismatch`；不自动换 Host-local、sandbox、sibling backend 或 fixture。
- `DatabaseRecord`
  - identity：`database_id` 绑定 database logical name、version、safe digest 和 prerequisite evidence ref。
  - owner：Host backend/toolchain registry 管理。
  - lifecycle：启用 route 缺 database 返回 `database_missing`；database digest 漂移必须触发新 approval 或 drift failure。S14 中 `bio_tools.hmmer_search_cli` 是 disabled route，不创建 production `DatabaseRecord` 要求，也不把缺 database 当成本 session 完成失败。
- `CommandTemplate`
  - identity：`command_template_id` 指向 versioned allowlist template。
  - owner：Host bio tool supervisor 管理。
  - lifecycle：params schema validation 后渲染 sanitized args digest；raw args、shell、redirect 和 path override 都返回 structured failure。
- `BackendRun`
  - identity：`backend_run_id` 由 Host 创建，绑定 `operation_id` / `operation_digest`、`sandbox_run_id`、`source_snapshot_artifact_id` 或 source digest、`hpc_workspace_id`、selected backend、toolchain id、stage refs、declared outputs 和 runner invocation id。
  - owner：Host HPC backend service 创建、恢复、结束和登记 outputs。
  - lifecycle：`queued -> staging -> running -> fetching -> validating -> completed|failed|recovery_failed`。
  - persistence：backend run summary、stage/fetch manifest、safe log refs、output validation result、registered artifact ids 和 S12 `AdapterResultEnvelope` 回链持久化；remote path、Slurm id 和 private runner config 不进入 public projection。
  - recovery：Host 重启后只能通过持久化 `BackendRun`、同一 `operation_digest` 和同一 runner invocation 安全查询 / 继续既有真实 run；无法证明同一 run 可恢复时返回 `backend_run_recovery_failed`，不得重放已批准真实 work。
  - idempotency：stage declaration 以 stage ref digest + workspace-relative path 幂等；fetch 以 `backend_run_id` + declared output path 幂等；重复 fetch 返回既有 registered artifact refs，不重新登记 divergent artifact。
  - cleanup：retention/cleanup 由 Host backend policy 管理；cleanup failure 只产生 `hpc_cleanup_failed` diagnostic warning，不把已成功登记的 artifact 改为失败。

补充错误码：

- `toolchain_not_configured`
- `toolchain_digest_mismatch`
- `route_prerequisite_missing`
- `unsupported_in_s14`
- `backend_run_recovery_failed`
- `hpc_fetch_failed`
- `hpc_cleanup_failed`

## 推荐实施顺序

这一段是 S14 动工顺序，不是当前完成状态。每一步先补 focused failing test、schema assertion 或最小 live prerequisite probe，再改实现；只在前一步验收通过后进入下一步。

1. Guardrail tests first：覆盖 route policy lookup、`hmmer_search_cli` disabled route、S12 approval/result 字段分离、approval 前无 runner side effect、typed params allowlist、per-tool output validators、path/secret scrubber 和 fixture / Host-local / sandbox binary fallback forbidden。
2. Route / toolchain / runtime registry：固定 `bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild`、`bio_tools.hmmalign` 为 `hpc` route 或 prerequisite failure；runtime packaging、toolchain id、command template id、route policy id 和 evidence ref 必须进入 approval/provenance，缺失或漂移 fail-closed。
3. S12 approval seam：把 S11 `hpc_workspace_id`、stage refs、workspace-relative input paths、declared outputs、resource estimate 和 planned fetch intent 写入 `AdapterApprovalEnvelope`；确认 `backend_run_id`、fetch refs、registered artifacts、validation result 和 diagnostics 只进入 `AdapterResultEnvelope` 或 output provenance。
4. `HpcBioToolBackend` 接入：approval 通过后才调用 runner physical stage、remote workspace materialization、remote command、declared output fetch、log retrieval 和 S08 artifact registration；operation 完成前不得 eager persist visible artifacts。
5. Output normalization / validation：按本文件 declared outputs 表将 runner raw outputs normalize 到 canonical product paths；validation、copy/seal、sealed digest recheck 或 immutable commit 任一步失败时不得创建 visible artifact。
6. Recovery / idempotency / projection：补齐 `BackendRun` 状态恢复、重复 stage/fetch 幂等、partial fetch 失败语义、cleanup warning、oversized log artifactization 和 runner-specific public payload scrubber。
7. Verification and readiness review：先通过 controlled smoke 和非-live regression，再运行 product-route `live_hpc` smoke；缺 runner、toolchain、runtime packaging、output validation 或 live evidence 时只能标记 `prerequisite_missing` / `route_prerequisite_missing`，不能标记 S14 complete / cutover-ready。

## 测试/验收

- route table 中每个 `hpc` 选择都有 evidence ref；缺 `ok` HPC 证据时只能是 `unsupported/prerequisite_missing`。`bio_tools.hmmer_search_cli` 必须固定为 `disabled/unsupported_in_s14`，不进入 completion gate。
- 每个 operation 有 params schema validation、command rendering golden test 和 output validation test。
- 缺 MAFFT/CD-HIT/HMMER/database/HPC runner/HPC runtime packaging 时结构化失败，不能改走 Host-local、sandbox binary、fixture 或 sibling backend。
- toolchain id、runtime packaging id、database id、command template id 和 route policy id 进入 operation/approval/provenance；缺失或漂移结构化失败。
- HPC backend envelope 必须复用 S12 双层结构：approval/plan 展示 `hpc_workspace_id`、stage refs、declared outputs、planned fetch intent、selected backend 和 route/runtime refs；result/fetch 展示 fetch refs、backend run id、validation results 和 artifact ids。
- controlled smoke 必须覆盖 route policy lookup、typed params schema、command rendering、S12 envelope pre/post 字段分离、S08 artifact registration、output validation 和 path/secret scrubbing。
- product-route live HPC smoke 必须从 `openzyme_pipeline.bio_tools.*` 进入，覆盖 `hpc.workspace`、`stage_artifact`、S10/S12 approval/envelope、真实 runner artifact staging、remote command execution、declared output fetch、format validation、S08 artifact registration、log artifactization 和 provenance；直接运行 runner contract smoke 只能作为 prerequisite evidence。
- live smoke 使用 `apps/mcp-hpc-runner/fixtures/hpc_tool_samples/aox_hmm` 的最小输入集，并必须产出 declared outputs 表中的 canonical product paths；runner raw outputs、logs 和 contract records 可额外登记为 diagnostic/raw artifacts，但不能替代 canonical product outputs。
- S14 实现阶段必须新增稳定 `integration` + `live_hpc` 验收入口；命令应固定为 `uv run pytest ... -m "integration and live_hpc"` 的 product-route test，而不是只运行 `apps/mcp-hpc-runner` contract smoke。
- oversized logs 以 artifact ref 暴露，RPC 只返回截断摘要。
- S14 是真实 backend 接入 session。`bio_tools.cdhit`、`bio_tools.mafft`、`bio_tools.hmmbuild`、`bio_tools.hmmalign`、HPC runner、staging/fetch 或 output validation 中任何关键 prerequisite 缺失时，本 session 只能停在 `prerequisite_missing` / `route_prerequisite_missing`，不能标记完成或 cutover-ready。controlled smoke 和 live HPC smoke 都通过后，才允许标记 S14 complete / cutover-ready。`bio_tools.hmmer_search_cli` 的 `unsupported_in_s14` 不阻塞 S14 完成。

## 明确不做什么

- 不允许 sandbox code 直接调用 MAFFT、CD-HIT、HMMER binary、Apptainer/container runtime、SSH、Slurm 或 runner config。
- 不允许 approval 前发生 runner 侧 physical stage、remote workspace materialization、remote command、fetch、log retrieval 或 output registration。
- 不在 S14 重新设计 `hpc.workspace` / `stage_artifact` / `fetch_outputs` API；这里只实现 S11 已定义的后端接入。
- 不把 `structure_tools.fpocket` / `docking.vina` 的真实 runner 接入作为 S14 完成门槛。
- 不把底层 CLI 全量参数透传给 LLM。
- 不使用 deterministic fixture output、Host-local observation 或 sandbox binary 替代缺失工具或失败命令。
