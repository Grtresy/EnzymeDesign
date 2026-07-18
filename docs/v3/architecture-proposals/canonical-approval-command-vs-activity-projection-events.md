# Deferred: canonical approval command events vs activity projection events

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只修复 AOX/HMM live cutover driver 已经被真实路径触发的 consumer
判定错误：browser approval proof 只接受带有 closed `decision` 的 canonical
`approval.resolved` command-derived event；同名但只有完整 `ApprovalRequest`
projection、含 `status=approved|rejected` 且不含 `decision` 的 activity backfill 既不能
证明批准，也不能证明拒绝，必须忽略并继续等待 canonical command event。若最终没有
canonical event，则 bounded timeout fail closed；真实 `decision=rejected` 仍立即 fail
closed。

这是局部 consumer 小修，不改变 durable event schema、`V3EventStore`、workspace
projection、SSE、Web UI reducer 或全局 event taxonomy。它能避免一次 projection echo
被误判为 operator rejection，却不能解决同一 durable stream 中“canonical transition
fact”和“derived activity item”复用相同 `event_type`、相同 envelope version 的架构歧义。

全局修复会影响 control-plane ownership、event schema、cursor/replay、SSE client、UI
reducer、offline verifier、历史数据兼容和事件生产事务，属于大架构调整。本提案只记录
方案，不在当前 Goal 实施。当前 Goal 的两次独立正向 E2E、一次 fail-closed fault 和
Chrome proof 不得把该提案描述为已经落地。

## Real r11 evidence

r11 positive attempt
`positive-467ca78288b5413eb18d7946b8ec4286` 在同一 SQLite durable event log 中留下了
以下顺序；这些记录来自真实 browser approval 与后续 driver 协调，不是 fixture：

1. cursor `449` 是 canonical `approval.resolved`：top-level
   `actor_ref=user:local-dev`，payload 恰为
   `{approval_id=appr_74c64dd106c9, decision=approved,
   actor_ref=user:local-dev}`。
2. cursor `450` 是
   `sdk_controlled_operation.approval_resolved`，明确绑定相同 approval、operation
   `op_1a5a30935990`、operation digest、continuation id 和
   `decision=approved`。它证明该 controlled operation 按批准结果续接。
3. cursor `536` 再次出现 `approval.resolved`，但 payload 是完整
   `ApprovalRequest` projection：包含相同 approval id、`status=approved`、kind、
   request ref、requested action、session/task 与时间；它没有 `decision`，top-level
   `actor_ref` 也为空。
4. 当时的局部 driver 以“匹配 approval id 的 `approval.resolved` 且
   `decision != approved`”判断拒绝，因此把 cursor `536` 的缺失值误判为
   `browser_approval_rejected`。
5. coordination cleanup 随后才显式拒绝 agent 修正参数后创建的第二个 approval
   `appr_e62dde5f982a`；cursor `547` 的 payload 真实包含
   `decision=rejected`，cursor `548` 再把该结果绑定到第二个 controlled operation。

因此 r11 的首个 operator command 实际已获批准，UI command route 与 operation binding
并未伪造拒绝；NO-GO 是 consumer 把 projection echo 当 command fact 的结果。r11 bundle
仍然只能作为 fail-closed 诊断证据，不能转成 cutover positive，也不能复用。

## Current implementation and collision mechanism

当前路径有两类本应分离的 producer：

### Canonical approval transition producer

`V3HostApiService._resolve_approval_locked()` 接受 authenticated operator decision，先构造
一个窄 payload 的 `approval.resolved`，再更新 canonical `ApprovalRequest`，并在 SDK
operation 场景产生独立的
`sdk_controlled_operation.approval_resolved`。前者记录 operator command 被 Host 接受后的
approval transition fact；后者记录 operation owner 如何消费该 decision。它们都有明确的
业务含义，能够被 command receipt、actor、approval/operation identity 与 durable cursor
复核。

### Derived activity projection producer

`WorkspaceProjector.build_activity_feed()` 从 canonical approval rows 重新构造展示条目：
pending approval 产生 `approval.requested`，非 pending approval 再产生
`approval.resolved`，payload 直接使用 `approval.to_dict()`。这类 item 的目的是让 workspace
UI 展示状态历史；它是 read model，不是 operator command，也不是一个新的 approval
transition。

