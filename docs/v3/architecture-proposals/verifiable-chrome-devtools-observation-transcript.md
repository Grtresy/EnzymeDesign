# Deferred: verifiable Chrome DevTools observation transcript

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 AOX/HMM Goal 使用 `aox_browser_observation_receipt@2`，由可信 operator 在同进程 loopback Web UI 上完成一次 canonical approval，并在 Host 保留的完成后观察窗口内使用 Chrome DevTools MCP 收集 console、terminal page state 与 PNG。Host 发出随机 challenge、sealed session/approval/operation identity、hold/not-before timing 与 expected terminal state；稳定 helper 从实际观测生成摘要，并仅在 not-before 后按 mode-`0600` sibling-temp、file `fsync`、atomic no-replace install、parent-directory `fsync` 协议提交；Host 校验闭集 schema、challenge、页面/Host/UI identity、zero application error、PNG bytes、摘要和时序，并要求 final 是 post-hold、non-symlink、两次 stat/read 稳定的 regular file。

这能在当前 trusted-operator threat model 下形成一个 bounded、receipt-internal tamper-evident 的 Chrome observation receipt，也能拒绝 Host bounded poll 观察到的提前 final、final mtime 过早、不稳定文件、错误 challenge、错误 operation、错误 terminal state、console error、畸形 PNG 或摘要漂移。Host 不能由 final file 证明轮询之间的连续缺失，也不能证明该文件确实来自 atomic install/fsync；这两项是当前 trusted operator 的操作合同，不是 Host-observed provenance。它同样不等于“offline verifier 能从封存的原始 Chrome MCP response 独立重放并重算每次调用”。当前 receipt 只保存 per-call request/response digest，没有保存规范化 preimage、MCP server authority signature 或 append-only call record；console message projection/error 分类也没有版本化；`page_state` 还包含只由 Host driver public-receipt ledger 产生的 response bindings，不能仅从浏览器 DOM 或 public fetch response 推导。

因此本轮 Goal 可以继续按已声明的 trusted operator 合同验收 `@2`，但不得把结果扩张表述为 cryptographically signed、sidecar-attested、independently replayable 或 browser-origin-complete transcript。把 Chrome MCP invocation、response 与 Host-only binding 收敛成可独立复核的 observation protocol，会改变 MCP authority、Host/operator handoff、evidence schema、private/public artifact boundary、offline verifier 与兼容策略，属于独立大架构调整。本 Goal 只记录，不实现；当前 live run 不应临时发明未版本化签名或把任意 digest 当成更强证明。

当前 Goal 内的小改已把 sealed logical page URL、Host process、served UI dist digest、receipt schema id 与独立 180s submission timeout 发入 handoff/effective config。这使 dynamic identity 自洽并改善可操作性，但 handoff 仍没有 protocol id/digest、完整 closed receipt-builder input 或权威 raw-call preimage，因而不足以解决本提案的 transcript provenance 问题。

## Current implementation evidence

