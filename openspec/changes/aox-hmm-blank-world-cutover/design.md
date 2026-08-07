## Context

当前 AOX/HMM 路径同时存在三类断点：产品内没有可执行、可版本化的参考位点评分实现；research provider 的成功、失败和降级尚未形成 cutover quorum；现有 S15 live eval 仍是单 executor、fixture 兼容且不能封存完整报告链的证明。只读参考 notebook 和 runner 给出了坐标规则，但其历史运行被分页中断，且 Python 二进制浮点把数学上的 `33.6` 计算为 `33.599999999999994`，导致边界样本被错误拒绝。因此本变更以参考公式而非历史候选行数为标准答案，并以 correctional breaking change 建立新的科学合同。

系统边界保持不变：SQLite 仍限单进程，runner 只面向可信 Host，Deep Agents 只提供 teammate 工作面，canonical session/task/lane/approval/artifact/event/report 仍由 OpenZyme control plane 持久化。真实外部依赖包括 NCBI E-utilities、PubMed、EBI HMMER、UniProt、MICU LLM 和 Host-supervised HPC；任何必需依赖失败都必须留下结构化证据而不是生成替代结果。

本设计涉及科学 SDK、research adapter、execution engine、Host API/eval、Web UI、workflow pack、campaign tooling 和稳定文档。reference 目录只用于开发期只读复核和最小 golden 的来源审计，绝不进入 live roots。

### 2026-07-23 selected-chain implementation addendum

r48-r51 继续作为冻结的永久 NO-GO 历史证据，旧
`aox_blank_world_attempt_bundle@2` collector/verifier 只负责离线验证这些历史
bundle，不得自动升级。后继 production contract 是
`aox_blank_world_attempt_bundle@3`：Host 保存 formal attempt 内的完整 controlled
operation universe，agent 对每个 occurrence 显式写入 `adopted`、`superseded`、
`failed` 或 `abandoned` disposition，并选择唯一 adopted scientific chain。已知且
闭合的中间失败不再自动毒化 attempt；unknown external effect、未退役 process/writer、
未闭合 authority、资源越界或不完整 disposition 仍 fail closed。

fresh attempt 由 durable authorization envelope 授权，AOX live campaign 使用
Host-finalized、one-use 的 exact-three authority plan，分别绑定两个 independent
positive 与一个 fault attempt。same formal attempt 内允许跨 sandbox run
adoption/materialization；跨 formal attempt、campaign、positive/probe/fault scope
复用继续禁止。attempt closure 消费完整 selection、materialization、资源账本与
quiescence，但不推导 task 业务终态。

本 addendum 只完成 control-plane、bundle/verifier、driver admission、产品投影和
非 live qualification。它明确停在下一次编号 attempt（r52）的 authorization、root
creation、provider/HPC/browser action 之前；任何新 live evidence 必须在后续独立
授权下产生。

### 2026-07-23 r52 live diagnostic correction addendum

operator 随后精确批准并消费 authority plan
`sha256:c2755edc4a8f08a161618a7291ff8dad40c340c390c527c24c8f956366492bbb`，
r52 在 clean commit `5ccb0d3ba6055cd3d50b0e42437c350ee442a1f0` 上启动。
campaign 只到达 positive 1，未发生 Chrome handoff，也没有封存任何 eligible attempt
bundle。parent supervisor 以 `attempt_supervision_fatal` 收口，campaign decision
`sha256:7284ce153ed150688887ff1315f52ac236e1a5ef18cf7c519085380013befe8b`
保持永久 NO-GO。

r52 暴露两个彼此独立、均可局部修复的合同缺口。第一，master 第一次 provider
response 请求了超过三项 tool call；旧 driver 只把前三项转换为 invocation，却把包含
全部 calls 的 assistant response 留在 transcript。前三个 `task.create` 均成功后，
下一次 provider call 因第四个 call 没有匹配 `ToolMessage` 返回 non-retryable 400。
纠正后 master/teammate 仍只按顺序 dispatch 前三项，但 public trace 保留全部请求；
每个 overflow call 形成持久
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe` failure observation、
`tool.rejected`/`tool.completed` event 与匹配 ToolMessage，绝不 dispatch、改写用户意图
或放宽并发上限。

第二，positive 1 的 independent probe 实际完成 NCBI、UniProt、MAFFT、hmmbuild、
CD-HIT 与 HMMalign 六项真实 controlled operation，所有 operation/approval/run 均已
terminal；旧 collector 却只从 `provider_request_id` 或 legacy `backend_run_id` 读取
规范化 identity，而当前 durable HPC result 的 canonical 字段是 `run_id`，因此 probe
attestation 以 `controlled_operation_backend_receipt_missing` fail closed。纠正后
collector 根据 `selected_backend` 做 closed mapping：
`hpc -> run_id`、`provider_http -> provider_request_id`，再统一投影为 evidence
`backend_run_id`；completed operation 缺失 canonical field、携带 legacy/other-backend
field、出现多候选或 backend 未知均拒绝，不猜测 identity。

该 correction 不追认 probe success，不恢复 formal turn，也不改变 r52 的 unknown
external outcome、未声明 SQLite/artifact closure 或无 bundle 事实。r52 authority、
roots、tasks、operations、artifacts 与 effects 永久不可复用；MICU 只保守记录到
`74,356,412 / 500,000,000`，remaining `425,643,588`，零 overage/breach。任何后继
campaign 必须使用 correction 后的新 clean commit、重新 full admission、fresh pin、
fresh exact-three authority plan 与 fresh roots，并再次获得对该新 plan 的精确消费授权。

### 2026-07-24 r52 tool-call batch settlement correction addendum

post-r52 review 发现 6.46 的普通连续回合已闭合，但 harness 当时先 dispatch 前三项，
再处理 overflow rejection。若其中一项先触发 runtime suspension、pending approval、
successful terminal action 或 boundary-fatal dispatch，harness 会在 rejection loop 前
返回；public LLM trace 仍保留全部 provider calls，但后续未 dispatch 的调用缺少
durable disposition。该问题不推翻 r52 原始四项 `task.create` 的直接修复，却违反
“harness 忠实呈现每个请求的真实处理结果”以及 6.46 对每个 overflow call 的无条件
结算要求。

纠正后的共享 harness 把单个 provider response 作为有序 tool-call batch。driver 仍
只把前三项标为 dispatch-eligible，并把后续项标为
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`；harness 在任何 eligible
dispatch 前先持久化这些确定不会 dispatch 的 overflow observations，但保持公开
`tool.rejected`/`tool.completed` 与 ToolResult 的原始 call 顺序。若一个 eligible call
触发 approval、terminal action 或 boundary-fatal failure，所有排在它之后且尚未
dispatch 的 eligible calls 必须结算为
`tool_call_batch_interrupted/no_effect/verify_then_retry`，明确指出 causal call 与
boundary；它们不发送 `tool.invoked`，也不在恢复后自动执行。发生 boundary-fatal
exception 的已 dispatch call 保留原 FailureObservation 的真实
`effect_certainty/retry_eligibility`，并取得同 call id 的失败 ToolResult；
`dispatch_in_doubt` 绝不降格为 `no_effect`。

预持久化 overflow 不得顺带提前解析或验证 eligible call 的 task/lane 引用。前三项仍
逐项在真正 dispatch 前、基于前序 call 已提交的最新 durable state 解析，因此同一
response 中合法的 `task.create -> lane.bind_task` 依赖继续成立。never-dispatched
overflow/interrupted call 的 ToolResult 与 observation facts 保留 provider 返回的引用，
但 observation 的关系字段只绑定当前真实 step context；不能为了丰富 rejection metadata
而要求其未来 task/lane 已经存在，或把未执行目标伪装成 durable authority。

这仍不让 harness 选择 agent 的下一策略：`same_phase_safe` overflow 只说明该
occurrence 未产生 effect，interrupted call 则要求 agent 在新 turn 检查最新 durable
state 后决定是否重新发起。即使当前 turn 因 approval/terminal/failure 不再调用
provider，全部 call 也必须具有唯一、持久、顺序可审计的 disposition；只有可能继续
同一 conversation 时，才进一步要求每个 call id 的 matching ToolMessage 闭合
provider transcript。

### 2026-07-24 r53 formal barrier observer correction addendum

operator 在 clean commit `83475a01fb6be91ca8ba5dc39c4c0b09774504e7`
上批准并消费 authority plan
`sha256:a0bccbb4b71b2fb60a0a7131eae692d7400831ee7b516ba8143089f0d71aaabf`。
r53 只启动 positive 1
`positive-1c69b5acac4bffc18f20abeace792f14`。独立 probe 的 NCBI、UniProt、
MAFFT、hmmbuild、CD-HIT 与 HMMalign 六项真实 operation 全部完成，probe mutation
scope 以 receipt digest
`sha256:e436d57b8d4b71611202dd0feac3e90c6ea69391d77424ef80e1ac3868be4e20`
密封。随后 formal session 已提交 entry message 并完成纯协调 turn，但尚未产生 formal
controlled operation、approval 或 Chrome handoff，就在第一次 runtime barrier 以
`mutation_driver_writer_identity_invalid` fail closed。

根因是 selected-chain formal 路径需要由 Host 在 agent writer 退休后，把 pre-attempt
session scope 原子密封并 rollover 为 scientific attempt scope，因此它不能像 probe
那样跨整个 session drive 长期持有 outer writer；旧 driver 却继续要求 barrier 观察到
一个活动的 `aox-attempt-driver:*` root writer，又没有在 snapshot 边界短暂登记它。
r53 数据库因此保留一个 open pre-attempt scope；所有已登记 writer 和 session lease
已退休/释放，且没有 formal external controlled effect，但该状态不具备 quiescence、
SQLite closure、artifact completeness 或 attempt-bundle 资格。

parent fatal evidence
`sha256:5bd1ce75253cda54e6cd25092731b5f1c7bc5aae1b839e16e4055ea01c3de947`
证明 child process group 退休并永久阻断该 authority 的后续槽位；campaign decision
`sha256:d506914841245e9853ef28f7023a942891c6fc2f99244cbe496c899776e3e469`
保持 `attempt_child_runner_failed` NO-GO。MICU 仅能保守记录到
`75,434,226 / 500,000,000`，remaining `424,565,774`，零 breach/overage。
positive 2 与 fault 未启动；r53 authority、roots、LLM/probe effects 与诊断状态均不得
复用或采用。

纠正后的 formal driver 只在每次 barrier projection 的有界同步窗口登记一个 exact root
`aox-attempt-driver:<outer-attempt-id>:formal` writer；projection 完成或失败后立即退休，
不跨 runtime drain、admission/closure finalizer、provider/HPC dispatch 或 approval
等待。barrier 只排除这个 exact observer，其他 root/child writer 继续阻止 ready。
这样既保留真实 writer 可见性，也不会阻塞 pre-attempt → attempt scope rollover。
任何后继 campaign 仍需新的 correction commit、clean full admission、fresh pin、
fresh exact-three authority plan、fresh roots 和对新 plan 的单独精确批准。

### 2026-07-24 post-r53 barrier call-surface correction addendum

对 `6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` 的非 live 审计证明 6.48
只闭合了 formal session 的完整语义观察入口，没有闭合 runtime command 已终态后用于
等待 attached mutation writer 退休的窄检查。后一个分支仍直接调用
`AoxRuntimeObservationService.has_inflight_mutation_writers()`；它同样会投影 generic
runtime barrier，却没有在 open pre-attempt scope 上登记 exact AOX observer，因此可在
真实 SQLite 上再次得到 `mutation_driver_writer_identity_invalid`。既有终态协调测试把
该方法替换为测试桩，未执行真实 observer identity 合同，所以主线通过不能证明该分支
已经闭合。

纠正后的 live driver 以一个共享的 bounded observer context 作为所有 formal runtime
barrier projection 的唯一入口。完整 session observation 与 terminal-command writer
settlement 都必须显式携带同一 `purpose + attempt_authority`，在 snapshot 前登记 exact
root `aox-attempt-driver:<outer-attempt-id>:formal` writer，只在投影期间排除它，并在
返回、等待、下一次 compact approval read、下一次 drain 或异常传播前退休。probe 继续
由既有 attempt-scoped outer writer 提供 observer identity，不能额外嵌套 formal
observer。真实 SQLite 回归必须覆盖 terminal command 无其他 writer 时可完成、存在其他
root/child writer 时仍阻塞、observer 每次均退休且 pre-attempt scope 可随后密封。

该审计没有启动新的 numbered attempt，也不追认 r53。任何绑定
`6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` 的未消费后继 authority plan 都不能跨本次
correction commit 使用；后续 live 仍需 fresh full admission、pin、exact-three plan、
roots 和对新 plan 的单独精确批准。

### 2026-07-24 r54 scientific selection 与 runtime receipt 诊断 addendum

r54 继续作为冻结的永久 **NO-GO** 历史证据。它已经产生 canonical scientific I/O
以及六项 terminal formal controlled-operation 成功事实，但这些事实只证明各 operation
自身发生并完成；它们不等于 scientific attempt 已闭合，更不等于 report 已发布或
campaign 已成功。r54 的 selected-chain selection 停留在 draft，完整 occurrence
disposition/adoption、selection seal、attempt close、eligible report 与三-attempt
campaign reducer 均未形成，因此任何底层 operation success 都不得被追认为 positive
attempt 或 GO。

直接触发失败的是 agent-facing selection 合同不完整：旧
`aox_blank_world_selected_chain@1` digest 只覆盖 role 名称/cardinality，没有覆盖 Host
实际校验的 `role -> (sdk_module, function_name)` 映射；inspection 也没有给出 exact
operation signature、compatible roles 与完整 readiness gaps。executor 先按旧两步工具
顺序提交 effect adoption，又猜错 workflow role，随后为补查真实约束耗尽 bounded turn
steps。这个结果本应只终止 exact signal/turn，并把 task 留给 master 显式 replan。

旧 runtime consistency projection 随后把只含 CAS pointer/version 的
`ScientificSelectionHead` 错当成带 lifecycle state 的 selection，访问不存在的
`state`。scheduler 已经 durable 处理一个 signal，异常却在 post-scheduler projection
阶段冒泡，runtime command worker 又把整次命令统一改写成
`processed_signal_count=0`。因此旧 receipt 同时丢失真实 scheduler 进度并诱导盲目重放；
这不是 operation 未执行，也不是 task 业务失败。

修复只面向新合同和新 attempt：`aox_blank_world_selected_chain@1` 的 preimage、digest、
r54 数据库/bundle/decision/ledger/root 全部保持 immutable/read-only；新 admission 只
接受 digest 覆盖完整 scope/role/operation-signature 映射的
`aox_blank_world_selected_chain@2`。新 config pin 使用
`aox_blank_world_runtime_config@3` 把该 exact contract identity 封入
`config_digest`，bundle `@3` verifier 拒绝历史 config/contract crossgrade。统一
readiness evaluator、原子 `scientific.operation.adopt`、resolved selection head、
两层 runtime receipt 与结构化 step-budget recovery 不迁移或继续 r54。

完成这些 non-live correction 仍不构成 live authority。任何后继 numbered campaign
必须从 fresh clean commit 开始，完成 full non-live architecture qualification，重新
生成并审查 pin 与 exact-three authority plan，使用 fresh roots，并在消费该 exact plan
前取得用户的单独精确批准。

### 2026-07-24 r55 max-step scheduler settlement 诊断 addendum

r55 在 clean commit `88d0d2f0cfe681cd9eb423dbf8d6c01179bbce0b` 上消费了
exact-three authority plan
`sha256:997d7f5c43a0b8bbecc10df5ed66d155cd494bf1adaf0aeb2496ab166bd6adce`，
但只启动 positive 1
`positive-6304b259d55318e1d877ab69c43b2670`。独立 probe 的 NCBI、UniProt、
MAFFT、hmmbuild、CD-HIT、HMMalign exact six 全部完成；formal researcher 完成真实
PubMed evidence。formal executor 尚未创建 controlled operation 或 Chrome handoff，
其 `sig_60109e5f37d4` 在第 16 step 以
`agent_turn_budget_exhausted` terminal failed。canonical observation 已正确记录
`agent_can_replan/no_effect/terminal`，execution task 保持 `in_progress` 且业务 failure
fields 为空，source-bound master wakeup `sig_1caa82176c1e` 已唯一排队为 pending。

旧 core receipt 仍从 `outcome.ok=false` 直接推导 scheduler failed，因此
`runtime_command_974d42e9be42` 虽然保存
`processed_signal_count=1`、`projection_status=complete`、`replay_safe=false`，却以
`runtime_scheduler_batch_failed` 终止。cutover driver 把该 command failure 当作
attempt-fatal，child exit `70`，positive 2/fault 未启动。这个事实不允许继续 r55：
其一次性 plan 已消费，parent fatal 只证明 descendants retired，并显式不声明
ledger-after、SQLite closure、artifact completeness、business terminal state 或
external outcome。

forward-only correction 不把 exact signal 改成 completed，也不重放或加 budget。Core
在 exact session runtime authority 内形成 immutable typed settlement，只对以下完整闭包
使用 budget-replan handoff disposition：

1. outcome 是 teammate `max_steps_exceeded`，canonical signal 为 exact failed occurrence；
2. 同 attempt version 存在结构化 budget observation，scope 只限 signal transition；
3. business task 仍非终态；
4. exactly one source-bound、pending master wakeup 与 task/lane/correlation identity
   一致。

全部成立时 scheduler layer 可为 `completed`，含义只是 bounded batch 已把 recovery
attention 交给一个新的 canonical turn。缺失/重复/取消 wakeup、observation/task/identity
drift、普通 runtime failure或 master 自身 max-step 仍为 `failed`。task business status
与 scheduler settlement 正交：后续或同一正常 completed signal 中的显式 business failure
不会反向改写 occurrence receipt。

任一 master/teammate max-step typed settlement 同时设置 batch barrier。当前 claim wave
完成后 scheduler 停止新 claim，本轮新建的 master successor 即使在产品默认
`max_signals=3` 下也只能由下一条 command/tick 推进。Host core receipt 只消费 typed
disposition，删除 object-identity 分类、mutable repository rescan 与 task-status 反向映射。
AOX 固定 `max_signals=1` 仍是 campaign identity 与逐 signal durable observation 约束，但
不再承担通用 runtime correctness。driver 仍必须先做 post-drain durable
operation/task/sandbox observation，确认没有 terminal failure 后，才可由后续 command
claim 该 master wakeup。

r55 decision
`sha256:cf95804d4d33937abada9902254fce3c9603398e9007843c1213e9633b26be07`、
fatal `sha256:e4513f9183f1e5b5e47db6902fd03ee03efb80f02bbc8bd2e67a324ce06eff0b`
及全部 roots/effects/partial evidence 保持永久 NO-GO、immutable、non-reusable。该
correction 必须在新 commit 上完成 full qualification、fresh pin 与 fresh exact-three
authority；没有对新 plan 的单独精确批准，不得消费或启动后继 live campaign。

### 2026-07-24 r56 scope rollover 与运行类别拆分 addendum

r56 在 clean commit `92712310df96925cabe6b88a949a33b00470cf7d` 上消费 exact-three
authority plan
`sha256:a3d6ed88cca88962281eed38e29f14155701ee7be0ddb2810cc67f47b5882627`，
campaign 为 `aox_campaign_9e5f5da425f7e209d34b01c5`，只启动 positive 1
`positive-77f043cfc659aca80405494ef950588d`。它已经跨过 r55 的 max-step
settlement blocker：独立 probe 的 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign
exact six 全部完成；Chrome Web UI 对 formal approval
`appr_d86d2b0b5082` / operation `op_32dd1b4ae57d` 完成 same-operation
approval；formal exact-14 NCBI、MAFFT、hmmbuild、EBI HMMER、UniProt、HMMalign 六项
controlled operation 全部 terminal-known completed。17 个规范化 AOX deliverable
均已登记；当前数据诚实地产生 zero-byte candidates/CD-HIT FASTA 与无候选分支，而没有
伪造 discovery。

executor 随后完成六项 occurrence 的 selection、disposition/adoption、selection seal 与
scientific-attempt closure。数据库中的 closure digest 为
`sha256:0018a0933139739a2c31919ddc1b8ca7bfa3d660fb4ca8cbd69ae62d819714a3`，
quiescence/sealed receipt digest 为
`sha256:cd8e3d9e02d2d2a6003611a16c21121d4003966dbbaf8bfc5c2701efe293a7eb`。
但是 reporter task 仍为 `todo`，不存在 draft/published report；两个后续 runtime signal
仍为 pending，也没有 terminal browser observation、formal `SessionDriveResult`、eligible
`@3` bundle、positive 2 或 fault。

根因是 Host scientific transition finalizer 仍在 non-transactional
`connection_scope` 中逐 repository commit。r56 attempt scope 在
`2026-07-24T16:26:13.955598+00:00` 已提交为 sealed，post-attempt scope 到
`2026-07-24T16:26:14.099927+00:00` 才提交为 open，因而向并发 reader 暴露约
`144 ms` 的零 open scope 窗口。第 7 次 drain 后的 AOX barrier observer 恰好进入该
窗口；`MutationWriterTurnFactory` 无 scope 可绑定，driver 将这个瞬态 rollover
误报为 `mutation_driver_writer_identity_invalid`。post-attempt scope 随后正常出现且
`host:scientific-transition-finalizer` writer 全部退休，证明失败来自 framework
coordination，而不是 scientific/provider/HPC failure。forward-only correction 必须把
attempt seal、closure 与 post-attempt scope open 放进同一个短本地 write transaction；
barrier 只能看到 transition 前或后，不能靠 blind retry 隐藏非原子状态。

parent supervision 以 child exit `70` 封存 fatal
`sha256:4e0f23b05f8fc5dbe84b35d0781e5c08926eacd4224aa00ab27e5052917463f9`，
证明 descendants retired 与 next-attempt blocked，但明确不声明 ledger-after、
SQLite closure、artifact completeness、quiescence 或 external outcome。campaign decision
为永久 **NO-GO**
`sha256:826bbaf5bbcd07dccff481c363d0d6bb9b4be7aae1f00a33a22ba2e4b346f87f`。
r56 新增 `3,116,328` charged tokens，MICU verified lower bound 为
`86,881,198 / 500,000,000`，remaining `413,118,802`，零 breach/overage。全部
authority、roots、provider/HPC effects、Chrome receipt、scientific bytes、closure 与
partial evidence 永久 immutable、non-reusable。

r56 又一次在首个 eligible result 形成前暴露新 framework defect，触发 operator
预先批准的规范修订。新的目标合同不降低正式验收门槛，而是把 live execution 分成两个
closed run class：

1. **diagnostic live run**：独立 one-use 单 positive authority、独立 diagnostic
   campaign/root/consumption/decision schema，最多运行一个 positive-shaped path；允许在
   精确授权内产生真实 MICU/provider/HPC/approval/browser effect，但所有输出固定
   `acceptance_eligible=false`，不生成 `aox_blank_world_attempt_bundle@3`，也不进入
   campaign GO reducer；
2. **formal acceptance campaign**：保留现有 exact-three
   `positive, positive, fault` authority 与全部 GO 门槛，只接受 fresh formal roots、
   effects、reports、browser proof、`@3` bundles 与 decision。

两类 plan/consumption/receipt/validator 必须 schema-disjoint；内容 digest 相同也不允许
diagnostic artifact/effect/bytes 被 formal adoption。现有 `authorize` / `run-live` 在新
diagnostic command 与 validator 实现前仍只代表 formal acceptance，不能事后重命名为
diagnostic。实现 atomic rollover 和双运行类别、完成 focused/mainline/full admission
并形成新 commit 之前，不得启动 r57 或消费另一份 exact-three formal plan。

### 2026-07-25 post-r56 atomic transition implementation addendum

forward-only atomic correction 复用现有 `CoreRepositories.atomic()` /
`BEGIN IMMEDIATE` ownership，不引入第二套 transaction manager。
`ScientificAttemptService.finalize_closure_request()` 自身拥有一个短 write transaction，
并在事务内重新读取 immutable closure request、attempt、selection、operation universe、
quiescence 与 authority；attempt scope freeze/seal、closure insert 和 deterministic
post-attempt session scope open 因而只有一个 commit point。已有 post child 必须唯一并
匹配 exact id/kind/ref/parent；真正 missing、ambiguous 或 unrelated active scope 继续
fail closed。两个并发 finalizer 串行 replay 同一 closure，不会创建第二个 child。

