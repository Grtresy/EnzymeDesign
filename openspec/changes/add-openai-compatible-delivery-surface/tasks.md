## 1. 前置架构与契约冻结

- [ ] 1.1 在任何实现修改前核验 `separate-openzyme-kernel-from-capability-extensions` 已完成全部 tasks、`file_workspace_public@2` 已真实切换、EnzymeDesign composition/wheel/startup qualification 已通过；若任一项不成立，记录 blocker 并停止 apply，不添加 `@1` 或 Host-internal fallback。
- [ ] 1.2 对照 `docs/openai-compatible-agent-integration-guide.md` 冻结 L0 验收矩阵：Bearer、`/v1/models`、JSON/SSE chat、严格 boolean `stream`、`max_tokens:1`、`sessionId`、usage、finish reason、探测超时与错误形状。
- [ ] 1.3 冻结第一版 unsupported 矩阵：tools/functions、`tool` role、reasoning、多模态、文件、attachments、Responses API、动态 model/provider/route/bounds，并为每项定义 mutation 前拒绝断言。
- [ ] 1.4 盘点完成后 EnzymeDesign manifest 的 exact Kernel/Adapter/Plugin/Driver/delivery-surface set 与 digest，生成本 change 的 source-bound 基线供派生 Distribution 比较。
- [ ] 1.5 固定 compatibility contract/schema IDs、component IDs、wheel/import names、public model label、HMAC namespace/version和错误 code registry，确保 app、manifest、docs、fixtures使用同一组常量。
- [ ] 1.6 固定并评审 request/message/output/concurrency/runtime deadline/SSE keepalive 等 hard bounds，证明它们不超过 Host contract且不能由外部 request覆盖。

## 2. Public client seam

- [ ] 2.1 审核 prerequisite 完成后的 `openzyme-client`，列出 compatibility flow 所需的 Session create/inspect、message post、runtime command admit/observe 和 `file_workspace_public@2` conversation读取能力，证明无需 repository或 Host service直连。
- [ ] 2.2 在 `openzyme-client` 公开边界补齐缺失的 closed request/response DTO和 typed methods；所有 mutation继续携带 exact release/public-contract/projection/binding/affordance与 idempotency identities。
- [ ] 2.3 为 Session create bootstrap、message idempotent response anchor、runtime `202`/poll terminal和 workspace conversation projection增加 fake transport单元测试。
- [ ] 2.4 为 stale release、public contract、binding、affordance、media type、unknown field和非 2xx safe error增加 fail-closed client测试，固定 `mutation_applied=false` 与 `fallback_performed=false` 语义。
- [ ] 2.5 增加 dependency/import gate，证明 `openzyme-client` 和 compatibility app不依赖 `openzyme-kernel` implementation、Core repository、SQLite Adapter、Host service、LLM/provider、Plugin internals或 runner/HPC。

## 3. Compatibility app 骨架、配置与安全

- [ ] 3.1 创建 `apps/openzyme-openai-compatible-api` 的 src-layout wheel、tests、README、ASGI入口和受控启动命令，并在 pyproject中登记 `component_id = "openzyme.openai-compatible.api"` 与现有 application-surface source kind。
- [ ] 3.2 实现 closed settings model，绑定一个 tenant、一个 fixed project、一个 model label、private Host URL、public listener和全部 hard bounds；拒绝 unknown config与 request-time override。
- [ ] 3.3 实现 public Bearer、private Host credential和Session HMAC key三种独立 secret locator/material加载，启动时拒绝缺失、相同 identity/digest、空值或公开配置回显。
- [ ] 3.4 校验 private Host principal 的 fixed project scope、非-admin身份以及所需 user/operator最小权限；拒绝 wildcard project或额外 authority。
- [ ] 3.5 实现 constant-time public Bearer鉴权与 OpenAI-style `401 invalid_api_key`，并测试失败鉴权零 Host请求、零Session和零runtime mutation。
- [ ] 3.6 实现 compatibility private diagnostic model与公开错误 sanitizer，记录 code/component/phase/safe identities/effect certainty/mutation/fallback/retry/reconcile/cause chain/`diagnostic_id`，禁止 secret、raw `sessionId`、prompt全文、路径、URL、traceback和backend output泄漏。
- [ ] 3.7 实现无 mutation 的 liveness/readiness；readiness必须校验配置、secret separation、single-instance topology、Host reachability、fixed project、exact release/client/public/surface contract后才为 ready。
- [ ] 3.8 为配置、secret、principal、diagnostic redaction、readiness drift与无 mutation health probe添加单元测试。

