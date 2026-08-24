# V3 Agent Runtime

> 框架无关的 `RuntimeTurnCommand`/`RuntimeTurnOutcome`、`AgentRuntimeAdapter`、capability gateway 和
> `ProcessIsolationPort` 由只依赖 Contracts 的 `openzyme-runtime-spi` 定义；Kernel 实现 command builder、
> exact outcome validation 与 once-only consumption。`openzyme-runtime-llm` 实现 exact-provider bounded-turn
> Adapter；Standard Host composition 通过 exact operational selection 接入 bounded runtime command 和
> capability gateway。`openzyme-process-podman` 进入 Standard composition，并实现可独立资格验证的
> ProcessIsolationPort、WorkspaceProcessPort、Podman exact
> mount/image command、bounded stream、process-group cleanup 与本地 Observation/Filesystem/Transfer Ports；旧
> `sandbox_*` image/workspace/run DTO 也由
> 该包唯一实现，并已接管 container lease/retirement。Store、control socket、credential material 和生产
> 历史 deployment 的真实离线 cutover 未在本 change 中执行。

## Resident teammate

agent member 是 session-scoped durable identity，拥有 role、authority lease、workspace generation、
private namespace 和 runtime state。Session bootstrap 原子保留 exact repository pin、workspace generation、
pending exact-generation lease 与 provisioning intent；Distribution 选定的 bounded worker 才调用 workspace
Adapter，并把公开状态推进为 `provisioning`、`ready` 或 `blocked`。HTTP bootstrap 不等待外部 provision，
Adapter 成功也不能自行激活 authority、完成 Task 或发布 revision。LLM process 可以重启，但
member/task/protocol/workspace/provisioning 状态继续由 control plane 持有。

当前 `@1` 数据模型和部分源码仍使用历史名 `AgentCapabilityLease`；目标 `@2` 公共 contract 只使用
`AgentAuthorityLease`，物理表名首轮保留。

## Signal 与 drain

message、delegation、protocol delivery 或显式 operator action 产生 durable `AgentRuntimeSignal`。每个可运行
occurrence 还必须绑定 exact `RuntimeSignalAuthorityLink@1`：root user message 指向该 request-lineage 的
`WorkflowAuthorityBinding@1`，delegation 只能派生 caller 当前 binding 的显式子集，protocol、approval 与
continuation 只传播既有 causation。scheduler claim pending/expired signal 后，在 session runtime lease 下执行
一个 bounded turn；它不扫描 latest/all conversation 或从 prose、task kind、operator drain 参数猜 workflow。

`POST .../messages` 不 drain。`POST .../runtime/drain` 只接纳一个显式 bounded durable command：短事务原子写入
`RuntimeCommandRecord@1` 与 outbox 后返回 HTTP `202`，请求线程不取得 Session lease、不 claim signal、不调用
Provider/Adapter。独立 `RuntimeCommandWorker` 以 CAS claim、lease token、expiry 与 fencing token 获取 command，
再取得 Session lease、claim 最多 `max_signals` 个 occurrence、预注册 exact turn command/context/exposure、调用所选
Agent runtime Adapter、once-only 消费 outcome，并最终结算顶层 command。客户端只通过 exact command status GET
观察进度，不能重复 POST 当作轮询。该路径不扫描 ready Task、不隐式完成 Task，也不在失败时换 Provider/route 或
重放可能已发生的工具调用。`auto_enqueue_ready_tasks` 默认 false，只用于显式 operator/debug/recovery。

## Bounded turn

每个 turn 有 signal、step、tool-result 和时间上限。结束原因（idle、max steps、provider error、lease loss）
写入 runtime outcome，但不自动完成 task。LLM blocking call 在 worker thread 中运行时，coordinator 仍按
TTL 有界 heartbeat；确认 lease 丢失后停止 canonical write。