Host admission/closure endpoint 与 pending scanner 现在共用一条 transition delivery
settlement。Core transition、deterministic public transition event 与 source-bound
`MANUAL_RESUME` signal 在同一个外围 transaction 内提交，进程内 notifier 只在 commit
后触发。pending scanner 不再因为 attempt/closure 已存在就跳过；它按 record/event/source
identity 补齐旧崩溃留下的 delivery 缺口，但不重开 terminal signal。这样关闭了
“closure 已提交、event/signal 尚未提交”造成 agent 永久失联的相邻 crash seam。

非 live 回归使用真实 file-backed SQLite/WAL 和确定性 barrier：writer 在同一未提交事务中
完成 closure insert 后暂停，并发 reader 仍只看到旧 open attempt scope；commit 后 reader
只看到唯一 open post scope。另有两个 concurrent finalizer、post-scope fault
rollback/replay、missing/ambiguous barrier fail-closed 与 Host delivery fault/recovery
覆盖。该 correction 不修改或采用 r56 的 authority、closure、event、signal、artifact 或
bytes，也不授权 r57；diagnostic/formal run-class 实现仍由 6.55 单独闭合。

### 2026-07-25 post-r56 schema-disjoint run-class implementation addendum

6.55 以 `AoxLiveRunClass` / `AoxLiveRunPolicy` 明确区分
`formal_acceptance` 与 `diagnostic`，并把 root、ledger、process supervision、live runner
和 scientific-control settlement 收敛到同一个单-attempt execution core。run class
不是一个可选 CLI flag：正式入口仍是 `authorize` / `run-live`，只接受现有 exact-three
`positive, positive, fault` plan；诊断入口独立命名为 `authorize-diagnostic` /
`run-diagnostic-live`，只接受
`aox_diagnostic_attempt_authority_plan@1` 的一个 positive-shaped slot。

两类 plan、publisher、validator、deterministic consumption sibling 与 receipt schema
完全不同。formal consumption 升级为
`aox_live_attempt_authority_consumption@2`，显式绑定
`run_class=formal_acceptance`、plan schema/digest 与 sibling filename；diagnostic 使用
`aox_diagnostic_attempt_authority_consumption@1` 和
`<plan>.diagnostic-consumed.json`。launcher 先用 committed declarations 与当前
qualification 验证 plan/target并 no-replace 消费，随后才构造 live launch、supervisor
或 root。复制 plan、错误 sibling、重复消费、跨类 schema、移除 diagnostic run-class、
切换 slot identity 或伪造相同 digest 均在 root/effect 前 fail closed。

diagnostic root basename 必须精确等于 plan 的 `aox-diagnostic-*` namespace，并先封存
`aox_diagnostic_root_marker@1`；attempt proof 使用
`aox_diagnostic_root_proof@1`。formal collector 拒绝自身或任一 ancestor 带 diagnostic
marker 的 root，故不能把 diagnostic root 的子目录伪装为 fresh formal campaign。
diagnostic runner 对返回 evidence 中所有嵌套
`acceptance_eligible|cutover_eligible` 强制为 false，同时另行记录
`product_path_completed` 这一诊断事实。诊断 collector 只封存 append-only
`aox_blank_world_diagnostic_decision@1` 的 blocker/count/digest closure，不调用
selected-chain `aox_blank_world_attempt_bundle@3` builder，也不调用 campaign reducer；
formal verifier 对 diagnostic decision 明确失败。

focused regressions 覆盖 closed schema、private canonical one-use file、wrong sibling、
cross publisher/consumer/receipt、equal-digest、stripped-mode、root/ancestor、append-only、
formal verifier/reducer rejection、nested eligibility projection和真实 file-backed SQLite
diagnostic execution。architecture qualification 新增
`evidence-projection.aox-run-class-disjoint-closure`，零真实 external effect。该实现与
non-live green 不消费任何 live authority，不执行 diagnostic，不启动 r57；真实 diagnostic
与后继 formal exact-three campaign 仍分别受 authority plan 和 operator approval gate。

### 2026-07-25 r57 diagnostic binding / settlement addendum

r57 在 clean commit `059b69f2c49f136a42554caa06bc029610d77a7e` 上消费独立
diagnostic plan
`sha256:f084d934feceb31322d1d1c6789018c897315cbf27b4afb825c0398f541590b8`，
diagnostic id 为 `aox_diagnostic_8679ff6b73191fbf3ee6d799`，唯一 attempt 为
`diagnostic-positive-859bdeaccc13bde99bceb56a1e632179`。run-class 边界按设计工作：
所有诊断输出固定 non-acceptance，没有生成 formal `@3` bundle、positive slot 或 reducer
输入。独立 probe 的 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign exact six
全部 terminal completed；formal 的 NCBI、MAFFT、hmmbuild、EBI HMMER、UniProt、
HMMalign、CD-HIT exact seven 也全部 terminal-known completed，证明当前 provider/HPC
主能力并非本轮 blocker。

executor 在外部 effect 全部闭合后，把 representative-only
`AOX_candidates_cdhit85.fasta` 作为
`build_similarity_graph()` 第一输入，却同时传入描述 full candidate set 的
`AOX_candidates_cdhit85.clusters.csv`。pinned calculation 正确以
`scientific_prerequisite_missing:candidate_membership_set_mismatch` fail closed；
13 个规范化 deliverable 已形成，但 nodes/edges/graph manifest 与 execution summary
没有生成。这里不修改 calculation 或阈值：forward correction 只把第一输入的 artifact
identity 明确为 full pre-CD-HIT `AOX_candidates.fasta`，并明确 representative FASTA
永远不是 graph input。

同一 diagnostic 又证明“exact task set / close last”只写在 prompt 中不构成可靠 runtime
constraint。master 在已有 canonical research/execution/report task 外创建了一个 suffixed
report task，在 execution 仍 `in_progress`、canonical report 仍 `todo`、没有
draft/report 时请求 `scientific.attempt.close`，随后 16-step turn 以
`agent_turn_budget_exhausted` 结束；runtime command
`runtime_command_3f25ee1a1338` 因而 failed。corrected Host composition 现在只给该
authority-bound formal session 注入
`aox_cutover_formal_tool_precondition@1`：Router 在真实 handler 前拒绝缺失/额外/错误 kind
的 task create，并在 exact task identity、每项唯一 matching `task.finish`、positive 的
ready-report/published-draft 或 fault 的负向 report state 未闭合时拒绝 attempt close。
拒绝是结构化 `precondition_rejected=true`、`no_effect`、
`same_phase_safe` validation；它不选择 operation、task outcome 或替代 plan，probe 与普通
V3 session 不受影响。

该 binding 更新把 AOX SOP pin 改为
`sha256:54173f4b32f19e547fad83bfbb70cef008cc54c1cdea4d899c30c634d3e2f4ea`，
workflow ref 改为
`workflow:aox-hmm-live@2.0.0#sha256:9000c479adc1127474ca340920bcf2dcc7337808bf8341c98a1f152d66b34f87`；
任何旧 workflow ref 都不能用于后继 authority 或 attempt。

r57 parent fatal
`sha256:500f7e6b183906e7d849eeaed00af3e67a2c3512d4cebdd34e7a31a560acabae`
证明 child exit `70` 与 descendants retired，但不声明 ledger-after、SQLite/artifact
completeness 或 quiescence。diagnostic decision
`sha256:6cf0216335fdad7d08e7a11ac72c7f7f868e0c523819979514f1aa4521c16614`
永久 **NO-GO**；MICU verified lower bound 为
`94,243,539 / 500,000,000`，remaining `405,756,461`，零 breach/overage。全部 r57
authority、root、effect、bytes、partial deliverables 与 pending signals 永久
immutable、non-reusable。因为本轮已形成真实 probe/formal operation results，且直接
blocker 是 workflow data binding 而非“首个有效结果前的新 framework defect”，它不再次
触发或放宽 diagnostic/formal 规范；8.3a 仍未完成 fully settled diagnostic receipt。

### 2026-07-25 post-r57 closure-protocol correction addendum

对 `73bd045baf309a885caeaffaecde72cfb9baaa22` 的 non-live 审计确认
`aox_cutover_formal_tool_precondition@1` 已把 exact task set 与 close readiness 从
prompt 提升为 session-scoped runtime constraint，但仍有三个相邻合同需要闭合。

第一，readiness guard 只能决定 `scientific.attempt.close` 是否可以 dispatch，不能证明
它是 requesting turn 的最后 mutation。科学 closure 的既有语义要求 Host 在 requester
writer 退休后才 finalization；因此 successful close 本身必须是 harness terminal action。
同一 provider batch 中排在其后的 call 必须按既有 batch settlement 得到
`tool_call_batch_interrupted/no_effect/verify_then_retry`，不能 dispatch，也不能把 close
结果再次喂给模型继续 mutation。该 turn barrier 是通用 scientific-attempt 生命周期事实，
不只属于 AOX；它不完成 task、不选择 scientific outcome，也不把 closure request 冒充
final closure。

第二，r57 的最后一步还证明 `task.finish.evidence_refs` 的 canonical
`<kind>:<id>` wire format 不能只藏在 handler validation error 中。tool schema 与
LLM-readable error details 必须同时暴露 exact format、closed known kinds 与示例；合法值
仍由 repository 在当前 session 内解析。runtime 不按 id prefix 猜 kind、不自动添加前缀、
不把 closure request 当 final `scientific_closure`，也不替 agent 选择应采用的 evidence。

第三，AOX formal contract 的“每个 assigned teammate 显式 business exit”必须与
precondition 和 collector 一致。generic V3 仍可保留 master 的恢复性
`task.finish` authority，但 AOX formal close/readiness 与最终 receipt 只接受每项 canonical
task 恰好一个、status 匹配且 `finished_by == assigned_ref` 的 finish document；master
代替 researcher/executor/reporter 写终态不能满足 cutover eligibility。

实现必须补真实 repository-backed regression：三项 canonical task、owner finish receipt
与 positive report/draft 全部闭合后，master 的 close request 成功并立即终止 turn；同批
后续 mutation 被持久结算为 no-effect，Host finalizer 只能在 requester 退休后推进。另需
覆盖 malformed evidence ref 的结构化提示、master-proxy finish 拒绝、ordinary session
不受 AOX policy 影响。该 correction 只运行 non-live tests/evals，不创建 preflight/root、
不消费 diagnostic/formal authority，也不授权 successor live attempt。

## Goals / Non-Goals

**Goals:**

- 固化 `aox_motif_rule_score@1`，用精确整数十分制消除边界误判，并提供独立 golden 与严格前置校验。
- 把 PubMed 必需证据、Semantic Scholar/Tavily enrichment、NCBI/EBI/UniProt 身份链表达为可持久化、可投影、可故障验证的合同。
- 用一条真实 product path 产生 normalized artifacts、published report 和可离线重算的 sealed evidence bundle。
- 用两个独立 clean-root 正向 attempt 加一个 fail-closed attempt 形成机器判定的 local GO/NO-GO。
- 修复会把不适用 workflow pack 强制传播给 teammate 的小型 harness 摩擦，同时保持 agent 对具体研究与执行策略的选择自由。

**Non-Goals:**

- 不把 motif heuristic 描述为实验活性模型，不引入新的 ML 模型或校准结论。
- 不把 LangGraph/Deep Agents 变成顶层产品真状态，不引入多进程 SQLite 或不可信 runner。
- 不把 notebook、历史 CSV/FASTA/HMM、fixture adapter 或 seeded task 当作 live 证据。
- 不在本 Goal 内实施需要重塑顶层 harness、workflow schema 或调度模型的大架构调整；每个此类问题只在独立文档中记录背景、方案、迁移和验收。
- 不承诺外部共享环境 cutover；GO 只覆盖当前 commit/config 下的 local trusted-Host 边界。

## Decisions

### 1. Scoring contract lives in the sandbox SDK and uses exact tenths

在 `openzyme_pipeline` 增加无第三方依赖的 AOX motif 模块。模块负责 FASTA alignment 解析、唯一 reference 解析、ungapped-reference 到 alignment column 映射、逐行评分、规范化 CSV 字段和 contract metadata。内部权重为 `50/20/-1`，threshold 为 `336`；`33.6` 只在展示/序列化边界用固定一位小数生成。contract digest 由规范化 rule payload 计算，implementation digest 由实现源码字节计算，workflow manifest 同时 pin 两者及 SDK source digest。

aligned FASTA 统一绑定 `hmmer_afa_alignment_canonicalization@1`。parser 只按 LF 分段，只有真正 LF 终止的 segment 可去掉一个紧邻 CR；header marker 必须在 raw column 0，只忽略真正空物理行。每个非空 raw sequence line 在 strip、大小写或 Unicode 规范化前必须完整匹配 ASCII `^[A-Za-z.-]+$`，随后只执行 ASCII uppercase 与 `.`→`-`。raw input digest 始终绑定原始 bytes；合法大小写和 HMMER `.`/`-` gap 差异只在 canonical aligned-sequence/alignment digest 收敛。whitespace、lone/重复/其他 CR、`ß`/`ſ` 等 Unicode expansion 或任何非 ASCII 输入均 fail closed。最终 motif implementation/contract digest 分别固定为 `sha256:795535d9d6c232a79bc9791f8c2780c2f4aa64b234b15a83deb8c76d3406871c` 与 `sha256:71aff3b872aaef3254550db53c7554011923d19293f9c5837ddc4bb8ca0bec10`。最终源码对真实 HMMER 3.4 AFA 的只读预检覆盖 `12,273,402` bytes、`2,562` records、width `4,700`，得到 `517` total pass（含 AAB）和 `516` non-reference pass；raw/canonical digest 分别为 `sha256:d72e36bc5c0431d8f3806eb4d0d0cadb51e7d3825c873610d8e4c0098eccf7a6` 与 `sha256:2df12971eae2d83c390f22e689e04e493539cf6be2d79599f33823f0f52df836`。这些普通 `/tmp` bytes 只作 source-level preflight，不是 sealed/cutover evidence。

Host/evidence verifier 显式依赖同一 SDK 代码来重算，不复制第二份规则。`openzyme-pipeline` 因此成为 Host 的声明依赖；这与 Host 已负责 seal/copy SDK source 的现有边界一致。备选方案是把规则放入 `openzyme-domain`，但该包承载 control-plane 领域真相而非科学计算；另一个备选是只在 eval 内嵌脚本，但无法提供可复用、可离线复核的合同，均不采用。

最小 golden 只保留授权参考中可解释的少量 alignment 行、期望 residue vector、score/pass 和输入 digest。历史 2689-row 输出只用于开发期对照，不入测试夹具和 live 输入。golden 必须覆盖精确边界、一个高于阈值、一个因关键位点低于阈值以及 missing/duplicate/truncated/unequal-width/drift 失败。

### 2. Canonical schema is breaking and legacy fixture output is quarantined

规范字段为 `motif_rule_score_tenths`、`motif_rule_score`、`passes_motif_rule`、逐位点观察、`scoring_contract_id`、`scoring_contract_digest`、`scoring_implementation_digest`、reference identity 和 alignment/input digests。`activity_score`、`seq_score`、`pass_rule` 不做隐式 alias；validator 看到 legacy-only schema 时直接拒绝 cutover eligibility。

现有 deterministic/fixture eval 可继续为非 cutover 回归服务，但必须改用显式 `fixture_non_cutover` 标记与不会通过科学 validator 的 fixture schema，且不得再声称 live success。候选数、cluster 和 edge 不再由固定常数产生。备选的兼容读取会让旧 artifact 被误当作新合同，违反 fail-closed，因此不采用。

### 3. Provider calls return a structured outcome, not an exception-only side channel

research adapter 增加共享的 bounded HTTP invocation seam，统一 timeout、attempt、`Retry-After`、transient/quota/auth/schema/empty 分类、request identity、safe response digest 和 retrieval time。服务方法返回或抛出带稳定 error taxonomy 的类型化结果；tool boundary 必须先建立 canonical invocation/operation，再执行网络调用，并在成功、degraded 或失败时终结同一个 operation。sandbox provider request draft 建立后的 `PipelineSdkFailure` 必须通过同一 artifact boundary 登记 request/observation/error exact-three diagnostic artifacts，再保留原 canonical code/stage/retryable 语义并附 safe refs；不 retry、不 replay、不解释成 provider success。凭据和私有 header 永不进入 payload、artifact 或 public projection。

PubMed query 使用 NCBI identity，至少一个 schema-valid PMID 才满足 required quorum；DOI 只从 PubMed article identifiers 提取。Semantic Scholar/Tavily 是独立 enrichment attempt，其 429 或 retry exhaustion 在 PubMed 完整时写 `degraded`，不抹除主证据，也不触发备用 synthetic search。NCBI reference、EBI HMMER 和 UniProt 则按科学阶段被标记为 required，其失败/空结果语义由阶段合同决定。

researcher 可以在同一 bounded policy 内按科学需要迭代 PubMed query；harness 不固定 query、不要求 one-call，也不按 first/latest/result-count 猜测主证据。研究 task 完成前，agent 必须在 `task.finish.evidence_refs` 中显式采用 exactly one succeeded、source-bearing PubMed `artifact:<id>`。collector、positive blocker 与 offline verifier 只以这个结构化 adoption 为 primary receipt authority，并要求 researcher task、invocation、artifact、全部数字 PMID source 的 task/lane 完全闭合；可选 `lane_id` 允许整条链一致为 `None`。零个或多个 PubMed artifact adoption 均 fail closed，report 还必须引用所选 artifact 内的 PMID/source。未采用 invocation 继续留在 canonical SQLite；把 accepted/exploratory/failed/empty/superseded 全量历史与 completeness root 封入 bundle 需要 `@2` schema，已独立提案而不在本 Goal 实施。

备选方案是保留各 provider 私有 retry 并在 eval 汇总异常，但那会丢失 attempt/operation 关联且容易出现调用发生在 invocation 持久化之前的证据洞；不采用。

### 4. Sequence identity is append-only across providers

正式 NCBI protein fetch 一次请求 exact 14 个 identity：原 notebook 的 13 个 HMM model accession（包括以固定规则解析的 `9AVH_A`）加坐标 reference `AAB57849.1`。provider aggregate 必须封存全部 requested/resolved identity、原始 FASTA record、sequence SHA-256 和 aggregate FASTA digest，不允许缺失、重复、多余或身份替换。两个 versioned calculation 从同一份封存 bytes 分别生成 exact-13 `AOX_ref21.fasta`（`aox_hmm_reference_set_selection@1`）和单条 `AOX_coordinate_reference_AAB57849.1.fasta`（`aox_reference_selection@1`）；后者不得进入 MAFFT/hmmbuild 的 model-training input。

EBI HMMER `refprot` hit 的 candidate 主身份是 UniProt accession。`provider_config:ebi_hmmer:v3` 保留 v2 的 result `page_size=1000` 默认/上限与无缺口 result materialization，同时把 EBI/Celery `RETRY` 识别为同一 accepted job 的非终态：只轮询原 job id，不重新 submit，poll deadline 固定 `3300s < sandbox 3600s`，超时映射为 retryable `provider_timeout`；`FAILURE`/未知状态继续 terminal fail closed。poll 显式携带 `page=1&page_size=<configured>`，terminal payload 只消费 status 与 `result.stats.nreported`，不作 result page。result 必须从同宽显式 page 1 开始物化，每页重复同一非负 `page_count`；非截断 raw hit count 精确等于 terminal `nreported`，SUCCESS empty 只接受 `nreported=0/page_count=0/hits=[]`。该修复不改 `max_hits`、sorting 或 parsed-hit schema。`hmmer_score_filtered_accessions@1` 只从严格 provider parsed schema 中保留 score `>200` 的 accession，其 canonical artifact 和 exact non-empty accession set 是唯一允许的 UniProt 请求输入；HMMER 不提供下游 sequence/length 真值。

UniProt 使用 `uniprot_primary_sequence_identity@2`：active sequence records 与 exact-requested typed `Inactive/DELETED|MERGED` records 必须对 complete requested set 形成互斥分区。active provider `entryType` 只允许精确的 `UniProtKB reviewed (Swiss-Prot)` 或 `UniProtKB unreviewed (TrEMBL)`，分别派生 `reviewed=true|false`；raw result 若另有 `reviewed` 字段，必须是与派生值相等的 boolean，active 带 `inactiveReason` 或组合漂移均 fail closed。inactive 必须在 producing query 中精确匹配 requested primary accession；`DELETED` 封存非空 canonical deleted reason，`MERGED` 封存非空、去重 replacement-target annotations。两类均封存 UniParc id、release/retrieval、response/record digests，固定 `identity_replaced=false`，无 sequence/entry audit，不跟随/抓取 replacement、不从 replacement/UniParc/HMMER 取 sequence。`DEMERGED`、unknown/malformed inactive、active 缺 sequence、missing/duplicate/extra identity、完全无返回或 partition 不闭合均 fail closed。`aox_sequence_length_join@2` 先确定性排除两类 inactive，再对 active UniProt sequence 应用 `650..700`，产生 `target.fasta` 与 `hits_len650_700_200.csv`；active/inactive-reason/output/length-rejected counts 和 sorted identity mappings 均可离线重算。cross-reference mapping 只追加 annotation edge；若两源序列不同，保留双方 bytes/digest 并要求显式 selection，禁止 overwrite。

到达 UniProt 的 cutover-eligible positive 还必须通过 `scientific_checks.sequence_join.uniprot_raw_response_artifact_id` 绑定同一个 formal `uniprot_fetch` operation 的 output、artifact provenance/digest 与该 operation 的 UniProt provider receipt。provider `request_digest` 必须等于同一 operation 从 sealed canonical params 重算的 `params_digest`；completed operation outputs 与 completed provider `artifact_ids` 必须是相同的 exact-three distinct artifact set，roles 固定为 `uniprot_raw_response`、`uniprot_metadata`、`uniprot_sequences`，每个只出现一次且 role/formal scope/origin operation/content digest 全部相等，不得混入 request/observation/error diagnostics。offline verifier 只接受 closed `provider_raw_http_response_set@1` envelope/response rows，严格重放 canonical base64、size、ordinal、status、body digest 和 ordered response chain。每页的 sanitized header map 必须带同一个非空 `x-uniprot-release` 并精确等于 metadata；`x-uniprot-release-date` 只允许所有页缺失且 metadata null，或所有页存在、同值并等于 metadata。raw results 使用 engine sanitizer 与 metadata 建立 requested/primary 双射；active sequence 经 `strip().upper()` 后验证字符、raw/metadata length 与 digest，并继续由既有 join 绑定 FASTA；inactive 明确禁止 `sequence`/`entryAudit`，并从 raw 重建 exact DELETED reason 或 MERGED non-follow annotation。无关 future raw result fields 可以存在，但完整 sanitized non-sequence object 必须等于 `provider_metadata`，完整 sanitized result 则重算 `record_digest`；因此本轮 diagnostic 的 exact-five inactive shape 不是未来字段 allowlist。

最终实现上的 read-only full-set diagnostic 用时 `679.154s`，得到 `37,772 = 32,176 active + 5,596 inactive`、`5,594 DELETED + 2 MERGED`、`378` 个 ordered response digest、release `2026_02` 与 `2,561` 个 length-filtered hit；score-filter input、provider metadata、hits CSV、join manifest digest 分别为 `sha256:c4f1e134c4e38fcda5424706544cccf0bf65b4187be2ce6d2f30114aeaf69b8f`、`sha256:9deaebcf2c674cc8a7af52c1c00384fe2798b6d364f7d09e50c002abdcc89109`、`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`、`sha256:d768beb08f1bf5e5905e63249db352e1bcfe3e9eaea2d5be871e3adba39d8bca`。这些普通 `/tmp` 输出没有 seal，不是 cutover artifact/attempt/GO evidence，也不证明 formal raw-artifact closure。

