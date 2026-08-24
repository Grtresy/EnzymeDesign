# Adopted: request-lineage workflow authority

Status: adopted by OpenSpec change
`complete-openzyme-resident-teammate-product-loop` on 2026-08-24. The stable product contract is
[Resident Teammate 产品闭环](../resident-teammate-product-loop.md); this document retains the threat model、
causation analysis and migration history behind that contract.

The earlier 2026-07-26 projection hardening closed only the model-facing compaction/empty-selection ambiguity.
The adopted change adds the previously deferred durable multi-hop binding, causal signal link, epoch/revocation,
subset delegation and exact-registry resolution. New Sessions use that closed path directly; legacy rows are not
silently upgraded by scanning conversation prose or latest/all selections.

## Historical decision boundary before adoption

当前 Goal 只修复一个局部且已经被真实路径触发的 authority 丢失：
`POST /v3/sessions/{session_id}/messages` 接收显式、完整、digest-pinned 的
`skill_keys` 后，将去重结果与同一 canonical user conversation document 持久化；
scheduler claim 该消息直接产生的 `agent:master + INBOX_UNREAD` signal 时，从
`source_ref` 指向的 exact user message/document 恢复 focus。这样 message admission
与 background/manual drain 分离后，第一次 master turn 不会丢失 caller 明确选择的
workflow。

该修复有意保持窄边界：

- 它只覆盖 admission 到 exact first drain/claim；
- 普通发给 master 的 agent protocol inbox signal 合法运行，但不获得 user workflow
  authority；
- conversation binding 损坏、跨 session、类型漂移或 ref 非法时，在 provider call 前
  fail closed；
- `AgentRuntimeSignal` 不新增 `skill_keys`，`/runtime/drain` 也不能提交或扩张 authority；
- teammate 继续只从 durable delegation request 的显式 `workflow_refs` 子集和 manifest
  snapshot 恢复自己的 binding。

这不解决 request lineage 跨后续 causal wake 的持续 authority。尤其是 teammate 结果
产生的 master wake 当前使用 `MANUAL_RESUME`，其 `source_ref` 是前序 runtime signal，
不是原始 user message。如果 master 合法地选择“先委派 researcher，等待结果，再委派
executor”，后续 master turn 无法再次证明原 entry message 的 workflow authority。强迫
master 在第一次 turn 内预先创建并委派全部任务会损害 agent 的策略自由，不能作为长期
架构答案。

跨 user message、task、delegation、protocol、approval 和后续 wake 持久化同一份受控
authority，会改变 control-plane schema、causation、revocation、scheduler restore 和迁移
语义，因此已由独立 OpenSpec change 作为纠正性闭合变更实施，而不是继续扩大旧 AOX/HMM Goal。

## Adoption 前的 implementation evidence and gap

当前边界已经具备可复用基础：

1. Public message ingress 持久化 conversation document 与 inbox message，再以 message id
   作为 master `INBOX_UNREAD` signal 的 `source_ref`。这足以恢复第一次 turn，且避免把
   request-local `SessionRuntimeContext.active_skill_keys` 当 durable truth。
2. `RestoreFocus.skill_keys` 是一次 harness invocation 的显式 focus；registry 在 provider
   call 前解析 exact workflow ref、manifest digest 和 knowledge document digest。
3. `task.delegate.workflow_refs` 只能选择 caller 当前 authorized refs 的显式无重复子集；
   delegation request 持久化 refs 与 manifest snapshot，teammate restore 再验证 role、tool、
   capability 和 drift。
4. `AgentRuntimeSignal.source_ref` 当前表达 wakeup source：user/protocol inbox message、task、
   approval、invocation 或前序 signal。它不是通用 authority reference，也不能同时稳定表达
   原始事件和跨多跳 request lineage。
5. teammate 收口后排队给 master 的 signal 绑定 task、lane、correlation 和前序 signal，
   但没有原 entry message 或 authority binding identity。
