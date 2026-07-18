# Deferred: canonical research evidence adoption and complete invocation history

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 AOX/HMM Goal 可以继续做有边界的小修：允许 researcher 自由迭代多个 PubMed query，随后仅以
canonical `task.finish.evidence_refs` 选择一个 source-bearing PubMed aggregate 作为当前 `@1`
required-literature primary；collector 和 verifier 对该 artifact、invocation、task 与 nullable lane 做
严格相等校验。没有 lane 的 research task 只允许同一条 lineage 上全部为 `None`，不能把 `None`
字符串化成空字符串后制造“已绑定 lane”的假象。选择零个或多个 PubMed aggregate 都 fail closed。

这个小修只回答“当前 `@1` bundle 采用哪个 PubMed aggregate”，不会把同一 task 内其余真实
invocation 封入一个可离线证明完整的历史，也不会为 failed、empty、exploratory 或 superseded
调用建立 canonical disposition。它仍依赖当前 `task_finish` document 的 evidence refs，不能证明
collector 没有漏掉同一 scope 内另一条 invocation。

以下调整会新增顶层 authority、append-only selection/disposition、SQLite schema、public projection、
archive manifest、bundle `@2` 和 verifier `@2`，并改变 `task.finish` / report publish 的写入前置条件，
属于大架构调整。本 Goal **只记录本提案，不实现**：

- 不新增 `ResearchInvocationUniverse`、`ResearchEvidenceSelection` 或 disposition 表；
- 不改变现有 provider tool、`EngineInvocation`、artifact、source-ref 或 task state machine；
- 不把历史 attempt 按新 schema 回填、升级或重新判为 eligible；
- 不把现有 `task.finish` 自由文本、报告里的“primary”字样或 artifact 顺序解释为历史 adoption；
- 不宣称当前 `@1` bundle 已封存全部 research invocation 或能够证明其完整性。

本提案对照：

- [V3 Harness Doctrine](../00-harness-doctrine.md)；
- [V3 Control Plane](../02-control-plane.md)；
- [Capability Engines](../03-capability-engines.md)；
- [Public Interfaces](../04-public-interfaces.md)；
- [AOX/HMM blank-world cutover](../aox-hmm-blank-world-cutover.md)；
- [AOX/HMM live workflow contract](../execution-pipeline-docs/aox-hmm-live.md)；
- [Unified provider evidence broker](unified-provider-evidence-broker.md)；
- [Canonical scientific chain adoption and attempt closure](canonical-scientific-chain-adoption-and-attempt-closure.md)。

## Real campaign evidence and why the current projection is insufficient

一次真实 AOX/HMM campaign 中，researcher 在同一 research task 内依次执行了多次 PubMed 调用：
有 required-provider empty/failed outcome，也有 source-bearing completed outcome；agent 通过更宽的
query 和精确 PMID query 继续收集证据。这是合理的探索策略，不是重复 operation 缺陷。当前 V3
文档也明确允许同一 `task_id` 存在多个 research invocation。

该次 task 最终在 `task.finish.evidence_refs` 中绑定了两个 PubMed evidence artifacts，而当前 AOX
collector 期待全部 numeric PMID source refs 恰好来自一个 invocation。以下任何做法都不能把该
历史 attempt 事后修成 eligible：

- 选择最后一个 completed invocation；
- 选择 source 数最多或 query 最精确的 invocation；
- 从 task summary 里的“primary”自然语言猜一个 artifact；
- 忽略 failed/empty invocation，只封存成功路径；
- 把相同 PMID 或相同 citation digest 的多个 invocation 合并成一次调用；
- 由 collector 在 bundle sealing 时替 agent 补一个 adoption 选择。

这些做法都会把执行事实和科学选择混为一谈，并允许 selective success 隐藏真实 provider history。
当前 Goal 的小修只能要求**未来** task 明确绑定一个 PubMed primary；上述 campaign 仍是永久
NO-GO，不能复用其 session、task、invocation、artifact、source ref、root 或 browser interaction。

这次实证暴露的是两个长期模型缺口：

1. `EngineInvocation` 正确记录了每次真实调用，但没有一个 attempt-scoped closure authority 证明
   “这个 scope 的全部调用就是这些”；
2. `task.finish.evidence_refs` 能表达交付引用，却没有版本化、可 CAS、可解释全部调用的选择与
   disposition 语义。

因此长期方案必须同时保留完整 occurrence universe 和显式 adopted evidence set；只做其中一半
都不能成为可离线验证的科学证据闭环。

## Goals and non-goals

### Goals

1. 封存一个 research scope 内**所有** canonical invocation，包括 successful、failed、empty、
   degraded、exploratory 和被 supersede 的调用，不让最终成功遮盖过程事实。
2. 用独立 canonical selection 表达 agent 最终采用哪些 provider evidence；artifact 顺序、最新时间、
   source 数量和报告 prose 都没有 adoption authority。
3. 为每个 terminal invocation 建立闭合 disposition；未知、running、缺 receipt 或未 disposition 的
   invocation 使 selection/bundle fail closed。
4. 将 provider attempts、safe request/response provenance、sealed artifacts、source refs、task finish、
   report claims 与 archive manifest 绑定到同一个 completeness root。
5. 让 offline verifier 在无 SQLite、无 provider 网络和无 Host 文件路径时重算全部 digest、集合与
   lineage，并检测增删、替换、重排和 bytes tamper。
6. 保持 agent 对 query、provider 顺序、调用次数、何时停止探索以及采用何种证据的策略自由；
   harness 只呈现事实、约束和显式 command。

### Non-goals

