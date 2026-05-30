# Session 13：真实 Bio Provider Adapters

## 目标

为 `openzyme_pipeline.bio` 接入真实 Host-supervised provider adapter，使 AOX/HMM persistent sandbox workflow 能获取 NCBI protein、UniProt 记录和 EBI HMMER REST 结果。本 session 是 Session 12 adapter envelope 后面的 provider backend 实施层：真实 provider work 只能在 `AdapterApprovalEnvelope` 创建并通过审批后执行，结果必须通过 `AdapterResultEnvelope` 回链同一个 `operation_id` / `operation_digest`。缺网络、缺配置或 provider 不可用时必须结构化失败，不得 fallback 到 deterministic adapter。

## 当前缺口

- fixture adapter 只能证明 SDK envelope，不能证明真实 NCBI、UniProt 或 EBI HMMER cutover。
- provider identity、timeout、retry、quota、pagination、polling、schema validation 和 provenance 仍需要真实实现。
- `provider_config_digest`、`route_policy_id`、Session 06 evidence/current re-probe 和真实 provider config 之间的 linkage 仍需要由 S13 固化。
- 大型 FASTA、metadata、raw hits、parsed hits 和 provider transcript 不能返回 RPC 全文，但除敏感信息外应写入 sandbox `output_dir` 并登记 artifact，让 executor 能直接检查真实 provider 观察结果。
- provider error/warning 字段必须与 S12 canonical envelope 对齐，不能再形成一套并行的 public error shape；provider 原生状态、消息和 payload 保留在脱敏 transcript 中。

## 实施范围

- `bio.ncbi_fetch_proteins` 使用 Host 托管 NCBI provider client，支持 accession 批量 fetch、identity policy、rate limit、retry、sanitized provider transcript 和 parsed sequence outputs。
- `bio.uniprot_fetch` 使用 Host 托管 UniProt REST client，支持 accession list、字段选择、batch size、cursor pagination、schema validation、sanitized provider transcript 和 parsed sequence outputs。
- `bio.hmmer_search` 使用 Host 托管 EBI HMMER REST client，支持 submit、poll、result pagination、sanitized provider transcript、raw hits artifact 和 parsed hits CSV artifact。
- S13 负责 provider route policy linkage：`bio.*` provider route policy 必须回链 Session 06 evidence 或当前 live prerequisite probe，携带 selected backend `provider_http`、runtime packaging `provider_http:v1`、resource class、expected outputs、approval requirement、prerequisite/failure mapping 和 `provider_config_digest`。缺 route policy、缺 provider config、evidence 不兼容或 fixture backend 均 fail-closed。
- S13 的第一项实现前置任务是重新 probe EBI HMMER REST：使用 S15 固定 AOX/HMM 合同中的 HMM、database `refprot` 和 known-good bounded sample，更新 `06-adapter-foundation-evidence.md` 中 `bio.hmmer_search` evidence。若该 probe 仍不是 `ok`，NCBI/UniProt 子能力可以作为单独 provider adapter 完成，但整个 S13 不能标记 passed；`bio.hmmer_search` 产品路径只能返回结构化 provider failure，S15 也不能标记 passed。
- provider output provenance 记录 provider、operation、operation digest、route policy id、query/accession/database、page/cursor、response digest、retrieved_at、API version、input artifact ids、source snapshot、provider request id 和 transcript artifact ids。
- provider request、sanitized raw response、polling/pagination/retry history、parsed outputs 和 provider error diagnostics 必须先写入 caller 指定的 `output_dir`，再经 S08 `ArtifactBoundaryService` 或等价 Host-owned artifact boundary 完成 validation、copy/seal、sealed digest recheck 和 immutable Artifact row commit 后，才能作为 `AdapterResultEnvelope` 的 artifact refs 返回。provider cache、Host temp file 或 sandbox path 不能作为 canonical artifact。
- empty result、provider error、schema drift、pagination failure、polling failure 和 partial result 必须区分，但 public canonical code 保持粗粒度；provider 细节由 `provider_observation.json` 承载。

## Provider Route Policy v1

S13 v1 使用当前 S12 route policy identity，不重新发明命名：

