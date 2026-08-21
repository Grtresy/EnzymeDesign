## Context

本 change 服务于一个明确的外部接入约束：比赛平台按 `docs/openai-compatible-agent-integration-guide.md` 探测 `GET /v1/models` 和 `POST /v1/chat/completions`，并期望 Bearer 鉴权、OpenAI 风格 JSON 或 SSE。OpenZyme 的内部事实并不是一次无状态模型调用，而是持久化的 Session、Task/Lane、Approval、conversation、runtime signal 和显式 bounded runtime command。兼容层必须翻译协议形状，但不能伪造或夺取这些语义的 owner。

本设计假定 `separate-openzyme-kernel-from-capability-extensions` 已完整实施和验收：`file_workspace_public@2` 已切换，`openzyme-client` 可验证 exact release/public-contract/binding/affordance identity，EnzymeDesign Distribution 可真实构建并通过启动门禁。若这些前置条件仍未成立，本 change 只能保留为规格，不得用旧 `@1`、Host internal service 或 repository 直连补洞。

当前目标架构把部署组合定义为：

```text
Kernel
+ exact Adapters
+ activated Plugins
+ selected Drivers
+ delivery surfaces
= one versioned Distribution
```

因此 OpenAI-compatible API 是 delivery surface，不是 Agent-facing Plugin、Port Adapter、Plugin Driver 或 Kernel API。它面向外部用户，同时通过私网调用 canonical Host `/v3`；Host、Web UI 和 CLI 仍是同级的其他 delivery surfaces。

主要约束与参与者：

- 比赛平台只需要 L0 文本对话，但会用 `stream:true,max_tokens:1` 做最小探测；`sessionId` 可能存在，也可能在探测时缺失。
- 外部调用方只有一个比赛租户和一枚外部 credential；部署绑定一个固定 OpenZyme `project_id`。
- surface 与 Host 使用独立 credential，Host credential 只属于一个固定项目、具备创建 Session 和显式 drain 所需的最小 user/operator 权限，不能是全局 admin。
- Approval、科学授权、HPC/Provider 资格与其他受控 effect 仍由 OpenZyme 原生 UI/CLI/operator surface 处理；聊天文本不构成 approval command。
- 第一版单实例运行。相同 internal Session 上的并发兼容 turn 必须 fail closed，不能依赖多实例分布式锁。
- 本 change 不执行 live Provider/HPC、真实比赛平台注册或公网部署。

## Goals / Non-Goals

**Goals:**

- 用独立、可删除的 HTTP sidecar 满足比赛指南的 L0 OpenAI-compatible 探测和文本试聊。
- 只使用 exact public Host/client contract，把每个新兼容 turn 映射为一次用户消息 admission 和一个显式 bounded runtime command。
- 保持 OpenZyme 的 Session、runtime、approval、task terminal、effect certainty、release pin 和 public projection 语义不变。
- 为有 `sessionId` 的会话提供稳定、无明文泄漏的 deterministic Session mapping；为无 `sessionId` 的探测提供明确的新会话语义。
- 提供可重试、可诊断、secret-safe、无隐式 fallback 的 JSON/SSE error behavior。
- 生成可独立构建和验证的 `enzymedesign-openai-compatible` Distribution，而不是修改 Standard 或把兼容路由硬编码进 generic Host。

**Non-Goals:**

- 不把 OpenAI Chat Completions 协议提升为 Kernel、Plugin 或内部 canonical contract。
- 不支持 function/tool calling、`tool` role、reasoning 输出、图片/音频/文件输入、附件输出、Responses API 或 `/v1` 以外的 OpenAI API。
- 不允许外部 `model`、`max_tokens`、temperature 或其他采样字段选择内部 Provider、Agent、route、工具、runtime budget 或 approval policy。
- 不将外部完整 `messages` 历史写成 canonical OpenZyme conversation；历史 assistant 文本不能冒充 OpenZyme 已产生的事实。
- 不让 surface 自动批准、自动创建科学授权、重复 drain、自动 enqueue ready task、自动取消 command 或把 runtime completion 当作 Task completion。
- 不承诺多租户、多 public credential、多 project 动态路由、多实例水平扩展或跨 region Session mapping。
- 不在本 change 中修复前置架构 change、保留 `@1` 双栈或添加 legacy fallback。

## Decisions

### 1. 使用独立 sidecar delivery surface，不做 Host route Plugin（D1）