1. `apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_live.py::_wait_for_browser_approval()` 生成随机 `observation_challenge`，发出实际 loopback `ui_url`、sealed logical page、Host/UI dist、schema id 与 session/approval/operation/sandbox identity，并从 durable `approval.resolved` 与 `sdk_controlled_operation.approval_resolved` events 证明同一 operation 续接；driver 本身不得调用该 approval 的 resolve route。
2. `_wait_for_browser_approval()` 内部构造 `aox_browser_approval_receipt@2`，保存 fixed sealed logical `page_url`、Host process id、effective-config UI dist digest、pre/post workspace snapshots、durable event records 与 public response bindings。approval handoff 提供动态 identity，但完整 receipt 与 23-field builder 不是 handoff 内的 closed schema payload。
3. `LiveAoxAttemptRunner.__call__()` 在 formal positive terminal 后发出 `status=ready_for_completion_observation`，包含 expected page state、workspace/event digest、challenge、sealed page/Host/UI identity、schema id、receipt path、hold seconds、`receipt_not_before_unix_ns` 和独立 submission timeout。trusted operator 必须使 final target 在整个 hold 内不存在。
4. `_wait_for_browser_observation()` 以 <=0.25s bounded poll 拒绝已观察到的 early target，然后对 final file 做非 symlink、post-hold mtime、double-stat/double-read stability 与 strict duplicate-key JSON 校验，再要求 raw operator object 恰好包含 23 个字段。Host 接受后追加六个 `host_observation_*` timing 字段。这些检查不证明轮询间连续缺失或 atomic/fsync provenance。
5. runtime validator 要求 `devtools_transcript` 至少覆盖 `list_console_messages`、`evaluate_script` 与 `take_screenshot`，每行只有 sequence、tool、method、page target、request digest 和 response digest。它只检查 per-call digest 的 `sha256:<64 lowercase hex>` 形状及 aggregate transcript digest，不拥有这些 digest 的 request/response preimage，因而不能重算单次调用。
6. `devtools_command_receipt.command_digest` 和 `response_digest` 有明确 canonical preimage：前者绑定 tool/command/page/challenge/action，后者绑定 projected page state、console entries、error count、aggregate transcript digest 和 screenshot digest。它们证明 operator 提交对象内部闭合，不证明 transcript row 对应真实 MCP transport response。
7. `console_entries` 只允许 `debug|info|log|warning`、non-empty source 与 message digest，同时要求 `application_error_count=0`。实现没有版本化说明 Chrome `warn/error/issue/assert`、source location、stack/argument serialization、service worker message、重复消息或 pagination 如何投影和计数。
8. `_terminal_browser_page_state()` 组合了 browser-visible/product facts与Host-only public response bindings：session/approval/operation、approval absence、operation status、final response/report、scientific/workspace/event digests，以及 workspace/event receipt sequence/route/raw-response digest/semantic digest。浏览器可以重新 fetch 并比对 semantic bytes，但不能生成 driver ledger 中的 receipt sequence 与 raw response binding。
9. `apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_evidence.py::_browser_observation_receipt_is_valid()` 离线重算 closed receipt 内的 canonical digests和PNG，却同样没有 MCP raw-call artifact 或签名 authority，无法发现“operator 用另一份内容生成一个格式合法的 per-call digest”。
10. `docs/v3/aox-hmm-blank-world-cutover.md` 已要求 same page/Host/UI dist、terminal state、DevTools transcript、zero console error、完整 PNG 与 Host timing，但没有定义可复现的 MCP request/response canonicalization、console normalizer 或 browser/Host composite-state protocol。

## Problem statement

### Digest without an authoritative preimage

当前 transcript 可以抽象为：

```text
Chrome DevTools MCP call
  -> operator sees CallToolResult
  -> operator chooses a projection and computes request/response digest
  -> bundle stores only digest
  -> offline verifier checks digest syntax and receipt-internal aggregate
```

当规范没有声明“哪些 request fields、content blocks、image bytes、tool metadata、ordering 与 transport error 进入 preimage”时，两个诚实 operator 可能对同一次调用产生不同 digest。更重要的是，offline verifier 没有 bytes 或 authority receipt，不能区分真实 MCP response digest 与任意格式合法 digest。aggregate transcript digest 只把未知 preimage 的 digest 列表再 hash 一次，不会恢复来源证明。

### Unversioned console semantics

Chrome console 是带类型、source、arguments、stack、timestamp、execution context 与 pagination 的结构化流。当前四字段 projection 没有决定：

- `warn` 是否映射为 `warning`，`assert`、`issue`、unhandled rejection、CSP 或 failed network resource 是否计入 application error；
- message digest 是 text、formatted arguments、完整 protocol record 还是 operator display string 的摘要；
- source 是 URL、execution context、service worker、console API 类别还是 operator label；
- pagination、preserved navigation、重复/updated message 与 late message 的闭合规则；
- console message 中可能出现的 credential、query、Host path 或许可内容如何在 private raw record 与 public safe projection间隔离。