6. approval、engine completion、manual recovery 和 protocol follow-up 也各有自己的 canonical
   source。扫描 session 中“最近”或“任意”带 workflow 的 conversation document虽然能找回
   refs，却无法证明该 source 与当前 wake 属于同一 user request。

因此 adoption 前局部修复的真实语义是 **source-message turn-scoped authority**，不是
**request-lineage authority**。本次 change 以 durable binding 与 causal link 取代该局部恢复规则；这段清单
保留用于证明为什么不能继续依赖 source-message fallback。

## Agent and harness impact

- master 应能根据科学证据和 teammate 结果自由选择串行、并行或延迟委派；authority 的
  生命周期不能迫使它把所有委派塞进第一 turn。
- harness 应忠实呈现“当前 turn 由哪个显式 user request 授权、有哪些 exact refs、是否已撤销”，
  但不得根据关键词、task kind、最近消息或 operator drain 参数推断 workflow。
- teammate 只获得 master 显式委派的 compatible 子集；master 的完整 authority 不因 parent-child
  关系自动扩散。
- compaction、Host restart、signal reclaim 和 worker thread repository rebuild 后，authority
  identity 必须可从 canonical control plane 恢复，而不是依赖进程内 context。
- invalid、revoked、expired、drifted 或无法证明 causation 的 binding 必须在 provider/tool side
  effect 前失败；不能静默退化为空 workflow 后继续消耗 MICU 或执行普通路径。
- authority 只约束可加载的 versioned workflow knowledge/capability contract，不替 agent 决定
  task DAG、工具顺序、重试、科学早停或 business completion。

## Threat model

本提案至少防御以下边界错误；它不以恶意 Host 内核或数据库管理员为对手：

1. **Ambient session authority**：历史某条 user message 选择过 workflow，后续无关 request
   被错误继承。
2. **Authority union**：两个并发或相邻 user message 的 refs 被合并，使任一 caller 获得自己
   未明确选择的 workflow。
3. **Latest-message confusion**：scheduler 扫描 latest conversation，而当前 signal 实际属于
   更早的 task/delegation lineage。
4. **Protocol injection**：agent 在普通 `protocol_payload` 中伪造 `skill_keys`、workflow ref 或
   authority id，从而扩大 master/peer authority。
5. **Signal duplication/drift**：把 raw `skill_keys` 复制进每条 signal 后，conversation、delegation
   和 signal 三份值发生分歧，worker选择最宽的一份。
6. **Cross-session/cross-principal reuse**：一个 opaque ref 被另一 session、project 或无 access
   principal 重放。
7. **Causation spoofing**：同 session 的无关 task completion、approval 或 manual resume 指向一个
   活跃 authority binding。
8. **Registry drift**：binding 创建后 manifest/knowledge/tool requirement 漂移，runtime仍按旧名称
   或近似版本继续。
9. **Revocation race**：worker读取 active 后，caller撤销，旧 worker仍发 provider/tool side effect
   或写回新的 delegation。
10. **Stale worker replay**：signal/session lease过期后旧 worker携带缓存 authority迟到写回。
11. **Compaction loss**：prompt/memory compaction删除显式选择，runtime从自然语言 summary重新猜测。
12. **Empty-selection ambiguity**：新 user message显式不选择 workflow，却因旧 session state获得
    隐式继承。

## Target invariants

1. workflow authority 只能由 authenticated public user action或另一个已经验证的 canonical
   server-owned derivation产生；模型文本、task subject、protocol payload和operator drain参数都
   不是 authority source。
2. 每个 user request lineage 有唯一、versioned、durable binding identity；显式空选择同样形成
   “无 workflow”边界，不能回退到上一条 message。
3. authority 与 `session_id + project/session access owner + source_message_id + source_document_id`
   exact 绑定；跨 session/project/principal lookup一律拒绝。