新增 `apps/openzyme-openai-compatible-api`，其 Python distribution 为 `openzyme-openai-compatible-api`，component ID 为 `openzyme.openai-compatible.api`。它运行独立 FastAPI/ASGI 进程，对公网只暴露 `/v1` compatibility routes，对私网只访问 configured Host `/v3` base URL。

依赖方向固定为：

```text
competition gateway
        |
        v
openzyme-openai-compatible-api  (public /v1, external credential)
        |
        | exact HTTP + openzyme-client guards
        v
openzyme-host-api               (private /v3, service credential)
        |
        v
Kernel + selected Adapters/Plugins/Drivers
```

surface 不得 import `openzyme_kernel` implementation、Core repositories、SQLite Adapter、Host `V3HostApiService`、runtime implementation、LLM/provider class、HPC/runner 或 Plugin internals。它只依赖 public contracts/client DTO、HTTP transport、FastAPI 和自身的 wire models。若 prerequisite 完成后的 `openzyme-client` 缺少 Session/message/runtime-command DTO helper，只能在 public client seam 增加薄方法；不得为方便而新增 Host-internal shortcut endpoint。

仓库 source inventory 当前把 Host/CLI 这类应用标记为 `component_kind = "delivery_adapter"`。本 app 沿用该构建/qualification 标签以避免扩大底层 taxonomy change，但它不得提供 Adapter manifest、占用 Adapter slot 或被描述为架构意义上的 Adapter。

拒绝的替代方案：

- 直接在 `openzyme-host-api` 添加 `/v1`：会把外部兼容策略、public credential 和竞赛生命周期耦合进 canonical Host surface。
- 做 Plugin：协议翻译没有新的 Agent tool/state/worker/scientific semantics，Plugin 身份会错误扩大 Session capability bundle。
- 做 Agent-turn Adapter：该 Adapter 的职责是实现 `AgentTurnPort`，而 `/v1/chat/completions` 是外部入站产品面，方向相反。

### 2. 创建独立且完整的 EnzymeDesign 派生 Distribution（D2）

新增：

- `distributions/enzymedesign-openai-compatible/openzyme-composition.toml`；
- `packages/enzymedesign-openai-compatible-distribution`，project name 为 `enzymedesign-openai-compatible`，component ID 为 `enzymedesign.openai-compatible`；
- Python namespace `enzymedesign_openai_compatible_distribution`。

manifest 必须直接、精确地选择 EnzymeDesign 的 Kernel、Adapters、required/optional Plugins 与 Drivers，并在 delivery surfaces 中选择 Host API、client、CLI、Web UI 和 `openzyme.openai-compatible.api`。它不使用 runtime `extends`、ambient entry point 或 Standard/EnzymeDesign hot inheritance。qualification 会比较其非-surface component set 与同版本 EnzymeDesign composition；任何漂移都要求显式更新 manifest、digest 和版本。

Distribution wheel 直接闭合所选组件和新 surface 的安装依赖，不把 `openzyme-standard` 当语义依赖层。若复用 composition factory 代码，只能抽取/使用无业务语义的公开 composition helper；activation authority 仍来自本 Distribution 自己的 exact manifest 和 proof。

保留 CLI/Web UI 是有意设计：兼容 surface 不承载 approval resolution，operator 必须仍能通过原生受控面查看 Session、处理 pending approval、检查失败和在必要时显式推进 continuation。

### 3. 公网 credential、Host credential 与 Session mapping key 三者分离（D3）

部署配置分成三种秘密：

1. 外部 Bearer token：仅用于 `/v1` constant-time authentication；
2. Host service token：仅用于 sidecar 到私网 Host 的请求，对应 `user:openai-compatible-surface`、固定 project scope、`user + operator` 最小角色；
3. Session mapping HMAC key：只用于将外部 `sessionId` 映射为 opaque internal Session ID。

三者不得相同、互相派生、写入 Distribution manifest、日志、公开错误或 projection。public token 永不转发给 Host；Host token 永不出现在公网 response；HMAC key 轮换不得静默把既有 external session 映射到新 Session。

non-secret 配置固定 `tenant_id`、`project_id`、公开 model label、Host base URL、runtime bounds、poll/stream deadline、message/request byte budget、global concurrency 和 per-session concurrency policy。请求不能覆盖这些值。

### 4. L0 wire contract 是 closed compatibility contract（D4）

`GET /v1/models` 在有效 Bearer 下返回一个固定 model label。该 label 只用于兼容展示，不是内部 LLM/provider/capability route。

`POST /v1/chat/completions` 第一版只接受：

