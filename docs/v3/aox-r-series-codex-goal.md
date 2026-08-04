# AOX r-series Codex 测试 goal（post-r70 / pre-r71）

状态：paste-ready operator prompt。它定义 Codex 测试员的权限、证据顺序和停止条件，不构成
任何 diagnostic/formal live、MICU、provider、HPC 或 Chrome 授权，也不预先创建或命名 r71。

```text
/goal

目标：从一个 fresh clean HEAD 驱动 AOX/HMM r-series。只有同一 formal campaign/authority plan
的 exact ordinal 1/2/3（positive 1、positive 2、fault）分别形成独立且可离线复核的
aox_blank_world_attempt_bundle@3，并由 offline campaign reducer 封存 GO，目标才完成。
implementation green、单 attempt、diagnostic、conductor prose、Host task label、process exit、
empty drain、generic controlled failure或未封存 status digest都不是 GO。

当前不可变事实：r43-r67 是历史永久 NO-GO；r68 是 authority-consumed prelaunch blocked；r69
是 authority/root/session/provider/MICU-consumed pre-admission blocked。当前没有 r71。r70 已消费
authority、slot、root、session和receipt，但首个 runtime drain 从未提交，Host scientific
authorization、admission request与scientific attempt均未创建；它是 pre-runtime conductor
blocked，不是canonical r70 NO-GO。r68/r69/r70及更早的plan、slot、authority、root、SQLite、
session、task、envelope、effect、artifact、report、receipt、browser state和MICU attribution全部
不可复用，也不得通过补写task、grant、drain或attempt继续旧状态。下一fresh formal run只能在
repair commit形成clean HEAD后重新full architecture admission、pin、fresh exact plan/consumption、
fresh slot/root/session，并在事实可见后推导下一rNN；不能预先假定它就是r71。

角色边界：Codex是产品runtime之外的test conductor，只能通过public Host API/CLI进行session
create、entry message、explicit bounded drain、sealed command-status read、canonical workspace/task
read、late-bound scientific authorization grant、pending approval read/resolve、workspace/events/
attempt inspect、exact fault capability和最终evidence export。不得读写SQLite、调用private
service/repository/provider/runner/HPC helper、手工组装ToolRegistry、合成wakeup/receipt，或恢复
AOX observer/barrier/automatic driver。Host独占canonical task/attempt/report、approval、lease/
fence、unknown/external effect、continuation、artifact catalog、sandbox和isolation；agent保留科学
策略自由。offline verifier/reducer是唯一GO权威。

工作分三阶段，权限不能跨阶段推断：

1. 只读诊断：检查HEAD/status、OpenSpec/current docs、qualification selection、public route/CLI
   composition、最新r-series证据和MICU ledger；不修改、不提交、不启动Host/provider/HPC/Chrome/
   live、不消费authority。输出下一rNN候选、earliest typed blocker、deletion-first repair范围、
   non-live验证和一条可复制批准语句，然后停止等待用户。
2. repair Phase 2：仅在用户明确批准exact方案后修改。优先删除错误或失去production caller的
   policy/duplicate truth，再补最小canonical contract；同步OpenSpec、docs/OpenZyme架构设计.md、
   docs/v3、qualification registry和resource manifest，运行全部non-live gates并提交一个本地
   commit。不得顺便启动下一rNN/live/MICU/provider/HPC/Chrome。提交后报告commit、净diff、验证
   与下一阶段仍需的独立批准，然后停止。
3. live：仅在用户另行批准当前clean commit上推导出的exact fresh rNN plan后进行。批准必须明确
   run class、campaign/plan digest、ordinal/slot、budget/effect allowlist和停止条件；旧批准不随
   commit或repair延续。任一source/config/qualification/manifest/pin drift都fail closed并回到只读
   诊断。

formal launch规则：current aox_live_attempt_authority_plan@3、consumption@4、slot claim@3、
root proof@3、preflight@4和Host startup/supervision@3只绑定consumed campaign、ordinal、attempt
kind、session、root、authority policy及deterministic launch identity。它们不得包含或推导task、
authority envelope/request、lane、attempt、admission request或admission idempotency key。claim在
root前atomic no-replace发布；claim后失败会烧毁该slot，不能换root、task或session重试。

首次late-bind顺序不可调整：

1. 通过public API创建fresh session并封存response。
2. 发送唯一entry message，task_id/lane_id保持null，并封存response。
3. 提交一次bounded runtime drain，封存其HTTP 202 admission response。
4. 只经public command status轮询到terminal，并封存exact terminal response。
5. 读取并封存public canonical workspace；其中必须恰有一个execution task。
6. 仅把该slot的operator scientific authority原子grant给这个真实execution task。

缺失/多个execution task、提前grant、错误task、重复grant或synthetic task均在零scientific
authorization/零effect下停止。不得在formal plan、preflight、supervisor或bundle中预生成task或
envelope，也不得使用hidden exact task.create matcher迫使agent创建预定identity。

每个bounded drain必须同时具备sealed admission response和在下一drain/final reads之前出现的唯一
sealed terminal status。terminal response必须与同command id的唯一runtime.command.finished event
在command_type、status、completed_at、bounded_outcome_summary、error_code、safe_error_summary和
safe_retry_hint上exact一致。digest-only status GET、未封存response、额外handoff、synthesized
response或event drift都不是terminal proof。CLI JSON handoff必须flush；non-2xx response必须先递归
sanitize，再按与2xx相同的bounded canonical response/receipt语义封存，不能泄露Host path、secret
或raw exception。

scientific admission规则：late-bound execution task的current assignee先调用canonical lane.create
和lane.bind_task，再通过agent tool调用attempt.create(envelope_id,idempotency_key)。Codex不得代发，
tool也不得接受outer-plan的campaign/scope/resource/lane/attempt字段。Host从durable authority、
canonical task/lane和唯一current workflow contract推导exact admission，在finalizer再次检查
assignee后才生成canonical attempt id，并通过source-bound owner wake返回late-bound facts。
wrong actor、reassignment、missing/foreign lane、ambiguous authority、active fence或legacy caller-
supplied identity必须在零attempt/零effect下停止。

exact-three task规则：最终session恰有research、execution、reporting三种task kind；agent role与
task kind一致，三个assignee identity唯一，每个task恰有一个由current assignee签发的immutable
task_finish，且positive三项均completed。execution projection不能冒充report handoff；positive还
必须闭合source-linked report/draft、final assistant answer和source-bound exact 17-deliverable
validation/finalization receipt。task scope、lane ownership、approval/fencing、unknown/external
effect、provenance/isolation与Host process settlement均继续fail closed。

fault规则：ordinal 3只使用public authority-bound AOX_ref21.fasta exact byte-zero flip capability。
Host在零consumer前持久化one-use claim，验证fixed reference-selection contract/sealed bytes，执行
一次同尺寸byte flip/fsync/mode restore并封存source/authority/idempotency receipt。
aox_fault_negative_state_closure@1必须证明唯一bio_tools.mafft consumer以
artifact_blob_digest_mismatch失败、execution failed/blocked/cancelled、reporter未completed、无
ready/published report或draft、无successful alternate consumer、无post-fault fixed deliverable，
并使task/report/draft/conversation/final failure/events一致。generic failure不能替代该证明。

finalize规则：public inspect/workspace/full replay/export只读取Host真实control identities。
finalize-and-seal必须在创建目标前一次性验证identity、preflight、startup/retirement、连续receipt、
全部sealed handoff/final responses、17-deliverable receipt、MICU snapshots和source attestations，
随后原子发布profile aox_public_conductor_bundle@3的@3 bundle。不得用private service、直接SQLite、
manual ToolRegistry、synthetic receipt、test builder、digest-only status或arbitrary source snapshot
补齐positive reachability。

campaign规则：三槽共享同一campaign/plan且ordinal严格1/2/3；slot层的session/root/policy/receipt
chain分别唯一，public late-bind后的task/envelope以及Host生成的attempt/lane/admission request/
idempotency/selection identities也分别唯一。每个attempt只由network-free offline verifier判
eligible，campaign只由exact-three offline reducer判GO/NO-GO。diagnostic永久non-eligible；Chrome
不是current GO prerequisite。持续只读核对MICU累计账本，绝不重置或重归属历史usage。

遇到失败：先封存earliest typed cause，再解释outer wrapper；不要自动repair、rerun、retry、
rollover或消费下一slot。先只读复核并给出deletion-first下一方案与精确批准语句。只有完整
exact-three reducer GO后才把本goal标记完成；结构性production blocker应按实际阶段记录为
prelaunch/pre-runtime/pre-admission blocked，不能伪造attempt NO-GO。
```

推荐批准语句：

- 只读：`批准检查下一轮 r 系列问题；仅只读诊断，不修改代码、不提交、不启动 live。`
- repair：由诊断结果生成包含 exact scope、non-live gates、docs/OpenSpec、local commit 和
  `不启动下一 rNN/live/MICU/provider/HPC/Chrome` 的一次性批准语句。
- live：只有 clean commit、fresh full admission/pin、exact current plan/consumption 与尚未使用的
  slot 均可见后才生成；不得复用本页或任何 repair 批准。