| operation | route_policy_id | selected_backend | runtime_packaging_id | provider_config_digest | approval_requirement |
| --- | --- | --- | --- | --- | --- |
| `bio.ncbi_fetch_proteins` | `bio.ncbi_fetch_proteins.provider:v1` | `provider_http` | `provider_http:v1` | `provider_config:ncbi:v1` | `{"required": true}` |
| `bio.uniprot_fetch` | `bio.uniprot_fetch.provider:v1` | `provider_http` | `provider_http:v1` | `provider_config:uniprot:v1` | `{"required": true}` |
| `bio.hmmer_search` | `bio.hmmer_search.provider:v1` | `provider_http` | `provider_http:v1` | `provider_config:ebi_hmmer:v1` | `{"required": true}` |

每一行还必须保留对应 Session 06 `evidence_ref` / `parameter_inventory_ref`，并在 S13 re-probe 更新后指向当前可用证据。policy status 不是 `ok`、evidence 状态不是可用状态或 `provider_config_digest` 与 ProviderRegistry 不匹配时，不能执行 provider request。

每个真实 provider operation 都必须走 S10/S12 SDK controlled-operation approval。同一 session 内同一 `operation_digest` 可以复用 approved approval；provider retry、UniProt cursor pagination、EBI HMMER polling 和 EBI HMMER result pagination 属于同一个 approved provider request，不创建新的 approval。

## 接口变化

- S13 复用 S12 canonical error/warning envelope。public error/warning 固定字段为 `code`、`stage`、`retryable`、`summary`、`details_ref` 和 `safe_diagnostics`；provider 原生状态、HTTP/job response、affected accessions、affected pages、quota/rate-limit headers、polling state 和 pagination state 进入脱敏 transcript outputs/artifacts。
- `openzyme_pipeline.bio` 的三个 public SDK function 必须新增必填 `output_dir` 参数。`output_dir` 必须规范化到 `/workspace/output/...` 下的目录；缺失、空值、绝对 Host path、`..`、symlink escape、`/workspace/input|work|src|logs` 或旧 `/openzyme/*` path 均返回结构化 failure。
- Host provider adapter 把 sanitized provider transcript、parsed outputs 和 diagnostics 写入 `output_dir`，再立即通过 S08 `ArtifactBoundaryService` 执行 copy/seal/register。artifact `relative_path` 使用去掉 `/workspace/output/` 前缀后的同一路径；后续跨 operation 使用仍必须通过 artifact id，不通过 sandbox path 授权。
- provider request 已经产生 provider 观察结果后，即使最终失败，Host 也必须在 `output_dir` 写入 `provider_observation.json` 和 `provider_error.json` 并注册 diagnostic artifacts；审批拒绝、配置缺失、`output_dir` 无效等 pre-run failure 不要求写 transcript。
- `AdapterApprovalEnvelope` pre-run 字段必须包含 `sdk_module="bio"`、`function_name`、`route_policy_id`、`selected_backend="provider_http"`、`provider_config_digest`、`resource_estimate`、`expected_outputs`、`approval_requirement` 和 planned output path summary。`provider_request_id`、registered artifact ids、response digest、actual validation result 和 provider error artifact id 不得参与 pre-run approval digest。
- `AdapterResultEnvelope` post-run 字段必须回链同一个 `operation_id` / `operation_digest`，并携带 `provider_request_id`、`registered_artifact_ids` / `output_artifact_ids`、validation results、bounded summary、warnings、error 和 safe diagnostics ref。S13 不新增 S12 envelope 顶层字段；transcript manifest 必须放入 `bounded_summary.transcript_manifest`，完整内容通过 artifact refs 暴露。
- SDK/RPC inline payload 只返回 manifest、artifact refs、counts、digests、warnings、error 和 provider summary；不得 inline 返回大型 FASTA、metadata 全文、raw hits 全文或 parsed hits 全文。完整非敏感 provider transcript 通过 `output_dir` files 和 artifact refs 暴露给 executor。
- SDK result、event、workspace projection、registered artifacts 和 transcript files 都不得暴露 credential、API token、private endpoint、Host cache path、Host temp path、sandbox host path、raw secret、`storage_uri`、private provider config 或完整未脱敏 provider response。

## Sanitized Provider Transcript Contract

