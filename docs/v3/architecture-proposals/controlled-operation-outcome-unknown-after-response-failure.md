# Deferred: controlled-operation outcome unknown after response failure

Status: implemented for `durable_async_v1` controlled operations by
`runtime-hpc-reliability-refactor`; generic non-controlled side-effect RPCs remain deferred.

Stable contract: [`../07-runtime-hpc-reliability.md`](../07-runtime-hpc-reliability.md).
The decision-boundary and current-facts sections below are the pre-refactor baseline and
must not override current code or OpenSpec checkpoints.

重构收敛说明：本文只拥有 effect-versus-delivery protocol 与 reconciliation 语义，不拥有第二个 external-operation scheduler。admission、result、delivery、reconciliation records 必须附着于整合路线定义的唯一 canonical `ControlledOperationExecution`：
[`runtime-hpc-reliability-refactor-roadmap.md`](runtime-hpc-reliability-refactor-roadmap.md)。

## Decision boundary for the current Goal

当前sandbox control socket采用“一条Unix连接、一个JSON-RPC 2.0 NDJSON request、一个response”的同步
协议，request/response frame上限均为4 MiB。Host先执行`_handle()`，再由`_encode_response()`序列化和
检查response大小。若handler已完成controlled operation、登记artifact或写入SQLite，但response无法
JSON序列化、超过4 MiB，或`sendall()`时client断开，effect与delivery会分叉：Host真状态可能已提交，
sandbox SDK却只看到transport error或没有response。

当前exact idempotency key和operation digest已有重要保护：重复同一request可查询已存在operation，digest
漂移会拒绝，完整completed adapter result也可能复用。但wire没有显式stable result handle、
`outcome_unknown`或只读reconcile command；`sandbox_transport_response_invalid/too_large/unavailable`也不能
告诉caller handler是否已经committed。把普通transport error再次调用仍容易被agent或compat client误解为
“原操作没有发生”。

本Goal保留4 MiB cap并要求result bounded；它不实施新的submit/result/reconcile协议，不追溯改变历史
operation语义。本文只记录大架构调整，不能用作当前AOX/HMM bundle的outcome proof。

## Current facts and failure modes

当前顺序可概括为：

```text
client send request
  -> Host validate/idempotency lookup
  -> handler/adapter executes
  -> artifacts + controlled-operation result may commit
  -> build JSON-RPC response
  -> serialize and enforce 4 MiB cap
  -> send response
  -> client parse response
```

关键歧义：

- **serialization after commit**：非JSON值或encoder异常使Host用
  `sandbox_transport_response_invalid`替换原result，已提交effect不回滚。
- **frame cap after commit**：过大result被替换成`response_too_large`；cap正确保护transport，却没有提供
  已提交result的opaque handle。
- **disconnect after commit**：Host发送失败只退休当前connection；client不知道result是否已durable。
- **client parse failure**：truncation、wrong id或invalid shape发生时，server-side effect仍可能成立。
- **generic partial side effect**：`register_many`等多项handler若逐项commit，晚response failure不证明all-or-
  nothing。本文重点是controlled operation，未来generic side-effect RPC也应采用同一原则。
- **blind replay**：对read-only call或已有Host idempotency的operation，reconcile可能安全；对外部submit、
  非幂等provider或artifact writer，盲重发可能重复effect。

4 MiB上限本身不是缺陷；缺陷是“effect outcome”和“response delivery outcome”没有成为两个typed、durable
维度。exactly-once network effect也不能仅靠本地idempotency key保证。

## Agent-harness principles

- agent发出一个科学action后，harness必须准确区分`failed_before_effect`、`committed`与
  `outcome_unknown`；不能把delivery failure伪装成确定未执行。
- agent可决定在reconcile结果后如何继续，但不应通过猜测、raw SQLite或重复tool call来探测世界。
- response cap、result artifactization、idempotency与reconcile属于harness约束，不改变agent的科学计划。
- unknown禁止自动改写成retryable。只有method policy证明read-only/idempotent或provider支持reconcile时，
  Host才可采取受控恢复。
- task业务终态不由transport状态推导；committed operation也不自动完成task。
- public error只给safe handle、closed state和下一步；不泄露private result locator、path、credential、
  fencing或raw payload。

## Target invariants