没有版本化 normalizer 时，`application_error_count=0` 是可信 operator 的 assertion，不是 verifier 从原始 console stream 重算的结论。

### Composite state with two authorities

terminal `page_state` 同时需要：

1. Chrome authority：当前 target、actual loopback location、DOM/accessible UI、console、screenshot、浏览器发起的 public fetch；
2. Host authority：driver public-API receipt sequence、raw response digest、semantic response digest、event replay cursor 与 effective UI dist identity。

把 Host 的 `expected_page_state` 原样放进 operator receipt可以保证两侧值相等，但如果没有一个版本化 merge protocol，不能说明哪些字段由 Chrome 实测、哪些由 Host封存、Chrome 对 Host字段执行了什么 comparison。要求“所有 page_state 都来自浏览器”是不可能的；要求“所有字段都由 Host 给出”又会把浏览器观测退化为截图附件。

### Agent-operability consequences

- agent 无法从稳定 schema 判断应如何摘要实际 MCP output，只能依赖会话内手工约定；相同世界状态可能产生不同证据。
- 极短 final handoff 窗口会迫使 agent 在证明语义尚未固定时快速拼装 JSON，增加误填而不是增加真实约束。
- verifier 的错误只能报告 `browser_observation_receipt_invalid`，不能指出是 console normalizer、call receipt、state merge、signature、pagination 还是 browser authority失败。
- harness 把真实约束以 digest slot 形式呈现，却没有把产生 digest 的权威协议呈现给 agent；这会压缩 agent 的策略自由，使其不得不猜 harness 私有表示。
- 若未来 MCP server、Chrome protocol 或 tool response格式变化，现有 `@2` reader无法区分无语义变化的serialization升级与实际证明退化。

## Impact on agent autonomy and trust

- agent 应决定何时观察、选取哪个已经由 Host challenge 绑定的page target，以及如何处理真实UI失败；它不应发明digest preimage、console error taxonomy或Host/browser merge规则。
- harness 应提供versioned closed observation protocol、支持的MCP authority与stable error，让agent能依据真实失败重新观察或诚实NO-GO，而不是修改JSON直到validator接受。
- observation sidecar/MCP authority只证明工具调用与响应，不拥有approval、task、report、scientific outcome或GO reducer；不能变成第二套control plane。
- Host仍拥有session/approval/operation/effective-config/public receipt truth；Chrome authority不能覆盖Host state，Host也不能代写browser console/screenshot事实。
- private raw console/MCP bytes可以支持复核，但不得直接进入public workspace/report；public projection只暴露safe closed facts和digests。
- 任何signature、sequence或transport失败都必须显式fail closed；不能回退到unsigned operator digest、synthetic empty console、Host screenshot或auto approval。

## Non-goals

- 不改变`session + task board + lane/workspace + approval + runtime/drain`顶层产品真状态。
- 不改变AOX科学workflow、NCBI/UniProt身份、motif规则、HPC证明、MICU账本或GO reducer的三attempt顺序。
- 不让MCP server、sidecar或浏览器自动批准operation；approval仍由用户通过public UI显式触发。
- 不把Chrome DevTools Protocol全部永久保存或公开；只封存versioned protocol要求的bounded raw/projection bytes。
- 不让agent/operator提交签名key、伪造page target authority、选择Host process或覆盖served UI digest。
- 不用screenshot OCR替代workspace/event/report structured state，也不用DOM text替代canonical public API semantic bytes。
- 不要求浏览器生成Host-only receipt sequence/raw-response binding；两类authority通过显式composite protocol合并。
- 不原地改变`aox_browser_observation_receipt@2`语义。未来可独立复核能力使用新schema/version，历史`@2`永远按trusted-operator scope解释。
- 不在本提案中解决通用remote browser farm、multi-user browser tenancy或非loopback部署；首阶段只覆盖当前trusted local Host + Chrome DevTools MCP。

## Target invariants