S13 v1 使用统一 `ProviderObservation` contract，而不是为每个 provider 发明一套 public schema。所有 relative path 均相对于 caller 指定的 `output_dir`。

| file/directory | artifact kind/format | contract |
| --- | --- | --- |
| `provider_request.json` | result/json | approved operation id/digest, route policy id, provider config digest, normalized params, requested output dir summary, source snapshot/input artifact refs, resource limits and request timestamps |
| `provider_observation.json` | result/json | 脱敏 provider transcript manifest：provider name/API version、request ids、HTTP/job statuses、allowlisted headers、response digests、retry attempts、polling/pagination history、output files、warnings、canonical error 和 provider 原生非敏感消息 |
| `provider_raw/*` | result/json, result/text or provider-native safe text | 按真实观察写入的脱敏 raw provider responses/pages/jobs；完整非敏感 body 可以 artifactize，binary 或超大 payload 只保留为 file/artifact，并在 inline result 中摘要 |
| `provider_parsed/*` | sequence/fasta, result/csv or result/json | best-effort parsed outputs useful to executor, derived only from observed provider content |
| `provider_error.json` | result/json diagnostic | canonical code/stage/retryable/summary，加 provider 原生 status/message/body excerpt 或脱敏 body ref、response digest、provider request id 和可用时的 remediation hint |

NCBI/UniProt/HMMER convenience outputs such as `proteins.fasta`, `sequences.fasta`, `raw_results.json`, `raw_hits.json` or `parsed_hits.csv` may be written under `provider_parsed/` or `provider_raw/` when useful, but they are not separate public schemas. Parsed files must not invent fields absent from the observed provider response; missing provider fields are omitted or left empty with a warning in `provider_observation.json`.

`bio.hmmer_search` v1 artifactizes at most the top 100000 hits by provider result order. If provider reports more hits or pages, `provider_observation.json`, transcript manifest and parsed outputs must record total hit count/page count when available, truncation marker and warning. S15 may later normalize these raw provider artifacts into final `aox_hmm/*` deliverables, but S13 raw artifacts are not those final deliverables.

任何内容进入 `output_dir`、SDK result、event、workspace projection 或 artifact metadata 前都必须先脱敏。Headers 使用 allowlist，例如 status、content type、request id、date 和 rate-limit/quota fields。JSON/text body 使用 denylist key scrubbing 和 path-pattern scrubbing，过滤 credential、token、API key、secret、private endpoint、Host path、Host cache path、Host temp path、sandbox host path、storage URI、runner/config path 和等价敏感值。未脱敏完整 provider response 只能留在 Host-private diagnostics。

## Provider Policy Defaults

- HTTP request timeout default is 30 seconds per provider HTTP request.
- Retry default is 2 retries with bounded exponential backoff of 1s then 2s; only network/timeout/quota stages marked retryable by the provider adapter may retry.
- NCBI and UniProt v1 batch/page size cap is 100 records per provider request/page. Host settings may only tighten this cap unless route policy is explicitly revised.
- EBI HMMER v1 polling interval is 5 seconds, total polling timeout is 30 minutes, result `page_size` is 100 and max artifactized hits is 100000.
- Host settings may tighten timeout, retry, batch and hit caps. Raising caps requires an explicit provider policy or route policy update so approval summary and provenance show the changed resource estimate.

## Provider Error Mapping

S13 error mapping 刻意保持粗粒度。SDK error 使用 S12 canonical fields；provider 原生 status、message、allowlisted headers、body excerpt、sanitized body artifact refs、job status、polling history、pagination history、retry history、response digest 和 `provider_request_id` 进入 `provider_observation.json` / `provider_error.json`。这样 executor 能判断是否通过修改 pipeline code 或参数修复请求，不要求 S13 预判每一种 provider 细节失败。