- 不要求 researcher 只调用一次 PubMed，也不固定 query 模板或 provider 顺序。
- 不让 harness 自动选择“最佳”“最新”或“来源最多”的证据。
- 不把 research provider 查询改造成 execution controlled operation，也不绕过 execution approval。
- 不把 `ResearchEvidenceSelection` 变成新的 task、lane、scheduler、report 或 artifact store。
- 不把 provider raw body、受限全文、credential、private URL、Host path 或 SQLite path 暴露到 public
  projection。
- 不在 schema migration 中回写历史选择事实；缺少当时 canonical decision 的旧 attempt 保持旧语义。
- 不用一个 hash 单独宣称对恶意 Host 的密码学不可抵赖；见下文 trust model。

## Architectural invariants

1. `EngineInvocation` 继续是一次 research capability occurrence 的 canonical owner；selection 不改写
   invocation outcome、attempts、task/lane、artifact 或 source refs。
2. provider I/O 前必须先创建 invocation；retry 仍属于同一 invocation，不能为获得成功创建一个
   隐藏的 replacement identity。
3. `ResearchInvocationUniverseClosure` 是 scope 完整性的唯一 authority；`list_by_task()`、最新时间、
   workspace projection 或 collector 内存列表都不是完整性证明。
4. `ResearchEvidenceSelection` 是 adoption 的唯一 authority；`task.finish`、report 和 bundle 只引用
   sealed selection，不能各自维护一份可漂移的 selected refs。
5. universe occurrence set 与 selected evidence set 永远分离。一个 failed/empty invocation 即使不支持
   report claim，也必须出现在 universe 和 disposition 中。
6. 每个 closure 内 invocation 必须恰有一个 current disposition。重复、缺失、未知 enum 或与 canonical
   outcome 不相容的 disposition 全部拒绝。
7. `accepted` 只表示该 selection revision 采用某个 source-bearing invocation/artifact 来满足显式
   evidence slot；它不把 provider 内容自动宣称为科学真理。
8. `exploratory`、`failed`、`empty` 与 `superseded` 都保留原始 invocation 和 receipt，不能删除、降采样
   或从 archive manifest 中省略。
9. task/lane binding 使用 typed nullable equality：`None == None` 合法，`None != ""`；非空 lane 必须
   在 task、invocation、artifact、source ref、selection 和 report lineage 上 exact-match。
10. scope closure 后禁止创建新的 invocation、provider attempt、evidence artifact 或 source ref；需要
    继续探索时显式创建新的 closure revision/scope epoch，不得重开已 sealed universe。
11. selection revision 是 immutable、append-only、CAS 写入；改变 adoption 必须创建新 revision，旧
    selection 仍可审计，已被 task finish/report/archive 采用的 revision 不得原地覆盖。
12. required/enrichment quorum 来自 versioned evidence contract。provider adapter 不根据结果好坏
    改 contract，collector 不在 sealing 时补 fallback。
13. failed/empty receipt 是 evidence，不是“没有 evidence”。没有 citation 可以合法为零，但 provider
    attempt、outcome、request identity、response/failure digest 与 sealing state必须闭合。
14. public projection 是 canonical records 的 allowlisted read model，不拥有 selection、disposition 或
    completeness 状态。
15. bundle/verifier `@1` 与 `@2` 永不混读。`@1` 不能通过读取新增表获得 retroactive eligibility。

## Scope and identity model

完整性不能只按 `task_id` 查询。task 可能被 resume，agent 也可能在同一 task 中先做一次 evidence
campaign、再因用户新要求开始另一轮。建议增加 Host-issued `research_scope_id`：

```text
ResearchEvidenceScope@1
  research_scope_id
  attempt_id
  session_id
  task_id
  lane_id?                            # nullable, typed
  agent_id
  workflow_ref / workflow_manifest_digest?
  evidence_contract_ref / evidence_contract_digest
  purpose                             # formal | enrichment | probe | fault
  epoch
  state                               # open | closing | closed | invalidated
  opened_event_cursor / opened_at
  current_closure_id?
  created_by
```

`research_scope_id` 在第一次 provider invocation 前由 Host 创建并注入 tool context。caller 不能自报
另一个 scope 来逃避历史。AOX formal researcher、known-positive probe 和 controlled fault 必须使用
不同 purpose/scope；probe evidence 不能被 formal selection 采用。

同一 task 可以有多个 scope epoch，但一次 eligible task finish 必须显式引用 exact sealed selection。
scope 若仍 open，`task.finish(status=completed)` 不得把它机械关闭。agent 先发出显式 evidence-select/
close command；Host 校验后才允许 finish。这保留“业务完成”和“证据 universe closure”的边界。

## Ownership model

建议在 V3 control plane 增加窄的 `ResearchEvidenceService`。它协调现有 repository 与 artifact boundary，
但不成为 provider engine、reporter 或 scheduler。

| owner | canonical authority | explicitly does not own |
|---|---|---|
| `EngineInvocationRepository` | research occurrence identity、status、task/lane/scope binding | 最终采用哪些 evidence |
| provider adapter / future broker | provider attempts、normalized outcome、safe provenance | task 完成、report claim、provider fallback strategy |
| `ArtifactBoundaryService` | sealed bytes、content digest、read grant | citation adoption、quorum policy |
| source-ref repository | bibliographic/source identity 与 artifact link | universe completeness、report claim truth |
| `ResearchEvidenceService` | scope closure、universe root、selection revision、disposition CAS | query 生成、provider ranking、科学结论 |
| task service | business status 与 atomic `task_finish` document | 自动关闭 scope、猜 selected evidence |
| report service | draft/publish 与 claim-evidence binding | 改写 selection、隐藏非采用 invocation |
| workspace/UI | safe facts、counts、command surface | canonical selection/disposition/closure |
| archive service | immutable manifest、bundle bytes、retention | 重新选择证据、在线补查 provider |
| offline verifier | sealed records的独立重算 | 回写 SQLite、事后补 selection |
| researcher agent | query/order/stop/adoption/reason 的显式决策 | 伪造 provider outcome、receipt、identity、time |

