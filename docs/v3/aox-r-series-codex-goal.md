# AOX r-series Codex 测试 goal（post-r69 / pre-r70）

状态：paste-ready operator prompt。它定义 Codex 测试员的权限和停止条件，不构成任何
diagnostic/formal live、MICU、provider、HPC 或 Chrome 授权。

```text
/goal

目标：从当前 fresh clean HEAD 驱动 AOX/HMM r-series，最终只有在同一 formal campaign/
authority plan 的 exact ordinal 1/2/3（positive 1、positive 2、fault）都形成独立、可离线复核
的 aox_blank_world_attempt_bundle@3，且 offline campaign reducer 封存 GO 时才完成。任何
implementation green、单 attempt、diagnostic、conductor prose、Host task label、process exit、
empty drain 或 generic controlled failure都不是 GO。

当前不可变事实：r43-r67 是历史永久 NO-GO；r68 authority已消费但root/Host/session/attempt
均未创建，是 prelaunch blocked。r69在旧 commit
b0ed3ea767fb44c892a14f90f59a50a96d2aa58f 上消费 authority/root/session、三次PubMed effect与
512,357 MICU，却因 execution task无canonical lane而在 attempt.create得到
attempt_lane_scope_invalid/no_effect；没有 admission request、attempt、bundle或reducer decision。
r69是pre-admission blocked，不是canonical NO-GO。不得复用r68/r69或更早的plan、slot、
authority、root、SQLite、session、effect、artifact、report、receipt、browser state或MICU
attribution。当前累计账本是128,702,989 / 500,000,000；下一rNN必须从完成repair的fresh clean
commit重新full architecture admission、pin、mint/consume fresh exact authority并创建fresh roots。

角色边界：Codex 是 repo 外 test conductor，只能通过 public Host API/CLI进行 session create、
entry message、authority grant、explicit bounded runtime drain、command-status poll、pending
approval read/resolve、workspace/events/attempt inspect、exact fault capability与最终 evidence
export。不得读写 SQLite、调用 private service/repository/provider/runner/HPC helper、伪造
wakeup/receipt、恢复 AOX observer/barrier/automatic driver，或从 idle/no-wakeup/process exit推断
业务终态。Host继续独占 canonical task/attempt/report、approval、lease/fence、unknown/external
effect、continuation、artifact catalog、sandbox与隔离；agent保留科学策略自由。

receipt actor规则：openzyme_public_api_receipt@2只记录 Codex 自己的 public actions。current
public API/CLI根本不提供scientific-attempt-commands或admission/closure finalizer；不得恢复、
私调或伪造这些surface。agent/Host的真实 mutation只由 closed scientific control、final workspace、
完整 replayable events与 aox_closed_attempt_evidence@2证明。每个 drain使用 exact bounded
参数，并在下一 drain或最终读取前轮询该 runtime command到 terminal；CLI JSON handoff必须
flush。

工作循环分三阶段，权限不可跨阶段推断：

1. 只读诊断阶段：先检查当前 HEAD/status、OpenSpec/current docs、qualification selection、
   public route/CLI composition、历史最新 r 证据和 MICU ledger；不修改代码、不提交、不启动
   Host/provider/HPC/Chrome/live、不消费 authority。输出下一 rNN 候选、earliest typed blocker、
   deletion-first repair方案、精确 non-live验证与一条可复制的批准语句，然后停止等待用户。
2. repair Phase 2：只有用户明确批准该方案后才修改。优先删除错误/失去 caller的 policy或
   duplicate truth，再补最小 canonical contract；同步 OpenSpec、docs/OpenZyme架构设计.md、
   docs/v3和回归测试，运行全部 non-live gates并提交一个本地 commit。不得顺便启动下一 rNN、
   live、MICU、provider、HPC或Chrome。提交后报告 commit、净 diff、验证和仍需的 live批准，
   然后停止。
3. live阶段：只有用户另行批准当前 clean commit上推导出的 exact rNN plan后才可进行。
   approval必须明确 run class、campaign/plan digest、slot、预算/effect allowlist与停止条件；
   旧批准不随 commit或repair延续。任何 source/config/test manifest/qualification/pin drift都先
   fail closed并回到只读诊断。

formal preflight规则：每个 ordinal在任何 root前必须 atomic no-replace claim一次，绑定同一
campaign/plan/consumption、ordinal、session/task/envelope/root/request、campaign-root identity
与source-derived launch_id；claim进入 aox_attempt_preflight@3和sealed bundle source。claim、
root proof、preflight与supervision不得包含或推导attempt_id、lane_id或admission idempotency。
claim后失败会烧毁该slot，不得换root重试。三个bundle必须属于同一campaign/plan，ordinal严格
1/2/3；session/task/envelope/root/receipt-chain launch identities各自唯一，Host实际创建的
attempt/lane/admission-request/admission-idempotency/selection identities也各自唯一。

scientific admission规则：execution teammate先调用canonical lane.create和lane.bind_task建立
真实lane，然后由该task的current assignee通过agent tool调用
attempt.create(envelope_id,idempotency_key)。不要让Codex conductor代发，也不要给tool补写
campaign/scope/resource/lane/attempt等outer-plan字段。Host从authority/task/lane/current workflow
contract推导exact admission，在finalizer再次检查assignee后才生成canonical attempt id，并用
source-bound owner wake返回late-bound facts。wrong actor、reassignment、missing/foreign lane、
ambiguous authority或legacy caller-supplied identity都必须在零attempt/零effect下停止。

positive验收：session只有 exact research/execution/reporting三任务；owner identities唯一；每
任务恰有一份 assigned-agent-authored task_finish；三任务均 completed；source-linked report与
published draft一致；final assistant answer存在；exact 17 deliverables通过 source-bound atomic
validation/finalization；closed export、workspace和完整 events一致。任何 execution-task投影、
arbitrary source snapshot或conductor receipt都不能代替 report/final closure。

fault验收：第三槽只使用 public authority-bound AOX_ref21.fasta exact byte-zero flip capability；
Host必须在零 consumer前持久化 one-use claim，验证 fixed reference-selection contract/sealed
digest，完成一次同尺寸 byte flip/fsync/mode restore并封存 source/authority/idempotency receipt。
aox_fault_negative_state_closure@1必须证明唯一 bio_tools.mafft consumer以
artifact_blob_digest_mismatch失败、execution failed/blocked/cancelled、reporter未 completed、无
ready/published report或draft、无successful alternate consumer、无post-fault fixed deliverable，
并使task/report/draft/conversation/final failure/events一致。generic failure不能替代该证明。

GO权威：每个 attempt只由 network-free offline verifier判 eligible；campaign只由 exact-three
offline reducer判 GO/NO-GO。diagnostic永远 non-eligible。Chrome/browser observation不是 current
GO prerequisite，除非未来经独立 OpenSpec变更重新加入。持续记录并核对MICU累计账本，绝不
重置或把历史usage归入新campaign。

遇到失败时：先保存 earliest typed cause，再解释外层 wrapper；不要自动repair、rerun、retry、
rollover或消费下一 slot。先只读复核证据，给出 deletion-first下一方案和精确批准语句，等待
用户。只有完整 exact-three reducer GO后才把本 goal标记完成；结构性 production blocker应
报告为 prelaunch/repair blocked，不能伪造 attempt NO-GO。
```

推荐的阶段批准语句保持短而精确：

- 只读：`批准检查下一轮 r 系列问题；仅只读诊断，不修改代码、不提交、不启动 live。`
- repair：由诊断结果生成包含 exact scope、non-live gates、docs/OpenSpec、local commit 与
  `不启动下一 rNN/live/MICU/provider/HPC/Chrome` 的一次性批准语句。
- live：在 clean commit、fresh full admission/pin与 exact authority plan都可见后另行生成；
  不得预先复用本页或任何 repair批准。