1. 每个observation由Host签发唯一、不可重用的challenge，精确绑定session、approval、operation、Host process、served UI dist、sealed page identity、allowed MCP authority、protocol version、hold/not-before/deadline与nonce。
2. challenge、browser target binding、MCP call sequence与final observation receipt形成单一operation-scoped lineage；跨attempt、跨page、跨Host process、过期或重复challenge全部拒绝。
3. 每次required MCP call都有versioned closed request preimage、response preimage或authority-signed receipt；offline verifier可以不联网重算digest并验证sequence、method、target与challenge。
4. signed receipt绑定MCP server identity/version、browser target/session epoch、request digest、response digest、call sequence、started/completed timing与outcome；operator不能覆盖这些字段。
5. `list_console_messages`使用versioned console normalizer，从sealed raw response确定ordered public entries、application error count、pagination completeness与redaction receipt；同一raw response得到唯一projection。
6. `evaluate_script`使用registered observation program id/digest，而不是任意unsealed JavaScript。request绑定program digest、expected Host facts与target；response绑定browser-derived facts和comparison result。
7. browser-derived state与Host-derived state分别closed-project，再由versionedmerge function生成composite page state；每个field有唯一authority，冲突显式失败。
8. screenshot receipt绑定实际MCP response或sidecar-captured raw PNG bytes、target、viewport、capture mode与digest；完整PNG由offline verifier解码，不能只信operator dimensions。
9. final handoff file只引用已sealed call receipts/artifacts与composite result；operator负责触发观察和atomic publish，不负责生成authority fields或重写raw result。
10. observation必须覆盖整个Host hold窗口：console cursor/window起点、terminal evaluation和screenshot completion均受Host challenge timing约束；late message、navigation或target replacement有closed failure。
11. private raw MCP/console response可能含敏感内容，必须进入restricted evidence tier；public bundle只含allowlisted projection、content digest、redaction policy/version与authority receipt。
12. unknown protocol/server/program/normalizer/version、missing call、extra authority field、signature失败、sequence gap、pagination不完整、state conflict或redaction失败全部fail closed。
13. retry必须由Host签发新observation attempt/challenge并保留旧failure receipt；不能覆盖原final文件、重用call sequence或在同challenge下选择“能过”的第二份console。
14. observation failure只影响Chrome proof/cutover eligibility，不自动改写task业务终态、scientific report或已完成operation。
15. 历史`@2` verifier不升级解释为independent transcript；新schema verifier也不接受用`@2` operator digests填充signed/raw receipt slots。

## Proposed protocol and object model

建议未来发布独立协议族，例如：

```text
BrowserObservationChallenge@1 (Host authority)
  challenge_id / nonce / protocol_id + digest
  session_id / approval_id / operation_id + digest
  host_process_identity / served_ui_dist_digest / sealed_page_identity
  allowed_mcp_authority_id / registered_program_ids
  ready_at / not_before / submission_deadline / console_window_start

BrowserTargetBinding@1 (MCP authority or sidecar)
  challenge_id / mcp_authority_id + version
  browser_instance_epoch / page_target_id / navigation_epoch
  actual_origin_digest / document_identity / bound_at
  authority_receipt_digest / signature

McpCallReceipt@1 (authority issued)
  challenge_id / target_binding_id / call_sequence
  tool / method / request_schema_id / response_schema_id
  request_content_digest / response_content_digest
  started_at / completed_at / outcome / failure_code
  raw_request_artifact_id / raw_response_artifact_id
  authority_id / signing_key_id / signature

ConsoleObservationProjection@1
  call_receipt_id / normalizer_id + implementation_digest
  cursor_start / cursor_end / pagination_complete / navigation_count
  safe ordered entries / application_error_count
  raw_private_artifact_digest / redaction_receipt_digest

RegisteredPageStateObservation@1
  program_id + source_digest / call_receipt_id
  browser_facts / browser_facts_digest
  host_expectation_digest / comparison_outcome / conflicts

BrowserScreenshotObservation@1
  call_receipt_id / png_private_or_public_artifact_id
  png_digest / dimensions / viewport / capture_mode

CompositeBrowserObservationReceipt@1
  challenge + target binding + exact ordered call receipt ids
  console/page/screenshot projection ids + digests
  Host facts / browser facts / merge_protocol_id + digest
  hold coverage / submission receipt / terminal outcome
```

