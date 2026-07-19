# Deferred: Host-authoritative controlled-operation resource estimate and limit snapshot

Status: proposed; not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 sandbox SDK 在 `controlled_operation(...)` wire envelope 中提交
`resource_estimate`。Core 校验该值是 JSON object，随后把它复制进 operation digest、
`ControlledOperation`、approval summary 和 public projection。对于当前 UniProt v3，SDK 使用本地
常量 `query_batch_size_cap=100` 预测 `accession_count` 与
`estimated_query_batch_count`，因此纠正后的 37,772 个 accession 在默认配置下显示 378 个 query。

这项透明预测有助于 agent/operator 理解当前默认请求规模，但它不是授权真值：实际 provider
adapter 使用 Host 注入的 `BioProviderHttpConfig`，operator 可以收紧 query、page 或 operation
cap。Core 当前没有从 route policy 和 exact injected config 重建 estimate/limits，也没有逐字段
证明 sandbox 声明与 Host 将执行的资源拓扑一致。

本 Goal 只把现状诚实记录为“default-config prediction”，继续由 Host adapter 在 provider I/O
前执行实际 cap/identity/page validation。把 sandbox 输入降级为需求声明、由 Host 编译并封存
canonical estimate/actual limit snapshot、再绑定 approval/config/usage，需要跨 Pipeline SDK、
Core、route policy、Host composition、engine adapter、repository/projection 与 verifier 的 schema
迁移，属于大型 harness 调整。本提案只记录方案，不实现，不把当前 approval estimate 追认为
authoritative resource grant。

## Current evidence and failure mode

1. `openzyme_pipeline.client.controlled_operation` 接受任意 mapping 形状的
   `resource_estimate`，并由 sandbox caller把它放入 S12 envelope。
2. Core 的 envelope validation 目前只要求 `resource_estimate` 是 object；它不按 SDK method
   校验字段、单位、范围、计算公式或 provider config identity。
3. Core 把该 object纳入 operation digest、persisted `ControlledOperation.resource_estimate`、
   approval details与workspace projection。digest只能证明“批准了这份caller bytes”，不能证明
   这些 bytes由资源authority计算。
4. UniProt SDK 当前用 `_UNIPROT_QUERY_BATCH_SIZE_CAP=100` 计算 query数；Host adapter用注入的
   `BioProviderHttpConfig.batch_size_cap` 实际分 query。测试或部署可以把Host cap收紧为2、50等，
   但SDK仍可显示100。
5. 例如同一37,772 accession请求在SDK默认预测下是378 queries；若Host cap收紧为50，实际是
   756 queries。Host仍可在I/O前拒绝operation cap或执行收紧后的有界请求，但operator批准时
   看到的规模不再等于实际拓扑。
6. `provider_config_digest`/route policy id进入operation identity，但当前Core没有用它解析exact
   runtime config snapshot并重建estimate，也没有验证composition注入的adapter config就是该
   digest所代表的safe配置。
7. page count等动态量可能依赖provider `Link`响应，preflight只能给bound/estimate，不能谎称
   exact actual usage。当前shape没有统一区分declared demand、computed estimate、hard limit、
   reserved quota和observed usage。
8. caller可以少报、错报或增加无schema字段；Host实际adapter limit仍可能阻止部分越界，但
   approval、reuse、audit和UI语义不再是Host-authoritative。
9. 仅把SDK常量改成与当前Host默认相同不能消除漂移；未来config收紧、route切换或另一个SDK
   module仍会重复问题。

## Real r25 evidence: planned demand and observed result topology diverge

r25 把 resource snapshot 中必须分开的几类事实具体化：

- sandbox 根据 `37,722` 个 UniProt accession 和 cap `100` 声明 `378` 个 query batch；第 `102` 项
  `A0A034VJ94` 属于第二个 batch，但当前 adapter 先完成并内存累积全部 query/page，随后才统一验证
  record contract。因此该失败不能被描述成“在第二 batch 停止网络请求”；它反而证明 planned、
  dispatched、buffered 与 validation-terminal 是四个必须分开的 observed 维度；
- EBI HMMER terminal poll 约 `24s` 完成，并以默认 `page_size=50` 返回首个 result payload；旧 adapter
  随后按 `page_size=100` 请求 `page=2..686`，约 `52m` 后得到 `68,542` 条，而 provider 完整
  `nreported` 为 `68,592`；