1. side-effecting request在handler I/O前持久化canonical admission record、request digest和stable opaque
   handle；client即使未收到ack，也可用exact idempotency identity查询。
2. handler effect state与wire delivery state分开持久化，不能用一个`error`字段覆盖。
3. terminal result先以bounded envelope或immutable artifact/result document持久化，再把operation标为
   committed；wire只返回小handle、digest和safe summary。
4. response serialization/cap/send/client-ack failure不回滚已提交effect，也不把它改成ordinary failed。
5. caller遇到delivery ambiguity只能执行只读`resolve/reconcile`，不得重跑handler。
6. Host只有在证明pre-effect failure时才能返回`failed_before_effect`；send begun/no receipt默认unknown。
7. outcome unknown时，provider-specific idempotency/reconcile优先；不能证明时保持unknown并阻止blind retry。
8. duplicate submit以session、request digest、idempotency key和method scope做CAS，只产生一个canonical
   admission/dispatch generation。
9. public result永远bounded；大result通过artifact/result handle获取，不能绕过4 MiB cap。
10. restart、duplicate drain、stale worker和client reconnect均遵守lease/fencing，不能重复commit或投递旧
    generation。

## Target protocol and topology

```text
SDK submit(request, idempotency_key)
  -> persist ControlRequestAdmission before effect
  <- small accepted handle (or client resolves by key if ack lost)

Host dispatcher
  -> claim + fence
  -> execute/reconcile exact handler effect
  -> persist result artifact/envelope
  -> commit effect outcome

SDK await/resolve(handle)
  -> read durable outcome only; never execute handler
  <- pending | committed(result handle) | failed_before_effect
     | failed_after_known_effect | outcome_unknown | reconcile_required
```

SDK可以继续提供同步外观：内部执行`submit + await_result`。这个外观不能再由一个长连接承载全部effect和
唯一result delivery；显式async form只是额外表达能力，不强迫agent改变pipeline source。

若第一次accepted ack在网络中丢失，client用原session-scoped idempotency key/request digest调用
`control.resolve_by_identity`。该命令只能查canonical admission，绝不“没有就顺便执行”。没有record时返回
`not_admitted`；是否fresh submit由caller/agent另行决定。

## Proposed typed schemas

### `control_request_admission@1`

```text
ControlRequestAdmission@1
  request_handle / session_id / sandbox_run_id / workspace_id
  method / idempotency_key_digest / request_digest
  controlled_operation_id / operation_digest
  policy_id / idempotency_class
  state:
    admitted | dispatch_ready | dispatching | result_staging
    committed | failed_before_effect | failed_after_known_effect
    outcome_unknown | reconcile_required | cancelled
  effect_boundary_state / state_version
  claim_owner / claim_expires_at / fencing_token
  created_at / terminal_at
```

raw idempotency key和request payload保持在原approved owner/private store；public projection只含opaque handle、
digests和closed states。

### `controlled_operation_result_handle@1`

```text
ControlledOperationResultHandle@1
  result_handle / request_handle / operation_id
  terminal_effect_state
  result_envelope_artifact_id / result_digest / result_size
  output_artifact_ids / output_artifact_set_digest
  bounded_summary / safe_failure
  result_schema_id / producer_identity
  committed_at / result_commit_digest
```

`bounded_summary`本身有严格serialized-byte cap；完整provider transcript、large validation results和output
manifest通过artifact/document refs读取。

### `control_response_delivery@1`

```text
ControlResponseDelivery@1
  delivery_id / request_handle / result_handle
  connection_generation / response_frame_digest / response_size
  state = prepared | send_started | sent | acknowledged | failed | unknown
  failure_code / created_at / terminal_at
```

delivery receipt只描述transport，不改变effect state。Unix socket通常无法证明application-level client已处理
result，因此`sent`与`acknowledged`分开；不需要强求每个sync caller ack才认为operation committed。

### `controlled_operation_reconciliation@1`

```text
ControlledOperationReconciliation@1
  reconciliation_id / request_handle / operation_id
  reason / strategy_id
  provider_idempotency_ref_digest / private_provider_ref
  observed_effect_state
  recovered_result_handle
  outcome = committed | not_effected | still_unknown | recovery_failed
  evidence_artifact_ids / evidence_root_digest
  reconciled_at / receipt_digest
```