## 4. L0 wire models 与序列化

- [ ] 4.1 实现 closed chat request models，支持 string `system|user|assistant`、严格 boolean `stream`、bounded `model|max_tokens|sessionId` 和可选外部 `Idempotency-Key`，要求最后一个可执行消息为非空 user。
- [ ] 4.2 实现 unsupported/unknown field识别，分别覆盖 tools/functions/tool_choice、`tool` role、content array、reasoning、多模态、file和attachments，统一在 Host mutation前返回 `400 unsupported_parameter`。
- [ ] 4.3 实现 `GET /v1/models` 的固定 model list；证明 request model只作兼容 label，不能选择内部Agent、Provider、route、Plugin、target或approval policy。
- [ ] 4.4 实现 OpenAI-style error envelope与 HTTP mapping，覆盖 invalid request、session conflict/busy、approval required、runtime locked/failed/timeout/no output和upstream contract drift。
- [ ] 4.5 实现非流式 `chat.completion` serializer：稳定 `chatcmpl-*`、Unix `created`、fixed model label、单 choice、assistant string、`finish_reason="stop"` 与三项全零 usage。
- [ ] 4.6 实现 SSE serializer：单 role frame、UTF-8-safe bounded content frames、可选 comment keepalive、单 stop/zero usage frame和唯一 `[DONE]`，禁止把 error写入 `finish_reason`。
- [ ] 4.7 实现 post-header SSE error终止路径：safe error-bearing stop frame后恰好一个 `[DONE]`；pre-header错误仍返回非 2xx JSON。
- [ ] 4.8 添加 wire golden tests，逐字校验 media type、JSON closed shape、SSE frame顺序/分隔/终止、usage和合法 finish reason。

## 5. Session、objective 与 turn identity

- [ ] 5.1 实现版本化 HMAC-SHA256 `sessionId -> ozc_*` 映射，输入精确包含 tenant/project/session值，使用bounded编码并证明日志、response和internal ID不含raw external ID。
- [ ] 5.2 实现无/空 `sessionId` 的 fresh-per-request Session identity，以及有 external `Idempotency-Key` 时的稳定重放；明确无两者时不宣称跨请求 exactly-once。
- [ ] 5.3 实现 deployment base objective与initial system text的canonical delimiter/normalization；system text只能成为untrusted context，不能进入provider policy或authority字段。
- [ ] 5.4 实现 mapped Session create-or-inspect：验证fixed project、surface owner/access、compatible release/pin和objective；collision或drift返回 no-fallback conflict。
- [ ] 5.5 实现 existing Session的system规则：缺失不改变objective，出现时必须与canonical initial objective一致，否则在message前返回 `system_context_conflict`。
- [ ] 5.6 实现版本化 turn digest，精确覆盖tenant/project/internal Session/canonical full messages/可选external idempotency；从中派生互异的message key、drain key和public completion ID，并排除stream/model/max_tokens。
- [ ] 5.7 实现只admit最新user message的translation；既有user与assistant历史只参与turn identity，不写入canonical conversation。
- [ ] 5.8 从idempotent message response的verified projection取得本轮user `message_id` anchor，禁止依赖进程内pre-snapshot或repository读取。
- [ ] 5.9 添加Session/turn测试，覆盖重启稳定性、tenant/project隔离、raw ID不泄漏、缺失session、key namespace变化、system conflict、历史不重放、同turn retry与下一轮新identity。

## 6. 单 command 编排、并发与结果投影