`V3HostApiService._extend_with_activity_events()` 随后读取整个 workspace
`activity_feed`，把每个尚未见过的 item 重新包装成 event，加入当前 command result，并由
`V3EventStore.append()` 写入 durable event log。去重 fingerprint 只有：

```text
event_type + created_at + canonical_json(payload)
```

canonical command fact 与 activity projection 的 payload shape 不同，因而即使表达同一个
approval resolution，也不会被 fingerprint 识别为同源。两者最终都使用
`event_type=approval.resolved`、默认
`schema_version=openzyme.v3.event.v1`、`visibility=public`，而 envelope 没有
`record_kind`、payload schema id、producer class、source event id 或 entity version。consumer
只能猜 payload shape。

当前 Web UI reducer 对任意 `approval.resolved` 都按 `approval_id` 删除 pending card，并把
event 加入 activity feed；该行为对展示通常看似幂等，却掩盖了两个语义来源。AOX driver、
offline evidence verifier、外部 SSE client 或未来自动化如果把同一 type 当成 authoritative
decision，就可能得到与 UI 展示完全不同的安全后果。

## Problem boundary

这不是一个只需把 `payload.get("decision")` 改成 truthy check 的 AOX 特例。

### Event type no longer identifies semantics

同一个 `event_type` 同时表示：

- authenticated command 被 Host 接受后产生的一次 canonical transition；
- 从当前 entity row 重建的 derived display item；
- command response 为补齐 activity feed 而生成的 backfill；
- 未来 restart/reprojection 后可能再次出现的等价展示状态。

event name 无法回答“发生了什么一次性事实”还是“当前 read model 看起来怎样”。

### Payload-shape inference is an unsafe protocol

以 `decision` 是否存在临时区分两类记录只适合作为 legacy reader migration shim。它不是
长期 schema：projection 将来可能为了展示加入 `decision`，canonical payload 也可能升级；
宽松 reader 还可能把 malformed canonical event 当 projection 忽略，或把 projection 当成
command。安全 consumer 应按 explicit schema/provenance 分类，而不是按字段偶然缺失分类。

### Projection rebuild creates apparent new facts

read model 可以重建、扩字段或改变序列化，但 canonical business transition 不应因此获得新
`event_id` 和 cursor。当前 fingerprint 绑定完整 payload；projection 增加一个 display field 就
可能产生一个新的 durable row，看起来像 approval 再次 resolved。

### Full entity projection expands the public surface

把 `ApprovalRequest.to_dict()` 作为 public durable event payload，会让未来 entity 新字段在
没有独立 event schema review 时进入 replay/SSE/bundle。展示 projection 与 audit/canonical
fact 的字段许可边界因此耦合，容易泄露 requested action 内部信息、private ref 或未来敏感
metadata。

### Consumer behavior diverges

UI、driver、eval、offline verifier 和第三方 SSE client 可以分别对同一 ambiguous row 做
“刷新、批准、拒绝、忽略、计数”中的不同选择。一个 consumer 的局部 shape guard不能保证
其它 consumer 同样安全。

### Cursor provides order, not authority

cursor `536 > 449` 只说明 row 后写入，不说明它比 canonical command fact更权威。若 consumer
采用 last-event-wins，它会让 projection backfill覆盖更早但权威的 decision。durable order 与
semantic ownership必须分开表达。

## Agent and harness impact

- agent 应看到真实的 pending approval、operator decision、operation continuation 与失败原因，
  并自由选择修正参数、重试、换科学分支或诚实 NO-GO；它不应猜哪个同名 event来自 UI、
  projection 或 command。
- harness 应忠实、结构化地呈现“谁做了什么 command、哪个 canonical object发生了哪个
  transition、哪个 read model需要刷新”，但不替 agent决定后续策略。
- projection echo 不能暗中变成 approval/rejection、task terminal、operation completion或重试
  命令；display reconstruction 也不能唤醒 agent或触发 side effect。
- unknown、ambiguous、schema-invalid 或 provenance-invalid 的 decision event必须在
  continuation、runner/provider side effect和 GO reducer前 fail closed。fail closed可以表现为
  bounded refresh/等待后显式失败，不能静默猜测 `status`、采用最后一条记录或自动重发
  approval。
- 一个真实 rejected command 应快速、明确传达给 agent；不能因为防 projection collision而把
  所有 negative decision都降级成 timeout。
- event taxonomy 约束世界事实的表达，不约束 agent 的 task DAG、工具顺序、科学判断、重试次数
  或报告内容。

## Non-goals