4. runtime signal 只携带 opaque `authority_ref` 或由独立 signal-authority link表关联；**raw
   `skill_keys` 永不进入 signal row、event或claim payload**。
5. signal 的 event `source_ref` 与 authority identity保持分离：前者解释为何 wake，后者证明当前
   turn可使用哪些 workflow。不能复用一个自由字符串同时承担两种语义。
6. 任一 turn最多绑定一个 request authority lineage。多个 lineage coexist时不得自动 union；如
   未来需要组合，必须创建显式、versioned composition record，并逐一验证 caller authority。
7. downstream causal wake只有在 canonical task/delegation/protocol/approval/operation链可证明时
   才继承同一 opaque authority ref；仅有相同 session、task subject、role或时间邻近不够。
8. `task.delegate` 仍要求 agent显式选择 parent binding 的无重复子集，并创建 derived child
   binding/manifest snapshot；未选择 teammate不继承任何 workflow。
9. 每次 provider call、受控 tool side effect和 canonical delegation commit前都重新验证 binding
   status、epoch、session fence和registry drift。一次 preflight不能替代 commit fence。
10. revoke/expire/consume 后旧 epoch不可用于新 provider/tool/delegation；迟到 worker写回按 session
    lease与authority epoch双重拒绝。
11. authority binding不拥有 task、approval、operation、artifact、report或business completion，
    也不成为第二套 workflow graph/scheduler。
12. public projection只暴露 stable binding id、schema/version、status、source/lineage identity和
    safe exact refs或digest；不得暴露 lease token、principal credential、private path或内部 locator。
13. legacy record缺失 authority不能通过扫描历史 conversation补造。可证明的 exact source message
    才能做一次 deterministic migration；其它情况保持 authority-empty或显式 migration failure。
14. background、manual drain、recovery和测试 scheduler必须消费同一 authority resolver；不得各自
    实现 fallback。

## Proposed control-plane model

建议引入窄的 versioned authority record，而不是把 workflow选择塞进 `AgentMember`、task自由文本
或 signal JSON：

```text
WorkflowAuthorityBinding@1
  authority_id                         # opaque, Host-issued
  session_id / project_id
  request_lineage_id
  source_message_id / source_document_id
  source_principal_id / access_owner_version
  authorized_actor_id                  # initial owner: agent:master
  selected_workflow_refs[]             # normalized exact digest refs
  selected_refs_digest
  registry_snapshot_digest
  parent_authority_id                  # derived binding only
  derivation_kind                      # user_selection | delegation_subset | explicit_composition
  scope_kind / scope_ref               # request lineage, optional task/delegation child
  status                               # active | revoked | expired | consumed
  authority_epoch
  created_at / updated_at / terminal_at
  revocation_reason / terminal_event_ref

RuntimeSignalAuthorityLink@1
  signal_id
  authority_id
  authority_epoch
  causation_kind
  causal_source_ref
  created_at
```

`RuntimeSignalAuthorityLink` 可以实现为 `AgentRuntimeSignal@next` 的 nullable opaque
`authority_ref + authority_epoch`，也可以是独立一对一表。选择应以 migration、projection和索引
复杂度为准；两种方案都禁止 raw refs/manifest snapshot进入 signal。独立表的优点是保持 signal
调度 schema窄且可对历史 signal明确无绑定；signal字段的优点是claim时少一次 join。不得同时
实现两套可写 authority link。

`registry_snapshot_digest` 只用于证明 binding创建时看见的 registry identity；每次实际使用仍需
根据 `selected_workflow_refs` 对当前 authoritative registry重放 exact manifest/knowledge digest
验证。它不能成为绕过 current drift检查的缓存。

Derived delegation binding必须存 parent authority、选中子集和完整现有 delegation manifest
snapshot。parent撤销策略按 versioned policy传播，不能由 teammate自行解除。普通 protocol
message不创建 derived binding，也不能从 payload指定 `authority_id`。

## Causation and propagation rules

### Root user request

