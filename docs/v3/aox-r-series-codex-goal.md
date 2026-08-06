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

同一 canonical checkout 的 qualification 任意 mode/output 共用 nonblocking single-flight。
一次只发出一条 command。若工具 yield `cell_id`/`session_id`，只能恢复该 exact handle；handle
未 terminal 时不得重发等价命令、focused recheck 或另建 output。handle 失联时只做有界只读
process/target 检查并停止，不采用另一 report、sidecar 或 partial bytes。output invalid、run
active、source drift、typed terminal failure或non-admissible report都立即停止，不自动 recovery、
relaunch、fallback GAP cascade或启动新 rNN。

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