`ResearchEvidenceService` 可以复用未来 `ProviderEvidenceBroker` 的标准 envelope，但二者职责不同：
broker 统一一次 provider call 的 mechanics；evidence service 关闭跨多次 invocation 的 universe 并记录
adoption。任何一方都不能吞并 execution approval 或 task control plane。

## Proposed canonical objects

### `ResearchInvocationUniverseClosure@1`

```text
ResearchInvocationUniverseClosure@1
  closure_id
  research_scope_id / epoch
  attempt_id / session_id / task_id / lane_id? / agent_id
  evidence_contract_ref / evidence_contract_digest
  state                               # preparing | sealed | invalidated
  opened_event_cursor
  closure_barrier_event_cursor
  repository_schema_id
  universe_query_contract_ref         # closed predicate, not raw SQL
  invocation_count
  provider_attempt_count
  evidence_artifact_count
  source_ref_count
  outcome_counts                      # completed/empty/degraded/failed
  invocation_leaf_digests[]           # sorted by invocation_id
  invocation_universe_root
  provider_attempt_root
  evidence_artifact_root
  source_ref_root
  completeness_root
  previous_closure_id? / previous_completeness_root?
  sealed_by / sealed_at
  invalidation_ref?
```

closure 在一个 SQLite write transaction 中建立 barrier：

1. CAS `scope.state=open -> closing`；
2. 读取该 scope 的 canonical high-water event cursor；
3. 拒绝任何 nonterminal invocation、open provider attempt、pending artifact seal 或未提交 source ref；
4. 读取 closed predicate 下全部 records，计算 leaves、counts 与 roots；
5. 写入 immutable closure、scope `closed` projection 和 durable event；
6. commit 后才允许 selection seal、task finish、report publish 或 archive。

scope 进入 `closing` 后，provider tool admission 必须 fail closed；不能在 closure query 与 commit 之间
插入新 invocation。单进程 SQLite 可以用同一 UoW、`BEGIN IMMEDIATE`、foreign keys、unique indexes
和 trigger 双层约束实现，但 service contract 不依赖“现在只有一个 Python process”这一偶然事实。

`universe_query_contract_ref` 是 versioned logical predicate，例如“exact research_scope_id 下所有非
fixture research-tool/deep-research invocation”；它不能保存任意 SQL，也不能由 collector 选择
provider allowlist 后漏掉不喜欢的 invocation。

### Invocation leaf and completeness digest

每个 invocation leaf 至少覆盖：

```text
ResearchInvocationLeaf@1
  invocation_id / engine_kind / provider / operation
  research_scope_id / attempt_id / session_id / task_id / lane_id? / agent_id
  canonical_status / normalized_outcome
  requirement                         # required | enrichment
  started_at / terminal_at
  safe_request_identity_digest
  provider_identity_digest?
  provider_attempt_ids[] / provider_attempt_root
  output_document_ids[] / document_digests[]
  evidence_artifact_ids[] / evidence_artifact_digests[]
  source_ref_ids[] / source_ref_digests[]
  failure_receipt_id? / empty_receipt_id?
  call_local_quorum_digest
  fixture_non_cutover
  leaf_digest
```

序列化必须使用 versioned canonical JSON/CBOR contract；object key、Unicode、timestamp、nullable value
与 array ordering 都有唯一编码。集合先按 canonical id 排序，不能依赖 SQLite row order 或 artifact
展示顺序。

建议的 root 关系为：

```text
invocation_universe_root = H(domain, sorted(invocation_leaf_digests))
provider_attempt_root    = H(domain, sorted(provider_attempt_receipt_digests))
evidence_artifact_root   = H(domain, sorted(artifact_record_digest || sealed_content_digest))
source_ref_root          = H(domain, sorted(source_ref_record_digests))
completeness_root        = H(
  domain,
  scope_identity,
  closure_barrier_event_cursor,
  evidence_contract_digest,
  all counts,
  all four roots
)
```

counts 进入 root，防止空集合、duplicate id 或 leaf 去重把遗漏隐藏。每个 id 必须 unique；同一 digest
的两个真实 invocation 仍是两个 leaves，不能按内容 digest 合并。

### `ResearchProviderAttemptReceipt@1`

每一次真实 provider attempt（包括 adapter retry）都必须有 immutable safe receipt：

```text
ResearchProviderAttemptReceipt@1
  provider_attempt_id / invocation_id / attempt_index
  research_scope_id / task_id / lane_id?
  provider / operation / endpoint_id
  requirement
  provider_io_performed
  request_identity_digest / request_body_digest?
  provider_identity_digest?
  started_at / finished_at
  transport_status / http_status?
  response_body_digest? / response_byte_size?
  retry_after_seconds? / retry_reason_code?
  terminal_outcome                     # completed | empty | degraded | failed
  safe_failure_code? / safe_failure_summary?
  raw_private_receipt_artifact_id?
  safe_receipt_artifact_id
  receipt_digest
```

retry 不创建新 invocation，但每次已发生 network attempt 都进入 `provider_attempt_ids[]`。若在 provider
I/O 前失败，`provider_io_performed=false` 且 request identity/failure code 仍闭合；若 transport outcome
不确定，receipt 必须表达 unknown effect，invocation 不能被 selection seal 为 accepted/empty，也不能
被下一个成功 attempt 覆盖。