这些对象是现有controlled operation/attempt evidence的下属attestation，不是新的session或task owner。所有signature覆盖canonical bytes和schema id；key rotation通过authority/key id显式表达，不能把“来自本地socket”当作永久身份。

## Authority and ownership boundaries

- **Host API/cutover driver**：签发challenge、绑定product identity、提供Host-only expectation/public receipt bindings、控制hold/deadline、接受最终引用并投影public receipt；不生成Chrome call response。
- **Chrome DevTools MCP authority**：执行exact registered calls，维护browser instance/page/navigation epoch，产生closed call receipts；不读取或修改control-plane repository。
- **Local observation sidecar（可选实现）**：若现有MCP server不能签发receipt，在authenticated local channel上代理tool calls、capture raw request/response、签名并写restricted artifacts。它不能提供任意filesystem/HTTP代理或approval shortcut。
- **Operator/agent**：选择Host允许的target、通过UI完成approval、触发registered observation workflow并提交final reference；不能填写authority-owned digest、error count、page state或signature。
- **Evidence boundary**：保存private raw records、public safe projections、redaction receipt与retention policy；禁止console/raw response泄露到workspace/report。
- **Offline verifier**：验证schema/signature/authority/key、重算raw/projection/merge/PNG digest和timing，不连接Chrome/Host/network，也不信operator summary。
- **GO reducer**：只判断required Chrome attestation是否passed并与positive 1 identity一致；不解释raw DevTools protocol。

## Observation flow

1. Positive 1 formal operation通过public UI进入browser approval gate；Host在approval lineage验证后继续同一operation。
2. formal terminal且product-path blocker为空时，Host创建`BrowserObservationChallenge@1`，封存effective UI identity、registered protocol/program/normalizer、console window、not-before和submission deadline。
3. operator把challenge交给本地observation client；client通过authenticated MCP/sidecar列出target，要求实际loopback origin、browser/page epoch和Host sealed identity匹配，然后取得`BrowserTargetBinding@1`。
4. observation client按protocol顺序执行console、registered evaluate program与PNG capture。每次调用的exact request/response进入restricted artifact，authority对closed call receipt签名。任一调用失败后不继续生成passed composite receipt。
5. console normalizer从raw response验证pagination/window/navigation并生成safe projection。error taxonomy由normalizer version决定；unknown message type默认error/unsupported，不静默丢弃。
6. registered evaluate program从浏览器读取DOM与canonical public workspace/event replay semantic facts；它输出browser-owned fields和对Host expectation的comparison，不回填Host receipt sequence。
7. Host merge verifier按field ownership把browser facts与Host facts合并。相同语义字段必须digest一致；Host-only binding只由Host注入并明确标注authority。
8. screenshot raw bytes通过MCP/sidecar receipt绑定target和capture timing；evidence boundary验证PNG并形成safe projection。
9. not-before后，operator只atomic提交composite receipt/reference。Host验证签名、call sequence、timing、target/challenge、projections和merge result，再追加Host acceptance timing。
10. attempt sealer把public composite receipt与所需restricted artifact digests封存；offline verifier从bundle+authorized evidence root独立复核。positive 2/fault不继承positive 1 challenge或call receipt。

## Stable failure semantics

建议closed failure codes：