- 不改变 `session + task board + lane/workspace + approval + resident teammate + explicit
  runtime/drain` 顶层产品语义。
- 不让 durable event log、SSE、activity feed或 Web UI成为 approval canonical truth；truth仍在
  approval repository及其受控 service transition。
- 不把 `approval.resolved` 本身解释成 operation completed；SDK operation continuation与
  terminal outcome仍由自己的 canonical records/events表达。
- 不允许 projection builder、UI reducer、AOX driver或offline verifier写 approval decision。
- 不为历史 event重排或重编号 cursor，不删除已经封存的 r11 row，也不把历史 projection echo
  改写成 canonical command。
- 不原地赋予 `openzyme.v3.event.v1` 新的强语义；新保证使用新 envelope/payload schema。
- 不在当前 Goal 实施数据库 migration、全局 event producer迁移、SSE版本协商或 UI reducer
  重构。
- 不把本提案扩大成所有 OpenZyme event type 的一次性重写；首阶段只建立可推广规则并封闭
  approval seam，再按 consumer audit逐类迁移。

## Ownership and truth model

必须明确区分五个 owner：

1. **Approval repository/service** 拥有 `ApprovalRequest` lifecycle真状态和 version；只有受控
   transition可以把 pending改为 approved/rejected。
2. **Command receipt/idempotency boundary** 拥有 operator request是否被接受、谁提交、request
   digest、response与重复命令等价性；它不拥有 operation terminal outcome。
3. **Durable canonical event log** 拥有已提交事实的 immutable identity、schema、visibility、
   causation和cursor顺序；它不是从 read model反向生成业务事实的地方。
4. **Workspace projector/activity feed** 拥有面向用户的 read model。它可随代码版本重建，但必须
   标明 source并且不能获得 command authority。
5. **SSE/UI/offline consumers** 只消费相应 owner的 projection或事实；它们不得以 payload shape、
   最新时间、DOM状态或 activity text补造 decision。

`approval.resolved` canonical event 是 approval transition 的 durable fact，不是第二份可写
approval状态。repository row与event应由同一 transition Unit of Work/outbox lineage产生；若其中
一边缺失，系统报告 consistency failure，而不是让 projection backfill伪造另一边。

## Target invariants

1. 一个 approval lifecycle version至多有一个 canonical resolution fact；idempotent retry返回同一
   command receipt/event identity，不产生第二次 transition。
2. canonical approval resolution必须显式包含 closed `decision=approved|rejected`、approval
   identity、actor identity、entity version、resolved time和command/causation binding；缺任一必需
   字段都不是可消费的 decision fact。
3. activity/read-model item永远不是 canonical decision，即使它展示 `status=approved` 或未来为了
   UX显示decision文本。
4. canonical fact、projection notification和diagnostic observation必须由 envelope中的 closed
   semantic class与payload schema id区分；consumer不得只看 `event_type` 或字段存在性。
5. projection item不得复用 canonical `event_type` 写回 durable fact stream。若需要 SSE触发刷新，
   使用独立 `workspace.projection.invalidated`（或同等明确命名）的 notification schema。
6. projection rebuild不得创建新的 canonical event id/cursor，也不得触发 approval continuation、
   runtime wake、provider/runner dispatch或 GO/NO-GO变化。
7. event producer必须声明 canonical owner和producer class；projection builder不能声称
   `owner=approval_service`。
8. payload schema是 closed、versioned、allowlisted的；不能把整个可增长 domain entity直接作为
   canonical event payload。
9. top-level actor/command/correlation/causation索引字段若在payload中兼容重复，值必须严格相等；
   不一致 fail closed，不能任选更宽的一份。
10. cursor保持全局单调但允许gap；authority来自schema/provenance，不来自cursor新旧。
11. restart、pagination、SSE reconnect与offline replay对同一 canonical row返回相同
    `event_id + cursor + canonical bytes`。
12. legacy v1 history不改写。兼容分类器只能识别有限、已测试的 exact legacy shapes；未知shape
    标记 ambiguous并且不能驱动 side effect。
13. public event不包含credential、private locator、Host/runner path、完整敏感 requested action或
    projection未来新增的任意字段。
14. approval canonical fact只表示decision已提交；operation resumed/completed、task terminal和报告
    发布必须继续由各自owner的独立事实证明。
15. canonical fact commit失败时，不得用 activity projection补洞；projection notification失败也
    不得回滚或改变已经提交的 approval decision。