raw URL、query secret、header、API key、email、response body 和 private locator 留在 Host-private
allowlisted boundary；public/safe receipt 只含不可逆 identity/digest 与 closed taxonomy。若 license
允许保存 citation payload，bytes 经 artifact boundary 封存；metadata 上写一个 digest 不等于 sealed。

### Failed and empty receipts

失败或 empty invocation 不得因为没有 source refs 就从 universe 消失。建议增加两个 closed payload：

```text
ResearchInvocationFailureReceipt@1
  failure_receipt_id / invocation_id
  provider_attempt_ids[] / provider_attempt_root
  canonical_failure_code / retryability / provider_io_state
  last_response_digest? / safe_diagnostic_digest
  evidence_sealing_state
  terminal_transition_event_cursor
  receipt_digest

ResearchInvocationEmptyReceipt@1
  empty_receipt_id / invocation_id
  provider_attempt_ids[] / provider_attempt_root
  provider_io_performed
  normalized_item_count                  # exactly 0
  parser_contract_ref / parser_contract_digest
  response_digest / normalized_empty_digest
  call_local_quorum_digest
  terminal_transition_event_cursor
  receipt_digest
```

`failed` 不能伪装成 `empty`；transport timeout、schema drift、credential error、rate-limit exhaustion 和
artifact-seal failure均保留各自 failure taxonomy。`empty` 只允许真实 provider response 经 pinned parser
得到合法零项。LLM 文本“没有找到”不是 empty receipt。

provider 返回 citation 但 artifact sealing 失败时，invocation outcome 仍为 failed；不能保留 public
source refs 再把调用标成 accepted。source-ref、artifact、invocation terminal transition 应由同一 UoW
或明确的 recovery protocol 闭合，crash 后不允许 half-visible success。

### `ResearchEvidenceSelection@1`

```text
ResearchEvidenceSelection@1
  selection_id
  research_scope_id / closure_id
  attempt_id / session_id / task_id / lane_id? / agent_id
  evidence_contract_ref / evidence_contract_digest
  completeness_root
  revision
  parent_selection_id?
  state                                  # draft | sealed | invalidated
  evidence_slot_bindings[]
  disposition_ids[] / disposition_set_digest
  accepted_invocation_ids[]
  accepted_artifact_ids[]
  accepted_source_ref_ids[]
  selection_digest
  selected_by / selected_at
  sealed_by? / sealed_at?
  invalidation_ref?
```

`evidence_slot_bindings` 使用 workflow/evidence contract 定义的 slot，例如
`required_literature.pubmed_primary`、`enrichment.semantic_scholar`，而不是 prompt 中的自然语言标签。
每个 slot 声明 cardinality、allowed providers、required/enrichment、source schema 和 quorum rule。

AOX 当前 `@1` 的“一个 PubMed aggregate”在 `@2` 中应表达为：

```text
slot_key = required_literature.pubmed_primary
cardinality = exactly_one_invocation
accepted_invocation_id = ...
accepted_evidence_artifact_ids = [...]
accepted_source_ref_ids = [...]
```

selection 只能引用同一 sealed closure universe 内的 records。禁止跨 attempt、session、task、scope 或
purpose 采用；nullable lane 必须 exact-match。artifact/source ref 必须由 accepted invocation 产生且
sealed content digest 与 closure leaf 一致。

`draft` 允许 agent 分批 disposition；`sealed` 后 immutable。若 agent 在 task finish 前改变选择，创建
新 revision 并用 expected revision/completeness root 做 CAS。已经被 task finish、published report 或
archive manifest 引用的 selection 不得切换 authority；只能显式 reopen task/新建 scope，并保留旧链。

### `ResearchEvidenceDisposition@1`

每个 universe invocation 在一个 sealed selection revision 中恰有一个 current disposition：

```text
ResearchEvidenceDisposition@1
  disposition_id
  selection_id / research_scope_id / closure_id
  invocation_id
  disposition                           # accepted | exploratory | failed | empty | superseded
  evidence_slot_keys[]
  artifact_ids[] / source_ref_ids[]
  superseded_by_invocation_id?
  supersedes_disposition_id?
  actor_ref / reason_code
  bounded_reason_summary?
  recorded_at
  disposition_digest
```

闭集语义：

| disposition | canonical prerequisite | selection meaning |
|---|---|---|
| `accepted` | invocation outcome completed；call-local quorum valid；至少一个 sealed evidence artifact / valid source ref；满足 slot policy | 该 invocation 明确支持一个或多个 selected evidence slots |
| `exploratory` | completed 或允许的 enrichment degraded；历史与 receipt 完整；未用于 selected slot | agent 调用并查看过，但没有作为 report claim authority |
| `failed` | canonical outcome failed，或 evidence contract 明确判定 degraded 不可采用；failure receipt完整 | 保留 failure，不支持 claim，也不因后来成功而消失 |
| `empty` | canonical outcome empty；empty receipt、真实 I/O 与 pinned parser证明零项 | 合法零结果，不支持非空 claim，不等于 provider failure |
| `superseded` | source-bearing completed/degraded invocation；存在同一 policy slot 下明确 accepted replacement | 旧结果保留，但当前 selection 采用 replacement；相同内容不自动 supersede |

以下组合必须拒绝：

- failed outcome 标成 exploratory 或 superseded；
- empty outcome 标成 accepted；
- completed source-bearing invocation 标成 failed 以隐藏不喜欢的结果；
- `superseded_by_invocation_id` 未在同一 selection 中 accepted；
- 一个 invocation 同时 accepted 和 exploratory；
- disposition 只引用 artifact 子集，却没有声明其余 artifact/source-ref 的处理规则；
- reason summary 含 raw query、secret、private URL/path 或受限全文。