provider ref、remote job id、private endpoint和credential不进入public schema。

## Effect and delivery lifecycle

1. **Preflight/admission**：closed-validate request、operation digest、approval、call budget和result contract；
   SQLite commit admission成功后才允许任何不可逆I/O。
2. **Small ack**：优先返回request handle。ack丢失时client以exact identity只读resolve，不重新submit。
3. **Dispatch**：Host claim/fence admission，写effect boundary marker，再调用adapter。对外部submit，在provider
   支持时携带pinned idempotency key。
4. **Effect receipt**：artifact/provider/job result先进入immutable evidence；无法证明dispatch outcome时写
   `outcome_unknown`，不猜failed。
5. **Result commit**：构建closed bounded result handle，绑定operation/output artifacts/evidence。result
   artifact和SQLite terminal CAS成功后effect state=`committed`。
6. **Delivery**：serialize固定小response `{request_handle,result_handle,state,digest,summary}`。编码/size/
   send failure只终结delivery row。
7. **Client resolution**：SDK在transport异常后自动执行一次bounded只读resolve；若Host unreachable，向agent
   返回`controlled_operation_outcome_unknown`和handle，不自动重发effect。
8. **Reconcile**：Host恢复器按policy查询existing operation/provider job/artifact commit；每次reconcile有
   evidence receipt。仍无法证明时保持unknown。
9. **Consume**：sandbox只在result digest和operation identity匹配时消费result；重复delivery幂等，旧
   generation/fencing拒绝。

## Failure and recovery

- **admission前失败**：明确`failed_before_effect`，provider/runner/artifact call count为零，可fresh submit。
- **admitted未dispatch crash**：restart用fresh fencing执行同一request一次；duplicate worker不能dispatch。
- **dispatch begin后无receipt**：`outcome_unknown`。non-idempotent route禁止resubmit，先provider reconcile。
- **effect完成、result staging失败**：保留effect evidence，状态`failed_after_known_effect`或unknown；不能把
  operation标成未发生。可纯本地重建result时不重做effect。
- **result committed、response encode/too-large失败**：operation保持committed；client resolve得到小result
  handle。large original result应已artifactized，不能再次尝试内联。
- **send成功但client parse/ack失败**：重复resolve返回同一result digest，不执行handler。
- **Host restart**：扫描非终态admission并按effect boundary/reconcile policy恢复；stale fencing全部拒绝。
- **result artifact损坏/缺失**：committed result verification失败并撤销可消费资格，保留operation effect fact；
  不重新执行外部effect来“修复”证据。
- **client永不回来**：result仍是canonical state，retention/GC遵循artifact policy，不由socket生命周期决定。

建议stable errors：

- `controlled_operation_not_admitted`
- `controlled_operation_result_pending`
- `controlled_operation_outcome_unknown`
- `controlled_operation_reconcile_required`
- `controlled_operation_result_commit_failed`
- `controlled_operation_result_unavailable`
- `control_response_delivery_failed`
- `control_request_identity_drift`
- `control_request_fenced`

`outcome_unknown`固定`retryable=false`并带`recovery_action=reconcile`；这不表示永远失败，而是禁止把
re-execution当普通retry。

## Authority and security

- control server拥有admission、idempotency lookup、delivery records和small wire schema；不拥有provider
  科学parser或task terminal。
- controlled-operation service拥有approval continuity、operation digest/status和result binding。
- adapter/engine拥有实际effect和provider-specificreconcile，但不能创建第二operation owner或修改approved
  request。
- artifact boundary拥有large result bytes和immutable result/evidence artifacts；control socket只持opaque refs。
- scheduler/recovery使用单进程SQLite lease/fencing；近期不引入分布式queue或跨进程writer。
- request/result handle必须高熵、session/sandbox/operation scoped、不可由artifact digest推导；知道handle不
  授予跨session读取。
- public error/event/workspace只投影safe handle、state、digest、artifact IDs和closed failure；private path、
  provider handle、cursor、credential、raw request/result、lease/fencing全部排除。
- reconcile endpoint只读canonical state或使用Host credential查询exact provider identity；agent/caller不能传
  任意provider locator。

## Compatibility and migration