## Recommended event model

推荐采用“canonical facts only in durable fact stream + explicit provenance envelope + projection
invalidation when necessary”的组合，而不是只给现有 payload加一个 `source`字符串。

### Versioned envelope

新增 `openzyme.v3.event.v2`，至少包含以下 closed字段：

```text
OpenZymeEventEnvelope@2
  cursor                              # storage assigned, immutable
  event_id
  session_id
  event_type                          # stable semantic name
  schema_version = openzyme.v3.event.v2
  semantic_kind                       # canonical_transition |
                                      # projection_notification |
                                      # diagnostic_observation
  payload_schema_id                   # e.g. approval.resolved@2
  visibility                          # public | audit | internal
  producer
    producer_id                       # registered service/projector id
    producer_kind                     # domain_service | projection_builder |
                                      # diagnostic_adapter
    owner_kind                        # approval | controlled_operation |
                                      # workspace_projection | ...
  entity_ref
    entity_kind
    entity_id
    entity_version
  source
    command_id?
    command_receipt_id?
    source_event_id?
    source_record_ref?
  correlation_id?
  causation_id?
  actor_ref?
  created_at
  payload                             # closed by payload_schema_id
```

`semantic_kind`决定一条记录能否驱动 canonical state consumer；`producer_kind`与
`owner_kind`证明谁有权生产该类语义；`payload_schema_id`决定字段闭集。三者都参与 event
canonical digest/immutability check，不能由 payload覆盖。

现有 top-level `command_id`、`correlation_id`、`causation_id`、`actor_ref` 可以映射到 v2
envelope，避免重复索引。若为了 v1 compatibility暂时在 payload保留 actor或command字段，writer
必须执行 exact equality invariant；后续 major reader完成迁移后再退役重复字段。

### Canonical approval resolution

建议新 canonical payload 使用 `approval.resolved@2`：

```text
event_type: approval.resolved
semantic_kind: canonical_transition
payload_schema_id: approval.resolved@2
producer:
  producer_id: v3.approval_service
  producer_kind: domain_service
  owner_kind: approval
entity_ref:
  entity_kind: approval
  entity_id: <approval_id>
  entity_version: <resolved approval version>
source:
  command_id: <Host command id>
  command_receipt_id: <idempotency receipt id>
actor_ref: <authenticated principal>
payload:
  approval_id: <approval_id>
  decision: approved | rejected
  resolved_at: <UTC timestamp>
  approval_kind: <closed safe enum>
```

对 SDK controlled operation，`sdk_controlled_operation.approval_resolved@next` 继续是独立的
canonical transition，绑定 operation id/digest、continuation id、同一 approval id/decision和前一
event id作为 causation。不能通过只看到 approval event就推断 operation已续接，也不能让
operation projection反向补造 approval event。

建议在 storage或service层对
`(session_id, entity_kind, entity_id, entity_version, event_type,
semantic_kind=canonical_transition)` 建立唯一性/consistency invariant，并用 command receipt保证
重复 POST 返回原结果。`event_id` 由首次成功commit确定；projection rebuild不参与identity。

### Activity feed as a read model

`WorkspaceProjector.build_activity_feed()` 可以继续把 approval row变成用户可理解条目，但条目应
使用自己的 versioned schema并显式标注来源：

```text
ActivityFeedItem@next
  item_id
  item_type: approval.resolved
  source_kind: canonical_event | canonical_record
  source_event_id?
  source_record_ref?
  source_record_version
  created_at
  display_payload                   # safe, closed, non-authoritative
```

若同一个 canonical event已经存在，优先以 `source_event_id`构造 stable item id和display
projection。若迁移期只能从 historical approval row重建，则使用
`source_kind=canonical_record`、approval version和projection schema生成stable item id，并明确
它不是event authority。

`_extend_with_activity_events()` 不再把这些 item按原 `item_type`写回 durable event log。UI通过
workspace snapshot读取 activity feed；canonical event本身已足以让 event-following client更新或
触发 bounded workspace refresh。

### Optional projection notification

若某些 read model更新没有合适的 canonical event、必须通过 SSE通知 client刷新，使用独立类型，
例如：

```text
event_type: workspace.projection.invalidated
semantic_kind: projection_notification
payload_schema_id: workspace.projection.invalidated@1
producer:
  producer_id: v3.workspace_projector
  producer_kind: projection_builder
  owner_kind: workspace_projection
payload:
  projection_name: activity_feed
  entity_kind: approval
  entity_id: <approval_id>
  entity_version: <version>
  reason: approval_resolved
  source_event_id: <canonical event id, when available>
```

