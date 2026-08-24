# Resident Teammate Product Loop

本文固定 OpenZyme V3 从 fresh Session 到常驻队友可恢复回复的产品心智模型。它解释产品用户看到的状态、
每一层的 owner、identity、lifecycle、persistence、compatibility、error semantics 与 forbidden fallback；
具体代码事实仍需与当前源码、主规格及 OpenSpec
`complete-openzyme-resident-teammate-product-loop` 的归档工件和实现证据交叉验证。

## 一条不可折叠的产品链

```text
create Session
  -> durable workspace reservation / provisioning intent
  -> provisioning worker: provisioning -> ready | blocked
  -> admit user message + workflow authority + inbox + wake signal
  -> explicit runtime drain command
  -> claim one signal and build structured world context
  -> bounded provider/tool loop with Direct/Deferred/Hidden exposure
  -> fenced outcome settlement
  -> canonical assistant/tool/failure transcript and collaboration projection
```

这些步骤是不同 command/occurrence。以下等价关系全部错误：

- Session 已创建 ≠ workspace 已 ready；
- message accepted ≠ Agent 已运行；
- drain accepted ≠ command 已完成；
- Agent turn idle/step-limit ≠ Task completed；
- tool/provider returned ≠ outcome 已持久化；
- Plugin installed/mounted ≠ tool Direct/authorized/qualified；
- non-live E2E green ≠ deployment cutover/live external readiness。

## Owner 与持久化

| 事实 | canonical owner | 机制 owner | durable representation |
| --- | --- | --- | --- |
| Session、Task、lane、Agent、inbox、approval | Kernel | Store Adapter 提供事务/codec | ControlStore/SQLite owner rows + version ledger |
| workspace generation/readiness | Kernel | selected Workspace Adapter 提供 volume/Git mechanism | `WorkspaceGeneration`、runtime binding、provisioning intent/receipt |
| workflow selection authority | Kernel | Distribution registry resolver 解释已采用 refs | `WorkflowAuthorityBinding`、`RuntimeSignalAuthorityLink` |
| runtime command/context/signal/lease | Kernel | Runtime Adapter 执行 bounded mechanism | command/context、signal/lease/claim、event/outbox |
| model tool presentation | Distribution role policy + Kernel resolver | Runtime Adapter 投影 provider schema | affordance/exposure snapshot；command expansion 不是产品真状态 |
| provider/tool outcome与conversation | Kernel outcome settlement | Runtime/Plugin mechanism 返回提案/receipt | immutable outcome、assistant/tool message、failure、settlement |
| Git bytes/revision/LFS | Git/LFS Adapter mechanism；Kernel publication owner | Git/LFS process/transport | owner volume/bare repo/LFS bytes + typed observation/receipt |

Adapter/Plugin/Driver 私有表、prompt、memory、浏览器 state、workspace 文件、provider response 和 subprocess stdout
都不能成为上表 Kernel 真相的替代 owner。

## Session bootstrap 与 workspace provisioning

bootstrap 的短事务至少固定：

- exact project repository binding pin；
- master Agent/member identity 与 process epoch；
- generation 1 的 `WorkspaceGeneration(RESERVED)`；
- 绑定 generation 1 的 pending `AgentAuthorityLease`；
- exact provider/target/Adapter binding 的 durable provisioning intent；
- Session composition/capability binding 与 event/outbox。

HTTP 在这些事实提交后返回 `provisioning`，不等待 volume allocate、Git clone、credential round-trip 或 provider。
bounded worker 以 CAS claim 获取唯一 occurrence，写事务外调用 selected Adapter，回到 Kernel 后按 exact
intent/generation/claim/receipt fence 结算：

- success：generation/runtime binding/member/lease/intent 原子进入 ready；
- `no_effect` failure：blocked，只有显式 recovery 才可再次行动；
- `dispatch_in_doubt`：blocked + reconcile required，禁止重新 dispatch；
- terminal-known failure：blocked，保留 mutation fact 与 diagnostic；
- duplicate exact callback：幂等；identity drift：在 mutation 前拒绝。