- `browser_observation_protocol_unsupported`：protocol/program/normalizer/MCP authority版本不受支持。
- `browser_observation_challenge_stale`：challenge过期、已消费、跨attempt或不在window。
- `browser_target_binding_mismatch`：page/browser/navigation epoch、origin、Host或UI dist identity不匹配。
- `browser_mcp_call_receipt_missing`：required method没有唯一call receipt。
- `browser_mcp_call_sequence_invalid`：sequence gap、duplicate、extra forbidden call或顺序不符。
- `browser_mcp_call_signature_invalid`：authority/key/signature/canonical bytes校验失败。
- `browser_mcp_response_digest_mismatch`：sealed raw response与call receipt不一致。
- `browser_console_projection_invalid`：pagination、normalization、redaction或message schema失败。
- `browser_application_error_observed`：versioned taxonomy重算得到非零application error。
- `browser_page_state_conflict`：browser facts与Host expectation或field ownership冲突。
- `browser_observation_program_drift`：evaluate program source/implementation digest不匹配。
- `browser_screenshot_receipt_invalid`：PNG bytes、target、timing、viewport或call binding失败。
- `browser_observation_submission_too_early` / `browser_observation_submission_timeout`：final publish不在closed timing bounds。

所有public error只带safe schema/authority/call/field identity和digest，不回显console文本、raw script result、loopback端口、private artifact path、key material或credential。自动retry只能请求新challenge；不能在旧challenge下删除error message、换page或改normalizer。

## Phased migration plan

1. **冻结并窄化`@2`表述。** 文档和verifier明确它是trusted-operator closed receipt，不宣称independent call provenance。保留现有negative tests和历史reader。
2. **完成剩余operator handoff protocol。** 当前小改已发出safe sealed page identity、Host process、served UI dist、schema id和完整submission timeout；本阶段剩余工作是引入protocol id/digest与closed receipt-builder input，消除operator从静态guide/code补全23字段及digest preimage。该阶段仍不是signed transcript。
3. **盘点MCP wire/result。** 对当前Chrome DevTools MCP的list/evaluate/screenshot request和CallToolResult建立字段、content block、image、error、pagination和version drift inventory；不得先选一个方便serialization便称canonical。
4. **定义raw artifacts与canonical schemas。** 为三类required call固定request/response schema、canonical encoding、size bounds、private/public tier和redaction规则；建立golden corpus。
5. **定义console normalizer和registered evaluate program。** 固定error taxonomy、source/message normalization、pagination/window semantics、program source digest与browser/Host field ownership。
6. **实现unsigned shadow recorder。** sidecar/MCP wrapper只记录raw call artifacts和candidate receipts，与现有operator`@2`并行比较；shadow结果不可满足GO且不得执行第二次approval/observation副作用。
7. **引入local authority与key lifecycle。** 选择MCP原生signed receipt或最小authenticated sidecar，定义authority enrollment、key rotation/revocation、browser epoch、socket权限与crash recovery。
8. **发布新major evidence schema。** Host接受`CompositeBrowserObservationReceipt@1`（或`aox_browser_observation_receipt@3`），offline verifier强制验证raw artifacts/signatures/projections/merge；schema变化按breaking change发布。
9. **canary真实Chrome E2E。** 同一次positive 1同时生成legacy `@2`与shadow new receipt，比较terminal facts/PNG/console；只有新路径稳定通过后才允许新campaign要求strong proof。
10. **切换cutover gate。** 新campaign只接受new schema。失败不回退`@2`；历史bundle仍由`@2`reader按旧scope验证。
11. **退役active operator-digest writer。** 确认无外部调用方后删除新run中的手工per-call digest/console projection入口，保留历史fixture和offline reader。

## Compatibility and breaking-change strategy

- `aox_browser_observation_receipt@2`内容与解释永久冻结；不得给它追加“signed”或“independent”语义。
- 新protocol使用新schema id/major version，并在effective config、challenge、attempt bundle和campaign identity中封存protocol/normalizer/program/authority identities。
- shadow阶段可以双读但不能双权威：current `@2`仍是当前campaign判定输入，new receipt只作comparison；切换后反过来也不允许`@2`fallback。
- raw restricted artifacts是新schema的required evidence，不得用仅digest的历史记录回填。历史bundle缺raw response是正常scope，不进行伪迁移。
- MCP server/sidecar升级若改变canonical response、console taxonomy或program semantics，必须发布新version/digest；只改变非语义transport字段可由明确compat normalizer处理。
- key rotation保留旧public verification keys和revocation时间语义；不能因当前key变化让既有sealed bundle不可验证，也不能让撤销key签发新receipt。
- rollback关闭new route并让要求strong proof的新campaign保持NO-GO；不能降级回trusted operator继续宣称同一acceptance level。
- local-dev首阶段可只支持一个allowlisted authority/browser instance，但schema不得把process-local path、port或machine secret投影为public identity。