该 notification只允许“invalidate/refetch”，不能携带或驱动 `decision`、approval transition、
operation continuation或task terminal。对于已有 canonical approval event的普通路径，首选不额外
发 notification，避免一个事实产生两条无必要 cursor；只有测得 client确实需要独立invalidator时
才引入。

## Commit, causation and consistency

目标 transition应在一个 bounded Unit of Work或transactional outbox lineage中完成：

1. 验证 authenticated command、session access、approval pending/version和idempotency key；
2. 写 command receipt pending/accepted state；
3. compare-and-set canonical approval row到 approved/rejected并增加version；
4. 写唯一 `approval.resolved@2` canonical event，绑定command、actor、entity version；
5. 若为 controlled operation，在同一可恢复lineage中写operation continuation intent/event；
6. commit后才发布 SSE/outbox并构建 workspace projection。

若当前 repository transaction边界不能一次包含全部记录，实施阶段需使用既有 durable outbox或
明确的 recovery protocol，保证至少满足：重复执行不会产生第二个transition；canonical approval
row存在而event缺失时进入consistency attention，不由projector修复；event存在而row/version不匹配
时fail closed并禁止 operation side effect。

canonical event的 `causation_id` 指向 accepted command或前序operation event；projection item通过
`source_event_id`引用它。不得反向让canonical event以projection item作为 causation。

## Cursor, replay and SSE contract

### Cursor preservation

- 不修改、删除或重排历史 v1 rows；r11 cursor `449/450/536/547/548` 永久保持原bytes与顺序。
- migration只从一个声明的cutover cursor/version开始产生 v2记录。v1与v2可在同一session history
  中混合，reader逐条按 `schema_version + semantic_kind + payload_schema_id`分派。
- 停止activity backfill后，新session会产生更少的cursor。cursor从来不保证连续；private/audit
  visibility本来也可以形成public gap，因此 SSE client不得把gap当丢事件。
- `Last-Event-ID`、`after_cursor`、fixed high-watermark、分页与restart replay语义保持不变；不为
  migration合成新cursor或把old cursor映射到new ordinal。

### SSE event naming

non-envelope SSE目前把 `event_type`放在SSE `event:`行。v2 canonical approval仍可使用
`event: approval.resolved`，但 authoritative consumer必须读取data envelope并验证schema/kind；只
订阅event name不足以执行side effect。projection notification使用不同event name
`workspace.projection.invalidated`。

支持 generic `event: openzyme.event` 的 client可直接按envelope分派。实施时应评估是否让所有新
authority-sensitive client强制使用generic envelope mode，或通过 `Accept`/query capability声明
v2；在没有协商前，不得让legacy client把未知 v2 projection notification解释成 canonical fact。

### Replay identity and deduplication

consumer以 `event_id`做delivery dedup，以cursor做ordered progress，以
`entity_ref + entity_version + payload_schema_id`做semantic consistency check。不能继续用完整
projection payload fingerprint作为canonical identity，也不能按“相同approval id取最后一条”覆盖
earlier canonical fact。

SSE delivery可以重复，canonical transition不能重复。收到相同event id/bytes是幂等重投；收到
不同event id却声明同一 approval version/transition是consistency violation，而不是两个合法
decision。

## Web UI behavior

Web UI需保持“workspace是read model、event是增量提示”的边界：

- `approval.resolved@2 + canonical_transition` 可以从 `pending_approvals`移除exact approval，并触发
  workspace refresh；UI不得据此显示operation completed。
- `workspace.projection.invalidated` 只触发bounded refetch，不直接从payload伪造approval状态。
- legacy v1 projection echo可作为activity display compatibility输入，但不能触发 approval command、
  browser proof或任何自动side effect；duplicate item按stable source identity去重。
- unknown/malformed v2 event不应用partial reducer；UI保留最后一个canonical workspace，显示
  refresh/consistency error并进行bounded retry。
- canonical rejected event应明确展示operator rejection；projection row中的
  `status=rejected`不能替代该 command evidence。
- event replay与initial workspace snapshot交错时，以workspace entity version和event entity
  version判定stale/forward，不采用arrival-time last-write-wins。