每个 blocked provisioning occurrence 都必须形成同一 `diagnostic_id` 关联的公开
`FailureObservation` 与私有 `PrivateDiagnosticRecord`。worker 从 Adapter 收到的私有 sidecar 只在进程内随
receipt 传回 Kernel，Kernel 在结算事务中同时持久化 failure、diagnostic 与 blocked intent；Adapter 若只返回
blocked 状态而没有闭合 failure pair，Kernel 会先把该不完整 receipt 归一为明确的 harness failure，再按同一规则
结算，不能把缺诊断的 blocked 当成已知产品事实。公开 projection 只读取 failure，私有 traceback、request 与
Adapter context 不进入 Host/CLI/UI。

系统没有同步 clone fallback、in-memory workspace、相邻 Adapter、目录存在即 ready、测试 direct seed 或自动
successor generation。replacement/reconcile/new generation 都是 operator 明确 command。

其中 `dispatch_in_doubt` 的 reconcile 不是重开原 intent，而是创建独立、持久、可claim/settle的
`WorkspaceProvisioningReconciliation@1`。它绑定原 intent digest/state-version、request、dispatch receipt、
attempt/parent与claim fence，只调用selected Adapter的observation-only reconcile。READY可原子激活原reserved
generation/runtime binding/lease，但原blocked intent、receipt和failure永不覆写；terminal blocked diagnosis
只能把next action推进为显式successor，后者创建下一monotonic generation、新pending lease与新intent。

## Request-lineage workflow authority

`workflow_refs`（以及兼容 wire 上的 `skill_keys`）只是选择请求。Distribution resolver 在 Session 已采用的 exact
registry snapshot 下把请求解析为 versioned ordered refs；Kernel 才拥有 authority binding。root message 即使选择
为空也创建 active empty binding，避免 missing 被解释为 default/all。

binding 至少固定：authority/session/project、request lineage、source message/principal、authorized actor、exact
selection/digest、registry snapshot、task/lane scope、parent/derivation/causation、status、epoch、timestamps 和
binding digest。每个 runtime signal 另有 exact link，signal 不以 raw refs代替它。

派生规则：

- `task.delegate` 只能创建 parent selection/scope 的子集；
- `protocol.send` 只写 inbox + wake signal/link，不运行 recipient；
- approval resolution 与 continuation delivery 沿 source authority/causation排队；
- actor/scope 改变时必须创建显式 child binding；
- revoke/expire/consume 通过 CAS 增加 epoch并改变 status。

runtime admission、provider invocation前、每个tool/delegation dispatch前都重验 exact binding/link。禁止从
memory、summary、Task、protocol/assistant prose、“latest workflow”、全 registry scan 或 parent/child union恢复
authority。registry drift、legacy missing link、revoked/stale epoch都 fail closed。

workflow resolver 在 message admission 之前失败时，原 admission Unit of Work 不产生 message、binding、inbox、
signal 或 link；Kernel 另以同一原始 ingress authority 写一个公开/私有诊断 pair，并保留原 resolver error 为
exception cause。相同 request/registry/error occurrence 跨 advancing clock 与进程重启仍复用 exact failure/
diagnostic identity，不重复 event/outbox；pair 缺一半或 identity/digest 冲突则显式
`workflow_resolution_diagnostic_collision`，不能继续 admission 或选择 empty/default workflow。

## Structured world context

Kernel 为每个 claimed signal 生成 `RuntimeTurnContext`，至少含：

- Session objective/status/version/request lineage；
- current Agent/member/role/process epoch/authority lease；
- scoped Task、board、dependency与明确 terminal facts；
- lane、workspace generation/readiness/revision；
- unread inbox、delegation/protocol causal refs；
- approval/continuation；
- public-safe failure与 `diagnostic_id`；
- workflow authority status/epoch/selection；
- capability binding、affordance、tool exposure与exact route；
- bounded canonical user/assistant/tool conversation。

各 fact class 有固定 collection/byte bound、排序和cursor/truncation fact。current authority、task、workspace、
approval、failure、affordance/exposure identity不可由Adapter为省token而删除；超出整体输入budget时必须显式失败。
Adapter可以确定性压缩历史 transcript，但summary只能是历史信息，不能授予authority或覆盖current truth。

context 告诉模型“世界现在是什么、什么能做、什么受阻”，不告诉模型“应该选哪个策略”。agent仍决定任务拆分、
工具顺序、研究路径、何时请求approval/发布/finish。