`reason_code` 使用 versioned taxonomy，例如 `selected_primary_for_slot`、
`useful_context_not_claim_authority`、`provider_terminal_failure`、`provider_valid_empty`、
`replaced_by_more_specific_query`、`duplicate_citation_not_adopted`。reason 解释 agent 决策，但不能替代
canonical outcome、slot binding 或 lineage 校验。

若 invocation 内部分 source refs accepted、部分只作 context，需要在 selection slot binding 中显式列出
accepted source refs，并为 invocation 仍保留一个 disposition。长期若需要 source-level disposition，
应另起 schema major version；不能把 source-level state偷偷塞入当前 invocation enum。

## Command protocol and agent freedom

建议新增两个明确 agent-facing command，而不是让 collector解析 prose：

```text
research.evidence.close_scope(
  research_scope_id,
  expected_scope_epoch,
  expected_open_event_cursor
) -> closure_id, completeness_root, safe_universe_summary

research.evidence.select(
  closure_id,
  expected_completeness_root,
  expected_parent_selection_id?,
  slot_bindings,
  dispositions
) -> sealed selection_id, selection_digest
```

Host 返回结构化、bounded facts：invocation ids、provider/outcome、safe citation count、artifact/source-ref
ids、receipt closure 和 contract slots。它不输出 `recommended_actions`，不按 citation count 排名，也不
替 agent填 disposition。

researcher 可以自由：

- 先精确 query，再宽 query，或反过来；
- 因 empty、rate limit 或 schema failure 决定是否发起另一个 materially different query；
- 同时使用 required 与 enrichment provider；
- 采用早期或后期 invocation，只要显式 slot policy 和 evidence closure 满足；
- 在无法得到 required evidence 时以 failed task 结束，而不是生成 synthetic citation。

但 researcher 不能：

- 在 scope closed 后继续调用 provider；
- 将未发生 provider I/O 的模型知识标成 PubMed evidence；
- 省略 failed/empty invocation；
- 通过新 invocation identity 隐藏同一 call 的 retry；
- 跨 formal/probe/fault scope 采用 artifact；
- 让 task/report summary 替代 selection command。

## Binding to provider execution

provider tool admission 的顺序建议固定为：

1. 从 authenticated runtime context 取得 session/task/agent 与 Host-issued research scope；
2. 校验 scope `open`、task可运行、lane typed-equal、provider/tool在 evidence contract allowlist；
3. 在 provider I/O 前持久化 `EngineInvocation(RUNNING)` 与 durable started event；
4. 为每个 network attempt 先分配 attempt id，随后终结 safe receipt；
5. 解析 response，封存 evidence bytes，再在同一 UoW 写 artifact/source refs/document 与 invocation terminal
   outcome；
6. 发出 terminal event，供 agent 读取 facts；不自动关闭 scope或完成 task。

future broker 可实现第 4/5 步的共同 mechanics，但 owner identity 仍来自 caller 的 invocation。direct
research、deep-research 和其他 research engines 若进入同一 scope，必须投影相同 leaf/receipt contract；
不能因为调用面不同而在 completeness root 中漏掉一类。

## Binding to `task.finish`

research task 的 `task.finish` 应新增 exact `research_evidence_selection_id`（对需要 research evidence 的
completed outcome 为必填）。Task service 在同一 transaction 中验证：

1. selection `sealed`，且属于 exact session/task/agent/scope；
2. selection 绑定当前 sealed closure 和 completeness root；
3. scope closure 后没有新增 invocation/event，也没有 invalidation；
4. required slots、cardinality、provider、quorum 与 fixture exclusion 满足 pinned contract；
5. 每个 universe invocation 恰有一个有效 disposition；
6. task、invocation、artifact、source ref 的 nullable lane exact-match；
7. `evidence_refs` 若在兼容期仍存在，只能由 selection accepted refs机械投影，caller不能再提交另一集合；
8. `task_finish` document、task terminal status、selection binding 与 durable event 原子 commit。

`task.finish(status=failed)` 也应引用 closure/selection 或显式 `research_failure_closure_id`，从而保留
真实 failed/empty history；但它不能被 required-slot quorum gate 阻止。失败 task 仍需 universe 完整，
除非 process crash 造成 unknown effect；该情况进入 attempt-level ineligible closure，不能伪装成正常
research failure。

task idle、agent turn结束、provider terminal、scope closure、selection sealed都不自动代表业务 completed。
反过来，generic task PATCH 也不能绕过 selection prerequisite。

## Binding to report drafts, claims, and publication

reporter 不应重新从全 session source refs 中选择证据。research task向 reporter 交付 exact：

```text
ResearchEvidenceHandoff@1
  selection_id / selection_digest / completeness_root
  accepted slot bindings
  accepted artifact/source-ref ids
  exploratory/failed/empty/superseded safe summaries
  task_finish_id / delegation message id
```

report draft 保存 `research_evidence_selection_ids[]`；每个结构化 claim 保存支持它的 accepted source refs
和 slot key。publish gate 验证：

- report selection 与 task finish handoff exact-match；
- claim citations 是 accepted source refs 的子集；
- exploratory/superseded source 只能在方法、讨论或局限性中以非 claim-authority 角色出现；
- failed/empty receipt 可支持“检索失败/无结果”的过程披露，不能支持非空科学发现；
- selection 未 invalidated，artifact bytes 和 source-ref digests仍与 closure一致；
- report 不含 private receipt、raw query secret、Host path 或 restricted body。

若 reporter 认为 primary selection 科学上不足，它应 protocol.send 反馈 researcher/master 并显式 reopen/
new scope，而不是在 report 中偷偷改用 exploratory artifact。report publish 不拥有 selection mutation。