UniProt 使用 `provider_config:uniprot:v3`，但 route policy id 保持 `bio.uniprot_fetch.provider:v1`。exact accession artifact 通过一次 SDK call、一次 approval 和一个 controlled operation 提交，总 cap `100000`；Host 默认拆成每 query 最多 `100` accession。SDK `batch_size` 仍是 response page 的 `size`（上限 `100`），每个 query 独立跟随 `Link: rel=next` 且各有 `100` 页 cap；next link 只允许 `https://rest.uniprot.org[:443]/uniprotkb/search` 且无 userinfo/fragment，malformed/off-origin 只记录 digest并`provider_schema_drift`。approval 前 SDK resource estimate 显式给出 accession count、默认 query cap 与 estimated query count；纠正后当前完整集合为 37,772 accession，仍预测 378 个内部 query，而不是 378 个 operation/approval。该 estimate 只是透明预测，不授予 limit；Host injected provider config 可收紧实际 cap 并在 I/O 前最终校验。transcript 绑定 query/page index、accession range/count/digest 和 response digest；每个 page 只接受 producing query exact slice，operation 内跨 query identity swap 以 `provider_identity_mismatch` 拒绝。HTTP failure 只增补 query batch index/count/start/count/digest 与 completed/requested page progress，不回显 raw URL、accession list 或 cursor。duplicate/order checks 使用预建 set/frequency-map 线性扫描并只稳定排序重复 key。Host-authoritative canonical estimate/limit snapshot 及其 approval/config binding 属于独立 proposal，本 Goal 不实现。当前输入已是 primary UniProt accession；切换 async ID Mapping 会引入 durable job handle、submit/poll/result resume、幂等、approval 与 evidence/verifier schema 迁移而没有当前 mapping 需求，因此不在本 Goal 实施。

`aox_scoring_input_assembly@1` 把单条 AAB 坐标 reference 放在首位，再按 target id 字典序追加 post-UniProt target，生成 `AOX_scoring_input.fasta`。非空 target 时 HMMalign 必须同时消费 `AOX_ref.hmm` 和该 scoring input；空 target 时不伪造一次 HMMalign，而是用 `aox_reference_only_scoring_alignment@1` 将已验证的 AAB-only scoring input 物化为 scoring alignment。

每一科学跳转都以 `input_artifact_ids + input_digests + operation_id + provider/toolchain identity + output_artifact_ids + output_digests` 连接。空 hit/空 candidate 可输出 schema-valid 空 artifact 和 empty-result explanation，但 known-positive probe 必须另行证明 provider/HPC 健康，probe 数据不得合入正式结果。

### 5. AOX execution remains agent-authored within a strict manifest

workflow pack pin required outcomes、contract/digests、13 个 HMM model accession + AAB 坐标 accession 的 exact-14 NCBI 身份和拆分合同、数据库 `refprot`、artifact schema 和 fail-closed 条件，但不硬编码唯一命令序列。executor 仍可选择合理的分批、重试和中间检查策略；Host 只提供真实约束与受控 `openzyme_pipeline` SDK。MAFFT、hmmbuild/hmmalign、CD-HIT 和 similarity 都由真实 input/output 产生并 seal tool version/params。similarity 采用版本化的全局 alignment identity 计算；不得用常数边或复制 HMM/motif score。

similarity 保留原 Gotoh 科学规则和 tie break，但将 `(score_half_units, exact_matches, aligned_residue_pairs)` 以 `R=max(m,n)+1` 精确编码为 `score_half_units * R^2 + exact_matches * R + aligned_residue_pairs`；由于两个 count 均小于 `R`，整数比较与原 tuple lexicographic order 完全等价。最终 similarity implementation/calculation digest 分别固定为 `sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5` 与 `sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`。backend 固定为 `biopython_trace_guarded_numpy_gotoh@1`、Biopython `1.87`、NumPy `2.4.4` 和 `Gotoh global alignment algorithm`；packed integer 只有在严格 `<2^53` bound 后才能通过 binary64，score 必须 finite、integral 且未越界。首个 optimal trace 出现相邻 horizontal/vertical gap-state switch 时，调用 versioned exact NumPy `int64` `numpy_three_state_gap_switch_correction@1`；这是 calculation contract 内的纠正而不是 fallback。import/version/algorithm/numeric/trace/correction failure 全部 fail closed，不允许纯 Python、其它依赖版本或 alternate backend。reference recurrence 的 state order 只作为 score/count tuple 的 tie provenance；当前 calculation 不发布或承诺 coordinates/path，未来 path output 必须使用新 calculation id 与显式 trace contract。reference validation 使用 NumPy `2.4.6`，cutover exact pin 为 `2.4.4`；两个环境不等同，且运行时不得在版本间 fallback。

candidate FASTA 同样只按 LF、raw-column-zero header、raw ASCII-before-uppercase 解析，并拒绝 gap/stop/whitespace/Unicode expansion。pair 按 lexical order；少于 `128` 必串行，至少 `128` 时 parallel-eligible。worker count 取 pair count、`16`、affinity（仅其不可用时使用 `cpu_count`）及所有可用 cgroup v2/v1 quota/period 向上取整值的最小值；present 但 unreadable/incomplete/malformed 的 cgroup constraint fail closed。worker=`1` 在执行前选择串行；只有更大 worker count 才使用 `chunksize=64` 的 ordered process map。parallel branch 开始后的 pool/worker/serialization/result failure 稳定映射为 `scientific_prerequisite_missing:similarity_parallel_execution_failed`，不得静默串行 fallback。offline verifier 每次 invocation 只重算一次 graph，并将同一 invocation-local result 对照 node、edge 与 manifest；无跨 invocation/attempt cache authority。历史 pure-v3 receipt `sha256:caf483bedbe2865cdf3be0677dbcb3a27d6ccfb9fd1a57bbc0093a35ef90bcf5` 与临时 2-CPU Podman receipt `sha256:b9749e6c3f23dd553a1e33b55f7cb9a67a1aee6dfbfae8fb4235ce0aa52f563c` 均明确 non-cutover。最终 current-backend comparison receipt `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e` 绑定两次独立 exact-cutover-NumPy-`2.4.4`、2-CPU/2-worker full-set run：raw outputs 逐字节相同，只规范化 pins 与 pin-induced manifest closure 后又逐字节等于 old pure-v3，所有 non-pin fields 相同。它不声称 direct full-set NumPy patch A/B；`non_cutover=true` 只完成 benchmark/reviewer 与 knowledge repin gate，不是 live GO evidence。

manifest 声明完整 capability set，但正式 operation closure 由封存 artifact 重算实际到达分支，不用静态“全工具必须调用”清单惩罚正确早停：

- HMMER upstream empty：省略 UniProt、HMMalign 和 CD-HIT；UniProt 以 `provider_upstream_empty_receipt@1` 记录 `provider_io_performed=false`，不允许 request/response digest。
- length-filter empty：已到达 UniProt 与 sequence join，省略 HMMalign 和 CD-HIT。
- motif-filter empty：已到达 HMMalign 与 motif scoring，省略 CD-HIT。
- nonempty：执行完整正式链。

分支必须由 raw/parsed HMMER、score-filter、sequence join、motif/candidate artifact 重算，不信任 execution summary 或 agent 自报。正式分支省略的 capability 由独立 known-positive probe 覆盖，probe bytes/operation/task/workspace 不得进入正式图或 report claim。将这一逻辑抽象为通用 harness 的调整已单独记录为 `artifact-derived-conditional-capability-closure.md`，本 Goal 不实施通用化。

formal prompt 只呈现实际安装的 `openzyme_pipeline.aox_reference`、`aox_hmmer`、`aox_sequence_join`、`aox_motif`、`aox_similarity` callable 及 canonical serializer，不允许 agent 近似重写。provider artifact 按 transcript manifest 的唯一声明后缀选择；HPC artifact 按 runner-owned canonical path 对应的唯一 `fetch_refs[].declared_output_path` 选择，HMMER search 精确绑定 fetched HMM artifact id/digest。合法零记录 FASTA 必须是 exact zero bytes，并携带 `fasta_zero_records@1`、稳定 empty reason 和版本化 derivation contract；通用空文件或 sentinel 不能通过 artifact boundary。

r12b 证明 rich operation/fetch envelope 会在 nested provenance 中重复描述同一 artifact，若让 agent 自行递归扫描，很容易在外部 operation 已完成后因本地 parser 误判而整段重跑。当前 Goal 的小修把三个只读 canonical direct-field selector 固定为互斥终点：`provider_file_ref` 只消费 direct provider-operation response，`fetched_output_ref` 只消费 direct `ws.fetch_outputs` response，`registered_artifact_ref` 只消费 direct real `artifacts.register` response；missing/duplicate/malformed/nested-only、selector chaining 与 synthetic registration envelope 均以 non-retryable SDK error fail closed。executor 在下游本地解析前把已完成 response 写入 attempt-local `/workspace/work`；operation-bearing run 之前可用短、显式 source-bearing 的 inspection/source-repair run 消除本地错误，但 controlled operations 开始后，checkpoint 只能服务同一个仍成功的 operation-bearing run。一旦任意 operation-bearing sandbox run failed，cutover driver 在下一次外部 approval/dispatch 前停止该 attempt；同一 method 的第二个 operation同样拒绝。control-socket register、provider artifactization 与 HPC fetch 的 source provenance 由 Host 显式绑定当前 Host-sealed run/operation source snapshot，不能用 stale `last_command_summary` 推断，也不能接受 sandbox 自报。该修复不改变 exact-operation-set，不选择最新或成功子集，也不实现跨 run adoption。

### 6. Workflow refs are explicit per delegation

`task.delegate` 增加可选 `workflow_refs` 参数，值只能是当前 turn 已授权的 active workflow refs 的无重复子集；payload 持久化所选 manifest snapshot。省略或传空数组均表示不绑定 workflow，不再从 parent focus 隐式继承全部 refs。若 ref 与目标 role/tool/capability 不兼容，delegation 在 claim 前返回 LLM 可读错误。master prompt/tool result 会列出可选 refs，使 agent 能把 executor pack 只交给 executor，同时让 researcher/reporter 使用各自工具面。

这是局部、可测试的 harness 修复：它消除隐式传播但不改变 scheduler、task ownership 或 workflow manifest 顶层模型。若实施中证明需要 role-scoped multi-pack composition、动态 capability negotiation 或 workflow schema 重构，则每项写入 `docs/v3/architecture-proposals/` 独立文档并在本 Goal 中停止该大改。

cutover collector 不把 task row 当作 workflow binding 的充分证明。它从 durable delegation document 重建 researcher/executor/reporter 三个 role receipt：executor 必须精确绑定 campaign workflow ref 和完整 manifest snapshot，其他两者必须空绑定；bundle 封存不含 raw instructions 的 closed public request projection，offline verifier 独立重算 projection digest、manifest content/core digest，并把 projected agent 与 task assignment 绑定。这样仍不引入新的 product truth，只封存既有 durable record 的安全投影。

### 7. Campaign is a product-path driver plus an offline verifier

新增 campaign CLI/模块而不是把 cutover 判定塞进 pytest fixture。`run-live` 在构造 runner、campaign 或任何 attempt root 前先生成 canonical launch snapshot。launch identity 是 exact-seven 闭集：`git_commit`、`config_digest`、`workflow_ref`、`scoring_contract_digest`、`scoring_implementation_digest`、`image_digest`、`sdk_digest`。这些字段分别从 canonical clean checkout 的完整 commit、digest-pinned workflow registry selection、`aox_motif_rule_score@1` contract/implementation、实际 Podman sandbox preflight 和 Pipeline SDK source tree 计算；operator 提交的 identity 只用于逐字段精确比较，不能成为真值来源。dirty checkout、字段缺失/多余、mutable/malformed identity 或任一 mismatch 都在 root 创建前失败。

r51 证明仅有 immutable image digest 仍可能把一个缺少 frozen scientific dependency 的旧
`dev` image 带入昂贵 formal path。局部 correction 在 identity resolution 内增加
`aox_sandbox_scientific_backend_probe@1`：复制 exact SDK、统一目录 `0755`/文件 `0644`、
重算 source digest，然后在 selected immutable image 中以 no-pull/no-network/read-only/
bounded container 真实执行 `biopython_trace_guarded_numpy_gotoh@1` 的 import、
Biopython `1.87` / NumPy `2.4.4`、Gotoh、binary64 和 numeric examples。它在 pin runner、
attempt root、MICU/provider/runner effect 前 fail closed，且每次 attempt-boundary guard
重跑；不 runtime install、不使用 Host package、不 fallback。该 correction 不扩张
exact-seven/exact-nine，也不实现已有独立 proposal 中的 reproducible base/wheelhouse/
hash closure/SBOM/attestation 大架构。

`pin` 是生成 `run-live` declaration pair 的 canonical supported operator bootstrap。它使用 production `compile_hpc_tool_request` 和受信 Host 的 forced-SSH `MCPHpcServer` 执行 deterministic non-scientific MAFFT、CD-HIT、hmmbuild 与 chained hmmalign payload，只从 runner-issued same-shell runtime identity 构造四个 toolchain image digest。writer 把 exact-seven 与 exact-nine payload 以 mode `0600` canonical JSON 落在 checkout 外同一 existing real transaction directory，并要求两个 payload 与 fixed marker 三个 reserved target 初始不存在；两个 payload fsync/no-replace publish 后才最后发布 exact closed `.aox-cutover-pin-commit.json`，用两个 basename 及 canonical payload digest 作为单一 consumer-visible commit point。`run-live` 在 settings/launch/root 之前拒绝 marker 缺失、symlink、跨目录、malformed/open 字段或 digest drift。marker 发布前 crash 可留下 orphan payload，但它们不可消费，operator 必须使用新 transaction directory。该无签名 marker 只证明 pair 的 transaction integrity，不证明 producer provenance、目录整体 freshness 或消费时 file mode。随后 `run-live` 仍重算 actual launch snapshot，pinned pair 只是 exact comparison declaration，真实 toolchain identity 仍由 live operations 的 runner-issued receipts fail-closed。

`config_digest` 是 safe `aox_blank_world_runtime_config@3` preimage 的 canonical JSON digest，而不是任意配置标签。preimage 绑定 effective post-foundation 设置：trusted `local-dev`、single-process SQLite、background runtime disabled、HPC backend 与 runner-config file digest、runner-owned manifest bytes digest 与 exact AOX `tool_id` 到 adapter/template/runner-contract digest 的闭集 expectation map、provider limits、MICU endpoint/model/policy/token/runtime bounds、research bounds/credential availability/opaque NCBI identity、tracing digest、显式 live opt-ins、driver approval/time/drain/agent/browser bounds、`chrome-once` UI dist digest，以及 controlled-operation owner policy、durable route allowlist、command drain、generic mutation closure、bounded shadow observation、完整 `aox_blank_world_selected_chain@2` schema/contract/workflow/digest identity、scenario、固定累计 500M ceiling 和既有 ledger identity digest。pin 在 forced-SSH attestation 前、run-live 在 campaign/attempt root 前验证每个 AOX provider/HPC route 均为 `durable_async_v1` owner，并要求 `command_v1` 与 `generic_v1`；这些值的任一漂移都会改变 config digest。raw credential、NCBI email、Host/runner/ledger path 不进入 preimage；launch receipt 封存 preimage 与 digest，offline verifier 重算 canonical digest并拒绝 historical contract/config crossgrade。旧 config `@1/@2` 与 selected-chain `@1` 只为 frozen evidence 离线复核保留读取兼容，不再由新 live launch 产生或接纳。runner expectation map 与 selected-chain identity 都只是 config preimage 的内部闭集字段，不扩展 exact-nine prerequisite 顶层 schema。

MICU/OpenAI-compatible endpoint 的 blank-world live context 必须显式声明且 `context_window_tokens <= 200000`；不能用模型名推导第三方 endpoint 未证明的百万级窗口。`world.inspect(sections=["capabilities"], task_id=..., limit=...)` 同时改为 bounded facts index：teammate 绑定当前 task，master 保留既有 session-wide 权限；页面 newest-first，最多 20 个 invocation、每类 8 个 closed opaque refs、serialized facts 64 KiB，不回填文档、output、evidence 或 source body。当前 rich hydration 的读取成本尚未有界，窄列/lazy/cursor 大调整只记录在独立 proposal。

每个 attempt 创建唯一空目录，随后初始化 SQLite、artifact/blob root、sandbox root 和独立 HPC workspace label；preflight 记录目录清单与 digest，并拒绝预载科学文件。`allowed_prerequisites` 是 exact-nine 闭集：`git_commit`、`config_digest`、`workflow_ref`、`image_digest`、`sdk_digest`、`toolchain_image_digests`、`credential_slots`、`ncbi_identity`、`prompt_accessions`。前五项必须与 launch identity 相等；toolchain map 只含 `mafft_7.525.hpc_apptainer_sif:v1`、`hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`、`hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`、`cdhit_4.8.1.hpc_apptainer_sif:v1` 四个 immutable image digest，且 hmmbuild/hmmalign 必须绑定相同 HMMER SIF bytes；credential slots 只含 `llm/ncbi/semantic_scholar/tavily` 四个 boolean 且 LLM/NCBI 必须 ready；NCBI identity 是 opaque digest；prompt accessions 只含 formal exact-14、固定 probe NCBI 与 probe UniProt 集合。未知字段、credential value、private locator 或 scientific bytes 直接拒绝。

r46 暴露的 provider reconciliation seam 属于现有 durable execution/result materialization 内的局部合同缺失，不新增 state 或 owner。provider callback 正常路径已有完整 `result.summary + transcript_manifest + validation + warnings`，而旧 reconcile 仅因 callback 丢失就把它降级成通用 artifact-count 摘要，使 agent 看不到真实已封存的 provider file refs。纠正方案不 replay effect，也不让 adapter 猜测科学结果：reconcile 只读取同一 operation/request 已经由 Host artifact boundary 封存的 request/terminal observation，两份 control document 逐 byte 核 digest 并按 closed schema/identity 校验；其余 artifact 继续以 catalog digest/metadata 形成 manifest。原 provider summary 从 observation 恢复，manifest/validation 从同一 catalog set closed-reconstruct，S12 envelope 仍由 durable route materialize。control document 保持 `8 MiB` 上限；完整 canonical immutable result envelope 与 core 统一为 `256 KiB`，inline summary 连同 envelope 其余字段必须共同落在该界内，bulk identities 留在 digest-bound artifacts。任何缺失、tamper、schema/route/config/output/artifact drift 都是 terminal-known failure。r46 原 82,719-hit transcript 的只读恢复只证明 correction，不能 adoption 或改变其 NO-GO 身份。

r47 证明先前 `1.5 MiB` inline-summary 设计与 core 的 `256 KiB` immutable result-envelope validator 矛盾：真实 EBI HMMER 返回 `68,592` 个 candidate identity，adapter 把完整 `candidate_accessions` 重复写入 summary，使其达到 `862,426` bytes；Host route 能 materialize，但 core closed validation 拒绝后又把 terminal-known invalid observation错误降回 `reconcile_required`，形成不 replay effect、却持续 claim/reconcile 和写事件的热循环。局部纠正保留现有 owner/state：HMMER summary 删除完整 candidate list，候选真值只在 digest-bound `provider_parsed/parsed_hits.csv`，summary 保留 count/schema/digest/transcript refs；Host 在 materialize 前按同一 `256 KiB` 完整 envelope 上限 fail closed；worker 对 terminal-known invalid observation一次性终结为 `recovery_failed`。这不引入 fallback、截断 candidate set、effect replay 或新的顶层真状态。

r49 证明 durable event 的 same-content replay 还必须拥有明确的 SQLite transaction closure。失败的 duplicate INSERT 会让 standalone connection 进入隐式 transaction；旧 idempotent 分支直接返回 existing row，使紧随其后的 event-outbox mutation-writer retirement 再次 `BEGIN IMMEDIATE` 并失败，进而阻断 execution/continuation/sandbox 与 attempt quiescence。局部 correction 在返回 same-content existing event 前调用已有 `_commit()`：standalone connection 完成短事务，owning UoW 因 managed depth 保持 no-op 并继续由 owner 原子提交。它不改变 event identity/cursor、冲突语义、writer tree、execution owner 或外部 effect policy。

r50 使用 correction commit `723336f0aad3f766c130de4c7589060b13cc5a12`、fresh full admission 与 fresh pin/roots。known-positive probe 的真实 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 operation 均完成，但旧 durable HPC materializer 从 runner terminal raw result 重建 immutable result envelope 时漏投影已存在的 `mcp_hpc_toolchain_runtime_identity@1`，collector 因而正确以 `toolchain_image_identity_missing` 拒绝 probe attestation；不能把底层 operation 成功追认为 cutover probe success。formal 路径取得真实 PubMed primary evidence，完成 exact-14 NCBI、MAFFT、hmmbuild，并由 Chrome 对 canonical approval `appr_c0592ffe765c` 批准同一 EBI HMMER operation `op_a68d862c1466` 后继续执行。HMMER submit 产生 accepted job `563241d6-b460-4c74-bc92-70a34ab7c18a`，result endpoint 返回 `{status: RETRY}`；旧 adapter 的 nonterminal set 漏掉 Celery `RETRY`，立即将其错判为 non-retryable `provider_invalid_request`。attempt bundle `sha256:07eec83396eeef00a0331431da8c1bf4e30368b1ba998453de680bab73450f64` 离线验证 `issues=[]`，decision `sha256:da164049f628f15dbf66bb9498f7087cabf49c02b4a39309b799f98587db07ca` 保持永久 NO-GO；MICU 累计 `72,553,945 / 500,000,000`，remaining `427,446,055`，零 breach/overage。r50 的 root、provider job/effect、artifact、approval、browser receipt、bundle、decision 与 pin 永久不可复用。两处局部 correction 都不新增 owner/state 或隐藏 retry：durable route closed-validate terminal raw attestation 后只投影 exact safe eight fields，剥离 private SIF path，present-but-invalid identity 直接 terminal-known failure，missing identity 不推断；HMMER v3 只把 `RETRY` 纳入原 job poll 状态机，把 deadline 从与 provider 默认首次 retry 同边界的 `1800s` 提高到 `3300s`，并保持 `3300 < 3600 < 7200`，到期仍非终态即 fail closed。后继 live 必须使用 repinned `workflow:aox-hmm-live@2.0.0#sha256:b8f3424aa591ab59fb89e911df65e5d44300614933fb8d10105028c296ad17f4` 并重新生成 fresh commit/admission/pin/roots。

source snapshot 是 `kind=code` 的 typed directory artifact，evidence collector 将其规范化为 `openzyme_sealed_source_tree@1`：relative path 必须安全、唯一并排序，每个 entry 绑定 size/content digest/canonical base64，envelope 再绑定 source-tree digest。bundle builder 与 offline verifier 都重算 envelope 内外 digest，并对 base64 解码后的 UTF-8 source 执行 public-safety 检查；symlink、FIFO、empty tree、kind drift、非规范 JSON/base64、private decoded source 或任一 digest drift 均 fail closed。零记录 FASTA 的 catalog validation payload 另封存为 `openzyme_typed_empty_artifact_validation@1`，offline verifier重建 validation digest并与科学 empty reason闭合。

首次 live campaign 证明 sandbox root 不能只在 composition 层声明：workspace status 若独立使用共享默认 root，会把同一 `sandbox_workspace_id` 标成 READY，而 file/exec/Podman 实际解析到 attempt root，最终以缺失 bind source 消耗 agent turn。小型纠正因此锁定为：status、显式/隐式 lookup、file/exec、snapshot 与 Podman bind 共享 Host-injected attempt root；显式 id 仍校验 executor ownership；无 canonical row 时派生 leaf 必须不存在并以 no-replace/exclusive-create 建立六目录，预存目录/文件/symlink不得接管或修改；已有 layout 缺失、非目录或 symlink 直接 `sandbox_volume_corrupt`，且失败先于 snapshot/run/process。此修复沿用现有 canonical state 与错误 taxonomy，不新增顶层真状态，属于本 Goal 可直接实施的小改动。

launch snapshot 还提供 attempt-boundary guard。`AoxCutoverCampaign` 在每次调用 `create_blank_world_roots` 之前重新计算 checkout、workflow/scoring、sandbox image、SDK 和 effective-config identity；任何 drift 以稳定 launch failure 终止 campaign，封存 safe driver-failure/NO-GO decision，不创建该 attempt root，也不触达 model、provider 或 runner。已创建 attempt 内的 runtime/artifact failures 仍走 attempt evidence，不被 guard 伪装成 launch success。