新 Kernel 的 `RuntimeTurnCommand` 固定 Session/agent/member/turn/signal、runtime lease/fence/process epoch/budget、Distribution/
Extension/DeclaredToolCatalog、Session capability binding 和 ToolAffordanceSnapshot identity，并携带 Kernel
构造的 `RuntimeTurnContext@1`、exact workflow binding/link/epoch 与 `ToolExposureSnapshot@1`；Adapter
不得从 conversation prose 恢复这些权威事实。Adapter 只返回 closed `RuntimeTurnOutcome`；Kernel 对
command/session/member/signal/lease/fence/epoch 和 usage 逐项重验。消费
repository 以 command+outcome digest 原子判定 accepted/duplicate，duplicate ingestion 只返回既有 receipt，
不会再次运行 Adapter；cross-Session、wrong-member、late epoch 或 bundle drift 在 outbox 写入前拒绝。
continuation delivery 与 runtime settlement 是两个独立 typed intent，后者固定
`task_transition_performed=false`。Provider/process outcome 不直接写 Task、Protocol、Approval 或 publication。
`RuntimeTurnCommand` 还携带完整 layered `release_digest`，continuation intent 从该 command 原样固定 release、
Extension bundle、DeclaredToolCatalog、binding revision/digest 与 affordance snapshot。resume validator 对
release/bundle/catalog/owner/process epoch 漂移硬失败；binding/affordance 漂移只保留 conversation resume，
拒绝旧 dispatch 并要求 fresh bounded turn，不自动换 route、重放 tool call 或修改 canonical state。

目标 `@2` 的 once-only 持久化由 `ControlStoreRuntimeOutcomeRepository` 完成。Host 在调用 runtime Adapter
前必须先注册 exact command：repository 将它与 canonical claimed signal occurrence、active
`SessionRuntimeLease` generation/fence、未退休 `AgentMember` process epoch 做同事务 CAS 并写 durable
admission event。outcome 消费点重新读取同一组 current facts；lease 到期、signal attempt 改变、member
retirement/epoch 前进或 command digest 漂移均以 no-effect 拒绝。接受路径原子写 signal settlement、outcome
consumption、ordered assistant message、每个 tool invocation/result、public failure、可选 continuation intent
和独立 runtime settlement outbox；这些记录保留 command/task/lane/correlation/message order identity，并成为
下一 turn transcript 的 canonical source，完全没有 Task mutation；exact
duplicate 只返回 duplicate receipt，不重新运行 Adapter。

runtime Adapter 不能直接持有 Plugin registry 或调用 runtime object；它只能使用 Kernel 注入的
`MountedRuntimeCapabilityGateway`。Gateway 以 command ID 定位 pinned snapshot，并在每次调用前对 current
authority/binding/workspace/health/policy/route 做二次 admission。工具 runtime 未挂载或 snapshot stale 时外部效果为
`no_effect`；runtime 调用已经开始后出现异常或错 receipt identity 时保持 `dispatch_in_doubt`，禁止 Adapter 自动重放。

`RuntimeCoordinationKernelApplicationService` 是 signal/lease 的 canonical application owner：

- Session runtime lease 的 acquire、heartbeat、release 绑定 exact owner、opaque token、monotonic generation
  与 fencing token；活动 lease 不允许被静默接管，过期 lease 只能创建下一 generation/fence；
- signal enqueue 固定目标 Agent member、process epoch、目标 `AgentAuthorityLease` digest 和 workspace
  generation；
- claim 只接受 pending 或 claim 已过期的 occurrence，并同时重验当前 Session lease、目标 authority、
  workspace generation 与 process epoch；
- reclaim 增加 attempt 并签发新 claim token，不重用旧 claim，也不触发 runtime Adapter；
- 所有 mutation、event、outbox 在一个短 UoW 内提交，且明确记录 `task_transition_performed=false`。

因此 Session lease 只回答“谁可以推进这个 Session”，signal claim 只回答“该 owner 正在处理哪个 bounded
occurrence”；二者不能互相替代，也不能由进程存活、模型输出或 transient scheduler state 推导。

当前 SPI DTO 已将 messages、tool requests、bounded usage、approval/continuation wait 和 common
`FailureObservation` 设为 closed surface；未知 `task_status`、Provider response、LangChain message 或 process
handle 会在 contract 构造/qualification 时拒绝。Process request 另外绑定 workspace generation、authority
generation/fence、process epoch、exact argv/environment/image/mount manifest 和 timeout，只返回 opaque
process identity 与 bounded receipt。

上述 SPI/Store DTO 是内部恢复真相，不是公开响应 schema。Kernel public projector 先逐字解析和验 digest，再生成
独立 `*_public@1` allowlist：lease/claim token、raw `RuntimeTurnContext`、输入 messages、raw tool requests 与 tool
arguments 永不越过 Host 边界；公开 outcome 以 count/aggregate digest 与 `source_*_digest` 保留可核对关系。猜测
Hidden/unknown 名称的拒绝 receipt 使用固定 `unexposed.tool` identity，公开 tool transcript 再去掉 internal
`tool_name`，因此 API、CLI、UI 都不会因拒绝路径反向披露名称。