## SQLite and control-plane persistence

建议 additive tables（名称仅表示 ownership，不要求当前 Goal 落地）：

- `research_evidence_scopes`；
- `research_provider_attempt_receipts`；
- `research_invocation_failure_receipts`；
- `research_invocation_empty_receipts`；
- `research_universe_closures`；
- `research_universe_invocation_leaves`；
- `research_evidence_selections`；
- `research_evidence_slot_bindings`；
- `research_evidence_dispositions`；
- `task_finish_research_selections`；
- `report_research_selections` / `report_claim_source_bindings`；
- append-only invalidation records。

关键数据库约束：

- `(research_scope_id, epoch)` unique；
- invocation 必须 FK 同 scope/session/task，lane 由 trigger执行 typed nullable equality；
- provider attempt `(invocation_id, attempt_index)` unique 且单调；
- terminal invocation 的 outcome 与 failure/empty receipt one-of check；
- sealed closure immutable，closure 后禁止向 scope插入 invocation/attempt/artifact/source ref；
- `(selection_id, invocation_id)` current disposition unique；
- accepted slot cardinality由 service校验，并将 normalized binding digest写入 selection；
- parent revision、expected digest 和 scope epoch 使用 CAS；
- published report/task finish FK exact sealed selection；
- fixture/non-cutover invocation不能进入 cutover selection。

repository/service 校验与 SQLite trigger 是同一 contract 的两层防线。测试不能用 raw INSERT 绕过
真实 migration；fixture seed 必须显式 non-cutover，并永远不能进入 eligible bundle。

事务边界至少覆盖：

- provider terminal outcome + receipt + artifact/source refs；
- scope closure + completeness roots + closed state + event；
- selection seal + disposition set + slot bindings + event；
- task finish + selection binding + terminal task + event；
- report publish + claim bindings + report artifact + event。

crash recovery只重放同一 idempotency/CAS command；不得创建新的 invocation或选择“能提交”的替代
artifact。无法证明原事务是否提交时返回 typed consistency failure并使 cutover ineligible。

## Public projection and UI

workspace projection 应增加 bounded、facts-only summary：

```text
research_evidence:
  scopes:
    - research_scope_id / purpose / epoch / state
      closure_id? / selection_id?
      invocation_count / outcome_counts / disposition_counts
      evidence_contract_ref
      required_slot_statuses
      completeness_root? / selection_digest?
      needs_attention_codes[]
```

agent-facing detail tool可分页读取 invocation safe summaries、receipts和 disposition，但不得内联大
response、全文或全部 citations。UI 可展示“4 calls: 1 accepted, 1 exploratory, 1 failed, 1 empty”，并
明确区分 provider outcome 与 selection disposition。

public projection 不得包含：

- raw NCBI identity/email/API key；
- credential/query-bearing URL、private header、Host/Blob/SQLite path；
- provider raw body或许可受限全文；
- private diagnostic、stack trace或runner locator；
- selector 推荐、自动 primary ranking或可修改 canonical state的本地 UI state。

UI command 必须调用 Host selection/closure API，并展示 canonical version/digest conflict。浏览器 local
state、optimistic badge或报告文本都不能成为 adoption authority。

建议增加 durable events：

- `research.evidence.scope.opened`；
- `research.provider.attempt.completed`（safe summary）；
- `research.evidence.scope.closed`；
- `research.evidence.selection.sealed`；
- `research.evidence.selection.invalidated`；
- `task.finished` / `report.published` 中的 selection refs。

event 是恢复与审计索引，不替代 canonical rows。closure barrier cursor进入 completeness root，防止
旧 projection或截断 replay冒充当前 universe。

## Archive and offline bundle `@2`

建议新增 `research_evidence_archive@2`，并由 `aox_blank_world_attempt_bundle@2` 引用。最小闭集包括：

```text
research_scope_record
research_universe_closure
all invocation leaves
all canonical invocation public records
all provider attempt safe receipts
all failure/empty receipts
all referenced evidence artifact catalog records
all licensed/public-safe sealed evidence bytes
all source-ref records
research evidence selection + slot bindings
all dispositions
task_finish selection binding
report handoff/draft/publish claim bindings
event cursor range + safe relevant events
archive manifest + schema/contract serializers
```

archive manifest 对每个 member保存 logical path、schema id、byte size和 content digest；按 canonical order
计算 manifest root，再绑定 attempt id、commit/config/workflow/evidence contract和 campaign attestation。
Host local path、SQLite filename或blob locator不进入 archive。

offline verifier `@2` 不访问网络、不打开 live SQLite、不信任 artifact filename或报告 prose。它必须：

1. 校验 archive manifest、member bytes、schema id和顶层 attestation；
2. 重算所有 receipt、artifact、source-ref、invocation leaf和四个子 root；
3. 重算 counts、barrier identity与 completeness root；
4. 证明 manifest 含 closure列出的每个 id且没有额外未 disposition invocation；
5. 校验 outcome与 failed/empty/accepted/exploratory/superseded disposition matrix；
6. 校验 provider attempt序号、request/response digest和invocation terminal transition闭合；
7. 校验 selection slot cardinality、required/enrichment quorum和 fixture exclusion；
8. 校验 nullable lane、session/task/scope/purpose/agent lineage；
9. 校验 task finish exact引用 selection，report claims仅引用 accepted evidence；
10. 对许可允许封存的 evidence bytes重算 citation/source identity；
11. 拒绝 unknown schema、unknown enum、duplicate id、unsorted canonical set或任何网络 fallback。

### Trust model and completeness claim

Merkle/root 只能检测 sealed 后的增删改，不能单独证明一个恶意 Host 在 sealing 前没有删库。因此
`@2` 的准确 claim 应是：

