# Deferred: canonical typed public diagnostic boundary

Status: proposed, not implemented in the current AOX/HMM blank-world Goal.

## Decision boundary for the current Goal

当前 Goal 只加固真实 campaign 已触达的局部 seam：sandbox/control-socket/adapter error、binary-captured stdio 的 bounded public summary、failed ToolResult、runtime signal、`harness.failed`、HTTP error、schema-declared event diagnostic、workspace/run structured locator、S15 eval 与 AOX failure artifact使用共享 high-risk sanitizer；已知 attempt workspace/control-socket path映射成逻辑路径，常见 Host/HPC roots、private/special-use URL/locator 与 credential corpus被删除。EventStore 仍保留 public 业务事件 payload 语义，不对 user/scientific字段做无类型全局改写。AOX verifier保持独立严格扫描且不放宽。

这不等价于“能从任意自由文本中无误识别所有 private path”。例如 `/private/...` 可能是 Host path，也可能是用户语料；`/v3/...` 是 public API route；scientific report还可能合法讨论 filesystem-like motif。若在所有 event/tool/report 文本上无类型地全局替换，会损失 agent事实并改变既有字段 shape。建立 typed diagnostic envelope、private retention 与 versioned projection policy需要跨 runtime/core/Host/API/UI/evidence迁移，本 Goal只记录，不实施整体架构。

## Current evidence

1. 首次 live failure 的 Podman stderr在一句自由文本内部携带 attempt Host path。旧 projection只检查字符串前缀，导致 `SandboxRun.stderr_summary -> workspace -> blocker artifact` 泄漏并被 offline verifier拒绝。
2. `harness.failed`、runtime signal、legacy tool runtime、HTTP exception和adapter result曾各自直接保存 `str(exc)`；修一个调用点不能保护其它 durable/public出口。
3. 读取侧也重要：旧 SQLite row可在新写入 sanitizer落地后继续通过 activity feed/workspace replay泄漏。
4. 全局递归 sanitizer会产生兼容风险：某些 trace合同要求保留 `secret_token="[redacted]"` 的字段 shape，而 strict evidence又要求完全删除 `access_token`/`storage_uri` 等 key。
5. URL/path语法不是充分分类信息。当前 diagnostic producer只保留 query-free公网 locator；有科学意义的 UniProt/NCBI query必须放在 typed query field或digest中，不能作为可能携带签名/OAuth credential 的通用 URL query原样公开。`/workspace`是逻辑路径，任意 Host root则不应公开。缺少字段语义时无法同时保证零泄漏和零误伤。
6. `dual-tier-scientific-evidence-boundary.md` 处理受限 artifact/license/authorization；它不能代替诊断 schema、异常 taxonomy、event shape与private debug retention。

## Impact on agent autonomy

- agent需要具体、稳定、可行动的 error code、logical path、operation/artifact identity与retryability；把整段错误统一变成 `[redacted]` 会妨碍恢复。
- harness应先结构化世界事实，再决定哪些字段可公开；agent不应从 Host traceback、credential或locator推测系统状态。
- 用户输入、scientific evidence和report正文不是“诊断”，不能因包含 path-like文本被无差别修改。
- raw private diagnostic可供operator审计，但只通过受保护authority与opaque ref访问；普通agent/UI只获得safe projection。

## Non-goals

- 不建立第二套event store、task状态或error scheduler。
- 不把所有ToolResult都视为错误；成功scientific payload继续使用其typed DTO/artifact policy。
- 不用正则扫描替代artifact authorization、provider evidence policy或secret manager。
- 不允许public client通过opaque diagnostic ref读取raw bytes。
- 不在本提案中改变AOX科学阈值、GO reducer或browser proof。

## Target invariants

1. 每个可公开failure/diagnostic使用versioned `PublicDiagnosticEnvelope`，自由文本只作为bounded safe summary。
2. stable `error_code`、stage、retryable、operation/tool/call identities与logical path是allowlisted字段；caller不能自报Host/private字段为safe。
3. raw exception/stdio/provider diagnostics在进入public surface前写入`PrivateDiagnosticRecord`，记录raw digest/size与retention；public只持opaque ref。
4. logical path mapping由typed source提供，例如workspace authority把精确Host root映射为`/workspace`；不从任意字符串猜测“看起来像同一路径”。
5. sanitizer policy version与event/tool/error schema绑定；字段删除、保留redacted placeholder或summary退化均可离线重算。
6. public durable write先验证schema/policy，读取侧对历史row按其版本投影；不能无版本地重写canonical历史内容。
7. user message、conversation、scientific artifact/report正文不经过diagnostic sanitizer；它们使用各自content/evidence policy。
8. policy无法分类、序列化或确认安全时fail closed为稳定`public_diagnostic_unavailable`，raw内容不回退公开。
9. private URL、credential、Host/runner/storage locator corpus与unknown sensitive key在所有public diagnostic schema上零命中。
10. AOX/offline verifier继续独立检查最终bundle；producer sanitizer不能成为降低verifier阈值的理由。

