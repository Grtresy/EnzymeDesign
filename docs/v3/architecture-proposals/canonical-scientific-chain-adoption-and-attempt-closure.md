# Deferred: canonical scientific chain adoption and attempt closure

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只实施三类有边界的小修：

1. `openzyme_pipeline.artifacts` 的 strict direct-field selectors 是三个互斥终点：
   `provider_file_ref` 只读取 direct provider-operation response，`fetched_output_ref` 只读取
   direct `ws.fetch_outputs` response，`registered_artifact_ref` 只读取 direct real
   `artifacts.register` response；递归遍历、selector chaining、把 canonical ref 再包装，以及
   synthetic registration envelope 都不是合法 artifact authority；
2. artifact source provenance 由 Host 显式绑定当前 Host-sealed run/operation source snapshot；
   control-socket registration、provider artifactization 与 HPC fetch 不能从 stale
   `last_command_summary` 推断旧 snapshot，也不能接受 sandbox 自报 source id；
3. AOX live driver 的 pre-approval exact-operation budget/history guard，在 provider/runner
   dispatch 前拒绝同一 reached SDK method 的第二个 controlled operation、已有 terminal
   `failed` / `recovery_failed` operation，以及任何已经 failed 的 operation-bearing sandbox
   run。

配套 workflow guidance 允许在 operation-bearing run 前使用短 inspection/source-repair run，并
要求 executor 在每个 controlled operation 完成后，先把完整响应保存到同一 sandbox 的
`/workspace/work`。controlled operations 开始后，该 checkpoint 只服务同一个仍成功的
operation-bearing run。它是 attempt-local mutable working state，不是 canonical evidence；一旦
该 run failed，checkpoint 只保留为失败诊断，不授权继续外部 dispatch，更不授权跨 sandbox
run、session 或 attempt 复用。

本 Goal **没有**新增 `scientific_chain_selection`、operation disposition、cross-run
adoption/materialization、attempt closure、bundle `@2` 或 verifier `@2`；也没有改变当前
exact-operation-set 的 acceptance semantics。以下方案会新增 control-plane authority、command
protocol、artifact handoff、public projection 和 evidence schema，属于大架构调整，因此只记录，
不在本 Goal 实施。

本提案对照：

- [V3 Harness Doctrine](../00-harness-doctrine.md)；
- [V3 Control Plane](../02-control-plane.md)；
- [Capability Engines](../03-capability-engines.md)；
- [Public Interfaces](../04-public-interfaces.md)；
- [AOX/HMM blank-world cutover](../aox-hmm-blank-world-cutover.md)；
- [AOX/HMM live workflow contract](../execution-pipeline-docs/aox-hmm-live.md)；
- [Artifact boundary](../execution-pipeline-docs/artifacts.md)。

## Real r12b evidence and why it cannot be retroactively adopted

r12b pinned commit `3819ba7eab0b7ba9febd43ff13206cf3d0f9e1a6`。在同一 formal
session 中，durable history 已包含：

- NCBI `op_80b00685b2a0` completed；
- 第二个 NCBI `op_fb3cc37d8df6` failed；
- MAFFT `op_830c597ac386` completed；
- 第二个 MAFFT `op_e5ca4eba6220` completed。

第二个 NCBI operation 已到达真实 adapter，随后才在 Host artifact-conflict persistence 失败，
因此不能归类为“provider I/O 前的无副作用 validation”。两个 MAFFT operation 生成相同 alignment
bytes，但最终 HMMbuild 只绑定第二个 artifact identity。当前 verifier 要求 branch-derived exact
formal operation set；它不能忽略第一个 MAFFT，也不能把 failed NCBI 从历史中抹去。

以下看似方便的处理全部不成立：

- 选最新 completed operation；
- 选被下游消费的 operation；
- 按 output digest 合并两个 operation；
- 把 failed operation 当作本地 parser failure；
- 事后增加一个标记，把旧 bundle 宣称成采用了某条链。

这些方法都会让 collector 或 verifier 替 agent 补造当时不存在的选择事实，并隐藏 approval、
provider effect、source snapshot、workspace、toolchain 或 failure history。r12b 仍是严格 NO-GO，
没有 eligible sealed bundle；未来 schema 不得回填、升级或复用其 session、operation、artifact、
workspace、root 或 browser interaction。

r12b 暴露的设计问题是：严格拒绝重复 operation 能安全阻止 selective success，却也让一次已完成
外部 effect 后发生的低级本地 source/parser 错误永久毒化整个 attempt。若产品将来允许在同一
blank-world attempt 内跨 sandbox run 恢复，就需要在重放前显式表达“采用哪一个已发生 effect、
为何排除其余 operation、bytes 如何进入新 workspace、所有失败如何闭合”。这不能继续由
`list_by_session()` 后的 selector 猜测。

## Real r19 evidence: six completed effects still do not form an eligible chain