- 统一 `page_size=1000` 的只读恢复拓扑是 `69` 页、最后一页 `592` 条。page size 是 Host route/config
  事实，page count 和 `nreported` 是运行时 observed closure facts，均不能由 sandbox 自报。

本 Goal 的小修会把 HMMER materialization 固定为同宽 `page=1..N`、默认 `page_size=1000`，在 publish
前校验 `nreported` 与完整 coverage，并因 route/default 改变而版本化 provider policy/config digest。
这只修正一个 bounded adapter contract；它没有新增 canonical resource grant/usage schema。现有
HMM-capable `sandbox.exec=3600s` 与 formal/public 至少 `7200s` 的分层预算先不继续放宽，因为旧
`52m` 主要来自错误且低效的分页拓扑，corrected live timing 才能决定是否需要调整某一语义层级的
deadline。

未来 authoritative snapshot 至少要分别绑定 requested page width、preflight max page/request/byte
bound、terminal-poll usage、materialization GET count、observed pages/records/bytes 与 completeness receipt。
approval 看到的 estimate 不能在执行时静默换 width；若 provider 的 page metadata、`nreported` 或
actual usage 超出 approved bound，必须 fail closed 或回到 operator 重新批准，不能靠扩大 timeout 或
截断尾页继续。

## Agent-harness principles

- agent/sandbox声明它想做什么和输入规模，不自授额度、不自报backend limit，也不需要知道
  private provider配置。
- harness把真实route、限额、估算方法与不确定性结构化呈现给agent/operator；不因估算偏大
  自动改写agent请求，也不因偏小静默执行。
- approval必须绑定Host将实际执行的canonical resource snapshot，而不是caller提供的展示文本。
- estimate、hard limit、reservation和actual usage是不同事实，schema必须分开表达，不能用一个
  `resource_estimate` object混写。
- 无法计算、config identity漂移、参数无法有界化或actual超出approved bound时fail closed；不
  fallback到更宽limit、另一个provider/backend或拆分成未批准operation。
- Host-authoritative不等于Host规定科学策略。agent仍可选择合法batch_size、stop/retry和operation
  顺序；compiler只验证并呈现真实world constraints。
- public snapshot只含safe单位、计数、digest和opaque policy identity，不暴露credential、private
  endpoint、Host path、provider token/quota secret或runner配置。

## Target ownership and topology

```text
sandbox SDK
  `-- controlled-operation demand declaration
        method + normalized params + input refs + desired outputs + optional hints
                          |
                          v
Host resource compiler registry
  |-- exact route policy snapshot
  |-- injected provider/tool/runner config snapshot
  |-- canonical params/input facts
  `-- versioned per-capability estimator + limit validator
                          |
                          v
controlled_operation_resource_snapshot@1
  |-- canonical demand
  |-- Host-computed estimate/bounds
  |-- effective hard limits
  |-- config/policy/compiler identities
  `-- approval + operation digest binding
                          |
               approved / rejected
                          |
                          v
adapter execution + atomic budget consumption
                          |
                          v
controlled_operation_resource_usage@1
  `-- observed/reserved/released usage and limit reconciliation
```

Host API composition root负责注入route policy repository、provider/tool/runner configs和resource
compiler registry。Core只消费一个typed interface，不能import具体Bio adapter；engine/adapter只
执行已绑定snapshot并回传actual usage receipt。Pipeline SDK不再拥有limit常量authority。

## Demand declaration from the sandbox

建议把现有caller `resource_estimate`替换为闭集
`controlled_operation_resource_demand@1`，仅包含可从请求本身重算的事实：

- `sdk_module`, `function_name`, normalized params digest；
- input artifact ids/digests和input cardinality facts；
- requested accession/item count、requested page size、expected output categories；
- placement/backend preference（若public contract允许）；
- caller-known bounded loop/max-call facts；
- optional `client_prediction`只作diagnostic，必须独立标记
  `authoritative=false`，不能进入grant或reuse decision。

sandbox不能声明以下authority字段：effective operation/query/page cap、quota remaining、provider
rate class、selected backend limit、reservation id、hard timeout、actual cost或approval verdict。
unknown/extra字段fail closed。Host从canonical params重算count，不能相信caller重复填的数字。