## Proposed model

```text
PrivateDiagnosticRecord (Host-private)
  diagnostic_id / session + operation identity
  source_kind / raw_digest / raw_size / content type
  private storage authority / created_at / retention

PublicDiagnosticEnvelope@1
  error_code / error_type / stage / retryable
  safe_summary / safe_hint / safe_details
  tool + call + operation + artifact identities
  logical_locations[] / private_diagnostic_ref?
  policy_id / policy_result_digest / truncated

DiagnosticProjectionPolicy
  schema id / source-kind allowlist
  sensitive-key actions / logical-location mapper
  URL/locator policy / size limits / fallback code
```

`private_diagnostic_ref`没有读取authority。operator debug resolver另行认证，并只在private boundary返回raw bytes。

## Source-specific policy

- **sandbox stdio：** 精确workspace/control-socket root来自runtime context；raw digest/size针对原bytes，safe summary针对映射/脱敏后bytes。
- **tool error：** 只处理`ok=false`的diagnostic fields；成功tool payload继续走tool-specific DTO，避免误伤docs/scientific content。
- **runtime/event：** event schema声明哪些payload field是diagnostic；EventStore不对所有业务/用户字段做无类型递归修改。
- **provider/adapter：** typed error/result schema先剥离private fields，再生成public summary；raw provider evidence按artifact policy保管。
- **HTTP：** public error DTO只接受safe envelope；debug endpoint通过独立operator gate读取private record。
- **campaign：** failure artifact只嵌入public envelope与safe projection，构建时再次执行strict verifier。

## Alternatives considered

- **扩大正则到所有绝对路径：** 会误伤API route、用户输入和科学文本，且仍无法识别自定义locator，不作为最终架构。
- **只在最终bundle扫描：** 能阻止GO但失败证据本身可能无法封存，agent也已看到private内容，不足。
- **只在写入端sanitize：** 历史row继续泄漏；需要versioned读取投影。
- **全局删除所有sensitive-looking key：** 简单但破坏已有event/trace shape和credential availability等安全字段，不采用。

## Migration plan

1. 盘点ToolResult、event、runtime signal、workspace/run、provider/adapter、HTTP、UI、eval与campaign中的diagnostic字段，区分user/scientific content。
2. 定义`PublicDiagnosticEnvelope@1`与source-specific policy；建立high-risk corpus、合法URL/path corpus和shape compatibility golden。
3. 先shadow生成envelope/digest，不改变existing payload；比较泄漏、误伤、长度和agent恢复质量。
4. 迁移sandbox/tool/runtime/HTTP等高风险error seams；raw record写入受保护storage并只返回opaque ref。
5. 为durable event引入schema版本化字段投影；历史event按旧schema读取并在public read model安全映射，不改写原row。
6. 迁移provider/adapter与campaign failure artifacts，最后让UI只消费typed envelope。
7. 审计外部调用方后退役legacy free-form error fields；历史schema保持reader，不补造private diagnostic。

## Compatibility and rollback

- 同一event/tool schema固定字段action；需要删除key时发布major schema，不在原version中无声改变shape。
- migration期间可以双算policy digest，但只允许一个public payload authority；shadow结果不得进入GO evidence。
- 回滚typed producer时public surface保持NO-GO或legacy non-cutover，不能回退raw `str(exc)`。
- private diagnostic records append-only并受retention约束；回滚不把它们复制到public artifact。

## Risks

- 过度脱敏降低agent恢复能力：保留typed code/stage/logical identity，并用agent task replay评估可行动性。
- 低估source种类导致旁路：public schema registry default-deny unknown diagnostic source。
- private store成为secret dump：最小retention、size cap、encryption/permissions、operator audit和禁止LLM自动读取。
- policy版本爆炸：共享primitive但由少量source class组合，schema contract tests防止各包复制规则。

## Acceptance criteria

- high-risk credential/private URL/Unix+Windows+UNC/locator corpus在ToolResult、event、workspace、HTTP、UI、eval、report与campaign failure artifact中零命中。
- 合法`/workspace`、public API route、query-free公网 NCBI/UniProt locator、typed scientific query field与scientific文本golden不被误伤；通用 URL query/fragment默认剥离。
- historical row通过versioned read projection安全输出；canonical row不被后台重写。
- raw digest/size可与private record重算，public ref不能读取raw bytes；permissions/authorization tests通过。
- schema shape兼容测试证明同一version的redacted placeholder/field deletion规则稳定；breaking change显式升major。
- agent在典型provider、sandbox、approval和runner failure中获得足够code/stage/logical identity完成合理恢复，且不接触Host path或credential。
