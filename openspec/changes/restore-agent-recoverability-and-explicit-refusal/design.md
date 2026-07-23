## Context

V3 已经正确地把 task 业务终态留给 agent，也有 `ControlledOperationExecution` 的 effect certainty / retry eligibility 和 `runtime_attention` consistency repair；缺口在失败交付链。`ToolRouter` 仍会让普通 adapter/runtime exception 穿透，harness 会把 planning/tool dispatch exception 直接变成 `HarnessStatus.FAILED`，而 owner-agent 的后续 signal 常只恢复 task description，拿不到刚才的失败事实。

这造成两个相反风险：小的本地错误杀死 agent，真正危险的 unknown-effect 错误又只能靠零散文本辨识。本设计让失败成为 canonical observation，而不是把 fail closed 改成 fail open。

## Goals / Non-Goals

**Goals:**

- 让仍能运行的 agent 得到结构化、source-bound、可安全展示的失败事实，并在同一 bounded turn 或后续 wakeup 中自主修复、改道、求助或拒绝。
- 统一 validation/tool/provider/controlled-effect/harness/runtime/system failure 的 closed taxonomy。
- 保持 unknown effect、fencing、authority、permission、integrity 和 budget 错误 fail closed。
- 保持 task 终态只能由 agent 显式 `task.finish` 或已有文档化机械迁移写入。

**Non-Goals:**

- 不自动选择替代工具、改写参数、重放外部 effect 或创建新 formal attempt。
- 不把 raw exception、secret、Host path、backend locator 暴露给模型或用户。
- 不引入 LangGraph/Deep Agents 作为顶层产品状态；V3 repository/signal/task board 继续拥有真状态。
- 不把 agent 的推测伪装成 Harness 已确认事实。

## Decisions

### 1. Canonical `FailureObservation` 分三层表达

Host 持久化 immutable observation，至少绑定 `failure_id`、session/task/lane/agent、source kind/ref、phase、stable code、severity、recoverability、effect certainty、retry eligibility、safe summary/hint、evidence refs 和时间。公开 projection 分为：

1. `facts`：Harness/Host 已验证事实；
2. `likely_causes`：由稳定 code 经过确定性规则映射得到的候选原因；
3. `agent_hypothesis`：仅当 agent 后续显式提交时保存，带 confidence 和 evidence refs。

不使用自由文本 exception 作为公开 authority。相比只把 error 塞进 prompt，该对象可持久恢复、审计和投影；相比让 Harness 自动诊断，它不会夺走 agent 判断权。

### 2. Tool boundary 把 ordinary exception 降为 typed failed result

`ToolRouter.dispatch` 在最外层捕获普通 `Exception`，先写 failure observation，再返回 `ToolResult(ok=False, status="failed", error=...)`。参数 validation 继续使用稳定 validation code。下列 boundary-fatal 类不被当成可继续的普通 tool error：进程取消/退出、fencing/lease loss、mutation authority/integrity violation、以及无法确认 external effect 的异常；它们必须形成 fail-closed observation 并结束当前 ownership。

这比在每个 tool 内逐个 `try/except` 更完整，也不改变 tool 自己返回领域失败的能力。

### 3. “当前 turn 可继续”与“需要 durable wakeup”分开

如果失败结果已成功返回模型，harness 允许剩余 step budget 内继续，不额外制造重复 wakeup。若失败发生在 parked execution、continuation delivery或 turn 已结束之后，Host 用稳定幂等 key 创建 `recovery_required` signal，signal payload 只携带 failure/source ids；agent runtime 在 claim 时从 repository 重建 bounded recovery brief。

一个失败最多形成一个未消费 recovery signal。signal failure、turn failure 与 task status 保持正交。

### 4. Driver/provider 本身不可用时由 system identity 说真话

若 `driver.plan`、model provider或 runtime infrastructure 失败导致 agent 没有生成回复的能力，Host 记录 `runtime_attention` 和 `FailureObservation(actor=system)`；API/workspace 显示“agent 未能运行”的系统诊断。Host 不调用 `task.finish`，不生成伪 agent message，也不把规则化 likely cause 写成 agent hypothesis。

### 5. Agent 的“说不”复用 `task.finish`

不新增平行 task terminal API。提示和 recovery brief 明确：可修复问题可继续；需要用户/操作者/authority 时使用 `task.finish(status="blocked", reason_code, summary, evidence_refs)`；科学或技术上确知无法完成时才使用 `failed`。Harness 校验结构和权限，不判断该科学选择“是否够努力”。

### 6. 内部 retry 只属于同一 logical operation

provider/engine 可执行预声明的 bounded retry，但 retry policy、次数、backoff、effect-safety 必须在 dispatch 前绑定。同一 operation 的 retry 不改变用户参数或 backend target。无法证明 no-effect/幂等/reconciled 的失败不得自动重放；新 operation 或新 attempt 由 agent/authority 层决定。

## Risks / Trade-offs

- [把编程错误过度转换成 tool error 会掩盖缺陷] → observation 保留 private diagnostic digest，测试环境可配置 re-raise；公开仍安全，关键 invariant exception 永不降级。
- [模型可能陷入重复修复循环] → bounded turn、stable failure id、相同 invocation 去重和明确 retry eligibility；不自动延长 step budget。
- [failure 表增长] → immutable bounded payload、索引 session/source/time、retention 复用事件/证据策略。
- [规则化 likely cause 误导] → 只按稳定 code 映射，标成候选原因，不输出置信度或科学结论。

## Migration Plan

1. 新增领域类型、migration/repository 和安全 projection，旧记录无需回填。
2. 先接入 ToolRouter/harness ordinary exception，再接 execution/continuation wakeup。
3. 更新 API/workspace/UI 与 agent recovery instructions。
4. 运行 focused unit/contract tests、非 live eval、主线验证；可通过关闭 recovery signal producer 回滚调度行为，但保留 observation rows。

## Open Questions

无。产品语义已确定：最终约束不放松，agent 可显式 blocked/failed，system diagnostic 不冒充 agent。