Public message admission在一个短 Unit of Work中原子写入：

- canonical conversation document（内容与 normalized explicit selection）；
- user inbox message；
- `WorkflowAuthorityBinding@1` root record，包括显式空选择；
- master `INBOX_UNREAD` signal及其 authority link；
- public/audit events与必要outbox通知。

任何一步失败都不能留下“有消息无 binding”或“有 signal 指向未提交 binding”的半状态。当前 Goal
的局部 conversation-document修复可先独立存在；本提案实施时再收敛原子 UoW。

### Master turn and delegation

scheduler claim后在 worker自己的 fresh repository scope中：

1. 以 signal id读取唯一 authority link；
2. 校验 session、actor、source causation、status/epoch和session lease；
3. 解析 exact refs并对 registry重验；
4. 构造本 turn 的 `RestoreFocus`，不修改 session-global ambient focus；
5. `task.delegate` 只接受该 binding的显式子集，并原子写 derived child binding、delegation request、
   inbox和teammate signal/link。

master turn结束不会自动消费 root binding；是否仍可用于同 lineage后续 turn由 closed lifecycle
policy决定，而不是由模型输出文本决定。

### Teammate result to master

teammate completion/failure/blocking产生 master wake时，Host从 canonical delegation child binding、
task assignment、correlation thread和originating signal重建 causation。只有完整链都指回同一个 active
root authority，才给新的 master signal写 root `authority_ref + epoch`。这样 master可在 researcher
结果后再选择 executor binding，而不要求预先固定 task DAG。

teammate不能通过 result payload声称另一个 authority。若 task被重新分配、correlation漂移、parent
binding撤销或链条缺失，wakeup仍可作为普通事实送达，但 privileged workflow authority必须
fail closed；是否允许一个 authority-empty diagnostic turn应由明确 error taxonomy决定，不能静默
伪装成正常 continuation。

### Protocol, approval and engine completion

- 普通 agent protocol inbox默认无 authority继承。只有 Host生成、与现有 lineage/operation exact
  绑定的 continuation message可以建立 authority link；caller payload里的同名字段一律忽略或拒绝。
- approval resolve不能选择 authority。agent-level resume或 Host-owned continuation terminal后，
  server从 approval/operation/originating tool call的 durable chain恢复原 ref。
- engine completion只有 invocation/task/owner/originating authority均匹配时才传播；同 session 的
  任意 terminal invocation不能唤起其它 lineage authority。
- manual `/runtime/drain` 只claim既有 link；operator不能在 request中附带、替换或扩大 ref。
- recovery worker只能恢复已持久化的 exact ref/epoch，不能从最近 conversation或 task描述猜测。

## Revocation, expiry and anti-union semantics

### No latest/all scan

authority resolver禁止以下查询作为正常路径：

- “取本 session 最新一条带 `skill_keys` 的 conversation”；
- “合并本 session/task/correlation出现过的所有 workflow refs”；
- “如果当前为空，就退回 parent agent上一次 active refs”；
- “从 prompt、memory compaction、task subject或protocol payload重新识别 workflow”。

多个 user request可并发存在，每条 signal只解析自己的一个 opaque authority ref。显式空 selection
不会撤销其它仍在运行的独立 lineage，也不会继承它们；它只保证本 lineage为空。若一个 user action
明确要求把两个 lineage合并，Host必须创建 `explicit_composition` record，记录参与binding、caller、
冲突检查和新digest，不能在restore时临时 union。

### Revocation and lifecycle

- 用户取消 request、session access owner变更、security policy撤销或operator执行有权限的 recovery
  action时，可把 binding转为 revoked并递增 epoch。
- task/report完成可以按 versioned policy把 request binding转为 consumed；“某个 capability成功”或
  “runtime idle”不能机械消费 authority。