| broad condition | canonical mapping |
| --- | --- |
| invalid accession, invalid query, unsupported database, malformed HMM or provider-declared bad request | `provider_invalid_request`, non-retryable unless the adapter explicitly marks a request repair path |
| HTTP 429, quota exhaustion, rate-limit response or equivalent provider throttling | `provider_rate_limited`, retryable only when retry-after/quota policy allows bounded retry |
| provider outage, HTTP 5xx, DNS/connect failure or unavailable endpoint | `provider_unavailable` |
| HTTP request timeout, EBI polling timeout or bounded pagination/polling deadline exceeded | `provider_timeout` |
| provider response cannot be parsed into the minimal observation/manifest contract after sanitization | `provider_schema_drift` |
| provider output files cannot be sanitized, written to `output_dir`, validated, copied/sealed or committed as immutable artifacts | `provider_artifactization_failed` |
| `output_dir` is missing, outside `/workspace/output/...`, conflicts with existing output or fails path/symlink guard before request execution | `provider_output_path_invalid` |

Empty provider results are completed-with-warning, not provider failure, when the provider successfully processed a valid request. Partial provider results may only be returned as partial if `provider_observation.json` clearly marks missing pages/jobs/files and the `AdapterResultEnvelope` status is `failed_partial`; partial artifacts cannot be presented as complete.

## Resource Identity / Lifecycle

本 session 锁定 `ProviderRegistry`、`ProviderRequest`、`ProviderObservation` 和 provider output path binding。Provider page/cursor state and cache records may exist, but they are Host-private implementation details unless surfaced through sanitized observation fields.

- `ProviderRegistry`
  - identity：`provider_config_digest` 由 provider name、API version、identity policy、quota policy、schema version 和 safe config fields 计算。
  - owner：Host provider registry/config 管理；sandbox 不接触 credential、private endpoint 或 Host cache path。
  - lifecycle：配置缺失返回 `provider_not_configured`；credential identity 缺失返回 `provider_identity_missing`；credential 过期返回 `provider_credential_expired`。
  - route linkage：`provider_config_digest` 必须进入 S12 `AdapterApprovalEnvelope` 和 provider route policy snapshot；缺失、不兼容或与 policy evidence 不匹配时返回结构化 failure，不执行 provider request。
  - persistence：safe digest、API version、schema version 和 quota policy 进入 provenance；secret value、private endpoint 和 Host cache path 不进入任何 artifact/projection。
- `ProviderRequest`
  - identity：`provider_request_id` 由 Host 创建，绑定 operation id、provider、query/accession/database、params digest、source snapshot 和 normalized `output_dir` digest。
  - owner：Host provider adapter 创建、重试、结束、脱敏 transcript、写 output files 并登记 artifacts；sandbox SDK 只能触发 request 并接收 bounded inline result 与 artifact refs。
  - lifecycle：`created -> running -> completed|completed_with_warnings|failed|failed_partial`；empty result 是 completed 状态的一种，不等同 provider failure。
  - retry：只有 provider adapter 标记为 retryable 的 network/timeout/rate-limit stage 可重试；重试次数、backoff policy and observed retry outcomes 进入 `provider_observation.json`。
  - artifactization：success、completed_with_warnings、failed 和 failed_partial 的 provider transcript/outputs 必须先写入 requested `/workspace/output/...`，再通过 Host-owned artifact boundary 登记；artifact commit 失败时 request 不能伪装成 completed。
- `ProviderObservation`
  - identity：`provider_observation_id = provider_request_id + observation_sequence_or_digest`。
  - owner：Host provider adapter 创建；所有进入 sandbox/output/artifact/projection 的 observation fields 必须先完成 sanitization。
  - lifecycle：记录 request attempts、provider statuses、allowlisted headers、response digests、retries、polling/pagination checkpoints、transcript file paths、parsed output paths、warnings 和 canonical error mapping。Host 不得为了恢复而静默重提 EBI job、改写 cursor、跳页或返回 synthetic success。
  - persistence：脱敏 observation files 和 artifact ids 对 executor 可见；未脱敏 provider body/header、credentials、private endpoints 和 Host/cache paths 仍为 Host-private。
- Host-private page/cursor/cache state
  - pagination/polling cursors and provider cache records may be persisted for recovery and efficiency, but their raw content is not a public S13 resource.
  - cache hit/miss, retrieved_at, response digest and safe cache key digest may enter `provider_observation.json`; cache content is not canonical artifact and cannot alone support live cutover passed evidence.