r19 pinned commit `e6aaa085c94cb1b63bbda5ff44395817495a88cc` 与 config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`。
其 positive attempt `positive-98b4c1cdab5a47e6bd83d3c91b64d9fe` 最终存在六个真实
completed probe operation：

- NCBI `op_2bfe8f7ec798`；
- UniProt `op_077c1756762a`；
- MAFFT `op_4b74f52b785f`；
- hmmbuild `op_6d911baa02ef`；
- CD-HIT `op_0c33b3927655`；
- HMMalign `op_cfd9780670c5`。

但这些 effect 不是在一个成功的 operation-bearing run/source 下产生。首个 run
`srun_bff58c931ec3` 完成 NCBI 后，agent 将已经 terminal 的
`provider_file_ref(...)` 结果错误送入 `registered_artifact_ref(...)`，触发
`artifact_registration_projection_invalid`，该 sandbox run 以
`sandbox_exec_nonzero` failed。第二个 run `srun_66720840bd4a` 使用修复后的新 source，读取
attempt-local NCBI checkpoint，并且没有重放 NCBI；它执行了其余五个 operation。于是外部 effect
集合看似 exact-six，durable provenance 却包含两个 operation-bearing run、两个 source snapshot，
以及一个不可删除的 failed run。当前 `aox_known_positive_probe@2` 明确要求一个成功 run、一个
source snapshot 和无 failed-run history，collector 不能把第二个 source 追溯解释为已采用第一个
run 的 NCBI effect。

r19 还暴露了相邻但可局部修正的 source-authority 问题：第二个 run 创建的 controlled operations
正确绑定当前 source snapshot，部分 registered provider/HPC artifacts 却可能因 Host 优先读取
stale `workspace.last_command_summary` 而绑定旧 inspection/command snapshot。修复边界是 Host 在
control-socket register、provider artifactization 和 HPC fetch 内部显式传递当前 run/operation
snapshot，并只把 latest source-code id 当遗留 fallback；sandbox caller 没有自报该 authority 的
权限。这只纠正新 artifact provenance，不会生成 r19 当时不存在的 cross-run adoption record。

r19 的 non-eligible bundle digest 是
`sha256:d811da6e9fd0f291413c7f0369c6399f24e38d94997dc0d24516155773a72f16`，sealed
**NO-GO** decision digest 是
`sha256:f067ac844a5cd2df557d8b03b6ad89eb05c2b58f94fc502f04e976d9e55ccf84`；MICU ledger
累计 `41,557,461 / 500,000,000`，remaining `458,442,539`，零 breach/overage。该 bundle
与 decision 只能证明 failure evidence 的可封存性，未来 `@2` schema 也不得回填、升级或复用其
run、source、operation、artifact、root 或 browser state。

r19 使本提案的分界更具体：**阻止 failed run 后继续 dispatch 是当前 Goal 的 fail-closed 小修；
允许同一 attempt 从 failed run 显式采用一个已完成 effect，并在新 run 继续，则是本提案的大架构
能力。** 后者必须先有 durable selection/disposition、effect adoption/materialization、source/bytes
handoff、approval/public projection、attempt closure 与 bundle/verifier `@2`；仅凭 checkpoint、
相同 workspace、exact-six operation ids 或 agent prose 均不成立。

## Real r25 evidence: completed upstream work is neither correct nor adoptable

r25 pinned commit `6b9ac473fe01376d144ae800352a06e5d016223c`，formal operation-bearing run
`srun_6526213157db`。HMMER remote job 约 `24s` 已 terminal，但旧 adapter 将 terminal poll 的默认
`page_size=50` payload 与后续 `page_size=100`、`page=2..686` 结果拼接，漏掉索引 `50..99`：
provider 完整结果为 `68,592` 条，r25 只封存 `68,542` 条，而且缺失的 `50` 条均高于 AOX 分数
阈值。随后 UniProt 对 `37,722` 个 accession 形成 `378` 个 query batch；第 `102` 项（属于第二个
batch）是本次首个确认的 inactive/deleted identity。当前 adapter 在全部 query/page 累积后才统一
验证 record contract，并因旧 contract 强制要求每条 identity 都有 sequence 而失败。

r25 因此同时给出两条不可 adoption 的理由：

1. HMMER artifact 本身不满足 provider `nreported` 和科学 coverage closure，不能作为 realized effect；
2. 即使某个上游 effect 科学上完整，只要所在 operation-bearing run 已 failed，当前 `@1` contract 也
   没有 selection、disposition、materialization 或 attempt closure authority把它带入 fresh run。

当前 verifier 要求 AOX 的 `17` 个最终 deliverable 来自同一个 completed run/source，MAFFT 等下游输入
绑定该 run 内 exact final artifact identity。当前 Goal 会修复同宽 HMMER pagination、`nreported`
closure 与 UniProt inactive identity 后，从 fresh blank world 重跑；不会从 r25 复制 HMMER bytes、
checkpoint、operation 或 artifact ref，也不会为了节省真实 provider 调用而临时实现 cross-run adoption。
r25 永久 NO-GO，后续只读恢复诊断不能追溯升级其 bundle。

若未来希望在长链后段本地 contract failure 后复用一个**已经完整且可授权**的 provider effect，仍须按
本文分别实现 selection/disposition、Host-supervised materialization、approval、public projection、
attempt closure 与 verifier `@2`。这不能塞进 timeout、checkpoint 或 selector 的局部 fallback，也不在
本 Goal 实施。

## Current exact-operation-set semantics

当前 `aox_blank_world_attempt_bundle@1` 把 operation occurrence 与 accepted scientific chain 基本
视为同一个集合：offline verifier 从 sealed artifacts 推导实际 branch，再要求该 branch 每个 reached
formal SDK method 恰有一个 canonical completed operation，并拒绝额外或 hidden failed formal
operations。branch 正确省略的 optional methods 由 sealed empty facts 证明，probe 独立覆盖 formal
branch 未触达的 required capabilities。

该规则有三个重要优点：

1. verifier 不需要相信 agent 的自由文本“我采用了哪个结果”；
2. 不能用 successful retry 遮盖 failed attempt，也不能把相同 output bytes 冒充同一 execution；
3. approval、operation、artifact 和 report lineage 都可按一个闭集重算。

但它也把两个不同概念压在一起：

- **occurrence set**：世界里实际创建、批准、运行、失败或完成过的 controlled operations；
- **selected effect set**：agent 明确采用来构成一个 scientific result 的 effect 与 artifact lineage。

本提案不弱化 occurrence set 的穷尽审计。目标是增加一个 canonical、append-only、可 CAS 的
selection/disposition layer，使 verifier 从“恰好只发生过一条链”升级为“所有发生事实均被封存，
且恰好一条满足政策的链被明确采用”。未知、未闭合或越权的额外 operation 仍使 attempt
fail closed。

## Architectural principles

1. `ControlledOperation` 继续拥有某次真实 execution occurrence 的 provenance 与 terminal
   outcome；selection 不改写其 status、approval 或 result。
2. `ScientificChainSelection` 是 adopted scientific chain 的唯一 canonical authority；artifact
   order、最新时间、相同 bytes、workspace 文件或 UI 选择都没有 adoption authority。
3. 每个 scope 内被观察到的 operation 必须有一个当前有效 disposition；未 disposition 的
   operation 使 selection 无法 seal。
4. disposition 是 agent/operator 的显式科学选择，但 Host 校验真实世界约束。Harness 不替 agent
   选“最好”的结果，也不因结果相同自动合并。
5. cross-run continuation 只采用已经发生且已验证的 effect；它不伪造新的 completed
   `ControlledOperation`，也不把旧 approval 解释为新 execution 的授权。
6. artifact materialization 是 Host-owned boundary action，必须重验 catalog、blob bytes、permission
   和 target workspace；copy、mount 或 agent 自报 path 不是 adoption proof。
7. failure/abandonment 只描述该 operation 在 selected chain 中的 disposition，不删除 execution
   fact，也不自动授权 replacement。
8. attempt closure 是单独的 canonical command/object；task idle、sandbox exit、report 文本、bundle
   sealing或 UI terminal badge 都不能补造 closure。
9. bundle/verifier `@1` 与 `@2` 永不混读。历史 `@1` 只能按 exact occurrence set 验证，不从新表
   推断 adoption。
10. blank-world campaign 的跨 run adoption 只允许发生在同一个 fresh attempt authority/root 内；
    两个独立 positive attempts 和 fault attempt 之间禁止复用。

## Ownership model

建议增加一个窄的 `ScientificChainService`，属于 V3 control plane，而不是 AOX driver、execution
engine、sandbox SDK、reporter 或 Web UI。

| owner | authority | 明确不拥有 |
|---|---|---|
| `ControlledOperationRepository` / Host supervisor | operation occurrence、approval binding、backend result、failure | 是否进入最终科学链 |
| `ScientificChainService` | selection revision、disposition set、adoption command、attempt closure | provider/tool execution、科学内容自动判断 |
| `ArtifactBoundaryService` | sealed bytes、read grant、materialization、digest revalidation | selection policy、operation replacement |
| workflow/scientific contract registry | versioned node roles、branch rules、reuse constraints | session 状态、actor decision |
| agent | 选择 adoption/supersession 理由、显式关闭 task/attempt | 伪造 actor、approval、bytes、toolchain/provider facts |
| offline verifier | 对 sealed bytes 和 canonical records做独立重算 | 事后选链、在线补查 provider |
| workspace projector / UI | safe read model 与 command surface | canonical adoption、closure、permission |

`ScientificChainService` 不能变成 deterministic workflow router。workflow contract 可以声明 node
role、dependency 和可复用限制，但 ordering、batching、何时修复 source、是否放弃 attempt 仍由 agent
决定。Harness 只确保 agent 看到完整事实并且提交的选择不违反世界约束。

## Proposed canonical objects

### `ScientificChainSelection@1`

```text
ScientificChainSelection@1
  selection_id                         # identifies this immutable revision
  attempt_id
  session_id / task_id / lane_id
  workflow_ref / workflow_manifest_digest
  scientific_contract_refs[]
  scope                              # formal | probe | fault
  branch_id / branch_derivation_digest
  revision
  state                              # draft | sealed | invalidated
  parent_selection_id?                 # previous immutable revision
  operation_universe_digest
  disposition_set_digest
  adopted_chain_digest
  selection_set_digest
  created_by / created_at
  sealed_by? / sealed_at?
  invalidated_by? / invalidated_at? / invalidation_reason_code?