正向 attempt 只通过一个 `/messages` 请求进入，之后使用公开 runtime drain、approval API 和读取接口推进，不直接调用 repository/service 写入真状态。driver 可自动轮询，但不得 seed task/approval/artifact/report。`run-live` 把 complete attempt 放入 fresh local POSIX spawn child；该 child 独占 loopback Host 与 attempt roots，parent 只做 lifecycle/retirement supervision。`chrome-once` 只把 positive 1 的首个 formal approval 暴露给 child loopback Host 所服务的 digest-pinned Web UI；parent supervisor 与 driver 都不调用该 approval 的 resolve route。driver 在触发可能产生 handoff 的 drain 前记录 durable event cursor，然后从该 cursor 重建 resolution/continuation，避免即时 UI resolve 与事后 snapshot 竞争。浏览器 approval timeout 从 handoff 发出时独立计时，同时受 attempt 总 deadline 上界约束，outer supervision deadline 由现有 session/browser bounds 确定性推导。用户从 UI resolve 后，driver 必须观察顺序严格递增的 pre/resolution/continuation event cursor，并保留同一 `approval_id`、`operation_id`/digest、sandbox workspace/run 和 continuation identity，直到同一 operation 到达 terminal state，再进入 bounded UI observation window。

drain worker 的成功 response 与最后一个 `waiting_approval` workspace projection 存在并发可见性 seam。coordinator 在观察到 worker terminal 后必须再完成一次确定从 response 之后开始的 public workspace GET，才可结束本轮；后台 drain exception 保留 command-failure taxonomy，只有 workspace/approval coordination 或 cleanup exception 归为 coordination failure。一旦 coordination 失败，已有及后来出现的 unresolved approval 都在既有 attempt deadline 内通过 public API 明确 reject，不能 approve cleanup 或继续 science；cleanup GET/resolve 瞬时失败只记 safe secondary type，并以同一 idempotency key 重试，原始 blocker 保持权威。由于 approval row 可能先于 drain response 和 `approval.requested` 回填持久化，Web UI 以五秒、single-flight-per-generation、只读的 selected-session workspace reconciliation 补充 SSE refresh；session switch、workspace mutation 与 applied SSE reducer 都 abort/失效旧 token，token identity 保护旧 `finally` 不清除新请求，避免旧 snapshot 覆盖较新状态或挂起旧 GET 饿死新 session，且不新增 UI 真状态。

`aox_browser_approval_receipt@2` 记录 mode/channel/Host process、session/approval/operation/sandbox identity、pre/post workspace semantic preimage 与 public response binding、resolution/continuation 的完整 durable-event record 与 replay binding、authenticated actor、continuation id、post-operation status 和 `driver_resolve_route_absent=true`。positive 1 还必须封存 `aox_browser_observation_receipt@2`：challenge、page/Host/UI-dist identity、Host-held completion window timing、console entry digest 与 `application_error_count=0`、terminal page state、DevTools transcript 以及可完整解码且 digest-bound 的 PNG。approval/terminal handoff 对动态身份是完整的：它发出 sealed logical page、Host process、served UI dist digest、schema id、not-before、exact target 与 expected page state。trusted operator 必须使 final target 在 hold 内不存在；稳定 helper 从闭集 Chrome capture 派生 exact raw 23-field receipt，并只在 not-before 后通过 mode-`0600` sibling temp + file fsync + atomic no-replace install + parent fsync 交付，且不生成 Host acceptance timing；窗口结束后再进入独立、正有限并计入 effective-config digest 的 submission timeout。当前 Host 只证明 bounded hold polls 未观察到提前 target，且 final 是 post-hold mtime、non-symlink、两次 stat/read 稳定的 regular file；它不证明轮询间的连续缺失或 operator atomic/fsync provenance。closed `public_api_receipts` 每项 exact 七字段 `sequence/method/route/status_code/request_digest/response_digest/response_semantic_digest`；query semantics、response semantic preimage 和 canonical list digest 都由 verifier 重算。另以 bundle-level `aox_public_final_workspace_snapshot@1` 与 `aox_public_final_event_replay@1` 封存最后一次只读 public workspace 和 `replay=true,after_cursor=0` 全事件 preimage，fault closure 必须与 task/report/draft/conversation/event/consumer 全集合 exact equality。`auto` mode 不产生 browser receipt，不能满足 Chrome GO criterion。attempt 完成还要求 researcher/executor/reporter participation、task business exits、published report、final master response 和所有规范 artifact。

Chrome resolution 的局部判定只接受带闭合
`decision=approved|rejected` 的 canonical `approval.resolved` command event。
当前 activity backfill 可能复用同一 event type，但其 ApprovalRequest projection
只有 `status`、没有 `decision`；consumer 必须忽略这种 projection echo，不能把它
推断成批准或拒绝。真正的 canonical `decision=rejected` 仍立即 fail closed；若在
既有 bounded approval deadline 内没有 canonical closed decision，则以缺失浏览器
决策证据 fail closed。把 canonical command 与 derived activity projection 在全局
event taxonomy 中分型是单独记录的大架构调整，本 Goal 不实施。

MAFFT、hmmbuild、hmmalign 和 CD-HIT 的 cutover execution identity 只能由 runner 签发。runner-owned manifest 绑定 tool、adapter、command template、contract digest 和 private SIF locator；caller 提交 locator、runtime request/identity 或环境 override 均被拒绝。当前 SSH runner 在执行真实 payload 的同一个 login shell 中先 scrub 所有 inherited `APPTAINER_*` / `SINGULARITY_*` runtime-control 变量并二次确认不存在；任一变量无法移除就在 payload 前 fail closed。随后 runner 直接执行 resolved SIF pathname，并在 payload 前后对同一 pathname 计算 SHA-256。只有两次 digest 相等且 payload 成功才返回现有 closed `mcp_hpc_toolchain_runtime_identity@1`：`attestation_scope=same_ssh_login_shell_pre_exec`、`execution_mode=ssh`、exact tool/adapter/template ids、`runner_contract_digest` 和单一 equal `image_digest`；private pathname 和 pre/post 中间 digest 不进入 Host 投影。Host 各层 closed-reconstruct 该 public identity，collector/verifier 把 observed image digest 与对应 exact-nine prerequisite 比较。当前保证仅限于“受控 runtime 环境中同一 pathname 前后未变且被直接执行”，immutable inode/content-addressed snapshot 的大架构调整已单独记录在 `docs/v3/architecture-proposals/immutable-hpc-sif-execution-snapshot.md`，本 Goal 不实施。Slurm 仍是一般 runner backend，但当前没有 job-internal same-execution SIF attestation；submit/preflight metadata 不得冒充 runtime identity，因此 Slurm operation 不是本 cutover 的有效 toolchain identity。跨层 single-source toolchain registry 属于已记录的大架构提案，本 Goal 不实施。

独立健康证明使用已实现的 `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"`：NCBI `NP_000509.1` / `NP_000549.1`、UniProt `P68871` / `P69905`，以及 MAFFT、hmmbuild、protein CD-HIT identity `1.0`、一次同时消费真实 HMM 与 clustered UniProt FASTA 的 HMMalign，总共 exact six controlled operations。probe 使用单独 task/workspace/sandbox/source snapshot，绑定 raw HTTP response-body digest，不重复正式图必然到达的 EBI HMMER，也不允许任何 probe identity/bytes 进入正式 artifact 或 report claim。合同已实现不代表 live 已通过；仍必须由当前 attempt 封存并离线验证。

offline verifier 使用 canonical JSON（排序 key、稳定 separators、UTF-8）重算 bundle digest，遍历 sealed artifact closure，重算 scoring rows、schema、provenance links 和 report references；不得发网络请求。tamper test 修改 artifact byte和 provenance 字段，必须定位精确 mismatch。

### 8. GO is derived, never asserted by prose

campaign manifest pin exact-seven `git_commit/config_digest/workflow_ref/scoring_contract_digest/scoring_implementation_digest/image_digest/sdk_digest`。attempt 1 和 2 必须使用不同 clean roots 且以上 identity 完全相同；两者均通过 offline verifier并发布 report。attempt 3 只接受 `derived_required_artifact_blob_byte_flip@2`：从 real NCBI exact-14 `proteins.fasta` 经 `aox_hmm_reference_set_selection@1` 得到 derived `AOX_ref21.fasta`，在 pending MAFFT 消费前翻转一个 byte，并要求 exact `artifact_blob_digest_mismatch`。`aox_fault_negative_state_closure@1` 封存 task business exit、report/draft 状态、conversation/final failure、durable events、所有直接 consumer 及 fixed-deliverable path 集；offline verifier 必须证明无 ready/published report/draft、无 successful alternate consumer、无 downstream final deliverable，且 fault MICU 增量全部归因于本 campaign。只有聚合 verifier 同时确认三项才生成 GO decision；否则只能输出带最小 blocker 的 NO-GO。代码与非 live gate 的完成不代表这些真实 attempt 已运行；在三份 live bundle 与 sealed reducer decision 存在前状态保持 NO-GO。

MICU token 使用现有持久 500M ledger；summary、reserve 与 campaign 初始化不自动重解释旧 policy。operator 必须显式调用 canonical migration，且只有 exact legacy fixed 100M→500M；事务不重置历史 usage，500M 幂等，caller-selected lower limit fail closed。真实测试在 focused/non-live gates 后运行，并在每个 attempt 前后记录累计账本快照。

### 9. Evidence projection is summarized, not a storage escape hatch

workspace/events/API/UI 只呈现 provider、status、citation、operation/artifact/report identity、digest prefix、warning/degradation 和 verifier status。Host path、remote path、credential、private header、原始受限全文不进入 public projection。approval UI 必须显示并续接同一 operation id/digest；若恢复创建新 operation，attempt 失败。

公开诊断不仅检查字段前缀，还必须处理异常文本内部的 Host path。control-socket/adapter error、sandbox stdio summary、workspace last-command、runtime signal、failed ToolResult、`harness.failed` 与 eval 在各自 schema-declared diagnostic/locator field 使用共享 high-risk sanitizer：精确 sandbox/control-socket Host root 映射到逻辑路径，随后对当前测试覆盖的常见 Unix/HPC roots、Windows、UNC、file URI、private/special-use URL、storage/runner locator 与 credential corpus fail-closed 脱敏；lane `cwd`、memory `source_range` 等历史 structured locator在 projection再次处理。该 producer不声称识别任意自由文本中的所有 private path，也不无类型改写 user/scientific/report正文；跨全部 surface 的 typed/versioned diagnostic envelope 已单独记录，本 Goal 不实施。进程 stdio 以 binary capture，raw digest/size 证明捕获的原始 bytes，完整 payload 仅写 attempt-local Host-private log；AOX offline verifier 仍独立拒绝 surviving absolute Host path/private locator，不降低任何既有阈值。scanner 只允许四个 exact AOX logical manifest suffix `/provider_parsed/metadata.json`、`/provider_parsed/parsed_hits.csv`、`/provider_parsed/proteins.fasta`、`/provider_parsed/sequences.fasta`，并只在 sealed Python source 中窄识别 `Path("aox_hmm")/p.name` 这类真实 `/` path-join syntax；未知 suffix、traversal、任意 `prefix)/p.name`、`/home/...`、`/tmp/...` 和其他 unknown absolute path 仍拒绝。

### 10. Harness findings follow a two-tier change rule

实施中发现的 harness 问题先判断是否能以单一局部合同、现有状态模型和 focused regression 解决。满足者可直接修复并同步稳定文档；涉及新增顶层真状态、跨包 ownership 重划、scheduler/approval/protocol 语义迁移或 workflow schema 总体重构者视为大架构调整。每个大调整单独成文，至少包含现状证据、agent 受限方式、目标不变量、候选方案、迁移、兼容/回滚、风险和验收；本 Goal 只引用文档，不实现代码。

本轮发现“科学 callable、canonical serializer、agent-facing facts 与 receipt 分散”会迫使 agent 自行猜测计算入口，但统一 registry/projection 涉及跨 SDK、workflow、tool catalog 和 evidence schema ownership，属于大改；详细方案单独记录在 `docs/v3/architecture-proposals/versioned-scientific-calculation-capability-projection.md`，本 Goal 不实现。

本轮还发现跨 `sandbox.exec` 显式采用一个既有 completed operation、同时保留 failed/superseded/abandoned 全历史，需要 durable chain-selection 真状态、operation disposition、approval/public projection 与 bundle/verifier schema 升级，不能用“最新成功”或 content-digest 去重局部修补。详细方案单独记录在 `docs/v3/architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md`，本 Goal 不实现。

r14 暴露了 AOX HMM-capable path 的直接可用性缺陷：真实 EBI HMMER 在约 `1375.8s` 完成，但旧 `sandbox.exec` `900s` 和 formal public/session `1800s` 先后截断调用。局部修正不新增真状态：S09 policy 升为 `v2`、默认仍 `120s` 而最大 `3600s`；任何可能到达 HMMER 的 command 要求 exact `3600s`，显式 source-bearing 的 inspection/repair 可更短；AOX driver 默认和最小均为 `7200s`，launch 与 HMMER approval 对 canonical policy fail-fast。它只修当前 AOX 层级，不自动 replay。通用 durable async continuation、取消/lease fencing、Host writer quiescence 与封存顺序后来由独立 `runtime-hpc-reliability-refactor` 实现，其 proposal 已随该 change 归档。

r15 证明上述 timeout hierarchy 已容纳一次约 24.5 分钟的真实 EBI HMMER，但随后 37,722 个 accession 产生的 metadata object 精确为 `513,565 B`，artifact-register request frame 精确为 `513,803 B`，后续 UniProt request frame 约 `514,234 B`；它们暴露了 control socket 的局部 framing defect。旧 server 把一次 `recv(65536)` 错当完整 JSON-RPC request，截断合法 NDJSON frame 并让 worker 退出。该问题不需要新增顶层真状态、operation schema 或调度语义，因此按小修处理。Host 与无依赖 SDK client 都锁定一连接一帧 JSON-RPC 2.0 NDJSON，请求/响应 payload 对称上限 `4 MiB`（不含 newline），跨 chunk 聚合；非 null id 只允许 UTF-8 `<=256` bytes string 或 signed int64，其他 semantic error 保留 safe id，而 oversized/invalid id error 使用 null；malformed UTF-8/JSON、EOF 残帧、identity drift 或超限均结构化 fail closed，首newline后已观察到的非空trailing bytes在dispatch前拒绝。每connection最多执行一个request；首帧接受后晚到的第二帧可只遇到connection关闭而无第二个error，但绝不执行。per-connection fault不得杀死accept worker。SDK发送前检查request size并有界读取response，Host oversized response改为小型error。该 correction不升级sandbox protocol/image version，也不授权operation replay。r15的failure bundle与NO-GO decision保留为可验签诊断，不能追认为positive。

r16-r19 的后续真实运行没有降低 GO 标准。r16 因未提供强制的 `OPENZYME_LLM_CONTEXT_WINDOW_TOKENS=200000`，以 `aox_launch_effective_config_schema_invalid` 在科学 I/O 前停止；r17 以 transient `aox_launch_toolchain_pin_execution_failed` 停止，随后独立只读 full-pin probe 通过也不授权复用失败 pin root。r18 成功 pin commit `e6aaa085c94cb1b63bbda5ff44395817495a88cc` 和 config digest `sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`，但 attempt `positive-bb0e97ce9db847c58c9c0dc0b7d0bddf` 在真实 NCBI probe 完成后，MAFFT controlled operation 约 `64s` 即产生 `hpc_runner_timeout`，与 runner 的 `60s` preflight/default bound 一致。独立四工具链 recovery probe 随即通过，因此该次仍按 transient failure 封存。r18 bundle `sha256:4770bdb0d327adfd55826181b5fafbc6de3312e5953e745fefc7562627e5fbf1`、decision `sha256:f5521eb8e0de8dab60c7dc139dcdfd22515859d7701e234c1f17fa0108e8f520` 均为 NO-GO，MICU 累计 `41,023,337 / 500,000,000`，零 breach/overage。

r19 attempt `positive-98b4c1cdab5a47e6bd83d3c91b64d9fe` 最终完成六个真实 probe operation：NCBI `op_2bfe8f7ec798`、UniProt `op_077c1756762a`、MAFFT `op_4b74f52b785f`、hmmbuild `op_6d911baa02ef`、CD-HIT `op_0c33b3927655`、HMMalign `op_cfd9780670c5`。但首个 operation-bearing sandbox run 在 NCBI 完成后错误调用 `registered_artifact_ref(provider_file_ref(...))`，以 `artifact_registration_projection_invalid` / `sandbox_exec_nonzero` 失败；source 修复后，第二个 run 复用 attempt-local NCBI checkpoint 并完成其余五项。该事实横跨两个 operation-bearing run 与两个 source snapshot，且保留历史 failed run，违反当前 probe exact-one successful run/source 与 no-failed-run-history 合同。r19 non-eligible bundle `sha256:d811da6e9fd0f291413c7f0369c6399f24e38d94997dc0d24516155773a72f16` 和 sealed NO-GO decision `sha256:f067ac844a5cd2df557d8b03b6ad89eb05c2b58f94fc502f04e976d9e55ccf84` 不得追认为 positive；MICU 累计 `41,557,461 / 500,000,000`，remaining `458,442,539`，零 breach/overage。selector 互斥、failed-run pre-dispatch stop 与 Host current-source binding 属局部 correction；若允许同一 attempt 跨 run 采用已经完成的 effect，则必须实施独立提案中的 durable selection/disposition/adoption/materialization/closure 及 bundle/verifier `@2`，本 Goal 不实现。

r20/r21 的独立 clean pin 分别因 remote preflight 与 HMMalign pin command timeout 停止，后续只读 recovery 通过也不授权复用。r22 在 commit `8791dac334a2418d9ef5ad15b89ff32b19429f32` 成功 pin，attempt `positive-8f9cc348326244939469da424daf046b` 的 probe 在单一 successful run `srun_cf22230c4b99` 内完成 NCBI/UniProt/MAFFT/hmmbuild/CD-HIT/HMMalign exact six operations，formal Chrome approval `appr_a09dd0d824b5` 也证明 `op_ca8f635e43b9` 恢复到同一 `srun_86107f5b8e3f` / `sw_a2320c75a37b5f96751de797`。但 formal source 随后把规范化 `AOX_ref.hmm` 登记为 `kind="model"`；该值不属于 `ArtifactKind`，formal 在真实 NCBI、MAFFT 与 hmmbuild 后本地失败，failed-run guard 阻止所有后续 external dispatch。r22 non-eligible bundle `sha256:2825e71fdde04d705591a97cc5184371c1735c9e24cbf64fd1fcac67818c05fe` 与 NO-GO decision `sha256:2338261b56076744bfdab7b12d78b0f0ebf5436a8e64bd814b8c145101ee0345` 只封存失败事实；MICU 累计 `43,593,190 / 500,000,000`，remaining `456,406,810`，零 breach/overage。局部 correction 保持九值 kind 闭集：SDK 在 control call 前校验，Host/Core/Podman raw boundary 对旧/绕过调用重复校验并统一返回 non-retryable `artifact_kind_invalid`；bio-tools 对显式非法 runner kind 不再按扩展名静默回退，而是在 runner dispatch 前拒绝，显式 valid-but-wrong kind/format 同样按固定模板 fail closed；AOX final mapping 固定为 FASTA=`sequence/fasta`、HMM=`result/hmm`、CSV=`result/csv`、JSON=`result/json`，并通过 `aox_fixed_deliverable_artifact_contract@1` 在 online copy/cache-hit、fault target 和 offline verifier 中绑定 exact path/kind/format，不新增 replay 或顶层真状态。

Chrome terminal observation 的动态 handoff 已足够完整，但此前要求 operator 手工拼装 exact 23-field JSON，容易在 60 秒 hold 后的有限提交窗口引入无科学价值的字段、digest 或写盘错误。局部 correction 新增稳定的 `aox_browser_observation_capture@1` → `openzyme-aox-cutover browser-receipt` operator helper：它从 trusted-operator 提供的 Chrome console、page target、三类 MCP request/response 与 PNG 投影派生 raw receipt，拒绝 error console，等待 not-before 后才以 mode-`0600` sibling temp、file fsync、atomic no-replace install 与 parent fsync 发布 exact Host target，且不生成 Host acceptance timing。helper 不证明投影与 MCP 原始 response 的对应关系；这只降低 trusted-operator 摩擦，不把 Chrome MCP 结果升级为签名或可重放 authority，也不新增顶层产品状态。

r23 在 commit `3e9d9d3ddc74bbce063d68cb7ee4c802b05c585a` 上继续使用 fresh pin/root。真实 probe 六项 controlled operation 均完成，但源码以 `f"{OUT}/provider/..."` 拼接 provider output root，public-safe scanner 将其中 slash-prefixed suffix 误判为未知 Host absolute path，故封存为 `probe_attestation_unavailable`；局部 correction 只要求完整 `/workspace/output/provider/ncbi|uniprot` literal 并补真实 source-envelope 回归，不放宽 scanner。formal NCBI/MAFFT/hmmbuild/EBI HMMER 均完成，产生 68,542 raw rows 和 37,722 score-filtered UniProt accession；唯一 UniProt operation 在 378 个 Host-internal query batch 中运行时，旧 scheduler 因一次 SQLite contention 永久退出 heartbeat，五分钟后正确的 repository fence 拒绝 stale canonical write。该失败不是科学 empty/negative，r23 bundle/decision 永久 NO-GO 且不可复用。局部 correction 让每次 file-backed heartbeat/retry 使用 fresh scope，只对 SQLite `BUSY`/`LOCKED` 在现有 lease deadline 内有界退避；其他异常显式传播，confirmed lease loss 仍 fail closed。`RuntimeWriteFencingError` 跨 sandbox control、Pipeline SDK 与 Host API 稳定投影为 non-retryable `runtime_write_fenced` 与固定公开消息；原始异常文本不进入公开投影，既有 Host-private logging 语义不变。这不拆分 UniProt controlled operation，也不实施 durable async continuation。

r25 pinned commit `6b9ac473fe01376d144ae800352a06e5d016223c`。其 EBI HMMER job 约 `24s` 已 terminal，但旧 adapter 把默认 50-hit terminal poll body 当 page 1，再从 `page=2&page_size=100` 开始，因而漏掉索引 50..99 的 50 条 hit；r25 封存的 68,542 条不满足 terminal `nreported=68,592`，且缺失的 50 条全部高于 AOX score threshold。同 job 的只读恢复诊断以统一 `page_size=1000` 从显式 page 1 读取 69 页（末页 592），完整物化 68,592 条并产生 37,772 个 score-`>200` accession；该恢复只是诊断，不是 cutover artifact。旧 37,722-accession UniProt 请求还使本轮首次观察到 `A0A034VJ94` 的 exact typed inactive identity：`entryType=Inactive`、`inactiveReasonType=DELETED`、reason 为 `Not part of a reference proteome`、`uniParcId=UPI000453BEA2`，按 provider 语义无 sequence/audit。旧 contract 将它错判为 schema drift。随后对纠正后 37,772-accession set 的 read-only census 覆盖 `378/378` batch，得到 `5,596` inactive（`5,594 DELETED`、`2 MERGED`、other `0`），全部 UniParc 有效且 raw inactive object 都是由 `entryType`、`primaryAccession`、`uniProtkbId`、`inactiveReason`、`extraAttributes` 构成的 exact-five-key 顶层 shape。两条单目标 MERGED 为 `A0A2U8U0K3 → P18173`（`UPI000A0F4040`）和 `A0A8N4L368 → A0A034VJ86`（`UPI001114BBC8`）；scan-manifest digest 是 `sha256:4d734dd881829450178ed260ef331f7c3a21cdf0006f14ad3daa886c36125458`。该 census 只冻结当前 schema 诊断，不固定未来 provider 数量，也不可作为 cutover evidence。故 `@2` 接受 exact requested-primary `DELETED|MERGED` 判别联合、禁止跟随/抓取 replacement，`DEMERGED` 与未知/malformed reason 继续 fail closed。r25 同时因 HMMER coverage 缺口和 failed operation-bearing run 永久 NO-GO；恢复 bytes、operation、checkpoint 或 artifact ref 均不得 adoption。fresh blank-world attempt 必须同时满足 HMMER 无缺口 closure、UniProt active/inactive exact partition 和既有 17-deliverable verifier。