- TTL若存在，只能是显式产品合同并投影过期时间；不能用进程内timer或任意消息到达顺序决定。
- derived child binding默认受 parent revocation约束。已经 dispatch 的外部 operation按自身 frozen
  approval/idempotency/reconciliation合同收口，但不得用 revoked authority创建新operation或委派。
- revoke transaction与 provider/tool/delegation preflight/commit共享 authority epoch fence。旧 worker
  可能已触达远端时必须记录 reconciliation-required，不能假设本地拒写就代表远端未执行。
- audit保留 terminal binding与digest，但 terminal record不可重新激活；恢复需要新的显式 user action
  和新 authority id。

## Ownership and API boundary

- Host message admission/service拥有 root binding创建；UI/CLI提交 canonical `workflow_refs`；`skill_keys` 仅是
  二选一的兼容输入并在 admission 时归一化，不进入 canonical authority row。客户端不提交 `authority_id`、
  epoch、parent或causation。
- `ProtocolService.delegate()` 或其单一上游 delegation service拥有 derived binding、delegation
  request、inbox、signal/link的原子写路径。
- scheduler只claim work并调用 authority resolver；它不选择 workflow、不做 latest fallback、
  不决定binding lifecycle。
- workflow registry拥有 exact ref、manifest/knowledge digest和requirements验证；authority store不
  缓存可绕过registry的“已验证”布尔值。
- session access/security service拥有 principal与session/project可见性校验；opaque id不可绕过404
  或operator/admin gate。
- public `POST /messages` 使用显式 `workflow_refs`（包括显式空数组），并可接受互斥的 compatibility
  `skill_keys`；`POST /runtime/drain` 永远不新增 authority选择字段。
- 如需显式 revoke，应提供单独、鉴权、幂等、versioned command，或复用明确的 request/task cancel
  transition；不能把 revoke藏在新消息文本中。
- workspace/world facts可投影当前 turn/lineage的 safe binding status与digest，供agent理解真实约束；
  read model不拥有或修改 authority。

## Persistence, fencing and recovery

1. root admission与derived delegation各自使用短事务，绑定 document/inbox/binding/signal/link/event；
   provider或模型调用不在事务内。
2. signal claim仍受 `SessionRuntimeLease + signal claim lease`保护；authority link额外绑定 epoch，不替代
   现有fencing。
3. worker在provider call、side-effecting tool dispatch和delegation commit前分别检查 active epoch；
   commit使用expected epoch条件更新或repository fence。
4. Host restart只读取durable binding/link；进程内 `active_skill_keys` 不用于恢复。
5. stale claimed signal被新worker reclaim时重新解析binding和registry；不能复用旧worker缓存的
   `SkillDocument`或manifest validation result。
6. binding/link缺失、重复、跨session、epoch mismatch、causal chain drift和unknown schema均返回稳定
   typed failure；禁止回退到 authority-empty真实provider turn。
7. authority resolver与public diagnostic不得输出raw conversation、principal credential、Host path、
   registry filesystem locator或lease token。

## Adopted migration/cutover plan

1. **Inventory and semantics freeze**：枚举所有 master/teammate signal producer、conversation/delegation
   payload、protocol/approval/engine resume路径和外部 API caller；明确哪些 wake属于同 request lineage，
   哪些必须 authority-empty。
2. **Schema and repository**：定义 `workflow_authority_binding@1` 与唯一 signal-link schema、closed state
   transitions、session/principal FK、epoch fence和stable error taxonomy；补 migration/backup/restore测试。
3. **Shadow root bindings**：message admission继续使用当前 first-drain逻辑，同时shadow写 root binding/link，
   比较 exact refs、source identity和registry validation；shadow数据不得扩大model context。
4. **Root cutover**：按 session/profile冻结feature version，scheduler从 root authority resolver恢复第一
   turn；conversation document仍保留audit binding，但不再是唯一跨跳resolver。
5. **Derived delegation bindings**：把 explicit subset、manifest snapshot、parent ref与teammate signal link
   纳入 canonical delegation UoW；用差分测试证明当前 teammate restore结果不变。