```

`attempt_id` 必须是 Host launch 时注入的 canonical attempt authority，而不是路径名或 agent 文本。
`scope` 分离 formal、known-positive probe 与 fault chain；formal selection 不能采用 probe artifact。

`branch_id` 不能由 agent 任意声明。AOX verifier 仍从 sealed HMMER/UniProt/motif artifacts 推导 branch，
并要求 `branch_derivation_digest` 重现。selection 只在该 branch 下选择 reached nodes，不负责让一个
未达到的 branch 看起来合法。

每个 revision 获得新的 `selection_id`；`revision` 是同一 attempt/scope 内用于 CAS 和展示的单调
序号，`parent_selection_id` 指向前一 immutable revision。因此下游 canonical record 只引用
`selection_id`，不再重复保存一份可漂移的 `selection_revision`。

`state=draft` 可增加 disposition/materialization；`sealed` 后 immutable。改变选择必须创建新
revision，显式引用 parent，并只在旧 revision 尚未被 bundle/closure 采用时切换 authority。
`state` 是 create/seal/invalidation lifecycle facts 的 canonical projection；sealed row 不因后续
invalidation 被原位改写。`invalidated` 只用于发现 canonical prerequisite 漂移或 consistency
failure，由独立 append-only invalidation fact 投影，不能删除旧 revision。

### `ScientificOperationDisposition@1`

每个 disposition 是 append-only record：

```text
ScientificOperationDisposition@1
  disposition_id
  selection_id                       # exact immutable selection revision
  attempt_id / session_id / scope
  operation_id
  chain_node_key?                    # adopted/superseded 时必需
  disposition                       # adopted | superseded | failed | abandoned
  actor_ref / actor_kind
  reason_code / reason_summary?
  evidence_refs[]
  supersedes_disposition_id?         # 同一 operation 的显式 decision revision
  supersedes_operation_ids[]         # replacement/adoption 所替代的 occurrence
  adopted_effect_digest?             # adopted 时必需
  reuse_contract_digest?             # cross-run adoption 时必需
  source_materialization_ids[]
  effective_at / recorded_at
  disposition_digest
```

`actor_ref` 来自 authenticated principal 或 canonical resident agent identity，不能接受 caller 自报。
`reason_code` 使用 versioned closed taxonomy，例如：

- `canonical_first_success`；
- `local_consumer_repaired_reuse`；
- `explicit_safe_replacement`；
- `operation_terminal_failure`；
- `approval_rejected`；
- `never_dispatched`；
- `operator_abort`；
- `branch_not_selected`；
- `duplicate_effect_not_adopted`。

`reason_summary` 只允许 bounded、public-safe 解释，不能替代 code 或 evidence refs。时间来自 Host，
ordering authority 来自 selection revision、record id 和 durable event cursor，不依赖客户端时钟。

四种 disposition 的闭集语义：

| disposition | prerequisite | effect on chain |
|---|---|---|
| `adopted` | operation completed、Host result origin可信、output closure完整、node/reuse policy满足 | 是该 node 唯一有效 source effect |
| `superseded` | operation canonical status 为 `completed`，且另一 adopted operation 显式列出它 | 保留结果与 provenance，但不进入 selected chain |
| `failed` | canonical status 为 `failed` / `recovery_failed`，failure/effect closure完整 | 不进入链；本身不授权 replacement |
| `abandoned` | operation 未执行外部 effect，且 approval/continuation/run/backend 已闭合 | 不进入链；不得用于含 unknown effect 的 running/transport loss |

`superseded` 不能把 failed operation 改称 successful duplicate；failed operation 保持 `failed`，由
replacement 的 adopted disposition 在 `supersedes_operation_ids` 显式引用。相同 output digest 也不
自动产生 supersession。

一个 operation 在某 selection revision 中只能有一个 current disposition。若 agent 修正决定，必须
创建新 disposition 并设置 `supersedes_disposition_id`，同时以 expected selection revision 和旧
`selection_set_digest` 做 CAS。repository 不提供“按最新时间覆盖”语义。

### `ScientificEffectAdoption@1`

跨 sandbox run 的 adoption 必须有独立 command receipt：

```text
ScientificEffectAdoption@1
  adoption_id
  selection_id / chain_node_key
  source_operation_id
  source_sandbox_workspace_id / source_sandbox_run_id
  source_provenance_digest
  source_requested_effect_digest
  source_realized_effect_digest
  source_result_closure_digest
  reuse_contract_id / reuse_contract_digest
  target_sandbox_workspace_id / target_sandbox_run_id
  target_source_snapshot_digest
  permission_decision_ref
  approval_requirement_digest
  materialization_ids[]
  supersedes_operation_ids[]
  actor_ref / reason_code
  requested_at / committed_at
  adoption_digest
