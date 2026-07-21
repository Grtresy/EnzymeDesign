# Deferred: versioned provider retry policy and failed-attempt evidence

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前bio HTTP adapter有一个局部、同步的retry loop：默认`max_retries=2`，退避序列为`1s, 2s`；
HTTP 429/500/502/503/504、timeout、URL/connection failure可以在adapter内部重试。最终失败会返回
structured `PipelineSdkFailure`，safe header allowlist已经包含`retry-after`，但retry loop本身不解析或
服从`Retry-After`，没有jitter，也不为每次中间失败建立durable attempt receipt。

当前Goal可以通过真实live测试发现provider当时是否可用，但不能在不改变provider runtime、repository、
limiter、approval resource budget、artifact ingress与recovery lifecycle的情况下，把上述loop描述成完整
retry governance。本提案只定义未来统一policy/evidence architecture；不修改当前`BioProviderHttpConfig`、
不为历史调用补造failed attempts，也不改变本轮AOX/HMM GO标准。

本文专注“已知HTTP/provider attempt的分类、等待、预算与证据”。长时remote job的durable poll lifecycle、
operation内部batch checkpoint、control response交付歧义分别属于相邻proposal，不能用本文一个retry loop
代替。

## Real r25 evidence: inactive is not retryable schema drift

r25 的 UniProt 大集合按默认 cap 形成 `378` 个 batch；完整列表第 `102` 项、位于第二个 batch 的
accession `A0A034VJ94` 返回本次诊断首个 typed inactive/deleted identity，没有 sequence，并提供
inactive reason 与 UniParc reference。旧 adapter 将其终止为 non-retryable
`provider_schema_drift`。这个 outcome 不应通过增加 attempt、扩大 timeout 或退避后重发来解决：
response 已完整到达，问题是本地 response contract 没有表达 provider 的合法 inactive 状态。这里的
“第二个 batch”只定位 record；当前实现先累积全部 query/page 再统一 validation，不能据此声称网络
请求在第二 batch 已停止。

本 Goal 的小修边界是版本化 UniProt identity contract，把已验证的 inactive/deleted record 正规化并在
下游 length join 前显式排除；它不改变通用 retry coordinator。以下仍为 terminal failure：缺失 exact
requested identity、inactive reason 不在闭集、active record 缺 sequence、response truncation、unknown
entry type 或 requested-set closure 失败。不得把任一 malformed response 通过“可能已删除”重分类为
成功，也不得自动切换 UniParc 或另一个 provider。

未来 retry evidence 应把本例记录为“一次 completed transport attempt + validated inactive member”，
而不是 failed transport attempt；若 contract validator 自身版本不支持该状态，则 operation failure
必须绑定 validator/policy digest，不能让 automatic retry 重复同一确定性结果。r25 不会被历史重分类，
仍是永久 NO-GO，也不会为当时未持久化的中间 attempts 补造 receipts。

## Current code facts and failure modes

当前`_http_request()`的事实：

最多执行`max_retries+1`次（默认3次）。429/500/502/503/504及timeout/URL/connection/OSError按固定tuple
delay重试，其他4xx terminal；没有exponential cap或jitter。header sanitizer允许Retry-After/rate-limit/
request-id，但loop不使用Retry-After，中间failure不形成canonical transcript，只有final failure/success
可见。总attempt/elapsed/wait/download budget未绑定approved estimate，sleep也没有durable not-before。

主要failure modes：

由此可能忽略provider等待指令、形成同步retry herd、用最终success抹去429/timeout历史、让不同调用面
taxonomy漂移并逃逸approved budget。若helper用于POST/job submit，`no response`也不能证明`not accepted`；
crash会丢失backoff intent。直接持久化raw URL/header/body又会带来secret/license泄漏。

## Agent-harness principles

- agent决定科学问题、query、provider选择、是否在terminal failure后进行materially changed retry；
  harness只执行已批准logical request内明确、bounded、versioned的transport retry policy。
- automatic retry不能修改query、accession集合、fields、provider、科学阈值或output contract。任何此类
  改变都需要agent创建fresh operation。