- `messages`: 非空数组，role 仅为 `system|user|assistant`，content 仅为有界字符串；最后一个可执行 message 必须是非空 `user`；
- `stream`: 缺省 `false`，且若存在必须是真正 JSON boolean；
- `max_tokens`: 可缺失，或为指南探测可接受的有界正整数 compatibility hint；它不改变 OpenZyme runtime bounds，也不截断 canonical output；
- `model`: 可缺失、空或任意有界字符串，但仅作为被忽略的 compatibility label；
- `sessionId`: 可缺失/为空，非空时必须为有界字符串。

未知字段、`tools`/`functions`/`tool_choice`、`tool` role、content array、multimodal part、reasoning request 或附件扩展返回明确 `400 unsupported_parameter`，不静默丢弃或改写。后续扩大协议必须另建 successor change。

### 5. `sessionId` 使用 deterministic opaque mapping，Host 保持唯一 canonical owner（D5）

非空 `sessionId` 的 internal Session ID 由版本化 canonical input 计算：

```text
HMAC-SHA256(mapping_key,
  "openzyme-compat-session@1\0" + tenant_id + "\0" + project_id + "\0" + sessionId)
```

输出编码为满足 Host identifier contract 的 `ozc_<bounded digest>`。raw `sessionId` 不写入 Session ID、日志或公开诊断。相同 tenant/project/key/sessionId 在重启后映射到同一 Session；不同 tenant/project 或 key 不得碰撞复用。

当 `sessionId` 缺失或为空时，每个新 HTTP request 创建 fresh internal Session。若调用方同时提供受支持的 `Idempotency-Key` header，则 fresh Session 与 turn identity 可由该 key 在本部署范围内稳定重放；没有这两个 identity 时，surface 不宣称跨请求 exactly-once。

Session 创建时：

- objective 由 deployment-owned base objective 加上显式分隔、标记为外部不受信上下文的初始 `system` 内容构成；该内容绝不能成为 provider system policy、authority grant 或 approval；
- 没有 `system` 时只使用 deployment-owned base objective；
- 已存在 mapped Session 时，缺失 `system` 不改变 objective；若请求携带 `system`，其 canonical objective 必须与既有 objective 一致，否则返回 `409 system_context_conflict`；
- 既有 Session 必须仍属于 fixed project、exact compatible Distribution/release 和 surface principal；identity/owner/objective 不匹配时不得收养。

Host control store 是 Session、conversation、task、approval 和 runtime command 的唯一持久真值。surface 不建立第二份业务数据库；其本地状态只允许是有界 in-process lock/cache。Session 的 retention、终止、历史查看与删除继续由 OpenZyme operator policy 管理。

### 6. 外部历史只用于 transport identity；每个新 turn 只 admission 最新 user message（D6）

平台会回传完整 `messages` 历史，但 surface 不得把历史 `assistant` 文本写入 OpenZyme，也不得重复写入较早 user 文本。对一个新 turn，它只取最后一个非空 user content，调用一次 canonical `/v3/sessions/{id}/messages`。初始 system 内容仅按 D5 参与 Session objective。

turn identity 由 schema version、tenant、project、internal Session、canonical `messages` transcript 和可选 external idempotency key 计算；`stream`、`model` 和 `max_tokens` 不改变语义 turn identity。该 identity 派生互不相同的 Host message idempotency key、runtime-command idempotency key 和 public `chatcmpl-*` response ID。同一完整 transcript 的网络 retry 必须观察相同 Host message/command，不创建第二个 effect；包含新历史的下一轮产生新 turn identity。

surface 从 idempotent message response 的 verified conversation projection取得本轮 user `message_id`，把它作为输出关联锚点。这样即使 sidecar 在 command 完成前重启，retry 仍能重新取得同一锚点和同一 command，而不依赖进程内 snapshot。

### 7. 每个 admitted turn 恰好提交一个 bounded runtime command（D7）

处理顺序固定为：

1. 验证 public auth、request schema、大小/并发预算；
2. 通过 private Host/client exact contract inspect 或 create mapped Session，并拒绝 release/binding/owner/objective drift；
3. 若 Session 已有 pending approval，在写 user message 前返回 `openzyme_approval_required`；
4. idempotently post 最新 user message，取得 anchor `message_id`；
5. idempotently `POST /v3/sessions/{id}/runtime/drain` 一次，使用 deployment-fixed `max_signals`、`max_steps_per_agent` 和 `auto_enqueue_ready_tasks=false`；
6. 只 observe/poll 该 command ID 到 terminal 或本次 HTTP deadline；
7. 通过 verified `file_workspace_public@2` conversation projection读取 anchor 后、下一条 user message前的 assistant entries。