迁移早期可以保留原 `resource_estimate` wire key作为advisory hint，但Host必须将其放入单独的
private mismatch diagnostic；它不进入authoritative snapshot。最终schema应删除或重命名该key，
避免旧调用方误以为可授予资源。

## Host resource compiler registry

每个external SDK method绑定一个versioned compiler，例如：

```text
bio.uniprot_fetch.resource_compiler@1
bio.ncbi_fetch_proteins.resource_compiler@1
bio.hmmer_search.resource_compiler@1
bio_tools.hmmalign.resource_compiler@1
```

compiler input是闭集：

- canonical SDK method/params/input facts；
- exact route policy id/content digest与selected backend；
- injected config safe snapshot及digest；
- operation/plan call budget；
- global/session/provider limiter policy identity；
- platform/runtime facts中确实影响limit的safe部分。

compiler output必须deterministic、canonical且无I/O副作用。缺compiler、config、policy、单位定义或
无法证明bound时返回stable error，不能把client estimate原样提升为authoritative。

对于UniProt，compiler至少重算：

- accession count和duplicate/operation-cap前置结果；
- effective query accession cap与`ceil(accession_count/cap)`；
- requested/effective response page size；
- per-query page cap与worst-case page bound；
- max HTTP requests bound、network/provider类别与output upper-bound policy；
- operation cap、query cap、page cap、timeout/retry policy identity；
- `provider_config:uniprot:v3`的safe canonical config digest。

动态 `Link` 数量仍未知，因此snapshot应表达`estimated_queries`和`max_pages_per_query`/worst-case
bound，不能伪造exact total pages。actual receipt再记录真实page/query/request counts。

## Proposed authoritative snapshot

`controlled_operation_resource_snapshot@1`建议使用closed schema：

- `schema_id`, `snapshot_id`, `snapshot_digest`；
- session/task/lane/sandbox run/source snapshot/operation candidate identity；
- sdk method、params digest、input facts digest；
- route policy id/content digest、selected backend、runtime packaging id；
- provider/tool/runner config identity和safe config snapshot digest；
- resource compiler id/implementation digest；
- canonical demand projection；
- `estimates`：带单位与计算method的point/range；
- `hard_limits`：operation/query/page/call/time/output等effective cap；
- `uncertainties`：只允许versioned category，例如provider-driven pagination；
- `approval_summary`：由上述字段机械派生的bounded public projection；
- created_at/config epoch/high-watermark和expiry/revalidation policy。

所有numeric value必须有明确integer/decimal单位与范围；禁止自由文本数字、nonfinite、负count、
重复单位或unknown key。snapshot digest覆盖complete canonical preimage。

## Approval and operation binding

1. Core在创建`ControlledOperation`或`ApprovalRequest`前调用Host resource compiler。
2. authoritative snapshot digest进入operation digest、approval request/details、plan digest、
   idempotency/reuse key和workspace public projection。
3. approval UI展示Host-computed estimate、hard limits、不确定性和config/policy digest prefix；client
   prediction若展示，必须明确标记advisory并同时显示mismatch。
4. approve只授权exact snapshot。params、input、route、backend、config、compiler、limit或snapshot
   expiry任一漂移都需要重新计算并重新approval或结构化失败。
5. adapter dispatch前再次从current authoritative config重建snapshot并constant-time比较digest；
   漂移发生在provider/runner I/O前。
6. approved reuse只适用于same method/params/input/source/runtime/resource snapshot。旧operation中
   caller-authored estimate相同不能作为reuse authority。
7. plan-level max calls与operation resource snapshot共同生效：snapshot不提高plan call budget，
   plan也不放宽provider hard limit。

## Actual limit enforcement and usage receipt

Host adapter仍是实际limit enforcement boundary，但必须只消费snapshot中绑定的effective config：

- dispatch前原子消费call/quota reservation；
- query/page/operation/output/timeout每一步对照snapshot hard limit；
- retry只在approved retry bound内，同一operation identity下计数；
- actual usage超过approved hard bound立即fail closed，不继续分页或提交backend；
- adapter不能私下读取另一份unbound config改变limit。

`controlled_operation_resource_usage@1`建议记录：

- operation/snapshot/config/route identity；
- actual query/page/HTTP/backend call counts；
- reserved、consumed、released量及单位；
- output bytes/count、elapsed time和retry count；
- limit comparison verdict、terminal status和safe error code；
- provider-driven unknown/incomplete usage的显式状态。