- harness必须让每次真实attempt可审计，不能只保留最终success；failed、rate-limited、cancelled、unknown
  与recovered都是真实world facts。
- `retryable=true`表示policy允许同一intent的另一attempt，不表示一定会retry，也不表示task应继续；
  budget、deadline、approval、cancellation和outcome certainty仍可能阻止retry。
- provider给出的等待建议是输入事实，不是无限authority。Host必须closed-parse、上下界限制并将采用/
  拒绝理由写入receipt。
- 自动retry必须比agent自行盲重试更安全：无idempotency/reconciliation证明的副作用attempt进入unknown，
  不因“网络错误通常可重试”而重复。
- public evidence提供safe request/response identity和decision，不暴露credential、完整URL/query、raw header/
  body、Host path或private jitter seed。

## Target invariants

1. route绑定immutable policy/digest；approval包含max attempts/elapsed/wait/bytes和idempotency class。
2. attempt在I/O前写intent，终态为`completed | failed | outcome_unknown | cancelled`，success不能删历史。
3. versioned classifier依据method、dispatch certainty、status/exception、safe headers和completeness决策。
4. Retry-After严格解析delta/date并转monotonic deadline；effective delay记录backoff、provider minimum、
   bounded jitter、cap和not-before。
5. attempt原子消费approved budget；waiting durable且不占thread，restart用lease/fencing claim。
6. side-effect/unknown先reconcile；retry terminal不改task或自动fallback。

## Target architecture

```text
approved provider operation
  |
  v
ProviderRetryPolicyRegistry (versioned, route-bound)
  |
  v
ProviderAttemptCoordinator (Host-owned durable state)
  |-- attempt intent / budget debit
  |-- one transport dispatch through adapter plugin
  |-- response/error evidence ingress
  |-- closed classifier
  |-- Retry-After + backoff + jitter decision
  `-- durable next-attempt scheduling / reconcile
          |
          v
terminal ProviderCallResult / ControlledOperation result
```

registry是logical contract，不拥有task或provider credential。coordinator是operation execution detail，可由
未来统一provider evidence broker复用，但canonical owner仍是原`EngineInvocation`或
`ControlledOperation`。

## Proposed typed schemas

### `provider_retry_policy@1`

```text
ProviderRetryPolicy@1
  policy_id / version / policy_digest
  provider / operation / safe_endpoint_id
  methods / idempotency_class = read_only | idempotency_key_supported
                               | provider_reconcilable | non_idempotent | unknown
  attempts/elapsed/wait/single-delay/response-byte caps
  retryable/terminal HTTP and transport/schema categories
  base_delay_ms / multiplier / max_backoff_ms
  jitter_algorithm / jitter_ratio
  retry_after_mode / max_retry_after_ms
  required_reconcile_categories

  config_schema_id / created_at
```

`retry_after_mode`建议closed enum：`ignore | provider_minimum | provider_exact_bounded`。一般429/503使用
`provider_minimum`：effective delay至少为合法Retry-After，同时不超过approved cap；超cap时不提前重试，
而是terminal `retry_budget_exhausted`或等待fresh authority，不能静默clamp成更短延迟违背provider要求。

### `provider_attempt_receipt@1`

```text
ProviderAttemptReceipt@1
  attempt_id / owner_id / operation_id
  attempt_ordinal / previous_attempt_id
  policy_id / policy_digest / request_identity_digest
  safe_endpoint_id / method / idempotency_class
  private_request_ref
  state = intent_committed | dispatching | response_ingesting
          | completed | failed | outcome_unknown | cancelled
  budget_debit_id / dispatch_generation / fencing_token
  started_at / headers_at / terminal_at / elapsed_ms
  status_code / safe_headers / response_completeness
  response_artifact_id / response_digest / response_size
  transport_category / provider_error_category
  safe_failure_code / classification_id
  receipt_digest