6. **Causal propagation**：逐一迁移 teammate terminal、agent protocol continuation、approval、engine
   completion和recovery producer；每条路径有closed causation validator，未迁移路径不继承 authority。
7. **Revocation and epoch fencing**：实现幂等revoke/consume、parent-child propagation、pre-dispatch与commit
   fence、stale worker/reconciliation测试；先internal/operator，再决定public command。
8. **Agent-facing projection**：只投影safe status/digest/lineage facts，验证compaction/restart后策略自由；
   不把authority store变成workflow planner。
9. **Legacy retirement**：确认无外部caller依赖session-sticky或隐式selection后，退役任何 latest/all scan、
   request-local context propagation和legacy signal fallback。历史signal不补造跨跳authority。

实际采用纠正性 closed cutover：新 Session 只写并读取新 schema；同一 Session 不能让旧 resolver 与新
resolver 各自选择一份 refs。旧 Session 缺少完整 binding/link 时返回 versioned incompatibility，需要 offline
migration 或新建 Session；不会把 shadow、conversation source fallback、隐式 union 或 terminal binding 复活。

## Compatibility policy

- 当前带 `skill_keys` 的 conversation document可作为 root migration输入；缺字段按显式空处理，不从
  message文本推断。
- 已有 delegation request中完整 refs/manifest snapshot可迁移为 child binding，但必须证明其 task、
  agent、correlation和session一致；否则只读保留并标记legacy-unbound。
- 旧 signal没有 authority link时，只允许 exact user-source first-turn按当前局部规则运行，或返回
  versioned migration-required failure；不得扫描别的消息补齐。
- public message API可保持兼容；若新增revoke/status API，使用显式versioned DTO和idempotency，不让
  client依赖内部binding row shape。
- 允许纠正性 breaking change，但退役前必须完成caller inventory、UI/CLI更新和历史SQLite读取验证。

## Alternatives considered

- **把 raw `skill_keys` 加到 AgentRuntimeSignal**：复制canonical value、需要每个producer正确传播并
  产生drift/union风险，不采用。
- **扫描 latest conversation**：无法证明当前signal causation，新空message也会继承旧authority，
  不采用。
- **扫描并合并全部conversation/delegation refs**：直接造成authority expansion，不采用。
- **把 refs 存在 AgentMember/session active focus**：形成ambient session/agent authority，并发request
  相互污染，不采用。
- **从 task/correlation猜 workflow**：identity不足且容易被protocol payload/subject注入，不采用。
- **让 master第一 turn必须预先委派全部角色**：把authority缺陷转成prompt recipe，限制agent策略，
  不采用。
- **只持久化自然语言 workflow instruction**：不能做digest、drift、subset和role/tool验证，不采用。
- **让 operator drain指定 refs**：把debug/runtime command变成授权入口，不采用。

## Risks and mitigations

- **schema过重**：先只实现root + delegation child两类closed derivation，其他causation逐条迁移；禁止
  通用自由图。
- **binding成为第二套workflow状态**：record只回答authority identity/status，不保存步骤、task DAG、
  next action或完成判定。
- **revocation与远端side effect竞态**：authority epoch + session fence + operation idempotency/reconcile
  三层分离；不承诺无法证明的exactly-once。
- **protocol可用性下降**：普通agent inbox继续authority-empty运行；只有它试图扩大workflow时拒绝，
  并提供stable diagnostic。
- **多lineage并发复杂**：每signal单binding、无隐式union；需要组合时显式composition record。
- **registry升级导致长任务中断**：exact digest ref本就要求fail closed；发布新version必须由新user action
  选择，不能自动升级旧binding。
- **SQLite写竞争**：保持短事务、合适索引与server-owned bounded查询；近期仍是单进程SQLite，不
  为未来多进程引入外部queue。
- **公开projection泄漏**：allowlist stable identity/digest/status；principal、lease和内部locator保持
  Host-private。

