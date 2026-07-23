# Failure recovery、显式拒绝与 scientific attempt

## 1. 当前稳定结论

OpenZyme 的 harness 负责忠实、结构化、低摩擦地呈现真实约束；它不替 agent
选择科学策略，也不把任意失败机械地提升为业务终态。稳定语义如下：

- 普通 validation、tool、adapter 或本地 engine 失败，在 external effect 已知时返回
  LLM 可读的失败结果；同一 bounded turn 仍可继续。
- fencing、lease/authority、permission、budget、integrity、process cancellation 和
  `dispatch_in_doubt` 保持 fail closed，必须先恢复 authority 或完成 reconciliation。
- tool、turn、signal、continuation 或 Host finalizer 失败都不自动写 task
  `completed`、`blocked`、`failed` 或 `cancelled`。
- agent 可以修复、改道、请求帮助，或显式调用 `task.finish` 说“不”。需要
  user/operator/authority/harness 修复时用 `blocked`；只有 objective 本身确知不可能时才用
  `failed`。
- provider/driver 使 agent 根本无法作出决定时，Host 只发布 system-attributed
  diagnostic，并明确 `agent_decision_produced=false`；不得伪造 agent 回复。

## 2. FailureObservation 与 agent hypothesis

`FailureObservation` 是 immutable canonical fact，绑定 session/task/lane/agent、
source kind/ref/version、phase、稳定 error code、recoverability、effect certainty、
retry eligibility、safe facts、规则化 likely causes、evidence refs 与 actor identity。
private exception 只保留不可逆 digest，不能进入 public projection。

三类内容必须保持分离：

1. `facts`：Host/Harness 已确认的事实；
2. `likely_causes`：由稳定 error code 确定性映射出的候选原因；
3. `FailureHypothesis`：agent 通过 `failure.hypothesis.record` 追加的解释，绑定真实
   canonical agent、confidence、evidence refs 和 idempotency identity。

`FailureHypothesis` 是独立 append-only row，不能回写或覆盖
`FailureObservation`。`failure.get` 和 workspace projection 可以把两者联读；投影中的
`agent_hypothesis` 只是 latest compatibility view，`agent_hypotheses` 才是完整归属历史。
记录 hypothesis 不提供 retry authority，不消除 unknown effect，也不改变 task status。

## 3. Runtime recovery

ordinary failed tool result 成功交给 agent 后，不另造重复 wakeup；harness 将它作为下一轮
tool observation 继续 bounded loop。若失败只在原 turn 结束后可见，例如 continuation
delivery recovery failure 或 Host-finalized transition failure，Host 使用 exact source/version
创建去重 wakeup，并在 claim 时从 canonical repository 重建 recovery brief。

`recovery_required` brief 只能陈述事实和安全边界。agent 可选择：

- 在同一 logical operation 的预声明、effect-safe retry policy 内重试；
- 创建新的显式 operation/plan；
- reconciliation；
- 请求 user/operator/authority；
- `task.finish(status="blocked")`；
- 在 objective 确知无法完成时 `task.finish(status="failed")`。

Harness 不得静默改参数、切 provider/backend、重开 operation、创建新 formal attempt 或把
known failure 擦除。step budget 用尽只是 non-business runtime outcome。

## 4. Fresh scientific-attempt authority

每个 formal scientific attempt 必须先有 durable
`ScientificAttemptAuthorization` envelope。envelope 固定 grantor、session/task、campaign、
workflow、root、scope、effect classes、provider/HPC target allowlist、最大 attempt 数、
MICU/cost/wall-time ceiling、expiry、policy digest 与 idempotency identity。

agent 的 `attempt.create` 只写 admission request。它自己的 mutation writer 退休后，
Host finalizer 才在新的短 authority slice 中原子校验和消费 envelope、打开 attempt scope，
再唤醒原 agent。这样不会让同一 writer 既申请又自批 authority。非 retryable finalizer
拒绝必须生成 system-attributed failure observation 并返回 responsible agent；不得静默吞掉。