## Direct、Deferred 与 Hidden

四类事实保持分离：declared catalog表示composition声明了什么；capability/resource/route表示机制条件；
affordance表示本turn是否真正可调用；exposure只表示如何向模型呈现。

- `Direct`：稳定协作动词和当前role必需工具；affordance available时进入provider function list。
- `Deferred`：available或blocked的long-tail Plugin tools；可被`capabilities.inspect`安全发现，但初始不进入list。
- `Hidden`：role/policy禁止向模型披露；provider和inspection都看不到。

Standard baseline至少覆盖world/capability inspection、task create/update/finish/delegate、protocol send、approval
request和role适用的workspace tools。EnzymeDesign再按role把少数必需Plugin tools设为Direct，其余long-tail通常
Deferred。policy必须覆盖exact catalog；缺失/unknown/duplicate/release drift在startup/admission时拒绝，不能默认
all-visible。

`capabilities.inspect` 可以先查询，再提交 exact `expand_tool_names`。扩展只在同一 command 后续 provider step
生效；新 command/continuation重新计算。扩展不创建authority、不批准操作、不清除workspace/qualification/health
blocker、不选择另一route。无论Direct还是expanded，gateway dispatch前都重验当前facts。

## Stable collaboration verbs

model-facing verb 必须落到唯一 Kernel application owner：

- `task.create` / `task.update`：普通字段和非终态；
- `task.finish`：唯一显式业务终态入口，运行owner/validator/evidence检查；
- `task.delegate`：product-facing delegation，真实路径为 `ProtocolService.delegate()`；
- `protocol.send`：inbox + wakeup/link，不同步运行；
- `approval.request`：创建pending approval，human resolution走Host/CLI/UI；
- `world.inspect` / `capabilities.inspect`：只读current scoped facts；
- workspace/file/process verbs：只经selected Workspace Adapter与current runtime scope。

参数错误是LLM可读structured tool error；effect不确定时生成FailureObservation并要求reconcile。tool result、assistant
prose、idle和max steps不自动finish Task。

## Outcome settlement 与 transcript

Runtime Adapter返回closed `RuntimeTurnOutcome` 提案：disposition、summary、assistant/tool messages、tool requests、
usage、optional approval/continuation/failure。Kernel消费前重验command/outcome、signal claim、Session lease、process
epoch、workflow epoch、affordance/exposure和message/failure identities。

首次接受在一个短Unit of Work中写：

- immutable full outcome + digest；
- ordered assistant/tool `conversation_message`；
- canonical `FailureObservation`；
- signal terminal、settlement、optional continuation；
- durable event/outbox。

exact duplicate返回原consumption identity且不重复message；同command另一outcome、message/failure collision、stale
fence或缺失failure owner在任何部分mutation前拒绝。下一turn、workspace projection、CLI与UI读取同一canonical
transcript，不读取provider stdout作为产品回复。

如果 outcome 请求 continuation，settlement 只创建带 source signal/link/binding/epoch 的 durable pending intent，
不在当前 turn 同步运行下一步。Distribution worker 在当前 command 的 turn 集合完成后，或在无旧 pending signal 的
一次 bounded tick 中，独立把 intent 结算为 `delivered` 并原子创建一个新的 pending signal 与 exact authority
link；因此该 signal 最早由下一次显式 drain claim。delivery exact retry 幂等，source authority、recipient lease、
process epoch、workspace generation 或 delivery identity 漂移均在新 signal 出现前拒绝。

顶层 `RuntimeCommandRecord` 的失败终态也不是进程日志：context/admission/provider/tool/settlement 任一阶段失败时，
worker 用当前 command/claim/fence 写同一事务内的公开 failure、私有 diagnostic 与 `FAILED` command 引用；公开状态
只暴露 `failure_id` / `diagnostic_id` 与安全 effect facts。provider exception 只调用一次，不 retry、换 route 或
fallback；如果原业务 settlement 因 stale/collision 在零部分写后失败，独立诊断 occurrence 仍可重启读取，exact
retry 不产生孤儿或重复 pair。

## Public API、CLI、UI 与 compatibility

