# Deferred: transactional provider batch-attempt evidence and recovery

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 AOX/HMM 工作树已经把一次 `bio.uniprot_fetch` 逻辑 operation 内的 accession 查询拆成
确定性的内部 batch：每个 query batch 最多 100 个 accession，batch 内继续跟随 UniProt
pagination，全部 batch 完成后才执行全局 identity/release closure。这个局部修复避免了单个超长
GET URL，也不要求 agent 手工创建数百个 controlled operation。

它没有实现 durable page/batch transaction。当前 adapter 仍在一个同步 Host handler 内依次发起
HTTP request，并把成功 page、response 与 safe request summary 暂存在进程内列表。只有整个
adapter 返回后，Host 才能生成 provider observation、raw-response artifact、parsed artifacts 和
terminal controlled-operation result。如果第 378 个 query batch、某个后续 page、全局 identity
validator 或 artifact registration 失败，先前已发生的 provider request 与成功 response 没有
逐 attempt/page durable checkpoint，可恢复执行也没有一个权威 high-watermark 告诉 Host 从何处
继续。

r15 并未实际进入这个 late-UniProt-failure 分支；它在 UniProt controlled operation 创建前因
control-socket framing 失败。因此本提案中的 failure anatomy 来自当前代码审计和确定性故障模型，
不是把 r15 追溯描述成已经观察到的 UniProt batch 故障。

当前 Goal 继续使用现有 one-operation/in-memory execution，并以 fresh live E2E 验证它是否足以完成
本轮 cutover。本文只记录未来跨 provider adapter、controlled-operation repository、artifact
boundary、recovery scheduler 与 evidence verifier 的大架构调整；不修改当前 schema，也不允许把
proposal 当作当前 bundle 已拥有的证明。

## Current code facts and failure mode

当前一个SDK调用创建一个approved controlled operation；query batch由规范化accession顺序和固定cap
确定，pagination cursor来自provider `Link`。adapter把`pages`、`page_responses`和`requests`累积在
内存中，`_http_request()`的中间失败retry不形成独立record；只有所有batch/page和全局identity validation
成功后，才构建provider observation、`provider_raw_http_response_set@1`、FASTA/metadata drafts并登记
artifact。completed operation可按exact idempotency复用，但failed operation没有page-level resume。

因此late batch failure会只留下operation failure；先前真实request、失败retry和成功response不能从
canonical state完整重建。Host若在send与receipt commit之间退出，恢复器也无法区分`not_sent`、
`sent_no_response`和`response_received_not_committed`。从batch 1盲重跑会重复effect，猜offset又可能漏页
或跨UniProt release拼接；把partial batch当成功则绕过exact accession closure。private log或memory dump
不能补足这些authority缺口。

## Agent-harness principles

- agent 决定 query、科学分支、是否发起一个 materially changed retry、是否早停和如何解释结果；
  harness 只管理已批准 operation 内真实 request 的身份、effect、证据与恢复。
- internal batching 是 provider transport mechanics，不应迫使 agent 为 37,722 个 accession 编写或
  批准 378 个重复步骤。
- harness 必须忠实呈现所有已经发生的 provider attempt，包括失败、rate limit、empty、unknown 与
  recovered；不能只投影最终成功的那一次。
- checkpoint 证明“这些 exact bytes 已安全持久化并通过 page-local validation”，不是“整个科学
  operation 已成功”。只有全局 requested-set、identity、release 和 artifact closure 通过后，
  controlled operation 才能 completed。
- missing/extra/duplicate page、cursor drift、release drift、response mutation 或 unknown outcome 均
  fail closed；不得通过缩小 accession 集合、跳过 batch 或切换 provider 生成看似成功的结果。
- 恢复必须复用 exact original operation/config/source/approval identity。改变 query、batch cap、
  fields、identity policy 或 provider release tolerance 都是新 operation，而不是 resume。
- public projection 只提供 agent 可行动的 safe facts；private URL、cursor、headers、credential、
  Host path 和原始受限 bytes 不进入 prompt、event、workspace 或 report。

## Target invariants