LLM Adapter 每个 provider step 都从 Kernel gateway 重新取得本 turn effective function list。稳定协作动词与
role-essential capability 为 Direct；long-tail capability 先由只读 `capabilities.inspect` 返回非隐藏 Deferred
摘要，再经 exact command-scoped expansion 进入后续 step；Hidden 的名称、描述和参数永不披露，context只含
aggregate count与完整snapshot identity digest。expanded tool 在每次 dispatch
前仍重验 workflow epoch、authority、approval、workspace、qualification、health 与 exact route。Adapter 不
自行增加已安装工具、探测 HPC、延长 lease、换模型/provider/route 或重放可能已发生的调用。

目标 `openzyme-runtime-llm` 从 closed `LlmAdapterConfiguration` 接收 exact provider/model/base URL、
credential slot、timeout/retry/context/output limits 和 credential-free provider options。composition root 先选择
Adapter，再解析 credential slot；可 import 的 LangChain/provider package 或环境变量不能改变选择。
`LangChainProviderBackend` 延迟导入，locator import 无 I/O；preflight 只证明依赖和 identity，不做网络请求。
context 超预算时 Adapter 只做确定性的旧消息裁剪并留下 compaction marker；达到 step/time/usage 上限返回
closed outcome，不写 Task。只允许在同一 provider/backend identity 内按显式 retry budget 重试，禁止 provider
switch。Provider 原始异常只进入 private cause，公共 failure 固定 `mutation_applied=false` 与
`fallback_performed=false`。

LangChain factory/invoker、Provider retry、prompt tokenizer、token ledger、debug recorder 和
connectivity mechanism 由 `openzyme-runtime-llm` 唯一实现；旧 Runtime compatibility package 已删除。
Standard 用 `StandardLlmAdapterFactory` 构造 exact
实现；generic Host 不得从环境、可 import package 或默认值自行构造 Provider。LLM 已启用而 factory 缺失时，
必须在 credential 使用或网络调用前失败。

Runtime SPI 中的 tool request/result 直接使用 Contracts 的 provider-independent
`ToolInvocation` 和 public-safe `ToolResult`。旧 mixed Runtime 在 cutover 前可以内部使用
`ToolDispatchInvocation`/`ToolDispatchResult` 保留 process-local diagnostic，但它们不能进入
manifest、continuation、event、Host response 或 `file_workspace_public@2`。

## Protocol

`task.delegate` 通过 `ProtocolService.delegate()` 原子更新 task assignment、agent relation、inbox 和
wakeup。`protocol.send` 只追加 inbox message/wakeup。recipient 在后续独立 claim 中运行。
Protocol 与 Runtime Coordination 同属 Kernel，但不能各自定义 signal schema，也不能通过嵌套 application
service/UoW 调用通信。Protocol 在自己的原子 UoW 中调用共享的 typed signal payload reducer；recipient 的
`AgentMember.active_authority_lease_id/workspace_generation` 必须与 exact active lease、agent identity 和
process epoch 求交，随后写入完整 `agent_runtime_signal`。任一 binding 缺失或 stale 时，protocol/inbox/signal/
event/outbox 全部回滚。

handoff 中的文件只能是 verified published `RevisionPathRef`。mutable path、private ref、Host path 或
历史不可采用 ref 均拒绝。

## Task terminal

`task.update` 只编辑普通字段和非终态。`task.finish` 校验 assignee、dependency、finish evidence 和
idempotency 后写业务终态。下列事实都不等价于完成：

- runtime idle 或 signal consumed；
- protocol message sent；
- external job succeeded；
- report/scientific receipt exists；
- workspace clean 或 revision published。

Reporting 的目标 finish validator 只在上述显式 `task.finish` admission 内读取 exact generic `EvidenceRef` 与
Reporting namespace：它核对 report contract/version/digest 和预先存在的 accepted validation，返回 closed
`TaskEvidenceValidation`。它不在 Kernel UoW 中 render、fetch、publish 或写状态；缺失/歧义/drift 使整个 Task
mutation unapplied。独立的 draft、render worker 或 report publication runtime result 固定
`task_finished=false`。

Science 采用同一 finish admission，但只接受 owner 为 `openzyme.science`、contract 为
`openzyme.science.closure@1` 且 Session/Task/closure digest 精确匹配的 generic evidence。attempt close request、
closure receipt、deliverable validation、worker completion 或 continuation wakeup 均固定不改变 Task；Science
validator 只读既存 namespace，不运行科学计算、不发布文件、不写 Core/Science state。

## Agent workspace

