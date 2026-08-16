## Context

AOX current evidence constant 已是 `aox_blank_world_attempt_bundle@2`，但语义仍是 exact occurrence set：同一 method 第二 occurrence、任何 failed operation-bearing run 或 history failure 都在 approval 前阻断。r48–r51 已按该合同冻结为 NO-GO，当前任务明确停在下一次编号 live attempt 前。

generic scientific selection/closure 使 AOX 可以在完整保留所有 history 的情况下验收唯一 adopted chain。因为 `@2` 已存在，新合同必须使用 `@3`，而不是覆盖旧 verifier。

## Goals / Non-Goals

**Goals:**

- AOX driver 以 durable attempt authority、effect certainty、disposition 和 closure eligibility 决定能否继续。
- `@3` bundle 离线证明完整 occurrence universe、唯一 adopted chain、cross-run materialization、quiescence 和 envelope consumption。
- 通过非 live recovery qualification 后停下，等待用户授权下一次 numbered live attempt。

**Non-Goals:**

- 不升级、复用或重写 r48–r51 及任何旧 `@2` root/session/artifact/browser evidence。
- 不降低两次独立 positive、一次 fail-closed fault、真实 approval/UI 与 MICU 等最终 GO 门槛。
- 不在本变更运行 live provider、HPC、browser campaign 或创建下一编号。

## Decisions

### 1. `@2` 与 `@3` 完全分派

collector 为新 attempt 只发 `aox_blank_world_attempt_bundle@3`。offline entrypoint 按 exact schema id 调用独立 verifier；`@2` 代码和 golden fixtures 保持只读。`@3` 不从旧 DB 推断 selection，也不接受后补 adoption timestamp。

### 2. AOX role contract 验证 selected chain，不放弃 occurrence audit

bundle 包含：

- Host-derived operation/run universe及 digest；
- 每个 occurrence 的 disposition 与理由码；
- adopted role → operation/result/artifact 映射；
- effect adoption/materialization receipts；
- selection revision/seal；
- attempt authority/envelope consumption；
- attempt closure/quiescence receipt；
- AOX branch derivation、identity/digest lineage、report/UI/approval evidence。

verifier 仍从 sealed scientific artifacts重算 branch和最终 deliverables。它要求每个 reached role 恰好一个 adopted operation，optional omission 有 branch fact，所有额外 occurrence 已合法处置。相同 bytes 不能替代 identity/receipt。

### 3. Driver guard 改为 safety/admission guard

删除“相同 method 已出现”与“任一已知 failed run”作为绝对 blocker。每次 controlled dispatch 前检查：

- attempt authority active 且 envelope 未越界；
- 不存在 `dispatch_in_doubt`、活动/未 reconciled previous execution；
- source workspace/run 有合法 materialization 或本 run 产物；
- previous occurrence 能被 disposition，且 replacement policy/approval 允许；
- writer/process authority有效。

known terminal failure 可由 agent 标 `failed` 后修复；completed but unselected 可标 `superseded`；未知 effect 仍停止整个 attempt/campaign。

### 4. 新 attempt 暂由显式批准切换到 envelope

新 driver 接受 exact `attempt_authority_id`，不再把目录名当 authority。若没有 durable grant，preflight 返回 `authorization_required`；正式 live run 不使用测试 fixture 自动发 grant。后续操作者可创建 envelope，agent 在额度内消费下一 attempt。当前实现和非 live tests 不消费真实 MICU 或 live slot。

### 5. Recovery qualification 是 live admission 前置门

新增离线/synthetic qualification，至少覆盖：

1. run A completed upstream effect 后 local failure，agent adoption/materialize 到 run B，最终 closure 通过；
2. duplicate completed operation 明确 superseded 后唯一 chain 通过；
3. failed no-effect operation disposed 后 replacement 通过；
4. unknown-effect、active process、unresolved writer、unauthorized target 均失败；
5. envelope count/MICU/time/expiry 并发边界；
6. bundle/universe/disposition/materialization/closure tamper；
7. `@2` frozen fixture 仍按旧结果验证且不能升级。

只有 qualification、focused tests、非 live eval、前端 tests/build 和 mainline gate 全部通过，文档才记录“ready before next live attempt”，不得记录 GO。

## Risks / Trade-offs

- [AOX driver 与 generic service 双重规则漂移] → driver 只做 AOX role/branch admission，authority/effect/closure 委托 generic service；contract digest封存。
- [允许 duplicate 被误解为降低证据门槛] → verifier 审计完整 universe，每个 extra occurrence 必须合法 disposition，unknown/unclosed 永远失败。
- [schema 分支增加维护成本] → 显式 version registry与 frozen fixtures，不做 polymorphic best-effort parse。
- [测试 accidentally 触发 live] → qualification 只使用 fake providers/sandbox records，命令不带 live markers；任务清单明确 stop boundary。

## Migration Plan

1. 在 generic selection/closure 能力合并后接 AOX driver与 collector。
2. 增加 `@3` verifier/fixtures，回归 `@2`。
3. 更新 API/workspace/UI、runbook、stable docs和 active AOX tasks。
4. 执行所有非 live gates，写 readiness note，停在下一编号 attempt admission 前。

回滚时关闭 `@3` live admission并保留所有新 canonical rows；绝不把新 evidence 降格成 `@2`。

## Open Questions

无。下一次编号 live attempt 需要本目标之外的明确启动动作。