1. 首次I/O前持久化operation/execution identity和versioned policy；每个batch/page/retry在I/O前写intent，
   终态只能是`completed | failed | outcome_unknown`。
2. page identity绑定approved input、稳定ordering、query window、cursor predecessor、fields、provider config
   与schema；caller不能提交裸resume offset。
3. response完成bounded ingest、digest/size验证和immutable commit后，checkpoint high-watermark才可用SQLite
   CAS/fencing单调推进。
4. resume不重发committed page；unknown先reconcile，无安全重发证明时禁止replay。
5. 全局result要求同一operation/release、exact requested coverage与唯一validated fragments；partial/failed/
   recovered facts全部保留但不能满足下游identity prerequisite。
6. terminal result、attempt transcript、response artifacts和parsed outputs由一个closure digest绑定；task业务
   终态仍只由agent显式写入。

## Proposed ownership and topology

```text
approved ControlledOperation
  |
  | create execution before provider I/O
  v
ProviderBatchExecution repository (single-process SQLite authority)
  |-- deterministic batch/page planner
  |-- attempt intent + lease/fencing
  |-- immutable response ingress refs
  |-- monotonic checkpoint CAS
  `-- exact resume/reconcile state
          |
          v
provider adapter plugin
  |-- build request from typed batch/page identity
  |-- perform one bounded HTTP attempt
  `-- parse page-local schema from sealed response handle
          |
          v
global provider result reducer
  |-- exact requested-set coverage
  |-- release/schema/identity consistency
  `-- parsed artifact transaction + terminal operation result
```

`ProviderBatchExecution` 是既有 controlled operation 的 execution detail，不是第二套 task board、
workflow graph 或 approval system。近期实现继续由可信 Host 单进程和 file-backed SQLite 拥有；
不引入 Redis、Celery、Kafka 或跨进程 SQLite writer。

## Proposed typed schemas

### `provider_batch_execution@1`

```text
ProviderBatchExecution@1
  execution_id / operation_id / operation_digest
  session_id / task_id / lane_id / sandbox_run_id
  provider / sdk_method / route_policy_id / provider_config_digest
  approved_request_set_digest / field_set_digest
  planner_contract_id / planner_digest
  batch/page caps / expected batch/accession counts
  state = planned | running | waiting_retry | reconcile_required
          | reducing | artifactizing | completed | failed | outcome_unknown
  committed_batch_count / committed_page_count
  checkpoint_generation / state_version
  terminal_transcript_root_digest / terminal_result_envelope_digest
  claim_owner / claim_expires_at / fencing_token
  created_at / started_at / terminal_at
```

`approved_request_set_digest` 绑定完整、按 contract 排序的 accession 集合，但 public projection只暴露
digest 与 count。完整 accession list属于 approved operation payload或受限 evidence，不复制到每个
attempt row。

### `provider_request_attempt@1`

```text
ProviderRequestAttempt@1
  attempt_id / execution_id / operation_id
  batch_ordinal / page_ordinal / retry_ordinal
  predecessor_checkpoint_digest / request_identity_digest
  safe_endpoint_id / method / idempotency_class
  private_request_ref / private_cursor_ref
  request headers/body digest / request_size
  state = intent_committed | dispatching | response_ingesting
          | completed | failed | outcome_unknown | superseded_by_reconcile
  dispatch_generation / fencing_token
  started_at / headers_at / terminal_at / elapsed_ms
  status_code / safe_header_projection
  response_blob_id / response_digest / response_size
  response_completeness / error_classification_id / safe_failure_code
  retry_decision_id / next_attempt_not_before
```

`private_request_ref` 可以包含完整 URL/cursor或 provider request handle，但只能由 Host private store读取。
public receipt只含 `safe_endpoint_id`、method、opaque attempt id、request digest、status、duration、
response digest/size和 closed failure code。

### `provider_page_checkpoint@1`

```text
ProviderPageCheckpoint@1
  checkpoint_id / execution_id / generation
  batch_ordinal / page_ordinal / request_attempt_id
  query_window_start / query_window_count / query_window_digest
  predecessor_checkpoint_digest
  response_blob_id / response_digest / response_size
  page_schema_contract_id / page_validation_digest
  normalized_fragment_artifact_id / normalized_fragment_digest
  observed record count / identity-set digest / provider release identity
  next_cursor_digest / private_next_cursor_ref
  page_terminal = has_next | batch_complete
  checkpoint_digest / committed_at