workspace provision/observation/recovery 与 agent process lifecycle 分离。generation 变化会使旧
credential、process callback 和 clean observation stale。agent 可自由进行 Git 操作；publication
service 只在 agent 明确请求共享时验证 exact commit/tree/LFS closure。

Workspace Runtime 的内部 SPI 分成 Observation、Filesystem、Process 与 Transfer Ports。status/stat/list/read/hash
保持 query-only；mutation/exec/transfer 先建立 durable ControlledOperation。local tools 由 Host 从 current
member/generation 解析唯一 binding，不接受模型提交 workspace ID；HPC tools 使用独立命名空间和 opaque
workspace ID。旧 `workspace.exec` 的 HPC credential provider、Host 注册和 prompt 指引已经删除；即使迁移期
旧 credential router 被注入，`hpc-native`/SSH 类请求也会在签发和 Adapter 调用前失败。迁移期仍存在的
repository credential seam 只服务 exact Session-pinned Git/LFS，不构成 `@2` public contract。
该 seam 的 claims/token/issuance-ledger/ref ACL/closure/GC/client qualification mechanism 已迁入
`openzyme-workspace-git-lfs`；旧 broker 只做 canonical admission 并借用 Store UoW。runtime 只能取得进程作用域
bearer handle，不能看到 signing key、ledger row、repository root 或借 token 验证结果扩张 authority。

当前新 `openzyme-kernel.WorkspaceOperationCoordinator` 已落实这一 admission 次序：query-only 路径仅执行
authority 与 exact provider observation；effectful 路径在 Port 调用前记录 admission，并把 exact receipt
写成 observe/reconcile。typed symlink/CAS rejection 保留 `no_effect`，lost response 保留
`dispatch_in_doubt + mutation_applied=null`；process request 额外绑定 authority generation/fence 与 process
epoch，Adapter result payload 以 digest/size 纳入 receipt 且受调用方输出预算约束。任一路径都不自动 retry、
换 provider/target/route、checkpoint、publish 或 finish Task。Standard Host 通过 exact runtime mount 与
operational selection 接入该 coordinator。

effectful Port 的 reconciliation 复用完整原请求，只允许查询同一 operation/intent 的既有 Adapter receipt；
Kernel 不再执行 admission 或 dispatch，只记录一个 `redispatch_performed=false` 的 RECONCILE observation。
Podman Adapter 在本 epoch 有 terminal receipt 时可结算；没有可验证 receipt 时继续报告原 operation
`dispatch_in_doubt`，不能再次运行 argv/helper，也不能因为目标文件看似存在就推导原 effect 成功。当前
inner process active request 与 terminal receipt 仍是进程内状态；若进程已启动而 Host 在外层 ledger settle 前
硬崩溃，新 Adapter epoch 可能永久保持 `reconcile_required`。外层 ledger 阻止重复执行，但这不是自动恢复到
terminal truth 的 liveness 证明。

workspace provisioning 将这一原则提升为持久化产品生命周期：原 intent/dispatch receipt/failure 在
`dispatch_in_doubt` 后保持 blocked；每次显式恢复都是带attempt/parent/claim fence的独立
`WorkspaceProvisioningReconciliation`。reconciliation READY可以激活原reserved generation但不覆写历史；
terminal diagnosis只能允许显式successor创建新generation/intent，绝不把旧intent重新交给provision worker。

同一 Kernel 包已提供五个 base tool runtimes：`workspace.status`、`workspace.fs.read/list/mutate` 与
`workspace.exec`。Host 的 read-only context resolver 从 exact Session/member/current AgentGitWorkspace/current
authority lease 与显式 composition pin 构造 binding、fence、process epoch 和 local route；调用参数不能提交
`workspace_id`，也不能提交 credential/target/remote locator。context 只从 target Control Store 读取 `@2`
canonical facts；五个 base runtimes 由 Standard exact mount 开放，不存在 repository-backed `@1` bridge、
旧 ToolRegistry 或旧 SSH channel。

Transfer request 不携带 URL、Host path 或 remote locator，只携带 opaque `transfer_ref`、exact transfer
manifest digest、root-relative workspace path、byte budget、deadline 与 authority/generation/fence。当前
Podman 实现把 resolver 选出的第二个 named volume 挂到固定内部路径：download/revision source 只读，upload
destination 可写；helper 对 file/tree 重新计算 content manifest 后才做 create-only atomic copy。revision sync
只把已由 Git/LFS owner 验证的 immutable tree 物化到显式私有子目录，不执行 Git checkout/merge，不发布文件，
也不代表 workspace lifecycle cleanup。transfer staging reservation 和 durable resolver 由 selected
Adapter/Distribution 显式注入，缺失时 fail closed。

