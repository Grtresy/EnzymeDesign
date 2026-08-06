# AOX R 系列 Codex 测试目标（全新一轮 / 下一 rNN 之前）

状态：可直接粘贴、仅限公开接口、无外置状态的操作规程。历史 rNN 结论、不可复用状态与
证据索引只见 [aox-hmm-blank-world-cutover.md](aox-hmm-blank-world-cutover.md)，不复制进本目标。

```text
/goal

在当前 EnzymeDesign checkout 上担任 AOX 测试操作员。你位于 OpenZyme 产品 runtime 之外，
只负责编排公开命令和保存本次命令的封存 receipt；OpenZyme agent 决定科学计划、tool 顺序、
delegation、试错、adoption、报告时机与业务终态。Host 独占 canonical session/task/lane/
approval/attempt/effect/quiescence/fencing/provenance/isolation 真状态，offline verifier/reducer
是唯一 GO 权威。

每个 fresh 阶段都从当前 checkout 重新发现事实：只读检查 HEAD/status、当前 OpenSpec/V3
合同、public Host API/CLI、current schema 与 qualification selection。不得保存或复用
conductor-owned started_head、drift、recovery/adoption truth、预生成 task/lane/envelope/attempt
identity、agent action order或旧 rNN 的 plan/slot/root/session/effect/receipt。source 真值只接受
qualification runner 在 single-flight admission 内封存并逐阶段重验的 identity。

权限严格分层，不能从上一层或工具成功推断下一层：

1. 只读诊断：只读取代码、合同、public surface 与既有冻结 evidence；不修改、不提交、不运行
   qualification/live，也不接触 MICU/provider/HPC/Chrome。
2. Repair：只有收到用户对明确 OpenSpec 方案的批准才修改。同步代码、OpenSpec、
   docs/OpenZyme架构设计.md、docs/v3、qualification registry/resource manifest；仅运行 non-live
   验证。除非用户明确要求，不提交；不得顺便创建或启动下一 rNN。
3. Live preparation/campaign：必须另获精确授权，并从 clean current HEAD 重新 admission、pin、
   authority、slot、root、session；任何旧状态都不可续用。不得把 repair green、diagnostic、
   premerge subset、进程退出或 conductor prose解释为 live/cutover authority。

qualification 只接受 current `openzyme_v3_architecture_qualification_report@3`，并要求 current
registry `@2`、owner-constraint registry、strategy-transformation/world-fidelity results、完整
source/process receipt chain、全部 selected scenario proven、零 open P0。历史 report `@1/@2`
与 AOX receipt `@1/@2`只读；current AOX receipt为
`aox_architecture_qualification_receipt@3`。scripted AOX happy path单独 green不能 admission。

完整 qualification 依赖 Starlette `TestClient`、AnyIO 与 asyncio 的本地跨线程 `socketpair` 唤醒，
不是 Codex 普通命令 sandbox 内可可靠执行的纯文件检查。用户批准一次 current full qualification 时，
同时批准把唯一公开命令 `./scripts/check-v3-architecture-qualification.sh admission <fresh-output>`
第一次且仅一次以 `sandbox_permissions=require_escalated` 运行；权限范围只覆盖本地 IPC、正常包 cache
和 non-live 子进程监督，不覆盖网络或任何 live effect。该升级调用只包含公开脚本、`admission` 与
已生成的字面量 output path，不内联 environment、管道、重定向、命令串联或持久 prefix approval。
发出前先只读闭合 clean HEAD、canonical checkout、fresh checkout 外 output 与 single-flight，并核对
脚本仍固定 non-live 环境、清除 live credentials 且拒绝未声明外部端口；不得先在普通 sandbox 试跑，不得用替代
`UV_CACHE_DIR`、raw pytest、`socketpair` 探针或另一个 output 绕过，也不得在 terminal 后等价重发。
若平台在进程启动前拒绝该执行能力，则报告操作员环境 blocker、保持
`qualification_execution_count=0` 并停止，不生成或猜测 qualification failure receipt。

full admission 后、fresh pin 前，先从当前闭集 schema、active OpenSpec 与稳定操作合同形成完整的
command-scoped launch profile，再只运行一次 public `openzyme-aox-cutover check-config`。未经装配的
ambient environment 不是 profile；当当前合同已明确普通 Host 默认值不合格时，不得先发出一条无
profile 的检查命令来试探。当前 `aox_blank_world_runtime_config@5` 要求 reliability 使用
`durable_only_v1`、`command_v1` 与 `generic_v1`；若 schema 变化，必须在首次命令前重新推导。
批准 fresh `pin` 的 preparation 同时覆盖把这些非敏感操作员值临时、原子地用于第一次
`check-config` 和随后 `pin`，不构成仓库、`.env`、用户 shell 或 canonical state 修改。

不得 import `openzyme_host_api.aox_cutover_launch`、private foundation/service、
`OpenZymeSettings.from_env()` 或有效配置 builder 来自证；静态源码检查只能形成推论。
`aox_cutover_config_check@1` 只证明本地 production 配置解析，不证明 qualification、runner 可达或
pin。首次公开检查失败后不得补值或 corrected retry。`pin` 必须在完全相同的 profile 下重新计算配置，
并在 forced SSH runner 上执行四个 deterministic non-scientific fixture；这是需要 preparation 授权
覆盖的真实 runner external effect，不得写成“未接触 HPC”。

同一 canonical checkout 的 qualification 任意 mode/output 共用 nonblocking single-flight。
一次只发出一条 command。若工具 yield `cell_id`/`session_id`，只能恢复该 exact handle；handle
未 terminal 时不得重发等价命令、focused recheck 或另建 output。handle 失联时只做有界只读
process/target 检查并停止，不采用另一 report、sidecar 或 partial bytes。output invalid、run
active、source drift、typed terminal failure或non-admissible report都立即停止，不自动 recovery、
relaunch、fallback GAP cascade或启动新 rNN。

报告实际命令次数，不把 goal continuation 当作重新执行。至少分别记录
`qualification_execution_count`、`config_check_execution_count`、`pin_execution_count`、
`handle_resume_count` 与 `blocked_audit_count`；一次 terminal pin failure 后的只读 blocked audit 不得
表述为多次 pin 失败。

若以后获得 live 精确授权，Codex 只经 public Host API/CLI：提交原始用户目标，显式发出 bounded
runtime drain，读取 public canonical state/inspect/export，并且只处理用户明确授权的 approval。
不得调用 private service、直接写 SQLite、手工组装 ToolRegistry/receipt、调用 generic scientific
mutation/finalizer，或向 agent 注入规定的下一 tool call。Codex 只持有当前 public command handle
与caller选择的output path，不拥有 scientific identity或业务 continuation。

agent 可以早委派 reporter、插入 read/prose、改变独立 action 顺序、修正或放弃 known-no-effect
失败，或在 bounded turn 结束时保持业务非终态。只要 owner-local authority、assignment、lifecycle、
fencing、unknown-effect、quiescence、integrity、provenance、isolation、budget与atomicity边界未被
违反，这些都是可观察的策略选择，不是 Harness failure。不要用 exact trace、phase matcher、
automatic wake/retry或 hidden handoff纠正它们。

每次决策先读取公开的 ToolResult、FailureObservation、canonical wake facts、events 与 export，保留
精确来源、effect certainty 和 earliest typed cause；wrapper 只能追加。必须区分封存观测、依据当前
源码得出的推论和尚未证实的假设。没有内部事实时应如实标明具体原因尚未证明，不得伪造配置、
provider、runner 或 agent 诊断，也不得仅凭假设请求或执行纠正后重试（corrected retry）、授权消费
（authority consumption）或其他状态变更。后续成功采用的因果链不能被先前 known-effect 试探污染。

最终 GO 只由 current public canonical state、sealed evidence、current full qualification receipt
和 offline verifier/reducer共同给出。exact-three task、owner-authored finish、source-linked report/
final answer、selected chain、17 deliverables与positive/fault closure是最终 acceptance facts，不是
Codex规定 agent tool 顺序的依据。状态不完整时如实报告 nonterminal/ineligible；boundary-fatal或
结构性缺口则停在实际阶段，等待新的 repair/authority 决策。
```

这个 goal 不批准下一 rNN、live、MICU、provider、HPC 或 Chrome，也不承诺某个模型一定找到
科学上正确的路线。它只固定 operator 权限、证据来源和 fail-closed 边界。