AOX 使用更窄的 `aox_live_attempt_authority_plan@1`：

- plan 精确包含 `positive, positive, fault` 三个槽；
- 每槽绑定预声明 attempt/session/task/lane/root、exact operator grantor、同一 identity 和
  qualification、`max_attempts=1`、effect/route/resource/expiry policy；
- `run-live` 只能把 plan 消费到 deterministic sibling
  `<plan-name>.consumed.json`，并且必须在创建任何 attempt root 前通过 atomic no-replace
  完成一次性消费；
- 复制 plan 文件不能获得新的 campaign authority；当前信任边界要求 operator 保护原 plan
  与其 deterministic consumption sibling，并以 durable in-attempt envelope 证明每槽消费。

## 5. Full occurrence universe 与 selected chain

scientific attempt 允许中间路径试错，但不允许隐藏历史。Host 从 exact attempt scope 导出全部
controlled-operation 和 covered sandbox-run occurrence，计算 digest-bound universe。agent
显式创建 CAS-protected selection revision，并为每个 occurrence 给出且只给出一个 disposition：

- `adopted`：进入唯一 selected workflow chain；
- `superseded`：保留事实并指向 replacement/adopted role；
- `failed`：绑定 terminal known failure；
- `abandoned`：仅限 no-effect，或已 reconciliation、已退休且不会再活动的 occurrence。

同一个 formal attempt 内可以跨 sandbox run 采用已完成 operation，并由 Host 通过 artifact
catalog grant、digest 和 target authority 物化其 bytes。跨 formal attempt、campaign、
positive/probe/fault 的 effect、operation、materialization、browser receipt 或 scientific bytes
不得采用。相同 provider 内容 bytes 可以独立出现，但 execution/effect identity 必须 fresh。

`dispatch_in_doubt`、未知 effect、活动 process/writer、未退休 continuation、authorization/cost
breach 或不完整 universe 不能靠 disposition 消失；selection seal 必须拒绝。

## 6. Closure 与 task 独立

`scientific.attempt.close` 先写 closure intent，并立即禁止该 attempt 继续绑定 run、
operation 或新 selection revision。agent writer 退休后，Host：

1. freeze exact mutation scope；
2. 获取同 generation 的 quiescence receipt；
3. 重算 universe、dispositions、adoptions、materializations、authorization consumption 与
   unresolved effect；
4. 验证 selected workflow roles 和 lineage；
5. 写 immutable closure。

quiescence 只证明“不会再变”，selection 只证明“采用什么”，两者互不替代。closed attempt 是
agent 可消费的 evidence，不是 `task.finish`；owner 仍需显式决定完成、继续、blocked 或 failed。

## 7. AOX evidence migration

新的 AOX production collector 只生成 `aox_blank_world_attempt_bundle@3`。`@3` 在保留原有
科学、artifact、public API、browser、MICU 和 fault 验收门槛的同时，增加：

- exact authorization envelope/consumption；
- full controlled-operation universe 与每个 occurrence disposition；
- unique selected workflow roles；
- same-attempt adoption/materialization lineage；
- sealed selection、quiescence 和 closure；
- unknown-effect、writer/process、cross-attempt reuse 与 tamper rejection。

历史 `aox_blank_world_attempt_bundle@2` verifier 保留为只读历史入口。旧 bundle 不得升级、
回填 selection、与 `@3` row 混合或被新 campaign 采用。r48、r49、r50、r51 永久保持
NO-GO；对应 root、effect、provider job、artifact、browser evidence 和 scientific bytes
均不得复用。

当前代码与文档工作明确停在下一次编号 live attempt 之前：非-live qualification 和
`authorize` 只准备/发布 authority，不创建 attempt root；`preflight`、`run-live`、provider、
MICU、HPC、Chrome 和任何新 numbered root 都属于下一次独立 operator-authorized 行动。