- [ ] 6.1 实现单实例 bounded global coordinator与per-Session lock；不同active turn在任何Host mutation前返回 `session_busy`，相同turn retry允许进入observation路径。
- [ ] 6.2 在message admission前通过verified projection检查pending approval；存在时返回approval-required且不把“yes/approve”等聊天文本写入Session。
- [ ] 6.3 实现一次idempotent public message admission，固定latest user text和anchor identity，并审计每个new turn恰好一条user message。
- [ ] 6.4 实现一次idempotent `runtime.drain` admission，使用deployment-owned `max_signals`/`max_steps_per_agent`与`auto_enqueue_ready_tasks=false`；禁止request字段改变这些值。
- [ ] 6.5 实现只poll exact command ID的bounded observer，区分accepted/claimed/completed/failed/locked/cancelled/deadline，并且绝不提交replacement或第二个drain。
- [ ] 6.6 实现anchor-to-next-user的assistant segment投影；只读verified `file_workspace_public@2`，按canonical order以精确 `\n\n` 连接多条assistant entry。
- [ ] 6.7 实现completed/no-output、pending approval/suspended、failed、locked、cancelled、still-running timeout的truthful映射，禁止placeholder success或从Task/workspace变化推断command结果。
- [ ] 6.8 实现native operator批准后的retry恢复：复用原message/command，读取后来落在同anchor segment的assistant output，不由compatibility surface推进continuation。
- [ ] 6.9 实现client disconnect/cancellation handling：停止本连接的poll/serialization但不cancel、retry、redispatch或改变canonical Host command。
- [ ] 6.10 添加orchestration fault tests，逐项断言message/drain计数、idempotency、anchor、per-Session并发、timeout、response loss、restart、approval、operator continuation和disconnect行为。

## 7. Public API 集成与比赛探测回归

- [ ] 7.1 用fake/non-live Host启动真实ASGI app，验证有效/无效Bearer、`/v1/models`和不变的fixed model label。
- [ ] 7.2 验证比赛最小流式请求 `stream:true,max_tokens:1,model absent/null` 能快速收到parseable role data frame，最终遵守content/stop/`[DONE]` lifecycle。
- [ ] 7.3 验证非流式response含 `choices[0].message.content`、zero usage和`finish_reason="stop"`，且背后只有一个bounded runtime command。
- [ ] 7.4 验证有 `sessionId` 多轮复用、无 `sessionId` fresh Session、完整历史不重复写入以及相同请求response-loss retry。
- [ ] 7.5 验证 strict boolean、unknown/unsupported fields、request/content/identifier/output bounds、global/per-Session saturation全部在预期阶段fail closed。
- [ ] 7.6 验证pre-header JSON error与post-header SSE error矩阵，并对public bytes运行secret/raw ID/path/URL/traceback/backend词汇扫描。
- [ ] 7.7 将指南 §8 curl等价请求固化为non-live probe script/fixture，输出deterministic machine-readable receipt，不包含真实credential或live endpoint。

## 8. 派生 Distribution 与组合闭包

- [ ] 8.1 创建 `distributions/enzymedesign-openai-compatible/openzyme-composition.toml`，直接枚举exact EnzymeDesign Kernel/Adapters/Plugins/Drivers及Host/client/CLI/Web UI/compatibility delivery surfaces，不使用`extends`或ambient discovery。
- [ ] 8.2 创建 `packages/enzymedesign-openai-compatible-distribution` src-layout wheel、README、composition loader/locator selection和component metadata，project/component/import names与冻结契约一致。
- [ ] 8.3 将repository manifest以byte/digest-equivalent resource打包进Distribution wheel，并测试packaged/repository document完全一致。
- [ ] 8.4 实现compatible composition activation/fresh seed/read-only startup helper，复用公开generic composition primitives而不import Standard或EnzymeDesign作为语义层。
- [ ] 8.5 实现base-set comparator，证明compatible manifest的Kernel/Adapter/Plugin/Driver选择与同版本EnzymeDesign exact一致，唯一区别为Distribution/release identity和新增surface选择。
- [ ] 8.6 更新root `pyproject.toml` uv workspace、package依赖与`uv.lock`，确保Distribution直接闭合所选组件、compatibility app和所需Host/client/CLI/UI artifacts。
- [ ] 8.7 为missing/mismatched surface digest、extra/missing component、wrong component kind、Adapter-slot误用、ambient installed app、manifest drift和base-set drift增加negative composition tests。
- [ ] 8.8 添加single-instance topology、fixed project、三secret separation、non-admin service principal与private Host/public `/v1` network boundary的deployment config validation tests。
- [ ] 8.9 证明停止/移除compatibility surface不会删除或迁移canonical Session/Task/Approval/command/workspace/science/report状态，并保留native operator surfaces。

## 9. Architecture qualification、wheel 与 test-gate