```

Adoption 只说明新 run 选择消费旧 effect。它不改变 source operation，也不创建一个“result copied”
的虚假 controlled operation。若下游 SDK/API 需要一个 handle，应返回 versioned
`AdoptedScientificEffectRef`，其中只含 adoption id、source operation、output artifact refs 和 safe
digests；不能伪装成新 `operation_id`。

### `ScientificArtifactMaterialization@1`

```text
ScientificArtifactMaterialization@1
  materialization_id / adoption_id
  source_artifact_id / source_content_digest
  source_operation_id
  target_session_id / target_sandbox_workspace_id / target_sandbox_run_id
  target_logical_path                     # normalized workspace-relative role
  mode                                    # readonly
  artifact_read_grant_digest
  source_blob_observation_digest
  materialized_content_digest / byte_size
  materializer_id / materializer_contract_digest
  state                                   # prepared | committed | failed
  prepared_at / committed_at?
  failure_code?
  materialization_digest
```

目标只允许 Host 注入的 workspace root 下 normalized relative path；record/public projection 不含 Host
blob path、runner path、storage URI 或 private locator。materializer 从 catalog id 解析 sealed blob，
重新计算实际 bytes digest，先写 sibling staging object，再执行 mode/size/digest 校验、fsync 和原子
publish。只有 `committed` record 可进入 adoption。失败 staging 不可见，不触发 provider/runner
fallback。

### `ScientificAttemptClosure@1`

```text
ScientificAttemptClosure@1
  closure_id / attempt_id
  session_ids[] / task_ids[] / scope_selection_ids[]
  outcome                                  # eligible_positive | scientific_empty |
                                           # failed | aborted | ineligible
  reason_code / failure_code?
  operation_universe_digest
  disposition_set_digests[]
  adopted_chain_digests[]
  unresolved_operation_ids[]               # eligible closure 必须为空
  open_approval_ids[] / open_continuation_ids[] / active_run_ids[]
  backend_effect_closure_digest
  artifact_closure_digest
  task_report_conversation_closure_digest
  micu_ledger_transition_digest
  closed_by / closed_at
  closure_digest
```

closure command 必须在短 UoW 中 CAS 当前 selection/operation universe，并写 canonical event 与
command receipt。它不把 provider/runner wait 包在事务里；若仍有 active/unknown external effect，
返回 structured blocker，attempt 保持 open/ineligible。

## Digests: provenance is not effect equivalence

当前 S12 `operation_digest` 包含 `sandbox_workspace_id`、source snapshot、input artifact ids/digests、
route、toolchain/provider config、expected outputs、resource/approval 等字段。它适合绑定一次批准的
operation intent，却不能同时承担 cross-run reuse identity：workspace 或 source snapshot 改变就会
漂移；反过来，只有 output bytes 相同又不足以证明两个 effect 等价。

建议 `@2` 明确分离四类 digest：

### `operation_provenance_digest`

绑定真实 occurrence 的完整身份：session/attempt、operation id、workspace/run、source snapshot、
approval、SDK envelope、route、provider/toolchain、backend request/run、timestamps、result origin、
input/output artifact ids/digests 与 terminal outcome。任何执行位置、授权或 lineage 不同都产生不同
provenance digest。

### `requested_effect_digest`

绑定 Host 实际要让外部世界执行的闭集语义，排除 operation id、sandbox/run id、客户端 timestamp
等 location/occurrence 字段，但至少包括：

- versioned SDK method、adapter/tool contract 和 normalized parameters；
- 有角色的 ordered input content digests；
- provider endpoint/database/query/cache-bypass/freshness contract，或 toolchain/runtime packaging/image
  prerequisite；
- selected backend/route policy 中会改变 effect 的部分；
- expected output contract、resource class 中会改变算法结果的字段；
- scientific calculation contract/implementation digest；
- permission class 与 external-effect class。

对于任意 sandbox-authored calculation，source snapshot 默认属于 effect identity，除非 operation 只
调用一个 Host-pinned versioned calculation，且 verifier 能从 installed implementation digest
重算。不能为了提高 cache hit 率把任意 Python source 从 effect identity 移除。

### `realized_effect_digest`

在 `requested_effect_digest` 上增加实际 provider request/response digest、retrieved-at/freshness
observation、runner-issued toolchain execution identity、backend outcome 与完整 output artifact content
digests。它证明“发生了什么”，不是第二个 approval digest。

### `reuse_contract_digest`

由 versioned reuse policy 对 `requested_effect_digest + realized_effect_digest + result closure + current
constraints` canonicalize。它明确哪些 occurrence-specific 字段允许变化，哪些约束必须保持：

- same attempt/session scope；
- source result origin 与 artifact sealing；
- provider freshness/cache policy；
- toolchain/provider/scientific contract compatibility；
- target permission/workspace policy；
- branch/node role与 output contract；
- replacement/side-effect policy。

reuse 必须由 named policy 计算；不能用 `operation_digest ==`、`content_digest ==` 或任意字段删除后的
ad-hoc JSON hash。policy version变化必改 digest。AOX blank-world `@2` 默认只允许 same-attempt
cross-run adoption；跨 attempt、probe-to-formal、fault-to-positive 和 campaign-to-campaign 永远不匹配。

## Selection and set digests

为了避免 collector 选择性查询，selection revision 必须绑定三个可离线重算的集合：

1. `operation_universe_digest`：对 attempt/scope 内所有 controlled operation 的
   `operation_id + operation_provenance_digest + terminal status` 按稳定 key 排序后计算；
2. `disposition_set_digest`：对该 universe 每个 operation 的 current disposition id/digest 按
   operation id 排序后计算；
3. `adopted_chain_digest`：对 branch reached node 按 workflow-declared node key，绑定 adopted
   operation/effect、input/output artifacts、materializations 和 dependency edges 后计算。

`selection_set_digest` 再绑定 workflow/branch/contract refs、以上三个 digest、selection revision 与
parent selection。任一新 operation、status transition、disposition revision、artifact materialization
或 branch drift 都使旧 digest 无法通过 CAS/closure；系统不得静默重算并把旧 command 套到新集合。

## State machine and command protocol

推荐命令面：

```text
scientific_chain.create(attempt_id, scope, workflow_ref, expected_operation_universe_digest)
scientific_chain.set_disposition(selection_id, expected_revision,
                                 expected_selection_set_digest, operation_id,
                                 disposition, reason_code, ...)