在shared deployment profile下，UI还必须继续执行project/session access；event provenance字段
不得泄露其它principal、private receipt或internal command material。public actor ref使用现有安全
projection，而不是credential或认证token。

## AOX/Chrome and offline verifier behavior

### Browser approval proof

迁移完成后的 Chrome approval proof必须同时满足：

1. exact session、approval、operation和operation digest；
2. `schema_version=openzyme.v3.event.v2`；
3. `semantic_kind=canonical_transition`；
4. `payload_schema_id=approval.resolved@2`；
5. registered approval service producer/owner；
6. closed `decision=approved`、authenticated safe actor、command receipt/causation和entity version；
7. 对应 controlled-operation continuation event与前述decision一致。

真实 `decision=rejected`立即产生显式 negative proof。projection notification、activity item、
status-only entity snapshot、DOM文本、approval card消失或operation projection都不能单独证明批准或
拒绝。

当前 Goal 的 v1兼容逻辑只能把 exact legacy command shape
`{approval_id, decision, actor_ref}`识别为canonical candidate，并交叉验证top-level actor与operation
event；status-only完整 ApprovalRequest echo被忽略。该shim必须有退役期限，不能成为 v2正式规则。

### Offline replay

sealed evidence bundle应保存canonical event的完整安全envelope、event id/cursor、payload schema、
producer/owner、command receipt safe digest和对应operation event。offline verifier应：

- 从同一cutover cursor按顺序重放，拒绝event bytes/schema/provenance/decision/entity version篡改；
- 证明一个approval version只有一个canonical resolution；
- 证明operation continuation causation指向同一approved event；
- 忽略projection notification对decision reducer的影响，但验证它没有冒充canonical kind；
- 对legacy v1应用version-pinned exact classifier，并把unknown shape报告为
  `ambiguous_legacy_approval_event`，不能猜测；
- 不因cursor更大、activity status或UI最终状态覆盖canonical decision；
- 在canonical event缺失、duplicate conflict或producer不合法时fail closed。

tamper suite至少要分别改动 `decision`、semantic kind、payload schema、producer owner、entity
version、command binding、source event id和cursor order，证明每种篡改都不能通过。

## Compatibility and migration

### Phase 0: inventory and freeze

先冻结当前v1含义并审计所有 producer/consumer：`_extend_with_activity_events()`调用点、
`WorkspaceProjector`、Host command result、SSE encoder、Web UI reducer、AOX driver/evidence verifier、
eval、tests以及确认存在的外部 client。记录每个 consumer是展示、刷新、诊断、authority判定还是
side-effect trigger。未完成调用方审计前不删除legacy path。

### Phase 1: schema and reader first

- 定义 `OpenZymeEventEnvelope@2`、registered producer ids、semantic kind enum与
  `approval.resolved@2` closed schema。
- 所有authority-sensitive reader先支持v2，并集中使用一个typed decoder；禁止各自实现
  `payload.get("decision")`。
- 提供严格v1 compatibility decoder，只接受已封存的exact canonical command shape；完整
  ApprovalRequest shape只标记为legacy projection，不参与decision。
- metrics/diagnostics区分canonical、projection、ambiguous和invalid，但不公开private payload。

### Phase 2: canonical writer and uniqueness

- approval service开始写v2 canonical event，绑定command receipt、entity version和actor；
- 为同一approval version/transition增加唯一性与consistency audit；
- controlled operation event升级并绑定canonical approval event causation；
- 双读期间可以继续返回v1兼容响应，但不得为同一transition双写两个都被视为canonical的事件。

若必须dual-write，应让legacy row明确标记compatibility mirror并共享source event identity，new reader
只认v2 canonical；在设计评审通过前更推荐single v2 write + legacy reader，而不是制造新的歧义。

### Phase 3: detach activity projection

- activity item增加stable source identity和read-model schema；
- 关闭approval类 `_extend_with_activity_events()` durable backfill；随后按producer audit逐类移除通用
  backfill；
- 需要刷新通知的projection使用独立
  `workspace.projection.invalidated@1`，不复用domain event name；
- UI改为canonical event增量 + bounded workspace refetch，不把projection payload当truth。

### Phase 4: mixed-history verification

在未改写历史数据库的情况下验证：

- v1 canonical + v1 projection echo；
- v1 history后接v2 canonical；
- restart、1000+ event分页、Last-Event-ID reconnect与visibility gap；
- command idempotent retry、duplicate delivery、projection rebuild和concurrent workspace fetch；
- shared profile access/redaction与local single-process SQLite。