- Host-owned `ResearchEvidenceService` 在 SQLite closure transaction 中按 closed predicate建立 canonical
  universe；
- closure row、barrier event cursor、event-chain root（若可用）和 archive manifest由 campaign
  attestation authority绑定；
- offline verifier证明 archive与该 attested closure完全一致，且 sealed后未被篡改。

若未来要求对 Host 本身实现外部不可抵赖，必须另行引入硬件/远端签名、WORM transparency log或
外部 timestamp authority；不能把普通 SHA-256 root宣传成独立第三方证明。当前 trusted-Host-only
runner和单进程 SQLite前提下，Host attestation boundary是明确且足够的产品信任边界。

## Tamper and omission model

`@2` 至少必须 fail closed 于：

- 删除任一 failed、empty、exploratory、superseded或 accepted invocation leaf；
- 添加不在 attested closure中的 invocation；
- 修改 outcome、provider、task/lane/scope、timestamps、attempt count或 fixture flag；
- 删除失败 receipt，或把 failed改成empty/completed；
- 删除一次 retry attempt，重排 attempt index，或用后一次 success覆盖前一次 transport failure；
- 改 accepted invocation/artifact/source ref，或把 exploratory/superseded ref用于 report claim；
- 用相同 citation/content digest合并两个真实 invocation；
- 改 evidence bytes、artifact record、source-ref PMID/DOI或 provider provenance；
- 把 `lane_id=None`改成`""`，或跨 task/session/purpose graft lineage；
- 修改 evidence contract、slot cardinality、workflow/config/commit identity；
- 截断 event cursor、替换 closure root、重放旧 selection revision；
- 在 scope closure后追加 invocation或 source ref；
- 从 archive manifest省略 member，或加入未被 root/selection覆盖的shadow evidence；
- verifier unknown enum/schema时尝试兼容解析或在线补查。

tamper fixture必须直接修改 sealed bytes/records后运行 offline verifier；不能只单元测试一个 helper。
每个拒绝都返回 closed safe reason code，不能泄露 raw provider payload或Host path。

## Versioning and migration plan

### Phase 0: specification and fixtures

- 固化 scope、receipt、leaf、closure、selection、disposition和canonical serialization schema；
- 给 current direct PubMed/Semantic Scholar/Tavily、deep research和provider broker proposal建立cross-path
  conformance fixtures；
- 明确 evidence slot registry、nullable lane equality和public/private字段；
- 写 property tests与tamper corpus，先不改变live admission。

### Phase 1: additive occurrence capture

- 增加 scope和provider-attempt receipt表；
- direct research invocation先dual-write/shadow计算leaf；
- 对 completed/empty/degraded/failed和artifact-seal failure逐项对比legacy projection；
- 任何shadow mismatch只告警并阻止`@2`，不改写legacy outcome，也不自动fallback。

### Phase 2: closure and completeness shadow mode

- 实现Host-owned closure transaction和root计算；
- 对既有live campaign只生成non-authoritative shadow archive，比较DB查询、event cursor和manifest集合；
- 注入concurrent admission、crash、rollback、duplicate retry与nullable lane故障；
- 在充分验证前不让 task finish/report依赖shadow root。

### Phase 3: explicit selection and task/report binding

- 上线 `research.evidence.close_scope/select` command；
- agent prompt只解释facts/constraints，不固定query策略；
- task finish增加selection binding并原子写入；
- reporter handoff和claim bindings迁到exact selection；
- compatibility `evidence_refs`变成selection-derived只读projection。

### Phase 4: bundle/verifier `@2`

- 实现独立archive builder和offline verifier；
- `@2`只接受new-scope/new-selection，不读取legacy inference；
- 同一attempt不能混用`@1` research evidence与`@2`selection；
- shadow生成`@1/@2`时两者分别判定，禁止择优选择成功版本。

### Phase 5: live cutover and legacy retirement

- fresh roots/session/scope完成多query real-provider positive、真实empty/failed和report publish验证；
- 完成post-seal tamper matrix与archive portability验证；
- 审计CLI、Host API、UI、plugin、外部脚本和历史consumer；确认无外部调用方后才退役caller-submitted
  `task.finish.evidence_refs`和`@1` selector；
- 保留`@1` verifier用于历史archive，只读且永不升级eligibility。

## Compatibility and rollback

- additive capture阶段不改变现有tool result或workspace schema的required fields；新projection采用versioned
  optional section。
- migration不回填历史 adoption。历史 task finish只按当时 contract验证；没有canonical selection的
  attempt不能生成`@2`。
- rollback可以停止新scope admission并切回`@1`新campaign，但不得删除已写scope、receipt、closure、
  selection或disposition；它们保留为immutable non-cutover evidence。
- rollback不能把sealed `@2` selection降级成caller提交的evidence refs，也不能恢复自动latest selector。
- schema reader遇到future version必须fail closed；不做宽松字段丢弃。
- legacy compatibility path只有在外部调用方审计完成后才退役，且退役要单独release note/migration gate。

## Risks and mitigations

### Selection layer becomes a hidden workflow engine

风险：slot registry或UI开始规定query顺序、provider fallback和“最佳”证据。

缓解：contract只声明cardinality、allowed provider、quorum和安全约束；query/order/stop/adoption由agent
显式决定，facts projection不含recommended actions。

### Universe root gives a false completeness claim

风险：只hash collector拿到的列表，却没有scope barrier/DB authority，仍可漏行。

缓解：closure必须在Host-owned SQLite transaction中关闭admission、绑定high-water cursor/counts/closed
predicate；archive attestation绑定closure。文档明确Host trust boundary与hash能力上限。

### Disposition hides inconvenient evidence