actual receipt进入result envelope、evidence bundle与offline verifier，但不允许adapter通过自报usage
把failed/partial operation变success。remote outcome unknown时保持unknown，不能填零。

## Config identity and injection

- Host provider config必须有canonical safe snapshot：只含影响execution/resource语义的非secret
  fields，secret value/private endpoint/path分离且只以opaque availability/identity表达。
- route policy引用该config schema/identity；composition root注入的runtime object必须重算safe digest
  并与policy/snapshot一致。
- config object在operation lifecycle内immutable或按epoch/fencing读取；approval后in-place mutation
  使dispatch fail closed。
- operator收紧limit产生新config digest/snapshot；不能沿用旧approval。放宽limit同样需要显式
  policy/config版本和新approval。
- provider-global remaining quota等快速变化状态如果参与grant，应通过独立quota authority/reservation
  receipt绑定，而不是塞进静态config digest。

## Failure taxonomy

建议稳定分类：

- `resource_compiler_missing`
- `resource_demand_invalid`
- `resource_estimate_mismatch`（advisory/client hint与Host计算不符，仅在policy要求时阻断）
- `resource_config_identity_mismatch`
- `resource_snapshot_drift`
- `resource_limit_exceeded`
- `resource_usage_incomplete`
- `resource_usage_identity_mismatch`

public diagnostics只投影method、safe counts/units、digest prefixes和stable remediation；不echo raw
params、private config或credential。哪一类允许agent修改请求后fresh retry由现有policy显式表达，
不能自动拆分或fallback。

## Relationship to current UniProt correction

当前Goal保留以下已实现且真实的边界：

- one SDK call/approval/controlled operation；
- operation total cap 100,000；
- actual Host config决定query cap并在HTTP前验证；
- page cap按query独立，response page绑定producing query slice；
- default SDK prediction以100为cap，纠正后的37,772显示378；
- duplicate、cross-query identity、pagination link和provider schema全部fail closed。

本提案不撤销这些边界，也不授权本Goal修改Core schema。稳定文档必须将378写成默认配置下的
透明预测，并明确Host actual validation仍是唯一执行约束；在提案落地前不能称approval已经绑定
Host-authoritative limit snapshot。

## Alternatives considered

### Keep the SDK estimate authoritative

sandbox是低信任caller且不拥有Host config/quota，无法授予真实resource limit。不采用。

### Require SDK estimate to equal a static route-policy constant

比任意mapping更严格，但static policy仍可能与composition注入的runtime config、backend选择和
operator收紧值漂移；还会复制每个cap到SDK/policy/adapter三层。不作为终态。

### Remove estimates from approval entirely

避免虚假精确，但operator失去高成本请求的关键规模与bound，违背透明approval。不采用；应由
Host正确计算并表达uncertainty。

### Let the adapter recompute only at execution time

能执行安全cap，却使approval看不到实际resource topology，approval后才发现漂移，且reuse/audit
仍不闭合。不采用为唯一机制；dispatch recheck仍是第二道防线。

### Share one constants module between SDK and Host

减少代码重复，但SDK与Host处于不同runtime/image/version，且config可以operator注入/收紧；shared
constant不是authority或snapshot。可作为generated client hints，不替代Host compiler。

## Migration plan

1. **Inventory**：列出所有SDK method的现有`resource_estimate` keys、来源、单位、Host实际config/
   limiter和approval/public consumers，标记caller-owned与Host-owned。
2. **Schema/golden**：定义demand、snapshot和usage `@1` closed schemas、canonical serializer、digest
   与public projection；先以pure functions和golden tests锁定。
3. **UniProt shadow compiler**：Host基于exact params、route policy和injected
   `BioProviderHttpConfig`计算shadow snapshot，与SDK prediction比较但不改变current verdict；drift
   只进Host-private metrics/diagnostic。
4. **Config binding**：为provider configs建立canonical safe snapshots和composition-time digest
   verification；secret/private locator继续分离。
5. **Dual-write migration**：新operation同时保留legacy advisory estimate与Host authoritative
   snapshot，UI明确标识；approval/reuse暂按旧schema但shadow gate收集兼容证据。