- `ProviderOutputPathBinding`
  - identity：`output_binding_id = provider_request_id + sandbox_workspace_id + normalized_output_dir_digest`。
  - owner：Host provider adapter 创建，S08 artifact boundary 登记 artifacts；executor 只能通过 SDK 参数声明 output directory。
  - lifecycle：同一 provider request 内文件名固定；同一 output path 已存在不同 digest 或 path 越界返回 structured failure，不覆盖。失败时 `provider_observation.json` / `provider_error.json` 是 diagnostic output，不代表 provider success。
  - persistence：normalized workspace path summary、artifact ids、validation result 和 source snapshot binding 进入 provenance；Host path 不进入 public projection。

固定错误码：

- `provider_not_configured`
- `provider_identity_missing`
- `provider_credential_expired`
- `provider_invalid_request`
- `provider_rate_limited`
- `provider_unavailable`
- `provider_timeout`
- `provider_schema_drift`
- `provider_partial_result`
- `provider_artifactization_failed`
- `provider_output_path_invalid`

## 测试/验收

- fixture/unit tests 覆盖 provider success、empty result、invalid accession、partial batch、HTTP unavailable、timeout、rate limited、schema drift、polling recovery failure、pagination recovery failure、cache hit、fixture backend forbidden、missing/forbidden `output_dir`、sanitized transcript output 和 provider error diagnostic artifacts。
- 每个真实 `bio.*` provider operation 在执行 provider request 前都有 S12 `AdapterApprovalEnvelope`，并冻结 route policy id、provider config digest、params digest、input artifact digests、source snapshot digest、expected outputs 和 approval requirement。
- provider result 只通过 S12 `AdapterResultEnvelope` 返回 bounded inline summary、manifest、warnings/errors、safe diagnostics refs、provider request id 和 artifact refs；运行后字段不得写回或改写 approved approval envelope。
- provider outputs 通过 Host-owned artifact boundary 登记；artifact validation、copy/seal、sealed digest recheck 或 immutable row commit 失败时不创建 visible artifact，也不 fallback 到 provider cache、workspace path 或 synthetic artifact。
- provider output files 写入 caller 指定的 `/workspace/output/...` 目录；artifact `relative_path` 使用同一路径的 workspace-relative form；`output_dir` 越界、冲突、symlink escape 或缺失时不执行 provider request。
- provider request 已产生 provider observation 后，即使失败也写入并注册 sanitized `provider_observation.json` / `provider_error.json` diagnostic artifacts；SDK error 同时返回 canonical code、manifest、bounded summary 和 details/artifact refs。
- 产品默认路径缺真实 provider 配置时返回 `provider_not_configured` 或 `provider_identity_missing`；缺 route policy、policy 与 evidence 不兼容、缺 provider config digest 或 fixture backend 返回结构化 failure，不能创建 synthetic artifact。
- credential 过期、schema drift、polling/pagination recovery failure 和 cache hit 都有明确 provenance；cache hit 不能单独支撑 live passed。
- provider warning/error 进入 execution status、events 和 workspace 安全投影，并使用 S12 canonical `code`、`stage`、`retryable`、`summary`、`details_ref`、`safe_diagnostics` 字段。
- live/provider prerequisite 证据可回链 Session 06 evidence，但 passed 只能来自当前真实检查。
- EBI HMMER REST 主路必须用 `database="refprot"` 覆盖 submit、poll、result pagination、empty/failed result mapping、sanitized transcript artifact 和 parsed hits output；若 AOX/HMM 固定 HMM re-probe failed 未修复，整个 S13 不能标记 passed，只能产生 provider failure evidence。
- public SDK result、event、workspace projection 和 registered transcript artifacts 不暴露 credential、private endpoint、provider raw secret、Host cache path、Host temp path、sandbox host path、storage URI 或未脱敏 provider response。
- sanitizer tests 覆盖 allowlisted headers，以及 credential、token、API key、secret、private endpoint、Host path、Host cache path、Host temp path、sandbox host path 和等价敏感值的 JSON/text denylisted keys/patterns。
- executor usability tests 证明：失败 provider calls 只要已有 observation，就在 `provider_observation.json` / `provider_error.json` 中暴露足够的脱敏 provider 原生 message/status/body context，让 executor 判断是否可以通过改参数修复。

## 推荐实施顺序