surface 不得为等待最终报告而提交第二个 drain、自动 enqueue ready tasks、扩大 bounds、选择 route、解决 approval、重发 response-unknown external effect 或从 workspace/task变化推断 command 成功。`runtime command completed` 只表示这次 bounded scheduler command 终止，不表示 Task、scientific attempt、publication、report 或整个 Session terminal。

同一 internal Session 同时只允许一个不同 turn identity 进入 admission；第二个并发 turn在任何 Host mutation 前返回 `409 session_busy`。相同 turn identity 的 retry可以 observe 已有 command。第一版单实例约束必须由 deployment qualification 强制；多实例需要 durable/distributed admission lease 的后续 change。

### 8. assistant 输出只从 public projection关联，不读取 runtime internals（D8）

response content 是 anchor user message 之后、下一条 user message之前按 canonical order 出现的所有 assistant conversation entries；多条以 `\n\n` 精确连接。surface 不读取 engine document repository、private output、traceback、tool result 或 Host memory object。

若 command terminal 后没有关联 assistant entry：

- pending approval/suspended 映射为 approval-required；
- failed/locked/cancelled 映射为对应 safe OpenAI-style error；
- completed 但无 assistant output 映射为 `502 openzyme_no_assistant_output`，不得制造占位成功文本。

Approval resolution 和 continuation drain 必须由 native operator surface 显式执行。之后调用方可 retry 同一 compatibility turn；surface 只复用原 message/command identity并读取后来出现在同一 anchor segment 的 assistant output，不为该 retry提交新的 drain。

### 9. 非流式与流式共享同一已验证结果模型（D9）

`stream=false` 等待同一 command/anchor result，在成功时返回一个 `chat.completion`、一个 choice、assistant string、`finish_reason="stop"` 和 usage。因为 surface 没有可信 token accounting，三个 usage 值固定为 `0`；不得用字符数伪装 token 数。

`stream=true` 在 auth、schema、Session/message/drain admission 成功后才发送 `200 text/event-stream`。首个 data frame恰好包含一次 assistant role，随后可发送 SSE comment keepalive；terminal assistant content以有界、UTF-8-safe chunks发送，然后发送一个空 delta/`finish_reason="stop"`/zero usage stop frame，最后发送 `data: [DONE]`。这是真实 command 生命周期上的 buffered compatibility streaming，不宣称是 provider token streaming。

若流式响应头已发出后 command 失败、超时、等待 approval 或无输出，surface 按比赛指南发送一个 `finish_reason="stop"` 的 stop frame并附 safe `error`，随后 `[DONE]`。若错误发生在任何 SSE data frame前，则返回普通非 2xx OpenAI-style JSON error。

客户端断开只停止本连接的 observation/serialization，不取消、重发或替换已 admitted Host command。retry 必须依据同一 turn identity observe canonical state。

### 10. 错误映射保持真实 effect certainty 且不泄漏内部信息（D10）

公开错误统一为 OpenAI-style envelope：`error.message/type/param/code`。映射至少覆盖 `401 invalid_api_key`、`400 invalid_request_error`、`409 session_busy|system_context_conflict|openzyme_approval_required`、`409/503 openzyme_runtime_locked`、`502 openzyme_upstream_failed|openzyme_no_assistant_output` 和 `504 openzyme_runtime_timeout`。

timeout、transport loss 或 command still-running 不得写成“未执行”；private structured diagnostic 要保留 exact request/turn/session/command identity、observed status、mutation/fallback事实、effect certainty、retry/reconcile policy、cause chain 与 `diagnostic_id`。public response 只暴露 bounded correlation ID 和安全动作，不暴露 raw external session ID、tokens、prompt全文、Host path、private URL、credential、traceback、Plugin/runner locator 或 backend output。

### 11. 并发、资源和健康状态在 surface 边界显式受限（D11）

surface 对 request bytes、message count、单条/总 content bytes、sessionId/idempotency-key长度、global active turns、每 Session active turn、Host poll interval、command deadline、SSE keepalive 和 output bytes设 closed bounds。超过边界在 Host mutation前返回 `400/413/429`，不得截断用户意图或降级到无状态模型回答。

readiness 只有在 public secret配置有效、private Host可达、exact Host/client contract与 Distribution release匹配、fixed project可访问、surface contract digest匹配 active composition时为 ready。`/v1/models` 不能把一个尚未通过这些条件的 deployment 宣称为可用；failure readiness不触发 Session或runtime mutation。