## Test strategy

### Repository and state-machine tests

- root/child/composition binding创建、重复幂等、状态迁移、epoch递增、parent revocation与terminal不可
  复活；
- admission与delegation事务任一步失败时document/inbox/binding/signal/link/event零部分提交；
- cross-session/project/principal、duplicate link、unknown schema、invalid ref和registry drift全部拒绝；
- migration读取legacy conversation/delegation时只做可证明转换，缺失不扫描补造。

### Scheduler and causation tests

- exact public user signal恢复root binding；普通发给master的agent protocol inbox正常运行但authority
  为空；畸形user source在provider前失败；
- master先委派researcher并结束turn，researcher完成后master causal wake仍能显式把同root的allowed
  subset委派给executor；证明harness没有强迫预先固定DAG；
- unrelated task completion、approval、engine invocation和manual resume不能借用同session活跃binding；
- background/manual/recovery从同一resolver得到相同结果；restart、expired claim和fresh worker scope不
  丢失binding；
- revoke发生在claim后/provider前、provider后/commit前和stale worker写回前的竞态均按epoch/fence
  收口。

### Anti-union and security tests

- 同session两条并发user message分别选择A与B，任一turn只见自己的ref；新空message看不到A/B；
- protocol payload伪造`skill_keys`、`authority_ref`、parent或epoch不能扩大authority；
- signal row、public event、claim payload和workspace projection均不含raw `skill_keys`或manifest body；
- explicit composition以closed record产生确定新digest；缺任一caller authority或冲突时无部分写入；
- principal失去session access或binding被revoke后，opaque id重放统一不可见/不可用。

### Agent-autonomy tests

- 同一workflow下预先并行委派、研究后串行委派和需要clarification后继续三种策略都可表达；harness
  只验证authority与真实capability，不改写计划；
- workflow binding不存在/失效时返回typed约束事实，不生成recommended action、替代workflow或
  “能跑”的fallback；
- task.finish、report publish和capability terminal继续由既有业务合同决定，authority lifecycle不
  自动完成task。

## Acceptance criteria

- clean restart后，从canonical rows可恢复root与derived authority、causal chain、status和epoch；进程
  内context清空不改变结果。
- 一次entry message选择的workflow在同request lineage的later teammate-result wake中仍可由master
  显式选择并委派；不要求第一turn预建全部task。
- 两个并发/相邻request永不自动union或latest-inherit；显式空selection保持空。
- 普通agent protocol inbox不会被错判为损坏，也不会获得user workflow authority；伪造protocol
  payload无法影响resolver。
- raw `skill_keys`、manifest snapshot和knowledge正文不进入AgentRuntimeSignal；signal只出现opaque
  ref/epoch或等价link identity。
- revoke/expire/consume与session/signal lease共同阻止stale provider/tool/delegation；竞态测试无
  unauthorized canonical write。
- exact ref/manifest/document/role/tool/capability drift在provider或side effect前fail closed，无隐藏
  fallback和无authority expansion。
- public API、workspace和events经schema/sanitizer验证，不泄露principal credential、lease、Host
  locator或private registry path。
- full non-live、focused scheduler/protocol/harness/API tests及真实但受控的sequential-delegation E2E
  通过后，才可把该proposal提升为稳定产品合同。

## Explicit non-goals

- 不把该 change 扩张成 AOX/HMM live campaign、Provider/HPC qualification、deployment cutover 或历史数据在线修复。
- 不把workflow authority变成task graph、planner、scheduler或business completion owner。
- 不让workflow selection由关键词、task kind、model `skill.load`、latest conversation或operator推断。
- 不自动组合多个request lineage，也不把master完整binding隐式传播给所有teammate。
- 不修改approval、operation、artifact、report或session runtime lease的canonical ownership。
- 不承诺跨恶意Host/DB管理员的加密证明；如未来需要远程可验证authority，应另立签名/attestation提案。