### Phase 5: retire legacy compatibility

只有在确认无外部调用方依赖“status-only `approval.resolved` 是command decision”、所有active client
声明v2能力、历史offline verifier已pin decoder后，才能：

- 停止生成所有同名activity backfill；
- 从active authority reader移除payload-shape inference；
- 保留historical bundle verifier中的v1 decoder；
- 文档化cutover cursor/version和reader support window；
- 将未知v1 live event从“兼容忽略”收紧为显式unsupported/ambiguous failure。

历史rows永不重写；退役的是active writer/reader fallback，不是审计记录。

## Test plan

### Schema and unit tests

- `approval.resolved@2` approved/rejected各自通过closed decoder；缺decision、非法decision、未知字段、
  producer/owner错误、entity version缺失或actor不一致全部拒绝。
- v1 exact canonical command shape被compat decoder识别；r11 cursor `536`同形projection被分类为
  projection echo且不批准、不拒绝；真实cursor `547`形状仍分类为explicit rejection。
- projection notification永远不能传入decision reducer；即使恶意payload加入
  `decision=approved`也因schema closed而拒绝。
- event id delivery dedup、entity-version uniqueness和duplicate command receipt均有positive/negative
  tests。

### Repository and transaction tests

- approval row、command receipt和canonical event在成功路径具有同一version/causation；注入每个commit
  point失败，证明没有projection backfill补造fact，也没有side effect越过不完整commit。
- repeated approve/reject、相反decision重放、concurrent operator command与stale entity version明确
  idempotent或conflict，不能产生两个canonical resolution。
- projection rebuild前后canonical durable row count/event bytes不变。
- SQLite restart后event id/cursor/bytes完全一致；public/audit/internal visibility仍按原合同隔离。

### SSE tests

- mixed v1/v2 history按cursor完整replay；超过1000 rows分页不漏不重；follow从fixed high-watermark继续。
- Last-Event-ID跨private cursor gap继续正常；停止activity backfill后更稀疏的cursor不会触发client
  false loss alarm。
- generic envelope client按semantic kind分派；typed event-name client收到projection invalidation只
  refresh，不执行approval transition。
- duplicate network delivery只应用一次，different event ids声明同一entity version触发consistency
  failure。

### Web UI tests

- canonical approved/rejected event正确更新pending cards/activity并触发workspace refresh；operation仍
  单独显示resuming/terminal。
- status-only legacy projection echo不会触发browser approval proof、command POST或错误negative state；
  activity展示可幂等去重。
- projection invalidation只refetch；malformed/unknown v2保留last good workspace并显示bounded错误。
- initial snapshot、event replay和5秒rerender交错时，entity version不会回退或重复approval card。

### Offline/evidence tests

- 以r11 exact chronology做locked regression：449/450被识别为approved lineage，536被忽略为
  projection，547/548只属于第二个rejected lineage。
- bundle replay只用canonical event得出decision；删除449、修改decision/actor/owner/schema/version、
  把536改成canonical kind、切断450 causation全部fail closed。
- historical v1 bundle与new v2 bundle各自pin decoder，不能用new semantics改写旧GO/NO-GO结论。

### Real integration and live acceptance

- 真实Chrome只点击一次approval，durable log只出现一个该approval version的canonical
  `approval.resolved@2`，UI refresh/reprojection不新增同名canonical row。
- agent因参数错误创建第二个approval时，首个projection/display rebuild不能把第二个approval自动
  reject；只有真实operator command才能解决它。
- 真实explicit rejection立即形成canonical negative proof，operation不dispatch且driver按声明错误
  fail closed。
- Host restart、SSE reconnect与workspace refresh后，Chrome、driver、UI、offline verifier对同一
  decision/operation lineage结论一致。

## Staged acceptance criteria

本提案只有在以下条件全部满足后才可标记implemented：

1. 架构与schema评审确认canonical fact、projection notification、diagnostic observation的closed
   分类及registered ownership。
2. approval service是`approval.resolved@2`唯一active canonical producer；projection builder无法
   生产该semantic kind/type组合。
3. canonical approval row、command receipt、event和controlled operation continuation形成可验证
   causation/transaction lineage，并有duplicate/conflict注入测试。
4. active durable log不再写同名status-only activity backfill；projection rebuild不改变canonical
   event rows。