## Security, privacy and operability risks

- **sidecar成为高权限浏览器代理：** 只允许registered methods/program、loopback target与bounded payload；禁止arbitrary CDP、filesystem、network proxy或approval resolve API。
- **authority key被盗：** key放入OS-protected storage或短寿命process authority，receipt绑定browser/Host/challenge epoch；支持rotation/revocation和audit。
- **replay/cross-session substitution：** signature覆盖challenge、session/approval/operation、target/navigation epoch、call sequence和timing；challenge单次消费。
- **raw console泄密：** raw artifact默认restricted，加密/权限/retention隔离；public normalizer只输出level/source class/message digest/error count和redaction receipt。
- **malicious page伪装UI：** target binding验证actual loopback origin、document/UI dist identity、Host challenge与navigation epoch；screenshot不能单独建立identity。
- **registered script本身越权：** program source固定digest，禁止动态eval/arbitrary arguments；只读DOM和allowlistedpublic endpoints，不读取storage/credential或发mutation request。
- **late console race：** challenge定义console cursor和window closure；finalization先封console end cursor，再capture terminal facts，Host acceptance后不把late message静默忽略。
- **pagination truncation：** response receipt绑定page/cursor与completion marker；缺页、重复页或server cap未知时fail closed。
- **DoS/oversized response：** request/response/console/PNG有closed数量、字符、byte和时间上限；超限产生稳定failure而不是截断后声称clean。
- **clock disagreement：** Host monotonic时间仍决定hold，authority receipt使用Host challenge window和bounded skew；wall clock只用于可审计时间，不单独建立顺序。
- **operator失去策略自由：** protocol只固定证明mechanics；agent仍可选择诚实NO-GO、重新请求新challenge或调查真实UI错误，不能被harness强迫隐藏error。
- **迁移双观察扰动：** shadow recorder应复用同一read-only MCP calls/bytes或明确一次capture多投影；不得因比较路径额外导航、刷新或改变console。

## Test matrix

### Schema, canonicalization and property tests

- challenge、target binding、call receipt、console projection、page observation、screenshot与composite receipt的closed schema：missing/extra/duplicate/non-finite/unknown-version全部拒绝。
- canonical field reorder不改变digest；任一语义字段、content block、binary byte、sequence、target、challenge或timing变化必须改变digest/signature。
- request/response golden覆盖Unicode、empty content、multiple text/image blocks、tool error、timeout、partial response和MCP版本字段。
- registered evaluate program source digest、argument schema与output schema有golden；任意source/argument漂移拒绝。

### Signature and authority tests

- valid current key、rotated historical key、revoked-before/after-signing边界、wrong authority、wrong key id、bit flip、truncated signature和noncanonical bytes。
- receipt跨challenge/session/operation/page/browser epoch重放全部失败。
- sidecar socket/IPC权限、peer identity、multiple client race、crash/restart和stale sequence fail closed。
- caller/operator不能提交或覆盖authority id、response digest、error count、target epoch或signature。

### Console normalization tests

- `debug/info/log/warn/error/assert/issue/unhandled rejection/CSP/network failure`和service worker消息的versioned分类golden。
- source URL/context/stack/argument serialization、Unicode、circular value、large message、duplicate/update与redaction均deterministic。
- pagination完整、缺页、重复页、out-of-order、preserved navigation、late message和server cap unknown边界。
- raw response相同必须产生相同safe projection/error count；任一application error必使passed=false，不能通过filter隐藏。