### 12. Qualification 与文档把“协议通过”和“OpenZyme 完成”分开（D12）

non-live qualification 使用 fake Host/public client transport覆盖：正确/错误 credential、models、非流式、SSE frame顺序、`max_tokens:1`、有/无 `sessionId`、retry、并发、restart observation、pending approval、runtime failed/locked/timeout/no-output、disconnect、unknown fields、secret redaction和 one-command invariant。另有 Distribution composition、wheel metadata/content/import和 source-bound dependency检查。

比赛探测通过只证明 L0 compatibility surface。它不证明 live LLM/HPC、复杂 Agent workflow完成、Task/science/report terminal、公网安全、比赛审核通过或 production cutover。文档和验收输出必须分别报告这些证据层级。

## Risks / Trade-offs

- [Buffered streaming 不是 provider token streaming，完整 content 只能在 bounded command产生 assistant output后出现] → command admission后立即发送 role frame并使用 SSE keepalive满足探测/连接活性；文档明确能力边界，不伪称 token-level streaming。
- [一个 bounded command可能只产生中间回复，不能自动跑完整个多 Agent workflow] → 保留真实 reply并明确 runtime completion不等于业务终态；需要继续推进时由新的用户 turn或原生 operator command显式触发，不循环 drain。
- [复杂请求可能触发 approval，使公共聊天体验中断] → 在 mutation前检查既有 pending approval；新 approval用明确 error映射，原生 UI/CLI完成批准和 continuation drain，聊天文本绝不解释为批准。
- [conversation anchor关联依赖同一 Session内没有并发 user turn] → 单实例 per-session fail-fast lock、Host idempotency、anchor-to-next-user segment规则；多实例和跨-surface并发列为不支持的部署拓扑。
- [HMAC key轮换会改变 deterministic mapping] → mapping key视为持久 deployment identity，备份并独立轮换；变更 key必须使用新 namespace或显式离线迁移，绝不尝试多 key猜测 fallback。
- [外部完整历史与 canonical OpenZyme conversation可能不一致] → 只把最新 user写入 canonical state，历史仅参与 turn identity；不导入外部 assistant事实。若需要跨系统 history reconciliation，另立 capability。
- [固定 service principal具有显式 runtime drain权限] → project scope固定、无 admin、Host仅私网、external/internal secrets分离、请求不能指定 project/session principal/route/bounds。
- [无可信 token usage] → 按比赛协议允许值返回全零，并明确 unknown；不以字符估算冒充 token accounting。
- [派生 Distribution与 EnzymeDesign component selection可能漂移] → qualification比较 exact base component set；任何差异fail closed并要求显式版本/digest更新。
- [前置大 change尚未真实完成时，开发者可能用 legacy seam提前实现] → tasks首项设置 hard prerequisite gate；发现 `@1`、Host internal import或未激活 composition即停止 apply，不建立兼容分支。

## Migration Plan

1. **前置门禁**：确认 `separate-openzyme-kernel-from-capability-extensions` 的 tasks、`file_workspace_public@2` cutover、EnzymeDesign wheel/composition和 public client/Host qualification全部通过；否则本 change不进入实现。
2. **无激活实现**：先创建 surface wire models、pure mapping/idempotency/error/SSE逻辑和 fake Host contract tests；不修改 active Distribution，不启动公网 listener。
3. **组合打包**：创建独立 Distribution wheel和 exact manifest，加入新 delivery surface contract digest，同时保留原生 Host/CLI/UI；运行 manifest、wheel closure、import和negative dependency qualification。
4. **non-live end-to-end**：在隔离临时环境启动 fake/non-live Host与 surface，执行比赛指南等价 probe、故障矩阵和 one-command审计；不调用真实 Provider/HPC。
5. **受控部署**：操作员配置独立 secrets、private Host endpoint、fixed project和单实例拓扑，完成 read-only startup proof后才开放 `/v1`。公网/TLS/reverse-proxy与比赛平台注册需要另行部署授权。
6. **回滚**：停止兼容 sidecar并切回先前 EnzymeDesign Distribution/epoch；不删除 canonical Session。由于无新业务 schema，回滚不需在线数据迁移；已创建 Session按现有 retention policy保留或由明确 operator流程处理。

## Open Questions

L0 范围内没有待用户决策的阻塞问题；本设计采用已确认的推荐方案。reasoning、多模态、附件、function calling、多租户、多实例、真实 token streaming和跨系统 history reconciliation均明确延期，任何一项进入范围都必须创建 successor OpenSpec change。