5. SSE cursor/replay/restart/visibility合同在mixed v1/v2历史上通过，历史cursor零改写。
6. Web UI、AOX driver、eval、offline verifier和已确认外部consumer都使用typed decoder；authority
   path不再自行猜payload shape。
7. r11 chronology regression、真实single approval、真实explicit rejection和第二approval隔离测试全部
   通过。
8. sealed bundle tamper suite能拒绝decision/schema/provenance/entity version/causation漂移。
9. public event/projection经过private locator、credential、requested-action敏感语料审计，零越界。
10. docs/OpenZyme架构设计.md、相关docs/v3稳定合同、OpenSpec、UI/API示例与migration runbook同步，且
    明确v1 support/retirement窗口。
11. 外部调用方审计确认旧compatibility mirror/status-only interpretation可退役；否则legacy reader
    保留并明确标记，不静默删除。
12. 两次独立真实正向E2E与一次explicit rejection/fault验证证明taxonomy迁移没有降低agent策略
    自由、没有新增隐藏fallback，也没有把projection误当canonical truth。

## Rejected shortcuts

- **只把缺失 `decision` 当 approved。** 这会把任何malformed/forged event提升为批准，违反
  fail-closed。
- **把 `status` 映射成 `decision`。** `status` 是entity snapshot，无法证明哪次authenticated
  command导致transition，也不能绑定actor/idempotency/causation。
- **last cursor wins。** cursor只给storage顺序；更晚projection不比更早canonical fact权威。
- **按payload fingerprint去重。** display字段变化会改变fingerprint；它不表达entity version或
  source event identity。
- **让UI最终DOM作为approval真状态。** DOM是projection，可因rerender、stale fetch或client bug
  漂移，不能替代Host command receipt与canonical event。
- **双写两个同名canonical-looking events。** 即使payload一样，也会让delivery/event identity与
  offline uniqueness模糊；兼容mirror必须显式标记且不能被new reader当canonical。
- **原地重定义v1。** 历史bundle和外部client无法知道新旧含义，审计重放会随软件升级改变结论。
- **把所有activity item永久写入durable fact stream。** 展示历史可由read model或独立projection
  log承载；不能为了UI方便污染business fact taxonomy。
- **projection collision时自动重试/重开approval。** 这会改写agent/operator意图并消耗真实provider/
  runner资源；应等待明确canonical fact或显式失败。

## Risks and mitigations

- **迁移期reader复杂度。** 使用一个共享typed decoder与locked r11 fixture，禁止每个consumer
  重写shape logic；按cutover cursor/schema选择decoder。
- **事件数量/顺序变化破坏UI。** UI测试不应断言activity backfill的偶然cursor数量；改为断言entity
  version、source event identity与最终workspace语义。
- **canonical row与event事务不一致。** 用同一Unit of Work/outbox、entity version uniqueness和
  consistency audit；不让projector修复。
- **v2 envelope过度泛化。** 首阶段只为approval和projection invalidation定义closed schemas；其它
  event逐类迁移，不允许一个自由form `provenance`对象替代review。
- **public schema膨胀。** producer/owner使用registered enum/opaque safe refs；command receipt只公开
  opaque id或safe digest，原始request/credential留在private boundary。
- **legacy echo被无限保留。** 发布明确metrics、consumer inventory和retirement gate；historical
  decoder永久可读不等于active writer永久继续。
- **fail-closed造成无提示timeout。** typed decoder对projection、ambiguous、invalid分别给
  LLM/operator可理解的安全diagnostic；projection可被忽略等待，invalid canonical立即报告，最终
  bounded timeout包含exact safe blocker code。
- **taxonomy变成第二套control plane。** event只证明既有owner提交的fact，不拥有approval/task/
  operation状态，不从event反向写业务对象。

## Final architectural position

长期边界应是：**approval service提交一次 canonical transition；durable event log封存该事实；
workspace projector展示该事实；SSE传送事实或明确的projection invalidation；consumer按versioned
schema与provenance消费，绝不从activity payload猜operator command。**

这样 harness 能把真实约束低摩擦地呈现给 agent：批准就是批准，拒绝就是拒绝，projection只是
projection。agent仍保留修正参数、重新规划、早停或报告NO-GO的策略自由；harness不再因为展示层
重建而替它制造新的业务事实。

在本提案完成独立评审、迁移和验收前，当前 Goal 只保留已实施的局部consumer guard与对应回归
测试；不得修改全局 event taxonomy，也不得宣称 r11 已因此转为有效positive proof。