6. **Authority cutover**：version bump operation/adapter approval envelope和repository migration；
   operation digest、approval、plan、reuse全部改绑authoritative snapshot。旧row只读，不作为新
   approved reuse来源。
7. **Usage receipts**：adapter逐route输出actual usage并由Core验证identity/bounds；offline evidence
   与report只引用validated receipt。
8. **Expand compilers**：依风险顺序覆盖NCBI、HMMER、bio_tools/HPC、structure/docking、research
   provider；缺compiler的external route保持fail closed或留在明确legacy non-cutover模式。
9. **Fresh qualification**：重新跑focused tamper/config-drift tests、non-live gates，以及AOX两次
   positive+一次fault+Chrome live campaign，之后才把新snapshot作为cutover authority。

## Compatibility and rollback

- historical operations/approvals保留原caller estimate并标记`authority=client_advisory_legacy`；不得
  原位补Host snapshot或用于new-schema approval reuse。
- 新旧schema按explicit version分流，不用字段存在性猜测。mixed snapshot authority的两个positive
  attempts不能聚合GO。
- rollback到legacy runtime时必须恢复明确NO-GO/legacy-advisory语义，不能让new approval在旧Host
  下执行。
- client SDK可以继续发送advisory prediction一段迁移期，但unknown/extra authority fields被拒绝；
  最终移除时使用correctional breaking version。
- public UI/API需要在迁移期保留read-only legacy display，同时不把legacy estimate标为Host granted。

## Risks and mitigations

- **compiler重复adapter逻辑**：抽取versioned pure policy/limit compiler，由adapter消费同一snapshot，
  不在Core复制provider HTTP实现。
- **动态provider pagination无法精确预测**：schema区分estimate/range/hard bound/actual，不伪造point。
- **config digest泄密**：只hash canonical safe fields，secret/private fields由opaque identity分离；做
  dictionary-risk审查，不公开低熵secret-derived digest。
- **approval过于庞大**：保存完整sealed snapshot artifact/digest，public projection只显示bounded
  high-value units/counts/limits。
- **config频繁变化导致重批**：只有影响execution/resource语义的fields进入snapshot；quota remaining
  用reservation authority，不把无关timestamp写入digest。
- **agent被固定策略**：demand仍允许合法batch/顺序选择；compiler不自动改参数，只返回真实bound和
  可读failure。
- **actual usage不完整**：failure/remote unknown显式标记，conservative quota reconciliation阻止
  误判零消耗。

## Acceptance criteria before implementation becomes authoritative

1. malicious/incorrect sandbox estimate不能改变Host snapshot、hard limit、approval grant或usage。
2. UniProt Host query cap分别为100、50、2时，same params得到可重算的378、756、18886 query
   estimates（37,772 accessions），snapshot绑定各自不同config digest；SDK hint漂移被明确标记。
3. operation/query/page/output/timeout/retry cap在provider I/O前验证；超限不创建HTTP/runner副作用。
4. params/input/route/backend/config/compiler/limit任一approval后漂移都拒绝dispatch或要求new approval；
   old approval不能reuse。
5. snapshot closed-schema tests覆盖unknown/missing field、单位混淆、negative/nonfinite/overflow、digest
   drift、duplicate key和noncanonical JSON。
6. composition tests证明实际注入provider config的safe digest与route/snapshot一致；private secret/path
   不进入snapshot、error、UI或evidence。
7. approval/UI/API展示Host estimate、hard limit、uncertainty和authority标记；legacy/advisory值不能冒充
   grant。
8. actual usage receipt与operation/snapshot一一绑定；跨operation receipt、超bound usage、missing/extra
   call、partial/unknown outcome全部fail closed。
9. idempotency/reuse/recovery tests证明same authoritative snapshot可稳定resume，config epoch漂移不能
   静默延续。
10. offline verifier从sealed params/input/policy/config/snapshot/usage重算identity和bound comparison，
    不联系provider或读取Host-private config path。
11. migration tests证明historical rows只读、无原位authority升级、mixed authority campaign拒绝、rollback
    恢复明确legacy NO-GO语义。
12. fresh AOX live qualification完成两次独立positive、一次fail-closed fault和Chrome proof，三次都绑定
    同一Host-authoritative resource compiler/config identity且actual usage在approved bounds内。

在这些条件全部满足前，本提案保持 **proposed / not implemented**；当前SDK resource estimate只能
称为透明预测。