风险：agent把不喜欢的successful result标成failed或直接省略。

缓解：disposition与canonical outcome做closed matrix；所有invocation必有且仅有一个disposition；
successful non-selected只能是exploratory/superseded，仍进入archive和public counts。

### Retry semantics create duplicate or missing calls

风险：adapter把retry建成新invocation，或只保留最终success。

缓解：invocation owner先建立；每次provider attempt有单调index/receipt/root；unknown transport effect阻止
eligible closure，不能自动重开replacement。

### Public projection leaks research identity or licensed content

风险：完整历史扩张后，raw query、NCBI email、response body或private URL进入UI/report。

缓解：private raw receipt与safe receipt分层；projection allowlist、secret/path corpus测试和license policy
是publish/archive gate。

### `task.finish` becomes too high-friction

风险：agent需要手工复制大量ids和dispositions，导致错误或prompt膨胀。

缓解：Host提供分页facts和bounded universe summary；command接受typed ids/closed enums并返回precise tool
errors。Harness可机械展示尚未 disposition的invocation，但不能替agent选择其类别。

### Scope closure races or deadlocks

风险：provider call仍在运行时closure等待或部分提交。

缓解：closure不无限等待；发现nonterminal/open attempt即返回typed blocker。supervisor/agent先显式闭合或
abort，unknown effect使attempt ineligible。SQLite transaction保持短小，不在锁内做network/blob I/O。

### Report and selection drift

风险：reporter复制source refs后researcher修改selection。

缓解：selection immutable；published report绑定exact selection id/digest。需要改变时创建新scope/revision
和report revision，旧报告不被原地重写。

## Acceptance criteria

### Canonical state and database

- completed、empty、degraded、failed、artifact-seal failure和transport-unknown fixtures都先有invocation，
  每次attempt完整终结同一identity。
- SQLite/service双层拒绝closed scope新invocation、duplicate attempt index、cross-task/scope artifact、
  invalid nullable lane和sealed selection mutation。
- closure在concurrent admission故障注入下要么包含该invocation，要么让admission失败；不得成功closure
  后出现unrooted row。
- crash在provider response、artifact seal、source-ref write、terminal transition、closure和selection任一
  边界发生时，不产生half-success或replacement invocation。

### Selection and strategy freedom

- researcher可执行多个materially different PubMed queries并显式采用任意一个policy-valid primary；
  harness不按时间、source count或内容自动选择。
- universe内每个invocation恰有一个accepted/exploratory/failed/empty/superseded disposition，且outcome
  matrix逐项验证。
- failed、empty和exploratory调用不会阻止一个本来满足contract的selection，但任何遗漏、receipt不闭合、
  unknown effect或required slot缺失都会fail closed。
- 相同PMID、citation digest或artifact bytes的两个调用仍保留两个invocation leaves。

### Task and report lineage

- completed research `task.finish`缺selection、引用open/invalid selection、cross-task/scope selection或required
  slot不足时全部拒绝。
- `task_finish` document、task status、selection binding和event在一个transaction内原子可见。
- report draft/publish只能引用accepted source refs；exploratory/superseded claim graft、failed/empty支持非空
  claim和selection drift全部拒绝。
- task/lane/session/agent/purpose在invocation、artifact、source ref、selection、task finish和report上exact；
  all-`None` lane合法，`None`/空字符串混用拒绝。

### Archive and offline verification

- 一个多query真实provider fixture的archive在删除任一failed/empty/exploratory/superseded invocation后
  offline verifier失败。
- post-seal bytes flip、receipt replacement、source-ref修改、attempt omission、count/root修改、event cursor
  truncation、selection replay和report claim graft tamper matrix全部返回stable fail-closed reason。
- verifier在断网、无SQLite、不同绝对目录下得到相同digest/decision；不能依赖Host path或row order。
- secret/private URL/path/restricted-content corpus在public projection、archive safe records、tool errors、
  events和report中零命中。
- `@1`与`@2`交叉喂入、unknown schema/enum和legacy attempt retro-upgrade全部拒绝。

### Live qualification before architecture cutover

- fresh root的真实literature workflow至少覆盖：多个探索query、一个明确accepted primary、至少一个
  exploratory或superseded invocation，以及完整task/report binding；
- 另一个fresh scope真实验证empty或failed receipt路径，不使用fixture/synthetic provider result；
- controlled fault在closure前后、archive sealing后各验证一次omission/tamper fail closed；
- 全部provider调用计入持久MICU ledger，额度是硬上限而不是消耗目标；不得为覆盖测试而无意义调用；
- live evidence使用当次commit/config/workflow/schema pin，历史NO-GO attempt不参与新的eligibility。

## Exit conditions for retiring the proposal

只有以下条件全部满足，本提案才能从“deferred”转为implemented并同步进入稳定V3架构文档：

1. canonical schemas、migration、repositories、services、events和public projection已落地；
2. direct/deep-research provider paths通过同一conformance contract；
3. task finish、report publish、archive和offline verifier全部绑定sealed selection；
4. tamper/secret/crash/concurrency测试与真实provider qualification通过；
5. `aox_blank_world_attempt_bundle@2`和verifier `@2`有独立versioned文档与golden fixtures；
6. 外部调用方审计确认可以退役legacy caller-selected evidence refs；
7. `docs/OpenZyme架构设计.md`、相关`docs/v3/`稳定文档、OpenSpec和操作手册同步；
8. 历史`@1` archive仍可只读验证，且没有任何retroactive adoption或eligibility upgrade。

在这些条件之前，当前产品合同仍以现有V3 canonical objects和各workflow的`@1` evidence规则为准；
本文件只记录下一次大架构调整的完整设计与验收边界。