r27 pinned commit `d922f136fa44fe1142ad58a65647a0eee58ce281`，config digest保持`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`。positive attempt `positive-a02c118c11dc4e7fb0ef516157ad9100` 经Chrome解决canonical approval后，真实EBI HMMER完整得到`68,592` hits / `69` pages / `37,772` score-filtered accession；唯一UniProt operation完成`378` query batches，闭合为`32,176 active + 5,596 inactive`，随后length join得到`2,561` records。`aox_sequence_length_join@2`完整`identity_mappings` logical metadata为`17,016,803` canonical JSON bytes，旧SDK将其内联后RPC约`17,767,360` bytes，超过4 MiB；故首个`hits_len650_700_200.csv`在Host dispatch前以`sandbox_transport_request_too_large`失败，没有该output的partial Artifact。attempt bundle `sha256:4920739cde6aa9bb7f5fd484674bbbccbc8d385bf7c6c98b872390d922ccac3c`与campaign decision `sha256:4628f5f2a91eed77808b09b875e3daaddf893160503d60850985b714aedd0c0b`均只封存永久NO-GO事实，不得追认为positive；MICU累计`49,959,197 / 500,000,000`，remaining`450,040,803`，零breach/overage。

r27后的局部correction不提高4 MiB frame，也不删除科学mapping：SDK用`<=256 KiB` inline、`(256 KiB,32 MiB]` attempt-local digest-bound sidecar，Host以fd-anchored/no-follow strict loader对exact wire path及bytes在effect前验证，canonical Artifact row继续保存完整logical metadata；direct response的artifact收窄为exact `{artifact_id,metadata}`，metadata和validation投影为bounded versioned summary。active compatibility runner修正64 KiB单次recv与partial-frame timeout，诚实返回省略重复path/context的compact `pipeline_provisional_registration_response@1(canonical=false)`，在128-item上限内保持bounded且不能伪装durable ref；SDK partial response同样以固定5秒timeout fail closed。大型metadata从SQLite row迁移到immutable manifest、真正bounded paging、dedup/GC/verifier migration只记录在`docs/v3/architecture-proposals/bounded-canonical-artifact-metadata-manifest-references.md`，本Goal不实施。`register_many`只补item/aggregate cap与全metadata transport预检；晚项非metadata失败的跨项transaction仍属于既有outcome-unknown proposal。

最终修复使用r27保留的exact HMMER/UniProt输入，在campaign root外的全新单进程file-backed SQLite/workspace、当前SDK和真实Unix socket上执行transport-only replay：重现`2,561` hits、CSV `sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`以及`17,016,803` bytes / `sha256:873a5ff9be6114f761b0ed48a9be2509c74bbb024955555dfe4700d015524f25` logical metadata；唯一sidecar size/digest相同，catalog逐字段保留完整logical object，strict-selector可消费的response只有`1,234` bytes。该诊断没有provider/HPC/MICU调用，明确`diagnostic_only=true`、non-cutover，不改变r27永久NO-GO或授权任何adoption。

r28 pinned clean commit `bea16bef2a54c8fb75a7649fe8a17a0c6ee7bc07` 与 r27 相同的旧 config digest，fresh positive attempt `positive-cfddd24986bf465fa49ef70449c5ec63` 的known-positive probe完成exact 2 provider + 4 HPC，formal PubMed也选择唯一canonical artifact；但formal executor三次触达`120s` MICU timeout，`world.inspect`因opaque-ref namespace规则错误拒绝合法`aox_...` current task id，最终又把shell heredoc当作Python direct argv，`srun_9b0a7b28365f`以exit 2 / `sandbox_exec_nonzero`失败。formal尚无controlled operation或approval；bundle `sha256:be8edc94d95f9800dfae403270372447e6b4335388b0d2f51bd23cbfa472c577`通过自身offline verify但明确non-eligible，decision `sha256:5b832c85c1c79e0903a3a6cfa1ab1696b8d58642c2f79f47bd5125c312e57d56`永久NO-GO，MICU累计`55,691,311 / 500,000,000`。局部correction只修正安全product task filter、agent-visible direct-argv合同与pre-run typed heredoc拒绝；下一pin必须把live request envelope设为`300s`、一次pre-response retry和configured `max_tokens=8192` request cap，不改变科学/operation fail-closed或把r28变成可采用证据。

r29 pinned clean commit `2c0adce5adf5905560fa552c3efabc70c6f7d31d` 与 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`，且已把 `timeout=300`、`max_retries=1`、`max_tokens=8192`、`context_window_tokens=200000` 封入 identity。fresh attempt `positive-39ce51e320414f149023e2ddc5f55e18` 的 attempt-local 状态显示 NCBI、MAFFT、hmmbuild、UniProt 四个真实 operation 已完成；CD-HIT `op_9d6144ff379a` 使用正确 digest `sha256:fbaf487d05f7a9cdff8afae156367ae521378aa67036e62ae7ea514b762add97`，但 runner 在 payload 前以 exact `runner_failure@1(phase=input_parent,input_ordinal=1,returncode=255,timed_out=false,elapsed_seconds=60.267664)` 失败，HMMalign 与 formal product path 均未启动。private stderr 不投影，因此只能判定 SSH input-parent staging command failure；pin 和随后只读 SSH probe 成功与 transient recovery 一致，但不授权复用。bundle `sha256:84c5083e6b1bc562ffb7c6826fb74010c6ea2807998c7cd074962ed263feae1e` 自身 offline verify 通过但 six probe checks 仍因 `probe_attestation_unavailable` 失败；decision `sha256:d7073ddcff93146fdc72330de4143bf78b1e03a13075038ca680d56ac7270867` 永久 NO-GO，MICU `55,691,311→56,276,589 / 500,000,000`，delta `585,278`、remaining `443,723,411`、零 breach/overage。局部 correction 只把安全 `error_code/stage/retryable/hint/details.runner_failure` 经 sandbox control response 透传到 SDK，保留一次 dispatch 与现有 no-adoption 语义；下一 campaign 必须 fresh clean commit/SDK pin 与 fresh roots。

r30 pinned clean commit `24c403effb2a5f30821392384c552c83a03f4cf5` 与相同 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`，fresh attempt `positive-7d634900da8c4cc3b1580f68a9c055df` 的 known-positive probe 完成真实 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项 check。formal NCBI、MAFFT、hmmbuild、EBI HMMER 也完成；HMMER 闭合为 `68,592` hits / `69` pages / `truncated=false`。formal UniProt 已在 `378` 个 query batch 中抓取并验证 `37,772` 个 requested identity（`32,176 active + 5,596 inactive`），但登记 `providers/uniprot/provider_parsed/sequences.fasta` 时，把 `32,176` 项 active-sequence `sequence_digests` map 内联进 Artifact metadata，超过 `256 KiB` ArtifactBoundary 上限；FASTA 为 `20,297,730` bytes，`69,353,082` bytes raw pages 已先登记。sandbox 因 non-retryable `provider_artifactization_failed(stage=bio_artifact_registration)` exit `1`。Chrome 已真实批准 formal operation `op_a6d1d125c83c`，但未到 terminal observation handoff；formal report、positive 2 与 fault 均不存在。non-eligible bundle `sha256:825d2a13c9188c3fadc5c130c2c7ce0b10444c0a957ed2fb44e4c67f04d92887` offline verify `issues=[]`，sealed decision `sha256:e8122845ff9e9b2467990da4cfacee02782311c0c11d6bef636721e824a45ecb` 永久 NO-GO；MICU `56,276,589→58,976,497 / 500,000,000`，delta `2,699,908`、remaining `441,023,503`、零 breach/overage。r30 全部 root/effect/artifact/browser/bundle/decision 永久不可复用。局部 correction 保持完整 active/inactive identity partition 位于独立 canonical `metadata.json`；FASTA Artifact metadata 只以 count、exact canonical index digest 与 contract id 替代线性 active-sequence map，同时保留固定 provider provenance。该 bounded catalog summary 不是 cutover eligibility 输入；formal UniProt 的既有 raw→parsed metadata→FASTA 科学闭包仍由 verifier 独立重算，其他 provider 路径继续依赖各自既有 byte-Artifact/operation contract而非该摘要。`batch_size` 只接受 exact non-bool integer；所有 artifact draft 在任一登记前完成 path-conflict preflight。该要求不提高 metadata limit、不重放或采用 provider effect；后续 campaign 必须 fresh clean commit/config/SDK pin 与 fresh roots。

r31 pinned clean commit `d430be9d106f5a978794a0c588e8fcd28e013e7f`、相同 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef` 与当时 workflow ref `workflow:aox-hmm-live@2.0.0#sha256:eb4a36e2d4ef3e294406d6fcf93d8414c00afa8fff8d7060ef7fed34f7632d98`，fresh attempt `positive-9dfa89f23352424f8ba0f1d993ad6a3f` 的独立 known-positive probe 再次完成两项真实 provider 与四项真实 HPC check，且保持 formal data isolation。formal researcher 也完成真实 PubMed adoption，选择 `art_provider_5eaf6f6b2864`；但 executor 在空 `/workspace/src` 上以 `sandbox.exec(["python", "-c", ...])` 做 package/signature introspection。既有正确 runtime 在 `SandboxRun`、process 与任何 controlled operation 前以 `source_snapshot_empty` fail closed，execution task `aox_execution_cutover_4f9d1ec865484a73b4544cdb8ccedfcb` 显式 failed，reporter 保持 blocked；没有 formal approval、Chrome handoff、formal operation、published report、positive 2 或 fault。non-eligible bundle `sha256:72a118a7b888cecc066274e9b101a36d0d95cce8d3cf4e7e93c0c0f5d9db730a` offline verify `issues=[]`，sealed decision `sha256:762cabdc53719ce4129755a35a33656d13ed6899f3164cf8113b60b57c31313c` 永久 NO-GO；MICU `58,976,497→59,877,108 / 500,000,000`，delta `900,611`、remaining `440,122,892`、零 breach/overage。r31 roots/effects/artifacts/browser/bundle/decision 永久不可复用。局部 correction 不改 snapshot runtime：只在 agent-facing tool descriptor、executor contract、controlled docs 与 probe/formal prompt 明示通过前序校验并进入 source preflight 的每次 exec 都要求 eligible non-empty source，并分别为 `sandbox.exec` whole-tree preflight 与 direct `artifacts.snapshot_code` selection 返回可执行的 factual hint；controlled docs 优先，确需 introspection 时先 author source。不得生成 placeholder、添加无审计 inspection fallback 或放宽 provenance。受影响 workflow knowledge 必须重算 digest，下一 campaign 使用 fresh clean commit/config/workflow pin 与 fresh roots。

r32 pinned clean commit `f54ea431ceaeff9274527afb20816c8110e39ee3`、相同 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef` 与当时 workflow ref `workflow:aox-hmm-live@2.0.0#sha256:0d78c5246018b71a7ef79258cc410dfd4f300495bb4e5a37af58e096a0e29241`，fresh attempt `positive-9f2badd3274d42fdabb4e1421f7d5e47` 的独立 known-positive probe 完成 NCBI、UniProt、MAFFT、hmmbuild、CD-HIT、HMMalign 六项真实 check，formal researcher 完成真实 PubMed，formal NCBI operation `op_b5857f8371a9` 也由 Chrome UI 对 canonical approval `appr_3ea9addd5614` 完成同 operation/digest resume。随后同一 source-bound sandbox run `srun_0ee366725cd1` 在封存源码 `aox_cutover.py:268` 将 `result.to_fasta()` 的 Python `str` 直接传给 bytes-only `Path.write_bytes`，以 `TypeError: memoryview: a bytes-like object is required, not 'str'` / `sandbox_exec_nonzero` fail closed；execution task 显式 failed，reporter 发布诚实失败报告，但不存在后续 formal operation、terminal Chrome observation、eligible report、positive 2 或 fault。non-eligible bundle `sha256:039cbb6551cd785f9c5c9ac023cfa6d899503d52a0df7c570ced942e603411a6` offline verify `issues=[]`，sealed decision `sha256:7b168335c45f7e8865aea8e92f591596c5a743d24894d1a958adc2882e45e5e8` 永久 NO-GO；MICU `59,877,108→62,008,441 / 500,000,000`，delta `2,131,333`、remaining `437,991,559`、零 breach/overage。r32 roots/effects/artifacts/browser/bundle/decision 永久不可复用。局部 correction 不修改科学 callable 或 implementation digest，只把当前 SDK 的 primary FASTA/CSV/JSON accessor 与 `metadata_json()` 精确投影为 `str`、`metadata()` 投影为 `dict[str, object]`，并要求进入 `Path.write_bytes` 等 bytes-only 边界前 exactly-once UTF-8 encode；annotation/type drift 直接 fail closed，禁止 best-effort coercion。AOX SOP 更新为 `sha256:d325d4e72bd89217b9506d79e168b6d4f177c348082efd067a425217a415fe26`，workflow ref 更新为 `workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`；下一 campaign 必须使用 fresh clean commit/config/workflow pin 与 fresh roots。

r33 pinned clean commit `2ef39e02273ceb3784f6f77f53100ce2af26228b`、相同 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`、workflow ref `workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf` 与 fresh declaration commit `sha256:b783665a70b36f475b582bde3486eda65ed82cc7f9f43d8d8083793459635316`，fresh attempt `positive-44e0487fd8fb49569facd6d93d77f69e` 的独立 known-positive probe 再次完成六项真实 check，formal researcher 完成真实 PubMed PMID `42278471`。formal executor 已正确按新类型合同对 serializer text 做 UTF-8 encode，但在 source module import 阶段先执行 `Path('/workspace/input/aox_cutover').mkdir(...)`；sandbox process 的 input mount 正确为 read-only，故 `srun_0e6b36a1f5e2` 在任何 formal provider/HPC operation 或 approval 前以 `OSError: [Errno 30] Read-only file system` / `sandbox_exec_nonzero` fail closed。reporter 发布诚实失败报告；没有 Chrome handoff/approval、eligible report、positive 2 或 fault。non-eligible bundle `sha256:5abc24e21fee44da499e6b01f051e0cf34503ab4fbb749ac462aae06d2d72a2f` offline verify `issues=[]`，sealed decision `sha256:318d3d623d42395684e0af52a96576e3fef046990c94ed6a3a846eb89596c8c8` 永久 NO-GO；MICU `62,008,441→64,808,804 / 500,000,000`，delta `2,800,363`、remaining `435,191,196`、零 breach/overage。r33 roots/effects/artifacts/browser/bundle/decision 永久不可复用。局部 correction 不改变只读 mount：materialize tool descriptor、强制读取的 artifacts 文档、AOX SOP 与 formal prompt 均明示 caller 不得在 `/workspace/input` mkdir/write/copy/pre-create，`artifacts.materialize()` 自身通过 Host 创建 target 与 parents；mutable scratch/output 分别使用 `/workspace/work` 与 `/workspace/output`，`EROFS` 不授权 remount/fallback/duplicate operation。AOX SOP 更新为 `sha256:a9f636a1ba9c974b31c984db900fd07687ce2399d0412e80b73d69fee3ff2c0a`，workflow ref 更新为 `workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`；下一 campaign 必须使用 fresh clean commit/config/workflow pin 与 fresh roots。

r34 pinned clean commit `bd87adbb03a005ed8d87a0cd00c7336727a12e94`、旧 config digest `sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`、workflow ref `workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a` 与 fresh declaration commit `sha256:e255bda0b0b19d7108a0aa7271b9763d4c587cea0f6ef56fcd983f85a211fe72`，fresh attempt `positive-66a1cde757804d5c851a84f21a77fb35` 在独立 probe、formal session 之前失败。原始 probe task 的 real NCBI `op_8cd0e405d335`、UniProt `op_644823f9483a`、MAFFT `op_ecc41e1f61b3`、hmmbuild `op_e202d38e35b8` 已完成，CD-HIT `op_9c45ba4e7a4d` 以 `hpc_staging_failed(stage=hpc_staging,retryable=true)` 失败，HMMalign 未运行，task 显式 failed 并正确禁止 retry。旧 driver 却在唯一 `runtime.drain:1(max_signals=10)` 返回并检查 terminal state 前继续消费 queued master wakeup，创建两个 replacement task；其 NCBI operations `op_198e3c268386`、`op_9e164b1204bb` 均被现有 budget guard reject，没有 effect adoption，但额外消耗 MICU 并把最终 blocker 污染为 `cutover_operation_budget_exceeded`。non-eligible bundle `sha256:ec1299a5f055f4be0ed07a6965994f58ce7f55165b8580ffe1e038301e27e944` offline verify `issues=[]`，decision `sha256:8dd7676ccd48653b570618e8aa1680998630011a4733d3ce6c8f14f968ab654e` 永久 NO-GO；MICU `64,808,804→66,138,051 / 500,000,000`，delta `1,329,247`、remaining `433,861,949`、零 breach/overage。r34 全部 roots/effects/tasks/browser/bundle/decision 永久不可复用。局部 correction 将 cutover effective config、CLI 默认、runtime runner 与 evidence request identity 全部固定为 `max_signals_per_drain=max_signals=1` 并拒绝其他 pin；同一 agent turn 内 serial approvals 仍由一个 drain 协调，但每个 signal 返回后必须先检查 durable operation/task/sandbox failure，故 failed executor 后排队的 master wakeup 不能在该 attempt 被 claim。它不重试 transient CD-HIT、不改变 scheduler 产品默认、不收窄 agent turn 内策略；下一 campaign 必须使用 fresh clean commit、新 config digest 与 fresh roots。

r35/r36 使用 clean commit `94ee5eb74a7b0e9b3d0fa65dc49efa43580a4f65`、config digest `sha256:bc83b3c14973a513279361f220710e137d0da8f259f68e7026badad69fe68485` 与 workflow ref `workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`，各自 known-positive probe 均完成真实 exact six checks；formal PubMed/NCBI/MAFFT 与 Chrome same-operation approval也完成，但 hmmbuild 均在 payload 前以 runner `remote_layout` return code `255` / `hpc_staging_failed` 停止。r35 attempt `positive-ed6e23d5a63843a0800f71c7e12a95a9` bundle/decision 分别为 `sha256:9de50d9f24e5521d1022c69f2c1f3d7aabd08ecef7c47d9b7deb022d113f9a90` / `sha256:e1699b0b28f2a2f561eeb3b027d795684860d17e481babab2e703e29476d8c15`，MICU 累计 `67,127,906 / 500,000,000`；r36 attempt `positive-a7286a020bbb4fb6a18211fbced008ad` bundle/decision 分别为 `sha256:d3a421ef4bbbee57879be457671344537e60414273f948fc5db109589d73bef6` / `sha256:1c06f3f0995c5c369f502b6fa496dab03b3021c20a560401cf0aacf69c370319`，MICU 累计 `67,949,791 / 500,000,000`。后续独立 SSH 健康只说明 transient recovery，不授权采用；两轮永久 NO-GO。r37 因错误 shell-source `.env` 只留下 incomplete root、没有 canonical bundle/decision，永远不是 evidence；账本消耗仍保留，r38 启动前累计 `68,091,186`。

r38 fresh attempt `positive-f53ef36dcdf04817baebfdaeed1bbf59` 首次穿过此前 blocker：probe exact six、formal PubMed/exact-14 NCBI/MAFFT/hmmbuild、Chrome approval、EBI HMMER `68,592` hits / `69` pages / `37,772` score-filtered accessions，以及 UniProt 约 `378` 个 query batch 均真实完成，随后到达 HMMalign approval `appr_df15c554b6cf` / `op_6fdb7e5a9f64`。失败根因是 public read-model amplification，不是科学空结果：43 个 Artifact 的 canonical metadata JSON 合计约 `36,963,643` bytes，旧 workspace 在 artifacts/index/activity/capability 多次回显为 `106,364,236` bytes，r38 DB 上构造约 `57.766s`；driver 又在同步 drain 内每 `0.5s` GET workspace，approval resolve 的 write UoW 通过 activity backfill/command response重复构造它。approved HMMalign continuation 未及时 claim，最终 `internal_error` fail closed。bundle `sha256:66a3582c593b9ac979f21ce039385eb00fe1fe07e3c1dce543b7c22e5fdb0669` 与 decision `sha256:1f0870318927623b124895b4d370ea5b00fd23ebfe2f50cf9a72280e3b3c8e32` 只封存永久 NO-GO；MICU `68,091,186→69,063,458 / 500,000,000`，remaining `430,936,542`，零 breach/overage。

局部 correction 增加与 workspace pending approvals 同源的 compact `GET /v3/sessions/{session_id}/pending-approvals`；它只投影 Approval/ControlledOperation/SandboxRun rows并校验 exact response/session/approval identity。cutover driver 热循环和 cleanup 只读 compact view，Chrome handoff与 drain 退休后证据才读取 workspace。workspace 的 artifact、index、activity、capability occurrences 统一复用现有 `artifact.list` bounded item contract，catalog exact metadata 不截断并继续由 `artifact.get` 分页；derived activity-event backfill 直接构造 sanitized activity projection，不再在 mutation write UoW 内递归构造 composite workspace。r38 DB 的 correction 后只读 benchmark 为 compact read约 `0.0013s`、workspace build `2.771s`、JSON `727,362` bytes；它只验证 correction，不追认 r38。下一 campaign 必须 fresh commit/config pin 与 roots。

本轮还确认 current collector 逐文件直接写 final evidence root：单文件 no-replace/append-only 不提供 collection transaction，也不能统一证明 committed artifact root 与 declared inventory exact equality。两阶段 private staging/prepare/verify→atomic commit、artifact-root 全闭包、failure atomicity、crash recovery 与 schema migration 需要跨 collector/archive/verifier ownership 调整，已单独记录在 `docs/v3/architecture-proposals/transactional-attempt-evidence-collection-and-root-closure.md`；本 Goal 不实现，也不把 proposal 语义追溯附加到现有 bundle。

本轮还确认 controlled-operation `resource_estimate` 当前由 sandbox SDK 自报，Core 只验证它是 mapping；SDK 默认 query cap 常量可能与 Host 注入并收紧的 provider config 漂移，因此 approval 中的 estimate 不是 authority。让 sandbox只声明需求、Host按 route policy + injected config重算canonical estimate/actual limits并绑定approval/config identity，需要跨 SDK/Core/engine/schema迁移，单独记录在 `docs/v3/architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md`，本 Goal不实现。

### 2026-07-25 r58 diagnostic final-response/closure addendum

r58 used clean commit `d00ada97f8eb13af35f9c83247cd51e14138f428` and consumed the
separate diagnostic plan
`sha256:691cf17bd8548fa3bfd4e338cb61ce608bb97c4cde17f0e66483b84ff65397e3`.
Its root was `aox-diagnostic-335c68cf214a01b34876f97b`. Run-class isolation
again held: diagnostic eligibility stayed false and no formal campaign slot was
authorized or started.

The independent probe and the formal NCBI/MAFFT/HMMBUILD/EBI-HMMER/UniProt/
HMMALIGN/CD-HIT path all completed. The formal result contained 516 candidates,
78 CD-HIT representatives, 13,778 similarity edges, all 17 normalized outputs,
a sealed selection, one published source-linked report, and explicit completed
exits for all three canonical tasks. Browser approval was observed. This is the
first meaningful end-to-end scientific result/report in the diagnostic series,
but it is not acceptance evidence.

The remaining blocker was a harness lifecycle contradiction. After report
publication, the master inspected world/thread state and returned an
assistant-only final answer. That text could be persisted, but no new wakeup
remained on which the same master could explicitly call
`scientific.attempt.close`. Conversely, the post-r57 terminal-action rule ended
the turn immediately after a successful close, while provider-response text
attached to a tool-call response was previously retained only in the LLM trace
and never became the canonical assistant conversation message. The active
attempt therefore had neither closure request nor closure; the child exhausted
120 formal drains after seven approvals with
`formal_runtime_drain_exhausted`. Diagnostic decision
`sha256:8c877189130838b29030200d9c592e8e096cd028cd60a5c5bc38dd424c718a57`
is permanent **NO-GO**. MICU moved by `2,119,558` to
`96,363,097 / 500,000,000`, leaving `403,636,903`, with no breach or overage.
All r58 authority, root, state, effects, artifacts, browser receipts, report and
decision remain immutable and non-reusable. Because a meaningful result/report
formed before this framework blocker, the user's conditional trigger for
another diagnostic/formal specification split did not fire.

The forward contract keeps closure agent-authored. Host does not auto-close,
infer a selection, synthesize an answer, or choose strategy. The AOX formal
lifecycle policy is bumped to
`aox_cutover_formal_tool_precondition@2`. When the exact close readiness facts
hold for one active attempt, an assistant-only master response is returned to
the same bounded model loop as a structured no-effect rejection and is not
written to conversation truth. The model must instead include its complete
user-facing answer as response text in the same provider response that calls
`scientific.attempt.close`. The invocation carries this private companion text;
the close handler rejects an empty companion before any closure effect. Only a
successful terminal close result marks the companion for persistence, after
which harness writes it exactly once, settles later calls as no-effect, and
retires the turn. Failed/rejected close attempts persist neither answer nor
closure request. The response-policy seam is Host-composed and inherited by
master runtime; unmatched sessions retain ordinary assistant behavior.

### 2026-07-25 post-r58 durable closure-response correction

The r58 correction originally fixed the model-turn contradiction but still left
two cross-layer gaps. Its positive precondition and live collector independently
required `report.status=ready`, although the public report contract and r58's
durable state permit `published`; and the closure request was committed before
the harness wrote the companion conversation message.

The forward contract derives one successful publication predicate from existing
report/draft truth: the report is `ready` or `published`, the draft is
`published`, both identities and task/session match, and the draft links one
non-empty content document to that report. Policy, projection, live collection,
and offline verification consume this predicate while preserving the actual
report enum.

The co-terminal response remains agent-authored. The close tool now uses the
existing Core SQLite atomic boundary to commit the closure request, deterministic
conversation document/message, and immutable
`scientific_attempt_closure_response@1` binding together under the requesting
writer. A replay verifies and returns the same binding; a changed response or an
older unbound pending request fails closed. Host finalization verifies any
present binding against the canonical conversation bytes before closure. This
adds no new top-level product owner and does not authorize live continuation.

### 2026-07-26 r59 positive-exit handoff correction

r59 在 clean commit `431e2c558c13ebd1f99dcc9e3eae6758630a843d`
上消费 formal exact-three plan
`sha256:168aa86c433b3c3b90aab4c665453a56cb796f99056f7d04567bc8f453b8e7de`，
但只启动 positive 1
`positive-c3c2c4cc13a367fb54eec84505a61742`。独立 probe exact six 与
formal NCBI/MAFFT/hmmbuild/EBI-HMMER/UniProt/HMMalign exact six 均为
terminal-known success；Chrome 对 canonical approval 完成 same-operation resume。
formal HMMER score-filter 得到 37,772 个 accession，UniProt/length join 得到 2,561
个 target，motif filter 诚实得到 0 candidate，execution summary 固定原因为
`no_candidates_after_motif_filter`。executor 封存了 current selection
`selection_090ab4b6c30e4839d60dd664`，reporter 发布 source-linked report
`report_1ba5b65a4582`；healthy empty 是有效科学结果，不是 discovery。

生命周期随后被错误终态化。executor 尝试 master-only
`scientific.attempt.close`，Router 正确以
`aox_cutover_close_actor_violation/no_effect/same_phase_safe` 拒绝；executor 却把这个
预期 handoff 误解释为 harness capability unavailable，并将 canonical positive execution
task 以 owner-authored `blocked` 终结。master 随后尝试改写为 `completed`，generic task
board 正确以 `task_already_terminal` 拒绝；没有 reopen/resume 合同。master 又把
inspection 中的 `selection_active_writers` / `closure_ready=false` 误读为当前 turn
不能请求 closure，因而只形成非持久的 assistant response。active attempt 最终没有
closure request，120 formal drains 耗尽。

该 inspection 投影混淆了两个不同阶段。`request_attempt_closure()` 必须在 requesting
agent writer 仍有 authority 时持久化 intent，并按 selection-seal evidence boundary
忽略该预期 writer；Host finalizer 才在 turn 退休后要求 writer quiescence。forward
projection 因此保留 legacy `closure_ready` 作为
`host_finalization_after_request` readiness，同时新增
`closure_request_ready` 与 `closure_finalization_ready`。sealed selection 在只有 active
requesting writer 时应投影前者 true、后者 false；这只是结构化事实，不替 agent 生成
closure intent。

session policy 升为 `aox_cutover_formal_tool_precondition@3`。它仍允许 positive executor
在 selection seal 前对真实 authority/provider/HPC/runtime blocker 使用普通
`blocked|failed|cancelled` 语义；一旦该 assigned executor 的 current positive
selection 已 sealed，这些 non-completed exit 会以
`aox_cutover_positive_execution_exit_mismatch/no_effect/same_phase_safe` 被拒绝，并明确
要求 owner-authored `completed` handoff 与 resident master closure。该 guard 不自动完成
task、不自动关闭 attempt、不选择 scientific outcome，也不改变 fault 或 ordinary V3
session。

该 handoff 事实进入 pinned SOP 后，document digest 更新为
`sha256:1c6c30e2241c20e405a35f6d62ff48f42dbd765cf91207f877bfc18fe052b6a0`，
workflow ref 更新为
`workflow:aox-hmm-live@2.0.0#sha256:4ab19e8c7d88429e6019b070a81f7335984aa534ed6d05be200d8a275f8ee339`；
此前 workflow ref 对后继 admission/pin/authority 全部 stale。