scientific_chain.adopt_effect(selection_id, expected_revision,
                              source_operation_id, target_run_id,
                              chain_node_key, reuse_contract_id, ...)
scientific_chain.seal(selection_id, expected_revision,
                      expected_selection_set_digest)
scientific_attempt.close(attempt_id, expected_selection_set_digests,
                         outcome, reason_code)
```

所有 mutation 使用 idempotency key、request digest、authenticated actor、short write UoW、durable
canonical event 与 immutable command receipt。重复相同 command 返回首次 receipt；同 key 不同
request冲突。CAS 失败向 agent 返回新 universe/revision 的 bounded facts，不自动重放其 decision。

建议状态流：

```text
operation occurrences become terminal
  -> draft selection binds complete occurrence universe
  -> agent records exhaustive dispositions
  -> optional Host-supervised effect adoption/materialization
  -> selection.seal validates exact adopted chain + all excluded closures
  -> tasks/reports/approvals/runs reach explicit closure
  -> scientific_attempt.close
  -> bundle @2 seals canonical closure snapshot
```

如果 selection seal 后又发现同 scope 的新 operation，repository 不修改 sealed selection；它写
`scientific_chain.selection_invalidated` consistency fact，attempt 不能 eligible close。若旧 selection
尚未进入 closure，可由 agent 创建新 revision；若已 sealed bundle，则该 bundle 按其 immutable
universe 验证，新迟到 fact导致 campaign consistency failure，不能改包。

## Cross-sandbox-run adoption protocol

一次合法 adoption 至少经过以下步骤：

1. agent 用 bounded query 查看 source operation、result closure、output artifact refs、当前 selection
   revision 与 target run identity；不能从 `/workspace/work` 文件名猜 source。
2. Host 确认 source operation 属于同 attempt/允许 scope，status completed，adapter result origin 是
   Host-confirmed，approval 为 source execution 的真实 authorization，且 provenance digest可重算。
3. reuse policy 重算 requested/realized effect 与 `reuse_contract_digest`；provider freshness、toolchain、
   workflow、branch、scientific implementation、target permission任一漂移即 fail closed。
4. Host 对 target session/task/workspace 做 access check；目标 run 必须 active、owned、fenced，且没有
   与 logical target path 冲突的 mutable/symlink entry。
5. ArtifactBoundaryService 逐个 materialize source artifacts。catalog digest、actual blob bytes、size、
   format 和 grant全部重验；每个 committed materialization均有独立 receipt。
6. ScientificChainService 在一个短 UoW 中 CAS selection revision，写 adoption、source operation 的
   adopted disposition、被替代 operation refs、materialization refs、canonical events 与 command
   receipt。
7. target sandbox 只收到 readonly artifact refs/paths 和 `AdoptedScientificEffectRef`。后续 local
   code 或 controlled operation显式把这些 refs 作为 input；Host provenance保留 source operation与
   adoption edge。
8. 若 materialization 或 CAS 失败，不写 adopted disposition；已安装但未被 adoption commit引用的
   target object按 orphan policy清理，不能被 agent当作已采用 evidence。

这条协议复用 effect，不复用进程、continuation、approval lease、HPC workspace、runner handle 或
mutable checkpoint。source sandbox 可已结束；source sealed artifacts 与 canonical operation必须仍在
attempt retention内。

## Approval and permission invariants

1. 原 approval 只授权 source operation 当时绑定的完整 digest；它永不授权第二次 provider/runner
   execution。
2. pure adoption/materialization 是新的 Host command。它通常不重复收费/外部 effect，但必须通过
   session access、artifact read grant、target workspace write/materialize policy；policy要求时产生
   独立 adoption approval。
3. operation 参数、input、provider/toolchain、expected output 或 external-effect class变化必须创建
   fresh operation 与 fresh approval；不能通过 adoption规避。
4. rejected/superseded/expired approval不能作为 source execution authority。已 approved 且 completed
   source operation可保留历史 authorization，但 permission撤销可以阻止新 materialization。
5. actor来自服务端认证。浏览器、agent tool payload、bundle或 projection中的 `actor_ref` 不能提升
  权限。
6. public read permission不等于 artifact byte permission；project相同不自动跨 session adoption。
7. adoption command receipt要同时绑定 source approval ref、current permission decision ref 与 target
   grant digest，三者语义不能折叠为一个 `approved=true`。

## Provider, toolchain, workspace and scientific constraints

### Provider effects

- exact provider、endpoint/database、query/accession set、pagination、cache bypass、response digest、
  retrieved-at 与 provider config identity必须完整。
- reuse policy显式定义 freshness window；blank-world同 attempt内可采用已经真实获得的 response，
  但跨 independent attempt禁止，即使 accession和bytes相同。
- degraded/enrichment evidence不能升级为 required evidence；empty outcome只能按 branch contract采用。
- transport失败且 adapter effect未知不能 disposition为 abandoned。只有 bounded request identity、
  provider receipt和 side-effect closure证明无可用 result时才可 failed close。

### Toolchain effects

- input digests、normalized parameters、route policy、runtime packaging、runner-issued toolchain identity、
  image digest、command template/contract、execution mode/scope与 expected outputs必须满足 reuse policy。
- 相同 output bytes不能替代 toolchain identity；不同 toolchain/parameter的偶然同输出仍是不同 effect。
- HPC workspace/runner run不转移到 target sandbox。只 materialize catalog outputs；private remote path、
  SSH target和scheduler handle永不进入 public adoption。
- source tool operation若 output validation、fetch或artifact registration不完整，不能 adopted；必须先有
 闭合 result/artifact lineage。

### Workspace and source

- target workspace/run必须是同 attempt内 Host-issued canonical identity，带 current owner/lease/fencing。
- source snapshot变化保留在 provenance。它是否影响 effect reuse由 method-specific policy决定，不能
 由 agent随意删字段。
- arbitrary sandbox calculation默认不跨 run复用；AOX installed versioned calculations只有在 contract、
  implementation、input/output digest全部可离线重算时才可采用其 sealed result。
- `/workspace/work` checkpoint可帮助同 run source repair，但不进入 selection/bundle，也不替代
  materialization receipt。
- target path冲突、symlink、preexisting mutable bytes、digest mismatch或partial install全部 fail closed；
  不覆盖、不择优、不改名躲避。

## Replacement and failure closure

允许 adoption 不等于允许任意 retry。每个 versioned chain node 必须声明
`replacement_policy_id`：

```text
never
same_effect_after_proven_no_dispatch
same_attempt_after_terminal_no_unknown_effect
explicit_operator_override_non_cutover
```

AOX cutover初始应从最窄 policy开始。failure classification至少区分：

- `pre_dispatch_no_effect`；
- `dispatch_rejected_no_effect`；
- `backend_completed_result_closed`；
- `backend_effect_failed_closed`；
- `effect_unknown`；
- `result_persistence_failed_after_effect`。

只有 policy明确允许且 failure closure证明不存在 unknown effect时，agent才可创建 replacement
operation。`retryable=true` 仍只是 agent-visible事实，不是 replay authority。未知 provider/runner
effect、失联 running process、未终结 continuation、未关闭 approval或未审计 output都会让 attempt
closure失败。

attempt failure/abandon closure必须穷尽检查：

- 所有 controlled operations terminal，或有可验证的 pre-dispatch abandonment；
- 所有 approvals与 continuations closed；
- sandbox runs/processes与 backend requests无 active/unknown owner；
- 每个 formal/probe/fault operation有一个 current disposition；
- 所有 materializations committed或 failed且不可见；
- fixed deliverables、draft/report和task状态与 outcome一致；
- MICU/provider/runner账本已收口，保守 reservation不能被删除；
- events、conversation、artifact namespace与 final response形成 negative-state closure。

失败 attempt也应尽可能 seal `@2` bundle，但 `cutover_eligible=false`。无法证明 effect closure时可 seal
诊断 bundle，必须标记 `closure_complete=false` 和 unresolved ids；它不能进入 campaign GO reducer。

## Bundle and offline verifier `@2`

建议新增 `aox_blank_world_attempt_bundle@2`，不扩写 `@1` 的语义。payload 在现有 identity、clean
world、MICU、provider/toolchain、task、artifact、report和 scientific checks基础上增加：

```text
operation_occurrences[]              # 全量，不只 adopted
scientific_chain_selections[]        # exact canonical revisions
operation_dispositions[]             # 全量 current + superseded history
effect_adoptions[]
artifact_materializations[]
attempt_closure
operation_universe_digest
selection_closure_digest
```

eligible positive 的 `@2` verifier至少执行：

1. 重算 attempt/scope 的完整 operation universe，拒绝漏项、重复 identity、未知 schema与隐藏
   failed operation；
2. 重算每个 provenance/requested/realized/reuse digest，禁止把 bytes equality当 effect equality；
3. 对每个 operation建立唯一 current disposition，验证 supersession lineage无环、没有悬空 ref；
4. 从 sealed scientific bytes独立推导 AOX branch，要求每个 reached node恰有一个 adopted effect，
   omitted node与 empty reason一致；
5. 验证 adopted source operation completed、Host result origin、approval、permission、toolchain/provider
   constraints及 replacement policy；
6. 逐个重算 materialized bytes、catalog lineage、target workspace/run与 readonly handoff，不信任 target
   path内容自报；
7. 验证 adopted chain dependency edges：下游 input必须绑定 adopted output或其 exact materialization；
8. 要求所有 unadopted operation均有合法 superseded/failed/abandoned closure；unknown effect立即拒绝；
9. 重算 operation/disposition/adopted-chain/selection/attempt closure digests与 canonical event/command
   receipts；
10. 继续执行 motif、similarity、literature、report claim、known-positive probe、fault seam、browser和
    MICU等现有离线检查。

`@2` verifier不联网、不读取 SQLite、不扫描 sandbox working tree，也不根据 report prose决定 chain。
bundle必须携带可公开验证的 closed records和sealed artifacts。private permission/provider/runner details
通过安全 digest/attestation projection绑定；缺失时拒绝，不要求 verifier访问 secret。

### Tamper cases that must fail

- 删除 failed/abandoned operation或 disposition；
- 把 `superseded` 改成 `adopted`，或改变 actor/reason/timestamp/supersedes ref；
- 用相同 bytes替换不同 operation/artifact identity；
- 只改 target path文件而不改 materialization receipt；
- 把 probe、fault或另一 attempt artifact连到 formal selection；
- 更换 provider config、toolchain image、route policy、scientific implementation或 freshness policy；
- 复用旧 permission/approval digest，伪造新 target授权；
- 在 selection seal后增加 operation但保持旧 universe digest；
- 把 `effect_unknown` failure改称 abandoned；
- 省略 active approval/continuation/backend request；
- 将 `@1` bundle/schema字段包装成 `@2`。

## Public projection and UI

workspace projection建议增加只读 `scientific_chain` 区域：

```text
scientific_chain
  attempt_id / scope / workflow_ref / branch
  selection_id / revision / state / safe set digests
  nodes[]
    chain_node_key / method / status
    adopted_operation_ref / effect digest
    source_run_ref / target_run_ref
    materialization state
  excluded_operations[]
    operation_ref / method / disposition / reason_code / failure_code
  closure
    outcome / complete / unresolved counts / safe blockers