这一段是 S13 动工顺序，不是当前完成状态。每一步先补 focused failing test、schema assertion 或最小 live prerequisite probe，再改实现；只在前一步验收通过后进入下一步。

1. Current HMMER prerequisite re-probe：先用 S15 固定 AOX/HMM HMM、`database="refprot"` 和 bounded hit cap 重新 probe EBI HMMER REST，并更新 `06-adapter-foundation-evidence.md`。若这一步仍不是 `ok`，可以继续完成 NCBI/UniProt adapter，但 S13 不能标记 passed，`bio.hmmer_search` 产品路径只能返回结构化 provider failure。
2. S12 result field placement：锁定 S13 不扩展 S12 `AdapterResultEnvelope` 顶层 schema；transcript manifest 落在 `bounded_summary.transcript_manifest`，完整 transcript 只通过 `registered_artifact_ids` / `output_artifact_ids` 和 `details_ref` 暴露。
3. SDK `output_dir` contract and docs/examples：给三个 `openzyme_pipeline.bio` function 增加必填 `output_dir`，同步 execution-pipeline SDK docs、eval snippets 和相关 tests；旧无 `output_dir` 调用应更新或明确期望失败。
4. Provider registry / route policy linkage：固定三条 `bio.*.provider:v1` route policy、provider config digest、evidence ref 和 approval requirement；缺 policy/config/evidence 不兼容先 fail-closed。
5. Replace deterministic bio fallback on product path：当前 execution engine 默认 `DeterministicBioDatabaseAdapter()` 只能保留为显式 unit/eval fixture；产品路径缺真实 provider adapter 或 provider config 时返回 `provider_not_configured` / `provider_identity_missing`，不得自动 fixture success。
6. S12 approval seam：确认 provider request 只在 approved `AdapterApprovalEnvelope` 后执行，result/error 只进入 `AdapterResultEnvelope`；provider request id、response digest、registered artifacts、actual validation result 和 transcript manifest 不进入 pre-run digest。
7. Output path binding and S08 artifact boundary：Host 在 caller requested `/workspace/output/...` 写 transcript/parsed files，再通过 S08 `ArtifactBoundaryService` validation/copy/seal/register；不得继续使用 Host tempdir、provider cache 或 direct artifact save 作为 canonical provider output。
8. Provider observation and sanitizer：实现统一 `provider_request.json`、`provider_observation.json`、`provider_raw/*`、`provider_parsed/*` 和 `provider_error.json` 写入逻辑；先完成 header allowlist、body/key/path scrubber、artifact manifest 和 sanitizer regression tests。
9. NCBI provider adapter：实现 email/tool identity policy、batch cap、脱敏 transcript、FASTA/metadata convenience outputs、rate-limit header allowlist、invalid accession 粗粒度 mapping 和 diagnostic artifacts。
10. UniProt provider adapter：实现 fields allowlist、batch/cursor handling、脱敏 raw pages、optional FASTA/JSON parsed outputs、no-hit warning、HTTP 400/429/schema drift 粗粒度 mapping。
11. EBI HMMER provider adapter：实现 JSON submit、poll、result pagination、top 100000 hit cap、脱敏 job/page transcript、parsed hits output、job failure 粗粒度 mapping 和 polling/pagination observation；adapter 行为必须复用第 1 步的 current probe 结论。
12. Focused verification and readiness review：覆盖 route policy、approval reuse、`output_dir` guard、fixture forbidden、coarse error mapping、sanitized transcript exposure、artifactization、scrubber、cache-not-proof、SDK docs/examples、HMMER re-probe gate 和 “S13 passed 不等于 S15 live E2E passed” 的文档边界。

## 明确不做什么

- 不让 sandbox 直接访问 NCBI、UniProt 或 EBI HMMER。
- 不把 provider credential、API token、private endpoint、Host cache path 或 raw secret 写入 public projection。
- 不把未脱敏的完整 provider response 写入 SDK result、workspace projection、artifact 或 sandbox output；非敏感完整 transcript 只能在 sanitization 后暴露。
- 不实现 S14 的真实 local/HPC runner stage/run/fetch、toolchain registry 或 `bio_tools.*` backend。
- 不把 provider cache hit、Session 06 historical evidence、fixture success 或 synthetic artifact 当成 S13 passed / S15 live cutover proof。