- [ ] 9.1 将新app/package/distribution/component IDs加入source-bound architecture inventory、allowed dependency policy、delivery-surface kind检查与forbidden import规则。
- [ ] 9.2 新增 `enzymedesign_openai_compatible_single_tenant@1` non-live qualification profile及scenario registry，绑定本change specs、source files、test selectors、bounds、fault points和zero-live-effect预算。
- [ ] 9.3 扩展installed-wheel/source/import qualification，验证surface和Distribution wheel metadata/content、direct closure、manifest resource、Web UI build identity与禁止的legacy/optional依赖。
- [ ] 9.4 扩展composition/startup qualification，验证surface contract digest、matching Host release/client contract、fixed project readiness、single instance与gate-before-listener顺序。
- [ ] 9.5 将app/package/docs/manifest影响加入 `scripts/test-affected-scope-map.json`、test-gate source/resource inventory及相关architecture qualification runner选择。
- [ ] 9.6 运行新profile的protocol/orchestration负面矩阵，证明“OpenAI-shaped bytes成功但duplicate drain/secret leak/base drift”仍会使qualification失败。
- [ ] 9.7 构建所有affected wheels与Web UI assets，在隔离环境重算安装闭包和digest，并保存不含secret的machine-readable non-live receipt。

## 10. 架构、开发与运维文档

- [ ] 10.1 更新 `docs/OpenZyme架构设计.md`，加入compatible delivery surface和派生Distribution，明确它与Kernel/Adapter/Plugin/Driver及Host/CLI/Web UI的同级/所有权关系。
- [ ] 10.2 更新 `docs/v3/01-target-architecture.md`、`04-public-interfaces.md`、`05-agent-runtime.md`、`06-top-level-llm-loop.md`，记录external `/v1`到private `/v3`、one-message/one-drain、auto-enqueue false、projection output与task-terminal separation。
- [ ] 10.3 更新 `docs/v3/README.md`、`enzymedesign-distribution.md`、`deployment-composition-operator-guide.md` 和 `distributions/README.md`，说明exact compatible composition、启动门禁、single-instance、native approval和rollback。
- [ ] 10.4 新增compatibility app/distribution README与部署指南，完整列出config、secret locator、service principal、network/TLS前置、Session mapping/lifecycle/persistence、bounds、concurrency、timeout/disconnect、diagnostics和禁止fallback。
- [ ] 10.5 在部署指南中提供无secret的 `/models`、non-stream和SSE curl示例及expected shapes，并将 `docs/openai-compatible-agent-integration-guide.md` 标为比赛external contract source而非OpenZyme内部authority。
- [ ] 10.6 建立“支持/明确拒绝/后续change”表，禁止文档声称reasoning、多模态、attachments、function calling、provider token streaming、chat approval、多租户或多实例已支持。
- [ ] 10.7 文档分别说明L0 probe、non-live distribution qualification、live Provider/HPC readiness、复杂workflow terminal、public deployment和competition审核证据，禁止用前者替代后者。

## 11. 最终验证与实现边界审计

- [ ] 11.1 运行compatibility app与public client focused pytest，覆盖wire、identity、auth、orchestration、failure、bounds和secret redaction全部场景。
- [ ] 11.2 运行compatible Distribution focused pytest，覆盖manifest、base-set、activation/startup、wheel/resource、topology、absence与rollback场景。
- [ ] 11.3 运行 `ruff check` 覆盖新增/修改Python app与packages，并运行architecture import/dependency checker确保无Kernel/Host/repository/plugin-internal shortcut。
- [ ] 11.4 运行指南等价non-live probe并验证receipt中的两端点、JSON/SSE、`max_tokens:1`、Session和one-command证据。
- [ ] 11.5 运行新architecture qualification profile、affected-scope test gate和built-wheel isolated qualification；任何live effect尝试都必须立即失败。
- [ ] 11.6 运行 `./scripts/check-mainline.sh`，记录完整命令、退出状态和任何与本change无关的既有失败，禁止用局部成功掩盖mainline失败。
- [ ] 11.7 审计git diff，确认实现只触及本change批准的app/client seam/distribution/qualification/docs，没有修改Kernel业务语义、Standard required Plugin集合或已有EnzymeDesign capability policy。
- [ ] 11.8 核对proposal/design/specs/tasks与source/docs/tests逐项可追踪，确认所有checkbox有真实证据后再进入OpenSpec verify；本任务不执行live部署、比赛提交、commit、push或archive。