1. 明确记录当前S10/S12同步one-response协议的scope；4 MiB cap保持，不宣称它有outcome-unknown恢复。
2. additive增加admission/result/delivery/reconcile tables和closed schemas；历史operation不补造delivery ack。
3. 先让当前completed-operation idempotency lookup生成non-authoritative shadow result handle，验证重复call不
   执行adapter。
4. 为side-effecting controlled operations发布versioned `submit/resolve@2`；SDK内部保持同步wrapper。旧client
   遇到required-v2 route显式unsupported，不能回退v1执行。
5. 把provider/HPC/large artifact result逐项迁为bounded result handle；wire response serialized-size在commit前
   preflight。
6. 接入provider idempotency/reconcile与durable async scheduler；没有reconcile能力的route保持unknown-safe。
7. UI/events/verifier读取effect/delivery双状态；不把delivery failed显示为operation failed。
8. 外部调用方审计后退役side-effecting v1 writer；保留历史reader。rollback只影响fresh operation route，
   不把已有@2 admission重新走v1。

## Test strategy and acceptance criteria

- 在handler前、external send后、artifact commit后、operation save后、response encode、4 MiB cap、sendall、
  client parse/ack各barrier注入failure；每种case都得到唯一effect/delivery状态。
- handler counter证明result committed后的resolve/reconnect/duplicate drain不增加effect call count。
- nonserializable或>4 MiB handler result被artifactized并返回同一small handle；不能用ordinary error隐藏committed
  operation。
- side-effecting sent/no-response进入unknown/reconcile，automatic resubmit count为零。
- exact idempotency key + different request/operation digest始终`identity_drift`，不能复用旧authority。
- crash/restart、duplicate worker、stale lease/fencing只产生一个canonical dispatch/result commit。
- public projection对credential、provider locator、raw payload、Host path和fencing corpus零泄漏。
- offline verifier能从admission、operation、result/effect artifact和delivery receipts区分“effect committed但
  response failed”与“effect前失败”。
- 真实provider/HPC canary在断开client后通过resolve取得原result，不重复submit；无法reconcile的fault保持
  explicit NO-GO/unknown。

完成验收前，不得声称controlled operation具备exactly-once delivery、outcome-unknown reconciliation或large
result handle协议。

## Non-goals

- 不取消4 MiB cap或通过提高cap掩盖large result设计问题。
- 不承诺任意外部系统exactly-once；目标是at-most-one local dispatch、可验证idempotency/reconcile和诚实
  unknown。
- 不让agent直接读SQLite、private provider handle或Host path来恢复。
- 不自动重试unknown effect、不fallback alternate provider/runner、不修改科学参数。
- 不把operation committed推导成task/report/campaign completed。
- 不在本文实现provider batch checkpoint、HTTP retry policy、streaming Blob或campaign archive transaction。

## Relationship to existing proposals and stable contracts

- [Harness doctrine](../00-harness-doctrine.md) 要求harness忠实呈现世界；effect/delivery分离防止agent基于
  错误“未发生”事实决策。
- [Sandbox external capability bridge](../sessions/10-sandbox-external-capability-bridge.md) 定义当前supervised
  SDK/approval boundary；本文是未来versioned protocol，不改变当前合同。
- [Durable async controlled operation and quiescent sealing](durable-async-controlled-operation-and-quiescent-sealing.md)
  定义submit/poll/continuation和long-operation state；本文聚焦terminal result与wire delivery歧义，应复用
  其handle、lease/fencing而非新建队列。
- [Transactional provider batch evidence](transactional-provider-batch-attempt-evidence.md) 解决operation内部
  page effects；其terminal closure必须先commit，再由本文result handle交付。
- [Provider retry policy](provider-retry-policy-and-failed-attempt-evidence.md) 解决provider HTTP attempt retry；
  provider-attempt unknown与control-delivery unknown是两个因果相连但不可混同的层级。
- [Streaming provider response and artifact persistence](streaming-provider-response-and-artifact-persistence.md)
  提供large result artifactization与atomic Blob commit；本文只传bounded handle。
- [Transactional attempt evidence](transactional-attempt-evidence-collection-and-root-closure.md) 收集最终archive；
  collector不能因response delivery失败而重跑effect，也不能把unknown补成failed。

未来实施必须统一operation/result handle和outcome taxonomy，同时保留provider attempt、handler effect、wire
delivery三个独立维度。