r59 child/process group、全部 controlled operation/continuation/writer/lease 已退役，
但 attempt 仍 active、execution task 已 blocked、closure request 不存在，因此不可继续
或修补原 state。fatal
`sha256:cf555a381ac9a5c5e38e36d33e83ce78c887c35528096112cbbbd9939a95e01e`
与 decision
`sha256:8b05ef13dfaf79f9a15a647fbbafa446e7ef75656b16db77a7b32baa8b4c6ccc`
保持永久 **NO-GO**。MICU verified lower bound 为
`100,114,267 / 500,000,000`，remaining `399,885,733`，零 breach/overage。全部 r59
authority/root/state/effect/artifact/report/browser bytes 不得复用；后继 formal campaign
仍需 correction 后 fresh clean commit、full admission、pin、exact-three plan、fresh
roots 与对该 exact plan 的单独批准。

### 2026-07-26 post-r59 canonical-readiness qualification

对未提交 `@3` policy 的逐路径审查发现，“current selection 已 sealed”只是 handoff 的
必要条件，不是充分条件。selection seal 固定当时的 universe/evidence snapshot，但不会
冻结 attempt 后续的 operation binding，也不会使 authority、workflow contract、process、
continuation、disposition、adoption、materialization 或 result closure 永久有效。若这些
事实在 seal 后漂移，单看 `state=sealed` 拒绝 executor 的
`blocked|failed|cancelled`，会把真实 blocker 强迫改写成 `completed`，再次制造不可恢复的
业务终态。

forward guard 因此不复制 readiness 条件，也不把 seal 当作成功证明。它通过当前
`SessionRuntimeContext` 的 repositories 与 scientific workflow contract registry 调用
同一个 `ScientificAttemptService.evaluate_selection()`，并且只在 current evaluation 的
`closure_request_ready=true` 时拒绝 positive executor 的 non-completed exit。该字段仍按
request-time evidence boundary 忽略预期 active requesting writer；它并不忽略 universe、
authority、workflow、process、continuation 或 evidence gap。evaluation 不可得或返回
non-ready 都不能证明 successful handoff，task exit 因而保留 generic 显式语义，由 agent
选择修复、建立 child selection 或诚实终止。

回归必须使用真实 SQLite repositories 构造 ready sealed selection，并证明 active writer
只影响 finalization、不影响 request readiness；随后分别让 authority 失效以及在 seal 后
绑定新的 operation universe，证明 selection 虽仍 sealed，policy 也不会强迫 completed。
fault attempt、pre-selection 与 ordinary session 继续不受该 positive-only guard 影响。
该 qualification 只同步 non-live code/tests/OpenSpec/稳定文档和新的 SOP/workflow digest，
不采用 r59 state，不创建 live root，也不授予下一 numbered action。
qualified SOP digest 为
`sha256:2aff245ff633a33f1533e3d076ace08908ee7dcfbbf57b7d0207f576c2d8fa4e`，
current workflow ref 为
`workflow:aox-hmm-live@2.0.0#sha256:a34878a922536f429acb7ebef52e303610df184fcc16acf4dce894704321b313`；
r59 correction 初稿固定的旧 ref 对任何后继 admission/pin/authority 均 stale。

### 2026-07-27 r60 full-path diagnostic recovery-settlement correction

> Historical design record. The turn-local obligation, hypothesis settlement,
> and response-veto correction described below was superseded on 2026-07-28 by
> `simplify-v3-harness-control-boundary`. The r60 failure evidence remains
> immutable; these mechanisms are no longer active product requirements.

r60 在 clean commit `fb890390dc0518476da6334885df3d623bbb9426` 上消费独立
full-path diagnostic plan
`sha256:4467743b950fec87a50464d1ada1149e0c5ba5582bf6faf8d7b068b2f4e1d4ce`，
root 为 `aox-diagnostic-1b4458dc162671cc71d84399`，attempt 为
`diagnostic-positive-d01e53efad6c224c1791421cb32e3447`。run-class 隔离继续成立：
该 plan 只授权一个 `acceptance_eligible=false` diagnostic slot，没有启动 formal
exact-three campaign。

独立 probe 的 NCBI `op_e2f517086e3f`、MAFFT `op_18d3fae18639`、hmmbuild
`op_bd941b05e9ae`、UniProt `op_59f4daae1f0a`、CD-HIT
`op_758a11d2fc72` 与 HMMalign `op_c87011a68d2b` 六项真实 operation 全部完成。
formal researcher 完成而 scientific attempt 仍 active，canonical execution task 为
`in_progress`、report task 为 `todo`；formal 尚未产生 provider/HPC controlled operation
或 Chrome approval，因此不能把 probe success 表述为产品路径成功。

直接 blocker 是 turn-local recovery settlement 过窄。master 先在上游 task 仍 blocked 时
尝试 reporter delegation，形成 terminal-known/no-effect
`failure_53512639855e20439560`；随后调用 `failure.hypothesis.record` 时漏传必需
`idempotency_key`，形成 `agent_can_retry/no_effect/same_phase_safe`
`failure_fc34244aeb4a850e72bc`。同一 agent 紧接着以补齐 idempotency key 的 canonical
调用成功写入原目标 failure 的 hypothesis；在 Harness 第一次拒绝 assistant-only prose 后，
agent 又读取 `failure_fc34244aeb4a850e72bc` 并为它持久化 exact
`failure_hypothesis_bfcf3591d7be824c6da9`。旧 settlement allowlist 仍把这两个成功的
`failure.hypothesis.record` 都当作 unknown nominal write，最终错误产生
`assistant_response_repeated_without_durable_action` /
`agent_turn_recovery_unresolved`，使 exact signal 和 runtime command failed。

diagnostic decision
`sha256:3c8a5001b237e25dbfdde386b02c9138f2c1148fd5f7d2f4c69d4db6e196fc37`
保持永久 **NO-GO**。MICU 从 `107,813,011` 增至
`108,646,236 / 500,000,000`，delta `833,225`、remaining `391,353,764`，
零 breach/overage。由于 formal runtime 在形成 fully settled diagnostic receipt 前失败，
8.3/8.3a 仍未完成；r60 plan、consumption、root、state、probe effects、failure records 与
decision 全部不可复用。

forward correction 不把任意 hypothesis 解释为 repair。只有当前 recovery obligation
本身由失败的 `failure.hypothesis.record` 产生，且后续同名调用返回成功
`failure_hypothesis_recorded`，Harness 才从 repository 重读该 `hypothesis_id`，并要求
它与 ToolResult 的完整 `failure_hypothesis@1` payload 相等、session 与 canonical agent
均等于当前 turn 后结算该 obligation。这覆盖缺失参数后的 canonical corrected retry，
同时不允许 hypothesis 结算其他工具的失败、赋予 retry authority、reconcile unknown
effect、改写 Host failure facts 或改变 task/scientific state。synthetic、跨 session、
跨 agent、missing 或 payload-drift result 均不结算。该局部合同沿用现有 truth owner 与
append-only repository，不新增顶层状态；后继 live 仍需 fresh correction commit、full
admission、pin、独立 diagnostic plan/consumption/root 和对该 exact plan 的单独批准。

### 2026-07-27 r61 full-path diagnostic blocked-delegation disposition correction

> Historical design record. The failure recovery disposition, exact settlement,
> synthetic wakeup, and AOX response-veto correction described below was
> superseded on 2026-07-28 by `simplify-v3-harness-control-boundary`. The r61
> failure evidence remains immutable; these mechanisms are no longer active
> product requirements.

r61 在 clean commit `a66a15597ce3aefdff73105f5a6ad8b14a577089` 上消费独立
full-path diagnostic plan
`sha256:0825957e40b09ad2e2975d98d10fad53f855e1beace4375c6d8836a314df506a`，
root 为 `aox-diagnostic-ad91859299754d89a52d2edf`，attempt 为
`diagnostic-positive-e521b461d344c1258dd47d0389ef7e6c`。其 one-slot authority
与 formal exact-three campaign 保持 schema/root/reducer 隔离，
`acceptance_eligible=false`。

独立 probe 再次完成六项真实 operation：NCBI `op_f44bb795fecf`、UniProt
`op_87f19387e204`、MAFFT `op_511fb3fe1dc0`、hmmbuild
`op_3ad9f919b85a`、CD-HIT `op_564c4bfeeab9` 与 HMMalign
`op_b3a928948f9a`；六项 approval、terminal identity 与 quiescence receipt
`sha256:a6d80e2453eb6a59768a488c2bf24173381362553b15d0b6095fef99e26f51db`
均闭合。formal 尚未创建 scientific attempt、controlled operation、approval、
selection、report 或 closure，因此 probe success 仍不是产品路径结果。

formal master 先以错误 kind `report` 创建 canonical report id，得到无效参数 failure，
随即用 `reporting` 修正并成功创建 research/execution/report 三项 task。research 和
execution delegation 成功；report task 仍由这两项 durable dependency 阻塞时，master
提前调用 `task.delegate`，形成 exact
`failure_74cdc468bf2825461268`：
`task_blocked/agent_can_replan/terminal_known/retry_eligibility=terminal`，
facts 中的 `blocked_by_open_task_ids` 正好是 canonical research 与 execution task。
agent 正确识别为“等待上游完成”，也追加了 failure hypothesis，但只重复 prose，
没有可表达“按现有依赖等待”的 durable recovery decision。Harness 因而保持 obligation，
最终以 `failure_fa7bb62e36562f834a2b` /
`agent_turn_recovery_unresolved` 终结 signal，runtime command failed。

diagnostic decision
`sha256:21d8d0a7421669a4b5c7c36abee3c66c500794f4b2d7150aefa84a68c241e93d`
保持永久 **NO-GO**。MICU 从 `108,646,236` 增至
`109,839,777 / 500,000,000`，delta `1,193,541`、remaining `390,160,223`，
零 breach/overage。8.3/8.3a 仍未完成；r61 plan、consumption、root、probe effects、
SQLite/failure rows 与 decision 全部不可复用。

forward correction 不把 prose、hypothesis 或任意 write 视为等待决策。新增
`failure_recovery_disposition@1` 与 `failure.recovery.record`，初始闭集只允许
`defer_until_task_dependencies_complete`。handler 只接受当前 agent/session 的 exact
`task.delegate -> task_blocked/terminal_known` observation，要求 target 仍为 unassigned
`todo`，请求 task ids、failure snapshot 与 repository 当前 open dependencies 完全相等，
且 blockers 仍为 `todo|in_progress`。Harness 随后重读 immutable record、source failure
与 current dependencies，完整 payload equality 后才结算 obligation。record 显式不授权
retry、不执行 delegate、不改 task/scientific state；cross-tool/session/agent/failure、
terminal non-completed dependency、synthetic/missing/payload/state drift 全部拒绝。该工具
自身发生 no-effect 参数校验失败时，仅同工具 canonical corrected call 可按相同 repository
closure 结算。AOX prompt 同时要求 report task 声明两项 dependency、只 delegate ready
tasks，并在 stale plan 仍触发该失败时使用此 typed disposition，不自动改写 agent 策略。

后继 live 仍需 fresh correction commit、full admission、pin、独立 diagnostic
plan/consumption/root 和用户对 exact plan 的单独批准。

### 2026-07-30 Phase 2 scientific terminal-boundary collapse

r58–r62 的 authority、root、operation、task、report、response binding、closure、
MICU 与 decision 仍是不可改写、不可复用的历史事实；其中 co-terminal response 和
master-only close 仅描述当时生效的旧契约。Phase 2 将 forward contract 收敛为一个
canonical lifecycle owner：`ScientificAttempt.task_id` 当前 `assigned_ref` 是唯一可以
请求 closure 的 agent，Core 在 request 和 Host finalization 两处都重核 assignment。
selection、operation、authority、provenance、writer、quiescence 与 immutable closure
继续 fail closed，但 report publication、resident-master answer 和 conversation delivery
不再参与 scientific closure authorization。

`scientific.attempt.close` 仍是 terminal turn action，但不再携带或持久化 companion
assistant response。active closure-response domain/repository/service、conversation
transaction、digest binding 与 scientific-specific no-model settlement 已删除；
migration `035`、旧表和历史 row 保留为 frozen evidence compatibility，current runtime
不再写入。Host 写 immutable closure 和 source-bound notification 后，open attempt task
沿 ordinary fenced model-driven wake 继续，canonical assignee 再显式
`task.finish(status=completed)`；generic task completion 会在 closure 前以 typed
`scientific_attempt_task_not_closed` no-effect error 拒绝。terminal task 上的旧 notification
只走既有 stale-signal mechanical path，closure 从不自动完成 task。

AOX formal policy 升至 `aox_cutover_formal_tool_precondition@5`，删除 master、exact-three
task/report/response 共终止 veto，只保留 session-scoped operation universe、canonical task
creation 与 report source-link guards。formal product-ready 还必须观察 exact immutable
closure；若相同 open attempt 连续两次处于 replay-safe zero-signal、zero-writer 且无 wake
source，driver 以 `scientific_attempt_open_no_wakeup` 有界终止，而不是耗尽全局 drain。
diagnostic wrapper 保留已观察 operation/task/report/lifecycle、raw facts 与实测 MICU；
缺 closure 只使 diagnostic non-eligible，formal acceptance 仍要求 exact control。

sealed source safety 改为 closed unsafe-category scanner：仍拒绝 secret、private locator/
URL、path escape、digest drift、explicit private roots 及其编码形式，但不再把任意
slash-prefixed program token 当作 Host path，因此 portable shebang、route syntax 和普通
language path expression 保留 exact bytes。probe execution status 与后续 attestation
status 分栏，attestation failure 不回写已证明的 passed operation。runtime consistency
warning 保持 workspace read-only projection，不再在每次 drain 追加 derived durable
events。

本 correction 只完成 local/non-live implementation、tests、specs 与 docs；它不创建或
消费 admission、pin、diagnostic/formal authority、root、MICU、provider/HPC/browser
effect，也不授权 numbered follow-on。下一次 live 仍需 fresh clean commit 上的新 plan
与用户对 exact plan 的单独批准。

### 2026-07-30 r63 canonical wake-facts correction

r63 的 fresh diagnostic authority、one-use consumption、exact commit、root、probe、
formal SQLite 与 decision 均保留为永久 **NO-GO**。隔离 probe 的两项 provider 与四项
HPC operation 全部完成；formal executor 的第一项 `attempt.create` 也以 exact authority
参数成功记录并由 Host finalizer 准入。最早 typed failure 出现在随后 source-bound
`manual_resume`：fresh teammate driver 只得到原 task prose，没有 admitted attempt 或
transition facts，于是错误地再次调用 `attempt.create`，Host 正确以
`authorization_required/no_effect/terminal` 拒绝。executor 随后显式 blocked task，
而 AOX observer/diagnostic 又把 causal failure 压成 `task_blocked`，并因读取
`TaskBoardItem.status` 而不是 `TaskBoardItem.task.status` 将三个 task 全部投影为
`unknown`。

forward correction 不新增 signal reason、phase、持久 wake state、automatic inspect、
retry 或 task finish。Core 以一个 bounded read-only resolver 直接投影已有 admitted
attempt、immutable closure 与 failure observation，重核 claimed signal/source/
correlation/session/task/lane/actor/request/lifecycle binding，并把 facts 放在 task prose
之前；unrelated manual resume 保持 ordinary。`attempt.create` 与
`scientific.attempt.close` 成功后共享 non-business bounded-turn handoff，让 Host 在
writer retirement 后 finalization；失败请求仍是可读 no-effect tool result。

AOX observation 从 owner-authored task-finish 的 exact `failure_ref` 解析 canonical
FailureObservation，以其 error code 作为 earliest cause，同时单独保留
`task_blocked` wrapper、effect certainty、retry eligibility 与 evidence refs。
diagnostic raw counts 使用真实 nested task projection，non-eligible failure evidence
保留 bounded terminal/nonterminal task facts。所有 authority、unknown-effect、
fencing、provenance、writer/quiescence 与 formal GO controls 保持 fail closed。

post-r63 composition correction 进一步收口两处实现边界。成功的
`attempt.create`/`scientific.attempt.close` 不再同时产生 generic
teammate-to-master successor；Host finalizer 写入的 source-bound owner wake 是唯一
transition successor，而 ordinary teammate result 和 turn-budget replan 仍保留原有
master successor。canonical facts 通过 bounded ephemeral harness context 同时进入
master 与 teammate turn，不写 conversation 或新的 durable wake state；failure
projection 保留 exact identity/effect/retry 元数据，并以 count/digest/truncated 表达
有界 evidence refs 和 raw facts。

AOX observer 对每个 current task 从完整合法 resume history 中选择一个 deterministic
exact `task_finish`；相同 normalized UTC timestamp 的不等价 current binding
fail closed 为 `task_finish_current_binding_ambiguous`。operation、current task exit 与
sandbox 的 actionable typed failure 统一按 timezone-aware causal timestamp 和 stable
identity 排序，已恢复的历史 blocked exit 不再覆盖当前状态。该 bounded current-task
projection 由 runtime observation 与 failure evidence 共同消费，不再二次读取 task
board 生成另一份投影。closure-stage live runtime summary 以 closed nested record
继续绑定该投影的 count/digest/truncated 元数据，成功路径也不能静默丢弃或改形。

本 correction 只授权 local code/spec/docs、non-live verification 和本地 commit；
不授权 r64、live authority/root、MICU、provider、HPC 或 Chrome。

### 2026-07-30 r64 sealed runner cause and bounded controlled-failure handoff

r64 的 commit、diagnostic authority、root、probe、formal SQLite、runner attempt 与
decision 全部保留为永久 **NO-GO**。独立 probe 的六项 operation 全部完成；formal
前五项 operation 完成，HMMalign 在 dispatch 前因 bounded SSH ControlMaster connect
失败而终止。runner attempt 已封存 `transport_connect_failed` 且 effect 为
`no_effect`，但旧的 closed-result metadata 未携带 terminal status/error code，
execution adapter 又只接受大写 error code；Host 还先读取本地 failed Run，并把 cause
压成 `durable_hpc_terminal_failure/terminal_known`。continuation 已按该错误写入
`controlled_effect/agent_can_replan` FailureObservation，并排队一个 exact
source/task/lane/agent 的 `engine_completed` owner wake；AOX driver 却在返回 failed
observation 后立即停止，未给 canonical owner 一次 bounded replan turn。failure bundle
同时只保留 probe operations，遗漏已发生的 formal operation facts。

forward correction 让 SSH/Slurm closed attempt metadata 统一携带 sealed status、safe
machine error code 与既有 effect/retry envelope；adapter 接受大小写安全 machine code，
Host 在存在 exact runner reservation 时先以 runner observation 为 causal source，
只在 result materialization 内使用本地 Run。runner 的 `transport_connect_failed` 与
`no_effect` 因而原样进入 ControlledOperationExecution、ContinuationState、
FailureObservation 与 agent-facing observation；缺失、非法或与 sealed attempt
envelope 冲突的 runner projection fail closed，不回退成更宽泛的成功/重试语义。

AOX observer 从 canonical ControlledOperation、唯一 execution、continuation、
scientific-attempt binding 与 exact FailureObservation 生成一份 bounded operation
facts projection，以 `scope=probe|formal`、count、digest 和 truncated 标记同时供
session observation、diagnostic raw facts 与 failure evidence 使用。failure evidence
合并 probe attestation 与 formal projection，不能再把 probe success 冒充全部 operation
事实。