`openzyme-process-podman` 中的 sandbox record 是 Adapter-private mechanism state，不是 Agent-facing 顶层
entity，也不能自行贡献工具。它已用 Podman named volume、digest-pinned image、exact argv/root-relative cwd、
non-interactive foreground process、bounded stdin/stdout/stderr 和 process-group termination 实现底层 Port；
结构化 filesystem/transfer helper 固定各自 source digest 并使用 network-none 容器，重复验证 path
confinement、拒绝 symlink/hardlink 和 CAS/content drift，以原子 replace/copy 实现小文件 mutation 与批量传输；
响应不确定时只报告 `dispatch_in_doubt`，不重发或回退 native process。Session 固定 process Adapter identity
与 workspace generation；state row 或 process exit 只构成 mechanism receipt，不可推导 publication、formal
Compute、Science adoption 或 Task terminal。

Agent Git workspace 的 named-volume inspect/create、deterministic volume identity 以及
Session/member/workspace-generation owner labels 也由该 Adapter 唯一实现。旧
`openzyme_core.agent_workspace_volumes` 与 Core 顶层 re-export 已删除；Host composition 直接注入
Adapter backend；provider-neutral volume fact/error/backend Port 已进入 Contracts。Git/LFS Adapter 的
provisioning mechanism 组合 volume allocator 与 exact-base clone，recovery mechanism 组合 volume Port 与
observation provider，并只返回 observation 或 typed blocker。上层 Kernel lifecycle 才能执行 ready/block/
replacement、lease activation 和 failure observation。volume 已存在、创建成功或 labels 匹配都不等价于
workspace ready，更不能产生 authority、checkpoint、publication 或 Task terminal。

Agent capsule image 的 manifest、build、qualification 与 package assets 同样由 Podman Adapter 唯一拥有；
`openzyme_core.agent_capsule_image`、旧 Core `PodmanAgentCapsuleProcessRunner`、Core re-export 和旧 assets 已删除。
exact-volume Podman process command 与 bounded control-socket server 也位于 Adapter；Core runtime/workspace
lifecycle 只消费结构化 runner Port 和 exact `AgentCapsuleImageQualification` receipt，Host 的 runner/executor
来自显式 Podman Adapter import。
qualification 只证明 digest-pinned image 在无网络、无 Host mount、非 root 环境通过固定 probe，不证明
workspace ready、authority 有效、runtime command 已执行或 Task 完成。

Podman Adapter 的 component manifest 绑定 closed configuration schema 与 preflight contract。preflight 只对
显式绝对 binary path 做 regular/executable identity observation，不执行 Podman 或网络探测；container lease
使用 exact run/root labels 和防替换 CID 读取，retirement 失败不能解释为 workspace 已静止。旧
`openzyme_runtime.podman_lifecycle` compatibility path 已删除。

## RuntimeTurnContext 与 prompt

Kernel 是唯一 `RuntimeTurnContext@1` projection builder。它从 canonical repositories 读取并有界呈现：
Session/member/role、current Task 与 task board、lane、exact workspace generation/readiness/revision、
inbox/protocol、approval/continuation、workflow binding/link/epoch、capability/affordance/exposure、safe failure
以及 ordered conversation/runtime transcript。每个 section 有 item/byte budget、truncation marker 和 continuation
identity；`observed`、`unknown`、`stale`、`not_authorized`、`absent` 不能互换。

Adapter 把结构化事实渲染给模型，但 prompt prose 不覆盖其中的 authority、owner、terminal、readiness 或
effect certainty。contradictory user/assistant 文案只是 conversation evidence，不能把 blocked workspace 说成
ready、把 revoked workflow 说成 active，或把 tool/runtime result 说成 Task completed。oversized context 只对
历史 transcript 做确定性压缩并留下可验证 marker；current authority、task、workspace、approval、exposure 和
failure facts不得被摘要掉，也不能创建第二套文件或 workflow identity。

Runtime outcome 是完整可重放 transcript，而不只是 consumption receipt。provider success、tool loop、provider
failure 和 bounded exit 都以同一 closed outcome 进入 once-only settlement；exact duplicate 幂等返回已有
receipt，不同 outcome 复用 identity、stale fence/epoch 或 message/failure collision 在任何部分写入前拒绝。

## Retirement

agent retirement 需要停止新 claim、等待或 fencing 当前 process/workspace authority、完成 namespace/
credential cleanup proof，再写 retirement receipt。retirement 不删除 immutable published revision，也不
改变已完成 handoff/task/scientific evidence。