`file_workspace_public@2` root/core section集合保持不变；版本化resident facts进入既有`session`、`agents`、
`conversation`、`runtime`、`workspace`、`failures`、`tool_reflection` object sections。mutating client仍要携带exact
release/projection/binding/affordance identities。

- `POST /v3/sessions`：提交bootstrap reservation，返回readiness；
- `POST /v3/sessions/{id}/messages`：只admit/enqueue，`runtime_executed=false`；
- `POST /v3/sessions/{id}/runtime/drain`：admit bounded durable command；
- `POST /v3/sessions/{id}/workspace/provisioning/reconcile`：exact operator-only durable observation，返回`202`；
- `POST /v3/sessions/{id}/workspace/provisioning/successor`：exact diagnosed failure的新generation admission，返回`202`；
- runtime command status：Session-scoped polling；
- approval decision：写decision并schedule exact downstream work；
- workspace inspect：返回readiness、collaboration、transcript、runtime和failure truth。

`workspace_provisioning_public@2`公开intent digest/state-version与nullable safe reconciliation facts；
reconciliation READY时effective readiness可以是ready，但原intent仍公开历史blocked failure。CLI保持HTTP-only，
从投影交叉验证这些identity后提交reconcile/successor，并再次inspect；UI只以Host projection确认成功。旧Session若缺少current provisioning/workflow/exposure/outcome
identity，返回`resident_teammate_state_incompatible`；不做online seed、silent schema translation、default workflow、
default route或automatic repair。

reconcile/successor的HTTP `202` result均为exact closed admission-only合同，显式证明adapter、external effect、runtime、
Task与fallback未发生。reconciliation admission只公开occurrence/source lineage及enqueue事实，不公开worker `claim_*`、
terminal receipt、failure/diagnostic或private/tool payload；Host与CLI都在继续产品循环前fail closed验证。

runtime公开面使用独立的`runtime_command_public@1`、`runtime_turn_command_public@1`、
`runtime_turn_outcome_public@1`、`runtime_turn_outcome_receipt_public@1`、
`runtime_command_outcome_summary_public@1`与`runtime_outcome_consumption_public@1`。internal Store保留full
command/context/outcome/receipt用于fencing、settlement与restart；API/CLI/UI只获得safe identity/fence、count、
aggregate/source digest、summary、effect facts以及continuation/settlement reference，不获得claim/lease token、raw
context/messages、tool request名称/参数、嵌套internal receipt或私有failure payload。

## Error semantics 与 forbidden fallback

跨Store、Git、process、provider、tool、workflow和external effect的失败至少携带：stable code、component、phase、
related identities、effect certainty、mutation/fallback facts、retry/reconcile policy、cause chain与`diagnostic_id`。
非空public failure只接受exact closed `failure_observation@2`；旧schema、未知字段、private diagnostic或无法安全解析
的facts/identities都fail closed。public projection只保留allowlisted safe facts，且不得包含traceback、stdout/stderr、
private context或tool request；private diagnostic保存完整traceback、return code、bounded stdout/stderr和context，
异常包装使用`raise ... from exc`。

禁止：provider/Adapter/route自动切换，unknown effect redispatch，blocked action自动重开，Task自动finish，消息自动
drain，protocol同步执行，raw key/prose授予workflow authority，Deferred expansion扩大authority，旧Session在线补写。

## Non-live acceptance boundary

官方 Distribution launcher 的 preflight 不是配置自证：它只读核验实际 file-backed Store 路径/provider 与 active
release、bundle/catalog、完整 Adapter set、workflow registry、全角色 policy 和 workspace binding，才允许开放 Host
surface；不能硬编码 `file_backed=true`，也不能在身份漂移时改用 in-memory、相邻 Distribution 或 live route。

Standard与EnzymeDesign各自从empty temporary file-backed roots构造真实Distribution composition，使用deterministic
fake LLM和recording/no-effect Adapter，验证create→provision→message queued→explicit drain→assistant/tool transcript
→collaboration projection→same-root restart。EnzymeDesign再验证workflow binding、role essentials、Deferred expansion
与Hidden non-disclosure。

deny guard覆盖network、真实provider、SSH、Slurm、HPC、browser和未声明subprocess。该证据只能声明non-live
composition/product semantics；不能声明deployment cutover、真实external availability、AOX campaign、完整科学报告或
任何live effect已完成。