failed observation 默认仍立即停止。唯一例外是 exact source-bound bounded handoff：
当前 failure 必须是同一 formal attempt 中唯一 operation/execution/continuation 的
`controlled_effect + agent_can_replan + no_effect + terminal`，task 仍为业务非终态，
且恰有一个未 claim、attempt_count=0、source/correlation/agent/task/lane 全绑定的
`engine_completed` owner signal。driver 只允许下一次既有 drain 消费该 signal 一次；
它不创建 signal、operation、task、attempt、approval 或 authority，不 retry/replay
failed effect，也不规定 agent 必须换用哪种策略。缺失、重复、claimed、cancelled、
已消费、跨 identity、unknown-effect、dispatch-in-doubt、非 terminal 或 authority/
attempt drift 均维持原 failed result，不再 drain。

本 Phase 2 只授权 local code/spec/docs、non-live verification 和本地 commit；不授权
r65、live authority/root、MICU、provider、HPC 或 Chrome。

### 2026-07-31 r65 exact calculation and atomic finalization correction

r65 的 fresh diagnostic authority、one-use consumption、exact commit、root、probe、
formal SQLite、provider/HPC effects、sealed sandbox source 与 decision 全部保留为永久
**NO-GO**。probe 与 formal 的 exact-six controlled operations 都成功，但 agent-local
candidate filter 读取非 canonical 字段 `passes|pass|passed|motif_pass` 与
`score_tenths|motif_score_tenths`，没有读取 scorer 已发布的
`passes_motif_rule` / `motif_rule_score_tenths`。因此 2,561 条 target 中本应由 516 条
通过记录构成的 candidate FASTA 被写成零字节；脚本继续逐项注册 17 个 normalized
deliverable、关闭 attempt、完成 execution 并交接 report，直到晚期 evidence collector
才由 validator 返回 146 项错误。该事实证明既有 Host-only calculation label、
任意 sealed source-snapshot implementation digest 与 post-hoc validator 不能构成
scientific capability 或 terminal authorization。

forward contract 将 motif candidate filter、upstream-empty materialization、
reference-only alignment、empty membership 以及 final deliverable normalization
迁入 dependency-free `openzyme_pipeline` exact typed calculation。每项 capability
拥有 closed input/result schema、canonical serializer、contract digest 与真实
implementation digest；candidate filter 只接受 `aox_motif_rule_score@1` canonical rows，
从 `passes_motif_rule` 派生 membership，并对 score、sequence、reference 与 digest
closure fail closed。conditional-empty 只可由 exact typed zero-upstream result触发，
不能由空文件、prose 或脚本分支伪造。qualification、SOP 与 installed callable map
必须逐项列出 callable/result/serializer/contract/implementation closure；agent source
snapshot 只证明执行源码身份，永久不得替代任何 calculation implementation。

新增 `aox_final_deliverable_bundle@1` Host finalization boundary。sandbox 以一次
`artifacts.finalize_bundle` 请求提交固定 17 path 的 closed draft manifest 与 exact
calculation receipts；Host 在同一 source/session/workspace/sandbox run、attempt 和
selection binding 下读取每个 draft，先运行统一的 live/eval/offline scientific
validator，再开启短 SQLite transaction。只有完整验证通过时，transaction 才一次性写入
17 个 catalog occurrence 与一个 deterministic immutable
`aox_final_deliverable_validation_receipt@1` document；任一 draft、metadata、calculation、
serializer、path、digest、validation 或第 N 次 catalog write/receipt write 失败都回滚
全部 catalog truth。content-addressed seal 可留下无引用 immutable blob，但不能出现
部分 artifact row、receipt、attempt closure 或 business terminal state。

receipt 绑定 session/task/attempt/selection/workspace/sandbox run/source snapshot、
exact 17 artifact ids/digests、calculation ids/digests、validator digest 和 bundle digest。
AOX formal tool precondition 在 dispatch 前重读并验证该 receipt：
`scientific.attempt.close` 必须引用相同 attempt/selection 的 exact passed receipt；
execution `task.finish(status=completed)` 必须在 evidence refs 中携带该 document；
report delegation/publication/completion 必须绑定同一 receipt 与已关闭 execution。
missing、duplicate、stale、cross-source、cross-attempt、cross-selection、artifact drift、
calculation drift 或 failed receipt 均以 typed no-effect error 拒绝，且不自动 retry、
补注册、完成 task、关闭 attempt 或创建替代 work。

live、eval 与 offline evidence verification 共享一个 production-owned validator，
保留完整 ordered typed errors 与 earliest causal error；public projection 只可产生
bounded summary，不能用 `error_count` 覆盖 cause。旧
`_sandbox_source_implementation_digest` 与逐项 normalized registration 路径删除；
formal 中间态若需 staging，必须使用非 normalized intermediate artifact identity。

已完成的 closure-stage live diagnostic change 同步退役。其 authority、source builder、
reconstruction、live runner、run class、tool-policy 特例、CLI commands 与 runnable docs
全部删除，因为其 master-only companion-response validator 与 current assignee-owned、
response-free close contract 永久不可同时满足。migration `035`、旧 SQLite table/rows、
历史 sealed evidence schema reader 与 formal non-adoption rejection 保留；任何历史
closure-stage authority/root/result/artifact 都不能成为 current formal authority、
calculation receipt、finalization receipt 或 campaign evidence。归档该完成 change 只
表示历史实施工件封存，不恢复 runnable surface。

本 Phase 2 只授权 local code/spec/docs、non-live verification、OpenSpec sync/archive 与
本地 commit；不授权 r66、live authority/root、MICU、provider、HPC 或 Chrome。后继 live
仍需 fresh clean commit 上的新 exact plan 与用户单独批准。

### 2026-07-31 r66 source-bound local failure and bounded selected-chain recovery correction

r66 的 fresh diagnostic authority、plan、root、SQLite、provider/HPC effects、sealed
evidence 与 decision 永久 **NO-GO**，不得重试、重标或复用。formal executor 从
`bio.fetch_sequences` 取得 MAFFT artifact 后，没有先调用 `ws.stage_artifact(...)`，而把
fetched descriptor 直接传给 `bio_tools.hmmbuild`。因此 exact causal failure 是 Host
control pre-admission validation 的 `hpc_stage_ref_required/no_effect`；没有
ControlledOperation 被 admit，也没有 runner/HPC/external dispatch。sandbox process 随后
以 exit 1 结束并形成外层 `sandbox_exec_nonzero`。旧实现既未把两者持久化为
FailureObservation，也把 run 的 failed exit 返回成 successful ToolResult；formal observer
因而只能看到 generic failed history，无法区分安全可重规划的本地拒绝与业务终态。

forward contract 不再由 sandbox SDK 本地吞掉 malformed stage descriptor。SDK 保留 exact
caller request，Host 是唯一 canonical pre-admission validator：它在 operation admission
之前封存 source-bound `hpc_stage_ref_required` cause，固定
session/workspace/source-tree/agent/task/lane/origin signal、request digest 与 idempotency
digest，并证明 `operation_admitted=false`、`external_dispatch_started=false`。terminal
SandboxRun 再封存 `sandbox_exec_nonzero` wrapper，绑定唯一 local cause、selected attempt
和 canonical continuation identities。`sandbox.exec` 对 non-completed run 返回 failed
ToolResult，Core 的 `ENGINE_COMPLETED` wake-facts projector 重建同一 wrapper/cause；missing、
duplicate、cross-source、cross-attempt 或 malformed binding 全部 fail closed。

AOX formal observation 对 controlled-operation failure 与 local sandbox failure 使用同一个
selected-chain policy。只有 exact current formal attempt、business-nonterminal task、
`agent_can_replan/no_effect` cause 以及 exact owner handoff 闭合时，该 failure 才是
nonblocking history；probe、unknown-effect、retryable、dispatch-in-doubt、unbound 或显式
task failed/blocked/cancelled 仍立即 fatal。immutable closure 形成后，同一 selected chain
中已 disposition 的 exact safe failure 保留为 evidence，但不继续 poisoning closed
attempt；business task/report/closure 事实仍必须完整。

旧 AOX `_recoverable_controlled_operation_handoff_source`、per-source one-shot bookkeeping
与 `max_signals_override` 删除。driver 始终使用 pinned `max_signals=1` ordinary bounded
drain；Harness 不合成 wake、不扩大 authority、不自动 retry/replay，也不规定 agent 的修复
策略。existing canonical owner wake 和后续 selected-chain work 可以在多个 bounded command
中前进；最终只由 complete selected-chain closure、显式 business task state，或两次相同
replay-safe no-wakeup observation收敛。

本 Phase 2 只授权 local code/spec/docs、non-live verification 与本地 commit；不授权
r67、live authority/root、MICU、provider、HPC 或 Chrome。r66 consumed state 不得成为
任何后继 admission、selection、closure 或 campaign evidence。

### 2026-07-31 r67 deletion-first test-conductor correction

r67 diagnostic authority、plan、root、SQLite、MICU usage、provider effects、sealed evidence 与
decision 永久 **NO-GO**。其 diagnostic id 是
`aox_diagnostic_8c2ce426355c001253b86c1c`，attempt id 是
`diagnostic-positive-5dfdd0686e9174a975ff85b18404e85d`，decision digest 是
`sha256:d9356b0bdd25885f19e2452773dfac03bfa09e39562ed4c00c8fca9828ef480b`。
旧 observer 把一个可由 agent 在同一业务任务内修正的 sandbox-local request 错标为
`sandbox_run_failure_binding_invalid`：executor 首先把相对 `output_dir` 交给 provider SDK，
SDK 在 Host admission 前抛出裸 `ValueError`；agent 随后修正 request，正式 NCBI operation
成功完成，但 AOX observer 仍把 failed history 解释成 attempt terminal。该次诊断从账本
增加 `3,903,566` charged tokens 与 `81` attempts；这些是整次诊断消耗，不能全部归因于
单一 observer 错标。r67 不得被重标、续跑、replay、adopt 或作为后继 authority/evidence。

纠正采用 deletion-first，而不是继续扩张 observer 的 failure taxonomy。删除
`aox_runtime_observation`、Core `runtime_barrier` / observer-writer 与 live runner 内建的
drive-until-terminal、two-empty-drain/no-wakeup、automatic approval、scope-rollover retry 和
business-terminal reducer；删除 `run-live` 与 `run-diagnostic-live` runnable commands。
authority、pin、preflight、process supervision、append-only evidence、bundle verifier 与
campaign reducer 保持独立 shell，但这些 shell 不读取业务状态来决定下一步、不发送下一条
message/drain、不批准 operation、不改写 task/attempt/report，也不声明 GO。

后继测试由 Codex 测试员作为外部 test conductor 完成。它只能通过 public Host API/CLI
创建 session、投递 message、显式 drain、读取 workspace/events/pending approvals，并在用户
授权范围内 resolve approval；每一步是否继续由测试员根据 public facts 显式决定，不形成
仓库内 automatic policy loop。Host 仍独占 canonical task/attempt/report state、approval、
lease/fencing、unknown-effect/external-effect、sandbox/provider/HPC admission 与隔离边界。
Codex 不得直接写 SQLite、伪造 receipt、绕过 approval、把 runtime idle 当成 task terminal，
或自行声明 GO。只有离线 verifier 验证每个 sealed bundle，campaign reducer 再依据两次独立
positive 与一次 fault bundle 产生 GO/NO-GO。

Host pre-admission 继续收口 typed causal evidence。provider output-dir / stage-ref 等
authority-bearing validation 不由 sandbox SDK 以裸异常提前吞掉；Host 在 operation admission
与 external dispatch 前封存 source-bound `no_effect` cause。terminal SandboxRun、failed
ToolResult 与 canonical `ENGINE_COMPLETED` owner wake 继续绑定同一 cause/wrapper。该证据只向
agent/测试员呈现真实约束，Host 不据此替 agent 选择 retry、repair、stop 或业务终态。

本 Phase 2 只授权 local deletion、Host typed-failure correction、spec/docs、全部 non-live
verification 与本地 commit；不授权 r68、新 live authority/root、MICU、provider、HPC 或
Chrome。删除后必须以 source audit 证明生产代码净减少，且不得留下 observer/automatic
driver 的别名、兼容入口或隐藏 fallback。

### 2026-07-31 r68 prelaunch-blocked public-conductor production repair

r68 的 exact authority 已消费，但旧 production surface 无法从 public `/v3` 导出 closed
attempt/quiescence evidence，也没有可调用的 production Host startup/supervision 与 `@3`
sealing 入口。因此测试在 root、Host、session 与 scientific attempt 创建前停止。该事实只记为
**prelaunch blocked**，不是 canonical r68 NO-GO：不存在可供 verifier 判断的 r68 attempt，
也不存在 attempt bundle 或 reducer decision。authority consumption 不可撤销或复用；截至
该停止点没有 Host/provider/HPC/Chrome effect，MICU 仍为
`128,190,632 / 500,000,000`。任何后继测试都必须基于本 repair commit 重新完成 full
admission、pin、fresh authority 与 fresh roots，并取得对新 exact plan 的独立批准。

repair 继续采用 deletion-first。失去 production caller 的 generic `AttemptRunner`、legacy
`@2` emitter、从 production module 暴露给 tests 的 evidence builder、旧 driver config/write
path、browser observation helper 与 runnable automatic contract 全部删除；历史 `@1..@3`
runtime config、legacy supervision/evidence receipt 只保留 closed read-only verifier，不得成为
current launch caller。test evidence fixture 移入 tests package，production composition 禁止引用。

current `aox_blank_world_runtime_config@4` 把 Codex tester、public Host API/CLI、receipt
chain、policy-free supervised Host 与 MICU identity 封入 config digest，并强制 automatic
drain/approval/rollover 全为 false。`preflight` 在任何 root 前验证 exact consumed slot、clean
identity、committed pin、full architecture qualification、runtime config 与 plan/consumption；
post-r68 addendum进一步要求先 atomic claim exact slot；全部通过后才创建该 slot 的 private
root并原子封存 `aox_attempt_preflight@2`，其状态明确为
`preflight_complete_host_not_started`。preflight 本身不启动 Host/session/attempt 或外部 effect。

`serve-attempt` 只用 exact preflight 启动固定 loopback production Host/process group，关闭
background runtime，不发送 message/drain、不中断或批准业务操作、不做 rollover/terminal
判断。startup 与 supervision receipt 证明 exact local process epoch、root fsync、SQLite
checkpoint/integrity 与全部 local writer 退休；不证明 remote cancellation、业务成功或 GO。

thin Host CLI 通过全局 `--receipt-chain` 为每次 public request 追加 exact closed
`openzyme_public_api_receipt@2`，包括 non-2xx；`--seal-response` 以
`openzyme_public_host_response@1` no-replace 封存最后 workspace/events/evidence response。
message receipt只保留 message digest 与 skill/task/lane semantics。Host 新增 exact closed
attempt/selection evidence GET；Core export 要求 session、closed attempt 与 sealed selection
一致，formal positive 还必须重验 persisted 17-deliverable validation receipt，并经 artifact
boundary 读取每个 sealed file。

唯一 current builder 是 `finalize-and-seal`：它在输出前完整验证 identity/preflight、固定
startup/supervision siblings、连续 public receipt chain、final workspace/event/evidence sealed
responses、source attestations 与 MICU snapshots，随后才以 no-replace 原子安装 profile
`aox_public_conductor_bundle@1` 的 `aox_blank_world_attempt_bundle@3`。offline verifier只从
封存 source attestations 在 private temporary topology 中重建 payload并比较 exact bytes；
不读 live SQLite，不接触 provider/runner/network。production reachability qualification同时
证明 public route/CLI/finalizer/verifier/reducer 有 production caller，且已删除 runner/emitter/
browser/automatic surfaces 不可达。

本 repair 只闭合 positive production reachability，不降低 formal fault contract。若第三个
bundle 只证明一般 controlled failure，却没有闭合
`derived_required_artifact_blob_byte_flip@2`、exact derived `AOX_ref21.fasta` consumer 与
`artifact_blob_digest_mismatch`，campaign reducer 必须以
`fault_contract_unproven` 保持 NO-GO。该 Phase 2 只运行 non-live verification、更新规格/文档
并提交本地 commit；不启动下一 rNN、live、MICU、provider、HPC 或 Chrome。

### 2026-08-01 post-r68 / pre-r69 deletion-first actor and closure repair

上一版 public receipt sequence错误地要求 Codex conductor 代替 agent 提交
`attempt.create`、selected-chain mutations与 close，并代替 Host 调用 admission/closure
finalizer。这不是 public orchestration proof，而是 actor ownership的伪造要求。本 repair
从 bundle validator删除整条伪 conductor sequence；一旦 receipt chain出现
`scientific-attempt-commands`、admission finalizer或 closure finalizer，立即以
`public_conductor_actor_boundary_invalid` fail closed。合法 chain 只包含 session create、entry
message、authority grant、explicit bounded drain/status、pending approval/resolve、exact fault
capability与最终 workspace/events/export reads。每个 drain必须在下一 drain或 final reads前有
terminal command status，CLI JSON stdout显式 flush；process exit与空 drain仍不是业务终态。

formal slot allocation新增 `aox_attempt_authority_slot_claim@1`。preflight在创建任何 root前对
plan sibling执行 mode-private atomic no-replace publish；claim闭合 campaign、plan/
consumption、ordinal、attempt/session/task/lane/envelope/request与 campaign-root identity。
claim被复制到 attempt evidence并进入 `aox_attempt_preflight@2` 与 bundle source attestations；
preflight失败后的 slot保持已消费，不能换 root重放。

Host public export升级为 `aox_closed_attempt_evidence@2`。新的
`aox_public_product_closure@1`直接从 real repositories与完整 durable event replay生成，并由
offline finalizer对照 final public workspace/events：session只能有 exact research/execution/
reporting三任务，三项 assigned identity唯一，每项恰有一个 assigned-agent-authored
`task_finish`。positive还必须让三任务 completed，闭合 source-linked report/draft与 final
assistant answer；因此 execution task projection不再冒充 report handoff或整场 closure。

fault槽新增单一 public `reference-byte-flip` capability。Host只接受 active authority-bound
fault attempt及 exact derived `aox_hmm/AOX_ref21.fasta` contract artifact，在零 consumer前先
持久化 immutable claim，再对 sealed file byte offset 0执行一次 XOR flip、fsync并恢复 mode，
最后持久化 pre/post digest、source contract、authority与 idempotency receipt。完整
`aox_fault_negative_state_closure@1`还要证明唯一 `bio_tools.mafft` consumer以
`artifact_blob_digest_mismatch`失败、execution非成功、reporter未完成、无 ready/published
report/draft、无 alternate consumer与 post-fault fixed deliverable，并闭合 conversation/final
failure/events。

campaign reducer不再只看三个按顺序输入的 bundle。它要求同一 non-empty campaign_id与
plan_digest、ordinal严格为 1/2/3，并要求 attempt/session/task/lane/envelope/selection/root/
receipt-chain identities全部三项唯一；两个 positive各自必须有 exact三任务、source-linked
report、final answer和17 deliverables，fault必须携带完整 negative closure。production
reachability scenario也不再用 source-level `inspect`：它通过
`ProductionCompositionFactory`、public FastAPI route、真实 file-backed SQLite写读和 typed
negative route证明当前 composition。

该 repair只运行 non-live tests并更新
`docs/v3/aox-r-series-codex-goal.md`。r68 authority/state不可复用；r69或任何 live/MICU/
provider/HPC/Chrome action仍需新的 clean commit、full admission、pin、fresh authority、fresh
roots与用户对 exact plan的独立批准。

### 2026-08-01 post-r69 / pre-r70 late-bound admission repair

r69 在旧 clean commit `b0ed3ea767fb44c892a14f90f59a50a96d2aa58f` 上消费了 campaign
`aox_campaign_2a57780d6663d57da38621d6` 的 authority、slot/root、Host session、三次 PubMed
provider request与 `512,357` MICU。累计账本到达
`128,702,989 / 500,000,000`，剩余 `371,297,011`。但是 execution task 尚未绑定真实 lane，
public `attempt.create` 因 `attempt_lane_scope_invalid/no_effect` 返回 409；SQLite 中没有 admission
request、scientific attempt 或 closure，测试在 bundle/reducer 前停止。这是 consumed
**pre-admission blocked**，不是 canonical r69 NO-GO。r69 的 plan、slot、root、session、provider
effect、receipt 与 MICU attribution全部只读封存且不可复用；没有 r69 attempt identity可以被后续
repair“补上”。

该 defect 暴露出 outer formal plan 在 agent 尚未建立 canonical control objects 时预造
`attempt_id`、`lane_id` 与 admission idempotency key，形成 shadow truth。current
`aox_live_attempt_authority_plan@2`、`aox_attempt_authority_slot_claim@2`、
`aox_blank_world_root_proof@3`、`aox_attempt_preflight@3` 与 Host startup/supervision `@2` 删除这些
字段，只闭合 campaign、ordinal、session、task、envelope/root、campaign-root identity 与从上述
source确定性派生的 `launch_id`。legacy plan/claim/root proof仍可按原 schema离线读取，但不得与
current schema配对或进入新 launch。

executor 先使用 canonical `lane.create` 与 `lane.bind_task` 建立真实 lane；`attempt.create` 的
公开 tool schema只接收 `envelope_id` 与 agent选择的 `idempotency_key`，task来自当前 focus。
Core 从 durable authority、task、lane与唯一 workflow contract推导 campaign/scope/resources/
effect/private route，并在 request write与 Host finalization两端都要求 actor仍是该 task的 current
assignee。wrong actor、reassignment、missing/foreign lane、ambiguous scope/workflow/provider/HPC
route均在 attempt创建前 fail closed。Host finalizer生成 canonical admission/attempt id，成功后
通过 canonical owner wake把 late-bound facts交还 executor；outer plan、preflight和supervisor
不得猜测或覆盖它们。

public `scientific-attempt-commands` 与 admission/closure finalizer routes、对应 thin CLI/client、
dead `ScientificAttemptService.create_attempt` convenience、private
`attempt_admission_arguments`、diagnostic authority mint/consume module及命令全部删除。agent继续
通过自己的 Harness tools执行 selection/adoption/seal/close，Host继续在 bounded writer退休后
内部 finalize；Codex conductor仅从 public inspect/workspace/events/closed export读取结果。
`aox_public_conductor_bundle@2` 先用 slot authority绑定真实 control graph，再 late-bind
attempt/lane/admission/idempotency/selection identities；campaign reducer分别强制三个 launch
slot identity与五类真实 control identity唯一。

production qualification通过 real `HostApiDependencies/create_app()` route composition、真实
file-backed SQLite、production V3 service和 canonical lane/scientific tool handlers证明正向可达，
并覆盖 wrong actor、finalizer前 reassignment、legacy public routes、diagnostic commands、deleted
modules与 fault/export fail-closed。历史 SQLite migration/rows与 sealed evidence不改写，formal
non-adoption gate继续是唯一兼容入口。该 Phase 2只运行 non-live验证、同步文档并提交本地 commit；
不启动 r70、live、MICU、provider、HPC或Chrome。

### 2026-08-04 r70 pre-runtime blocked / post-r70 late-bound task and terminal handoff repair

当前不存在 r71。r70 已消费 authority、slot、root、session 与 public receipt，但在提交首个
runtime drain 前停止；Host 没有 scientific authorization、admission request 或 scientific
attempt。这是 **pre-runtime conductor blocked**，不是 canonical r70 NO-GO。r70 的 plan、claim、
root、session、receipt 与任何派生 identity 都只读封存且不可复用；repair 不得通过补写 drain、
task、authority envelope 或 attempt 把 r70 续跑成 acceptance attempt。

本轮 deletion-first repair 删除 current formal launch artifacts 中的 speculative task truth。
`aox_live_attempt_authority_plan@3`、consumption `@4`、slot claim `@3`、root proof `@3`、preflight
`@4` 与 Host startup/supervision `@3` 只闭合 consumed campaign、ordinal、attempt kind、session、
root、authority policy 与 deterministic launch identity。它们不得携带 task、envelope/request、
lane、attempt 或 admission identity，也不再通过 finalization policy 隐藏匹配 exact
`task.create`。historical schema/evidence 继续只读，但不能进入 current launch。