```

checkpoint 必须 immutable。全局 high-watermark row 只指向最新 checkpoint，并用 expected generation 和
fencing token做 CAS；不得原位修改历史 checkpoint。

### `provider_operation_closure@1`

```text
ProviderOperationClosure@1
  execution_id / operation_id / operation_digest
  ordered checkpoint/attempt digests
  requested/resolved/duplicate identity-set digests
  release identity / raw-response / normalized-fragment root digests
  output artifact-set digest
  closure_status = completed | failed | outcome_unknown
  failure_code / verifier_contract_id / closure_digest
```

只有 `closure_status=completed` 且 verifier 重算所有 exact-set invariants 成功，才允许既有
controlled operation进入 `COMPLETED`。

## Execution and checkpoint protocol

1. admission验证approved operation、snapshot、config、caps与resource estimate，并在网络前写execution。
2. planner从canonical requested set生成batch identity；cursor只能来自sealed predecessor response。
3. Host claim exact next page并持久化attempt intent/fencing后才dispatch；response以bounded stream封存。
4. sealed response通过page-local schema/release/identity/cursor validation后生成normalized fragment，再由同一
   repository transaction写checkpoint并CAS推进high-watermark。
5. retry创建新attempt并保留旧failure；restart从checkpoint恢复，unknown先reconcile。
6. 所有batch terminal后，从checkpoint refs执行全局exact-set/release closure并transactionally发布parsed、
   raw-manifest和provider observation；先commitclosure/result handle，再唤醒sandbox/agent。

## Failure, recovery and replay rules

intent commit前的validation/quota/storage failure证明provider call count为零且不得补“空page”。完整
response已封存但parse失败时保留blob和failed receipt；response commit后、checkpoint前crash可从同一blob
幂等完成checkpoint；checkpoint后crash则从下一page恢复，旧worker被fence。

send开始但无完整receipt时必须`outcome_unknown`：优先用provider request/job/idempotency handle只读
reconcile；只有policy证明read-only exact request可安全重发时才创建新attempt，并保留unknown历史；
non-idempotent且不可reconcile时保持unknown。resume遇到release/cursor drift默认fail closed。terminal
artifactization失败只允许重做纯本地reduction，不重新请求provider来掩盖storage failure。

## Authority and security

- controlled-operation service拥有 approved intent、operation digest与business-facing status；它不解析
  provider body，也不替agent选择query。
- provider execution repository拥有 attempt/checkpoint state、lease/fencing和resume high-watermark；
  只能由可信Host写。
- provider adapter plugin从typed request capability执行一个attempt；它不能自行跳过batch、改变fields、
  选择fallback provider或宣告task完成。
- artifact boundary拥有response/fragment bytes ingress、digest、size、immutability和license policy；
  checkpoint只能引用已committed handle。
- reducer拥有exact-set/release/identity closure，不拥有网络或approval authority。
- public projection/verifier只读closed receipt。credential、Authorization、email identity、完整URL/query、
  cursor、private request handle、Host path和raw restricted bytes均被schema闭集排除。
- opaque ID仍需session/operation scope校验；知道ID不授予跨session读取provider evidence的authority。
- response artifact的license/publication policy与checkpoint存在性分离：可恢复并不意味着raw bytes可公开。

Stable failures至少覆盖admission/plan drift、attempt unknown、response incomplete、page schema、checkpoint
conflict/fenced、cursor/release drift、identity closure、artifact commit和reconcile required。public detail只含
safe IDs、ordinal/count/digest/status/timing，不含query、cursor、URL、raw header/body或path。

## Compatibility and migration

1. 冻结`provider_raw_http_response_set@1`和one-shot历史语义，不补造checkpoint。
2. 在单进程SQLite additive增加execution/attempt/checkpoint/closure表与versioned route，先shadow比较但不
   进入GO evidence。
3. 先迁read-only小型UniProt canary，再接streaming ingress、retry/outcome-unknown和large-operation canary；
   legacy/@2不得在同一operation失败后切换。
4. 发布closure verifier/public projection；@1不升级解释@2保证。确认无外部caller后退役legacy writer，
   保留历史reader和所有failure/ledger records。

rollback只能让新operation选择legacy route。已经创建的@2 execution继续按@2恢复或明确终止；不能在
原operation内把checkpoint丢弃后从头走legacy并择优采用成功。

## Test strategy and acceptance criteria

Digest/schema tests覆盖window/cursor/config/release drift、missing/extra/duplicate page、cross-operation ref与private
projection；CAS在duplicate worker/stale fencing下只能有一个winner，partial/path-only response不能checkpoint。
故障注入覆盖request前、response commit后、checkpoint前后、429/503/success、unknown send、release drift、
reducer/artifact failure，证明已commit page不重复、unknown不blind retry、local recovery不增加provider call。

live验收要求数百batch的真实UniProtoperation可restart resume，attempt/transcript exact closure，requested/
resolved/release/artifact/result由一个closure digest绑定；failure/unknown时下游AOX调用为零，public面无secret/
URL/cursor/path，offline verifier不查询provider或operator log。未来schema仍需两次positive E2E加一次fault；
本文不改变当前GO标准。

完成以上验收前，不得宣称“UniProt internal batching可断点恢复”或“每个provider effect已durable审计”。

## Non-goals

- 不改变AOX motif、HMM score、NCBI/UniProt identity或文献科学规则。
- 不把query batch变成agent必须逐一调度的task，也不固定agent的科学调用顺序。
- 不自动选择alternate provider、缩小accession集合、接受partial identity或把empty改写为success。
- 不以provider cache、HTTP access log、debug file或memory snapshot替代canonical attempt evidence。
- 不保证任意外部provider exactly-once；无idempotency/reconciliation能力时必须显式unknown。
- 不在本文实现通用HTTP streaming、retry policy或control-response outcome protocol；它们分别由相邻
  proposal定义，并应共享基础类型。
- 不引入新的顶层workflow engine、跨进程SQLite writer或分布式队列。

## Relationship to existing proposals and stable contracts

- [Harness doctrine](../00-harness-doctrine.md) 要求harness负责真实世界约束和可恢复状态，而agent保留
  判断；本文把该原则落实到provider内部batch，不替agent编排科学workflow。
- [Capability engines](../03-capability-engines.md) 已要求engine invocation、provider limiter、canonical
  evidence和explicit failure；本文增加的是execution子级attempt/checkpoint，不改变engine ownership。
- [Unified provider evidence broker](unified-provider-evidence-broker.md) 负责跨direct/deep/execution调用面的
  provider envelope与mechanics；未来broker可承载本文SPI，但不能夺走controlled-operation owner。
- [Durable async controlled operation and quiescent sealing](durable-async-controlled-operation-and-quiescent-sealing.md)
  负责长时operation handle、poll/continuation与quiescence；本文负责一个provider operation内部的
  request/page/batch evidence和resume high-watermark。
- [Transactional attempt-evidence collection](transactional-attempt-evidence-collection-and-root-closure.md)
  负责campaign archive的prepare/commit与root closure；它只能收集本文已经durable的provider closure，
  不能从partial files补造attempt history。
- [Canonical scientific chain adoption](canonical-scientific-chain-adoption-and-attempt-closure.md) 负责跨run
  adopted/superseded科学链；本文只描述单一approved provider operation内部的transport attempts。
- [Verified artifact materialization handoff](verified-artifact-materialization-handoff.md) 保护provider input
  bytes到consumer；本文保护provider output response与batch progress。两者digest/authority不可互相替代。

后续实施必须先协调上述proposal的共同operation、lease、fencing、artifact-handle和public-envelope类型，
不能各自生成四套不兼容的“真状态”。