### Browser/Host composite-state tests

- browser facts和Host facts按field ownership合并；Host-only binding不要求browser伪造，shared semantic digest必须完全一致。
- wrong session/approval/operation/digest、approval仍存在、operation非terminal、final response/report缺失、workspace/event replay drift分别返回稳定code。
- browser fetch raw response与Host driver receipt可内容相同但sequence不同；merge只在声明的authority字段比较，避免假冲突或越权覆盖。
- navigation/target replacement、actual origin drift、UI dist drift与stale document epoch在observation前失败。

### Screenshot and timing tests

- real Chrome viewport PNG positive；CRC、IHDR/IDAT/IEND、trailing bytes、zlib bomb、dimension、interlace和digest负例。
- capture receipt必须绑定同一target/challenge和window；另一tab、旧screenshot或operator-suppliedunbound PNG失败。
- final target提前出现、symlink、partial/unstable write、mtime before not-before、post-install modification和submission timeout全部失败。
- configurable submission grace进入effective config/challenge/receipt；边界前后用monotonic fake clock deterministic测试，不依赖慢sleep。

### Integration and live tests

- local same-process Host +真实Chrome DevTools MCP产生一套raw call artifacts、valid authority receipts、zero-error console、registered state result和PNG，offline环境完全断网仍通过。
- 注入一条真实console error，normalizer与offline verifier都得到相同非零count并使Chrome gate NO-GO。
- tamper任一raw MCP response、call receipt、signature、redaction projection、Host expectation或PNG，offline verifier定位到具体stable failure。
- sidecar/MCP crash、browser close、Host exit、navigation、SSE reconnect与deadline exhaustion不产生partial passed receipt，也不自动改task/report状态。
- shadow migration证明legacy `@2`和new protocol共享同一实际observation，不发生第二次approval或隐藏refresh；差异产生comparison artifact而非择优成功。

## Acceptance criteria

- offline verifier在没有Chrome、Host或network连接时，能从sealed authorized evidence重算每个required MCP request/response digest、验证authority signature和exact ordered call sequence。
- console clean结论由versioned normalizer从sealed raw response重算；pagination/window完整，任何classified application error都稳定导致NO-GO。
- registered evaluate program和merge protocol能分别证明browser-owned与Host-owned字段；没有字段由operator自由填写，也不要求browser伪造Host receipt binding。
- screenshot raw bytes由same target/challenge的authority call receipt绑定，PNG/dimensions/digest可离线重算。
- challenge、target、Host process、UI dist、session/approval/operation、hold/not-before/deadline和attempt identity形成单一不可重放lineage。
- private raw console/MCP bytes不进入public workspace/report；public projection、redaction receipt与restricted artifact retention通过secret/path/licensed-content corpus。
- operator只负责真实UI动作、target选择和final atomic publish，不再选择per-call digest preimage、console taxonomy或page-state authority。
- new protocol失败不回退unsigned digest、synthetic empty console、Host-only screenshot、auto approval或旧`@2`；agent收到stable可行动failure。
- 历史`@2`bundle仍可按trusted-operator窄scope复核，但任何文档/接口/verifier都不把它升级声称为independently replayable transcript。
- 至少一次真实positive Chrome E2E和一组tamper/error live negatives证明new receipt可封存并完全离线验证，随后才允许要求strong Chrome proof的campaign cutover。

## Current-Goal statement

本提案没有在当前 AOX/HMM blank-world Goal 中实现。当前 Goal 继续使用已测试的 `aox_browser_observation_receipt@2` trusted-operator合同，并可做不改变证明等级的局部handoff/操作性修复；不得新增sidecar、签名authority、raw MCP artifact schema、console normalizer major version或`@3` verifier。任何当前GO结论必须把Chrome证据描述为“same-process UI、durable approval lineage、Host-held window、可信operator提交的closed observation receipt”，不能描述成“原始DevTools transcript已被独立离线重放或authority签名”。