新的唯一正向顺序是 session create → entry message → bounded drain admission response → sealed
terminal status → public canonical workspace。workspace 必须只含一个 execution task；operator
authority 只能在此后原子 late-bind 到该真实 task。后续 executor 才能创建/bind lane，并由
current assignee 调用 `attempt.create`。最终 product closure 按 task kind、agent role、assignee 与
owner-authored finish cardinality闭合 exact research/execution/reporting 三任务；task scope、lane、
approval/fencing、unknown/external effect、provenance/isolation、17-deliverable finalization、Host
process settlement以及 offline verifier/reducer 的权威边界不变。

public receipt 不再把 digest-only status GET 当作 terminal proof。每个 bounded drain 的 public
admission response和唯一 terminal response都必须作为 bounded sealed handoff进入 bundle；terminal
response的 command id/type、status、completed_at、bounded outcome与safe error/retry字段必须 exact
复现唯一 `runtime.command.finished` event。CLI 对 non-2xx payload 先递归脱敏，再以相同 response
semantic digest、链上限与封存合同落盘。Host 若 command执行期间才打开 mutation scope，terminal
settlement与 post-transition projection只获得绑定 exact command id的短 writer authority，完成后
必须退休；这不授予 observer、retry或业务 terminal policy。

`aox_public_conductor_bundle@3` 只接受上述 late-bound task与 sealed terminal chain。production
reachability qualification通过 real public FastAPI application、thin Host client、file-backed
SQLite 和 injected deterministic model/runtime完整组成；它不得直接调用 private service、手工
组装 `ToolRegistry`、写 canonical repository truth或合成 receipt。该 Phase 2只运行 non-live
验证、同步 OpenSpec/架构/V3文档、qualification registry/resource manifest并提交本地 commit；
不启动 r71、live、MICU、provider、HPC或Chrome。

### 2026-08-04 r71 pre-attempt sandbox-bootstrap blocked / post-r71 fresh-Host repair

r71 campaign `aox_campaign_0356c33b043b00e1ea64d08c` 已消费 authority、positive ordinal 1、
root、session、三任务、late-bound scientific authorization 与 public receipt，并发生 9 次 model
ledger attribution；MICU 从 `128,702,989` 增至 `129,139,238`，本轮增量 `436,249`。首个 execution
task 在创建 scientific admission/attempt 前读取 `sandbox.workspace.status`，event cursor 74 返回
typed `sandbox_image_missing`，因此没有 admission request、scientific attempt、provider、HPC、
sandbox command或 browser effect。这是 authority-bound **pre-attempt sandbox-bootstrap blocked**，
不是 canonical r71 NO-GO。r71 的 authority、slot、root、session、task、authorization、receipt、
MICU attribution 与全部派生 identity 只读封存且不可复用；事后 inventory 只能证明检查时 image
存在，不能反推 cursor 74 时的物理 image 存在性，稳定根因限定为
`aox_supervised_host_sandbox_image_identity_not_registered`。

repair 删除 `dev_web_ui` 与 eval live scenario 中直接探测 Podman、静默返回或直接写
`sandbox_image_records` 的 ambient bootstrap。唯一正向路径属于 supervised Host child：它先创建
一个 `PodmanPipelineSandboxRunner`，并在 foundation、listener、child-ready、session、model/provider
之前对其 `preflight()` 的 exact six-field identity做 closed validation；`image_digest` 与
`pipeline_sdk_digest` 必须 exact 匹配 authority-bound preflight，immutable ref、组合 digest 与
当前 runner必须一致。完成 bootstrap 后，同一 runner instance注入 public runtime health与 execution，
后续 identity drift直接 fail closed，不得换 runner或 mutable tag。

fresh file SQLite transaction在任何业务 write 前同时证明 `sandbox_image_records`、`sessions` 与
`sandbox_workspace_records` 的全表 row count 均为零，不能只检查 default ref。事务随后把 runtime
image投影为一个 `repo@sha256` immutable、cutover-compatible Core `SandboxImageRecord`，使用 Core
workspace manifest protocol（当前 `s07`）并与 Podman runtime protocol（当前 `s10`）保持显式分离；
write 后必须在同一事务内 exact reread，任一失败整体 rollback。bootstrap receipt闭合 preflight、
runtime identity、Core registry projection与 digest，并进入 child-ready、Host startup receipt和 bundle
source attestation。它不执行 pull/build/install/tag，不允许 env/debug fallback，也不改变普通未 bootstrap
Host 的 `sandbox_image_missing` 语义。

production qualification只在 external sandbox port注入 deterministic runner，以 exact production
bootstrap function、real `HostApiDependencies/create_app()`、public FastAPI/thin client 与 file SQLite
证明 registry row 和 public ready status先于 session/model。executor从
`scientific.attempt.inspect` 读取真实 envelope，自行调用 production lane tools创建/bind lane后再
`attempt.create`；删除 model factory 的 envelope side channel与 master-side lane fixture。negative
controls覆盖 missing/malformed/image/SDK/immutable/runtime mismatch、default/non-default preexisting
row、duplicate、runner drift、receipt tamper与 transaction rollback。该 Phase 2只运行 non-live
验证、同步 OpenSpec/架构/V3文档、qualification registry/P0/resource manifest并提交本地 commit；
不启动下一 rNN、live、MICU、provider、HPC或Chrome。

### 2026-08-05 r72 qualification single-flight and yielded-handle correction

r72 没有形成 canonical attempt bundle 或 reducer decision。一次 full qualification 已在
canonical checkout 上运行并最终发布 report，但 Codex 在原 yielded handle 未结算时又启动同
output 的等价 full command；随后又运行 focused recheck，并以不存在 parent 的 recovery output
启动第三次 full matrix。第三次直到 collection、harness 和 scenario 全部执行后才在 publication
阶段返回 `qualification output parent is unavailable`。这些 report/recheck/recovery/stop facts
相互污染，只能封存为 **prelive conductor blocked**，不是 canonical r72 NO-GO；全部 r72 state
不可重跑、拼接、采纳或用于后继 admission。

forward correction 删除 Codex automatic/bounded admission recovery、等价命令 relaunch 和
lost-handle continuation。tool 返回 yielded `cell_id`/`session_id` 后只能恢复同一 handle；若该
handle 失联，只允许只读检查 process 与 output target，然后停止。repository runner 在任何 pytest
collection、harness self-test 或 scenario 前先验证 primary output 与 mainline sidecar 的 absolute、
lexically canonical、existing real parent、no-symlink/no-alias、outside-checkout 和 absent target
合同。invalid target 使用 `architecture_qualification_output_invalid`，不再晚期折叠为 report
error。

同一 canonical checkout 的 root inode identity 映射到 trusted-local private lock root 中一个
inert regular lock file；runner 以 `O_NOFOLLOW|O_CLOEXEC` 打开并通过
`flock(LOCK_EX|LOCK_NB)` 在 collection 到 report verification/sidecar publication 的整个区间持有。
所有 mode 和 output 共用这一个 lock；竞争者立即得到
`architecture_qualification_run_active`。fd close 或 process crash 由 kernel 自动释放，文件本身不
记录 owner、business lifecycle 或 retry authority，也不允许 steal、wait queue、observer 或
recovery policy。final publication 再次校验 target，并保留 mkdir/file `O_EXCL`、file/directory/
parent fsync、pure verifier、mainline-private sidecar non-adoption 与 live fail-closed。

本 Phase 2 只授权 local code/spec/docs、全部 non-live verification、一次 clean 且明确
non-adoptable 的 full diagnostic qualification 与本地 commit；不授权下一 rNN、live、MICU、
provider、HPC 或 Chrome。

### 2026-08-05 r73 stale-conductor-source / qualification-causal-evidence correction

r73 没有创建 root、session、scientific attempt 或 canonical bundle，也没有 reducer GO/NO-GO。
Codex conductor 把外部保存的 stale HEAD 当成运行真值，错误丢弃了首份实际绑定
`789f1c177552ece953564932f9e29753179cb2fa` 的 full report，随后在首个 terminal report 后串行启动
等价 full admission。两次 run 的 qualification harness 都触及 bounded timeout；旧 `@1` report只保存
stdout/stderr digest，并继续为未运行场景生成 fallback/unproven GAP cascade，丢失最早 process cause。
因此 r73 只作为 **prelive conductor/qualification blocked** 封存，不是 canonical NO-GO；两份report、
reproduction/stop state及旧 persistent goal全部不可复用。

forward repair 删除 conductor-owned `started_head`、drift/recovery/adoption判断和terminal failure后的
equivalent relaunch。fresh Codex goal要求每次从当前 checkout read-only推导 source/rNN；yielded handle
只能恢复原 handle，terminal report一旦出现就停止，Codex不再在repository evidence之外维护HEAD truth。

pytest orchestration从Host production package整体删除。`scripts/v3_architecture_qualification.py`仅进入
产品无关`scripts/test_gate`包之外的repository `scripts/architecture_qualification_runner.py`，所有 process统一由
`scripts/test_gate/runner.py` bounded process-group executor拥有。single-flight lock内第一份 source
identity是admission真值；collection前后、harness后、scenario前后与publication前逐阶段复核。
current report `@2`封存每个process的safe command、bounded output digest/bytes/tail、exit、timeout、
TERM/KILL、source digest以及唯一earliest typed failure。collection/harness/scenario/source-drift任一
terminal failure立即停止selected chain，not-run identities exact闭合，不生成fallback result或GAP
cascade。AOX current receipt `@2`进一步绑定report schema、source identity与run-evidence digest；report/
receipt `@1`只允许历史bundle reader显式只读，不能进入pin/preflight/run/reducer。

operator-retirement的 eligibility/quarantine/unknown-effect由pure semantic calculation决定，不再依赖
亚秒real-clock阈值。suite只保留一个秒级宽限的真实process-group containment probe，其余identity、
exit/signal、descendant residue与forced-unproven组合均为deterministic checks。本 repair只运行non-live
验证、同步registry/resource manifest/docs并在clean commit上生成一次明确non-adoptable full
diagnostic；不启动下一rNN、live、MICU、provider、HPC或Chrome。

### 2026-08-06 启动失败证据与判断边界修正

ec69fd8 上的 `pin` 只执行一次，公开 stderr 仅证明
`aox_launch_effective_config_schema_invalid`；事务目录没有产出身份、前置条件或提交标记，
因此具体字段只能记为 `exact_identity_unproven`。把缺少
`OPENZYME_RESEARCH_MCP_ENABLED` 直接写成根因，是将未被 AOX 有效配置构造器消费的环境输入
误当成封存事实。该状态是 prelaunch blocked，不是 canonical NO-GO；没有 root、session、attempt、
MICU、provider、runner 或 Chrome effect，也不授权纠正后重试（corrected retry）。

本次修复删除 `ResearchSettings.mcp_enabled` 及其环境解析。普通 Host 仍由 foundation 明确启用
Research MCP；AOX 有效配置继续把这项 Host 权威能力投影为 `research.mcp_enabled=true`，从而只保留
一处产品真值。公开 CLI 失败升级为 `aox_cutover_launch_failure@2`：稳定的 `failure_code` 始终可见，
只有失败源明确提供的 `public_details` 才映射为 `failure_details`。当前闭合 schema 失败源只允许逻辑字段
`identity/missing/unexpected`；内部 `details`、配置值、路径、凭据、消息和异常链不会自动公开。
历史 `@1` 只读保留。

验证 skill 只增加通用证据纪律，不写死错误码、环境变量或调查顺序。Codex 可自由检查当前代码并形成
假设，但必须分别陈述封存观测、源码推论和未证实假设；假设不能改写封存证据，也不能取得状态变更、
纠正后重试或授权消费权限。该约束保护真实世界感知与策略自由，同时把“能够调查”与“已经证明”分开。
本次修复仅运行 non-live 验证，不启动下一 rNN、live、MICU、provider、HPC 或 Chrome，且未获明确要求
时不提交。

### 2026-08-06 公开配置预检与 runner 因果闭合

后续 fresh preparation 证明了上一版验证 skill 仍把“仅使用公开接口”和“调用有效配置 builder”写在
同一流程里。Codex 因而直接 import production 私有模块并把返回值当作配置闭合证明；真正的 `pin`
随后只执行一次，在第一个 forced-SSH toolchain fixture 上以
`aox_launch_toolchain_pin_execution_failed` 终止。旧公开回执丢弃了 runner 已经提供的安全
`error_code` 与 effect certainty，于是无法区分 transport、payload、output validation 或 projection
failure。该状态发生在 identity/prerequisite/plan/root/session/attempt 创建前，是 preplan blocked，
不是 canonical NO-GO，也不能据 goal 的多次只读 blocked audit 写成多次 pin 失败。

forward repair 新增 public `check-config`。它与 `pin` 共用 `OpenZymeSettings.from_env()`、ledger 解析、
`build_aox_cutover_effective_config()` 和闭集 normalizer，只返回 current config schema id 与 digest；
不接收 qualification report，不写文件，不创建 authority/state，也不实例化 runner。它是可重复的本地
precheck，不是 admission、pin 或 external availability receipt；`pin` 必须重新计算配置。Codex skill
禁止直接 import Host 私有 settings/builder/service，静态源码检查只可形成推论，不能代替该 public
receipt。

`bc16ef3` 后的首次真实使用暴露了 conductor 顺序缺口：skill 引用了未定义的 command-scoped
launch profile，却先用未经装配的 ambient environment 执行 `check-config`，随后又正确地因 terminal
failure 禁止补值重试。修复后的顺序是 current contract/schema discovery → 完整非敏感 profile 原子装配
→ 首次且唯一的 public `check-config` → 在完全相同 profile 下执行 `pin`。fresh `pin` preparation
授权覆盖首次命令前的 command-scoped 非敏感装配；它不修改仓库、`.env`、用户 shell 或 canonical
state。若完整 profile 的首次检查仍失败，则继续 fail closed，不能逐字段 corrected retry。

因为 `pin` 的 forced-SSH fixture 会真实连接 runner、执行四个非科学 deterministic payload 并产生
runner staging/output，所以它不是“零 HPC 接触”的本地配置检查。准备授权必须明确覆盖这一真实但
非正式科学 workload 的外部 effect。当前 launch failure 升级为 `@3`：schema branch 以
`kind=schema_field` 保留 `identity/missing/unexpected`；runner branch 以
`kind=runner_attestation` 保留安全 `tool_id`、可选 run/attempt-receipt identity、
`runner_call|runner_result`、effect certainty 和可选
machine `runner_error_code`。runner code 只接受全大写执行码或全小写 source-causal code，拒绝混合
大小写与自由文本。任意路径、credential、原始消息、异常文本和未知字段继续被丢弃；
没有 runner receipt 时 effect certainty 明确为 `unproven`。terminal `pin` failure 立即停止，不自动
重试；报告分别记录 `pin_execution_count` 与 `blocked_audit_count`。

### 2026-08-06 qualification 本地执行能力闭合

`d770f78` 上的新 preparation 证明，Codex 普通命令 sandbox 不具备 full qualification 的完整本地
执行能力。harness 的 collection tests 全部通过，首个 production-composition driver 却在
Starlette `TestClient.__enter__()`、Host lifespan 之前等待。最小复现进一步证明
`socketpair.send()` 在该 sandbox 内返回 `EPERM`，asyncio 跨线程唤醒被内部吞掉后 AnyIO portal
无法继续；同一路径在 sandbox 外立即通过。因此 `architecture_qualification_harness_failed` 只是
180 秒 supervisor timeout 的外层封装，不能作为产品、Host lifespan、SQLite、依赖版本或最近提交的
因果证据。

本修复不修改 qualification runner、TestClient、timeout、Host 或 report schema，而是把 executor
capability 放在唯一命令 admission 之前。用户批准一次 current full qualification 时，该批准覆盖
对 exact public repository script 使用窄范围 `sandbox_permissions=require_escalated`；理由只允许本地
IPC、正常包 cache 与 non-live process supervision，不覆盖网络或 live effect。Codex 先只读闭合
canonical checkout、clean source、fresh checkout 外 output 与 single-flight，然后第一次且仅一次启动
script。升级调用只允许公开 script、`admission` 与已生成的字面量 output path，不内联 environment、
管道、重定向、命令串联或持久 prefix approval，并在发出前核对 script 的 non-live 环境清理与未声明
外部端口拒绝仍然成立。禁止普通 sandbox 试跑、替代 `UV_CACHE_DIR`、raw/focused pytest、`socketpair` probe、另一个
output 或 terminal 后等价重发。平台若在进程启动前拒绝该能力，则 execution count 保持零，停止于
operator environment boundary，不创建 product failure 或 qualification report。

这一低自由度规则只约束脆弱的 repository test-gate 执行桥，不约束 OpenZyme agent 的科学策略。
`check-config` 保持普通 sandbox 内的无副作用 production settings 解析；`pin` 继续作为独立授权的
forced-SSH external effect。source binding、kernel single-flight、bounded process receipt、
no-replace/fsync publication 与 pure verifier 均保持唯一权威。

### 2026-08-06 late-bound lane 与 pre-attempt 正式失败闭合

最近一次正式 slot 暴露了两个独立缺口。第一，execution assignee 在首次 turn 内通过公开工具创建并绑定了真实 lane，但源 runtime signal 按事实仍携带空 lane；旧 settlement 把历史 source snapshot 与 turn 结束时的 handoff identity 当成必须相等的同一字段，于是把合法的单调身份补全误判为 `budget_replan_identity_not_closed`。新 `AgentRuntimeOutcomeSettlement@2` 不改写源事实：`lane_id` 继续表示 source lane，`handoff_lane_id` 只允许从空值单调绑定到当前 task、agent 与唯一 durable successor 共同认可的 lane。已有非空 source lane 发生漂移仍然 fail closed，后续推进仍须由 Codex 发起显式 bounded drain，harness 不选择科学策略或自动循环。

第二，已获批并消费的正式 slot 可能在 scientific attempt 创建前终止。attempt bundle 的定义要求真实 attempt，因此不得为这种情况伪造 bundle；但若直接把它降级成无编号 blocker，正式 rNN 又会失去可裁决终局。新增的 `aox_formal_slot_failure@1` 只接受 exact authority/preflight/slot、supervised Host retirement、退休前封存的最终 public workspace/events/terminal handoffs、MICU transition、零 attempt 证明与最早类型化原因。纯离线 verifier 从不可变 source 重新构造事实；验证通过后，独立的 failure reducer 只能产生 `aox_blank_world_campaign_failure_decision@1 / NO-GO`，其 attempt identities 与 digests 必须为空。缺少任一来源时保持 evidence blocker，不能由文字结论或 exit code 补足。

rNN 只在 fresh pin 与 exact formal plan 发布后分配并冻结；此前失败报告 `rNN=none`。用户对该 exact plan 的一次批准覆盖同一 plan、slot、authority、预算和 effect 闭集内的公开 approval resolution 与显式继续动作，不覆盖身份漂移、预算扩大或新 effect。session 入口必须逐字使用当前公开的 objective、title 与 message，Host 退休前必须先封存所有最终读取。历史失败缺少 current receipt 或入口字节不匹配时不得追溯补造，只作为不可复用历史 blocker 保留。

### 2026-08-07 public conductor execution contract 与退休证据门

r74 再次证明，单靠提示词或 skill 提醒操作员手工附加 `--receipt-chain`、
`--seal-response` 并在 Host 退休前补做最终读取，并不能形成可靠的产品合同。该正式 slot 已消费
authority、root、session 与一次 runtime turn，但操作员没有同步封存 public receipt/response；Host
退休后失去唯一公开读取面，因此既不能伪造 attempt bundle，也不能满足
`aox_formal_slot_failure@1` 的零 attempt NO-GO 来源闭合，只能保留为 evidence blocker。

前向修复不恢复 AOX observer、automatic driver 或业务策略机。`preflight` 额外发布一个
source-bound conductor execution contract，只含 consumed slot 推导出的 Host/project/session
身份和相对 evidence 名称。新的 formal public Host command 机械注入这些身份、receipt chain 与
sealed response 目标，并拒绝调用者重绑定；其余 public action、参数、科学工具、drain 次数与推进
节奏仍由 Codex 测试员根据真实世界状态决定。

在操作员请求 Host 退休前，policy-free evidence shell 从公开 receipt/response 重新计算
one-to-one coverage、bounded drain admission/terminal event handoff，以及 mutation 后最终
workspace/events，封存不可变 retirement-readiness receipt。该 receipt 缺失、漂移或不完整时，
supervisor 只拒绝这次操作员退休并保持同一 Host 可读，不重放 command、不创建 task、不判断业务
终态；真实 child exit 与 authority expiry 仍按原监督合同封存。positive/fault finalizer 与零 attempt
slot-failure finalizer 都只接受 readiness receipt，并从中派生 exact source，删除 caller-selected
receipt/workspace/event/handoff/evidence path 组合。
脱敏且逐条封存的 4xx/5xx 可进入 readiness 与零-attempt failure source，避免一次真实 command
failure 永久毒化退休；positive bundle仍只接受成功 chain，HTTP status本身也不能替代 canonical
typed cause。architecture owner registry以 `aox.conductor-evidence` 固定该能力的 lifecycle、
persistence与 forbidden edges，禁止 action selection、automatic drain、business terminal write 和
campaign decision。

验证 skill 同步降为当前合同路由器：每个阶段先完整读取 `AGENTS.md`、V3 索引、当前 goal、active
OpenSpec 与公开 CLI help，再提取本阶段 execution contract。skill 只保留稳定的授权、证据与停止
不变量，不再复制易漂移的 schema、配置默认值、固定命令序列或 harness fixture 数量。这样把机械
证据约束放进产品，把世界理解和策略判断留给 agent，也避免文档与 skill 双重维护。

## Risks / Trade-offs

- [整数十分制会显著改变历史候选数] → 将其声明为 correctional breaking change，以公式级 golden、边界测试和 legacy non-cutover 标记替代对历史行数的兼容。
- [外部 provider 限流或 schema 变化导致真实 campaign 不稳定] → 使用 bounded retry、明确 required/enrichment、known-positive probe 和完整失败 evidence；不放宽 GO。
- [两次 live E2E 消耗高且运行时间长] → 先通过所有 focused/non-live gate，复用 immutable image 但不复用科学 payload，持续核对 MICU 账本。
- [LLM 可能选择不同合法策略，使输出顺序不稳定] → contract 固定规范化 schema、排序和 digest，而不固定内部推理/命令顺序。
- [Host 依赖 sandbox SDK 形成耦合] → 依赖只用于共享纯计算与离线验证，SDK source digest 已是现有 sandbox identity；禁止 SDK 反向依赖 Host/control plane。
- [显式 workflow ref 是 breaking behavior] → tool schema、prompt、错误信息和回归测试同时更新；旧 implicit inheritance 不保留隐藏 fallback。
- [Chrome/真实 HPC 不可达] → 保存精确 preflight/operation failure，campaign 保持 NO-GO，不用 seeded smoke 替代。
- [evidence bundle 误收敏感内容] → canonical safe projection allowlist、secret scanners 和 negative tests；原始 provider payload按许可边界封存，不直接投影。

## Migration Plan

1. 先落评分 contract、golden、validator 和 workflow pin；将 legacy AOX fixture 标为 non-cutover，并更新 S15 schema。
2. 落显式 delegation workflow selection 小修，补 role mismatch/no-inheritance/drift tests 与 runtime 文档。
3. 落 provider invocation taxonomy、PubMed quorum、UniProt identity/release 和 required/enrichment failure tests。
4. 把真实 AOX execution source迁移到新 SDK/scoring schema，删除产品路径中的常数 candidate/cluster/edge 生成。
5. 落 evidence bundle/verifier、blank-world preflight、campaign CLI、fault injection 和 tamper tests。
6. 更新 Host API projection、Web UI、workflow pack、主架构和 V3 稳定文档；历史 S15 改为 historical non-cutover。
7. 依次执行 focused tests、全量非 live gates、eval、live probes、两次 positive 和一次 fault attempt；最后才生成 GO/NO-GO。

回滚以语义提交为单位。评分 schema 不提供旧字段回滚兼容；若新实现失败，回滚到明确 NO-GO 的旧版本，而不是恢复旧 live-passed 声明。campaign/evidence artifacts 是 append-only，失败 attempt 保留且不能被后续成功覆盖。

## Open Questions

无待用户决策。实施期仍需由 live preflight 回答的外部事实包括当前 NCBI/PubMed/EBI/UniProt schema、HPC toolchain/image digest、Chrome MCP 可用性和 MICU 账本余量；这些是运行证据，不授权变更验收标准。