```

失败HTTP body如license允许，封存为restricted response artifact；public receipt只含digest/size/status和closed
failure code。`body_excerpt`不作为canonical evidence requirement。

### `provider_retry_decision@1`

```text
ProviderRetryDecision@1
  decision_id / attempt_id / policy_id
  classification = retry | terminal | reconcile_required
  reason_code
  local backoff / normalized Retry-After / jitter
  effective_delay_ms
  next_attempt_not_before
  attempts/elapsed/wait/response-bytes used and remaining
  cancellation_state / approval_state
  decision_digest / decided_at
```

public form不包含raw Retry-After string或private seed；private attempt evidence可以保留sanitized original header
digest供审计。

### `provider_attempt_chain@1`

```text
ProviderAttemptChain@1
  owner_id / operation_id / request_identity_digest
  ordered attempt-receipt and retry-decision digests
  terminal_outcome
  terminal_response_artifact_id / terminal_response_digest
  total_attempts / total_elapsed_ms / total_wait_ms / total_response_bytes
  recovered_after_restart / reconcile_count
  chain_digest
```

terminal provider observation、artifact provenance与offline verifier引用chain digest，确保最终success不能
丢失中间failure。

## Classification and delay protocol

1. admission按exact route/config绑定policy并预留attempt/elapsed/wait/bytes；单attempt前CAS消费call slot。
2. 持久化request identity、idempotency class、deadline/fencing后，adapter只执行one transport attempt；
   response经bounded artifact ingress，exception归一化closed category。
3. success/failure/unknown先写receipt再classify。schema/identity通常terminal，429/selected5xx可retry，
   connection failure结合dispatch certainty，side-effecting sent/no-response需reconcile。
4. 严格解析Retry-After，计算bounded backoff+jitter/provider minimum并验证budget/deadline；persist not-before后
   释放worker，scheduler用fresh fencing claim。
5. success/terminal生成完整attempt chain并释放unused budget，绝不为用完quota多请求。

## Retry-After, backoff and jitter rules

delta-seconds只接受bounded非负整数；HTTP-date用可信UTC解析并转monotonic not-before，clock不可靠则停止。
provider minimum超过approved wait/deadline时显式budget exhaustion，不clamp成更短延迟。无header时使用
versioned full/equal jitter backoff；jitter不改变eligibility、attempt cap或deadline。rate-limit reset只有
provider-specific parser可用。HMMER poll interval属于remote job lifecycle，不并入transport retry counter。

## Authority, safety and budgets

- route policy/manifest选择retry policy并进入approved digest；agent或sandbox不能提交`max_retries=999`、
  自定义retryable status或private endpoint。
- ProviderAttemptCoordinator拥有attempt state、budget debit、schedule和lease/fencing；provider adapter只执行
  one attempt并返回typed response/error。
- retry classifier是pure/versioned logic；它不读取prompt、task描述或模型推断，也不选择fallback provider。
- limiter在attempt dispatch时消费concurrency，waiting retry不占worker/thread；budget repository与limiter
  都不能用线程池大小代替call quota。
- provider credential和完整request只在private adapter/record中；public receipt使用safe endpoint、digest、
  allowlisted header与opaque request id。
- `Retry-After`等header即使allowlisted也要长度/charset/format cap；raw value不能直接进入log/error/UI。
- failure body按license policy进入restricted artifact。公开error不依赖raw excerpt，防止provider回显secret/
  query或恶意path。
- attempt chain属于canonical operation evidence，但不拥有task terminal、report conclusion或campaign GO reducer。

## Failure and recovery

dispatch前crash可用fresh fencing执行一次且call count为零；send后无outcome则unknown，non-idempotent禁止
retry。response artifact commit后、receipt前crash复用同一response终结receipt。backoff的not-before/budget
durable且duplicate signal由CAS去重；运行中chain继续pinned policy。budget exhausted不“再试一次”；artifact
sealing failure不能回滚已发生call；cancel不伪造in-flight已停止；clock不可靠则停止而非burst retry。

Stable failure覆盖policy missing/drift、budget exhausted、Retry-After invalid/over-budget、clock unreliable、
dispatch/unknown/evidence commit/reconcile、schedule fenced和cancelled。每个failure携带closed
`retry_eligibility = eligible | terminal | reconcile_required | unknown`，不只用boolean。

## Compatibility and migration

1. 冻结legacy 1s/2s loop语义，不宣称Retry-After或intermediate evidence；先发布pure classifier/policy和
   non-authoritative shadow metrics。
2. @2 adapter只执行one attempt，coordinator调度并接durable response ingress；禁止legacy+@2双层retry。
3. 先迁NCBI/UniProt read-only canary，再迁可reconcile side-effect route，并向direct/deep/execution共享policy
   但保留各owner。
4. attempts/wait/bytes进入approval和projection，verifier闭合attempt chain；历史不补造。无caller后退役
   legacy writer，rollback只影响fresh operation。

## Test strategy and acceptance criteria

unit/property tests覆盖status/exception/method/idempotency matrix、Retry-After边界、bounded jitter/budget、chain
digest closure和secret corpus。deterministic faults覆盖429->503->200、concurrent jitter、intent/send/body/
receipt/decision/wakeup crash、duplicate fencing和POST unknown，证明not-before、不丢history、不重复submit，
首attempt success立即释放unused budget。

live验收要求真实rate limit遵守Retry-After且不人为耗额度；transient recovery保留failed receipts，budget
exhaustion不fallback，restart无需sleep thread，三种调用面共享taxonomy但保留owner，offline verifier只读
attempt chain/sealed artifacts。

完成这些验收前，不得声称“provider retry统一遵守Retry-After”“每次失败attempt可验证”或“重试预算已
纳入approval”。

## Non-goals

- 不改变agent的query、provider选择、科学策略、task completion或GO reducer。
- 不通过提高max attempts、缩短Retry-After或扩大MICU/network额度来制造成功。
- 不把schema/identity/invalid-request错误自动分类为transient，也不fallback synthetic/fixture结果。
- 不承诺所有HTTP method都可安全retry；无idempotency/reconcile证明时明确unknown/terminal。
- 不把remote job polling、batch pagination或control response delivery都压进一个generic retry counter。
- 不要求保留任意rawsecret-bearing header/body到public evidence；完整private evidence仍受license/retention。
- 不引入分布式scheduler；近期在单进程SQLite上用durable not-before、lease/fencing实现。

## Relationship to existing proposals and stable contracts

- [Harness doctrine](../00-harness-doctrine.md) 要求harness忠实呈现真实failure，不替agent选fallback；本文把
  retryability拆成world policy和agent科学decision。
- [Capability engines](../03-capability-engines.md) 已规定LLM调用由统一runtime处理Retry-After；本文为非LLM
  research/execution HTTP provider定义等价但独立的typed policy，不能误用LLM token retry状态。
- [Unified provider evidence broker](unified-provider-evidence-broker.md) 适合托管共享classifier/attempt envelope；
  本文细化retry policy与failed-attempt chain，canonical owner仍由各调用面保留。
- [Transactional provider batch evidence](transactional-provider-batch-attempt-evidence.md) 使用本文的attempt/
  decision作为每个page的transport历史；batch checkpoint不应只记录最终success。
- [Streaming provider response and artifact persistence](streaming-provider-response-and-artifact-persistence.md)
  为每次attempt提供bounded immutable response evidence；本文不自己实现Blob writer。
- [Durable async controlled operation](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/durable-async-controlled-operation-and-quiescent-sealing.md) 提供nonblocking
  wait、lease/fencing和long operation recovery；本文的`next_attempt_not_before`应复用该scheduler primitive，
  不创建第二套后台队列。
- [Controlled-operation outcome unknown](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/controlled-operation-outcome-unknown-after-response-failure.md) 处理Host
  handler已effect但SDK未收到结果的delivery ambiguity；本文处理provider HTTP attempt本身的dispatch/
  response ambiguity。两个unknown必须分别建模并可因果关联。

未来实现应抽取共享`AttemptOutcome`、`RetryDecision`、budget和safe receipt类型，但不得用一个模糊
`retryable: bool`抹平provider method、dispatch certainty、approval和agent strategy的差异。