```

UI必须同时展示：

- adopted operation与其 source run；
- cross-run materialization badge与 target run；
- superseded/failed/abandoned operation，不默认隐藏；
- selection revision/set digest drift；
- open approval、unknown external effect和 closure blocker；
- “selection是 agent显式提交”而不是“系统自动选最新成功”。

UI按钮只能调用 canonical command route并提交 expected revision/set digest。浏览器 reducer、DOM顺序、
checkbox或 local state没有 authority；command成功后以 canonical event/receipt刷新 projection。public
projection隐藏 prompt、private path、provider credential、SSH/Slurm locator、raw permission policy与
unbounded error body。

建议事件使用明确类型与 closed payload schema：

- `scientific_chain.selection_created`；
- `scientific_chain.disposition_recorded`；
- `scientific_chain.effect_adopted`；
- `scientific_chain.materialization_committed`；
- `scientific_chain.selection_sealed`；
- `scientific_chain.selection_invalidated`；
- `scientific_attempt.closed`。

projection activity不能反向写回这些 canonical facts；event command/projection taxonomy仍应遵守
[canonical approval command vs activity projection](canonical-approval-command-vs-activity-projection-events.md)
的分界。

## Persistence, concurrency and recovery

单进程 SQLite 近期保持不变，但新对象仍需严谨 transaction ownership：

- 新 tables使用 immutable ids、foreign keys、unique constraints与 append-only/transition triggers；
- selection revision和 current authority pointer在一个 `BEGIN IMMEDIATE` UoW 中 CAS；
- domain mutation、durable event、command receipt同事务提交；
- materialization/provider/runner等待不持有 write transaction；以 prepared record、lease/fencing和后续
 短 UoW收口；
- crash后恢复 prepared materialization，先核对 source/target digest和 fencing，不盲目重 copy；
- sealed selection/closure不可 update/delete；correction创建 superseding revision；
- operation status在 universe snapshot后漂移会 invalidate draft/sealed selection，绝不静默吸收；
- repository query默认返回完整 universe与 bounded pagination proof，不能因分页漏掉 excluded
 operation。

当未来转向多进程或远端 store时，CAS、idempotency、fencing和 append-only语义必须保持；不能把
SQLite serialization偶然性当作设计保证。

## Compatibility and migration

1. **Freeze current semantics.** 明确 `aox_blank_world_attempt_bundle@1` 只接受 exact occurrence set；
   strict selectors/pre-approval guard继续服务当前 Goal。
2. **Schema/design phase.** 固定 selection/disposition/adoption/materialization/closure schemas、digest
   canonicalization、reason/failure/replacement taxonomy与 threat model，不改 live acceptance。
3. **Shadow universe.** 对新 non-cutover sessions只读计算 occurrence universe和候选 effect digests，
   与现有 verifier比较；shadow数据不产生 adoption authority。
4. **Add canonical tables/API.** 按 current SQLite migration doctrine升级 schema version；旧本地库
   fail fast并由 operator使用 fresh DB，不做隐式原位修复。
5. **Canary adoption.** 仅 non-cutover workflow允许 same-attempt cross-run materialization；现有 execution
   route仍是对照，任何 mismatch NO-GO。
6. **Publish bundle/verifier `@2`.** 先验证 synthetic/property corpus与真实 non-cutover evidence；`@1`
   reader保持只读历史支持。
7. **AOX opt-in.** 新 workflow major version显式选择 `@2`；同一 attempt不能混用 `@1` exact selector
   acceptance与 `@2` adoption acceptance。
8. **Live qualification.** 重新执行独立 blank-world positives、fault和 Chrome proof；旧 r12b及其他
   campaign不可充当 positive。
9. **Retire legacy new-write path.** 确认 CLI/UI/API/verifier/operator及外部调用方无依赖后，停止新建
   `@1` bundle；历史 verifier永久保留其原始语义。

rollback只能关闭 `@2` route并让要求 adoption保证的 campaign保持 NO-GO；不能在 `@2` 失败后降级
为“选唯一 completed”或重写历史 disposition。shadow/canary records不得混入正式 bundle。

## Security and scientific-integrity threats

- **Selective-history laundering:** collector只导出 adopted operations。缓解：universe digest + 全量
  dispositions + repository/bundle completeness proof。
- **Same-bytes conflation:** 两次 MAFFT同 bytes被合并。缓解：provenance/effect/result/reuse digests分离，
  bytes只是一项 result事实。
- **Approval laundering:** 旧 approval授权新 execution。缓解：source approval只证明 source occurrence；
  adoption与 fresh execution使用独立 permission/approval。
- **Actor forgery:** agent/UI自报 operator actor。缓解：server-authenticated actor、command receipt和event
  binding。
- **Stale selection race:** agent基于旧 operation set提交 adoption。缓解：revision + universe/set digest CAS。
- **Projection authority confusion:** UI latest/success badge成为选择。缓解：UI只投影 canonical selection，
  command route closed schema。
- **Artifact substitution/TOCTOU:** source catalog digest正确但 blob/target bytes被换。缓解：materialize前后
 重哈希、staging/fsync/atomic publish、readonly、receipt digest。
- **Workspace escape:** target path含绝对路径、`..`、symlink或 private root。缓解：Host normalized logical
 path、no-follow/beneath resolver和 public-safe projection。
- **Cross-authority contamination:** probe、fault、另一 session 或另一 attempt 的结果进入 formal。
  缓解：以单一 attempt/session/scope authority约束 source，并与 reuse policy硬绑定。
- **Provider freshness laundering:** 旧 response冒充 cache-bypassed live。缓解：provider retrieval/freshness
  contract进入 effect/reuse digest；跨 attempt禁用。
- **Toolchain drift:** 同 output掩盖不同 image/parameters。缓解：runner identity、contract/image/input/params
 进入 effect与 verifier。
- **Failure laundering:** running/unknown effect标 abandoned。缓解：closed failure taxonomy、backend/approval/
 continuation closure；unknown永不 eligible。
- **Supersession cycle:** A supersedes B，B supersedes A。缓解：repository DAG/unique constraints与 verifier
  cycle check。
- **Reason injection/secret leak:** free text含 credential/path。缓解：closed reason code、bounded scrubbed
  summary、private evidence只以 digest/ref出现。
- **Adoption replay:** 相同 receipt对不同 target复用。缓解：idempotency request digest绑定 source、target、
  selection revision、grant与 materialization set。

## Test strategy

### Domain, digest and repository tests

- 每个 schema使用 exact-key/closed enum验证；unknown/extra/non-finite/private fields拒绝。
- disposition状态机、supersedes lineage、selection revision和 attempt closure property tests。
- operation universe/disposition/adopted chain/set digest对排序稳定；任一语义字段变化必改变对应 digest。
- provenance相异但 realized output bytes相同的 operations保持两个 occurrence。
- authenticated actor覆盖 caller伪造 actor；timestamp由 Host产生。
- CAS、idempotent retry、same-key drift、concurrent disposition和 late operation invalidation测试。
- sealed selection/closure append-only trigger与 rollback时无 event/receipt泄漏。

### Artifact/materialization tests

- same-attempt cross-run正向：真实 sealed artifact从 source workspace物化到 target，只读 bytes/digest一致，
  不创建 provider/tool operation。
- catalog/blob digest mismatch、source missing、target preexisting、symlink、path escape、partial write、fsync/
  rename失败全部 fail closed。
- permission revoked、wrong session/task/attempt、stale run lease/fencing、probe-to-formal与 fault-to-positive拒绝。
- crash在 prepare、copy、publish、selection commit各点恢复，无 adopted disposition指向未 committed bytes，
  orphan不可被 sandbox消费。

### Provider/toolchain/reuse policy tests

- normalized request相同但 provider config/freshness/cache policy漂移不能 reuse。
- MAFFT相同 bytes但 input、parameter、image、template或 route变化不能合并。
- arbitrary sandbox source snapshot变化默认阻止 calculation reuse；pinned calculation只有 exact
  contract/implementation/input/output可采用。
- source completed + local parser failure后，新 run显式采用 source response；provider/runner调用计数不增。
- failed pre-dispatch operation可按允许 policy replacement；effect unknown、post-dispatch persistence failure
 和 active backend一律阻止 eligible closure。
- 原 approval、new adoption permission与 fresh execution approval分别测试，互不替代。

### Bundle/verifier adversarial tests

- 对每个 disposition字段、supersedes edge、actor/time、effect/reuse/set/closure digest逐一篡改。
- 删除或增加 operation/disposition/materialization，改变 branch/node或下游 input edge。
- 把 identical-content artifact id替换成另一个 provenance，验证失败。
- canonical JSON duplicate key、noncanonical bytes、symlink、unreadable artifact、secret/private path corpus。
- `@1`/`@2` cross-wrap、legacy fallback、unknown schema与 historical r12b retrofit全部拒绝。
- verifier离线运行，网络被禁用，结果与 SQLite/UI/working tree无关。

### Integration and live E2E

1. non-cutover真实 provider/HPC：第一次 run完成 operation后注入本地 parser failure；第二个 sandbox run
   显式 adoption/materialization并继续下游，证明没有重复 external dispatch。
2. 创建两个 completed identical-output tool occurrences，agent显式 adopted一个、superseded另一个；bundle
   保留两者并通过 `@2` verifier，删除任一个即失败。
3. failed/unknown effect场景保持 ineligible，后续 successful replacement也不能越过 policy。
4. 真实 permission撤销、toolchain drift、provider freshness与 target artifact byte flip分别 fail closed。
5. Chrome UI展示 adopted与 excluded history；用户命令含 exact selection revision/set digest，reload/reconnect
   后一致，DOM状态不影响 authority。
6. AOX正式 qualification必须重新完成两次独立 positive和一次 controlled fault；attempt roots、sessions、
   operations、MICU segments与 browser proof全部独立，任何 r12b evidence只作 negative regression fixture。

## Phased acceptance gates

### Phase 0 — specification freeze

- schemas、owner、digest字段、reason/failure/replacement taxonomy和 public/private边界评审完成；
- r12b selective-success、same-bytes、post-dispatch persistence failure成为不可删除的 threat fixtures；
- 明确哪些 operation kinds可 reuse，默认 `never`。

### Phase 1 — shadow facts

- current sessions可生成稳定 universe/effect candidates，但没有 command/adoption side effect；
- shadow结果与 `@1` exact-operation verifier零漂移；
- shadow字段不进入正式 workspace/report/bundle。

### Phase 2 — canonical control plane

- selection/disposition/closure repository、UoW、events、receipts、CAS、access control和 safe projection落地；
- agent可显式选择，Harness不自动选择 latest/success；
- unresolved/unknown operation无法 seal selection或 close eligible attempt。

### Phase 3 — cross-run materialization canary

- Host artifact boundary完成 same-attempt readonly materialization，crash/fencing/permission tests通过；
- pure adoption不会创建新 controlled operation或触发 provider/runner；
- output lineage同时回链 source operation、adoption、materialization和 target consumer。

### Phase 4 — bundle/verifier `@2`

- verifier能穷尽验证 occurrence/disposition/adoption/closure，tamper corpus全部失败；
- historical `@1`结果保持原样，不能被 `@2` reader升级；
- public bundle不含 private locator、permission detail、credential或 mutable path。

### Phase 5 — AOX opt-in qualification

- 新 workflow/schema major显式启用 `@2`；缺任一新 record/digest直接 NO-GO；
- 两次全新独立正向 live E2E、一次 fail-closed fault与真实 Chrome proof在同一 pinned commit/config通过；
- MICU/provider/HPC账本证明 adoption未重复外部 effect，且没有 hidden fallback。

### Phase 6 — compatibility retirement

- CLI、Host API、UI、workflow packs、verifier、operator tooling与所有外部调用方审计完成；
- 停止新写 `@1` adoption-incompatible路径，保留历史只读 verifier；
- rollback、schema mismatch和 fresh SQLite operator流程有运行手册与演练证据。

## Final acceptance criteria

- canonical `ScientificChainSelection` 是唯一 adoption authority；任何 latest-result、bytes equality、UI
  state或 report prose都不能改变选择。
- attempt/scope内所有 operation occurrence均进入 universe并获得可验证 current disposition；没有 hidden
  failed、unknown或 active effect。
- adopted/superseded/failed/abandoned均绑定 actor、reason、Host timestamps、supersession lineage和 set
  digest；修改任一字段导致 command CAS或 offline verification失败。
- provenance、requested effect、realized effect与 reuse contract身份明确分离；相同 bytes不会合并不同
  execution facts。
- cross-sandbox-run adoption只 materialize verified sealed artifacts，保留 source provenance，不伪造新
  completed operation，不复用旧 execution approval。
- approval、permission、workspace lease/fencing、toolchain/provider/scientific contract任一不满足时 fail
  closed，无 provider/runner、Host-local或 mutable checkpoint fallback。
- bundle/verifier `@2`能离线重算 complete selected chain与所有 excluded operation closure，并拒绝所有
  tamper、cross-scope、legacy-wrap和 unknown-effect场景。
- public projection/UI低摩擦展示 adopted与 excluded history及 closure blockers，同时不泄露 private
  locator、credential、Host/runner path或 authority-bearing token。
- 当前 Goal仍只声称 strict selectors + pre-approval budget guard；在以上 phases全部完成并重新执行真实
  qualification前，不得把本提案描述为已实现，也不得把 r12b从 NO-GO改写为可采用结果。
